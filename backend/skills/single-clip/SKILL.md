---
name: single-clip
description: 单镜头短片计划指南：选最短可行数据流，避免过度协作。
when_to_use: 一个连续场景和事件即可满足用户视频需求时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- i2v-prompt-writing
- t2v-prompt-writing
version: 2
blueprint:
  builder: app.plans.blueprints.single_clip:build
  params_schema: {"$defs":{"ImageStep":{"additionalProperties":false,"properties":{"mode":{"enum":["t2i","i2i"],"title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"reference_attachment_ids":{"items":{"type":"string"},"title":"Reference Attachment Ids","type":"array"},"params":{"additionalProperties":true,"title":"Params","type":"object"},"n":{"default":1,"maximum":4,"minimum":1,"title":"N","type":"integer"}},"required":["mode","model_id","prompt"],"title":"ImageStep","type":"object"},"SimpleDraft":{"additionalProperties":false,"properties":{"recipe":{"enum":["image_edit","image_create","single_clip"],"title":"Recipe","type":"string"},"title":{"maxLength":200,"minLength":1,"title":"Title","type":"string"},"image":{"anyOf":[{"$ref":"#/$defs/ImageStep"},{"type":"null"}],"default":null},"video":{"anyOf":[{"$ref":"#/$defs/VideoStep"},{"type":"null"}],"default":null},"assumptions":{"items":{"type":"string"},"maxItems":10,"title":"Assumptions","type":"array"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"}},"required":["recipe","title","rationale"],"title":"SimpleDraft","type":"object"},"VideoStep":{"additionalProperties":false,"properties":{"mode":{"const":"i2v","default":"i2v","title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"first_frame":{"enum":["user_attachment","generated_image"],"title":"First Frame","type":"string"},"first_frame_attachment_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"First Frame Attachment Id"},"params":{"additionalProperties":true,"title":"Params","type":"object"}},"required":["model_id","prompt","first_frame"],"title":"VideoStep","type":"object"}},"additionalProperties":false,"properties":{"plan":{"$ref":"#/$defs/SimpleDraft"},"goal":{"anyOf":[{"maxLength":2000,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Goal"}},"required":["plan"],"title":"Params","type":"object"}
---
# 单镜头视频计划

一个合法时长的连续片段足够时由 Producer 直接规划，不编造多幕故事或强制委派。已提供适用首帧则只做 i2v；需先构图时增加一张 t2i/i2i 图，不能为每个简单视频无条件重复生图。

当前 Blueprint 只覆盖 i2v，plan.recipe=single_clip，video.first_frame 为 user_attachment（需 first_frame_attachment_id 且不含 image）或 generated_image（需 image 且 image.n=1）。t2v/其他模式可在能力、开关与约束允许时写通用 PlanDraft，不把不支持的模式塞进此 Blueprint。

动作复杂度与合法视频秒数匹配，明确的模型系列约束对所有视频路线有效。报价包含实际发生的图像和视频节点；未知或冲突的关键时长才澄清。

## Blueprint 参数

先调用 read_skill_resource 读取 resources/params.schema.json（与当前 builder 相同的作者输入 Schema），再读 resources/examples.json。load_skill 不返回 frontmatter，因此不能省略资源读取后猜字段。仅 Producer/Director 可调用 instantiate_blueprint；其他角色只提供对应资料，Skill 不增加工具权限。

示例全部是演示数据，模型 ID、素材 ID、时长和参数不是服务端配置；必须换成当前工具返回的真实 ID 和合法参数。无模型要求时先用通用 PlanDraft 的 model_id=null 经 check_plan 解析默认，再填写 Blueprint 必需的具体 ID；不得猜测默认。示例的占位工件不能用于编译/审批证据。

instantiate_blueprint 只构建/保存草稿，无模型调用或生成费。返回 issues 后有针对性地修改；最终编译、dry-run、服务端报价和用户批准才决定可执行性。禁止输入估价、manifest、plan_version、quote、许可，或伪造 origin.blueprint 收据。
