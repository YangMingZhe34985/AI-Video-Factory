# AI Video Factory

AI Video Factory is a full-stack video generation workflow system. It provides a Flask backend and a Vue 3 + Vite frontend for creating, running, monitoring, and packaging AI video generation jobs.

The project is designed around workflow nodes, prompt versioning, model registry management, generated artifacts, and job event tracking. It supports both mock execution for local development and real DashScope/Qwen-compatible model adapters for production practice.

## Features

- Create and manage video generation jobs.
- Run full workflows, run from a selected node, or run a single node.
- Configure workflow nodes and per-job model parameters.
- Manage prompt versions with activation, rollback, edit-as-new-version, and job snapshots.
- Manage model registry entries for text, image, video, I2V, R2V, and I2I flows.
- Track job node runs, API tasks, artifacts, package outputs, and structured error details.
- View live job events and historical event logs in the job detail page.
- Package selected final videos, images, and prompts into a downloadable ZIP.
- Browse and preview artifacts, including Markdown and JSON text artifacts.

## Tech Stack

Backend:

- Python 3.10+
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- PyMySQL
- Pydantic
- python-dotenv
- requests

Frontend:

- Vue 3
- Vite
- Pinia
- Vue Router
- Axios
- Tailwind CSS
- Phosphor Icons
- vue-i18n

## Project Structure

```text
.
|-- backend/                 # Flask REST API, workflow engine, adapters, database models
|   |-- app/
|   |-- migrations/
|   |-- storage/             # Runtime data, ignored by git
|   |-- .env.example
|   |-- requirements.txt
|   `-- run.py
|-- frontend-vue/            # Vue 3 + Vite frontend
|   |-- src/
|   |-- public/
|   |-- package.json
|   `-- vite.config.js
|-- factory_prompts/         # Prompt templates used by workflow seed logic
|-- workspace/               # Local generated/runtime workspace, ignored by git
|-- .gitignore
|-- LICENSE
`-- README.md
```

## Security Notice

Never commit real API keys, local `.env` files, generated videos/images, user uploads, database files, or runtime storage directories.

This repository includes a `.gitignore` that excludes:

- `.env` and `.env.*`, while keeping `.env.example`.
- `backend/storage/`, `storage/`, and `workspace/`.
- generated images, videos, audio files, local databases, logs, caches, and build outputs.
- local tool state such as `.claude/`, `.codex_smoke/`, and IDE folders.

Before publishing, run:

```bash
git status --short
```

Check carefully that no file containing `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`, JWT secrets, database passwords, uploaded videos, generated images, or personal reference photos is staged.

## Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env` for your local environment.

Important variables:

```env
SECRET_KEY=change-me
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/video_factory
STORAGE_ROOT=storage
UPLOAD_FOLDER=storage/uploads
DASHSCOPE_API_KEY=
DEFAULT_VIDEO_UNDERSTANDING_MODEL=qwen3.6-plus
DEFAULT_PROMPT_REWRITE_MODEL=deepseek-v4-flash
DEFAULT_T2V_MODEL=wan2.7-t2v
DEFAULT_IMAGE_MODEL=wan2.7-image
DEFAULT_I2V_MODEL=wan2.7-i2v
```

Initialize the database:

```bash
flask --app run.py db upgrade
flask --app run.py init-db
```

Start the backend:

```bash
flask --app run.py run --host 0.0.0.0 --port 5000
```

Health check:

```bash
curl http://127.0.0.1:5000/api/health
```

## Frontend Setup

```bash
cd frontend-vue
npm install
npm run dev
```

The Vite dev server runs at:

```text
http://localhost:5173
```

API requests are proxied to:

```text
http://127.0.0.1:5000
```

Production build:

```bash
npm run build
```

## Workflow Overview

The main I2V path is:

```text
reverse_prompts
rewrite_prompts
submit_first_frame_image
poll_first_frame_image
submit_i2v
poll_i2v
export_manifest
```

Optional branches include:

- T2V: `submit_t2v -> poll_t2v`
- R2V: `reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash`
- I2I test: `rewrite_t2i_to_i2i` and the I2I test batch nodes
- Failure diagnosis: `failure_agent`

The backend supports queued job execution and DAG-style parallel node scheduling where dependencies allow it.

## Prompt System

Prompts are versioned assets. The system never overwrites old prompt versions. Editing, rollback, and workflow-generated prompts create new versions and can be snapshotted per job for reproducibility.

Key prompt types include:

- `t2v`
- `first_frame_image`
- `i2v`
- `i2i`
- `r2v_flash`
- `video_understanding_system`
- `prompt_rewrite_system`
- `reverse_prompts4r2v_system`
- `rewrite_t2i_to_i2i_system`
- `failure_agent_system`

Factory prompt files live in `factory_prompts/` and can be seeded into templates.

## Model Registry

Models are managed through the backend model registry. Business code calls adapters through a unified interface instead of calling provider APIs directly.

Examples:

- `qwen3.6-plus`
- `qwen3.5-plus`
- `glm5-1`
- `deepseek-v4-flash`
- `deepseek-v4-pro`
- `wan2.7-t2v`
- `wan2.6-image`
- `wan2.7-image`
- `wan2.7-image-pro`
- `wan2.7-i2v`
- `wan2.6-r2v-flash`

## API Overview

Common response format:

```json
{
  "success": true,
  "data": {}
}
```

Common error format:

```json
{
  "success": false,
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "Job not found"
  }
}
```

Core API groups:

- Auth: `/api/auth/*`
- Dashboard: `/api/dashboard/summary`
- Templates: `/api/templates`
- Jobs: `/api/jobs`
- Workflow: `/api/workflow/nodes`
- Prompts: `/api/prompts`, `/api/templates/{template_id}/prompts`
- Models: `/api/models`
- Artifacts: `/api/artifacts`, `/api/jobs/{job_id}/artifacts`

## Production Notes

- Use MySQL for production practice instead of local SQLite.
- Use strong `SECRET_KEY` and JWT settings.
- Keep `API_AUTH_REQUIRED=true` unless you are developing locally.
- Store API keys only in environment variables or server secret managers.
- Do not commit runtime storage or generated media.
- The current job queue is process-local. For multi-process or distributed production deployment, migrate queue execution to Celery/Redis or an equivalent external task queue.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
