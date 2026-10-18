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
# Single clip 计划指南

先判断一个合法时长的连续片段是否可满足意图。已有首帧可以直接规划 i2v；需固定人物但无适用首帧时先准备参考一致的图像；t2v 仅在能力、开关与约束允许时作为候选。

不为简单片段编造多幕故事或强制调用所有 Agent。模型系列约束作用于最终选择的每个视频生成节点，不能通过改变路线绕过。

动作复杂度与时长相配，报价包含实际图像和视频节点；未知或冲突时长才澄清。全部生成由批准后的确定性运行时执行。


来源：app/agent/director_lite.py；v3 契约 V.4.2。

本 Blueprint 仅生成确定性草稿，不调用模型、不消耗费用；服务端编译、dry-run 与用户批准后才可执行。
params_schema 是作者输入；价格、媒体检查、计划版本与授权均由服务端生成，禁止自行填入。
