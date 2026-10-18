---
name: budget-planning
description: 区分规划与生成费用，按目录计价单位估算并保留审批边界。
when_to_use: 选模型、拆分镜头、拟定预览或讨论重做影响时。
agents:
- producer
- director
- creative
- critic
- repair
tools:
- list_models
- estimate_cost
- check_plan
related: []
version: 2
---
# 预算与时长

目录价格为演示 credits，不代表服务商真实账单。图像按张或目录单位；视频按合法秒数和分档单价；Wan3 的 billing_basis 可能为实测输入视频 I + 完整输出 G，延长新增秒数与 G 不同。不得把所有视频算成固定按次费。

estimate_cost 用于已有真实素材和候选参数，只读且不授权。完整 DAG 用 check_plan，根据未来输出类型/时长上界估算，禁止伪造未来工件 ID 或按零秒处理未知素材。编译/dry-run 后的服务端报价为审核依据；价格/输入变更会要求重新确认。

展示规划费用（LLM、检索、理解、受限 request_preview）、生产费用和 repair_budget_credits 预留。它们受同一 Run 总预算约束；子任务额度来自父剩余，修订和新版本不重置。ask_user 不是自动增加额度的接口；不足时说明可缩减范围或明确返回。

委派以本轮服务端 quota 快照为依据，区分 delegation_limit / delegation_remaining、run_planning_limit / run_planning_spent 与 run_budget_limit / run_spent。快照是 LLM 调用前值，本轮也消耗额度；按必要子任务成本显式填写 planning_credits，留出父任务后续汇总/提交空间。不要逐级盲用默认分配，也不要把生产预算当作规划余额。旧运行缺少快照时不编造余额、不猜测可以加额；任何快照都不是新授权。

Patch 报价区分 repair 与 continuation：前者为受影响的重做节点，后者为原计划尚未执行部分；复用/保留产物无新增模型费。only 保留既有下游可能有衔接风险，cascade 重新执行影响子图，必须展示对应报价。低风险自动修复也占原池与跨版本次数；人工批准不重置修复池。报价不是账本已花费用。

交付秒数不等于计费秒数：输入视频、多个尝试、裁切/拼接都会造成差异。只保留原片的裁切没有生成费，默认不额外压缩。不要为了预算私自改变用户指定系列、身份、关键情节或目标时长。
