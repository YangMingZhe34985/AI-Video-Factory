# CineCrew

[中文](README_zh.md) | **English**

CineCrew (formerly AI Video Factory) is an AI video creation platform. Use Agent Studio to turn a brief or source video into an approved shot plan, or control individual generation nodes through the classic workflow. Both modes share model registration, Jobs, artifacts, packaging and the execution queue.

## Choose a mode

| Mode | Best for | Your controls |
| --- | --- | --- |
| Agent Studio | Creation from a written idea or remixing an existing video | Goal, shots, model preference, budget, plan approval and shot edits |
| Classic workflow | Node debugging, source-video pipelines and batch tests | DAG branches, prompt versions, models, parameters and partial reruns |

### Agent Studio

Director structures the brief, Creative writes the shot plan, and Production executes approved generation tools.

**From scratch:** brief → shot plan → edit and approve → generate first frames and videos → review → package. Example: “Create a video of a dancing cat using the wan2.7 video model family.” The current route is first-frame generation followed by I2V; automatic T2V/I2V/R2V route selection is not implemented.

**Source-video remix:** upload → describe edits → analyze → approve which segments to keep/regenerate → review and revise individual shots → package. Kept segments are cut locally with FFmpeg. Regenerated segments can use a source frame or a newly generated frame.

A source time range identifies material in the original video; generated duration is a separate model parameter. Invalid draft plans can be edited before approval. Remix shot revisions preserve other shots. Successful results remain available after partial failure. Delivery consists of shot assets and prompts in ZIP packages; automatic final-film assembly is not included.

Without a model preference, the server's default video models apply. An explicit family or model restricts generation to registered, enabled models with the required capability. Unsupported combinations are rejected. Review concrete models and parameters in the plan before approval.

Budgets are estimated credits, not provider invoices. Analysis and planning happen before media-generation approval and may already incur costs in real mode. Start with Mock.

### Classic workflow

Create a Job from a template, upload a source video and run the pipeline or individual nodes: video understanding → prompt rewrite → first frame → I2V. Optional branches include T2V, R2V and I2I Test. The DAG supports parallel execution, pause/cancel, partial reruns, prompt history and packaging of usable results.

## Local setup: Windows PowerShell

Use **host MySQL + Docker Redis + host Python/Node.js**. Prerequisites: Python 3.10+, Node.js 18+, a running MySQL 8.0+ database, Docker Desktop with Linux containers, and FFmpeg.

### 1. Activate your existing Conda environment

Start in the **repository root** and reuse your normal Conda environment. Replace the example name `video-factory` with your actual environment name:

```powershell
conda env list
conda activate video-factory
python -m pip install -r backend/requirements.txt
```

If needed, first create an environment with `conda create -n video-factory python=3.12`. The environment name does not need to change when the project is renamed.

After activation, `python` resolves to that environment's interpreter. Check with `python -c "import sys; print(sys.executable)"`. Activate the same environment in **each new terminal**. Use an initialized Anaconda PowerShell Prompt if Conda activation is unavailable in your normal shell.

<details>
<summary>Optional: Python venv instead of Conda</summary>

From the root, run `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` (Linux/macOS: `source .venv/bin/activate`). Subsequent `python -m ...` commands are the same. Conda users do not need this additional environment; the directory name `.venv` alone does not identify the environment manager.

</details>

### 2. Configure one .env

The **root `.env`** is the single local configuration for the API, Agent and MQ workers. Use the root [`.env.example`](.env.example); `backend/.env` is no longer used. Existing process environment variables take precedence. Restart processes after configuration changes.

When upgrading an older checkout, migrate the active backend values into the root `.env`, keeping backend values on conflicts. Back up and remove `backend/.env` so Flask CLI cannot discover the stale file.

```powershell
# Preserve an existing file and its credentials.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Confirm these values in `.env`:

```dotenv
DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/video_factory?charset=utf8mb4
REDIS_URL=redis://127.0.0.1:6379/0
MQ_ENABLED=true
AGENT_MODE_ENABLED=true
MODEL_ADAPTER_MODE=mock
```

Replace MySQL credentials/database; the database must already exist. Percent-encode password special characters. Set your own `SECRET_KEY` and `JWT_SECRET_KEY`. Set `FFMPEG_BINARY` if FFmpeg is not on PATH. `auto` model mode may use real APIs when keys are present; `mock` keeps local testing on test assets.

Relative storage/upload paths remain relative to **backend/**, as does `FACTORY_PROMPTS_DIR=../factory_prompts`. Moving `.env` does not move existing media. Preserve Agent checkpoints under `backend/storage/agent/`.

### 3. Start Docker Redis

From the repository root, with Docker Desktop running:

```powershell
docker compose -f docker-compose.local.yml up -d --wait
docker compose -f docker-compose.local.yml exec redis redis-cli ping
```

Expected: `PONG`. This starts only Redis, bound to `127.0.0.1:6379`, with AOF and a named volume. It reuses your host MySQL. If the port is occupied, change the Compose host port and `REDIS_URL` together. Workers create streams/groups automatically.

### 4. Migrate MySQL

Drain and stop previous backend/workers first. Back up an existing database. In your activated environment:

```powershell
cd backend
python -m flask --app run.py db upgrade
python -m flask --app run.py db current
```

Expected revision: `20261017_001 (head)`. For a new database, run `python -m flask --app run.py init-db` to seed defaults. It can also seed missing defaults in an existing database; it does not replace migration. Do not skip migrations with `db stamp`.

### 5. Run API and workers

Open three terminals, each starting in the repository root:

```powershell
conda activate video-factory
cd backend
```

Keep one command running in each terminal:

| Terminal | Command | Purpose |
| --- | --- | --- |
| 1 | `python -m flask --app run.py run --host 127.0.0.1 --port 5000` | REST API |
| 2 | `python -m flask --app run.py mq-worker --role all` | Shared dispatch, submit, poll and download |
| 3 | `python -m flask --app run.py agent-worker` | Agent planning and approved execution |

Classic-only testing can omit the Agent worker. With MQ enabled, the MQ worker is required for both modes. Run only one Agent worker per host/checkpoint. For real provider testing, run separate `scheduler`, `submit`, `poll`, `download` MQ roles so synchronous submission does not block polling.

### 6. Run the frontend

Another terminal, starting at the repository root:

```powershell
cd frontend-vue
npm install
npm run dev
```

Visit `http://localhost:5173`, register/log in, and start with a one-shot Mock Agent session: edit plan → approve → inspect results → package. Mock video assets may be placeholders and do not demonstrate video quality or playback compatibility.

API health: `http://127.0.0.1:5000/api/health`. Inspect queue state from an activated `backend/` terminal:

```powershell
python -m flask --app run.py mq-status
```

## Real models

Set the required `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` and `MODEL_ADAPTER_MODE=real` in the root `.env`, then restart the API and all workers. Ensure models are enabled in the registry, create a new session, and review the plan and costs before approval.

`DEFAULT_*_MODEL` provides environment defaults; existing node configuration and Job overrides may take precedence. Model IDs belong in their dedicated fields, not inside `image_params` / `video_params`.

## Troubleshooting and shutdown

| Symptom | Check |
| --- | --- |
| Missing Python packages | Activate the same Conda environment; install using `python -m pip` |
| Agent navigation missing | Enable `AGENT_MODE_ENABLED`, restart API, refresh frontend |
| Agent or generation stays queued | Check Agent worker, MQ worker and Redis as appropriate |
| Missing database tables/columns | Run `db upgrade` against the configured MySQL database |
| Upload/retained-shot failure | Check FFmpeg, media format and upload limit |
| `submit_unknown` | Reconcile with the provider before retrying; see queue operations docs |

Stop application terminals with `Ctrl+C`. From the root, `docker compose -f docker-compose.local.yml stop redis` stops Redis; `up -d --wait` resumes it. Preserve the volume, MySQL and storage; avoid `down -v` or `FLUSHDB` on business queues.

## Development and documentation

Vue 3/Vite frontend, Flask/SQLAlchemy backend, LangGraph Agent orchestration. MySQL holds business state and transactional outbox; Redis Streams transports events. Files are stored in storage.

- Root `.env.example`: the local configuration template; `.env` is Git-ignored.
- `backend/app/agent/`: planning, approval, remix and recovery.
- `backend/app/queue/`: shared execution queue.
- `backend/app/services/`: workflow DAG, models, prompts, artifacts and packaging.
- `frontend-vue/`: Agent Studio and classic workflow UI.
- `docker-compose.local.yml`: Redis only; `docker-compose.yml`: full production stack.

Offline tests, from the root with the virtual environment activated:

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

Tests isolate SQLite/storage, force Mock and block provider HTTP. Source-video tests need FFmpeg. Frontend validation: `npm run build` in `frontend-vue/`.

Further reading: [Agent creation](docs/architecture/phase2_langgraph_mvp.md), [source-video remix](docs/architecture/phase3_video_remix.md), [stability evaluation](docs/architecture/phase4_stability_evaluation.md), [MQ operations and rollback](docs/architecture/mq_implementation.md), [backend API](backend/README.md), [production deployment](DEPLOYMENT.md).

Production uses its own `.env.production` injected into containers; keep it separate from local `.env`. Licensed under [MIT](LICENSE).
