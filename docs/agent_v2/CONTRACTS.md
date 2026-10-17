# Agent v2 契约

> 跨任务接口的唯一来源。实现必须与此一致；修改契约前先在 `DECISIONS.md` 记录。
> 章节状态：**A 已定稿（2026-10-17）**｜B、C、D 待写（分别由 B0、C0、D0 任务产出）。
> 约定：所有 Schema 以 pydantic v2 实现，`extra="forbid"`，字符串去首尾空白；字段长度为上限。

---

# A 章：一句话入口

## A.1 Run 版本与兼容

| 项 | 规定 |
|---|---|
| 版本标记 | 新建的 Run 在 `agent_runs.request.schema_version = 2`。旧 Run 无此字段，视为 1 |
| 执行图 | worker 按 `schema_version` 选择图：1 走现有 `agent/graph.py`（只用于恢复已有 Run），2 走新的 v2 图 |
| 旧字段 | 创建请求中出现 `goal`、`mode`、`shot_count`、`video_model_preference`、`source_artifact_id` 任一字段，返回 `422 DEPRECATED_FIELD`，`payload.fields` 列出这些字段 |
| 旧接口 | `POST /api/agent/sources` 保留到 Phase C 结束，内部转调 A.3 的附件上传，返回值不变 |
| 序列化 | `serialize()` 不得再读取 `request["shot_count"]`；镜头统计从 `snapshot.plan` 计算（v1 Run 仍按旧逻辑） |

## A.2 创建 Run

`POST /api/agent/runs`

```json
{
  "text": "生成我的一张西装照",
  "attachment_ids": ["art_xxx"],
  "budget_limit": 100,
  "request_key": "client-generated-uuid"
}
```

| 字段 | 类型与约束 | 说明 |
|---|---|---|
| `text` | str，必填，去空白后 2–8000 字符 | 不满足返回 `422 TEXT_REQUIRED`。只有附件没有文字时同样拒绝 |
| `attachment_ids` | list[str]，0–`AGENT_MAX_ATTACHMENTS` 个，不可重复 | 必须是当前用户通过 A.3 上传的附件，否则 `404 ATTACHMENT_NOT_FOUND` |
| `budget_limit` | float，可选，`0 < x ≤ AGENT_MAX_BUDGET` | 省略时取 `AGENT_DEFAULT_BUDGET` |
| `request_key` | str，必填，1–128 字符 | 幂等键：同一用户同一 key 重复提交返回原 Run；内容不同返回 `409 IDEMPOTENCY_KEY_CONFLICT` |

返回 `202`，`data` 为 A.10 的 Run 视图。创建时不做模型选择、不估算镜头费用（这些由 Agent 决定）；只做最低费用检查：`budget_limit` 不足以覆盖理解阶段（`AGENT_MIN_RUN_CREDITS`）时返回 `402 BUDGET_EXCEEDED`。

## A.3 附件上传

`POST /api/agent/attachments`（multipart，字段名 `file`，一次一个文件）

| 类型 | 扩展名 | 大小上限 | 其他限制 |
|---|---|---|---|
| image | `.jpg .jpeg .png .webp` | `AGENT_MAX_IMAGE_MB`（默认 20） | 能被解码；边长 ≥ 256 px |
| video | `.mp4 .mov .mkv .webm` | `MAX_CONTENT_LENGTH`（现有 500 MB） | 时长 ≤ `AGENT_MAX_VIDEO_SEC`（默认 300）；能被 `VideoMediaService.inspect` 解析 |

不符合返回 `422 INVALID_ATTACHMENT`（`payload.reason`）。成功返回 `201`：

```json
{
  "attachment_id": "art_xxx",
  "kind": "image",
  "file_name": "me.jpg",
  "mime_type": "image/jpeg",
  "size": 1234567,
  "width": 1080, "height": 1440,
  "duration": null,
  "preview_url": "/api/artifacts/art_xxx/preview"
}
```

实现约定：
- 沿用 `agent/sources.py` 的做法：附件登记在 `agent_workspace` 模板下的一个 `strategy="agent_upload"` Job 中，Job 的 `config.agent_upload_owner` 记录上传者；`attachment_id` 即工件的 `artifact_id`。
- 工件类型：图片 `agent_attachment_image`，视频沿用 `source_video`（以便 remix 链路直接复用）。
- 媒体信息写入 `artifact.meta.media`：`{kind, width, height, duration, fps}`。
- 归属校验函数 `attachment_for_owner(artifact_id, owner_id) -> Artifact` 供 API 与图共用。

## A.4 能力目录（`models.capabilities`）

`models` 表新增 JSON 列 `capabilities`（非空，默认 `{}`），种子数据为每个模型填写。Agent 只能在 `agent_selectable=true` 的模型中选型。

```json
{
  "modes": ["i2v", "first_last_frame"],
  "duration": {"min": 2, "max": 15, "step": 1},
  "resolutions": ["720P", "1080P"],
  "aspect_ratios": ["16:9", "9:16", "1:1"],
  "reference_images": {"max": 3},
  "pricing": {"unit": "second", "credits_per_unit": 1.0},
  "quality_tier": "standard",
  "agent_selectable": true,
  "notes": "人像参考图可能触发更严格的内容审核"
}
```

| 字段 | 取值 |
|---|---|
| `modes` | `text` `image_understanding` `video_understanding` `t2i` `i2i` `t2v` `i2v` `first_last_frame` `r2v` 的子集 |
| `duration` | 视频生成模型必填，其余为 `null` |
| `reference_images` | 支持参考图时填写最大张数，否则 `null` |
| `pricing.unit` | `second`（视频）、`image`（图片，按张）、`call`（LLM 每次调用） |
| `quality_tier` | `fast` `standard` `high` |

规则：
- `capabilities` 与现有 `task_type` 并存；`model_guard` 的 `task_type` 校验保持不变，Agent 选型额外要求所需 `mode ∈ capabilities.modes`。
- 换用新模型只需新增或更新一条目录记录（种子或模型注册表 API），Agent 代码不得硬编码模型 ID。现有 `DEFAULT_*_MODEL` 配置继续作为“未指定时的默认值”。
- 种子中的单价是**演示值**，真实单价由用户在模型注册表中填写（见 DECISIONS D-003）。

## A.5 按秒计费

```text
视频：cost = credits_per_unit × duration × n_outputs          （unit = second）
图片：cost = credits_per_unit × n                             （unit = image）
LLM ：cost = credits_per_unit                                 （unit = call，缺省 1）
```

- `duration`、`n` 取最终参数：显式参数 → 模型 `default_params` → 能力目录 `duration.min`（视频）/ 1（图片）。
- 模型缺少 `pricing` 时回退到旧常量（视频 10、图片 2、LLM 1），并在日志中告警，便于发现漏配。
- 新函数 `skills/budget.py: estimate_model_cost(model, params) -> float`；`estimate_nodes_cost`、`PlanSpec.estimated_cost`、各生成类 Skill 的 `cost_fn` 都改为调用它。
- 重试与重做按实际参数再计一次（与现有账本累加语义一致）。

## A.6 RequestSpec（Intake 输出）

```text
RequestSpec
  deliverable: "image" | "video"
  recipe_hint: "image_edit" | "image_create" | "single_clip" | "story_video" | "remix"
  summary: str (≤ 500)                       # 一句话复述用户需求，展示在理解卡片上
  target_duration_sec: int | null (1–600)    # 仅视频；“2 分钟左右”→ 120
  duration_tolerance_sec: int (0–120, 默认 10)
  aspect_ratio: "16:9" | "9:16" | "1:1" | "4:3" | "3:4" | null
  output_count: int (1–4, 默认 1)            # 图片候选张数；视频固定 1
  subjects: list[Subject] (≤ 12)
  attachments: list[AttachmentUse]           # 与请求中的 attachment_ids 一一对应
  constraints: Constraints
  research_needs: list[ResearchNeed] (≤ 5)   # Phase A 只记录，Phase B 消费
  open_questions: list[Clarification] (≤ 3)
  confidence: float (0–1)

Subject
  name: str (≤ 80)
  description: str (≤ 1000)
  source: "user_text" | "attachment" | "needs_research"
  attachment_ids: list[str]

AttachmentUse
  attachment_id: str
  kind: "image" | "video"
  role: "identity_ref" | "style_ref" | "first_frame" | "remix_source" | "content_ref" | "unused"
  description: str (≤ 1000)                  # 来自 analyze_image / analyze_video
  reason: str (≤ 300)                        # 为什么判定为该用途

Constraints
  model_preferences: list[str]               # 用户点名的模型或系列，原文保留
  model_exclusions: list[str]
  must_include: list[str]
  must_avoid: list[str]
  style: str | null (≤ 500)
  language: str | null                       # 画面文字/对白语言
  compress_output: bool (默认 false)         # 只有用户明确要求时为 true

ResearchNeed
  query: str (≤ 200)
  reason: str (≤ 300)
```

校验规则（纯代码，Intake 输出后执行；不通过时把错误交回 Intake 重试一次，仍失败则 Run 进入 `needs_attention`）：
- `attachments` 覆盖全部 `attachment_ids`，且不引用不存在的附件；
- `recipe_hint = image_edit` 需要至少一个 `identity_ref` 或 `content_ref` 图片；`remix` 需要恰好一个 `remix_source` 视频；`single_clip` 若有 `first_frame` 则必须是图片；
- `deliverable = image` 时 `target_duration_sec` 为 null；
- 模型偏好与排除只记录原文，由 Director 在能力目录中解析（取代 `model_policy` 的正则抽取）。

## A.7 Clarification（选择题）

```text
ClarificationCard
  card_id: str
  asked_by: "intake" | "research" | "director" | "creative" | "production"
  questions: list[Question] (1–3)

Question
  question_id: str
  text: str (≤ 200)
  why: str (≤ 300)                           # 不问会怎样
  options: list[Option] (2–4)
  recommended_option_id: str | null
  allow_free_text: bool
  blocking: bool                             # 非阻塞题必须有 default_option_id
  default_option_id: str | null

Option
  option_id: str
  label: str (≤ 80)
  detail: str | null (≤ 300)                 # 选择后的影响，如“预计多花 30 credits”
  image_artifact_id: str | null              # 图片选项（例如候选形象）
```

流程规则：
- 图在节点产出 `open_questions` 后统一触发中断 `{"kind": "clarify", "card": ...}`，Run 状态变为 `awaiting_input`。Agent 节点不得自行中断。
- 每个 Run 最多 `AGENT_MAX_CLARIFY_ROUNDS`（默认 2）张卡片；超过后剩余问题一律取默认或推荐选项，并在审核页“Agent 的假设”中列出。
- 不设自动超时（见 D-006）。非阻塞题可以由用户点“按默认继续”一次性跳过。
- 回答通过 A.9 的 `answer` 动作提交；全部阻塞题都有答案才继续。答案写入 `snapshot.clarifications[]`（含卡片与答案），后续节点读取。

## A.8 Simple 配方计划（Director-lite 输出，审核对象）

适用于 `image_edit`、`image_create`、`single_clip`。`story_video` 与 `remix` 的计划结构见 A.11。

```text
SimplePlan
  recipe: "image_edit" | "image_create" | "single_clip"
  title: str (≤ 200)
  image: ImageStep | null                    # single_clip 使用用户图片作首帧时为 null
  video: VideoStep | null                    # 仅 single_clip
  assumptions: list[str] (≤ 10)              # Agent 自行默认的事项，展示给用户
  rationale: str (≤ 1000)                    # 选型与提示词思路
  estimated_cost: float                      # 由代码按 A.5 计算后覆盖，LLM 填写的值无效

ImageStep
  mode: "t2i" | "i2i"
  model_id: str
  prompt: str (≤ 8000)
  reference_attachment_ids: list[str]        # i2i 必填 ≥ 1，且不超过模型 reference_images.max
  params: dict                               # 经 model_guard.validate_params 校验
  n: int (1–4)

VideoStep
  mode: "i2v"                                # Phase A 只开放 i2v；first_last_frame 在 D2 开放
  model_id: str
  prompt: str (≤ 8000)                       # 只写动态
  first_frame: "user_attachment" | "generated_image"
  first_frame_attachment_id: str | null      # first_frame = user_attachment 时必填
  params: dict                               # duration 必须落在能力目录范围内
```

规则：
- 模型必须满足：`agent_selectable`、所需 mode 在 `capabilities.modes`、未被 `constraints.model_exclusions` 排除；用户点名的偏好在能力目录中无法满足时，产生 Clarification，不得静默替换。
- 审批：`estimated_cost ≤ AGENT_AUTO_APPROVE_CREDITS` 时跳过审批直接执行（默认 0，即总是审批，见 D-003）。
- 用户在审批时可以修改 `prompt`、`params`、`model_id`、`n`；修改后的计划重新执行全部校验与费用计算。

## A.9 Run 动作

`POST /api/agent/runs/<run_id>/actions`，在现有 `RunAction` 基础上扩展：

| action | 允许的状态 | 请求体 | 说明 |
|---|---|---|---|
| `answer` | `awaiting_input` | `{"card_id", "answers": [{"question_id", "option_id"?, "text"?}], "use_defaults": false}` | 每题必须给 `option_id` 或（`allow_free_text` 时）`text`；`use_defaults=true` 时非阻塞题取默认值 |
| `approve` | `awaiting_approval` | `{"plan"?: SimplePlan \| PlanSpec}` | v2 Simple 配方接受 `SimplePlan` |
| `reject` | `awaiting_approval` | — | 不变 |
| `deliver` / `revise` / `resume` | 不变 | 不变 | v2 Simple 配方不使用 `revise`（重新生成通过新 Run 或 Phase D 的重做） |

所有动作沿用现有命令收件箱语义：`agent_runs.command` 为空且状态匹配时才写入，否则 `409 INVALID_AGENT_STATE`。

## A.10 Run 视图与状态

v2 Run 的状态集合：

```text
queued → understanding → [awaiting_input ⇄ understanding] → planning → [awaiting_input]
       → awaiting_approval → producing → awaiting_delivery → delivering → success | partial_success
任意阶段 → failed | cancelled | needs_attention
```

`GET /api/agent/runs/<id>` 的 `data` 在现有字段基础上增加（v1 Run 这些字段为 null）：

```json
{
  "schema_version": 2,
  "text": "生成我的一张西装照",
  "attachments": [ /* A.3 返回结构 */ ],
  "request_spec": { /* A.6 */ },
  "pending_card": { /* A.7，仅 awaiting_input 时 */ },
  "plan": { /* A.8 或 A.11 */ },
  "results": [ {"kind": "image|video", "artifact_id": "...", "preview_url": "...", "download_url": "..."} ],
  "summary": {"steps_total": 2, "steps_success": 1, "steps_failed": 0}
}
```

## A.11 Phase A 的路由（v2 图）

```text
START → analyze_attachments → intake → (clarify)* → route(recipe_hint)
  image_edit / image_create → director_lite → (clarify)* → approval* → generate_image → collect → deliver
  single_clip               → director_lite → (clarify)* → approval* → [generate_image] → animate_shot → collect → deliver
  remix                     → 现有 remix 节点（analyze → … → deliver），源视频取 role = remix_source 的附件
  story_video（过渡）        → 现有 from_scratch 节点：shot_count = ceil(target_duration / 选定 i2v 模型 duration.max)，上限 20
(* approval 在费用不超过 AGENT_AUTO_APPROVE_CREDITS 时跳过)
```

`story_video` 的过渡路由在 Phase C 被 Creative v2 / Director v2 替换（见 D-007）。`deliver` 对单张图片/单段视频直接给出结果，不强制打包；同时保留 `package_project` 作为“下载素材包”。

## A.12 新增与扩展的 Skill

| Skill | 角色 | 权限 | 输入要点 | 输出要点 |
|---|---|---|---|---|
| `analyze_image`（新） | intake、research | llm | `attachment_id`（或 B 章的参考工件 ID）、`focus` (≤ 300，可选) | `ImageAnalysis{summary, subjects[{label, appearance}], style, text_in_image, has_human_face, suggested_role}` |
| `generate_image`（扩展） | production、system | generate | 新增 `mode: "t2i"|"i2i"`（默认 t2i，保持兼容）、`reference_artifact_ids`（i2i 必填）、`n` | 不变（`JobLaunchOutput`） |
| `animate_shot`（新） | production、system | generate | `first_frame_artifact_id`、`prompt`、`model_id`、`params`；预留 `last_frame_artifact_id`（Phase A 传入即 422） | `JobLaunchOutput`，`expected_outputs = ["artifact:i2v_video"]` |

实现约定：
- i2i 复用现有 wan2.7-image 多模态同步调用路径（I2I Test 中的 `DashScopeMultimodalSyncAdapter` 用法），由能力目录中 `modes` 含 `i2i` 的模型执行；不新增第二套生成代码。
- `animate_shot` 与 `generate_video(mode=i2v)` 共用 Job 化实现；`generate_video` 保持不变以兼容现有调用。
- 所有 `cost_fn` 改用 A.5 的 `estimate_model_cost`。
- Agent 发起的生成 Job 遵循 `constraints.compress_output`（默认不压缩）的规定放到 E1 实现；Phase A 不改变压缩行为。

## A.13 Agent 节点的 LLM 调用

- 每个 Agent 角色的模型由配置决定，留空时回退：`AGENT_INTAKE_MODEL`、`AGENT_VISION_MODEL`、`AGENT_DIRECTOR_MODEL`（空 → `AGENT_PLANNER_MODEL` → `DEFAULT_PROMPT_REWRITE_MODEL`）。具体模型暂不确定（见 D-002）。
- 统一使用 `planning.structured_call` 的模式：Schema 约束输出、本地校验、Mock 模式返回确定性样例。用户文本与附件分析结果作为“用户数据”传入，不拼进系统指令。
- 每个节点的 Mock 输出必须能让 Mock 全流程跑通，并覆盖至少一种需要澄清的样例。

## A.14 配置项（新增）

| 键 | 默认 | 说明 |
|---|---|---|
| `AGENT_MAX_ATTACHMENTS` | 8 | 单个 Run 的附件上限 |
| `AGENT_MAX_IMAGE_MB` | 20 | 单张图片上限 |
| `AGENT_MAX_VIDEO_SEC` | 300 | 附件视频时长上限 |
| `AGENT_DEFAULT_BUDGET` | 100 | 创建 Run 未给预算时使用 |
| `AGENT_MIN_RUN_CREDITS` | 3 | 理解阶段的最低预算 |
| `AGENT_AUTO_APPROVE_CREDITS` | 0 | 低于等于此费用的 Simple 计划免审批；0 表示总是审批 |
| `AGENT_MAX_CLARIFY_ROUNDS` | 2 | 每个 Run 的提问卡片上限 |
| `AGENT_INTAKE_MODEL` / `AGENT_VISION_MODEL` / `AGENT_DIRECTOR_MODEL` | 空 | 见 A.13 |

## A.15 错误码（新增）

| HTTP | code | 场景 |
|---|---|---|
| 422 | `TEXT_REQUIRED` | 没有有效文本 |
| 422 | `DEPRECATED_FIELD` | 请求包含 v1 字段 |
| 422 | `INVALID_ATTACHMENT` | 附件类型、大小、时长或解码不合法 |
| 404 | `ATTACHMENT_NOT_FOUND` | 附件不存在或不属于当前用户 |
| 422 | `INVALID_REQUEST_SPEC` | Intake 输出两次校验都不通过（记录在 Run.error） |
| 422 | `MODEL_CAPABILITY_MISMATCH` | 计划中的模型不具备所需 mode、时长或参考图数量 |
| 409 | `CLARIFICATION_INCOMPLETE` | `answer` 缺少阻塞题的答案 |
| 422 | `INVALID_ANSWER` | 选项不存在，或不允许自由文本却提交了文本 |

---

# B 章：联网与看图（待写，任务 B0）

# C 章：长片规划与审核 A（待写，任务 C0）

# D 章：依赖调度与局部修复（待写，任务 D0）
