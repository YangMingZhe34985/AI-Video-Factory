# V10 隔离评测

真实调用须已有用户授权；单次测试轮共享同一个 `EVAL_WORK_DIR`，不得换目录绕过累计上限。
使用 conda `video-factory` 的 Python。脚本只读取白名单 DashScope 凭据，禁用 dotenv 自动加载，数据库与存储均在临时目录，MQ 关闭。

```powershell
$env:EVAL_WORK_DIR = "$env:TEMP/cinecrew-v10-<本轮唯一标识>"
python backend/scripts/v3_eval/eval_v3.py all
python backend/scripts/v3_eval/eval_v3.py c3_story c5_novel c3_story c5_novel
python backend/scripts/v3_eval/summarize.py
```

- HTTP 层只允许指定 DashScope 文本/视觉模型，累计最多 800 次；先持久化预留，再发请求；失败/未知请求也占用次数。
- 图片上限为 0；视频适配器仍阻断。禁止媒体生成、上传、外部检索等其他 HTTP。不通过模型的 Mock 标志推断“零真实请求”，使用独立请求计数。
- 结果按 Run ID 独立保存；`result_<case>.json` 只是最新结果便捷副本。每个 Run 保留完整计划、逐轮实际 usage、委派树、选择引用和编译问题码。
- token 缺失明确记录，不把字符数当真实 token；账本 credits 为目录演示价，不是人民币账单。
- 图片/视频内容质量和真实媒体供应商接入不在此轮验收范围。

## 混合执行

保持同一 `EVAL_WORK_DIR`，使用 V10a 尚未批准的 Run。`hybrid.py` 要求显式设置 `EVAL_MOCK_MEDIA=1`：真实规划和视觉理解不变，只替换媒体适配器；Job 通过本地同步调度执行，不连接 Redis。需提供可用的本地 FFmpeg（`FFMPEG_BINARY`）。

```powershell
$env:EVAL_MOCK_MEDIA = '1'
python backend/scripts/v3_eval/hybrid.py delivery --run-id <第一份长片Run>
python backend/scripts/v3_eval/hybrid.py failure-auto --run-id <单镜头Run>
python backend/scripts/v3_eval/hybrid.py failure-manual --run-id <另一单镜头Run>
python backend/scripts/v3_eval/hybrid.py story --run-id <另一份长片Run>
python backend/scripts/v3_eval/hybrid.py choice --run-id <三候选Run>
python backend/scripts/v3_eval/hybrid.py crash
```

前五项分别记录审批动作、状态、来源计划、Patch、报价与账本；失败保存 JSON 并返回非零退出码，不自动放宽批准条件。Mock 图片/视频带占位标记，可本地解码、拼接和下载，不能代表画质。媒体适配器阻断计数与 HTTP 白名单审计共同证明零真实生成；固定的 Mock 零计数字段本身不是网络抓包证据。

`story` 在批准前还会使用同 Run 的原始 Plan 与审阅后的 PatchDraft 校验范围：仅允许目标视频及其专属首/尾帧提示词变化，拒绝修改其他镜头、共享角色、型号、时长或引用；报价与实际账本也必须匹配。公开 `diff_preview` 会脱敏，不作为引用未变的唯一证据。此检查不能替代对提示词语义和真实画质的人工判断。

强杀用例只覆盖“付费成功回执已提交、Agent/checkpoint 尚未推进”的边界，检查重启第一步不发新请求、不增费用，然后继续新规划回合。HTTP 在途强杀的供应商结算不在此用例范围；未知请求仍禁止盲目重发。活跃计时在强杀前未提交的区间可能丢失，不能据此声称任意中断的时间统计精确。

## 一次性 MySQL 验证

用户批准后，在 Docker Desktop 可用且本地已有固定镜像 `mysql:8.4.4` 时执行；脚本不会隐式拉取镜像。`Work` 必须是 TEMP 下尚不存在的目录，端口必须空闲且不能为 3306。

```powershell
./backend/scripts/v3_eval/Docker.ps1 -Backend "$PWD/backend" -Work "$env:TEMP/cinecrew-v10c-<唯一标识>" -Port 3307
```

脚本仅创建带 `cinecrew-v10c` 前缀的本次容器与数据卷，绑定 `127.0.0.1`；`finally` 删除这两个对象并记录结果。`mysql_verify.py` 完全禁用 dotenv，不读取项目配置，网络仅允许本次 loopback MySQL 端口，全部模型调用用 Stub/Mock。临时自签名 TLS 只用于此隔离容器，不是生产 TLS 配置示例。

验证实际 `db upgrade`（不使用 `create_all` 或自动补表）：空库到 `20261019_005`；从 v2 头 `20261018_002` 插入四条历史记录再升级并比对；一个 v3 Mock 交付；两个独立线程/会话的 Run 同时规划。`mysql-evidence.json` 和 `docker-lifecycle.json` 保存证据。`--sqlite-self-check` 仅用于检查脚本自身，不算 MySQL 验收。双 Run 测试不代表同 Run 多 worker 抢占、Redis/MQ 吞吐或生产压力测试。
