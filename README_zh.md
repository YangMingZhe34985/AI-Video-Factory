# CineCrew 影组

**中文** | [English](README.md)

CineCrew（原 AI Video Factory）是一个 AI 视频创作平台。你可以让 Agent 根据文字或原视频制定分镜计划，也可以在经典工作流中直接控制生成节点。两种模式共用模型注册表、Job、素材工件、打包能力和消息队列。

## 两种使用方式

| 模式 | 适合什么场景 | 你控制什么 |
| --- | --- | --- |
| Agent Studio | 一句话描述想要的图片或视频，可附图片 / 视频 | 需求文字、附件、预算上限、回答 Agent 的选择题、计划审批与局部修改 |
| 经典工作流 | 已有源视频，需要逐节点调试或批量测试 | DAG 节点、提示词版本、模型参数、启用分支和局部重跑 |

### Agent 模式

只需要写下需求（必填），需要参考的照片或视频作为附件上传。Intake Agent 理解文字和附件，判断要做什么；有会明显影响结果的不确定之处时，以选择题向你确认；Director 选择模型并写提示词，计划经你审批后才开始生成和计费。

| 任务类型（由 Agent 判断） | 例子 | 流程 |
| --- | --- | --- |
| 编辑照片 | `用这张照片生成一张穿西装的职业照` + 人像 | 理解 → 计划（图生图）→ 审批 → 出图 |
| 生成图片 | `画一张赛博朋克风格的城市夜景海报` | 理解 → 计划（文生图）→ 审批 → 出图 |
| 单镜头视频 | `让这张图动起来，海风吹动头发，10 秒` + 图片 | 理解 → 计划（首帧 → 图生视频）→ 审批 → 出片 |
| 多镜头短片 | `做一个 2 分钟左右的猫咪冒险短片` | 理解 → 按模型时长自动拆分镜头 → 审批分镜 → 生成 → 打包（Phase C 将升级为剧本与角色设定） |
| 改造原视频 | 上传视频 + `保留开头，重做后半段动作` | 见下文 |

模型偏好直接写在需求里即可（如“使用 wan2.7 系列”）；无法满足时 Agent 会询问，不会静默换模型。

**原视频二次创作**：上传原片 → 描述修改需求 → 分析并规划 → 审批各段保留/重生成策略 → 预览、局部修改 → 打包。

例如：`保留开头的介绍，重做后半段动作。` 保留镜头由本地 FFmpeg 裁切；重生成镜头可用原片首帧，或先生成新首帧。需要区分：

- **原片时间范围**：从原视频的哪一段取素材。
- **生成时长**：交给视频模型的输出时长，须符合该模型支持的参数，两者不必相等。

草稿不合法时可以人工修改后重新确认。二创结果交付前可只修改一个镜头，其他镜头不重跑。单个镜头失败不会丢弃其余成功结果；交付为分镜素材与提示词 ZIP，不自动拼接成一条成片。

**模型选择**：不指定时使用服务器默认视频模型；指定系列后，实际生成只能使用该系列中已注册、已启用且能力匹配的型号。系列没有所需能力时会提示问题。界面会展示模型策略；确认计划前可以检查具体型号与参数。

**预算与审批**：预算是工具调用的估算 credits，不等于供应商实际金额。视频分析、Director/Creative 规划在审批前执行，真实模式下这些阶段也可能收费。先用默认 Mock 验证流程，再显式开启真实模型。

### 经典工作流

从模板创建 Job，上传源视频，执行完整流程或单个节点：视频理解 → 提示词改写 → 首帧生成 → I2V。T2V、R2V、I2I Test 为可选分支。支持 DAG 并行、暂停/取消、局部重跑、提示词版本管理、部分成功结果展示和打包。

## 本地启动（Windows PowerShell）

本教程统一使用：**本机 MySQL + Docker Redis + 本机 Python/Node.js**。先准备 Python 3.10+、Node.js 18+、运行中的 MySQL 8.0+、Docker Desktop（Linux 容器）和 FFmpeg。

### 1. 激活已有 Conda 环境

以下命令从**项目根目录**执行。沿用你平时使用的 Conda 环境即可，下面以 `video-factory` 为例，替换为你的实际环境名：

```powershell
conda env list
conda activate video-factory
python -m pip install -r backend/requirements.txt
```

没有现成环境时，可先执行 `conda create -n video-factory python=3.12`，再激活和安装依赖。环境名不必随项目改名而修改。

激活后，`python` 就是该 Conda 环境的解释器，无需写 `..\.venv\Scripts\python.exe`。用 `python -c "import sys; print(sys.executable)"` 可以确认。**每次打开新终端都要先激活同一个环境**。如果普通 PowerShell 无法识别 `conda activate`，可使用已初始化的 Anaconda PowerShell Prompt。

<details>
<summary>可选：不使用 Conda 时，使用 Python 自带 venv</summary>

在根目录执行 `python -m venv .venv`，然后执行 `.\.venv\Scripts\Activate.ps1`；Linux/macOS 使用 `source .venv/bin/activate`。之后的 `python -m ...` 命令相同。

Conda 用户无需创建或激活这一份 `.venv`。目录名称 `.venv` 并不决定它由 Conda 还是 Python venv 管理。

</details>

### 2. 配置唯一的 .env

本地配置统一放在**项目根目录 `.env`**，完整模板为 [`.env.example`](.env.example)。不再使用 `backend/.env`。API、Agent、MQ 进程均读取这一份配置；已设置的系统/终端环境变量优先，修改文件后需重启相关进程。

从旧版升级时，将 `backend/.env` 中正在使用的配置迁入根目录 `.env`，冲突项以当前后端配置为准。备份后移除旧文件，避免 Flask CLI 自动发现它。

仅首次创建时复制模板；已有 `.env` 请直接编辑，保留密码和 Key：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

先确认这几个值：

```dotenv
DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/video_factory?charset=utf8mb4
REDIS_URL=redis://127.0.0.1:6379/0
MQ_ENABLED=true
AGENT_MODE_ENABLED=true
MODEL_ADAPTER_MODE=mock
```

| 配置 | 如何填写 |
| --- | --- |
| `DATABASE_URL` | 替换为现有本地 MySQL 用户、密码和库名；数据库须事先存在，密码特殊字符需 URL 编码 |
| `REDIS_URL` | 与下一步 Docker 发布的本机端口一致；无需手动建 Redis 库或 Stream |
| `MQ_ENABLED` | `true`：Agent/工作流分析与媒体任务共用持久化队列 |
| `AGENT_MODE_ENABLED` | `true`：开放 Agent Studio；只测试经典工作流时可关闭 |
| `MODEL_ADAPTER_MODE` | `mock` 验证功能；`real` 调用真实模型；`auto` 有 Key 时可能直接调用真实服务 |
| `FFMPEG_BINARY` | FFmpeg 已在 PATH 则留空，否则填写可执行文件路径，Windows 可用正斜杠 |
| `SECRET_KEY` / `JWT_SECRET_KEY` | 设置自己的随机密钥；不要提交真实 `.env` |

存储路径 `storage`、上传路径 `storage/uploads` 和 `FACTORY_PROMPTS_DIR=../factory_prompts` 仍相对于 **backend 目录**，移动 `.env` 不会移动历史素材。Agent checkpoint 默认位于 `backend/storage/agent/`，需保留。

### 3. 启动 Docker Redis

在项目根目录执行，只启动 Redis，复用你原有的本地 MySQL：

```powershell
docker compose -f docker-compose.local.yml up -d --wait
docker compose -f docker-compose.local.yml exec redis redis-cli ping
```

预期返回 `PONG`。Redis 仅监听 `127.0.0.1:6379`，使用 AOF 和具名卷保存数据。端口被占用时，同时调整 `docker-compose.local.yml` 的主机端口和 `.env` 的 `REDIS_URL`。

### 4. 升级本地数据库

先结束旧后端/worker 正在执行的任务并停止旧进程；已有数据库先备份。以下命令在激活的环境中执行：

```powershell
cd backend
python -m flask --app run.py db upgrade
python -m flask --app run.py db current
```

预期迁移版本为 `20261017_001 (head)`。新数据库再执行 `python -m flask --app run.py init-db` 写入默认模板、模型与节点；已有库需要补默认数据时也可执行。不要用 `db stamp` 跳过升级。

### 5. 启动后端和两个 worker

分别打开三个终端，每个都先从**项目根目录**执行（将环境名换为你的实际名称）：

```powershell
conda activate video-factory
cd backend
```

然后各自执行一条命令，并保持运行：

| 终端 | 命令 | 用途 |
| --- | --- | --- |
| 1 | `python -m flask --app run.py run --host 127.0.0.1 --port 5000` | REST API |
| 2 | `python -m flask --app run.py mq-worker --role all` | 共用队列调度、提交、轮询、下载 |
| 3 | `python -m flask --app run.py agent-worker` | Agent 分析、规划与审批后的流程推进 |

只测经典工作流可省略终端 3。启用 MQ 后，只有 API 和 Redis、没有 MQ worker 时，任务会一直等待。Agent worker 单机只运行一个。

`--role all` 适合本地 Mock。进行真实调用时，建议在不同终端分别运行 `scheduler`、`submit`、`poll`、`download` 四个 MQ 角色，避免同步提交阻塞轮询，命令形式为 `python -m flask --app run.py mq-worker --role submit` 等。

### 6. 启动前端并测试

另一个终端从项目根目录执行：

```powershell
cd frontend-vue
npm install
npm run dev
```

访问 `http://localhost:5173`，注册/登录。先在 Agent Studio 创建一个单镜头 Mock 会话，检查计划编辑 → 确认 → 结果 → 打包，再尝试二创或经典工作流。Mock 视频可能是占位文件，不能用于评估画质或播放兼容性。

API 健康地址为 `http://127.0.0.1:5000/api/health`。查看 MQ 状态时，在已激活的 `backend` 终端执行：

```powershell
python -m flask --app run.py mq-status
```

## 任务中心

登录后从侧栏进入“任务中心”（`/task-center`），统一查看**自己的 Agent 会话与共享的经典工作流作业**。可以按来源、状态、标题或编号筛选，并展开镜头/节点详情查看等待依赖、等待授权、待提交、服务商生成、下载及本地交付阶段。

页面每5秒刷新；请求失败会保留上次数据并标记过期。进度以完成镜头/节点数表示，不推算剩余时间或精确队列排名。当前没有 Worker 心跳，页面显示健康状态未知；MQ 开关只表示是否接纳新任务，不能证明 Worker 正常运行。

这是只读业务视图，直接读取数据库，不连接 Redis 或触发任务。审核、重做与恢复需跳回 Agent Studio 或经典作业页操作。任务中心本身不需要额外启动进程；执行任务仍需要前述 worker。

## 模型目录更新（2026-10）

新增模型不会替换现有服务器默认值。API 启动时（`AUTO_REPAIR_SCHEMA=true`）会补齐模型种子；需要手动补齐时，可通过现有 `POST /api/models/seed-defaults` 接口更新目录。这里只更新目录，不会调用生成服务。生产环境修改前请保留自己配置的模型参数与价格。

| 模型 | 当前接入范围 |
| --- | --- |
| `qwen-image-3.0` / `qwen-image-3.0-pro` | 文生图、最多3张参考图的图像编辑；异步提交/轮询/下载，保留多张输出（Agent入口最多4张） |
| `wan3.0-video` / `wan3.0-video-prime` | 文生视频、首帧、首尾帧候选、参考图片；同一真实模型ID用于多种任务，固定2–30秒 |
| `deepseek-v4.1-flash` | 百炼文本/结构化决策，使用 `DASHSCOPE_API_KEY`；默认关闭思考，不使用 DeepSeek 自营 Key |

新模型继续沿用当前域名，不需要 Workspace ID：

```dotenv
DASHSCOPE_API_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Wan3 首尾帧仍由 `AGENT_ENABLE_KEYFRAME_BRIDGE` 控制，默认关闭；不能据 Mock 结果认定它与首帧模式画质相同。官方全模态参考、视频编辑/延长能力与当前 Agent 可执行能力分列：本轮不允许 Agent 自动使用参考视频、编辑、延长或文件/网页。受控视频输入、完整预算和审核契约尚需后续开发；智能时长 `-1` 暂不开放，避免无法确定费用上界。

模型目录的 **credits 仍是演示估算，不是人民币账单**。Wan3 按分辨率选择每秒费率，参考视频的费用规则是“输入视频秒数 + 输出视频秒数”；延长的 `duration` 表示完整输出长度，不是新增段长度。图片输入计费、LLM token计费等差异不能由演示credits精确表示。新模型仅经过隔离Mock与HTTP Stub验证，真实账号在旧域名下的可用性、画质及费用尚未实测。

官方参考：[Qwen Image 3.0](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)、[Wan3统一API](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference)、[DeepSeek百炼API](https://help.aliyun.com/zh/model-studio/deepseek-api)、[计费](https://help.aliyun.com/zh/model-studio/model-pricing)。开发边界与Claude交接见 [M/T契约](docs/agent_v2/CONTRACTS.md) 和 [交接日志](docs/agent_v2/PROGRESS.md)。

## 切换真实模型

在根目录 `.env` 填写对应的 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY`，设置 `MODEL_ADAPTER_MODE=real`，重启 API 和所有 worker。确认模型注册表中的模型已启用，再创建新会话，检查计划和费用后审批。

服务器默认模型可通过 `DEFAULT_*_MODEL` 配置；数据库中已有的节点配置和 Job 覆盖可能优先于环境默认值。模型参数只能使用该型号支持的字段，不能把 `model_id` 塞进 `image_params` / `video_params`。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| 找不到 Flask 或其他 Python 包 | 确认当前终端已激活相同的 Conda 环境，用 `python -m pip` 安装依赖 |
| Agent 入口不显示 | 检查 `AGENT_MODE_ENABLED=true`，重启后端并刷新前端 |
| Agent 一直排队或审批后不推进 | 检查 Agent worker；生成 Job 等待时再检查 MQ worker 和 Redis |
| 提示缺表或未知字段 | 对当前 MySQL 执行 `db upgrade`；`init-db` 不能代替迁移 |
| 上传/保留镜头失败 | 检查 FFmpeg 路径、媒体格式与上传大小 |
| 提交结果未知 `submit_unknown` | 先核对供应商任务记录，按运维文档对账，避免重复生成 |

日常停止：各应用终端按 `Ctrl+C`；根目录执行 `docker compose -f docker-compose.local.yml stop redis`。下次 `up -d --wait` 恢复。保留 Redis 卷、MySQL 数据和 storage，不用 `down -v` 或 `FLUSHDB` 清业务队列。

## 技术与开发

前端为 Vue 3 / Vite，后端为 Flask / SQLAlchemy，Agent 使用 LangGraph。MySQL 保存业务状态与事务 Outbox，Redis Streams 运送执行事件，文件存于 storage。

```text
.env.example                 # 唯一本地配置模板
.env                         # 本机配置，Git 忽略
backend/app/agent/           # 分镜规划、审批、二创与恢复
backend/app/queue/           # 共用队列执行层
backend/app/services/        # DAG、模型、提示词、工件与打包
backend/tests/               # 隔离 Mock 回归
frontend-vue/                # Agent Studio 与经典工作流界面
docker-compose.local.yml     # 本地 Redis
docker-compose.yml           # 完整生产部署
```

在已激活环境的根目录运行离线回归：

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

涉及原视频的测试需要 FFmpeg。测试使用独立 SQLite/storage、强制 Mock 并阻断供应商 HTTP。前端验证为在 `frontend-vue` 执行 `npm run build`。

## 进一步阅读

- [Agent 从零创作实现](docs/architecture/phase2_langgraph_mvp.md)
- [原视频二次创作与镜头协议](docs/architecture/phase3_video_remix.md)
- [稳定性与系统评估](docs/architecture/phase4_stability_evaluation.md)
- [MQ 部署、恢复、人工对账和回滚](docs/architecture/mq_implementation.md)
- [后端 API 与业务细节](backend/README.md)
- [生产部署](DEPLOYMENT.md)：单独使用 `.env.production`，由容器注入配置，不与本地 `.env` 混用。

本项目使用 [MIT 许可证](LICENSE)。
