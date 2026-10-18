---
name: clarification
description: 对会改变创作方向或浪费预算的不确定性提出简短选择题。
when_to_use: 身份候选、故事方向、互相冲突的要求或不可行时长不能可靠推断时。
agents:
- producer
- research
- creative
- director
- repair
tools: []
related:
- intent-analysis
version: 1
---
# 有边界的二次交互

优先使用已有文字、附件分析和已答问题；能用合理默认解决的小问题不打断。每轮最多三个具体问题，提供可辨别的选项、建议及影响；界面允许用户自由输入。不要把镜头数、模型参数、技术配方变成必填表单。

研究候选应带已核验参考图与来源 ID。区分“搜索排名高”与“已证实主流”；有多个互不相同形象且会影响身份时交给用户确认。不能发明候选、URL 或附件 ID。

只有 Producer 面向用户提问。其他 Agent 将问题和已完成的部分结果结构化退回上层，由 Producer 合并去重；不越权发布问题。已回答问题（包括明确采纳的默认）不重复询问，用户后续更改则记录新版本。

等待回答时不能进入视频生成。回答写入 clarification 工作区条目供协作读取；超过轮数上限返回明确缺口，不能无限循环或擅自假定获得付费审批。

来源：app/agent/clarify.py、intake.py、research.py；v3 契约 V.6.4。
