# Agent v2 交接日志

> 每次停手前在**末尾**追加一条，最新的在最下面。格式：

```text
## 日期 · 负责方 · 任务ID
状态：完成 / 进行中 / 阻塞
分支与提交：agent-v2/<ID> @ <commit>（已合并 / 未合并）
完成内容：
测试：pytest N passed；新增 …
未完成 / 下一步：
需要对方或用户决定：
```

---

## 2026-10-17 · Claude · P0-1 / P0-2 / P0-3
状态：完成
分支与提交：`feat/agent-v2`（从 `codex/shared-task-queue` 切出；本条所在提交即 P0 产出）
完成内容：
- P0-1：提交了 `codex/shared-task-queue` 上的未提交改动（根目录 `.env.example`、`docker-compose.local.yml`、README 与文档更新、`test_config_environment.py`），并提交 Agent v2 方案与开发计划；从此处切出 `feat/agent-v2`。
- P0-2：新建 `docs/agent_v2/` 四个协作文件；根目录 `CLAUDE.md` 与 `AGENTS.md` 改为同一份协作说明并纳入版本控制，旧内容移到 `docs/archive/`（D-008）。
- P0-3：写完 `CONTRACTS.md` A 章（Run 创建、附件、能力目录、按秒计费、RequestSpec、选择题、SimplePlan、动作、状态、路由、Skill、配置、错误码）；决策 D-001 至 D-009。
测试：基线 `pytest` 227 passed（P0 未改动代码）。
未完成 / 下一步：
- 可以并行开始 A1、A3、A5（互不依赖）。建议 Codex 先做 A1 → A2 和 A3；A5 由 Claude 做。
- A4 依赖 A3；A6 依赖 A1、A2、A4、A5。
需要对方或用户决定：
- 实现时请核实：现有 qwen 多模态模型（如 qwen3.7-plus）通过 `QwenChatAdapter` 能否接受图片输入。若不能，A4 需要扩展适配器的图片消息格式（仍属 A4 范围），并在本日志说明。
- 用户尚未确定：各 Agent 的 LLM、真实单价与自动审批阈值、检索服务商（D-002、D-003、D-004），均不阻塞 Phase A。

## 2026-10-17 · Codex · A1（用户暂停）
状态：进行中，已按用户要求暂停
分支与提交：`agent-v2/A1`，基于 `feat/agent-v2 @ bac81a9`；未提交、未合并。
工作树：`C:\Users\MingZheYang\.codex\worktrees\agent-v2-codex\AI Video Factory`（与主目录隔离）。
完成内容：
- 已阅读交接日志、PLAN、CONTRACTS 与开发计划；本轮授权范围为 A1–A4，不进入 Claude 负责的 A5。
- A1 已写入但尚未验收：ModelRegistry.capabilities、模型 API Schema 字段、能力种子及演示单价、避免覆盖运营者能力/定价、迁移 20261018_001 与旧库 schema repair、相关回归测试。
- 主目录 PLAN 已将 A1 标为进行中；业务改动均在上述独立工作树，未修改 Claude 的 A5 图与协议。
测试：指定 Conda 环境的 7 个定向测试在 fixture 建立临时目录时全部报环境权限错误，未完成业务验证；随后申请在沙箱外运行离线测试，但用户此时要求暂停，自动审批以此为由拒绝，未重试。
未完成 / 下一步：
- 用户恢复后先复核 A1 diff 与测试环境，完成定向及全量 Mock/SQLite 回归，再提交并按协作规则合并；当前实现不应视为完成。
- A2、A3、A4 尚未开始。保持任务分支隔离，检查 Claude 最新交接再继续。
需要对方或用户决定：等待用户恢复任务；没有真实模型调用、真实数据库迁移、远程推送或 PR。

## 2026-10-17 · Codex · A1–A4（恢复开发）
状态：进行中
分支与提交：独立工作树 `agent-v2/A1`、`agent-v2/A2`、`agent-v2/A3`、`agent-v2/A4`，均未合并；不操作 Claude 的 `cinecrew-wt-A5`。
完成内容：
- A1 能力目录、迁移与种子回归已写好；全量回归正在验收。
- A2 按最终模型与参数计费；`ToolSpec.cost_fn` 统一为 `(data, ctx)`，以读取冻结的模型策略；幂等成功重放不重新报价。`protocol.py` 仅改 `validate_plan` / `validate_request` 的费用计算，不改 A5 的 `RunAction`。
- A3 附件上传、解码与归属检查；仅针对 `agent_upload` 资源补齐经典工件/Job 接口的访问边界。
- A4 Intake、RequestSpec、图片理解 Skill 与 Mock 样例已准备；等待 A1–A3 集成验证。直接复用 A5 的 `clarify.Question`，不重复实现选择题或中断机制，需 Claude 合入 Schema 后完成集成。
测试：全部采用 Mock、临时 SQLite、HTTP 阻断；独立工作树需给测试进程指定 FFmpeg 路径与较短的临时目录，避免缺少根目录 .env 配置和 Windows 260 字符路径限制；不复制 .env。
未完成 / 下一步：完成各任务全量回归后分别提交、合并；最终追加验收结果。不进入 A5/A6，不调用付费模型，不迁移真实 MySQL，不推送。
需要对方或用户决定：真实模型、单价与提示词评审仍按原计划；A4 等待 A5 的共享 Question Schema 集成，不修改 Claude 工作树。

## 2026-10-17 · Claude · A5
状态：完成
分支与提交：`agent-v2/A5` @ 4bf4fc6，已快进合并到 `feat/agent-v2`。在独立工作树 `../cinecrew-wt-A5` 中开发，未触碰 Codex 的工作树。
完成内容：
- `backend/app/agent/clarify.py`：选择题卡片 / 问题 / 答案的 Schema，答案解析（未答的非阻塞题取默认），轮数上限（超出后取默认 / 推荐 / 首个选项并记入 `assumptions`），`ClarifyState` 状态类型，`clarify_gate` 图节点，`answer_for` 读取函数。
- `answer` 动作：`RunAction` 新增 `card_id` / `answers` / `use_defaults`；API 在写入命令前先校验答案，非法答案不会进入队列；worker 对 `clarify` 中断用 `answer` 命令恢复。
- 配置 `AGENT_MAX_CLARIFY_ROUNDS`（默认 2）。
- 契约 A.7 补充了答案记录格式与 A6 的接入方式；新增 D-010 与错误码 `INVALID_CLARIFICATION`。
测试：全量 245 passed（基线 227 + 新增 `test_agent_clarify.py` 18 个）。
未完成 / 下一步：
- A6 接入方法见 CONTRACTS A.7 末尾：v2 图状态继承 `ClarifyState`；需要提问的节点返回 `queue_questions(...)`，其后接 `clarify_gate` 节点。
- A7 前端：`pending_card` 在 Run 详情的 `snapshot` 中；提交格式见 A.9。
需要对方或用户决定：
- **测试环境提示（给 Codex）**：在工作树中跑全量测试时，remix 相关用例需要 FFmpeg。主目录根 `.env` 里有 `FFMPEG_BINARY`，但值带引号，而且工作树里没有这个 `.env`。在工作树中可以这样运行：`FFMPEG_BINARY=<.venv 中 imageio_ffmpeg 的 ffmpeg 路径，不带引号> python -m pytest -q`。不设置时会出现 20 个 remix 用例 setup 报错，与业务代码无关。

## 2026-10-17 · Codex · A1 已合入 / A2–A4 集成验收中
状态：进行中
分支与提交：A1 `a3b9ef0` 已合入 `feat/agent-v2`（合并提交 `eedb670`）；A2 候选 `66b35bb`、A3 候选 `625a55a` 待最终全量验收；A4 独立工作树集成上述依赖及 A5。
完成内容：
- A1 最终全量 231 passed；模型目录采用明确标注的演示价格和保守参考图能力，运营者已有非空能力记录不会被种子覆盖。
- 已读取 Claude 的 A5 交接并使用正式共享 Schema；不再需要临时依赖验证，不修改 Claude 工作树。
- A2 新增计费/重试定向 20 passed；迁移/目录/计费组合 22 passed；原片 5 秒生成旧固定费用断言改为 3 + 5 = 8，并保留生成 payload 和镜头保留回归。
- A3 附件与访问边界已完成定向验证；最终全量仍进行中。
协作分工更新（用户本轮明确指定）：
- **A7 及其界面美化由 Claude 负责**。Codex 不重复改前端；前端按 CONTRACTS 开发，v2 Run API 与 A6/A8 就绪后联调。
- 本轮先完成 A1–A4，不接手 A5；后续后端任务与前端可并行，但以各任务依赖与契约为准。
未完成 / 下一步：A2、A3 全量通过后合入；A4 完成 RequestSpec、分析恢复与一次结构修复回归后合入。所有验证仍为 Mock/SQLite，无付费调用、真实库迁移、远程推送或 PR。

## 2026-10-18 · Codex · A1–A4 集成验收
状态：完成
分支与提交：A1 `a3b9ef0`、A2 `66b35bb`、A3 `625a55a`、A4 `9e7edff` 均已合入 `feat/agent-v2`，A4 合并提交为 `deca28c`。各任务保留独立 `agent-v2/A1` 至 `agent-v2/A4` 分支。
完成内容：
- A1：能力目录字段、模型 API、迁移及旧库修复、完整种子数据。价格明确为演示值；不覆盖运营者已有的非空能力配置，不把尚未验证的首尾帧能力标为可用。
- A2：视频按秒、图片按张、LLM 按次估算；费用与提交使用同一份最终模型参数。排队和失败重试保留原 Job 的模型/参数，成功重放不重新报价；覆盖多输出、I2I 批量生成和局部重跑。缺失价格按契约回退并告警。
- A3：`/api/agent/attachments`、图片解码及尺寸/大小检查、视频探测、工件登记与归属校验；旧 `/sources` 保持返回结构。登记失败会回滚数据库并清理文件；经典接口与 Skills 的附件引用也执行归属检查。
- A4：`RequestSpec`、`analyze_attachments` / `intake` 节点、`analyze_image` Skill、角色模型配置与 `.env.example` 示例。拒绝空文本，复用 A5 的 Question/答案记录，保留用户原文模型偏好，校验附件覆盖和配方语义；结构错误只修复一次，恢复不会产生第三次理解调用。
根因修复与复核：
- Alembic 默认 `fileConfig` 会关闭已创建的应用 logger，导致缺价告警丢失；改为保留现有 logger，并补迁移回归。
- v2 附件分析恢复曾提前读取 v1 的 `goal` 模型策略；现仅对视频生成 Job 校验该策略，分析任务可独立恢复。
- Qwen 已完成响应的格式错误此前与网络状态未知混淆；现在明确标记响应校验失败，让 Intake 的一次结构修复生效，未知传输结果不自动重试。两项 A4 修复已独立复核通过。
测试：
- A1：全量 231 passed，新增 4 项；A2：全量 269 passed（含 A1/A5），新增 20 项；A3：全量 271 passed，新增 44 项。
- A4：定向 54 passed，其中新增 50 项，包含 10 类需求各两种措辞；集成 A1–A5 后最终全量 **363 passed**（296.90 秒）。首轮唯一失败为注册表测试的固定工具清单遗漏新增 `analyze_image`；补齐清单并保留全部 Schema 断言，单项复测 1 passed 后重跑完整回归全绿。
- 合入后比对 `backend/` 与 `.env.example`，与上述已验收 A4 工作树无差异；`git diff --check` 通过。
- 全部使用 Mock、临时 SQLite 和 HTTP 阻断；已有 34 条 JWT 测试密钥长度告警。未修改真实 `.env`，未调用付费模型、迁移真实 MySQL、推送远程或创建 PR。
未完成 / 下一步：
- 本轮截止 A4。A6 接入时，图状态必须保留 `IntakeState` 与 A5 `ClarifyState` 的键；`attachments_ready=false` 进入可恢复等待，节点不阻塞。Intake 的 `open_questions` 交给 `queue_questions` / `clarify_gate`，回答后再执行理解。
- A6 实现 Simple 配方及生成 Skill，A8 接通 v2 Run 创建、序列化和版本路由；当前 A4 节点尚未接入公开 Run 全流程，不能把本次后端模块验收等同于新版入口已交付。
- **A7 及其美化由 Claude 负责**，已同步 PLAN 和开发计划。前端按 CONTRACTS 开发，待 A6/A8 就绪后联调；附件预览/下载接口需要鉴权，应以带 Bearer 的请求获取 blob，直接使用裸 `<img src>` / `<video src>` 不会携带该请求头。
- A4 系统提示词仍待 Claude 在阶段评审时审阅；`analyze_image` 目前接收 Run 归属附件，检索参考工件通路留到 Phase B。
验证边界：真实模型理解质量、真实服务商价格/能力及 MySQL 迁移未验证。Qwen 图片消息格式通过假响应测试验证，未进行真实多模态调用。旧 `/api/jobs` 列表保留共享列表语义，可能展示上传 Job 元数据；此次保护覆盖媒体内容、单个上传 Job 操作和引用，不代表整个经典系统完成多租户隔离。

## 2026-10-18 · Codex · A6 / A8 开始
状态：进行中
分支与提交：从 `feat/agent-v2 @ cfcb5b0` 创建 `agent-v2/A6`、`agent-v2/A8`；复用 Codex 原 A4、A2 的干净工作树，均未合并。
完成内容：已读取最新交接、看板和 A 章契约；A6 实现 SimplePlan、Director-lite、生成 Skill 与 v2 编排，A8 实现新旧版本 API/worker/序列化兼容。旧图保持原节点与恢复语义，v2 的 story/remix 复用既有生产流程。
协作边界：A7 和界面美化由 Claude 负责，Codex 不修改前端或 Claude 工作树。共享契约不变；若实现中确需调整，先记录决策。
测试：本轮仅 Mock、临时 SQLite 与隔离存储；禁止付费调用，不复制真实 `.env`，不迁移真实库、不推送远程。
未完成 / 下一步：先完成 A6 定向与全量验收后合入，再集成验收 A8；最终补充交接和前端联调说明。

## 2026-10-18 · Claude · A7 / B0
状态：A7 前端完成（待 A6/A8 联调）；B0 契约完成
分支与提交：`agent-v2/A7-B0`（3a3cd7f A7、2bd4e33 B0、412c2d9 鉴权预览修复），已合并到 `feat/agent-v2`（e514b22、9868e6b）。独立工作树 `../cinecrew-wt-A7`，未触碰 Codex 的工作树或后端代码。
完成内容：
- A7：Agent Studio 按 v2 契约重做。输入区只有文本 + 附件（选择 / 拖放 / 粘贴，逐个上传并显示进度）和收起的预算；运行页包含阶段进度、需求气泡、理解卡片（RequestSpec）、选择题卡片（图片选项、推荐 / 默认、自由文本、按默认继续）、已确认选择、SimplePlan 编辑器（按能力目录筛选模型、按秒实时估算、时长范围校验）。旧的分镜 / remix 编辑器保留为 `ShotPlanEditor`，v1 Run 和过渡路由仍可用。移除了创作方式、镜头数、模型系列字段。
- 根据 Codex 的提示：附件预览需要鉴权，新增 `AuthedImage`（带 Bearer 获取 blob 并缓存），附件与参考图都用它展示。
- `vite.config.js` 支持 `CINECREW_API_TARGET`，可以把开发服务器的代理指向其他后端。
- B0：CONTRACTS B 章（检索适配器接口、四个 Skill、ResearchDossier、Research 图流程、网址白名单与 SSRF、提示注入防护、Mock 服务商、配置与错误码）；决策 D-011；新增任务 B5（资料卡片前端，Claude）。A.10 状态集合新增 `researching`，前端已支持。
测试：`npm run build` 通过。用隔离的 Mock 后端（临时 SQLite，端口 5055）实测：三种状态（等待回答 / 等待审批 / 已完成）渲染正常，亮色、暗色正常；从界面提交选择题答案后，A5 接口校验通过并写入命令队列；提交创建请求时，v1 后端返回 422 并在界面显示（A8 合入后应变为正常创建）；开启鉴权后附件缩略图通过 blob 正常加载。
未完成 / 下一步：
- **A6/A8 联调（给 Codex）**：前端按 A.10 读取 Run 视图的 `text`、`attachments`、`request_spec`、`pending_card`、`plan`、`results`，同时兼容这些字段放在 `snapshot` 里的情况。创建请求体为 `{text, attachment_ids, budget_limit, request_key}`。`results[].preview_url` 若指向需要鉴权的工件，前端已能处理；视频结果目前用裸 `<video src>`，如果视频也受鉴权保护需要告诉我。
- 已知问题（不属于 A7）：整个应用的布局在手机宽度下不可用（固定宽度侧边栏占满屏幕），影响所有页面，建议以后单独处理。
需要对方或用户决定：
- **测试事故（给用户）**：第一次启动隔离后端时，本机 5000 端口已有另一个开发后端（`flask --app run.py run --port 5000`）。Windows 允许两个进程绑定同一地址，我的一次注册请求和浏览器登录落到了那个后端，**在它连接的数据库中创建了测试用户 `a7_tester`**。种子数据和上传都在隔离库中。之后改用独立端口，并在脚本中加了端口占用检查。该用户是否删除由用户决定。

## 2026-10-18 · Codex · A6 / A8 完成
状态：完成；A7 浏览器联调与 A-Gate 待 Claude 接手
分支与提交：A6 `agent-v2/A6 @ 4a12de5`（合并 `9d159dc`）；A8 `agent-v2/A8 @ 0578e93`（合并 `c0d8295`），均已合入本地 `feat/agent-v2`。
完成内容：
- A6：新增 `SimplePlan`、Director-lite、能力与参数选型校验、v2 图和简单配方执行。图片修改 / 图片创作 / 单镜头视频走短流程；人像西装照自动选择 i2i，单镜头使用用户首帧或先生成首帧，再串行执行 i2v。Simple 结果直接提供媒体链接，无须强制打包。
- 模型偏好来自 `RequestSpec.constraints`；未指定时使用服务器默认模型，指定系列与排除约束贯穿规划、审批和生成。无法满足时给出选择题，不静默换系列；用户选择保留要求后可在运营配置修复后恢复。审批可修改提示词、参数、模型、图片张数，并重新校验能力、归属和剩余预算。视频按秒、图片按张估算，默认仍始终人工审批。
- `generate_image` 扩展 t2i/i2i、参考图与多张输出；`animate_shot` 复用现有 I2V Job 路径，Phase A 明确拒绝尾帧参数。生成、分析、规划都经过 ToolRegistry；图片失败不提交依赖它的视频，多张图片可以部分交付。MQ 与非 MQ 共用输出槽及下载回执，缺失文件恢复只补下载，不重新付费提交。
- v2 story_video 按模型时长能力拆分（上限 20 镜头），复用旧生产/打包节点；remix 复用 Intake 已完成的原片分析。旧图仅提取公共节点工厂，原节点名、拓扑和 checkpoint 恢复保持。A8 所需的 RequestSpec 模型策略读取因 A6 执行依赖，已提前随 A6 提交。
- A8：公开创建接口接受 `{text, attachment_ids, budget_limit?, request_key}`，必填文本、附件归属和最低理解预算在创建边界校验；旧创建字段返回 `DEPRECATED_FIELD`。按 `request.schema_version` 分图；已有 v1 Run 可继续审批、恢复和 remix 局部修改。v2 视图提供理解结果、选择题、计划、结果和步骤统计，不再依赖请求中的镜头数。
- `.env.example` 补齐 `AGENT_DEFAULT_BUDGET`、`AGENT_MIN_RUN_CREDITS`、`AGENT_AUTO_APPROVE_CREDITS`；真实 `.env` 未修改。Claude 已合入的 A7/B0 文件均保留，前端无本轮改动。
根因修复与复核：
- 图片张数同时存在于 `image.n` 与归一化 `params.n` 会导致只修改张数被旧值拒绝；现在审核计划以 `image.n` 为唯一来源，执行/计费边界再合入最终参数。
- 旧适配器只保留首个图片 URL，无法完整交付 `n` 张结果；现在保留全部 URL 并逐项登记。下载回执绑定原模型任务，避免经典重跑复用旧输出；下载故障恢复仍使用同一个 ApiTask。
- v2 复用 remix 时曾读取 v1 `goal`，现按版本读取文本并使用同一预算域的模型策略；同次图调用自动审批前先发布理解结果，生成守卫无需依赖 worker 下一次保存。
- 逐点遍历时长网格在极细步长下可能停滞；改为有界分配，共享能力校验用精确分数检查步长，拒绝非法步长。无效业务草稿保留供人工修改，不强制重新规划。
- 历史列表不应重新执行附件文件存在性校验。现在历史展示只读取归属正确的元数据，已删除记录省略；创建、理解与执行仍严格验证附件。审批未提交修改时保留命令中缺省的 `plan`，避免绕过原草稿的总时长校验。
测试：
- A6 最终完整回归：**444 passed**，417.47 秒（比 A1–A5 基线新增 81 项）。覆盖西装照、用户首帧/生成首帧、多图、自动审批、重启与幂等、未知模型选择题、无效草稿编辑、首帧失败隔离、120 秒计划拆分及生产/打包过渡、原视频分析复用。
- A8 API/真实 v2 图/稳定性定向：38 passed；最终集成完整回归：**473 passed**，434.55 秒（A8 新增 29 项）。包括上传→理解→审批→i2i→交付下载、换模型/仅改张数、非法审批不入队、选择题回答、历史附件删除、旧 v1 图恢复及经典/MQ 回归。
- 两次全量均只有原有的 34 条 JWT 测试密钥长度告警。全部使用 Mock、临时 SQLite、隔离存储与 HTTP 阻断；没有真实模型调用、真实 MySQL 迁移、服务端口启动、远程推送或 PR。
- 合入后 `backend/` 与 `.env.example` 和已验收的 A8 工作树无差异；`frontend-vue/` 与 Claude 的 `7a6f2b8` 基线无差异。旧用例只把已弃用的创建入口改为预存 v1 Run，保留原审批、费用、恢复和故障断言。
未完成 / 下一步：
- **Claude：A7 浏览器联调和 A-Gate**。后端已接受新入口并返回 A.10 视图；SimplePlanEditor 只修改 `image.n` 即可，规范化的 `image.params` 不含重复 `n`。本轮已完成 API/worker/图联动，没有启动浏览器或改 A7 UI。
- 回答 A7 的预览问题：生成结果沿用经典工件的公开预览/下载规则，裸视频链接目前可用；上传的原片属于 `agent_upload`，其预览/下载仍需要 Bearer，`legacySource` 的裸 `<video src>` 在开启鉴权时需由前端处理。未扩大经典工件的权限语义。
- 本地联调前重启 API、`agent-worker` 和 `mq-worker` 以加载修改；保持 `MODEL_ADAPTER_MODE=mock`。图片附件需要 `AGENT_VISION_MODEL` 指向具备 `image_understanding` 能力的模型，本轮图/API 测试显式配置 `qwen3.7-plus` 并使用 Mock；配置示例见 `.env.example`，不要把文本模型回退视为具备视觉能力。README 的 Agent 入口表格仍描述旧镜头数/模型表单，可在 A7/A-Gate 文档同步时更新。不要通过真实库或真实模型验证此次联调。
- A4/Director-lite 提示词质量待 Claude 阶段评审。复杂故事的 Creative/Director v2 属于 Phase C；首尾帧属于 D2；Agent 默认不压缩属于 E1，本轮按 A.12 不改变压缩行为。B0 已完成，本轮未进入 B1/B2。
验证边界：真实多模态理解/生成质量、真实模型参数与价格、真实 MySQL/Redis 部署及浏览器端完整交互未验证。演示目录与 Mock 输出不能作为真实效果承诺。

## 2026-10-18 · Codex · B1–B4 开始
状态：进行中
分支与提交：从 `feat/agent-v2 @ db066a6` 创建 `agent-v2/B1` 至 `agent-v2/B4`，分别复用 Codex 的独立工作树；尚未合并。
完成内容：已读取最新交接、Phase B 看板和 B 章契约，领取检索/安全抓取、参考图片、Research 编排和注入测试。
协作边界：A7 联调、A-Gate 由 Claude 负责；B5 资料卡片前端和 B-Gate 保持原分工。Codex 不修改 Claude 工作树或前端；若阶段评审涉及后端共享文件，集成时按最新提交核对。
测试：本轮仅 Mock、隔离 SQLite/存储与离线网络替身；不进行付费调用、真实库迁移、远程推送或真实服务启动。真实检索服务商仍不确定，本轮不绑定服务商。
未完成 / 下一步：B1/B2 先确定公共接口并并行开发，B3 接入 v2 图，B4 完成注入及恢复回归；各任务完整回归通过后按顺序合入，最终追加交接。

## 2026-10-18 · Claude · A-Gate（Phase A 阶段评审）
状态：**通过**，评审中发现的问题已修复并合入
分支与提交：`agent-v2/A-Gate` @ 69b13e4，合并到 `feat/agent-v2` 为 7ddd4cb。所有 `agent-v2/*` 分支均已合入（未合并提交数为 0）。
评审范围：A1–A8 的代码、A4 Intake 与 A6 Director-lite 提示词、契约一致性、全量回归，以及 Codex 无法完成的浏览器端联调。
验证结果：
- 全量回归：评审前 473 passed，修复后 **474 passed**（新增 1 个 Intake 用例）；`npm run build` 通过。
- 浏览器端联调（隔离 Mock 后端 + agent-worker，临时 SQLite，开启鉴权）：纯文字需求“画一张赛博朋克风格的城市夜景海报”完成 创建 → 理解（image_create）→ 计划 → 审批 → 生成 → 结果展示；带人像附件的“用这张照片生成西装照”被识别为 image_edit，附件用途为人物参考，模型列表只剩支持 i2i 的模型，受保护缩略图正常加载。旧字段请求返回 DEPRECATED_FIELD。
评审发现与处理：
1. **简单配方多了一步交付审批**（与 A.11 不一致）：结果出来后停在“可交付”，还要点“打包”，但该步骤并不打包。已改为收集结果后直接完成；旧的中断节点保留注册，已停在该中断的 Run 仍可恢复。相关测试改为直接断言 success。
2. **轮数用完后 Intake 仍提问会让 Run 失败**（INVALID_CLARIFICATION → needs_attention）：改为按当前理解继续，并在 assumptions 中提示审核时确认。新增用例。
3. **提示词**：Intake 补充输出语言、summary 写法、只问与预算相关的问题、不问技术参数；Director-lite 补充项目已验证的写法（图生图首句锁定人物身份、图片提示词只写静态、视频提示词只写动态、中文、不含含糊词）。
4. **前端**：v2 改造视频任务从附件中找原视频，并可“修改镜头”（原先只认 v1 的 `request.mode`）；原视频受鉴权保护，改为点击后带凭证加载；计划编辑器在窄栏中不再挤压提示词输入框。
5. README 的 Agent 入口说明已改为一句话入口（Codex 提到的遗留项）。
遗留（不阻塞，已知）：
- 多镜头短片的过渡路由（时长分配逻辑较复杂）将在 Phase C 被 Creative/Director v2 替换。
- 整个应用在手机宽度下布局不可用（共享布局问题，非 Agent 范围）。
- 用户尚未决定是否删除误建在开发库中的测试用户 `a7_tester`（见上一条 Claude 交接）。
给 Codex（Phase B 进行中）：
- **B 分支基于 db066a6，A-Gate 修改了 `graph_v2.py`、`intake.py`、`director_lite.py`**，B3 合入前请先合并最新的 `feat/agent-v2`（7ddd4cb 及之后），注意 `_queue` 与 `simple_collect` 路由的改动。
- worker 的 `tick()` 只轮询 `queued/understanding/analyzing/planning/producing/delivering`，B3 新增 `researching` 状态时需要加入该列表，否则 Research 中的 Run 不会被推进。
- B3 的选择题请继续通过 `queue_questions` / `clarify_gate`；Research 提问用 `asked_by="research"`，A7 前端已支持图片选项。

## 2026-10-18 · Codex · B1–B4 完成
状态：完成，完整回归通过并已合入本地 `feat/agent-v2`；B5 / B-Gate 待 Claude 接手
分支与提交：B1 `agent-v2/B1 @ af4618f`（主体 `93c552d`）；B2 `agent-v2/B2 @ 74af298`（主体 `5d8ec10`）；B3 `agent-v2/B3 @ c244d60`；B4 `agent-v2/B4 @ 2673459`。均在 Codex 独立工作树开发，最终 B4 包含全部依赖，统一合入提交为 `85cfd27`。
协作同步：已重新读取 Claude 的 A-Gate 交接，在 B3 合入 `feat/agent-v2 @ a290a7d`（合并 `d0c94ed`），保留 `_queue`、简单任务自动交付、提示词和全部前端/README 修改。没有修改 Claude 工作树、前端或真实 `.env`。
完成内容：
- B1：新增服务商接口与强制离线 Mock、`web_search` / `fetch_page`、`external` 账本权限。网址权限只来自同 Run 的成功检索收据和用户原文；抓取逐跳验证公网地址、固定解析出的 IP 连接、保留 TLS 主机校验，并限制端口、重定向、超时、类型和字节数。不预选真实检索服务商。
- B2：新增 `image_search` / `download_reference`，解码及尺寸校验、Run 内 SHA 去重、来源登记和持久下载收据。参考图存于所属用户的 `agent_upload` Job，分析复用 `analyze_image`；统一以 `reference_for_run` 校验用户、Run 和文件。无 Run 的经典导入不能借用参考图或其未登记缓存。
- B3：v2 按 `research_needs` / `needs_research` 进入规划→检索→结果 ID 选择→抓取下载→看图→汇总；普通任务跳过。资料、图片分析和后续规划参考统一通过 `untrusted_content` 传递。Dossier 校验来源、候选与图片归属；无引用事实被丢弃。明确候选自动选定并记假设，模糊候选复用 A5 图片选择题；多批问题共用原轮数限制，回答后只更新选择，不重复检索或分析。worker 纳入 `researching`，v2 API 顶层新增 `research_dossier`。
- B4：六类恶意资料、伪造结构化决策、跨 Run 引用、权限与费用不变、真实 checkpoint 下载恢复和两轮 API 选择题恢复。测试保留 Qwen 消息组装/解析，仅替换网络 I/O；Mock 图验证之外，另直接提供恶意模型输出验证代码拒绝边界。
根因修复：
- 已完成 LLM 响应的 422 结构校验失败不能按“尚未调用”免账单；以现有 `response_validation` 标记区分，保留费用且不自动重复调用。
- 外部工具和图片分析重放必须重新验证 Run、输入与角色；未知付费结果仍停，只有免费下载可凭持久收据重入。
- 所有当前检索失败时只检查本次计划的收据，历史手动检索成功不能掩盖本轮故障；部分普通资料失败保留警告并继续。
测试：
- 最终集成完整回归：**589 passed, 34 warnings in 666.79s**，包含 B1–B4 和 Claude 最新 A-Gate；相比 A-Gate 的 474 项基线新增 115 项。34 条均为已有 JWT 测试密钥长度告警。已验收提交为 `2673459`。
- B1 新增检索/安全抓取 43 项通过；独立全量 515 passed / 1 failed，唯一失败为已收集的旧工具清单断言（11）。已在 `af4618f` 修为 13，API 定向 4 passed；B2 加入后最终清单为 15。
- B2 新增 26 项通过，旧附件/Intake/Skills 定向 83 项通过；缓存路径边界与恢复另复测 3 项通过。
- B3 原 22 项通过，新增历史检索故障场景与全失败场景定向 2 项通过。B4 与最终 B3 合并定向 **46 passed**（79.06 秒，B4 新增 23 项）。B4 初轮负例缺少成功搜索收据，已改为真实 Mock 搜索前置，未削弱拒绝或费用断言。
- B2/B3 的早期全量因后续安全修复中断，最终由 B4 对包含 A-Gate 的同一份集成代码执行完整回归。全部为 Mock、隔离 SQLite/存储、HTTP 阻断；B4 额外统计 DNS/HTTP 访问尝试为 0。没有付费调用、真实库迁移、服务端口启动或远程推送。
- 合入后核对：`backend/` 与 `.env.example` 和已验收 B4 提交完全一致；前端、README、AGENTS/CLAUDE 与 Claude 的 `a290a7d` 基线无差异。`git diff --check` 通过；用户原有未跟踪的技术说明文件未改动。
给 Claude / 下一步：
- **B5 资料卡片及 B-Gate 仍由 Claude 负责**。v2 Run 视图的 `research_dossier` 与 `snapshot.research_dossier` 相同，未检索为 null；候选的 `reference_id` 是工件 ID，预览 `/api/artifacts/<id>/preview` 需要 Bearer，继续使用 `AuthedImage`。确认卡片沿用 `pending_card` 与 `asked_by="research"`；展示 sources、warnings、assumptions 和选中候选，资料正文按不可信文本呈现。
- `.env.example` 增加 B.9 配置；`MODEL_ADAPTER_MODE=mock` 强制离线检索，样例形象、热度、单价均为演示。参考图理解需要配置具备视觉能力的 `AGENT_VISION_MODEL`（测试为 `qwen3.7-plus`）；`AGENT_RESEARCH_MODEL` 留空复用已有 planner 配置。开发联调前重启 API 与 Agent worker，继续使用隔离 Mock 环境。
- 已选参考图目前只作为规划资料，接入生成模型的角色参考绑定属于 Phase C；没有提前实现 C 章。Research 提示词和浏览器资料展示留待 B-Gate 评审。
验证边界：未验证真实搜索服务商、真实模型的抗注入/理解/生成质量、真实价格或 MySQL/Redis 部署。Mock 抗注入测试证明结构化边界和权限约束，不等同于真实 LLM 的内容判断能力。下载缓存为恢复保留，本阶段未增加缓存清理机制。

## 2026-10-18 · Claude · B5 + B-Gate 评审 + C0
状态：完成。B5 与 B-Gate 修复合入本地 `feat/agent-v2`（`776172f`）；C0 在 `agent-v2/C0`，已合入。所有 `agent-v2/*` 分支均无未合并提交。
B5：新增 `ResearchCard.vue`（检索统计、warnings、实体共同特征与候选图网格、已选/推荐标记、主题要点带来源角标、可折叠来源列表）。来源链接只渲染 http(s)，`target=_blank rel="noopener noreferrer nofollow"`；资料正文按纯文本插值，不用 v-html；候选图走 `AuthedImage`。
B-Gate 评审结论：通过。
- 安全：逐跳 DNS 解析并检查全部地址、IP 固定连接与 TLS 主机校验、端口/重定向/字节/类型限制（`search/fetch.py`）；网址白名单只来自本 Run 收据与用户原文（`search/scope.py`）；参考图解码炸弹与尺寸检查、SHA 去重（`search/references.py`）；Research 提示词的不可信边界与 result_id 选择充分。
- 修复（1 处）：`research.resolve()` 的用户可见假设里出现内部候选 ID（如 `e1_c1`），改为“候选 N”。
- 待 Phase C：选定的参考图尚未接入生成（D-014）。
- 测试：完整回归 **589 passed**；修复后 research 相关 89 passed；`npm run build` 通过。
- 隔离 Mock 实测（临时 SQLite、端口 5055、鉴权开启）：输入“AI 漫化形象（DeepSeek、ChatGPT 等）二创故事，约 2 分钟”，预算 300 → researching → awaiting_input（10.6 credits）；DeepSeek 自动选定、ChatGPT 出图片选择题；资料卡显示 3 次检索、4 页、6 张参考图且全部加载；在界面选择 ChatGPT 候选 2 → 记录 `e2_c2` → 进入审核，故事计划 4 个镜头。进程已停止，`.claude/launch.json` 已删除。
C0：CONTRACTS C 章定稿（C.1–C.13）；DECISIONS D-012–D-014；PLAN 展开 C1–C7 与 C-Gate。
给 Codex（Phase C）：
- 全部在 `AGENT_STORY_V2_ENABLED=true` 下开发和测试，开关关闭时现有 story_video 过渡路由与全部旧测试必须不变。
- 建议顺序：C1 与 C2 可并行 → C3 → C4 → C5 → C6。C6 完成后在 PROGRESS 写清 Run 视图 `story` / `plan` / `previews` 的实际样例，供 C7 前端使用。
- worker `tick()` 需加入 `previewing`；两个审核状态由命令推进，不轮询。
- 角色参考：research 来源复用 `reference_for_run` 校验归属；生成镜头的 i2i 参考图数量受能力目录 `reference_images.max` 约束（`validate_generation_model` 已有 `reference_count` 参数）。
- 预览图片生成必须经 ToolRegistry 的现有图片 Skill（幂等、预算、账本），不要直接调适配器。
需要用户决定：无新增。各 Agent 模型、真实单价、检索服务商仍未定（不阻塞）。

## 2026-10-18 · Codex · C1–C7 完成
状态：完成，已合入本地 `feat/agent-v2`；C-Gate 与界面美化由 Claude 接手。
分支与提交：C1 `2276aed`；C2 `3d66b89`；C3 `edcc023`；C4 `8292cb3` / `de2655d`；C5 `1e46510` / `f451dc4`；C6 `5ddb56b` / `9440d72` / `636486e`；C7 `a855450` / `91b018e` / `5b74903`。各任务均使用 `agent-v2/Cn` 分支，集成在 Codex 独立工作树完成，没有修改 Claude 工作树。
完成内容：
- C1–C4：Creative v2 产出剧本、节拍、角色与风格；Director 按能力目录拆镜头，代码推导衔接依赖、计算按秒视频费用；Prompt Smith 经 ToolRegistry 逐镜头写静态/动作提示词；Plan Check 校验时长、引用、能力、模型约束与预算，最多自动修订一次，仍无效则保留可编辑草稿。低预算、部分提示词成功与恢复均保留已有结果，不重新调用成功部分。
- C2：计划版本不可变，预览任务按版本/目标/attempt 保存；操作收据绑定内容，同 key 不同内容冲突。新增迁移与 SchemaService 兼容；旧版本和旧产物保留。
- C5：优先直接使用本 Run 已选研究参考图或附件，仅缺失时生成定妆图。所有图片提交/查询均经 ToolRegistry；输入哈希相同的成功图片复用，单张失败局部重做。角色参考变化只使相关关键帧过期，不自动级联重做。预览 Job 在后台启动前绑定 Run，列表、预览、下载、复制和生成引用均校验归属。
- C6：接通角色审核 → 关键帧预览 → 分镜审核；worker 自动推进 previewing，两个审核状态仅由命令推进。edit_plan / regenerate / regenerate_stale / approve_characters / approve_storyboard 均做版本、归属、能力与预算校验，审批前再次校验视频费用与预览完整性。命令重放、checkpoint 恢复及已提交版本恢复不重复付费。最多 128 字符的请求 key 使用固定长度内部命令 ID。
- C7：新增分镜板、时长对比、角色卡、衔接时间线、镜头编辑抽屉、图片已花/视频按秒预计/累计规划费用、局部重做报价与确认；受保护图片使用鉴权预览。并发版本更新保留未应用抽屉草稿，不覆盖用户修改；角色未保存修改与显式重做分开。只做功能及必要布局，未改全局美化。
- D-015 补充审核视图的可选报价/支出/服务端规则字段；D-016 明确修改角色外观后先保存并标记定妆图过期，用户明确重做后才能继续，不隐式追加图片费用。开发计划的旧 C 阶段编号已同步 C0 契约与看板，C1–C7 均由 Codex 负责。
集成修复：
- 默认 i2i 模型只能接受一张参考图时，Mock Director 按角色交叉切镜头并保留总时长；真实提示词要求遵守相同能力约束，不能靠放宽目录绕过。中文“wan2.7系列视频模型 / 系列的视频生成模型”正确归一化，不再误触发选择题。
- 重复 API 命令返回前释放事务锁；worker 合并快照保留版本与动作收据；重放已提交编辑时不因目录说明变化重写提示词。预览费用按可复用结果计算，避免已完成图片重复占用剩余预算。
- 首轮全量发现后台线程完成与恢复检查之间的竞态：缓存 Job 仍为 running，可能误恢复已完成任务并再次提交图片。恢复逻辑现在在确认线程/队列未运行后使用锁定的数据库当前读刷新终态，完成分支及时释放锁；同时覆盖重复命令恢复入口。回归断言提交次数与账本不增长，不以延长等待或接受多余产物规避。
测试：
- 后端最终完整回归：**729 passed, 34 warnings in 676.02s**（验收代码 `636486e`，比 B-Gate 的 589 项基线新增 140 项）；包含此前 A/B、经典 DAG、MQ、Simple、remix 与本轮 C 相关用例。首轮为 721 passed / 2 failed，失败均为上述恢复竞态，已修复并加入确定性用例。34 条警告仍为既有 JWT 测试密钥长度告警。
- C1 新增 33 项；C2 24 项；C3/Director-lite 初轮 25 项；C4 最终 37 项；C5 相关初轮 68 项；C6 两级审核与独立边界 19 项。中文模型系列后缀另有 46 项相关回归通过。恢复修复后 C5、Agent MVP、模型策略、remix、Simple 生成相关 113 项通过（126.62 秒）。
- 前端 `node --test tests/storyboard.test.js`：15 passed；`npm run build` 通过；真实 Mock 浏览器联调使用独立端口 5067 / 5187、临时 SQLite/存储、开启鉴权、阻断模型外网访问。主 Run 完成 8 个版本：角色修改不加费 → 明确重做 → 关键帧 → 单镜头修改 → 并发草稿保护 → 2 张过期图片报价确认 → 分镜批准。主 Run 只有 7 次图片生成，0 视频提交；鉴权图片全部加载，业务流程无失败、无页级 JS 异常。
- 修改后新建第二 Run 验证中文系列表达不再多余澄清，检查角色审核的新按钮后取消。临时服务和本次创建的浏览器页面均已关闭。测试库仅作本机审计保留在 `%TEMP%/cc-c7-browser-9fa77c023e/browser.db`，含两个测试 Run；不属于交付依赖。
- 全部使用 Mock 与隔离 SQLite；没有付费调用、真实库迁移、真实 .env 修改、远程推送或 PR。用户原有未跟踪技术说明文件保留。合入后核对业务目录与验收工作树一致，`git diff --check` 通过。

实际 Run 视图摘录（`agent_c1e79e01c03e482b`，演示模型/单价；省略提示词和部分必需字段，非完整请求体）：
```json
{
  "status": "storyboard_approved",
  "plan_version": 8,
  "story": {"characters": [{"character_id": "c01", "name": "主要主体", "reference": {"source": "generate", "artifact_ids": ["art_d5a36afd2b404641"]}}]},
  "plan": {
    "plan_version": 8, "recipe": "story_video", "target_duration_sec": 120,
    "shots": [
      {"shot_id": "s01", "duration_sec": 25, "transition_in": "start", "depends_on": []},
      {"shot_id": "s02", "duration_sec": 30, "transition_in": "independent", "depends_on": []},
      {"shot_id": "s03", "duration_sec": 30, "transition_in": "independent", "depends_on": []},
      {"shot_id": "s04", "duration_sec": 30, "transition_in": "tail_frame", "depends_on": ["s03"]}
    ]
  },
  "previews": {"keyframes": {"s01": {"status": "success", "stale": false}, "s02": {"status": "success", "stale": false}, "s03": {"status": "success", "stale": false}}, "end_frames": {}},
  "estimates": {"preview_credits": 4, "video_credits": 115, "total_credits": 119, "preview_spent_credits": 14, "spent_credits": 27},
  "story_rules": {"duration_tolerance_ratio": 0.1, "max_shots": 30, "keyframe_bridge_enabled": false}
}
```
此例总长 115 秒，目标 120 秒，在 10% 容差内；视频均为 wan2.7-i2v。preview_credits 是该版本检查时保存的图片估算，累计图片支出看 preview_spent_credits，累计规划与图片支出看 spent_credits。s04 等 Phase D 从 s03 提取尾帧，不存在待重做的预览图片任务。
给 Claude / 下一步：
- **C-Gate 与界面美化**：重点评审 Creative / Director / Prompt Smith 提示词、D-015/D-016、两级审核及局部重做的用户表达。C7 功能已与真实 API/worker 联调，不需再猜字段。移动端全局侧边栏问题仍按此前交接单独处理。
- 默认 `AGENT_STORY_V2_ENABLED=false`，旧 story_video 过渡路由仍可用；隔离 Mock 联调需显式开启。Phase C 仅停在 `storyboard_approved`，没有视频生产和最终拼接。首尾帧开关仍默认关闭，真实质量未验证；用户要求的默认不压缩留在 E1。
- **Phase D 必须承接审核选型**：审核页显式选择的模型记录在服务端 `story_model_overrides`，通过 `select_plan_model` 校验，仍遵守用户排除约束。D 的视频 Skill/job policy 必须消费已批准的逐镜头模型，不能沿用仅按原 RequestSpec 服务器默认值锁定的旧路径而回退或拒绝这次用户选择。
- 角色图/关键帧受保护，继续使用 AuthedImage。尾帧依赖由 D 调度与提取；失败只处理受影响目标，额外费用必须明确展示。当前约束不保证真实角色视觉一致性，需后续经用户单独批准做质量评测。
验证边界：未验证真实生成效果、真实服务商能力与价格、真实 MySQL/Redis 部署；已实现迁移仅在隔离 SQLite 回归。角色/价格/模型能力的 Mock 样例不代表真实质量承诺。没有新增必须由用户决定的事项。

## 2026-10-18 · Codex · D0–D5 开始
状态：进行中；D0 契约完成。
分支与提交：从 feat/agent-v2 @ f621d51 分别创建 agent-v2/D0、D2、D3、D5，复用四个 Codex 独立工作树；D1/D4 将按依赖创建。
完成内容：已读取最新 C1–C7 交接、看板、C 章与 D 章占位，先记录 D-017–D-019，再补齐 D 章契约；用户指定的 D0–D5 全由 Codex 承担。
协作边界：主目录当前在 Claude 的 agent-v2/C-Gate；不修改该工作树。C-Gate、界面美化与 D-Gate 留 Claude。D5 只新增功能组件和最小接线，集成时保留 Claude 后续变更。
测试：本轮仅 Mock、隔离 SQLite/存储；不改真实 .env，不进行付费调用、真实库迁移、推送或 PR。
下一步：D1 依赖调度、D2 媒体 Skill、D3 局部修复、D5 独立组件并行；D4 接入审核/级联动作，最终统一回归并追加完成记录。

## 2026-10-18 · Claude · C-Gate 评审 + 分镜板美化
状态：完成，分支 `agent-v2/C-Gate`，已合入本地 `feat/agent-v2`。所有 `agent-v2/*` 分支无未合并提交。
C-Gate 评审结论：通过。
- 提示词：Creative（用户情节只补全不改写、角色外观锁定、只复用 Research 选定候选、最多 3 个非技术问题）、Director（只写结构不写提示词、衔接规则、按能力拆分、参考图上限时拆交叉镜头而不丢身份）、Prompt Smith（首帧只写静态、动作只写动态、尾帧承接）均与 C 章一致；所有外部内容都作为数据传入，不进系统提示词。
- 代码边界：Plan Check 纯代码、逐镜头问题可编辑；审核命令带请求键收据与版本校验，入队用条件更新防并发；预览图走 ToolRegistry 图片 Skill；私有预览按 Run 所有者鉴权（`is_private_agent_job`、工件列表按 Run 所有者过滤）。D-015 / D-016 合理。
- 修复（1 处）：`prompt_smith._run` 原先在真实 LLM 返回的首帧/尾帧提示词没有逐字以 `style.prompt_prefix` 开头时直接判为 `PROMPT_VALIDATION_FAILED`（已计费、不重试，该镜头卡死）。现改为代码补上前缀；空提示词、继承帧带提示词、超长仍然拒绝。原“无效响应计费且不重复调用”测试改用空提示词，新增“缺前缀自动补全且只调用一次”测试。
- 测试：Codex 交付代码完整回归 **729 passed**（17 分 16 秒）；修复后 story / plan_versions 相关 141 passed（含新增 1 项，合计 730）；`node --test tests/storyboard.test.js` 15 passed；`npm run build` 通过。
分镜板美化（`StoryboardEditor.vue`，逻辑与事件不变）：
- 新增 `storyboard-messages.js`，分镜板全部界面文案接入 zh/en（原先在英文界面下是硬编码中文）。本地预检与服务器返回的 `plan_issues` 文案仍为中文（来自 `storyboard.js` 与后端），未改。
- 头部：图标、状态胶囊（审核中琥珀 / 生成中蓝色转圈 / 已确认绿色）、审核步骤条（角色定妆 → 分镜关键帧 → 分镜确认；没有需要生成的角色时省略第一步）。
- 概览：时长条按场景着色、标出目标时长刻度与容差余量，有问题的镜头红框；三项费用卡片。故事与风格折叠为卡片，风格用标签展示。
- 角色卡：竖版定妆图、来源与状态标签；镜头改为响应式卡片网格（16:9 关键帧、编号与时间段角标、衔接方式彩色标签 + 图标、角色列表）。网格按容器宽度自适应，不依赖视口断点。
- 底部操作栏吸底；有未保存修改时只显示“撤销 / 保存修改”，否则显示“重做过期预览 / 确认分镜”。重做与放弃的确认从页面底部的内联块改为居中模态框（原先在中部镜头点“重做”，确认块出现在页面最底部）。编辑抽屉分“画面 / 时长与模型 / 提示词”三组，顶部显示当前关键帧，保存按钮吸底。
- 文案修正：角色审核阶段关键帧原显示“排队中”，改为“角色确认后生成”；角色审核提示按状态区分（有修改 / 有失败或过期 / 可以确认），不再总是提示“请先重做失败或过期的定妆图”。
- 隔离 Mock 实测（临时 SQLite、端口 5056 / 5175、鉴权开启、`AGENT_STORY_V2_ENABLED=true`）：一句话长片 → awaiting_characters → 确认角色 → 关键帧 → 改 s01 时长（版本 3，关键帧不过期，符合输入哈希）→ 改 s02 画面（版本 4，s02 过期）→ 模态框确认重做（约 2 credits）→ 中文界面确认分镜 → storyboard_approved，步骤条全绿、无视频提交、无控制台错误。Mock 关键帧为 1×1 白图，缩略图显示为空白属正常。进程已停止，`.claude/launch.json` 已删除。
已知未处理：移动端整页横向溢出来自全局侧边栏布局（此前交接已记录），分镜板内部无溢出。
给 Codex（D0 及 Phase D）：
- D0 契约已由 Codex 完成（95d9909）。实现时请从 `storyboard_approved` 接续，消费已批准计划版本的逐镜头模型（含 `story_model_overrides`），不要回退到 RequestSpec 默认选型。
- `agent_shot_tasks` 已为 `video` / `tail_frame` 预留 `target_type`；尾帧依赖与局部修复只处理受影响目标，额外费用需在界面显式确认（与审核 A 的“过期不自动重做”一致）。
- **D5 集成注意**：`StoryboardEditor.vue` 的模板与样式已整体重写（脚本逻辑、props、事件、`data-testid` 不变），新增文案放在 `storyboard-messages.js`（zh/en）。D5 接线请基于合入后的版本，新文案同样走本地 i18n；生产看板组件可复用该文件中的 `.status-pill`、`.step`、`.notice-*`、`.state-*` 样式约定，视觉统一由我在 D-Gate 处理。
  - `agent-v2/D5` 对 `StoryboardEditor.vue` 的两处文案改动（副标题、分镜已确认提示）已按 D5 的新措辞写入 `storyboard-messages.js` 的 `subtitle` / `approvedNote`（zh/en）。合并时该文件冲突直接取 `feat/agent-v2` 版本即可。
- Prompt Smith 现在会补全缺失的风格前缀；若 D 阶段增加新的提示词校验，建议同样优先在代码中修复可确定的格式问题，避免已计费的结果直接失败。
需要用户决定：无新增。


## 2026-10-18 · Codex · Phase D 集成验收中
状态：D0 完成；D1–D5 功能已接通，仍在补边界和验收，不作为完成交付。
协作：已合入 Claude 的 C-Gate / 分镜板美化 da14962；保持主目录原有未跟踪笔记，不改变其界面样式。独立工作树 agent-v2/D1 集成，D5 使用独立 5078 / 5198 Mock 服务联调。
进展：十镜头真实 Mock 调度 6 项通过（并发上限、依赖、MQ/非 MQ、重启去重）；生产图完整链路 2 项通过；D2 相关回归 158 项；D3 修复 38 项、集成恢复 9 项；D4 主体 22 项、补充 3 项。完整回归运行中。
仍在处理：本地尾帧失败的局部恢复、连续 only 重做的来源记录、恢复时修复加后续镜头的总费用上限、回到分镜编辑后复用成功视频的预算展示。所有测试 Mock / 隔离 SQLite，不做付费调用。
下一步：合入上述修复及浏览器结果，再更新本看板为完成并追加最终交接。


## 2026-10-18 · Codex · D0–D5 完成

状态：功能与本轮 Mock 验收完成；合入本地 `feat/agent-v2`。D-Gate 与界面美化由 Claude 接手，未进入 E/F。
验收代码：`agent-v2/D1 @ 7333677`（此后仅文档更新）；D0 `95d9909`；D1 `c40b81f` / `677c158`；D2 `fc8faac` / `e3f6d00` / `8440fbb`；D3 `9adaa00` / `aa81b3c` / `66eb0e1`；D4 `018d0df` / `ecc761e` / `9d64e63`；D5 `c15a7d0`。任务分支均已保留，本轮没有远程推送或 PR。

完成内容：
- D0：D 章契约与 D-017–D-022，明确生产授权、依赖调度、局部修复、报价/级联、审核 B 与私有数据边界。
- D1：从审核 A 的 `storyboard_approved` 通过显式 `start_production` 接续；编译持久 video / tail_frame 任务，无依赖镜头并发，尾帧承接串行。共用经典 Job/MQ，不增加另一套队列；恢复以任务/回执/账本为准。单镜头失败不会阻断其他独立镜头，最终进入 `awaiting_video_review` 或 `production_attention`。
- D2：免费 `extract_frame` Skill 经 Registry 执行，限制工件归属、输入与路径；提帧缓存校验 PNG，丢失/零字节/损坏可恢复。审核选定的逐镜头模型贯穿提交、恢复、预算和 MQ；首尾帧参数传入支持的 WAN 适配器，仍受开关与能力目录双重限制，未验证真实画质。
- D3：基于结构化错误区分瞬时错误、内容审核、参数错误、未知提交和永久失败；未知提交停止。下载/轮询恢复复用原 Job / ApiTask / provider task；明确未提交才允许新 attempt。合规改写最多一次，自动修复次数硬上限 2，并受显式修复额度、单镜头额度与 Run 总预算约束；手动重试按报价授权。额度与记录跨版本保留。
- D4：只读报价绑定版本、任务/工件及当前费用；`only / cascade / cancel` 显式选择，按实际尾帧依赖闭包重做，其他成功/失败/未知记录保留。连续 only 保留原始下游来源，报价包含未完成镜头的继续费用。可回到审核 A 修改计划；成功视频按输入哈希复用，预算只计剩余工作。审核 B 确认后停在 `videos_approved`，尚未拼接交付。
- D5：新增生产看板，展示镜头状态、串并行依赖、预计/累计/修复支出、保留下游风险与报价确认；支持鉴权视频预览/下载、局部重试、三种重做选择及审核 B，文案接入 zh/en。只做功能和最小接线，保留 Claude 的 StoryboardEditor 与 storyboard-messages 原样。

集成与安全修复：
- 修复历史审核 checkpoint 接续时误读旧 checkpoint 的问题；报价/预算/版本错误保持可恢复的审核状态。无效空提示词草稿可读取/编辑，不能启动生产。
- 修复真实后台线程的下载恢复竞态：旧 Job 终态不能提前结束刚启动的恢复；同时覆盖本地队列及 MQ dispatch/API 在途状态。已授权任务启动后若动作收据写入前崩溃，恢复时即使报价上涨，也先收敛在途工作，禁止未授权的新支出。
- 审核 B 意图落库后发生崩溃，重放仍重新校验当前版本、图片与视频完整性；不能凭旧意图通过缺失文件的审核。
- 本地尾帧失败/缓存丢失可对 blocked 子镜头显式恢复，不重交源视频；崩溃重放不重复创建提帧 attempt，费用报价包含后续视频。
- 离线攻击回归复现并封堵公共 Skill / run-* / rerun_node 绕过生产报价授权：服务端派发许可精确绑定 Job 与执行参数，不接受请求字段。原 key、新 key、去标记 PATCH、提示词漂移等均覆盖；普通经典 Job 保持可用。
- 封堵共享模板 ZIP、历史同步提示词和公共 Job/提示词列表的私有内容泄漏。私有 Job 停止向公共模板同步提示词；内部/私有模板不公开打包、下载或聚合，覆盖历史 ZIP、数字别名及无效 job_id 参数旁路。显式 Job 内容按所有者读取，列表先过滤再分页；经典公共模板包及所有者 Job 包仍可用。

验证：
- **后端最终完整回归：920 passed, 38 warnings in 882.80s（14分42秒）**，固定验收代码 `7333677`；相比 C-Gate 的 730 项增加 190 项。覆盖经典 DAG/API、MQ、Simple、remix、A/B/C 与本轮 D。38 条警告来自测试用短 JWT 密钥（原 API smoke 34 条，加预算审核测试 4 条），没有使用真实密钥。
- 首轮集成为 827 passed / 3 failed：两项旧 C 测试假定 video 不是合法任务类型、模型没有首尾能力，已更新为真实无效目标与开关×能力四组合；另一项空提示词草稿详情返回 422，已修复为可编辑。修复后相关 64 项通过，最终全量全绿。
- D1 十镜头实际 Mock 验收包含并发上限、尾帧依赖、重启去重及 MQ/非 MQ 产物/账本一致；10 次视频、4 次提帧、50 演示 credits。首尾帧候选不引入视频间依赖。D2 另用有效小 MP4 与本地 FFmpeg 验证首/尾帧，Mock 白图不作为真实质量证据。
- 故障注入包含五类失败、未知停止、修复次数/费用上限、提交与收据间崩溃、价格变化、文件丢失/损坏、真实线程门闩竞态和动作幂等；修复与授权路径均有账本/提交次数断言。
- 前端 `node --test tests/*.test.js`：**29 passed**；`npm run build` 通过。
- 真实 Mock 浏览器联调：临时 SQLite/存储、独立 5078 / 5198、鉴权开启。120 秒四镜头任务完成 only / cascade / cancel：视频调用从 4 次到 7 次，视频估算支出 120 → 150 → 210，旧下游提示与新版本行为符合报价；鉴权预览/下载 200，匿名 401。
- 浏览器首次免费恢复暴露上述竞态，故障 Run `agent_0f3b1f153eab4d7c` 保留原现场，未用付费重做掩盖。修复后新 Run `agent_356e4557133d402e` 完成 15 秒四镜头：删除一个本地文件 → 报价 0 → 原任务免费恢复 → 审核 B → `videos_approved`。始终 4 次视频调用，视频 15 / Run 合计 30 / 修复 0 演示 credits，审核 B 无额外生成。
- 浏览器业务交互无 JS 错误/警告；亮色及暗色 CSS 验证、400px 组件/弹窗无内部溢出。**全局固定侧栏仍导致手机整页内容裁切**，保持 Claude 的已知美化事项，不声称整页移动端已验收通过。故意匿名请求的 401 与停服务后的网络错误另计。
- 临时服务与本轮浏览器页均已关闭，5078 / 5198 无监听。Mock 审计资料保留在 `%TEMP%/cinecrew-d5-ui-20261018/{smoke.db,summary.json}`；另有私有导出漏洞复现库 `%TEMP%/cinecrew-private-export-review-oa0o0vxa`，均不属于部署依赖。
- 全程 Mock / 隔离 SQLite；没有付费模型调用、真实 MySQL/Redis 部署验证、真实库迁移或真实 .env 修改。没有修改 Claude 的界面美化文件、AGENTS.md / CLAUDE.md。主目录原有未跟踪 `AI_Video_Factory_Technical_Notes_CN.md` 保留；`git diff --check` 通过。

给 Claude / 下一步：
- **D-Gate 与界面美化**：重点评审生产状态/报价与级联表达、D-017–D-022、公共派发和私有导出边界，复用当前 ProductionBoard 功能接线；全局移动端侧栏与主题初始化继续由 Claude 处理。
- 新链路默认仍关闭：隔离 Mock 联调需同时设置 `AGENT_STORY_V2_ENABLED=true`、`AGENT_STORY_PRODUCTION_ENABLED=true`，使用 `MODEL_ADAPTER_MODE=mock` 与临时 SQLite/存储。默认并行上限 3、自动修复最多 2 次；开始生产的显式修复额度默认 0，手动重试单独确认报价。`AGENT_ENABLE_KEYFRAME_BRIDGE=false` 仍保持默认关闭。
- **Phase E 接入点是 videos_approved**：尚未实现本轮新链路的默认不压缩、拼接与最终交付；不要将审核 B 完成显示成成片交付成功。真实首尾帧效果、角色视觉一致性和服务商费用仍需后续单独批准的评测。
- 本轮没有新增必须由用户决定的事项；不自动进入 E/F，不启动付费测试。


## 2026-10-18 · Codex · E1–E4 开始
状态：进行中。已读取最新D交接、任务看板与契约；追加D-023及E章后开始实现。
分支：四个独立Codex工作树分别使用agent-v2/E1、E2、E3、E4，从feat/agent-v2 @ d06b3f4切出。主目录在Claude的agent-v2/D-Gate，不切换/修改其工作树。
范围：Agent压缩策略、拼接与可选副本、结构质检/Editor/素材包、交付功能界面。D-Gate与美化保持Claude负责。
验证：仅Mock、隔离SQLite/存储和本地FFmpeg有效测试片；不改真实.env、不做付费调用、推送或PR。完成后更新验收与交接。



## 2026-10-18 · Codex · Phase E 集成验收中
状态：E1–E4实现已整合，仍待完整回归与浏览器验收结束；不作为最终交付。
冻结代码：agent-v2/E1 @ 16e2c60（此后本条仅文档）。已合入E2/E3/E4功能，主目录仍由Claude在agent-v2/D-Gate工作，未移动其分支或修改其未提交文件。
已验证：集成相关61项通过；公共授权与双开关边界8项通过；前端39项通过、npm run build通过。完整后端Mock/隔离SQLite回归进行中。
内容：默认保留Agent源片、私有零费用拼接与可选压缩副本、独立源规格质检、素材ZIP、Editor断点恢复、交付组件。有效MP4/WebM仅本地生成测试片，Mock输出有显式标记，未调用真实生成服务。
下一步：读取完整回归结果，完成鉴权浏览器交付/恢复验收，更新PLAN与最终交接；E-Gate留Claude，不进入F。独立工作树缺node_modules入口已用Junction复用现有依赖，未安装新包或修改真实.env。

## 2026-10-18 · Claude · D-Gate 评审
状态：完成，分支 `agent-v2/D-Gate`，已合入本地 `feat/agent-v2`。按用户指示，本轮跳过前端美化。
评审结论：通过（修复 1 处）。
- 契约与决策：D 章与 D-017–D-022 清晰，实现一致。显式 `start_production` 授权、默认修复额度 0、未知提交一律停止、报价编号绑定版本/任务指纹/修复回执并在执行前重算、cascade 只取真实尾帧依赖闭包、only 保留旧下游并记录风险。
- 调度：`production_engine.tick_production` 以持久任务驱动，限并发、依赖失败只阻塞后代；`recover_job` 只处理非终态 Job，付费节点无服务商任务号即停止，不会重交。
- 公共入口：生产 Job 的派发许可是 ContextVar，按 Job + 执行参数精确匹配，只在服务端同步准入时存在；公共 Skill、run-*、rerun_node 均拒绝（UNSAFE_RETRY）。`validate_job` 恢复时重新核对模型、参数、提示词与首尾帧来源。
- 修复：`production_engine._submit` 原先把所有非参数类本地错误记为 `submit_unknown`，包括注册表在预算/权限检查阶段已拒绝、账本状态 `rejected` 且无 Job 的调用。结果是该镜头永久停止、手动重试和重做报价都返回 UNSAFE_RETRY，且新版本会继承这条“未知”记录。现在只有账本证明没有启动 Job（无记录，或 `rejected` 且按调用编号找不到 Job）时记为 `permanent / not_submitted / stop`，可通过重做或改计划恢复；其他情况仍保守记为未知。新增 `test_registry_rejection_is_not_an_unknown_submission`（修复前失败、修复后通过）。
- 测试：Codex 交付代码完整回归 **920 passed**（23 分 17 秒）；修复后生产相关 166 passed（含新增 1 项，合计 921）。
- 隔离 Mock 实测（临时 SQLite、端口 5057 / 5176、鉴权开启、Story v2 与生产开关开启）：一分钟长片 → 角色 → 分镜确认 → 生产看板 → 开始生产（修复额度 0）→ 4 镜头完成（60 credits）→ s03 重做报价（only 15 / cascade s03→s04 30）→ cascade 超出剩余预算被服务器拒绝、无任何调用 → only 执行生成版本 3，s04 标为保留旧下游 → 审核 B → `videos_approved`。账本：animate_shot 5 次共 75 credits、extract_frame 1 次。生产视频匿名 401、所有者 200、其他用户 404；其他用户的提示词与作业列表看不到该 Run 内容。进程已停止，`.claude/launch.json` 已删除。
非阻塞问题（留给美化或后续）：
1. 报价与超预算表达：报价弹窗没有对比剩余预算，cascade 超预算时直到确认才失败，且界面直接显示后端英文原文（含内部 Run 编号 `Budget exceeded for scope 'agent_…'`）。建议报价返回 `exceeds_budget` 或前端按 `remaining_budget` 提前禁用并给出中文说明；错误码映射为本地文案。
2. 看板文案：开始生产前各镜头显示“排队待执行”（实际尚未排队）；新版本中重做的镜头显示“第 1 次执行”（按版本计数），用户可能以为未重做。
3. 性能：`private_views.private_jobs()` 每次列表请求读取全部私有 Job 并逐个校验所有者，数据量增长后会变慢；建议改为 SQL 过滤（所有者字段或 Run 所有者子查询）。
4. 已知：手机端全局侧栏导致整页裁切（美化事项）。
给 Codex / 下一步：
- Phase E 从 `videos_approved` 接续（拼接、默认不压缩、交付）。拼接时注意 `kept_downstream`：保留的旧下游片段与新上游可能不连贯，交付前应在界面再次提示。
- 若后续新增提交前的服务端拒绝码，沿用本次规则：以账本与 Job 记录判断是否提交，不用错误类别猜测。
需要用户决定：无新增。生产看板美化待用户安排。


## 2026-10-18 · Codex · E1–E4 完成

状态：功能与本轮 Mock 验收完成，合入本地 `feat/agent-v2`；E-Gate 与界面美化留 Claude，不进入 F。
分支与提交：`agent-v2/E1`、`E2`、`E3`、`E4` 均保留。整合代码 `ac2f264`；包含 Claude D-Gate `034ff35 / 0ec8c99`，未改写其生产状态修复。此后仅本条文档、看板与 QC 文件末尾空行整理。没有推送远程或创建 PR。

完成内容：
- E1（`9f71bbe / 7af8d0e / 66f8007`）：Agent Job 冻结输出策略，默认不额外压缩；明确要求才允许压缩。故事片源镜头始终保留，压缩只在最终另产副本。线程与共用 MQ 下载使用同一策略；经典 Job 仍遵循原全局配置。Registry 注册 compose_video、probe_media、qc_video、package_story，共 20 个 Skill。
- E2（`e675828 / 3688929`）：使用批准的原片，拒绝缺失原件时回退压缩代理；按源工件顺序与 SHA-256 冻结授权。充分一致的编码参数/流布局才 stream-copy，否则按首镜头规格保比例补边、高质量重编码，音频补静音并对齐视频时长；不将重编码称为无损。显式压缩副本与主片独立保存，临时文件原子落盘，源文件不覆盖。
- E3（`9f186df / 44c2756 / 1032209`）：确定性 Editor 经 Registry 完成探测、拼接、结构质检和素材包，全部完成才 success。逐源/主片/压缩副本完整解码，按批准镜头时长而非最初目标检查总时长，画幅与帧率独立取批准源规格。ZIP 保留原镜头容器后缀与字节，包含主片、可选副本、计划/故事/QC/估算费用；不导出密钥、绝对路径或外部下载地址。
- E4（`365886a / 084afef / e45ac36`）：成片播放器、鉴权主片/压缩副本/素材包下载、阶段与失败展示、免费恢复。视频按需获取鉴权 blob，并清理取消请求和 object URL；只接受匹配工件 ID 的本地接口地址。保留旧下游镜头的连贯性风险在交付区再次提示（承接 Claude 最新交接），不增加审核门槛，不改变其组件样式。

授权与恢复：
- 新审核 B 在交付开关开启时接续 Editor；历史 videos_approved 需显式 start_delivery。关闭开关保持原终点，内部 Skill 同样校验 Story v2 与交付开关。
- 服务端 delivery_version、批准版本、源摘要、完整输入及 Run 归属在执行和幂等重放时均校验；公共请求不能伪造 Editor 上下文。主片/ZIP 非空损坏也会隐藏下载并允许恢复，不靠“文件存在”冒充成功。
- 崩溃恢复复用持久工具回执；retry 意图冻结 target_attempt，收据落库前崩溃不重复加次数。仅 ZIP 缺失时复用有效主片和副本。恢复只执行本地步骤，不新增模型生成；源片缺失或摘要变化时停止，需要恢复批准的原字节。
- E 章契约与 D-023/D-024 记录了上述边界；没有新增数据库迁移。零 credits 仅指没有新增模型费用，仍有本地 CPU/磁盘成本。

验证：
- **完整后端回归：991 passed, 38 warnings in 1592.80s（26分32秒）**，冻结代码 `16e2c60`，退出码 0；相比 D 基线 920 项新增 71 项。覆盖经典 DAG/API、MQ、Simple、remix、A–D 与本轮交付。38 条警告仍来自测试用短 JWT 密钥（API smoke 34、预算审核 4）。
- 全量运行期间 Claude 合入 D-Gate。另在合并代码 `6d0bf04`（16e2c60 + 0ec8c99）跑全部 `test_production*.py` 及交付图、恢复、公共边界：**148 passed in 376.01s**，含 Claude 新增的拒绝提交回归。两组有重叠，不相加冒充总用例数；未重复跑第二轮全量。最终后端与该集成版本一致，仅删除一个 EOF 多余空行。
- 最终前端 `e45ac36`：**40 passed**，`npm run build` 通过。无新增依赖；独立工作树通过忽略的 node_modules Junction 复用本机现有依赖。
- 本地有效 MP4/WebM 覆盖同规格 copy、异规格规范化、画面顺序、混合音频及长音轨对齐、压缩副本、错时长/画幅/空文件/损坏/源漂移、归档字节保留；Mock 哨兵只精确识别后生成带示意标识的有效视频，不将任意坏视频当 Mock。
- 真实浏览器 Mock 联调：临时 SQLite/存储，阻断外网 HTTP，鉴权开启。120 秒需求“请压缩”自然解析 compress_output=true；4×30秒源镜头完成审核 B，主片实际 **119.84秒 / 320×180 / 25fps** 可播放；主片、压缩副本、ZIP 均实际点击下载。最终 `16e2c60` 上丢失 ZIP 后恢复，主片/副本保持原件；ZIP CRC 正常、18 项 QC 通过，下载视频与包内字节一致。
- 120秒 Run `agent_eb972b5fef5e4560` 始终 4 次 animate_shot、8 条 ApiTask、135 演示 credits；交付/重试没有增加模型次数或费用。另一个 Run 覆盖非空损坏主片恢复与模拟持久 QC 失败的界面停止，始终 4 次视频、8 条 ApiTask、30 演示 credits。匿名主片预览及三类下载均 401。历史 videos_approved 的显式开始入口也已验证。
- 联调边界如实保留：首轮临时脚本晚于 Config 导入才设置 FFmpeg，触发 MEDIA_TOOL_UNAVAILABLE；改用 config_overrides 后恢复，这是测试启动配置问题。“请提供压缩视频副本”未被 Mock 的固定关键词解析器识别，该 Run 仅用于历史入口测试；压缩端到端证据来自新的“请压缩”120秒 Run。注入持久 QC=false 的浏览器操作是界面故障模拟，不代表真实编码质检证据。
- 亮色/暗色 CSS 与组件 360px 宽度通过，内部无溢出。**400px 整页仍被既有全局侧栏裁切**，留 Claude 的美化范围，不声称整页移动端验收通过。StoryboardEditor、storyboard-messages、ProductionBoard、AGENTS.md、CLAUDE.md 没有本轮修改。
- 临时 5078 / 5198 服务与本轮浏览器页已关闭，无监听。审计保留在 `C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-e4-ui-20261018/`：`acceptance-summary.json`、`final-audit.json`、`media-validation.json`、`cleanup.json`、`smoke.db` 与下载样本。无真实 .env 修改、MySQL/Redis 部署验证、付费调用或真实库迁移。
- 开发在独立工作树完成；Claude 的 D-Gate 代码与完整交接已保留。其主目录切回 feat 后仅在已跟踪文件干净时快进集成；原未跟踪 `AI_Video_Factory_Technical_Notes_CN.md` 保留。最终差异检查通过。

给 Claude / 下一步：
- E-Gate 可评审 D-023/D-024、源摘要授权、结构 QC、原片/主片/压缩副本语义、恢复与公开接口边界；全链路证据可复用。原 D-Gate 的预算提示、列表性能与全局侧栏事项保持原记录，未扩展处理。
- 隔离 Mock 联调需同时开启 `AGENT_STORY_V2_ENABLED=true`、`AGENT_STORY_PRODUCTION_ENABLED=true`、`AGENT_STORY_DELIVERY_ENABLED=true`，配合 `MODEL_ADAPTER_MODE=mock`、临时 SQLite/存储和可用 FFmpeg（`FFMPEG_BINARY` 或 PATH；必须在应用配置导入前设置，或用 config_overrides）。这三个新链路开关默认仍关闭，真实 .env 未自动启用。历史视频审核完成的 Run 使用 start_delivery。
- 真实模型画质、角色一致性、首尾帧质量、真实费用及高分辨率长片的负载未评测；结构 QC 不能替代视觉评审。F 与任何付费测试等待新的用户指令。本轮没有新增必须由用户决定的事项。

## 2026-10-18 · Claude · E-Gate 评审
状态：完成，分支 `agent-v2/E-Gate`，已合入本地 `feat/agent-v2`。
评审结论：通过（修复 1 处性能问题）。
- 契约与决策：E 章与 D-023 / D-024 和实现一致。交付开关默认关闭；历史 `videos_approved` 需显式 `start_delivery`；交付授权冻结源工件顺序与 `source_sha256`，恢复时不接受源漂移；Editor 全程经 Registry，零模型费用。
- 媒体处理：FFmpeg 参数以列表传递；stream-copy 用受控相对文件名并开启 concat 安全模式与协议白名单；规范化滤镜写入脚本文件；临时目录生成后原子替换，源文件不被覆盖；原件缺失不回退压缩代理。
- 质检：源镜头与主片、压缩副本均完整解码，时长按批准分镜比较，画幅与帧率按首镜头规格。素材包过滤密钥、路径与外部链接字段。
- 前端：下载与预览只接受与工件编号完全匹配的本地接口地址，按需取鉴权 blob 并在切换与卸载时释放。
- 修复：`delivery.public_delivery` 每次序列化 Run 都会对所有批准源视频完整计算约 3 遍 SHA-256，再加主片、压缩副本、素材包摘要和一次 `ZipFile.testzip()`（整包解压校验）。Agent Studio 每 3 秒轮询 Run **列表**，列表会序列化全部 Run，所以真实成片下每次轮询要读取所有已交付 Run 的全部媒体字节（Mock 文件很小，测试与联调看不出来）。新增 `app/services/file_fingerprint.py`：按文件身份（解析路径、大小、mtime_ns、inode）缓存摘要和 ZIP 完整性结果，读取期间文件变化则不缓存。`delivery_policy.source_hashes` / `resolve_delivery_artifact` 与 `package_story.cached_output_is_valid` 改用它。替换、改写或截断文件都会改变身份，校验语义不变。新增 `test_polled_delivery_view_does_not_rehash_unchanged_media`：成功交付后 5 次读取视图与列表时，`hashlib.file_digest` 和 `testzip` 调用均为 0；同尺寸原地改写主片后仍隐藏下载并允许恢复。修复前失败、修复后通过。
- 文档：CONTRACTS 顶部章节状态行补上 D、E 已定稿。
- 测试：Codex 交付代码完整回归 **992 passed**（26 分 38 秒，含 D-Gate 新增 1 项）；修复后交付相关 52 passed（含新增 1 项，合计 993）。
- 隔离实测（临时 SQLite、端口 5058 / 5177、鉴权开启、三个新链路开关开启、真实 FFmpeg）：脚本驱动一分钟长片 → 角色 → 分镜 → 生产 → 审核 B → 自动交付 → success。主片 59.84 秒 / 320×180 / 25fps，规范化拼接，结构质检 14 项全过，素材包生成。主片与 ZIP 匿名下载 401、本人 200；浏览器交付面板显示正确，成片以鉴权 blob 加载并可播放，无控制台错误。账本：animate_shot 4 次 60 credits；compose / probe ×4 / qc / package 均 0 credits，交付没有新增模型调用。进程已停止，`.claude/launch.json` 已删除。
非阻塞问题：
1. 交付提示混合语言：拼接与 Mock 两条警告是后端英文原文（如 “Source formats differed; normalized…”），与中文界面混排。建议后端返回警告码，由前端本地化。
2. Mock 示意片都是 320×180 / 25fps，仍走规范化并提示“源格式不一致”，措辞对 Mock 不准确（真实素材下语义正确）。
3. D-Gate 记录的报价超预算提示、看板文案、私有列表性能与全局侧栏问题保持原状。
给 Codex / 下一步：
- 后续凡是在 GET 或轮询路径里校验文件完整性，请用 `file_fingerprint.cached_digest` / `memoized`，不要每次全量读取。
- Phase F 尚未开始；F 章契约与任何付费评测都需要用户新的指令。
需要用户决定：无新增。

