# Agent v2 决策日志

> 格式：编号 · 日期 · 决定 · 原因 · 影响。修改契约前必须先在这里追加一条。

## D-001 · 2026-10-17 · 采用 Claude 版 Agent v2 方案
- 决定：以 `docs/architecture/agent_v2_proposal_claude.md` 为下一轮开发方案；开发按 `agent_v2_dev_plan.md`，由 Claude 与 Codex 协作完成。
- 原因：用户对比两份方案后认为方向一致、该方案考虑更全面。

## D-002 · 2026-10-17 · 各 Agent 的 LLM 暂不确定
- 决定：每个角色的模型都做成配置项（A.13），留空时回退到现有默认；Agent 代码不硬编码模型 ID。
- 原因：项目沿用的视频/图像/语言模型已经落后，用户计划后续更换。
- 影响：A1 能力目录必须让“换模型 = 改数据”成立；F1 评测后再定具体模型。

## D-003 · 2026-10-17 · 预算与单价暂不确定
- 决定：能力目录种子使用演示单价；`AGENT_AUTO_APPROVE_CREDITS` 默认 0（所有计划都需要用户审批）；F2 付费评测在用户给出预算前不执行。
- 原因：视频生成费用高，用户需要时间考虑。
- 影响：A1、A2、A6、F2。

## D-004 · 2026-10-17 · 检索服务商暂不确定
- 决定：B 章只定义统一的检索接口；开发与测试期使用 Mock 适配器。
- 影响：B0、B1、B2。

## D-005 · 2026-10-17 · 首尾帧生视频作为候选方式
- 决定：首尾帧模型已确认可接入，但画质能否达到首帧生视频尚未验证。Phase A 只开放 i2v；`first_last_frame` 在 D2 开放，是否默认使用由 F2 的 A/B 评测决定。
- 影响：A.8 `VideoStep.mode`、A.12 `animate_shot`。

## D-006 · 2026-10-17 · 澄清不设自动超时
- 决定：选择题没有超时自动继续；非阻塞题提供“按默认继续”按钮，阻塞题必须回答。
- 原因：worker 侧定时恢复会增加复杂度，且用户离开期间不应该自动产生费用。
- 影响：A5；开发计划中 A5 的“超时走默认值”验收项以此为准。

## D-007 · 2026-10-17 · story_video 在 Phase C 之前走过渡路由
- 决定：Intake 判定为 `story_video` 时，暂时进入现有 from_scratch 节点，镜头数按“目标时长 ÷ 所选 i2v 模型最大时长”向上取整（上限 20）。
- 原因：Phase A 删除了“镜头数”字段，需要保持长片功能可用，直到 Creative v2 / Director v2 完成。
- 影响：A6、A8；Phase C 替换此路由。

## D-008 · 2026-10-17 · 协作说明纳入版本控制
- 决定：根目录 `CLAUDE.md` 与 `AGENTS.md` 内容一致并提交到仓库；旧内容移到 `docs/archive/`；从 `.gitignore` 移除这两项。`codex.md` 仍是旧任务说明，保持忽略。
- 原因：两个工具交替开发，需要共同、可追溯的入口说明。

## D-009 · 2026-10-17 · v1 Run 保留旧图
- 决定：`schema_version` 缺省为 1 的 Run 继续由现有图恢复执行；v1 创建字段对新请求返回 `DEPRECATED_FIELD`。
- 原因：已有 LangGraph checkpoint 只能由原图恢复。
- 影响：A8。

## D-010 · 2026-10-17 · 澄清契约补充（A5 实现时确定）
- 决定：未回答的非阻塞题直接取默认值，`use_defaults` 只是“一次性接受默认值”的显式写法；超过轮数自动取值时，无默认也无推荐的问题取第一个选项（`source=fallback`）；答案记录格式与 `ClarifyState` 状态键写入 A.7；新增错误码 `INVALID_CLARIFICATION`。
- 原因：原契约对“未回答的非阻塞题”与“无推荐的阻塞题被自动取值”未作规定。
- 影响：A6（v2 图需继承 `ClarifyState`）、A7（前端按 `Resolution` 格式展示答案与假设）。

## D-011 · 2026-10-18 · 联网检索的边界（B0）
- 决定：B 章新增权限级别 `external` 与 Run 状态 `researching`；`fetch_page` / `download_reference` 只接受本 Run 检索结果或用户原文中出现过的网址，并对每次请求和重定向做 SSRF 检查；Research 按“结构化计划 → 图调用 Skill → 结构化汇总”完成，LLM 只能按 `result_id` 选择结果，不能输出网址。
- 原因：网页内容不可信，若允许 LLM 自由提供网址，提示注入可以让 Agent 访问内网或任意地址。
- 影响：B1–B4；A.10 状态集合；A7 前端已加入 `researching` 状态。
- 分工：资料卡片前端（B.11）由 Claude 负责，记为任务 B5。

## D-012 · 2026-10-18 · 长片 v2 在开关后开发（C0）
- 决定：新增 `AGENT_STORY_V2_ENABLED`，默认 false；Phase C 的 story_video 只做到分镜确认（`storyboard_approved`），视频生产由 Phase D 接上后再默认开启。`remix` 在 Phase C 保持现有链路。
- 原因：Phase C 结束时还不能产出视频，直接替换过渡路由会让长片功能在 C、D 之间不可用。
- 影响：C1–C7；D 章从 `storyboard_approved` 开始。

## D-013 · 2026-10-18 · 审核 A 与计划版本（C0）
- 决定：新增状态 `previewing` / `awaiting_characters` / `awaiting_storyboard` / `storyboard_approved`；每次 Director 产出、用户编辑、重做都生成计划版本；预览产物按 attempt 保留不覆盖；角色图重做后相关关键帧标记 stale 但不自动重做；`edit_plan` / `approve_storyboard` 携带版本号，不一致返回 409。
- 原因：审核 A 只花图片费用来锁定角色和画面，必须避免用户的修改被并发覆盖，也避免自动连锁重做产生意外费用。
- 影响：C2、C5、C6、C7；A.10 状态集合扩展。

## D-014 · 2026-10-18 · Research 参考图直接作为角色参考（C0）
- 决定：Creative v2 的角色 `reference.source = research` 时直接使用选定候选的 `reference_id`；用户 `identity_ref` 附件同理；只有两者都没有时才生成定妆图并进入 `awaiting_characters`。Plan Check 要求含该角色的生成镜头使用 i2i 并引用参考图。
- 原因：B-Gate 发现选定的参考图尚未接入生成；复用它们可省去定妆图费用并保证形象一致。
- 影响：C1、C4、C5。
- 分工：分镜板前端（C7）建议由 Claude 负责，与 A7 / B5 一致；用户可调整。


## D-015 · 2026-10-18 · 审核费用展示与本轮分工补充
- 决定：用户指定 C1–C7 功能由 Codex 完成，Claude 保留界面美化和 C-Gate；审核视图追加可选的预览实际支出、单项重做报价与模型、服务端时长容差/镜头上限/衔接开关。重做命令响应追加 `action_estimated_credits`。
- 原因：全 Run 累计费用包含规划调用，不等于预览图片费用；角色定妆的模型不在 CharacterReference 内，前端不能自行猜测重做单价。
- 影响：C5–C7；原 C.8 请求体、C.9 必需字段保持兼容，所有报价为按模型目录计算的估算。

## D-016 · 2026-10-18 · 角色审核编辑使定妆图过期时先显式重做
- 决定：`approve_characters` 的编辑若改变定妆输入，保存新版本并将原定妆图标记 stale，保持 `awaiting_characters`；用户明确重做并再次确认后进入关键帧预览。不自动追加定妆费用。
- 原因：旧图片不能被标成符合新外观描述，且修改角色应遵守不自动连锁重做的预算约束。
- 影响：C5–C7；补充 C.8 的角色编辑边界，普通无编辑确认路径不变。
