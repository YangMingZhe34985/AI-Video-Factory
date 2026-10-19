---
name: video-transform
description: 原生视频参考、编辑与延长计划指南，保留正确的源与最终时长语义。
when_to_use: 用户需要单次原生视频变换，而非重排多个镜头时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- wan3-transform
- video-remix
version: 2
blueprint:
  builder: app.plans.blueprints.video_transform:build
  params_schema: {"$defs":{"MediaReference":{"additionalProperties":false,"properties":{"type":{"enum":["reference_image","reference_video","reference_audio","file"],"title":"Type","type":"string"},"artifact_id":{"maxLength":100,"minLength":1,"title":"Artifact Id","type":"string"}},"required":["type","artifact_id"],"title":"MediaReference","type":"object"},"TransformDraft":{"additionalProperties":false,"properties":{"recipe":{"const":"video_transform","default":"video_transform","title":"Recipe","type":"string"},"operation":{"enum":["reference","edit","extend"],"title":"Operation","type":"string"},"title":{"maxLength":200,"minLength":1,"title":"Title","type":"string"},"model_id":{"maxLength":120,"minLength":1,"title":"Model Id","type":"string"},"prompt":{"maxLength":8000,"minLength":1,"title":"Prompt","type":"string"},"params":{"additionalProperties":true,"title":"Params","type":"object"},"media":{"items":{"$ref":"#/$defs/MediaReference"},"maxItems":20,"minItems":1,"title":"Media","type":"array"},"source_artifact_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Source Artifact Id"},"assumptions":{"items":{"type":"string"},"maxItems":10,"title":"Assumptions","type":"array"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"}},"required":["operation","title","model_id","prompt","media","rationale"],"title":"TransformDraft","type":"object"}},"additionalProperties":false,"properties":{"plan":{"$ref":"#/$defs/TransformDraft"},"goal":{"anyOf":[{"maxLength":2000,"minLength":1,"type":"string"},{"type":"null"}],"default":null,"title":"Goal"}},"required":["plan"],"title":"Params","type":"object"}
---
# 全模态参考、视频编辑与延长

需要原生参考生成、编辑或延长时先核对目录能力、集成开关与用户指定系列。plan.operation 只允许 reference/edit/extend；media 中 type 与真实媒体匹配，edit/extend 还需唯一 source_artifact_id，不能把所有输入误标成图片。

输入素材必须通过现有上传/研究获取路径并属于当前 Run；网页/文件只接受工具安全处理后的工件，不把任意 URL 放入模型参数。公开计划不接收模型自报时长、manifest 或费用。

Wan3 的估价按服务端媒体检查得到的输入视频 I 和完整输出 G（I+G），不是只按延长新增秒数。原片时长、用户希望新增时长、目标总时长应分别说明；单段不满足时长/能力则返回具体冲突或改为完整多节点计划，不能静默截短或换系列。

该 Blueprint 产出单个 transform_video 节点及视频交付；不承诺尚未测过的质量、音画保真或任意格式支持。

## Blueprint 参数摘要（V9c）

正文包含最小完整参数和演示 JSON。已覆盖所需结构时直接使用，不再为形式重复读取 resources/params.schema.json / resources/examples.json；未覆盖字段、复杂嵌套或具体字段错误才按需深读。仍以实际 Schema、编译结果和用户硬约束为准；Skill 不增加工具权限。

演示数据：REPLACE_* 必须换成本 Run 真实工件及已核验模型 ID；示例秒数、角色和构图不代表用户要求、模型上限、价格或批准。未指定模型时从 check_plan 的 model_id=null 草稿取得 resolved_models，再填写要求具体 ID 的 Blueprint；不能从目录排序猜默认。显式系列/禁用约束须覆盖全部视频节点，不能自行换系列。

- params={plan,goal?}；plan 必填 operation/title/model_id/prompt/media/rationale，recipe 省略即 video_transform；可选 params={}、assumptions=[]。
- operation=reference/edit/extend；media 为1–20项 {type,artifact_id}，type=reference_image/reference_video/reference_audio/file；仅用真实受控的当前 Run 工件。
- edit/extend 必填 source_artifact_id 且指向 media 中唯一主视频；reference 不填主视频。params.duration 是完整输出 G，输入 I 由服务器测量；model_id 不放 params。
- title 1–200、prompt 1–8000、rationale 1–1000字符；goal 可省略。下例覆盖 reference；编辑/延长或组合媒体不确定时按需读取完整 Schema 和对应示例。

reference：I+G 费用由服务器计算（演示）：
<!-- blueprint-params-example:0 -->
```json
{"plan":{"operation":"reference","title":"演示原生视频变换","model_id":"REPLACE_ALLOWED_TRANSFORM_MODEL_ID","prompt":"按原素材角色与风格延续场景","params":{"duration":10},"media":[{"type":"reference_image","artifact_id":"REPLACE_OWNED_IMAGE_ARTIFACT_ID"}],"rationale":"能力、输入与完整输出时长需服务器验证"}}
```

instantiate_blueprint 只构建并保存草稿，同时返回 issues、estimates、workspace_ref，不调用生成模型。无 issues、费用与已确认需求及预算一致时，Producer 直接 submit_plan({plan_ref:workspace_ref})；无需再读同份草稿或重复 check_plan，Director 返回 plan_ref。提交内部仍会编译及隔离 dry-run，通过后仅进入用户审核，不授予生产许可。

失败或修改后按具体问题修订再校验。禁止输入估价、manifest、plan_version、quote、许可或伪造 origin.blueprint；预算不足不擅自缩短明确时长或放宽指定系列，按既有澄清流程处理。
