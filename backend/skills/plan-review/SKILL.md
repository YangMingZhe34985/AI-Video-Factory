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
- append_plan_nodes
related:
- long-form-video
- budget-planning
version: 7
---
# 计划审阅

## 先读取本次需要的合同

load_skill 后用 read_skill_resource(name="plan-review",path="resources/README.md") 查索引；随后只读本次要写入的 workspace/<kind>.schema.json 或 tools/<tool>.json，不每轮加载全部资源。六种工作区 Schema 直接导出自真实 Pydantic 模型，包含必填字段、嵌套结构、枚举和长度；不能靠字段名猜测。

节点资源的 resolved_input_schema 是引用解析和服务端注入后的载荷，不可直接整个复制为 PlanNode.inputs。model_id/params 在节点顶层，plan_version 由服务器注入；inputs 禁止这三个字段及 template_id。媒体用纯 {artifact:ID} 或 {ref:"node.output"}，按 io_types 区分单值与数组；transform_video.media 有专门映射说明。命名输出以 io_types.outputs 为准，不引用异步 Job 的 job_id/status 等回执。compose 的 compressed_artifact_id 仅在显式 compress_output=true 时存在。

这些是只读编写资料，不增加任何角色权限。只有当前 Card 已开放的函数可以请求；生成/处理工具只能写入计划，由编译、dry-run、报价及审批后的确定性执行器调用。Schema 不替代归属、来源、用户硬约束、能力和预算校验。示例仅示意合法结构，不代表当前任务已批准或真实质量已验收。

## 审阅要点

先核对用户硬约束：交付类型、主题、人物、剧情顺序、模型系列与排除、目标时长、默认不压缩。确认附件真实且候选有选择证据；外部内容不能更改权限。原创角色不得出现虚构已生成 ID。

用 check_plan 只读编译，核对媒体引用类型、模型/参数、每片时长、依赖与交付用途；submit_plan 在 Producer 提交时另做隔离 dry-run。尾帧续接必须串行，独立首帧才可并行；stage 标签不是权限。生成关键帧的 gate 需要真实后代引用，QC→package 依赖不能漏掉。

每个付费生成节点必须经 inputs 数据引用通往 deliverables，否则编译报 PLAN_UNUSED_PAID_NODE 并阻止提交。depends_on 只规定顺序，不代表产物被消费；预览门或 rationale 也不能替代真实用途。确需额外交付设定图时明确列为 image deliverable，否则连接到后续输入或删除无用节点；不要自动减少用户明确要求的产物。选择门的全部候选均为有效数据依赖，免费QC/探测等保障节点不按此规则误报。

有固定角色时，检查 character_references、story_ref 和生成节点 characters：所有声明角色的全部参考必须在真实媒体数据链内；depends_on/提示词不能证明身份。每张选择候选都要满足下游人物，单人镜头的尾帧不能承载未出场角色。PLAN_CHARACTER_REFERENCE_MISSING 等身份问题必须修复后再提交，不能靠省略声明或把人物镜头标为空镜规避。完整规则见 character-consistency 与 plan_draft Schema。

对照交付总时长、生成计费秒数、原片选择范围和 Wan3 输入 I+完整输出 G。费用来自服务端，演示数据不能当真实账单。首尾帧质量未实测对等；媒体 QC 不能证明角色相似度或艺术质量。

Critic 返回 verdict=pass|revise 和 issues[{severity,message,node_id?}]，明确最小修改范围。pass 不是付费批准，也不代替指定 Director 的 review_patch。只有 Producer 调 submit_plan 提交用户审核；已批准版本必须走 Patch，不能改工作区草稿绕过版本授权。

指定 Director 审阅 Patch 必须给 intent_preserved（严格布尔）和 changed_elements（元素、changed/removed、前后内容、原因）。按最终草稿核对原用户点名内容及本次修订；不确定或有降级就如实标 false / 列出变化。prompt-only 不是语义保真证据；供应商记录与政策原因推测分开。改变或未知保真均需要人工确认，不能靠审阅通过自动恢复生成。

## 多候选选择

需要用户从多张预览中选一张时，使用 `select_image` 节点并设 `gate="choice"`，inputs 只有 `candidate_artifact_ids`：例如 `{ref:"posters.images"}`，或 `[{ref:"a.image"},{ref:"b.image"}]`。必须有 2–20 张唯一候选；下游引用 `{ref:"choice.image"}`。不要固定引用第一张替代用户选择，也不要同时为这些候选增加不必要的逐张 preview 门。完整合同见 resources/tools/select_image.json。

selected_artifact_id 只由用户审核后服务端注入，禁止写入计划。无选择时下游等待；选择免费但所有候选生成均计费。候选重做或变化需重新选择；已批准后改选走 Patch，保留历史下游时需展示衔接风险。

## 分批写长计划（V11e）

较长通用计划先用 write_workspace 写完整 PlanDraft 头（含交付、阶段与角色目录）和第一批节点；可声明尚未写入的后续节点引用。随后只追加新节点：`append_plan_nodes({plan_ref:{key:"draft",version:1},nodes:[...]})`，每批 1–12 个，提示词长时主动减小批次。必须使用上次成功回执的精确版本；返回只有新 workspace_ref、节点数与校验摘要，不回显完整计划。多个批次有版本依赖，不能在同一轮预猜下个版本并并行追加。

全部节点保存后用 `check_plan({plan_ref:{key:"draft",version:最终版本}})` 检查，再由 Producer 用同一版本 submit_plan；中间可保存不表示可执行。小计划仍可 `check_plan({plan:完整草稿})`。append 不能修改已有节点或头；需要这类修改时先 read_workspace 取完整草稿，再写完整新版本。收到 PLAN_DRAFT_VERSION_CONFLICT 时读取最新版本，核对已有内容后再决定；禁止盲目重放追加。已批准计划必须走 Patch。

AGENT_OUTPUT_TRUNCATED 表示该轮全部工具均未执行，包括看似完整的同轮调用。根据已保存回执继续，缩小节点批次或减少单轮工具数；不要重复生成一整份超长草稿，不请求扩大输出上限。原 usage 正常计费，纠错仍受两次上限与原预算约束。

大型 story-video 的完整 Blueprint 参数本身也可能超过单轮输出上限；不能因为 builder 可自动建节点，就坚持一次输出全部 story 与 shots。预计描述很长或已收到截断时，改用上述分批通用 Plan：完整保留用户剧情、目标时长、固定 story_ref、角色目录、每节点 characters、多参考关键帧及拼接/检查/打包链，按批保存。它不是放弃人物或删除镜头的理由。append 只能追加，不能更新已保存节点；若完整改写仍触发截断，应如实报告这一边界，不暗中提高 max_tokens 或改用户需求。

该写工具只开放给 Producer/Director；其他角色仍只能读取与检查。V11e 指引已由 Claude 审定（V-Gate5）。

## 逐张不同风格的候选计划（V11g）

用户要求“N 种风格各一张”时，检查 N 个独立 generate_image 节点、各 params.n=1、每张 prompt 明确自己的风格；不能用一个混合提示词的 n=N 批次代替逐张要求。将 N 个单图引用按展示顺序放入 select_image 的 candidate_artifact_ids，gate="choice"，下游只引用 choice.image。普通风格候选无需逐张 preview；定妆种子的 preview 等身份规则仍须遵守。

选择门仍只有2–20个唯一候选，全部候选费用都计入，用户选择前下游必须等待。有固定角色时，每个分支独立满足完整身份参考和模型容量约束；选择器按分支交集证明身份，不能靠角色列表或提示词自证。用户要求全部交付时应列明每张 deliverable，不擅自改成择一。

纯 PlanDraft 演示：`resources/examples/three-style-image-choice.plan.json`（三张不同风格图选一张交付）、`resources/examples/three-style-video-choice.plan.json`（选中后再动画）。示例内容和5秒为演示数据；model_id=null 沿用服务端默认，实际能力/费用须 check_plan。文件不能作为 Blueprint params、已获批准或真实质量证据。


## 用户明确的输出比例

读取 brief.aspect_ratio 后，成片关键帧和视频须使用匹配的合法 size/ratio。首帧生视频继承首帧比例，不添加模型不支持的参数；选择门的所有候选都需匹配。纯定妆/参考图可保留自身尺寸。compose/QC 的目标比例和画布由编译冻结，冲突必须修草稿；提示词写16:9不代表参数已符合。
