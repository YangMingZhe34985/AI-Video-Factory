---
name: image-edit
description: 图像编辑计划指南：明确参考、修改区域与保留条件。
when_to_use: 在现有图片基础上修改人物、服装、场景或风格时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- image-edit-portrait
version: 2
blueprint:
  builder: app.plans.blueprints.image_edit:build
  params_schema: {"$defs":{"ImageStep":{"additionalProperties":false,"properties":{"mode":{"enum":["t2i","i2i"],"title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"reference_attachment_ids":{"items":{"type":"string"},"title":"Reference Attachment Ids","type":"array"},"params":{"additionalProperties":true,"title":"Params","type":"object"},"n":{"default":1,"maximum":4,"minimum":1,"title":"N","type":"integer"}},"required":["mode","model_id","prompt"],"title":"ImageStep","type":"object"},"SimpleDraft":{"additionalProperties":false,"properties":{"recipe":{"enum":["image_edit","image_create","single_clip"],"title":"Recipe","type":"string"},"title":{"maxLength":200,"minLength":1,"title":"Title","type":"string"},"image":{"anyOf":[{"$ref":"#/$defs/ImageStep"},{"type":"null"}],"default":null},"video":{"anyOf":[{"$ref":"#/$defs/VideoStep"},{"type":"null"}],"default":null},"assumptions":{"items":{"type":"string"},"maxItems":10,"title":"Assumptions","type":"array"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"}},"required":["recipe","title","rationale"],"title":"SimpleDraft","type":"object"},"VideoStep":{"additionalProperties":false,"properties":{"mode":{"const":"i2v","default":"i2v","title":"Mode","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"first_frame":{"enum":["user_attachment","generated_image"],"title":"First Frame","type":"string"},"first_frame_attachment_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"First Frame Attachment Id"},"params":{"additionalProperties":true,"title":"Params","type":"object"}},"required":["model_id","prompt","first_frame"],"title":"VideoStep","type":"object"}},"additionalProperties":false,"properties":{"plan":{"$ref":"#/$defs/SimpleDraft"},"goal":{"anyOf":[{"maxLength":2000,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Goal"}},"required":["plan"],"title":"Params","type":"object"}
---
# Image edit 计划指南

输入为必填需求文字与经授权的图像参考，提取需要改变和保留的内容。选支持 i2i 的目录模型及合法参数，单幅图像无需视频节点、视频时长或长故事分工。

计划清楚标出输入图、提示词、模型与估价；保留人物身份时参考角色一致性规则。提交审核后才允许确定性运行时生成。

这是 V2 的知识指南，没有 blueprint 元数据或可执行 builder。V4 才实现 image-edit 的确定性 Blueprint，需与 v2 对应路径的节点、模型、参数和费用一致。不能声称当前可 instantiate_blueprint。

来源：app/agent/director_lite.py；v3 契约 V.4.2。

本 Blueprint 仅生成确定性草稿，不调用模型、不消耗费用；服务端编译、dry-run 与用户批准后才可执行。
params_schema 是作者输入；价格、媒体检查、计划版本与授权均由服务端生成，禁止自行填入。
