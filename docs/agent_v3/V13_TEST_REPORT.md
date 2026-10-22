# V13 与 V-Gate6 测试报告

日期：2026-10-22。状态：**V13a–e 与评测入口开发、离线验证完成；V-Gate6 首样本被 DNS 护栏中止，未完成真实验收。用户已选择“先完成报告，真实验收暂挂”，本轮停止调用并收尾。**

## 1. 结论与边界

V13 已完成显式时长约束、无损规范化、有证明的上下文投影、草稿诊断与固定事件指引，以及运行期帧级技术余量。最终集成源后端 **3205 项 / 158 文件全部通过**，前端构建通过，保留 Claude 的需求约束界面。各阶段独立分支验证后仅本地合并，未推送、未建 PR、未进入 V8。

真实评测冻结提交为 `90175c745912d7d20c99e2dc0d505916e9cdafdb`。第一个固定 c3 在首次 Producer 请求的 DNS 检查阶段中止，未取得模型响应或计划。后续 c3、c7 和身份抽检均未启动。不能据此判断规划质量、token 峰值、时长、角色一致性或真实图片质量，默认开启 v3 继续阻塞。

开发回归仅 Mock/Stub、隔离 SQLite/临时存储，禁网、禁 dotenv。真实入口沿单一凭据白名单规则，不读取/连接真实 MySQL 或 Redis，不修改 `.env`、私人技术笔记或 Claude 美化。`TEMP/` 指 `C:/Users/MingZheYang/AppData/Local/Temp/`；本文只引用停机归档与只读审阅证据，不增加请求或复跑失败样本。

## 2. 开发与正式离线验证

| 阶段 | 本地提交 | 定向 | 完整后端 / 文件数 | 构建 | 正式证据目录（TEMP 下） |
| --- | --- | --- | --- | --- | --- |
| V13a：明确时长 | `a03b6b3` | 初轮205/207；修夹具后两条通过 | 2898 / 146，通过 | 通过 | `cc-v13a-1022203122-6d33` |
| V13b：无损规范化 | `e1acfbe` | 217通过 | 2946 / 147，通过 | 通过 | `cc-v13b-1022204537-43f1` |
| V13c：回执投影 | `a22d5bb` | 133通过 | 2996 / 148，通过 | 通过 | `cc-v13c-1022212916-7761` |
| V13d：诊断、指引、统计 | `b920367` | 234通过 | 3097 / 153，通过 | 通过 | `cc-v13d-1022214039-a9a4` |
| Gate6：私有评测入口 | `f729d89`；集成合并`8f54f0b` | 新56+旧safety24，共80通过 | 3153 / 157，通过 | 通过 | `cc-v13gate6-1022215930-e652` |
| V13e：实测技术余量 | `90175c7` | 176通过 | **3205 / 158，通过** | 通过 | `cc-v13e-1022222538-40ec` |

全部正式全量均精确 collected=reported，遗漏、额外、重复、失败、跳过、畸形报告和组归属错误为0；全部进程通过，source/HEAD/branch冻结、guard为0。定向与全量存在重叠，不相加作为独立测试数。E 定向证据 `cc-v13e-focus-1022221911-374d/summary.json`，pytest336.06秒；最终全量从22:25:38.624560至22:54:01.787705（UTC+8），**28分23.163秒**。

Gate入口与 Claude 并行约束界面/默认开启草稿正常合并；仅 PROGRESS 追加位置有冲突，双方记录保留。最终 E 全量验证的是该集成源。真实阶段使用 E 最终全量证据，不以较早入口全量替代。

### 关键行为

- **A / D-055**：新 brief 仅对用户明确时长设目标，记录 mode 与原文出处；approx容差`max(3,target×0.125)`，exact/at_most严格。按真正交付链计时，compose重复播放重复计数，retain用区间差，transform用完整输出，package/master/压缩别名去重，多交付聚合。120秒目标与7×10秒计划被拒；未知时长不猜。审批根约束冻结，直接视频也在结果审核/批准前实测；旧批准receipt不重写。出处校验是原文包含校验，不等于对所有自然语言时长表达的语义证明；提取正确性仍待真实验收。
- **B / D-056**：只在编译副本忽略已知非生成节点`characters: []`，为合法显式比例且缺尺寸的compose/QC推导既定画布；不猜语义、不接受别名、不覆盖冲突或未知SAR，不改原输入。
- **C / D-057**：policy4仅投影有完整证明、已被同key更高版本合法check取代的旧失败回执，及同规范参数旧模型目录。最新资料/草稿/目录、原历史/账本和冻结pending_context保持；字符缩短不等于真实token降幅。
- **D / D-058**：投影对象返回`PLAN_CONTEXT_PROJECTION`和受限重读提示；普通字符串、既有类型化嵌套及原JSON边界保持。Director固定事件须在镜头实际内容中完成；版本V13、plan-review10、long-form-video4。仅旧V12f已审，新V13文案待Claude Gate6。统计识别续验、分离新旧阈值与图片/阶段费用，交付预计秒不冒充计费或实测秒。

### E / D-060、V.23.6：仅离线覆盖

编译仍严格使用批准参数和用户容差，不允许用技术余量批准原本超标的计划。运行期在原上下界外增加`E=max(0.5秒,Σ(n_i/fps_i))`；n取批准最终compose输入出现次数，嵌套compose算一个输入，其他视频为1。多主片0.5秒基线只算一次；FPS取同一文件本次完整解码探测的头部速率，不宣称独立证明恒定帧间隔；缺失/非法不猜默认，只记录未知片段。技术余量不改用户意图、参数、预算或批准哈希。

离线覆盖 exact5→5.04通过、→5.8拒绝，at_most120→120.3通过，compile5.04参数对exact5仍拒绝；包含多交付、重复、别名、未知FPS、非法actual与工件指纹。独立复核还修复了输出登记旧+0.05秒早门，以及Registry剥去QC详情的问题：统一完整解码/余量与前后指纹，v3-only输出保留可选details，经典输出不变。实际Mock Job链以5.3秒Stub探测值经过登记、可选QC、审核与批准，调用数和费用不增加。

**这些验证证明离线逻辑与执行链，不是实际媒体边界验收。** 不能声称真实编码器/提供商帧偏差已经验证；后续Gate6视频仍为Mock，也不能补足这一限制。

### 性能观察

D全量约14分50秒、E约28分23秒，比前阶段约8分钟慢。多个未改经典用例也变慢；独立旧defaults profile通过，create_app约1.082秒，未调用投影验证器。目前没有确定的D新增热点证据，E变慢也无已证实根因；不推断机器负载为结论，不为提速改代码或跳测试。证据 `TEMP/cinecrew-v13d-performance-profile/`。

## 3. V-Gate6 首样本：DNS护栏停止

工作根：`TEMP/cinecrew-v13-gate6-20261022-01`（以下`WORK`指该目录）。固定阶段`01-c3-1`，Run `agent_1f18acf306c742a2`，唯一逻辑调用`tinv_221b90f0414840fa`。归档约0.4秒停止，Run为attention，Producer failed、0 steps，无子委派，未生成计划或进入编译。

首次文本请求先完成持久额度预留，之后提供商主机DNS解析到非公网地址，被`gate6_transport`在socket.connect前拒绝，错误为`Provider DNS resolved to nonpublic addresses`。主任务另外只读核实系统解析`dashscope.aliyuncs.com → 198.18.0.83`；审计保存原因字符串、不保存具体IP，精确IP来自该现场核对，独立审阅未重复联网。该现象与本地DNS改写/FakeIP相容，但不能凭现有证据确定具体软件或配置。

这不是提供商HTTP错误、提示词/Skill或Plan编译失败。护栏按策略拒绝非公网解析；未放行保留地址、绕过代理策略或更换API URL来继续。向用户说明网络/FakeIP问题后，用户选择先完成报告、暂挂真实验收；本轮不再等待或新增调用，未自动重试、补采、清除计数或替换样本。

### 精确调用、usage与费用口径

| 项目 | 本轮记录 | 解释 |
| --- | --- | --- |
| 文本尝试预留 | 1，`deepseek-v4.1-flash`，审计status=unknown | 请求前占用持久120额度中的1次；不等于1次成功模型调用 |
| 提供商HTTP响应 / 成功输出 | 0 / 0 | http_status、response_id均null，连接前中止 |
| 输入 / 输出 / 峰值token | **未获得** | usage缺失1；汇总显示0仅因无可汇总usage，不能称实测0token或80k达标 |
| 网络blocked / unknown或reserved | 1 / 1 | network阻断；审计唯一调用终态unknown，未退款或清零 |
| 视觉 / 图片POST / 视频 | 0 / 0 / 0 | 图片预留、返回、下载也均0；未进入身份阶段 |
| 唯一逻辑调用 | failed / TOOL_FAILED | error_message与DNS护栏一致 |
| 应用预算估计 | **0.54391演示credits** | 保守保留预估；归档0.5439为显示舍入。没有usage，不是服务商账单，不能确认实际收费或确定免费 |
| pending/running预算预留 | 0 | 失败调用的保守账目仍计入accounted/LLM演示credits；不是pending，也未退款 |

`01-c3-1.finished.json`为runner_completed=true、safety_ok=false，错误`Safety counters are not clean`。completed仅表示采集归档结束，不是Gate通过；blocked1、unknown1、usage_missing1要求停止。

正式停机只读统计位于`WORK/readonly-statistics-v2-network-stop01/v13-statistics.{json,md}`：data_quality=passed仅表示归档完整性检查通过；reconciliation=needs_review，safety=failed。唯一尝试的峰值为null、已知token和为0且usage缺1，不能写成0token达标。图片审计表尚未创建，因此统计的实媒体观察为null，不可把缺表当“图片检查通过”；阶段归档、入口meter与无生成工具记录支持图片/视频均未启动。统计中的固定样本数量和c3进入审核目标为failed/未完成，其他质量项为not_covered或needs_review，不代表模型质量已经被测失败。

`WORK/network-stop-readonly-proof.json`证明统计前已有13个文件SHA全部不变；原审计、失败归档与started均保留。统计不修改旧记录，也不改变0.54391的失败账目。

### 固定样本结果

| 阶段 | 实际状态 | 质量、约束与性能验收 |
| --- | --- | --- |
| c3-1 | DNS护栏中止，attention，无计划 | 未覆盖；compile_issue_codes为空是未编译，不是编译成功 |
| c3-2 | 未启动，无started | 未覆盖 |
| c7 | 未启动，无started | 未覆盖 |
| 四图身份抽检 | 未启动；无manifest审批、原图、副本或视觉正文 | 未覆盖，不能填写图片或虚构判断 |

本轮未取得可验收的输入峰值、120秒规划、16:9链、角色引用、固定情节、纠错效率或图片质量。c3至少1/2进入审核的目标本轮未完成，不能把“尚未运行”写成模型规划失败率，也不能宣布任何真实指标通过。

## 4. V12基线保留与只读复核

Claude对V-Gate5b为有条件通过，新Gate峰值门槛≤80k，60k仍是优化方向；旧轮未达60k的事实不回写。V12固定轮74次物理成功（73文本+1视觉）、75逻辑含1次HTTP前子预算拒绝；输入2,520,793、输出71,353、峰值68,541，物理usage缺失/unknown均0。演示账本25.95513 LLM/视觉+98 Mock媒体+0.8 Mock Research=124.75513 credits，不是货币账单。真实图片/视频/上传0；Research是模型驱动Mock服务，不是实网检索验收。

| 指标 | V12基线 | 本轮V13真实比较 |
| --- | --- | --- |
| c3进入计划审核 | 1/2；另一例为无默认的合理澄清门 | 未完成真实验收 |
| 时长 | c3-2为70秒，不符合约120秒；c7为120秒 | A/E离线反例已通过；真实未覆盖 |
| 峰值 | c7 65,182；c3-2 68,541，旧60k未达 | usage缺失，不能比较或判达标 |
| 比例 | c7全部成片关键帧、视频与compose落实16:9 | 无计划，未覆盖 |
| 规划纠错条数 | c7共13条；c3-2四次check为32/10/10/6，共58条（含连带错误，非58个独立根因） | 未进入编译；空错误码列表不能视为纠错改善 |
| 已完成长片规划费用 | c7 8.27133；c3-2 11.34801，均≤20 | 0.54391只是中止尝试的保留预估，非完整规划费用 |
| 固定事件 | c7“上楼”仅准备/走向，Claude判轻微偏差 | 新指引离线通过，真实语义未覆盖 |
| 角色身份/画质 | 结构引用通过，未做真实抽检 | 四图及视觉均未开始 |
| 审核B | 同Run/Patch的07续验通过；15节点复用，第三镜一次10秒Mock重做 | 只读复核旧证据，不重复收费，不证明雨夜画质 |

新统计只读复核旧B续验通过，原工作根130个文件字节不变；首次failed与07passed分列，不覆盖旧required_coverage=failed或旧阈值。证据 `TEMP/cinecrew-v13d-v12-readonly-review/REVIEW.md`，SHA256 `234adad3fb712873bbb5ad71cfc1b878d6d67447224c3a3ed9261a17dbe8b962`；`review-result.json` SHA `0945c889c164c6dc7c17ca9316db0f19fc51116bb82c9e41ba3b9ca13ad67bfc`。只读连接已关闭。

旧失败根因继续保留：时长门当时未关联用户目标；c7的story_ref错指note及视频characters遗漏；c3的节点命名、默认模型、非生成空角色、非法尺寸与compose/QC缺尺寸造成纠错。Research类型/未准入证据/重命名ID不合法，推荐选项不等于用户授权。Director7.00802/9、剩余1.99198不足预留2.60962是正确子预算拒绝，不得与Run11.34801/20混比。旧B scope误判未变引用、06 Popen函数替换破坏Windows asyncio，均留证；07同Patch零新LLM恢复成功不抹去此前失败。

## 5. 开发期失败与修正

| 事件 | 根因与处理 |
| --- | --- |
| A两条transform用例初失败 | 夹具指定Wan3但请求/brief没声明系列，默认模型规则正确拒绝；仅补测试前提，随后正式全量通过。原证据`cc-v13a-focus-1022202638-485c`、`cc-v13a-fix-focus-1022203101-21ba`保留 |
| A Schema生成未启动 | TEMP写入权限阻止；自动审批后受限生成三资源，无应用/网络请求 |
| C首次全量未执行 | 自动审批服务额度耗尽，是执行环境故障，非产品失败或安全否决；用户继续后新正式全量通过 |
| D投影初稿/统计候选 | before统一finite_json误拒类型化嵌套，改只读扫描；mock.patch旧模块路径修正；交付秒误标计费秒修正并补回归 |
| D旧文案冲突 | long-form固定±10秒与D-055不符，改统一公式；旧V12已审与新V13待审明确区分 |
| Gate6 HTTP继承包装 | HTTP先包装，HTTPS再捕获继承包装导致一次许可双消费；先冻结原方法，独立探针通过 |
| Gate6未知/异常响应留证 | UNKNOWN曾误归http_error；非JSON、下载非2xx/超限先抛错丢证据；改unknown锁定，保存HTTP/hash/bytes及partial。choices=dict导致KeyError丢视觉raw，改严格类型提取、完整原body保留 |
| Gate6入口/夹具边界 | 精确只读SQLite URI原被误拒，改仅两库放行且UNC先拒；约60秒循环不足，改1200秒墙钟并测慢完成/超时。默认模型、重复gate批准、相同输入复用、usage字段等夹具问题已修，未改真实提示词凑样本 |
| 独立探针/历史统计启动失败 | 导入库的本地IPv6能力探测被严guard拒绝；只读脚本tempfile探测写被自身guard拒绝、DB未打开。调整受限预载/已知TEMP后通过，原失败保留，无真实网络 |
| E执行链两处缺陷 | 输出登记固定+0.05秒比新门更早拒绝；QC输出Schema丢details。先补契约，再统一技术余量、完整解码/指纹及v3-only输出类型；正式定向和全量通过 |

候选失败与正式回归分开保存，不以定向通过替代全量；没有为单个真实样本调提示词、抬预算或重采。

## 6. 证据索引与下一步

最终源与全量：`90175c745912d7d20c99e2dc0d505916e9cdafdb`；`TEMP/cc-v13e-1022222538-40ec/summary.json`及source-before/after、精确JUnit清单。固定首样本：

- `WORK/results/result_c3_story_agent_1f18acf306c742a2.json`，SHA256 `2c3198eb842eb008a2de79fc2e4e0cda18a1f4e360a887f6e90e1a78d0941be9`。
- 对应`_private_profile.json`，SHA `20c5d3ce07617e2d24f1f1d4699ff3c7f736b0dd2fc352914c8fbc87c0ec3085`；私有证据，不把完整消息写入公开报告。
- `WORK/01-c3-1.finished.json`，SHA `490c4a21dd19fa2790dc76334d81940c6e80469d45446bcb53574073892f7e2d`；started与source-freeze保留。
- `WORK/readonly-statistics-v2-network-stop01/v13-statistics.{json,md}`及`WORK/network-stop-readonly-proof.json`：停机只读统计与原13文件字节不变证明。
- `TEMP/cinecrew-v13-gate6-first-failure-review/readonly-evidence.json`，独立导出唯一逻辑/物理记录、未启动检查与文件哈希。
- 同目录`first-sample-dns-root-cause.md`，SHA `0817a1382afa318e3a21123e9ad36f6cf6565309c63dc29d62ecb73a97051e88`；独立只读根因审阅，不追加请求。

按用户选择，本轮完成报告，真实验收暂挂，不继续等待或执行。保留原started、unknown、blocked、失败保守账目和全部归档。不能删除锁/计数、静默换工作根、放行非公网地址或用新成功替换固定失败。网络恢复后如要续验，须先明确原Run与固定样本安排、如何保留本失败和累计额度，再遵守封存入口逐阶段执行；本报告不授予自动重试或重采权限。

本轮交Claude的结论是：**实现与离线回归完成；真实Gate因网络前提未满足而中止，所有真实质量目标未验收。** 默认开启v3、V14运行指标及灰度开启计划仍待后续评审和用户确认。
