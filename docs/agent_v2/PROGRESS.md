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
