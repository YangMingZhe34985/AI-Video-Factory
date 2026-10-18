---
name: video-remix
description: 区分保留、裁切和重生成原片镜头，保持原片区间与输出时长语义。
when_to_use: 用户希望重排、保留部分原视频，或替换特定镜头时。
agents:
- producer
- director
- critic
- repair
tools:
- analyze_video
- get_task_status
- list_models
- estimate_cost
related:
- video-transform
- budget-planning
version: 1
---
# 原片二次创作

先分析用户授权原片，记录每段 source_start / source_end 与事件内容。原片时间范围用于定位素材；生成片段 duration_sec 表示新输出长度，两者不同，不能混填或用原片绝对终点当生成时长。

对每段明确保留、裁切/重排或局部重生成。保留段优先复用原片，不产生模型生成费用；重生成段按模型秒数规则估价。总交付时长来自处理后的全部片段，不能把原片时长和生成时长重复相加。

无法满足时长或模型要求时保留可编辑草稿和具体问题，不丢弃已完成分析，也不擅自截断或改用另一系列。用户修改后复验并复用成功结果。局部失败只修复相关镜头和必要依赖。

本目录同时作为未来 video-remix Blueprint 的知识指南。V2 不登记 builder，不提供计划实例化或执行权限；确定性 Blueprint 由 V4 实现、对齐 v2 行为并验收。

来源：v2 原视频规划与人工草稿修订契约；app/agent/planning.py、transform_director.py。
