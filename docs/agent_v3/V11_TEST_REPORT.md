# Agent v3 · V11 测试报告

停机统计：2026-10-21T00:42:13+08:00。实现与测试：Codex；V-Gate5 审读：Claude，尚未判定。

A–G研发实现已完成，逐阶段离线全量通过并本地合并；真实评测暴露了尚未修复的缺陷。c1/c6各5轮达标，c5三风格候选结构正确；c3按要求执行3次，2/3进入审核，达到原至少2/3门槛，但较V10的3/3下降，1例停澄清。c7保留12事件、120秒及身份数据链、没有多余Creative，但未落实16:9，整体需求保真失败。

新Repair已通过真实独立Director审阅、人工意图门与Mock交付；审核B场景在参考图预处理触达上传入口，被护栏拦截后停止，尚未进入首次结果审核或局部修订。**全轮118次真实调用；安全统计failed（1次越界入口尝试），数据质量和对账passed，真实媒体HTTP与上传均未发生。审核B失败/未覆盖，不能以离线全绿宣告V-Gate5通过。** 所有原定规划样本与两个混合场景均已执行，没有重采样、清除失败或追加真实调用。详细离线历史见[离线证据稿](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-offline-report.md)。

## 范围、实现与版本

遵循 AGENTS.md、D-040–D-046 / V.21.1–V.21.7。所有 Agent 工具仍经 Registry；生成只由批准后的确定性运行时执行。保留经典工作流与 Claude 的 V7 美化，仅补审核功能；未推送、不开PR、不进入V8，私人未跟踪技术笔记保留。

|阶段|实现与关键限制|本地提交|
|---|---|---|
|A / D-040|角色目录、节点characters、媒体数据引用链校验；控制依赖/提示词不证明身份，选择门按分支交集；旧计划显式identity_upgrade强制人工|`3cf0685`，合并`5ea3a9e`|
|B / D-041|独立Director必填严格bool意图评估及changed_elements，不可变证据绑定最终草稿；变化/未知不自动批准，卡片显示前后差异|`d1c5c47`|
|C / D-042|提议/最终修订作者由委派、工作区与收据核验；报价、批准同候选；历史applied读取实际版本，origin/rationale/depends_on差异单列|`8cb3cbe`|
|D / D-043|补合法brief与按需读取示例；完整剧情直接规划、不为格式委派Creative；不猜测转换用户字段|`55605f2`|
|E / D-044|finish_reason=length整批工具不执行，记AGENT_OUTPUT_TRUNCATED并结算usage；精确版本追加1–12节点、CAS与幂等，不绕审批|`a90aab0`|
|F / D-045|只在请求视图投影有保存证明的旧计划，保护最新参数/完整读取；原state、账本、工作区和冻结pending_context不改|`9f3009b18bb5dfca81f150c58329479e1dd44df3`|
|G / D-046|各风格独立n=1节点汇入choice，选中结果驱动下游、全部候选计费；image-create Skill=3、plan-review=6，Blueprint来源仍2|`85918ed1a76f98e1575eb7bb9cf4d6ac1ff17558`|

C 的approve审阅沿用B评估/工作区边界，不声称新增了对所有approve原始review收据的完整核验。E只追加，修改旧节点/计划头仍需完整新稿。F的60000 Unicode字符是软目标，不能当成60000 token实测。G用Mock验证引用和执行，不证明真实画风。

真实测试冻结提交为`85918ed1a76f98e1575eb7bb9cf4d6ac1ff17558`；唯一WORK为`C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01`。`v11-round.json`为V11、call_limit=400、real_image_limit=0、real_video_limit=0、media_mode=mock，SHA-256为`f87c6985187ec1181851875f35a2bf54974b82bf1033a51decd1cd00b70a9e56`。真实请求窗口为北京时间10月21日00:10:45.633–00:41:10.361；最后story场景00:42:11.154停止，00:42:13.230生成最终只读统计。评测前后源码保持冻结；`agent-v3/V11-report`只包含本报告、PLAN与PROGRESS，未改测试后的产品代码。

真实评测禁用dotenv自动加载；仅既有白名单读取器解码DashScope密钥/地址，不解析.env中的MySQL/Redis值、不输出凭据。MQ关闭、数据库和存储均隔离在该TEMP目录；不修改真实.env。HTTP只允许指定文本/视觉模型，物理请求发送前持久预留400次额度；图片上限0，原生成/上传入口继续封锁。最终一次上传入口阻断也保留在同一账本，没有重置额度或换目录绕过。

## 离线验证

各阶段为包含既有功能的完整集合，不能累加成独立用例数。A–G最终摘要均passed=true，精确ID无遗漏/多余/重复/失败/跳过，源码冻结、guard_events=[]、前端构建通过；使用隔离SQLite/存储与Mock/Stub，禁用dotenv、阻断真实网络，真实调用0。

|阶段|后端完整结果|构建|正式证据|
|---|---:|---|---|
|A|2402/2402，127文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11a-1020123528-dad7/summary.json)|
|B|2446/2446，128文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11b-1020163553-1182/summary.json)|
|C|2477/2477，131文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11c-1020171315-c5de/summary.json)|
|D|2487/2487，132文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11d-1020181631-3b7e/summary.json)|
|E|2537/2537，134文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11e-1020195400-catalog-fixed/summary.json)|
|F|2577/2577，135文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11f-1020212835-guard-fixed/summary.json)|
|G|2581/2581，136文件|通过|[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11g-10202332-versions-fixed/summary.json)|

补充证据：B/C前端各137项；1440/400宽、亮/暗四组Mock浏览器无横向溢出、pageErrors=0，历史报价不可直接批准，显式审批绑定当前quote_id。证据为仓库忽略目录`.playwright-mcp/v11b/final-result.json`、`v11c/result.json`。C附带依赖差异由7项后端回归覆盖，不夸称浏览器专项覆盖。G新增4项Registry/Mock选择执行已通过；版本修正后[16项定向](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11g_versions-focus-1020232511-b6c5/summary.json)全过（27.219秒），含实际image-create实例化、来源与submit，不能替代全量。

### 失败根因与修正

|记录|原因、处理与证据边界|
|---|---|
|B旧选择夹具失败|手改草稿却复用旧hash意图评估，正确拒绝PATCH_REVIEW_REQUIRED；改为真实提议和独立审阅，不放宽审批。12进程首轮显著变慢并中止，疑似IO争用但未证实，四进程全量通过。|
|B/C TEMP环境与夹具|B缺FFmpeg路径，修正测试环境；C免费propose收据使旧“0调用”断言失效，改为精确一条免费收据。C另有compose INVALID_SOURCE未留stderr、未再复现，原因仍未知；20项deselect错误造成重复，不计新增。|
|C展示遗漏|同作者insert.before只变依赖时旧diff漏显示；补depends_on前后差异及7项回归，不改执行规则，纳入正式全量。|
|E首轮2536过/1失败|工具目录旧断言42，遗漏append_plan_nodes；精确改43并保留经典22及角色权限断言，[失败证据](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11e-1020190524-formal/summary.json)保留，完整重跑2537通过。另TEMP适配器精确预期补finish_reason:null。|
|F首轮2573过/2失败|CallMeter卸载将包装过的继承方法固化为子类自有属性；E的Wan3/safety分属g0/g2，F同g0按safety→Wan3暴露既有顺序泄漏，非上下文业务回归。[失败](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11f-1020204012-formal/summary.json)→新增red为1过/1失败→逆序恢复原描述符/继承关系→[原顺序120项通过](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11f_safety_fixed-focus-1020212713-3d5d/summary.json)→完整2577通过；护栏未放宽。|
|G首轮2579过/2失败|[原始摘要](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11g-1020223642-formal/summary.json)精确2581/136、冻结/guard0/构建通过。两项旧断言将Skill=3与Blueprint=2强制相等，[独立复现](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11g_failure_probe-focus-1020231139-d76d/summary.json)均3==2；只迁移精确版本矩阵，保留来源/schema/费用等断言，16定向通过，完整重跑2581项/136文件通过（约41分钟，构建/源码冻结/guard0），原失败记录保留。|

恢复器另修正两项证据格式假设：失败全量没有combined.xml，改核对四组原始JUnit；focus没有落盘source-after，依据其冻结摘要与current==source-before核对。执行代理实际只读检查通过后启动重跑；未补造证据。失败记录不能被最终成功覆盖。

临时混合入口另补交付覆盖：原脚本的合法自动分支只核对Patch批准，没有推进实际重做；新入口对自动/人工合法分支均检查成功任务、生成收据和非空下载，同时保留人工分支未覆盖时的退出2。没有改变提示词、审批或意图分类。7项隔离Mock/Stub通过，见[覆盖说明](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-hybrid-delivery-20261021/HANDOFF.md)和[summary](C:/Users/MingZheYang/AppData/Local/Temp/cc-v11_hybrid_delivery_mock-1021002257-9834/summary.json)。真实本轮选择了人工分支，不把离线自动交付测试算成真实自动修复通过。

外层规划runner的退出码遮蔽修复经过8项零网络Stub；混合runner的结果分类也经过8项纯AST/Stub检查（不运行wrapper、不读DB）。混合入口SHA为`95bdd9bcb5ed5b5e3dacb37b3c0aa2c0ad0458e244e62124f314cd8b7503dfd2`；wrapper SHA为`b21f43beeab502653479776d04bfb5369991500460198220978bac99bf67d3c1`，见[执行说明](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-hybrid-runner.md)。这些检查不覆盖后续暴露的Wan2.7直接构造预处理路径；该缺口仍如实失败。

## 真实规划结果与量化目标

样本：c1/c6/c5各一次、c3三次、完整剧情c7一次；c2单列为新Repair混合基准。V10只作[历史基线](<C:/Users/MingZheYang/Desktop/项目开发/AI Video Factory/docs/agent_v3/V10_TEST_REPORT.md>)，旧Run、费用与JSON别名不计本轮。

|用例/Run|规划冻结时状态|文本轮/视觉次|文本输入峰值token|输入/输出合计|完整规划credits / 其中LLM视觉|归档|
|---|---|---|---|---|---|---|
|c1 / agent_bbc41ab735584c4b|待审核|5 / 1|18,561|80,696 / 2,647|0.85961 / 0.85961|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c1_portrait_agent_bbc41ab735584c4b.json)|
|c6 / agent_0a7e9e4d31764f7a|待审核|5 / 0|19,170|85,816 / 1,040|0.86856 / 0.86856|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c6_constraint_agent_0a7e9e4d31764f7a.json)|
|c5 / agent_4fda990daeaa4548|待审核|8 / 0|31,782|207,885 / 2,054|2.09939 / 2.09939|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c5_novel_agent_4fda990daeaa4548.json)|
|c3 #1 / agent_64a9a3fd07bb437a|待审核；120秒/22节点|22 / 0|56,366|838,852 / 20,941|8.59793 / 8.59793|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c3_story_agent_64a9a3fd07bb437a.json)|
|c3 #2 / agent_9fd28fe814b142e7|awaiting_input；无计划|17 / 0|32,576（未完成观测）|328,163 / 6,052|完整规划未覆盖；已花4.14215=文本3.34215+Mock检索0.8|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c3_story_agent_9fd28fe814b142e7.json)|
|c3 #3 / agent_9d7371a4fcd24c9a|待审核；120秒/22节点|23 / 0|57,616|841,148 / 16,711|8.57859 / 8.57859|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c3_story_agent_9d7371a4fcd24c9a.json)|
|c7 / agent_53460024db194288|待审核；120秒/29节点；比例约束失败|22 / 0|58,401|775,316 / 18,940|7.94256 / 7.94256|[原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c7_complete_story_agent_53460024db194288.json)|
|c2混合基准 / agent_3288fb43f99d44e2|规划归档待审核；后续修复执行另计|8 / 0|24,923|163,616 / 1,559|1.65175 / 1.65175|[规划原归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/result_c2_clip_agent_3288fb43f99d44e2.json)|

完成样本的规划统计冻结于首次成功submit_plan，Repair后续调用另列；完整规划费用含初始Mock预览及其他规划工具，不能只算LLM。c3 #2从未submit，其完整规划费用为null；已花费用与截至澄清的token保留，但不得判为完成长片的峰值/费用目标通过。缺失usage单列，不补零或用字符数代替token。

c1/c6/c5最终编译问题均为空、无子委派，归档耗时分别55.6/27.1/40.3秒；这些样本没有发生媒体执行，未执行报价2/5/16 credits不计已花费。费用取唯一账本五位精度，归档spent_total四舍五入不能取代它。c1最终i2i保留上传卡通身份、纯白背景、深色西装与正面构图；输出1280×1280是已知配置，不代表某一证件规格。c6海浪拍礁石的5秒/系列约束满足。c5三prompt的风格特征分别明确；本轮用户要求不同风格，具体三种由Agent选择。

c3 #1为Producer 7 + Director 15轮，#3为Producer 9 + Director 14轮，均无Creative/Research；分别232.0/188.6秒、8×15秒，最终编译问题为空。#1首两帧单角色，后六帧双角色；#3八帧均双角色，两张cast经关键帧的真实媒体引用传到对应视频，双参考帧采用qwen-image-3.0、视频为wan2.7-i2v。执行代理已审读双方身份数据链与竞争、波折、合作、握手剧情，未发现最终付费死节点；这不证明真实画面质量或主流拟人设定。#1待执行媒体报价140 credits不是已花费。

c3 #2为Producer 8 + Research 9轮，96.7秒，没有Director、PlanDraft或编译。最终询问角色外观采用官方资料/参考图、文字造型或通用AI形象，不代答、不重跑。研究Run ID上下文缺口与Mock检索无法核实品牌是两个独立限制（详见失败表），不能把作用域护栏成功当成研究功能成功。

c7为Producer 8 → Director 14轮，225.4秒，无Creative；执行代理逐镜头核对原12个事件均保留。s10是无角色空镜、直接t2v，其余11镜按出场角色引用身份图→首帧→视频；不能从Director概括的“12段均i2v”直接得出结论。最终draft@6编译0问题，峰值58,401 token、完整规划7.94256 credits，均在阈值内；无Mock媒体或检索费用，真实媒体未执行。自动统计的semantic_review仍是needs_review，人工审读与统计字段分开记录。

**c7仍有明确语义约束失败**：原需求16:9，s10_video实际参数ratio=9:16，与prompt中的16:9相反；11个首帧均为方形（s01/s07为1280×1280，其余9帧1024×1024），compose未传目标比例、compress_output=false；服务必要时会按第一片尺寸归一化，不能据此保证16:9。因此只能判无Creative、12情节与120秒、身份数据链及token/费用各项通过；不得将最终0issues扩大为比例满足或成片交付成功。已定位来源：原作者params省略size/ratio，编译器补入方图/9:16默认值，且没有与brief的16:9约束交叉校验；不是Agent显式指定竖屏。[完整快照审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c7-agent_53460024db194288-review.md)已确认；当前冻结轮不修改计划或源码。

c2规划基准仅Producer，33.6秒、8轮、无brief纠错；最终单个generate_video(t2v)、wan2.7-t2v、8秒、720P，保留橘猫/阳光窗台/跳舞。用户未指定比例，本例默认9:16不构成违约；规划结束时的8 credits媒体报价不加入1.65175规划费用；后续失败与重做的实际Mock账本另计。该冻结归档只证明修复测试起点，不能代替后续failure-intent结果，也不能把仅针对c1/c6的≤6轮阈值套到c2。

8个规划样本合计111次真实请求（110文本+1视觉），输入3,321,492、输出69,944 token；LLM/视觉33.94054演示credits，另有c3 #2的Mock检索0.8。Repair新增7次文本，审核B新增真实调用0。规划冻结与最终执行状态分别报告；重用Run及JSON别名不重复计数。

|验收目标|结果与必要证据|
|---|---|
|c1/c6各≤6文本轮且无子委派；c1一次视觉理解；c6全部视频满足指定系列|通过：各5轮且仅Producer；c1视觉调用`tinv_71c06e8a96b24584`只传1张图，不能据此声称多图批处理已验；c6唯一视频为wan2.7-t2v、5秒，无HappyHorse|
|c3按要求测试3次；沿用至少2/3可审核门槛；完成样本无付费死节点、峰值≤60000 token、完整规划≤20 credits|**原门槛通过：2/3可审核，较V10的3/3下降**。#1/#3分别56,366/57,616 token、8.59793/8.57859 credits且无最终付费死节点；#2停澄清，32,576观测值与已花4.14215不证明完整长片token/费用/身份通过，完整覆盖缺1例。没有新增3/3门槛|
|A角色身份输入|#1/#3双人真实媒体链与剧情文字审读通过；#2无计划，未覆盖。目录→cast→关键帧→对应视频均有数据引用，仅characters或depends_on不算；真实画面身份未验|
|c7完整剧情|部分通过：无Creative，Producer8→Director14；12事件与120秒保留，s10空镜无角色、其余11镜具身份媒体链；峰值58,401、完整规划7.94256。**16:9比例约束失败**：s10实际9:16、首帧方形、compose未携带目标比例；必要归一化沿第一片尺寸，未执行交付。不替代c3三次测试及其覆盖差异|
|c5三风格可选|规划结构及文字审读通过：Art Deco、浮世绘、包豪斯三个独立n=1节点，choice汇集，10秒动画引用choice.image；实际选择/生成与风格画质未覆盖|
|E/F分批与投影|#1实际append两次形成v2/v3（18/22节点），纠错完整重写v4/v5；实际请求投影旧v1–v4并保留最新v5完整，原state/账本未变。#3的5次append形成v2–v6（6/10/14/18/22节点），完整重写v7修复既有节点；真实请求投影旧v1–v6，最新v7完整13,455字符。c7有4次append（8/8/7/4节点）形成v2–v5，完整v6修复；旧5批参数投影、最新稿完整保留。未观察到真实length截断，截断保护仍仅Mock覆盖|
|B意图改变人工；C局部修订作者正确|B人工意图门真实覆盖：Repair改写→Director revise、false/非空评估→PATCH_INTENT_CHANGED→显式quote批准→Mock交付；不是自动修复覆盖。C审核B场景失败，修订/最终作者/其他镜头复用未覆盖，见下节|

与V10的同名样本对照如下。模型输出存在波动，未做成对或消融实验，不把变化唯一归因于某一项实现。

|维度|V10|V11|解释|
|---|---|---|---|
|c1/c6文本轮数|8 / 8|5 / 5|本轮达到≤6轮；c1视觉各一次、另计|
|c1/c6耗时秒|99.8 / 34.4|55.6 / 27.1|单次观测，不是稳定延迟保证|
|c3进入审核|3/3|2/3|达到原最低门槛，但有Research澄清停点，完整长片覆盖下降|
|c3单轮输入峰值|69,481 / 64,185 / 82,588|完成样本56,366 / 57,616；未完成样本32,576|只将两个完成样本判为完整长片≤60k通过|
|c3完整规划credits|9.28397 / 12.22532 / 10.44906|完成样本8.59793 / 8.57859；未完成样本完整费用null|未完成样本已花4.14215仍计总账，不当作低成本成功|
|c5逐张风格|单prompt、n=3，未逐张表达|三个风格独立n=1，经choice驱动视频|本轮规划和离线引用执行通过；未生成真实图片比较画风|

c3 #1最终Director请求上下文由263,030压到130,977字符，旧作者参数投影4处、成功回执压缩22条；仍超60,000字符软目标，实际峰值56,366 token符合另一个量纲的目标。不能无对照实验将全部改善归因于F。#1第三镜kf03仅供shot03使用，适合作后续局部修订；仅计划图适用得到确认；后续执行在kf01上传预处理失败，未覆盖局部Patch、实际复用或重新交付。

c3 #3最终Director请求196,601→123,408字符，投影6处旧作者参数；Producer为137,116→88,794，均仍超60,000字符软目标。另一项取舍需Claude审读：旧工具契约在错误作者轮次已被投影为带精确重读地址/hash的标记，Agent没有重读，编译失败后才重新读5份契约并恢复。原响应完整，没有供应商输出截断；这仅确认时间关联，不能把错误唯一归因于压缩，也不能把既有工具结果压缩全部归因于V11f。可评审为当前起草工具保留精简合同或明确先重读，本轮不改策略。c7同样在第一个镜头append轮只保留旧契约的重读标记，错误后才重读6份合同；最终Director上下文200,348→122,284字符，最大整稿输出7,089 token接近8k限额。实际未截断不保证更大计划安全，也不能将默认参数约束漏检归结为压缩。

## 混合执行与局部修订

**新Repair：人工意图门已覆盖。** Run `agent_3288fb43f99d44e2` 复用8秒橘猫窗台跳舞计划，规划期1.65175 credits/8轮另记。正式批准v1并给30 credits修复额度后，在唯一video节点注入一次Mock content_policy；提交状态not_submitted、无provider_task_id，不是真实供应商政策判定。真实Repair 3轮 + 独立Director 4轮，共新增7次文本请求；调用计数111→118；新增输入132,345、输出3,802 token、峰值26,385，LLM费用1.36147。

|修复步骤|冻结证据与判定|
|---|---|
|Repair提议|仅update_inputs(video.prompt)，删去“跳舞”字面表达、改为前爪交替抬起/身体摇摆；保留橘猫、窗台、阳光以及模型/8秒参数。是否由“跳舞”触发拒绝只是模型猜测，注入不提供该因果证据|
|Director审阅|verdict=revise，恢复“跳舞”字面并保留动作描述；最终intent_preserved=false、changed_elements非空，指出原Repair削弱点名内容及审核原因不确定。最终before/after均含“跳舞”，不能把保守false直接说成最终草稿已删除该词；这一保守人工控制有效，但reason部分回指原Repair删除字面表达，应由Claude评审最终草稿与评估说明是否一致|
|人工批准|Patch `patch_6f765a6ca12842b3`，scope=only、base_version=1、quote=`9cdb855e92e552757d939a18ceef35d947ec8cb38ade64e3fab0950d1a670860`；只重做video、报价8演示credits，reuse/continuation空。automatic.eligible=false，原因PATCH_INTENT_CHANGED；进入attention/awaiting_approval后由测试脚本模拟用户、用该quote_id显式approve_patch，未自动放行|
|执行与交付|批准后v2执行，video成功→awaiting_result_review→显式approve_results→success；下载1个Mock MP4，9,651字节、SHA `2871813c1b66f5e9b174d78fb0b19f333e861dddbbaee46cc09578a2159a32ee`。这是单视频直接交付，不误写为ZIP打包|
|覆盖及安全|manual_intent_path_covered=true、safe_control_flow=true、repair_delivery_covered=true；automatic_repair_delivery_covered=false。Mock提交2次（1次注入失败、1次成功），写出视频1个、图像0。安全断言真实图/视频/媒体HTTP/适配器尝试及网络/媒体阻断均0且passed；不是独立抓包证明|
|费用与错误|新增真实LLM1.36147（Repair0.39347、Director0.96800），Mock16=注入失败估计8+重做8，混合增量17.36147；含原规划的本Run总额19.01322。失败估计不代表真实服务商收费。生成JOB_FAILED为预期注入，不能写成真实供应商审核失败；原提议173与审阅179的输入已由[独立审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-failure-intent-review.md)核对；最终changed_elements不能单独证明Repair删字，需引用propose_patch原输入|

归档：[唯一hybrid结果](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/hybrid_V11-failure-intent-agent_3288fb43f99d44e2_agent_3288fb43f99d44e2.json)，SHA `d30a8e00b7bdbd17de22eff83ee5d4cf4e45606dcfc8bacf81af624fa8a34fd9`；对应private_profile SHA `2c9248750730d24b5eab98d81767c76e456516606db664f0bec61de73a033b9f`。三项动作approve_plan/approve_patch/approve_results均返回202；外层进程exit0由执行代理记录。已保存原提议、最终审阅草稿、不可变评估引用、引用quote的动作与状态序列，不伪造模型输出。

**历史反例：未执行。** 本次新Repair已实际覆盖人工意图门，无需再用V10固定反例追加真实Director调用；不声称另做了历史反例审阅。

**审核B：执行失败，核心修订验收未覆盖。** 复用c3 #1 `agent_64a9a3fd07bb437a`，未新增规划或真实LLM调用。批准v1后，两张cast由Mock生成成功；批准cast_deepseek预览后，kf01的i2i参考预处理进入真实上传辅助入口，护栏在原函数执行前阻断，Run转attention。第二个cast的审批随后返回409；没有到awaiting_result_review，没有发送“只改第三镜”的修订请求，没有Patch/quote/v2，因此不能宣称局部范围、可信作者、实际重做/复用或交付通过。

|证据|结果|
|---|---|
|预览与失败|approve_plan 202；两张cast成功；approve_gate(cast_deepseek) 202；kf01失败，INTERNAL_ERROR/submit_unknown，recovery_action=stop；最终attention/v1|
|真实调用与媒体|真实LLM增量0；新增Mock提交2、写图2。kf01在进入Mock submit前失败，因此事件层新增2次提交，但生成账本包含3项；不能要求二者相等|
|费用|新增Mock估计6 credits=2张成功cast各2+kf01上传前失败估计2。该Run含原规划总额14.59793；没有真实图片消费或上传|
|级联409|harness已读取Run=attention的新视图，但gates只看cast成功/preview/未批准，不检查Run状态，仍审批cast_gpt；服务正确返回INVALID_AGENT_STATE。不是陈旧计划版本问题，也不是产品审批缺陷|
|直接原因|NodeRunner._i2i_test_image_adapter_payload直接构造DashScopeMultimodalSyncAdapter，绕过ADAPTERS Mock工厂；use_mock=false的预处理走原class上传入口。safety替换入口整段拒绝，原GET/OSS POST未执行；属于混合评测Mock覆盖缺口|
|覆盖边界|审核B/局部修订未执行，C作者归一化本轮仅有离线覆盖；不扩大修改范围、不补调用、不清除失败。应修复评测预处理Mock覆盖与attention诊断、补回归后再另轮补验|

[唯一story归档](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/results/hybrid_V11-story-agent_64a9a3fd07bb437a_agent_64a9a3fd07bb437a.json) SHA `e2eaff943f76fdca682ee19f7da8e237ee2af3614f77f3a69dcb9e90f7f2582b`；private_profile SHA `f80921f23ab4dd88e4ecd1b57c035a4cff384a9ca865ce829c2d1868bccc149e`。场景状态failed；safety_assertions.passed=false、blocked_media_attempts=1。失败归档和共享阻断记录均保留。[调用链审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/story-agent_64a9a3fd07bb437a-failure-review.md)与[独立安全复核](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-story-safety-review.md)一致：任务submission_state=unknown是通用错误分类，不等于真实HTTP未知；审计unknown/reserved=0。
## 最终费用、安全与真实失败

授权边界：文本deepseek-v4.1-flash，视觉qwen3.7-plus，共享上限400次；真实图片/视频/上传禁止。全轮仅用临时SQLite/存储，未连接真实MySQL/Redis或改.env。最终总量含全部成功、未完成和失败样本，以下为停机后的实际记录。

|指标|最终值|
|---|---|
|物理文本 / 视觉 / 总请求|117 / 1 / **118**，分别为deepseek-v4.1-flash和qwen3.7-plus，物理请求均success；未达400上限|
|输入 / 输出token；单轮峰值|3,453,837 / 73,746；58,401。文本输入3,452,462/输出72,503；视觉输入1,375/输出1,243|
|usage缺失；unknown/reserved；未映射请求|均0|
|真实图片 / 视频 / 媒体HTTP / 上传|均0；有1次媒体上传辅助入口尝试被阻断，不能写零越界尝试。blocked_network_attempts=0|
|LLM/视觉 / Mock媒体 / 其他演示credits|35.30201 / 22 / 0.8；Mock22含失败估计，其他0.8为c3 #2 Mock检索|
|唯一账本计入总额；pending/running预留|**58.10201**；预留0。8次规划34.74054 + Repair混合17.36147 + story混合6 = 58.10201|
|唯一逻辑invocation / 状态|183：177成功、4拒绝、2失败；4 rejected不计费用，不能将183当成真实请求数|
|对账与安全|data_quality=passed；reconciliation=passed，118次物理/逻辑模型请求按Run聚合usage相等；**safety=failed**，1次上传入口阻断使零越界尝试目标失败|
|最终统计|read_at=2026-10-20T16:42:13.229818+00:00，SHA `187becf01091e43341631ffdce1c79da51581892630e4f141732560df4860641`|

全轮Mock事件为mock_submit=4、写图2、写视频1、content_policy注入1；生成账本有3张图/2段视频调用，含kf01提交前失败，因此不与submit事件逐条等同。物理模型请求均成功不表示工具/流程无错误。真实媒体零调用的结论来自受控入口和共享审计，非独立网络抓包。

物理次数来自real_call_audit.sqlite.calls；费用按eval.db唯一(budget_scope, invocation_id)，排除rejected、预留单列。规划/混合/profile/JSON别名不得重复计费；credits不是货币账单，Mock费用不是真实媒体消费。worker停止后以mode=ro、query_only读取；跨库不具原子快照。安全、数据质量或对照不通过先停止查因，不能只看最终状态。固定零计数字段不能独立证明无网络调用。

|真实阶段/Run/调用|错误码/字段/节点|根因与证据|确认程度|恢复与代价|
|---|---|---|---|---|
|c1 / tinv_31e20a113a8e4fa3|MODEL_CAPABILITY_MISMATCH，级联INVALID_DELIVERABLE / image|目录列出Qwen能力但本Run未指定模型、仅允许服务器默认Wan；单参考不触发多参考回退。选型失败导致缺output metadata，非交付字段拼错；无证据说明Qwen不支持i2i或1024尺寸非法|已确认，见[c1审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c1-agent_bbc41ab735584c4b-review.md)|下一轮改wan2.7-image后成功，5文本轮内完成；brief首次写入成功，无Schema纠错|
|c5 / call_bd9dc210d3d94f69a9948193|SKILL_RESOURCE_NOT_FOUND|将plan-review所属视频示例路径传给image-create；路径存在，正文第二句只给相对路径有歧义。随后加载plan-review并以相同路径成功读取，非资源缺失/损坏|已确认归属错误；文案歧义为解释，见[c5审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c5-agent_4fda990daeaa4548-resource-review.md)|8文本轮，brief/Plan各首次写成功，最终及历史编译码均空；未为单例改Skill或重跑|
|c1 外层runner|evaluation_exit_code=null，runner status=failed|局部LASTEXITCODE遮蔽全局原生命令退出码；[补记](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate-runner-exitcode-fix.md)含零网络复现和8项Stub验证，修为显式global读取|遮蔽根因已确认；c1原进程退出码已丢失、无法恢复|原失败回执保留，未伪造exit0或重跑c1；产品规划成功依据唯一归档及安全/对账补证，不能写runner首轮通过|
|c3 #1 / tinv_8b53490ff68c41f7|INVALID_WORKSPACE_PAYLOAD / brief.confidence|首次brief漏必填confidence，补0.9后保存；不是示例已消除所有Schema纠错|已确认，见[c3 #1审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c3-agent_64a9a3fd07bb437a-review.md)|1次brief纠错；其成本已在22轮中|
|c3 #1 / draft v3–v5|PLAN_INVALID_STORY_REFERENCE、INVALID_INPUT、UNTYPED_REFERENCE、INVALID_NODE_MODEL、MISSING_PLAN_OUTPUT、INVALID_DELIVERABLE|story_ref误指brief；单参考Wan帧kf03/04用了不支持的1536*864（模型口述1920不可信）；视频image、probe/qc/package的media等为未声明引用字段。compose把compress_output放入params触发INVALID_NODE_MODEL，继而级联缺输出/交付|已确认；失败检查16+5条issue不等于21个独立根因，详见同一审阅|v4重排人物/镜头、全稿改尺寸/引用，v5将compress_output放inputs后通过；并非只改两个尺寸的最小修复，未观察到真实截断|
|c3 #2 / fetch_page 1次、download_reference 2次|TOOL_FORBIDDEN / run_id|工具Schema必填run_id，服务器ToolContext已有实际ID，但Research全部9次真实模型输入均未提供它。模型自造research-deepseek-chatgpt，三次在require_run作用域检查处被拒，未抓取/下载成功|已确认的新运行时/契约上下文缺口，见[c3 #2审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c3-agent_9fd28fe814b142e7-review.md)|护栏正确阻断；第一次获知不匹配后仍用同一假ID尝试两次下载。交Claude审定可信上下文/服务端绑定方案，保留隔离校验；本轮不改源码/提示词/Skill|
|c3 #2 / tinv_fcee412b8ad34dc8、tinv_2605f393549f40ec、tinv_c7f052d107c7435e|INVALID_WORKSPACE_PAYLOAD、INVALID_RESEARCH_DOSSIER、INVALID_AGENT_OUTPUT|research_needs字符串应为query/reason对象；空候选dossier却塞入通用策略问题，不符合单entity候选映射；returned结果多带仅completed允许的dossier_ref|已确认，连同上述3个scope错误共6条失败回执|改brief对象、移除dossier问题保留缺口、移除returned额外字段；Producer改用ask_user，停awaiting_input。Mock检索演示页独立不足以证明真实品牌/主流形象，未换真实检索或补造候选|
|c3 #3 / draft@6→@7|UNTYPED_REFERENCE×11、INVALID_NODE_MODEL×1、INVALID_DELIVERABLE×2|8视频用未声明image而非first_frame_artifact_id；probe/qc/package用media，package还虚构qc.report；compose把compress_output放params，其clips字段也错但未另外报码；2条交付为缺输出级联，交付字段原本正确|已确认，见[c3 #3审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c3-agent_9d7371a4fcd24c9a-review.md)；本例无brief纠错/MISSING_PLAN_OUTPUT/story引用错误|重读5份合同和v6、完整重写v7后通过；同时修正anim01/05/06/07的站姿/合作/领奖/握手动作衔接，不能称仅改字段且提示词不变；23轮无截断|
|c7 / draft@5→@6|UNTYPED_REFERENCE×25、INVALID_NODE_MODEL×1、INVALID_DELIVERABLE×2|11关键帧误用images、11视频误用image、probe/qc/package误用media及probe.probe/qc.report；compose非空params被拒，clips错误被更早拒绝遮住；2交付缺输出连带|已确认，见[c7审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c7-agent_53460024db194288-review.md)；28 issues，brief首次成功|重读6合同与v5、整稿v6修复，全部媒体prompt不变；结构恢复但size/ratio仍缺失，22轮无截断|
|c7 / s10_video、11首帧、compose|语义约束：16:9未保留（没有对应编译问题码）|原作者v1–v6省略size/ratio，validate_generation_model合并方图/9:16默认，能力检查未比较brief16:9；不是Agent显式选竖屏。元数据/QC也未核对目标比例|已确认原始/编译及调用路径，见同一c7审阅；定妆图方形本身不是问题，视频关键帧与空镜参数才是偏差|拼接规格归一化沿第一片宽高，compress=false不保证横屏，也不禁止必要归一化；未执行媒体，不能断言最终必然方屏或拼接失败。冻结轮未改/重跑|
|c2 / 首次check_plan|INVALID_NODE_INPUT、级联INVALID_DELIVERABLE|把仅支持i2v的animate_shot当t2v，缺必填first_frame_artifact_id；并非时长/预算问题，brief同轮首次写入成功|已确认，见[c2规划审阅](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-case-review-tools/c2-agent_3288fb43f99d44e2-planning-review.md)|读取Blueprint/plan-review中的generate_video合同，改generate_video(mode=t2v)通过并保存draft@1；8轮。只读check失败无副作用ledger行，11行success不代表全程无错误|
|新Repair / video|DataInspectionFailed→JOB_FAILED|测试注入一次content_policy，无provider_task_id；不能推断拟人化/“跳舞”是真实供应商审核原因|注入及修复路径已确认；具体政策原因未验证|真实Repair3/Director4后人工意图门，手动quote批准成功交付Mock视频；增量17.36147演示credits|
|审核B预处理 / kf01|INTERNAL_ERROR / submit_unknown；上传入口阻断|直接构造真实adapter的参考图预处理绕过Mock工厂，safety入口阻断原上传函数，原GET/OSS POST未执行|确认Mock覆盖缺口与停机状态；不称真实上传成功|新增真实LLM0、Mock估计6；保留1次阻断，safety failed，审核B修订未覆盖|
|审核B harness / cast_gpt|409 INVALID_AGENT_STATE|harness已读到attention新视图，仍仅凭节点success/preview条件批准另一个cast，未检查Run必须awaiting_gate；服务正确拒绝|级联状态诊断问题，不是旧版本或审批授权缺陷|场景failed且停止，未清记录/重采样/追加调用|

全部中间Schema纠错、编译拒绝、预期注入与实际护栏阻断保留。真实响应未观察到length或AGENT_OUTPUT_TRUNCATED；截断保护仅离线验证，不能伪称实际发生过。未因额度耗尽停止；停止原因是审核B触达被禁止的媒体上传入口。

## 证据与 Claude 交接

唯一归档SHA-256：

|样本|SHA-256|
|---|---|
|c1|`6747b61846b9b6845f117313d9e643e386690fee4c2990eda8c6ee9b5b0dfa68`|
|c6|`c89f2fb840c1f8fa4418f114d87da9f74ed1738d9c199d596b37582c39635674`|
|c5|`2e2ead96e57b57500ecdf5dcbc15bcc880917ba5e0b499d822e652165055a8eb`|
|c3 #1|`b35c5db478bf38221448899cfd1d0f61a42cc68fdf7c2952dee892389927c7ff`|
|c3 #2|`708efd68177e29f1c8bbe84e8f7949eb21ea54f700d3075b3122e8111bee5810`|
|c3 #3|`de028cedde9db386e7b47ed0664dbae1c1f79c0d56a5367b28c248fada9e709d`|
|c7|`2ec424a0141171672eabcd2c7483deee39f8d40488e8b81863d9dea6785316ea`|
|c2规划|`4d06bd4207370b724609d5fd5aa6943b193187c774f97425e5b5902409b03d10`|

[最终只读统计](C:/Users/MingZheYang/AppData/Local/Temp/cinecrew-v11-gate5-20261021-01/readonly-statistics/v11-statistics.json) SHA=`187becf01091e43341631ffdce1c79da51581892630e4f141732560df4860641`，以最终118次/58.10201为准。7个已完成规划均planning_cost_slice_verified、ledger_slice_verified、physical_slice_verified=true，规划对账通过；c3 #2无submit，完整规划费用null、planning_cost_slice_verified=false，已花费用仍计入总账。其峰值阈值布尔只说明已发生请求未超，不证明完成长片验收。统计为Run聚合，没有共享response_id证明逐物理请求一一关联；两个只读SQLite事务不具跨库原子性，本次在worker停止后核对。

c3 #1审阅快照SHA=`c34f86c80af35e31eaa8228bed44dc25c252b88a33a1bf8e7b23ff651a07887f`；#2审阅快照SHA=`cd30b75682a425ea1c228a755654d7b4ce596fdc2b87dfc2c1daf6899a83effe`，路径见各自根因报告；#3快照SHA=`ce6c19692b52ec5b58079edcc1c513dfb7de9e96cb0c18fa4ede3cc29c14f5d6`，c2规划快照SHA=`525a262f02c33f85b2c3c21f63d4fabeb78bedbf6ee3d11c5fb62d246a8acd46`。c7快照SHA=`6981509ae1dd8c13166512f7a3752d7c357aba3a7b7edf4fee08811e2d77311e`，完整根因审阅MD SHA=`c31b5d43a6e8b54796eb7d0bc6bd4b4543fde6187204428051d8f32762f8abda`。全部规划、hybrid与profile费用按唯一invocation对账，不因重用Run或多个归档重复计数。Repair审阅使用actual_reviewed_patch/failure_quote；审核B没有形成revision或scope_before_approval，不能补造这些证据。原始错误保留于规范消息、唯一账本和已冻结profile。新增独立审阅SHA：failure-intent=`a88417d1f8cd65f664c60ef84046c2560f2e8899d12d5af232fd91f366fdf37c`；story调用链=`973963bc066bbbb4fb19bf34033aabc5274ebd058563d9fbb63824a25f4afab6`；story安全=`67e66678a5220cfec73155d0a0d6858b085e6b13875b1f738b682079f654eae5`。

研发完成：A–G代码及离线回归全部完成。真实已达：c1/c6效率、c1/c6/c5规划文字结构、c3完成的两例身份链/剧情/60k token/20 credits/无付费死节点、c7无Creative与12事件/120秒/身份链，以及新Repair人工意图门与Mock交付。c3按要求复跑3次，2/3达到原门槛，但较V10的3/3下降，未完成1例没有完整长片覆盖。

明确未达：c7的16:9需求保真；零越界尝试安全目标；审核B及其局部修订/作者/复用/重新交付验证。Research工具要求run_id却未向模型提供可信ID，是已确认运行时/契约缺口；Mock检索自身也不能提供真实品牌证据。工具契约在起草期间被投影、报错后重读恢复，以及Director最终恢复“跳舞”后仍以旧删除理由作保守false评估，是需要Claude审读的取舍与语义风险，不能无对照实验扩大为唯一致因。

建议Claude按缺陷和覆盖分别决定V-Gate5：先审定比例从brief到生成/交付的约束校验、Research可信Run上下文、混合预处理Mock覆盖与attention诊断；各自按契约/任务分支补回归，确认恢复条件后在已有授权及总额度内补审核B，保留本轮失败与累计调用记录。当前不修改冻结源码/提示词、不清账、不重采样、不追加真实调用；报告不等于Gate通过，不擅自进入V8。

身份校验的保证范围仍是**已声明角色**的真实数据引用链；`characters`是否漏掉prompt隐含人物、实际画面是否相似都不能由该编译器保证（契约V.21.1已明示）。c3的粗纲已有比赛→波折→握手的事件顺序与结局，按V.21.4可由Director补镜头；本轮未委派Creative不能直接判为违规跳过创作。粗纲完整性的模型判断和不同分工的质量收益仍需另行评估。

未验证：真实媒体画质、身份相似度、逐张风格质量；真实选择/改选执行、HTTP在途崩溃、同Run多worker争用、MQ吞吐。本轮未覆盖或未重测的V10能力不记为通过；用户私人技术笔记及全部原始失败证据保留。
