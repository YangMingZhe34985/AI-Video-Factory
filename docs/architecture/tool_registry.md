# Tool Registry 与 Skill 层（Phase 1）

> CineCrew 多 Agent 升级第二阶段的交付物：把现有业务能力封装为带 Schema、权限、审批、预算和幂等约束的工具，供 Phase 2 的 LangGraph Agent 调用。
> 代码：`backend/app/skills/`、`backend/app/agent/`、`backend/app/api/skills.py`、`backend/app/models/tool_invocation.py`。

## 1. 定位与边界

- **工具层只做约束和编排，不做生成**。所有生成类工具都“基于 Job”（job-backed）：创建一个只启用所需节点的经典 Job，再交给原有 DAG 执行。生成、轮询、工件登记、断点续跑、打包全部复用现有实现。
- **`ToolRegistry.invoke()` 是唯一执行入口**。Agent（以及运维人员通过 REST）不能绕过它直接调用业务服务。
- **默认关闭**。`AGENT_MODE_ENABLED=false` 时不注册 `/api/skills`，经典模式完全不受影响。

```text
LangGraph Agent（Phase 2） / REST /api/skills（运维、调试）
                │
                ▼
ToolRegistry.invoke(name, input, ToolContext)
   ① 输入 Schema  ② 角色  ③ 审批  ④ 预算  ⑤ 幂等  ⑥ handler  ⑦ 输出 Schema → tool_invocations 账本
                │
                ▼
skills/tools/*  ──►  skills/job_backed.py（专用模板、节点启停、模型/参数钉定）
                │
                ▼
JobService.create_job  +  JobRunService.start   ──►   经典 19 节点 DAG（不改动）
```

## 2. 执行管线

| 步骤 | 实现 | 失败时 |
|---|---|---|
| ① 输入校验 | `input_model.model_validate`（pydantic v2，`extra="forbid"`） | `422 INVALID_INPUT`，不写账本 |
| ② 角色 | `ctx.role ∈ spec.allowed_roles` | `403 TOOL_FORBIDDEN`，不写账本 |
| ③ 审批 | 付费工具要求 `ctx.approved=True` | `403 APPROVAL_REQUIRED`，不写账本 |
| ④ 预算 | `BudgetGuard.check(budget_scope, limit, cost)` | `402 BUDGET_EXCEEDED`，账本记为 `rejected` |
| ⑤ 幂等 | 以 `idempotency_key` 查账本，见第 4 节 | 重放或进入重试 |
| ⑥ handler | 工具实现；不阻塞，生成类只负责建 Job 并入队 | 记 `failed` 或 `rejected`（见第 4 节） |
| ⑦ 输出校验 | `output_model.model_validate` | `500 TOOL_OUTPUT_INVALID` |

只读工具（`permission=read`，即 `get_task_status`）执行 ①②⑥⑦，不写账本、不计预算。

## 3. 工具清单

| 工具 | 允许角色 | 权限 | 审批 | 估算成本 | `max_wait_sec` | 重试 | 实现（启用的节点） | 产出 |
|---|---|---|---|---|---|---|---|---|
| `analyze_video` | creative, system | llm | — | 1 | 600 | 1 | `reverse_prompts`；源视频只接受工件 ID | `prompt:t2v` |
| `rewrite_prompt` | creative, system | llm | — | 每个节点 1 | 300 | 1 | `rewrite_prompts` 和/或 `reverse_prompts4r2v` | `prompt:first_frame_image`、`prompt:i2v`、`prompt:r2v_flash` |
| `generate_image` | production, system | generate | ✔ | 2 | 1200 | 1 | `submit/poll_first_frame_image` | `artifact:first_frame_image` |
| `generate_video` | production, system | generate | ✔ | 10 | 1200 | 1 | t2v / i2v / r2v 对应的 submit+poll；i2v 复用首帧工件，r2v 复用参考图工件 | `artifact:{t2v,i2v,r2v_flash}_video` |
| `produce_shot`（复合） | production, system | generate | ✔ | 12 | 1800 | 1 | 一个 Job 同时启用首帧与 i2v 两条分支，由 DAG 依赖完成首帧 → 视频的衔接 | `artifact:first_frame_image`、`artifact:i2v_video` |
| `rerun_node` | production, system | generate | ✔ | 按将执行的节点估算 | 1800 | 1 | `JobRunService` 的 run_node / run_from | 原 Job 的新结果 |
| `package_project` | production, system | write | — | 0 | — | 0 | 每个 Job 调用 `JobPackageService.create_or_refresh`；不去重 | 每个 Job 一个 ZIP |
| `get_task_status` | 全部角色 | read | — | 0 | — | — | `JobService.get_detail` 收敛为稳定 DTO | 状态、进度、节点、图片/视频工件、prompt、根因错误 |

所有工具都会补上 `export_manifest` 节点，并在 `job_config` 写入：
- `skill`：`invocation_id`、`tool_name`、`budget_scope`、`caller_role`；
- `node_models` / `node_model_params`：钉定已校验的模型和参数（见第 6 节）。

Job 的 `strategy` 字段记为 `skill:<tool_name>`。

本轮**没有注册** `remix_shot`、`deliver_project`、`compose_video`。前两者属于 Phase 2/3；`compose_video`（多镜头拼接成片）是系统目前没有的能力，需要单独开发。

## 4. 幂等、重试与状态

**幂等键**：调用方显式传入的 `idempotency_key`，否则取 `sha256(tool_name + 规范化后的输入 JSON)`。`package_project` 设置了 `dedupe=False`，每次调用都会重新执行，因为包必须反映 Job 的最新状态。幂等键只由输入决定，与 `budget_scope` 无关。

| 账本中同键记录的状态 | 再次调用的行为 |
|---|---|
| 不存在 | 预算检查 → 写入 `pending` → 执行 |
| `pending` / `running` / `success` / `partial_success` | **重放**：返回原输出（`replayed=true`），不建 Job、不提交任何付费任务 |
| `failed` 且 `attempt < 1 + max_retries` | 重试：`attempt+1`，预算累加；生成类工具**对原 Job 再次 run_full**，已成功的节点自动跳过，不重复计费 |
| `failed` 且已达上限 | `409 RETRY_LIMIT_EXCEEDED` |
| `rejected` | 视为未执行过，重新评估（例如提高预算后重试） |
| 被其他工具占用 | `409 IDEMPOTENCY_KEY_CONFLICT` |

**状态机**：

```text
pending ──handler 成功且关联 Job──► running ──Job 终态──► success / partial_success / failed
   │                                         （由 get_task_status 或下一次同键调用同步）
   ├──handler 成功且无 Job──► success
   ├──handler 抛 4xx 且尚未创建 Job──► rejected（不计预算、不占重试次数）
   └──handler 抛其他错误──► failed
```

**时序保护**：线程执行模式下，重跑刚启动时 Job 仍显示上一轮的终态。账本记录每次尝试的 `started_at`，只有 `updated_at` 晚于 `started_at` 的 Job 终态才会被采信。`get_task_status` 的 `terminal` 也会考虑调用记录的状态，避免 Agent 提前结束轮询。

`rerun_node` 的重复调用同样会被去重；确实需要再跑一次时，调用方需要传入新的 `idempotency_key`。

## 5. 预算

- 成本是抽象的 **credits 估算值**，用于防止失控生成和重复提交，**不是厂商账单**。单价：LLM 调用 1、图像生成 2、视频生成 10；I2I 节点按样本数相乘（`skills/budget.py`）。
- 口径偏保守：只要任务提交就计费，即使厂商侧任务后来失败；重试再累加一次。
- 限额：调用时传入的 `budget_limit`，否则取 `SKILL_DEFAULT_BUDGET`（默认 100）。按 `budget_scope` 汇总所有非 `rejected` 的调用。Phase 2 中 `budget_scope` 对应一次 Agent 创作会话。
- 删除 Job 不会退还预算：账本的外键是 `ON DELETE SET NULL`，记录会保留。

## 6. 安全约束

| 约束 | 实现 |
|---|---|
| 不接受任意文件路径 | `analyze_video` 只接受工件 ID。LLM 给出的路径可能指向任意本地文件，并被发送给外部服务 |
| 模型必须存在、已启用、`task_type` 匹配 | `model_guard.resolve_model`。例如不能用 i2v 模型生成图片 |
| 参数必须符合模型的 `parameter_schema` | `model_guard.validate_params`：未知参数、类型、`enum`、`min`/`max` 都会校验。经典 UI 只用 schema 渲染表单，后端此前没有任何校验 |
| 运行时使用的就是校验过的模型 | 未指定模型时，按“节点全局配置 → 环境变量默认值”解析出实际模型，并写入 `node_models`，后续全局配置变更不影响已创建的 Job |
| Agent 不能动用户的经典 Job | `rerun_node` 只允许操作 `job_config.skill` 存在的 Job；`system` 角色例外 |
| prompt 不污染经典模板 | Skill Job 统一归入专用模板 `agent_workspace`（系列 `agent_studio`）。初始 prompt 经 `PromptSyncService` 回写到模板时，只写进这个模板 |

## 7. 数据库映射

`tool_invocations`（模型 `ToolInvocation`）：

| 字段 | 说明 |
|---|---|
| `invocation_id` | 对外 ID（`tinv_…`） |
| `tool_name` / `caller_role` / `budget_scope` | 调用信息 |
| `idempotency_key` | 唯一约束，String(128) |
| `status` / `attempt` | 见第 4 节 |
| `input_payload` / `output_payload` | 校验后的输入与输出（JSON） |
| `error_code` / `error_message` | 最近一次失败原因 |
| `job_id` | FK → `jobs.id`，`ON DELETE SET NULL` |
| `estimated_cost` | 累计估算成本 |
| `duration_ms` / `started_at` / `finished_at` | 执行耗时与时序 |

建表有两条路径：
- Alembic 迁移 `20261014_001`。迁移本身是幂等的：`flask db upgrade` 会先启动应用，而自动修表可能已经建好了这张表。
- `SchemaService.ensure_compatible_schema()`：给早期用 `create_all` 建的、没有 Alembic 历史的库补表。

Job 表不改结构：工具来源通过 `jobs.strategy` 和 `jobs.config.skill` 记录。

## 8. API 契约

仅在 `AGENT_MODE_ENABLED=true` 时注册，沿用全局 JWT 鉴权。

```http
GET  /api/skills                               # 工具清单 + 输入/输出 JSON Schema
POST /api/skills/{name}/invoke                 # 调用工具
GET  /api/skills/invocations/{invocation_id}   # 查询账本记录
```

调用请求体：

```json
{
  "role": "production",
  "approved": true,
  "input": {"shot_id": "opening", "first_frame_prompt": "…", "i2v_prompt": "…"},
  "idempotency_key": "film-1:opening",
  "budget_scope": "film-1",
  "budget_limit": 50
}
```

调用响应（`data`）：

```json
{
  "tool": "produce_shot",
  "invocation_id": "tinv_…",
  "status": "running",
  "attempt": 1,
  "estimated_cost": 12.0,
  "replayed": false,
  "output": {"job_id": "job_…", "status": "queued", "expected_outputs": ["artifact:first_frame_image", "artifact:i2v_video"]}
}
```

错误码：

| HTTP | code | 含义 |
|---|---|---|
| 422 | `INVALID_INPUT` | 输入 Schema、模型或参数校验失败（含 `payload.errors`） |
| 403 | `TOOL_FORBIDDEN` | 角色无权调用，或 Agent 试图重跑非 Skill Job |
| 403 | `APPROVAL_REQUIRED` | 付费工具未获批准 |
| 402 | `BUDGET_EXCEEDED` | 超出 `budget_scope` 预算（含 spent / requested / limit） |
| 409 | `IDEMPOTENCY_KEY_CONFLICT` | 幂等键已被其他工具使用 |
| 409 | `RETRY_LIMIT_EXCEEDED` | 失败次数已达上限 |
| 404 | `TOOL_NOT_FOUND` / `INVOCATION_NOT_FOUND` / `JOB_NOT_FOUND` / `ARTIFACT_NOT_FOUND` / `MODEL_NOT_FOUND` | 资源不存在 |
| 400 | `NO_PACKABLE_CONTENT` | 请求的 Job 都无法打包 |
| 500 | `TOOL_OUTPUT_INVALID` / `TOOL_FAILED` | 工具实现错误 |

## 9. 已知限制

1. 幂等只覆盖“Agent → 工具层”这一段。适配器传输层仍会对 POST 自动重试（审计风险 #3），厂商侧重复提交的风险没有消除。
2. 如果进程在 handler 执行期间崩溃，账本会停在 `pending`，同键调用会一直重放这条记录，需要人工处理（Phase 4 处理崩溃恢复时一并解决）。
3. Skill Job 会出现在经典 Jobs 列表中（模板 `agent_workspace`，strategy `skill:*`），前端暂未过滤。
4. `package_project` 是每个 Job 一个 ZIP，不会把多个镜头合成成片。
5. 已有的迁移 `20260603_001` 没有做幂等防护，与自动修表同时存在时可能冲突。这不属于本轮范围，未修改。

## 10. Phase 2 衔接

- **工具暴露给 LLM**：`ToolSpec.input_model` 可以直接作为 LangChain `StructuredTool` 的 `args_schema`，`describe()` 提供 JSON Schema。LangGraph 节点只通过 `get_registry().invoke()` 执行工具。
- **人工确认**：`APPROVAL_REQUIRED` 对应 LangGraph 的 interrupt。用户批准后，带 `approved=True` 和**同一个 `idempotency_key`** 重新调用，保证不会重复提交。
- **计划执行**：Creative 产出 `PlanSpec`（`app/agent/plan_spec.py`），校验通过后，Production 对每个 `ShotSpec` 调用一次 `produce_shot`，`budget_scope` 取会话 ID，再用 `get_task_status` 轮询，单个镜头失败可以单独重试。
- **状态持久化**：Checkpointer 只保存 Agent 状态以及 `invocation_id` / `job_id`，业务数据仍在 MySQL。开发环境可用 SQLite Checkpointer；生产环境需评估 MySQL 社区实现或改用 Postgres。
- **执行位置**：Agent 运行要像 `JobQueueService` 一样放到后台线程，不能占用 Gunicorn 请求线程。多进程部署和重启恢复见 `phase0_audit.md` 风险 #1、#2。
