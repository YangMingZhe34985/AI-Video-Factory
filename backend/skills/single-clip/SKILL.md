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

## Blueprint 参数摘要（V9c）

正文包含最小完整参数和演示 JSON。已覆盖所需结构时直接使用，不再为形式重复读取 resources/params.schema.json / resources/examples.json；未覆盖字段、复杂嵌套或具体字段错误才按需深读。仍以实际 Schema、编译结果和用户硬约束为准；Skill 不增加工具权限。

演示数据：REPLACE_* 必须换成本 Run 真实工件及已核验模型 ID；示例秒数、角色和构图不代表用户要求、模型上限、价格或批准。未指定模型时从 check_plan 的 model_id=null 草稿取得 resolved_models，再填写要求具体 ID 的 Blueprint；不能从目录排序猜默认。显式系列/禁用约束须覆盖全部视频节点，不能自行换系列。

- params={plan,goal?}；plan 必填 recipe="single_clip"、title、rationale、video，可选 assumptions=[]。
- video 必填 model_id、prompt、first_frame；mode 省略即 i2v，params 是模型参数（时长写 params.duration）。已有首帧：first_frame="user_attachment"、必填 first_frame_attachment_id，不填 image。
- 生成首帧：first_frame="generated_image"，不填 first_frame_attachment_id；image 必填 mode/model_id/prompt，n=1。t2i 参考为空；i2i 需非空且唯一的 reference_attachment_ids，params 可省略。
- title 1–200、rationale 1–1000、两类prompt 1–8000字符；goal 可省略。model_id 位于 image/video 顶层，不放 params。

已有首帧直接生视频（演示）：
<!-- blueprint-params-example:0 -->
```json
{"plan":{"recipe":"single_clip","title":"演示创作","rationale":"根据实际需求决定路线，不直接执行示例","video":{"model_id":"REPLACE_ALLOWED_VIDEO_MODEL_ID","prompt":"主体缓慢向前行走，稳定镜头","params":{"duration":5},"first_frame":"user_attachment","first_frame_attachment_id":"REPLACE_OWNED_IMAGE_ARTIFACT_ID"}}}
```

未指定模型时的 check_plan({plan:下列草稿}) 形状（先替换真实素材、提示词、张数与时长；Plan 完成输出是 image/images/video，不是 Job 回执）：
<!-- blueprint-default-plan:0 -->
```json
{"title":"演示创作","goal":"演示创作","nodes":[{"id":"video","tool":"animate_shot","model_id":null,"inputs":{"first_frame_artifact_id":{"artifact":"REPLACE_OWNED_IMAGE_ARTIFACT_ID"},"prompt":"主体缓慢向前行走，稳定镜头"},"params":{"duration":5},"origin":{"agent":"producer","skills":[]},"rationale":"根据实际需求决定路线，不直接执行示例"}],"deliverables":[{"kind":"video","node_id":"video","output":"video"}]}
```

先生成一张首帧再生视频（演示）：
<!-- blueprint-params-example:1 -->
```json
{"plan":{"recipe":"single_clip","title":"演示创作","rationale":"根据实际需求决定路线，不直接执行示例","image":{"mode":"t2i","model_id":"REPLACE_DEFAULT_IMAGE_MODEL_ID","prompt":"保持主体身份，柔光下的干净构图","reference_attachment_ids":[],"params":{},"n":1},"video":{"model_id":"REPLACE_ALLOWED_VIDEO_MODEL_ID","prompt":"主体缓慢向前行走，稳定镜头","params":{"duration":5},"first_frame":"generated_image"}}}
```

未指定模型时的 check_plan({plan:下列草稿}) 形状（先替换真实素材、提示词、张数与时长；Plan 完成输出是 image/images/video，不是 Job 回执）：
<!-- blueprint-default-plan:1 -->
```json
{"title":"演示创作","goal":"演示创作","nodes":[{"id":"image","tool":"generate_image","model_id":null,"inputs":{"mode":"t2i","prompt":"保持主体身份，柔光下的干净构图","reference_artifact_ids":[]},"params":{"n":1},"origin":{"agent":"producer","skills":[]},"rationale":"根据实际需求决定路线，不直接执行示例"},{"id":"video","tool":"animate_shot","model_id":null,"inputs":{"first_frame_artifact_id":{"ref":"image.image"},"prompt":"主体缓慢向前行走，稳定镜头"},"params":{"duration":5},"origin":{"agent":"producer","skills":[]},"rationale":"根据实际需求决定路线，不直接执行示例"}],"deliverables":[{"kind":"video","node_id":"video","output":"video"}]}
```

instantiate_blueprint 只构建并保存草稿，同时返回 issues、estimates、workspace_ref，不调用生成模型。无 issues、费用与已确认需求及预算一致时，Producer 直接 submit_plan({plan_ref:workspace_ref})；无需再读同份草稿或重复 check_plan，Director 返回 plan_ref。提交内部仍会编译及隔离 dry-run，通过后仅进入用户审核，不授予生产许可。

失败或修改后按具体问题修订再校验。禁止输入估价、manifest、plan_version、quote、许可或伪造 origin.blueprint；预算不足不擅自缩短明确时长或放宽指定系列，按既有澄清流程处理。
