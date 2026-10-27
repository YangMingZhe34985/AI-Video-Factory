# 工作区与 Plan 作者合同

旧计划修订若缺少角色目录，可在 Patch 中显式提供 identity_upgrade；有故事时填写准确 story_ref，并通过 replace_node 为生成节点补齐角色。此升级只能首次添加目录，始终人工审批，重做范围和费用可能增加；不得替换既有身份目录或固定故事。

使用 `read_skill_resource`，name 固定为 `plan-review`，path 使用下表中的完整资源路径。只读取当前任务需要的文件；已有同版本资源可复用，不要每轮全量加载。

这些文件是只读知识，不是函数目录或执行许可。生成工具仍不向 Agent 开放。JSON Schema 只检查结构；素材归属、来源回执、模型能力、用户硬约束、预算、实际时长与审批仍由服务端核验。

## 工作区输入

各文件是对应 Pydantic 模型直接导出的 JSON Schema，描述 `write_workspace.payload`，不是整个 write_workspace 入参。调用另需 `key` 和准确的 `kind`；返回的 `{key,version}` 才能用于后续委派/finish，不编造版本。

| kind | 资源 | 主要使用角色 |
|---|---|---|
| brief | resources/workspace/brief.schema.json | Producer |
| research_dossier | resources/workspace/research_dossier.schema.json | Research |
| story | resources/workspace/story.schema.json | Creative |
| plan_draft | resources/workspace/plan_draft.schema.json | Producer、Director；PromptSmith/Critic/Repair 按需读取理解范围 |
| critic_review | resources/workspace/critic_review.schema.json | Critic |
| patch | resources/workspace/patch.schema.json | 服务端指定的 Repair/Director |

- brief 中附件必须完整覆盖本次上传；`transform_source` 必须配套 `transform`，edit/extend 的 `source_attachment_id` 指向唯一主视频。视频模型偏好/排除保留原用户文本，修订不得放宽。
- research_dossier 的 Topic、Candidate、Source 等都有严格子字段。`source_id` 对应实际搜索 `result_id`，网页事实还须成功 fetch；图片候选须下载、分析并绑定同一实体。`selected_candidate_id` 不能由推荐代替。
- 原创角色 source=generate 时尚无工件，artifact_ids 为空；不能把计划中的未来产物写成已生成 ID。
- Patch 通过 `propose_patch({draft})` 提交，指定 Director 用 `review_patch` 审阅；读取 patch Schema 不允许普通角色写补丁或自行启动修复。成功提议/审阅会结束对应委派，不另调 finish。review_patch 另需显式 intent_preserved 和 changed_elements；变化项包含 element/change(removed|changed)/before/after/reason。以最终草稿与用户点名内容比较，不确定不报 true；只有保真且无变化才可能满足自动修复条件。
- `finish` 仍按当前函数 Schema 和角色合同调用；引用字段为 plan_ref/dossier_ref/story_ref 等，不能把工作区完整对象直接代替 `{key,version}`。submit_plan 成功即完成 Producer。

## 计划节点输入与命名输出

`resources/tools/<tool>.json` 每份包含：

- `resolved_input_schema`：引用解析、模型选择和服务端字段注入后，工具实际校验的输入 Schema。
- `io_types.inputs/outputs`：Plan 编译器实际使用的类型与完成输出名。它不是异步 Job 回执 Schema。
- `authoring`：作者字段放置、媒体引用、可选输出与额外语义说明。`plan_node_fields` / `server_injected_fields` 不写入 inputs，`forbidden_input_fields` 在 inputs 中全部禁止。

| tool | 资源 |
|---|---|
| generate_image | resources/tools/generate_image.json |
| animate_shot | resources/tools/animate_shot.json |
| generate_video | resources/tools/generate_video.json |
| transform_video | resources/tools/transform_video.json |
| extract_frame | resources/tools/extract_frame.json |
| retain_video_segment | resources/tools/retain_video_segment.json |
| select_image | resources/tools/select_image.json |
| run_workflow_template | resources/tools/run_workflow_template.json（经典路径，先读 production-workflow Skill） |
| compose_video | resources/tools/compose_video.json |
| probe_media | resources/tools/probe_media.json |
| qc_video | resources/tools/qc_video.json |
| package_story | resources/tools/package_story.json |

生成节点 model_id/params 只放 PlanNode 顶层。未指定模型时 model_id=null，check_plan 按服务器默认和原用户约束解析；不要从 list_models 排序推测默认。非生成节点 model_id=null、params={}。plan_version 由服务端注入，inputs 禁止 model_id/params/template_id/plan_version。

固定角色使用 Plan 顶层 character_references（每角色全部单图 artifact/ref），生成节点顶层 characters（空镜 []），不要写进 inputs。原创定妆为 generate_image、n=1、preview，characters 仅含该角色。story_ref 是同 Run 故事的固定 {key,version}。双角色首帧必须实际引用两角色参考；数据链的选择分支按交集验证，控制边不算身份输入。

媒体字段使用单键 `{artifact:真实ID}` 或 `{ref:"node.output"}`。单图输出不能当数组，数组输出不能放进数组元素再期待自动展开；数组字段可整体引用同类型数组输出，也可由单媒体引用组成。只有工具声明且编译器支持的输入位置可以使用类型匹配的引用，prompt/params 中不允许。json 输出是结构数据，不能当作媒体；json 输入还须符合对应 Schema 与特殊映射，并非任意字典都能接引用。transform_video.media 虽标为 json，仍要求有序数组，内部每项 `{type,artifact_id}` 的 artifact_id 按 reference_image→image、reference_video→video、reference_audio→audio、file→document 特殊校验。

probe_media.media 与 qc_video.passed/checks/warnings 是 json 输出。当前 qc_video 没有 probe 输入，使用 depends_on 指向 probe 表达控制依赖；不要自行添加 probe 字段或把结构数据当视频 ID。

select_image 必须 gate=choice，只写 candidate_artifact_ids；selected_artifact_id 由用户选择后服务端注入。下游用 select_image 节点的 image 输出，不提前固定使用第一张。所有候选都收费，选择本身免费；候选变化需要重选。

引用名必须来自 io_types.outputs：例如 generate_image.image 是首张，images 是数组；animate_shot.video 是视频；extract_frame.artifact_id 是图片；compose_video.artifact_id 是成片；package_story.artifact_id 是包。不要引用 Job 的 job_id/status/artifacts。compose_video.compressed_artifact_id 只在 inputs.compress_output=true 时可用，默认不压缩；打包可选压缩副本必须来自同一 compose。

通用示例：`resources/examples/first-frame-delivery.plan.json`。这是一份纯 PlanDraft 演示：首帧→视频→拼接→probe/QC→打包，带关键帧 gate 和 QC 控制依赖。模型由服务器解析，5 秒只为形状示例，不保证所有配置支持，也不代表当前用户时长。按本次需求改写后必须 check_plan；生产费用、审批及真实质量均不由示例保证。

逐张风格选择示例：`resources/examples/three-style-image-choice.plan.json` 与 `resources/examples/three-style-video-choice.plan.json`。两者都是纯 PlanDraft，使用三个独立 n=1 图像节点汇入 choice 门；前者交付选中图，后者将选中图接至动画输入。逐张 prompt 保留不同风格，禁止用单一 prompt n=3 代替。内容/时长为演示数据，默认模型、费用、身份与审批依原服务端合同；Mock 不验证画风质量。
