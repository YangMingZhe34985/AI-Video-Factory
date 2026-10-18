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
| D-Gate | 阶段评审 | Claude | D0–D5 | 待开始 |

## Phase E–F

见开发计划第3节，任务ID：E1–E4、F1–F3。本轮不进入E/F。

## 待用户决定（不阻塞 Phase A）

- 各 Agent 角色使用的 LLM（见 D-002）
- 真实单价、自动审批阈值、F2 付费评测预算（见 D-003）
- 检索服务商（见 D-004）
