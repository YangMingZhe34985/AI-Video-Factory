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

## 2026-10-19 · Codex · V5 开始
V4 提交 4051247 已快进合入本地 feat/agent-v2，未推送。当前从该集成基线创建 agent-v3/V5；D-035 与 v3 契约 V.17 已先行记录 Patch、审阅证据、增量报价、only/cascade 及跨版本额度边界。应用实现与回归随后推进；本条不代表 V5 验收。

## 2026-10-19 · Codex · V5 集成检查点
状态：进行中，尚未提交或合并 V5。分支 agent-v3/V5；V4 已合入 4051247，V6/V7 尚无应用变更。
完成内容：Patch Schema/编译/只读报价、独立 Director 审阅、only/cascade、增量授权与跨版本额度、人工修订/API/公开差异已集成；默认经典22工具不变，v3为41项。
验证进展：编译31项、执行19项、API相关26项、修复协作及既有运行时集合有定向通过证据；集合有交叉，不相加声称全量。前端64项及构建通过。首轮四组全量已主动中止，原因是只读恢复审查发现并复现审批旧报价卡箱、已批准后恢复误报成功，以及已提交规划旧回合未收尾的修订冲突；不计作通过。
接续：前两条已修复并补回归；正在完成旧回合收据记账修复，随后从最终代码重新执行全部后端回归。只有全绿才提交/本地合并，然后先落D-036/V.18再推进V6，最后V7。Claude仍负责Gate、关键Skill/Producer/Director审定与美化，不能据本条认为Gate通过。
真实调用：0，真实费用0；只用Mock/Stub、隔离SQLite/存储和短临时路径，未读取真实环境启动服务、未连接真实MySQL/Redis。保留用户未跟踪技术笔记与私人报告，不推送、不进入V8。
## 2026-10-19 · Codex · V5 Plan Patch 与恢复完成
状态：Codex 实现与 Mock/Stub 回归完成；V-Gate2 由 Claude 负责。V4 提交4051247已本地合入，本阶段在 agent-v3/V5 完成后快进合入 feat/agent-v2；不推送、不进入V8。

完成内容：
- D-035 / V.17 定义严格 PatchDraft、独立 Director 审阅、只读增量报价、only/cascade、审批收据和跨版本额度。Repair 仅对明确可修复失败起草，未知提交、鉴权/余额/配置问题不唤起修复 Agent。
- 改动影响范围取新旧 DAG 后代闭包；only 保留已有下游产物及真实来源，cascade 重做影响子图；未启动的正常节点单独计为继续执行。费用按服务端模型单价/输入与输出秒数计算，不信任 Agent 自报。
- 低风险提示词修复必须通过审阅、原审批约束、总预算和修复池，每个逻辑节点最多两次；人工批准不会补满额度或清零次数。修复预留不重复计入实际工具账本。
- 用户可提交修改意图；未批准计划交回 Producer，已批准计划走 Director 起草与独立审阅。旧硬约束保持，取消/旧版本/已替代补丁不能恢复执行。API与公开视图增加准确报价、前后差异、保留来源、修复额度与动作待处理状态。
- 审批、任务、版本和额度原子提交；源文件漂移、未知任务、重复请求安全停止或回放原收据。过期报价清理旧动作允许重新审核，未知结果继续保留原动作。批准/拒绝提交后崩溃恢复实际状态；规划提交后未收尾的旧回合只补记已核验成功收据，不重发 LLM、不重置配额。

验证与证据：
- 最终后端完整覆盖 **2000 passed，0 failed，0 skipped**，全部106个测试文件。四组隔离进程中旧 test_v3_cards 已收集的V3断言仍禁止 propose_patch；修正为精确角色权限后完整文件15项复测通过，最终报告用该文件的新结果替换旧结果，不将失败运行计为通过。
- 聚合报告按 node id 与最终 collect-only 清单逐项核对：2000/2000、重复0、缺失0、额外0。证据：%TEMP%/cinecrew-v5-final-results.xml；原始分片 cinecrew-v5-final-0/1/2/3.xml 与 cinecrew-v5-cards.xml 保留。7条既有JUnit格式警告不影响结果。
- 修复协作与旧运行时联合63项、API相关26项等定向证据与全量重叠，不重复累加。前端未改源码，64项通过、构建通过；git diff --check通过。先前主动中止的全量不计入本次结果。
- 默认经典22项工具与19节点DAG保持，v3私有目录41项；AGENT_V3_ENABLED仍默认false。

真实调用：0次，费用0；指定Conda Python、短临时目录、隔离SQLite/存储、Mock/Stub与网络阻断。未连接真实MySQL/Redis，未安装依赖或修改真实.env。用户未跟踪技术笔记与私人报告保留。

下一步：
1. 本地合并V5后从集成分支创建agent-v3/V6，先落D-036/V.18，再迁入已在TEMP准备的角色策略/范围约束/离线场景草案并验证。TEMP草稿未参与V5应用测试。
2. 按用户授权继续V6–V7；Claude仍负责关键Skill、Producer/Director策略审定、各Gate与美化。本轮脚本测试不代表真实LLM自主规划、视觉质量、MySQL并发迁移或服务商真实价格已验收。
需要用户决定：无新增。

## 2026-10-19 · Codex · V6 开始
V5 提交 f19dbd4 已快进合入本地 feat/agent-v2，未推送；已从该基线创建 agent-v3/V6。D-036 / V.18 先定义正式策略、Prompt Smith 范围和现有多模态能力边界。随后迁入临时草稿并做定向及完整回归；当前不代表V6或Gate验收。用户本轮不调用LLM的限制优先于D-030的历史授权，所有测试仍为Mock/Stub。

## 2026-10-19 · Codex · V6 合同可见性补充检查点
状态：V6继续实现，未提交或合并。首轮2070项全量在运行中主动中止，不计作通过。只读审查发现真实Agent无法完整读取严格工作区Schema和生产节点命名输出，且Research把网页正文快照表述成视觉参考；ScriptedLLM预知字段不能证明真实模型可正确构造。已先补D-036/V.18，随后补只读Skill资源及回归，冻结后重跑完整测试。V7全部草稿仍仅在TEMP；无真实调用、无费用、不进入V8，Claude关键Skill未改。

## 2026-10-19 · Codex · V6 正式角色策略与范围约束完成
状态：Codex 实现与 Mock/Stub 回归完成；Producer/Director、关键 Skill/委派策略审定及 V-Gate1/2/3 仍由 Claude 负责。本条不代表真实 LLM 自主规划或生成质量已验收。
分支：agent-v3/V6，基于 feat/agent-v2 @f19dbd4；验证后本地快进合入，不推送。保留用户未跟踪技术笔记、私人报告、真实.env、AGENTS.md/CLAUDE.md。

完成内容：
- D-036 / V.18 先行。七个 Card/提示词明确输入输出、简单任务直接规划、复杂任务按需委派、证据/额度/失败边界；Director增加只读get_task_status，普通目录隐藏仅由服务端分配的Repair。
- Prompt Smith委派必须携带同Run不可变plan_ref和明确node_ids，服务端冻结草稿hash；只接受范围内非空prompt更新。模型、参数、时长、引用、结构和重复/越界节点均拒绝；父Agent写新草稿重新编译，已批准计划仍走Patch。委派本地恢复核验原输入/父子关系及冻结范围。
- 每个新LLM step持久化六项调用前额度快照，重放用原快照，模型按剩余额度显式分配子任务并保留自身收尾额度；不改变服务端预算。旧账本消息保持，但跨版本工具Schema变化仍严格停止，不声称在途委派无缝迁移。
- 更新九项非关键Skill及预算资源，六Blueprint提供真实params Schema/示例。plan-review新增六类工作区Schema、十个Plan工具的resolved input和命名输出、可编译示例；Agent按需读取，不开放生产工具权限。回归核对资源与实际Pydantic/ToolSpec一致。
- 明确能力缺口：analyze_video仅返回异步内容描述，未提供精确镜头切点；analyze_images只理解上传/研究图，生成预览由用户gate审核；capture_reference_page是原请求URL的正文快照，不是网页截图。首尾帧效果仍待验证，默认不主动压缩。
- 六个ScriptedLLM场景覆盖照片双图批量理解、单镜头默认/显式系列/时长、120秒八镜头协作、原片保留与局部重生成。均执行真实运行时/Registry/编译和dry-run，在计划审核停下，重放不增规划费/版本，无生成Job。

验证：
- 最终全量 **2098 passed，0 failed，0 skipped，111个测试文件**。四组隔离进程的node id与最终collect-only清单逐项匹配：缺失/额外/重复均0。证据：%TEMP%/cinecrew-v6-final-results.xml；原始cinecrew-v6-final2-0/1/2/3.xml，清单cinecrew-v6-collected-final2.txt。
- 首轮2070项全量因合同可见性审查主动中止，未计通过。新增资源后联合153项通过，再冻结代码重跑上述2098项；定向与全量重叠，不累加。
- 前端仓库本阶段未改，沿用已验证的64项/构建基线；V7临时副本65项新helper、构建、18组Mock浏览器预检通过，但这些不冒充正式V7阶段验收。git diff --check通过。7条既有JUnit格式警告不影响结果。
- 所有调用为Mock/Stub，隔离SQLite/存储、网络阻断、指定Conda Python与短TEMP路径；真实LLM/多模态/图片/视频调用0次，真实费用0，没有连接真实MySQL/Redis或修改用户环境。

下一步：
1. 本地合并后建agent-v3/V7，先落D-037/V.19，迁入已预检的功能界面并在正式源码重验；不进入V8。
2. Claude重点审定：delegation-policy的简单任务直接完成与显式额度保留；long-form-video中Prompt Smith改按需并带prompt_scope；character-consistency不能将生成图理解描述成已有自动QC；intent-analysis应使用RequirementBrief而非v2 RequestSpec。四个关键Skill本轮保持未改。
3. Claude检查Producer/Director及三个Gate。600秒墙钟上限仍包含排队/人工等待，恢复不重置；真实自主规划质量、实际单价/媒体效果、MySQL迁移并发均待验收。AGENT_V3_ENABLED继续默认false。
需要用户决定：无新增；按本轮要求继续V7，禁止真实LLM/付费测试。

## 2026-10-19 · Codex · V7 开始
V6提交2681f1c已快进合入本地feat/agent-v2，未推送；当前从该基线创建agent-v3/V7。D-037/V.19先定义功能界面、审批/报价、迟到响应及美化边界。随后将已在TEMP预检的源码迁入正式分支，仅做Mock验证；本条不代表V7正式验收。

## 2026-10-19 · Codex · V7 功能界面与 V4–V7 本地交付
状态：V4–V7 Codex实现与逐阶段Mock/Stub验证完成，不进入V8；本条随agent-v3/V7提交，验证后快进合入本地feat/agent-v2，不推送。前置提交：V4 4051247、V5 f19dbd4、V6 2681f1c均已本地合入。

完成内容：
- D-037 / V.19先行；schema_version=3专用V3RunPanel，保留原必填文本/附件入口、v1/v2历史面板。未增加任务类型、模型、镜头数表单。共享布局的responsive默认为false，仅Agent Studio启用必要手机适配；该页旧版本也使用响应式侧栏，其他经典页面保持原默认行为。
- 协作树与分页公开步骤，通用阶段/节点/依赖/门/历史保留来源，规划/总/修复预算分开显示。节点费用取服务器估价，区分交付秒数、累计生成秒数、I+G输入秒数；未知费用不显示为免费。
- 计划审批绑定当前版本及可选修复预授权，预览审批/反馈绑定成功未批准节点，修改仅提交意图；结果确认和本地鉴权下载。服务端继续决定权限、预算、范围与最终执行。
- Patch展示前后差异、独立审阅和六类影响范围，须重新获取当前only/cascade报价。只保留下游旧产物时要求明确勾选衔接风险；人工准入与有限费用同时校验，报价失效不能批准。不可人工批准时仍可拒绝有效的当前补丁。
- 请求键在同内容网络重试保持稳定；范围/版本变化取消旧请求并丢弃迟到响应。普通轮询不会重置编辑、scope、展开节点、在途动作或下载；选择新任务在途时旧动作回执不能夺回选择，旧轮询不能回滚已确认的历史状态。
- 新增可复用的frontend-vue/tests/browser/agent-v3.smoke.js及使用说明，所有API内存拦截；没有新增npm依赖、没有修改后端应用/经典DAG/真实.env。

验证：
- 正式源码前端 **129 passed**（原64 + 新65），npm run build通过，git diff --check通过。
- 正式构建浏览器 **18组通过**：分页、费用上限、稳定重试键、选择题、门、未知动作恢复、only/cascade及失效报价、版本漂移、慢动作/下载跨轮询、任务切换及历史回退竞态、空文本/快捷键、v1/v2兼容。1440/400px各亮/暗主题，document/body及内容区边界均无横向溢出；pageerror 0、意外请求0。现有Google Fonts请求被主动拦截，不访问外部网络。
- 后端相关runtime/Plan/Patch API联合 **26 passed**；V7的backend与2681f1c无差异，完整基线沿用V6的 **2098 passed/111文件**，没有将这26项与全量相加。V4/V5分别1906/2000项完整覆盖，逐阶段证据见对应记录。
- 浏览器结果保存于忽略目录.playwright-mcp/v7-preview-20261019/v7-final-result.txt；后端API报告%TEMP%/cinecrew-v7-api-results.xml。前端拦截和后端隔离集成分别验证，不冒充真实端到端服务商调用。PNG仅占位、ZIP为空包、未提供MP4，本次UI不验证媒体解码或生成效果。
- 使用Mock/Stub、隔离SQLite/存储、网络阻断；真实文本/视觉/图片/视频调用累计0，费用0，未连接真实MySQL/Redis。临时预览在收尾时关闭。未安装依赖，用户未跟踪的AI_Video_Factory_Technical_Notes_CN.md、私人报告和环境配置保留。

交给Claude / 尚未验收：
1. V-Gate1/2/3、Producer/Director及委派策略审定、四项关键Skill审定和界面美化仍待Claude；本轮未修改delegation-policy、intent-analysis、long-form-video、character-consistency。具体策略差异见上一条V6记录。
2. 重点复验公开计划/费用投影、审批与修订版本、Patch保留风险、轮询/选择竞态，以及资源Schema与真实工具合同一致。浏览器脚本可重复执行，默认不开真实后端。
3. AGENT_V3_ENABLED仍默认false。真实LLM自主规划、视觉一致性/首尾帧质量、真实单价、MySQL迁移与并发、600秒墙钟含人工等待的取舍仍未验收。不得据Mock全绿直接打开付费生产或宣称Gate完成。
4. 本轮仅本地提交/合并，无远程推送、无PR；V8尚未开始，需要在V-Gate3后按用户指令推进。
需要用户决定：本轮无新增；后续真实测试须遵循用户当轮授权，不沿用历史授权自动调用。


## 2026-10-19 · Claude · V-Gate3 评审与真实 LLM 评测（含 V-Gate1/2）
状态：**有条件通过**，分支 `agent-v3/V-Gate3`，已合入本地 `feat/agent-v2`；未推送。V7 美化尚未做。
评审范围：V1–V7 代码、D-032 – D-037、Producer/Director 提示词与四个关键 Skill（本该在 V-Gate1/2 做的审定一并完成）。
代码评审要点：
- 生成类工具对 Agent 不可见：`ToolSpec` 构造时断言，Registry 导出时再过滤，两处都有。v3 只通过批准后的 Plan IR 执行；check、dry-run、批准回执、补丁审阅链路与契约一致。
- Producer / Director 提示词方向正确（简单任务不委派、不猜默认模型、外部内容当数据），但信息密度高、前置读取多；按真实评测结果做了修订并审定。
真实评测（D-030；详见 `docs/agent_v3/VGATE3_EVAL.md`，脚本在 `backend/scripts/v3_eval/`）：
- 范围：6 个用例（证件照改图、8 秒单镜头、两分钟拟人长片、模糊需求、三选一再做动画、模型约束），并在 v2 上用同一模型做对照。
- 用量：v3 共 15 个 Run，234 次 LLM/视觉调用，约 672 万输入 token、26 万输出 token；v2 共 14 次调用。**图片生成 0 次，视频生成 0 次**：评测进程替换了视频适配器，所有计划都没有批准执行。演示价合计 v3 117.8 credits、v2 14 credits，实际人民币费用未估算。
- 结论：
  - 简单任务全部由 Producer 独立完成，没有委派；多图理解只调用一次。
  - 模糊需求先提问；模型约束得到遵守。
  - 两分钟长片在第 5 次运行时由 Producer → Director 产出 27 节点计划：定妆图与关键帧都设预览门，10 镜头 i2v 合计正好 120 秒，含拼接、质检、打包；规划 8.9 credits，用时 311 秒。
  - 与 v2 相比：简单任务 v2 更快（少 20–40 秒、少约 7 轮调用）；复杂任务和非模板任务 v3 明显更强。
修复（D-038，契约 V.2.1 / V.3 / V.6.1 / V.13 已同步）：
1. 计价：`deepseek-v4.1-flash` / `qwen3.7-plus` 增加演示 token 单价（0.01 / 0.02 每千 token），只在价格仍为出厂默认时回填，运营者改过的价格不动；v2 按次估价不变。（`model_service.py`）
2. 工具拒绝对 Agent 返回清洗后的字段级 `errors`（不含提交值），工作区 Schema 错误与 finish 契约错误带上具体字段。（`agents/runtime.py`、`schemas.py`、`tools.py`）
3. 编译器节点问题写明原因与可选模型，例如“请求 2 张参考图，模型最多 1 张”。（`plans/compiler.py`、`agent/model_selection.py`）
4. `check_plan` 对 Agent 只返回 issues / estimates / experimental / resolved_models / order；计划版本持久化的检查结果保持完整。（`plans/tools.py`）
5. 上限只累计 Agent 自身回合的活跃时间，不再包含等待用户和子 Agent 的时间；新增 `AGENT_V3_DELEGATION_ACTIVE_SEC`（默认 600，已写入 `.env.example`）。此前用户超过 10 分钟才回答问题，Producer 会立即停止。（`runtime.py`、`config.py`）
6. 审定并修订：Producer / Director 提示词（工作效率、先写草稿再检查、预算冲突时退回、显式划拨额度），`delegation-policy`（此前与 Producer 冲突：简单任务应由 Producer 直接规划）、`long-form-video`（补充生成方式取舍表、衔接与预览门），以及 `intent-analysis`、`character-consistency`。
新增与调整的测试：字段错误不回显提交值、等待用户不计活跃时间、活跃时间上限、token 计价回填与运营者价格保护；三项依赖“每次 1 credit”的测试改为显式固定或调低额度；审定标记测试改为断言“已由 Claude 审定”；场景测试改用 `resolved_models`。
测试：
- Codex 交付代码基线全量：2098 项中 2096 通过，失败的 2 项是审定标记测试（我中途修改了 Skill 文件，旧断言读到了新文件），在交付代码上本应通过。
- 最终代码全量：**2101 passed**（50 分 45 秒；原 2098 项加新增 3 项；PYTHONPATH 提供 pypdf，FFMPEG_BINARY 指向本机 FFmpeg 7.1）
- 前端 129 项通过，`npm run build` 通过。
留给 Codex（PLAN V9a – V9e，之后由我做 V-Gate4 复跑评测）：
- V9a 选择门：Plan IR 不能表达“从多个预览候选中选一个”（c5 中动画固定引用第 1 张海报，Agent 已在 rationale 中如实说明）。需要契约先行（DECISIONS → CONTRACTS）。
- V9b 上下文管理：加载过的 Skill 和资源永久留在历史中，长片单轮输入最高约 11 万 token、单轮 30–40 秒。
- V9c 简单任务开销：约 9 轮调用，主要是读取 Blueprint 资源。
- V9d 死节点检测：c3 计划中有一张没有被下游引用的双人设定图。
- V9e 多参考图默认选型：默认图片模型只支持 1 张参考图，多人同框需要能接受多张参考图的模型。
- 复跑评测：`python backend/scripts/v3_eval/eval_v3.py all`；`EVAL_V2=1` 跑 v2 对照。需要按 D-030 记录调用量。
未验证：真实图片和视频生成质量、角色视觉一致性、MySQL 上 v3 迁移与并发、V7 界面美化。
需要用户决定：无新增。

## 2026-10-19 · Codex · V9a–V9e 接手
状态：进行中；从已合入的 V-Gate3 开始，分支 agent-v3/V9a；用户要求暂跳过 V8。
契约：D-039 → CONTRACTS V.20 已先行；保留 D-038 的活跃时间、token 演示计价与 Claude 审定策略。
当前：选择门后端与功能界面正在验证；V9b/V9c 在 TEMP 独立预检，尚未迁入任务分支，不冒充正式验收。选择器无副作用、免费，经 Registry 和用户选择证明执行；候选变化重新确认。
验证进展：前端 134 项、构建、新选择门 8 组浏览器检查与既有 18 组通过，1440/400px 亮暗主题无横向溢出，应用 pageerror/意外 API 均 0。浏览器所有 API 内存拦截，预览已关闭。
边界：本轮 Mock/Stub、隔离 SQLite/存储，真实 LLM/视觉/图片/视频调用 0；不推送、不进入 V8，Claude 仍负责 V-Gate4 和美化。用户私人未跟踪技术笔记与环境配置保留。
下一步：完成后端审批/Patch/故障回归后本地合并 V9a，再逐任务分支落实 V9b–V9e，最终更新本日志与看板。

## 2026-10-19 · Codex · V9a 选择门完成
状态：agent-v3/V9a 已完成，验证通过后本地合入 feat/agent-v2；未推送。D-039 / V.20 已先行定义五项修订。
变更：Plan 私有免费 select_image、choice 门、用户显式选择与版本/候选/来源证明；接口和 worker 双重复验。候选重做重新确认；Patch 只继承有完整原审批链的相同选择，only 保留结果仍标明历史来源。作者资源、Schema、前端选择卡片与反馈同步，经典 Registry 不变。
测试：新增31项，既有执行/Patch74项，API/修复/作者资源/目录兼容184项，共289项后端定向通过。前端134项、构建、新8组和既有18组浏览器验收通过；1440/400px亮暗主题无横向溢出，应用错误0。最终全量将在五项集成后运行。
边界：隔离SQLite、Mock/Stub和网络阻断；真实LLM/视觉/图片/视频调用0，未修改环境配置或私人笔记。V8跳过；V-Gate4和整体美化仍由Claude负责。
下一步：V9b请求上下文投影；只替换runtime的请求构建函数，不覆盖选择门动作处理。

## 2026-10-19 · Codex · V9b 上下文投影完成
状态：agent-v3/V9b 验证通过后本地合入；未推送。保留V9a及D-038活跃时间逻辑。
变更：原历史/账本/工作区保留，仅精简旧的成功且可免费精确重读的工具正文；保留最近两轮、每个Skill最新正文、系统/用户约束、错误及研究/理解材料。60,000 Unicode字符是软目标，不是token硬上限。请求调用前冻结并校验摘要；同一步恢复优先使用原账本请求，不重新投影或加价调用。
测试：正式源码新增26项和既有额度8项共34项通过，包含前后账本中断、旧收据、Schema漂移、摘要损坏和免费重读。合成资源历史减少超过65%请求字符；不是实际token/延迟测量。TEMP另预检既有运行时/预算58项通过，正式全量留到集成收尾。
边界：隔离SQLite/Mock/Stub，真实调用0；Claude的V-Gate4仍需验证长片实际上下文和规划效果。下一步V9c六个Blueprint正文摘要与简单路径。

## 2026-10-19 · Codex · V9c 简单任务读取完成
状态：agent-v3/V9c 验证通过后本地合入，未推送；迁入前核验8个已有文件摘要，未覆盖并行修改。
变更：六个Blueprint正文包含最小完整参数例，简单三类另含默认模型检查草稿；完整Schema按需读取。Producer/Director只精确调整效率说明，修正check_plan真实入参，保留已审定策略和四个关键Skill。实例化返回无问题草稿后直接提交，内部编译/dry-run和人工生产批准仍必需。
测试：正式源码74项通过（新增18项、既有V6策略和Blueprint）；实际加载正文例并经Registry验证，六类能编译/dry-run，简单任务Stub四轮到审核、无委派、审核前无生成。不代表真实LLM已稳定减少轮次；由Claude复评。
边界：Mock/隔离SQLite，真实调用0；下一步V9d付费死节点检查和合法并行测试夹具的显式交付声明。

## 2026-10-19 · Codex · V9d 付费死节点检查完成
状态：agent-v3/V9d 验证通过后本地合入，未推送。
变更：从deliverables沿inputs数据引用反向追踪，未使用的四类生成节点报PLAN_UNUSED_PAID_NODE；不自动删除或改预算，depends_on/preview不算消费。选择门全部候选保留，免费QC/探测不受限制；plan-review同步指导。4个既有测试文件的合法并行分支补充显式交付，原断言与默认构造语义保留。
测试：正式源码新增12项+既有编译45项共57项通过；受影响V4/V5夹具15项另通过，共72项。覆盖孤立生成、纯控制边、完整链路、数组/列表选择候选、显式额外交付和只读编译/dry-run失败。
边界：Mock/隔离SQLite，真实调用0；下一步V9e，多参考容量选型严格遵守已精化D-039/V.20.5，不改共享v2策略。

## 2026-10-19 · Codex · V9e 定向完成，进入全量验证
当前分支agent-v3/V9e，源码冻结。V9a–V9d已依次本地合入feat/agent-v2（82c15db、3dfa1f1、ddc653e、303af9b）；未推送。
变更：v3 i2i默认容量不足时，在用户硬约束内稳定选择可容纳全部参考的模型；用户精确型号不放宽，具体节点ID不替换，完整参数/预算/价格照常校验。story-video去重角色参考后选择，生成帧允许model_id=null；不改共享v2选型、默认配置或视频策略。
测试：正式源码新增29项全通过，含归一化重编译、实际instantiate→submit→begin→Mock Job、用户型号/系列/排除、完整参数、配置无效、预算/价格变化及两角色故事。真实调用0。
收尾中：已收集2218项后端用例，六组全量回归进行中；报告位于本机TEMP/v9-full-0.xml至v9-full-5.xml，最终必须核验无缺失/重复/失败/跳过。尚未提交V9e，不将定向通过写作全量验收。

## 2026-10-19 · Codex · V9a–V9e 全量验收与本地交付
状态：五项实现完成，分别经任务分支验证并本地合入feat/agent-v2；本条随agent-v3/V9e提交后快进合并。未推送、未开PR；V8按用户指令跳过，V-Gate4与整体美化仍归Claude。
变更摘要：D-039 / V.20；用户显式选择门及候选/来源审批链；保留原始记录的请求上下文投影；六个Blueprint正文参数摘要和简单任务短路径；阻止未通往交付物的付费生成；默认i2i容量不足时在用户约束内选择完整参数可用的多参考模型。未改经典/v2默认策略或全局模型配置。
最终验证：
- 后端117个测试文件、2218项全部通过，六组退出码均0；与collect清单逐项比对，缺失/多余/重复/失败/跳过均0。覆盖经典工作流、共享队列、v1/v2及v3的工具、编译、审批、Patch、恢复和交付。存在7条既有record_property与xunit2报告格式警告，不影响断言和用例计数，本轮不改无关测试配置。
- 合并报告：C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v9-full.xml；清单cinecrew-v9-collected.txt；原始六组v9-full-0.xml至v9-full-5.xml。使用指定conda Python、临时pypdf依赖和FFmpeg 7.1，未安装新项目依赖。
- 前端134项、构建、新选择门8组及既有18组浏览器检查通过；1440/400px亮暗主题无横向溢出，应用pageerror和意外API均0。浏览器API全部Mock拦截，预览服务已关闭；V9b–V9e未再改前端。
- 最终跨任务只读复核无阻塞问题：所有choice候选仍全额估价并参与数据可达性；多角色参考完整保留；审批、Patch来源及费用复核未被绕过；D-038活跃时间与Claude此前审定的核心策略保留。
边界：全部Mock/Stub、隔离SQLite/存储并阻断测试外连；真实LLM/视觉/图片/视频调用均0，本轮真实调用估算费用0。AGENT_V3_ENABLED仍默认关闭，未改.env，用户未跟踪的AI_Video_Factory_Technical_Notes_CN.md保留且不纳入提交。测试进程均已结束。
交给Claude：
1. V-Gate4审查D-039/V.20和五项实现，重点检查用户改选、未选候选重做、嵌套选择、only历史保留及过期审批的处理。
2. 真实评测另按当轮授权执行；本轮未运行v3_eval。对比简单任务轮次、长片输入token/延迟及多参考默认选型；Stub四轮和合成字符减少不代表真实LLM效果。用户精确型号/系列/排除不可放宽，候选模型能力匹配不代表画质或身份一致性已验收。
3. 美化保留同版本/摘要轮询时的本地选择、候选/摘要/版本变化清空选择、明确确认与稳定request_key；继续检查400px和亮暗主题。不得引入默认第一张或绕过后端批准。
尚未验收：真实LLM自主规划和提速、真实生成质量/角色视觉一致性、MySQL上v3并发与迁移。V8仍跳过；无新增用户决策阻塞。

## 2026-10-19 · Claude · V10 测试任务安排（V-Gate4 进行中）
状态：给 Codex 安排下一轮工作；V-Gate4 依据 V10 报告完成。Claude 本周额度不足，本条只做任务安排与 V9 边界审阅，**没有重跑测试**。
V9 审阅（只读）：D-039 / V.20 的五项实现边界合理：
- 选择门不默认第一张，选择结果绑定版本、候选与来源摘要；
- 上下文压缩只作用于发给模型的旧成功回执，原历史与账本不变，错误和约束保留；
- 死节点只按数据引用判定，选择候选全部计入；
- 多参考选型不放宽用户的精确型号、系列和排除约束。
Codex 的 2218 项全量回归与前端 134 项记录完整。真实效果待 V10a 验证。

### 给 Codex：V10 测试任务（按顺序；全部遵守 D-030 与规则 6）
**通用约束**
- 文本 `deepseek-v4.1-flash`，多模态 `qwen3.7-plus`（多图一次调用）；**视频生成 0**；本轮图片生成也应为 0（V10b 用 Mock 媒体）。
- 只用临时 SQLite / 存储；绝不连接 `.env` 中的 MySQL / Redis；不修改真实 `.env`。
- 评测脚本：`backend/scripts/v3_eval/`（已屏蔽视频适配器）。可以扩展脚本，但保留现有安全护栏。
- 调用上限：本轮真实 LLM / 视觉调用总数 ≤ 800。超过时停止并在报告中说明。
- 每个失败都要写根因。不要只为让某个用例通过而调提示词；如果确实修改了提示词或 Skill，记入 DECISIONS 并说明对其他用例的影响。

**V10a 真实评测复跑**
- 跑 `python backend/scripts/v3_eval/eval_v3.py all` 一次，c3、c5 各再跑 2 次（看稳定性）。先给脚本补充记录以下指标：每轮输入 token 的最大值与总和、LLM 轮数、委派树、计划节点、是否出现 `select_image` / choice 门、编译问题码。
- 量化目标（对照 `docs/agent_v3/VGATE3_EVAL.md`）：
  1. c1 / c2 / c6 简单任务：不委派；LLM 轮数 ≤ 6（上次 9）；进入 `awaiting_plan_review`。
  2. c3 长片：3 次中至少 2 次进入 `awaiting_plan_review`；单轮输入 token 最大值 ≤ 60k（上次约 110k）；规划 ≤ 20 credits；最终计划没有 `PLAN_UNUSED_PAID_NODE`；多人同框关键帧使用支持多参考的模型，并保留全部角色参考。
  3. c4：只提问，不出计划。
  4. c5：使用选择门；动画引用用户所选的候选，不默认第一张。
- 可选：用 `EVAL_V2=1` 只复跑 c1、c2 作为速度基线（不必全量）。

**V10b 混合执行测试（真实 LLM + Mock 媒体，零生成费用）**
- 给评测脚本加 `EVAL_MOCK_MEDIA=1` 模式：LLM 与视觉理解走真实模型；图片、视频生成适配器替换为 Mock（拼接、质检用本地 FFmpeg 与 Mock 哨兵）。用计数器断言真实媒体服务商的调用为 0。
- 场景：
  1. c3 计划批准 → 定妆和关键帧预览门逐个确认 → 生产 → 审核 B → 交付 `success`。
  2. 生产中给某个视频节点注入 `content_policy` 失败 → Repair（真实 LLM）诊断 → Director 审阅 Patch → 如果只改提示词且在修复额度内则自动继续，否则生成报价等待人工批准；两种情况各覆盖一次。
  3. 审核 B 时用户 `revise_plan`（例如“把第 3 镜改成雨夜”）→ Patch → 报价 → 人工批准 → 只重做受影响的子图。
  4. c5 选择门：选第 2 张候选 → 动画引用第 2 张；再改选第 3 张，验证旧批准失效、需要重新确认。
  5. 规划进行中强杀 worker 并重启一次 → 不重复调用 LLM、不重复计费、Run 能继续。
- 每个场景记录状态流转、账本条目、Patch 与报价、调用量。

**V10c MySQL 迁移与并发（须用户确认后执行）**
- 需要用户同意在本机启动一个一次性 MySQL 8 容器（非默认端口，例如 3307，测试后删除）。在全新库上执行 `db upgrade` 到 head；再从 v2 的迁移头升级到 head；跑一次 v3 Mock 冒烟，以及两个 Run 并发规划。
- 没有得到用户确认就跳过，并在报告中注明。

**交付**
- `docs/agent_v3/V10_TEST_REPORT.md`：逐项列出指标表、与 V-Gate3 的对比、失败根因、调用量（次数、token、演示 credits），以及真实媒体调用为 0 的证据。
- PLAN 中 V10a / V10b / V10c / V10-Report 的状态与 PROGRESS 交接。修复发现的问题时走正常分支流程并补测试。
- 不推送、不进入 V8；V7 美化仍归 Claude。

## 2026-10-19 · Claude · 用户批准 V10c
用户在对话中批准 V10c：允许在本机启动**一次性** MySQL 8 Docker 容器做迁移与并发验证。限制条件：
- 非默认端口；容器与数据卷名带 `cinecrew-v10c` 前缀；测试结束后删除容器和数据卷；
- 绝不连接或读取 `.env` 中的 MySQL / Redis 配置；
- 不修改真实 `.env`；只做本地验证，不推送。
其余 V10 要求见上一条。

## 2026-10-19 · Codex · V10a 真实规划复跑完成
状态：agent-v3/V10a 完成；本条随脚本提交后本地合入 feat/agent-v2，再进入 V10b。不推送、不进入 V8、不改 V7 界面。
变更：评测增加逐轮真实 usage、输入 token 最大值/总和、委派树、完整计划与选择引用、编译问题码；免费 check_plan 无账本，额外读取原始历史回执。Run 独立归档，避免多次同场景覆盖。禁用 dotenv 自动加载，只解码白名单 DashScope 凭据；隔离 SQLite/存储，媒体生成/上传全阻断，跨进程 HTTP 预留账本硬限 800 次，未知请求禁止盲目重发。
验证：安全护栏与指标 25 项通过。真实 eval_v3.py all 一次，再 c3/c5 各两次，共十个 Run，未修改产品提示词、Skill 或规划实现。c1/c2/c6 均无委派并进入审核，LLM 轮次分别 8/6/8，只有 c2 达到六轮目标。c3 三次均进入审核，规划费用 9.28397/12.22532/10.44906 credits，最终无付费死节点；输入峰值 69,481/64,185/82,588，全部超过 60k。第一、三次双角色关键帧完整传入两个角色参考；第二次 Director 参数连续出错后由 Producer 兜底，省掉关键帧，双角色同框视频只传一个角色图，不能判一致性结构通过。c4 只提问；c5 三次均有 select_image/choice 且动画引用选择结果，真实选择/改选留给 V10b。
根因：简单任务猜错 brief 字段、错误型号及重复节点等增加纠错轮次；长片历史仍保留长篇计划函数参数和目录，软字符压缩不等于 60k token 硬上限；子 Agent 参数 JSON 错误与 8000 输出 token 附近的截断迹象导致兜底简化。未为单例调提示词。
调用：153 次文本 deepseek-v4.1-flash + 1 次视觉 qwen3.7-plus，共 154/800；图片/视频生成均 0。原始证据在 TEMP/cinecrew-v10-20261019，最终报告将核对唯一账本并合并 V10b 总量，credits 是演示价而非实际账单。
下一步：V10b 复用第一份 c3 做完整交付、第三份 c3 做审核 B 修订；先修正两处已有 D-038 活跃时间实现遗漏并补回归（Repair 仍用墙钟；运行时错误早退漏计），不改变契约/提示词/额度。保留本次 V10a 原始结果；用户私人未跟踪技术笔记与 .env 均未修改。

## 2026-10-19 · Codex · V10b 混合执行完成
状态：agent-v3/V10b 完成，验证后本地合入 feat/agent-v2；未推送。未修改提示词、Skill、契约或前端。
变更：EVAL_MOCK_MEDIA=1 保持真实 LLM/视觉，仅替换媒体适配器，使用本地同步 Job、FFmpeg 与可解码占位素材；HTTP 白名单和持久化累计上限保持。修复 D-038 两处遗漏：Repair 准入改读配置的活跃时间，运行时错误/早退也累计已执行时间；不计用户/子 Agent 等待。异常先回滚未完成状态，费用/幂等/额度规则不变。
执行：六个场景全部通过：c3 交付 success（13 个预览门）；content_policy 注入后的 Repair→Director 自动修复和额度不足人工批准各一次；第三镜雨夜修订只新增该镜关键帧/视频生成收据，其他 28 节点内容不变；选择第二候选后改选第三候选，旧批准拒绝并重新确认，候选图复用；真实强杀子进程后第一恢复步无新增请求/费用，继续到计划审核。
验证：计时/修复/运行时/预算/上下文及混合脚本 154 项通过；随后新增修订范围检查 33 项并重跑混合脚本 12 项，共 45 项通过。范围守卫在本次真实修订之后补入：实际修订用原始版本/Patch/报价/任务做独立事后审计通过，不能宣称该真实运行已使用新守卫。测试报告位于 TEMP/v10b-targeted.xml 与 v10b-scope-final.xml。
调用：V10b 新增文本 34 次，输入 644688、输出 11629 token，演示 LLM credits 6.56317；Mock 媒体账本 356 credits（含两次注入失败的保守预算记录），不是真实生成收费。A+B 累计 188/800 次，真实图片/视频均 0；最终报告按唯一账本核算。
未达与根因：自动修复把“猫跳舞”改为自然摆动，虽只改提示词且流程合规，存在需求弱化；注入没有供应商真实诊断，不能证明其推测的政策原因。人工修复有一次 review_patch reason 超长；强杀新 Run 恢复后仍发生 brief/节点/交付 Schema 错误和未保存 workspace 引用，纠正后继续。第三镜 Patch 的 origin.agent 元数据被写为 repair，与 Director 审阅记录不一致，留给 Claude 评审。
边界：强杀仅覆盖“成功账本已提交、checkpoint 未推进”；不覆盖 HTTP 在途结算，活跃时间未提交区间仍可能丢失。同步 Mock 调度不能验证 Redis/MQ 并行吞吐或真实画质。固定零计数字段不是独立抓包证据，零生成结论同时依据白名单、实际 HTTP 审计及拒绝测试。未连接真实数据库/Redis，未改 .env，私人未跟踪笔记保留。
下一步：按已批准范围执行 V10c，一次性 MySQL 8 容器和数据卷用 cinecrew-v10c 前缀、非默认端口，结束删除；再交付报告给 Claude V-Gate4。

## 2026-10-19 · Codex · V10c 一次性 MySQL 验证完成
状态：agent-v3/V10c 完成，验证后本地合入 feat/agent-v2；未推送。
完成内容：新增 Docker.ps1 / mysql_verify.py，禁止 dotenv 与外部 HTTP，模型全部 Stub/Mock；只允许 loopback 非默认 MySQL 端口。固定本地 mysql:8.4.4 镜像，在 127.0.0.1:3307 创建 cinecrew-v10c-20261019202619-cb8ab880 容器及同前缀 -data 卷，使用一次性密码与临时存储。
测试：离线护栏 5 项通过。真实 MySQL 8.4.4 四项全部通过：空库实际 db upgrade 到 20261019_005；新库先到 v2 头 20261018_002、插入四表 UTF-8/JSON 历史记录再升到 head，记录完整保留；v3 三轮 Stub 规划、Mock 图片生产与人工两次审批到 success；两个独立线程/SQLAlchemy 会话 Run 重叠规划，各三轮到审核，委派/工作区/版本/账本 ID 不串用。未使用 create_all/自动补表，不修改迁移或业务代码。
证据：TEMP/cinecrew-v10c-run-01/mysql-evidence.json 与 docker-lifecycle.json。容器/数据卷删除退出码均 0；独立 Docker 精确名称查询均不存在。测试真实 LLM/视觉/媒体/外部 HTTP 调用均 0；本次 Mock 媒体演示 credits 2，迁移夹具历史 1.25 不计为新消耗。
边界：并发覆盖两个不同 Run，不涵盖同 Run 抢占、Redis/MQ 或压力测试；checkpoint 使用独立内存 saver，MySQL 验证针对应用持久化表，不声称 MySQL 存储 LangGraph checkpoint。未读取真实 .env/MySQL/Redis，私人未跟踪技术笔记保留。
下一步：完成 V10_TEST_REPORT、逐项达标/未达根因与累计调用核算，更新看板，交给 Claude V-Gate4。

## 2026-10-19 · Codex · V10-Report 完成，交给 Claude V-Gate4
状态：V10a/V10b/V10c 与报告均完成；测试任务完成不等于全部量化目标通过。各阶段按任务分支本地验证合并：V10a f1e4eb8、V10b 2170c5e、V10c d3ab5f5；本条与 V10_TEST_REPORT.md 随 agent-v3/V10-Report 提交合入 feat/agent-v2。不推送、不开 PR、不进入 V8，V7 美化未改动。
已达成：c1/c2/c6 均不委派并进入审核；c2 六轮达标。c3 三次均进入审核、规划均低于20 credits、最终无付费死节点；c4 只提问；c5 三次选择结构正确，B 验证显式选第二张/改第三张与旧批准失效。B 六个控制流场景通过（完整交付、两种Repair→Director分支、审核B局部修订、选择/改选、已结算窗口强杀恢复）。C 四项真实 MySQL 8.4.4 测试通过，临时容器和数据卷已删除。
未达及根因：c1/c6 各8轮，brief/模型/重复节点纠错超过六轮目标；c3 峰值69481/64185/82588，软字符投影仍保留长计划参数、错误与目录，均超过60k token；第二份长片子Agent参数JSON持续错误且出现8000输出token截断迹象，Producer兜底省掉多人关键帧，仅一个身份参考，故多角色结构2/3。c5 单prompt n=3未保证逐张三风格；自动修复弱化“猫跳舞”意图；第三镜Patch来源标签repair与Director实际流程不一致。报告逐项记录中间失败和证据，不以最终编译通过代替语义验收。
最终用量：187次 deepseek-v4.1-flash + 1次 qwen3.7-plus，共188/800；真实输入4843479、输出226490 token，真实调用演示credits50.72617。B Mock媒体356+C Mock媒体2=358，合计演示账本408.72617；迁移夹具历史1.25排除，不是真实货币账单。真实图片/视频/HappyHorse调用均0，缺失usage/未知HTTP/越界尝试均0。
回归：V10a护栏与指标25项；V10b计时/修复/执行集成154项；后补局部范围守卫33项及重跑混合脚本12项合计45项；V10c离线护栏5项，均通过。没有把重复12项算新增；未将V9的2218项旧全量结果冒充本轮复验。仅两处D-038计时实现修复，无提示词/Skill/契约调整。
证据与边界：docs/agent_v3/V10_TEST_REPORT.md；TEMP/cinecrew-v10-20261019 为A/B原始账本、HTTP审计、逐Run归档；TEMP/cinecrew-v10c-run-01 为MySQL/清理证据。强杀只覆盖成功回执已提交而checkpoint未推进，未验证HTTP在途结算；活跃时间未提交区间可能丢失。MySQL是不同Run双线程与内存checkpoint，非同Run多worker压力测试；未验Redis/MQ吞吐、真实媒体质量与身份一致性。scope守卫在真实修订后加入，原结果经独立事后范围审计通过、守卫经离线回归，不声称已付费重跑。
交给Claude：完成V-Gate4，优先判定长片身份输入语义退化、自动修复意图保真、结构化参数/输出截断与上下文开销，并审查计时修复；结合报告决定后续修复任务。所有真实测试均已结束，无新增调用安排。用户未跟踪的AI_Video_Factory_Technical_Notes_CN.md保留；真实.env/MySQL/Redis未修改或连接；没有新的用户决策阻塞。

## 2026-10-20 · Claude · V-Gate4 审计结论与 V11 任务
状态：V-Gate4 **有条件通过**。审读了 `docs/agent_v3/V10_TEST_REPORT.md` 全文，并只读抽查原始数据：c3 #2 的 s03/s04/s07–s11 在 `depends_on` 中列出两个角色，但首帧只引用 `cast_deepseek.image`，与报告一致。Claude 额度有限，本轮没有重跑测试。
达成：隔离与零生成（188/800 次真实调用，真实图片/视频 0）；长片 3/3 进入审核且规划 <20 credits；选择门结构 3/3，运行时选择与改选通过；混合执行 6/6 控制流通过（交付、自动/人工修复、审核 B 局部修订、强杀恢复）；MySQL 8.4.4 迁移与双 Run 并发通过。报告如实区分了“控制流通过”和“内容满足”，这一点值得肯定。
判定：
- **阻塞默认开启 v3 的三项**（V11a–V11c）：
  1. 多角色身份输入只靠提示词与依赖边，Director 失败后 Producer 兜底时会悄悄丢掉身份参考。这是生成质量的根本问题，必须由编译器确定性校验。
  2. 自动修复把“猫跳舞”改成“自然摆动”，改变了用户点名的核心内容却被自动批准；这类改写必须交给用户确认。
  3. Patch 产物的来源标签错误，会误导审计与界面展示。
- **不阻塞，但要做的效率项**（V11d–V11g）：
  - 简单任务的额外轮次主要来自 brief 结构纠错；
  - 长计划一次输出超过 8k token 会被截断；
  - 长片单轮输入峰值 82k，超过 60k 目标。这个目标保留，但量化的是真实 token，不是字符数；
  - “三种风格各一张”目前只是单个提示词生成 3 张，无法保证逐张对应。
- 已知未验证，不阻塞，继续记录：真实媒体质量与角色一致性、HTTP 在途崩溃窗口、同 Run 多 worker 竞争与 MQ 吞吐。

### 给 Codex：V11 任务（按 V11a → V11c → V11d–g 顺序；规则与 D-030 不变）
- V11a 多角色身份输入（契约先行：DECISIONS → CONTRACTS）：
  - 生成类计划节点增加可选字段 `characters: [character_id]`，由 Director/Producer 依据故事填写；
  - 编译器要求：节点声明的每个角色，其参考图都必须出现在该节点的**数据引用链**中（直接引用，或经由引用了它的关键帧）；只出现在 `depends_on` 中不算；缺失时报阻塞问题，并写明缺哪个角色、可选修复方式（例如增加多参考关键帧）；
  - Producer 兜底时同样受此约束；
  - 补测试：复现 c3 #2 的结构必须被拒。
- V11b 自动修复意图保真：
  - Director 审阅 Patch 时必须给出结构化判断 `intent_preserved: bool` 与被移除/改变的用户点名元素列表；
  - 只有 `intent_preserved=true` 且满足原有低风险条件才可以自动批准，否则进入人工审批；
  - Run 视图与 Patch 卡片展示改写前后差异和原因；
  - 补测试：复现“猫跳舞 → 自然摆动”必须进入人工审批。
- V11c 来源标签：Patch 产生或修改的节点，其 `origin.agent` 与实际作者（Director/Repair/用户修订）一致，rationale 的修改单独标注；补测试。
- V11d 简单任务效率：优先在 Producer 提示词与 `intent-analysis` 中给出完整的 RequirementBrief 最小合法示例；对确定无损的常见形式（例如 subjects 写成字符串列表）可以由服务端规范化，但不得猜测语义。目标：c1/c6 ≤ 6 轮。修改提示词或 Skill 要在 PROGRESS 说明。
- V11e 长计划输出：记录服务商 `finish_reason`；长 PlanDraft 支持分批写入或增量更新（例如按节点批次追加），使单次输出不必超过上限；截断时给出明确错误码而不是 JSON 解析错误。
- V11f 上下文峰值：发给模型的历史中，只保留最新一版计划草稿的完整工具参数，旧版本投影为工作区引用；目标长片单轮输入峰值 ≤ 60k **token**（真实 usage）。
- V11g 选择门逐张风格：编译器允许选择门汇集多个独立生成节点作为候选；`image-create` / `plan-review` Skill 指导“N 种风格各一张”时规划 N 个节点。
- 完成后执行 V-Gate5 测试（D-030，真实调用 ≤ 400 次，图片/视频生成 0，混合执行仍用 Mock 媒体）：复跑 c1、c6、c5 各 1 次，c3 共 3 次；混合执行复跑自动修复（期望进入人工审批）与审核 B 修订；补一个新用例：用户给出完整情节的长片（期望不委派 Creative）。报告写入 `docs/agent_v3/V11_TEST_REPORT.md`，交 Claude 审读。
- 每个任务一个分支，全量后端回归与前端构建通过后本地合并；不推送，不进入 V8，V7 美化仍归 Claude。

## 2026-10-20 · Claude · V7（界面美化）
状态：完成（V3PatchReview 除外）
分支与提交：`agent-v3/V7-polish`（独立 worktree，不碰 Codex 的 V11a 工作区），已合并到 `feat/agent-v2`
完成内容：
- 新增 `frontend-vue/src/components/agent/v3-tones.js`：统一状态色（成功/失败/等待/执行中）与各 Agent 角色色。
- `V3RunPanel.vue`：头部图标与状态胶囊；预算三项改为带进度条的统计卡；需求与附件卡片；产物改为卡片网格。
- `V3Collaboration.vue`：委派树改为带角色色头像的缩进卡片，步骤记录改为时间线；分页文案不变。
- `V3PlanBoard.vue`：统计卡、按状态着色左边框的节点卡（带工具图标）、闸门提示条、候选图网格（可见单选框 + 选中角标）、审批/修改操作区。
- 只改样式和模板结构，所有测试依赖的文案、testid、aria 标签保持不变；没有改 `messages.js`，也没有改后端。
测试：`node --test tests/*.test.js` 134 passed；`npm run build` 通过；浏览器冒烟 `agent-v3.smoke.js`（1440/400 宽，亮/暗色，无横向溢出，pageErrors 0）和 `agent-v9-choice.smoke.js` 均 PASS。
未完成 / 下一步：
- `V3PatchReview.vue` 会被 V11b（意图保真差异展示）改动，等 V11b 合并后再由 Claude 美化，避免冲突。
- 手机端全局侧边栏仍按原计划延后。
需要对方或用户决定：无。Codex 合并 V11a 时，本文件末尾可能出现追加冲突，保留双方条目即可。

## 2026-10-20 · Codex · V11a 实现与验证进行中
状态：进行中，尚未合并。
分支与提交：agent-v3/V11a，从 feat/agent-v2 @ 268860b 切出；当前实现未提交。
完成内容：先记录 D-040，再补 V.21.1；新增角色目录、固定故事引用、节点角色声明与按实际媒体数据链校验，选择候选/拼接取共同依据，依赖边不证明身份。story-video builder 同步角色声明。旧已保存计划保持原摘要，新修订可通过必须人工审核的 identity_upgrade 补齐；可能扩大重做范围，报价不隐藏。Producer/Director、角色一致性与计划审阅 Skill 只补对应合同说明，交 Claude 复审。
测试：身份/编译/Blueprint/作者合同/多参考选型定向191项通过；新增升级19项及完整编译集成1项通过。全量收集2402项，正在四进程隔离执行；前端隔离构建已通过。证据目录 TEMP/cc-v11a-1020123528-dad7，必须待 summary.json 最终 passed=true 后才合并，不能把定向结果当全量。
未完成 / 下一步：完成 V11a 全量核验后本地合并，依次 V11b–V11g，再按本轮400次硬上限执行 V-Gate5 真实规划与混合测试。目前真实调用0，媒体调用0。子任务仅在 TEMP 准备后续实现，没有混入当前分支。真实 .env/数据库/Redis未读取或连接，私人未跟踪技术笔记保留；不推送、不进入V8。
需要对方或用户决定：无。

## 2026-10-20 · Codex · V11a 全量验证完成
状态：V11a 完成，本条随任务分支提交后本地合入 feat/agent-v2，不推送。
完成内容：D-040 / V.21.1 对角色身份输入按真实媒体引用链校验；c3 #2 双角色只传单人首帧的结构被拒。原有旧计划摘要保持兼容，新增 identity_upgrade 明示角色目录/节点改动并强制人工审核，不绕过完整编译。
验证：TEMP/cc-v11a-1020123528-dad7/summary.json 最终 passed=true。后端127文件、2402项全部通过，缺失/多余/重复/失败/跳过均0；测试期间源码冻结，隔离审计事件0；前端构建通过。定向191项及升级20项也通过，不重复计入全量新增。
下一步：独立 V11b 分支先写意图评估决策与契约，再引入实现与回归。后续 V11c–g 仅在 TEMP 准备，尚未合入；每阶段继续完整后端与前端构建验证。真实模型调用0、真实媒体0；未读取真实.env/连接MySQL或Redis，私人未跟踪技术笔记保留。
交给Claude：本项结构验证不代表真实角色画质一致，也不证明模型一定正确填写出场角色；最终 V-Gate5 实测后统一评审。

合并说明：发现 feat/agent-v2 已包含 Claude 的 b75dbcd（V7 美化），因此采用保留双方提交的本地 merge；仅 PROGRESS 追加条目冲突，双方记录均保留。合并后的后端与已验证 V11a 完全相同；Claude 界面文件原样保留，另复验前端134项和隔离构建通过。V11a 实现提交 3cf0685。

## 2026-10-20 · Codex · V11b 实现与全量验证进行中
状态：agent-v3/V11b 进行中，基于本地合并 5ea3a9e；V11a 已合入，当前 B 尚未提交。
完成内容：先落 D-041 / V.21.2，指定 Director 审阅显式给意图评估与元素变化，不可变证据绑定最终草稿、原需求和冻结约束；变化/未知不得自动批准。保留 A 的身份升级人工门。Patch 功能卡片展示前后内容与原因，不改 Claude 的 V7 美化文件。
验证：前端137项通过；B新增44项及既有夹具已迁入，旧自动预期夹具显式保存可信评估，未增加生产默认true。完整后端与构建在 TEMP/cc-v11b-1020161904-865f 运行，须待 summary.json 最终通过后才合并。TEMP初轮个别媒体测试失败来自未设FFmpeg路径，修正测试环境后回查，不修改业务断言掩盖。
下一步：B全量通过后提交合并，再按 D-042 / V.21.3 推进 C，随后 D–G；TEMP后续提案不算正式完成。真实调用0，媒体0；仍不推送、不进入V8，不读取真实数据库/Redis配置，私人未跟踪笔记保留。

验证补记：首轮完整收集2446项，发现旧 `test_patch_candidate_reorder_requires_new_selection` 手改草稿却仍复用旧不可变意图评估，按新约束正确拒绝。单项复现 `PATCH_REVIEW_REQUIRED` 后，将夹具改为实际提议与独立审阅；修正后单项通过（TEMP/cinecrew-v11-choice-fixture-20261020/b-original.xml、b-fixed.xml）。首轮12进程吞吐明显下降，疑似临时SQLite磁盘争用；已停止且保留失败/中止证据，不能计作全量通过。修正后完整四进程重跑目录为 TEMP/cc-v11b-1020163553-1182；未放宽业务规则或审批条件。

浏览器补记：V11b卡片功能检查通过，1440/400宽度与亮/暗色四组布局均无横向溢出；未知意图与猫跳舞→自然摆动/删除聚光灯均展示人工确认提示、前后内容及原因。历史报价不能直接批准，四次获取报价无动作提交，最后仅一次显式批准绑定当前quote_id。全部API为Mock，外部字体请求已阻断，pageErrors=0；视口截图已人工查看，证据在忽略目录 `.playwright-mcp/v11b/final-result.json` 与同目录截图。超长卡片的初版整元素截图受内部滚动裁剪，改拍实际视口后重新完整检查通过；未更改产品布局或Claude美化文件。静态预览已关闭。

## 2026-10-20 · Codex · V11b 全量验证完成
状态：V11b 完成，任务提交后仅本地合入 feat/agent-v2。
完成内容：Director 必须给出结构化意图评估并绑定不可变草稿证据；改变点名元素或无法确认保真时不可自动批准。猫跳舞→自然摆动的回归进入人工审批；身份升级与既有预算/范围门保留。卡片显示前后内容和理由，未改 Claude 的 V7 美化。
验证：TEMP/cc-v11b-1020163553-1182/summary.json 最终 passed=true，128文件、2446项全过，遗漏/多余/重复/失败/跳过均0，源码冻结与隔离审计通过，前端构建通过；另前端137项与浏览器四组布局/显式审批通过。首轮旧夹具失败及中止记录保留，修复的是失效的审核证据夹具，没有放宽产品规则。
下一步：V11c 独立分支先落 D-042 / V.21.3，再引入可信作者与历史实际差异；TEMP 复核另外发现同作者 insert.before 的附带依赖展示遗漏，拟一并补齐。D–G 后执行 V-Gate5，仍由 Claude 审定；当前真实调用0、媒体0，不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-20 · Codex · V11c 实现与验证进行中
状态：V11b 已提交并本地快进合并为 d1c5c47；当前 agent-v3/V11c，尚未提交。
完成内容：先记录 D-042，再补 V.21.3；提议作者和 Director 最终修订者依据委派、不可变工作区及对应工具收据核验。批准与报价使用同一规范化候选，未改节点不改来源。来源、rationale 和显式/附带 depends_on 差异单列，applied 只展示实际批准版本（包括旧错误），缺版本不伪造结果。approve 审阅沿用 B 的不可变评估边界，不夸称所有审阅都新增原工具收据校验。
验证：TEMP候选曾发现免费 propose_patch 收据加入后旧夹具总数应从0改为精确仅一条提议，已迁移；另一次本地媒体 INVALID_SOURCE 未复现，原日志无stderr，根因未确定，失败证据保留在 TEMP/cinecrew-v11c-fixtures-20261020。正式定向验证在 TEMP/cc-v11c-focus-1020171038-ad6a 进行，随后仍须全量后端、前端构建和浏览器检查，不将TEMP部分通过当整阶段通过。
下一步：C 通过后本地合并，再逐阶段 D–G；F 应使用 ef-integration 中已移除 AppendStub 的最终测试副本，E/F结合59项纯函数验证已通过但不替代正式全量。当前真实调用0、媒体0；不推送、不进入V8，私人未跟踪笔记保留。

验证补记：正式定向95项通过（TEMP/cc-v11c-focus-1020171038-ad6a），前端137项通过；完整2477项/131文件及构建在 TEMP/cc-v11c-1020171315-c5de 执行，构建已通过，后端仍在运行。浏览器1440/400宽、亮/暗色四组均通过，实际作者/原提议作者、历史原值、长理由和人工审批可用，横向溢出0、pageErrors=0，四次只读报价及一次显式批准均为Mock；证据 `.playwright-mcp/v11c/result.json`，视口截图已检查，临时预览已关闭。附带 depends_on 的展示由7项后端回归覆盖，不把本次浏览器夹具描述成依赖边专项测试。完整结果未通过前不提交合并。

## 2026-10-20 · Codex · V11c 全量验证完成
状态：V11c 完成，任务分支提交后仅本地合入 feat/agent-v2。
完成内容：Patch 的提议和最终修订作者使用服务器证据核验；批准、报价和公开差异一致，历史已批准版本展示实际值，不回写修饰旧来源。来源、理由及直接/附带依赖变化分别展示，保留 A/B 人工审批门。
验证：TEMP/cc-v11c-1020171315-c5de/summary.json 最终 passed=true。131文件、2477项全过，遗漏/多余/重复/失败/跳过均0，源码冻结、隔离审计和前端构建通过；另有正式定向95项、前端137项和浏览器四组检查。完整回归约61分钟，未因耗时放弃或缩小检查。
下一步：独立 V11d 分支先写 D-043 / V.21.4，再引入合法 brief 示例与完整情节路由；随后 E–G 及真实 V-Gate5。当前真实调用0、媒体0；不推送，不进入V8，私人未跟踪笔记保留。Claude 的 V7 文件保持原样，V3PatchReview 仅本轮功能变更。

## 2026-10-20 · Codex · V11d 实现与验证进行中
状态：C 已提交并本地合并为 8cb3cbe；当前 agent-v3/V11d。
完成内容：先落 D-043 / V.21.4，再增补 Producer/Director、intent-analysis/delegation-policy：完整合法 brief 示例、必要资料按需读取，用户已提供完整情节时不为补 StoryPackage 格式调用 Creative；确有知识缺口仍允许 Research。不引入猜测语义的服务端自动纠错，不放宽审批或角色身份校验。两份 Skill 版本升2，增补交 Claude 在 V-Gate5 复审。
验证：迁入前精确增量和前序状态检查通过；新增10项正式 Mock/Stub 测试在 TEMP/cc-v11d-focus-1020181518-838b 执行，随后执行完整后端和前端构建。Stub 短路径不代表真实六轮目标已达。
下一步：D 完整验证通过后本地合并，再 E–G 与真实评测。本轮仍真实调用0、媒体0，不推送、不进入V8。

## 2026-10-20 · Codex · V11d 全量验证完成
状态：V11d 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：完整 brief 示例与完整情节直接规划。Producer/Director、intent-analysis/delegation-policy 增补；保留原用户情节，不为格式调用 Creative。没有自动猜测字段语义。 契约先行，策略/Skill增补交Claude复审。
验证：TEMP/cc-v11d-1020181631-3b7e/summary.json 最终 passed=true，132文件、2487项全过；精确ID遗漏/多余/重复/失败/跳过均0，源码冻结、隔离审计和前端构建通过。详细命令、JUnit与源码快照保留在该目录。
下一步：进入下一个独立任务分支继续验证；Mock控制流不代表真实轮数、token或画质达标。真实调用0、真实媒体0；不推送、不进入V8，未跟踪私人笔记保留。

## 2026-10-20 · Codex · V11e 实现与验证进行中
状态：当前 agent-v3/V11e，前序已完整验证并本地合并，尚未合入本项。
完成内容：先记 D-044 再落 V.21.5，增量迁入长计划分批写入与明确截断回执。append_plan_nodes 仅向精确最新版追加1–12节点，CAS、权限、收据重放和审批后 Patch 门保留；check_plan 支持精确引用。记录 finish_reason，length 整批工具拒绝并记 AGENT_OUTPUT_TRUNCATED，结算真实usage且有界纠错。长计划资料增补，plan-review升5、long-form-video升2。
验证与下一步：执行本项新增回归，再完整后端与前端构建；以TEMP/cinecrew-v11-prep/offline-stages-journal.json记录的实际summary为准，失败即停，不把准备稿结果当正式通过。当前真实调用0、媒体0，不推送、不进入V8，不改Claude美化。

验证补记：新增50项正式定向通过（TEMP/cc-v11e-focus-1020190341-40cf）。首轮全量 TEMP/cc-v11e-1020190524-formal 收集/执行2537项，2536通过、1失败；源码冻结、隔离审计和构建通过。唯一失败为 test_v3_catalog_does_not_mutate_legacy_roles_or_descriptions 的旧清单只列42个v3工具，没有新增 append_plan_nodes。已停止后续阶段，补齐精确清单/43数量并明确新工具仅Producer/Director可见、属于write且不可作为生产节点执行；经典22工具及角色/描述不变的原断言保留。此项是契约增量所需兼容性夹具迁移，不修改产品行为或放宽安全条件；须重新完整验证后才合并。

## 2026-10-20 · Codex · V11e 全量验证完成
状态：V11e 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：长计划分批写入与明确截断回执。append_plan_nodes 仅向精确最新版追加1–12节点，CAS、权限、收据重放和审批后 Patch 门保留；check_plan 支持精确引用。记录 finish_reason，length 整批工具拒绝并记 AGENT_OUTPUT_TRUNCATED，结算真实usage且有界纠错。长计划资料增补，plan-review升5、long-form-video升2。 契约先行，策略/Skill增补交Claude复审。
验证：TEMP/cc-v11e-1020195400-catalog-fixed/summary.json 最终 passed=true，134文件、2537项全过；精确ID遗漏/多余/重复/失败/跳过均0，源码冻结、隔离审计和前端构建通过。详细命令、JUnit与源码快照保留在该目录。
下一步：进入下一个独立任务分支继续验证；Mock控制流不代表真实轮数、token或画质达标。真实调用0、真实媒体0；不推送、不进入V8，未跟踪私人笔记保留。

## 2026-10-20 · Codex · V11f 实现与验证进行中
状态：当前 agent-v3/V11f，前序已完整验证并本地合并，尚未合入本项。
完成内容：先记 D-045 再落 V.21.6，增量迁入旧已保存计划参数的请求视图投影。只投影有保存证明的旧参数与冗余成功检查，保护最新参数和完整读取，原消息/账本/工作区及冻结 pending_context 不改。60000字符仍是软目标，真实60000 token目标由最后评测判定。使用真实 AppendInput 回归，无兼容Stub。
验证与下一步：执行本项新增回归，再完整后端与前端构建；以TEMP/cinecrew-v11-prep/offline-stages-journal.json记录的实际summary为准，失败即停，不把准备稿结果当正式通过。当前真实调用0、媒体0，不推送、不进入V8，不改Claude美化。

验证补记：V11f 首轮完整 TEMP/cc-v11f-1020204012-formal 为2573通过、2失败，构建/源码冻结/隔离审计通过，后续阶段自动停止。失败为安全测试之后的 Wan3 两个 HTTP Stub 协议测试。根因是既有 CallMeter._patch 通过 getattr 记录已被包装的继承方法，卸载时 setattr 将父类护栏固化为子类自有方法，造成测试顺序泄漏；并非 Wan3 协议变化，也没有发生真实调用。新增两项回归，先在 TEMP/cc-v11f_safety_red-focus-1020212634-00b3 复现属性归属未恢复，再修复评测护栏按原始类描述符/继承关系逆序还原；不放宽任何计费、HTTP或媒体阻断规则。必要修复范围增补 backend/scripts/v3_eval/safety.py 与其原有测试，接口/提示词/Skill不变。须按原失败顺序跑安全测试→Wan3协议测试，再重跑完整后端和构建后才合并。

修复定向验证：TEMP/cc-v11f_safety_fixed-focus-1020212713-3d5d 为120项全过（安全护栏→Wan3适配器→上下文投影），11.75秒；源码冻结、隔离审计通过。包含重复安装/卸载、嵌套护栏、继承属性恢复与外层传输Stub保留，既有两项协议断言原样通过。继续2577项完整后端和构建，尚不能视作阶段完成。

## 2026-10-20 · Codex · V11f 全量验证完成
状态：V11f 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：旧已保存计划参数的请求视图投影。只投影有保存证明的旧参数与冗余成功检查，保护最新参数和完整读取，原消息/账本/工作区及冻结 pending_context 不改。60000字符仍是软目标，真实60000 token目标由最后评测判定。使用真实 AppendInput 回归，无兼容Stub。 契约先行，策略/Skill增补交Claude复审。
验证：TEMP/cc-v11f-1020212835-guard-fixed/summary.json 最终 passed=true，135文件、2577项全过；精确ID遗漏/多余/重复/失败/跳过均0，源码冻结、隔离审计和前端构建通过。详细命令、JUnit与源码快照保留在该目录。
下一步：进入下一个独立任务分支继续验证；Mock控制流不代表真实轮数、token或画质达标。真实调用0、真实媒体0；不推送、不进入V8，未跟踪私人笔记保留。

## 2026-10-20 · Codex · V11g 实现与验证进行中
状态：当前 agent-v3/V11g，前序已完整验证并本地合并，尚未合入本项。
完成内容：先记 D-046 再落 V.21.7，增量迁入逐张风格候选汇入选择门。image-create升3、plan-review升6，独立n=1节点各自风格prompt，全部候选计费、下游引用实际选择；新增两个完整资源和实际Registry/Mock执行回归。沿用现有多来源编译/运行时，不新增生成权限。
验证与下一步：执行本项新增回归，再完整后端与前端构建；以TEMP/cinecrew-v11-prep/offline-stages-journal.json记录的实际summary为准，失败即停，不把准备稿结果当正式通过。当前真实调用0、媒体0，不推送、不进入V8，不改Claude美化。

验证补记：G新增4项正式定向通过（TEMP/cc-v11g-focus-1020223521-bf5b）。首轮完整 TEMP/cc-v11g-1020223642-formal 为2579通过、2失败，136文件/2581项精确执行、无跳过，源码冻结/隔离审计/前端构建通过。两项旧断言将 Skill 文档版本与 Blueprint 构建器来源版本绑定，image-create 指导升3后仍要求2，独立复现于 TEMP/cc-v11g_failure_probe-focus-1020231139-d76d。生产链确认版本独立：SkillLibrary 返回指南版本；构建器、instantiate 收据和 compiler 来源校验共同使用 Blueprint VERSION=2。仅迁移 test_v6_policy.py/test_v3_blueprints.py 的精确版本矩阵（image-create=3，其余五种=2），保留 schema、builder、来源、零写入和费用断言；不修改生产版本或放宽 provenance。补验 Registry 实例化与实际 submit 路径，再完整重跑后才合并。真实调用仍0。

## 2026-10-21 · Codex · V11g 全量验证完成
状态：V11g 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：逐张风格候选汇入选择门。image-create升3、plan-review升6，独立n=1节点各自风格prompt，全部候选计费、下游引用实际选择；新增两个完整资源和实际Registry/Mock执行回归。沿用现有多来源编译/运行时，不新增生成权限。 契约先行，策略/Skill增补交Claude复审。
验证：TEMP/cc-v11g-10202332-versions-fixed/summary.json 最终 passed=true，136文件、2581项全过；精确ID遗漏/多余/重复/失败/跳过均0，源码冻结、隔离审计和前端构建通过。详细命令、JUnit与源码快照保留在该目录。
下一步：进入V-Gate5真实规划与混合执行，统一400次硬上限，生成仍全部Mock；Mock控制流不代表真实轮数、token或画质达标。真实调用0、真实媒体0；不推送、不进入V8，未跟踪私人笔记保留。

## 2026-10-21 · Codex · V-Gate5 真实评测进行中
状态：V11a–g已逐阶段完整验证并本地合入；冻结产品提交85918ed1a76f98e1575eb7bb9cf4d6ac1ff17558。报告分支agent-v3/V11-report仅改文档，暂未提交；Claude最终审读仍待完成。
证据与用量：本轮唯一目录TEMP/cinecrew-v11-gate5-20261021-01，持久400次硬限，真实图片/视频/上传均禁止。截至c3第三次结束累计81次（80文本、1视觉），usage完整、安全/数据质量/跨账本对照通过；这是阶段快照，后续调用继续累加，不重置额度。临时SQLite/存储，禁用dotenv自动加载，仅已有白名单读取DashScope凭据，不解码MySQL/Redis值，不连接真实数据库/Redis，不改.env。
已有结果：c1/c6均5文本轮、无子委派，c1一次视觉；c5三种独立n=1风格候选经choice进入10秒动画。c3第一/第三次均120秒、角色引用完整，峰值56366/57616、规划8.59793/8.57859演示credits；第二次停在角色外观澄清，没有完成规划，已花费4.14215（含0.8 Mock检索）。Research工具要求run_id但本轮实际输入未给出真实值，自造ID被scope正确拒绝；Mock检索不能核实品牌是另一独立限制，交Claude评审，本轮未为单例修改产品/提示词或重跑。
评测脚本问题：c1外层PowerShell脚本的局部LASTEXITCODE遮蔽真实退出码，产生伪失败；原回执保留，不补造丢失退出码。已对唯一归档、冻结提交及6次实际调用独立复核，并用8项零网络Stub验证全局退出码修正；c1不重跑。自动修复原临时测试仅判断Patch批准，缺实际交付覆盖；新临时入口补推进重做/下载，7项隔离Mock通过，人工覆盖仍单独判定，产品代码未改。详情保留TEMP相应审阅记录，最终报告必须列入。
下一步：当前正在执行完整剧情c7；随后原定c2基准、真实Repair+Mock媒体与审核B局部修订，逐条停机后对账，不并发真实调用。不再重跑三次c3；失败逐项写根因。最终完成V11_TEST_REPORT.md、PLAN/PROGRESS后仅本地合并，交Claude做V-Gate5；不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-21 · Codex · V11 实现、真实评测与 V-Gate5 交接
状态：V11a–V11g 已逐任务分支验证并本地合入 feat/agent-v2；产品冻结提交85918ed1a76f98e1575eb7bb9cf4d6ac1ff17558。报告分支agent-v3/V11-report只提交报告及本看板/交接，随后本地合入；没有推送、PR或V8，Claude的V7美化及用户未跟踪私人技术笔记保留。V-Gate5待Claude审定，不能宣告全部验收通过。

实现与离线验证：D-040–D-046先于契约V.21.1–V.21.7；A身份数据链、B独立意图评估与人工门、C可信作者、D合法brief与完整情节路由、E分批写入/截断错误码、F旧草稿请求视图投影、G逐风格候选全部完成。各阶段后端完整通过数依次2402/2446/2477/2487/2537/2577/2581，均精确执行、无跳过/遗漏、源码冻结、隔离审计和前端构建通过；B/C各137项前端与亮暗/1440及400宽浏览器通过。最终全量证据TEMP/cc-v11g-10202332-versions-fixed/summary.json；后续仅文档改动，不把重复的阶段测试累加成新增用例。

真实评测：唯一目录TEMP/cinecrew-v11-gate5-20261021-01；c1/c6/c5各1次、c3共3次、完整情节c7一次，另c2一次供混合修复，未重采样。c1/c6均5文本轮、无子委派；c5三个独立n=1风格节点汇入choice，动画引用选择结果。c3第一/第三次均120秒22节点、完整身份引用链、无付费死节点，峰值56366/57616、规划8.59793/8.57859演示credits；第二次停在角色外观澄清，没有计划。2/3进入审核达到原至少2/3门槛，但较V10的3/3下降；未完成样本不能算完成长片token/费用/身份验收。c7无Creative、12情节与120秒保留，峰值58401、规划7.94256；显式16:9未落实到结构参数，关键帧补方形默认、空镜补9:16，需求保真未全通过。

混合结果：c2真实Repair3轮、Director4轮，Repair弱化“跳舞”，Director恢复字面要求但保守判intent_preserved=false，PATCH_INTENT_CHANGED禁止自动批准；测试显式批准当前quote后，Plan v2局部重做和结果批准成功，下载9651字节Mock视频。人工门已覆盖，未运行可选历史反例；真实合法自动交付分支本轮未触发，仍仅Mock回归覆盖。

审核B失败及停止原因：复用最早合格c3第一份计划，两个cast完成后，kf01的Wan2.7图生图路径直接构造DashScopeMultimodalSyncAdapter，绕过评测ADAPTERS工厂替换；全局real用于LLM，真实类预处理本地参考图时进入上传入口。安全护栏在任何上传策略GET/OSS POST之前阻断并持久记1次media block，真实上传/媒体HTTP均0。任务变为attention后，测试驱动仍尝试批准cast_gpt预览门，API正确返回409。未到首次结果审核，审核B修订、局部复用及该场景的来源验收均未覆盖；不是原计划成功执行或仅UI故障。最终安全判定failed原样保留，停止后续真实调用，不清账、不另建目录、不换样本绕过失败。

最终用量：118/400次（deepseek-v4.1-flash文本117、qwen3.7-plus视觉1），输入3453837/输出73746 token，最大输入58401；usage缺失0、HTTP未知/预留0。真实图片/视频生成0、上传0、HappyHorse0；上传入口阻断1必须和零真实媒体分开报告。LLM/视觉35.30201、Mock媒体22、Mock检索0.8，唯一账本合计58.10201演示credits、待结算预留0；包含失败工具估算，不是货币账单。最终data_quality/reconciliation通过，但safety因已阻断尝试未通过。仅临时SQLite/存储，禁止dotenv自动加载，仅白名单凭据读取，不解码或连接.env中的MySQL/Redis，不修改.env。

交给Claude：先审docs/agent_v3/V11_TEST_REPORT.md及D-040–D-046/Skill增补；决定V-Gate5，不默认开启v3。优先安排评测直接构造适配器的Mock覆盖及attention诊断回归，再补审核B；保留本轮失败证据和额度，不盲重试submission_state=unknown（本次外部护栏证据确认未发送，但业务状态本身无法证明）。另审Research必填run_id却未提供可信当前ID的上下文缺口，以及显式比例从brief到生成/拼接交付链的校验；定妆图不必强制成片比例。c3 #3/c7作者轮所需工具契约已被旧上下文策略投影，Agent未重读便起草，随后出现字段纠错；仅确认时间关联，未证明因果或增幅。真实媒体质量、角色相似度、HTTP在途崩溃、同Run多worker/MQ吞吐仍未验；逐项证据、错误根因和TEMP路径见报告。所有真实进程已结束，没有等待中的模型调用。

## 2026-10-21 · Claude · V-Gate5 评审
状态：完成（结论：未通过，安排 V12 修补与 V-Gate5b 补验；默认开启 v3 继续阻塞）
分支与提交：`agent-v3/V-Gate5`，已合并到 `feat/agent-v2`
完成内容：
- 审读 V11_TEST_REPORT.md、D-040–D-046、V11a–g 提交与 Skill 增补；抽查源码确认三项根因：通用 PlanDraft 不读 brief 比例、Research 工具要模型传 run_id、`_i2i_test_image_adapter_payload` 直接构造适配器。
- 判定：V11a/b/d/e/g 通过；V11f 通过但需调整契约投影；V11c 仅离线通过；c7 比例失败；审核 B 未覆盖。安全护栏有效，没有真实上传，“零越界尝试”失败归因于 Mock 覆盖缺口。
- Skill 增补审定通过；新增 D-047；结论与 V12 任务细节写入 `docs/agent_v3/VGATE5_REVIEW.md`。
测试：本次只改文档，未运行测试；真实调用 0。
未完成 / 下一步：

### 给 Codex：V12 任务（顺序 V12c → V12a → V12b → V12d → V12e → V12f → V-Gate5b；规则与 D-030 不变）
详细验收见 `docs/agent_v3/VGATE5_REVIEW.md`“V12 任务”一节。要点：
- V12c 先做：适配器统一走 `get_adapter`（经典 I2I 行为不变并补回归）；harness 审批预览门前确认 Run=awaiting_gate，attention 时报失败节点错误码后停止。
- V12a、V12b 契约先行（D-048 起）。V12a：用户明确的比例从 brief 传到成片关键帧/视频（省略时按比例和模型能力选默认，冲突报阻塞问题）、compose 与 QC；定妆/参考图豁免；复现 c7 结构的测试。V12b：run 由 ToolContext 绑定，伪造仍拒绝。
- V12d：每个 (name, path) 最近一次 `read_skill_resource` 结果不投影。V12e：编译错误 details 带节点/字段/合法引用输入名。V12f：意图评估以最终草稿为对象，判定不放宽。
- 顺手把各 Skill 中“待 V-Gate5 复审”标记改为“已由 Claude 审定”并递增版本。
- 完成后 V-Gate5b：c7×1、c3×2、审核 B（基于新 c3 计划只改第三镜）、c1×1；真实调用 ≤150、图片/视频生成 0、媒体全 Mock；报告交 Claude。
- 每个任务一个分支，全量回归与前端构建通过后本地合并；不推送、不进入 V8。V3PatchReview 美化已由 Claude 完成（本条之后的 V7 收尾提交），V12f 如需改该组件请在现有样式上改。
需要对方或用户决定：无。

## 2026-10-21 · Claude · V7 收尾（V3PatchReview 美化）
状态：完成；V7 美化全部结束（手机端全局侧边栏仍按原计划延后）
分支与提交：`agent-v3/V7-patch-polish`，已合并到 `feat/agent-v2`
完成内容：`V3PatchReview.vue` 改为与其他 v3 面板一致的样式：状态胶囊、Director 审阅卡与意图评估卡按结论着色，前后差异红绿对照，范围选项为可选卡片，报价区统计卡 + 影响分组色点，批准/拒绝操作区。只改模板结构与样式，文案、单选框标签、复选框、按钮名称和 testid 均不变；脚本仅新增 reviewTone 与分组色。
测试：node --test 137 passed；npm run build 通过；agent-v3.smoke.js PASS（含 1440/400 宽、亮/暗色无横向溢出，pageErrors 0）。真实调用 0。
未完成 / 下一步：无。V12f 如需改该组件，请在现有样式上修改。
需要对方或用户决定：无。

## 2026-10-21 · Codex · 接手 V12 评审修补
状态：已读最新交接、看板、V-Gate5 评审及契约，当前独立分支 agent-v3/V12c。
完成内容：按 D-047 的顺序从混合评测边界开始。Wan2.7 I2I 改用已注册工厂，其他协议选型保持；harness 只在 awaiting_gate 批准预览，attention 记录失败节点错误码后停止，显式人工 Patch 待审仍保留。全仓运行代码检索未发现另一处直接构造媒体适配器。
验证：正式隔离定向位于 TEMP/cc-v12c-focus-1021213525-d76d；尚在运行，不能视为阶段通过。后续须完整后端与前端构建通过才本地合并。并行准备 V12a/b 的契约和候选仅在 TEMP，未写入当前任务源文件。
下一步：V12c → V12a → V12b → V12d → V12e → V12f；每阶段独立完整验证。最后新一轮 V-Gate5b 按 ≤150 次执行，与 V11 已封存118次分开；当前真实调用0，媒体0。不推送、不进入V8，不改Claude既有美化，私人未跟踪笔记保留。

验证补记：首轮定向25项为24过、1失败，根因是新增 Wan2.7 引用计划夹具遗漏 mode=i2i，编译器按既有规则拒绝；只修夹具，不放宽实现。TEMP/cc-v12c_fixed-focus-1021213953-c192 的新增13项全部通过，包含全局real/媒体Mock下实际Wan2.7引用图Job执行、零上传、经典工厂选择、attention停止及人工Patch待审。首轮已有12项混合驱动回归通过。正式完整2594项/137文件在 TEMP/cc-v12c-1021214043-8ec3 执行，前端构建已通过，后端尚未完成，不提前提交合并。

### V12 并行准备补记（正式全量仍在 V12c）

后续实现仅在 TEMP 封存，尚未迁入主仓或完成正式阶段：V12a 位于 cinecrew-v12a-prep，最终14文件补丁 d9360303，定向去重128项（116项主批加安全边界小集，不是最终128项一次完整复跑）；V12b 位于 cinecrew-v12b-prep，201项；V12d 位于 cinecrew-v12d-prep，83项；V12e 位于 cinecrew-v12e-prep/candidate，40项；V12f 位于 cinecrew-v12f-prep，5项。各目录 HANDOFF.md 保存首轮失败根因、版本与哈希。A 的实测 SAR/旋转、参考用途和非方像素画布边界经独立审阅补齐；正式仍须全量。F 必须在 A 后动态生成补丁，保留 plan-review 的 A 内容并从7升到8，不能覆盖预A副本。

后续顺序仍为 C→A→B→D→E→F，每阶段独立分支、决策/契约先于主源改动，全量后端和构建通过才合并。正式 V-Gate5b 尚未初始化，真实调用0；入口及独立统计保存在 TEMP/cinecrew-v12c-review，44项Stub通过。新轮150次与V11旧轮分开，不重采失败样本；审核B只选最早适用的新c3计划。不得把TEMP定向结果写成正式全量或真实验收通过。

## 2026-10-21 · Codex · V12c 全量验证完成

状态：V12c 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：媒体适配器统一走工厂；harness按真实门状态审批，attention记录失败节点后停止；经典路径与实际Wan2.7引用链回归通过。
验证：TEMP/cc-v12c-1021214043-8ec3/summary.json 最终passed=true；137文件、2594项完整通过，精确ID遗漏/多余/重复/失败/跳过均0；源码冻结、隔离审计、前端构建通过。命令、逐组日志、JUnit与完整收集清单在同目录。
下一步：继续评审规定顺序的下一阶段。Mock通过不代表真实token/轮数/媒体质量达标，V-Gate5b尚未开始；当前本轮真实调用0、媒体0。不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-21 · Codex · V12a 正式实现与验证

状态：前序已完整验证并本地合并，当前独立分支 agent-v3/V12a。先追加决策，再写契约，最后迁入已审阅候选。
完成内容：显式比例从需求贯穿成片关键帧、视频、拼接和QC；定妆与参考用途豁免，实测SAR及旋转证据保守校验。候选定向证据及失败根因保存在对应 TEMP 准备目录 HANDOFF.md；不代替正式完整验证。
下一步：冻结源码，完整后端回归与前端构建通过后才提交、合并。当前本轮真实调用0、媒体0；不推送、不进入V8，保留Claude既有美化和私人未跟踪笔记。

V12a 首轮完整验证中止补记：TEMP/cc-v12a-1021223525-399f 完整收集2677项，前端构建通过；执行早期已发现6条既有V10混合流程失败，故主动中止，不作为完整运行或通过统计。根因证据为评测专用mock_geometry将Job实际提交的storage-relative首帧路径按backend工作目录解析，错误报“Mock frame must be a local managed file”，导致视频下载/Repair后续流程进入attention；已有绝对路径定向夹具未覆盖此真实payload形态。已确认8个精确pytest子进程均退出；原日志与未完成summary保留，另记中止说明。只修评测本地路径解析并增加相对路径及越界回归，不放宽护栏或旧测试断言；正式仍须重新完整回归与构建后才合并。当前真实调用0。

修复复验：仅改评测mock_geometry，先拒绝URI/UNC/设备及驱动器相对路径，再经StorageService.resolve解析本地相对路径并校验真实归属；应用级StorageService不改。TEMP/cc-v12a_path_fixed-focus-1021224634-2147 为48项全过（23项Mock尺寸/路径、12项原V10混合流程、13项V12c媒体边界），包含原来失败的自动/人工修复、选择改选及审核B修订交付。精确清单、源码冻结及隔离审计通过，零真实调用。最终小修补丁89c85ad2及候选根因证据保存在TEMP/cinecrew-v12a-mock-path-fix；继续新的正式全量，不把这48项当全量替代。

V12a 第二轮完整验证中止补记：TEMP/cc-v12a-1021225223-formal-f0b0 收集2691项/139文件、构建通过，新增指定画布拼接测试失败后中止，12个精确pytest子进程确认退出。独立复现TEMP/cinecrew-v12a-onecase为1失败/17.47秒；本地Mock PNG编码视频未显式写入SAR=1，新增的未知SAR阻塞规则正确拒绝该素材。前期准备在严格SAR校验后只补跑边界小集，未覆盖原拼接用例，正式完整回归检出了缺口。仅给本地Mock编码增加setsar=1，保留真实未知SAR拒绝、QC及原断言；重新定向与完整验证，未合并。原日志/summary保留，operator-stop.json单独说明中止；本轮真实调用仍0。

V12a 最终定向复验：TEMP/cc-v12a_geometry_fixed-focus-1021231413-25f2 为122项全部通过，实际进程401.266秒（pytest396.59秒），包含74项比例、23项Mock几何/路径、12项既有混合流程、13项媒体边界。精确清单无失败/遗漏/重复/跳过，源码冻结及零guard通过；SAR编码补丁不放宽实物校验。接着执行全新完整回归，本轮真实调用0。

## 2026-10-21 · Codex · V12a 全量验证完成

状态：V12a 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：显式比例从需求贯穿成片关键帧、视频、拼接和QC；定妆与参考用途豁免，实测SAR及旋转证据保守校验。
验证：TEMP/cc-v12a-1021232124-formal-903d/summary.json 最终passed=true；139文件、2691项完整通过，精确ID遗漏/多余/重复/失败/跳过均0；源码冻结、隔离审计、前端构建通过。命令、逐组日志、JUnit与完整收集清单在同目录。
下一步：继续评审规定顺序的下一阶段。Mock通过不代表真实token/轮数/媒体质量达标，V-Gate5b尚未开始；当前本轮真实调用0、媒体0。不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-21 · Codex · V12b 正式实现与验证

状态：前序已完整验证并本地合并，当前独立分支 agent-v3/V12b。先追加决策，再写契约，最后迁入已审阅候选。
完成内容：Research的run由可信上下文绑定，显式伪造仍拒绝；给出有界结构纠错示例，保留来源和回放隔离。候选定向证据及失败根因保存在对应 TEMP 准备目录 HANDOFF.md；不代替正式完整验证。
下一步：冻结源码，完整后端回归与前端构建通过后才提交、合并。当前本轮真实调用0、媒体0；不推送、不进入V8，保留Claude既有美化和私人未跟踪笔记。

## 2026-10-22 · Codex · V12b 全量验证完成

状态：V12b 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：Research的run由可信上下文绑定，显式伪造仍拒绝；给出有界结构纠错示例，保留来源和回放隔离。
验证：TEMP/cc-v12b-1021234901-formal-9492/summary.json 最终passed=true；140文件、2724项完整通过，精确ID遗漏/多余/重复/失败/跳过均0；源码冻结、隔离审计、前端构建通过。命令、逐组日志、JUnit与完整收集清单在同目录。
下一步：继续评审规定顺序的下一阶段。Mock通过不代表真实token/轮数/媒体质量达标，V-Gate5b尚未开始；当前本轮真实调用0、媒体0。不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-22 · Codex · V12d 正式实现与验证

状态：前序已完整验证并本地合并，当前独立分支 agent-v3/V12d。先追加决策，再写契约，最后迁入已审阅候选。
完成内容：保护每个资源最近一次成功且匹配的读取，只投影被替代的旧副本；冻结恢复上下文不改。候选定向证据及失败根因保存在对应 TEMP 准备目录 HANDOFF.md；不代替正式完整验证。
下一步：冻结源码，完整后端回归与前端构建通过后才提交、合并。当前本轮真实调用0、媒体0；不推送、不进入V8，保留Claude既有美化和私人未跟踪笔记。

## 2026-10-22 · Codex · V12d 全量验证完成

状态：V12d 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：保护每个资源最近一次成功且匹配的读取，只投影被替代的旧副本；冻结恢复上下文不改。
验证：TEMP/cc-v12d-1022001605-formal-ce4f/summary.json 最终passed=true；141文件、2743项完整通过，精确ID遗漏/多余/重复/失败/跳过均0；源码冻结、隔离审计、前端构建通过。命令、逐组日志、JUnit与完整收集清单在同目录。
下一步：继续评审规定顺序的下一阶段。Mock通过不代表真实token/轮数/媒体质量达标，V-Gate5b尚未开始；当前本轮真实调用0、媒体0。不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-22 · Codex · V12e 正式实现与验证

状态：前序已完整验证并本地合并，当前独立分支 agent-v3/V12e。先追加决策，再写契约，最后迁入已审阅候选。
完成内容：编译错误增补节点、字段和真实合法引用输入；保留原校验与payload，不接受别名。候选定向证据及失败根因保存在对应 TEMP 准备目录 HANDOFF.md；不代替正式完整验证。
下一步：冻结源码，完整后端回归与前端构建通过后才提交、合并。当前本轮真实调用0、媒体0；不推送、不进入V8，保留Claude既有美化和私人未跟踪笔记。

V12e 迁入前校验补记：前序D全量2743项通过并已合并。临时执行链在E任何源码/契约迁入前因补丁哈希不一致停止；原补丁110个CRLF，字节SHA256 af1f928960c657644f2fd76dfdec3ba4940e67ad7ca2325fc2b1c078379cb9e8，仅归一为LF后精确匹配原封存e67390854f91450dbc47dbb01cfb7080fd5ab80aaa94293f55e578405aba84a6。根与独立代理核对全部hunk、旧基线和测试副本哈希，未发现内容漂移；git apply --check通过。保留原补丁，只修临时执行器的字节哈希预期，未弱化产品校验或算作测试通过。完整证明TEMP/cinecrew-v12c-review/V12e-patch-hash-review.json。接续独立E分支全量验证，当前真实调用0。

## 2026-10-22 · Codex · V12e 全量验证完成

状态：V12e 完成，独立任务分支验证后提交并仅本地合入 feat/agent-v2。
完成内容：编译错误增补节点、字段和真实合法引用输入；保留原校验与payload，不接受别名。
验证：TEMP/cc-v12e-10220044-formal-4ac1/summary.json 最终passed=true；142文件、2766项完整通过，精确ID遗漏/多余/重复/失败/跳过均0；源码冻结、隔离审计、前端构建通过。命令、逐组日志、JUnit与完整收集清单在同目录。
下一步：继续评审规定顺序的下一阶段。Mock通过不代表真实token/轮数/媒体质量达标，V-Gate5b尚未开始；当前本轮真实调用0、媒体0。不推送、不进入V8，私人未跟踪笔记保留。

## 2026-10-22 · Codex · V12f 正式实现开始

E完整验证并本地合并后，从当前源生成并人工审阅13文件补丁。先写D-052，再写V.22.5，最后局部应用。保留Claude组件script/style、审批条件与历史reason；不推送、无真实调用。
动态补丁：TEMP/cinecrew-v12f-after-e-10220114/v12f-candidate.patch，SHA256 4b5f40d8e028e956f18c520c2a9fa666d2a10198d757c119ff05122384da0148。
下一步：新两条Registry回归包含在完整后端验收；另需137项前端测试、构建与独立浏览器四布局功能验收。预A候选5项不代替正式验证。

## 2026-10-22 · Codex · V12f 正式验证完成

最终候选意图/理由说明已同步Director、实际Repair审阅任务和Skill；界面原reason不改写，Claude script/style保持。
验证：TEMP/cc-v12f-10220120-formal/summary.json，完整后端2768项，精确清单无遗漏/重复/跳过，前端构建通过。独立前端137项与浏览器1440/400亮暗四布局均通过，源码/HEAD冻结、guard为0；证据路径见TEMP/cinecrew-v12c-review/V12f-merged.json。
仅本地提交合并，不推送；无真实模型/媒体调用。下一步由父代理手动决定V-Gate5b，Mock不证明真实语义或画质达标。

## 2026-10-22 · Codex · V-Gate5b 固定样本与评测脚本纠错

状态：c7×1、c3×2、c1×1和审核B初次流程已执行；固定累计74次真实调用（73文本、1视觉），真实媒体与上传0。证据在TEMP/cinecrew-v12-gate5b-20261022-01；运行源冻结5e5db145，未重采失败样本。c7成片参数16:9落实、无Creative委派；c1五次物理调用且无委派；c3一次进入审核，一次在用户选择门停下。真实Research省略run_id的下载已成功。峰值65182/68541超过60k；c3成片仅70秒，与120秒目标不符；字段纠错仍多，不能称Gate通过。

审核B原20节点Mock交付成功，Director已生成并独立审阅第三镜雨夜Patch。原评测因重复携带未变的首帧引用误判越界；实际只有s03_video.prompt变更。另一脚本缺陷是默认答题漏传request_key导致422；当前选择卡没有default，不能把recommended当成用户授权。

接手：独立分支agent-v3/V12c-eval-recovery，D-053先记录，只修评测脚本及测试，完整后端/构建通过后本地合并。随后禁止新增LLM，复用同一Patch重新报价、明确批准并验证其他15节点复用和重新交付。原失败归档保留，真实token/时长缺陷单列。不推送、不进入V8、不改Claude美化，私人未跟踪笔记保留。

## 2026-10-22 · Codex · V12c-eval-recovery 完整验证完成

状态：两处评测修复及31项新增回归完成，准备仅本地提交合并。已有64项纯Mock/Stub定向通过；正式TEMP/cc-v12-eval-recovery-10220204-formal完整2799项/144文件全部通过，精确ID无遗漏/额外/重复/失败/跳过，source/HEAD冻结、guard0、全部进程和前端构建通过，耗时25分01秒。不得将定向与全量相加。

范围：仅v3_eval/eval_actions.py、eval_v3.py、story_scope.py及对应两份测试、文档；产品、Skill、Claude界面未改。默认答题按Run/card生成稳定键，错误留证后停止，v2兼容；scope按合并后实际值检查，允许相同引用透传，仍拒绝引用/模型/参数/时长/其他节点变化及无效prompt。

下一步：核对新提交与全量源完全一致后，运行TEMP/cinecrew-v12-b-resume-prep/resume_review_b.py，仅恢复agent_be1e06bb981b4dd2的patch_54c2d2d6060645e5。入口独立静态审阅、20项纯/Stub和Windows只读Git自检通过，SHA3afe179507ab68322dc3d3d2cbaa34b13cde0513de9912fae49459198a9fbe26。禁止新规划/LLM/真实媒体/读取凭证；保留原74次计数及首次失败归档，尚不能宣告B通过。续验前统计已字节不变另存readonly-statistics-before-resume。完成后补最终报告与Claude交接。

## 2026-10-22 · Codex · V12 与 V-Gate5b 测试完成，交 Claude 审读

状态：按评审顺序完成 V12c→a→b→d→e→f，每项独立分支、完整回归和前端构建通过后仅本地合并。追加 D-053 评测脚本修复，最终代码提交 f2728c3007f3f33487d2d0c40697d5f33e96ce37；正式后端2799项/144文件全通过，精确收集无遗漏/额外/重复/失败/跳过，隔离guard为0，构建通过。F另有137项前端及1440/400亮暗四布局验收。最终报告与看板在独立文档分支 agent-v3/V-Gate5b-report 收尾；无新增产品、Skill或界面变更。详见 docs/agent_v3/V12_TEST_REPORT.md。

审核B续验：原Run agent_be1e06bb981b4dd2、原Patch patch_54c2d2d6060645e5 未重规划。06临时入口因Popen函数替换破坏Windows asyncio继承而在应用初始化前失败；原DB字节未变、调用74、阻断0，失败证据保留。07独立入口改为受控Popen类，21项纯/Stub与真实导入/只读Git冒烟及独立静态审阅通过后执行，exit0。新鲜cascade报价经明确Mock人工批准，只新增s03_video一次10秒Mock生成；15节点inputs/output/hash/job/invocation完全复用，compose/probe/qc/package重执行，v2全部20任务成功、结果审批后Run成功。实际下载video与package，可信Director来源由不可变提案及持久化批准版本核验，公开reason与存储原文一致。原失败归档不改写；此结果不证明雨夜实物画质或修复原计划70秒缺陷。

真实调用与费用：固定c7×1、c3×2、c1×1及B初次提案/审阅合计74次（deepseek-v4.1-flash文本73、qwen3.7-plus视觉1），低于150上限；续验新增0。75条逻辑模型调用记录含1条调用前预算拒绝，该条无HTTP；物理74行及计数续验前后完全一致。输入2,520,793、输出71,353、单轮峰值68,541；74次物理成功调用的usage缺失/未知/预留/未映射均0，逻辑统计中的1条缺usage对应预算拒绝。真实图片、视频、媒体上传及网络越界尝试均0。演示账本LLM/视觉25.95513 + Mock媒体98 + Mock研究0.8 = 124.75513 credits，非服务商实际账单；待结算0。真实阶段仅既有凭据白名单读取允许的密钥行，MySQL/Redis值未读取或连接；离线回归和07续验禁止真实.env读取，均临时SQLite/存储，真实.env未修改。

目标逐项：
- 已达：c7全部成片关键帧/视频/拼接16:9、120秒、完整情节不委派Creative；真实LLM驱动的Mock下载省略run_id成功（不是实网检索验收）；c3至少1/2进入审核；c1四文本轮加一次视觉、无委派；已完成长片规划演示费用均≤20；审核B第三镜局部重做、15节点复用、可信来源与再次交付；安全边界通过。
- 未达：c7/c3-2峰值65,182/68,541超过60k；字段诊断虽消除本轮UNTYPED_REFERENCE，其他同类问题仍批量纠错；c3-2需求120±15秒却批准7×10=70秒，当前QC只与批准片段合计比对。c3未到最好2/2：首例资料不确定进入无默认选项的选择门，原评测缺request_key已修，但推荐选项不等于用户授权，未替选或补采。
- 待审或未测：c7“一起上楼”只写准备上楼，局部动作保真待Claude裁定；真实角色相似度、风格与雨夜转换未测。现有统计器不识别续验专用outcome，required_coverage的B仍failed；以保留的首次失败与07完整续验证据联合审读，不篡改统计或原归档求全绿。

证据：TEMP=C:/Users/MingZheYang/AppData/Local/Temp；工作根 cinecrew-v12-gate5b-20261022-01，最终readonly-statistics与原readonly-statistics-before-resume并存，07-resume-control.json与results/hybrid_V12-story-resume07-agent_be1e06bb981b4dd2_agent_be1e06bb981b4dd2.json（SHA256 8d4c84b44743eb78b488291849fa9c2496a4e5c24d62ef2b56aad0f5d9456776）；最终全量cc-v12-eval-recovery-10220204-formal；各次失败根因、上下文冻结证据及独立审阅在cinecrew-v12c-review。原05、06与74次物理记录全部保留。

接手：请Claude审读V12_TEST_REPORT、D-048–D-053、V.22及本轮Skill增补，裁定V-Gate5b并安排token预算、时长意图校验和纠错效率后续任务。当前不能宣布Gate通过，默认开启v3继续阻塞。不推送、不建PR、不进入V8；保留Claude美化、原工作树及用户未跟踪的AI_Video_Factory_Technical_Notes_CN.md。不要重跑06/07入口或把recommended当默认回答；新一轮真实测试另按批准范围执行。

## 2026-10-22 · Claude · V-Gate5b 评审
状态：完成（结论：有条件通过；默认开启 v3 仍阻塞，须完成 V13a 并通过 V-Gate6）
分支与提交：`agent-v3/V-Gate5b`，已合并到 `feat/agent-v2`
完成内容：
- 审读 V12_TEST_REPORT.md、D-048–D-053、V12 提交及提示词/Skill 增补；抽查确认通用 PlanDraft 不核对计划总时长与 brief 时长。
- 判定：比例、Research 上下文、Mock 覆盖、审核 B 局部修订与来源全部通过；c1 4 轮通过；c3 1/2 达下限（c3-1 的品牌形象提问属合理行为）；c3-2 时长 70 秒 vs 约 120 秒失败；峰值 65k/68k 未达 60k；“一起上楼”为轻微偏差不阻塞。
- 峰值 Gate 门槛调整为 ≤80k token（60k 保留为优化方向）；新增 D-054；结论与 V13 任务写入 `docs/agent_v3/VGATE5_REVIEW.md` 末节。
测试：本次只改文档，未运行测试；真实调用 0。
未完成 / 下一步：

### 给 Codex：V13 任务（顺序 V13a → V13b → V13c → V13d → V-Gate6；规则与 D-030 不变）
详细验收见 `docs/agent_v3/VGATE5_REVIEW.md`“V-Gate5b 补验结论 / V13 任务”。要点：
- V13a 契约先行（D-055 起）：用户明确时长才校验；编译器按 compose 实际片段总长判断容差，超出报 PLAN_DURATION_MISMATCH；QC 核对成片时长；复现 c3-2（120 秒 brief、7×10 计划）必须被拒。
- V13b：只做无损规范化（非生成节点 characters=[] 忽略；compose/QC 只给比例时推导尺寸），其他错误照旧拒绝。
- V13c：取代的失败 check_plan 回执与重复模型目录只保留最新一份；最新契约/草稿/回执保护不变；峰值门槛 ≤80k。
- V13d：固定事件须在镜头内完成（Director 提示词）；草稿含 context_projection 时返回专用错误码；统计识别续验标签；“待 Claude V-Gate5b 审阅”标记改为已审定并递增版本。
- V-Gate6：c3×2、c7×1；身份抽检只真实执行 2 张定妆 + 2 张双人关键帧（真实图片 ≤6，视频与后期 Mock），qwen3.7-plus 一次调用多图同传判断一致性；文本/视觉 ≤120 次；报告 `docs/agent_v3/V13_TEST_REPORT.md` 交 Claude。
- 每个任务一个分支，全量回归与前端构建通过后本地合并；不推送、不进入 V8。
需要对方或用户决定：V-Gate6 会产生少量真实图片费用（≤6 张，属 D-030 授权范围）；如用户不希望本轮生成图片，可只做 1 项。

## 2026-10-22 · Claude · V-Gate6 图片抽检授权
状态：用户已同意 V-Gate6 的真实图片身份抽检（真实图片 ≤6 张，视频生成 0；文本/视觉 ≤120 次）。按上一条的 V13 任务执行即可。

## 2026-10-22 · Codex · V13a 契约与实现，完整回归进行中

分支：agent-v3/V13a，基线c098d4c；尚未提交或合并。已先记录D-055，再写V.23.1，实现显式时长出处/模式/固定容差、最终媒体数据路径计时、批准约束冻结、QC及结果批准前实测。无明确目标保持无约束；旧批准receipt不重写。未改经典/v2或Claude界面，私人未跟踪笔记未读取或暂存。

定向：TEMP/cc-v13a-focus-1022202638-485c，207项中205通过、两条新增transform测试失败；根因是测试硬指定Wan3却未在原测试请求/brief声明系列，既有默认模型约束正确拒绝。只修测试前提，TEMP/cc-v13a-fix-focus-1022203101-21ba两项通过；两次source冻结、guard均0。三份Schema资源已受限离线生成，证据TEMP/cc-v13a-schema-1022202537-5a42。TEMP目录首次创建因沙箱权限失败，随后经工具自动审批运行已审隔离入口，未发生应用或网络请求。

进行中：TEMP/cc-v13a-1022203122-6d33，完整收集2898项/146文件，12组运行；前端构建已通过，尚未宣称后端完整通过。所有源码/HEAD/branch冻结，只有TEMP准备后续候选。后续须确认精确清单、无skip/遗漏/重复/失败、guard0及冻结后，才提交合并A，再依次B→C→D；候选不能替代各阶段正式完整验证。

本轮真实LLM/视觉/图像/视频均0。V-Gate6只在全部开发验证完成后新建独立目录运行固定c3×2、c7×1，再做已批准双人计划的4图身份抽检；保留请求前持久额度120/6/0与原始失败。不推送、不建PR、不进入V8。

## 2026-10-22 · Codex · V13a 完整验证通过

状态：实现及Mock验证完成，准备仅本地提交合并。正式证据TEMP/cc-v13a-1022203122-6d33/summary.json：2898项/146文件全部通过，精确ID无遗漏/额外/重复/失败/跳过；全部进程、前端构建通过，source/HEAD/branch冻结，guard0。提交前再次核对当前源码与source-after.json完全一致。真实调用0。

已验证120秒目标与7×10秒计划被阻塞；无目标不产生约束；重复播放计时、包与压缩副本去重、原片区间/变换完整输出、严格模式与容差边界；QC及直接视频实测不符转attention并保留已生成媒体，允许用户发起修订。旧brief读取/批准receipt兼容，Patch不能放宽根约束。新Skill说明待Claude V-Gate6审读。

下一步从feat/agent-v2新建agent-v3/V13b，先D-056/V.23.2，再迁入已审的两处无损规范化与测试；后续C/D候选仅TEMP，不替代正式分支验证。Gate6未开始，默认启用v3仍阻塞。

## 2026-10-22 · Codex · V13b 完成

分支：agent-v3/V13b，基线a03b6b3（V13a已本地合并）。先D-056/V.23.2，仅在编译候选忽略已知非生成节点characters: []，并为compose/QC显式合法比例推导D-048画布；生成角色声明、未知字段/别名、显式冲突、未知SAR等仍拒绝。原输入和批准历史不改。

验证：TEMP/cc-v13b-focus-1022204222-9182定向217项全通过；TEMP/cc-v13b-1022204537-43f1/summary.json全量2946项精确收集/报告全通过，无遗漏、额外、重复、跳过或失败，前端构建通过；source/HEAD/branch冻结、guard0，提交前再核对source-after一致。真实LLM/视觉/图片/视频均0。准备本地提交合并，再从feat/agent-v2切V13c。C/D/Gate6候选仅在TEMP审查，不冒充正式验收；不推送，不进入V8，不触碰私人笔记。

## 2026-10-22 · Codex · V13c 接续验证

V13b已以e1acfbe本地合并，当前agent-v3/V13c。已先记录D-057/V.23.3，迁入仅请求视图的旧失败check与重复目录投影，policy4保留旧冻结恢复数据。TEMP/cc-v13c-focus-1022205523-6a5e正式定向133项全通过、source冻结、guard0。

第一次全量启动未执行：自动审批服务报额度耗尽，属于工具审批服务失败，不是产品失败或安全否决。用户继续后同一已审入口成功启动TEMP/cc-v13c-1022212916-7761，正在全量回归/构建，运行源码保持冻结。D投影/指引/统计与Gate6防护候选仍仅TEMP；真实文本/视觉/图片/视频均0。后续按C全量通过→本地合并→D开发验证→Gate6正式防护验证→固定真实样本顺序执行，不能跳过或把候选结果当正式全量。

## 2026-10-22 · Codex · V13c 完成

正式证据TEMP/cc-v13c-1022212916-7761/summary.json：2996项/148文件精确收集与报告全通过，无遗漏/额外/重复/跳过/失败；前端构建与所有进程通过，source/HEAD/branch冻结、guard0；提交前复核source-after一致。旧失败检查只在同key更高版本完成合法check后投影；目录只去同规范过滤器旧副本；原历史、最新资料/计划/回执与冻结恢复保护已回归。

当前准备提交agent-v3/V13c并本地合并，再切agent-v3/V13d；真实80k峰值仍待Gate6 usage，不能由字符统计宣布达标。本轮真实调用全0，私人笔记保持原样。D/Gate候选安全审查中发现的HTTP继承包装、非JSON原证据等问题均先在TEMP修复，未发真实请求。

## 2026-10-22 · Codex · V13d 完成

V13c已以a22d5bb本地合并；D基于该提交，先D-058/V.23.4。新增PLAN_CONTEXT_PROJECTION及受限重读提示，保持原JSON边界/历史恢复；Director明确固定事件完成，long-form-video旧±10秒与D-055对齐；Director文案V13，plan-review10、long-form-video4。仅旧V12f已审，新V13待Claude Gate6。正式只读统计区分新旧阈值、续验标签、阶段/图片/副本/逻辑费用归属，计划交付秒不再误称计费秒。

正式定向TEMP/cc-v13d-focus-1022213947-e4d2：234项全通过。全量TEMP/cc-v13d-1022214039-a9a4：3097项/153文件精确全通过、无遗漏/额外/重复/失败/跳过，前端构建及所有进程通过、source/HEAD/branch冻结、guard0；提交前再次复核source-after一致。本轮比前轮慢（约15分钟），多个未修改经典用例同样变慢；独立旧defaults用例profile通过，create_app1.082秒，投影验证器未调用，没有已证实的D性能回归。诊断保留TEMP/cinecrew-v13d-performance-profile，未因此改代码或跳测试。

准备本地提交合并后切agent-v3/V-Gate6，先D-059/V.23.5、迁入已独立审查的评测护栏，再定向与全量验证后才真实执行。候选56项Stub不是正式Gate结论。所有真实调用仍0；默认启用v3不变，不推送、不建PR、不进V8，不读写私人笔记。

## 2026-10-22 · Claude · V13 前置评审、约束展示与默认开启草稿（与 Codex 并行）
状态：完成
分支与提交：`agent-v3/V13-constraint-ui`（独立 worktree），已合并到 `feat/agent-v2`
完成内容：
- 前置评审 V13a–c（已合并部分）：V13b、V13c 无问题。V13a 发现缺陷：exact/at_most 容差为 0，`runtime_duration.check_delivery_duration` 用 1e-6 误差比较 ffprobe 实测时长，真实视频的帧级偏差（如 5.04 秒）会在生成完成后把 Run 打成 attention（`runtime.py:_check_result_duration`）。Mock 时长精确，测试测不出。
- 计划视图显示需求约束：新增 `v3-constraints.js`，`V3PlanBoard.vue` 在统计卡下显示目标时长与容差、当前总长是否符合、画面比例（读计划 duration_constraint 与 compose/QC 的 target_aspect_ratio，服务端 PLAN_DURATION_MISMATCH/UNKNOWN 优先）。只读展示，不改后端。
- 起草 `docs/agent_v3/DEFAULT_ON_PLAN.md`：现状（开关只影响新 Run）、开启前置条件、分阶段灰度（借助 AGENT_ALLOWED_USERS）、回滚、观察指标、用户可见变化与待用户决定事项。
测试：node --test 144 passed（新增 7 项）；构建通过；agent-v3.smoke.js PASS（夹具补约束字段并断言可见）。真实调用 0。
未完成 / 下一步：

### 给 Codex：插入 V13e（V-Gate6 交付前完成；若已收到用户转达的同一条指令则忽略本段）
- 编译期仍按参数严格校验；只在运行期实测这一步增加测量误差，建议 max(0.5 秒, 片段数 × 1 帧时长)，at_most 同样适用；先记决策（D-059 起）再改 CONTRACTS。
- 补测试：exact 5 秒实测 5.04 秒通过；实测 5.8 秒仍失败；at_most 120 秒实测 120.3 秒通过。报告注明本项只有离线覆盖。
- 另建议 V14a（默认开启前）：v3 运行指标。现有 `agent/monitoring.py: run_metrics` 按 v2 结构编写（shots、needs_attention），不覆盖 v3 计划节点与 attention；需求见 DEFAULT_ON_PLAN.md 第 5 节。
- V3PlanBoard 新增了“需求约束”区块与 `data-testid=plan-constraints`，改该组件时请保留。
需要对方或用户决定：DEFAULT_ON_PLAN.md 第 7 节三项，待 V-Gate6 通过后一并交用户确认。

## 2026-10-22 · Codex · V-Gate6 评测入口离线验证完成，插入 V13e

先D-059/V.23.5，新增独立评测入口与120/6/0持久预留、固定样本与四图一次视觉、选择性真实图片及传输护栏。正式定向TEMP/cc-v13gate6-focus-1022215804-d252：80项全通过；全量TEMP/cc-v13gate6-1022215930-e652：3153项/157文件精确全通过、无遗漏/额外/重复/失败/跳过，前端构建及所有进程通过、source/HEAD/branch冻结、guard0。提交前再次核对source-after一致。仅本地合并评测基础设施，真实调用仍0，不代表Gate通过。

用户与Claude追加V13e：现有exact/at_most运行时实测使用近零误差，5.04秒可能误拒5秒目标；QC同样存在。将在真实Gate前从feat/agent-v2切agent-v3/V13e，D-059已用于评测入口，按“D-059起”使用下一号D-060并同步契约。编译严格不变，仅运行期增加技术测量余量，补全量与构建；报告明确本项只有离线覆盖，不以Mock证明真实帧级行为。之后才运行固定c3×2、c7×1和四图身份抽检。

## 2026-10-22 · Codex · V13e 实现完成，完整回归进行中

分支agent-v3/V13e，基线8f54f0b。Gate入口f729d89与Claude约束界面/默认开启草稿1225da6并行产生非快进，已通过正常merge保留双方；仅PROGRESS追加位置冲突，双方记录全部保留，未覆盖Claude界面。

先D-060/V.23.6，编译严格不变；运行期用户QC/交付采用独立max(0.5秒,Σ片段数/文件FPS)技术余量，不猜未知FPS。独立审查又发现旧输出完成门固定+0.05秒及QC输出Schema丢details，两处均同步修复并补契约；所有估价/参数/下游引用约束不变。仅v3输出类型扩展，经典QC保持。定向TEMP/cc-v13e-focus-1022221911-374d：176项全通过、source冻结、guard0；包括完整Mock Job→QC→审核→批准与费用/调用数不变。

当前全量TEMP/cc-v13e-1022222538-40ec，3205项/158文件，12组运行；构建已通过、后端未终态，源码/HEAD/分支必须保持冻结。结果完成后核对精确清单及source-after，才本地合并；V-Gate6使用本次最终全量证据，不使用旧入口全量冒充新源。真实调用仍0，V13e明确只有离线覆盖，随后真实Gate的视频也仍Mock。默认开启不变，不推送，不进V8，私人笔记未读写。

## 2026-10-22 · Codex · V13e 完整验证通过

正式TEMP/cc-v13e-1022222538-40ec/summary.json：3205项/158文件精确收集与报告全通过，无遗漏/额外/重复/失败/跳过；前端构建和所有进程通过，source/HEAD/branch冻结、guard0。提交前再次确认source-after与当前源码完全一致。全量约28分钟，比前轮慢，未修改或跳过用例，未证实具体性能根因；定向176项已通过。

准备仅本地提交合并V13e；之后在agent-v3/V-Gate6固定最终提交，使用上述全量证据与唯一TEMP/cinecrew-v13-gate6-20261022-01运行固定样本。本轮真实调用当前全0，后续限120文本/视觉、6图片、0视频。V13e三指定样例和真实Registry/Mock Job链均离线通过；不能称真实视频帧偏差已验收。Claude评审及用户默认开启确认仍待后续。

## 2026-10-22 · Claude · 真实端到端测试（含真实视频，D-061）
状态：完成（发现 2 个阻塞缺陷，默认开启 v3 继续阻塞）
分支与提交：`agent-v3/real-e2e-report`，已合并到 `feat/agent-v2`
完成内容：
- 按用户授权在隔离环境用 v3 跑真实任务：T1 江南水乡 t2v ✅；T2 三风格（wan2.6-image）❌；T2b 三风格（wan2.7-image）✅；T3 小狐狸首次 ❌；T3b 小狐狸两镜头：生成全部成功，拼接失败。
- 用量：真实视频 33 秒（wan2.7，720P）、图片实际 20 张、规划 LLM 75 轮。执行器 `backend/scripts/v3_eval/real_e2e.py`，证据目录 `%TEMP%/cinecrew-real-e2e-20261022`。
- 报告 `docs/agent_v3/REAL_E2E_20261022.md`；新增 D-061。
测试：本次只新增执行器与文档，未改产品代码；未运行自动化测试。
未完成 / 下一步：

### 给 Codex：V14 任务（V-Gate6 完成后、默认开启前；按 V14a → V14b → V14c → V14d → V14e）
- **V14a（阻塞）**：wan2.7 真实视频不带 SAR 标记，`MediaProbeService` 给出 `geometry_unverified`，指定比例时 compose 在 `plans/aspect.py:54` 报 INVALID_SOURCE。对本系统生成适配器产出的视频，缺失 SAR 按 1:1 处理并记录依据；外部上传来源保持保守。V12a 给 Mock 加 `setsar=1` 的做法改为让 Mock 与真实形态一致（不带 SAR），补“无 SAR 视频 + 指定比例可拼接”的回归。先记决策再改契约。
- **V14b（阻塞）**：wan2.6-image 默认参数与 `adapters/dashscope_image.py` 都带 `enable_interleave: true`，真实服务商对 n=1 返回 5 张，运行时报 PLAN_OUTPUT_COUNT_MISMATCH（计费已发生）。agent 计划的图片节点显式发送 false（确认经典首帧节点是否依赖多图后再决定是否改全局默认）；按实际返回张数记账；补测试。
- **V14c**：V11d 让 brief 逐字存偏好，整句（“图片使用wan2.7-image模型”）在 `agent/model_selection.py` 匹配不到任何模型。selector 与 source_text 分开存，或复用 `model_policy` 的提取；补测试覆盖整句写法。
- **V14d**：系列偏好是否同时约束图片（建议：系列内有图片模型时也约束）；经用户确认的修改能更新 brief 模型约束。涉及契约，交 Claude 审。
- **V14e**：多镜头短片默认 compose 成一个成片、各镜头首帧各自对应。
- 注意：V-Gate6 的视频仍是 Mock（且 Mock 带 setsar=1），测不出 V14a/V14b；请在 V-Gate6 报告中注明。修复后可用剩余授权（视频约 27 秒）复跑 T3b（执行器已在仓库）。
需要对方或用户决定：V14d 的产品取舍（系列偏好是否覆盖图片）。

## 2026-10-22 · Codex · V13 开发交付；用户要求暂挂 V-Gate6 真实验收

状态：V13a–e实现与离线回归完成并本地合并，V13e提交90175c745912d7d20c99e2dc0d505916e9cdafdb。最终全量3205项/158文件、构建全通过，定向176项；精确清单无失败/skip/遗漏/重复，source冻结、guard0。保留Claude约束界面和DEFAULT_ON_PLAN草稿。报告docs/agent_v3/V13_TEST_REPORT.md供Claude审读，V13e只有离线覆盖。

真实阶段固定源码90175c7。TEMP/cinecrew-v13-gate6-20261022-01首个01-c3-1创建Run agent_1f18acf306c742a2后0.4秒进入attention：Provider DNS resolved to nonpublic addresses。现场系统解析dashscope.aliyuncs.com为198.18.0.83；传输在TCP连接前拒绝，未收到HTTP响应或usage。审计保留1次文本预留（deepseek-v4.1-flash）、unknown1、network blocked1、usage缺失1，不重置或退款求通过。逻辑账本演示0.54391 credits，非实际服务商账单；输入/输出已知合计0但峰值未知，不能以0宣称≤80k。入口图片/视频/视觉计数均0，图片抽检表尚未创建，不等于质量验收通过。

02-c3-2、03-c7、04-identity均未启动；无可审核计划、无4张原图或多模态判断原文，真实时长/比例/峰值/纠错改善与V12对比全部未覆盖。已按只读方式生成readonly-statistics-v2-network-stop01，network-stop-readonly-proof.json确认原13个证据文件SHA不变；safety=failed、reconciliation=needs_review原样保留，data_quality=passed只表示归档可读完整。首次失败及started/finished不可删除。

用户明确回复“先完成报告，真实验收暂挂”，后续不发任何模型请求。本轮未放宽DNS护栏、未改代理或.env、未连接真实MySQL/Redis；只读取既有白名单服务商密钥进入子进程，不保存密钥。真实费用/请求未知状态按保守账本保留。没有重采样、图片重试、视频生成或默认开关变更。

交Claude：审读D-055–D-060、V.23与各阶段实现/新Skill；V13e三个指定样例及完整Mock链均通过，但真实Gate仍未验收，默认开启v3继续阻塞。暂挂原因是网络环境与护栏条件不匹配，不是模型规划能力失败；不得据此宣称V13真实指标通过。待用户恢复该域名真实公网DNS并明确续验安排后，先只读核实，再约定如何保留原Run、尝试1及原失败继续剩余固定样本，禁止直接重跑01入口或新建目录清账。不进入V8，不推送或建PR，私人未跟踪技术笔记保持原样。

收尾合并说明：Claude并行新增0e910c8（D-061独立真实E2E报告/执行器与V14a–e看板），本次正常合并保留全部内容，PLAN取本轮Gate暂挂状态，PROGRESS保留双方完整记录。报告补充引用其无SAR拼接、交错多图输出、模型偏好问题；这些独立样本不替代Gate6、不混入本轮120/6/0账本。3205项证据仍精确对应90175c7，不涵盖其随后新增real_e2e.py；本次仅合并文档，没有运行该执行器或V14，不把另一轮剩余额度当成本轮续验授权。此前DEFAULT_ON_PLAN中的“V14a运行指标”与新看板编号重名，后续由Claude协调编号，当前不改其方案。

## 2026-10-23 · Claude · 整体优化：简单任务降耗、交互效率与结果稳定性（D-062，用户指示）
状态：完成；V14a–V14e 一并完成
分支与提交：`agent-v3/prompt-quality`（独立 worktree），已合并到 `feat/agent-v2`
完成内容（详见 `docs/agent_v3/OPTIMIZATION_20261023.md`，契约 V.24）：
- `submit_plan` 支持内联 `{plan}`（保存 + 编译 + dry-run + 提交一步完成）；Producer 新增“简单任务速通”与 4 个可编译示例（测试保证一次提交成功），多镜头默认 compose 成一个成片。
- 模型偏好从原话提取模型/系列名（最长匹配、尊重“视频/图片”范围词）；系列同时约束其拥有的图片与视频模型。
- wan2.6-image：Agent 计划提交使用交错模式 + `max_images=n`（真实调用返回 1 张；注意：此前 V14b 建议的 enable_interleave=false 是图像编辑模式，需要输入图片，已作废）。
- 未声明 SAR 按 1:1；Mock 拼接素材不再 setsar。两段真实 wan2.7 视频 stream_copy 拼接、QC 通过。
- 参数错误与交付输出错误的诊断给出 fields / allowed_params / available_outputs。
- t2v / i2v / t2i-prompt-writing 重写为写作标准（提炼自 factory_prompts），Producer / Director / Prompt Smith 引用；Agent 提示词上限 12000 → 14000。
测试：后端全量 3237 passed（12 组并行，约 11 分钟；脚本思路：按测试文件轮转分组、各组独立 basetemp）。新增 5 个测试文件，按 D-062 调整 test_simple_plan、test_v6_policy、test_v6_agent_scenarios、test_story_director 的旧预期。前端未改动。
真实调用（D-030 范围）：A/B 规划约 105 次文本 + 5 次视觉；真实图片 2 次（1 次失败未出图、1 次出图 1 张）；视频 0。A/B：4 个简单任务轮数 29→8、输入 token 59.2 万→12.8 万、耗时 195→85 秒、提问 1→0；两镜头短片 10→4 轮。
未完成 / 下一步：
- 新提示词在真实视频上的画质提升尚未验证：需用户授权少量真实视频（可用 D-061 剩余约 27 秒）复跑 T1/T3b。
- 复杂任务仍会读取 2–5 个 Skill，可在后续把 long-form-video / character-consistency 的要点压缩进 Director。

### 给 Codex
- 本次改动由 Claude 直接实现，已合并；后续开发从 feat/agent-v2 最新提交切分支。修改 producer.md 时注意 14000 字符上限与 `tests/test_fast_path_examples.py`（示例必须能一次 submit 成功）。
- 全量回归可并行：12 组约 11 分钟（单进程需数小时）。建议每个任务跑定向测试 + 并行全量，不必串行。
- 默认开启 v3 的阶段 1（只对用户本人开放）前置条件见 `docs/agent_v3/DEFAULT_ON_PLAN.md`；V-Gate6 是否补跑由用户决定（失败原因为 Clash fake-ip 与 gate6 DNS 护栏不兼容，不是网络故障）。
需要对方或用户决定：是否授权少量真实视频验证新提示词画质；是否采用更快的开发流程（见 Claude 回复）。

## 2026-10-26 · Claude · 真实视频复测、快速流程与 v3 运行指标（D-063、D-064）
状态：完成；分支 `agent-v3/fast-process`、`agent-v3/v3-metrics` 已本地合并到 `feat/agent-v2`
完成内容：
- 真实视频复测（用户授权，D-061 剩余额度）：两镜头小狐狸 20.05 秒成片一次规划通过，系统自身拼接成功（上次失败），角色外观两镜头一致；不足：第二镜灯笼未明显叼在嘴里。单镜头水乡 5.04 秒氛围更好，但船夫中途才出现（与上次“消失”同类）——wan2.7-t2v 主体稳定性不足，改为“有主体时单镜头也用首帧 + i2v”。
- 协作流程（D-063）：CLAUDE.md / AGENTS.md 更新，Claude 主要实现；新增 `backend/scripts/test_parallel.sh`；`.gitattributes` 固定 .sh 为 LF。
- v3 运行指标（D-064，契约 V.24.7）：`/api/agent/runs/<id>/metrics` 的 v3 段与 `/api/agent/metrics/v3?days=7`。
- DEFAULT_ON_PLAN 前置条件已全部满足，剩阶段 1 是否开启待用户决定。
测试：新增 tests/test_v3_metrics.py；全量见本次并行回归（logs 路径记录在合并提交说明）。
真实调用：视频 25 秒（总计 58/60 秒）、图片 3 张、规划文本约 10 次。
下一步：阶段 1 开启需在部署环境设置 `AGENT_V3_ENABLED=true` 与 `AGENT_ALLOWED_USERS=<用户 ID>`；可选：前端展示 v3 指标、模型选择器。

## 2026-10-26 · Claude · 仓库整理与推送 GitHub
状态：完成。main 与 feat/agent-v2 均快进到最新提交并推送到 origin（无强推）。
完成内容：README（中英）更新为 Agent v3 说明（已验证范围、实验性长片、已知限制、指标接口）；.env.example 默认 AGENT_V3_ENABLED=true；根目录 MQ 规格与重构说明书移入 docs/architecture/；同步 CLAUDE.md 与 AGENTS.md 的语言约定；删除 95 个已合并的本地分支（保留 Codex worktree 使用中的分支与未合并的 agent-v2/T1）。推送前检查：无密钥、无大文件、无临时/存储文件被跟踪；后端全量 3239 通过，前端 144 项与构建通过。
已知限制（非阻塞）：联网检索只有 Mock 提供方；约 2 分钟长片真实成片未完整验证；wan2.7-i2v 对“叼起”等精细交互理解有限。
下一步候选：真实检索提供方、前端展示 v3 指标、前端模型选择器、V8 经典路径。

## 2026-10-27 · Claude · 提示词规范微调（D-065）与 V8 计划
状态：提示词微调完成并本地合并；V8 计划草案待用户确认（docs/agent_v3/V8_PLAN.md）
完成内容：写作标准增加“关键交互写成全程保持的状态并在首帧成立”“声音只写具体声源”“动作末尾一句自然度”；规划 A/B（小狐狸两镜头，约 6 次文本调用）确认新规则生效。整理联网检索接入说明：目前只有 Mock 提供方；真实抓取已有公网地址护栏，本机 Clash fake-ip 下需要配合配置。
下一步：等待用户确认 V8 计划三项决定与检索服务商选择。

## 2026-10-27 · Claude · V8 经典路径（D-066，契约 V.25）
状态：V8a–V8f 完成并本地合并到 feat/agent-v2（分支 agent-v3/v8a-contract、v8b-list-templates、v8c-workflow-node、v8d-production-skill）。
完成内容：只读工具 list_templates；计划节点 run_workflow_template（模板目标、分支白名单、冻结模型与单价、写入确认、逐次提交校验、结果映射、按需经典打包）；production-workflow Skill 与 Producer 路由；前端计划卡写入确认与经典结果卡（作业详情链接、提示词版本）。
验证：路由 A/B 10 条，误触发 0；真实冒烟“反推提示词”和“首帧提示词测试”成功并写回模板；修复了两个真实问题（经典文本节点在 worker 中缺少 JSON 降级、只有图片的作业无法打包）。后端并行全量 3267 通过，前端 148 项与构建通过，浏览器冒烟（Mock）确认写入确认、批准、经典作业链接与模板写回。
费用：文本约 37 次、多模态理解 5 次、图片 2 张、视频 0；估算 1–2 元。报告 docs/agent_v3/V8_REPORT_20261027.md。
下一步候选：经典路径的真实视频验证（需授权）；真实检索提供方（已暂停）；前端 v3 指标面板。
