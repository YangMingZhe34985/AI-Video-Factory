# AI Video Factory Backend

这是一个全新的 Flask 后端服务，用于把视频生成流水线从命令行脚本重构为可由前端调用的 REST API。当前 MVP 使用后台线程触发工作流，支持 Mock 模式，也已经接入真实 DashScope/Qwen Adapter 调用路径。

## 技术栈

- Python 3.10+
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- PyMySQL
- Pydantic
- python-dotenv
- requests
- Werkzeug

## 目录结构

```text
backend/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── models/
│   ├── api/
│   ├── services/
│   ├── adapters/
│   ├── schemas/
│   └── utils/
├── migrations/
├── storage/
│   ├── uploads/
│   ├── jobs/
│   ├── templates/
│   └── artifacts/
├── .env.example
├── requirements.txt
├── run.py
└── README.md
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

```bash
cp .env.example .env
```

核心配置：

- `DATABASE_URL`: 默认建议 MySQL，例如 `mysql+pymysql://root:password@localhost:3306/video_factory`
- `STORAGE_ROOT`: 文件产物根目录
- `UPLOAD_FOLDER`: 源视频上传目录
- `API_AUTH_REQUIRED`: 是否启用业务接口 JWT 校验，默认 `true`
- `DASHSCOPE_API_KEY`: 真实模型 API 调用使用
- `DEFAULT_*_MODEL`: 各节点默认模型
- `T2V_ENABLED`, `FIRST_FRAME_IMAGE_ENABLED`, `I2V_ENABLED`, `R2V_FLASH_ENABLED`: 全局默认分支开关

如果没有设置 `DATABASE_URL`，代码会回退到 `storage/video_factory.db`，方便本地快速验证。

## 安装依赖

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 初始化数据库

推荐使用 Flask-Migrate / Alembic 管理表结构，再用 `init-db` 写入默认数据：

```bash
flask --app run.py db upgrade
flask --app run.py init-db
```

职责划分：

- `db upgrade`：根据 `backend/migrations/versions` 创建或升级数据库表结构。
- `init-db`：写入默认 Series、默认 Template、默认 Workflow Nodes、默认 Models，并兼容执行 schema repair。

只有在 SQLAlchemy 模型发生变化并需要生成新迁移时，才运行：

```bash
flask --app run.py db migrate -m "describe schema change"
flask --app run.py db upgrade
```

## 启动项目

```bash
flask --app run.py run --host 0.0.0.0 --port 5000
```

健康验证可访问：

```bash
curl http://127.0.0.1:5000/api/health
```

## API 概览

Auth：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/refresh`

Health / Dashboard：

- `GET /api/health`
- `GET /api/dashboard/summary`

Template：

- `POST /api/templates`
- `GET /api/templates`
- `GET /api/templates/{template_id}`

Job：

- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/run-full`
- `POST /api/jobs/{job_id}/run-from`
- `POST /api/jobs/{job_id}/run-node`
- `POST /api/jobs/{job_id}/pause`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}/events`
- `GET /api/jobs/{job_id}/stream` (SSE)

Prompt：

- `POST /api/templates/{template_id}/prompts`
- `POST /api/templates/{template_id}/prompts/seed-factory`
- `GET /api/templates/{template_id}/prompts/{prompt_type}/versions`
- `GET /api/templates/{template_id}/prompts/{prompt_type}/active`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/activate`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/rollback`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/activate`（前端兼容路由）
- `POST /api/templates/{template_id}/prompts/{prompt_type}/rollback`（前端兼容路由）

Model：

- `GET /api/models`
- `GET /api/models/{model_id}`
- `POST /api/models`
- `PUT /api/models/{model_id}`
- `POST /api/models/{model_id}/enable`
- `POST /api/models/{model_id}/disable`
- `POST /api/models/seed-defaults`

Artifact：

- `GET /api/jobs/{job_id}/artifacts`
- `GET /api/artifacts/{artifact_id}/download`
- `GET /api/artifacts/{artifact_id}/preview`
- `POST /api/jobs/{job_id}/uploads/reference-images`

统一响应格式：

```json
{"success": true, "data": {}}
```

错误格式：

```json
{"success": false, "error": {"code": "JOB_NOT_FOUND", "message": "Job not found"}}
```

## Prompt 管理

Prompt 永远新增版本，不覆盖旧内容。创建版本时默认设为 active，并自动将同一 `template_id + prompt_type` 下的旧 active 取消。

回滚不会修改历史版本，而是复制历史内容生成新版本，再设置为 active。Job 执行时会把使用到的 active prompt 写入 `job_prompt_refs`，保证旧任务可复现。

支持的 Prompt 类型包括：

- `t2v`
- `first_frame_image`
- `r2v_flash`
- `i2v`
- `video_understanding_system`
- `video_understanding_user`
- `prompt_rewrite_system`
- `prompt_rewrite_user`
- `failure_agent_system`
- `failure_agent_user`

## 模型库

模型配置保存在 `models` 表，业务服务只通过 `adapter_name` 获取统一适配器，不直接调用具体模型 API。

默认模型：

- `qwen3.7-plus`
- `qwen3.7-max`
- `qwen3.6-plus`
- `glm-5.1`
- `qwen3.5-plus`
- `wan2.7-t2v`
- `wan2.6-image`
- `wan2.7-image`
- `wan2.6-r2v-flash`
- `wan2.7-i2v`

当前 Adapter 支持 `auto/mock/real` 三种模式，真实 API 调用和 Mock 回退都在以下文件中实现：

- `app/adapters/qwen_chat.py`
- `app/adapters/dashscope_t2v.py`
- `app/adapters/dashscope_image.py`
- `app/adapters/dashscope_i2v.py`
- `app/adapters/dashscope_r2v.py`

## Job 工作流

默认节点由 `workflow_nodes` 表控制，初始化时写入：

```text
reverse_prompts
submit_t2v
poll_t2v
rewrite_prompts
submit_first_frame_image
poll_first_frame_image
submit_i2v
poll_i2v
reverse_prompts4r2v
submit_r2v_flash
poll_r2v_flash
export_manifest
```

推荐主路径：

```text
reverse_prompts
rewrite_prompts
submit_first_frame_image
poll_first_frame_image
submit_i2v
poll_i2v
export_manifest
```

T2V 和 R2V Flash 默认为可选分支。T2V 分支为 `reverse_prompts -> submit_t2v -> poll_t2v`；R2V 分支为 `reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash`。每个 Job 可通过 `enabled_nodes` 和 `disabled_nodes` 覆盖全局节点开关。

## 文件存储

视频、图片、大 JSON 不进入数据库。数据库只存路径、文件名、MIME、大小、产物类型、分支、模型和 Prompt 版本等元信息。

文件布局：

```text
storage/
├── uploads/
├── jobs/
│   └── {job_id}/
│       ├── raw/
│       ├── outputs/
│       ├── logs/
│       └── manifest.json
├── templates/
└── artifacts/
```

## 快速验证流程

```bash
flask --app run.py init-db

curl -X POST http://127.0.0.1:5000/api/templates ^
  -H "Content-Type: application/json" ^
  -d "{\"template_id\":\"demo\",\"name\":\"Demo Template\"}"

curl -X POST http://127.0.0.1:5000/api/jobs ^
  -H "Content-Type: application/json" ^
  -d "{\"template_id\":\"demo\"}"
```

拿到 `job_id` 后：

```bash
curl -X POST http://127.0.0.1:5000/api/jobs/{job_id}/run-full ^
  -H "Content-Type: application/json" ^
  -d "{\"force\":true}"
```

## 后续开发计划

- 完善真实 DashScope/Qwen API 的错误映射、成本统计和异步队列
- 引入 Celery + Redis 异步任务
- 增加成本统计和预算中断
- 增加节点参数的 JSON Schema 校验
- 增加用户角色和权限分级（当前仅有 JWT 基础认证）
- 增加任务并发限制和排队机制

## 真实模型 API 说明

当前后端已经接入真实 DashScope/Qwen 调用路径，同时保留 Mock 模式用于本地开发。

适配器模式由 `MODEL_ADAPTER_MODE` 控制：

- `auto`: 默认值。有 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY` 时走真实 API，否则走 Mock。
- `mock`: 强制 Mock，不访问外网，适合前端联调和单元测试。
- `real`: 强制真实 API，缺少 Key 会直接报错。

真实调用使用的环境变量：

```bash
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_API_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_ADAPTER_MODE=auto
POLL_INTERVAL_SEC=10
MAX_POLL_ROUNDS=90
FACTORY_PROMPTS_DIR=../factory_prompts
```

已接入的真实适配器：

- `QwenChatAdapter`: OpenAI-compatible `/chat/completions`，用于 `reverse_prompts`、`rewrite_prompts`、`reverse_prompts4r2v`、`failure_agent`
- `DashScopeT2VAdapter`: `/services/aigc/video-generation/video-synthesis`
- `DashScopeImageAdapter`: `/services/aigc/image-generation/generation`
- `DashScopeI2VAdapter`: 图生视频提交、OSS 本地文件上传、轮询、下载
- `DashScopeR2VFlashAdapter`: 参考图生视频提交、OSS 本地文件上传、轮询、下载

Template 创建时会自动从 `FACTORY_PROMPTS_DIR` 导入 factory prompts。已存在的 Template 可以手动导入：

```bash
flask --app run.py seed-factory-prompts demo
```

或调用：

```http
POST /api/templates/{template_id}/prompts/seed-factory
Content-Type: application/json

{"skip_existing": true}
```

## 前端对接文档

### 1. 基础约定

API Base URL：

```text
http://127.0.0.1:5000
```

所有 JSON API 成功响应：

```json
{
  "success": true,
  "data": {}
}
```

失败响应：

```json
{
  "success": false,
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "Job not found"
  }
}
```

前端建议统一封装：HTTP 2xx 且 `success=true` 时使用 `data`；否则展示 `error.message`，并按 `error.code` 做分支处理。

常见错误码：

```text
JOB_NOT_FOUND
TEMPLATE_NOT_FOUND
MODEL_NOT_FOUND
PROMPT_NOT_FOUND
ARTIFACT_NOT_FOUND
NODE_NOT_FOUND
NODE_DISABLED
DEPENDENCY_MISSING
INVALID_INPUT
API_TASK_FAILED
INTERNAL_ERROR
```

### 2. 推荐页面结构

- Template 列表页：创建、查看模板
- Prompt 管理页：按 `prompt_type` 查看版本、设置 active、回滚
- Model Registry 页：查看模型、启用/禁用、编辑默认参数
- Job 列表页：创建任务、查看状态
- Job 详情页：节点状态、事件流、Artifacts、运行控制
- Artifact 预览页：图片/视频/manifest 预览与下载

### 3. 初始化流程

后端启动前：

```bash
cd backend
flask --app run.py init-db
flask --app run.py run --host 0.0.0.0 --port 5000
```

前端登录后建议携带 `Authorization: Bearer <access_token>` 请求：

```http
GET /api/workflow/nodes
GET /api/models
GET /api/templates
```

这三个接口可以填充全局节点、模型和模板选择器。

### 4. Template API

创建模板：

```http
POST /api/templates
Content-Type: application/json

{
  "template_id": "demo",
  "name": "Demo Template",
  "description": "可选描述",
  "config": {}
}
```

查询：

```http
GET /api/templates
GET /api/templates/{template_id}
```

### 5. Prompt API

创建新版本：

```http
POST /api/templates/{template_id}/prompts
Content-Type: application/json

{
  "prompt_type": "i2v",
  "title": "I2V prompt v2",
  "content": "...",
  "content_format": "markdown",
  "parent_version": "v1.0",
  "note": "优化镜头运动",
  "activate": true
}
```

查询和切换：

```http
GET /api/templates/{template_id}/prompts/{prompt_type}/versions
GET /api/templates/{template_id}/prompts/{prompt_type}/active
POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/activate
POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/rollback
```

回滚会创建一个新版本，不会修改历史版本。

### 6. Job 创建

JSON 创建：

```http
POST /api/jobs
Content-Type: application/json

{
  "template_id": "demo",
  "strategy": "default",
  "enabled_nodes": [],
  "disabled_nodes": ["submit_t2v", "poll_t2v", "reverse_prompts4r2v", "submit_r2v_flash", "poll_r2v_flash"],
  "job_config": {
    "models": {
      "video_understanding": "qwen3.7-plus",
      "prompt_rewrite": "qwen3.5-plus",
      "image": "wan2.6-image",
      "i2v": "wan2.7-i2v"
    },
    "model_params": {
      "i2v": {
        "duration": 10,
        "resolution": "720P"
      }
    }
  }
}
```

上传源视频创建：

```http
POST /api/jobs
Content-Type: multipart/form-data

template_id=demo
strategy=default
enabled_nodes=[]
disabled_nodes=["submit_t2v","poll_t2v"]
job_config={}
source_video=@source.mp4
```

返回：

```json
{
  "success": true,
  "data": {
    "job_id": "job_xxx",
    "status": "pending"
  }
}
```

### 7. Job 运行控制

```http
POST /api/jobs/{job_id}/run-full
POST /api/jobs/{job_id}/run-from
POST /api/jobs/{job_id}/run-node
POST /api/jobs/{job_id}/pause
POST /api/jobs/{job_id}/cancel
```

`run-from` 请求体：

```json
{
  "node_key": "rewrite_prompts",
  "force": true
}
```

`run-node` 请求体：

```json
{
  "node_key": "submit_i2v",
  "force": true
}
```

前端按钮建议：`run-full` 做主按钮；`run-from` 放在节点右键菜单或节点详情；`force=true` 放在二次确认弹窗里。

### 8. Job 详情轮询

```http
GET /api/jobs/{job_id}
```

返回重点字段：

```json
{
  "job": {
    "job_id": "job_xxx",
    "status": "running",
    "current_node": "poll_i2v",
    "error_summary": null
  },
  "nodes": [
    {
      "node_key": "submit_i2v",
      "display_name": "Submit I2V",
      "enabled": true,
      "status": "success",
      "latest_run": {}
    }
  ],
  "artifacts": [],
  "recent_events": []
}
```

轮询建议：

- `pending/running`: 每 2-3 秒请求一次 `GET /api/jobs/{job_id}`
- `success/failed/paused/cancelled/partial_success`: 停止轮询
- 节点状态用 `nodes[].status`
- 错误摘要优先展示 `job.error_summary`
- 更详细错误展示 `nodes[].latest_run.error_message`

### 9. Artifact 预览和下载

```http
GET /api/jobs/{job_id}/artifacts
GET /api/artifacts/{artifact_id}/download
GET /api/artifacts/{artifact_id}/preview
```

展示规则：

- `mime_type` 以 `image/` 开头：用 `<img>`
- `mime_type` 以 `video/` 开头：用 `<video controls>`
- `artifact_type=manifest`：作为 JSON 文本预览
- 其他类型：只提供下载按钮

### 10. 参考图上传

```http
POST /api/jobs/{job_id}/uploads/reference-images
Content-Type: multipart/form-data

files=@ref1.png
files=@ref2.png
artifact_type=reference_image
branch_key=reference
metadata={}
```

上传成功后可运行 R2V：

```http
POST /api/jobs/{job_id}/run-node
Content-Type: application/json

{"node_key": "submit_r2v_flash", "force": true}
```

### 11. Workflow 节点

```http
GET /api/workflow/nodes
POST /api/workflow/nodes/{node_key}/enable
POST /api/workflow/nodes/{node_key}/disable
PUT /api/workflow/nodes/{node_key}/config
POST /api/workflow/validate-run
```

默认主路径：

```text
reverse_prompts
rewrite_prompts
submit_first_frame_image
poll_first_frame_image
submit_i2v
poll_i2v
export_manifest
```

可选分支：

```text
reverse_prompts -> submit_t2v -> poll_t2v
reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash
```

`failure_agent` 默认禁用。若前端需要手动触发错误处理 Agent，可在创建 Job 时传：

```json
{
  "enabled_nodes": ["failure_agent"]
}
```

然后调用：

```http
POST /api/jobs/{job_id}/run-node
Content-Type: application/json

{"node_key": "failure_agent", "force": true}
```

### 12. Model Registry

```http
GET /api/models
GET /api/models?task_type=image_to_video
GET /api/models/{model_id}
POST /api/models
PUT /api/models/{model_id}
POST /api/models/{model_id}/enable
POST /api/models/{model_id}/disable
```

新增模型示例：

```json
{
  "model_id": "wan2.7-i2v",
  "display_name": "Wan 2.7 I2V",
  "provider": "dashscope",
  "task_type": "image_to_video",
  "adapter_name": "dashscope_i2v",
  "enabled": true,
  "input_schema": {},
  "parameter_schema": {},
  "output_schema": {},
  "default_params": {
    "duration": 10,
    "resolution": "720P"
  }
}
```

前端表单需要把 `default_params/input_schema/parameter_schema/output_schema` 当作 JSON 编辑器字段处理。

### 13. JWT 认证

`POST /api/auth/register` 和 `POST /api/auth/login` 无需 Token。`GET /api/auth/me` 需要 access token，`POST /api/auth/refresh` 需要 refresh token。其余 JSON 业务接口默认需要在请求头携带 access token：

```http
Authorization: Bearer <access_token>
```

浏览器原生 `EventSource` 和普通 `<a href>` 下载无法设置 `Authorization` 头，因此当前后端对以下接口放行：`GET /api/jobs/{job_id}/stream`、`GET /api/artifacts/{artifact_id}/download`、`GET /api/artifacts/{artifact_id}/preview`。如果后续改为 Cookie 认证或签名 URL，可以收紧这三个例外。

注册：

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "alice",
  "email": "alice@example.com",
  "password": "secret123"
}
```

登录：

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "alice",
  "password": "secret123"
}
```

登录/注册成功返回 `access_token` 和 `refresh_token`：

```json
{
  "success": true,
  "data": {
    "user": { "user_id": "...", "username": "alice" },
    "access_token": "eyJ...",
    "refresh_token": "eyJ..."
  }
}
```

获取当前用户：

```http
GET /api/auth/me
Authorization: Bearer <access_token>
```

刷新 Token（使用 `refresh_token`）：

```http
POST /api/auth/refresh
Authorization: Bearer <refresh_token>
```

返回新的 `access_token`。前端应在 401 响应时自动调用此接口刷新，刷新失败则跳转登录页。

### 14. Health / Dashboard

健康检查：

```http
GET /api/health
```

返回：

```json
{
  "success": true,
  "data": { "status": "healthy", "mode": "auto" }
}
```

仪表板摘要：

```http
GET /api/dashboard/summary
```

返回模板总数、作业总数、各状态作业数、工件总数、节点运行总数等统计数据。

### 15. SSE 实时事件流

```http
GET /api/jobs/{job_id}/stream
```

响应为 `text/event-stream`，每 2 秒推送一次新事件。事件格式：

```
id: 42
data: {"id":42,"job_id":"job_xxx","node_key":"poll_i2v","event_type":"node_completed",...}
```

2 分钟无新事件后自动关闭连接。前端通过原生 `EventSource` 消费。

## Vue 3 + Vite 前端对接文档

当前对接对象是 `frontend-vue/`，不是旧的 `frontend/` 静态 HTML 目录。前端技术栈为 Vue 3 + Vite + Vue Router 4 + Pinia 2 + Axios + TailwindCSS 3。

启动方式：

```bash
cd frontend-vue
npm install
npm run dev
```

开发服务器运行在 `http://localhost:5173`，`/api` 请求通过 Vite 代理到 `http://127.0.0.1:5000`。

### 对接约定

- 所有 Axios 请求以 `/api` 为 baseURL。
- 成功响应统一为 `{ "success": true, "data": ... }`，前端拦截器会自动解包 `data`。
- 失败响应统一为 `{ "success": false, "error": { "code": "...", "message": "..." } }`。
- 登录和注册返回 `access_token`、`refresh_token`；前端把 access token 放入 `Authorization: Bearer <access_token>`。
- access token 过期时，前端用 refresh token 调用 `POST /api/auth/refresh`，刷新失败后跳转登录页。
- SSE 进度流使用 `EventSource('/api/jobs/{job_id}/stream')`；下载和预览产物使用普通链接。

### 前端当前实际调用的接口

Auth：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/refresh`

Dashboard：

- `GET /api/dashboard/summary`

Template：

- `GET /api/templates`
- `POST /api/templates`
- `GET /api/templates/{template_id}`

Job：

- `GET /api/jobs`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/run-full`
- `POST /api/jobs/{job_id}/run-from`
- `POST /api/jobs/{job_id}/run-node`
- `POST /api/jobs/{job_id}/pause`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}/events`
- `GET /api/jobs/{job_id}/stream`

`GET /api/jobs` 返回：

```json
{
  "jobs": [],
  "total": 0,
  "page": 1,
  "perPage": 20
}
```

`GET /api/jobs/{job_id}` 返回后端详情结构：

```json
{
  "job": {},
  "node_runs": [],
  "total_nodes": 12,
  "completed_nodes": 0,
  "nodes": [],
  "artifacts": [],
  "error_summary": null,
  "recent_events": []
}
```

Prompt：

- `POST /api/templates/{template_id}/prompts`
- `GET /api/templates/{template_id}/prompts/{prompt_type}/versions`
- `GET /api/templates/{template_id}/prompts/{prompt_type}/active`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/activate`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/rollback`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/activate`，请求体 `{ "version": "v1.0" }`
- `POST /api/templates/{template_id}/prompts/{prompt_type}/rollback`，请求体 `{ "version": "v1.0" }`

Model：

- `GET /api/models`
- `GET /api/models/{model_id}`
- `POST /api/models`
- `PUT /api/models/{model_id}`
- `POST /api/models/{model_id}/enable`
- `POST /api/models/{model_id}/disable`

模型对象同时返回 `model_id/model_key` 和 `display_name/name`，用于兼容前端列表和详情页。

Workflow：

- `GET /api/workflow/nodes`
- `POST /api/workflow/nodes/{node_key}/enable`
- `POST /api/workflow/nodes/{node_key}/disable`
- `PUT /api/workflow/nodes/{node_key}/config`
- `POST /api/workflow/validate-run`

Artifact / Upload：

- `GET /api/jobs/{job_id}/artifacts`
- `GET /api/artifacts/{artifact_id}/download`
- `GET /api/artifacts/{artifact_id}/preview`
- `POST /api/jobs/{job_id}/uploads/reference-images`

创建 Job 时，Vue 前端会把分支开关转换为节点列表，例如 `i2v=false` 会发送 `disabled_nodes: ["submit_i2v", "poll_i2v"]`。后端也兼容 `{ "i2v": false }` 这种分支布尔对象。

详细前端工程说明见 [frontend-vue/README.md](../frontend-vue/README.md)。

## 2026-05 Workflow / Prompt / DeepSeek 对接说明

### Workflow 主路径

当前默认主路径为：

```text
reverse_prompts
  -> rewrite_prompts
  -> submit_first_frame_image
  -> poll_first_frame_image
  -> submit_i2v
  -> poll_i2v
  -> export_manifest
```

`reverse_prompts` 只生成 `t2v`。`rewrite_prompts` 只生成 `first_frame_image` 与 `i2v`。新增 `reverse_prompts4r2v` 负责把 `t2v` 改写为 `r2v_flash`。前端 Workflow 连线以 `/api/workflow/nodes` 返回的 `depends_on` 为准。

可选分支：

```text
reverse_prompts -> submit_t2v -> poll_t2v
reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash
```

禁止再出现这些旧链路：

```text
reverse_prompts -> submit_first_frame_image
reverse_prompts -> submit_i2v
rewrite_prompts -> submit_r2v_flash
```

新增/强化的非法配置会返回 `DEPENDENCY_MISSING`：

- `submit_first_frame_image` 启用但 `rewrite_prompts` 禁用，且没有提供 `first_frame_image` prompt。
- `submit_i2v` 启用但 `rewrite_prompts` 禁用，且没有提供 `i2v` prompt。
- `submit_i2v` 启用但没有 `poll_first_frame_image`，且没有已有 `first_frame_image` artifact。
- `submit_r2v_flash` 启用但 `reverse_prompts4r2v` 禁用，且没有提供 `r2v_flash` prompt。
- 任意 `poll_xx` 启用但对应 `submit_xx` 禁用。

### Prompt 文件来源

- `reverse_prompts` 使用 `factory_prompts/video_understanding_system.md`，内容来自根目录 `五段式提示词模版.md`，旧 `video_understanding_user` 不再参与该节点执行。
- `rewrite_prompts` 使用 `factory_prompts/prompt_rewrite_system.md`，内容来自根目录 `文生视频提示词改写.md`，旧 `prompt_rewrite_user` 不再参与该节点执行。
- `reverse_prompts4r2v` 使用 `factory_prompts/reverse_prompts4r2v_system.md`。
- 旧 user prompt 类型仍可在 Prompt Manager 中保留，用于历史数据兼容。

### Prompt 显示规则

`GET /api/templates/{template_id}/prompts` 现在返回 Prompt Manager 可见资产：

- Template 级系统 Prompt，例如 `video_understanding_*`、`prompt_rewrite_*`、`failure_agent_*`。
- Template 级手动、导入、回滚 Prompt。
- Job 级 `PromptVersion`。
- Job 运行时写入的 `job_prompt_refs` 快照，返回为只读版本记录，`source=job_snapshot`。

当带 `job_id` 查询时，接口同时返回当前 Job 的 Prompt 和 Template 级系统 Prompt，避免前端只显示 `No prompts for this job yet`。

### DeepSeek 模型配置

默认模型库包含：

```json
{
  "model_id": "deepseek-v4-flash",
  "display_name": "DeepSeek V4 Flash",
  "provider": "deepseek",
  "task_type": "text_to_text",
  "adapter_name": "qwen_chat",
  "default_params": {"temperature": 0.7}
}
```

配置项：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_OPENAI_BASE_URL=https://api.deepseek.com/v1
DEFAULT_PROMPT_REWRITE_MODEL=deepseek-v4-flash
```

`rewrite_prompts` 和 `reverse_prompts4r2v` 节点的模型选择会同时展示 `prompt_rewrite` 与 `text_to_text` 模型，因此可以选择 `deepseek-v4-flash`；旧 Qwen 模型仍保留。
## 2026-06 I2I Test Workflow Alignment

This backend implements I2I Test as a real image-to-image then image-to-video branch. The test I2V step no longer uses the original test image directly.

Implemented workflow paths:

```text
Main path:
reverse_prompts -> rewrite_prompts -> submit_first_frame_image -> poll_first_frame_image -> submit_i2v -> poll_i2v -> export_manifest

Core prompt path:
reverse_prompts -> rewrite_prompts -> rewrite_t2i_to_i2i -> export_manifest

I2I test path:
reverse_prompts -> rewrite_prompts -> rewrite_t2i_to_i2i -> prepare_i2i_test_batch -> submit_i2i_test_image -> poll_i2i_test_image -> submit_i2i_test_i2v -> poll_i2i_test_i2v -> export_manifest

T2V branch:
reverse_prompts -> submit_t2v -> poll_t2v -> export_manifest

R2V branch:
reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash -> export_manifest
```

Implemented I2I Test nodes returned by `GET /api/workflow/nodes`:
- `rewrite_t2i_to_i2i`
- `prepare_i2i_test_batch`
- `submit_i2i_test_image`
- `poll_i2i_test_image`
- `submit_i2i_test_i2v`
- `poll_i2i_test_i2v`

Model routing rules:
- Main I2V reads `job_config.models.main_i2v`; old `job_config.models.i2v` is only a main-path compatibility alias.
- I2I Test first-frame image generation reads `job_config.models.i2i_test_image` or `job_config.i2i_test.image_model`.
- I2I Test video generation reads `job_config.models.i2i_test_i2v` or `job_config.i2i_test.i2v_model`.
- Test image generation never falls back to the main first-frame image model, and test I2V never falls back to `models.main_i2v`.

Job config example:

```json
{
  "models": {
    "main_i2v": "wan2.7-i2v",
    "i2i_test_image": "wan2.7-image",
    "i2i_test_i2v": "wan2.6-i2v-flash"
  },
  "i2i_test": {
    "enabled": true,
    "mode": "couple",
    "test_count": 3,
    "male_dataset_dir": "workspace/personas/male",
    "female_dataset_dir": "workspace/personas/female",
    "image_model": "wan2.7-image",
    "i2v_model": "wan2.6-i2v-flash"
  }
}
```

I2I Test artifacts:
- `i2i_test_source_image`
- `i2i_test_first_frame_image`
- `i2i_test_video`

All primary test artifacts use `branch_key=i2i_test`. Process files such as `request_payload.json`, `response.json`, and `task_meta.json` remain available but are sorted behind images, videos, prompts, and manifest-level outputs.

Validation behavior:
- `poll_i2i_test_image` requires `submit_i2i_test_image`.
- `poll_i2i_test_i2v` requires `submit_i2i_test_i2v`.
- `submit_i2i_test_image` requires an `i2i` prompt and an `i2i_test_batch`.
- `submit_i2i_test_i2v` requires an `i2v` prompt, an `i2i_test_batch`, and an `i2i_test_first_frame_image` artifact generated by `poll_i2i_test_image` or supplied as an initial artifact.
- `prepare_i2i_test_batch` requires `rewrite_t2i_to_i2i` or a provided `i2i` prompt.
- Invalid submit/poll combinations return `DEPENDENCY_MISSING`; missing manual inputs return `MISSING_INPUT`.
- `export_manifest` depends on `poll_i2v`, `poll_i2i_test_i2v`, `poll_t2v`, and `poll_r2v_flash`. Disabled branches are skipped at runtime; enabled optional branches must finish before manifest export.
- `GET /api/workflow/nodes` returns `description_zh` and `description_en` for every default node.
- `POST /api/models/deduplicate` disables legacy display-name alias rows and keeps canonical `model_id` options such as `wan2.7-image` and `wan2.6-i2v-flash`.

## 2026-06 Workflow Required Inputs Validation

`POST /api/workflow/validate-run` calculates missing manual inputs from the complete selected node set:

```text
manual_inputs = all_selected_required_inputs - all_selected_generated_outputs - provided_initial_inputs
```

This means a prompt or artifact is only treated as generated when its generating node is enabled in the current workflow selection.

Example:

```text
Selected nodes:
rewrite_t2i_to_i2i
prepare_i2i_test_batch
submit_i2i_test_image
poll_i2i_test_image
submit_i2i_test_i2v
poll_i2i_test_i2v

Required manual inputs:
prompt:first_frame_image
prompt:i2v
```

If `rewrite_prompts` is also selected, `prompt:first_frame_image` and `prompt:i2v` are generated during the same run. If `poll_i2i_test_image` is not selected, `submit_i2i_test_i2v` must receive an existing `i2i_test_first_frame_image` artifact.

## 2026-06 PromptVersion Job Scope

Prompt versions are now scoped as prompt assets:

```text
template -> optional job -> prompt_type -> prompt_key -> version
```

The database no longer treats `template_id + prompt_type + version` as globally unique. Job-level prompts use the unique key:

```text
job_id + prompt_type + prompt_key + version
```

This allows different Jobs under the same Template to each own `i2v/default/v1.0`, `t2v/default/v1.0`, or `i2i/default/v1.0` without duplicate-key failures. Within the same Job, the same `prompt_type + prompt_key + version` is still rejected.

Operational notes:
- `JobService._write_initial_prompts()` creates Job-level `PromptVersion` rows by passing the external `job.job_id`.
- `job_prompt_refs` snapshots also store `prompt_key` and use `job_id + prompt_type + prompt_key + version`.
- `GET /api/templates/{template_id}/prompts?job_id={job_id}` returns Template-level prompts plus the selected Job's prompt versions and snapshots.
- Existing local databases can be repaired with `flask --app run.py repair-schema`; app startup also runs this compatibility repair when `AUTO_REPAIR_SCHEMA=true`.

## 2026-06 Quick Start / Manifest / Model Naming Fixes

Latest backend behavior:
- `export_manifest.depends_on` includes `poll_i2v`, `poll_i2i_test_i2v`, `poll_t2v`, and `poll_r2v_flash`.
- Disabled optional branches are skipped by runtime dependency checks, so Manifest can still run when T2V/R2V are disabled.
- Enabled T2V/R2V branches must finish before Manifest export, and their artifacts are included in the Manifest artifact list.
- `submit_r2v_flash` requires `prompt:r2v_flash`; `reference_images` are optional. Uploaded reference images are used first. If none are uploaded, the backend samples local images from `R2V_REFERENCE_IMAGE_DIRS` and registers them as `reference_image` artifacts for reproducibility.
- `GET /api/workflow/nodes` includes `description_zh` and `description_en` for every default workflow node.
- Model defaults use canonical ids such as `wan2.7-image` and `wan2.6-i2v-flash`; display-name aliases are hidden from list results.
- `POST /api/models/deduplicate` can be used to disable legacy alias rows already present in a local database.

## 2026-06 Same-Job DAG Parallel Scheduler

`run-full` and `run-from` now use a same-Job DAG scheduler by default. The external API is unchanged, but nodes whose `depends_on` are satisfied can run in parallel within the same Job.

Configuration:

```env
WORKFLOW_PARALLEL_ENABLED=true
WORKFLOW_MAX_PARALLEL_NODES=4
WORKFLOW_MAX_PARALLEL_POLLS=2
```

Behavior notes:
- `run-node` remains single-node execution.
- `WORKFLOW_PARALLEL_ENABLED=false` falls back to the old serial scheduler.
- Poll nodes still use blocking polling in this phase, but `WORKFLOW_MAX_PARALLEL_POLLS` limits how many poll nodes can occupy worker threads at once.
- `Job.current_node` may contain comma-separated node keys while multiple nodes are running, or `parallel:<count>` if the list is too long.

Failure tolerance:

```env
FAILURE_AGENT_ENABLED=true
FAILURE_AGENT_MAX_RETRIES=1
```

- When a node fails, the Failure Agent is invoked as a decision hook, not as a normal workflow dependency.
- Deterministic configuration/input errors are not retried. Retryable model/API failures are capped at 1 retry by default and 2 by hard limit.
- A failed optional branch can become `path_failed`; unrelated branches continue. If at least one deliverable video artifact exists, the Job can finish as `partial_success`.
- Node statuses may include `retrying` and `path_failed` in addition to the original `pending/running/success/failed/skipped` values.

## 2026-06 Prompt Manager UX / Job Package

Prompt Manager now supports type-first filtering through a global list endpoint:

```http
GET /api/prompts?series_id=&template_id=&job_id=&prompt_type=&prompt_key=&scope=
```

Behavior:
- `prompt_type` can be selected without selecting Series, Template, or Job.
- `prompt_key` is optional. If omitted, all keys for the selected type are returned.
- `scope=template`, `scope=job`, and `scope=job_snapshot` can narrow the result set.
- When `job_id` is provided, the API returns Template-level prompts for that Job's Template plus that Job's PromptVersion rows and `job_prompt_refs` snapshots.
- System/legacy prompts are still returned; the Vue page groups them under the advanced/system section.

Response:

```json
{
  "success": true,
  "data": {
    "prompts": [],
    "total": 0
  }
}
```

Job one-click package is implemented as:

```http
POST /api/jobs/{job_id}/package
```

The backend generates or refreshes a single latest package artifact:

```text
storage/jobs/{job_id}/packages/job_{job_id}_package.zip
```

The package Artifact uses:
- `artifact_type=job_package`
- `branch_key=package`
- `mime_type=application/zip`
- `file_name=job_{job_id}_package.zip`

The package includes only deliverable material:
- `final/`: best final video by priority `i2v_video > t2v_video > i2i_test_video > r2v_flash_video`.
- `assets/`: key image assets such as `first_frame_image`, `i2i_test_source_image`, `i2i_test_first_frame_image`, and `reference_image`.
- individual prompt Markdown files such as `prompts/i2v.md`, `prompts/i2i.md`, or `prompts/r2v_flash.md`, plus `prompts/prompts.json`.
- `package_manifest.json`.

Excluded process artifacts include `request_payload`, `api_response`, `task_meta`, `raw_response`, `manifest`, and `i2i_test_batch`.

If no final video exists but key images or job prompt snapshots exist, the package is returned with `package_status=partial`. If nothing useful can be packaged, the API returns:

```json
{
  "success": false,
  "error": {
    "code": "NO_PACKABLE_CONTENT",
    "message": "No packable video, image, or job prompt snapshot was found for this job"
  }
}
```

Successful response:

```json
{
  "success": true,
  "data": {
    "artifact": {},
    "download_url": "/api/artifacts/{artifact_id}/download",
    "package_status": "full",
    "included_counts": {
      "videos": 1,
      "images": 2,
      "prompts": 4
    }
  }
}
```

Latest package selection correction:
- I2V main path packages `i2v_video`, the matching `first_frame_image` artifact, and only the `i2v` prompt.
- If `rewrite_t2i_to_i2i` succeeded or I2I Test outputs exist, the package also includes `i2i_test_video`, `i2i_test_source_image`, `i2i_test_first_frame_image`, and the `i2i` prompt.
- R2V prompts and reference images are included only for R2V-only jobs, where no I2V, I2I, or T2V deliverable exists.
- T2V-only jobs can package `t2v_video`, but no `t2v` prompt is included.
- System prompts, legacy user prompts, `first_frame_image` prompts, `t2v` prompts, `negative` prompts, and process/debug JSON are excluded.
- `package_manifest.json` records `included_prompt_types`, `included_video_artifact_ids`, and `included_image_artifact_ids`.

Prompt edit is implemented as immutable version creation:

```http
POST /api/templates/{template_id}/prompts/{prompt_type}/versions/{version}/edit
```

The endpoint creates a new `PromptVersion` with `source=edit` and `parent_version` pointing to the edited version. It does not overwrite the old version.

## 2026-06 Template Package / Redis Assessment

Template package is implemented as a minimal production handoff ZIP. It does not use the `artifacts` table because `artifacts.job_id` is job-scoped and non-null.

Endpoints:

```text
POST /api/templates/{template_id}/package
GET  /api/templates/{template_id}/package/download
```

The backend writes one latest package file:

```text
storage/templates/{template_id}/packages/template_{template_id}_package.zip
```

The ZIP contains only the prompt/video assets needed for production use:

- `prompts/i2i.md` when an I2I prompt can be resolved.
- `prompts/i2v.md` when an I2V prompt can be resolved.
- `prompts/r2v.md` only when neither I2I nor I2V prompt can be resolved.
- `video/{artifact_type}_{artifact_id}_{file_name}` for the best generated video across this template's jobs.
- `package_manifest.json`

Prompt resolution ignores old template-level business mocks with `source=factory_prompts`. It prefers synced template business prompts, then falls back to the latest usable Job-level PromptVersion or JobPromptRef snapshot from this template. Video priority is `i2v_video > t2v_video > i2i_test_video > r2v_flash_video/r2v_flash_videos`. A template with no packable prompt and no video returns `NO_TEMPLATE_PACKABLE_CONTENT`.

## 2026-06 Template Business Prompt Sync

Template creation still seeds system prompts from `factory_prompts/`, because these prompts are required by workflow nodes. It no longer creates default business mock prompts for `t2v`, `first_frame_image`, `i2v`, `i2i`, `r2v_flash`, or `negative`.

Job-level business prompts are now the source of truth. When a Job creates, edits, rolls back, activates, or workflow-generates a business prompt, the backend creates a new template-level copy with `source=synced_from_job` and marks it active for the same `prompt_type + prompt_key`. Existing template versions are preserved for history. The sync event is recorded as `TEMPLATE_PROMPT_SYNCED`.

Runtime prompt lookup remains Job-first for business prompts. If a Job has no active prompt, the backend may fall back to a usable template prompt, but old factory business mocks are ignored and do not satisfy workflow validation or template packaging.

Redis is not introduced in this phase. The current process-local `JobQueueService` is suitable for single-machine practice. Redis/RQ/Celery would be a medium-difficulty production upgrade: it improves queue durability, crash recovery, multi-process worker safety, and throughput across many jobs, but it will not significantly shorten a single job because the dominant latency comes from remote DashScope/Qwen model tasks and polling.
