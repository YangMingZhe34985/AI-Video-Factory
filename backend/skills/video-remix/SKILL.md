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
# 原视频局部改造

用户要求保留一部分原片、替换另一部分时使用本 Blueprint。analyze_video 提供内容描述，不提供精确镜头检测；source_start/source_end 必须来自用户明确范围或可信时间证据，无法确定且影响保留内容时由 Producer 澄清。

plan.mode=remix，source_artifact_id 为当前 Run 原视频。shots 按最终顺序排列：keep 通过 retain_video_segment 免费裁切；regenerate 只替换指定原片区间。source_start/source_end 是原片选择范围，video_params.duration 是新生成片段时长，两者不能混用。first_frame_mode=source 从替换区间起点抽帧；generate 则需图像提示词和合法图像参数。

不要在 image_params/video_params 内放 model_id；分别使用 image_model_id/video_model_id。默认服务器模型与用户明确视频系列约束仍生效。原片保留部分没有生成费，新片段按实际合法秒数估算；交付总时长是保留时长加新片段时长。默认不额外压缩，经有序拼接、probe/QC 后打包。

## Blueprint 参数摘要（V9c）

正文包含最小完整参数和演示 JSON。已覆盖所需结构时直接使用，不再为形式重复读取 resources/params.schema.json / resources/examples.json；未覆盖字段、复杂嵌套或具体字段错误才按需深读。仍以实际 Schema、编译结果和用户硬约束为准；Skill 不增加工具权限。

演示数据：REPLACE_* 必须换成本 Run 真实工件及已核验模型 ID；示例秒数、角色和构图不代表用户要求、模型上限、价格或批准。未指定模型时从 check_plan 的 model_id=null 草稿取得 resolved_models，再填写要求具体 ID 的 Blueprint；不能从目录排序猜默认。显式系列/禁用约束须覆盖全部视频节点，不能自行换系列。

- params={plan,source_artifact_id,goal?,compress_output?}；原视频必须属于当前 Run，compress_output 默认 false。
- plan 必填 title/mode="remix"/shots（交付顺序）；每段必填 shot_id/action/source_start/source_end/edit_reason，区间必须在真实媒体内。
- keep 只保留范围。regenerate 另填 i2v_prompt/video_model_id/video_params，video_params.duration 独立指定生成秒数；first_frame_mode="source" 从原片起点抽帧，"generate" 另需 first_frame_prompt/image_model_id/image_params。
- image_model_id/video_model_id 可留空由服务器解析，不得嵌入 image_params/video_params；复杂可选字段按需读取完整 Schema。

保留原片 3 秒，替换原片另一段为新生成 5 秒（演示）：
<!-- blueprint-params-example:0 -->
```json
{"source_artifact_id":"REPLACE_OWNED_VIDEO_ARTIFACT_ID","compress_output":false,"plan":{"title":"演示局部改造","mode":"remix","shots":[{"shot_id":"keep_1","action":"keep","source_start":0.0,"source_end":3.0,"edit_reason":"保留开场"},{"shot_id":"replace_2","action":"regenerate","source_start":3.0,"source_end":6.0,"edit_reason":"修改后半段动作","first_frame_mode":"source","i2v_prompt":"主体缓慢向前行走","video_model_id":"REPLACE_ALLOWED_VIDEO_MODEL_ID","video_params":{"duration":5}}]}}
```

instantiate_blueprint 只构建并保存草稿，同时返回 issues、estimates、workspace_ref，不调用生成模型。无 issues、费用与已确认需求及预算一致时，Producer 直接 submit_plan({plan_ref:workspace_ref})；无需再读同份草稿或重复 check_plan，Director 返回 plan_ref。提交内部仍会编译及隔离 dry-run，通过后仅进入用户审核，不授予生产许可。

失败或修改后按具体问题修订再校验。禁止输入估价、manifest、plan_version、quote、许可或伪造 origin.blueprint；预算不足不擅自缩短明确时长或放宽指定系列，按既有澄清流程处理。
