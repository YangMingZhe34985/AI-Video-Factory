# Agent v2 任务看板

> 详细说明见 `docs/architecture/agent_v2_dev_plan.md`；接口以 `CONTRACTS.md` 为准。
> 状态：`待开始` `进行中` `完成` `阻塞`。领取任务时把状态改为“进行中”并写上负责方，避免两边同时做。
> 集成分支：`feat/agent-v2`；任务分支：`agent-v2/<ID>`。

## Phase 0 准备

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| P0-1 | 整理分支、建立 `feat/agent-v2`、基线测试 | Claude | — | 完成 |
| P0-2 | 协作文件与 `CLAUDE.md` / `AGENTS.md` | Claude | — | 完成 |
| P0-3 | Phase A 契约（CONTRACTS A 章） | Claude | — | 完成 |

## Phase A 一句话入口

| ID | 任务 | 负责 | 依赖 | 契约 | 验收要点 | 状态 |
|---|---|---|---|---|---|---|
| A1 | 能力目录：`models.capabilities` 列、迁移、种子数据（演示单价） | Codex | P0-3 | A.4 | 迁移幂等；种子模型都有完整能力字段；经典页面不受影响 | 完成（a3b9ef0） |
| A2 | 按秒计费：`estimate_model_cost`，替换固定常量 | Codex | A1 | A.5 | 5 秒与 15 秒费用不同；缺少 pricing 时回退并告警；预算相关测试更新后全绿 | 完成（66b35bb） |
| A3 | 附件上传接口与归属校验；`/sources` 转调 | Codex | P0-3 | A.3 | 合法图片/视频、各类非法输入、他人附件各有用例 | 完成（625a55a） |
| A4 | `analyze_image` Skill + Intake 节点 + RequestSpec 校验 | Codex（Claude 评审提示词） | A3 | A.6、A.12、A.13 | Mock 下 10 个样例得到预期配方与附件用途；校验失败重试一次 | 完成（9e7edff；提示词待阶段评审） |
| A5 | 澄清协议：`clarify` 中断、`answer` 动作、轮数上限、按默认继续 | Claude | P0-3 | A.7、A.9 | 阻塞题未答不前进；超过轮数取默认并记入假设；非法答案被拒 | 完成（4bf4fc6） |
| A6 | Simple 配方：Director-lite、`generate_image` i2i 扩展、`animate_shot`、v2 图路由（含 remix 与 story_video 过渡） | Codex | A1 A2 A4 A5 | A.8、A.11、A.12 | “西装照 + 人像”无需任何选项完成（Mock）；remix 与旧 from_scratch 回归通过 | 完成（4a12de5；全量 444 passed） |
| A7 | 前端：新输入框、附件、理解卡片、选择题卡片、Simple 计划审批；移除旧字段及界面美化 | Claude（用户指定） | A3 A5（接口）；A6/A8 联调 | A.2、A.7、A.8、A.10 | `npm run build` 通过；空文本不可提交；选择题可提交 | 完成，已与 A6/A8 联调（3a3cd7f、412c2d9、69b13e4） |
| A8 | 兼容：`DEPRECATED_FIELD`、`schema_version` 分图、`serialize` 去除 `shot_count` 依赖、`model_policy` 改读 RequestSpec | Codex | A6 | A.1 | v1 Run 可恢复；v1 字段请求被明确拒绝 | 完成（0578e93；集成全量 473 passed） |
| A-Gate | 阶段评审 | Claude | A1–A8 | — | 见开发计划第 5 节清单 | 完成（69b13e4，合并 7ddd4cb） |

## Phase B 联网与看图

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| B0 | B 章契约 | Claude | P0-3 | 完成（2bd4e33） |
| B1 | 检索适配器接口 + Mock；`fetch_page` 与 SSRF 防护 | Codex | B0 | 完成（93c552d、af4618f；集成全量 589 passed） |
| B2 | `image_search` + `download_reference` | Codex | B0 | 完成（5d8ec10、74af298；集成全量 589 passed） |
| B3 | Research Agent 与候选形象选择题 | Codex（Claude 评审） | B1 B2 A5 | 完成（c244d60；提示词待 B-Gate 评审） |
| B4 | 提示注入测试集 | Codex | B3 | 完成（2673459；新增 23 项，集成全量 589 passed） |
| B5 | 前端：资料卡片（主题摘要与来源、实体候选图）（CONTRACTS B.11） | Claude | B3（接口） | 完成（f40c7cf，合入 776172f） |
| B-Gate | 阶段评审 | Claude | B1–B5 | 完成（589 passed；见 PROGRESS） |

## Phase C 长片规划与审核 A

契约：CONTRACTS C 章。整个阶段在 `AGENT_STORY_V2_ENABLED=true` 下开发，默认关闭，不影响现有 `story_video` 过渡路由。

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| C0 | C 章契约 | Claude | B-Gate | 完成 |
| C1 | Creative v2：StoryPackage（剧本、角色、风格）、校验、澄清、角色参考来源（research / attachment / generate）（C.3） | Codex | C0 | 完成（2276aed；33 项新增回归） |
| C2 | 数据表 `agent_plan_versions` / `agent_shot_tasks`、迁移与 SchemaService 兼容；计划版本服务（C.7） | Codex | C0 | 完成（3d66b89；24 项回归） |
| C3 | Director v2：ProductionPlan、衔接与 `depends_on` 推导、选型、费用估算（C.4、C.10） | Codex | C1 C2 | 完成（edcc023；25 项相关回归） |
| C4 | Prompt Smith 逐镜头 Skill + Plan Check（含一次自动修订）（C.5、C.6） | Codex | C3 | 完成（8292cb3、de2655d；37 项回归） |
| C5 | 预览生产：角色定妆图与关键帧（经 ToolRegistry 的图片 Skill）、`previewing` 轮询、stale 判定（C.2、C.7） | Codex | C2 C4 | 完成（1e46510、f451dc4；集成全量 729 passed） |
| C6 | 审核 A 动作、Run 视图字段、错误码、注入与恢复回归（C.8、C.9、C.13） | Codex | C5 | 完成（5ddb56b、636486e；集成全量 729 passed） |
| C7 | 前端：分镜板（时长条、角色卡、镜头时间线、编辑抽屉、重做过期关键帧）（C.11） | Codex（功能；视觉美化由 Claude 负责） | C6（接口） | 完成（a855450、5b74903；15 项回归、构建与真实 Mock 联调通过） |
| C-Gate | 阶段评审 | Claude | C1–C7 | 完成（730 项回归；分镜板视觉重做，见 PROGRESS） |

## Phase D 依赖调度与局部修复

契约：CONTRACTS D 章。依用户最新指令 D0–D5 由 Codex 完成；C-Gate、界面美化及 D-Gate 保持 Claude 负责。生产开关默认关闭；只做 Mock 验收。

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| D0 | D 章契约、显式授权、失败与级联确认 | Codex | C1–C7 | 完成（95d9909；补充 D-020–D-022） |
| D1 | 任务编译、依赖调度、worker恢复与共用MQ | Codex | D0 D2 | 完成（c40b81f、677c158；集成 920 passed） |
| D2 | extract_frame、animate_shot首尾帧、审核选型与工件保护 | Codex | D0 | 完成（fc8faac、e3f6d00、8440fbb；集成 920 passed） |
| D3 | 失败分类、免费恢复、有界局部自动修复 | Codex | D0 D1 | 完成（9adaa00、aa81b3c、66eb0e1；集成 920 passed） |
| D4 | 生产动作、只读报价、重做级联确认、审核B | Codex | D1 D3 | 完成（018d0df、ecc761e、9d64e63；集成 920 passed） |
| D5 | 生产看板功能及Mock联调（视觉美化由Claude负责） | Codex | D0 D4 | 完成（c15a7d0；29项前端回归、构建与Mock浏览器验收） |
| D-Gate | 阶段评审 | Claude | D0–D5 | 完成（921 项回归；生产看板美化暂缓，见 PROGRESS） |

## Phase E 成片交付

契约：CONTRACTS E章。E1–E4由Codex完成，E-Gate及界面美化留Claude；本轮仅Mock。
| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| E1 | Agent默认不压缩、统一下载策略与兼容 | Codex | D0–D5 | 完成（9f71bbe、7af8d0e、66f8007；全量991项通过） |
| E2 | compose_video、主片/显式压缩副本 | Codex | E1 | 完成（e675828、3688929；有效媒体与恢复验收） |
| E3 | probe/QC、Editor恢复与素材包 | Codex | E2 | 完成（9f186df、44c2756、1032209；D-Gate集成148项通过） |
| E4 | 成片播放器、鉴权下载、交付状态与恢复 | Codex（功能） | E3 | 完成（365886a、084afef、e45ac36；40项前端回归、构建与Mock联调） |
| E-Gate | 阶段评审 | Claude | E1–E4 | 完成（993 项回归；见 PROGRESS） |

## Phase F
见开发计划第3节，F1–F3；本轮不进入F。

## 待用户决定（不阻塞 Phase A）

- 各 Agent 角色使用的 LLM（见 D-002）
- 真实单价、自动审批阈值、F2 付费评测预算（见 D-003）
- 检索服务商（见 D-004）


## 模型目录升级与任务中心（用户追加，先于后续 Agent 开发）

契约：M/T章、D-025。保持旧百炼URL与默认模型；仅Mock隔离测试。
| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| M0 | 官方能力核查、兼容契约与并行边界 | Codex | E1–E4 | 完成 |
| M1 | 五模型目录、多模式/系列匹配、分档按秒估算与经典兼容 | Codex | M0 | 完成（76610ef、af55b83；集成1165项通过） |
| M2 | Wan3统一异步适配与首尾接线 | Codex | M0 | 完成（b69dba3、b02b37a；集成1165项通过） |
| M3 | Qwen3异步适配、多图输出、百炼DeepSeek与集成回归 | Codex | M0 | 完成（24ed7f8、38e22c4、1792ad1；集成1165项通过） |
| T1 | 统一只读任务中心API/功能页面与私有队列边界 | Codex（功能） | M0 | 完成（feea8f9；50项前端回归、构建与Mock浏览器验收） |
| MT-Gate | 模型升级/任务中心审计与界面美化 | Claude | M1–M3 T1 | 完成（1278 项回归；电脑端美化，见 PROGRESS） |

## Wan3 Agent 多模态贯通（用户追加）

契约W章、D-026；仍旧百炼URL、只做Mock；用户已授权完成后推送GitHub。
|ID|任务|负责|依赖|状态|
|---|---|---|---|---|
|W0|输入/时长/费用/审核与执行契约|Codex|M1–M3 T1|完成|
|W1|受控媒体、网页快照、Wan3校验|Codex|W0|完成（含音轨边界；D-028）|
|W2|需求理解、独立配方、权威报价与审批|Codex|W0 W1|完成（独立 video_transform）|
|W3|Skill/共享MQ、冻结授权、费用和恢复|Codex|W0 W1 W2|完成（全量基线及受影响233项复测，见PROGRESS）|
|W4|附件与新配方审核功能、Mock浏览器验收|Codex（功能）|W0 W2|完成（63项前端测试、构建及审核主流程；原生文件控件限制见PROGRESS）|
|W-Gate|集成审计及界面美化|Claude|W1–W4|完成（同上；手机端侧栏暂缓）|


2026-10-18 分支交付：用户授权将 feat/agent-v2 快进合入 GitHub main，并同步两分支。本轮只更新交接文档；MT-Gate / W-Gate 仍待 Claude 审计与美化，未开始 Phase F 或付费评测。


## 私人技术资料（用户追加，不推进 Phase F）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| TECH-REPORT | 根据当前代码整理本地私人 Agent 技术报告，并显式排除 Git 跟踪 | Codex | MT-Gate / W-Gate | 完成（仅文档与忽略规则；内容不纳入版本库） |

## Agent v3 真正的多 Agent 规划 + 受控执行

契约：`docs/agent_v3/CONTRACTS.md`（V0 定稿）；决策 D-029 – D-031；方案 `docs/architecture/agent_v3_proposal_claude.md`（r3）。开关 `AGENT_V3_ENABLED` 默认关闭，v1/v2 不受影响。真实调用范围见 D-030（禁止视频生成）。

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| V0 | v3 契约、决策、协作规则修订 | Claude | — | 完成 |
| V1 | 工具层：更名与垫片、ToolSpec/Context 扩展、函数调用导出、`agent_chat`、qwen_chat tools、ScriptedLLM、`analyze_images`、`list_models`/`estimate_cost` | Codex | V0 | 完成（后端全量1505项、前端64项与构建通过；D-032，见PROGRESS） |
| V2 | Skill 库：加载器、`list_skills`/`load_skill`/`read_skill_resource`、首批 Skill | Codex（Claude 审定关键 Skill） | V1 | 完成（关键 Skill 已由 Claude 审定，V-Gate3） |
| V3 | Agent 运行时：卡片/目录、循环、委派、提问、工作区、上限、步骤记录、v3 图骨架 | Codex | V1 | 完成（后端全量 1732 项、前端 64 项与构建通过；D-033，见 PROGRESS） |
| V-Gate1 | V1–V3 评审 | Claude | V1–V3 | 并入 V-Gate3 完成 |
| V4 | Plan IR：编译器、dry-run、通用运行时、预览门、六个 Blueprint、审核动作 | Codex | V2 V3 | 完成（D-034；后端1906项、前端64项与构建通过；Gate待Claude） |
| V5 | Plan Patch：Repair、Director 审阅、增量报价、低风险自动授权 | Codex | V4 | 完成（D-035；后端2000项、前端64项与构建通过；Gate待Claude） |
| V-Gate2 | V4–V5 评审 | Claude | V4 V5 | 并入 V-Gate3 完成 |
| V6 | Agent 上线：七个 Agent 的卡片与提示词、委派策略 | Codex（Claude 审定 Producer/Director/委派策略） | V-Gate2 | 完成（Producer/Director 提示词与委派策略已由 Claude 审定；真实评测见 VGATE3_EVAL） |
| V7 | 界面：协作时间线、通用计划视图、规划额度、Patch 审批 | Codex（功能），Claude（美化） | V6（接口） | 完成（美化 2026-10-20/21：RunPanel/Collaboration/PlanBoard/PatchReview） |
| V-Gate3 | 评审 + 真实 LLM 评测 + v2 对照 | Claude | V6 V7 | 有条件通过（D-038；真实评测与 v2 对照见 docs/agent_v3/VGATE3_EVAL.md；后续问题 V9a–V9e） |
| V9a | 选择门：用户从多个预览候选中选一个，下游引用所选结果（契约先行） | Codex | V-Gate3 | 完成（后端定向289项、前端134项及浏览器通过；最终全量见PROGRESS） |
| V9b | 上下文管理：裁剪/压缩旧工具结果或精简作者手册，降低长片单轮 token | Codex | V-Gate3 | 完成（正式分支34项上下文/额度回归通过；最终全量见PROGRESS） |
| V9c | 简单任务开销：Blueprint 参数摘要进 Skill 正文，减少资源读取轮次 | Codex | V-Gate3 | 完成（正式分支74项通过；Stub简单路径4轮，真实效果待Gate4） |
| V9d | 死节点检测：不通往交付物的付费节点给出编译问题 | Codex | V-Gate3 | 完成（正式分支72项通过；未消费付费节点阻止提交） |
| V9e | 多参考图默认选型：多人同框镜头自动引导到支持多参考的模型 | Codex | V-Gate3 | 完成（29项定向、V9集成后端全量2218项通过；本地合并未推送） |
| V-Gate4 | V9 评审与真实评测复跑（`backend/scripts/v3_eval`） | Claude | V9a–V9e | 有条件通过（2026-10-20；默认开启 v3 前须完成 V11a–V11c） |
| V10a | 真实评测复跑（D-030）：`v3_eval all` 一次，c3、c5 各再跑 2 次；按 PROGRESS“V10 测试任务”的量化目标对照 VGATE3_EVAL | Codex | V9a–V9e | 测试完成；长片审核 3/3、选择门 3/3；简单轮次、长片 token 与角色参考部分未达，详见 V10 报告 |
| V10b | 混合执行测试：真实 LLM 规划 + Mock 媒体执行（零生成费用），端到端覆盖批准、预览门、选择门、生产、内容失败→Repair→Director Patch、用户修订、交付、worker 中断恢复 | Codex | V9a–V9e | 六个执行场景通过；修复 D-038 计时遗漏；修复语义与任意在途崩溃不作通过，详见 V10 报告 |
| V10c | MySQL 迁移与并发验证（一次性独立 Docker 容器，绝不连接 .env 中的数据库） | Codex | 用户已批准（2026-10-19） | 完成：MySQL 8.4.4 四项通过；临时容器/数据卷已删除，真实模型调用 0 |
| V10-Report | `docs/agent_v3/V10_TEST_REPORT.md`：逐项指标、失败根因、调用量与费用 | Codex | V10a V10b V10c | 完成：188/800 次真实调用、真实媒体 0；逐项达标/未达及证据交给 Claude V-Gate4 |
| V11a | **阻塞**：多角色身份输入的确定性校验（节点声明出场角色，编译器要求数据引用覆盖每个角色的参考；依赖边不算身份输入；契约先行） | Codex | V-Gate4 | 完成（D-040 / V.21.1；后端全量2402项及前端构建通过） |
| V11b | **阻塞**：自动修复的意图保真（会删除或改变用户点名的核心元素时不得自动批准，必须人工确认；Run 视图展示改写前后差异） | Codex | V-Gate4 | 完成（D-041 / V.21.2；全量2446项、前端137项/构建及浏览器通过；真实Repair改写触发人工门，批准后Mock交付通过） |
| V11c | **阻塞**：Patch 产物来源标签与实际作者一致（修正 origin.agent 写成 repair 的问题） | Codex | V-Gate4 | 实现完成（D-042 / V.21.3；全量2477项、前端137项/构建及浏览器通过；真实审核B被Mock上传覆盖缺口阻断，未验收） |
| V11d | 简单任务效率：减少 RequirementBrief 结构纠错（Producer 提示词给出完整最小合法示例，或对常见可无损转换的形式做服务端规范化；目标 c1/c6 ≤6 轮） | Codex | V-Gate4 | 完成（D-043 / V.21.4；全量2487项及构建通过；真实c1/c6均5文本轮、无委派，完整剧情无Creative） |
| V11e | 长计划输出截断：记录 finish_reason；长 PlanDraft 支持分批写入或增量更新，避免一次 8k token 输出被截断 | Codex | V-Gate4 | 完成（D-044 / V.21.5；全量2537项及构建通过；真实分批写入有证据，length拒绝分支仅Mock覆盖） |
| V11f | 上下文峰值：长计划只保留最新草稿的完整参数、旧草稿参数投影为引用；目标长片单轮输入峰值 ≤60k token | Codex | V-Gate4 | 完成（D-045 / V.21.6；全量2577项及构建通过；完成的c3峰值56366/57616，c7为58401；c3第二次未完成规划） |
| V11g | 选择门的逐张风格：“N 种风格各一张”时规划为 N 个独立节点汇入选择门（Skill 指导 + 编译器支持多来源候选） | Codex | V-Gate4 | 完成（D-046 / V.21.7；全量2581项及构建通过；真实c5三个独立风格候选汇入choice，画质未测） |
| V-Gate5 | V11 评审：Codex 复跑 c1、c3×3、c5、c6 真实规划与 V10b 修复/修订场景并出报告，Claude 审读 | Claude | V11a–V11g | 未通过（2026-10-21，D-047；见 docs/agent_v3/VGATE5_REVIEW.md；V11c 仅离线通过，c7 比例失败、审核 B 未覆盖；修补 V12a–f 后 V-Gate5b 补验） |
| V12c | **补验前置**：混合评测 Mock 覆盖与诊断（适配器统一走工厂；harness 审批前检查 Run 状态，attention 时报失败节点后停止） | Codex | V-Gate5 | 完成（完整后端2594项、前端构建及隔离审计通过；仅本地合并） |
| V12a | **阻塞**：比例约束链（brief 比例 → 成片关键帧/视频默认值与冲突校验 → 拼接与 QC；定妆/参考图豁免；契约先行） | Codex | V-Gate5 | 实现完成（全量2691项及构建通过；c7真实规划全部成片关键帧/视频/拼接16:9，实物媒体质量未测） |
| V12b | **阻塞**：Research 工具 run 由服务端绑定（模型不再传 run_id，伪造仍拒绝；dossier 错误给合法示例） | Codex | V-Gate5 | 实现完成（全量2724项及构建通过；真实LLM驱动Mock下载省略run_id成功；c3可审核1/2，另一例等待用户选择） |
| V12d | 上下文投影保护最近一次读取的契约资源（token 目标不变） | Codex | V-Gate5 | 实现完成、量化未达（全量2743项及构建通过；真实c7/c3峰值65182/68541，均超过60k，原因见V12_TEST_REPORT） |
| V12e | 编译错误字段级提示（节点、字段、合法引用输入名；不改规则、不接受别名） | Codex | V-Gate5 | 实现完成、量化未达（全量2766项及构建通过；新样本无UNTYPED_REFERENCE，但角色/选型/参数等仍成批纠错） |
| V12f | 意图评估以最终草稿为对象（提示词与卡片文案；判定不放宽） | Codex | V-Gate5 | 完成（完整后端2768项、137前端、构建与独立浏览器通过；仅本地合并） |
| V12c-eval-recovery | 修复默认答题幂等键与审核B范围误报；同一Patch零新增LLM续验（D-053） | Codex | V12a–V12f | 完成；完整后端2799项/144文件、构建及隔离通过；原Patch零新增LLM续验通过，原失败保留 |
| V-Gate5b | 补验：c7×1、c3×2、审核 B 局部修订、c1×1（真实调用 ≤150，媒体全 Mock），Claude 审读 | Codex（测试）、Claude（审读） | V12a–V12f | 有条件通过（2026-10-22，D-054；比例/Research/Mock覆盖/审核B通过；c3-2 时长失败与峰值见 VGATE5_REVIEW.md 末节；默认启用须 V13a + V-Gate6） |
| V13a | **阻塞**：时长约束（brief 明确时长与容差 → 编译器按实际片段总长校验，PLAN_DURATION_MISMATCH → QC 核对成片时长；契约先行） | Codex | V-Gate5b | 实现完成（2026-10-22；D-055 / V.23.1；2898项后端与前端构建通过，待V-Gate6真实验收） |
| V13b | 无损规范化减少成批纠错（非生成节点 characters=[] 忽略；compose/QC 只给比例时推导尺寸） | Codex | V-Gate5b | 实现完成（2026-10-22；D-056 / V.23.2；2946项后端与前端构建通过） |
| V13c | 上下文压缩：取代的失败 check_plan 回执与重复模型目录只保留最新；峰值门槛 ≤80k token | Codex | V-Gate5b | 待开始 |
| V13d | 小修：固定事件须在镜头内完成；投影标记专用错误码；统计识别续验标签；审定标记更新 | Codex | V-Gate5b | 待开始 |
| V-Gate6 | 默认启用前验收：c3×2、c7×1 + 双人身份抽检（真实图片 ≤6、视频 0、文本/视觉 ≤120），Claude 审读 | Codex（测试）、Claude（审读） | V13a–V13d | 待开始 |
| V8 | 经典路径：生产意图、系列 + 模板、`run_workflow_template`（契约开工前补写） | Codex | V-Gate3 | 按用户指令暂跳过 |

