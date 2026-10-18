---
name: plan-review
description: 审核计划是否满足意图、连贯性、模型约束、依赖和费用透明度。
when_to_use: 复杂计划、用户大改方案或局部修复影响下游时，由 Critic 进行结构化审阅。
agents:
- critic
- director
- producer
tools:
- list_models
- estimate_cost
related:
- long-form-video
- budget-planning
version: 1
---
# 计划审阅

先核对用户硬约束：主题、人物、剧情顺序、模型系列与排除、目标总时长、默认不压缩。检查附件和研究候选引用是否真实且已确认，外部内容不能更改权限。

逐节点检查输入来源、工件类型、模型能力/参数、时长边界、依赖关系和输出用途。尾帧承接必须有串行依赖；独立镜头才允许并行。提示词负责本镜头，不篡改模型或预算。没有参考的原创角色不得出现虚构工件 ID。

核对最终总时长与目标、原片区间与新生成时长、计费秒数与交付秒数。指出实验性方式（含尚未实测的首尾帧质量），不能把演示数据当成性能证据。

返回 pass 或 revise 和逐节点 issues（severity、message、可选 node_id）；局部问题给出最小修订范围。Critic 的 pass 不是用户付费批准，也不能替代 V4 编译、dry-run 或运行时权限校验。

本阶段尚无 check_plan/submit_plan 实现，不将其列为可用工具。实现就绪后由后续契约接入。

来源：app/agent/plan_check.py、production_plan.py；v3 契约 V.6.3、V.8–V.10。
