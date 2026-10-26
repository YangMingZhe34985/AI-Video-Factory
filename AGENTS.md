# CineCrew 开发协作说明

> 本文件与 `CLAUDE.md` 内容保持一致，Claude Code 与 Codex 共用。修改其中一个时同步修改另一个。

## 当前工作：Agent v3（真正的多 Agent 规划 + 受控执行）

开始任何工作前，按顺序阅读：

1. `docs/agent_v2/PROGRESS.md` 的**最后一条**：上一位开发者停在哪里、下一步是什么。
2. `docs/agent_v2/PLAN.md`：任务看板。
3. 跨任务接口以 `docs/agent_v3/CONTRACTS.md` 为准（v2 功能维护读 `docs/agent_v2/CONTRACTS.md`）。
4. 需要背景时再读 `docs/agent_v3/OPTIMIZATION_20261023.md`（最近一次整体优化）与 `docs/architecture/agent_v3_proposal_claude.md`。

分工（D-063，取代 D-031）：Claude 负责主要实现（修复、提示词与 Agent 行为调优、真实冒烟验证）和评审；Codex 承担用户指定的较大功能或并行任务。两者同时开发时各用独立 worktree，不在对方的工作区切换分支。

完成或停手前：在 `PROGRESS.md` 末尾追加一条交接记录（≤15 行），并更新 `PLAN.md` 中的任务状态。

## 开发流程（D-063，快速流程）

1. **小改动直接做**：单点修复、提示词与 Skill 文案、诊断信息等，在 `DECISIONS.md` 用 1–3 句记录即可。只有接口、数据结构或审批/计费规则变化，才先写决策再改 `CONTRACTS.md`。
2. **测试**：每个任务跑相关的定向测试，合并前跑一次并行全量回归 `bash backend/scripts/test_parallel.sh`（12 组并行，约 11–33 分钟，取决于机器负载）。不再逐任务做串行全量。
3. **验收**：不再设阶段 Gate。每个里程碑跑一次固定的真实冒烟（`backend/scripts/v3_eval/real_e2e.py`：3–4 个短任务，视频合计约 30 秒以内，须用户授权）；平时用只调用文本模型的规划 A/B 对比验证 Agent 行为改动。
4. **报告**：专项报告不超过一页，写结论、失败原因与费用；证据路径放在报告末尾，不在正文逐项罗列。
5. **分支**：一个任务一个分支 `agent-v3/<名称>`，从 `feat/agent-v2` 切出，测试全绿后本地合并回 `feat/agent-v2`。不推送远程、不开 PR，除非用户要求。

## 必须遵守的规则

1. **不破坏经典工作流**（19 节点 DAG、经典 API 与页面）。
2. **接口以契约为准**：实现与 `CONTRACTS.md` 不一致时改实现；确需改接口，先在 `DECISIONS.md` 记录日期、原因与影响，再改契约（小改动按流程第 1 条）。
3. **只改与任务相关的文件**；不要顺手重构无关代码。
4. **工具调用必须受控**：v3 的 Agent 可以通过函数调用**请求**工具，但每次调用都经过 `ToolRegistry.invoke()`（校验、权限、审批、预算、幂等）。视频/图片生成类工具不暴露给任何 Agent，只能作为已批准计划（Plan IR）的节点由确定性运行时执行（D-029）。
5. **真实付费调用**：自动化测试只用 Mock/Stub 与隔离数据库。真实测试必须有明确目的、使用隔离数据库，并在 PROGRESS 中记录调用次数与估算费用。用户已授权的常规范围：文本 LLM（`deepseek-v4.1-flash`）、多模态理解（`qwen3.7-plus`，多张图放在一次调用里）、少量图片生成（D-030）。**视频生成每次都需要用户单独授权**（例如 D-061）。
6. `backend/.env` 与根目录 `.env` 可能指向真实 MySQL 并包含真实密钥：临时启动的实例必须用临时 SQLite（`config_overrides` 或环境变量）和 `MODEL_ADAPTER_MODE=mock`；真实测试只通过 `backend/scripts/v3_eval/safety.py` 的白名单读取 DashScope 凭据，不读取或修改 `.env` 中的数据库配置。

## 环境与命令

- Python：conda 环境 `video-factory`（`C:\Users\MingZheYang\anaconda3\envs\video-factory\python.exe`）。PATH 上的 `python` 是 msys2 版本，缺少依赖。
- FFmpeg：`.venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`，通过 `FFMPEG_BINARY` 环境变量指定（并行回归脚本会自动设置）。
- 后端定向测试（在 `backend/` 下）：`<上面的 python> -m pytest -q <测试文件>`；全量：`bash backend/scripts/test_parallel.sh`。
- 前端构建（在 `frontend-vue/` 下）：`npm run build`
- Vite 开发服务器监听 `localhost`（IPv6），用 `127.0.0.1:5173` 访问会失败。
- 本机使用 Clash（fake-ip）时，`dashscope.aliyuncs.com` 解析到 198.18.x.x；拒绝非公网地址的评测护栏会因此失败，这不是网络故障。

## 语言

文档、提交说明中的正文、交接记录以及和用户的交互均使用中文；代码、标识符与注释沿用仓库现有风格（英文）。
