# CineCrew 开发协作说明

> 本文件与 `CLAUDE.md` 内容保持一致，Claude Code 与 Codex 共用。修改其中一个时同步修改另一个。

## 当前工作：Agent v2

开始任何工作前，按顺序阅读：

1. `docs/agent_v2/PROGRESS.md` 的**最后一条**：上一位开发者停在哪里、下一步是什么。
2. `docs/agent_v2/PLAN.md`：任务看板，找到你要做的任务 ID、依赖与验收标准。
3. `docs/agent_v2/CONTRACTS.md` 中与任务相关的章节：接口与数据结构以此为准。
4. 需要背景时再读 `docs/architecture/agent_v2_proposal_claude.md`（方案）与 `agent_v2_dev_plan.md`（开发计划）。

完成或停手前：在 `PROGRESS.md` 末尾追加一条交接记录（格式见该文件开头），并更新 `PLAN.md` 中的任务状态。

## 必须遵守的规则

1. **不破坏经典工作流**（19 节点 DAG、经典 API 与页面）。
2. **契约优先**：`CONTRACTS.md` 是跨任务接口的唯一来源。实现与契约不一致时改实现；确需改契约，先在 `DECISIONS.md` 记录日期、原因与影响的任务，再改契约。
3. **只改任务声明的文件范围**；不要顺手重构无关代码。
4. **LLM 只产出结构化决策**，不直接调用工具；所有工具调用经过 `ToolRegistry.invoke()`（校验、权限、审批、预算、幂等）。
5. **禁止真实付费调用**：测试只用 Mock 适配器与隔离数据库。任何真实模型调用都需要用户在对话中单独批准。
6. `backend/.env` 与根目录 `.env` 可能指向真实 MySQL 并包含真实密钥：临时启动的实例必须用临时 SQLite（`config_overrides` 或环境变量）和 `MODEL_ADAPTER_MODE=mock`。
7. 每个任务一个分支 `agent-v2/<任务ID>`，从 `feat/agent-v2` 切出，测试全绿后合并回 `feat/agent-v2`。不推送远程、不开 PR，除非用户要求。

## 环境与命令

- Python：conda 环境 `video-factory`（`C:\Users\MingZheYang\anaconda3\envs\video-factory\python.exe`）。PATH 上的 `python` 是 msys2 版本，缺少依赖。
- 后端测试（在 `backend/` 下）：`<上面的 python> -m pytest -q`
- 前端构建（在 `frontend-vue/` 下）：`npm run build`
- Vite 开发服务器监听 `localhost`（IPv6），用 `127.0.0.1:5173` 访问会失败。

## 语言

文档、提交说明中的正文、交接记录使用中文；代码、标识符与注释沿用仓库现有风格（英文）。
