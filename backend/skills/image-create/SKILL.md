---
name: image-create
description: 独立图像创作计划指南：将文字目标映射到一幅静态画面。
when_to_use: 用户只希望创作新图像，而非视频或编辑已有参考时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- t2i-prompt-writing
version: 2
blueprint:
  builder: app.plans.blueprints.image_create:build
  params_schema: {"$defs":{"ImageStep":{"additionalProperties":false,"properties":{"mode":{"enum":["t2i","i2i"],"title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"reference_attachment_ids":{"items":{"type":"string"},"title":"Reference Attachment Ids","type":"array"},"params":{"additionalProperties":true,"title":"Params","type":"object"},"n":{"default":1,"maximum":4,"minimum":1,"title":"N","type":"integer"}},"required":["mode","model_id","prompt"],"title":"ImageStep","type":"object"},"SimpleDraft":{"additionalProperties":false,"properties":{"recipe":{"enum":["image_edit","image_create","single_clip"],"title":"Recipe","type":"string"},"title":{"maxLength":200,"minLength":1,"title":"Title","type":"string"},"image":{"anyOf":[{"$ref":"#/$defs/ImageStep"},{"type":"null"}],"default":null},"video":{"anyOf":[{"$ref":"#/$defs/VideoStep"},{"type":"null"}],"default":null},"assumptions":{"items":{"type":"string"},"maxItems":10,"title":"Assumptions","type":"array"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"}},"required":["recipe","title","rationale"],"title":"SimpleDraft","type":"object"},"VideoStep":{"additionalProperties":false,"properties":{"mode":{"const":"i2v","default":"i2v","title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"first_frame":{"enum":["user_attachment","generated_image"],"title":"First Frame","type":"string"},"first_frame_attachment_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"First Frame Attachment Id"},"params":{"additionalProperties":true,"title":"Params","type":"object"}},"required":["model_id","prompt","first_frame"],"title":"VideoStep","type":"object"}},"additionalProperties":false,"properties":{"plan":{"$ref":"#/$defs/SimpleDraft"},"goal":{"anyOf":[{"maxLength":2000,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Goal"}},"required":["plan"],"title":"Params","type":"object"}
---
# 文生图计划

用户只要图像时不新增视频、故事或不必要委派。根据文本起草静态画面，合理选择构图、画幅与张数；明确用户约束优先，缺少的普通创作细节自行补充并说明假设。

plan.recipe=image_create，plan.image.mode=t2i，reference_attachment_ids 为空，video 不填。模型能力与参数以目录和 check_plan 为准；默认模型由服务器解析。image.n 是张数，不将其藏入冲突的 params.n；图像按张或目录计价单位估算。

## Blueprint 参数

先调用 read_skill_resource 读取 resources/params.schema.json（与当前 builder 相同的作者输入 Schema），再读 resources/examples.json。load_skill 不返回 frontmatter，因此不能省略资源读取后猜字段。仅 Producer/Director 可调用 instantiate_blueprint；其他角色只提供对应资料，Skill 不增加工具权限。

示例全部是演示数据，模型 ID、素材 ID、时长和参数不是服务端配置；必须换成当前工具返回的真实 ID 和合法参数。无模型要求时先用通用 PlanDraft 的 model_id=null 经 check_plan 解析默认，再填写 Blueprint 必需的具体 ID；不得猜测默认。示例的占位工件不能用于编译/审批证据。

instantiate_blueprint 只构建/保存草稿，无模型调用或生成费。返回 issues 后有针对性地修改；最终编译、dry-run、服务端报价和用户批准才决定可执行性。禁止输入估价、manifest、plan_version、quote、许可，或伪造 origin.blueprint 收据。
