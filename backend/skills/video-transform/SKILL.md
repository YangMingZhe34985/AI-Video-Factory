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

## Blueprint 参数

先调用 read_skill_resource 读取 resources/params.schema.json（与当前 builder 相同的作者输入 Schema），再读 resources/examples.json。load_skill 不返回 frontmatter，因此不能省略资源读取后猜字段。仅 Producer/Director 可调用 instantiate_blueprint；其他角色只提供对应资料，Skill 不增加工具权限。

示例全部是演示数据，模型 ID、素材 ID、时长和参数不是服务端配置；必须换成当前工具返回的真实 ID 和合法参数。无模型要求时先用通用 PlanDraft 的 model_id=null 经 check_plan 解析默认，再填写 Blueprint 必需的具体 ID；不得猜测默认。示例的占位工件不能用于编译/审批证据。

instantiate_blueprint 只构建/保存草稿，无模型调用或生成费。返回 issues 后有针对性地修改；最终编译、dry-run、服务端报价和用户批准才决定可执行性。禁止输入估价、manifest、plan_version、quote、许可，或伪造 origin.blueprint 收据。
