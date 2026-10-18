# CineCrew Agent v2 开发计划（Claude + Codex 协作版）

> 对应方案：[agent_v2_proposal_claude.md](agent_v2_proposal_claude.md)（网页版见方案文末链接）
> 适用场景：Claude Code 与 Codex 交替开发，任一方随时可以接手。本计划的重点是**让交接不丢上下文**。

---

## 1. 协作原则

### 1.1 分工

| 角色 | 擅长且省额度的工作 | 本计划中的任务类型 |
|---|---|---|
| **Claude** | 契约设计、跨模块编排、复杂状态机、阶段评审 | 标记为 `Claude` 的任务：Schema/接口契约、LangGraph 图结构、调度器、修复策略，以及每个阶段结束时的代码评审 |
| **Codex** | 按明确契约批量实现、补测试、前端页面 | 标记为 `Codex` 的任务：Skill、数据表与迁移、API、前端组件、测试用例 |

原则：**Claude 先写契约，Codex 按契约实现，Claude 在阶段门评审**。契约一旦写进 `CONTRACTS.md`，实现方不得私自修改；需要改时先在 `DECISIONS.md` 记录原因。额度紧张时，任何任务都可以由另一方接手，前提是遵守第 2 节的交接规则。

### 1.2 不可违反的规则（两边共用）

1. 不破坏经典工作流；每个任务结束时 `python -m pytest -q` 全绿（用 conda 环境 `video-factory`）。
2. 测试只用 Mock 与隔离数据库；**任何真实付费调用都需要用户单独批准**。
3. `backend/.env` 指向真实 MySQL，临时实例必须使用临时 SQLite 和 Mock。
4. LLM 只产出结构化决策，不直接调用工具；所有工具调用都经过 ToolRegistry。
5. 一个任务只改它声明的文件范围；两个工具不能同时修改同一个任务的文件。

---

## 2. 交接机制

### 2.1 仓库中的协作文件（Phase 0 创建）

```text
docs/agent_v2/
├── PLAN.md        # 本计划的任务看板版：任务 ID、状态、负责方、依赖
├── CONTRACTS.md   # 所有跨任务契约：Schema、API、表结构、事件、错误码
├── DECISIONS.md   # 决策日志：日期、决定、原因、影响的任务
└── PROGRESS.md    # 交接日志：每次停手前追加一条
```

根目录 `CLAUDE.md` 与 `AGENTS.md` 内容保持一致，只写三件事：
1. 当前在做 Agent v2，先读 `docs/agent_v2/PROGRESS.md` 最后一条，再读 `PLAN.md`；
2. 第 1.2 节的规则；
3. 测试命令与环境说明。

> 现在根目录的 `claude.md` 仍是“写技术笔记、禁止改源码”的旧指令，`AGENTS.md` 也是旧任务。不替换的话，两个工具都会被误导。

### 2.2 PROGRESS.md 条目格式（每次停手必须写）

```text
## 2026-10-20 · Codex · A3
状态：完成 / 进行中 / 阻塞
分支与提交：agent-v2/A3 @ abc1234（已合并 / 未合并）
完成内容：……
测试：pytest 132 passed；新增 test_attachments.py（8 个用例）
未完成 / 下一步：……
需要对方或用户决定：……
```

### 2.3 分支策略

- 先把当前分支 `codex/shared-task-queue` 上未提交的改动整理提交，并在此基础上新建集成分支 `feat/agent-v2`。
- 每个任务一个分支 `agent-v2/<任务ID>`，完成后合并回 `feat/agent-v2`，合并前测试全绿。
- 阶段门评审通过后打标签 `agent-v2-phase-A` 等，便于回退。

### 2.4 任务卡模板（交给任一工具时直接粘贴）

```text
任务：<ID> <名称>
先读：docs/agent_v2/PROGRESS.md 最后一条、CONTRACTS.md 中 <相关章节>
目标：……
允许修改的文件：……
不要修改：……（尤其是契约、经典工作流）
验收：
- [ ] 测试用例 ……
- [ ] pytest 全绿
完成后：提交到 agent-v2/<ID>，在 PROGRESS.md 追加交接条目，更新 PLAN.md 状态。
```

---

## 3. 阶段与任务

规模：S ≈ 半天，M ≈ 1–2 天，L ≈ 3 天以上（按单人估算，仅供排期参考）。

### Phase 0 准备（先做，约 1 天）

| ID | 任务 | 负责 | 规模 | 产出 |
|---|---|---|---|---|
| P0-1 | 整理当前分支、建立 `feat/agent-v2`、跑通全量测试作为基线 | Codex | S | 基线测试数、基线提交 |
| P0-2 | 创建 `docs/agent_v2/` 四个文件与新的 `CLAUDE.md` / `AGENTS.md` | Claude | S | 协作文件 |
| P0-3 | **Phase A 契约**：`RequestSpec`、`Clarification`、附件 API、能力目录字段、按秒计费公式、新的 Run 创建 API | Claude | M | `CONTRACTS.md` 第 A 章 |

### Phase A 一句话入口

依赖：P0-3。A2/A3/A5 可以并行。

| ID | 任务 | 负责 | 规模 | 主要文件 | 验收 |
|---|---|---|---|---|---|
| A1 | 能力目录：ModelRegistry 增加生成方式、时长范围、画幅、参考图支持、按秒单价、质量档位；迁移 + 种子数据 | Codex | M | `models/model_registry.py`、`services/model_service.py`、迁移 | 种子模型都有完整能力字段；迁移可重复执行 |
| A2 | 按秒计费：`estimate_nodes_cost` / `BudgetGuard` 读取模型单价 × `duration`，图片按张；替换固定 10 credits | Codex | M | `skills/budget.py`、`agent/plan_spec.py` | 5 秒与 15 秒费用不同；重试按时长再计；现有预算测试更新后通过 |
| A3 | 附件上传：多文件、类型与大小校验、登记为工件、探测时长/分辨率；`ingest_attachment` Skill | Codex | M | `api/agent.py`、新 Skill | 图片/视频/非法类型各有用例 |
| A4 | Intake Agent：`analyze_image` Skill（多模态模型）+ Intake 节点，输出 `RequestSpec`；空文本拒绝 | Codex（Claude 评审提示词） | L | `agent/intake.py`、`skills/tools/analyze_image.py` | Mock 下 10 个样例需求得到预期的交付物、配方提示和附件用途 |
| A5 | 澄清协议：图中断类型 `clarify`、API 动作 `answer`、提问上限、合并提问、默认值 | Claude | M | `agent/graph.py`、`agent/protocol.py` | 阻塞问题未答时不前进；非阻塞题可“按默认继续”（不设超时，见 D-006）；提问次数受限 |
| A6 | 简单配方：`image_edit` / `image_create` / `single_clip`；`generate_image` 增加 t2i/i2i 与参考图；`animate_shot`（首帧模式） | Codex | L | `skills/tools/*`、`agent/graph.py` | “西装照 + 人像”全流程无需任何选项完成（Mock） |
| A7 | 前端：新输入框（文本 + 附件）、需求理解卡片、选择题卡片；删除创作方式/镜头数/模型字段及界面美化 | Claude（用户指定） | M | `views/AgentStudioView.vue`、新组件 | 构建通过；手工冒烟：空文本按钮不可用、附件可删、选择题可提交 |
| A8 | 兼容：旧的 `mode` / `shot_count` / `video_model_preference` 字段弃用；remix 由 Intake 自动识别；`model_policy` 的正则改为读取 `RequestSpec.constraints` | Codex | S | `agent/protocol.py`、`agent/model_policy.py` | 旧客户端请求返回明确的弃用错误；remix 回归通过 |
| A-Gate | 阶段评审：契约一致性、提示词质量、测试覆盖 | Claude | S | 评审意见写入 PROGRESS | 修复后打标签 |

### Phase B 联网与看图

依赖：P0-3 中补充的 B 章契约（Claude，S）。可以与 A4–A7 并行。

| ID | 任务 | 负责 | 规模 | 验收 |
|---|---|---|---|---|
| B0 | B 章契约：`web_search` / `fetch_page` / `image_search` / `download_reference` 的统一 Schema、`ResearchDossier` | Claude | S | 写入 CONTRACTS |
| B1 | 检索适配器接口 + Mock 适配器；`fetch_page` 正文抽取与 SSRF 防护（拦截内网与本机地址） | Codex | M | 内网地址、超大页面、非 HTML 均被拒绝 |
| B2 | `image_search` + `download_reference`：限制类型、尺寸、数量，入库为参考工件并记录来源 | Codex | M | 非图片、超限、重复下载各有用例 |
| B3 | Research Agent：根据 `needs_research` 检索、看图、汇总候选形象，候选不唯一时产生图片选择题 | Codex（Claude 评审） | L | Mock 下“AI 漫化形象”样例得到候选与选择题 |
| B4 | 提示注入测试集：网页/图片描述中嵌入恶意指令，验证不影响行为 | Codex | S | 全部样例通过 |
| B-Gate | 阶段评审 | Claude | S | — |

### Phase C 长片规划与审核 A

依赖：A 阶段完成。

| ID | 任务 | 负责 | 规模 | 验收 |
|---|---|---|---|---|
| C0 | C 章契约：StoryPackage、ProductionPlan、计划版本与审核动作 | Claude | M | 写入 CONTRACTS |
| C1 | Creative v2：剧本、角色、风格，引用校验与澄清 | Codex | M | 120 秒节拍在容差内；角色参考来源与归属合法 |
| C2 | 数据表与版本服务：`agent_plan_versions`、`agent_shot_tasks`、迁移 | Codex | M | 迁移幂等；版本递增；旧版本与产物保留 |
| C3 | Director v2：按能力拆镜头、衔接、选型与按秒估算 | Codex | L | 代码推导依赖；默认模型及用户约束有效 |
| C4 | Prompt Smith 逐镜头 Skill + Plan Check（纯代码），一次自动修订 | Codex | L | 各规则正反用例；单镜头编辑只重写相关提示词 |
| C5 | 角色与关键帧预览生产、轮询、stale 判定与局部重做 | Codex | L | 经 ToolRegistry；成功产物复用；失败不自动重花费用 |
| C6 | 审核 A 图节点、动作、Run 视图、权限与恢复 | Codex | L | 两级审核；版本冲突与幂等；终点 `storyboard_approved`，无视频调用 |
| C7 | 分镜板功能：时长条、角色卡、时间线、编辑抽屉、费用与重做确认 | Codex（功能；Claude 负责美化） | L | 构建通过；实时估算；无效计划不能确认；保护未保存编辑 |
| C-Gate | 阶段评审 | Claude | S | — |

本表已按 C0 定稿后的 CONTRACTS C 章与任务看板统一编号；依用户最新分工，C1–C7 功能由 Codex 完成，界面美化与阶段评审留给 Claude。Phase C 默认关闭新长片路由，视频生产在 Phase D 接入。

### Phase D 依赖调度与局部修复

依赖：C 阶段完成。

| ID | 任务 | 负责 | 规模 | 验收 |
|---|---|---|---|---|
| D0 | D 章契约：镜头状态机、失败分类、修复策略、级联确认的 API 与事件 | Codex | S | 写入 CONTRACTS |
| D1 | 任务图编译与调度：无依赖任务并发、尾帧接续串行、首尾帧两端关键帧并行；状态写入 `agent_shot_tasks` | Codex | L | 10 镜头样例的启动顺序符合依赖；重启 worker 后从表中恢复 |
| D2 | `extract_frame` Skill（复用 `video_media_service.extract`）与 `animate_shot` 首尾帧模式 | Codex | M | 尾帧文件有效；首尾帧模式参数通过校验 |
| D3 | 失败分类与自动修复：瞬时错误重试、内容审核改写一次、参数不符退回 Director；单镜头修复次数与费用上限 | Codex | M | 注入各类失败，只影响对应镜头 |
| D4 | 重做与级联确认：重做镜头生成新版本、旧版本保留；下游标记待定并询问，不自动级联 | Codex | M | 三种选择（连带 / 只重做 / 取消）都有用例 |
| D5 | 生产看板前端：镜头卡片、依赖连线说明、失败原因与修复按钮、实时花费 | Codex | M | 构建通过；手工冒烟 |
| D-Gate | 阶段评审 | Claude | S | — |

### Phase E 成片交付

依赖：D1、D2。

| ID | 任务 | 负责 | 规模 | 验收 |
|---|---|---|---|---|
| E1 | Agent 发起的 Job 默认关闭压缩，拼接使用原始视频 | Codex | S | Agent Job 不产生压缩版本；经典 Job 行为不变 |
| E2 | `compose_video`：参数一致时无损拼接，不一致时统一分辨率/帧率（高质量编码）；用户指定时才输出压缩版 | Codex | M | 一致/不一致两类素材都能拼接；默认未压缩 |
| E3 | `qc_video` / `probe_media` 与 Editor 节点：可解码、时长偏差、分辨率一致、镜头齐全 | Codex | M | 缺镜头、空文件被拦截 |
| E4 | 交付页面：成片播放器、原画质下载、素材包下载 | Codex | S | 构建通过 |
| E-Gate | 端到端评审（Mock 全流程：一句话 → 澄清 → 审核 A → 生产 → 审核 B → 成片） | Claude | S | — |

### Phase F 评测与调优

| ID | 任务 | 负责 | 规模 | 说明 |
|---|---|---|---|---|
| F1 | 评测集：约 30 条需求（简单图片 / 单镜头 / 长片 / remix / 新概念），标注预期配方与关键约束；自动化评测脚本 | Claude 设计，Codex 实现 | M | 衡量配方准确率、计划合法率、提问次数 |
| F2 | 首帧生视频 vs 首尾帧生视频 A/B | 需用户批准付费调用 | M | 同一组镜头分别生成，人工打分 |
| F3 | 成本与耗时看板 | Codex | M | 每次运行的估算 vs 实际花费、各阶段耗时 |

---

## 4. 排期与并行

```text
周 1  P0 ─► A1 A2 A3 A5（并行）─► A4 A6 ─► A7 A8 ─► A-Gate
周 2       B0 ─► B1 B2（并行）─► B3 B4 ─► B-Gate         （与 A 后半段并行）
周 3–4     C0 ─► C1 C2 ─► C3 C4 C5 ─► C6 C7 ─► C-Gate
周 5       D0 ─► D1 D2 ─► D3 D4 D5 ─► D-Gate
周 6       E1 E2 E3 E4 ─► E-Gate ─► F1 F3（F2 待批准）
```

当前分工：用户指定 C1–C7 与 D0–D5 由 Codex 完成，Claude 保留 A5、A7、B5、界面美化及阶段评审。D0–D5 已完成 Mock 验收，D-Gate 待 Claude 接手；后续调整以 `docs/agent_v2/PLAN.md` 为准。

---

## 5. 阶段门检查清单（Claude 评审时使用）

- [ ] 实现与 `CONTRACTS.md` 一致；契约变更都有 `DECISIONS.md` 记录
- [ ] 全量 pytest 绿；新增功能有正反用例；前端 `npm run build` 通过
- [ ] 没有真实付费调用；没有 LLM 直接调度工具的代码路径
- [ ] 预算、幂等、审批在新路径上同样生效
- [ ] 经典工作流回归通过
- [ ] `PROGRESS.md` 交接条目完整，下一阶段的阻塞问题已列出

---

## 6. 开工前需要你确认的事项

1. 是否同意按第 2.1 节替换根目录的 `CLAUDE.md` 与 `AGENTS.md`（旧内容可以移到 `docs/archive/`）。
2. 当前分支 `codex/shared-task-queue` 上的未提交改动如何处理（提交还是丢弃），之后从哪里切出 `feat/agent-v2`。
3. 每个 Agent 角色使用的 LLM：规划类（Director/Creative）、看图类（Intake/Research）、Prompt Smith，可以先沿用现有配置，到 F1 评测后再调整。
4. F2 的付费评测预算上限。
