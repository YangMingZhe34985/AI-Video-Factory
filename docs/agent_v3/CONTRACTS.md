# Agent v3 契约

> 跨任务接口的唯一来源（v3）。修改前先在 `docs/agent_v2/DECISIONS.md` 记录。依据：D-029 – D-031，方案 `docs/architecture/agent_v3_proposal_claude.md`（r3）。
> 章节状态：**V0 定稿（2026-10-18）**，覆盖 V1–V7；V8（经典路径）契约在开工前补写。
> 约定：Schema 用 pydantic v2，`extra="forbid"`；所有金额为演示 credits，不是服务商账单。

---

## V.1 术语与目录

| 术语 | 定义 |
|---|---|
| Tool | `ToolSpec`：输入/输出 Schema、权限、审批、费用、handler。经 `ToolRegistry.invoke()` 执行 |
| Skill | 仓库内 `backend/skills/<name>/SKILL.md`（frontmatter + 正文 + 可选资源）。只提供知识，不能执行 |
| Blueprint | 带 `blueprint` frontmatter 的 Skill，额外登记一个确定性的计划生成函数 |
| Agent | 由 Agent Card 定义的 LLM 循环，有工具清单、Skill 访问、上限，可以委派 |
| Plan IR | `ExecutionPlan`：Agent 与确定性运行时之间的契约（V.8） |
| Plan Patch | 对已批准计划的局部修改（V.10） |

目录：

```
backend/app/tools/                 # 由 backend/app/skills/ 更名；app.skills 保留 re-export 垫片（V1）
backend/app/tools/specs/           # 原 skills/tools/*.py
backend/skills/<skill-name>/       # Skill 库（V2）
backend/app/agents/                # 运行时、目录、工作区、委派（V3）
backend/app/agents/cards/*.yaml    # Agent Card（V3/V6）
backend/app/agents/prompts/*.md    # Agent 系统提示词（V6）
backend/app/plans/                 # Plan IR、编译器、运行时、Patch（V4/V5）
```

经典工作流、v1/v2 图、现有 API 路径与响应**全部不变**。

---

## V.2 工具层扩展（V1）

`ToolSpec` 新增字段（均有默认值，旧工具不需要修改即可工作）：

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `agent_visible` | bool | False | 能否出现在 Agent 工具清单中 |
| `plan_executable` | bool | False | 能否作为 Plan IR 节点 |
| `io_types` | `{inputs: {field: IoType}, outputs: {field: IoType}}` | {} | 计划编译器用于类型检查 |
| `agent_description` | str | `description` | 给 LLM 看的说明（面向“何时用”） |

`IoType` ∈ `image | image[] | video | video[] | audio | text | document | package | json`。

**硬性规则**：`permission == "generate"` 的工具**不得** `agent_visible=True`（启动时断言）。唯一例外是 `request_preview`（V.11），它有独立的额度和单价上限。

`ToolContext` 新增服务端字段（公共 Skill API 不接受这些字段）：`caller_agent: str|None`、`delegation_id: int|None`、`agent_step: int|None`。`tool_invocations` 新增可空列 `caller_agent`、`delegation_id`（迁移 + SchemaService 兼容）。

兼容目录（D-032）：`app.tools` 是唯一实现；旧 `app.skills` 全模块路径保持共享模块/账本行为。`build_default_registry()` 与旧 API describe 保留原22项及原字段；`build_v3_registry()` 扩展本阶段新工具。新元数据供代码及 `function_schemas` 使用。异步生成 `io_types.outputs` 表示完成后解析的命名工件（`image`/`images`/`video`），不是初始 Job 回执字段；V4 必须实现完成解析与类型检查，不能直接把 Job ID 当素材。

V1 新工具接口精化（D-032）：
- `analyze_images({artifact_ids:[1..8个唯一ID],focus?}) -> {images:[{artifact_id,analysis:ImageAnalysis}],usage:{prompt_tokens,completion_tokens}|null}`；多图仅一次请求，归属与返回ID一一核验。
- `list_models({mode?,family?}) -> {models:[{model_id,display_name,provider,family,modes,capabilities,parameter_schema,default_params,pricing,integration_status,verification_status}],demo:true}`；只返回启用且agent_selectable的目录，不由provider元信息授予权限。
- `estimate_cost({nodes:[1..200个 {node_id?,model_id,mode,params?,reference_artifact_ids?,media?,source_artifact_id?}]}) -> {nodes:[{node_id,model_id,mode,params,estimated_cost,input_video_seconds,output_video_seconds,pricing}],total_credits,demo:true}`；一项为单节点，多项为片段。只接受已解析输入，生成能力与参数仍验证；Wan3输入视频秒数由同Run素材实测，拒绝客户端自报或未解析的未来引用，不保存/执行计划。

回执隔离（D-032）：新Agent工具默认幂等键包含Run、caller_agent、delegation_id与输入摘要；运行时可提供更精确的工具调用键。`agent_llm_turn`保持V.3规定的step键，V3调用普通工具时须使用独立ToolContext，不能复用LLM回合键。v3预算准入按Run串行预留；`get_task_status.invocation_id`是查询目标而非上下文赋值，允许导出，但只能查询当前Run的Job/账本关联。

函数调用导出：`ToolRegistry.function_schemas(names) -> list[dict]`，返回 OpenAI 兼容的 `{"type":"function","function":{name, description, parameters}}`。`parameters` 来自 `input_model.model_json_schema()`，去掉 `ToolContext` 才能设置的字段。

### V.2.1 v3.0 Agent 可见工具

| 工具 | 来源 | 说明 |
|---|---|---|
| `analyze_images` | **新**：多图一次调用（D-030） | 输入 `{artifact_ids: [≤8], focus}`，一次多模态调用返回逐图结构化描述；`analyze_image` 保留兼容 |
| `analyze_video` | 已有 | 异步；Agent 通过 `get_task_status` 取结果 |
| `web_search` / `image_search` / `fetch_page` / `download_reference` | 已有 | 沿用 B 章来源白名单与 SSRF 防护 |
| `capture_reference_page` | 已有 | |
| `list_models` | **新**（只读） | 按 mode / family 过滤，返回能力、参数、单价，标注“已接入 / 未实测” |
| `estimate_cost` | **新**（只读） | 对节点或计划片段估价，与编译器同一算法 |
| `check_plan` | **新**（只读） | 调用计划编译器，只返回 `issues`、`estimates`、`experimental`、`resolved_models`（节点→服务器解析的模型）、`order`，不回显计划、不保存（D-038） |
| `list_skills` / `load_skill` / `read_skill_resource` | **新** | V.4 |
| `instantiate_blueprint` | **新** | V.4.2 |
| `list_agents` / `delegate` / `ask_user` | **新** | V.6 |
| `read_workspace` / `write_workspace` | **新** | V.7 |
| `submit_plan` | **新** | 只有 Producer 可用：把工作区中的计划交付审核（V.9） |
| `propose_patch` | **新** | 只有 Repair / Director 可用（V.10） |
| `request_preview` | **新** | 规划期低价预览图，受规划额度约束（V.11） |
| `get_task_status` | 已有 | |

### V.2.2 v3.0 Plan 可执行工具（`plan_executable=True`）

`generate_image`、`animate_shot`（含首尾帧，受原开关约束）、`generate_video`（t2v/r2v 图片参考）、`transform_video`、`extract_frame`、`compose_video`、`probe_media`、`qc_video`、`package_story`。V8 追加 `run_workflow_template`。新增可执行工具必须同时提供 `io_types` 与测试。

---

## V.3 `agent_chat`：带工具的 LLM 调用（V1）

```text
agent_chat(role, messages, tools: list[function_schema], *, ctx, max_tool_calls=8)
  -> {content: str|None, tool_calls: [{id, name, arguments: dict}], usage: {prompt_tokens, completion_tokens}}
```

- 以内部 ToolSpec `agent_llm_turn` 的形式经 Registry 执行（permission `llm`）。幂等键为 `{run_id}:{delegation_id}:{step}`：崩溃恢复时**回放**已记录的响应，不重复调用、不重复计费。
- 模型解析（D-032）：`AGENT_<ROLE>_MODEL → AGENT_PLANNER_MODEL → AGENT_V3_DEFAULT_TEXT_MODEL`；最后一项默认 `deepseek-v4.1-flash`，显式置空才回退 `DEFAULT_PROMPT_REWRITE_MODEL`。vision 对应 `AGENT_V3_DEFAULT_VISION_MODEL`（默认 `qwen3.7-plus`）。v2解析与经典默认不变。
- `qwen_chat` 适配器增加 `tools`、`tool_choice`，并解析 `tool_calls`（包括一次返回多个调用的情况）。参数 JSON 解析失败时返回结构化错误给 Agent 自我纠正，最多纠正 2 次，然后终止该 Agent 循环。
- 回合错误（D-032）：返回可选 `tool_call_errors:[{index,id?,name?,code,message,arguments}]`；任一错误使整轮工具请求不可执行。一次 `agent_chat` 只请求一次；纠错 helper 为下一step构建受控错误消息，最多两次修正，V3负责实际循环。已完成错误响应也持久化并结算，恢复不重复请求。
- **计费**：按 usage × 模型目录 `pricing.credits_per_1k_tokens`（新增可选字段；缺失时回退到原按次估价）。调用前先按 `max_tokens` 预估占用预算，调用后按实际 usage 结算。`credits_per_1k_tokens` 为非负有限标量，输入/输出同价；预留包括保守输入估计和输出max_tokens。缺失/无效usage不能当0退款；异常实际费超过预留时记录实际费并停止后续执行（D-032）。v3 默认文本/视觉模型的目录带演示 token 单价（D-038）。
- **多图调用**（D-032）：`analyze_images`在预留时冻结模型、消息、参数及价格，一次调用内不重新解析角色配置或单价；Mock使用独立`vision`脚本身份与服务端step，避免复用调用方的函数调用响应。
- **Mock**：`ScriptedLLM`。测试按 `(agent, step)` 预设返回值：文本或 tool_calls 序列。脚本耗尽时报错，**不得**静默返回空。`MODEL_ADAPTER_MODE=mock` 时 v3 的所有 LLM 都走脚本；没有脚本的 Agent 使用内置的最小“直接完成”脚本，供端到端 Mock 演示，并标注为示例结果。

---

## V.4 Skill 与 Blueprint（V2）

### V.4.1 SKILL.md

```yaml
---
name: long-form-video            # 小写短横线，等于目录名，唯一
description: 一句话，≤200 字     # 出现在 list_skills
when_to_use: ≤300 字
agents: [director]               # 推荐使用者，仅作提示
tools: [list_models, check_plan] # 依赖的工具，必须存在
related: [character-consistency]
version: 1
blueprint:                       # 可选，仅 Blueprint
  builder: app.plans.blueprints.story_video:build
  params_schema: {...JSON Schema...}
---
正文（Markdown，≤ 12k 字符）
```

- 加载器在启动时扫描、校验 frontmatter（引用的工具、related、builder 必须存在），结果缓存在内存中；校验失败的 Skill 不加载，并在启动日志和测试中报错。
- `list_skills(agent?, query?) -> [{name, description, when_to_use, blueprint: bool}]`
- `load_skill(name) -> {name, version, body, resources: [path]}`
- `read_skill_resource(name, path) -> {name, path, content}`：只能读取该 Skill 目录内的 UTF-8 文本文件（拒绝路径穿越），单文件 ≤ 64KB。资源与正文一起在启动时缓存为固定快照，读取不跟随启动后的文件更换（D-033）。
- Skill 内容视为**可信的系统知识**，因为它在仓库内并经过审定；运营者以后要在线编辑时另行决策。

### V.4.2 Blueprint

`instantiate_blueprint(name, params) -> {plan: ExecutionPlan, notes}`：确定性地生成计划草稿并写入工作区。不调用 LLM，也不产生费用。生成的节点带 `origin: {blueprint: name, version}`。

首批（V4）：`image-edit`、`image-create`、`single-clip`、`story-video`（含角色/关键帧预览门）、`video-remix`、`video-transform`。验收要求：同样的输入下，生成的计划与 v2 对应路径的节点、模型、参数、费用一致。

### V.4.3 首批 Skill（V2）

`intent-analysis`、`clarification`、`delegation-policy`、`image-edit-portrait`、`t2i-prompt-writing`、`i2v-prompt-writing`、`t2v-prompt-writing`、`long-form-video`、`character-consistency`、`first-last-frame`、`video-remix`、`wan3-transform`、`web-research`、`budget-planning`、`plan-review`（Critic 用），再加上六个 Blueprint 各自的 SKILL.md。内容从 v2 现有的 INSTRUCTION 与契约规则迁移，**不得编造未实测的能力或质量结论**。

分阶段启用（D-033）：V2 的六个 Blueprint 文档先作为知识指南，不含 `blueprint` frontmatter；V4 实现 builder 后再登记。`video-remix` 共用目录，因此本轮共 20 项。metadata 仅引用当前存在的工具；显式声明的 builder 仍须校验为可调用。四个关键 Skill 的内容由 Claude 审定。

---

## V.5 Agent Card 与目录（V3）

```yaml
name: director
description: ≤300 字，写给其他 Agent 看的“我能做什么、什么时候找我”
accepts: {brief: RequirementBrief, story: StoryPackage?, research: Dossier?}   # 工作区条目类型
returns: PlanDraft
model_role: director
tools: [...]                      # 必须是 agent_visible 工具
can_delegate_to: [creative, research, prompt_smith, critic]
limits: {max_steps: 40, max_llm_calls: 30, planning_credits: 20, max_parallel_delegations: 4}
prompt: prompts/director.md
```

v3.0 角色：`producer`（唯一面向用户、可 `submit_plan`）、`research`、`creative`、`director`、`prompt_smith`、`critic`、`repair`。
- `list_agents() -> [{name, description, accepts, returns}]`，不暴露提示词和上限。
- 卡片在启动时校验：工具存在且 `agent_visible`；`can_delegate_to` 中的 Agent 存在；全局委派图中不允许自己委派自己。

V3 只交付可运行的最小卡片与安全提示词，工具清单不得提前包含 V4/V5 未实现能力；V6 再完善正式提示词和创作策略（D-033）。

---

## V.6 Agent 循环、委派与提问（V3）

### V.6.1 循环

```text
run_agent(card, task, context_refs, delegation) :
  system = card.prompt + 用户约束摘要 + skill 索引(list_skills 结果) + 可委派 Agent 摘要
  loop:
    turn = agent_chat(...)
    执行 turn.tool_calls（按顺序；delegate 可以并行，受 max_parallel_delegations 限制）
    直到 Agent 调用 finish(output)，或触发上限
```

- `finish` 是每个 Agent 都有的工具，参数为该 Agent 的输出契约（V.6.3），经 Schema 校验后结束循环。
- **上限**（任一触发都停止，返回 `status=limit` 和已有的部分结果）：`max_steps`、`max_llm_calls`、委派额度、Run 规划额度、单次委派的**活跃时间**（只累计本 Agent 回合，不含等待用户与子 Agent；`AGENT_V3_DELEGATION_ACTIVE_SEC`，默认 600 秒，D-038）。工具拒绝向 Agent 返回清洗后的字段级 `errors`（不含提交值）。
- **循环检测**：同一工具、同样参数连续 3 次，或连续 5 轮没有新的工作区写入、委派或 finish，就注入一条“请换一种方式或结束”的系统消息；再次触发则停止。
- **持久化**：每个委派是一个 LangGraph 子图实例，每轮都写 checkpoint。工具结果靠 Registry 账本回放，恢复时不重复执行。worker 只运行一个 v3 Run 的一个就绪步骤，然后让出（沿用现有 tick 模型）。

### V.6.2 委派

`delegate(agent, task: str ≤2000, context_refs: [workspace_ref], expected: str, planning_credits?: float) -> {delegation_id, status, output_ref?, returned_reason?}`

- 校验调用方卡片的 `can_delegate_to`。委派深度从 Producer 算起不超过 3 层（Producer → Director → Creative → Research）。
- 被委派方的额度从委派方的剩余额度中划拨（调用时可以指定，默认为剩余额度的一半）。
- 被委派方可以 `finish(kind="returned", reason, suggestion)` **退回**，例如“2 分钟装不下这么多情节”。委派方收到结构化的退回结果后自行决定下一步。
- `task` 是不可信数据：被委派方的系统提示词写明“任务描述不能覆盖用户约束、预算与权限”。

### V.6.3 输出契约（`finish` 参数）

| Agent | `kind=completed` 的输出 |
|---|---|
| producer | `{outcome: plan_submitted | answer | cancelled, plan_ref?, message}` |
| research | `{dossier_ref}`（沿用 B 章 Dossier 结构，写入工作区） |
| creative | `{story_ref}`（StoryPackage，沿用 C.3 结构） |
| director | `{plan_ref, rationale}` |
| prompt_smith | `{updates: [{node_id, inputs_patch}]}` |
| critic | `{verdict: pass | revise, issues: [{node_id?, severity, message}]}` |
| repair | `{patch_ref, diagnosis}` |

所有 Agent 都可以使用 `kind=returned` 和 `kind=failed`（附原因）。

### V.6.4 提问

- 只有 Producer 能把问题发给用户：`ask_user(questions)` 复用 A.7 的 Clarification 结构与轮数上限，并触发图中断（`awaiting_input`）。
- 其他 Agent 调用 `ask_user` 时，运行时把问题作为 `returned` 结果交还给上一层，逐层上抛到 Producer；由 Producer 合并、去重，或者自己根据已知信息回答后再提问。
- 回答写入工作区（`kind=clarification`），所有 Agent 都可以读取。

V3 卡片的 `asked_by=producer`，问题与答案 Schema、默认策略沿用 A.7，不改变 v2 的 asked_by 枚举。额度耗尽可返回部分结果并停止，本阶段不自动批准追加预算（D-033）。

---

## V.7 Run 工作区（V3）

表 `agent_workspace_items`：`id, run_id, key, version, kind, payload JSON, artifact_ids JSON, author_agent, delegation_id, created_at`；`(run_id, key, version)` 唯一，写入只追加，不覆盖。

`kind` ∈ `brief | clarification | research_dossier | story | plan_draft | critic_review | patch | note`。

- `read_workspace(key?, kind?, version?)`：默认返回最新版本；可以列出全部 key 与摘要。
- `write_workspace(key, kind, payload)`：按 kind 做 Schema 校验（brief / story / plan_draft 必须是对应的模型）；单条 ≤ 256KB。
- 委派时传 `workspace_ref = {key, version}`，不复制内容。

`RequirementBrief`（Producer 写入）：沿用 A.6 RequestSpec 的字段**去掉 `recipe_hint`**，增加 `intent_notes`、`production_intent: bool`（V8 使用）。

阶段边界（D-033）：V3 的 `plan_draft` 只通过 V.8 结构 Schema，不表示通过编译和 dry-run；`patch` 写入、`finish(outcome=plan_submitted)` 在对应 V5/V4 实现前拒绝。工作区写入使用服务端调用键保存独立收据，崩溃回放不得追加重复版本。

草稿 `origin.blueprint` 未经验证。V4 必须将其与确定性 builder 的服务端收据核对后才能用于 experimental 判定，不能相信 Agent 自报来源。

持久化与调度（D-033）：每个委派保存独立 checkpoint，多个子委派可同时处于就绪状态，每 tick 协作式推进一个回合。工具账本是实际花费的唯一来源；父级可用额度扣除子树实际花费与未结束子委派的剩余配额，子委派结束后释放未使用配额。任何层级的上限不能被新委派扩大。

---

## V.8 Plan IR 与编译器（V4）

```text
ExecutionPlan
  plan_version: int (服务端), title, goal
  deliverables: [{kind: image | video | package, node_id, output}]
  nodes: [PlanNode] (1–200)
  stages: [{id, label}]                       # 仅用于界面分组
  estimates (服务端), experimental: bool (服务端)

PlanNode
  id: str (^[a-z0-9_]{1,40}$), tool: str (plan_executable)
  inputs: {field: literal | {ref: "<node_id>.<output_field>"} | {artifact: "<id>"}}
  model_id: str | null, params: dict
  depends_on: [node_id] (默认 [])             # 控制依赖，与数据引用共同形成 DAG
  stage: str | null
  gate: "preview" | null                      # 该节点完成后暂停，等用户确认再执行其后代
  origin: {agent, skills: [], blueprint?: {name, version}}
  rationale: str (≤300)
```

**编译器**（`compile_plan(plan, run) -> {plan, issues, estimates, experimental, dag}`）检查：
1. 工具在 V.2.2 列表中；输入通过该工具的 `input_model` 校验（引用位置用占位值）。
2. 引用存在、无环；`io_types` 匹配，包括单值与数组。
3. `{artifact}` 引用必须属于本 Run 的附件、检索参考图或已生成的工件（复用现有归属检查）。
4. 模型满足能力、模式、参数、时长与步长要求，以及用户的偏好和排除约束（复用 `select_plan_model`）。
5. 结构上限：节点 ≤ 200，深度 ≤ 30，单节点扇出 ≤ 50，视频总时长 ≤ `AGENT_V3_MAX_VIDEO_SECONDS`（默认 600）。
6. **视频节点之前必须有计划批准**（运行时保证）。`gate` 只能放在 image 输出节点上。
7. 估价：Σ 节点估价；按秒 / 张 / Wan3 的输入加输出计费，复用 `estimate_model_cost`。
8. `experimental`：只要有一个节点的 `origin` 中没有 `blueprint`，就为 true。
- issues 按节点返回：`{code, node_id?, message}`。计划保持可编辑，与 C 章一致。
- **dry-run**：`dry_run(plan)` 用 Mock 适配器在隔离环境执行整张 DAG，只验证数据流、产物类型与依赖顺序，零费用。提交审核前必须通过。

---

## V.9 运行时、状态与审核（V4）

表 `plan_node_tasks`：`run_id, plan_version, node_id, attempt, status(pending|running|success|failed|stale|cancelled), inputs_hash, invocation_id, job_id, artifact_ids, estimated_cost, error(FailureInfo), created_at, updated_at`；`(run_id, plan_version, node_id, attempt)` 唯一。这是 C/D 章镜头任务表的通用化版本，语义一致：输入哈希复用、失败分类、免费恢复、提交结果未知即停止、局部重做。

v3 Run 状态：`understanding`（Agent 规划中）· `awaiting_input` · `awaiting_plan_review` · `executing` · `awaiting_gate`（预览门）· `attention` · `awaiting_result_review` · `delivering` · `success` · `partial_success` · `failed` · `cancelled`。

动作（沿用 `/actions` 收件箱、请求键幂等、版本校验）：

| action | 状态 | 字段 |
|---|---|---|
| `approve_plan` | awaiting_plan_review | plan_version, repair_budget_credits(默认 0) |
| `revise_plan` | awaiting_plan_review / awaiting_result_review | plan_version, message（交给 Producer，由 Agent 处理） |
| `approve_gate` | awaiting_gate | plan_version, gate_node_id |
| `approve_patch` / `reject_patch` | attention / awaiting_result_review | patch_id, quote_id |
| `approve_results` | awaiting_result_review | plan_version |
| `reject` | 任意可交互状态 | — |

审批时再次编译并报价；`approve_plan` 检查 `estimates.total + 修复额度 ≤ 剩余预算`。

---

## V.10 Plan Patch（V5）

```text
PlanPatch
  patch_id (服务端), base_version, proposed_by: repair | director | user
  reason, evidence_refs: [failed task ids / artifact ids / workspace refs]
  ops: [ {op: update_inputs, node_id, inputs}
       | {op: replace_node, node_id, node}
       | {op: insert_node, node, before?: node_id}
       | {op: remove_node, node_id} ]
  scope: only | cascade
```

- **触发**：运行时按 D 章 FailureInfo 分类。只有 `content_policy`、`invalid_parameters`、`qc_failed`（新增，来自 qc_video 或预览门被用户否决）以及用户的 `revise_plan`，才会启动 Repair（或由 Producer 转给 Director）。`submit_unknown`、鉴权、余额、配置类错误**不启动 Agent**；可以免费恢复的查询或下载由代码直接恢复。
- **流程**：Repair 起草 → Director 审阅（可以修改或拒绝，拒绝时附原因）→ 编译器在 base_version 上应用 Patch，生成候选版本，计算影响范围（DAG 后代闭包）与增量报价 → 授权 → 新计划版本 → 运行时只执行受影响的节点，其余按输入哈希复用。
- **低风险自动授权**（D-029）：所有 op 都是 `update_inputs`，并且只修改提示词类字段；model、params、时长、引用不变；增量报价在 `repair_budget_credits` 剩余额度内；该节点自动修复次数 ≤ 2。全部满足时自动继续，否则生成 `patch_quote` 交给用户审批（复用 D 章的报价与 only/cascade 呈现）。
- 不得修改与失败无关的已完成节点，除非 `scope=cascade` 并已报价。版本不一致返回 409。内容合规改写沿用 `repair_motion_prompt` 的规则：只能改为无害表述，不得规避审核。
- Repair 的工具清单：`read_workspace`、`get_task_status`、`analyze_images`、`load_skill`、`check_plan`、`estimate_cost`、`propose_patch`、`finish`。**没有**任何执行或生成工具。

---

## V.11 额度与预算

| 层级 | 默认 | 说明 |
|---|---|---|
| Run 规划额度 | 20（`AGENT_V3_PLANNING_CREDITS`） | 包含全部 Agent 的 LLM 调用、`analyze_*`、检索与 `request_preview`。用尽后 Producer 必须 `ask_user` 申请追加，或者结束 |
| 委派额度 | 委派时划拨 | 不超过委派方的剩余额度 |
| `request_preview` | 单次 ≤ 1 张图，单价 ≤ `AGENT_V3_PREVIEW_MAX_CREDITS`（默认 3），每个 Run ≤ 6 次 | 规划期自动预览（D-029 已允许） |
| 计划执行 | 审批报价 | 与 v2 一致 |
| 修复 | `repair_budget_credits` | 与 D 章一致 |

全部计入 Run 的 `budget_limit`；账本按 `caller_agent` 区分，可以统计各 Agent 的花费。

---

## V.12 API 与 Run 视图（V3/V4/V7）

- 创建 Run 不变（text + attachment_ids）。`AGENT_V3_ENABLED=true` 时新 Run 写入 `schema_version=3`。
- Run 视图（schema_version=3）新增：
  - `agents`：委派树 `[{delegation_id, parent_id, agent, status, task_summary, credits, steps}]`；
  - `steps`：分页的步骤摘要 `[{agent, kind: llm|tool|delegate|ask, tool?, summary, credits, at}]`，**不返回**完整提示词或原始模型输出；
  - `plan`（ExecutionPlan）、`plan_issues`、`estimates`、`experimental`；
  - `nodes`：节点状态，同 D.6 的通用化版本；
  - `patches`：`[{patch_id, status, auto_approved, quote, diff_summary}]`；
  - `planning_budget`：`{limit, spent}`。
- 新接口：`GET /api/agent/runs/<id>/steps?page=` 获取完整步骤列表（本人可见，敏感字段脱敏）；`POST /api/agent/runs/<id>/patch-quote` 只读报价。
- 任务中心：v3 Run 的进度单位为 `plan_nodes`，阶段取 Run 状态。

---

## V.13 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `AGENT_V3_ENABLED` | false | 新 Run 是否使用 v3 |
| `AGENT_V3_DEFAULT_TEXT_MODEL` / `AGENT_V3_DEFAULT_VISION_MODEL` | deepseek-v4.1-flash / qwen3.7-plus | V1专用回退；不替换旧默认（D-032） |
| `AGENT_V3_PLANNING_CREDITS` | 20 | V.11 |
| `AGENT_V3_PREVIEW_MAX_CREDITS` | 3 | V.11 |
| `AGENT_V3_MAX_VIDEO_SECONDS` | 600 | V.8 |
| `AGENT_V3_MAX_DELEGATION_DEPTH` | 3 | V.6.2 |
| `AGENT_V3_DELEGATION_ACTIVE_SEC` | 600 | V.6.1（D-038） |
| `AGENT_PRODUCER_MODEL` / `AGENT_RESEARCH_MODEL` / … / `AGENT_REPAIR_MODEL` | 空 | 回退链见 V.3 |

---

## V.14 测试与评测

- **自动化测试**（Mock/Stub，隔离 SQLite）：用 ScriptedLLM 覆盖委派、退回、并行委派、上限、循环检测、注入内容、崩溃恢复（不重复调用和计费）、只有 Producer 提问、Patch 低风险自动授权与超额审批。断言的是**不变量**：
  - 生成工具从未出现在 Agent 的工具调用中；
  - 规划花费不超过规划额度；
  - 提交审核的计划都通过了编译和 dry-run；
  - 简单任务的脚本中不发生委派。
- **真实评测**（D-030）：`deepseek-v4.1-flash` 加 `qwen3.7-plus`（多图一次调用），可以少量生成图片，**禁止生成视频**。用例少而精，每条写明验证目的，记录调用次数与费用。只评测到“批准前的计划”与预览图。
- 每个阶段完成后，经典模式、v1、v2 的全量回归必须保持通过。

---

## V.15 任务与文件范围

| 任务 | 范围 | 验收 |
|---|---|---|
| V1 工具层 | `skills→tools` 更名与垫片；ToolSpec / ToolContext 扩展与迁移；`function_schemas`；`agent_chat` / `agent_llm_turn`；`qwen_chat` 的 tools 支持；ScriptedLLM；`analyze_images`；`list_models` / `estimate_cost` | 全量回归不变；Mock 与 Stub 覆盖多工具调用和参数纠错；可以做 1–3 次真实函数调用冒烟（D-030） |
| V2 Skill 库 | 加载器与三个 Skill 工具；V.4.3 首批 Skill；Skill 校验测试 | 引用全部有效；Claude 审定 `long-form-video`、`delegation-policy`、`intent-analysis`、`character-consistency` |
| V3 Agent 运行时 | Agent Card / 目录、循环、委派、提问、工作区、上限、循环检测、`agent_steps`、`agent_delegations`、v3 图骨架与 worker 接线、Run 视图的 agents / steps | 剧本回放覆盖 V.14 列出的场景 |
| V4 Plan IR | 编译器、dry-run、运行时（`plan_node_tasks`）、预览门、六个 Blueprint、`check_plan` / `instantiate_blueprint` / `submit_plan`、审核动作 | Blueprint 计划与 v2 对应路径的产物和费用一致 |
| V5 Plan Patch | Patch 模型、编译、增量报价、低风险自动授权、Repair 卡片、Director 审阅、`revise_plan` | 五类失败注入；只影响受影响子图；超额必须审批 |
| V6 Agent 上线 | 七个 Agent 的卡片与提示词、委派策略 | 真实评测达标，且简单任务不发生无谓委派 |
| V7 界面 | 协作时间线、通用计划视图（分镜板作为 stage 渲染）、规划额度、Patch 审批卡片 | 构建与浏览器验收（Claude 负责美化） |
| V8 经典路径 | 开工前补写契约（D-031） | — |

## V.16 V4 实施精化（D-034）

本节细化 V.2.2/V.8/V.9，不改变经典/v2 Registry：
- 新增仅 Plan 可执行的免费 `retain_video_segment({video_artifact_id,source_start_sec,source_end_sec}) -> {artifact_id:video}`，用于保留原片明确时间范围；输入必须属于当前 Run，区间须在实际视频内。
- `compile_plan(raw,run,*,registry=None,plan_version=1)` 返回 `{plan,issues,estimates,experimental,dag}`，内部另含 `validated_inputs`、`output_metadata`。`dag={order,dependencies,children}`；`node_inputs(node,*,plan_version=1)` 注入模型/参数及服务端版本，`resolve_inputs(value,outputs)` 递归解析引用。
- 输入只接受字面值、纯 `{artifact:id}`、纯 `{ref:node.output}` 或类型允许的容器；数组整体引用与单值元素引用严格区分。inputs 禁止 model_id/params/template_id/plan_version，媒体引用只在工具声明的媒体字段使用。generate_image.image 为首张、images 为完整数组，image 交付可用两者。
- estimates.video_seconds 为视频交付总时长，不重复累计中间合成；generated_video_seconds 限制全部计费生成节点秒数，两者均受 AGENT_V3_MAX_VIDEO_SECONDS 限制。未来引用按上游类型、数量与时长上界估价，真实执行复验；超出批准上界则停止，不以零秒报价未知素材。Wan3 保留完整 I+G 与全部实际媒体检查。
- v3 transform_video 明确输入为 `{operation:reference|edit|extend,prompt,media:[{type,artifact_id}],source_artifact_id?}`，model_id/params 由 PlanNode 顶层注入。交付工具 plan_version 由服务端注入。package_story 必须有针对同一视频的 QC 祖先且其结果通过。
- dry-run 使用隔离内存 Stub 执行整张 DAG，逐节点解析引用、校验真实输入 Schema、模拟类型化命名输出并验证依赖顺序；禁止生产 handler、数据库写入、文件写入与网络，费用为零。实际 Mock Job/MQ 贯通另有执行器回归，不将 dry-run 当作模型质量验收。
- 复用 AgentPlanVersion 保存 ExecutionPlan 与编译/dry-run 结果；plan_node_tasks 在 V.9 字段上增加 inputs/output/state JSON，state 保存输入/产物摘要、恢复次数与复用来源。未来产物在实际就绪时冻结解析值与摘要；已受理任务优先恢复原 provider_id。
- 一次计划批准覆盖整张 DAG，包括交付处理；gate 仅阻塞其后代。全部节点完成后 awaiting_result_review，approve_results 只确认交付、不重跑工具；终端处理可显示 delivering。规划费用与生产费用分开展示但共用 Run 总预算。
- Blueprint 收据保存服务端生成的原始及规范化草稿哈希，只有匹配才允许 experimental=false；原始输入不得自带服务端价格/manifest/quote/许可。四个关键 Skill 与正式提示词的 Claude 审定状态不因此改变。
- 规划工具输入：`check_plan({plan:PlanDraft})` 只读；`instantiate_blueprint({name,params})` 返回计划、说明、workspace_ref、issues、估价与 experimental，并原子保存工作区及来源收据；`submit_plan({plan_ref:{key,version}})` 仅 Producer 调用，通过编译与 dry-run 后原子创建审核版本，失败保留草稿及 issues，不授予生成许可。`finish(outcome=plan_submitted)` 必须携带与服务端提交收据相同的 plan_ref。
- `request_preview({purpose,prompt,reference_artifact_ids?})` 只提供一张规划图，服务端按有无参考图选择 t2i/i2i 默认模型；不接收 model_id/params/n。Registry 外层账本计费一次、最多六个非 rejected 调用、每次不超过配置的三 credits 上限；独立冻结 permit 保护 Job/MQ 调度，成功结果生成不可变工作区 note。公开工具输入不得设置 plan_node_task_id/plan_preview_id 等服务端上下文。
- 编译器内部另返回 source_artifact_ids/input_artifact_metadata；批准时冻结现有源素材摘要，节点就绪时复验源文件与前驱产物摘要。公开 Run 只返回可审核计划、节点状态、工件链接和统计，不返回内部校验占位值、原始模型消息或服务端许可。
- submit_plan 成功时在同一事务完成 Producer 委派并保存 plan_submitted 输出；无需额外模型回合才能进入审核。request_preview 已创建未提交 Job 的恢复仍使用原 permit/账本/Job；存在提交证据时只允许最多两次原 provider_id 的免费读取恢复，未知提交停止。QC 时长以批准的源片段时长为基准，打包前复验 QC 输入摘要；compressed_artifact_id 只能来自同一 compose 节点的明确压缩副本。

## V.17 V5 Patch 实施精化（D-035）

### V.17.1 草稿与操作
PatchDraft = {base_version:int>=1, reason:str(1–2000), evidence_refs:Evidence[](最多40，默认[]), ops:Op[](1–50), scope:only|cascade(默认only)}。不接收服务端字段。
Evidence 为互斥 {task_id:int>=1} | {artifact_id:str} | {workspace_ref:{key,version}}，逐项校验当前 Run 归属。
Op 为互斥 {op:update_inputs,node_id,inputs:dict} | {op:replace_node,node_id,node:PlanDraftNode} | {op:insert_node,node:PlanDraftNode,before?:node_id} | {op:remove_node,node_id}。
update_inputs 浅合并顶层 inputs；null 仅能清除工具允许的可选值。replace 的 node.id 必须保持一致；before 给目标增加新节点的 depends_on。单 Patch 每个目标至多一次操作，新插入 id 不可同时成为其他 op 目标。删除交付目标或产生悬空引用直接报编译 issue，不自动改写 deliverables。

### V.17.2 服务端记录与审阅
Run.snapshot.v3_patches 按 patch_id 保存 {patch_id,draft,proposed_by,proposal_ref,status,director_review,...}；工作区草稿只保存 PatchDraft。
Patch 状态为 proposed/review_pending/reviewed/awaiting_approval/rejected/applied/invalid。流程单独保存于 snapshot.v3_repair_flows[flow_id]，v3_active_repair_flow 指向当前流程；其 trigger 为服务端失败回执、用户修订或门反馈，不能由模型伪造。
propose_patch({draft}) 仅 Repair/Director，在同一事务保存草稿/来源/工具收据及提议委派完成状态；不执行生成。
review_patch({patch_id,verdict:approve|revise|reject,reason,revised_draft?}) 仅当前流程指定的 Director 委派。revise 必须带修订草稿并表示审阅修订后通过，approve/reject 不带替换草稿。审阅收据绑定 delegation_id、review_ref、最终 draft_hash、request_key 与基准版本；只读报价复核工作区作者/内容和委派，不信任模型自报审阅。
advance_repair_flow(run,registry)->bool 每次最多推进一个确定性阶段；创建 Repair/Director 仍经过 Registry.delegate，额度来自同 Producer 剩余规划配额。草稿提交、审阅和委派的本地收据覆盖 Registry/checkpoint 间隙。True 表示当前 tick 由修复流程接管，禁止普通 Producer 完成映射覆盖执行或等待批准状态。

### V.17.3 编译、影响范围与报价
apply_patch_draft(base,draft) 返回独立 PlanDraft，不写库；quote_patch(run,record,scope=None,registry=None) 返回内部 {compiled,dry_run,decisions,quote}，不产生模型调用或新版本。
decisions 包含 base_version/target_version/scope、私有哈希、每节点 execute/reuse/retain（以及范围外失败的保留状态）、来源证明、受影响集合和自动授权判断。SourceProof 冻结旧任务版本/id、真实 inputs/hash、输入/输出摘要、output、artifact_ids、invocation_id/job_id。任何客户端不可提供 decisions。
公开 quote = {patch_id,base_version,scope,quote_id,can_apply,affected_node_ids,execute_node_ids,reused_node_ids,kept_node_ids,removed_node_ids,continuation_node_ids,estimated_credits:{repair,continuation,total},node_costs:[{node_id,action,estimated_cost,input_video_seconds,output_video_seconds}],automatic:{eligible,reasons,remaining_credits},warnings,issues,demo:true}。
total=repair+continuation，不再收费复用/保留结果。only/cascade 分别有各自 quote_id；scope 选择进入报价哈希。无效候选返回 can_apply=false 与 issues；伪审阅、归属或版本冲突直接 403/409。
quote 另含 manual_can_apply：人工审批总预算需覆盖 total + 原修复池剩余预留；自动审批覆盖 total + 本次占用后剩余预留。can_apply 表示至少一种方式可执行；automatic.eligible 同时检查自动总预算。人工不可批但自动可批时使用专门 warning 说明，不将其混为全局编译失败。尚未开始的节点属于 continuation，不占本次修复池。
影响范围为旧/新 DAG 后代闭包并集。only 保留未直接修改的已完成下游生成结果，明确历史来源与衔接风险；cascade 强制执行影响子图，即使命中原输入 hash。所有交付处理节点重新执行。范围外成功产物需验证可用；范围外失败保留失败，不自动重新提交。
失败触发时 only 不允许改与失败无关的已完成节点；user_revision 允许在人工批准后重做已完成目标并保留下游，不能自动授权。已明确批准的 only 历史保留可以跨后续无关修订沿用，必须核验原 Patch 批准链与真实输入/产物摘要。

### V.17.4 批准与恢复
approve_patch(run,patch_id,quote_id,scope,*,automatic=False,registry=None) 在 Run 锁内复算，漂移返回 PATCH_QUOTE_CHANGED/409；原子保存版本、节点任务、执行批准、历史许可、Patch 状态和修复占用。重放已批准 patch 返回原版本，不重复创建任务或占额度。
自动修复只针对服务端允许的失败节点，全部 op 为提示词字段 update_inputs，模型/参数/时长/引用/结构不变，且不影响已完成产物、不需要保留风险确认。repair_budget_credits 不因新版本重置，repair_claims[patch_id] 一次性占用；同逻辑节点跨版本最多两次，失败修复也消耗次数。Run 总预算还覆盖 continuation，真实花费仅来自工具账本。
snapshot.v3_repair={budget_limit,repair_claims:{patch_id:{credits,node_ids,automatic,status,approved_version}}} 独立于每版本执行快照；只有自动修复占用该预授权池，人工批准不重置或补充池。Patch approval/rejection 保存 quote_id、scope，批准另存 version/automatic；同内容重放返回原结果。
确定性批准预检失败（版本、报价、预算或无效候选的明确拒绝）在处理器事务回滚后清除旧动作箱；原幂等 key 仍保持原请求，重新报价使用新动作 key。未知提交、意外异常及已激活后的执行不包含在该异常边界。批准/拒绝已落库而流程尚未结束时，从对应收据和 PlanTask 重建执行/审核状态；不得从 resume 的临时 understanding 推断成功。
未解决 submit_unknown、鉴权/余额/配置失败不启动 Repair；存在未知提交或旧 Job/MQ 仍在执行，任何 Patch 都不激活。原 provider_id 免费查询/下载仍由确定性代码处理。
revise_plan 对未批准计划唤醒同 Producer；对已批准计划转交 Director 起草 Patch。planning_epoch 只换 checkpoint 标识，不清计数、额度或 started_at；已超时仍停止。已批准版本禁止 submit_plan 绕过 Patch。
如上个终止工具已提交但规划回合尚未收尾，修订前必须匹配成功的原 LLM/终止工具收据，补齐缺失工具回复并完成原 steps 记账一次，再切换 epoch；不能丢弃未知 pending_turn 或换 key 重做收费调用。

### V.17.5 API 与公开状态
POST /api/agent/runs/<id>/patch-quote 输入 {patch_id,scope?}，只读、本人可见。
actions 增加 revise_plan {plan_version,message,gate_node_id?}、approve_patch/reject_patch {patch_id,quote_id,scope}，均要求 request_key；审批范围必须与 quote_id 一致。
revise_plan 可用于 awaiting_plan_review / awaiting_result_review / awaiting_gate，以及没有未知提交或仍在执行任务的 attention；门否决必须提供当前成功且未批准的 gate_node_id，服务端保存 qc_failed 反馈证据。修订不修改原用户硬约束。
公开 patches 返回状态、作者、原因、精简 diff、审阅结论、报价/是否自动批准及批准版本；不暴露私有哈希、原始模型消息或文件路径。reject_patch 只拒绝当前补丁，保留已完成产物及原失败状态。
Run 另公开 action_pending、resume_count 与 repair_budget={limit,committed,remaining}（预授权占用，不重复计入账本花费）；节点公开 retained、来源版本与依赖。attention 接受新动作后暂转 understanding，动作箱保存 admitted_from_status，由 worker 消费，避免后台自发重试。
patches.diff_preview 为逐操作 {op,node_id,before,after}：输入更新仅展示被改字段，替换/新增/删除展示对应 Plan 节点；使用同 Run 基准版本生成并脱敏，便于用户核对具体修改后再审批。

## V.18 V6 角色策略与提示词范围（D-036）
- 七个 Card 和正式提示词说明各自的输入/输出、何时委派、何时直接完成、工具失败/额度/不确定性的处理；角色输出仍使用 V.5 的 workspace/finish 格式。submit_plan、propose_patch、review_patch 的成功动作已原子完成对应委派，不需要额外 finish 回合。
- Producer 独立完成简单图片或单镜头任务；Research 提供受工具回执约束的来源，Creative 提供 StoryPackage，Director 起草 PlanDraft 并安排真实依赖/模型/按秒估价，Prompt Smith 返回范围内提示词更新，Critic 返回只读审阅，Repair 仅处理服务端分配的局部补丁。首尾帧仍是待验证候选，默认不压缩。
- delegate 输入新增 prompt_scope?:{plan_ref:WorkspaceRef,node_ids:NodeId[](1–200，唯一)}。agent=prompt_smith 时必填，其他角色禁止；plan_ref 必须同值包含在 context_refs、kind=plan_draft，node_ids 必须存在且为支持 prompt 的生成节点。创建子委派时服务端保存不可变范围，不能通过任务文字扩大。
- Prompt Smith finish(kind=completed,updates) 每条为 {node_id,inputs_patch:{prompt:非空字符串}}；列表不为空、不重复、不越界，长度使用已有提示词上限。不接受 negative_prompt/model_id/params/时长/引用或任意其他字段。此结果只是一份受限建议，由父 Agent 应用到新 PlanDraft 并重新 check_plan/submit_plan；已批准计划仍必须走 V5 Patch。
- 普通 delegate(agent=repair) 在没有服务端 active repair flow 时拒绝；确定性修复协调仍使用原 Registry.delegate、父配额与稳定收据。
- 本轮验收仅 Mock/Stub：照片改造、单镜头、约 120 秒故事、原片改造四场景，验证真实运行时/工具回执及编译计划。脚本的正确选择不证明真实 LLM 能自主达到同等效果，Claude 的 Gate 与提示词审定保持独立。

- 六个 Blueprint 指南增加可由 read_skill_resource 获取的 params.schema.json 与最小 examples.json；JSON Schema 与服务端 Params.model_json_schema 保持一致，示例素材标记为需替换的占位符。不能只把参数合同放在不会返回给 Agent 的 frontmatter；Schema 资源不授予执行权限。

- 视频理解边界：当前 analyze_video 通过异步 Job 返回内容/提示词描述，不提供已验证的逐镜头时间码。原片改造可采用用户指定且经媒体时长校验的范围；不得把内容描述伪装为自动镜头切分证据。精确切点不确定时由 Producer 澄清。

- Director 增加 get_task_status 只读工具用于取回异步预览；没有扩展任何生成权限。analyze_images 当前接受同 Run 上传/检索图，不接受生成图或预览图；生成关键帧由用户 gate 审核，不宣称已有自动视觉质量评估。

- Repair 仍登记在内部七角色目录以供确定性协调，普通 list_agents 与初始可委派提示不列出 Repair；Card 的内部权限不等同于允许模型自行启动修复流程。

- 规划额度上下文：新LLM step在请求前持久化一份服务端 quota snapshot，包含 delegation_limit、delegation_remaining、run_planning_limit、run_planning_spent、run_budget_limit、run_spent，均为调用前值（本轮LLM也会消耗配额）。快照只描述状态，不授予授权；同step重放必须使用原快照，已有旧账本而无快照时沿用旧消息，不新增上下文改变原请求摘要。模型应按实际子任务显式分配 planning_credits，并保留自身汇总/提交所需额度；不自动上调任何限额。
- 上述兼容只保证新增quota上下文不改写原step。跨发布若函数Schema或工具权限已变化，仍遵守原严格摘要校验并安全停止，不自动重发付费回合，也不声称可无缝迁移所有在途旧委派。
- 角色必须能读取实际写入合同：plan-review resources 暴露 brief/research_dossier/story/plan_draft/critic_review/patch 的模型 JSON Schema，以及十个 Plan 工具的 resolved input_schema、Plan io_types 命名输出和 authoring 字段放置说明。异步 Job 回执字段不等于 Plan 完成输出。角色按需读取，不把全部资源注入每轮，不开放生成函数；以实际编译/归属校验为准。资源漂移由回归阻止。capture_reference_page 只对原用户文本中 URL 创建正文工件，不能充当图片或任意研究网页截图。

## V.19 V7 功能界面（D-037）
- 新面板仅用于 schema_version=3。协作树使用 agents 的 delegation_id/parent_id，步骤使用 GET steps 分页；不读取内部 snapshot/messages。预算分别显示 Run 已花费、规划限额/已用、自动修复已占用/剩余，后两者不再加到账本花费。
- 按 Plan.stages 分组节点，展示工具/模型/提示词/参数/依赖、关键帧门与历史保留来源。输出时长与累计计费生成时长分别使用 estimates.video_seconds / generated_video_seconds，节点费用使用服务端 estimates.nodes；没有单价信息显示未知。
- approve_plan 明确当前 plan_version 与用户可选 repair_budget_credits；approve_gate 绑定当前成功未批准 gate_node_id；approve_results 只接受结果。revise_plan 输入修改意图，门反馈携带 gate_node_id，不直接改批准计划或绕过硬约束。
- Patch 先显示 diff_preview 与审阅结论，再请求当前scope只读报价。人工批准要求匹配patch_id/base_version/scope/quote_id、manual_can_apply、有限非负估价与显式风险确认；接口仍权威复验。quote_id非执行许可，前端不能提供私有decisions。
- 动作进行中禁用重复按钮；同内容网络重试使用稳定request_key。Run切换、版本或scope变化取消旧请求并废弃迟到结果；组件卸载取消请求/计时器。媒体只使用现有鉴权工件组件/精确本地路由下载。
- 浏览器验收覆盖亮/暗主题、约400px无横向溢出、分页步骤、计划/门/交付动作、only/cascade和旧报价失效；仅Mock。UI不声称已通过真实模型质量评估。

- 同一Run同版本的普通轮询不重置编辑、范围或进行中的动作/下载；正在切换到另一Run时，旧任务回执不能取消新选择，动作确认前的迟到轮询不能回滚历史列表。

## V.20 V9 评测问题修订（D-039）

### V.20.1 选择门（V9a）
- PlanDraftNode.gate 扩展为 preview|choice|null；choice 仅允许 select_image，select_image 必须带 choice。现有字段默认值不变，旧计划摘要不因扩展改变。
- select_image 是 v3 私有、Plan 可执行、需要批准、permission=read 的零费用本地工具，Agent 函数目录和经典 Registry 不变。作者 inputs 只有 candidate_artifact_ids：2–20 张唯一图片，可为单个 image[] 引用或 image 引用/本 Run 工件的列表；输出 image:image。服务端执行输入另注入 selected_artifact_id，作者禁止填入。
- 依赖成功且祖先门已批准后，selector 保持 pending，冻结候选顺序、文件指纹、来源任务、节点摘要与版本；Run 进入 awaiting_gate，无关分支仍可调度。没有选择时不得调用 selector 或下游，也不默认第一项。
- approve_gate 增加 selected_artifact_id 与 choice_digest：choice 必填，preview 禁填。服务端复验当前版本/未批准门、候选归属/文件/顺序/来源与摘要；接收后记录 snapshot.v3_execution.choice_receipts，选定 ID 进入实际 inputs_hash，后续 tick 通过 Registry 执行。选择不扩大预算；全部候选成本均纳入计划估价。
- 同一动作重放沿用原收据，不同选择需要 Patch；旧版本、过期摘要、非候选、文件或来源变更均拒绝。确定性拒绝消费动作箱，未知异常保留恢复证据。revise_plan 的门反馈同时接受已就绪且未批准的 pending choice。
- Patch 仅在节点、所有候选（含未选候选）、来源和原审批证明均保持一致时继承选择并重新绑定版本。候选重做、增删、重排或内容变化均重选；only 保留的旧下游产物保持旧 provenance 与明确风险确认，不能归因于新的选择。
- 公开节点增加 choice:{ready,choice_digest,candidates:[公开工件],selected_artifact_id}（非选择节点可省略/null）；不暴露文件路径或私有证明。前端展示所有候选、不预选，选中后显式确认；版本/摘要/候选变化清空本地选择，普通轮询不清空。
- 范围：agents schema/API/动作消费；plans 编译/私有工具/dry-run/执行/许可/选择证明/Patch/修订/公开视图；plan-review 作者资源；V3PlanBoard/v3-plan/v3-actions 与回归。不改变经典页面，不做整体美化。

### V.20.2 上下文投影（V9b）
- 原 state.messages、账本和工作区原文不删改；只生成模型请求视图，不改变 assistant tool_calls 的参数、顺序和调用/回复配对。 V11f（V.21.6）仅对有保存证明的旧计划参数提供明确例外；顺序、配对及持久历史仍不改变。
- 60,000 Unicode 字符为软目标、2,000 字符为候选下限；按旧到新压缩成功回执：read_skill_resource、重复 load_skill、read_workspace/write_workspace 的旧 payload。保留每个 Skill 最新正文、最近两个完整工具回合、system/user、错误、澄清/委派、付费理解、检索与计划问题。
- 替代回执明确不完整，提供原长度/SHA-256、精确免费重读工具及参数；工作区必须有不可变版本，不能用最新值代替原材料。无法安全重读则保留。软目标未达到不截断受保护消息，不宣称硬 token 限制。
- 每个 LLM step 在调用前保存单一 pending_context={step,policy_version,source_hash,messages_hash,messages,metrics}。已有账本优先恢复原 messages，否则同 step 校验消息摘要并用原冻结请求；新 step 才重算。原额度快照及工具 Schema 摘要校验保留，active_seconds 仍按 D-038。
- 范围：新增 agents/context.py、runtime 的请求投影与恢复、相关隔离测试；不引入摘要模型或额外 LLM 调用。

### V.20.3 简单任务读取（V9c）
- 六个 Blueprint Skill 正文加入最小完整参数例及必填/默认/引用说明；完整 Schema 与复杂示例按需读取。只精确调整 Producer/Director 的效率说明，不改 Claude 审定的职责、安全、预算与四个关键 Skill。
- 实例化返回可审核草稿及 issues 后，可直接 submit_plan；内部继续编译/dry-run，无需机械地再次读取/检查/finish。不能跳过缺失参数、模型能力或需求约束验证。
- 不更改 Blueprint 版本/接口；正文例通过实际 Params 与 Registry 回归防漂移。Stub 验证简单任务少量回合、无委派、审核前不生成，不宣称真实 LLM 延迟改善。

### V.20.4 付费死节点（V9d）
- 从 deliverables 经 inputs 数据 ref 反向追踪；不在可达集合的生成类付费节点报 PLAN_UNUSED_PAID_NODE（阻塞，含 node_id）。depends_on 仅控制顺序，不证明产物被消费；免费 QC/probe 等保障节点不受此限制。
- selector 的全部候选都是数据依赖，不因最终未选中误报。确需交付额外图则显式列 deliverable；单纯预览 gate 或说明文字不能掩盖无用收费。
- 范围：plans/compiler、plan-review 指引与编译/Blueprint/Patch 回归；不自动删节点或改变用户预算。

### V.20.5 多参考图选型（V9e）
- 仅 v3 generate_image/i2i、参考图大于一张且用户需求没有精确型号约束时允许容量回退。正常策略模型已满足容量则沿用原选型；只有其容量明确不足才扩展到启用、agent_selectable、适配器已接入且符合用户系列/排除的 i2i 模型。默认配置禁用、未知、排除或适配器未接入不能触发回退。禁止丢图或合成一张绕过限制。
- 空节点 model_id 按候选 model_id 稳定排序，逐个用真实 validate_generation_model 验证全部参数后选择；具体节点 ID 只在同一合格池内原样接受，不静默替换。用户需求中的精确 ID/显示名/规范别名永不放宽，明确系列只能系列内。保留全部模型参数，支持规范化计划再次编译；无可用候选返回问题，不吞掉预算或内部异常。视频与经典/v2 策略不变。
- v3 story-video 先收集并去重全部角色参考，再选择关键帧模型；生成帧 model_id 可为 null。各候选按其真实能力生成并校验画幅参数，编译及后续提交仍复验同一具体型号。
- 编译后冻结具体 ID 与成本，审核展示最终选择；批准后模型/参数/费用变化仍需原有重新校验/审批。不声称能力匹配等于画质验证。
- 范围：v3 compiler/选型辅助、story-video Blueprint/指南与能力/费用/约束回归，不修改共享默认配置。

## V.21 V11 质量与效率修订

### V.21.1 角色身份输入（V11a，D-040）
- PlanDraft/ExecutionPlan 增加 `character_references: {character_id: [IdentityRef]}`（默认 {}，最多8角色，每角色1–3个唯一引用），`story_ref: WorkspaceRef|null`（默认 null）。IdentityRef 仅为纯 `{artifact: id}` 或纯 `{ref: "node.image"}` 单图引用；character_id 沿用 StoryPackage 的字母/数字/下划线/连字符1–40限制。
- PlanDraftNode 增加 `characters: [character_id]|null`（默认 null，最多8个唯一ID）。null 表示未声明，[] 表示显式空镜。只允许生成工具声明非 null；定妆种子例外见下项。有非空角色目录时，每个生成节点都必须显式声明，未知角色报 `PLAN_UNKNOWN_CHARACTER`，遗漏声明报 `PLAN_CHARACTERS_REQUIRED`。
- 目录所有引用为必需的身份依据，不能丢掉其中任何一张。artifact 必须属于当前 Run 且为图片；未来输出只允许 `generate_image.image`、有效 n=1、gate=preview，且该节点只声明被定义的单个角色。身份种子可以从零生成，无需输入自身；不能将多角色镜头、数组、选择器或有循环的未来输出当定妆种子。每个未来种子最多定义一个角色。非法目录报 `PLAN_INVALID_CHARACTER_REFERENCE`。
- 若当前 Run 有 StoryPackage 且草稿未给 story_ref，编译只读选最新故事并将其确切 key/version 冻结在规范化计划中；显式引用必须是同 Run 的 story。目录必须覆盖该故事全部角色且不能增加未知角色；已有角色 artifact_ids 必须原样全部保留；待生成角色必须绑定合法定妆种子。缺目录/缺角色为 `PLAN_CHARACTER_REFERENCE_REQUIRED`，非法故事引用为 `PLAN_INVALID_STORY_REFERENCE`。已固定计划以后不随最新故事漂移。没有 story 的独立计划可以显式自带角色目录；没有目录或角色声明的简单旧计划兼容。
- 编译按真实媒体数据引用逐输出传播身份依据，忽略 depends_on、提示词、rationale 及 JSON 报告。普通生成节点合并图像/视频输入依据，再仅传播自己已声明且依据完整的角色；每个声明角色缺任何依据报阻塞 `PLAN_CHARACTER_REFERENCE_MISSING`，message 包含角色ID及补多参考关键帧/补引用等修复方式。不改变模型、不补图、不删角色。
- `select_image.image` 只能证明所有候选共同具有的身份依据（交集，含 image[] 的每个候选）；`compose_video` 与从其提取的帧保守使用各段交集。extract_frame/retain_video_segment 只沿对应视频输入传播，不从 QC/probe/package 或控制边取得依据。生成首尾帧、多参考输入仍受原能力/类型/预算约束。
- story-video Blueprint 根据输入 StoryPackage 生成目录，定妆、首尾帧和视频写 characters；尾帧链仍须满足当前镜头角色输入。通用 Producer/Director 及 Patch 重编译使用完全相同检查，不能用兜底或人工修改绕过。
- 保证范围：结构化声明的身份输入覆盖，不保证真实画面身份或角色出场声明的语义正确性。明确 [] 的空镜仍须 Director/用户审核；不从自然语言猜角色，不强行要求一个节拍拆出的每个近景都同框。
- 兼容：characters=null、空 character_references、story_ref=null 不序列化进旧形状，避免改变旧 Blueprint/节点摘要。仅当输入精确匹配当前 Run 数据库已保存的旧 ExecutionPlan 且没有新增身份字段，允许不追认最新 story；新草稿/新 Patch 不享受此豁免，客户端不能用自报版本绕过。
- 旧计划修订：PatchDraft 可选 `identity_upgrade:{character_references:<同Plan目录Schema，必填非空>,story_ref?:WorkspaceRef}`。仅基计划无非空目录时允许，已有目录报 `PLAN_IDENTITY_UPGRADE_FORBIDDEN`；已有固定 story_ref 必须继承，不可替换。节点声明/引用通过原有 replace/insert 操作明示，完整编译不放宽。普通 Patch 最多50操作，带升级最多200操作，Plan总节点上限仍200。升级始终要求人工（自动原因码 `IDENTITY_UPGRADE_REQUIRES_REVIEW`），参与 Patch/quote 摘要，公开身份目录/故事前后差异；null 不序列化，旧摘要不变。

### V.21.2 自动修复意图保真（V11b，D-041）

- review_patch 在原字段外必填 intent_preserved: strict bool、changed_elements: ChangedElement[]（最多40项）。ChangedElement = {element,change:"changed"|"removed",before,after,reason}；element 1–300字符，before/reason 1–1000字符且非空白，after 最多1000字符；changed 的 after 必须非空白，removed 可为空。无默认 true，也不把字符串布尔转为判断。
- Director 依据最终草稿评估用户点名的角色、动作、主题、目标等，变化逐项列前后内容与原因；不确定给 false。repair_flow 的不可变证据包含原 user_request 和冻结 constraints，模型推测的审核原因不能当作供应商事实。
- 服务端保存 patch.<id>.intent version=1、kind=note、author=指定独立 director；内容绑定 patch/base_version/draft_hash/verdict/reason/原请求键和结构化评估，使用独立派生请求键避免与 Patch 工作区收据冲突。复验 Run、委派、作者、工作区内容/哈希和引用，评估加入原审阅哈希及报价复验。
- 仅 intent_preserved=true 且 changed_elements=[] 才可能自动批准；仍须全部 V.17.4 条件和 V11a 人工门。变化产生 PATCH_INTENT_CHANGED，未知/false 产生 PATCH_INTENT_UNCERTAIN；报价展示 warning，人工批准仍使用当前 quote_id 和范围。非空变化即使错误地声明 true，也不得自动。
- 完全缺少新增评估的历史记录视为未知，不自动重放授权，不改已批准历史；新评估字段/引用残缺或与不可变证据不符，报 PATCH_REVIEW_REQUIRED。公开旧记录可以展示未知，但不能据此绕过报价核验。
- Run patches.review 增加 intent_preserved:boolean|null、changed_elements。UI 显示保真/变化/未知、点名元素的修改前后与原因；当前未知/变化等待用户审核，历史 applied 保持只读与实际批准方式。所有内容仍经公开视图脱敏，私有工作区/摘要/原始消息不暴露。

### V.21.3 Patch 来源与元数据差异（V11c，D-042）

- 实际作者来自同 Run 的 AgentDelegation、kind=patch 工作区的 author_agent/delegation_id/payload hash，以及服务端 v3_patch_tool_receipts 中 name/agent/delegation/input hash/output 引用的一致证明；不信任草稿 origin.agent 或 snapshot.proposed_by 单个字段。合法作者为 repair/director。
- 原提议绑定 proposal_ref 与 author_delegation_id；approve 采用已核验提议作者，审阅证明沿用 V.21.2 的独立评估及工作区，不新增对 approve 原始 review_patch 收据的完整核验。revise 采用独立 Director 的 review_ref、request_key 和对应 review_patch 原始收据，并核验最终 draft 与不可变工作区相同。原 proposed_by 与最终作者分开；用户修订按 trigger.kind=user_revision 表示来源事件。
- apply_patch_draft 的规范化候选接受已核验作者，对全部显式修改目标（update_inputs/replace/insert）及 insert.before 附带依赖调整节点统一 origin.agent；删除节点没有新来源。其余 origin 字段沿用草稿，rationale 不自动改写。未经修改的节点保持原样，复用产物的真实输入/历史授权链仍独立核验。
- 作者证明进入 review_hash，quote 与 approve 重算同一候选和证明；旧 quote 不可跨规则/作者变化使用。原始提议、审阅草稿及历史批准版本保持不可变。
- 完全缺少作者证明的旧记录 final_author=null、author_verified=false；自动条件增加 PATCH_AUTHOR_UNVERIFIED，只能人工。新证明部分缺失/篡改报 PATCH_AUTHOR_REQUIRED，不通过猜作者降级。
- patches 增加 final_author、author_verified、trigger_kind、metadata_diff。每个 metadata_diff 元素为 `{node_id,incidental,origin?,rationale?,depends_on?}`；可选字段均为 `{before,after}`，仅真实值不同时出现。depends_on 为节点ID数组，新增/移除节点的一侧可 null；显式目标和 insert.before 附带目标均覆盖，完全未变不造差异。来源、理由与依赖分别展示，所有内容脱敏，不暴露收据或私有哈希。
- 未应用新 Patch 展示规范化候选；已 applied 从持久化 approved_version 实际内容生成 after、metadata_diff 及身份头部差异，缺版本时 after=null、metadata_diff=[]，不能用新规则模拟旧结果。历史可同时显示已核验实际作者与当年错误 origin，原 diff_preview 的输入/结构展示继续保留。

### V.21.4 简单任务 brief 与完整情节路由（V11d，D-043）

- Producer与intent-analysis正文包含同形的合法RequirementBrief例，覆盖Subject/AttachmentUse/Constraints必填字段、枚举、严格布尔和模型原文；示例不是默认用户意图。沿用现有Schema及归属/附件全覆盖/硬约束校验，不新增自动规范化。
- 示例覆盖当前结构时不强制重复读取Schema；复杂transform、开放问题、未覆盖嵌套或字段错误才按需读取。已有资料可复用，真实多图理解仍单次批量，必须检查模型与费用。
- 主要事件、顺序及结局已有明确用户输入时，Producer直接交Director技术规划；Director不因缺少StoryPackage而再委派Creative。传递原文或精确note引用，不擅自删改；只有实际创作缺口或用户明确要求补写才调用Creative。必要Research仍按知识缺口调用。
- 不新增执行权限或免审核路径；V11a角色输入、各节点能力、估价和审批全部保留。目标c1/c6≤6轮，只有真实评测可确认；Mock/Stub回归只证明短路径可执行。

### V.21.5 回合终止原因与增量计划（V11e，D-044）

1. `AgentTurnOutput` 增加可选 `finish_reason: str|null`，从供应商choices[0].finish_reason原样记录到工具输出/账本与评测逐轮指标；旧回执和Stub缺失时是null。不能用completion_tokens等于8000反推真实finish_reason。
2. `finish_reason=="length"` 返回 `tool_call_errors` 中明确 `AGENT_OUTPUT_TRUNCATED`，`tool_calls=[]`；即便部分sibling参数完整也不执行，纯文本截断同样报告。该响应已完成并正常按usage结算；缺usage保留原保守计费。恢复使用原成功回执，不重发；未知HTTP仍按既有规则停止。
3. 纠错仍只由Agent运行时在下一付费step进行且最多两次；专门提示把计划拆成≤12节点的小批量、引用已保存版本，并指出该轮无工具执行。不自动增加max_tokens、配额或调用次数。原始输出/错误保留账本；面向模型的截断诊断只需摘要，不机械回灌整段未完成计划。
4. `append_plan_nodes({plan_ref:WorkspaceRef,nodes:PlanDraftNode[1..12]})` 是Agent可见、permission=write、零工具费用、只允许Producer/Director的规划工具，仍经ToolRegistry校验/幂等/账本。生成函数仍不暴露给Agent。
5. plan_ref必须是当前Run的plan_draft精确版本；首次用既有write_workspace写完整头（title/goal/deliverables/stages等）及第一批节点，结构合法即可保存，中间未解析引用不表示编译通过。追加只增加nodes，不能修改已存节点、头、交付或角色目录；需要改这些内容时写一个完整新草稿，不放宽现有Schema。总节点≤200、唯一ID、256KiB、素材归属及有限JSON校验不变。
6. 追加在Run锁与活动委派检查内完成；同一request_key先核验原输入摘要/作者/委派并返回原收据，之后才做最新版本检查，避免崩溃重放误报stale。不同请求使用过期基版报明确 `PLAN_DRAFT_VERSION_CONFLICT`，不自动对最新版本追加。写完整工作区新版本与本地工具回执同一事务，旧版本永不变。
7. 返回恰好七字段的精简收据 `{workspace_ref:{key,version},key,version,kind:"plan_draft",node_count,input_hash,payload_hash}`，不回显全计划；`read_workspace`可免费精确重读。`input_hash=inputs_hash(AppendInput.model_validate(原请求).model_dump(mode="json"))`，覆盖默认字段与现有节点序列化规则；`payload_hash=inputs_hash(validate_payload("plan_draft",保存的完整新Plan))`。inputs_hash 为当前已有规范 JSON（sort_keys、无空白分隔、ensure_ascii=false、allow_nan=false）的 SHA-256。key 与 workspace_ref 一致，version 精确等于输入基版 +1，node_count 为完整节点数，至少本批数 +1、至多200；这些证明供 V11f 仅投影确有保存回执的旧参数。新版本不继承已修改Blueprint的“原样生成”证明。已有批准/执行/完成状态拒绝增量新计划，用户修订仍走既有Patch。
8. `check_plan` 输入改为 `{plan:PlanDraft}` 或 `{plan_ref:WorkspaceRef}`，严格有且仅有一个非null值，不接受两者/空对象/显式null伪装；旧plan输入兼容。plan_ref只读解析所属Run及kind，再走相同compile_plan，输出仍是精简issues/estimates/experimental/resolved_models/order。写草稿与append不自动授予编译通过或生产许可，submit_plan仍完整编译/dry-run。
9. Runtime将append纳入本地回执恢复、有效进展及启动时未终结写回执扫描。崩溃可免费补齐工具回执，不重复新版本；源输入/hash不符时拒绝。目录/卡片Schema改变的旧LLM回执仍遵守原严格恢复校验，不重新调用规避冲突。
10. 验收：适配器length各种形状、usage及重放；多批追加与引用检查；旧版本/跨Run/权限/finished拒绝；重复ID/总量/尺寸边界；不同请求并发同基版；本地commit到Registry间隙恢复；未完成草稿仍不能submit。只Mock/Stub，真实质量与token目标留到V-Gate5。
11. 长片作者策略允许跳过大型 story-video Blueprint 的一次性参数输出，按分批通用 Plan 创建；这不是新自动服务端转换，不减少用户所需内容或人物/关键帧。append 不支持原地编辑/删除已有节点；完整重写仍可能超上限，该剩余边界应在验收报告中记录。

### V.21.6 已保存计划请求视图（V11f，D-045）

- context policy_version 改为2；仅 project_messages 输出可以改变经过以下证明的历史 assistant 函数参数。调用顺序、ID、回复配对及原始持久消息不变；未覆盖内容继续 V.20.2。
- 完整配对且成功的 write_workspace(plan_draft)，只有真实输入经 WriteInput/PlanDraft 归一化后的 payload 与保存回执完全同摘要，才产生保存证明。append_plan_nodes 使用真实 AppendInput，核验输入哈希、payload_hash、key、源版本+1及合法节点数；不从文字猜版本，不合成未返回的完整计划。
- 精确 read_workspace 的实际 plan_draft 回执也可提供已观察版本与 payload 摘要。相同 key/version 出现冲突摘要则相关内容全部保留。每 key 保留最高版本最新一次生产参数；最高版本最新完整 read 回执受保护，不能再被 V9 通用压缩删除。
- 旧版本及同版本重复生产参数可替换为显式 context_projection，附 request_view_only/not_executable、原参数 SHA-256、保存 payload/input 摘要和精确 read_workspace 地址；仅在实际更短时替换。旧 write 回执完整 payload 同步投影，可超越最近两轮的 V9 保留规则。
- check_plan(plan) 仅当 issues=[] 且规范化计划与已有保存证明精确相同，才可改成带投影说明的 plan_ref 视图（包括冗余检查最新版本）；失败、未保存或匹配不明的检查保持原文。小型 append 回执不重复裁剪。
- 原 state.messages、ToolInvocation 与 AgentWorkspaceItem 不变，投影参数绝不能作为 Registry 重放输入。runtime 仍在调用前冻结 pending_context；已有账本或同 step 恢复使用当时完整冻结请求，不用新版策略重算后再收费。
- system/user、硬约束、错误、澄清与其他受保护证据沿用原规则。每个 key 的最新版及大错误可能使软目标无法达到，应记录真实 token 峰值和根因，不能截断安全证据宣称达标。

### V.21.7 逐张风格候选（V11g，D-046）

- 对“每种风格一张”的需求，使用独立 generate_image 节点、n=1 与各自 prompt；同描述 n=N 仅表达多个变体，不能代替指定差异。引用同一固定身份时仍逐节点遵守 V.21.1。
- 选择门沿用 V.20.1：select_image.candidate_artifact_ids 为多个节点 image 引用组成的列表，gate=choice；全部候选都计费且参与数据可达性，下游仅引用 selector.image。未选择不执行下游，不默认第一张；无需额外逐图 preview 门。
- 继续限制2–20个唯一候选、Plan最多200节点、模型/参数/预算/归属/批准校验。用户要全部图片交付时直接声明所有 deliverables，不机械增加选择门。
- plan-review 资源提供纯图片选择和选择后动画两个完整示例，image-create/plan-review 正文链接并说明。回归通过实际编译/dry-run/Registry/Mock Job，明确选择第三张并核验 selector 与动画的真实输入一致；没有新增生产代码路径。

## V.22 V-Gate5 评审修补（V12）

本节各项保持原工具权限、审批与付费护栏。V12 新增 Skill 与提示词指引待 Claude V-Gate5b 审阅；D-047 对 V11 增补的既有审定不代替本轮新指引审阅。

### V.22.1 显式比例链（V12a，D-048）

- 唯一来源为 `RequirementBrief.aspect_ratio`（现有枚举或 null）。无明确值不新增目标、不重选模型、不修改既有尺寸默认。通过相同现有 ModelRegistry 能力与参数校验选择合法 size/ratio，不写提供商不接受的参数。
- 从交付输出沿真实媒体输入识别成片用途：compose 的片段、直接视频交付、图像交付、视频 first/last_frame，以及 select_image 的全部候选。仅这条成片链中的 compose 与对应 master 的 QC 继承 brief 目标；只作为 transform 参考的 compose/QC 保持其合法原目标。generate_image 的参考输入、r2v/transform 的参考素材不因被引用而自动成为成片关键帧。video brief 下，V.21.1 结构定妆种子（catalog 的 ref.image、n=1、preview、单对应角色）即使作为附属 image deliverable 交付仍豁免该附属用途；image brief 的直接图像交付不豁免。控制 depends_on 不证明用途；角色定妆另被兼作首/尾帧时帧用途优先，不能豁免。
- 受约束生成节点省略 size/ratio 时按选定模型 Schema 的 ratio 枚举、size 枚举/合法 preset 补齐；动态 image_size 无匹配 preset 时，以模型默认 size 像素面积为目标，在 Schema 面积/比例上下界内选择最接近的精确偶数尺寸，不默认降到最小画质。显式 size/ratio 与目标冲突返回阻塞 `PLAN_ASPECT_RATIO_MISMATCH`，带节点、字段、合法当前尺寸/比例和期望值；非法长文本/对象仅报告受限类型，不回显内容。模型不能表达目标返回 `PLAN_ASPECT_RATIO_UNSUPPORTED`。不自动裁剪用户附件、不改模型系列。
- i2v/首尾帧不能凭提示词证明比例。只有当前 Run 的实测图片尺寸或已验证上游 size/比例能作为证明；select_image 每个候选都要满足；末帧同样检查。缺证明返回 `PLAN_ASPECT_RATIO_UNKNOWN`。支持 ratio 的模型仍要求其首/尾帧兼容；不支持 ratio 的模型仅继承输入比例，不注入未知参数。
- `output_metadata` 的媒体几何为服务端派生信息：可含正整数 `width` / `height`、`aspect_ratio`（约分比例字符串或 null）；视频可含 `sample_aspect_ratio`（实测 SAR 或 null）。视频 aspect_ratio 表示显示比例，图片表示像素比例。已实测但显示几何不可信的来源可有 `geometry_unverified=true`，retain 与不能证明几何的 extract_frame 保留该阻塞依据；显式目标 compose/QC 在编译时即返回 `PLAN_ASPECT_RATIO_UNKNOWN`，避免批准注定失败的交付。未来生成节点的几何只是经模型参数验证的意图（预期方像素），不因尚未执行就标为不可信；已有素材必须实测，调用方不能把意图当作供应商实物验收。
- MediaProbe 只在输入 header 有 `displaymatrix:` 或 `rotate:` 证据时增加 `display_transform_unverified=true`；无证据时不增加该键、不改变既有探测形状。v3 显示几何对该标记返回 unknown，MASTER_ASPECT_RATIO 不得通过；显式目标 compose 必须在 stream-copy 选择前以 `INVALID_SOURCE` 拒绝。暂不实现旋转/翻转适配，此类片段需先规范化；无显式目标的经典路径保持原行为。
- 编译末端再次核对直接交付的图像/视频和包内 master 输出证明，覆盖直接保留片段和直接选择器输出，附属定妆豁免沿用上述规则。已有视频使用实测显示比例（像素尺寸乘 SAR）而非仅像素长宽比；SAR 缺失或非法时不构造已验证比例。已有竖片要交付横版时应显式通过目标 compose 留边适配；不得把直接保留的竖片视为横版。作为 compose 的输入片段/生成参考仍保留原比例，不暗中改源文件。extract_frame 的现有 PNG 输出未承诺非方像素归一，非 1:1 或未知 SAR 不向未来图片传播比例证明；可先 compose 归一或使用已生成并实测的图片。
- v3 `compose_video.inputs` 与 `qc_video.inputs` 增加可选 `target_aspect_ratio`（现有五值）和 `target_size`（正偶数 `width*height`，各边不超过 8192）。两个字段同时提供或同时省略；尺寸必须精确符合比例。缺省序列化不输出两个新键，保护旧任务载荷/审批哈希兼容。显式 brief 时编译器冻结目标；作者显式冲突阻塞。无用户比例时只允许两个目标一起显式提供、仍经 Schema 校验，不反推为用户需求。
- compose 仅在首段编译时可知的像素尺寸本身通过 `valid_target`（比例精确、偶数且边长合法）时继承该尺寸；只靠 SAR 使显示比例符合目标不算合法像素画布，例如 720×576 / SAR 64:45 不能直接冻结为 16:9 画布，应按默认 720 名义短边生成 1280×720。仅已知比例/名义分辨率时按名义短边生成最接近且不低于该短边的精确偶数尺寸；没有可验证尺寸信息时使用 720 名义短边。显式合法画布仍保留，QC 冻结该真实目标。实际提供商输出可能有像素舍入，编译元数据仅是意图；交付需以实际媒体 QC 为准。`target_size` 是拼接画布，不替代模型 resolution，不额外调用生成服务。
- compose 只有在全部源格式兼容且实际像素尺寸与目标相同时才 stream copy；否则按实测显示比例算偶数 fit 尺寸，在目标画布内留边、SAR=1，无裁剪。显式画布归一时若源 SAR 未知/非法，返回 `INVALID_SOURCE`，不按像素长宽比静默兜底或声称保形。原片不改；compress_output=false 仍不创建压缩副本，兼容性转码明确在 warnings 中说明，不宣称无损。
- QC 对最终成片的实测像素尺寸与显示比例（含 SAR）检查；有目标时新增 `MASTER_SIZE`、`MASTER_ASPECT_RATIO`，不符合返回 passed=false，沿既有 qc_failed 修复/用户门处理。不把 Mock 画质、角色相似度或提供商实际比例视为已验收。
- 上述字段必须同步到 `plan-review/resources/tools/{compose_video,qc_video}.json` 的真实 Schema 与作者说明。新草稿和 Patch 候选再编译沿用 brief 硬约束；已经批准的历史版本继续按原载荷和审批哈希执行/复用，不重新写入几何参数，不改变其历史审批。未批准的旧草稿若在再审核时有效输入变化，应生成新版本审核，不能静默批准。
- 混合评测的 LocalImageAdapter/LocalVideoAdapter 按实际提交载荷的合法 size、ratio、resolution 或本地首帧尺寸绘制；只产生本地标记素材、不访问 URL/上传服务，事件账本与提供商阻断规则不变。普通 MockAdapter 的既有哨兵字节约定保持不变；QC 不为评测跳过比例/尺寸检查。

### V.22.2 Research Run 绑定与错误修正（V12b，D-049）

1. fetch_page、download_reference、capture_reference_page 的输入 run_id 为 `str | null`，默认 null；模型可省略。服务器以可信 ToolContext.budget_scope 解析当前 Run；显式不同值返回 TOOL_FORBIDDEN，不回退到其他 Run。模型不能设置 ToolContext 字段。
2. 作用域存在性/所有权/授权验证成功后、创建或检查 ToolInvocation 前，将输入 run_id 规范化为当前 Run ID；账本输入与幂等比较均使用该规范值，省略与原显式同 Run 调用等价。旧 v2 恢复入口同样规范化，历史显式输入不改写。
3. URL 仍只能来自当前 Run 的原始用户文本或成功检索；capture 仅允许原始用户 URL。跨 Run、私网/重定向、无权角色、非活动/伪造委派、预算/次数与损坏快照继续按原契约拒绝。
4. `repair_guidance` 是服务器给出的有界结构帮助，可包含 `field`、`example_scope`、`example`、`rules`、`schema_resource`；进入 Agent 错误回执，不回显提交的敏感原值。research_needs 示例仅包含 query/reason 对象；dossier 示例只示范零证据的合法外壳，不伪造来源或候选，不自动写入或降低校验。
5. 测试需经真实 ToolRegistry 调用覆盖三工具省略成功、显式伪造拒绝、相同规范输入重放、v2 兼容、缓存/隔离/权限边界，以及 Schema/资源和错误示例可解析一致性；只用临时 SQLite、Mock/Stub 与网络阻断。

### V.22.3 最近资源合同保护（V12d，D-050）

- `context.policy_version=3`；对 `_completed_rounds` 认定完整的成功工具批次，若 read_skill_resource 输出有字符串 name/path/content，且 name/path 与调用参数精确一致，则按 (name,path) 记录最近位置。不同 Skill 同路径、同 Skill 不同路径独立。
- 每个键最近成功回执的 content 全文保留，不受最近两轮限制；只有被更新合法读取替代的旧回执可沿原规则投影。失败/不完整/不匹配/已投影或未解析的结果不建立新的成功位置，也不移除旧的有效保护。
- 最新 load_skill、最新持久计划证明、system/user、付费证据、澄清/错误及原有权限与信任边界保持；超软目标合法，不强删保护资料。
- 历史持久消息和收据不改。恢复同 step 继续使用原 pending_context / LLM ledger 冻结值，即便它是在 policy v2 创建；校验不通过仍停止，绝不重新收费规避漂移。
- 验收：唯一合同、多键合同、重复旧副本、后续失败/路径不匹配/不完整批次、最近两轮边界、不可变原文、既有冻结/恢复和计划投影；只 Mock/Stub。

### V.22.4 Plan 编译字段级诊断（V12e，D-051）

- PlanIssue 增加可选 details 对象，默认独立空字典；旧只有三字段的记录仍可读取。编译器仅在有诊断时序列化 details，原错误码、校验分支与接受路径不变。
- 节点诊断提供 node_id/tool、fields，以及由当前真实 ToolSpec 派生的 allowed_reference_inputs/allowed_input_fields；必要时提供 field_hints（from/to）及固定 hint。
- 新增 details 只提供字段位置与契约名字，不回显提示词、用户参数内容、密钥、完整路径或工件 ID；异常字段名有长度和字符界限。该承诺只限定新增 details，既有 issue.message 行为本轮不变。
- details 仅作纠错辅助，不执行归一化或自动改写，不接受 image/images/media 等别名，不自动搬运 params 至 inputs，不改变授权。
- allowed_reference_inputs 从当前 ToolSpec 的媒体类型输入派生；text/json 等普通字段不作为媒体引用建议。transform_video 的复合引用沿用 media[].artifact_id 与 source_artifact_id。
- animate_shot 的首帧、尾帧都是合法声明；是否启用首尾帧仍由既有模型和桥接策略校验。
- allowed_input_fields 排除通用服务端字段和选择门的 selected_artifact_id；选择结果仍仅由用户选择门写入。
- typed input 异常携带 inputs.<field>，节点顶层 params 异常位置仍为 params。已提供的安全 field 位置优先保留，不传播 current/expected 等附加值到公开诊断。
- 实现边界：新增 diagnostics.py；PlanIssue.details:dict 默认空；compiler.issue 接受可选details且仅有值时序列化；_typed_inputs 未声明引用异常 payload 带 field=inputs.<field>；node loop 每轮 spec=None 防前一工具Schema泄漏；节点异常catch调用 issue_details。不变规则：不增加接受路径。
- v3 check_plan、Patch 编译及可审核草稿沿用原 issues 传递；经典工具与 API 形状不变。

### V.22.5 最终草稿的意图评估（V12f，D-052）

- Director/plan-review：评估对象必须是本次最终候选，而不是 Repair 原提议。verdict=revise 时以 revised_draft 为准；approve/reject 以被审阅 draft 为准。reason、intent_preserved 和 changed_elements 必须针对同一候选。与原用户需求及已确认修订逐项对照：已在最终候选恢复的点名要求，不得继续沿用原提议中“删除/弱化该要求”的理由或变化项。若仍拿不准，保持 intent_preserved=false，说明最终候选尚不确定的具体内容；不要为自动通过把 false 改成 true。历史提议与旧审阅保留，不回写。
- repair_flow 指定审阅任务同步以上规则，不能仅改静态prompt。
- Patch卡片：保留patch.review.reason原值；加“审阅对象：最终草稿与原需求、已确认修订。”及理由标签“最终草稿审阅理由”。历史 applied 仍只读，不重新生成审阅文本。
- 不改变意图保真判定、人工门、不可变证据或已批准历史。原审阅文本保持原值；不在前端重写 reason 或猜测保真，保留现有组件结构、配色与报价授权路径。
- V11 Skill 增补审定标记按 D-047 更新并递增文档版本；V12 新增澄清单列待 Claude V-Gate5b 审阅，不把旧审定冒用到新文案。Blueprint 来源版本独立且不改。

## V.23 V-Gate5b 后续改进（V13）

### V.23.1 明确时长约束（V13a，D-055）

- RequirementBrief保留nullable target_duration_sec（1..600秒）；新增nullable duration_mode（approx/exact/at_most）、duration_source_text（非空，≤500字符）。duration_tolerance_sec支持有限非负浮点数（≤120）。新write_workspace有目标时必须提供mode/source，source须是run.request.text的原文子串，不能引用Agent补写的note；无目标时不得带mode/source。此校验证明出处，不代替语义理解。只有用户明确要求才填写目标，未指定就null；不按模型能力、片段数或故事自行补目标。图片无目标。
- mode=approx缺省容差max(3,target_duration_sec×0.125)，显式传入也须等于此默认值；exact/at_most容差为0。approx表示对称区间[max(0,target-tolerance),target+tolerance]，exact为单点，at_most为(0,target]。目标/容差拒绝bool、NaN、Infinity；比较只允许1e-6数值epsilon，不套旧QC的0.5秒/2%业务容差。不支持的用户区间/自定义容差先澄清，不擅自放宽。
- legacy读取：缺mode/source的旧brief继续接受原有target与duration_tolerance_sec，非空target按旧明确目标的对称容差处理；缺目标不产生约束。新字段为空时序列化省略，原有字段默认与旧工作区读取保持兼容。旧批准计划/收据不迁移、不重写。
- PlanDraft可带duration_constraint或省略；其结构为`{target_duration_sec:number,duration_tolerance_sec:number,mode:approx|exact|at_most}`，值有限、范围同brief，exact/at_most仅容差0。compiler从有效brief确定规范值；第一次编译注入，显式提供必须完全相等，冲突报PLAN_DURATION_CONSTRAINT_CONFLICT。无用户目标不能注入约束；Patch继承原根字段，不能删除/放宽。空值序列化不输出，不改变旧无约束Plan的形状。
- 原文出处保留在brief；Plan只冻结规范约束，进入审批、Patch与批准版本哈希。runtime.begin必须同时比较再编译的根约束与待审核版本；规则变化不能在仅比较nodes时绕过新审核。已存在批准receipt时只验证原approval_hash并恢复；后续执行、QC与结果批准不读最新brief。
- 交付时长由真实typed媒体输入链决定：生成/transform用验证后的完整输出秒数；retain=end-start；已有视频用实测；compose按有序video_artifact_ids逐项求和，重复片段每次计时，不能按节点集合或计费输入+输出秒数代替。无compose时按交付视频。只统计交付video及package主片，包内master与同源视频/压缩副本去重；多个独立视频聚合，中间参考compose不按全片目标校验。
- compiler的PLAN_DURATION_MISMATCH为阻塞，details包含current_duration_sec、target_duration_sec、duration_tolerance_sec、mode、minimum_duration_sec、maximum_duration_sec；消息含当前/目标/容差。不存在可验证交付时长时PLAN_DURATION_UNKNOWN；不得用goal/rationale补时长。check_plan、submit_plan、Patch重新编译走同一检查；原70秒与120秒目标结构必须拒绝，未给目标不追加该检查。
- 单一主片对应qc_video.inputs可冻结duration_constraint，缺省不序列化；与Plan目标冲突拒绝，中间参考QC不能继承全片目标。QC继续原解码/批准片段合计检查，再增加USER_TARGET_DURATION，检查实测master。多个独立主片由运行时聚合检查；不把总目标逐片重复应用。
- 进入awaiting_result_review前、approve_results时按批准Plan解析最终主片并聚合实测，直接视频无QC也覆盖。只信同Run有效工件、指纹及实际探测；失败不能进入success，沿PLAN_QC_FAILED/qc_failed进入attention或拒绝批准，不自动拉伸、裁剪、追加付费片段。旧批准Plan缺duration_constraint保持原行为。
- 验收仅Mock/Stub：120秒目标+7×10拒绝；无目标不变；approx边界/exact/at_most；来源缺失/伪造/无目标禁止猜测；生成、retain、transform、compose重复片段、master/package/压缩别名与多交付；QC实测不足/超出；根约束审批漂移、Patch、旧批准恢复；资源Schema同步。真实样本另按V-Gate6固定次数，绝不为单例调提示词或重新采样。

### V.23.2 无损计划规范化（V13b，D-056）

- check_plan、submit_plan和Patch编译共用规范化：有限JSON检查后、PlanDraft及身份校验前，仅忽略已知可执行非生成节点的characters: []。生成节点[]保留，其他声明和字段错误仍拒绝。
- compose/QC只给合法inputs.target_aspect_ratio、target_size省略或null时，按D-048继承同源合法画布，否则采用确定性720短边画布。brief比例优先；显式尺寸不覆盖；未知SAR、比例/宽高冲突与不成对的显式尺寸照旧阻断，执行Schema不放宽。
- 不接受videos、video_ids、ratio、size等别名，不从prompt/rationale推测身份、比例或数据路径，不改生成参数/模型/提示词/预算。
- 只改编译候选；原输入、workspace和旧receipt保持原样，新批准版本使用规范结果及哈希，重复编译稳定。已有批准版本按冻结receipt恢复，不重写历史。

### V.23.3 已被取代回执的请求投影（V13c，D-057）

- context.policy_version=4；原messages、ToolInvocation、workspace及已冻结pending_context不变，已有step/ledger恢复不重算。仅处理完整、连续且调用/回执一一配对的批次；解析、Schema或证明失败保留原文。
- 失败check指工具成功返回合法agent_check结构且issues非空，不含Registry/Schema/权限错误。plan_ref须精确合法；inline check(plan)须规范摘要唯一对应真实write/read/append保存证明；同key/version摘要冲突不得投影。输入仍受既有工作区JSON边界约束，合法大回执不误套工作区256KiB上限。
- 只有同workspace key更高版本在旧失败之后完成合法check（issues可仍非空）才取代旧失败；仅保存新稿、其他key、同版本重复检查或后续工具错误不算替代。只投影旧失败回执，assistant参数不因此改写。
- list_models仅压缩真实ListModelsInput规范参数完全相同的较旧合法ListModelsOutput；省略默认与null按Schema归一，不额外折叠family大小写。最新有效目录保留，后续坏回执不能替代它。
- 这两类已证明superseded回执可越过最近两轮保护，不依赖软字符目标触发，但仅在替换实际更短时投影。其余最新Skill资源、最新计划/读回、最近两轮及权限/硬约束保护沿用D-050。
- context_projection含policy_version、request_view_only、not_executable、原回执SHA256/字符数。旧check保留issue数量/码摘要、原精确WorkspaceRef、替代版本、免费read_workspace和check_plan入口；重check只提供当前规则诊断，不声称重现旧错误。目录保留规范过滤器、model_count与免费list_models入口；重读可变目录不是原历史快照。
- metrics新增compacted_check_result_count、compacted_catalog_result_count及对应indexes，总体索引去重；字符统计不证明真实token峰值。helper仅处理历史数据，不查询数据库、调用工具/LLM或改变预算。

### V.23.4 完整输入诊断、规划指引与只读统计（V13d，D-058）

- PlanDraft、PlanDraftNode、CheckInput根、AppendInput根、PatchDraft根在原解析前扫描已有dict/list/tuple/模型字段；结构键context_projection无论值是否有效均拒绝，422 / PLAN_CONTEXT_PROJECTION。普通字符串不匹配；无标记原对象返回，不额外拒绝原有类型化嵌套。迭代扫描循环安全，原工作区256KiB/64层有限JSON限制不变。
- 错误含固定说明、repair_guidance和最多3个去重read_workspace提示；条目精确{tool,arguments}，arguments精确{key,version}且通过WorkspaceRef，版本严格正整数、不能强制转换或含额外字段。不回显原标记任意元数据/路径/内容，不执行重读；地址存在性、Run归属与权限仍由Registry核验。无有效地址时要求定位已保存原稿，不猜缺失字段。
- compiler仅对专用错误保留安全message/details，其余错误沿用原通用说明；context_plans遇AppError/过深JSON保守保留。持久历史、冻结pending_context、旧批准内容与幂等收据不改。
- 固定事件须在镜头实际视频提示词中发生并达到完成状态，可跨连续镜头但明确完成位置；goal/rationale或“准备/打算/走向”不能代替要求动作。能力/预算不足退回Producer澄清，不删事件/改结局/推测目标时长。这是规划指引，不是实物剧情质量证明。时长文案与D-055一致，旧legacy读取兼容不变。
- Director文案版本V13，plan-review版本10，long-form-video版本4；仅旧V12f已由Claude V-Gate5b审定，新增V13a/d仍待Gate6审读。Blueprint来源版本不改。
- 统计CLI显式--profile V12|V13；work在系统TEMP对应前缀且精确marker。仅mode=ro、query_only=ON读取eval.db与real_call_audit.sqlite，不初始化app、读.env或联网；两个DB独立快照，worker停机后运行。默认readonly-statistics-v2，后续显式独立snapshot-name；已有输出拒绝覆盖。
- V12阈值维持150次文本/视觉、图片0、视频0、峰值60k；V13为120/6/0/80k。V13仅接受phase=planning及固定audit_label 01-c3-1:<run_id>、02-c3-2:<run_id>对应c3_story，03-c7:<run_id>对应c7_complete_story，各一次；身份04-identity同Run调用不并入初始规划。缺/错标签列诊断，不凭case猜测。
- 物理次数以calls行计，逻辑Registry拒绝另列；已知真实usage峰值超门槛即失败，不能被预算拒绝缺usage掩为未覆盖。演示credits按唯一(budget_scope,invocation_id)计一次；gate6_identity_review归视觉，generate_image依审计invocation映射真实/Mock，缺映射列未归因，不冒称实际货币账单。
- resumed_story_scope_and_origin_passed只在有效归档/覆盖证据成立时补充审核B通过，首次失败仍单列、保留源hash。planned_delivery_video_seconds为编译交付估计，generated_video_seconds独立；V12旧语义标明范围，不冒称实测或计费秒。
- 图片预留requested、POST、终态actual_images与下载分别报告；只读gate6_image_policy/images/downloads/violations/http_events、唯一gate6_identity_request及派生输入证据。缺失/未知/超产保留诊断。身份归档索引原图与展示副本路径/hash/尺寸，核对固定四图与专用qwen3.7-plus物理call_id/label；转换和执行权限另由V.23.5定义。计数/哈希证据不能代替视觉正文与人工身份判断，语义状态保持needs_review。

## V.23.5 V-Gate6 评测基础设施（D-059）

本节仅定义隔离评测接口，不属于产品公开 API；不向 Agent 暴露生成或评测工具。

### 固定阶段与隔离

- marker `v13-round.json`：`{"round":"V13-Gate6","call_limit":120,"real_image_limit":6,"real_video_limit":0,"media_mode":"identity_sample"}`。
- 阶段 `01-c3-1` / `02-c3-2` / `03-c7` / `04-identity`，前三归档 `phase=planning`、明确 `audit_label=<阶段>:<run_id>`；身份归档 `phase=identity_sample`。
- 独占锁与不可覆盖的 started/finished 文件；同轮固定提交、源码文件集合和全量验证。入口显式 `--execute`，身份额外 `--manifest` 与 `--approve-manifest-sha256`。没有自动重采或凭据文件读取。
- 120 为持久总额度；planning admission119，execution/complete 禁全部新 LLM，identity仅一次四图 Qwen。每次请求预留在传输前提交；失败不返还。图片最多6个单图预留，当前选择器仅原节点attempt1，不自动重试；视频0。

### 真实图选择 manifest

```json
{"run_id":"agent_...","plan_version":1,"plan_hash":"<64hex>","nodes":[
 {"node_id":"cast_a","kind":"cast","model":"wan2.6-image","node_hash":"<64hex>","n":1},
 {"node_id":"cast_b","kind":"cast","model":"wan2.6-image","node_hash":"<64hex>","n":1},
 {"node_id":"kf_a","kind":"keyframe","model":"qwen-image-3.0","node_hash":"<64hex>","n":1},
 {"node_id":"kf_b","kind":"keyframe","model":"qwen-image-3.0","node_hash":"<64hex>","n":1}]}
```

模型字段是原计划精确值，示例不授权替换。`plan_hash` / `node_hash` 均为 canonical JSON（排序键、紧凑分隔、UTF-8、禁止NaN）SHA256。严格两个单角色定妆preview、两个实际引用双方定妆的双人关键帧；两个关键帧不能是会被正常幂等复用的相同执行输入。只许可已审定老API、无上传的参考协议；不符合即停，不能修计划来凑样本。

### 持久审计

与旧 `calls/blocked/limits` 共用隔离 `real_call_audit.sqlite`，不修改旧表含义：

- `gate6_image_policy`：精确manifest及不可提高image_limit。
- `gate6_images`：attempt_key、选中node/model、request_hash、requested=1、retry_of、status、started/finished、response_hash、actual_images、request_id/provider_task_id、http_status/provider_usage、transport_started、实际inputs_hash/job_id/invocation_id、output_url_hash。
- `gate6_image_downloads`：reservation_id唯一、url_hash、sha256、bytes、completed_at，必须来自单图成功返回。
- `gate6_http_events`：kind（image_submit/poll/download）、reservation_id、url_hash、method、started/finished、status/http_status、response_hash/bytes。HTTP已返回后即保存，异常不能擦除；下载超限证据可为partial，status=unknown。
- `gate6_image_violations`：reservation_id/reason/at；超n等异常锁住后续请求。UNKNOWN不能转换成可重试的确定失败。
- `gate6_phase`：phase、identity_hashes（JSON数组，四个实际视觉副本哈希）；`gate6_identity_request`：单行call_id绑定旧calls。
- `gate6_identity_inputs`：单行records（JSON数组四项，顺序同manifest）。每项精确字段：`source_path/source_sha256/source_bytes/source_size` 与 `path/sha256/bytes/size/transform`。前者是原图，后者是展示副本；transform固定format=JPEG/max_edge=1024/quality=85/subsampling=2/optimize=false/resample=LANCZOS/alpha_background=#FFFFFF/crop=false/enhance=false，另记录exif_orientation_applied与pillow_version。

计数分开报告：预留图片单位、进入POST传输的尝试数、实际返回图数、已验证下载图数。失败/未知均不退款，原图过量返回如实记录。文本/视觉严格按物理calls与唯一逻辑invocation对账；媒体demo credits按唯一生成invocation，不把Mock费用当真实媒体账单。

### 私有视觉工具与归档

`gate6_identity_review` 输入仅 `{selection_hash:<64hex>}`；私有server持有四图映射，role=system/approved=true/caller_agent=None/budget_scope原Run，max_retries=0、agent_visible=false、非Plan节点。输入所有权/生成收据验证先于Registry；不存在重新调用的便捷重试路径。

输出包含四项 `comparisons`（character、keyframe_node、verdict=consistent/inconsistent/uncertain、visible_traits、differences）、limitations、usage。四项集合必须恰为两角色×两关键帧。一次调用同时传入四个固定展示副本，沿用实际token预留/结算，不能改预算/换模型或拆成逐图调用。

身份归档 `results/identity_04-identity_<run_id>.json`：round、phase、audit_label、run_id、manifest、budget_preflight、identity（selection_hash/images/display_inputs/tool_receipt/provider_response/path）、meter/images/ledger、review_b/tasks/actions、原图owned_images。`identity-provider-response.json`在适配器解析前独立保存完整原字节base64、响应hash/HTTP状态、完整正文/raw_response/finish_reason，格式错也留证。该归档与所有源图/副本均仅TEMP私有证据。

首个图片POST前预检原Run剩余可覆盖四图估价与512KiB×4副本上限推导的视觉预留，并用不可变 Plan.estimates.total_credits 检查完整计划（含四图、其余Mock）加视觉上界；两项覆盖不足均停止，明细保存在 identity-budget-preflight.json。实际副本超过上限停止，不改变转换。四图完成后先做视觉，再继续其余Mock；最终成片可停在结果审核，不能把抽检自动算作用户批准交付。固定展示副本的细节损失须在报告中说明，质量判断需结合原图人工复核。

启动器 gate6_launch 默认只校验正式已提交源码、完整回归与唯一工作目录，不读取凭证或执行子进程。显式 --execute 后只提取 DASHSCOPE_API_KEY 白名单行进入子进程环境；禁止解释数据库/Redis配置、不输出或保存凭证，实际执行入口继续禁dotenv。

身份Run必须属于三个固定规划归档之一，且 round、phase、case、audit_label、run_id 与审核状态逐项匹配；优先最早合格c3，均不合格可用固定c7。至少一个c3进入审核仍是独立验收目标，不因c7抽检成功而算通过。

### V.23.6 实测时长技术余量（V13e，D-060）

- 编译期V.23.1保持严格：用户容差和Plan.duration_constraint不变；不向Schema增加可由Agent调节的测量容差。exact/at_most编译只保留1e-6数值误差。
- 运行期QC和交付结果检查使用E=max(0.5秒, Σ(n_i/fps_i))，只在原批准用户上下界之外加入E。实测必须正有限，边界比较仍保留1e-6；approx亦适用，技术余量不冒充用户同意的容差。
- n_i来自批准最终compose的video_artifact_ids列表长度（重复出现计数；嵌套compose是一个输入片段），直接视频/retain/transform/既有主片为1。不数依赖节点或QC自填来源列表。多个独立最终主片求和，package与compressed别名复用原去重，整体仅一个0.5秒基线。
- fps_i只取该成片本次decode=True文件探测，缺失/无效不贡献帧增量且计入未知FPS片段数；不使用计划、缓存或默认帧率。文件FPS不是CFR间隔证明。无合法片段数或非有限计算拒绝。
- 检查详情保留原current/target/duration_tolerance/mode/minimum/maximum，另外给出measurement_error_sec、measurement_frame_allowance_sec、measurement_segment_count、measurement_unknown_fps_segments、effective_minimum_duration_sec、effective_maximum_duration_sec及passed。QC检查中details沿用同一详情；不改冻结Plan/批准hash/历史回执。归属、输出指纹前后复核及原结构QC保持。
- 仅离线覆盖，Gate6 Mock视频不能验证真实帧偏差。应单独报告此限制。
- v3视频输出登记的旧+0.05秒技术上限同步使用同一E；compose片段数取服务端冻结解析的task.inputs，其他输出1。按完整解码时长比较批准输出秒数，前后指纹一致才登记；不改变费用、参数或下游引用时长限制。v3专用QcOutput.checks支持可选details，缺失时不序列化，经典QC不变。

## V.24 简单任务降耗与结果稳定性（D-062，Claude）

### V.24.1 内联提交计划

- `submit_plan` 输入为 `{plan_ref:WorkspaceRef}` 或 `{plan:PlanDraft}`，严格有且仅有一个非 null 值（与 check_plan 相同）。仍只有 Producer 可调用。
- 内联 plan 先按 write_workspace 的同一校验与来源规则保存为工作区 key=`draft`、kind=plan_draft 的新版本（请求键沿用本次工具调用，重放返回同一版本），再走原有编译、dry-run 与原子提交；未通过时返回 issues 且不提交，草稿保留可继续修订。输出与 delegation.output 的 plan_ref 为保存后的 `{key:"draft",version}`。
- 导出给 Agent 的函数 Schema 中 `plan` 只声明为 object 并引用 check_plan 的结构，避免重复导出完整 PlanDraft Schema；服务端校验仍使用完整 PlanDraft。
- 同一轮先 write_workspace(brief) 再 submit_plan({plan}) 合法：工具按顺序执行，submit 成功后本委派结束、后续调用取消。

### V.24.2 模型偏好的选择器解析与适用范围

- brief 中的偏好/排除保留用户原文；匹配时从原文中提取已注册模型 ID、显示名或系列名（最长匹配优先，`wan2.7` 不匹配 `wan2.70`）。原文中没有任何已注册名称时按原值匹配并照旧失败，不猜测。`constraints_for_mode` 返回值仍为原文。
- 偏好原文中的范围词优先：含“视频”（如“wan2.7系列视频模型”“图生视频”）只约束视频节点，含“图片/图像/生图”只约束图片节点。没有范围词时，一个模型或系列约束其实际拥有模型的生成类型：系列同时含图片与视频模型时（如 wan2.7）同时约束图片与视频节点；单个视频模型只约束视频，单个图片模型只约束图片。无匹配的值归入视频侧并显式失败。deliverable=image 时规则不变。

### V.24.3 Agent 计划图片节点的提供方载荷

- agent_plan 与 agent_plan_preview 作业中 adapter 为 dashscope_image 的提交，提供方载荷使用 `enable_interleave=true` 并设 `max_images=n`（wan2.6-image 文生图只在交错模式下工作，该模式忽略 n、默认最多 5 张；关闭交错为图像编辑模式，必须输入图片）。同步执行与 MQ 提交消费者一致。审批绑定的 params、任务 inputs、费用与校验不变；经典工作流不变。运行期输出张数检查保持。

### V.24.4 未声明 SAR 的视频

- 媒体探测在视频流未声明 SAR 时记录 `sar="1:1"`、`sar_source="unspecified"`（与 FFmpeg 的显示与缩放语义一致）；显式非方形 SAR 照旧参与几何计算。拼接、显示比例与 QC 因此接受真实服务商输出（wan2.7 不带 SAR）。Mock 拼接素材不再显式 setsar，与真实输出形态一致。

### V.24.5 模型参数错误诊断

- 模型参数校验错误的 payload 增加 `allowed_params`（该模型参数 Schema 的名称列表）；计划 issue 的 details 相应给出 `fields`（如 `params.aspect_ratio`）与 `allowed_params`。只改诊断信息，不改校验规则、不接受别名。

### V.24.6 提示词写作标准与 Producer 速通

- t2v / i2v / t2i-prompt-writing Skill（version 2）为提示词质量标准，提炼自经典工作流系统提示词；Producer、Director 系统提示词包含要点，Producer 含简单任务速通与可编译示例。Agent 系统提示词长度上限由 12000 调整为 14000 字符。
- 多镜头短片默认 compose 成一个成片交付，各镜头首帧对应本镜头画面（Director 指引）。这些是规划指引，不是生成质量保证。

### V.24.7 v3 运行指标（D-064）

- `GET /api/agent/runs/<run_id>/metrics` 对 v3 Run 在原结果上增加 `v3`：planning（llm_rounds、input/output_tokens、peak_input_tokens、usage_missing、credits、questions、agents、reached_plan、seconds_to_first_plan）、execution（plan_version、node_status、failed_node_codes、media_credits、run_error_code）、patches（total、by_status、auto_applied、manual_applied）、alerts（PEAK_INPUT_OVER_80K / ATTENTION / NODE_FAILED）。
- `GET /api/agent/metrics/v3?days=N`（1–90，默认 7）只统计当前用户的 v3 Run：数量与状态分布、reached_plan_rate、asked_rate、各项中位数、峰值超 80k 的 Run 数、attention 原因、媒体费用与补丁计数。只读；credits 为演示估价。
- 规划路线：画面有必须全程稳定出现的主体时单镜头也用首帧 + i2v，纯风景/空镜才用 t2v（Producer 指引与 t2v-prompt-writing v3）。

## V.25 经典路径：在系列与模板下运行工作流（D-066，Claude）

只在用户明确表达生产意图（反推提示词、测试提示词、用于生产并保留提示词、放到某模板下）时使用；其余仍走 v3 私有计划。经典工作流（19 节点 DAG、经典 API 与页面）不变，只经 `JobService.create_job` / `JobRunService` 调用。

### V.25.1 只读工具 `list_templates`

- Agent 可见（producer、creative、director、research、prompt_smith、critic、repair、system），权限 read，无费用。
- 输入：`series_id?`、`query?`（名称/描述子串，≤80 字）。输出：`series[]`，每项 `{series_id, name, description, templates[]}`；模板项 `{template_id, name, description, prompt_types: {类型: {version, preview}}}`，preview 为该类型当前激活模板提示词的前 120 字。最多返回 50 个模板。
- 不列出 Agent 内部系列 `agent_studio` 及其模板 `agent_workspace`。

### V.25.2 计划节点 `run_workflow_template`

计划可执行、需审批、按启用分支计费；不暴露给 Agent 直接调用（D-029）。含此节点的计划称“经典路径计划”：计划只能有这一个节点，交付物只能引用它，不允许 `duration_constraint`，补丁不适用（需要修改时重新提交计划）。节点的 `model_id` 必须为空、`params` 必须为空；模型写在 inputs 中。

inputs：

| 字段 | 类型 | 说明 |
|---|---|---|
| `template_target` | object | 二选一：`{"template_id"}`（已有模板）或 `{"series_id", "new_template_name"}`（在已有系列下新建，名称 1–80 字、系列内不重名）。不得指向 `agent_studio` / `agent_workspace`。 |
| `branches` | list | 1–8 个且不重复，取值：`reverse_prompts`、`rewrite_prompts`、`r2v_prompt`、`t2v`、`first_frame_image`、`i2v`、`r2v`、`i2i_test`，分别对应经典节点 reverse_prompts、rewrite_prompts、reverse_prompts4r2v、t2v、首帧、i2v、r2v_flash、I2I Test 分支。 |
| `source_video_artifact_id` | video | 启用 `reverse_prompts` 时必填。 |
| `first_frame_artifact_id` | image | 启用 `i2v` 而未启用 `first_frame_image` 时必填。 |
| `reference_artifact_ids` | image[] | 启用 `r2v` 时必填（1–4 张）。 |
| `prompts` | object | 可选初始提示词：`t2v`、`first_frame_image`、`i2v`、`r2v_flash`、`i2i`（各 ≤8000 字）。 |
| `i2i_test` | object | 启用 `i2i_test` 时必填：`{mode: single_male|single_female|couple, test_count: 1–8}`。 |
| `models` / `model_params` | object | 可选，按槽位 `t2v`、`image`、`i2v`、`r2v`、`i2i_image`、`i2i_video` 指定模型与参数；未指定时编译器按需求简报的模型偏好与默认模型补全并冻结；文本/理解节点（reverse_prompts、rewrite_prompts、reverse_prompts4r2v、rewrite_t2i_to_i2i）以节点键为槽位，只由编译器按经典配置模型冻结，作者不得改写。 |
| `package` | bool | 默认 true：作业结束后生成经典 ZIP 包（final/、assets/、prompts/、manifest）。经典打包以视频为主体，只有启用视频分支（t2v、i2v、r2v、i2i_test）时有效，否则编译器置为 false。 |

- 依赖规则由经典 `WorkflowValidator` 判定（例如 `rewrite_prompts` 需要 t2v 提示词：来自 `reverse_prompts` 或 `prompts.t2v`；I2I Test 还需要 i2v 提示词）；编译期即报 `WORKFLOW_DEPENDENCY_MISSING`。不得同时提供已启用分支会生成的提示词（`WORKFLOW_PROMPT_CONFLICT`），例外：提供 `prompts.i2i` 时跳过 rewrite_t2i_to_i2i，按原文测试。未被启用分支使用的输入报 `WORKFLOW_INPUT_UNUSED`。
- 需求简报的比例与时长不生成计划时长约束，而是作为各生成槽位参数的默认值（比例经 aspect 规则写入 ratio/size，时长写入视频槽位 duration）；作者显式参数优先，冲突时报错。
- 报价：各生成槽位单价 × 次数（I2I 槽位 × test_count）+ 文本/理解节点的经典估价；`output_video_seconds` 为各视频分支时长之和。
- outputs：`job_id`(json)、`template`(json：template_id、name、series_id、created)、`prompts`(json：类型 → {prompt_id, version, content})、`videos`(video[])、`images`(image[])、`package`(package)。未启用相应分支时 `videos`/`images` 为空、`package` 为 null，其余分支的产出缺失即判失败。
- 交付物：`video`→`videos`、`image`→`images`、`package`→`package`；新增交付类型 `prompts`→`prompts`（只出提示词的任务用它交付）。

### V.25.3 模板写入授权

- 编译结果与计划版本的 check 增加 `template_writes[]`：`{node_id, mode: existing|new, series_id, series_name, template_id?, template_name, prompt_types[]}`，计划卡据此显示“将在 系列 X / 模板 Y 下创建作业，并把提示词新版本写回模板”。
- `approve_plan` 动作新增可选字段 `confirm_template_write: true`；计划含 `template_writes` 而未确认时拒绝（`TEMPLATE_WRITE_CONFIRMATION_REQUIRED`，422）。不含写入的计划可省略该字段（缺省值不进入回执哈希，旧回执不变）。
- 新模板在批准后、节点执行时才创建（模板 ID 由 run_id 与 node_id 确定性派生，重试复用）；提示词只经经典 PromptSync 追加版本（append-only，可回滚），不修改模板配置。

### V.25.4 执行绑定

- 作业 `config.agent_workflow = {branches, test_count}`，`node_models` / `node_model_params` 为冻结的全部槽位；作业快照只绑定初始提示词引用与初始素材，作业内 LLM 节点生成的提示词不在审批范围内（经典路径的固有特性，计划卡明示）。
- 经典路径作业内的经典文本节点保留经典适配器的 JSON 模式降级（json_schema → json_object → 不带格式，最多 2 次额外文本调用），即使运行在 Agent/MQ worker 中；Agent 规划调用仍不做隐式重试。
- 每次服务商提交校验：操作在冻结映射内、模型与参数一致、源素材指纹不变、初始提示词未变、单次价格不高于绑定时的单价；计划须为当前版本且处于执行状态。
- 经典路径作业不再按 Agent 私有作业处理（`is_private_agent_job` 为假）：提示词经 PromptSync 写回模板，作业与产物在经典页面可见，模板打包可用；经典页面的手动重跑仍被计划派发许可拒绝。
- 公开计划视图增加 `template_writes`；该节点的 `workflow` 投影给出 job_id、template、package 与各类型提示词（版本与正文前 4000 字）。结果卡给出经典作业详情链接 `/jobs/<job_id>`。

### V.25.5 Skill 与路由

- `production-workflow` Skill（producer）给出触发规则、三种任务的分支映射与三个可编译示例；Producer 路由第 5 条：生产意图明确时加载该 Skill，拿不准时用 ask_user 选择题确认，不默认走经典路径。
- plan-review 资源新增 `resources/tools/run_workflow_template.json`；`plan_draft.schema.json` 的交付类型增加 prompts。
