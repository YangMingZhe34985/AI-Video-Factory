# CineCrew Agent v3 重构方案：真正的多 Agent 规划 + 受控执行

> 作者：Claude｜日期：2026-10-18｜状态：**r3，已确认**（D-029 – D-031；契约见 `docs/agent_v3/CONTRACTS.md`）
> r3 修订：用户确认总体方案；真实测试范围（D-030）、分工（D-031）、经典路径定位与排期（§3.2、V8）。
> r2 修订（按用户意见）：执行期失败由 Agent 诊断并提交局部 Plan Patch（§4.1）；委派按需、不以 Agent 数量为目标（§2.5）；Plan IR 改为“开放但受约束”并给出稳定性保证（§3.1）；v2 配方与经典工作流路径改为可被 Agent 选用的 Blueprint（§3.2）。
> 前置阅读：`docs/private/CineCrew_Agent_Technical_Report_2026-10-18.md`（v2 现状）、`docs/architecture/项目重构说明书.md`（最初目标）

---

## 0. 结论先行

1. **v2 的问题出在设计上，不在实现上。** v2 方案规定“LLM 只产出结构化决策，不直接调工具”，并且用 `recipe_hint` 选择五条写死的分支（`graph_v2.py:220`）。这让每个“Agent”都只是一次结构化调用，整个系统是多角色 LLM 编排的工作流。最初的说明书要的是“Agent 自主规划、调用 Skill、协调执行”，v2 偏离了它。
2. **v3 的核心改变：规划阶段交给真正的 Agent，执行阶段保持确定。**
   - 规划阶段：多个 Agent 各自运行“思考→调用工具/加载 Skill→观察→再决定”的循环；它们查询 Agent 目录、相互委派、协商，自行组合 Skill 完成需求。**不再有写死的任务类型**。
   - 执行阶段：Agent 最终产出一份**可执行计划（Plan IR，任意的工具调用 DAG）**，代码负责校验并报价，用户批准后由确定性的运行时执行。付费生成不会被 Agent 自由探索。
3. **严格区分三个概念：**
   - **Tool**：原子、确定、有 Schema 的能力，通过函数调用交给 LLM 使用；
   - **Skill**：`SKILL.md` 加资源组成的“方法知识包”，告诉 Agent 何时、如何组合哪些 Tool；
   - **Agent**：有自己的系统提示词、工具集、可用 Skill、预算与步数上限的 LLM 循环，可以委派其他 Agent。
4. **典型任务不再写成代码路由**，而是变成 Skill（例如 `long-form-video`）和 Agent 系统提示词里的示例。新的任务形态通过新增 Skill 支持，不需要改图。
5. **v2 的护栏原样保留**：ToolRegistry 校验、账本、幂等、预算、审批、报价、局部修复、交付、MQ。这些正是让 Agent 安全地自主行动的前提，v3 在它们之上换掉编排层。

---

## 1. 三个概念的边界

| | Tool | Skill | Agent |
|---|---|---|---|
| 本质 | 一个函数：输入 Schema → 输出 Schema | 一份方法论：`SKILL.md` + 模板/示例/辅助脚本 | 一个会思考、会用工具、会委派的 LLM 循环 |
| 谁执行 | Registry 执行 handler（代码） | 加载它的 Agent 按说明去做（在该 Agent 的上下文里） | 运行时驱动循环，LLM 决策 |
| 是否有判断 | 无，确定性 | 无执行能力，提供判断依据 | 有 |
| 例子 | `analyze_image`、`web_search`、`estimate_cost`、`check_plan`、`generate_image`、`animate_shot` | `long-form-video`、`i2v-prompt-writing`、`character-consistency`、`wan3-extend` | Producer、Director、Creative、Research、Prompt Smith、Critic |
| 怎么被发现 | 每个 Agent 的工具清单（函数调用 schema） | Skill 索引（名称 + 一句描述）常驻上下文；需要时调用 `load_skill(name)` 读全文 | Agent 目录（Agent Card），调用 `list_agents` / `delegate` |

“Skill 比 Tool 强”的准确含义是：Skill 封装的是**怎么做**的经验（选哪种生成方式、提示词怎么写、参数有什么坑、典型失败如何规避），它会指导 Agent 组合多个 Tool；Tool 只负责**做**一件事。

### 1.1 目录调整

```
backend/app/tools/            ← 现 backend/app/skills/ 整体更名（ToolSpec、Registry、budget、permissions）
backend/app/tools/specs/      ← 现 skills/tools/*.py
backend/skills/<skill-name>/  ← 新：Skill 库（与代码分离，可由运营者增改）
    SKILL.md
    templates/  examples/  scripts/（可选，scripts 必须登记为 Tool 才能被调用）
backend/app/agents/           ← 新：Agent 定义、运行时、目录、工作区
```

为了兼容，`app.skills` 保留一个 re-export 垫片，经典工作流和旧测试不受影响。

### 1.2 SKILL.md 格式

```markdown
---
name: long-form-video
description: 制作 30 秒以上的多镜头视频时，如何选择生成方式、拆分镜头并保持角色一致
when_to_use: 目标时长超过单个视频模型上限，或需要多个镜头/场景
agents: [director]                     # 推荐使用者（不是强制）
tools: [estimate_cost, check_plan, list_models]   # 这份方法依赖的工具
related: [character-consistency, i2v-prompt-writing, first-last-frame]
version: 1
---
## 推荐策略
- 优先“首帧 → 图生视频”，每镜头首帧由 i2i 引用角色参考图生成；文生视频在长片中角色漂移严重，只用于空镜……
- 同场景连续动作用“尾帧承接”（串行），换场景独立生成（可并行）……
## 拆镜规则
- 按所选模型的时长范围与步长拆分；总时长容差 ±10%……
## 常见失败
- ……
## 计划片段示例
（一段 Plan IR 示例）
```

**初始 Skill 库**大多从 v2 现有的提示词和规则整理而来，例如 Director-lite、Director v2、Prompt Smith、Research 的 INSTRUCTION，以及 Plan Check 的规则：

| Skill | 主要内容 | 来源 |
|---|---|---|
| `intent-analysis` | 如何从一句话 + 附件判断交付物、时长、主体、约束、是否需检索/澄清 | intake.py INSTRUCTION |
| `clarification` | 何时问、问几个、怎么出选择题 | clarify.py、A.7 |
| `image-edit-portrait` | 人像改图：i2i、身份锁定、参数 | director_lite |
| `t2i-prompt-writing` / `i2v-prompt-writing` / `t2v-prompt-writing` | 各类提示词写法（静态/动态分离、身份锁定句……） | prompt_smith、director_lite |
| `long-form-video` | 长片策略、拆镜、衔接、并行/串行 | director_v2、plan_check |
| `character-consistency` | 角色锁定描述、参考图来源（检索/附件/定妆）、每镜头引用 | creative_v2、D-014 |
| `first-last-frame` | 首尾帧候选方式的适用场景与限制（默认关闭、质量未验证） | D-005 |
| `video-remix` | 保留/替换原片区间 | remix |
| `wan3-transform` | 参考/编辑/延长，I+G 计费与限制 | W 章 |
| `web-research` | 检索、选图、来源可信度、注入防护 | research.py BOUNDARY |
| `budget-planning` | 如何在预算内取舍（降分辨率、缩短、减少镜头），何时向用户报方案 | A.5、C.10 |
| `storyboard-review` | Critic 用：对照需求逐条检查计划 | plan_check、C-Gate 经验 |

Skill 的质量直接决定 Agent 的效果，所以 Skill 也要有测试：校验 frontmatter，检查引用的工具是否存在，并跑评测集（§8）。

---

## 2. Agent 设计

### 2.1 角色目录（Agent Card）

每个 Agent 都有一张卡片，存放在 `backend/app/agents/cards/*.yaml`，供其他 Agent 查询：

```yaml
name: director
description: 决定“怎么拍”——选择生成方式、拆分镜头/步骤、选模型、组织可执行计划与费用
accepts: {brief: RequirementBrief, story?: StoryPackage, research?: Dossier}
returns: PlanDraft
tools: [list_models, list_skills, load_skill, estimate_cost, check_plan, analyze_image,
        request_preview, delegate, ask_user, read_workspace, write_workspace]
can_delegate_to: [creative, research, prompt_smith, critic]
limits: {max_steps: 40, max_llm_calls: 30, planning_credits: 20, max_delegation_depth: 2}
model_role: director          # 沿用 AGENT_<ROLE>_MODEL 回退链
```

| Agent | 职责 | 典型工具 | 可委派 |
|---|---|---|---|
| **Producer**（需求理解与总协调，唯一面向用户） | 理解意图、追问、选择合作 Agent、整合结果、向用户呈现计划 | `analyze_image`、`analyze_video`、`list_agents`、`delegate`、`ask_user`、`submit_plan` | 全部 |
| **Research** | 资料与参考形象 | `web_search`、`image_search`、`fetch_page`、`download_reference`、`analyze_image` | — |
| **Creative** | 故事、角色设定、风格；不管技术 | `load_skill`、读写工作区 | research |
| **Director** | 技术路线、拆镜、选型、费用、组织计划 | 见上 | creative、research、prompt_smith、critic |
| **Prompt Smith** | 为计划节点写提示词；可并行多实例 | `load_skill`、`list_models` | — |
| **Critic**（新增） | 把计划提交给用户前，对照需求、Skill 与校验结果自查 | `check_plan`、`analyze_image`（看预览）、`estimate_cost` | — |
| Repair（按需启动） | 执行期出现可修复失败时提出修复方案 | `classify_failure`、`quote_repair` | — |

**不是 Agent 的部分**（明确叫“服务”）：计划编译与校验、执行运行时（生产调度）、Editor（拼接/质检/打包）、MQ。

### 2.2 Agent 运行时

```text
AgentLoop(agent, task, context_refs):
  messages = [system(agent.prompt + skill_index + agent_directory), user(task + refs)]
  repeat until final_answer | limits:
    resp = llm.chat(messages, tools=agent.tool_schemas)        # 原生函数调用
    for call in resp.tool_calls:
        result = ToolRegistry.invoke(call.name, call.args, ctx(agent, run, delegation))
        # load_skill / delegate / ask_user 也是工具，统一走 Registry
        messages += tool_result(result)                       # 外部内容标记为不可信数据
  return final_answer (经 Pydantic 校验的输出契约)
```

- **必须使用原生函数调用**。DashScope 兼容接口和 DeepSeek 都支持 `tools`；Mock 模式用“剧本式”假 LLM 回放预设的调用序列（§8）。
- **每一次工具调用仍然经过 `ToolRegistry.invoke()`**：Schema、角色、审批、预算、幂等、账本。LLM 只能**请求**调用，能不能执行由代码决定。这一点和 v2 相同；变化的是 LLM 可以自己决定调用哪个、调用几次、按什么顺序。
- **上限**：每次委派单独计算步数、LLM 调用次数和规划 credits，超限即停止并返回部分结果；运行时检测重复调用循环；委派深度不超过 2。
- **持久化**：每个 AgentLoop 是一个 LangGraph 子图，每一步都写 checkpoint。worker 重启后从最后一步继续；已完成的工具调用靠账本回放，不会重复执行。
- **可观测性**：每一步写入 `agent_steps` 表，包括 Agent、思考摘要、工具调用、结果引用、耗时与费用。前端提供“协作时间线”，展示谁委派了谁、调用了什么、为什么。

### 2.3 Agent 之间怎么交互

- **委派**：`delegate(agent, task, context_refs, expected_output)` 是一个工具。运行时启动目标 Agent 的循环，结束后把结果作为工具返回值交给委派方。被委派方可以继续委派（受深度限制），也可以**退回**并说明原因，例如 Creative 告诉 Director“2 分钟装不下这么多情节，建议删掉一条支线”。真正的协商发生在这里。
- **共享工作区（Blackboard）**：需求简报、资料、故事圣经、计划草稿、预览图都按引用存放在 Run 工作区（`agent_workspace_items` 表 + 工件），并带版本。委派时只传引用，避免把超长上下文来回复制。
- **只有 Producer 面向用户**：其他 Agent 调用 `ask_user` 时，问题先交给 Producer 合并、去重，再统一发给用户（复用 A5 的澄清卡片与轮数上限），避免多个 Agent 轮番提问。
- **拓扑**：以“监督者 + 委派”为主，允许同级之间直接委派（例如 Director 直接找 Creative 改稿）。运行时只限制“谁能委派谁”和资源上限，**不预设调用顺序**。

### 2.4 典型任务如何落地：写进 Skill 和提示词，不写进代码

v2 的五类任务在 v3 中**一个代码分支都没有**。下面是“做 2–3 分钟 AI 拟人故事”的一次**示意轨迹**（具体顺序由 Agent 自行决定）：

```text
Producer：分析需求 → 视频，120–180 秒，拟人角色，二创 → 判断这是长片 → list_agents
  → delegate(director, brief)
Director：list_skills → 看到 long-form-video、first-last-frame、t2v-prompt-writing……
  → load_skill(long-form-video)：长片优先“首帧→图生视频”，文生视频角色易漂移
  → list_models(i2v)：确认时长上限 → 估算约 10 个镜头
  → delegate(creative, "写 150 秒、约 8 个节拍的故事和角色设定")
      Creative：需要知道“ChatGPT 拟人形象”长什么样 → delegate(research, ...)
      Creative：返回故事圣经 + 角色卡（参考图来自检索）
  → load_skill(character-consistency) → 组织计划：定妆/关键帧/视频节点、衔接方式
  → delegate(prompt_smith × N, 各镜头) 并行写提示词
  → check_plan / estimate_cost → 超预算 → load_skill(budget-planning) → 给出 A/B 两个方案
  → delegate(critic, plan) → 指出 s05 与 s06 角色服装不一致 → 修正
  → 返回 PlanDraft
Producer：ask_user(预算方案 A/B) → submit_plan → 进入审核
```

“把我的照片改成证件照”也是同一套机制：Producer 判断任务简单，**自己**加载 `image-edit-portrait`（或直接实例化 Blueprint，§3.2），产出只有一个 i2i 节点的计划，不委派任何 Agent。**流程长短由 Agent 判断，不由代码分支决定。**

### 2.5 委派策略：按需，不以 Agent 数量为目标

开发目标是**任务质量、费用和耗时**，不是 Agent 数量或委派次数。

- **Producer 和 Director 都能直接产出计划**。Producer 自己能完成的任务（单图改图、证件照、单段短视频）就不委派；只有需要专门上下文（故事创作、资料检索、多镜头技术路线）时才委派。
- **委派的判断依据**写在 Producer 的系统提示词和 `delegation-policy` Skill 里：
  - 任务复杂度：镜头数、时长、是否有剧情；
  - 是否需要专门上下文：外部资料、角色设定、技术选型；
  - 委派成本：委派一次通常意味着多轮 LLM 调用。
- **Critic 有条件触发**：只在高风险计划上运行，例如含视频节点、费用超过阈值、节点数多，或计划属于“实验性组合”（§3.1）。由 Producer 或 Director 判断，代码只提供默认阈值建议。
- **评测会惩罚不必要的协作**（§8）：简单任务如果发生委派、提问或调用 Critic，记为扣分项。
- 剧本式测试同时覆盖“应该委派”和“不应该委派”两类用例。

---

## 3. 可执行计划（Plan IR）：Agent 和确定性执行之间的契约

这是去掉写死配方之后**唯一的硬约束**：规划无论怎么自由，最终都必须落成一份代码能校验、能报价、能执行的 DAG。准确地说，Plan IR 是**开放但受约束的 DAG**，不是“任意工具调用”（见 §3.1）。

```text
ExecutionPlan
  plan_version, goal, deliverables: [{kind: image|video|package, from: node_id}]
  nodes: [
    { id: "kf_s01", tool: "generate_image",
      inputs: {mode: "i2i", prompt: "...", reference_ids: [{ref: "char_c01.output.artifact_id"}]},
      model_id, params, stage: "keyframes",
      gate: "preview" | null,            # 生成后先给用户看
      produced_by: {agent: "director", skills: ["character-consistency"]}, rationale }
    { id: "vid_s01", tool: "animate_shot", inputs: {first_frame: {ref: "kf_s01.output.artifact_id"}, ...} }
    { id: "tail_s01", tool: "extract_frame", inputs: {video: {ref: "vid_s01.output.artifact_id"}} }
    { id: "final", tool: "compose_video", inputs: {videos: [{ref: ...}, ...]} }
  ]
  estimates (由代码计算)
```

- **计划编译器（代码）**：检查工具是否允许出现在计划中、输入是否符合 Schema、引用的类型和来源是否匹配、模型能力与时长步长、DAG 是否无环、各类上限和预算，并计算报价。它是 v2 Plan Check 的通用化版本，问题按节点返回，计划保持可编辑。编译器也作为 `check_plan` 工具交给 Director 和 Critic，让 Agent 在循环里自己修正。
- **审核门**：所有付费节点都必须经过用户批准计划；`gate: "preview"` 让 Agent 在昂贵节点之前插入“先看图”的检查点，这是审核 A 的通用化版本。Agent 可以决定在哪里插门，但代码有底线：视频节点之前必须有计划批准。
- **执行运行时**：在 `production_engine` 基础上通用化，按 DAG 的拓扑顺序和并发上限执行节点，复用节点级幂等、失败分类、免费恢复、报价重做、级联范围（DAG 后代闭包）。Story v2 的镜头任务表扩展为 `plan_node_tasks`。
- **界面**：审核页从“分镜板专用”改为**按 stage 分组的通用计划视图**；分镜板保留，作为 `stage = keyframes/shots` 的专用渲染。

### 3.1 稳定性：哪些能保证，哪些不能

稳定性分成两层，结论不同：

**（1）执行稳定性：可以保证，达到 v2 同等水平。** 计划里的每个节点都是现有工具，执行仍走同样的 Job / MQ / 幂等 / 恢复链路。DAG 的组合方式不会让单个节点的执行更不稳定。具体约束如下：

| 约束 | 作用 |
|---|---|
| **节点词表封闭**：只有标记为 `plan_executable` 的工具能进计划（约 12 个：生成图片、首帧生视频、首尾帧、变换、提帧、拼接、打包、经典模板作业等） | 运行时不会遇到没实现过的节点 |
| **类型化数据流**：每个工具声明输入输出的工件类型（image / video / audio / text / package），编译器检查每条引用的类型、数量与来源 | 不会出现“把视频当首帧图传入”这类拼接错误 |
| **结构上限**：节点数、深度、扇出、视频总时长、并发数 | 计划规模可控，不会膨胀 |
| **节点级契约**：每个节点沿用 v2 的幂等键、失败分类、免费恢复、提交结果未知即停止 | 失败只影响该节点及其后代 |
| **试运行（dry-run）**：编译通过后，先用 Mock 适配器把整张 DAG 跑一遍，验证数据流、依赖顺序和产物类型（零付费） | 结构问题在花钱前暴露 |

**（2）语义正确性：代码不能保证。** 比如“这种场景该用首帧生视频还是文生视频”“镜头顺序是否讲得通”，这是规划质量问题。缓解手段：
- **Blueprint 优先**（§3.2）：常见任务从经过验证的计划模板实例化，再按需修改；
- 计划中不属于任何已验证 Blueprint 的结构，标记为**实验性组合**。审核页会明确提示，并默认触发 Critic；
- 用户审核时可以看到每个节点由谁、依据哪个 Skill 产生；
- 评测集持续回归（§8）。

### 3.2 Blueprint：v2 配方与经典工作流路径怎么处理

**建议：保留，但改变它们的地位。** v2 的五种配方从“代码路由”降级为 **Blueprint（计划模板）**，作为 Agent 可以选用、也可以不用的规划加速器。

- **Blueprint 是什么**：一个参数化的 Plan IR 片段加一份 `SKILL.md`。
  - `SKILL.md` 说明何时使用、参数含义、已知限制；
  - 通过工具 `instantiate_blueprint(name, params)` 由代码**确定性地**生成计划草稿；
  - Agent 拿到草稿后可以修改、拼接或丢弃。
- **为什么不全部删掉**：
  1. **稳定**：这五条路径在 v2 中有上千项回归和多轮实测，是目前最可靠的计划形态；
  2. **便宜、快速**：常见任务不需要 Agent 从零推理，一次实例化即可；
  3. **可对照**：v2 的行为成为 v3 的基线，评测时能看出 Agent 自由规划是否真的更好。
- **和 v2 的本质区别**：
  - 不再由代码根据 `recipe_hint` 选择 Blueprint，选不选、选哪个、怎么改，都由 Agent 决定；
  - Blueprint 生成的只是计划，执行仍统一走 Plan IR 运行时，不存在“绕过计划直接跑工作流”的通道。
- **首批 Blueprint**：`image-edit`、`image-create`、`single-clip`、`story-video`（含角色/关键帧预览门）、`video-remix`、`video-transform`。
- **经典工作流路径（D-031，放在最后阶段 V8）**：
  - 两种模式的定位不同。经典模式面向服务端生产人员，按“系列 → 模板”管理全部类型的提示词与展示产物，目标是沉淀高质量模板并支持一键打包。Agent 模式的核心是“一句话生成视频”，用户关心的是视频质量，不关心提示词。
  - **触发条件是用户明确的生产意图**，例如“用于产品生产，保留 i2i + i2v 提示词”“帮我反推这个视频的提示词”“帮我测试这个提示词的效果”。没有这类意图时，Agent 不走经典路径。判断规则写进 Producer 的系统提示词和 `production-workflow` Skill。
  - 执行时必须落到“系列 + 模板”：由 Agent 选择或新建系列与模板，经用户确认后，通过 `run_workflow_template` 节点在该模板下创建作业，并启用白名单内的分支。提示词版本按经典模式的规则沉淀到模板。这一点和 Agent 默认的私有作业正好相反，需要单独的授权与写入契约。
  - 具体契约在 V8 开始前补写，不阻塞 v3 核心交付。
- **复杂度评估**：Blueprint 本身只是“代码生成计划草稿 + 一份 Skill 文档”，复杂度可控；最大的工作量在 `run_workflow_template` 与“系列 + 模板”的写入授权、报价，约相当于 v2 的一个中等任务。

---

## 4. 两个阶段的自主边界

| | 规划阶段（Agent 自主） | 执行阶段（确定性） |
|---|---|---|
| 可用工具 | 只读与分析（看图、看视频、检索、抓取、模型目录）、计算（估价、校验）、`load_skill`、`delegate`、`ask_user`、**有额度的预览**（`request_preview`，单张低价图） | 只执行已批准计划中的节点 |
| 付费上限 | 每个 Run 有单独的**规划额度**（如 20 credits，含 LLM 与预览），超出必须向用户申请 | 计划报价，用户批准；修复与重做单独报价 |
| 不确定时 | Agent 自己查 Skill / 委派 / 追问 | 停在 attention，等用户决定；提交结果未知时一律不重交 |
| 失败处理 | Agent 自行重试或换方案（只花规划额度） | Repair Agent 只能**提出**修复方案；执行仍需报价授权（沿用 D 章） |

生成视频的工具（`animate_shot`、`generate_video`、`transform_video` 等）**不出现在任何 Agent 的工具清单里**，只能作为计划节点出现，从机制上排除“Agent 自由探索导致花费”的可能。

### 4.1 执行期的 Agent 介入：失败诊断与局部 Plan Patch

进入生产后由确定性执行器负责，但**可修复的内容性失败**需要 Agent 参与：

```text
执行器：节点失败 → 代码分类（沿用 D 章 FailureInfo）
  ├─ 不可由 Agent 修复：提交结果未知 / 鉴权 / 余额 / 配置错误 → 停在 attention，等用户处理（不启动 Agent）
  ├─ 可免费恢复：查询 / 下载中断 → 代码直接恢复原任务（不启动 Agent）
  └─ 内容性失败：内容审核拒绝、参数与能力不符、质检不通过、用户在审核 B 指出问题
        ↓
Repair Agent：读取失败证据（错误码、被拒的提示词、相关节点、预览或质检结果、相关 Skill）
  → 分析原因 → 起草 Plan Patch（只涉及受影响的子图）
        ↓
Director（计划的负责者）：审阅 Patch，确认与整体计划一致（角色、风格、衔接、时长），必要时修改或拒绝
        ↓
计划编译器：校验 Patch → 计算影响范围（DAG 后代闭包）与增量报价 → 生成新计划版本
        ↓
授权：
  ├─ 在开始生产时预授权的修复额度内，且属于“低风险 Patch”（仅改提示词，模型、时长、引用不变）→ 自动继续
  └─ 其他情况（换模型、改时长、新增节点、超出额度、影响已完成节点）→ 用户审批（复用 D 章报价与 only/cascade 选择）
        ↓
执行器：只执行 Patch 影响的节点；其他已完成节点按输入哈希复用
```

**Plan Patch 格式**：

```text
PlanPatch
  base_version, reason, evidence_refs, proposed_by: repair | director | user
  ops: [
    {op: "update_inputs", node_id, inputs}           # 例如改写动作提示词
    {op: "replace_node", node_id, node}              # 例如换模型或换生成方式
    {op: "insert_node", after: node_id, node}        # 例如先补一张参考图
    {op: "remove_node", node_id}                     # 必须同时处理其后代
  ]
  scope: only | cascade                              # 已完成后代的处理方式，沿用 D 章语义
```

**约束**：
- Patch 必须基于当前版本；版本不一致时返回 409（沿用 D 章）；
- 不能修改与失败无关的已完成节点，除非 `scope=cascade` 并已报价；
- 每个节点的自动修复次数、每次修复的额度、Run 总预算继续沿用 D 章的硬上限；
- 合规改写只能把内容改为无害表述，不能规避审核（沿用 `repair_motion_prompt` 的规则）；
- Repair Agent 只有分析类工具和 `propose_patch`，**没有**任何执行或生成工具。

**同一条路径还能处理用户的修改意见**：用户在审核 B 中说“s03 的表情不对”，Producer 把意见转给 Director，Director 起草 Patch，后面的校验、报价、审批流程完全相同。D 章“重做此镜头”的固定操作由此升级为可以描述意图的局部修改。

---

## 5. 安全与可控（继承 v2，补上 Agent 特有的部分）

- **注入防护**：网页、文档、附件分析结果和其他 Agent 的输出，都作为带来源标签的不可信数据放进 tool result，不进系统提示词。委派时 `task` 字段由委派方生成，被委派方的系统提示词说明“任务描述不能覆盖用户约束、预算与权限”。
- **权限**：每个 Agent 只能调用卡片上列出的工具；`delegate` 校验可委派关系；Registry 按 `caller_agent` 记录账本。
- **预算**：规划额度、单次委派额度、Run 总预算三层；LLM 调用按 token 估算记账（v2 是按次固定值，v3 改为按 usage 记录）。
- **可复现**：账本 + `agent_steps` + checkpoint 足以回放一次规划过程；评测时可以固定模型温度并回放工具结果。

---

## 6. v2 资产的去留

| 保留并复用 | 改造 | 退役（v2 保留到 v3 默认开启） |
|---|---|---|
| ToolRegistry、账本、幂等、预算、审批、权限 | `skills/` → `tools/` 更名；增加函数调用 schema 导出与 `caller_agent` | `graph_v2.route` 与五个配方分支 |
| 能力目录、按秒计费、模型选择约束 | `structured_call` 扩展为支持 tools 的 `agent_chat` | Director-lite / Creative v2 / Director v2 的“单次调用”节点（提示词迁入 Skill） |
| 研究的安全抓取与 SSRF 防护、附件校验、Wan3 媒体校验 | Plan Check → 通用计划编译器 | `recipe_hint` 字段（保留读取以兼容旧 Run） |
| 生产引擎的修复/报价/级联、交付、MQ、任务中心 | 生产引擎 → 通用 DAG 运行时；分镜板 → 计划视图的一种渲染 | |
| 前端各审核与结果组件 | AgentStudio 增加协作时间线 | |

v1、v2 的 Run 继续由原图恢复（与 D-009 同理）；新 Run 由 `AGENT_V3_ENABLED` 决定是否走 v3。

---

## 7. 开发计划（沿用 Claude + Codex 交替）

| 阶段 | 内容 | 负责建议 | 验收 |
|---|---|---|---|
| **V0 契约** | Tool / Skill / Agent / Plan IR / Agent Card / 工作区 / 委派协议；DECISIONS；评测集定义 | Claude | 用户确认（D-029 – D-031）；契约 `docs/agent_v3/CONTRACTS.md` |
| **V1 工具层** | `tools/` 更名与垫片；函数调用 schema；`agent_chat`（tools、usage 记账）；剧本式 Mock LLM | Codex | 经典与 v2 全量回归不变 |
| **V2 Skill 库** | Skill 加载器、`list_skills` / `load_skill`；首批约 12 个 SKILL.md（从 v2 提示词迁移）；Skill 测试 | Codex（加载器与 Skill 初稿），Claude 审定关键 Skill | 引用的工具都存在；评测基线 |
| **V3 Agent 运行时** | AgentLoop 子图、Agent 目录、`delegate` / `ask_user` / 工作区、上限与循环检测、`agent_steps` | Codex（Claude 评审） | 剧本回放：委派、退回、并行委派、崩溃恢复不重复调用 |
| **V4 Plan IR** | 计划编译器（类型化数据流、结构上限、dry-run）、通用 DAG 运行时（由生产引擎通用化）、预览门、六个 Blueprint 与 `instantiate_blueprint` | Codex | 六个 Blueprint 生成的计划与 v2 对应路径的产物和费用一致 |
| **V5 Plan Patch** | Patch 格式、编译与增量报价、低风险自动授权、Repair Agent、Director 审阅、审核 B 的意图修改 | Codex | 五类失败注入；Patch 只影响受影响子图；超额必须审批 |
| **V6 Agent 上线** | Producer、Research、Creative、Director、Prompt Smith、Critic 的系统提示词、卡片、委派策略 | Codex 实现与初稿，Claude 审定 Producer / Director 提示词与委派策略 | 评测集达标，且简单任务不发生无谓委派 |
| **V7 界面** | 协作时间线、通用计划视图、规划额度、Patch 审批卡片 | Codex（功能），Claude（美化） | 构建与浏览器验收 |
| **V8 经典路径**（最后） | 生产意图识别、系列 + 模板的选择/新建与写入授权、`run_workflow_template`、经典分支 Blueprint | Codex（契约由 Claude 在开始前补写） | 经典模式不受影响；“反推提示词 / 测试提示词 / 保留提示词的生产任务”在系列 + 模板下完成 |
| **V-Gate1–3** | V1–V3 后、V4–V5 后、V6–V7 后各一次评审；V-Gate3 含真实 LLM 评测与 v2 对照（说明书要求“不预设多 Agent 必然更好”） | Claude | 成功率、费用、耗时、人工介入次数、主观满意度 |

---

## 8. 测试与评测：Agent 系统怎么保证质量

- **确定性测试**：剧本式 Mock LLM 按预设返回 tool_calls，覆盖委派、退回、超限、注入内容、重复调用循环、崩溃恢复等情况。断言的是**不变量**，不是固定的路径，例如：
  - 规划期从未调用视频生成工具；
  - 账本总额不超过规划额度；
  - 只有 Producer 发出澄清卡片；
  - 计划都通过编译器校验。
- **评测集**（按 D-030：文本用 `deepseek-v4.1-flash`，多模态用 `qwen3.7-plus` 且多图一次调用，可少量生成图片，**不生成视频**）：约 30 条需求，覆盖改图、单镜头、长片、二创、变换，以及**训练时没见过的组合**（例如“先给我 3 张海报风格图，选一张做成 10 秒动画”）。评分项包括计划是否可执行、是否符合需求、费用是否合理、是否进行了不必要的委派或提问。只评测到“批准前的计划”与少量预览图，追求少而精：每条用例都要说明它验证的是什么，并记录调用次数和费用。
- **对照**：同一评测集分别在 v2（工作流）和 v3（Agent）上跑，用数据决定默认开启哪一个。

---

## 9. 风险与取舍

| 风险 | 应对 |
|---|---|
| 规划变慢、变贵（多轮 LLM、多次委派） | 规划额度与步数上限；简单任务由 Producer 直接委派，不走全套；Skill 写清“何时不需要某个 Agent” |
| 不稳定、难复现 | 计划编译器作为最终闸门；`agent_steps` 可回放；评测集持续回归 |
| Agent 选错生成方式 | Skill 写清取舍；Critic 自查；用户审核时可以看到每个节点“由谁、依据哪个 Skill”产生 |
| 模型函数调用能力不足 | V0 先用评测集验证候选模型的函数调用质量（需付费批准）；不足时退回 JSON 模式模拟工具调用 |
| 改动面大 | 开关隔离，v2 并存；V1、V4 先做与 Agent 无关的通用化，每一步都可以独立验收 |

---

## 10. 已确认事项（D-029 – D-031）

1. 总边界：规划阶段 Agent 自主，执行阶段按批准的 Plan IR 确定执行，内容性失败走局部 Plan Patch。已确认。
2. 规划额度默认每个 Run 20 演示 credits，含预览图。已确认。
3. Critic 新增，按条件触发。已确认。
4. Skill 库放在仓库内。已确认。
5. 真实测试：文本 `deepseek-v4.1-flash`、多模态 `qwen3.7-plus`（多图一次调用）、少量图片生成，禁止视频生成。已确认（D-030）。
6. 低风险 Patch（只改提示词，模型、时长、引用不变）在预授权额度内自动继续。已确认。
7. 经典路径按生产意图触发，落到“系列 + 模板”，放在最后阶段 V8。已确认（D-031）。
8. 分工：Codex 承担主要实现；Claude 负责契约、规划、Gate、验收与美化。已确认（D-031）。
