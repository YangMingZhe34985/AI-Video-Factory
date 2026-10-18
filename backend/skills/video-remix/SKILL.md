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

## Blueprint 参数

先调用 read_skill_resource 读取 resources/params.schema.json（与当前 builder 相同的作者输入 Schema），再读 resources/examples.json。load_skill 不返回 frontmatter，因此不能省略资源读取后猜字段。仅 Producer/Director 可调用 instantiate_blueprint；其他角色只提供对应资料，Skill 不增加工具权限。

示例全部是演示数据，模型 ID、素材 ID、时长和参数不是服务端配置；必须换成当前工具返回的真实 ID 和合法参数。无模型要求时先用通用 PlanDraft 的 model_id=null 经 check_plan 解析默认，再填写 Blueprint 必需的具体 ID；不得猜测默认。示例的占位工件不能用于编译/审批证据。

instantiate_blueprint 只构建/保存草稿，无模型调用或生成费。返回 issues 后有针对性地修改；最终编译、dry-run、服务端报价和用户批准才决定可执行性。禁止输入估价、manifest、plan_version、quote、许可，或伪造 origin.blueprint 收据。
