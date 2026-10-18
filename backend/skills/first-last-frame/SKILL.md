---
name: first-last-frame
description: 评估首尾帧生视频作为候选衔接方式，并揭示质量和依赖限制。
when_to_use: 需要明确起止姿态、镜头桥接，且目录与开关支持该模式时。
agents:
- director
- prompt_smith
- critic
tools:
- list_models
- estimate_cost
related:
- i2v-prompt-writing
version: 1
---
# 首尾帧候选

先查询所选模型是否真实接入 first_last_frame，以及相应特性开关是否启用；提供两张已授权图片，参数和时长满足目录。不能仅凭服务商宣传推定集成能力。

首帧和尾帧分别描述静态状态，动作提示描述两状态之间在给定时间内可完成的运动。若尾帧需要生成，则增加对应图像节点、费用和前置关系；已有工件可复用，不重复生成。

此模式可接入，但与首帧生视频相比的画质和稳定性尚未实测。计划说明实验性、候选理由与可替代方式，不宣称必然更好。不可因不可用而自动切换用户禁止的模型或系列。

来源：app/agent/director_v2.py、plan_check.py 与 v3 契约 V.8。
