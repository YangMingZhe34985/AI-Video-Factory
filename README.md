# AI Video Factory

[中文文档](README_zh.md) | **English**

A full-stack AI video generation workflow platform featuring a DAG-based pipeline orchestrator, prompt versioning, model registry, and artifact management.

AI Video Factory turns a source video into production-ready AI-generated videos through an automated, configurable multi-step workflow — from video understanding and prompt engineering to image generation, video synthesis, and quality testing.

---

## ✨ Features

### Workflow Engine
- **DAG-based parallel scheduling** — nodes execute concurrently when dependencies are satisfied
- **Multiple run modes** — run the full pipeline, run from a specific node, or run a single node
- **Job lifecycle control** — pause, cancel, restart, and force re-run capabilities
- **Fault-tolerant execution** — individual node failures don't cascade; partial results are preserved
- **I2I test batch system** — batch identity-preserving image/video generation with per-sample fault isolation

### Prompt Management
- **Versioned prompts** — every edit, rollback, or LLM generation creates a new version; nothing is ever overwritten
- **Multi-source prompts** — factory defaults, LLM-generated, manual edits, and rollbacks all coexist
- **Job-level snapshots** — each job captures the exact prompt versions used, ensuring reproducibility
- **Template-first / Job-first resolution** — configurable strategy for prompt inheritance

### Model Registry
- **Adapter-based abstraction** — unified interface across DashScope, Qwen, DeepSeek, and mock providers
- **Per-job model overrides** — assign different models to specific nodes without changing global defaults
- **Supported task types** — text-to-video, image generation, image-to-video, reference-to-video, chat/understanding

### Artifact & Packaging
- **Full artifact tracking** — every generated video, image, and prompt is recorded with metadata and lineage
- **Artifact browser** — search, filter, preview (image/video/markdown/JSON), and download any artifact
- **One-click packaging** — export job results or template-level production packages as downloadable ZIP files

### Real-time Monitoring
- **SSE live event stream** — watch job progress in real time via Server-Sent Events
- **Structured event logging** — every state change, API call, and error is recorded with context
- **Node-level progress** — see which workflow nodes are running, succeeded, or failed at a glance

### Additional
- **LLM-based failure agent** — automatic error diagnosis with actionable recovery decisions
- **Automatic video compression** — configurable ffmpeg-based compression with size-aware fallback
- **JWT authentication** — secure API access with token refresh
- **Internationalization** — English and Chinese UI via vue-i18n
- **Docker deployment** — production-ready Docker Compose with MySQL, Gunicorn, and Nginx

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (Vue 3)                     │
│   Vite · Pinia · Vue Router · Tailwind CSS · vue-i18n   │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API / SSE
┌──────────────────────▼──────────────────────────────────┐
│                    Backend (Flask)                        │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Workflow  │  │   Prompt     │  │  Model Registry   │  │
│  │ Scheduler │  │   Versioning │  │  & Adapters       │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Artifact  │  │  Job Queue   │  │  Failure Agent    │  │
│  │ Service   │  │  & Events    │  │  (LLM Diagnosis)  │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   DashScope / Qwen / Mock   │
        │   (Model Provider APIs)      │
        └─────────────────────────────┘
```

### Workflow Pipeline

```
Source Video
    │
    ▼
reverse_prompts ──► Video Understanding LLM ──► T2V Prompt
    │
    ▼
rewrite_prompts ──► first_frame_image prompt + i2v prompt
    │
    ├──► submit_first_frame_image ──► poll_first_frame_image ──► First Frame
    │                                                               │
    │                                                               ▼
    │                                            submit_i2v ──► poll_i2v ──► Final Video
    │
    ├──► [T2V]        submit_t2v ──► poll_t2v ──► T2V Video
    │
    ├──► [R2V Flash]  reverse_prompts4r2v ──► submit_r2v_flash ──► poll_r2v_flash
    │
    ├──► [I2I Test]   rewrite_t2i_to_i2i ──► prepare_batch ──► submit/poll (batch)
    │
    └──► [Failure Agent] ──► LLM-based error diagnosis
    │
    ▼
export_manifest ──► Job manifest JSON
```

---

## 🛠 Tech Stack

| Layer | Technologies |
|---|---|
| **Frontend** | Vue 3.4, Vite 5, Pinia, Vue Router, Tailwind CSS 3, Phosphor Icons, vue-i18n |
| **Backend** | Python 3.12, Flask 3, Flask-SQLAlchemy, Flask-Migrate, Pydantic 2, Flask-JWT-Extended |
| **Database** | MySQL 8.0 (production) / SQLite (development) |
| **Deployment** | Docker, Docker Compose, Nginx, Gunicorn |
| **Model Providers** | Aliyun DashScope (Wan series), Qwen, DeepSeek |
| **Tools** | ffmpeg (video compression), Alembic (migrations) |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL 8.0 (optional, SQLite works for development)

### Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, DASHSCOPE_API_KEY, etc.

# Initialize database
flask --app run.py db upgrade
flask --app run.py init-db

# Start development server
flask --app run.py run --host 0.0.0.0 --port 5000
```

### Frontend

```bash
cd frontend-vue

npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and proxies API requests to `http://127.0.0.1:5000`.

### Docker Deployment (Production)

```bash
# Copy and edit production environment
cp deploy/.env.production.example .env.production

# Build and start all services
docker compose up -d --build
```

This starts three containers:
- **MySQL 8.0** — database with persistent volume
- **Backend** — Flask + Gunicorn on port 5000 (internal)
- **Frontend** — Nginx serving the SPA on port 80, reverse-proxying `/api/` to the backend

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full production deployment guide.

---

## 📂 Project Structure

```
.
├── backend/                    # Flask REST API & workflow engine
│   ├── app/
│   │   ├── adapters/           # Model provider adapters (DashScope, Qwen, Mock)
│   │   ├── api/                # Route handlers (blueprints)
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # Business logic layer
│   │   └── utils/              # Shared utilities
│   ├── migrations/             # Alembic database migrations
│   ├── storage/                # Runtime data (git-ignored)
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py                  # WSGI entry point
│
├── frontend-vue/               # Vue 3 + Vite SPA
│   ├── src/
│   │   ├── api/                # Axios API client modules
│   │   ├── components/         # Reusable UI components
│   │   ├── composables/        # Vue composables (SSE, auth, etc.)
│   │   ├── i18n/               # English & Chinese locales
│   │   ├── stores/             # Pinia state stores
│   │   ├── views/              # Page components
│   │   └── router/             # Vue Router configuration
│   ├── vite.config.js
│   └── package.json
│
├── deploy/                     # Docker & Nginx configs
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── nginx.conf
│   ├── entrypoint.sh
│   └── .env.production.example
│
├── factory_prompts/            # Default prompt templates (.md)
├── docker-compose.yml
├── DEPLOYMENT.md               # Production deployment guide
├── LICENSE                     # MIT License
└── README.md
```

---

## ⚙️ Configuration

Key environment variables (see `.env.example` for the full list):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Database connection string | `sqlite:///video_factory.db` |
| `SECRET_KEY` | Flask secret key | — |
| `DASHSCOPE_API_KEY` | Aliyun DashScope API key | — |
| `MODEL_ADAPTER_MODE` | `mock`, `real`, or `auto` | `auto` |
| `T2V_ENABLED` | Enable text-to-video branch | `true` |
| `I2V_ENABLED` | Enable image-to-video branch | `true` |
| `R2V_FLASH_ENABLED` | Enable R2V flash branch | `false` |
| `I2I_TEST_ENABLED` | Enable I2I test branch | `false` |
| `WORKFLOW_PARALLEL_ENABLED` | Enable DAG parallel scheduling | `true` |
| `VIDEO_COMPRESSION_ENABLED` | Enable ffmpeg video compression | `true` |
| `FAILURE_AGENT_ENABLED` | Enable LLM failure diagnosis | `false` |

---

## 📡 API Overview

All endpoints are prefixed with `/api/`. Authentication is via JWT tokens.

**Response format:**
```json
{ "success": true, "data": { ... } }
```

**Error format:**
```json
{ "success": false, "error": { "code": "JOB_NOT_FOUND", "message": "Job not found" } }
```

**Core endpoint groups:**

| Group | Prefix | Description |
|---|---|---|
| Auth | `/api/auth` | Register, login, token refresh |
| Dashboard | `/api/dashboard` | Aggregate statistics |
| Templates | `/api/templates` | Template CRUD & packaging |
| Jobs | `/api/jobs` | Job CRUD, run control, packaging |
| Workflow | `/api/workflow` | Node management & validation |
| Prompts | `/api/prompts` | Prompt versioning & management |
| Models | `/api/models` | Model registry CRUD |
| Artifacts | `/api/artifacts` | Artifact search, download, preview |

**Key job endpoints:**

```
POST   /api/jobs                          # Create job
POST   /api/jobs/{id}/run-full            # Run full workflow
POST   /api/jobs/{id}/run-from            # Run from specific node
POST   /api/jobs/{id}/run-node            # Run single node
POST   /api/jobs/{id}/pause               # Pause running job
POST   /api/jobs/{id}/cancel              # Cancel job
GET    /api/jobs/{id}/stream              # SSE live event stream
POST   /api/jobs/{id}/package             # Generate result ZIP
```

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create a feature branch** — `git checkout -b feature/my-feature`
3. **Make your changes** — follow the existing code style and patterns
4. **Test** — ensure the backend and frontend both run correctly
5. **Submit a pull request** — describe what you changed and why

### Development Notes

- Backend uses Flask blueprints for API routes; add new endpoints in `backend/app/api/`
- ORM models live in `backend/app/models/`; run `flask db migrate` after changes
- Frontend state is managed via Pinia stores in `frontend-vue/src/stores/`
- The workflow engine is in `backend/app/services/workflow_scheduler.py` and `node_runner.py`
- Model adapters follow the adapter pattern; see `backend/app/adapters/base.py` for the interface

---

## 📄 License

This project is released under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

- [Aliyun DashScope](https://dashscope.aliyun.com/) — Model provider for Wan series video/image generation models
- [Flask](https://flask.palletsprojects.com/) — Python web framework
- [Vue.js](https://vuejs.org/) — Progressive JavaScript framework
- [Tailwind CSS](https://tailwindcss.com/) — Utility-first CSS framework
