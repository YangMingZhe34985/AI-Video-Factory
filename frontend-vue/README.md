# AI Video Factory — Frontend (Vue 3 + Vite)

基于 Vue 3 + Vite 的工程化 SPA 前端，为 AI Video Factory 提供完整的 Web 管理界面。

## 技术栈

| 层 | 技术 |
|------|------|
| 框架 | Vue 3.4+ (Composition API + `<script setup>`) |
| 构建 | Vite 5 |
| 路由 | Vue Router 4 |
| 状态管理 | Pinia 2 + pinia-plugin-persistedstate |
| HTTP | Axios 1.7 |
| UI 样式 | TailwindCSS 3 |
| 图标 | @phosphor-icons/vue 2 |
| 国际化 | vue-i18n 9 |

## 快速启动

```bash
cd frontend-vue
npm install
npm run dev
```

开发服务器默认运行在 `http://localhost:5173`，`/api` 请求自动代理到 `http://127.0.0.1:5000`。

生产构建：

```bash
npm run build     # 输出到 dist/
npm run preview   # 预览生产构建
```

## 目录结构

```
frontend-vue/
├── index.html
├── package.json
├── vite.config.js              # Vite 配置 + API 代理
├── tailwind.config.js          # TailwindCSS 自定义颜色/字体
├── postcss.config.js
└── src/
    ├── main.js                 # 入口：挂载 Vue、Pinia、Router
    ├── App.vue                 # 根组件（router-view）
    ├── api/                    # Axios 请求模块
    │   ├── request.js          # Axios 实例 + JWT 拦截器
    │   ├── auth.js             # 认证 API
    │   ├── jobs.js             # 作业 API
    │   ├── workflow.js         # 工作流节点 API
    │   ├── models.js           # 模型注册表 API
    │   ├── prompts.js          # 提示词 API
    │   ├── templates.js        # 模板 API
    │   ├── artifacts.js        # 工件 API
    │   └── dashboard.js        # 仪表板 API
    ├── stores/                 # Pinia 状态管理
    │   ├── auth.js             # 认证（localStorage 持久化）
    │   ├── settings.js         # 设置（暗色模式、语言、紧凑模式）
    │   ├── toast.js            # Toast 通知
    │   ├── dashboard.js        # 仪表板
    │   ├── jobs.js             # 作业
    │   ├── workflow.js         # 工作流节点
    │   ├── models.js           # 模型
    │   ├── prompts.js          # 提示词
    │   └── templates.js        # 模板
    ├── composables/            # 组合式函数
    │   ├── useAuth.js          # 认证相关
    │   ├── useToast.js         # Toast 快捷方法
    │   └── useSSE.js           # SSE 事件流
    ├── i18n/                  # 国际化
    │   ├── index.js            # vue-i18n 实例配置
    │   └── locales/
    │       ├── en.json         # 英文翻译 (~200+ keys)
    │       └── zh.json         # 中文翻译
    ├── components/
    │   ├── layout/             # 布局组件
    │   │   ├── AppLayout.vue   # 整体布局（Sidebar + Main + Toast）
    │   │   ├── AppSidebar.vue  # 侧边栏导航 + API 状态
    │   │   └── AppHeader.vue   # 页头（标题 + 搜索 + 通知）
    │   ├── common/             # 通用组件
    │   │   ├── StatCard.vue
    │   │   ├── StatusBadge.vue
    │   │   ├── ToggleSwitch.vue
    │   │   ├── ToastContainer.vue
    │   │   ├── LoadingSpinner.vue
    │   │   ├── EmptyState.vue
    │   │   ├── Pagination.vue
    │   │   └── SearchInput.vue
    │   └── jobs/
    │       └── JobProgressBar.vue
    ├── layouts/
    │   └── DefaultLayout.vue   # 默认页面布局（Layout + Header + Content）
    ├── router/
    │   └── index.js            # Vue Router 路由定义 + 导航守卫
    ├── styles/
    │   └── main.css            # 全局样式 + Tailwind 指令
    ├── utils/
    │   ├── format.js           # 日期格式化、状态颜色
    │   └── constants.js        # 分支颜色、导航项、标签常量
    └── views/                  # 页面视图
        ├── LoginView.vue       # 登录/注册（粒子动画背景）
        ├── DashboardView.vue   # 仪表板（可点击统计卡片跳转 + 快速启动向导 + 最近任务）
        ├── JobsView.vue        # 作业列表（状态卡片筛选、搜索、分页、运行控制）
        ├── JobCreateView.vue   # 旧创建页文件保留；路由已重定向到 Jobs
        ├── JobDetailView.vue   # 作业详情（进度、SSE 事件、节点状态、工件、复制 ID）
        ├── WorkflowNodesView.vue  # 工作流节点画布（动态 SVG 连线）
        ├── TemplatesView.vue   # 模板列表（搜索、分页、创建模板对话框（系列名+模板名））
        ├── PromptManagerView.vue  # 提示词版本管理（创建、激活、回滚）
        ├── ModelRegistryView.vue  # 模型注册表（启用/禁用切换）
        ├── ArtifactsView.vue   # 工件浏览（按 Job 筛选、下载、预览）
        ├── SettingsView.vue    # 系统设置（语言切换 EN/ZH、暗色模式、紧凑模式、API 配置）
        └── NotFoundView.vue    # 404 页面
```

## 路由表

| 路径 | 视图 | 说明 |
|------|------|------|
| `/login` | LoginView | 登录/注册，guest only |
| `/` | — | 重定向到 `/dashboard` |
| `/dashboard` | DashboardView | 仪表板主页，统计卡片可点击跳转对应页面 |
| `/templates` | TemplatesView | 模板列表，支持搜索、分页、创建模板（系列名+模板名） |
| `/prompts` | PromptManagerView | 提示词管理器（选择模板+类型 → 查看/创建/激活/回滚版本） |
| `/models` | ModelRegistryView | 模型注册表（启用/禁用切换） |
| `/jobs` | JobsView | 作业列表（状态卡片筛选、搜索、分页、运行/暂停/取消） |
| `/jobs/create` | redirect | 重定向到 `/jobs`；创建作业由页面内嵌 `WorkflowJobWizard` 完成 |
| `/jobs/:jobId` | JobDetailView | 作业详情 + SSE 实时事件 + 复制 ID |
| `/workflow` | WorkflowNodesView | 工作流节点画布（动态 SVG 连线） |
| `/artifacts` | ArtifactsView | 工件浏览（按 Job 筛选、下载、预览） |
| `/settings` | SettingsView | 系统设置（语言切换 EN/ZH、暗色模式、紧凑模式、API 配置） |
| `/:pathMatch(.*)*` | NotFoundView | 404 |

**导航守卫**：未登录 → `/login`；已登录访问 `/login` → `/dashboard`。

## 调用的后端 API

所有请求由 Axios 统一封装（`src/api/request.js`），自动附加 `Authorization: Bearer <token>`，401 时自动刷新 token。

### 认证 (Auth)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `POST` | `/api/auth/register` | LoginView（注册表单） |
| `POST` | `/api/auth/login` | LoginView（登录表单） |
| `GET` | `/api/auth/me` | authStore.fetchUser() |
| `POST` | `/api/auth/refresh` | request.js 拦截器（自动刷新 token） |

### 仪表板 (Dashboard)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/dashboard/summary` | DashboardView（统计卡片数据） |
| `GET` | `/api/health` | AppSidebar（API 状态指示） |

### 模板 (Templates)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/templates` | TemplatesView、WorkflowJobWizard、PromptManagerView |
| `GET` | `/api/templates/:id` | templateStore.fetchTemplate() |
| `POST` | `/api/templates` | templateStore.createTemplate() |
| `POST` | `/api/templates/:id/package` | TemplatesView template package action |
| `GET` | `/api/templates/:id/package/download` | TemplatesView template package download |

### 作业 (Jobs)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/jobs` | JobsView（列表）、DashboardView（最近任务） |
| `GET` | `/api/jobs/:jobId` | JobDetailView（作业详情） |
| `POST` | `/api/jobs` | WorkflowJobWizard（创建作业） |
| `POST` | `/api/jobs/:jobId/run-full` | JobsView、JobDetailView |
| `POST` | `/api/jobs/:jobId/run-from` | 节点详情面板 |
| `POST` | `/api/jobs/:jobId/run-node` | 节点详情面板 |
| `POST` | `/api/jobs/:jobId/pause` | JobsView、JobDetailView |
| `POST` | `/api/jobs/:jobId/cancel` | JobsView、JobDetailView |
| `GET` | `/api/jobs/:jobId/events` | JobDetailView（历史事件加载） |
| `GET` | `/api/jobs/:jobId/stream` | JobDetailView（SSE 实时事件流） |

### 工作流节点 (Workflow)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/workflow/nodes` | WorkflowNodesView（节点画布） |
| `POST` | `/api/workflow/nodes/:key/enable` | WorkflowNodesView（启用节点） |
| `POST` | `/api/workflow/nodes/:key/disable` | WorkflowNodesView（禁用节点） |

### 提示词 (Prompts)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/templates/:id/prompts/:type/versions` | PromptManagerView |
| `GET` | `/api/templates/:id/prompts/:type/active` | PromptManagerView |
| `POST` | `/api/templates/:id/prompts` | 创建新版本 |
| `POST` | `/api/templates/:id/prompts/:type/activate` | PromptManagerView（激活版本） |
| `POST` | `/api/templates/:id/prompts/:type/rollback` | PromptManagerView（回滚版本） |

### 模型 (Models)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/models` | ModelRegistryView |
| `GET` | `/api/models/:id` | modelStore.fetchModel() |
| `POST` | `/api/models` | 新增模型 |
| `PUT` | `/api/models/:id` | 编辑模型 |
| `POST` | `/api/models/:id/enable` | ModelRegistryView |
| `POST` | `/api/models/:id/disable` | ModelRegistryView |

### 工件 (Artifacts)

| 方法 | 路径 | 前端调用位置 |
|------|------|-------------|
| `GET` | `/api/jobs/:jobId/artifacts` | JobDetailView、ArtifactsView |
| `GET` | `/api/artifacts/:id/download` | 工件下载链接 |
| `GET` | `/api/artifacts/:id/preview` | 工件预览链接 |

## 统一响应格式

```json
{"success": true, "data": {}}
```

错误：
```json
{"success": false, "error": {"code": "JOB_NOT_FOUND", "message": "Job not found"}}
```

## 架构说明

### JWT 认证流程

1. 用户登录/注册 → 后端返回 `access_token` + `refresh_token`
2. AuthStore 持久化到 localStorage（`pinia-plugin-persistedstate`）
3. Axios 请求拦截器自动附加 `Authorization: Bearer <access_token>`
4. 401 响应拦截器自动用 `refresh_token` 换取新 `access_token`
5. 刷新失败 → 清除 token → 跳转登录页

### SSE 实时事件

JobDetailView 在作业运行中时，通过原生 `EventSource` 连接 `/api/jobs/:jobId/stream`，实时展示工作流事件。2 分钟无事件后自动关闭。

### WorkflowNodes SVG 画布

节点按 Core / T2V / First Frame / I2I Test / R2V / I2V 等分支分列排布，SVG 连线根据 `depends_on` 动态绘制，颜色编码对应分支。

### 页面交互功能

各页面已实现的交互功能：

| 页面 | 交互功能 |
|------|---------|
| **Dashboard** | 6 个统计卡片可点击跳转（Templates → `/templates`，Jobs → `/jobs`，按状态筛选 → `/jobs?status=running` 等）；Quick Start 打开共享 `WorkflowJobWizard`；复制 Job ID 到剪贴板 |
| **Jobs** | 状态统计卡片可点击筛选对应状态的作业；复制 Job ID 到剪贴板；运行/暂停/取消按钮控制作业生命周期 |
| **Templates** | 搜索框实时过滤模板；分页组件支持翻页；"Create Template" 按钮打开创建对话框（系列名称 + 模板名称 + 描述）；View Details 跳转到提示词管理；Create Job 打开共享 `WorkflowJobWizard` |
| **Prompt Manager** | 选择模板和提示词类型后加载版本列表；激活/回滚版本；"+ New Version" 打开创建对话框（标题、内容、备注） |
| **Model Registry** | 搜索框实时过滤模型；ToggleSwitch 启用/禁用模型 |
| **Workflow Nodes** | 点击节点卡片选中并查看详情；ToggleSwitch + 按钮启用/禁用节点；SVG 连线实时更新 |
| **Artifacts** | 选择 Job 后加载对应工件列表；搜索框实时过滤；下载/预览按钮 |
| **AppHeader** | 全局搜索框（回车跳转到 `/jobs?search=xxx`）；通知铃铛和帮助图标（Toast 提示） |
| **Settings** | 语言切换（English / 中文）；暗色模式开关（`.dark` class + Tailwind dark 变体）；紧凑模式；API 配置 |

### 国际化 (i18n)

全站支持中英文切换，通过 vue-i18n 实现：

- 翻译文件位于 `src/i18n/locales/`，包含 200+ 翻译键，覆盖所有页面
- 默认语言为英文，用户可在 Settings 页面切换为中文
- 语言偏好通过 `settingsStore` 持久化到 localStorage
- 所有页面视图、布局组件（Sidebar、Header）、按钮文本、Toast 消息均已国际化

### 暗色模式

通过 TailwindCSS `darkMode: 'class'` 实现：

- `settingsStore` 统一管理暗色模式状态，切换时在 `<html>` 上添加/移除 `dark` class
- `main.css` 提供全局暗色覆盖（`.dark .bg-white` → `#1e293b` 等）
- 各页面组件使用 `dark:` 前缀适配暗色模式下的样式
- 设置页面的 Dark Mode 开关实时生效并持久化

### API 代理

开发环境由 Vite 将 `/api/*` 代理到 `http://127.0.0.1:5000`。生产环境建议通过 nginx 反向代理。

## 与后端对应的页面

| 前端视图 | 后端 Blueprint | 说明 |
|---------|---------------|------|
| LoginView | `auth` | JWT 登录/注册 |
| DashboardView | `dashboard` + `jobs` | 统计摘要 + 最近任务 |
| JobsView | `jobs` | 作业 CRUD + 运行控制 |
| WorkflowJobWizard | `jobs` + `templates` + `workflow` + `models` | Dashboard / Jobs / Templates / Workflow 共用创建作业 |
| JobDetailView | `jobs` + `artifacts` + SSE | 详情 + 工件 + 实时事件 |
| WorkflowNodesView | `workflow` | 节点画布 + 启用/禁用 |
| TemplatesView | `templates` | 模板列表 |
| PromptManagerView | `templates/*/prompts` | 提示词版本管理 |
| ModelRegistryView | `models` | 模型 CRUD + 开关 |
| ArtifactsView | `artifacts` | 工件浏览/下载/预览 |
| SettingsView | — | 前端本地设置 |

## 2026-05 Workflow / Prompt / Model 对齐说明

### Workflow 页面

WorkflowNodesView 的 SVG 连线只使用后端 `/api/workflow/nodes` 返回的 `depends_on` 生成。当前主路径应显示为：

```text
reverse_prompts -> rewrite_prompts -> submit_first_frame_image -> poll_first_frame_image -> submit_i2v -> poll_i2v -> export_manifest
```

可选分支应显示为：

```text
reverse_prompts -> submit_t2v -> poll_t2v
reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash
```

页面不应显示 `reverse_prompts -> submit_first_frame_image` 或 `rewrite_prompts -> submit_r2v_flash` 的直接连线。创建 Job 前调用 `POST /api/workflow/validate-run` 校验节点选择，后端会拒绝非法组合并返回 `DEPENDENCY_MISSING`。

### Prompt Manager 页面

PromptManagerView 使用 `GET /api/templates/{template_id}/prompts` 作为统一列表接口。

- 只选择 Template：显示该 Template 下全部 Template 级 Prompt，包括系统 Prompt、手动 Prompt、导入 Prompt 和回滚 Prompt。
- 选择 Template + Job：显示当前 Job 的 Prompt、Job 运行时保存的 `job_prompt_refs` 快照，以及 Template 级系统 Prompt。
- Job 快照版本会以 `source=job_snapshot`、`read_only=true` 返回，前端只展示和预览，不显示 activate / rollback 操作。
- Prompt 类型包含 `t2v`、`first_frame_image`、`i2v`、`r2v_flash` 和 `reverse_prompts4r2v_system`，旧 user prompt 类型保留用于历史兼容。

### Model Registry 与 DeepSeek

后端默认模型库包含 `deepseek-v4-flash`。该模型的 `task_type` 是 `text_to_text`，复用 OpenAI-compatible chat adapter。

WorkflowNodesView 在 `rewrite_prompts` 与 `reverse_prompts4r2v` 节点详情面板中会同时加载 `prompt_rewrite` 和 `text_to_text` 模型，因此可以在模型下拉框中选择 `deepseek-v4-flash`。旧 Qwen 模型仍可继续选择。
## 2026-06 I2I Test Workflow UI Alignment

The Vue frontend now treats I2I Test as a separate workflow branch named `i2i_test`.

Workflow canvas:
- Connections are rendered only from backend `depends_on` returned by `GET /api/workflow/nodes`.
- The `i2i_test` lane displays:
  `rewrite_t2i_to_i2i -> prepare_i2i_test_batch -> submit_i2i_test_image -> poll_i2i_test_image -> submit_i2i_test_i2v -> poll_i2i_test_i2v`.
- The page must not draw a hardcoded shortcut from `reverse_prompts` to `submit_first_frame_image`.
- The page must not draw a hardcoded shortcut from `rewrite_prompts` to `submit_r2v_flash`.

Shared Job Wizard:
- Dashboard Quick Start, Jobs Create, Templates Create Job, and Workflow Create all use `WorkflowJobWizard`.
- Dashboard, Jobs, and Templates use quick business path selection.
- Workflow uses advanced node-level selection with backend validation.
- Quick business paths map to backend node keys before submitting `POST /api/jobs`.

I2I Test configuration:
- Test mode supports `single_male`, `single_female`, and `couple`.
- `single_male` and `single_female` map to `shot_type=single`; `couple` maps to `shot_type=multi`.
- Test count is configurable and defaults to 3.
- I2I Test image model is configured with `job_config.models.i2i_test_image` or `job_config.i2i_test.image_model`.
- I2I Test video model is configured with `job_config.models.i2i_test_i2v` or `job_config.i2i_test.i2v_model`.
- Main I2V remains `job_config.models.main_i2v`; the test branch does not reuse it implicitly.

JobDetailView:
- I2I Test results are grouped by `metadata.test_index`.
- Each group can show `i2i_test_source_image`, `i2i_test_first_frame_image`, and `i2i_test_video`.
- The video card reads `metadata.mode`, `metadata.source_images`, `metadata.i2i_first_frame_image`, and `metadata.i2i_first_frame_artifact_id` when present.

ArtifactsView:
- The branch filter includes `i2i_test`.
- Type filters include `i2i_test_source_image`, `i2i_test_first_frame_image`, and `i2i_test_video`.
- Main images/videos/prompts are sorted before process JSON files.

PromptManagerView:
- The visible prompt type list includes `i2i` and `rewrite_t2i_to_i2i_system`.
- Generated Job prompt snapshots remain read-only.

## 2026-06 Required Inputs UI

The frontend uses `POST /api/workflow/validate-run` to display manual inputs for the exact selected node set.

The backend returns inputs after subtracting only outputs generated by nodes selected in the current run. For example, selecting only:

```text
rewrite_t2i_to_i2i
prepare_i2i_test_batch
submit_i2i_test_image
poll_i2i_test_image
submit_i2i_test_i2v
poll_i2i_test_i2v
```

requires the user to provide:
- `prompt:first_frame_image` shown as `T2I / First Frame Image Prompt`
- `prompt:i2v` shown as `I2V Prompt`

When `rewrite_prompts` is also selected, `prompt:i2v` is generated and no duplicate manual I2V prompt is requested. When `rewrite_t2i_to_i2i` is not selected, the UI requests `prompt:i2i`.

If `poll_i2i_test_image` is not selected, the backend may request an existing `artifact:i2i_test_first_frame_image` before allowing `submit_i2i_test_i2v`.

## 2026-06 PromptVersion Job Scope

PromptManagerView uses `GET /api/templates/{template_id}/prompts` as the unified prompt list endpoint.

Filtering behavior:
- Template only: shows Template-level system/manual/imported/rollback prompts.
- Template + Job: shows Template-level prompts plus the selected Job's PromptVersion rows and `job_prompt_refs` snapshots.
- Job prompt snapshots are read-only and use `source=job_snapshot`.

Version behavior:
- Different Jobs can each show `i2v/default/v1.0` or `i2i/default/v1.0`.
- The frontend should not treat `version` alone as globally unique. Use `scope + job_id + prompt_type + prompt_key + version` when deriving UI keys.

## 2026-06 Quick Start / Workflow Display Fixes

Latest alignment:
- Dashboard Quick Start, Jobs Create, Templates Create Job, and Workflow Create all use `WorkflowJobWizard`.
- Source video input supports both drag-drop and clicking "Choose video file"; the selected file name, size, and MIME/extension are displayed.
- Reference Images use a separate multi-image upload input and are optional for R2V. If left empty, the backend samples local project images.
- I2I Test Configuration is validated as `mode + test_count + image_model + i2v_model`, not as Reference Images.
- T2V quick path is `reverse_prompts -> submit_t2v -> poll_t2v -> export_manifest`.
- R2V quick path is `reverse_prompts -> reverse_prompts4r2v -> submit_r2v_flash -> poll_r2v_flash -> export_manifest`.
- Workflow node cards show a short description, and the details panel shows backend `description_zh` or `description_en` according to locale.
- Model dropdowns deduplicate by canonical `model_id`; fallback defaults are only added when missing from the backend model list.

## 2026-06 Prompt Manager UX / Job Package

PromptManagerView no longer requires `Series -> Template -> Job -> Type -> Key` selection order.

Current filtering rules:
- Prompt Type is always selectable.
- Series, Template, Job, Type, and Key are independent filters.
- Selecting a type without selecting a key shows all prompt keys for that type.
- Selecting a Template without selecting a Job shows Template-level prompts.
- Selecting a Job shows Template-level prompts, Job-level PromptVersion rows, and Job prompt snapshots.
- Business prompts are shown first.
- System and legacy prompts are kept under the advanced/system collapsible section.

PromptManagerView now calls:

```http
GET /api/prompts
```

with optional query params:

```text
series_id
template_id
job_id
prompt_type
prompt_key
scope
```

The old Template-scoped prompt APIs are still used for create, activate, rollback, and compatibility.

JobDetailView now has a one-click package action:

```http
POST /api/jobs/{job_id}/package
```

On success the page shows a download link returned by the backend:

```json
{
  "artifact": {},
  "download_url": "/api/artifacts/{artifact_id}/download",
  "package_status": "full",
  "included_counts": {
    "videos": 1,
    "images": 2,
    "prompts": 4
  }
}
```

The download itself still uses the existing artifact download route:

```http
GET /api/artifacts/{artifact_id}/download
```

If the backend returns `NO_PACKABLE_CONTENT`, the UI displays the backend error message and does not create a download link.

Latest UI alignment:
- Job packages now include only path-relevant prompts: `i2v` for main I2V, `i2i` when the I2I rewrite/test path exists, and `r2v_flash` only for R2V-only jobs.
- System prompts, T2V prompts, first-frame/T2I prompts, negative prompts, request payloads, API responses, task metadata, raw responses, manifests, and I2I batch JSON are not displayed as package content.

## 2026-06 Template Package / Quick Start i18n

TemplatesView includes a `Package Template` action for each template. It calls:

```http
POST /api/templates/{template_id}/package
GET  /api/templates/{template_id}/package/download
```

The downloaded ZIP is a minimal production package. It includes `prompts/i2i.md` and `prompts/i2v.md` when available, or `prompts/r2v.md` as the fallback path, plus one best generated video and `package_manifest.json`.

WorkflowJobWizard route labels are now localized through `vue-i18n`. Chinese mode shows:

- `首帧图 + I2V 主路径`
- `核心提示词路径`
- `I2I 测试路径`
- `T2V 可选分支`
- `R2V / 工具分支`

The node chain text remains the original English `node_key` values because those are technical workflow identifiers.

Prompt edit UI remains:
- PromptManagerView version rows now expose an Edit action for non-read-only versions.
- Edit opens a full-screen two-column dialog with before/after content, text diff mode, Markdown preview mode, and "save as new version" behavior.
- Job prompt snapshots remain read-only and do not show the Edit action.
