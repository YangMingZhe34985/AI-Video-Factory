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
