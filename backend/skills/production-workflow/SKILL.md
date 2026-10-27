---
name: production-workflow
description: 经典路径：用户明确要反推提示词、测试提示词或用于生产并保留提示词时，在经典“系列 + 模板”下运行工作流，提示词版本写回模板。
when_to_use: 用户表达生产意图——“反推这个视频的提示词”“测试这几条提示词的效果”“用于生产/做成模板，保留提示词”“放到某系列某模板下”。只想要一段视频或一张图时不用。
agents:
- producer
tools:
- list_templates
- submit_plan
related:
- t2v-prompt-writing
- i2v-prompt-writing
version: 1
---
# 经典路径：在系列与模板下运行工作流（V8 · Claude 2026-10-27）

经典工作流长期稳定：视频理解反推 t2v 提示词 → 改写为首帧 + i2v 提示词 →（可选）R2V / I2I 批量测试 → 打包。经典路径把这条链路放到用户的“系列 + 模板”下运行，作业内产生的每个提示词版本都写回模板（append-only，可在经典“提示词管理”中查看、回滚），作业可在经典作业详情页查看。

## 什么时候走经典路径

- **走**：用户明确要“反推提示词”“测试这些提示词/首帧/i2v/i2i 效果”“用于生产”“做成模板/保留到模板”“放到某系列某模板下”。
- **不走**：只想要一段视频或一张图（“做一段……视频”“画一张……”），即使附带参考视频。照常走私有计划。
- **拿不准**：用 ask_user 出一道选择题（“只要成片” / “用于生产并把提示词保存到模板”），不要默认走经典路径。

## 步骤（目标 2 轮）

1. 第一轮调用 list_templates（用户点名系列或模板时带 query）。用户点名已有模板就用 `{"template_id": ...}`；点名系列并给出新模板名就用 `{"series_id": ..., "new_template_name": ...}`。不能新建系列。没说放哪里时用 ask_user 选择题：列出最相关的 2–3 个已有模板，再加一项“在默认系列下新建模板（名称取自需求）”。
2. 第二轮同一轮调用 write_workspace（brief，production_intent=true）与 submit_plan。brief.deliverable 只能写 video 或 image：只出提示词或含视频分支时写 video，只有图片分支时写 image（实际交付类型由计划的 deliverables 决定，brief 里不能写 prompts）。上传的参考视频在 brief.attachments 里写 role=content_ref。用户明确的比例、时长照常写进 brief，服务端会把它们作为各视频分支的参数，不要写计划根的 duration_constraint。
3. 计划**只有一个** run_workflow_template 节点，model_id 为 null、params 为 {}；交付物只引用这个节点。批准时用户需勾选“写回模板”确认。

## 三种任务与分支

| 任务 | branches | 必填输入 | 交付 |
|---|---|---|---|
| 反推提示词（默认只出提示词） | `reverse_prompts`，通常加 `rewrite_prompts`（拆成首帧 + i2v）；要 R2V 提示词时加 `r2v_prompt` | `source_video_artifact_id`（上传视频的 attachment_id） | `{"kind":"prompts","output":"prompts"}`，`package` 设 false |
| 测试提示词 | 按用户给的类型：t2v → `t2v`；首帧 + i2v → `first_frame_image` + `i2v`；只测 i2v 并给了首帧图 → `i2v` + `first_frame_artifact_id`；R2V → `r2v` + `reference_artifact_ids`；I2I 批量 → `i2i_test` + `i2i_test` 配置 | `prompts` 中对应类型 | videos（有图片时加 images）；package 默认 true |
| 生产任务（默认打包） | `reverse_prompts` + `rewrite_prompts` + `first_frame_image` + `i2v`；用户要 I2I 批量时改为 `i2i_test` | `source_video_artifact_id`，或用户给的 t2v 提示词放进 `prompts.t2v`（此时去掉 `reverse_prompts`） | videos + package |

规则：
- **测试提示词时原样使用用户的提示词**，这正是要测试的对象；不要改写、不要补充。
- 不要同时提供启用分支会生成的提示词（例如启用 rewrite_prompts 时不写 prompts.i2v）。例外：提供 prompts.i2i 时会跳过 i2i 改写，按原文测试。
- I2I 批量测试（i2i_test）还需要 i2v 提示词（prompts.i2v 或 rewrite_prompts 生成）；`i2i_test` 写 `{"mode":"single_male|single_female|couple","test_count":1–8}`，按张数计费。
- 没用到的输入不要写（例如没启用 reverse_prompts 就不写 source_video_artifact_id）。
- 用户点名模型时才写 `models`（槽位 t2v、image、i2v、r2v、i2i_image、i2i_video），否则省略，由服务端按默认与用户约束补全；文本与视频理解节点用经典配置模型，不能指定。
- 编译报错时按 issues 的 code 与 fields 只改出错处，再提交一次。

## 示例（结构可直接套用；模板、附件 ID、名称与提示词必须按需求替换）

反推提示词（在默认系列下新建模板）：
<!-- workflow-example:reverse -->
```json
{"title":"参考视频反推提示词","goal":"反推参考视频的提示词并拆成首帧与 i2v，保存到新模板","nodes":[{"id":"workflow","tool":"run_workflow_template","inputs":{"template_target":{"series_id":"default","new_template_name":"参考视频反推"},"branches":["reverse_prompts","rewrite_prompts"],"source_video_artifact_id":"REPLACE_ATTACHMENT_ID","package":false},"model_id":null,"params":{},"origin":{"agent":"producer","skills":["production-workflow"]},"rationale":"用户要求反推提示词并保存，只出提示词"}],"deliverables":[{"kind":"prompts","node_id":"workflow","output":"prompts"}]}
```

测试首帧 + i2v 提示词（已有模板）：
<!-- workflow-example:test -->
```json
{"title":"测试首帧与 i2v 提示词","goal":"用用户给的两条提示词各生成一次，结果写回模板","nodes":[{"id":"workflow","tool":"run_workflow_template","inputs":{"template_target":{"template_id":"REPLACE_TEMPLATE_ID"},"branches":["first_frame_image","i2v"],"prompts":{"first_frame_image":"用户给的首帧提示词原文","i2v":"用户给的 i2v 提示词原文"}},"model_id":null,"params":{},"origin":{"agent":"producer","skills":["production-workflow"]},"rationale":"按经典分支原样测试用户提示词"}],"deliverables":[{"kind":"video","node_id":"workflow","output":"videos"},{"kind":"image","node_id":"workflow","output":"images"},{"kind":"package","node_id":"workflow","output":"package"}]}
```

生产任务（参考视频 → 成片 + 经典 ZIP 包）：
<!-- workflow-example:production -->
```json
{"title":"参考视频生产","goal":"反推、改写、生成首帧与 i2v 成片并打包，提示词写回模板","nodes":[{"id":"workflow","tool":"run_workflow_template","inputs":{"template_target":{"template_id":"REPLACE_TEMPLATE_ID"},"branches":["reverse_prompts","rewrite_prompts","first_frame_image","i2v"],"source_video_artifact_id":"REPLACE_ATTACHMENT_ID"},"model_id":null,"params":{},"origin":{"agent":"producer","skills":["production-workflow"]},"rationale":"经典完整链路，默认打包"}],"deliverables":[{"kind":"video","node_id":"workflow","output":"videos"},{"kind":"package","node_id":"workflow","output":"package"}]}
```

## 说明

- 作业内经典节点生成的提示词不在审批范围内（经典路径的固有特性），审批冻结的是分支、模型、参数、初始提示词与素材以及单价；计划卡会写明将写入的系列与模板。
- 经典路径计划不支持补丁，需要修改时重新提交计划。
- 结果卡提供“打开经典作业详情”链接；提示词版本可在经典“提示词管理”中查看。
