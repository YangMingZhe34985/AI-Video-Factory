---
name: image-create
description: 独立图像创作计划指南：将文字目标映射到一幅静态画面。
when_to_use: 用户只希望创作新图像，而非视频或编辑已有参考时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- t2i-prompt-writing
version: 1
---
# Image create 计划指南

理解图像主题、风格和构图，查询 t2i 目录与默认模型；使用清晰静态提示词与合法尺寸。用户要保留附件中的同一人时应重新考虑 i2i，不忽略身份输入。

无需故事分镜、视频秒数或拼接。预估图片费用，给出可审核计划。模型未指定遵循服务器相应默认，不能让用户填写技术必选表单。

本目录是 V2 知识指南，无 builder，不能执行生成。image-create 确定性 Blueprint 由 V4 实现并与 v2 路径对齐验收。

来源：app/agent/director_lite.py；v3 契约 V.4.2。
