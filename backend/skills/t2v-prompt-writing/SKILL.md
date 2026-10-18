---
name: t2v-prompt-writing
description: 在能力和一致性要求允许时编写文生视频的场景与运动描述。
when_to_use: 单镜头无需固定参考身份且目录确有文生视频能力时。
agents:
- director
- prompt_smith
tools:
- list_models
- estimate_cost
related:
- single-clip
version: 1
---
# 文生视频候选

先确认目录支持 t2v、用户没有必须保留的参考身份或指定首帧，以及该路径满足时长与模型系列要求。t2v 不是默认通用降级方案；不能为了绕过 i2v 参数限制或指定模型系列而切换路径。

提示词合并主体、场景、构图、光线、动作与运镜，保持一个可在片段时长内完成的事件。对人物跨镜头一致性要求高时应优先评估角色参考和 i2v 方案。

v2 多镜头故事路径限定 i2v，本 Skill 不改变该限制；v3 的具体允许路径以计划编译和目录为准。质量未实测，不将接口接入等同于可用质量结论。

来源：app/agent/director_lite.py、director_v2.py 与模型目录约束。
