---
name: t2i-prompt-writing
description: 把场景与角色约束转为清晰的单帧图像描述。
when_to_use: 生成角色设定图、分镜首帧或没有上传参考的独立图片时。
agents:
- prompt_smith
- director
- creative
tools:
- list_models
related:
- character-consistency
version: 1
---
# 静态画面提示词

每份提示词只描述一个静态瞬间：主体、姿态、环境、构图、光线、视觉风格。用统一 style.prompt_prefix 开头；存在角色时明确身份锁定描述，再写本镜头变化。不要把故事节拍和连续动作塞进单帧。

需要保留参考身份时应选择支持参考的 i2i，而不是声称 t2i 可以直接绑定附件。引用只能用已确认工件 ID；等待角色生成时留下正确依赖，不能捏造占位 ID。

继承尾帧或使用用户现成首帧时不生成新的首帧提示词，也不产生无用的图像节点。只有确实要生成尾帧的候选方案才给尾帧提示词。

Prompt Smith 仅修订被授权的提示字段，不改模型、时长、依赖、参考、预算或审批状态。

来源：app/agent/prompt_smith.py、creative_v2.py。
