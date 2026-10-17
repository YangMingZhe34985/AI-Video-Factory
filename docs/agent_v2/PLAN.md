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
| B1 | 检索适配器接口 + Mock；`fetch_page` 与 SSRF 防护 | Codex | B0 | 进行中（agent-v2/B1；隔离工作树） |
| B2 | `image_search` + `download_reference` | Codex | B0 | 进行中（agent-v2/B2；隔离工作树） |
| B3 | Research Agent 与候选形象选择题 | Codex（Claude 评审） | B1 B2 A5 | 进行中（agent-v2/B3；后端编排） |
| B4 | 提示注入测试集 | Codex | B3 | 进行中（agent-v2/B4；先准备测试与复核） |
| B5 | 前端：资料卡片（主题摘要与来源、实体候选图）（CONTRACTS B.11） | Claude | B3（接口） | 待开始 |
| B-Gate | 阶段评审 | Claude | B1–B5 | 待开始 |

## Phase C–F

见开发计划第 3 节，任务 ID：C0–C7、D0–D5、E1–E4、F1–F3。进入对应阶段时由 Claude 先补写契约章节，再把任务展开到本看板。

## 待用户决定（不阻塞 Phase A）

- 各 Agent 角色使用的 LLM（见 D-002）
- 真实单价、自动审批阈值、F2 付费评测预算（见 D-003）
- 检索服务商（见 D-004）
