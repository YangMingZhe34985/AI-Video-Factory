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
related: []
version: 1
---
# 预算与时长

模型价格全部来自目录，为演示 credits，不等同于服务商真实账单。视频按秒计费，按模型单价和合法输出秒数计算；Wan3 等 billing_basis 可能还包含实测输入视频秒数。图像按张或模型目录单位，LLM 按 usage 和 token 价格（缺失时按既有估价）。不能把按次单价当作所有视频成本。

先 estimate_cost 核验已解析素材与参数；它只读，不会创建、批准或执行计划，也不能把未来节点 ID 当成已存在工件。完整 DAG 的权威报价和编译在 V4。

区分规划额度与生成预算；子委派额度来自父剩余额度。预览和修复均有增量成本，不把重复调用藏在原报价中。未获得审批不能开始生成；额度不够时说明可调整方案，不擅自更改用户约束。

重做报价仅包含实际重做节点及受影响后代，可复用工件零新增模型费。总片长是交付时长，模型计费秒数可因输入、重试、裁切、转场而不同。展示这两者，避免“最终两分钟只会计费两分钟”的误解。

来源：app/tools/budget.py、chat_cost.py、specs/estimate_cost.py；v3 契约 V.11。
