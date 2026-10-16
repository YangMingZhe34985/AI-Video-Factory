# Phase 4：稳定性与系统评估

## 本轮交付

复用 AgentRun、ToolInvocation、ApiTask、Job 和 checkpoint，无新增数据库表或队列服务。本轮是离线稳定性验收，不是生产发布或真实模型质量评测。

- `AGENT_ALLOWED_USERS`：JWT `user_id` 白名单（逗号分隔，空值不限制），约束新会话、素材上传和直接 Skills 调用。
- `AGENT_ACCEPT_NEW_RUNS=false`：暂停上述新入口，已有会话仍可查询、审批、修订、交付；相同创建键仍可重放。
- `GET /api/agent/runs/{run_id}/metrics`：按原会话所有权读取成本和恢复指标。
- worker 状态变更日志：run_id、原状态、目标状态、估算 credits；不记录 Prompt、密钥或供应商 URL。
- 状态日志使用 Python logging 的 INFO 级别，部署时须确保应用 logger 的有效级别允许 INFO；metrics 接口不依赖日志级别。
- `backend/scripts/phase4_verify.py`：输出全量测试结果、失败详情、耗时和对照评估数据的 JSON。

## 监控口径

metrics 包含预算、估算占用、余额、按工具调用/尝试/成本汇总、账本状态、生成任务模型分布、恢复次数、镜头修订和草稿错误数。80%预算提示 `BUDGET_NEAR_LIMIT`，超预算提示 `BUDGET_EXCEEDED`，待处理/失败镜头提示 `RECOVERY_REQUIRED`/`SHOT_FAILED`。

运行中、失败及未知提交继续占预算，rejected 不占预算，幂等重放不新增成本。该值是**预算预留估算，不是账单**。provider_task_count 只计已保存的生成任务，不含分析/规划；回复丢失时可以为0，不能据此判断没有外部请求。真实 Token、货币费用仍需供应商用量接入。elapsed_seconds 包含人工等待，不是纯模型执行耗时。

## 故障与回归矩阵

| 场景 | 用例位置 | 断言 |
|---|---|---|
| 未审批/预算/模型/归属 | 原有 Agent、Skills、Remix | 校验保留、非法生成被阻止 |
| 上游受理后回复丢失 | test_phase4_stability | Fake提交一次，无provider ID，不重发且不退预算 |
| provider ID保存、节点未完成 | test_agent_mvp | 复用原任务，不重复生成 |
| checkpoint完成、索引未保存 | test_phase4_stability | 恢复后一个Job、两项生成任务、14 credits |
| 分析/生成后checkpoint丢失 | test_agent_mvp/test_agent_remix | 账本重放，无重复成本 |
| 下载中断 | test_phase4_stability | 显式重跑poll复用provider ID，恢复工件 |
| 打包中断 | test_agent_mvp | 恢复不增加重复工件 |
| 单样本/镜头失败 | 原失败隔离和Remix测试 | 保留成功结果，允许部分交付 |
| 旧审批/修订回执 | test_agent_mvp/test_agent_remix | 不重复推进或计费 |
| 四路并发审批 | test_phase4_stability | 一个202、三个409，仅执行一次 |
| worker锁进程死亡 | test_phase4_stability | 活跃锁排斥另一worker；进程终止后释放 |
| 12 Job突发 | test_phase4_stability | 并发不超过2，全部完成，仅24项生成任务 |
| 灰度排空/关闭/恢复 | test_phase4_stability | 新请求拒绝、旧会话交付、经典运行、历史保留 |

子进程测试实际终止持有相同SQLite锁协议的进程；图/节点故障采用明确窗口的异常注入，不等同于完整真实供应商崩溃演练。

## 离线实验与运行

固定橘猫、小狗两个主题，对比经典、单 Creative、Director+Creative 三条链路，均生成一个镜头并打包。单 Creative 使用固定 Brief；经典使用测试源素材。记录成功、耗时、估算成本、任务数和审批操作数。

Mock只用于编排基线，不用于质量排名。`quality_score=null`；Mock耗时不是生产时延，固定Brief与生成Brief的质量也不可据此比较。后续获准真实评测时，需统一输入/素材、固定模型参数、独立预算和随机样本顺序，记录人工修改、时长/范围/模型约束准确率及盲评满意度。

```bash
python backend/scripts/phase4_verify.py --output backend/storage/phase4-verification-<unique-id>
```

需测试依赖及FFmpeg（PATH或FFMPEG_BINARY）；输出目录必须新建。fixture固定隔离SQLite/存储/Mock，并拦截requests网络发送；失败详情和退出码写入报告。本轮无付费测试。

## 灰度回滚手册

1. 备份业务DB、checkpoint及存储目录，Web/worker保持版本一致。关闭AGENT_MODE_ENABLED时经典路径可用。
2. 开启AGENT_MODE_ENABLED、AGENT_ACCEPT_NEW_RUNS，设置试点user_id白名单；Web/worker配置与存储一致，同一路径仅运行一个Agent worker。
3. 检查完成率、needs_attention、预算和重复任务；异常时停止扩圈。
4. 先将Web的AGENT_ACCEPT_NEW_RUNS设为false并重载配置。该开关是准入暂停，已有会话仍有执行权限，不是强制停止付费开关。完成/拒绝会话或记录待人工处理状态，确认底层Job退出后停止worker。
5. 关闭AGENT_MODE_ENABLED并重载Web；验证Agent/Skills路由关闭、经典API和打包可用。保留表、checkpoint和文件，不以删表回滚。
6. 同一兼容版本与checkpoint路径重新启用，核对历史任务ID；未知提交先对账。二进制降级需另验checkpoint/schema兼容性。

本轮验证隔离DB/checkpoint上的配置关闭/重新创建应用、排空和经典路径。未执行生产Docker发布、备份恢复或二进制降级。[MQ只读审计](phase4_mq_audit.md)记录了后续迁移边界。

## 2026-10-17 验收结果

全量 **199 项通过，0 失败、0 跳过**（约189.75秒），相对上轮新增15项验收用例。前端 `npm run build`、Python编译检查和 `git diff --check` 通过。本轮外部付费调用为零。

机器报告：[report.json](../../backend/storage/phase4-verification-20261016-02/report.json)。首次评估运行暴露共享注册表污染，已改用独立注册表；原失败报告保留在相邻 `phase4-verification-20261016-01` 目录，没有调整或削弱原断言。

| Mock基线 | 成功样本 | 每镜头估算credits | 平均本地流程耗时 |
|---|---:|---:|---:|
| 经典 | 2/2 | 14 | 0.696秒 |
| 单Creative（固定Brief） | 2/2 | 13 | 0.656秒 |
| Director+Creative | 2/2 | 14 | 1.188秒 |

12 Job突发测试：12/12成功、24项生成任务、最大并发2、约8.156秒。样本量小且供应商为Mock，只作为可重复的本地执行基线，不据此决定生产扩容规模或宣称单Agent质量优于多Agent。

本轮离线验收完成。真实规划准确率、视频质量与真实成本评估，以及生产部署回滚、跨进程预算原子预留和持久化任务分发仍是后续明确的验收边界。
