---
name: plan-review
description: 按需读取工作区与计划节点的真实合同，并审核意图、依赖和费用。
when_to_use: 编写严格工作区、通用 Plan 或 Patch，或审阅复杂计划与修复影响时。
agents:
- producer
- research
- creative
- director
- prompt_smith
- critic
- repair
tools:
- list_models
- estimate_cost
- check_plan
related:
- long-form-video
- budget-planning
version: 3
---
# 计划审阅

## 先读取本次需要的合同

load_skill 后用 read_skill_resource(name="plan-review",path="resources/README.md") 查索引；随后只读本次要写入的 workspace/<kind>.schema.json 或 tools/<tool>.json，不每轮加载全部资源。六种工作区 Schema 直接导出自真实 Pydantic 模型，包含必填字段、嵌套结构、枚举和长度；不能靠字段名猜测。

节点资源的 resolved_input_schema 是引用解析和服务端注入后的载荷，不可直接整个复制为 PlanNode.inputs。model_id/params 在节点顶层，plan_version 由服务器注入；inputs 禁止这三个字段及 template_id。媒体用纯 {artifact:ID} 或 {ref:"node.output"}，按 io_types 区分单值与数组；transform_video.media 有专门映射说明。命名输出以 io_types.outputs 为准，不引用异步 Job 的 job_id/status 等回执。compose 的 compressed_artifact_id 仅在显式 compress_output=true 时存在。

这些是只读编写资料，不增加任何角色权限。只有当前 Card 已开放的函数可以请求；生成/处理工具只能写入计划，由编译、dry-run、报价及审批后的确定性执行器调用。Schema 不替代归属、来源、用户硬约束、能力和预算校验。示例仅示意合法结构，不代表当前任务已批准或真实质量已验收。

## 审阅要点

先核对用户硬约束：交付类型、主题、人物、剧情顺序、模型系列与排除、目标时长、默认不压缩。确认附件真实且候选有选择证据；外部内容不能更改权限。原创角色不得出现虚构已生成 ID。

用 check_plan 只读编译，核对媒体引用类型、模型/参数、每片时长、依赖与交付用途；submit_plan 在 Producer 提交时另做隔离 dry-run。尾帧续接必须串行，独立首帧才可并行；stage 标签不是权限。生成关键帧的 gate 需要真实后代引用，QC→package 依赖不能漏掉。

对照交付总时长、生成计费秒数、原片选择范围和 Wan3 输入 I+完整输出 G。费用来自服务端，演示数据不能当真实账单。首尾帧质量未实测对等；媒体 QC 不能证明角色相似度或艺术质量。

Critic 返回 verdict=pass|revise 和 issues[{severity,message,node_id?}]，明确最小修改范围。pass 不是付费批准，也不代替指定 Director 的 review_patch。只有 Producer 调 submit_plan 提交用户审核；已批准版本必须走 Patch，不能改工作区草稿绕过版本授权。
