# V-Gate5 评审结论（Claude · 2026-10-21）

审读对象：`docs/agent_v3/V11_TEST_REPORT.md`、D-040–D-046、契约 V.21.1–V.21.7、V11a–g 合并提交（`3cf0685`…`85918ed`）及 Skill 增补。抽查了报告中三项根因对应的源码，结论与报告一致。

## 结论：未通过，需补修后补验（V12 + V-Gate5b）

V11 研发本身质量高：七项实现都先写决策和契约，逐阶段跑全量，失败没有被掩盖，真实评测的边界写得很诚实。但这一轮暴露了三项会直接影响真实用户的缺陷，加上审核 B 场景完全没有覆盖，所以不能判通过；**默认开启 v3 继续阻塞**。

| 项目 | 判定 | 依据 |
|---|---|---|
| V11a 身份数据链 | 通过 | c3 #1/#3、c7 的双人镜头都经“定妆 → 多参考关键帧 → 视频”的真实引用链；只写 depends_on 不算 |
| V11b 意图保真 | 通过 | 真实 Repair 弱化“跳舞”，Director 判 false，PATCH_INTENT_CHANGED 阻止自动批准，人工批准后交付 |
| V11c 来源标签 | **仅离线通过** | 审核 B 没有走到修订，真实路径未覆盖 |
| V11d 简单任务效率 | 通过 | c1/c6 各 5 轮、无委派（V10 为 8/8） |
| V11e 分批写入 | 通过 | c3/c7 真实分批追加有证据；截断分支仅 Mock 覆盖，可接受 |
| V11f 上下文峰值 | 通过，需调整 | 完成样本峰值 56k/58k token；但起草所需的工具契约被投影掉，见 V12d |
| V11g 逐张风格 | 通过 | c5 三个独立 n=1 节点汇入选择门 |
| c3 可审核率 | 达到下限 | 2/3；失败那次的直接原因是 Research 拿不到可信 run_id（V12b） |
| c7 需求保真 | **失败** | 用户要求 16:9，空镜视频被补成 9:16，关键帧都是方图（V12a） |
| 审核 B 局部修订 | **未覆盖** | 预处理绕过 Mock 工厂，触达上传入口后被护栏拦截（V12c） |
| 安全 | 护栏有效，覆盖缺口 | 没有真实上传或媒体 HTTP；“零越界尝试”目标失败的原因是 Mock 覆盖缺口，不是泄漏。目标保留 |

## 抽查确认的根因

1. **比例约束断链**：`blueprints/common.py` 有 `aspect_ratio`，但通用 PlanDraft 路径不读取 brief 中的比例；作者省略 size/ratio 时，编译器补的是模型默认值（方图、9:16），也不与 brief 交叉校验。
2. **Research 可信上下文**：`fetch_page`、`download_reference`、`capture_reference_page` 都让模型传 `run_id`，再用 `require_run(ctx, data.run_id)` 校验；ToolContext 本来就有真实 run，模型却看不到，只能自己编。护栏拦截是对的，问题出在接口设计。
3. **预处理绕过适配器工厂**：`NodeRunner._i2i_test_image_adapter_payload` 遇到 `wan2.7-image` 时直接 `DashScopeMultimodalSyncAdapter(model=model)`，而 `ADAPTERS` 里已注册 `dashscope_multimodal_sync`。评测替换工厂对它无效。
4. **字段纠错成本高**：c3 #3 有 11 次、c7 有 25 次 `UNTYPED_REFERENCE`（image/images/media 写错），错误信息只有一句“Only declared typed inputs may contain references”，不给字段名和合法字段，Agent 只能重读全部契约后整稿重写。
5. **契约被投影**：`agents/context.py` 超过软目标后，从最早的轮次开始投影 `read_skill_resource` 结果；只保护最新的 `load_skill`，没有保护最新一次读取的契约资源。c3 #3、c7 都在投影后起草出错，再重读契约恢复。时间相关、未证明因果，但成本低、值得修。

## 对报告中待审取舍的裁定

- **Director 恢复“跳舞”后仍判 false**：保守结果可以接受，人工门本来就该在这种不确定时介入。但 reason 写的是 Repair 原稿的问题，不是最终草稿，对用户有误导。V12f 只改提示词和展示：评估对象是**最终草稿对比用户原需求**，reason 描述最终草稿；拿不准时仍判 false。
- **定妆图不强制成片比例**：同意。比例约束只作用于成片用的关键帧、视频和拼接输出，身份定妆图、参考图除外。
- **c3 未委派 Creative**：粗纲已有完整事件顺序和结局，按 V.21.4 由 Director 拆镜头是正确的，不算跳过创作。
- **Skill 增补（D-040–D-046）**：内容审定通过。V12 期间顺手把各 Skill 中“待 V-Gate5 复审”的标记改为“已由 Claude 审定”，并递增版本。

## V12 任务（交 Codex，顺序 V12c → V12a → V12b → V12d → V12e → V12f → V-Gate5b）

先做 V12c，因为它决定补验能否跑通；V12a/b 是用户可见的缺陷。

- **V12a 比例约束链（阻塞）**：契约先行。
  - brief 里用户明确的比例写入可校验字段，没指定就保持现有默认，不猜；
  - 编译器：成片用的关键帧、视频节点省略 size/ratio 时，按 brief 比例和模型能力选取默认值；显式参数与 brief 冲突时报阻塞问题，并写明节点、当前值、期望值；
  - 身份定妆图、参考图豁免（以节点角色或 characters 定妆规则判定，不靠提示词）；
  - compose 携带目标比例和分辨率，QC 核对成片比例；
  - 补测试：复现 c7 的结构（省略 size/ratio + brief 16:9）必须得到 16:9 的关键帧和视频参数，或被拒。
- **V12b Research 可信 run 上下文（阻塞）**：`fetch_page`、`download_reference`、`capture_reference_page` 的 run 由服务端从 ToolContext 绑定，从模型可见 Schema 中移除 `run_id`（或改为可选：省略时用当前 run，与当前 run 不同仍拒绝）；保留作用域校验和隔离。补测试：模型不传 run_id 能成功；伪造 run_id 仍被拒。同时让 research_needs、dossier 的错误回执给出合法结构示例。
- **V12c 混合评测 Mock 覆盖与诊断（补验前置）**：
  - `_i2i_test_image_adapter_payload` 改用 `get_adapter("dashscope_multimodal_sync", model=model)`，经典 I2I 行为不变，补一条经典路径选择同一适配器的回归；
  - 排查其他直接构造适配器的地方，一并改走工厂；
  - 混合 harness 审批预览门前必须确认 Run 处于 awaiting_gate，Run 进入 attention 时输出失败节点的错误码后停止，不再继续审批；
  - 补离线回归：评测 Mock 工厂下 wan2.7-image 的参考预处理不进入上传入口。
- **V12d 契约投影调整**：每个 `(name, path)` 最近一次成功的 `read_skill_resource` 结果与最新 `load_skill` 同等保护，只投影被更新读取取代的旧副本；token 目标（≤60k）不变，字符软目标允许超出。补测试。
- **V12e 编译错误提示**：`UNTYPED_REFERENCE`、`INVALID_NODE_MODEL` 等的 details 带上节点、工具、出错字段和该工具合法的引用输入名（例如 generate_video 的 first_frame_artifact_id；compose 的 compress_output 属于 inputs）。只改错误信息，不改校验规则、不接受别名。目标：c3/c7 不再出现成批同类纠错。
- **V12f 意图评估文案**：Director 提示词与 plan-review 中写明评估对象是最终草稿对比用户原需求；Patch 卡片显示的理由对应最终草稿。判定规则不放宽。
- **V-Gate5b 补验**（D-030；真实调用 ≤150 次，图片/视频生成 0，媒体全部 Mock，沿用隔离目录规则，本轮 118 次另计）：
  - c7 ×1：期望 16:9 落实到全部成片关键帧、视频和拼接参数；
  - c3 ×2：期望 Research 不再因 run_id 被拒，至少 1 次进入审核，最好 2/2；
  - 审核 B：基于新规划的 c3 计划，只改第三镜，验证 Patch 范围、可信作者（V11c）、其他镜头复用与重新交付；
  - c1 ×1：效率回归（≤6 轮）。
  - 报告追加到 `V11_TEST_REPORT.md` 末尾“补验”一节，或新建 `V12_TEST_REPORT.md`，交 Claude 审读。

## 仍未验证（不阻塞本 Gate）

真实媒体画质、身份相似度、逐张风格的实际画风；真实选择执行；HTTP 在途崩溃；同 Run 多 worker 争用；MQ 吞吐。默认开启 v3 前至少需要一次少量真实图片生成的身份抽检（D-030 允许范围内），放在 V-Gate5b 之后另行安排。
