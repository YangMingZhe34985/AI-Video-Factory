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
# Video transform 计划指南

区分 reference、edit、extend；edit/extend 必须选择唯一授权源视频，reference 没有主源。源视频不是参考中的普通重复项，保持输入清单与实际语义一致。

视频延长给出完整最终时长；用户追加秒数需结合实测原片时长。输入/输出限制与价格来自目录和媒体检查，不能手填虚构秒数。不可行方案保留可编辑草稿，复用已完成分析。

复杂原片剪辑重排使用 video-remix 知识；不要用 transform 替换用户要求的逐镜头保留。未经审核不调用生成。


来源：app/agent/transform_director.py、transform_plan.py；v3 契约 V.4.2。

本 Blueprint 仅生成确定性草稿，不调用模型、不消耗费用；服务端编译、dry-run 与用户批准后才可执行。
params_schema 是作者输入；价格、媒体检查、计划版本与授权均由服务端生成，禁止自行填入。
