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
