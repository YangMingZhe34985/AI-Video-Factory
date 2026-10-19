# Agent v3 V10 测试报告

日期：2026-10-19。执行：Codex；待审定：Claude / V-Gate4。

本轮完成 V10a、V10b、V10c。**测试工作完成，不代表所有量化目标通过**：长片三次都能进入审核，选择门结构三次均正确，混合执行六个场景、MySQL 四项验证通过；简单任务仅 c2 达到六轮目标，长片输入峰值三次均超过 60k，第二次长片丢失完整双角色参考。V-Gate4 保持待 Claude 判定。

## 范围、版本与总用量

遵循 PROGRESS 中“V10 测试任务安排”“用户批准 V10c”、D-030、D-038 及契约 V.20。基线为 `VGATE3_EVAL.md`；未进入 V8，未修改 V7 或其他前端代码。没有为单例调提示词或 Skill，没有更改契约、模型目录或真实 `.env`。

- V10a：基于 V9 集成版本 `d946b68` 补充护栏与指标，提交 `f1e4eb8`。
- V10b：提交 `2170c5e`，新增混合评测和局部范围审计；修复两处 D-038 计时遗漏，详见后文。
- V10c：提交 `d3ab5f5`，只增加独立验证脚本、测试和交接。各任务验证后本地合入 `feat/agent-v2`，未推送、未开 PR。

|阶段|真实文本 / 视觉调用|真实输入 / 输出 token|真实调用的演示 credits|Mock 媒体演示 credits|
|---|---:|---:|---:|---:|
|V10a|153 / 1|4,198,791 / 214,861|44.16300|0|
|V10b 新增|34 / 0|644,688 / 11,629|6.56317|356|
|V10c|0 / 0|0 / 0|0|2|
|合计|**187 / 1 = 188**|**4,843,479 / 226,490**|**50.72617**|**358**|

真实调用 **188 / 800**；真实图片生成 **0**、视频生成 **0**、HappyHorse 调用 **0**。合计 5,069,969 个真实 usage token；单轮最大输入 82,588。没有缺失 usage、未知/未完成 HTTP 记录或被阻断的生成请求。演示账本合计 **408.72617 credits**，其中真实 LLM/视觉估算 50.72617、Mock 媒体 358；这不是人民币账单。V10c 迁移夹具中的历史 1.25 credits 不算新消耗。

### 隔离与零生成证据

A/B 只使用同一 TEMP SQLite/存储，关闭 MQ；禁用 dotenv 自动加载，只解码白名单 DashScope 凭据行，不解析数据库/Redis 配置。C 完全禁止读取 dotenv，使用一次性容器内的两个新库。真实 `.env` 和私人未跟踪的 `AI_Video_Factory_Technical_Notes_CN.md` 保留。

HTTP 层只允许指定 DashScope 地址的文本/视觉请求，模型固定为 `deepseek-v4.1-flash`、`qwen3.7-plus`。请求发送前跨进程持久化预留，800 次硬限包含失败/未知尝试；未知请求不得盲目重发。禁用额外重试、重定向、代理和未经审计的 HTTP；原图片/视频提交、上传适配器继续阻断，图片上限为 0。B 仅显式安装本地 Mock 媒体适配器。独立 HTTP 审计的 188 条实际请求全部归类为文本/视觉，并与唯一工具账本 usage 一致。

固定初始化为零的 provider 计数字段**不能独立证明**零调用；本报告依据请求白名单、适配器阻断、实际 HTTP/越界审计、负向护栏测试共同判断，不声称进行了独立网络抓包。C 全部 HTTP 被拒绝，socket 仅允许本次 loopback MySQL 端口；Docker 包装器的新建链、随机密码及绑定证据确认了隔离端点身份。

## V10a：真实规划复跑

执行 `eval_v3.py all` 一次，再分别追加 c3、c5 各两次，共 10 个 Run。文本使用 `deepseek-v4.1-flash`，视觉使用 `qwen3.7-plus`；全部计划停在生产审批前。真实图片生成 **0 次**、真实视频生成 **0 次**。本节仅报告 V10a，不包含 V10b、V10c 结果。

9 个 Run 到达 `awaiting_plan_review`；c4 按预期到达 `awaiting_input`。这表示规划流程可结束，不等于全部效率与创作质量目标通过。

### 十次结果

“输入/输出合计”包含文本与视觉 usage；“最大输入”仅指单轮文本 LLM 输入。LLM 轮数为所有委派的文本调用合计，视觉单列。credits 取唯一账本的演示规划费用，保留五位小数；不包含未执行媒体节点的预计费用。

|用例/次|Run ID|文本轮数|视觉次数|输入合计|输出合计|最大输入|演示 credits|耗时秒|节点/视频秒|状态|
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
|c1 证件照|agent_1c87caf71fe54ae4|8|1|114,858|3,862|17,751|1.21368|99.8|1 / 0|待审核|
|c2 8秒猫跳舞|agent_aa1ac725a2424cd5|6|0|87,301|2,139|18,495|0.89440|29.8|2 / 8|待审核|
|c3 长片 #1|agent_48ca093630d34974|27|0|872,909|55,488|69,481|9.28397|416.8|28 / 116|待审核|
|c4 模糊需求|agent_bc4cddc3a4fb4c0e|2|0|19,594|692|10,235|0.20286|16.8|0 / 0|待回答|
|c5 三选一 #1|agent_60d7c7cd544e4588|8|0|189,377|2,373|27,778|1.91750|41.4|3 / 10|待审核|
|c6 模型约束|agent_a91ecbd7430643ab|8|0|139,619|1,932|22,772|1.41551|34.4|1 / 5|待审核|
|c3 长片 #2|agent_85bf8f6f83634f11|40|0|1,152,211|70,321|64,185|12.22532|557.0|17 / 113|待审核|
|c5 三选一 #2|agent_a3af267e81ca4c82|11|0|265,316|4,404|28,816|2.69720|63.5|3 / 10|待审核|
|c3 长片 #3|agent_e5d680dce2fd441a|28|0|975,945|68,961|82,588|10.44906|476.4|30 / 120|待审核|
|c5 三选一 #3|agent_37ef06bca62a4d4e|15|0|381,661|4,689|31,608|3.86350|90.4|3 / 10|待审核|
|合计|10 个 Run|153|1|4,198,791|214,861|82,588|44.16300|—|—|9待审核、1待回答|

c1 的视觉调用为一次附件理解：输入 1,378、输出 1,270 token；其余文本合计为输入 4,197,413、输出 213,591 token。此次只有一张上传附件，不能据此新增声称“多张图片批处理”已在本轮验证。

### 量化目标

|目标|结果|判定|
|---|---|---|
|c1/c2/c6 无委派、≤6轮、进入审核|均无委派并进入审核；轮数为8/6/8|c2达成；c1、c6轮数未达|
|c3 至少2/3进入审核|3/3；全部时长位于120±10秒范围|达成|
|c3 单轮输入≤60,000 token|69,481 / 64,185 / 82,588|0/3达成|
|c3 规划≤20 credits|9.28397 / 12.22532 / 10.44906|3/3达成|
|c3 最终无 PLAN_UNUSED_PAID_NODE|三次最终编译问题均为空|3/3达成|
|多人关键帧保留全部身份参考且模型支持多参考|#1与#3完整；#2未生成独立关键帧，双人镜头仅输入一个角色图|2/3达成，整体稳定性未达|
|c4 只提问，不出计划|2轮后等待回答，计划节点0|达成|
|c5 使用选择门、动画引用所选候选|3/3均为 select_image + choice，视频输入引用选择器.image|规划结构达成；运行时选第二张/改选验证见V10b|

长片委派树：#1 为 Producer(12轮) → Creative(6)、Director(9)；#2 为 Producer(24) → Creative(5，失败)、Creative(6)、Director(5，失败)；#3 为 Producer(12) → Creative(5)、Director(11)。其余用例均由 Producer 独立完成。

### 与 V-Gate3 基线比较

基线来源：`docs/agent_v3/VGATE3_EVAL.md`。它记录的15个Run包含五次长片调试迭代；本轮是10次固定复跑，样本和历史代码状态不同，总费用/总token不能用于严格性能因果推断。

|维度|V-Gate3|V10a|解释|
|---|---|---|---|
|简单任务轮数|约9轮|c1/c2/c6为8/6/8|有所减少，只有c2达到≤6|
|c1耗时|v3 53秒；v2 34秒|99.8秒|没有加速；本轮发生多次Schema纠错|
|c2耗时|v3 34秒；v2 12秒|29.8秒|比旧v3略短；不是同批v2对照|
|长片最终成功样本|第5次，311秒，8.9 credits，27节点/120秒|3/3到审核；416.8–557秒，9.28397–12.22532 credits|规划结束更稳定，但不证明更快或更好|
|长片单轮输入峰值|约110k token|本轮最高82,588|低于近似基线，仍超60k目标|
|c5选择结果|动画固定引用第1张|三次均引用选择器输出|选择结构缺口已补；真实执行另验|
|多参考关键帧|基线提出默认模型仅支持单参考的问题|#1/#3使用qwen-image-3.0并保留两角色引用|能力匹配通过；#2语义退化必须单列|
|生成质量|未生成图片/视频|仍未生成图片/视频|不得宣称角色相似度、画质、风格差异已验证|

本轮没有执行可选的 v2 c1/c2 复跑。

### 未达目标与中间失败根因

以下是受控工具拒绝、Agent纠错失败或语义不足。除明确标注的失败子委派外，各Run最终均恢复到预期人工停点；不能把“最终编译无问题”写成“过程中没有失败”。

|用例|根因与影响|历史编译/提交问题码|
|---|---|---|
|c1|brief连续3次写入猜错subjects、attachments、constraints字段/枚举及布尔值；首次i2i型号不符合允许模型，Blueprint再次实例化后修复。导致8轮超标。|MODEL_CAPABILITY_MISMATCH、INVALID_DELIVERABLE|
|c2|brief两次拒绝：subjects类型、production_intent类型、source缺失；早期视频节点缺first_frame_artifact_id。修复后仍在6轮内。|BRIEF_REQUIRED、INVALID_NODE_INPUT、INVALID_DELIVERABLE|
|c3 #1|节点引用未声明stage、package交付类型错误、一次check_plan缺title；Creative/Director的finish额外字段被拒后纠正。长草稿及回执累积，输入峰值超限。|UNKNOWN_STAGE、INVALID_DELIVERABLE_TYPE、INVALID_AGENT_OUTPUT|
|c4|无工具拒绝或编译问题；按预期提问。|无|
|c5 #1|brief的subjects类型、constraints字段、production_intent类型错误，修复后完成；但一个n=3节点仅写复古丝网印刷风格，未分别规划三风格。|无；brief错误为INVALID_WORKSPACE_PAYLOAD|
|c6|brief先猜错subjects及模型约束字段，随后补读资源；plan_draft一次重复节点ID被拒。最终型号约束正确，但8轮超标。|BRIEF_REQUIRED、INVALID_DELIVERABLE；另有INVALID_WORKSPACE_PAYLOAD|
|c3 #2|Creative第一次委派连续3次参数JSON“Extra data”；Director连续3次参数JSON不完整，均达到纠错上限。Producer兜底简化并修复模型/引用/质检/交付类型问题，但丢失双角色关键帧方案。|MODEL_CAPABILITY_MISMATCH、MISSING_PLAN_OUTPUT、UNTYPED_REFERENCE、QC_REQUIRED、INVALID_DELIVERABLE、INVALID_DELIVERABLE_TYPE|
|c5 #2|brief字段错误、未知workspace kind、后续视频错误使用choice gate和输出引用。修复后选择结构正确；单prompt+n=3仍无逐张风格映射。|BRIEF_REQUIRED、MISSING_PLAN_OUTPUT、INVALID_DELIVERABLE、INVALID_CHOICE_GATE|
|c3 #3|未声明stage、重复node ID、check_plan缺title，Creative/Director的finish额外字段；纠正后关键帧完整，输入峰值82,588仍超标。|UNKNOWN_STAGE、INVALID_AGENT_OUTPUT|
|c5 #3|brief字段错误；两次读取不存在Skill资源；提交不存在workspace_ref；使用未知kind；视频inputs混入保留配置、image与image[]/输出名混淆。最终通过但耗15轮。|BRIEF_REQUIRED、RESERVED_INPUT、INVALID_DELIVERABLE、PLAN_TYPE_MISMATCH、MISSING_PLAN_OUTPUT、WORKSPACE_ITEM_NOT_FOUND|

c3#2失败的 Creative 委派ID为10，Director为12，最终错误均为 `AGENT_ARGUMENT_CORRECTION_LIMIT`。Director三次输出 usage 均为8,000 token，错误含 `Unterminated string`，与输出上限相关截断高度吻合；回执没有保存服务商原始finish_reason，不能把该推断写成已经读取到length终止原因。

上下文目标未达并非计数混淆：V9b约束是60,000 Unicode字符的**软**投影目标，并非60k token硬上限。完整assistant工具参数、错误、最新Skill、受保护材料以及工具Schema仍保留，长计划反复写入/检查继续扩大请求。未用额外摘要LLM掩盖消耗。

c3#1峰值请求 `tinv_3fa090579f854684` 中，assistant消息约69,960字符，模型目录回执约24,430字符，工具Schema约28,948字符；c3#2峰值请求 `tinv_541af2c222a94370` 的assistant消息约81,601字符。这些字符统计只解释体积，计费与目标仍用真实usage token。

### 编译有效与创作满足分开判断

c3#1有2张定妆图、11张独立关键帧；c3#3有2张定妆图、12张独立关键帧。所有关键帧保留两个角色引用，使用目录上限为3张参考的 `qwen-image-3.0`，并有preview门。这是多参考结构验收，不是实际角色身份或画质验收。

c3#2仅2张单角色定妆图和11段i2v，没有独立镜头关键帧。s03/s04/s07/s08/s09/s10/s11虽然 `depends_on` 列出两角色且提示词描述两人，实际 `first_frame_artifact_id` 只有 `cast_deepseek.image`。控制依赖与文字描述不能替代ChatGPT的视觉身份输入。计划目标文字声称“生成各镜头首帧”，DAG却未实现，因此不能将该Run列为双角色生产方案合格。

两张定妆图又被显式列为image交付物，且各自被单人镜头数据引用，所以最终无 `PLAN_UNUSED_PAID_NODE` 是正确的。死节点检查不承担多角色语义完整性验证。

c5三次都由一个 `generate_image(n=3)` 产出 `posters.images`，经 `select_image/choice` 输出给动画。#1只明确一个复古风格；#2/#3在同一prompt中列三种风格，工具没有每张输出的独立风格分配。选择引用结构正确，但不能保证三张一一对应三种风格；本轮未生成，不应断言实际图片一定错误。

### 计数、token与演示费用口径

1. 只统计这10个明确Run ID；不把同一Run的摘要JSON和归档JSON重复相加。
2. `eval.db.tool_invocations` 按唯一 `invocation_id` 核对；文本只取 `agent_llm_turn`，视觉只取 `analyze_images`。`AgentStep`和委派轮数用于交叉校验，不额外累加为模型调用。
3. token取对应回执 `output_payload.usage.prompt_tokens/completion_tokens`，不使用字符长度估算。154次usage完整；本轮没有缺失usage、reserved请求或失败HTTP请求。
4. 与 `real_call_audit.sqlite.calls` 独立HTTP记录逐Run核对：次数、输入token、输出token三项全部相等。HTTP审计154条success，媒体请求0，blocked记录0。
5. 演示单价为文本0.01 credits/千token、视觉0.02 credits/千token；文本44.11004 + 视觉0.05296 = **44.16300 credits**，不代表供应商人民币账单。
6. 唯一账本费用保留5位小数。归档 `spent_total` 显示4位，十项相加为44.1631；差额0.0001是逐Run显示舍入，不能据此报告重复计费。例：c3#3账本10.44906，归档10.4491。
7. 本节154次只是V10a消耗。800次上限应按整轮V10的所有真实尝试累计，不能把本节数当最终V10a+V10b总量，也不能以成功次数规避失败尝试。

### 证据与复核入口

本地证据目录：`C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v10-20261019/`。

- `results/result_<case>_<run_id>.json`：以上10个Run的不可混淆归档，包含委派树、完整计划、轮次/usage、估价与错误。
- `eval.db`：委派原始消息、工作区版本、唯一工具账本和最终计划；只读访问使用 `mode=ro` 与 `PRAGMA query_only=ON`。
- `real_call_audit.sqlite`：独立HTTP计数及provider usage；本节审计快照154条success。
- `v10a-all.log`、`v10a-repeat.log`：执行顺序、状态和超时提示；两批正常退出，不代表所有量化目标通过。
- `C:/Users/MingZheYang/AppData/Local/Temp/v10-final-analysis.json`：逐Run核对结果、源归档SHA256、全部错误字段和去重usage证据。
- `C:/Users/MingZheYang/AppData/Local/Temp/v10-final-analysis.md`：独立只读审计；生成脚本为 `cinecrew-v10-prep/analyze_v10.py`，无应用导入或网络请求。
- 基线：`docs/agent_v3/VGATE3_EVAL.md`；V9边界：`docs/agent_v3/CONTRACTS.md` V.20。

本节交给V-Gate4的明确未达项是：c1/c6简单任务轮数、长片≤60k输入、长片多参考方案稳定性；三风格逐张覆盖属于独立语义不足。真实生成质量、运行时选择/改选、局部修复、worker恢复和MySQL并发不由本节代验。

## V10b：真实 Agent / Mock 媒体混合执行

五类要求拆为六个子场景（自动修复、人工批准各一次），控制流验收 **6/6 通过**。自动修复的用户意图保真仍有风险，不能将控制流通过等同于内容质量通过。

使用 `EVAL_MOCK_MEDIA=1`，复用 V10a 的未批准计划；仅强杀场景新建 Run。规划、Repair 和 Director 使用真实文本模型，媒体生成替换为本地占位图及可由 FFmpeg 解码的视频。临时 SQLite、存储与跨进程调用审计继续隔离；没有读取或连接真实 MySQL/Redis。真实图片、视频生成均为 **0 次**，媒体原适配器尝试、网络越界尝试也为 0。这里的 0 由替代适配器、原适配器拦截及网络白名单共同保证，不是独立网络抓包结果。

### 场景与新增用量

以下均扣除了复用源 Run 的 V10a 规划成本。B 轮没有新增视觉调用；全轮唯一一次真实视觉调用发生在 V10a。

| 场景 | 控制流 | 新增真实文本调用 | 输入 / 输出 token | 单轮输入最大值 | LLM 演示 credits | Mock 媒体演示 credits |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 完整故事交付 | 通过 | 0 | 0 / 0 | 0 | 0.00000 | 142 |
| content_policy → 自动修复 | 通过 | 6 | 90,759 / 1,939 | 21,965 | 0.92698 | 18 |
| content_policy → 人工批准 | 通过 | 8 | 126,715 / 2,570 | 21,276 | 1.29285 | 10 |
| 审核 B：第三镜改为雨夜 | 通过 | 6 | 177,127 / 2,957 | 38,871 | 1.80084 | 160 |
| 选择第二张 → 改选第三张 | 通过 | 6 | 111,343 / 2,111 | 21,903 | 1.13454 | 26 |
| 规划中强杀 worker 后恢复 | 通过 | 8 | 138,744 / 2,052 | 22,682 | 1.40796 | 0 |
| 合计 | 6/6 | **34** | **644,688 / 11,629** | **38,871** | **6.56317** | **356** |

B 轮新增合计 **362.56317 演示 credits**，不是真实供应商账单。Mock 媒体账本包括两次未提交成功的注入失败预估（8 + 5 = 13 credits）；不能据此推断服务商会对拒绝请求收费。本地产出占位图 32 份、占位视频 28 份。

### 审批、Patch、局部重做与交付证据

- **完整交付**：13 张图、11 段视频，共 116 秒；经过 13 次预览批准、审核 B，完成拼接、媒体探测、QC 和 ZIP 下载，交付包非空且保留 SHA256。执行阶段新增真实 LLM 调用为 0。
- **自动修复**：注入一次 `DataInspectionFailed/content_policy`；Repair 与独立 Director 各 3 轮。Patch 仅改 `video.inputs.prompt`，模型、8 秒时长、其他参数、首帧引用和 `image` 节点均不变。`scope=only` 报价执行 `video`、复用 `image`，修复报价 8 credits；30 credits 修复池满足条件，`approval.automatic=true`，未提交人工 `approve_patch`。新版本生成账本仅有该视频。
- **人工批准**：5 秒 `wan2.7-t2v`，修复池为 0；报价返回 `automatic.eligible=false`，原因 `REPAIR_BUDGET_EXCEEDED`。一次显式 `approve_patch` 绑定当前 `quote_id` 后，仅重做 `video`，报价 5 credits；模型、时长与用户系列约束保留。
- **审核 B 修订**：按交付 `master` 的输入顺序定位第三镜 `v03`，其专属首帧是 `f03`。Patch 改为雨夜；独立深比较确认只有这两个生成节点的内容改变，模型、参数、输入引用均不变，其他 28 个节点（包括两张角色基准）精确不变。批准报价执行 `f03/v03` 及 `master/probe/qc/package`，实际新增生成回执恰为 `f03/v03`；其余 24 个可复用节点的输入、哈希、输出、invocation 和 Job 来源不变。局部生成费 12 credits（1 图 2 + 10 秒视频 10），总片长仍为 120 秒，最终视频与 ZIP 可下载。
- **选择与改选**：先显式选第二张，再经人工 Patch 打开新版本选择门，显式选第三张。三个候选工件 ID 与 `posters` 原节点全字段不变；视频模型、提示词和参数保持不变，时长始终 10 秒；Plan IR 仍引用 `choice.image`，实际解析的首帧从第二张切换为第三张。报价仅执行 `choice/video`、复用 `posters`，新版本生成账本只有一次 `animate_shot`。旧选择与旧版本请求分别被 `INVALID_AGENT_STATE`、`PLAN_VERSION_CONFLICT` 拒绝（HTTP 409），未重新生成候选图。

### 中间失败及根因

最终成功不代表过程中没有错误。除账本外，还逐条检查了新增委派 18–26 的 canonical messages，覆盖未写入 `ToolInvocation` 的免费工具及 typed 输入拒绝。

| 场景 / 位置 | 失败或拒绝 | 根因与后续 |
| --- | --- | --- |
| 自动、人工修复各一次 | Mock `content_policy` | 由测试适配器定向注入，属于预期故障；不是真实服务商判定。均经 Repair → 独立 Director → 服务端报价继续。 |
| 人工修复，Director 第 4 轮 | `INVALID_AGENT_OUTPUT` | `review_patch.reason` 超过 2,000 字符；下一轮缩短后成功。 |
| 强杀场景，Producer 第 2 轮 | `INVALID_WORKSPACE_PAYLOAD` | `subjects` 传字符串列表，`production_intent` 传字符串；与 RequirementBrief 类型不符。 |
| 同轮 `check_plan` | `BRIEF_REQUIRED`、`INVALID_NODE_INPUT`、`INVALID_DELIVERABLE` | 有效 brief 尚未建立；`animate_shot` 缺少 `first_frame_artifact_id`，交付输出随之不可用。 |
| 强杀场景，Producer 第 3 轮 | 第二次 `INVALID_WORKSPACE_PAYLOAD` | subjects 改为对象后仍缺少必填 `source`；随后读取 Schema 并修正。 |
| 强杀场景，Producer 第 6 轮 | `WORKSPACE_ITEM_NOT_FOUND` | 在保存计划前提交 `plan@1`；补 `write_workspace` 后提交成功。 |
| 选择场景，两次旧审批 | HTTP 409 | 预期的旧选择 / 旧版本保护验证，不属于执行故障。 |

共发现 **4 条非预期工具错误响应、1 批包含 3 个问题码的编译失败**，最终均得到有界修正。auto/story/choice 的新增委派未观察到其他工具错误。没有为单用例改提示词或 Skill。

### 强杀恢复的精确边界

强制结束发生在 **真实 LLM 回执已成功落库、费用已结算，但 Agent 状态与 LangGraph checkpoint 尚未推进** 的窗口。原回执 `tinv_2742f60052e04841`，幂等键 `agent_c2390ab39af643b5:26:0`：

- 恢复首个 tick 只重放结果，新增真实调用为 0。
- 只读数据库确认该幂等键只有一条回执、`attempt=1`，输入 / 输出哈希及 0.09476 credits 不变。
- 共享物理调用审计中，原 `request_hash` 仅出现一次；子进程与恢复进程具有不同 PID。
- 整个场景共 8 次真实调用：强杀前已结算 1 次，恢复后产生 7 次新的规划调用。最终停在 `awaiting_plan_review`，未批准生成。

这证明了该已结算窗口的幂等恢复，**未验证 HTTP 在途、提交结果未知或供应商已受理但本地未记账的崩溃窗口**。

### 保留风险与验证时间边界

1. **自动修复的意图保真**：`video` 从“猫跳舞”改成自然摆动。Repair/Director 将拒绝归因于拟人化或跳舞只是推测，合成故障不能证明真实审核原因。自动控制流通过，但创作意图弱化应交 Claude 评审；也未验证新提示词的真实内容审核、画质或动作效果。
2. **来源标签不一致**：审核 B 修订的 `flow.author_role` 与 `patch.proposed_by` 都是 `director`，但 `f03/v03.origin.agent` 被写为 `repair`；同时更新了目标节点的 rationale。这没有扩大本轮生成范围，但会误导来源展示或审计。字段差异已保留，不能称为“仅 prompt 一处变化”。
3. **Mock 质量边界**：验证了可解码媒体、拼接、QC、打包与下载控制流；不能据此验收角色视觉一致性、雨夜画面或真实供应商故障策略。
4. **scope guard 的时间边界**：上述正式真实混合轮先执行完成，再补强评测脚本的修订范围守卫。正式结果另经只读深比较确认第三镜局部范围和改选约束，不能仅以“实际重做等于 quote”替代范围验收。新增守卫未进行真实调用重跑；其验证为 `test_v10_story_scope.py` **33 项**与 `test_v10_hybrid.py` **12 项**合跑，**45 passed / 128.20s**，证据 `v10b-scope-final.xml`。正式轮前的相关回归为 **154 passed / 446.47s**（`test_v10_runtime_time.py`、`test_v10_repair_active.py`、`test_v10_hybrid.py`、`test_v5_repair_flow.py`、`test_v3_runtime.py`、`test_v3_runtime_budget.py`、`test_v9_context.py`；证据 `v10b-targeted.xml`）。两批离线验证与真实执行结论分开记录。

### 独立对账

只读核对 `real_call_audit.sqlite` 与 `eval.db`：全轮 V10a + V10b 共 **188 次**真实调用，均成功（`deepseek-v4.1-flash` 187 次，`qwen3.7-plus` 1 次），输入 **4,843,479**、输出 **226,490** token，单轮输入最大 **82,588**；缺失 usage、未完成调用和越界尝试均为 0，低于 800 次限制。

唯一工具账本的演示费用为：文本 **50.67321** + 视觉 **0.05296** = **50.72617**；Mock 媒体 **356**；合计 **406.72617 credits**。B 轮每个场景的前后快照差均与独立调用标签分组一致；credits 按 tool 账本扣除源规划，避免源 `spent_total` 四位舍入造成微小误差。

原始证据位于隔离目录 `C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v10-20261019/`，包括 `results/hybrid_*.json`、`real_call_audit.sqlite`、`eval.db`、`mock-media.jsonl` 和强杀标记。只读分析位于 `C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v10-prep/`：`v10b-analysis.md/.json`、`v10b-independent-audit.json`、`v10b-intermediate-errors.json`。

|场景|Run ID|Patch ID / 原始归档后缀|
|---|---|---|
|delivery|agent_48ca093630d34974|无 Patch；`hybrid_V10b-delivery_<Run ID>.json`|
|failure-auto|agent_aa1ac725a2424cd5|patch_d68b05e477684044|
|failure-manual|agent_a91ecbd7430643ab|patch_76c5694d5c96420f|
|story|agent_e5d680dce2fd441a|patch_9813db983b724511|
|choice|agent_60d7c7cd544e4588|`hybrid_V10b-choice_<Run ID>.json`|
|crash|agent_c2390ab39af643b5|`hybrid_V10b-crash_399cc817.json`|

除 crash 外，各场景归档命名为 `hybrid_V10b-<场景>_<Run ID>.json`，其中保存完整状态序列、动作、Patch、报价和 ledger 前后差，不依赖报告中的摘要反推审批证据。

## V10c：一次性 MySQL 8 验证

使用 `Docker.ps1` 完整包装器执行，固定本地镜像 `mysql:8.4.4`，实际服务版本 8.4.4；镜像 ID 为 `sha256:23818b7d7de427096ab1427b2e3d9d5e14a5b933f9a4431a482d6414bc879091`。只绑定 `127.0.0.1:3307`，TLS cipher 为 `TLS_AES_256_GCM_SHA384`。临时自签名 TLS 配置只适用于本次本机容器，不作为生产配置建议。

|检查|结果|实际证据|
|---|---|---|
|全新库迁移至 head|通过，9.03秒|真实 Flask `db upgrade head`；空库逐条运行到 `20261019_005`，无 `create_all`、stamp 或自动补表|
|v2 头升级|通过，10.79秒|另一空库先到 `20261018_002`，插入四表历史记录，再运行后三条迁移到 head；Unicode/JSON 内容与摘要不变，新增 caller_agent/delegation_id 为 NULL|
|v3 Mock 冒烟|通过，9.03秒|`agent_b2fb9df62c314981`，3轮 Stub → 计划批准 → Mock 图片生成 → 审核 B → success；1个成功节点/工件，2演示 credits|
|两个 Run 并发规划|通过，5.76秒|`agent_e82f80e15c324f73` 与 `agent_14d018e0c4aa401b` 各3轮到审核；不同线程、会话、委派、工作区、版本、账本，无交叉引用；Barrier 证明首轮调用区间重叠|

两条迁移链均核对 `alembic_version`，检查四个 v3 表的列名与唯一约束；外键与 CHECK 定义保存在原始证据中，但没有用违规写入逐一验证。历史保留只覆盖 `series/agent_runs/agent_plan_versions/tool_invocations` 各一条样本，不等同于生产全量数据兼容验证。

并发是**同进程两线程、不同 Run**，使用独立 app context/session 与内存 checkpoint saver；未验证同 Run 竞争、多 worker 全局调度锁、MySQL checkpoint、跨进程恢复或压力吞吐。冒烟与并发在 fresh 库执行；upgrade 库验证迁移和历史保留。此前 SQLite 自检仅证明脚本可运行，不计入上述 MySQL 结果。

容器 `cinecrew-v10c-20261019202619-cb8ab880` 与卷 `cinecrew-v10c-20261019202619-cb8ab880-data` 已在 finally 删除，两个删除退出码均为 0；之后再次精确名称查询均不存在。未删除任何其他容器或数据卷。

证据：`C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v10c-run-01/mysql-evidence.json` 与 `docker-lifecycle.json`。四项检查 passed=true、整体 success=true，生命周期 container_removed/volume_removed=true。此阶段无真实模型或外部 HTTP 请求。

## 本轮代码修复与回归

只修复已有 D-038 的实现遗漏，不调整提示词、Skill、规划配额或接口契约，因此没有新增 DECISIONS 条目：

1. `repair_flow._delegate` 原来以创建后墙钟 600 秒判断 Producer 超限，用户长时间审核后即使未用尽活跃时间也无法 Repair。现在读取 `state.active_seconds` 和 `AGENT_V3_DELEGATION_ACTIVE_SEC`，保留步数/调用数/预算门槛。
2. `runtime._round` 原来只在正常尾部累计活跃时间，参数纠错等早退路径漏计。现在统一 finally 计时，异常先回滚未完成状态，再合并最新 state；等待输入、终态、已经完成的步骤不重复累计。

计时仍不是原子崩溃日志：操作系统强杀或业务提交与计时提交之间的中断可能丢失尚未持久化的时间。恢复幂等成功不意味着任意崩溃下计时完全精确。

|回归批次|结果|内容与证据|
|---|---|---|
|V10a 安全/指标|25 passed|`test_v10_eval_safety.py`、`test_v10_eval_metrics.py`；媒体/非白名单拒绝、计数与 usage 归档|
|V10b 计时/执行集成|154 passed，446.47秒|运行时、预算、上下文、修复及混合脚本；`TEMP/v10b-targeted.xml`|
|V10b 范围守卫|45 passed，128.20秒|33项新增范围用例 + 重跑12项混合脚本；`TEMP/v10b-scope-final.xml`|
|V10c 离线护栏|5 passed，1.18秒|禁止默认端口、外部存储、dotenv、越界网络；`TEMP/v10c-guard-final.xml`|
|V10c MySQL 集成|4/4 passed|真实迁移、数据保留、Mock交付和双Run规划；证据见上节|

154 与 45 两批包含重复的 12 项脚本测试，不应简单相加声称新增 199 项。本轮运行与改动相应的定向回归，没有重新运行 V9 的全部 2218 项后端或前端构建；V9 历史通过记录不能冒充 V10 全量复验。当前没有前端改动。

评测复现命令和边界见 `backend/scripts/v3_eval/README.md`。真实复跑仍须当轮授权、固定共享 `EVAL_WORK_DIR` 和跨进程 800 次计数，不能另建目录绕过累计限制。全部真实测试已结束，不需要为生成报告追加请求。

## 交给 Claude 的 V-Gate4 判定

|项目|本轮结论|下一步关注|
|---|---|---|
|简单任务短路径|部分未达：8/6/8轮|brief Schema、模板实例化到提交之间的纠错成本；不能只为c1/c6调提示词|
|长片可结束与预算|达成：3/3审核、各<20credits|保留独立审阅，不以“能提交”代替需求满足|
|长片上下文|未达：三个峰值均>60k|软字符目标与硬token目标的差别；大型assistant参数、目录与工具Schema的处理|
|长片角色参考|2/3结构通过|Director失败后的Producer兜底不得默默省掉多人关键帧；依赖边不是身份输入|
|c4不确定性提问|达成|本轮为模糊输入示例，不代表所有歧义识别|
|c5选择/改选|结构3/3、执行通过|单prompt n=3不能保证逐张风格覆盖；真实视觉差异待另行授权验证|
|Repair/Director/局部修复|控制流通过|自动修复有意图弱化；Director产物origin.agent标签不一致|
|worker强杀恢复|已结算窗口通过|HTTP在途未知结果与活跃计时窗口仍未验证，不得外推|
|MySQL迁移/双Run|达成窄目标|生产规模数据、同Run多worker竞争与MQ吞吐未覆盖|
|隔离、成本上限、零生成|达成|188/800；真实图片/视频0；一次性数据库已清理|

建议 Claude 优先审定：多角色参考语义退化是否构成 Gate 阻塞、自动修复改变用户意图的边界、结构化参数纠错和输出截断对效率的影响。未达项已保留原始证据，本轮不通过增样本、改提示词后重跑或合并费用口径来掩盖。

仍未验收：真实图像/视频质量、真实媒体供应商审核与恢复、角色视觉一致性、三种风格逐张覆盖、任意崩溃窗口、Redis/MQ 并行吞吐，以及生产数据库压力。V8 继续跳过，V7 美化仍归 Claude。
