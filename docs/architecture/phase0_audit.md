# Phase 0 架构审计与回归基线

> 范围：CineCrew（原 AI Video Factory）多 Agent 升级的第一阶段。
> 依据：分支 `refactor/cinecrew-phase0-1` 起点 `main@ae4ce97` 的真实源码。
> 目的：明确改造边界，确认经典工作流可以稳定执行，为 Phase 1（业务能力 Skill 化）提供依据。

## 1. 结论摘要

1. **经典 DAG 本身就可以充当 Agent 的确定性生产引擎**。`JobService.create_job()` 支持以编程方式传入初始 prompt（`initial_prompts`）、复用其他 Job 的工件（`initial_artifacts`，自动记录 `source_artifact_id` 血缘）、按分支启停节点、按节点覆盖模型和参数。因此 Agent 层可以把“一个镜头”映射为“一个经典 Job”，复用全部生成、追踪、恢复和打包能力，不需要改写 NodeRunner。
2. **唯一需要从经典代码中抽出的共享逻辑是“运行调度”**。它目前写在 API 层（`api/jobs.py` 的 run-full / run-from / run-node 及 `_start_async_run`、`_validate_start_node`），Tool 层无法复用。Phase 1 将其抽成 `JobRunService`。
3. **抽取前仓库没有任何自动化测试**。本阶段补齐了经典模式的回归基线（40 个用例，mock 模式下运行），作为后续每个 Phase 的回退门槛。

## 2. 模块依赖图

```text
frontend-vue (Vue3/Pinia/axios + SSE)
        │ REST /api/*（JWT）
        ▼
api/  (11 个 Blueprint，薄控制层；jobs.py 中混有运行调度逻辑 → Phase 1 抽取)
        │
        ▼
services/
  JobService ─────────────┐  建 Job：文件落盘、工件登记、节点快照、WorkflowValidator 输入推断
  JobQueueService ────────┤  进程内队列（deque + daemon 线程，全局并发 2）
  WorkflowService ────────┤  run_full / run_from / run_node；_validate_job_workflow 续跑资源注入
    └─ WorkflowScheduler ─┤  单 Job DAG 并行（4 worker / poll ≤2）、失败决策、终态裁决
         └─ NodeRunner ───┤  19 个 _run_<node_key> 处理器（反射分发）
              ├─ PromptService / PromptSyncService   版本、快照、回沉淀模板
              ├─ ModelService                        注册表 + 四级模型解析 + 五层参数合并
              ├─ ArtifactService / StorageService    工件登记、相对路径存储
              ├─ I2ITestBatchService                 I2I 批次抽样
              ├─ FailureDecisionService / ErrorDetailService
              └─ adapters/ (Base + DashScope×5 + QwenChat + Mock×4)
  JobPackageService / TemplatePackageService         一键打包
        │
        ▼
models/ (SQLAlchemy)  ←→  SQLite（开发）/ MySQL（生产）
storage/jobs/<job_id>/{raw,outputs,prompts,logs,packages}
```

## 3. 可复用服务清单

| 业务能力 | 现有实现 | 复用方式 | Phase 1 对应 Tool |
|---|---|---|---|
| 视频理解（反推 t2v prompt） | `NodeRunner._run_reverse_prompts` | 直接复用：只启用 `reverse_prompts` 的 Job | `analyze_video` |
| Prompt 改写（t2v → 首帧 / i2v / r2v） | `_run_rewrite_prompts`、`_run_reverse_prompts4r2v` | 直接复用：`initial_prompts.t2v` + 对应节点 | `rewrite_prompt` |
| 图像生成（首帧） | `submit/poll_first_frame_image` | 直接复用：first_frame_image 分支 | `generate_image` |
| 视频生成（T2V / I2V / R2V） | `submit/poll_t2v`、`submit/poll_i2v`、`submit/poll_r2v_flash` | 直接复用；I2V 通过 `initial_artifacts.first_frame_image` 复用首帧 | `generate_video` |
| 首帧 → 视频衔接 | DAG 依赖 `submit_i2v → poll_first_frame_image` | 直接复用：一个 Job 同时启用两条分支 | `produce_shot` |
| 任务状态查询 | `JobService.get_detail`、`ArtifactService.list_for_job` | 直接复用，Tool 层只做 DTO 收敛 | `get_task_status` |
| 节点重新执行 | `api/jobs.py` run-node / run-from | **需要抽取**为 `JobRunService` | `rerun_node` |
| 素材打包 | `JobPackageService.create_or_refresh` | 直接复用（单 Job） | `package_project` |
| 模型选择与参数 | `job_config.node_models` / `node_model_params` | 直接复用 | 各生成类 Tool 的 `model_id` / `params` |
| 断点续跑 | `WorkflowScheduler` 跳过当前批次已成功节点 | 直接复用：失败 Tool 重试时对原 Job 再次 run_full | Registry 的重试语义 |

**系统中没有的能力**（不在 Phase 1 范围）：
- 多镜头视频的自动拼接（compose_video）：现有打包只是把素材装进 ZIP，没有合成成片。
- 镜头级视频理解：`reverse_prompts` 输出的是整段视频的单个 t2v prompt，二次创作需要的镜头切分属于 Phase 3。
- 真实成本计量：`Job.budget_limit` / `cost_used` 字段存在，但没有任何计价逻辑。

## 4. 改造边界

| 类别 | 内容 |
|---|---|
| **不动** | `NodeRunner`、`WorkflowScheduler`、`WorkflowService`、全部适配器、`config.DEFAULT_WORKFLOW_NODES`、经典 API 的 URL / 请求体 / 响应结构、前端页面逻辑 |
| **增量改动** | `create_app` 增加 `config_overrides`（仅测试使用）；`api/jobs.py` 运行调度改为委托 `JobRunService`；health 接口追加字段；`SchemaService` 追加新表的兼容建表 |
| **新增** | `services/job_run_service.py`、`skills/`、`agent/`（骨架）、`models/tool_invocation.py`、`api/skills.py`（受 `AGENT_MODE_ENABLED` 控制，默认关闭）、对应 Alembic 迁移 |

## 5. 已知风险（本轮只记录，不修复）

| # | 风险 | 位置 | 对 Agent 模式的影响 |
|---|---|---|---|
| 1 | 队列与运行集是进程内内存状态；Gunicorn 默认 `workers=2`，每个进程各有一套队列，并发上限按进程计算 | `services/job_queue_service.py`、`deploy/entrypoint.sh` | Agent 会批量创建镜头 Job，实际并发可能是配置值的 2 倍；Phase 2 的 Agent 运行同样需要后台执行 |
| 2 | 进程重启后无恢复：DB 中 running/queued 的 Job 成为孤儿 | 同上 | Agent 依靠持久化 job_id 恢复时会看到“永远 running”的 Job，需要在 Phase 2/4 处理 |
| 3 | 传输层重试白名单包含 POST（429/5xx 自动重试最多 5 次），提交生成任务时没有幂等键 | `adapters/base.py:75-81` | 厂商已受理但响应超时时可能重复计费；Tool 层幂等只能防止 Agent 层的重复调用，防不住这一层 |
| 4 | 节点定义有两个来源，靠人工保持一致 | `config.py:DEFAULT_WORKFLOW_NODES`、`services/workflow_validator.py:177 NODE_DEFINITIONS` | Tool 层计算节点启停全集时以 `DEFAULT_WORKFLOW_NODES` 为准 |
| 5 | 种子同步不更新 `enabled` 字段，已初始化的库改环境变量开关无效 | `WorkflowService.seed_default_nodes` | Tool 层显式传入完整的启用/禁用列表，不依赖全局开关 |
| 6 | 初始 prompt 会经 `PromptSyncService` 回写到模板级版本 | `services/prompt_sync_service.py:43`、`JobService._write_initial_prompts` | Agent 的镜头 Job 必须使用专用模板（`agent_workspace`），否则会污染经典模板 |
| 7 | I2I Test 样本轮询仍是串行 for 循环 | `services/node_runner.py:1460` | 与 Agent 模式无直接关系 |
| 8 | 轮询超时只在本地判失败，不取消厂商侧任务 | `services/node_runner.py:301` | 预算估算按“提交即计费”保守处理 |

## 6. 回归基线

运行方式：

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

测试环境约束（`backend/tests/conftest.py`）：
- 每个用例使用独立的临时 SQLite 文件和存储目录；
- 在导入 `app.config` 之前固定环境变量，开发者本地 `backend/.env` 不影响结果；
- 强制 `MODEL_ADAPTER_MODE=mock`、清空 API Key，并拦截 `requests.Session.send`，任何真实外部请求都会让用例直接失败；
- personas / R2V 参考图目录指向临时目录中的假图片。

覆盖范围：

| 文件 | 覆盖内容 |
|---|---|
| `test_workflow_paths.py` | main_i2v、t2v、r2v_flash（上传参考图 / personas 抽样）、i2i_test 三种模式及 shot_type 映射、缺输入报错、manifest |
| `test_failure_semantics.py` | 分支失败只级联本分支、export_manifest 照常执行、partial_success / failed 判定、I2I 单样本失败隔离 |
| `test_rerun.py` | 再次运行跳过已成功节点且不重复提交、restart 批次隔离、run_from、run_node |
| `test_prompts.py` | prompt 血缘、快照、回沉淀模板、edit/rollback 追加版本、重跑时保留用户手改 |
| `test_package.py` | ZIP 结构（final / assets / prompts / manifest）、重复打包复用工件、无内容拒绝打包 |
| `test_api_smoke.py` | JWT 鉴权、全部只读接口返回结构、validate-run、multipart 建 Job → 运行（线程 / 队列两种执行方式）→ 打包下载、SSE 事件回放 |

前端没有测试框架，基线为 `npm run build` 成功，加上手工冒烟清单：登录、Dashboard、四步建 Job 向导、JobDetail 的 SSE 进度、工件预览、一键打包下载、Prompt 管理、模型注册表、工作流画布启停。

## 7. 进入 Phase 1 的条件

- [x] 回归基线在未改动的业务代码上全部通过（提交 `7eca36a`）
- [x] 前端构建通过
- [x] 可复用服务清单与改造边界已确认（本文第 3、4 节）
