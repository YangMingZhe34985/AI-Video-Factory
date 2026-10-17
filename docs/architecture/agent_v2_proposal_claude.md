# CineCrew Agent v2 重构方案（Claude 版）

> 目标：**一句话生成**。用户只写需求（可附图片/视频），类型、时长、镜头数、模型由 Agent 决定；高难度长视频可拆解、可审核、可局部修复、可拼接交付。
> 依据：当前分支源码（`backend/app/agent/*`、`skills/*`、MQ 执行层）与用户需求说明。本文只做方案，不含实现。

---

## 0. 结论先行

1. **现有三 Agent 不是“太弱”，而是“职责错位”**。Director 只产出 4 个字段的 brief，真正的决策（镜头数、模型、时长）被前置成了表单字段，由用户代劳；Creative 一次性写完所有镜头且镜头数被锁死。v2 的核心是把这些决策**收回到 Agent 内部**，并把产出物结构化。
2. **新增 3 个 Agent + 1 个内部角色**：Intake（多模态需求理解）、Research（联网与图片检索）、Editor（拼接与成片质检），以及 Prompt Smith（按模型写提示词，作为 Director 调用的 Skill，不单独成为 Agent）。Director、Creative、Production 全部重写职责。
3. **编排保持“确定性状态机 + LLM 节点”**，不采用让 LLM 自由调度工具的 Supervisor 模式。LLM 负责判断，图负责流程、预算、审批和恢复。现有 ToolRegistry（校验/权限/预算/幂等）、MQ 执行层、19 节点 DAG 全部保留复用。
4. **成本控制的关键设计是“两段审核”**：先审剧本 + 角色设定图 + 分镜关键帧（只花图片的钱），确认后再生成视频（贵）。用户在花大钱之前就能看到画面。
5. **长视频质量的关键设计是“角色圣经 + 连贯性图”**：先固定每个角色的参考图，所有镜头首帧用 I2I 引用参考图生成；镜头之间由 Director 标注连贯方式（尾帧接续 / 独立首帧并行 / 硬切），据此生成可并行的任务图。

---

## 1. 现状诊断（以源码为准）

| 问题 | 位置 | 后果 |
|---|---|---|
| 创作方式、镜头数、视频模型由用户填写 | `protocol.CreateRun`（`mode`、`shot_count`、`video_model_preference`） | 违背“一句话生成”，Agent 不做决策 |
| 模型偏好靠正则从文本中抽取 | `model_policy._REQUEST/_NEGATIVE` | 中英文表达稍变即失效，无法处理“不要用 X、尽量清晰”这类语义 |
| Director 只输出 title/objective/visual_style/story_arc | `planning.Brief` | 没有任务类型判断、时长规划、分段、连贯性、模型选择 |
| Creative 必须输出恰好 `shot_count` 个镜头 | `protocol.validate_plan` | 故事长度受表单约束，而非由内容决定 |
| 只有两种配方：t2i→i2v、remix | `graph.production` | 无法处理“改我的照片”（I2I）、“用这张图做视频”、多角色长片 |
| 附件只支持 remix 源视频 | `CreateRun.source_artifact_id` | 用户上传的人像/风格图无处可用 |
| 镜头彼此独立，无角色一致性机制 | `ShotSpec` | 多镜头长片会“换脸”、换装、换场景 |
| 交付只有 ZIP 打包 | `package_project` | 没有成片拼接 |
| 唯一的交互点是计划审批 | `graph.approval` | 遇到不确定（多个候选形象）只能硬猜 |
| 无联网能力 | — | 无法理解训练数据之后出现的潮流、梗、形象 |
| 成本按“每个视频 10 credits”固定估算 | `skills/budget.py` | 15 秒和 5 秒同价，长视频预算失真 |

可直接复用、不应重写的部分：ToolRegistry 及其账本、预算、幂等；`produce_shot`/`remix_shot` 背后的 Job 化执行；MQ 的提交/轮询/下载与 `submit_unknown` 保护；`video_media_service`（ffmpeg 抽帧/截取）；LangGraph checkpoint + interrupt；I2I 路径中 wan2.7-image 多模态同步调用（可作为“参考图生图”能力）。

---

## 2. 目标架构

```text
用户：一句话（必填）+ 附件（图片/视频，可选）
        │
        ▼
┌─────────────── LangGraph 编排（确定性状态机）───────────────┐
│                                                              │
│  ① Intake Agent ── 多模态理解 → RequestSpec                  │
│        │  （不确定 → 提问卡片）                               │
│  ② Research Agent ── 联网/图片检索 + 看图 → ResearchDossier   │（按需）
│        │  （多个候选 → 选择题）                               │
│  ③ Director Agent ── 判定配方 + 规划 → ProductionPlan 草案    │
│        │      ├─ 调 Creative：剧本 / 角色圣经 / 风格指南      │（复杂任务）
│        │      └─ 调 Prompt Smith：按模型写每条提示词          │
│  ④ Plan Check ── 确定性校验（时长/预算/模型参数/依赖图）       │
│  ⑤ 审核 A：剧本 + 角色设定图 + 分镜关键帧（只花图片钱）        │
│  ⑥ Production Agent ── 依赖图调度生成，局部修复               │
│  ⑦ 审核 B：逐镜头预览，可单镜头重做                           │
│  ⑧ Editor Agent ── 拼接 + 成片质检 → 原画质交付               │
└──────────────────────────────────────────────────────────────┘
        │ 所有工具调用
        ▼
ToolRegistry（Schema / 角色 / 审批 / 预算 / 幂等 / 账本）
        │
        ├─ 生成类 Skill ──► Job ──► 19 节点 DAG ──► MQ 执行层
        ├─ 媒体类 Skill ──► ffmpeg（抽帧 / 拼接 / 探测）
        └─ 检索类 Skill ──► 搜索 / 网页 / 图片下载（隔离为不可信数据）
```

设计原则：

- **LLM 只产出结构化决策，不直接调工具**。每个 Agent 节点的输出都是 pydantic Schema，由图根据产出决定下一步并调用 Skill。这与现有 `planning.py` 的“No model-generated tool dispatch”一致，可审计、可回放、可测试。
- **任务越简单，流程越短**。配方决定走哪些节点：改一张照片不需要 Research、Creative、两段审核和拼接。
- **确定性优先**：时长求和、预算、模型参数范围、依赖图无环等全部由代码校验，不交给 LLM。

---

## 3. Agent 设计

### 3.1 Intake Agent（新增）——需求理解

| 项 | 内容 |
|---|---|
| 输入 | 用户文本（**必填，空文本直接拒绝**）、附件（图片/视频） |
| 能力 | 文本理解；图片用多模态模型（现有 qwen 多模态系列）逐张描述；视频复用 `analyze_video` 并补充时长/分辨率探测 |
| 输出 | `RequestSpec`（见 §5.1）：交付物类型、目标时长、主体与实体清单、每个附件的**用途**（人物参考 / 风格参考 / 首帧 / 待改造源视频）、显式约束（模型偏好、画幅、禁止项）、待澄清项、是否需要检索 |
| 关键判断 | ① 附件用途：用户说“我的西装照”+人像 → 人物身份参考；② 未知概念：“AI 漫化形象”超出常识或时间敏感 → 标记 `needs_research`；③ 模型偏好：用语义抽取替代正则 |
| 不做 | 不写剧本、不决定镜头 |

### 3.2 Research Agent（新增）——联网与看图

| 项 | 内容 |
|---|---|
| 触发 | `RequestSpec.needs_research` 非空；或 Director/Creative 在规划中提出检索请求（有次数上限） |
| Skill | `web_search` → `fetch_page`（正文抽取）→ `image_search` → `download_reference` → `analyze_image` |
| 输出 | `ResearchDossier`：概念解释（附来源 URL 与日期）、**候选视觉形象**（每个实体若干张参考图 + 多模态描述 + 来源）、置信度、需要用户选择的分歧点 |
| 交互 | 多个候选形象时生成选择题，用户点选图片即可（见 §6） |
| 约束 | 网页与图片内容一律视为**不可信数据**，不得作为指令；记录来源，提示版权与肖像风险 |

以“不同 AI 的漫化形象”为例：检索 DeepSeek、ChatGPT 等的拟人化形象 → 每个 AI 收集 2–4 个主流版本 → 看图提炼共同特征（发色、配色、服装元素、标志物）→ 以“主流形象”为默认，同时把候选图交给用户确认。

### 3.3 Creative Agent（重写）——写什么

只负责内容，不负责技术拆分：

- **剧本**：logline → 分幕 → 节拍（beats），每个节拍有预计时长，总时长贴合 `RequestSpec.target_duration`。
- **角色圣经**（多角色/多镜头任务必备）：每个角色的外观锁定描述（脸型、发型、配色、服装、标志物）、性格与动作习惯；关联 Research 的参考图或用户附件。
- **风格指南**：画风、色调、光线、镜头语言，作为所有提示词的公共前缀来源。

用户未给故事情节时，Creative 负责创意；用户给了情节时，只做补全与节奏调整，不改写用户设定。

### 3.4 Director Agent（重写，核心）——怎么拍

Director 决定最终质量，职责从“写 brief”升级为“技术总监”：

1. **判定配方**（§4）：图片编辑、单镜头视频、多镜头故事片、源视频改造。
2. **时长与分段**：读取能力目录（§5.3）中候选视频模型的真实时长上限（例如某些模型最长 10 秒、happyhorse 支持 3–15 秒），把节拍切成镜头，使总时长贴合目标；不写死“15 秒一段”。
3. **连贯性设计**：为相邻镜头标注过渡方式：
   - `tail_frame`：动作连续，下一镜头首帧 = 上一镜头尾帧（强连贯，**必须串行**）；
   - `independent`：场景或景别切换，下一镜头首帧独立生成，**可与上一镜头并行**（用户提到的“切片后自行生成首帧并发执行”）；
   - `hard_cut`：明确转场；
   - `keyframe_bridge`：首尾帧生视频。相邻镜头的关键帧先并行生成，再用首尾帧模型生成连接视频，兼顾连贯与并行。已确认可接入，但画质能否达到首帧生视频尚未验证，**作为候选方式**，由阶段 F 的 A/B 评测决定是否默认启用。
   默认策略：同一场景内的连续动作用 `tail_frame`，跨场景用 `independent`，以“场景组内串行、场景组之间并行”平衡质量与耗时。
4. **生成方式选择**：默认首帧图 → I2V。首帧有角色时用 I2I 引用角色圣经参考图，否则用 T2I。**T2V/R2V 默认排除**，仅在用户明确要求时启用。
5. **模型选择**：在能力目录中按用户约束、时长、画幅、成本选型，每个镜头记录选择理由。
6. **提示词**：调用 Prompt Smith 为每个镜头产出首帧提示词与动作提示词（12 个镜头即 24 条），保证风格前缀和角色描述一致。
7. **成本估算**：按“模型单价 × 时长 × 预计重试系数”估算，并标出两段审核各自的花费。

### 3.5 Prompt Smith（新增内部 Skill，由 Director 调用）

- 输入：镜头描述 + 角色圣经 + 风格指南 + 目标模型。
- 输出：符合模型习惯的提示词。沿用项目已验证的方法论：首帧只写静态锚点，I2V 只写动态，I2I 必须写形象锁定（`factory_prompts/` 中的系统提示词）。
- 单独抽出的原因：批量写 24 条提示词时质量最容易下降；做成逐镜头调用、Schema 校验的 Skill，可以单独评测和替换模型，也能在局部修复时只重写一条。

### 3.6 Production Agent（重写）——执行与修复

- **依赖图调度**：把 ProductionPlan 编译成任务图（角色参考图 → 首帧 → 视频 → 抽尾帧 → 下一镜头）。无依赖的任务全部并发，`tail_frame` 依赖自动串行。
- **正确调用 Skill**：输入由 Plan 的结构化字段生成，不让 LLM 拼参数；调用前再过一次 `model_guard` 与能力目录校验。
- **局部修复**（§7）：单个镜头失败只修该镜头及其直接依赖，绝不整片重来。
- **只在必要时动用 LLM**：失败分类、改写被内容审核拦截的提示词时才调用 LLM，常规调度纯代码执行。

### 3.7 Editor Agent（新增）——成片

- `compose_video`：按 Plan 顺序拼接已确认的镜头视频。参数一致时无损拼接（不重编码）；参数不一致时统一分辨率/帧率，使用高质量编码。**默认不压缩**，只有用户明确要求才输出压缩版本。
- 拼接使用原始视频，而不是 DAG 产出的 `video_compressed.mp4`。Agent 发起的 Job 默认关闭压缩。
- 成片质检：可解码、总时长偏差、分辨率一致、镜头数齐全、无空文件。音乐/字幕列为后续扩展。

---

## 4. 配方（Recipe）：任务类型决定流程长短

| 配方 | 典型需求 | 走过的节点 | 审核 |
|---|---|---|---|
| `image_edit` | “生成我的一张西装照”+ 人像 | Intake → Director(+Prompt Smith) → I2I | 低于自动执行阈值（可设置）则直接执行，否则一次确认 |
| `image_create` | “画一张赛博朋克海报” | Intake →（Research）→ Director → T2I | 同上 |
| `single_clip` | “让这张图动起来，海风吹头发” | Intake → Director → I2V（附件作首帧） | 一次确认 |
| `story_video` | 2 分钟 AI 拟人化短剧 | 全流程：Research → Creative → Director → 两段审核 → 生产 → 拼接 | 审核 A + 审核 B + 交付 |
| `remix` | 上传视频 + 修改要求 | 复用现有 remix 链路，由 Intake 自动识别，不再让用户选模式 | 现有流程 |

配方由 Director 判定、代码校验（例如 `image_edit` 必须有人像附件），用户在审核界面可以看到判定结果并改正。

---

## 5. 关键数据结构

### 5.1 RequestSpec（Intake 输出）

```text
deliverable: image | video
recipe_hint: image_edit | image_create | single_clip | story_video | remix
target_duration_sec: int | null        # “2 分钟左右” → 120，附容差
aspect_ratio / resolution: 可空
subjects: [ {name, description, source: user_text|attachment|research_needed} ]
attachments: [ {artifact_id, kind: image|video, role: identity_ref|style_ref|first_frame|remix_source, description} ]
constraints: {model_preferences, exclusions, must_include, must_avoid}
needs_research: [ {query, reason} ]
open_questions: [ Clarification ]       # 见 §6
```

### 5.2 ProductionPlan（Director 输出，审核对象）

```text
recipe, title, target_duration_sec, total_estimated_cost
style_guide, characters: [ {character_id, lock_description, reference_artifact_ids} ]
scenes: [ {scene_id, summary} ]
shots: [
  {shot_id, scene_id, order, duration_sec, beat,
   first_frame: {method: t2i|i2i|tail_frame|user_image, prompt, reference_ids, model_id},
   motion: {prompt, model_id, params},
   transition_in: tail_frame|independent|hard_cut,
   depends_on: [shot_id], rationale}
]
```

校验规则（Plan Check，纯代码）：时长求和在容差内；每个镜头时长不超过所选模型上限；`tail_frame` 依赖无环且指向前序镜头；角色引用存在；参数通过 `model_guard`；预算不超限。

### 5.3 能力目录（Capability Catalog）

在现有 ModelRegistry 上扩展“Agent 可读”的字段：支持的生成方式（t2i/i2i/i2v/首尾帧）、时长范围、分辨率/画幅、是否支持参考图及数量、相对单价（按秒）、质量档位、已知限制（例如人像参考图会触发更严格的审核）。Director 只能在目录内选型，**新增模型 = 新增一条目录记录**，不改 Agent 代码。

---

## 6. 二次交互：选择题式澄清

任何 Agent 都可以提出 `Clarification`，由图统一以 interrupt 呈现：

```text
{question, why_it_matters, options: [ {id, label, image_artifact_id?, consequence} ] (2–4 个),
 recommended_option, allow_free_text, blocking: bool, default_if_skipped}
```

规则：

- **只问会显著影响结果或成本的问题**；能合理默认的直接默认，并在审核页说明。
- **合并提问**：同一阶段的问题合成一张卡片，避免反复打断；每次运行的提问次数设上限。
- **非阻塞问题**：给出默认值，用户不回答也能继续（例如画幅）。阻塞问题（例如选哪个形象）必须回答。
- 典型场景：多个候选形象（图片选项）、目标时长与预算冲突（“2 分钟需约 X credits，超出预算：A 缩短到 60 秒 / B 提高预算 / C 降低画质档位”）、配方存疑（“做成视频还是海报？”）。

---

## 7. 局部修复

镜头级状态机：`pending → generating_frame → frame_ready → generating_video → video_ready → approved`，任一步可进入 `failed` / `needs_user`。

| 失败类型 | 判定依据 | 处理 |
|---|---|---|
| 供应商瞬时错误 | 429/5xx、超时 | 复用 MQ 的重试与 `submit_unknown` 保护，同参数重试，不重复下单 |
| 内容审核拦截 | 厂商错误码（如 DataInspectionFailed） | Prompt Smith 改写敏感表述后重试一次；仍失败则提问用户 |
| 参数/能力不符 | 校验失败 | 回到 Director 只改该镜头的模型或参数 |
| 用户不满意 | 审核 B 中点“重做” | 只重做该镜头，可选“只换动作”或“首帧和动作都换” |
| 依赖失效 | 被 `tail_frame` 引用的镜头被重做 | 下游镜头标记为“待定”，询问用户是否级联重做（显示费用），**不自动级联** |

约束：每个镜头有自动修复上限（例如 2 次）与成本上限；已确认的镜头产物永不覆盖（新版本另存，便于回退）。

---

## 8. 审核 UI 设计

一个输入框加附件，配合**阶段化**的审核视图：

1. **输入**：类似聊天的输入框，附件以缩略图标签显示；“预算上限”默认收起在高级设置里。删除“创作方式 / 镜头数 / 模型系列”三个字段。
2. **理解确认（轻量）**：一张卡片展示 Agent 的理解（交付物、时长、角色、附件用途），可一键修改；如有澄清问题，直接在这里以选择题出现。
3. **审核 A：剧本与分镜板**（`story_video` 才有）
   - 顶部：总时长条（各镜头按时长分段着色，与目标时长对比）、预计花费（拆分为本阶段/视频阶段）、所用模型。
   - 角色卡：角色设定图 + 锁定描述，可替换参考图、重新生成。
   - 镜头时间线：关键帧缩略图横向排列，镜头间显示连贯方式图标（尾帧接续/独立/硬切/首尾帧）。点击镜头打开编辑抽屉：节拍、时长、首帧提示词、动作提示词、模型；修改后实时更新费用。
   - 支持增删、重排、合并镜头；“只看文字”与“看图”两种模式。
   - 关键帧未满意可单张重生成（便宜），全部满意后才点“开始生成视频”。
4. **生产看板**：每个镜头一张卡片（状态、耗时、花费、预览），失败卡片直接显示原因与修复按钮；串行链路用连线标出，用户能看懂“为什么这个镜头还在等”。
5. **审核 B 与交付**：逐镜头播放，可单独重做；确认后拼接，提供成片播放器、原画质下载、素材包下载。

---

## 9. 新增 Skill 清单

| Skill | 角色 | 权限 | 说明 |
|---|---|---|---|
| `ingest_attachment` | intake | write | 校验类型/大小，登记工件，探测媒体信息 |
| `analyze_image` | intake, research | llm | 多模态看图，结构化输出（主体、外观、风格、文字） |
| `web_search` | research | llm/外部 | 统一抽象，可接搜索 API 或模型自带联网检索；返回标题、摘要、URL、日期 |
| `fetch_page` | research | 外部 | 正文抽取；阻断内网地址（防 SSRF）；结果标记为不可信 |
| `image_search` + `download_reference` | research | 外部 | 返回候选图与来源页；限制尺寸/类型；入库为参考工件 |
| `write_prompts`（Prompt Smith） | director | llm | 逐镜头按模型写提示词 |
| `generate_image`（扩展） | production | generate | 增加 `mode=t2i|i2i` 与参考图列表，I2I 复用 wan2.7-image 多模态链路 |
| `animate_shot` | production | generate | I2V；支持 `mode=first_frame|first_last_frame`（首尾帧，已确认可接入，质量待评测） |
| `extract_frame` | production | write | 取尾帧/任意帧，复用 `video_media_service.extract` |
| `compose_video` | editor | write | 拼接，默认原画质 |
| `probe_media` / `qc_video` | editor, production | read | 时长、分辨率、可解码性 |
| `ask_user` | 图内部动作 | — | 不暴露给 LLM 自由调用，由节点产出 `Clarification` 后统一触发 |

搜索服务商**暂不定死**：Skill 层只定义统一接口（`web_search` / `image_search` 的输入输出 Schema），供应商适配器可替换，开发与测试期使用 Mock 适配器。

---

## 10. 数据与状态

- `AgentRun` 扩展：`request_text`、附件列表、`request_spec`、`research_dossier`、`story`、`plan_version`、澄清记录。
- 新增 `agent_plan_versions`：每次用户编辑或 Agent 修订都生成新版本，审核与生产绑定具体版本。
- 新增 `agent_shot_tasks`：每个镜头一行（阶段、依赖、尝试次数、关联 job/invocation、产物版本、花费）。UI 和恢复都读这张表，而不是从 LangGraph 状态里反推。LangGraph checkpoint 只保存流程位置和 ID 引用。
- **计费改为按秒**（已确认：模型调用按秒计费）：视频成本 = 模型单价（credits/秒）× 生成时长；图片按张；LLM 按调用。单价放在能力目录，`BudgetGuard` 与 `estimate_nodes_cost` 改为读取模型单价与 `duration` 参数，替代固定的 10 credits/视频。重试按实际时长再次计入。

---

## 11. 分阶段实施

| 阶段 | 内容 | 验收 |
|---|---|---|
| **A 一句话入口** | 多模态输入 API 与上传；Intake Agent；Clarification 协议与 UI 卡片；能力目录；删除三个表单字段；配方 `image_edit` / `image_create` / `single_clip` | “生成我的西装照 + 人像”无需任何选项即可完成；空文本被拒绝；附件用途判定准确 |
| **B 联网与看图** | `web_search` / `fetch_page` / `image_search` / `analyze_image`；Research Agent；候选形象选择题 | 新概念需求能产出带来源的资料与候选图；注入攻击样例不影响行为 |
| **C 长片规划与两段审核** | Creative v2（剧本/角色圣经/风格）；Director v2（分段、连贯性、选型、成本）；Prompt Smith；Plan Check；审核 A 分镜板 | 2 分钟需求产出时长正确、依赖合法的计划；关键帧审核通过前不产生视频费用 |
| **D 依赖调度与修复** | 任务图调度（并行/串行）、`extract_frame`、镜头状态机、局部修复与级联确认、生产看板 | 注入单镜头失败，仅该镜头重试；重做上游镜头时按规则询问下游 |
| **E 成片交付** | Editor Agent、`compose_video`、成片质检、原画质交付 | 成片可解码、时长与镜头数正确，默认未压缩 |
| **F 评测与调优** | 需求理解/提示词质量评测集（含长片样例）、首帧生视频 vs 首尾帧生视频 A/B 画质评测、成本与耗时看板、提问频率统计 | 以评测集对比 v1/v2 的计划质量、修复率、单片成本 |

A、B 可以并行开发；C 依赖 A；D、E 依赖 C。每阶段沿用现有规则：Mock 回归全绿后才进入下一阶段，真实调用需单独批准。

---

## 12. 两个需求的完整走查

**例 1：“生成我的一张西装照”+ 人像**
Intake：交付物为图片，附件用途为身份参考 → Director：配方 `image_edit`，模型选支持参考图的图像模型，Prompt Smith 写入形象锁定与“西装、正式肖像布光” → 费用低于自动执行阈值，直接执行 → 输出 2–4 张候选图，用户选择并下载。全程无澄清、无表单。

**例 2：“2 分钟左右，不同 AI 漫化形象的二创短片”**
1. Intake：交付物为视频，目标约 120 秒；“AI 漫化形象”标记为需要检索；未给剧情，交由 Creative 负责。
2. Research：检索各 AI 的拟人化形象 → 多数实体有多个版本 → 选择题：“DeepSeek 采用哪个形象？”（附图片），并给出推荐的主流版本。
3. Creative：写出约 2 分钟的剧本（如“各 AI 角色在一场比赛中各显神通”），分 4 幕、10 个节拍；角色圣经锁定每个角色的外观。
4. Director：按所选 I2V 模型的时长上限切成约 10 个镜头；同场景连续动作用尾帧接续，跨场景并行；首帧全部用 I2I 引用角色参考图；Prompt Smith 产出 20 条提示词；预计费用分为“审核 A 前约 X（角色图 + 关键帧）”与“视频阶段约 Y”。
5. 审核 A：用户在分镜板上确认角色卡与 10 张关键帧，重做其中 2 张不满意的关键帧（花费很少）。
6. Production：两个场景组并行生成；第 6 个镜头被内容审核拦截 → 自动改写提示词重试成功；其余镜头不受影响。
7. 审核 B：用户重做第 9 个镜头的动作；第 10 个镜头使用了第 9 个的尾帧 → 系统询问是否级联重做（显示费用）。
8. Editor：拼接为约 2 分钟成片，原画质交付，同时提供素材包。

---

## 13. 风险与取舍

| 风险 | 应对 |
|---|---|
| 尾帧接续导致长链串行、耗时长 | 场景组内串行、组间并行；评估首尾帧模型，实现“关键帧并行生成、视频连接”的方案 |
| 多镜头角色漂移 | 角色圣经 + I2I 参考图 + 每条提示词重复锁定描述；审核 A 中先看关键帧 |
| 检索内容的提示注入、版权、肖像 | 检索结果一律作为数据；保留来源；对真人肖像与知名 IP 给出提示，必要时提问确认 |
| 提问过多影响体验 | 只问高影响问题、合并提问、提供默认值、设次数上限 |
| LLM 计划不合法 | Plan Check 纯代码校验；不合法时把具体错误回传 Director 修订，最多 N 轮，仍失败则在审核页标出问题 |
| 成本估算偏差 | 按秒计价 + 重试系数；生产中实时显示已花费与剩余预算，超过预估阈值时暂停询问 |
| 规划模型能力不足 | 每个 Agent 角色单独配置模型（规划用强推理模型，看图用多模态模型），建立评测集后再定 |
