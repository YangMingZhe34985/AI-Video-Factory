---
name: i2v-prompt-writing
description: 将已确定首帧转为符合时长和衔接要求的动作、镜头与节奏提示。
when_to_use: 从首帧生成短片，或用上一镜头尾帧延续动作时。
agents:
- prompt_smith
- director
- repair
tools:
- list_models
related:
- long-form-video
- first-last-frame
version: 1
---
# 首帧到视频

动作提示只描述本镜头内可完成的主体动作、次级运动、运镜和节奏；静态外观由首帧承载，不机械重复大段服饰描述。动作复杂度与目录允许的片段时长相配。

继承上一个镜头尾帧时延续结束姿态、视线与屏幕运动方向，并建立真实前置依赖。不能一边声明尾帧连续，一边把下一镜头与上一段视频并行执行。

本镜头失败优先定位提示拒绝、参数、输入工件或服务异常，保留成功产物。只修改提示不能悄悄改变用户硬约束；费用增加或影响下游时按审核策略确认。

i2v 是受约束候选方式，不宣称所有模型和场景都优于其他模式。首尾帧方式的画质尚未验证，见 first-last-frame。

来源：app/agent/prompt_smith.py、production_repair.py、director_v2.py。
