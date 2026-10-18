# CineCrew 开发协作说明

> 本文件与 `CLAUDE.md` 内容保持一致，Claude Code 与 Codex 共用。修改其中一个时同步修改另一个。

## 当前工作：Agent v3（真正的多 Agent 规划 + 受控执行）

开始任何工作前，按顺序阅读：

1. `docs/agent_v2/PROGRESS.md` 的**最后一条**：上一位开发者停在哪里、下一步是什么（v2 与 v3 共用此交接记录）。
2. `docs/agent_v2/PLAN.md`：任务看板，v3 任务在“Agent v3”一节。
3. v3 任务读 `docs/agent_v3/CONTRACTS.md`（v3 契约，唯一接口来源）；维护 v2 功能时读 `docs/agent_v2/CONTRACTS.md`。
4. 需要背景时再读 `docs/architecture/agent_v3_proposal_claude.md`（v3 方案）；v2 背景见 `agent_v2_proposal_claude.md`。

分工（D-031）：Codex 承担主要实现；Claude 负责契约、规划、评审（各阶段 Gate）、验收与界面美化。

完成或停手前：在 `PROGRESS.md` 末尾追加一条交接记录（格式见该文件开头），并更新 `PLAN.md` 中的任务状态。

## 必须遵守的规则

1. **不破坏经典工作流**（19 节点 DAG、经典 API 与页面）。
2. **契约优先**：`CONTRACTS.md` 是跨任务接口的唯一来源。实现与契约不一致时改实现；确需改契约，先在 `DECISIONS.md` 记录日期、原因与影响的任务，再改契约。
3. **只改任务声明的文件范围**；不要顺手重构无关代码。
4. **工具调用必须受控**：v3 的 Agent 可以通过函数调用**请求**工具，但每次调用都经过 `ToolRegistry.invoke()`（校验、权限、审批、预算、幂等）。视频/图片生成类工具不暴露给任何 Agent，只能作为已批准计划（Plan IR）的节点由确定性运行时执行（D-029）。v2 代码仍遵守“LLM 只产出结构化决策”。
5. **真实付费调用按 D-030 执行**：自动化测试只用 Mock/Stub 与隔离数据库。用户已授权的真实测试范围：文本 LLM（`deepseek-v4.1-flash`）、多模态理解（`qwen3.7-plus`，多张图放在一次调用里，禁止逐图调用）、少量图片生成；**禁止视频生成**。真实测试必须有明确目的、使用隔离数据库，并在 PROGRESS 中记录调用次数与估算费用。
6. `backend/.env` 与根目录 `.env` 可能指向真实 MySQL 并包含真实密钥：临时启动的实例必须用临时 SQLite（`config_overrides` 或环境变量）和 `MODEL_ADAPTER_MODE=mock`。
7. 每个任务一个分支 `agent-v2/<任务ID>` 或 `agent-v3/<任务ID>`，从 `feat/agent-v2` 切出，测试全绿后合并回 `feat/agent-v2`。不推送远程、不开 PR，除非用户要求。

## 环境与命令

- Python：conda 环境 `video-factory`（`C:\Users\MingZheYang\anaconda3\envs\video-factory\python.exe`）。PATH 上的 `python` 是 msys2 版本，缺少依赖。
- 后端测试（在 `backend/` 下）：`<上面的 python> -m pytest -q`
- 前端构建（在 `frontend-vue/` 下）：`npm run build`
- Vite 开发服务器监听 `localhost`（IPv6），用 `127.0.0.1:5173` 访问会失败。

## 语言

文档、提交说明中的正文、交接记录使用中文；代码、标识符与注释沿用仓库现有风格（英文）。
