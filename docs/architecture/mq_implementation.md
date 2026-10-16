# CineCrew 共用执行队列

## 实施顺序

引入前基线：`214ce68`，已推送 `refactor/cinecrew-phase0-1`。Agent 与经典工作流都从 JobRunService 进入，保留 LangGraph 和现有 DAG。用户已授权本轮连续逐阶段实施；全部验收使用隔离数据库、Mock 供应商，不调用付费接口。

1. 持久化 Job 调度、ApiTask 操作身份及事务 Outbox；提交消费者在网络调用前保存领取状态。回复不明进入 submit_unknown，禁止自动重发。
2. 单次 Poll + 数据库到期调度，消息带代数，短事务领取，提交后 ACK；DAG 在等待外部结果时保存节点并释放执行线程。
3. 独立 Download、任务专属文件路径、校验收据、原子改名和工件幂等；I2I 样本分别推进。
4. Redis 故障、重复消息、失联消费者、过期租约、下载/数据库故障注入；Agent/经典/局部重跑回归；灰度排空回滚和运维文档。

MySQL 是状态真源，Redis Streams 只运送事件 ID。Redis 不可用时 API 仍能原子写入任务和 Outbox。提交/轮询/下载共用同一套消费者，与任务来自 Agent 或经典界面无关。灰度开关仅决定新 Job 的入口，已进入 MQ 的任务继续由 MQ 排空，不能切回旧执行器重复提交。

## 对现有逻辑的调整

既有 I2I Test 首帧提交逐项执行，poll 节点逐项阻塞等待，成功的首帧会内联提交 I2V，但仍可能被较慢的前一个样本阻塞。已有样本错误记录和部分成功工件。本轮将这些调用变为独立持久化 ApiTask；节点遍历遇到尚未完成的样本继续处理其余样本，结束后挂起。原有展示、打包和 DAG 依赖复用。

每次显式执行分配调度版本，挂起的节点复用同一个 JobNodeRun，重复消费复用同一调用键。保留人工 force/restart 的新调用语义。供应商提交结果未知时只允许人工绑定已经确认的 provider ID 或明确终止，不能通过重试自动生成第二单。

## 验收清单

- 业务状态与 Outbox 同事务回滚；重复发布/消费只推进一次。
- Agent 与经典工作流共享入口和三个执行流。
- 单次轮询不 sleep；重启恢复 next_poll_at；过期代数无副作用。
- 提交回复丢失或领取后退出保守进入 submit_unknown。
- 下载失败不会重交生成；文件成功、DB 确认前退出可补登工件。
- I2I 一个样本失败或变慢不阻止其他样本，成功结果可打包。
- 暂停/取消、局部重跑、完整重启、灰度关闭后排空。
- 实际 Redis/MySQL 隔离集成及全量离线回归；不以 Mock 结果宣称真实模型质量/生产容量。

## 发布与回滚

默认 `MQ_ENABLED=false`。先安装 backend/requirements.txt 并执行 `flask --app run.py db upgrade`，迁移版本为 `20261017_001`。旧记录新增字段均为可空或有默认值，不自动改写旧任务。开发环境的 `init-db` 不能替代已有库的迁移。

本地需要独立 Redis 7；生产 Compose 新增可选 `mq` profile、Redis AOF 卷和 scheduler/submit/poll/download 四种角色。所有角色与 API、Agent worker 必须使用同一个 MySQL、Redis DB 以及挂载位置一致的共享 storage。生产数据库迁移由 backend 启动入口执行，MQ worker 等待 backend 健康后启动。

```sh
# .env.production 设置 MQ_ENABLED=true；Agent 按需启用原有 agent profile。
docker compose --env-file .env.production --profile mq --profile agent up -d --build
docker compose --env-file .env.production exec backend flask --app run.py mq-status

# 小规模本地调试可用 all；生产应使用分开的角色，避免同步 Submit 占住 Poll。
flask --app run.py mq-worker --role all
flask --app run.py mq-worker --role scheduler
flask --app run.py mq-worker --role submit
flask --app run.py mq-worker --role poll
flask --app run.py mq-worker --role download
```

灰度只在一组隔离的试用部署上开启 MQ，避免旧进程的内存队列与新入口同时执行同一个 Job。切换前先停止接收新工作并排空旧线程任务。现有 MQ Job 在入口关闭后保持 MQ 所有权，后续局部重跑也走 MQ，不会意外切入旧执行器。

回滚顺序：关闭新 Agent 会话入口/停止接收经典新任务；设置 `MQ_ENABLED=false`；保持 MQ worker 运行，用 `mq-status` 确认 dispatch ready/running 为 0、无活动 task phase、unconsumed_events 为 0；人工处理 submit_unknown；停止 MQ worker。使用**仍在运行的新版本**执行 `flask --app run.py db stamp 20261016_001`，仅调整 Alembic 版本标记，不删除数据或列，然后回退到 `214ce68`。这一步使旧版 Docker 启动脚本能识别数据库版本，否则其自动 `db upgrade` 会因未知 revision 而拒绝启动。保留新数据库表、Redis 和 storage，不执行 `db downgrade`。回退后的旧代码不认识 MQ 所有权，**不能重跑或恢复仍在 MQ 中的 Job**。恢复新版本时正常执行 `db upgrade`，迁移会识别已存在的新增列和表，继续保留历史。

## 故障恢复与人工对账

每个 provider 调用有唯一 operation_key，每个可恢复节点有 execution_key；Outbox 的 event_key 含阶段与代数。领取、确认和恢复通过数据库条件更新/行锁完成，网络调用和媒体压缩不占用确认事务。调度器拥有续租线程，过期消费者的提交阶段不自动重试。下游节点等待时保存 `waiting`，不占一个线程持续 sleep。

调用键绑定调度版本、规范节点名与样本序号，而非可变提示词或临时 URL。队列等待期间修改默认参数不会产生第二笔调用；I2I 内联提交与后续补齐节点共享同一规范调用身份。新参数需显式发起新一轮执行。存在 submit_unknown 时普通重跑也会被拦截，必须先人工对账。

Publisher 每次扫描到期的 SQL 事件；同一事务中的状态与事件要么都提交，要么都回滚。XADD 成功但发布确认丢失允许重复投递；SQL 消费结果先提交，再 XACK。60 秒未确认的事件可以补发，Redis 重建/重启不会成为业务状态丢失的唯一原因。采用单 consumer group；只删除已 ACK 的那条消息，不使用可能丢未消费消息的 MAXLEN 截断。

默认租约 900 秒，Poll/Download 最多 3 次异常尝试；正常未完成 Poll 受 MAX_POLL_ROUNDS 限制；429 遵守数字 Retry-After（最多一小时）。这些设置不是全局 RPM 限流。Submit 网络结果不明、服务器错误或领取后失联进入 submit_unknown；只有明确的 429 拒绝可以自动再次尝试提交。真实同步图像结果跳过 Poll，并把结果 URL 保存在 JSON 中，不塞入受长度限制的 provider_task_id。

```sh
flask --app run.py mq-status
# 先在供应商后台核实原请求，以下命令只绑定已有任务 ID，再查询它。
flask --app run.py mq-reconcile api_xxx --provider-id confirmed-provider-id --reason "已核对供应商任务记录"
# 仅允许失败的 Poll/Download 重试；不会提交新的生成请求。
flask --app run.py mq-reconcile api_xxx --retry --reason "下载服务已恢复"
flask --app run.py mq-reconcile api_xxx --terminate --reason "人工确认无法恢复"
```

同步分析调用回复丢失不能靠媒体 provider ID 恢复，需人工检查。未知结果不能直接解释为未扣费。CLI 只应授予服务运维者；本轮未添加公开的管理写接口。`MQ_RECONCILED` 记录人工操作原因。

下载写入租约专属临时目录，通过实际图像/视频检查、SHA-256 收据及原子改名后登记 Artifact；文件成功而 DB 失败时复用收据。压缩最多 180 秒，沿用压缩失败时保留已校验原文件的策略。每个 ApiTask 有独立路径，显式重跑不覆盖旧结果。失败遗留的临时目录、历史 Outbox/Task 记录尚未自动清理，应按业务保留期归档，不能直接清空仍有未消费事件的表。

## 可观测性和范围

`mq-status` 提供调度数量、阶段分布、最老未确认事件年龄、发布次数和待对账任务。既有 `/api/jobs/queue/status` 返回持久化队列统计；节点 waiting 和 submit_unknown 提供中英文显示。Agent metrics 新增 queue_phases；预算仍是原工具账本的预估额度，不是供应商账单。Director/Creative 的会话规划仍由原 Agent worker 执行；分析和媒体 Job 均进入共用队列。

本轮没有启用生产 MQ、修改生产数据库或进行付费验证。SQLite 用于快速离线回归，生产应使用 MySQL。测试覆盖不等于多机容量认证；全局 RPM、分布式 Agent checkpoint/预算原子预留、自动供应商账单对账、监控告警推送和历史数据清理不在此版本中。Agent worker 仍保留原有单进程 checkpoint 锁。

## 可复现验收

离线：`python -m pytest backend/tests -q`，需可用 FFmpeg（Phase 3 原视频测试）。测试强制 Mock 并阻断供应商 HTTP。

真实服务测试位于 `backend/integration/test_queue_services.py`，与默认离线套件分开。仅允许显式设置 `CINECREW_MQ_INTEGRATION=isolated-1017` 并使用本机 `13306/cinecrew_mq_test`、`16379/15` 的一次性容器。该套件会重建这个测试 schema 并清空这个测试 Redis DB；不得指向生产。覆盖真实 MySQL 迁移、Redis 丢失重建、6 个并发领取者、Pending 接管及独立进程领取后退出。

回滚演练：`python backend/scripts/mq_rollback_verify.py --output .codex_smoke/mq-rollback-new`。输出目录必须不存在。脚本从 Git 基线导出旧代码，在三个独立进程中依次运行新版本、旧版本和恢复的新版本，使用同一份隔离 SQLite schema/storage；验证版本标记切换、各版本的迁移启动入口、每次执行成功及全部已有视频仍可访问。该演练不修改工作区分支或生产数据库。

## 本轮验收记录（2026-10-17）

以上四阶段已完成实现与隔离验收，生产入口仍默认关闭。

| 检查 | 结果 |
| --- | --- |
| 后端全量离线回归 | 221 项通过，无跳过；包括新增 20 项队列回归和 2 项实际图片校验 |
| MySQL 8.4.4 / Redis 7.4.2 隔离集成 | 4 项通过；MySQL 并行 DAG 用例另连续运行 3 轮通过 |
| 前端生产构建 | 通过 |
| Python 编译与 Git 差异检查 | 通过 |
| Compose 的 mq / agent profile 配置检查 | 通过；使用示例环境变量及 `--no-env-resolution`，不读取生产配置 |
| 回退基线、恢复新版本 | 通过；累计成功 Job / 可访问视频分别为 1 / 1、2 / 2、3 / 3 |
| 付费模型 / 生产数据库操作 | 未执行 |

本地报告保存在忽略目录 `.codex_smoke/mq-delivery-results.xml` 和 `.codex_smoke/mq-rollback-delivery/report.json`。覆盖的故障包括重复消费、Redis 事件丢失、消费者领取后退出、提交结果未知、下载后的 DB 确认失败、迟到结果与取消竞争、损坏图片、单样本失败和慢样本。真实供应商兼容性、网络延迟与生产容量仍需后续单独验收。
