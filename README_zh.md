# AI Video Factory

**中文文档** | [English](README.md)

全栈 AI 视频生成工作流平台，集成 DAG 流水线调度、提示词版本管理、模型注册中心和工件管理系统。

AI Video Factory 通过自动化、可配置的多步骤工作流，将一段源视频转化为 AI 生成的成品视频——涵盖视频理解、提示词工程、图像生成、视频合成和质量测试。

---

## ✨ 功能特性

### 工作流引擎
- **DAG 并行调度** — 节点依赖满足后自动并发执行
- **多种运行模式** — 全量执行、从指定节点执行、单节点执行
- **作业生命周期控制** — 暂停、取消、重启、强制重跑
- **容错执行** — 单个节点失败不影响全局，部分结果完整保留
- **I2I 测试批次系统** — 批量身份保持图像/视频生成，单样本故障隔离

### 提示词管理
- **版本化提示词** — 每次编辑、回滚或 LLM 生成均创建新版本，永不覆盖
- **多来源提示词** — 工厂默认、LLM 生成、手动编辑、回滚版本共存
- **作业级快照** — 每个作业捕获使用的精确提示词版本，确保可复现
- **模板优先 / 作业优先** — 可配置的提示词继承策略

### 模型注册中心
- **适配器抽象** — 统一接口对接 DashScope、Qwen、DeepSeek 及 Mock 提供商
- **作业级模型覆盖** — 为指定节点分配不同模型，无需修改全局默认值
- **支持的任务类型** — 文生视频、图像生成、图生视频、参考生视频、对话/理解

### 工件与打包
- **全链路工件追踪** — 每个生成的视频、图像和提示词均记录元数据和来源
- **工件浏览器** — 搜索、筛选、预览（图像/视频/Markdown/JSON）和下载任意工件
- **一键打包** — 将作业结果或模板级生产包导出为可下载的 ZIP 文件

### 实时监控
- **SSE 实时事件流** — 通过 Server-Sent Events 实时观看作业进度
- **结构化事件日志** — 每次状态变更、API 调用和错误均记录完整上下文
- **节点级进度** — 一目了然地查看哪些工作流节点正在运行、成功或失败

### 其他功能
- **LLM 故障诊断代理** — 自动错误分析并给出可操作的恢复决策
- **自动视频压缩** — 可配置的 ffmpeg 压缩，支持大小感知回退
- **JWT 认证** — 安全的 API 访问与令牌刷新
- **国际化** — 基于 vue-i18n 的中英文 UI
- **Docker 部署** — 开箱即用的 Docker Compose（MySQL + Gunicorn + Nginx）

---

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                   前端 (Vue 3)                            │
│   Vite · Pinia · Vue Router · Tailwind CSS · vue-i18n   │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API / SSE
┌──────────────────────▼──────────────────────────────────┐
│                   后端 (Flask)                            │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ 工作流    │  │  提示词       │  │  模型注册中心      │  │
│  │ 调度器    │  │  版本管理     │  │  & 适配器         │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ 工件      │  │  作业队列     │  │  故障诊断代理      │  │
│  │ 服务      │  │  & 事件系统   │  │  (LLM 诊断)      │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   DashScope / Qwen / Mock   │
        │   (模型提供商 API)            │
        └─────────────────────────────┘
```

### 工作流管线

```
源视频
    │
    ▼
reverse_prompts ──► 视频理解 LLM ──► T2V 提示词
    │
    ▼
rewrite_prompts ──► 首帧图像提示词 + I2V 提示词
    │
    ├──► submit_first_frame_image ──► poll_first_frame_image ──► 首帧图像
    │                                                               │
    │                                                               ▼
    │                                            submit_i2v ──► poll_i2v ──► 成品视频
    │
    ├──► [T2V]        submit_t2v ──► poll_t2v ──► T2V 视频
    │
    ├──► [R2V Flash]  reverse_prompts4r2v ──► submit_r2v_flash ──► poll_r2v_flash
    │
    ├──► [I2I 测试]   rewrite_t2i_to_i2i ──► prepare_batch ──► submit/poll（批量）
    │
    └──► [故障代理] ──► 基于 LLM 的错误诊断
    │
    ▼
export_manifest ──► 作业清单 JSON
```

---

## 🛠 技术栈

| 层级 | 技术 |
|---|---|
| **前端** | Vue 3.4、Vite 5、Pinia、Vue Router、Tailwind CSS 3、Phosphor Icons、vue-i18n |
| **后端** | Python 3.12、Flask 3、Flask-SQLAlchemy、Flask-Migrate、Pydantic 2、Flask-JWT-Extended |
| **数据库** | MySQL 8.0（生产环境）/ SQLite（开发环境） |
| **部署** | Docker、Docker Compose、Nginx、Gunicorn |
| **模型提供商** | 阿里云 DashScope（Wan 系列）、Qwen、DeepSeek |
| **工具** | ffmpeg（视频压缩）、Alembic（数据库迁移） |

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- MySQL 8.0（可选，开发环境可使用 SQLite）

### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env — 设置 DATABASE_URL、DASHSCOPE_API_KEY 等

# 初始化数据库
flask --app run.py db upgrade
flask --app run.py init-db

# 启动开发服务器
flask --app run.py run --host 0.0.0.0 --port 5000
```

### 前端

```bash
cd frontend-vue

npm install
npm run dev
```

前端运行在 `http://localhost:5173`，API 请求代理至 `http://127.0.0.1:5000`。

### Docker 部署（生产环境）

```bash
# 复制并编辑生产环境配置
cp deploy/.env.production.example .env.production

# 构建并启动所有服务
docker compose up -d --build
```

将启动三个容器：
- **MySQL 8.0** — 带持久化卷的数据库
- **Backend** — Flask + Gunicorn，端口 5000（内部）
- **Frontend** — Nginx 提供 SPA 服务，端口 80，反向代理 `/api/` 至后端

完整的生产部署指南请参阅 [DEPLOYMENT.md](DEPLOYMENT.md)。

---

## 📂 项目结构

```
.
├── backend/                    # Flask REST API & 工作流引擎
│   ├── app/
│   │   ├── adapters/           # 模型提供商适配器（DashScope、Qwen、Mock）
│   │   ├── api/                # 路由处理器（蓝图）
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 请求/响应模式
│   │   ├── services/           # 业务逻辑层
│   │   └── utils/              # 共享工具
│   ├── migrations/             # Alembic 数据库迁移
│   ├── storage/                # 运行时数据（git 忽略）
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py                  # WSGI 入口
│
├── frontend-vue/               # Vue 3 + Vite 单页应用
│   ├── src/
│   │   ├── api/                # Axios API 客户端模块
│   │   ├── components/         # 可复用 UI 组件
│   │   ├── composables/        # Vue 组合函数（SSE、认证等）
│   │   ├── i18n/               # 中英文语言包
│   │   ├── stores/             # Pinia 状态管理
│   │   ├── views/              # 页面组件
│   │   └── router/             # Vue Router 配置
│   ├── vite.config.js
│   └── package.json
│
├── deploy/                     # Docker & Nginx 配置
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── nginx.conf
│   ├── entrypoint.sh
│   └── .env.production.example
│
├── factory_prompts/            # 默认提示词模板（.md）
├── docker-compose.yml
├── DEPLOYMENT.md               # 生产部署指南
├── LICENSE                     # MIT 许可证
└── README.md
```

---

## ⚙️ 配置说明

主要环境变量（完整列表见 `.env.example`）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | 数据库连接字符串 | `sqlite:///video_factory.db` |
| `SECRET_KEY` | Flask 密钥 | — |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API 密钥 | — |
| `MODEL_ADAPTER_MODE` | `mock`、`real` 或 `auto` | `auto` |
| `T2V_ENABLED` | 启用文生视频分支 | `true` |
| `I2V_ENABLED` | 启用图生视频分支 | `true` |
| `R2V_FLASH_ENABLED` | 启用 R2V Flash 分支 | `false` |
| `I2I_TEST_ENABLED` | 启用 I2I 测试分支 | `false` |
| `WORKFLOW_PARALLEL_ENABLED` | 启用 DAG 并行调度 | `true` |
| `VIDEO_COMPRESSION_ENABLED` | 启用 ffmpeg 视频压缩 | `true` |
| `FAILURE_AGENT_ENABLED` | 启用 LLM 故障诊断 | `false` |

---

## 📡 API 概览

所有接口以 `/api/` 为前缀，认证方式为 JWT Token。

**响应格式：**
```json
{ "success": true, "data": { ... } }
```

**错误格式：**
```json
{ "success": false, "error": { "code": "JOB_NOT_FOUND", "message": "作业未找到" } }
```

**核心接口分组：**

| 分组 | 前缀 | 说明 |
|---|---|---|
| 认证 | `/api/auth` | 注册、登录、令牌刷新 |
| 仪表盘 | `/api/dashboard` | 聚合统计 |
| 模板 | `/api/templates` | 模板 CRUD 与打包 |
| 作业 | `/api/jobs` | 作业 CRUD、运行控制、打包 |
| 工作流 | `/api/workflow` | 节点管理与验证 |
| 提示词 | `/api/prompts` | 提示词版本管理 |
| 模型 | `/api/models` | 模型注册中心 CRUD |
| 工件 | `/api/artifacts` | 工件搜索、下载、预览 |

**关键作业接口：**

```
POST   /api/jobs                          # 创建作业
POST   /api/jobs/{id}/run-full            # 运行完整工作流
POST   /api/jobs/{id}/run-from            # 从指定节点运行
POST   /api/jobs/{id}/run-node            # 运行单个节点
POST   /api/jobs/{id}/pause               # 暂停运行中的作业
POST   /api/jobs/{id}/cancel              # 取消作业
GET    /api/jobs/{id}/stream              # SSE 实时事件流
POST   /api/jobs/{id}/package             # 生成结果 ZIP
```

---

## 🤝 参与贡献

欢迎贡献代码！以下是参与方式：

1. **Fork** 本仓库
2. **创建功能分支** — `git checkout -b feature/my-feature`
3. **编写代码** — 遵循现有代码风格和模式
4. **测试** — 确保后端和前端均能正常运行
5. **提交 Pull Request** — 描述你的修改内容和原因

### 开发说明

- 后端使用 Flask 蓝图组织 API 路由；新接口添加至 `backend/app/api/`
- ORM 模型位于 `backend/app/models/`；修改后运行 `flask db migrate`
- 前端状态通过 Pinia Store 管理，位于 `frontend-vue/src/stores/`
- 工作流引擎核心在 `backend/app/services/workflow_scheduler.py` 和 `node_runner.py`
- 模型适配器遵循适配器模式；接口定义见 `backend/app/adapters/base.py`

---

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

---

## 🙏 致谢

- [阿里云 DashScope](https://dashscope.aliyun.com/) — Wan 系列视频/图像生成模型提供商
- [Flask](https://flask.palletsprojects.com/) — Python Web 框架
- [Vue.js](https://vuejs.org/) — 渐进式 JavaScript 框架
- [Tailwind CSS](https://tailwindcss.com/) — 实用优先的 CSS 框架
