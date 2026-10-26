# Phase 4：消息队列只读审计

依据 `docs/architecture/mq_integration_spec.md` 审计经典 DAG 和 Agent 共用执行层。本轮未引入 Redis、Outbox 表或新调度器。当前版本用于单主机、单 Agent worker 的受控评估，不能宣称已具备分布式可靠队列。

## 实体映射

| 方案概念 | 当前实现 | 缺口/建议 |
|---|---|---|
| 用户幂等 | AgentRun 的 owner/request_key、command inbox、修订回执 | 保留会话层协议，不用 Stream ID 替代业务键 |
| 调用/预算 | ToolInvocation 的唯一键、scope、estimated_cost、job_id | 非供应商 HTTP 日志；检查预算与插入不是通用跨进程原子预留 |
| 生成任务 | ApiTask → JobNodeRun，保存 model/provider ID/request/response | 优先扩展该实体，缺提交未知、下载状态、next_poll_at、租约和代数 |
| DAG | WorkflowService、NodeRunner、JobRunService | 保留依赖、失败隔离及局部重跑语义 |
| 队列 | JobQueueService 的进程内 deque/线程 | 不跨进程共享，入队和 DB 提交无 Outbox 原子性 |
| Poll | NodeRunner._poll_until_complete | for/sleep 占用线程，无持久化到期时间或租约 |
| Download | NodeRunner._complete_task_from_adapter | 查询后串行下载、压缩、注册工件，不能独立调度 |
| 工件 | Artifact、StorageService、JobPackageService | 依赖本地磁盘；未来需稳定工件键、临时文件校验、原子改名及登记幂等 |
| Outbox | 尚无；JobEvent 用于业务展示 | JobEvent 不具投递状态和事件唯一键，不能直接当作可靠消息表 |
| 恢复 | Agent checkpoint + recovery.recover_job | 复用已知 provider ID；未知计费结果保守停止，尚无通用对账 |

## 调用链与故障窗口

```text
Agent → Tool Registry/账本 → JobService → JobRunService
                                            ↓
                                   JobQueue/后台线程
                                            ↓
                                   WorkflowService DAG
Submit → Adapter.submit → 保存 ApiTask/provider ID
Poll   → Adapter.poll 循环 → 下载/压缩 → Artifact 登记
```

经典模式同样使用 JobRunService/WorkflowService。异步视频有 provider ID 和 Poll；同步图像接口可返回结果引用，未来可跳过 Poll，不能跳过可靠下载状态。同步分析/规划也存在上游已执行而本地未保存结果的窗口。

| 故障窗口 | 当前行为 | 后续 MQ 验收 |
|---|---|---|
| 内存入队后退出 | 队列丢失，数据库状态不是可靠投递 | 同事务业务状态 + SubmitRequested |
| 上游受理、回复丢失 | Agent 不盲目重发，本轮 Fake 注入验证 | SUBMIT_UNKNOWN；供应商幂等/查询证明后再恢复 |
| provider ID 保存后节点未成功 | Agent 复用任务 ID | 版本/CAS 防并发重复推进 |
| 下载失败 | 节点失败可见，显式重跑 poll 复用任务 | DOWNLOAD_PENDING + DownloadRequested 同事务 |
| 文件成功但 DB 未确认 | 未具备通用文件/DB恢复协议 | 稳定工件键、内容校验、补齐确认；单独故障注入 |
| 图提交后索引更新前中断 | checkpoint 和回执恢复，本轮验证无重复生成 | 保留图与账本提交顺序 |

Agent 文件锁只约束同一 checkpoint 路径。直接 Skills 调用不受图 worker 锁保护，跨进程预算预留是后续执行层审计项。经典传输重试策略与 Agent 不同，不能把 Agent 的付费 POST 不自动重试保证推广到经典模式。

## 下一阶段路线

1. 确认 ApiTask 状态、操作版本、稳定工件键和事务边界，设计共用提交未知对账入口。
2. 独立 Outbox、唯一 event_key，先验证重复投递和事务故障，再接 Publisher/Streams。
3. Poll 改单次查询，持久化 next_poll_at/generation/租约；Download 独立执行。
4. 验证旧消息、重复领取、文件与 DB 故障、共享存储、灰度回退。

MQ 文档中的“暂不引入 LangGraph”需更新为保留现有 LangGraph 编排；队列只分发底层执行工作。本轮 12 Job Mock 突发测试只验证现有并发上限和无丢任务，不证明生产容量、RPM 或跨进程可靠性。多 worker/多主机发布前必须完成可靠分发验收。
