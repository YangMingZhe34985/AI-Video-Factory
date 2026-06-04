# 任务

请根据以下失败上下文，判断当前工作流最合理的处理方式，并返回符合 schema 的 JSON。

# Failure Context

```json
{{context_json}}
```

# 要求
- 仅输出 JSON
- 不添加解释
- 若选择 CONTINUE_FROM_NODE，必须提供有效 target_node
- 若选择 RETRY_NODE，可设置合理 sleep_sec
- 优先考虑成功率、成本与流程连续性