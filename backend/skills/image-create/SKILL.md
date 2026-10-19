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

## Blueprint 参数摘要（V9c）

正文包含最小完整参数和演示 JSON。已覆盖所需结构时直接使用，不再为形式重复读取 resources/params.schema.json / resources/examples.json；未覆盖字段、复杂嵌套或具体字段错误才按需深读。仍以实际 Schema、编译结果和用户硬约束为准；Skill 不增加工具权限。

演示数据：REPLACE_* 必须换成本 Run 真实工件及已核验模型 ID；示例秒数、角色和构图不代表用户要求、模型上限、价格或批准。未指定模型时从 check_plan 的 model_id=null 草稿取得 resolved_models，再填写要求具体 ID 的 Blueprint；不能从目录排序猜默认。显式系列/禁用约束须覆盖全部视频节点，不能自行换系列。

- params={plan,goal?}；plan 必填 recipe="image_create"、title、rationale、image，不填 video。
- image 必填 mode="t2i"、model_id、prompt；可选 reference_attachment_ids=[]、params={}、n=1（整数1–4）。t2i 不带参考，n 不与 params.n 冲突。
- plan 可选 assumptions=[]（最多10条）；title 1–200、rationale 1–1000、prompt 1–8000字符；goal 可省略。model_id 不放 params。

单张文生图（演示）：
<!-- blueprint-params-example:0 -->
```json
{"plan":{"recipe":"image_create","title":"演示创作","rationale":"根据实际需求决定路线，不直接执行示例","image":{"mode":"t2i","model_id":"REPLACE_DEFAULT_IMAGE_MODEL_ID","prompt":"保持主体身份，柔光下的干净构图","reference_attachment_ids":[],"params":{},"n":1}}}
```

未指定模型时的 check_plan({plan:下列草稿}) 形状（先替换真实素材、提示词、张数与时长；Plan 完成输出是 image/images/video，不是 Job 回执）：
<!-- blueprint-default-plan:0 -->
```json
{"title":"演示创作","goal":"演示创作","nodes":[{"id":"image","tool":"generate_image","model_id":null,"inputs":{"mode":"t2i","prompt":"保持主体身份，柔光下的干净构图","reference_artifact_ids":[]},"params":{"n":1},"origin":{"agent":"producer","skills":[]},"rationale":"根据实际需求决定路线，不直接执行示例"}],"deliverables":[{"kind":"image","node_id":"image","output":"images"}]}
```

instantiate_blueprint 只构建并保存草稿，同时返回 issues、estimates、workspace_ref，不调用生成模型。无 issues、费用与已确认需求及预算一致时，Producer 直接 submit_plan({plan_ref:workspace_ref})；无需再读同份草稿或重复 check_plan，Director 返回 plan_ref。提交内部仍会编译及隔离 dry-run，通过后仅进入用户审核，不授予生产许可。

失败或修改后按具体问题修订再校验。禁止输入估价、manifest、plan_version、quote、许可或伪造 origin.blueprint；预算不足不擅自缩短明确时长或放宽指定系列，按既有澄清流程处理。
