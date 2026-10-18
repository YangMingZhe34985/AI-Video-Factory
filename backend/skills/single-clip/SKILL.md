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
version: 1
---
# Single clip 计划指南

先判断一个合法时长的连续片段是否可满足意图。已有首帧可以直接规划 i2v；需固定人物但无适用首帧时先准备参考一致的图像；t2v 仅在能力、开关与约束允许时作为候选。

不为简单片段编造多幕故事或强制调用所有 Agent。模型系列约束作用于最终选择的每个视频生成节点，不能通过改变路线绕过。

动作复杂度与时长相配，报价包含实际图像和视频节点；未知或冲突时长才澄清。全部生成由批准后的确定性运行时执行。

本目录是 V2 知识指南，无 blueprint builder；V4 实现 single-clip 后验收与 v2 的节点、参数与费用一致。

来源：app/agent/director_lite.py；v3 契约 V.4.2。
