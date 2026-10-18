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
# Image create 计划指南

理解图像主题、风格和构图，查询 t2i 目录与默认模型；使用清晰静态提示词与合法尺寸。用户要保留附件中的同一人时应重新考虑 i2i，不忽略身份输入。

无需故事分镜、视频秒数或拼接。预估图片费用，给出可审核计划。模型未指定遵循服务器相应默认，不能让用户填写技术必选表单。


来源：app/agent/director_lite.py；v3 契约 V.4.2。

本 Blueprint 仅生成确定性草稿，不调用模型、不消耗费用；服务端编译、dry-run 与用户批准后才可执行。
params_schema 是作者输入；价格、媒体检查、计划版本与授权均由服务端生成，禁止自行填入。
