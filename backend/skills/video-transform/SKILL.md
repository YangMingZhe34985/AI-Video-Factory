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
version: 1
---
# Video transform 计划指南

区分 reference、edit、extend；edit/extend 必须选择唯一授权源视频，reference 没有主源。源视频不是参考中的普通重复项，保持输入清单与实际语义一致。

视频延长给出完整最终时长；用户追加秒数需结合实测原片时长。输入/输出限制与价格来自目录和媒体检查，不能手填虚构秒数。不可行方案保留可编辑草稿，复用已完成分析。

复杂原片剪辑重排使用 video-remix 知识；不要用 transform 替换用户要求的逐镜头保留。未经审核不调用生成。

本目录为 V2 知识指南，无 blueprint builder。V4 才实现确定性 video-transform Blueprint，并对齐 v2 变换路径的模型、参数与权威费用。

来源：app/agent/transform_director.py、transform_plan.py；v3 契约 V.4.2。
