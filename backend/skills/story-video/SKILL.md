---
name: story-video
description: 多镜头故事计划指南：连接故事、角色参考、镜头依赖和审核节点。
when_to_use: 需要多个镜头完成叙事的中长视频时。
agents:
- director
- creative
tools:
- list_models
- estimate_cost
related:
- long-form-video
- character-consistency
version: 1
---
# Story video 计划指南

从用户需求、已确认角色参考和 StoryPackage 出发，保留情节与目标时长。Director 拆镜头并决定衔接，Prompt Smith 按镜头写提示，不把技术参数交还用户逐项填表。

原创角色先规划受审核的角色/关键帧预览，明确预览门后继依赖。继承尾帧串行，独立首帧可并行；引用真实工件或结构化未来节点输出，不伪造 ID。

模型能力、总时长与各节点估价需校验。预览门和视频批准是运行时能力，当前知识文档不授予调用权限。画质、角色一致性和服务商真实费率尚未实测。

本目录为 V2 知识指南，无 builder；V4 实现 story-video Blueprint（包括角色/关键帧预览门）并验收数据流、费用和 v2 对应语义。

来源：app/agent/creative_v2.py、director_v2.py、prompt_smith.py；v3 契约 V.4.2、V.8。
