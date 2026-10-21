# V12 修补与 V-Gate5b 验证报告

> C/A/B/D/E/F及D-053评测纠错已逐阶段完整验证并本地合并。四个指定规划样本与同Patch审核B续验均已运行；B的局部执行、复用、可信作者与交付闭环通过。真实调用共74次，新增真实媒体0；但长片60k峰值、时长与成批纠错目标仍有明确缺口，不能据此宣告整个Gate通过。

首次真实样本冻结产品 SHA：`5e5db145a8316d69f4ee183e6c0938b94a83b960`。证据根目录 TEMP=`C:/Users/MingZheYang/AppData/Local/Temp`。保留全部失败与中止记录，不重采失败样本、不修改提示词求通过、不推送、不进入 V8。各阶段测试数量不相加成一个“单轮全量”。最终 Gate 与默认启用仍由 Claude 审读。

## 1. 实现结果与边界

| 阶段 | 变更 | 重要边界 |
| --- | --- | --- |
| C | Wan2.7 I2I预处理统一使用适配器工厂；混合harness遇attention先记录失败并停止 | 保留经典协议、MQ时机及明确人工Patch审批；避免再绕过媒体Mock |
| A / D-048 | brief比例贯穿成片关键帧、视频、compose/QC；省略补合法几何，冲突拒绝；实测SAR/变换保守校验 | 结构性定妆/参考豁免，兼作成片输入仍约束；未知SAR不伪造证明，不自动裁剪/压缩，不重写历史批准载荷 |
| B / D-049 | 研究工具run_id绑定可信ToolContext，先规范化再来源/幂等/账本；错误提供合法结构示例 | 显式伪造、越权、SSRF、损坏来源仍拒；v2恢复一致；空示例不冒充真实来源或下载 |
| D / D-050 | context policy3保护每个(name,path)最新成功完整配对的资料，只投影旧副本 | 不改持久消息，失败/不完整批次不能建立保护证明；已冻结pending_context继续精确恢复 |
| E / D-051 | 编译issue.details给出真实工具允许的引用字段与类型，新增诊断安全限长 | 不接受别名、自动改写或放宽Schema；旧message不改，经典接口保持 |
| F / D-052 | Director、审阅委派、plan-review共同要求reason/intent/changes评价同一最终草稿；UI两处文字说明审阅对象 | revise评价revised_draft；false仍人工，历史reason不回写；Claude样式/事件不改；新V12指引待Claude审阅 |

F保留A比例段，plan-review 7→8；image-create 3→4，Blueprint VERSION=2保持。正式仅新增两条实际Registry流程测试，三条逐字文案检查留TEMP。Mock比例与交付不证明真实服务商画质、角色相似度或最终LLM语义准确性。

## 2. 正式验证与本地提交

以下各阶段均精确collected=reported，遗漏/额外/重复/失败/跳过/格式及分组异常为0，source冻结、guard0、全部进程及构建通过。均只用Mock/Stub和隔离存储/数据库，未推送。

| 阶段 | 后端用例/文件 | 状态及本地提交 | 正式证据目录（TEMP下） |
| --- | --- | --- | --- |
| C | 2594 / 137 | 通过；a8de0c59ea2725983c0e7aea486b5427aba8f035 | cc-v12c-1021214043-8ec3 |
| A | 2691 / 139 | 通过；ff645760705030949f76bedc2e5c7bd723295d99 | cc-v12a-1021232124-formal-903d |
| B | 2724 / 140 | 通过；395cf988c6350f866fb6fc364bf777049bd53ff1 | cc-v12b-1021234901-formal-9492 |
| D | 2743 / 141 | 通过；b85a2f06bf3d49a888db761b7ab26371cae30a15 | cc-v12d-1022001605-formal-ce4f |
| E | 2766 / 142 | 通过；1277d49b929c814cf428318b9f5404fe29228721 | cc-v12e-10220044-formal-4ac1 |
| F | 2768 / 143 | 通过；5e5db145a8316d69f4ee183e6c0938b94a83b960 | cc-v12f-10220120-formal |
| D-053评测纠错 | 2799 / 144 | 通过；f2728c3007f3f33487d2d0c40697d5f33e96ce37 | cc-v12-eval-recovery-10220204-formal |

D-053正式全量耗时25分01秒；2799精确收集与执行一致，无遗漏/额外/重复/跳过/失败，source冻结、guard0、所有进程及前端构建通过。此前64项定向不与全量相加；31条新增评测回归不涉及产品或提示词。

F独立前端在cc-v12f-frontend-tap-10220117完整137项通过，fail/cancelled/skipped/todo均0，source冻结、guard0。首轮默认spec输出导致TAP解析失败的证据保留，不能把两轮相加为274项。

浏览器第二轮cinecrew-v12f-browser-evidence-02自动检查通过，主任务实际查看四张完整截图确认视觉通过：1440/400亮暗、原1000px布局无横向溢出，pageErrors0，最终与历史reason原文、false人工门、fresh quote及一次人工批准保持。扩高仅用于截图，产品/断言未改；source/dist冻结。browser-evidence.json SHA256为82c67ef36bc3950b70b871ec2b50d91f54fafdb83d8504769751f86149a59011。API全内存Stub，无真实后端、媒体或LLM；静态服务已结束。首轮自动通过但截图视觉失败的01证据原样保留。

首次真实规划冻结产品SHA：5e5db145a8316d69f4ee183e6c0938b94a83b960。D-053后的本地HEAD为f2728c3007f3f33487d2d0c40697d5f33e96ce37，仅评测脚本/测试/文档变化，产品、Skill与前端相对原真实样本保持一致。F完整后端于2026-10-21 17:35:53.083 UTC结束，耗时约24分49秒；stage_f_ops finish独立核验137 TAP与浏览器02后成功本地合并。V12f-merged.json中的路径、数量及离线real_calls=0已核准。

## 3. 失败根因与修正

| 证据/性质 | 根因 | 处理与结果 |
| --- | --- | --- |
| C首轮定向24过/1败；fixture | Wan2.7引用计划缺mode=i2i，编译器正确拒绝 | 只修fixture，新增13项复验通过，随后2594全量通过 |
| A TEMP初轮75过/4败 | 空景缺characters=[]、两图片低于最小短边；另1项实现读取旧probe Stub缺失width | 前3项修fixture，另补可选几何兼容；未放宽媒体规则 |
| A TEMP focus2；环境 | 自动pytest ID超过Windows环境变量限制；同一用例setup/teardown各error | 缩短ID；11过/2生命周期error不当作两个产品失败 |
| A TEMP focus5；fixture | Wan3纯参考夹具缺brief系列偏好，被默认选型规则拒绝 | 只补偏好，原选型规则不改 |
| A独立审阅；候选逻辑 | compose/QC无条件注入误伤纯参考；比例证明遗漏SAR；仅显示比可能接受非方像素画布 | 修结构用途、SAR/旋转与合法画布边界。TEMP最终去重128项来自多批，非单次最终128完整运行 |
| A正式首轮；评测路径 | storage-relative首帧被Mock按cwd解析，导致六个旧V10混合测试失败 | 主动中止并保留退出证据；改存储根解析及越界校验，48项复验通过 |
| A正式第二轮；Mock编码 | PNG转视频未显式setsar=1，未知SAR被fit_display_canvas正确拒绝；独立1败/17.47s | 再次中止，补Mock编码SAR，不放宽产品；122项/401.266s复验及最终2691全量通过 |
| B TEMP收集；环境 | 公共rootdir误扫无关不可访问目录 | 显式rootdir/confcutdir，无产品变更 |
| B TEMP24过/6败；fixture | 四条误认目录含Run明文，实际哈希目录；两条缺write_workspace幂等键 | 修预期/上下文，不改归属或幂等 |
| B TEMP28过/3败；overlay | 配置前提前import app导致JWT上下文错误 | 先共享conftest；最终199+2不重复通过，后2724全量通过 |
| E TEMP收集；环境 | 跨repo/TEMP收集误扫JetBrains目录，0项执行 | 固定rootdir/confcutdir，后37+3通过 |
| E正式迁入前；封存口径 | 原patch有110个CRLF，实际bytes哈希af1f9289…与规范化LF封存e6739085…不一致 | 在源码/文档迁入前拦截；独立验证7hunks反向基线及3overlay字节匹配，原patch保留，仅修校验期望；之后2766全量通过。不是产品测试失败 |
| F生成器静态审阅；迁入准备 | 旧materializer寻找V11e待审标记，A版本7已是已审标记 | 保留旧脚本，新入口严格接受A7及唯一已审标记，保留A全文后插入F升8；重新动态生成，不覆盖旧证据 |
| F前端首轮；验证器 | Node原生exit0但默认spec输出使TAP计数为空，helper failed | 显式--test-reporter=tap，完整重跑137通过；不是产品断言失败 |
| F浏览器01；截图证据 | 自动检查通过，嵌套scroll截图裁切/大段空白，实际视觉验收失败 | 仅修截图策略；02自动与实际四图视觉通过，原布局检查保持、扩高只截图，source/dist冻结 |
| Gate5b checker TEMP首轮2败；验证器 | brief缺失时误叠加定妆约束，将not_covered判failed | 缺需求证明改not_covered，原失败保留，最终44项Stub通过；尚未证明真实Gate目标 |

D封存定向83项无失败；旧V9夹具迁移为重复资源副本，保留不可变与恢复断言。F预A五项中仅两条Registry流程正式迁入，逐字文案三项留TEMP。V11旧轮118次与blocked1原样封存，不计本轮新增请求。

## 4. 真实规划样本与语义审读

唯一新轮：`TEMP/cinecrew-v12-gate5b-20261022-01`。严格按 c7×1、c3×2、c1×1运行；审核B选最早适用的新c3，不增加其他用例或重新采样。下表输入/输出仅计该样本成功物理调用；费用为演示账本，未执行媒体的报价不是已花费。

| 样本 / Run | 结果与耗时 | 真实文本 / 视觉；委派 | 输入总和 / 峰值 / 输出 | 规划费用及语义结果 |
| --- | --- | --- | --- | --- |
| c7 / agent_981a19a7d5c943c1 | awaiting_plan_review；276.1s | 20 / 0；Producer9→Director11，无Creative | 808,839 / **65,182** / 18,294 | 8.27133；30节点、12×10s=120s；16:9成片参数与角色引用链成立；60k未达 |
| c3-1 / agent_5b7b6c8b05834906 | awaiting_input；116.6s；未产Plan | 15 / 0；Producer6→Research9 | 275,351 / 29,400 / 5,978 | 已花LLM2.81329+Mock研究0.8=3.61329；不是完整规划费用，不计审核成功 |
| c3-2 / agent_be1e06bb981b4dd2 | awaiting_plan_review；279.0s | 26 / 0；Producer13→Director13；另1逻辑调用被预算拒绝 | 1,103,886 / **68,541** / 30,915 | 11.34801；20节点、7×10s=**70s**；主线/身份链成立，但约120±15秒需求失败，60k未达 |
| c1 / agent_791f07731aac4986 | awaiting_plan_review；57.9s | **4 / 1**；仅Producer，无子委派 | 合计64,038 / 17,811 / 3,175（文本62,658/1,188；视觉1,380/1,987） | 0.70580；image-edit单节点、本地合成测试人像附件的实际工件引用（真实视觉理解）、白背景/深西装/正面构图均在提示词；≤6文本轮通过；未生成实物 |

**c7**：全部12个关键帧为16:9，12个720P首帧视频沿用相应帧；master/QC显式16:9、1280×720、compress_output=false。纯身份参考图为方形，符合豁免。无Creative，26个付费生成节点都有通向交付物的数据链。固定事件第4步用户要求“一起上楼”，提示词写“准备一起上楼/向楼梯走去”，没有明确完成上楼；保留为局部动作保真待Claude裁定，不能写12项实物剧情全部验收。c7只做规划，真实画质和成片未执行。

**c3-1**：Research由真实LLM驱动，但检索/下载服务端均走Mock，不构成真实联网服务验收；Agent诚实说明Mock资料不能核实官方品牌视觉。web_search×2、image_search×2、download_reference×1成功；原始下载调用确实省略run_id，服务器持久账本绑定正确Run，覆盖V12b默认绑定的实际Registry路径。fetch/capture本例未调用。问题卡有“通用可区分形象 / 用户指定 / 等真实检索”三选项；recommended=generic_distinct，**default_option_id=null**。默认答题请求缺必填request_key造成422，修键也不能擅自把推荐项当默认选择；本轮不替用户选、不补采该样本。

**c3-2**：两位原创角色并肩进赛场→开始编程→竞争争执→DeepSeek报错→ChatGPT转为关切→伸手→握手。五个双人关键帧各实际引用两张定妆图，两个单人帧仅引用对应角色，七个视频各引用专属关键帧；不是只写depends_on或角色名。各视频duration均10，estimates和交付源合计均70；compose写“7段共120秒”与QC理由写“120±15秒”不改变参数。v3 QC只核对批准片段总和，不与原始时长意图交叉校验；即使Mock交付通过仍不满足两分钟需求。

## 5. 审核 B：同 Patch 局部执行与来源闭环通过

选最早可用的新c3-2。先API批准计划和9个preview门，9图+7视频共16次Mock生成完成，达到第一次结果审核。用户修订“只把第三镜改成雨夜，其他保持”，提案Director3轮、独立审阅Director5轮，新增8次文本：输入268,679/峰值49,287/输出12,991，LLM2.81670。原基准计划的70秒时长缺陷未随局部修订修改。

首次05归档failed源于harness把原样重复的first_frame_artifact_id误判为变更；实际仅s03_video.prompt改变。D-053纠错并完整2799项通过后，同Run、同Patch续验；06临时入口在app导入前因Popen被替换成函数而破坏asyncio继承失败，未触及审批。独立07入口用受控Popen子类修正，21条纯/Stub及首次asyncio/sqlalchemy导入冒烟通过后完成续验。05/06失败证据原样保留，未重新规划、重采样或修改LLM结果。

07对原Patch `patch_54c2d2d6060645e5` 重新获取cascade quote，明确人工approve_patch返回202；版本2实际新增仅一次s03_video生成（10秒，10演示credits），compose/probe/qc/package四个后期节点重跑。其他15节点（含s03_frame）输入、哈希、输出、job_id、invocation_id与版本1逐值相同，复用指针正确。计划值差异只有第三镜prompt与版本号；角色、模型、参数、时长、引用、origin/rationale均不变。

可信作者与原不可变proposal、propose_patch账本交叉核对为Director委派8，独立审阅委派9保留；最终计划仍归Director，metadata diff为空，审阅reason未改写。再次结果审核与approve_results返回202，Run最终success；视频下载112,613字节、ZIP264,510字节。全程新增LLM/视觉0，原74物理请求逐行不变，真实媒体/上传HTTP及blocked均0。

**通过范围是局部执行、复用、来源和交付流程。** 原提案reason仍误写“7×10=120”，独立最终审阅已指出70秒基准；intent_preserved=true只评价本次局部变化。雨夜仅写在视频提示词、首帧复用，真实雨夜画质和身份相似度未验证。

## 6. 真实过程失败根因与未达项

| 现象 | 确定根因 / 处理边界 |
| --- | --- |
| 两次c3首次brief失败 | research_needs写成字符串数组；Schema要求query/reason对象。回执附合法片段，重写后成功；不是工具缺run_id。 |
| c3-1 dossier拒绝 | 网页未fetch、下载图未analyze，可信admitted来源为空；仍写sources/候选，并把result_id w1/i1改名s_w1/s_i1。来源校验正确拒绝；后改只含warnings，无编造真实品牌证据。 |
| c3-1 finish拒绝 | returned附非空dossier_ref；此状态只允许reason与可选suggestion。删除多余字段后成功。 |
| c3-1自动答题422 | eval_v3.py遗漏RuntimeAction必填request_key；字段层拒绝。卡本身无默认项，不能靠补键代替用户决定。D-053修评测，不补采。 |
| c7中间13条编译问题 | story_ref指向同Run的plot_note（kind=note，非story）；vid01–vid12遗漏characters，虽然各首帧/身份目录已正确。v5整稿重写删除错误story_ref并补12个视频角色声明，随后检查0issues；该完整重写紧接峰值请求。不能称未再批量纠错。 |
| c3-2四次非空check共58条 | 32/10/10/6，含连带输出与交付物错误，不是58个独立根因：post/assembly不一致；定妆及单图选型违反当前默认约束；非生成节点显式characters=[]；wan2.7-image沿用1536×864；compose/QC只写target_aspect_ratio未写配对size。按回执逐次修复，最终零issues。 |
| c3-2把投影描述写入草稿 | 冻结模型输出与实际调用输入逐值一致，确认模型自己产出仅context_projection的占位草稿，非执行器篡改。notice已写not valid tool input；缺title/goal/nodes/deliverables，被Schema正确拒绝，未保存伪草稿；之后模型完整重写v6。 |
| c3-2 Director预算拒绝 | 已用7.00802/配额9，余额1.99198小于预留2.60962，正确拒绝第14次逻辑准入，无HTTP。Producer接手后提交。Run总规划11.34801未超20；rejected估计不计已花费。 |
| c3-2时长失配 | 原作者自早期草稿即7×10秒，后续未核对120±15；不是编译器缩短或审核B改短。已存在基准缺陷不在第三镜修订中顺手修。 |
| c7/c3-2峰值超60k | 分别65,182/68,541，真实usage证明未达。c3-2统计器因拒绝行无usage写not_covered，人工必须按成功物理请求明确判未达。冻结请求已证明旧write/append和旧读回有投影；不同path的最新资料、最新完整草稿及回执、近期读回、失败check和模型目录共同构成高基底。字符软目标不是完整请求真实token上限，不能把字符数换算为token。 |
| B独立审阅中间INVALID_AGENT_OUTPUT | 审阅Director手工check_plan的完整输入重复stages.id=act3，CheckInput正确拒绝；重写后检查成功。实际Patch未新增或修改stage，并非最终Patch再次越界。 |
| B首次ScopeViolation | 评测器误以原样重复传入字段等于改变字段。原Patch实际仅prompt变化；D-053回归后07同Patch局部执行与来源闭环通过，原首次失败保留。 |
| 06临时续验入口导入失败 | 入口把subprocess.Popen替换为函数；sqlalchemy→asyncio.windows_utils定义class Popen(subprocess.Popen)时报TypeError。失败早于app创建、Worker、审批和模型调用；control失败原样保留，guard0，eval.db SHA仍47c35c3ab0f05f1f6d2a7bcc44beebf83e6650c16c9a3a305ff803133b255723，字节未变。仅修新07临时入口，最终续验通过；产品未改、原样本未重采。 |
| 首次只读统计命令失败 | 使用-I导致相邻模块导入失败；按既有入口-B重跑只读统计成功，无新增真实请求或产品修改。 |

量化结果：c3可审核率**1/2达到至少1次门槛**，未达到最好2/2；不能把未完成c3-1算完整长片token、成本或身份链通过。c1 4轮≤6、无子委派、一次视觉理解通过。c7比例链规划通过，无多余Creative，120秒通过；完整固定动作仍有局部语义风险。已完成规划c7/c3-2费用均≤20；**60k和“不再成批同类纠错”未达**。审核B经07同Patch续验完成局部执行、复用、可信作者及再次交付；这不修复原规划的70秒与60k缺陷。

### 冻结请求补证

c7峰值65,182对应Director第10轮（全局第16轮）。9个资源均是不同path的最新成功读取，共44,811字符；v4读回、v5整稿写入助手消息和完整写入回执共53,853字符，失败check另10,114字符。旧write/append已压缩，当前草稿/回执与近期读回仍被保留；峰值与修正上述13项后的整稿重写直接相邻，不能归因为policy3未生效。

c3-2峰值68,541来自初始Director第13轮，早于审核B。同样9个最新资源44,811字符，模型目录24,423字符、三次失败check回执26,069字符、最新v5写入消息和回执27,549字符仍完整；旧v3读回已投影至899字符，旧v4写入参数734字符。占位稿已从原始LLM输出核实，属于模型把投影描述误作可提交内容；其失败消息不得凭不存在的保存证明压缩。上述字符数仅解释组成，不拆分或估算各段真实token。

费用作用域保持：c3-2 Run规划11.34801≤20，费用目标通过；Director已用7.00802≤9，仅下一轮预留2.60962超过余额1.99198而被正确拒绝。不得将Run总费用与单个Director额度混比。先前独立根因稿的错误比较已由作者更正并保留修正差异。

## 7. 唯一账本、真实用量与安全

以下为07结束后的**最终只读统计**（2026-10-21T18:34:00.440203Z），按唯一invocation去重。续验前74请求快照独立封存；它不是跨V10/V11累积值。

| 指标 | 核准结果 |
| --- | --- |
| 真实物理请求 | **74=73文本+1视觉**，全部success；deepseek-v4.1-flash / qwen3.7-plus；150上限未超 |
| 真实usage | 输入**2,520,793**，输出**71,353**，峰值**68,541**；全部74次usage完整 |
| 逻辑口径差异 | 75条模型工具记录=74成功+1预算拒绝；逻辑text74包括拒绝，不能误写74text+1vision=75次真实调用 |
| LLM/视觉演示费用 | **25.95513**（四个规划23.13843+B新增2.81670） |
| Mock媒体费用 | **98.0**，9图+8视频成功；包含第三镜重做10credits |
| 其他演示费用 | **0.8**，Mock联网研究 |
| 合计 / pending | **124.75513 / 0**；演示credits不是服务商真实账单 |
| 真实图片 / 视频 / 上传HTTP | **0 / 0 / 0**；媒体全Mock，未调用HappyHorse |
| blocked / unknown / reserved / unmapped | 均0；无阻断记录，原失败归档保持 |
| safety / data_quality / reconciliation | **passed / passed / passed**；成功逻辑与物理请求Run级usage一致 |

四个固定规划样本66次真实请求，初次B提案/审阅新增8次，07新增0。最终142个唯一工具invocation（136成功、6拒绝），其中75个模型记录含1次预算拒绝；成功物理请求74次usage完整。费用仅按唯一invocation计，Director拒绝预留2.60962排除。续验只新增5条成功工具账本共10credits，未重复计算原Run或同名归档。安全证明来自白名单审计与双层媒体拦截，不冒称独立抓包或操作系统网络沙箱。

自动统计`required_coverage`审核B仍failed：聚合器只认旧outcome=story_scope_and_origin_passed，07使用resumed_story_scope_and_origin_passed；同一JSON的07独立hybrid记录已passed。保留原统计与05失败，按第5节原始执行证据单列续验通过。c3-2 token目标自动not_covered由预算拒绝行缺usage触发，成功物理请求峰值68,541仍明确判未达。

离线全量封禁.env读取，只用临时SQLite/存储。真实Gate不整体加载dotenv，仅既有白名单提取获准API凭证，不解析/连接.env里的MySQL或Redis，不修改.env、凭证不入报告。首次B停机后经明确授权，以mode=ro/query_only导出四个已知Run；数据库前后SHA相同，连接已关。静态浏览器预期阻断Google字体与本轮媒体调用计数分开。

## 8. Claude 待审与后续边界

1. 审读V12a–f新契约/Skill/提示词及D-053评测修复；A–F研发完成与真实目标失败分开判定。
2. 审读c7保留16:9、人物链和12事件映射，特别“一起上楼”是否只是到楼梯；实际媒体未生成。
3. 审读c3-2的70秒意图失配、投影描述误作草稿、预算配额/反复纠错；确定后续修复优先级。不要为本次已定样本修改提示词求通过。
4. 审读60k失败与最新资料、当前草稿和失败证据保护的取舍；冻结请求分析已补齐，旧投影实际有效，不能以统计not_covered逃避确定超限。
5. 审读05失败、06入口失败与07成功的完整证据链；07已完成fresh quote人工批准、仅第三镜重做、15节点复用、可信作者和两项下载。保留自动统计对续验标签的识别限制，不能覆盖原失败。
6. 默认启用v3继续阻塞，最终Gate由Claude裁定。真实画质/身份相似度/逐张风格、真实选择执行、HTTP在途崩溃、同Run多worker与MQ吞吐仍未验证；按原评审安排，少量真实图片身份抽检在Gate后另行进行，本轮不追加。

## 9. 证据索引

- 正式全量：第2节各TEMP目录的summary、collection/groups、JUnit、source与guard、build日志；各阶段合并凭据cinecrew-v12c-review/V12{c,a,b,d,e,f}-merged.json。
- A两次中止：cc-v12a-1021223525-399f、cc-v12a-1021225223-formal-f0b0，raw summary和operator-stop均保留；48与122定向证据分别cc-v12a_path_fixed-focus-1021224634-2147、cc-v12a_geometry_fixed-focus-1021231413-25f2；独立SAR失败cinecrew-v12a-onecase。
- 前端/浏览器：cc-v12f-frontend-10220120失败解析、cc-v12f-frontend-tap-10220117成功137；cinecrew-v12f-browser-evidence-01/02。02 seal SHA在第2节。
- 各候选失败和恢复：cinecrew-v12{a,b,d,e,f}-prep/HANDOFF与manifest；详细历史REPORT_WORKING.md。E字节/换行核对、F旧生成器与新sealed生成器均保留。
- 唯一真实归档：cinecrew-v12-gate5b-20261022-01/results/result_*_<run_id>.json；B的hybrid同名私有profile；不使用会覆盖的无Run后缀文件。原B SHA52991b4adec99c5a81316b1d183f547df2495ead4d7c0d4a302435c352b850e1。
- 独立语义：cinecrew-v12c-review/review-c7.md、review-c3-1.md、review-c3-2.md；补齐原参数的review-static-profile-addendum.md。旧文件证据限制按补记更新，不抹去先后。
- B误判：review-b-first-attempt.md、review-b-first-attempt-diff.json（SHAe44bfd2089af4cdc3cea897259daf8b2f79ef88126b3f598f3d7d45bc6c395d6）；原批准base与rawPatch只有prompt值差异。
- 固定原始导出：static-profiles-after-first-b-20261022-01/manifest.json（SHAa830226e894cf6e8575edb80d78d9dc2c28d974d20723d8ae4094c4073f93914），仅四个已知Run；供中间根因与上下文审阅，不对外公开含原始模型消息的TEMP文件。
- 06入口失败：cinecrew-v12-gate5b-20261022-01/06-resume-control.json（SHA fe81cb3f6f61d353bb0c3530f32480a2cefaf6c2f0e9a16f2e0628ba99ca4bc6）、cinecrew-v12c-review/gate5b-1022-06-resume.log（SHA 29466270248a73726ca0427e4990b0c2a4234dcea318a210f49fd5d757ad03e5）。07随后独立成功，旧入口与失败证据不覆盖。
- 07独立终态审计：review-b-resume07.md、review-b-resume07-evidence.json；唯一hybrid_V12-story-resume07-agent_be1e06bb981b4dd2_agent_be1e06bb981b4dd2.json SHA 8d4c84b44743eb78b488291849fa9c2496a4e5c24d62ef2b56aad0f5d9456776；07-resume-control.json与退出日志均passed。
- 最终只读统计：cinecrew-v12-gate5b-20261022-01/readonly-statistics/v12-statistics.json SHA 8105875334f8380693340892773d8a99c66926697abe5d98df4c4856aab2a970，safety/data_quality/reconciliation全passed、diagnostics=[]；统计聚合标签限制见第7节。
- 固定续验前统计：cinecrew-v12-gate5b-20261022-01/readonly-statistics-before-resume/v12-statistics.json/.md；JSON SHA256 cc99d68547ddeea423a70b6f5e18770668265b1fbf956721e45c69af406f9e3e。首次B快照74请求，最终统计另存并已逐物理行对账，不覆盖失败取证。
- 冻结请求根因：rootcause-c7-context.md（SHA f992c0b56c3232759331804cc1737d21846068bd16288416247ca2bf0d47177a）、rootcause-c3-context-and-errors.md（费用作用域纠正后SHA 7d8ad54ed3fa97d7c7fa50eb8483d4f4bcf6318620661e5719aab291abb6edee）；机器明细context-static-evidence-20261022.json（SHA 5da827f37a1d0983ae11fd7e2e107184510ff5a6396d3ffb7e23f5b26eedf31a）。旧错误费用比较独立留档，报告不采用。
- 07入口审阅：resume07-entry-independent-review.md；cinecrew-v12-b-resume07-prep/resume_review_b.py SHA 9da8cb130df81ed0e5ffa61567850fd0ae4767e6eb2fd07928ead856be3ee5a3，同目录pure-tests.log（21项）与windows-import-smoke.json。仅已知兼容修复验证；实际07结果另列。
- 续验入口静态审阅：resume-entry-independent-review.md（SHA baf337368499f5e3835ac1e5ff0c05c7e2cb26b656b879aeebe6b74ab8ffd841）；cinecrew-v12-b-resume-prep/resume_review_b.py（SHA 3afe179507ab68322dc3d3d2cbaa34b13cde0513de9912fae49459198a9fbe26），同目录pure-tests-final.log和git-guard-smoke.json。旧06准备证据及其遗漏的继承兼容问题保留。

研发、正式回归和本轮固定真实测试证据已整理完成；最终Gate及默认启用由Claude裁定，未验证的真实画质与明确未达目标不因Mock闭环通过而消失。
