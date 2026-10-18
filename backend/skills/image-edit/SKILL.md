---
name: image-edit
description: 图像编辑计划指南：明确参考、修改区域与保留条件。
when_to_use: 在现有图片基础上修改人物、服装、场景或风格时。
agents:
- director
- producer
tools:
- list_models
- estimate_cost
related:
- image-edit-portrait
version: 1
---
# Image edit 计划指南

输入为必填需求文字与经授权的图像参考，提取需要改变和保留的内容。选支持 i2i 的目录模型及合法参数，单幅图像无需视频节点、视频时长或长故事分工。

计划清楚标出输入图、提示词、模型与估价；保留人物身份时参考角色一致性规则。提交审核后才允许确定性运行时生成。

这是 V2 的知识指南，没有 blueprint 元数据或可执行 builder。V4 才实现 image-edit 的确定性 Blueprint，需与 v2 对应路径的节点、模型、参数和费用一致。不能声称当前可 instantiate_blueprint。

来源：app/agent/director_lite.py；v3 契约 V.4.2。
