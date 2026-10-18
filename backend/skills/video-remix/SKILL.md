---
name: video-remix
description: 区分保留、裁切和重生成原片镜头，保持原片区间与输出时长语义。
when_to_use: 用户希望重排、保留部分原视频，或替换特定镜头时。
agents:
- producer
- director
- critic
- repair
tools:
- analyze_video
- get_task_status
- list_models
- estimate_cost
related:
- video-transform
- budget-planning
version: 2
blueprint:
  builder: app.plans.blueprints.video_remix:build
  params_schema: {"$defs":{"PlanSpec":{"additionalProperties":false,"properties":{"title":{"maxLength":200,"minLength":1,"title":"Title","type":"string"},"mode":{"default":"from_scratch","enum":["from_scratch","remix"],"title":"Mode","type":"string"},"style_notes":{"anyOf":[{"maxLength":8000,"type":"string"},{"type":"null"}],"default":null,"title":"Style Notes"},"shots":{"items":{"anyOf":[{"$ref":"#/$defs/RemixShotSpec"},{"$ref":"#/$defs/ShotSpec"}]},"maxItems":20,"minItems":1,"title":"Shots","type":"array"}},"required":["title","shots"],"title":"PlanSpec","type":"object"},"RemixShotSpec":{"additionalProperties":false,"properties":{"shot_id":{"maxLength":64,"minLength":1,"pattern":"^[A-Za-z0-9_-]+$","title":"Shot Id","type":"string"},"first_frame_prompt":{"default":"","maxLength":8000,"title":"First Frame Prompt","type":"string"},"i2v_prompt":{"default":"","maxLength":8000,"title":"I2V Prompt","type":"string"},"image_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Image model selection belongs here, never in image_params.","title":"Image Model Id"},"video_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Video model selection belongs here, never in video_params.","title":"Video Model Id"},"image_params":{"additionalProperties":true,"description":"Image generation parameters only; no model_id.","title":"Image Params","type":"object"},"video_params":{"additionalProperties":true,"description":"Video generation parameters only; no model_id.","title":"Video Params","type":"object"},"action":{"enum":["keep","regenerate"],"title":"Action","type":"string"},"source_start":{"description":"Start of original segment to preserve or replace; source first frame is extracted here.","minimum":0,"title":"Source Start","type":"number"},"source_end":{"description":"End of original segment to preserve or replace. Generated output length is independently set by video_params.duration.","exclusiveMinimum":0,"title":"Source End","type":"number"},"edit_reason":{"maxLength":2000,"minLength":1,"title":"Edit Reason","type":"string"},"first_frame_mode":{"default":"source","enum":["source","generate"],"title":"First Frame Mode","type":"string"}},"required":["shot_id","action","source_start","source_end","edit_reason"],"title":"RemixShotSpec","type":"object"},"ShotSpec":{"additionalProperties":false,"properties":{"shot_id":{"maxLength":64,"minLength":1,"pattern":"^[A-Za-z0-9_-]+$","title":"Shot Id","type":"string"},"first_frame_prompt":{"description":"Static description of the opening frame: subject, pose, scene, lighting.","maxLength":8000,"minLength":1,"title":"First Frame Prompt","type":"string"},"i2v_prompt":{"description":"Motion only: subject action, environment motion, camera movement.","maxLength":8000,"minLength":1,"title":"I2V Prompt","type":"string"},"image_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Image model selection belongs here, never in image_params.","title":"Image Model Id"},"video_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Video model selection belongs here, never in video_params.","title":"Video Model Id"},"image_params":{"additionalProperties":true,"description":"Image generation parameters only; no model_id.","title":"Image Params","type":"object"},"video_params":{"additionalProperties":true,"description":"Video generation parameters only; no model_id.","title":"Video Params","type":"object"}},"required":["shot_id","first_frame_prompt","i2v_prompt"],"title":"ShotSpec","type":"object"}},"additionalProperties":false,"properties":{"plan":{"$ref":"#/$defs/PlanSpec"},"source_artifact_id":{"maxLength":80,"minLength":1,"title":"Source Artifact Id","type":"string"},"goal":{"anyOf":[{"maxLength":2000,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Goal"},"compress_output":{"default":false,"title":"Compress Output","type":"boolean"}},"required":["plan","source_artifact_id"],"title":"Params","type":"object"}
---
# 原片二次创作

先分析用户授权原片，记录每段 source_start / source_end 与事件内容。原片时间范围用于定位素材；生成片段 duration_sec 表示新输出长度，两者不同，不能混填或用原片绝对终点当生成时长。

对每段明确保留、裁切/重排或局部重生成。保留段优先复用原片，不产生模型生成费用；重生成段按模型秒数规则估价。总交付时长来自处理后的全部片段，不能把原片时长和生成时长重复相加。

无法满足时长或模型要求时保留可编辑草稿和具体问题，不丢弃已完成分析，也不擅自截断或改用另一系列。用户修改后复验并复用成功结果。局部失败只修复相关镜头和必要依赖。

本目录同时作为未来 video-remix Blueprint 的知识指南。V2 不登记 builder，不提供计划实例化或执行权限；确定性 Blueprint 由 V4 实现、对齐 v2 行为并验收。

来源：v2 原视频规划与人工草稿修订契约；app/agent/planning.py、transform_director.py。

本 Blueprint 仅生成确定性草稿，不调用模型、不消耗费用；服务端编译、dry-run 与用户批准后才可执行。
params_schema 是作者输入；价格、媒体检查、计划版本与授权均由服务端生成，禁止自行填入。
