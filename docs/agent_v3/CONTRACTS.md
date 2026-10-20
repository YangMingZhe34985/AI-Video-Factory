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
- 原 state.messages、账本和工作区原文不删改；只生成模型请求视图，不改变 assistant tool_calls 的参数、顺序和调用/回复配对。
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
