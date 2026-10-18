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


## 2026-10-18 · Codex · M0 完成，模型升级与任务中心开始
状态：本轮用户追加工作，暂停后续Agent阶段；M/T章与D-025已写入，M1–M3/T1并行推进。官网确认五模型存在，价格/模型质量/账号开通情况未实测。
分工：M1目录/选型/费用；M2 Wan3；M3 Qwen3/DeepSeek与集成；T1任务中心功能均由Codex独立工作树实现。Claude主目录agent-v2/E-Gate及其未提交交付修复不触碰；E-Gate、美化与MT-Gate保留Claude。
明确约束：依用户最新要求仍使用旧DASHSCOPE_API_BASE_URL / DASHSCOPE_OPENAI_BASE_URL，不引入workspace-id。新模型不替换默认。官方能力与当前Agent可用模式分列，首尾质量未实测。模型价格仍为演示credits；Wan3参考视频按输入+输出秒数估算，不能只算新增延长段。
验证计划：Mock HTTP请求体与旧URL、隔离SQLite选择/预算/队列权限回归、前端测试/build，随后集成检查；无真实.env修改、付费、推送或PR。任务中心是业务只读页，不是Redis管理台；本人Agent+共享经典，未知Worker健康如实展示。
给Claude：请先读M/T章与D-025。新目录及任务中心接口将在独立任务分支合入feat后提供SHA；当前无需修改Agent图/ProductionBoard/DeliveryPanel或抢占上述文件。本记录后续会追加实际验收与剩余限制。

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

## 2026-10-18 · Codex · M1–M3 / T1 完成

状态：模型升级与任务中心功能、Mock 集成验收完成；MT-Gate 与界面美化留 Claude，不进入 Phase F 或付费评测。
分支与提交：保留 `agent-v2/M1`、`M2`、`M3`、`T1`。冻结验收代码为 `agent-v2/M3 @ 7498618`；已完整保留 Claude E-Gate `5396198 / 30560e0`，后续仅 README、本条交接与 PLAN 文档。本条所属文档提交为本轮交付提交，供本地 `feat/agent-v2` 快进集成；不推送、不创建 PR。

完成内容：
- M1（`76610ef / af55b83`）：新增 qwen-image-3.0、qwen-image-3.0-pro、wan3.0-video、wan3.0-video-prime、deepseek-v4.1-flash。保留旧 task_type，按已接入 modes 扩展 API/Skill/Agent/经典页面筛选；精确模型 ID 优先，系列匹配不串到相似前缀。没有切换任何 DEFAULT_*。Qwen 动态尺寸/图片数量、Wan 固定2–30秒及随机种子边界均校验；prime 标为高速，不承诺更高画质。
- M2（`b69dba3 / b02b37a`）：Wan3 单一真实 ID 接文生视频、首帧、首尾候选、图片参考，复用提交/轮询/下载与共用 MQ。请求使用 input.prompt + media，不发送虚构的任务类型或型号别名；经典反向提示词转换为正向文本中的“避免出现”段落，仍要求正向文本非空。模型默认参数先合并，再由显式参数覆盖；首尾与参考媒体互斥、资源数量/图片完整解码均在提交前检查。
- M3（`24ed7f8 / 38e22c4 / 1792ad1`）：Qwen3 异步 messages 协议，文生图/图像编辑、多图输出复用既有 output_slots 与下载链路；支持 n=1–6（Agent Skill仍最多4），参考图最多3张。拒绝不支持的参数及 i2i 的 prompt_extend_mode=agent，验证完整图片解码，含截断 JPEG 回归。DeepSeek v4.1 Flash 走百炼 Key/兼容接口，结构化调用也继承默认 enable_thinking=false；不误用 DeepSeek 自营凭据。
- **按用户要求沿用旧 URL**：图像 `/api/v1/services/aigc/image-generation/generation`，视频 `/api/v1/services/aigc/video-generation/video-synthesis`，轮询 `/api/v1/tasks/{id}`；文本使用现有 compatible-mode/v1。仍读取 DASHSCOPE_API_BASE_URL / DASHSCOPE_OPENAI_BASE_URL，不引入 Workspace ID。新适配器独立请求头，不给新模型继承旧内容检查开关；旧适配器行为保留。
- 费用：Wan3 使用分辨率对应的每秒演示 credits；公式为（受信任的输入视频秒数 + 输出秒数×输出数量）×费率。输入时长只接受服务端关键字参数，不信任用户 params；当前 Agent 无视频参考所以为0。非法时长/未知分档拒绝；保留旧估算回退。前端分镜估算同步分档。官方人民币价格、图像输入计价和 LLM token 账单均不与演示 credits 混为一谈。
- T1（`feea8f9`）：新增 `/task-center`、列表/详情 GET API、SQL 权限过滤与稳定分页。范围是本人 Agent + 现有共享经典作业；内部 Job 归并到父 Run，只统计当前版本/轮次/attempt，上传与孤立私有 Job 不进入共享列表。展示提交、服务商生成、下载、本地交付和等待依赖/授权/核实；未知提交归为需处理。无 Worker 心跳则显示未知，不编造队列名次或 ETA。
- 任务中心 GET 只读数据库，不调用完整 Run serialize、文件校验、Redis 或工具。旧 `/api/jobs/queue/status` 也补上所有者过滤和字段脱敏，保留 enabled/mode/counts/items 外层结构；不再暴露内部命令。前端5秒刷新、隐藏/卸载停止、失败保留旧数据并标记过期，操作返回原工作页。
- README 补充新模型与任务中心使用说明。没有真实数据库迁移或目录写入；API 启动种子/现有 seed-defaults 接口可在用户环境补目录，旧自定义价格/能力按原种子逻辑保留，默认参数/schema 仍会更新，操作前应保留自定义配置。

验收与审计：
- **完整后端回归1165 passed**：冻结代码 `7498618` 的77个测试文件分成3个互不重叠分片，342 / 446 / 377项，分别约580.91 / 620.48 / 700.00秒，均退出0。已解析JUnit核对没有遗漏、重复、失败或跳过。相对 E-Gate 的993项新增172项；定向回归与全量重叠，不相加计数。
- 45条警告：38条已有测试短JWT密钥警告，7条因本次导出JUnit触发的 record_property/xunit2 兼容警告。首轮因未激活环境的PATH缺少FFmpeg而停止；重新在配置导入前设置本机已有 `FFMPEG_BINARY` 后，完整三片从头运行通过，没有安装新依赖或修改应用配置。失败首轮不作为验收结果。
- 全量清单、JUnit与汇总：`C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-mt-regression-kgnztpwb/` 的 manifest.json、verified-shard-0/1/2.xml、acceptance-summary.json。使用 Conda video-factory Python；FFmpeg 来自主目录 .venv 中已有 imageio_ffmpeg 二进制。临时路径仅为本机证据，不是运行依赖。
- 新增协议与集成测试覆盖旧域名/headers/payload、模型默认参数、正确百炼凭据、MQ/非MQ、三张图片输出、三类经典视频模式、首尾、系列限制、分档费用、幂等和非法资源；仅 Stub HTTP。其余全量覆盖经典19节点DAG、旧Agent、A–E与本轮任务中心。没有真实供应商请求。
- **前端50项通过、npm run build通过**。任务中心浏览器验收代码 `1756d76` 与冻结版本 `7498618` 的 Git tree 完全相同（f64bc18a）。临时 SQLite/存储、鉴权开启、无执行器、阻断外网；父项分页20+8无重复、24镜头分页20+4，来源/状态/搜索、待依赖/待授权/未知提交/本地质检显示正确；注入503后保留4条旧记录并显示过期。
- 实际离开路由后22.6秒内 task-center GET 为0；浏览器工具切标签仍报告visible，**真实后台隐藏未验收**，隐藏取消/恢复由确定性前端测试覆盖。匿名任务中心401；后端回归覆盖双用户隔离与经典共享。只读浏览前后均26 Jobs /8 ApiTasks /2条种子ToolInvocation /0 Outbox /0 credits。
- 浏览器无最终控制台错误，中文/英文检查通过。**400px仍受原有260px侧栏与全局padding挤压，任务中心仅剩约70px可用宽度，不声称完整移动端通过**；没有修改 Claude 的全局布局。临时5086/5206服务和本轮标签已关闭、无监听。证据：`C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-t1-ui-20261018/` 的 acceptance-summary.json、cleanup.json、requests.jsonl、smoke.db及截图。
- 全程隔离 SQLite / Mock / Stub，无真实 MySQL/Redis部署、付费调用、真实.env修改或新数据库迁移。AGENTS.md / CLAUDE.md、ProductionBoard、DeliveryPanel 与 Claude E-Gate 文件没有本轮重写；主目录原有未跟踪技术笔记保留。

给 Claude / 下一步：
1. **MT-Gate**：先读 D-025 与 CONTRACTS M/T；重点审查多模式筛选、精确ID与系列、默认模型不变、分档计费、多输出恢复和旧queue/status隐私边界，可复用上述全量与浏览器证据。任务中心核心文件为 api/task_center.py、services/task_center_query.py / task_center_service.py、TaskCenterView.vue、components/task-center/；不要将旧 queue/status 的内部命令恢复到公开响应。
2. **界面美化**：任务中心已有功能接线，继续由 Claude 负责；优先处理既有移动端全局侧栏，沿用 E-Gate 留下的预算提示、警告本地化等事项。模型页面如展示官方能力，必须同时区分“已接入”与“未开放”，不能把 provider_capabilities 当作 Agent 许可。
3. **未开放能力**：所有 reference_video 在适配器明确拒绝；视频编辑/延长尚需受控输入、完整输入时长计费、计划审批和恢复契约。高级媒体仅有适配器级受控 WAV（总1–15秒）、TXT/MD与public link支持；远程音频/文件、MP3与分页文档拒绝，当前没有相应公共 Agent Skill。Agent 仍只能使用本轮明确接通的生成模式，智能时长-1不开放。
4. 首尾候选仍受 AGENT_ENABLE_KEYFRAME_BRIDGE 控制、默认关闭；未实测质量。五模型在真实账号与旧域名下的可用性、效果、时长和费用尚未付费验证。本轮不自动进入F、不更换默认模型；后续真实测试需用户单独批准。
需要用户决定：本轮无新增阻塞项；真实单价与后续付费测试仍待明确安排。

## 2026-10-18 · Codex · W0 完成，Wan3 Agent 贯通开始
状态：D-026及W章已定稿，W1–W4按独立工作树并行推进。
分支：W0从feat/agent-v2 @35edc68切出；后续媒体W1、规划W2、执行W3、功能界面W4均Codex负责。主目录留Claude；W-Gate和美化不抢占。
范围：新增video_transform(reference/edit/extend)，图片/视频/音频/文档/网页快照；旧Simple/remix/story语义不改。网页URL写入文本并冻结正文TXT；文档支持TXT/MD/PDF。输入全片不自动裁切，延长返回最终整段不拼接，费用I+G按秒。
安全边界：先核验并冻结素材/价格，再显式审核；Registry、Job、MQ提交均复验，公共重跑不能绕过，未知提交停止。旧URL/no Workspace ID保持。本轮无付费，Mock/Stub+临时SQLite；不改真实.env。
给Claude：请先看D-026/W章与W1–W4文件范围；Composer/AgentStudio仅新功能接线，ProductionBoard/StoryboardEditor/全局布局不动。最终交接会提供验收与提交。用户已明确授权完成后推送GitHub；仅推feat/agent-v2到现有origin，不强推main。清理只删除可证明冗余的根空package-lock.json，保留前端锁和未跟踪技术笔记。


## 2026-10-18 · Codex · W1–W4 完成与交付验收
状态：完成；W-Gate、MT-Gate及界面美化继续由Claude负责，未进入Phase F，未进行付费调用。
分支与提交：W1/W2/W4独立分支已集成到agent-v2/W3；最终后端验收版本205d57b，审核说明修正1981a9b。交付分支为本地feat/agent-v2与现有origin同名分支；按用户授权普通推送，不更新main或强推。

完成内容：
- W1：受控图片/视频/音频/文档引用，上传新增WAV/MP3与TXT/MD/PDF；完整解码、真实时长、来源归属、格式/数量/尺寸/体积限制；PDF固定pypdf==6.21.1，在有界子进程检查真实页树。网页仅取用户原始文本中的完整URL，经SSRF安全抓取生成同Run私有正文TXT快照，不把活动网页交给模型。网页快照与文档共用一个file槽位；音频不宣称已转写，PDF不宣称已理解正文。
- W2：独立video_transform配方支持reference/edit/extend；未指定仍采用服务器R2V默认，不支持则询问，不静默换型号。仅已接通的DashScope/Wan3协议可使用；显式系列约束继续有效。用户“再延长N秒”与最终输出G分开，G=ceil(S+N)，完整原片不自动裁切或重复拼接。输入I为全部实际参考视频秒数，I≤15、I+G≤30，G固定2–30整数；费用(I+G)×分辨率每秒credits，仍是演示估算。
- 新只读transform-quote接口重新核验草稿、素材与当前价格，报价不新增Job/Invocation/Outbox。有效计划必须显式审批，即使有自动审批额度；失效/非法草稿保留可编辑，源文件变化或报价过期拒绝提交。
- W3：transform_video只接收plan_hash，实际输入取服务端冻结回执；绑定Run、request_spec、素材摘要、模型/参数、单价、固定幂等key。复用旧R2V节点与共享MQ，NodeRunner和实际POST前均复验。未知提交停止，不自动重交；已有服务商ID只查询/下载恢复，不受之后价格、启用状态或源文件变化阻断，不重新收费。审批回执与checkpoint间隙恢复不新增授权或Job（D-027）。
- 私有agent_transform Job/工件接入已有归属隔离；公开付费Skill、run-*与rerun不能绕过审批，公共工件列表也检查同Run作用域。审批后的队列提示词、参数、素材、provider/adapter漂移均拒绝。Agent默认不额外压缩保持。
- W4：Composer接受音频/文档；审核显示最终整段、源片、追加、全部输入与计费秒数、每秒单价。时长/模型/分辨率/提示词修改后刷新权威报价，失败或未同步时禁审批；结果通过鉴权本地接口。初始规划说明与当前参数/报价明确分开，防止修改6秒后误读原始5秒说明。不改Claude全局布局与美化。
- 审计新增D-028：真实2秒画面+10秒音轨会低估输入，现拒绝音轨终点超过画面加max(0.1,2/fps)秒；等长AAC尾部填充、较短及未越界延迟音轨允许。终点缺失/非法拒绝，video校验缓存升v2；不猜供应商音画不齐的实际账单规则、不裁音轨。
- README中英文及backend README已更新入口、配方、按秒费用、旧URL、格式限制、灰度开关、启动/测试与恢复语义。全局AGENT_MAX_ATTACHMENTS默认8与Wan3每类型/总20上限分别说明。本轮无新迁移，head仍20261018_002。仅删除根目录无package.json对应的空package-lock.json；保留frontend锁、真实.env/storage与未跟踪用户技术笔记。

测试与证据：
- 完整基线9ca604f：82个测试文件分为3个互不重叠分片，共1264项，无跳过。结果381 passed / 423 passed+1 failed / 459 passed；唯一失败为旧API测试固定20个Skill，本轮新增网页快照和视频变换后应为22，已修正。
- 最终后端205d57b：受影响9个测试文件完整复测233 passed / 132.07秒，包含上述失败用例、全部三种变换配方MQ/非MQ、媒体/适配器、网页快照、附件与Registry。新音轨边界比基线增加13例；按JUnit用例ID合并去重后共1277项全部有通过结果，无未解决失败。这是“全量基线+受影响复测”，不是声称最终版本又全量重跑一遍。
- 全量警告45条：38条既有测试短JWT密钥提示，7条JUnit record_property/xunit2兼容提示；最终233项无警告。证据位于C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-w-regression-7au4jeik/，含manifest、3份JUnit、final-affected.xml、acceptance-summary.json。
- 前端63项测试及npm run build通过；最终说明文案修正后再次通过。无新增构建工具。
- 浏览器验收：隔离SQLite/存储、Mock、鉴权开启、5087/5207，实际审核页最终5→6秒、Wan3→Prime、720P→480P；报价未同步及注入503时禁审批，重试后可审批。报价前后均4 Jobs/0 ApiTasks/3 Invocations；批准后成功，仅增加1 transform_video/1 ApiTask，生成16 credits，总账本3→19，使用最终6秒与Prime/480P。源MP4/WAV/TXT通过真实本地上传API进入Run。
- 浏览器文件选择被Edge“允许访问文件URL”权限阻挡，未修改权限；预览/下载事件等待工具挂起后停止，因此不声称原生上传控件、浏览器下载或Mock视频播放已通过。400px仍有原全局260px侧栏限制，不把它算作本轮移动布局通过。证据目录C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-w4-ui-20261018/，包含acceptance-summary.json、cleanup.json、报价截图、前后账本与HTTP记录；实际页面代码为9ca604f。本人预览/下载API均200，匿名均401，媒体GET后Job/Task/账本不变。URL澄清、手机及主题未在本轮浏览器重验；相关确定性功能有自动回归覆盖。自己启动的API PID38244与Vite PID8164已停止，5087/5207无监听。测试Edge标签1818573562因工具无法重新绑定，关闭未确认；未操作用户原标签。
- 所有后端测试强制Mock/Stub、隔离SQLite/存储、阻断模型HTTP；未连接真实MySQL/Redis、未修改真实.env。使用Conda video-factory与已有FFmpeg7.1；pypdf仅装到临时测试PYTHONPATH，未修改用户全局Conda。用户启动新版前需安装更新后的backend/requirements.txt。

给Claude / 下一步：
1. 先读D-026/D-027/D-028与CONTRACTS W；W章取代M/T交接中“全模态/编辑/延长未开放”的历史限制。W-Gate重点审查冻结授权、已受理只读恢复、输入真实秒数与报价失效、公共重跑和素材所有权；可以复用本轮回归证据。
2. 功能入口是transform_plan/director/media/policy/execution、capture_reference_page/transform_video、TransformPlanEditor/TransformResults；共享Job/Queue只加有标记分支，不新增第二套执行队列。Source媒体、server-only transform_hash不可从公共请求自行赋权。
3. 美化与移动端全局侧栏仍由Claude负责；请沿用权威报价的禁审批逻辑，不在前端推算实际媒体秒数、精确排队位次或实时账单；初始规划说明不代表用户编辑后的参数。
4. 默认模型不变，旧DASHSCOPE_API_BASE_URL路径保持且无workspace-id；智能时长-1、超限自动裁片/拼接、自动付费重做、ASR/PDF语义提取未开放。新模型旧URL真实账号可用性、质量及账单尚无付费验证，须用户另批。
需要用户决定：本轮无新增阻塞；后续真实测试与实际单价另行安排。


## 2026-10-18 · Codex · main 合并与 Claude 审计交接
状态：分支同步与交接整理完成；MT-Gate / W-Gate 仍待 Claude 开始，本轮没有执行审计或美化。
分支与基线：agent-v2/merge-main 从 feat/agent-v2 @4c636d1 切出。获取远端后，origin/main @ae4ce97 是 origin/feat/agent-v2 @4c636d1 的祖先（0 / 239个独有提交），可无冲突快进；本次只追加交接文档，不改变应用代码。用户本轮明确授权把 feat/agent-v2 合入 GitHub main，同步两个远端分支，不强推、不删除分支或创建PR。
验证：核对祖先关系、工作树及文档差异；应用代码沿用上一条已验收版本，本轮没有重复运行测试或付费调用。保留主目录未跟踪技术笔记。最终远端提交通过 git ls-remote 与本地核对。

给Claude的执行指令：
- 按AGENTS.md顺序先读本条及上一条W完成记录、M1–M3/T1完成记录，再读PLAN与CONTRACTS M/T/W、DECISIONS D-025–D-028。完成MT-Gate、W-Gate及界面美化，修复发现的问题并补回归；W章取代M/T历史“未接入”限制。不要进入Phase F。
- MT-Gate审查五模型目录、多模式权限/精确系列、默认配置不变、旧URL/no workspace-id、按秒分档与多输出恢复；任务中心的本人Agent+共享经典范围、SQL过滤、只读无副作用、queue/status脱敏和分页/刷新生命周期。
- W-Gate审查reference/edit/extend三配方、完整媒体验证与长音轨边界、(全部输入视频秒数+完整输出秒数)计费、冻结素材/参数/价格、显式审批、过期报价拒绝、审批/检查点崩溃恢复、未知提交不重交、已受理任务仅查询下载、公开Skill/Job重跑与跨Run访问防绕过；MQ和非MQ一致。
- 美化优先任务中心、Agent变换审核/结果页及全局移动侧栏；保持一句话+可选附件入口，明确源片/最终/新增时长和演示credits，保留未同步/失败报价禁批和初始规划说明。完善预算不足、错误/交付警告本地化，验证亮暗主题与约400px手机整页无横向溢出。不要编造队列排名、ETA、Worker健康或真实账单。
- 复用证据但准确描述：MT完整1165项通过；W全量基线1264项含1项旧数量断言失败，修正后受影响233项通过，新增13例后合并去重1277项均有通过结果，不等于最终代码重跑全量。前端最终63项与构建通过。当前既有证据/路径详前两条交接。
- 优先补验：浏览器原生附件上传、实际下载、视频播放，URL澄清交互，任务中心真实后台隐藏停止/恢复轮询，手机布局与亮暗主题。API上传/本人媒体200、匿名401不等同浏览器控件验收；不能把Mock占位视频当画质/播放验证。若需测试播放，使用本地有效示意媒体并明确标注。既有260px侧栏造成400px页面挤压需要修复。
- 只用Mock/Stub与临时SQLite/存储，阻断真实模型HTTP；不改真实.env，不连接真实MySQL/Redis，不进行真实模型、旧URL账号可用性、画质或账单实测。核对新增pypdf==6.21.1和FFmpeg依赖，使用AGENTS指定Conda Python。
- 按任务使用独立工作树/agent-v2任务分支，从最新feat/agent-v2开始；保护他人未提交代码与用户笔记。需要改契约时先写DECISIONS。完成后更新PLAN、追加PROGRESS并提供实际测试数、截图/证据和剩余限制，清理自己启动的服务和测试标签。
- 本轮给Codex的GitHub合并授权不自动扩展到Claude后续工作；Claude默认只本地提交并合入feat/agent-v2，不自行推送、更新远程main或开PR，除非用户另行要求。
需要用户决定：无；可直接将本轮整理的指令发给Claude继续。


## 2026-10-18 · Claude · MT-Gate / W-Gate 审计与电脑端界面美化
状态：完成，分支 `agent-v2/MTW-Gate`，已合入本地 `feat/agent-v2`；未推送。按用户指示优先电脑端，手机端全局侧栏仍未处理。
MT-Gate 结论：通过。
- 模型目录：五个新模型只增不改默认；`supports_task_type` 正向权限只来自已接入的 `capabilities.modes`，`provider_capabilities` 不授予执行许可；系列匹配优先显式 `family`。Wan3 / Qwen3 适配沿用旧 `DASHSCOPE_API_BASE_URL` 路径，无 workspace-id。
- 任务中心：列表与详情均为 SQL 过滤（本人 Agent + 共享经典，私有/孤立/上传 Job 排除），GET 只读；旧 `/api/jobs/queue/status` 改为按所有者过滤且脱敏，前端无页面依赖其旧字段。
- 修复：没有分镜计划的 Agent Run（如视频理解、变换）按内部 Job 节点计进度时，把 19 节点 DAG 中“跳过”的节点也算作完成，界面显示“19 / 19 节点”像已完成。现在 Agent 分支不计跳过节点（经典作业保持原口径）。新增 `test_agent_helper_job_progress_ignores_skipped_dag_nodes`（修复前失败、修复后通过）。
- 待真实环境确认：`current_agent_job` 使用 `json_quote` 与动态 JSON 路径，测试只在 SQLite 上运行（已有 MySQL 编译测试，但未连真实 MySQL 执行）。
W-Gate 结论：通过。
- 冻结授权：`transform_video` 只接收 `plan_hash`；审批回执同步落库并冻结 request_spec；Job 的模型、参数、启用节点、提示词逐项与回执比对；派发许可只在服务端同步准入时存在，公共 Skill / run-* / rerun 拒绝。已有服务商任务号只查询下载（D-027），新的提交重新核验素材摘要与报价。
- 输入：网页 URL 必须出现在用户原文（RequestSpec 校验 + 抓取 Skill 二次校验），复用 B 阶段 SSRF 防护；计费按服务端实测输入秒数 + 完整输出秒数。
- 隔离实测（端口 5059 / 5178、临时 SQLite、Mock、真实 FFmpeg 生成的 5 秒 MP4）：上传视频 → “再延长 5 秒” → 默认 R2V 不支持延长时出现换模型选择题（未静默换型）→ 选 wan3.0-video → 审核页：主源 5 秒、最终 10 秒、输入 5 + 输出 10 = 15 计费秒、30 credits，报价同步后才可批准 → 批准生成 → 结果页浏览器实际点击下载，鉴权请求 200。
界面美化（电脑端；逻辑与接口不变）：
- 任务中心：顶部范围条（MQ 准入、Worker 健康未知、快照时间、刷新转圈）；7 张状态卡兼作筛选（高亮当前、再点取消）；来源分段切换与搜索框；列表改为紧凑行（来源图标、彩色状态胶囊、阶段与等待原因、服务商队列标签、进度条含失败段、更新时间）；选中后详情固定在右侧两栏，子任务为带状态色点的时间线。无计划标题的 Agent Run 显示“未命名创作（尚未生成计划）”——后端按契约 T.1 不返回需求原文，故不能用原文做标题。
- 视频变换审核：操作类型图标与标签、服务器报价卡（报价状态色与图标）、新增“计费秒数条”（输入/输出秒数对照 30 秒总上限与 15 秒输入上限）、提示词与设置分栏、素材卡按类型图标并标出主源、底部操作栏（报价状态、重新报价、放弃、批准）；未同步或失败报价仍禁止批准。结果页卡片化、下载按钮。
- 生产看板与交付面板：统一分镜板的视觉语言（图标头、状态胶囊、统计卡、按状态着色的镜头卡边、模态框）。交付质检折叠为“通过 14 / 14”，下载按钮带图标。
- 遗留问题修复：
  1. （D-Gate）重做报价显示剩余预算，超出的选项标红并写明超出额度，所选范围超预算时禁止确认；判断提取为 `production.js` 的 `exceedsBudget` 并加单元测试。
  2. （D-Gate）开始生产前镜头显示“待开始”，不再显示“排队待执行”；执行次数文案改为“本版第 N 次执行”。
  3. （D/E-Gate）已知错误码（预算不足、报价过期、素材变化、版本冲突等）在界面显示本地化文案，不再透出后端英文与内部 Run 编号（`agent-errors.js`，在 `AgentStudioView.message()` 统一处理）。
  4. （E-Gate）交付提示的两条后端英文警告本地化；Mock 示意片不再提示“源格式不一致”。
- 全局修复：暗色主题此前只有进过“设置”页才生效（设置 store 只在 SettingsView 实例化），刷新任何其他页面都会回到亮色。现在 `main.js` 启动时初始化设置 store。
测试：
- 后端：Codex 最终代码完整回归 **1277 passed**（27 分 53 秒，单次全量，非分片；PYTHONPATH 提供 pypdf，FFMPEG_BINARY 指向本机已有 FFmpeg 7.1），加上本轮新增 1 项合计 1278；任务中心修复后 `test_task_center.py` 33 passed（含新增 1 项）。
- 前端：`node --test tests/*.test.js` 64 passed（新增 1 项）；`npm run build` 通过。
- 浏览器：1440×900 亮色与暗色下任务中心、变换审核/结果、生产看板、交付面板均正常渲染，无控制台错误。服务已停止，`.claude/launch.json` 已删除。
未做 / 限制：
- 手机端整页仍受全局 260px 侧栏挤压（用户指示暂缓）。
- 原生文件选择控件上传、任务中心后台隐藏暂停未在浏览器验证（逻辑有前端单测覆盖）。
- 依赖：后端测试与本机运行需要 `pypdf==6.21.1`（requirements 已声明）；本轮用 Codex 留下的隔离目录 `%TEMP%/cinecrew-w1-pypdf-6.21.1` 通过 PYTHONPATH 提供，未改用户 Conda 环境。用户本机启动新版前需 `pip install -r backend/requirements.txt`。
需要用户决定：无新增。


## 2026-10-18 · Codex · TECH-REPORT
状态：完成；按用户要求仅整理私人技术资料，未推进 Phase F。
分支与基线：agent-v2/TECH-REPORT 从 feat/agent-v2 @6697867 切出；本条所在提交仅包含忽略规则与协作状态，完成后本地合入 feat/agent-v2，不推送。
完成内容：基于 Claude 最新审计与当前代码完成本地私人报告；docs/private/ 已显式加入 .gitignore。报告内容与个人排查线索不进入版本库，未改动应用代码或真实环境文件，保留用户已有未跟踪笔记。
验证：静态核对默认 Skill 清单、报告源码链接及文件行号；复核图编排、费用与恢复语义；git check-ignore 确认报告被忽略，git ls-files 确认未跟踪；git diff --check 通过。没有启动应用、连接真实 MySQL/Redis、重跑应用回归或进行付费调用。历史测试证据保持上一条 Claude 记录的实际口径。
未完成 / 下一步：私人报告已经交付；功能开发停在当前阶段，Phase F 需用户另行安排。
需要对方或用户决定：无新增；私人资料不要使用 git add -f 纳入版本库。

## 2026-10-18 · Claude · V0 Agent v3 契约
状态：完成，分支 `agent-v3/V0`，已合入本地 `feat/agent-v2`；未推送。
背景：用户指出 v2 是“多角色 LLM 编排的工作流”（`graph_v2.route` 按 `recipe_hint` 走五条写死的分支；每个“Agent”只是一次结构化调用；skills 目录实为 ToolSpec），要求做真正的多 Agent 系统，但不能为了展示协作而强行复杂化。这一偏离源自 v2 方案的设计取舍，不是实现缺陷。
完成内容：
- DECISIONS D-029（采用 v3 的总边界）、D-030（真实测试范围：`deepseek-v4.1-flash` 文本、`qwen3.7-plus` 多模态且多图一次调用、少量图片生成、禁止视频生成）、D-031（Codex 承担主要实现，Claude 负责契约/Gate/验收/美化；经典路径按生产意图触发并落到系列 + 模板，排在最后）。
- 方案 r3：`docs/architecture/agent_v3_proposal_claude.md`。
- 契约：`docs/agent_v3/CONTRACTS.md`（V.1–V.15）。主要内容：Tool / Skill / Agent 边界；生成工具禁止对 Agent 可见；`agent_chat` 函数调用与按回合幂等回放；SKILL.md 与 Blueprint；Agent Card、委派、退回、只由 Producer 提问；工作区；开放但受约束的 Plan IR、编译器与 dry-run；通用节点运行时；Plan Patch 与低风险自动授权；额度；API 与配置；测试不变量。
- CLAUDE.md / AGENTS.md：当前工作改为 v3；第 4 条改为“工具调用必须受控、生成类只经批准计划执行”；第 5 条改为按 D-030 执行；分支可用 `agent-v3/<ID>`。
- PLAN：新增“Agent v3”一节（V1–V8 与三次 Gate）。
给 Codex（从 V1 开始）：
- 先读 D-029 – D-031 与 v3 契约 V.1 – V.3、V.15。V1 不改任何 Agent 行为，经典、v1、v2 全量回归必须保持不变；`app.skills` 的 re-export 垫片要覆盖现有全部导入路径。
- `qwen_chat` 的 tools 支持需要兼容 DashScope 兼容接口与 DeepSeek，一次返回多个 tool_calls 时要正确处理。V1 允许做 1–3 次真实函数调用冒烟（`deepseek-v4.1-flash`），用隔离库，并在 PROGRESS 记录次数与费用。
- `analyze_images` 必须把多张图放在一次调用里（D-030）。
- V2 与 V3 可以在 V1 合入后并行。Skill 内容从 v2 现有 INSTRUCTION 与契约迁移，不得编造未实测的能力。
需要用户决定：无。



## 2026-10-18 · Codex · V1 工具层与受控函数调用
状态：完成；实现提交`ca69e13`已本地快进合入`feat/agent-v2`，未推送。最终后端全量1505项通过，前端64项与构建通过。
分支与基线：`agent-v3/V1` 从 `feat/agent-v2 @ a67ffaf` 切出；在既有隔离工作树 `cinecrew-agent-v2-a4` 实现。未改主工作区的用户笔记或私人报告；不推送、不创建PR。
完成内容：
- D-032先明确兼容目录、v3模型默认、回合纠错、token计费与新工具Schema，再更新v3契约V.2/V.3/V.13。此任务只交付V1基础，不提前接入v3图、Agent循环、Plan IR或界面。
- `app.tools` / `app.tools.specs` 为唯一工具实现；`app.skills`及原29个子模块路径保留兼容。旧默认Registry仍22项、原API字段不变，支持旧模块与新模块双向monkeypatch；`build_v3_registry()`私有目录为25项，内部`agent_llm_turn`仅按需在该实例注册。
- ToolSpec增加Agent可见性、计划可执行性、类型化输入输出与Agent说明；启动/注册/导出/执行多处拒绝向Agent开放生成工具。ToolContext增加server字段，公开Skill请求明确拒绝客户端提供caller_agent/delegation_id/agent_step；账本增加两个可空列，迁移`20261018_003`与SchemaService兼容旧库。
- `qwen_chat`透传tools/tool_choice，解析多函数调用、空content、usage与参数错误。工具模式明确禁用HTTP底层重试及重定向，仍沿用旧百炼兼容URL；普通无tools调用行为保留。任一函数错误使整批请求不可执行，纠错helper最多构造两次显式新回合。
- `agent_chat`经Registry按Run/委派/step持久化；已完成响应回放不调用不重复计费，失败/未知回合停止。新调用校验服务端模型、价格与预留，防伪造便宜内部请求。按usage结算，缺失usage保留预留，超额记录实际费用并报错；同Run并发调用先串行预留预算。普通v3工具默认key包含调用Agent和委派身份。
- `ScriptedLLM`支持按(agent,step)脚本、显式耗尽错误和标注Mock的最小完成示例。`analyze_images`支持1–8图一次请求、当前Run归属与返回ID校验、独立vision脚本身份、调用内冻结模型/消息/价格，费用只由外层工具账本结算一次。
- `list_models`仅只读返回启用、Agent可选且适配器已注册的能力/参数/演示价格；`estimate_cost`复用有效参数、系列约束与计价，Wan3输入秒数必须来自当前Run的媒体检查，缺失别名不会触发补种模型。视频分析和状态查询的v3分支新增当前Run素材/Job/真实账本关联校验，旧角色路径保持不变。
- 新增配置`AGENT_V3_ENABLED=false`与独立v3默认模型（文本deepseek-v4.1-flash、多模态qwen3.7-plus），并补`.env.example`；未改动真实.env、未连接真实MySQL/Redis。
测试：
- 定向：适配器及旧Qwen测试78项；agent_chat 35项；最终catalog46项；兼容52项；scope26项+旧相关5项；迁移/预算并发18项；随后修正公共Schema负向测试误触发必填字段问题，新增真实API边界后75项相关回归全部通过。以上为各次实际结果，不相加冒充全量。
- 前端未改源码；`node --test tests/*.test.js` 64 passed，`npm run build`通过。
- 第一轮后端全量在19%主动停止，用于修正上述测试假阳性和公共字段拒绝；第二轮在33%停止，MQ失败源于临时目录过长（263字符触发Windows路径限制），另补齐test_plan_versions中遗漏的Alembic head断言。短临时目录复验新模型集成10项、迁移/计划版本25项全部通过；两次中断不计作全量完成。最终短目录单次全量：**1505 passed，45 warnings，22分41秒**（基线1278项+新增227项，无跳过）；覆盖经典、v1/v2及V1新工具。警告来自既有测试短JWT密钥及JUnit record_property格式，不是失败。结果XML：`%TEMP%/cinecrew-v1-final-full-results.xml`。
- 测试使用AGENTS指定Conda Python、Mock/Stub和临时SQLite/存储，网络阻断；pypdf通过`%TEMP%/cinecrew-w1-pypdf-6.21.1`加入PYTHONPATH，FFMPEG_BINARY使用主工作区已有FFmpeg 7.1。Windows全量测试的--basetemp请用短名称（例如%TEMP%/v1xxxxxx），避免MQ租约产物子目录突破路径限制。没有安装/修改用户环境。
真实调用：0次，真实估算费用0；未进行可选的1–3次函数调用冒烟，没有任何真实图片/视频生成。所有credits为演示估价，未验证服务商账户可用性、真实账单或生成质量。
下一步 / 给Claude和后续实现：
- V1已完成并本地合并，可并行开始V2与V3。Claude的V-Gate1在V1–V3全部完成后进行；当前不提前宣称Gate通过。
- 新代码导入app.tools；旧app.skills仅作兼容。Agent运行时用build_v3_registry并从Card限制工具清单；不得把内部agent_llm_turn或生成工具加入Agent可见清单。
- V3必须为每次普通工具调用创建独立ToolContext和服务端key，不复用agent_chat留下的LLM回合key；由运行时处理循环、纠错step、委派额度、checkpoint和finish。messages采用兼容接口消息格式，输出tool_calls是已解析的{name,arguments}，回填assistant历史时需转换为function结构及JSON参数串。
- V4须解析异步Job完成后的image/images/video工件、校验类型及缺失输出；当前io_types不代表初始Job回执已含工件。estimate_cost只接受已解析素材，不是完整计划编译器；analyze_images当前接纳Run上传图与研究参考图，未来计划预览产物的授权解析需要在V4贯通。
- token输入预留是保守字节估计（图片包含data URL），不是服务商tokenizer或严格上限，可能偏高；未配置token价格时保持原按次演示费用。实际超额会记录并停止。真实模型函数调用能力、多图质量/价格、MySQL迁移与并发行为尚待单独验收。
需要用户决定：无新增。

## 2026-10-19 · Codex · V2 Skill 库与 V3 Agent 运行时
状态：Codex 实现与 Mock/Stub 回归完成；关键 Skill 审定与 V-Gate1 仍由 Claude 负责。本轮不进入 V4–V8，不修改前端功能或美化。
分支与提交：从 feat/agent-v2 @ea9da2c 分出 agent-v3/V2、agent-v3/V3。V2 @9f196f0、V3 @79eab34 已快进合入本地 feat/agent-v2；本条的后续提交仅记录合并结果，不改已验收应用代码。未推送、未开 PR。

完成内容：
- V2：新增 20 项 Skill（15 个知识包与六个 Blueprint 指南，video-remix 共用目录）、启动时校验与缓存、list_skills/load_skill/read_skill_resource。使用受限 SafeLoader，拒绝重复键、别名、不安全标签、过深或过大文档、无效工具/builder/关联项；资源仅可读启动时固定快照，拒绝越界路径、隐藏文件、符号链接。关键四项 intent-analysis/delegation-policy/long-form-video/character-consistency 明确标为待 Claude 审定。Blueprint 指南不冒充尚未实现的 V4 builder。
- V3：七角色最小 Card 与安全提示词、每个委派独立 LangGraph checkpoint、工具循环、纠错上限、循环/无进展检测、深度/步数/时间/额度限制。所有工具仍通过 Registry，LLM 回合和每个普通工具使用各自稳定 key；生成工具不向 Agent 开放。并行表示多个持久化子任务可就绪，单 worker 每 tick 推进一个回合，没有新增模型线程池或 MQ。
- 委派按父级可用规划额度划拨，未完成子任务保留配额，完成释放未用配额；自身、所有祖先及 Run 总预算共同准入，实际费用只取工具账本。新增默认规划额度 20 credits、最大委派深度 3；用户更低预算优先，不自动扩额。steps/calls/费用均不因 checkpoint 回放重复累计。
- 新增 agent_delegations/agent_steps/agent_workspace_items 三表及 Alembic head 20261018_004；工作区不可变版本、独立写入收据与来源校验。brief 复核用户原文的模型约束与附件，研究产物绑定成功检索/抓取/下载/视觉工具回执；不接受模型自报“已验证”。引用检查包括同 Run 归属、版本和类型。PlanDraft 仅有结构验证，尚无编译、报价或执行许可。
- 非 Producer 的问题自动逐层退回并保留部分工作区与其他子任务结果，不额外调用中间 Agent；由 Producer 决定询问用户。复用选择题/答案校验、默认规则与轮数限制，阻塞问题不能无答案越过。仅 Producer 创建公开问题卡。
- 本地副作用与 Registry/checkpoint 之间的故障可按原收据恢复：工作区不重复升版本、委派不重复创建、问题不丢失、finish 不重复执行、LLM 不重复扣费。未知或失败的付费提交不自动重发。意外 worker 错误保留原命令并进入 attention，需显式恢复，不在后台反复重试。
- v3 Run 创建灰度、公开状态投影、分页步骤与 answer/reject/resume 接通；请求幂等固定原 schema_version，关闭灰度后仍能恢复已有 v3 Run。公开响应不返回内部消息、工作区原始载荷或异常详情；任务中心按业务阶段聚合，尚无执行节点时为 0，不将分析 Job 伪装成产出进度。
- D-033 与 v3 CONTRACTS 已同步分阶段边界、配额、协作调度、工作区收据和资源返回形状。AGENT_V3_ENABLED 仍默认 false；默认经典工具目录保持 22 项，v3 私有注册表 34 项，按角色过滤可见工具。真实 .env、AGENTS.md/CLAUDE.md、用户未跟踪技术笔记和私人报告均保留。

测试与证据：
- 定向：Skill 库 87 项通过；最终运行时 31 项、API/恢复 9 项、工作区 65 项、配额 17 项通过；迁移与旧迁移/计划版本 28 项通过。测试集合存在交集，不相加声称总量。
- 前端未改源码；node --test tests/*.test.js 为 64 passed，npm run build 通过。
- 后端最终单次全量：**1732 passed，7 warnings，38 分 35 秒**，无失败、无跳过（V1 基线 1505 项，本轮新增 227 项）。警告均为既有 record_property 与 JUnit xunit2 格式兼容提示。证据：`%TEMP%/cinecrew-v2-v3-final-results.xml`，隔离测试目录 `%TEMP%/v335c471`。此前一次全量在早期主动中止以补齐深层问题的确定性上抛，不计作通过。
- 使用 AGENTS 指定 Conda Python、隔离 SQLite/存储、Mock/Stub；pypdf 沿用临时 PYTHONPATH，FFmpeg 使用工作区已有 7.1，--basetemp 使用短路径。没有安装或修改用户环境。
真实调用：0 次，真实费用 0；没有连接真实 MySQL/Redis、调用真实文本/多模态/图片/视频模型。credits 均为演示估价。

下一步 / 给 Claude 与后续实现：
1. Claude 审定四项关键 Skill，并执行 V-Gate1；重点检查 Card 权限、父子配额、深层提问、工作区证据与幂等恢复。可从 test_v3_skill_library/test_v3_runtime/test_v3_runtime_api/test_v3_runtime_budget/test_v3_workspace/test_v3_runtime_migrations 复用证据。本轮自检不代表 Gate 已通过。
2. V4 实现编译器、dry-run、六个 Blueprint builder、预览和计划审批后，再开放相关工具与 plan_submitted；工作区中的 origin.blueprint 仍是未验证草稿，必须用服务端 builder 收据确认，不能凭模型标记解除 experimental。还须映射异步 Job 的完成工件，并区分规划与生产费用。
3. V5 Patch、V6 正式创作提示词/策略、V7 协作与审核界面、V8 经典生产意图均未实现。当前最小 Card 只证明运行机制，不代表高质量长片规划已经验收。旧页面不作为 v3 新交互的验收结果。
4. 契约中的 600 秒为从委派开始计算的墙钟时限，当前包括排队与人工等待；恢复不重置此上限。Claude 可在 Gate 审查此取舍，如调整应先变更契约并补跨长等待回归。MySQL 迁移/并发、真实函数调用质量、真实价格与媒体效果均未验收。
需要对方或用户决定：关键 Skill 与 V-Gate1 待 Claude；本轮无需新增用户授权。

## 2026-10-19 · Codex · V4–V7 续作检查点（V4 集成中）
状态：进行中；用户要求逐阶段推进 V4–V7、每阶段验证，本轮不调用真实 LLM/模型。V4 尚未完成全量回归，不将本条视作阶段验收或 Gate 通过。
分支与基线：agent-v3/V4 从本地 feat/agent-v2 @bb68ad2 分出；当前改动未提交、未合并、未推送。保留用户未跟踪的 AI_Video_Factory_Technical_Notes_CN.md 与私人报告。
完成内容：
- D-034 与 v3 契约 V.16 先明确控制依赖、免费原片裁切、私有 Plan 工具 Schema、未来素材时长上界、typed Stub dry-run、审批与异步 Job 冻结边界。
- Plan IR 编译器、typed Stub dry-run、六个 Blueprint、PlanNodeTask 表与迁移 20261019_005、确定性节点调度、预览门、生成/交付私有工具已落盘；经典 19 节点与默认 22 项 Registry 保持不变。
- 正在集成 check_plan / instantiate_blueprint / submit_plan、request_preview、审核动作、公开节点视图与任务中心；Agent 规划费与生产费分开统计，总预算共同约束。提交前、Job 调度前、MQ 真正 POST 前分别验证冻结输入与价格，未知提交停止，轮询/下载可免费恢复。
已有定向证据（集合有交叉，不相加冒充全量）：六 Blueprint 33 passed；编译器/dry-run 39 passed；真实 Mock Job/MQ 图→视频、预览门、局部输入哈希复用、免费恢复、拼接/QC/ZIP 等定向通过，执行器完整集合仍在补测。Root 的审核/API/工作区/配额回归正在运行。
未完成 / 下一步：
1. 先完成 V4 所有定向测试及经典/v1/v2 全量回归、前端基线构建，再提交并本地合并；当前不得宣称 V4 全绿。
2. V5 Patch、V6 正式卡片/策略、V7 功能界面随后分别建分支推进与验证；不得进入 V8。Claude 继续负责关键 Skill/提示词审定、各 Gate 与美化。
3. Windows 测试继续使用 AGENTS 指定 Conda Python、短临时目录、Mock/Stub、隔离 SQLite、已有 FFmpeg；禁止读取真实 .env 启动测试、连接真实 MySQL/Redis 或真实模型。真实调用累计 0，真实费用 0。
需要对方或用户决定：无新增；Gate 与真实效果仍待 Claude/后续明确授权验收。

## 2026-10-19 · Codex · V4 Plan IR、Blueprint 与受控执行
状态：Codex 实现与 Mock/Stub 回归完成；V-Gate1/2、关键 Skill 审定仍由 Claude 负责，不宣称真实模型效果通过。进入 V5 前进行本地任务分支合并，不推送、不进入 V8。
分支：agent-v3/V4，从 feat/agent-v2 @bb68ad2 分出。用户未跟踪技术笔记、私人报告、真实 .env、AGENTS.md/CLAUDE.md 均保留。

完成内容：
- D-034 与 v3 CONTRACTS V.16 明确 Plan 控制依赖、异步命名输出、按秒/张及 Wan3 I+G 估价、隔离 typed Stub dry-run、审批许可、预览恢复和媒体 QC 边界。
- 六个 Blueprint builder、check_plan / instantiate_blueprint / submit_plan、不可变计划审核版本和可修订 issues；Blueprint 身份通过服务端草稿哈希收据验证。提交版本与 Producer 完成原子保存，崩溃不会额外要求一轮 LLM。
- plan_node_tasks 与迁移 20261019_005；通用 DAG 按依赖和并发限额调度，共用现有 Job/MQ。源素材和生成产物按 SHA 校验，门只阻塞后代；终端门同样须批准。成功结果复用，未知 POST 停止，已受理任务仅有界免费恢复。
- 仅 v3 私有 Registry 开放 Plan 输入 Schema，默认经典目录仍 22 项、19 节点 DAG 不变；v3 共 39 工具。正式生成工具不可见，request_preview 是唯一有界规划生成例外（每次一图、最多六次、每次三演示 credits 上限）。预览创建/链接/绑定/启动间隙只恢复原 Job，Agent 重放补回原输出，已受理读取最多两次，不新增生成费用。
- 原片保留裁切、Wan3 reference/edit/extend、提取尾帧、拼接/可选显式压缩、probe/QC/ZIP 贯通；QC 对比批准的片段/总时长，打包前与落盘前复验 QC 输入。压缩副本必须来自同一 compose 的明确输出。
- approve_plan / approve_gate / approve_results 接入幂等动作箱、公开计划与节点状态、私有产物归属和任务中心 plan_nodes 进度；规划/生产花费分开展示，仍共同受 Run 总预算限制。

验证：
- 后端最终全覆盖：1906 passed，0 failed，0 skipped，覆盖全部 102 个测试文件。使用四组隔离进程；运行时组修正两条 V3 阶段的过时断言后保留先前已通过的 133 项，再重跑该组全部运行时及剩余文件，最终报告按 node id 去重并与 collect-only 清单比对。原失败运行不冒充通过。
- 原断言分别是“任何生成权限工具均不可见”和“Plan 提交尚未实现”；现验证仅 request_preview 例外、没有服务端提交收据无法 finish(plan_submitted)。没有为迎合测试放宽生产审批。
- 最终聚合证据：%TEMP%/cinecrew-v4-final-results.xml；原分片 cinecrew-v4-full-0/1/3.xml、cinecrew-v4-full-2-prefix.xml、cinecrew-v4-full-2-tail.xml。既有 record_property/JUnit 格式警告不影响结果。
- 前端未改源码，node --test tests/*.test.js 为64 passed，npm run build通过；沙箱下 esbuild 启动权限问题经相同命令授权重试后成功。git diff --check通过。
- 定向故障覆盖提交后收据丢失、预览创建/链接/绑定断点、未知POST、免费读取/下载恢复、失效产物、源文件漂移、门与取消、批准时长和 QC 后素材篡改。既有 Mock PNG sentinel 仅证明管线，不证明真实图像解码或模型质量。

真实调用：0次，真实费用0。使用指定 Conda Python、短临时目录、隔离SQLite/存储与Mock/Stub，网络阻断；pypdf沿用临时PYTHONPATH、FFmpeg使用仓库已有7.1。未连接真实MySQL/Redis，未安装或修改用户环境。

下一步：
1. 本地合入 feat/agent-v2 后创建 agent-v3/V5，先落 D-035 / V.17，再实现 Patch 编译/审阅/报价/授权/恢复；V6正式提示词与V7功能界面随后逐阶段验证。
2. Claude仍负责各Gate与美化。当前AGENT_V3_ENABLED默认false；真实函数调用质量、媒体质量/服务商实际价格、MySQL并发迁移仍未验收。
需要用户决定：无新增；继续执行已授权 V4–V7，当前禁止真实 LLM/付费调用。
