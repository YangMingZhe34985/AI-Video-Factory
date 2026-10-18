async (page) => {
  // This file is a direct browser_run_code_unsafe filename entry, not a Node CLI.
  // Keep the API interceptor installed after completion: the page may still poll.
  // Synthetic public projections only; no server, model or billing request is allowed.
  const copy = value => JSON.parse(JSON.stringify(value));
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const reports = [], layouts = [];
  const currentUrl = (() => { try { return new URL(page.url()); } catch { return null; } })();
  const baseUrl = currentUrl?.protocol === 'http:' && currentUrl.hostname === 'localhost'
    ? currentUrl.origin : 'http://localhost:4173';
  const baseRun = {"run_id":"demo_v3_review","schema_version":3,"status":"awaiting_plan_review","text":"做一支约十秒的温室纸船短片，两段内容要连贯，先让我确认画面。模型与单价均为演示数据。","attachments":[],"created_at":"2026-10-19T10:00:00+08:00","updated_at":"2026-10-19T10:00:00+08:00","estimated_spent":5,"budget_limit":40,"planning_budget":{"limit":20,"spent":5},"agents":[{"delegation_id":101,"parent_id":null,"agent":"producer","status":"completed","task_summary":"协调需求理解与计划提交","credits":2,"steps":4},{"delegation_id":102,"parent_id":101,"agent":"creative","status":"completed","task_summary":"构思纸船进入温室的两段短故事","credits":1,"steps":2},{"delegation_id":103,"parent_id":101,"agent":"director","status":"completed","task_summary":"准备镜头计划与首帧预览门","credits":1,"steps":3},{"delegation_id":104,"parent_id":103,"agent":"critic","status":"completed","task_summary":"检查时长、依赖与费用","credits":1,"steps":2}],"pending_card":null,"message":"计划已完成，等待你审核。","error":null,"plan":{"title":"纸船与晨光 · 两镜头演示","goal":"创作约 10 秒的温室纸船短片，用场景切换衔接两个镜头。全部角色、提示词和费用为浏览器演示数据。","deliverables":[{"kind":"video","node_id":"compose","output":"artifact_id"},{"kind":"package","node_id":"package","output":"artifact_id"}],"nodes":[{"id":"s01_first","tool":"generate_image","inputs":{"mode":"t2i","prompt":"演示画面：蓝色纸船驶入清晨的玻璃温室。","reference_artifact_ids":[]},"model_id":"qwen-image-3.0","params":{"n":1,"size":"1280*720"},"stage":"creation","depends_on":[],"gate":"preview","origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"演示计划：验证界面与受控动作，不代表真实生成效果。"},{"id":"s01","tool":"animate_shot","inputs":{"first_frame_artifact_id":{"ref":"s01_first.image"},"prompt":"演示动作：镜头缓慢跟随纸船前进，露珠轻落。"},"model_id":"wan2.7-i2v","params":{"duration":5},"stage":"creation","depends_on":[],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"第一段 5 秒，沿已确认首帧生成。"},{"id":"s02_first","tool":"generate_image","inputs":{"mode":"t2i","prompt":"演示画面：同一温室的花瓣打开，蓝色纸船在池边停靠。","reference_artifact_ids":[]},"model_id":"qwen-image-3.0","params":{"n":1,"size":"1280*720"},"stage":"creation","depends_on":[],"gate":"preview","origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"独立构图；可以与第一段的首帧并行准备。"},{"id":"s02","tool":"animate_shot","inputs":{"first_frame_artifact_id":{"ref":"s02_first.image"},"prompt":"演示动作：花瓣打开，镜头抬升至暖光，使用场景切换衔接。"},"model_id":"wan2.7-i2v","params":{"duration":5},"stage":"creation","depends_on":[],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"演示计划：验证界面与受控动作，不代表真实生成效果。"},{"id":"compose","tool":"compose_video","inputs":{"video_artifact_ids":[{"ref":"s01.video"},{"ref":"s02.video"}],"compress_output":false},"model_id":null,"params":{},"stage":"delivery","depends_on":[],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"按镜头顺序拼接，默认不生成压缩副本。"},{"id":"probe","tool":"probe_media","inputs":{"artifact_id":{"ref":"compose.artifact_id"}},"model_id":null,"params":{},"stage":"delivery","depends_on":[],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"验证成片媒体结构。"},{"id":"qc","tool":"qc_video","inputs":{"artifact_id":{"ref":"compose.artifact_id"},"video_artifact_ids":[{"ref":"s01.video"},{"ref":"s02.video"}]},"model_id":null,"params":{},"stage":"delivery","depends_on":["probe"],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"核对批准时长与成片完整性。"},{"id":"package","tool":"package_story","inputs":{"artifact_id":{"ref":"compose.artifact_id"}},"model_id":null,"params":{},"stage":"delivery","depends_on":["qc"],"gate":null,"origin":{"agent":"director","skills":["story-video"],"blueprint":{"name":"story-video","version":2}},"rationale":"通过质检后打包主片与批准素材。"}],"stages":[{"id":"creation","label":"镜头创作"},{"id":"delivery","label":"成片交付"}],"plan_version":2,"estimates":{"nodes":[{"node_id":"s01_first","model_id":"qwen-image-3.0","mode":"t2i","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"s01","model_id":"wan2.7-i2v","mode":"i2v","estimated_cost":5,"input_video_seconds":0,"output_video_seconds":5,"pricing":{}},{"node_id":"s02_first","model_id":"qwen-image-3.0","mode":"t2i","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"s02","model_id":"wan2.7-i2v","mode":"i2v","estimated_cost":5,"input_video_seconds":0,"output_video_seconds":5,"pricing":{}},{"node_id":"compose","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"probe","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"qc","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"package","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}}],"total_credits":12,"video_seconds":10,"generated_video_seconds":10,"demo":true},"experimental":false},"plan_issues":[],"estimates":{"nodes":[{"node_id":"s01_first","model_id":"qwen-image-3.0","mode":"t2i","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"s01","model_id":"wan2.7-i2v","mode":"i2v","estimated_cost":5,"input_video_seconds":0,"output_video_seconds":5,"pricing":{}},{"node_id":"s02_first","model_id":"qwen-image-3.0","mode":"t2i","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"s02","model_id":"wan2.7-i2v","mode":"i2v","estimated_cost":5,"input_video_seconds":0,"output_video_seconds":5,"pricing":{}},{"node_id":"compose","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"probe","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"qc","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}},{"node_id":"package","model_id":null,"mode":null,"estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0,"pricing":{}}],"total_credits":12,"video_seconds":10,"generated_video_seconds":10,"demo":true},"experimental":false,"nodes":[{"node_id":"s01_first","tool":"generate_image","stage":"creation","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":"preview","gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":[],"updated_at":null},{"node_id":"s01","tool":"animate_shot","stage":"creation","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["s01_first"],"updated_at":null},{"node_id":"s02_first","tool":"generate_image","stage":"creation","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":"preview","gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":[],"updated_at":null},{"node_id":"s02","tool":"animate_shot","stage":"creation","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["s02_first"],"updated_at":null},{"node_id":"compose","tool":"compose_video","stage":"delivery","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["s01","s02"],"updated_at":null},{"node_id":"probe","tool":"probe_media","stage":"delivery","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["compose"],"updated_at":null},{"node_id":"qc","tool":"qc_video","stage":"delivery","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["compose","probe","s01","s02"],"updated_at":null},{"node_id":"package","tool":"package_story","stage":"delivery","status":"pending","attempt":0,"job_id":null,"estimated_cost":0,"gate":null,"gate_approved":false,"artifacts":[],"error":null,"reused_from_task_id":null,"retained":false,"source_plan_version":null,"depends_on":["compose","qc"],"updated_at":null}],"results":[],"summary":{"steps_total":8,"steps_success":0,"steps_failed":0},"patches":[],"repair_budget":{"limit":0,"committed":0,"remaining":0},"action_pending":false,"resume_count":0,"mock":true};
  const roles = ['producer', 'creative', 'director', 'critic'];
  const allSteps = Array.from({length: 37}, (_, index) => ({
    agent: roles[index % roles.length], kind: index < 5 ? 'llm' : 'tool',
    tool: index < 5 ? null : ['read_workspace', 'check_plan', 'list_skills'][index % 3],
    summary: index < 5 ? '完成一次规划回合' : '调用受控工具', credits: index < 5 ? 1 : 0,
    at: `2026-10-19T10:00:${String(index).padStart(2, '0')}+08:00`,
  }));
  baseRun.steps = allSteps.slice(0, 30);
  const variants = {"demo_v3_review":{"fields":{},"nodes":{}},"demo_v3_input":{"fields":{"run_id":"demo_v3_input","status":"awaiting_input","estimated_spent":2,"planning_budget":{"limit":20,"spent":2},"agents":[{"delegation_id":201,"parent_id":null,"agent":"producer","status":"awaiting_input","task_summary":"确认用户想采用的纸船风格","credits":2,"steps":2}],"pending_card":{"card_id":"demo_card_1","asked_by":"producer","questions":[{"question_id":"boat_style","text":"你希望纸船使用哪种形象？","why":"两种视觉风格都符合需求，需要确认后再规划。","options":[{"option_id":"blue","label":"蓝色折纸","detail":"形体简洁，适合温室暖光。","image_artifact_id":"demo_s01_png"},{"option_id":"white","label":"白色手绘","detail":"柔和描边，偏插画风格。","image_artifact_id":"demo_s02_png"}],"recommended_option_id":"blue","allow_free_text":false,"blocking":true,"default_option_id":null},{"question_id":"mood","text":"故事氛围偏向哪一种？","why":"可省略，默认使用轻松温暖的节奏。","options":[{"option_id":"warm","label":"温暖治愈","detail":null,"image_artifact_id":null},{"option_id":"wonder","label":"奇妙探索","detail":null,"image_artifact_id":null}],"recommended_option_id":"warm","allow_free_text":true,"blocking":false,"default_option_id":"warm"}]},"message":null,"plan":null,"estimates":null,"summary":{"steps_total":0,"steps_success":0,"steps_failed":0},"nodes":[],"steps":[{"agent":"producer","kind":"ask","tool":"ask_user","summary":"请求用户澄清","credits":0,"at":"2026-10-19T10:00:00+08:00"}]},"nodes":{}},"demo_v3_gate":{"fields":{"run_id":"demo_v3_gate","status":"awaiting_gate","estimated_spent":7,"message":"两个首帧已完成，请分别确认；视频节点仍等待对应预览门。","summary":{"steps_total":8,"steps_success":2,"steps_failed":0},"repair_budget":{"limit":3,"committed":0,"remaining":3}},"nodes":{"s01_first":{"status":"success","attempt":1,"job_id":"demo_job_s01_first","estimated_cost":1,"artifacts":[{"artifact_id":"demo_s01_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s01_png/preview","download_url":"/api/artifacts/demo_s01_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02_first":{"status":"success","attempt":1,"job_id":"demo_job_s02_first","estimated_cost":1,"artifacts":[{"artifact_id":"demo_s02_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s02_png/preview","download_url":"/api/artifacts/demo_s02_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"}}},"demo_v3_executing":{"fields":{"run_id":"demo_v3_executing","status":"executing","estimated_spent":17,"message":"对应预览门已批准，两个无相互依赖的视频可并行调度。","summary":{"steps_total":8,"steps_success":2,"steps_failed":0},"repair_budget":{"limit":3,"committed":0,"remaining":3}},"nodes":{"s01_first":{"status":"success","attempt":1,"job_id":"demo_job_s01_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s01_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s01_png/preview","download_url":"/api/artifacts/demo_s01_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s01":{"status":"running","attempt":1,"job_id":"demo_job_s01","estimated_cost":5,"updated_at":"2026-10-19T10:00:00+08:00"},"s02_first":{"status":"success","attempt":1,"job_id":"demo_job_s02_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s02_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s02_png/preview","download_url":"/api/artifacts/demo_s02_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02":{"status":"running","attempt":1,"job_id":"demo_job_s02","estimated_cost":5,"updated_at":"2026-10-19T10:00:00+08:00"}}},"demo_v3_patch":{"fields":{"run_id":"demo_v3_patch","status":"attention","estimated_spent":17,"message":"导演已审阅修改方案，请选择影响范围并确认最新报价。","results":[{"kind":"video","node_id":"compose","output":"artifact_id","artifact_id":"demo_master_mp4","preview_url":"/api/artifacts/demo_master_mp4/preview","download_url":"/api/artifacts/demo_master_mp4/download"},{"kind":"package","node_id":"package","output":"artifact_id","artifact_id":"demo_sources_zip","preview_url":"/api/artifacts/demo_sources_zip/preview","download_url":"/api/artifacts/demo_sources_zip/download"}],"summary":{"steps_total":8,"steps_success":8,"steps_failed":0},"patches":[{"patch_id":"demo_patch_1","status":"awaiting_approval","base_version":2,"scope":"only","author":"director","reason":"用户希望第一段首帧更明亮；只修改与联动重做的费用不同。","diff_summary":[{"op":"update_inputs","node_id":"s01_first","fields":["prompt"]}],"diff_preview":[{"op":"update_inputs","node_id":"s01_first","before":{"prompt":"演示画面：蓝色纸船驶入清晨的玻璃温室。"},"after":{"prompt":"演示画面：明亮的清晨暖光穿过玻璃温室，蓝色纸船停在前景。"}}],"review":{"verdict":"approve","reason":"修改范围明确；only 保留原视频，cascade 重做受影响的第一段并重新拼接。"},"auto_approved":false,"approved_version":null,"quote":{"patch_id":"demo_patch_1","base_version":2,"scope":"only","can_apply":true,"manual_can_apply":true,"affected_node_ids":["s01_first","s01","compose","probe","qc","package"],"execute_node_ids":["s01_first","compose","probe","qc","package"],"reused_node_ids":["s02_first","s02"],"kept_node_ids":["s01"],"removed_node_ids":[],"continuation_node_ids":[],"estimated_credits":{"repair":1,"continuation":0,"total":1},"node_costs":[{"node_id":"s01_first","action":"execute","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"s01","action":"retain","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":5},{"node_id":"s02_first","action":"reuse","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"s02","action":"reuse","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":5},{"node_id":"compose","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"probe","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"qc","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"package","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0}],"automatic":{"eligible":false,"reasons":["COMPLETED_OUTPUT_AFFECTED","FAILURE_TRIGGER_REQUIRED","REPAIRABLE_FAILURE_REQUIRED"],"remaining_credits":3},"warnings":[{"code":"RETAINED_HISTORICAL_OUTPUT","message":"保留已完成的第一段视频；新首帧不会改变该段历史画面。","node_id":"s01"}],"issues":[],"demo":true,"quote_id":"demo_quote_only_v2"}}],"repair_budget":{"limit":3,"committed":0,"remaining":3}},"nodes":{"s01_first":{"status":"success","attempt":1,"job_id":"demo_job_s01_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s01_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s01_png/preview","download_url":"/api/artifacts/demo_s01_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s01":{"status":"success","attempt":1,"job_id":"demo_job_s01","estimated_cost":5,"artifacts":[{"artifact_id":"demo_s01_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_s01_mp4/preview","download_url":"/api/artifacts/demo_s01_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02_first":{"status":"success","attempt":1,"job_id":"demo_job_s02_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s02_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s02_png/preview","download_url":"/api/artifacts/demo_s02_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02":{"status":"success","attempt":1,"job_id":"demo_job_s02","estimated_cost":5,"artifacts":[{"artifact_id":"demo_s02_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_s02_mp4/preview","download_url":"/api/artifacts/demo_s02_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"compose":{"status":"success","attempt":1,"job_id":"demo_job_compose","artifacts":[{"artifact_id":"demo_master_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_master_mp4/preview","download_url":"/api/artifacts/demo_master_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"probe":{"status":"success","attempt":1,"job_id":"demo_job_probe","updated_at":"2026-10-19T10:00:00+08:00"},"qc":{"status":"success","attempt":1,"job_id":"demo_job_qc","updated_at":"2026-10-19T10:00:00+08:00"},"package":{"status":"success","attempt":1,"job_id":"demo_job_package","artifacts":[{"artifact_id":"demo_sources_zip","mime_type":"application/zip","preview_url":"/api/artifacts/demo_sources_zip/preview","download_url":"/api/artifacts/demo_sources_zip/download"}],"updated_at":"2026-10-19T10:00:00+08:00"}}},"demo_v3_results":{"fields":{"run_id":"demo_v3_results","status":"awaiting_result_review","estimated_spent":17,"message":"成片与素材包已准备好，等待验收。","results":[{"kind":"video","node_id":"compose","output":"artifact_id","artifact_id":"demo_master_mp4","preview_url":"/api/artifacts/demo_master_mp4/preview","download_url":"/api/artifacts/demo_master_mp4/download"},{"kind":"package","node_id":"package","output":"artifact_id","artifact_id":"demo_sources_zip","preview_url":"/api/artifacts/demo_sources_zip/preview","download_url":"/api/artifacts/demo_sources_zip/download"}],"summary":{"steps_total":8,"steps_success":8,"steps_failed":0},"repair_budget":{"limit":3,"committed":0,"remaining":3}},"nodes":{"s01_first":{"status":"success","attempt":1,"job_id":"demo_job_s01_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s01_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s01_png/preview","download_url":"/api/artifacts/demo_s01_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s01":{"status":"success","attempt":1,"job_id":"demo_job_s01","estimated_cost":5,"artifacts":[{"artifact_id":"demo_s01_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_s01_mp4/preview","download_url":"/api/artifacts/demo_s01_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02_first":{"status":"success","attempt":1,"job_id":"demo_job_s02_first","estimated_cost":1,"gate_approved":true,"artifacts":[{"artifact_id":"demo_s02_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s02_png/preview","download_url":"/api/artifacts/demo_s02_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02":{"status":"success","attempt":1,"job_id":"demo_job_s02","estimated_cost":5,"artifacts":[{"artifact_id":"demo_s02_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_s02_mp4/preview","download_url":"/api/artifacts/demo_s02_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"compose":{"status":"success","attempt":1,"job_id":"demo_job_compose","artifacts":[{"artifact_id":"demo_master_mp4","mime_type":"video/mp4","preview_url":"/api/artifacts/demo_master_mp4/preview","download_url":"/api/artifacts/demo_master_mp4/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"probe":{"status":"success","attempt":1,"job_id":"demo_job_probe","updated_at":"2026-10-19T10:00:00+08:00"},"qc":{"status":"success","attempt":1,"job_id":"demo_job_qc","updated_at":"2026-10-19T10:00:00+08:00"},"package":{"status":"success","attempt":1,"job_id":"demo_job_package","artifacts":[{"artifact_id":"demo_sources_zip","mime_type":"application/zip","preview_url":"/api/artifacts/demo_sources_zip/preview","download_url":"/api/artifacts/demo_sources_zip/download"}],"updated_at":"2026-10-19T10:00:00+08:00"}}},"demo_v3_recovery":{"fields":{"run_id":"demo_v3_recovery","status":"attention","estimated_spent":7,"message":"原操作结果尚待核实，恢复检查会核对同一个受理回执。","error":{"code":"RECOVERY_REQUIRED","message":"规划已停止，请检查步骤记录。"},"summary":{"steps_total":8,"steps_success":2,"steps_failed":0},"repair_budget":{"limit":3,"committed":0,"remaining":3},"action_pending":true},"nodes":{"s01_first":{"status":"success","attempt":1,"job_id":"demo_job_s01_first","estimated_cost":1,"artifacts":[{"artifact_id":"demo_s01_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s01_png/preview","download_url":"/api/artifacts/demo_s01_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"},"s02_first":{"status":"success","attempt":1,"job_id":"demo_job_s02_first","estimated_cost":1,"artifacts":[{"artifact_id":"demo_s02_png","mime_type":"image/png","preview_url":"/api/artifacts/demo_s02_png/preview","download_url":"/api/artifacts/demo_s02_png/download"}],"updated_at":"2026-10-19T10:00:00+08:00"}}}};
  const runs = Object.fromEntries(Object.entries(variants).map(([id, variant]) => {
    const run = Object.assign(copy(baseRun), copy(variant.fields));
    run.run_id = id;
    for (const task of run.nodes) Object.assign(task, copy(variant.nodes[task.node_id] || {}));
    return [id, run];
  }));
  const quoteOnly = {"patch_id":"demo_patch_1","base_version":2,"scope":"only","can_apply":true,"manual_can_apply":true,"affected_node_ids":["s01_first","s01","compose","probe","qc","package"],"execute_node_ids":["s01_first","compose","probe","qc","package"],"reused_node_ids":["s02_first","s02"],"kept_node_ids":["s01"],"removed_node_ids":[],"continuation_node_ids":[],"estimated_credits":{"repair":1,"continuation":0,"total":1},"node_costs":[{"node_id":"s01_first","action":"execute","estimated_cost":1,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"s01","action":"retain","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":5},{"node_id":"s02_first","action":"reuse","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"s02","action":"reuse","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":5},{"node_id":"compose","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"probe","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"qc","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0},{"node_id":"package","action":"execute","estimated_cost":0,"input_video_seconds":0,"output_video_seconds":0}],"automatic":{"eligible":false,"reasons":["COMPLETED_OUTPUT_AFFECTED","FAILURE_TRIGGER_REQUIRED","REPAIRABLE_FAILURE_REQUIRED"],"remaining_credits":3},"warnings":[{"code":"RETAINED_HISTORICAL_OUTPUT","message":"保留已完成的第一段视频；新首帧不会改变该段历史画面。","node_id":"s01"}],"issues":[],"demo":true,"quote_id":"demo_quote_only_v2"};
  const quoteCascade = Object.assign(copy(quoteOnly), {"scope":"cascade","execute_node_ids":["s01_first","s01","compose","probe","qc","package"],"kept_node_ids":[],"estimated_credits":{"repair":6,"continuation":0,"total":6},"automatic":{"eligible":false,"reasons":["COMPLETED_OUTPUT_AFFECTED","FAILURE_TRIGGER_REQUIRED","REPAIRABLE_FAILURE_REQUIRED","REPAIR_BUDGET_EXCEEDED"],"remaining_credits":3},"warnings":[],"quote_id":"demo_quote_cascade_v2"});
  const cascadeNodeChanges = {"s01":{"action":"execute","estimated_cost":5}};
  for (const row of quoteCascade.node_costs) Object.assign(row, cascadeNodeChanges[row.node_id] || {});
  const envelope = data => ({success: true, data});
  const fixture = {
    runs_by_id: runs,
    quotes_by_scope: {only: envelope(quoteOnly), cascade: envelope(quoteCascade)},
    inline_artifacts: {"demo_s01_png":{"mime_type":"image/png","base64":"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII="},"demo_s02_png":{"mime_type":"image/png","base64":"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII="},"demo_sources_zip":{"mime_type":"application/zip","base64":"UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA=="}},
    step_pages_by_run_id: Object.fromEntries(Object.values(runs).map(run => {
      const items = run.run_id === 'demo_v3_input' ? run.steps : allSteps;
      return [run.run_id, Object.fromEntries([1, 2].map(number => [String(number), envelope({
        items: items.slice((number - 1) * 30, number * 30), page: number, per_page: 30, total: items.length,
      })]))];
    })),
  };
  // Old owner-facing projections have request/snapshot, not v3 plan-node fields.
  for (const version of [1, 2]) {
    const title = `历史 v${version} 创作记录 · 浏览器演示`;
    fixture.runs_by_id[`demo_legacy_v${version}`] = {
      run_id: `demo_legacy_v${version}`, schema_version: version, status: 'queued',
      request: version === 1 ? {goal: title, shot_count: 1, budget_limit: 100, mode: 'from_scratch'}
        : {schema_version: 2, text: title, attachment_ids: [], budget_limit: 100},
      snapshot: {}, command: null, error: null, resume_count: 0,
      created_at: baseRun.created_at, updated_at: baseRun.updated_at, estimated_spent: 0,
      text: version === 2 ? title : null, attachments: version === 2 ? [] : null,
      request_spec: null, research_dossier: null, pending_card: null, plan: null,
      results: version === 2 ? [] : null,
      summary: version === 1 ? {total: 1, success: 0, failed: 0, pending: 1}
        : {steps_total: 0, steps_success: 0, steps_failed: 0},
      ...(version === 2 ? {production: null, delivery: null} : {}),
    };
  }
  const h = {fixture, runs:copy(fixture.runs_by_id), actions:[], quotes:[], blocked:[], pageErrors:[], receipts:{}, failNextAction:false, failNextQuote:false, quoteDelay:0, listCount:0, listDelay:0, listResponseCount:0, listRecords:[], detailDelays:{}, detailResponses:[], actionResponses:[], actionDelay:0, assetDelay:0, assetRequests:[]};
  async function waitForCondition(predicate, message, timeout = 5000) {
    const deadline = Date.now() + Math.min(timeout, 9000);
    while (!predicate() && Date.now() < deadline) await page.waitForTimeout(50);
    check(predicate(), message);
  }
  // Stop prior page polling before replacing handlers; never leave a live app unguarded.
  await page.goto('about:blank');
  await page.unroute('**/*');
  page.on('pageerror', error => h.pageErrors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem('auth', JSON.stringify({accessToken:'mock-browser-token',refreshToken:null,user:{id:1,username:'Mock QA'}}));
    localStorage.setItem('settings', JSON.stringify({language:'zh',darkMode:false}));
  });
  await page.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url()), path=url.pathname;
    if (url.protocol !== 'http:' || url.origin !== baseUrl) {h.blocked.push(req.url()); return route.abort();}
    if (!path.startsWith('/api/')) {
      if (['GET', 'HEAD'].includes(req.method())) return route.continue();
      h.blocked.push(`${req.method()} ${path}`); return route.abort();
    }
    const send = (data,status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify({success:status>=200 && status<300,data})});
    const fail = (code,message,status=409) => route.fulfill({status,contentType:'application/json',body:JSON.stringify({success:false,error:{code,message}})});
    if(path==='/api/health') return send({agent_mode:true,mode:'mock',status:'ok'});
    if(path==='/api/models') return send({models:[]});
    if(path==='/api/auth/me') return send({id:1,username:'Mock QA'});
    if(path==='/api/agent/runs' && req.method()==='GET') {
      // Capture on request, not response: delayed polling must carry old state.
      const items=copy(Object.values(h.runs));
      const record={number:++h.listCount,startedAt:Date.now(),respondedAt:null,
        statuses:Object.fromEntries(items.map(item=>[item.run_id,item.status]))};
      h.listRecords.push(record);
      if(h.listDelay) await new Promise(resolve=>setTimeout(resolve,h.listDelay));
      await send({items});
      record.respondedAt=Date.now();h.listResponseCount++;
      return;
    }
    const match=path.match(/^\/api\/agent\/runs\/([^/]+)(?:\/(steps|actions|patch-quote))?$/);
    if(match) {
      const id=match[1], part=match[2], run=h.runs[id];
      if(!run) return fail('NOT_FOUND','未知演示任务',404);
      if(!part && req.method()==='GET') {
        const value=copy(run),startedAt=Date.now();
        if(h.detailDelays[id]) await new Promise(resolve=>setTimeout(resolve,h.detailDelays[id]));
        await send(value);h.detailResponses.push({id,startedAt,at:Date.now()});return;
      }
      if(part==='steps') {
        const number=url.searchParams.get('page') || '1';
        const data=fixture.step_pages_by_run_id[id]?.[number];
        return data ? route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)}) : send({items:[],page:Number(number),per_page:30,total:0});
      }
      const body=req.postDataJSON();
      if(part==='patch-quote') {
        h.quotes.push(copy(body));
        const value=copy(fixture.quotes_by_scope[body.scope || 'only'].data);
        if(h.failNextQuote) {h.failNextQuote=false;return fail('QUOTE_UNAVAILABLE','演示报价暂不可用',503);}
        if(h.quoteOverride) Object.assign(value,copy(h.quoteOverride));
        if(h.quoteDelay) await new Promise(resolve=>setTimeout(resolve,h.quoteDelay));
        try {return await send(value);} catch {return;}
      }
      if(part==='actions') {
        h.actions.push({id,...copy(body)});
        if(h.actionDelay) await new Promise(resolve=>setTimeout(resolve,h.actionDelay));
        if(h.failNextAction) {h.failNextAction=false;return fail('TEMPORARY_ERROR','演示传输失败，请重试',503);}
        const key = `${id}:${body.request_key}`;
        const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
          ? Object.fromEntries(Object.keys(value).sort().map(name => [name, stable(value[name])])) : value;
        const digest = JSON.stringify(stable(body));
        if(h.receipts[key]) {
          if(h.receipts[key].digest !== digest) return fail('IDEMPOTENCY_KEY_CONFLICT','请求键属于另一项操作。');
          return send(h.receipts[key].run, 202);
        }
        if(body.action==='approve_plan') {run.status='executing';run.action_pending=true;}
        else if(body.action==='approve_gate') {run.nodes.find(n=>n.node_id===body.gate_node_id).gate_approved=true;run.status='executing';run.action_pending=true;}
        else if(body.action==='revise_plan') {run.status='understanding';run.action_pending=true;}
        else if(body.action==='answer') {run.status='understanding';run.pending_card=null;run.action_pending=true;}
        else if(body.action==='approve_patch') {run.plan.plan_version++;run.status='executing';run.action_pending=true;run.patches.find(p=>p.patch_id===body.patch_id).status='applied';}
        else if(body.action==='reject_patch') {run.status='attention';run.patches.find(p=>p.patch_id===body.patch_id).status='rejected';}
        else if(body.action==='approve_results') run.status='success';
        else if(body.action==='reject') {run.status='cancelled';run.action_pending=false;}
        else if(body.action==='resume') {run.status='understanding';run.resume_count++;run.action_pending=true;}
        run.updated_at=new Date().toISOString();
        h.receipts[key]={digest,run:copy(run)};
        await send(run, 202);
        h.actionResponses.push({id,action:body.action,request_key:body.request_key,at:Date.now()});
        return;
      }
    }
    const asset=path.match(/^\/api\/artifacts\/([^/]+)\/(preview|download)$/);
    if(asset && fixture.inline_artifacts[asset[1]]) {
      const item=fixture.inline_artifacts[asset[1]];
      h.assetRequests.push({id:asset[1],authorization:req.headers().authorization});
      if(h.assetDelay) await new Promise(resolve=>setTimeout(resolve,h.assetDelay));
      return route.fulfill({status:200,contentType:item.mime_type,body:Buffer.from(item.base64,'base64')});
    }
    h.blocked.push(`${req.method()} ${path}`);
    return route.abort();
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_review`);
  await page.getByTestId('v3-run-panel').waitFor();

  // Approved UI scenario sequence; closure state survives all steps in this call.
  {
  check(await page.getByTestId('v3-plan-board').count()===1,'generic plan missing');
  await page.getByTestId('v3-collaboration').getByRole('button',{name:'下一页'}).click();
  await page.getByText('第 2 页 / 2 · 37 条',{exact:false}).waitFor();
  reports.push('steps page 2 / 37 records');
  await page.getByTestId('v3-collaboration').getByRole('button',{name:'上一页'}).click();
  await page.getByText('第 1 页 / 2 · 37 条',{exact:false}).waitFor();
  const repair=page.getByLabel('自动局部修复预授权（可选，credits）');
  await repair.fill('100');
  check(await page.getByRole('button',{name:'批准版本 2 并执行'}).isDisabled(),'over budget allowed');
  await repair.fill('3');
  check(await page.getByRole('button',{name:'批准版本 2 并执行'}).isEnabled(),'valid approval unavailable');
  h.failNextAction=true;
  await page.getByRole('button',{name:'批准版本 2 并执行'}).click();
  await page.getByText('演示传输失败，请重试',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:'批准版本 2 并执行'}).click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  const attempts=h.actions.filter(a=>a.action==='approve_plan');
  check(attempts.length===2 && attempts[0].request_key===attempts[1].request_key,'network retry changed key');
  check(attempts[1].plan_version===2 && attempts[1].repair_budget_credits===3,'incorrect plan payload');
  reports.push('budget cap / exact plan version / stable network retry key');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_input`);
  await page.getByRole('radio',{name:/白色手绘/}).click();
  await page.getByRole('button',{name:'提交选择',exact:true}).click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  const answer=h.actions.findLast(a=>a.action==='answer');
  check(answer?.card_id==='demo_card_1' && answer.answers.some(a=>a.question_id==='boat_style'&&a.option_id==='white'),'clarification did not use selected option');
  reports.push('multimodal clarification / producer label');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_gate`);
  const gate=page.getByTestId('v3-plan-board').getByRole('button',{name:'确认此预览'}).first();
  await gate.click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  const gateAction=h.actions.findLast(a=>a.action==='approve_gate');
  check(gateAction?.plan_version===2 && gateAction.gate_node_id,'gate approval lacks node/version');
  reports.push('preview gate exact node/version');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_recovery`);
  await page.getByRole('button',{name:'恢复检查',exact:true}).click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  check(h.actions.findLast(a=>a.action==='resume')?.id==='demo_v3_recovery','attention old-inbox recovery blocked');
  reports.push('attention with pending action can explicitly resume');
  }
  {
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_patch`);
  const panel=page.getByTestId('v3-patch-review');
  await panel.waitFor();
  check(await panel.getByRole('button',{name:'确认范围与费用，批准修改'}).count()===0,'historical quote actionable without fetching');
  await panel.getByRole('button',{name:'获取当前范围报价'}).click();
  const approve=panel.getByRole('button',{name:'确认范围与费用，批准修改'});
  await approve.waitFor();
  check(await approve.isDisabled(),'retained risk was implicitly accepted');
  await panel.getByRole('checkbox').check();
  check(await approve.isEnabled(),'retained risk acknowledgement not accepted');
  reports.push('fresh quote required / explicit downstream retention acknowledgement');
  await panel.getByRole('radio',{name:/重做受影响后续/}).check();
  check(await approve.count()===0,'only quote survived scope switch');
  h.quoteDelay=350;
  await panel.getByRole('button',{name:'获取当前范围报价'}).click();
  await panel.getByRole('radio',{name:/只重做目标/}).check();
  await page.waitForTimeout(450);
  check(await approve.count()===0,'late cascade quote replaced current only state');
  h.quoteDelay=0;
  h.failNextQuote=true;
  await panel.getByRole('button',{name:'获取当前范围报价'}).click();
  await panel.getByText('演示报价暂不可用',{exact:true}).waitFor();
  check(await approve.count()===0,'quote error preserved approval');
  reports.push('scope switch / delayed stale quote / quote failure');
  await panel.getByRole('radio',{name:/重做受影响后续/}).check();
  await panel.getByRole('button',{name:'获取当前范围报价'}).click();
  await approve.waitFor();
  check(await approve.isEnabled(),'fresh cascade quote rejected against stale only snapshot');
  check(await panel.getByRole('checkbox').count()===0,'cascade unexpectedly needs retained risk acknowledgement');
  await approve.click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  const action=h.actions.findLast(a=>a.action==='approve_patch');
  check(action?.scope==='cascade' && action.quote_id===h.fixture.quotes_by_scope.cascade.data.quote_id,'patch approval quote/scope mismatch');
  reports.push('current cascade exact quote approval');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_results`);
  const result=page.getByRole('region',{name:'创作产物'});
  await result.waitFor();
  const downloadPromise=page.waitForEvent('download');
  await result.locator('figure').filter({hasText:'素材包'}).getByRole('button',{name:'下载产物'}).click();
  const download=await downloadPromise;
  check(download.suggestedFilename()==='sources.zip','package download filename changed');
  await result.getByRole('button',{name:'确认产物',exact:true}).click();
  await page.getByTestId('v3-run-panel').getByRole('status').getByText('已完成',{exact:true}).waitFor();
  reports.push('authenticated local artifact download / result approval');
  }

  // Polling stability, authenticated downloads and responsive theme checks.
  {
  async function pollOnce() {
    const before=h.listCount;
    for(let i=0;i<80 && h.listCount===before;i++) await page.waitForTimeout(100);
    check(h.listCount>before,'polling did not occur');
    await page.waitForTimeout(100);
  }
  h.runs=copy(h.fixture.runs_by_id);
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_review`);
  const board=page.getByTestId('v3-plan-board');
  await board.waitFor();
  await page.getByLabel('自动局部修复预授权（可选，credits）').fill('3');
  await page.getByLabel('修改意图',{exact:true}).fill('保留温室与纸船，让结尾更轻松。');
  await board.locator('details summary').first().click();
  await pollOnce();
  check(await page.getByLabel('自动局部修复预授权（可选，credits）').inputValue()==='3','poll erased repair budget');
  check((await page.getByLabel('修改意图',{exact:true}).inputValue()).includes('结尾更轻松'),'poll erased revision');
  check(await board.locator('details').first().locator('.details-body').count()===1,'poll erased expanded node');
  h.actionDelay=4200;
  await page.getByRole('button',{name:'批准版本 2 并执行'}).click();
  await pollOnce();
  check(await page.getByRole('button',{name:'批准版本 2 并执行'}).isDisabled(),'poll cancelled active action');
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  h.actionDelay=0;
  reports.push('same-version polling preserves edit state and in-flight action');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_patch`);
  const patch=page.getByTestId('v3-patch-review');
  await patch.getByRole('radio',{name:/重做受影响后续/}).check();
  await patch.getByRole('button',{name:'获取当前范围报价'}).click();
  const approve=patch.getByRole('button',{name:'确认范围与费用，批准修改'});
  await approve.waitFor();
  await pollOnce();
  check(await patch.getByRole('radio',{name:/重做受影响后续/}).isChecked(),'poll reset scope');
  check(await approve.isEnabled(),'ordinary poll invalidated stable quote');
  h.runs.demo_v3_patch.plan.plan_version=3;
  await pollOnce();
  check(await approve.count()===0,'version change retained approval');
  reports.push('same-version scope/quote retained; changed version invalidates quote');
  h.runs.demo_v3_patch=copy(h.fixture.runs_by_id.demo_v3_patch);
  h.quoteOverride={manual_can_apply:false};
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_patch`);
  await patch.getByRole('button',{name:'获取当前范围报价'}).click();
  await approve.waitFor();
  await patch.getByRole('checkbox').check();
  check(await approve.isDisabled(),'manual_can_apply false allowed approval');
  await patch.getByRole('button',{name:'拒绝此补丁'}).click();
  await patch.getByText('已拒绝',{exact:true}).waitFor();
  h.quoteOverride=null;
  reports.push('server manual refusal blocks approval but allows rejection');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_gate`);
  await board.getByRole('button',{name:'提出修改'}).first().click();
  await page.getByLabel('修改意图',{exact:true}).fill('纸船保留蓝色，温室光线柔和一些。');
  await pollOnce();
  await page.getByRole('button',{name:'提交修改意图'}).click();
  await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor();
  const revision=h.actions.findLast(a=>a.action==='revise_plan');
  check(revision?.gate_node_id==='s01_first' && revision.plan_version===2,'preview feedback lost node/version');
  reports.push('preview revision survives poll and binds exact gate/version');
  await page.goto(`${baseUrl}/agent-studio?run=demo_v3_results`);
  h.assetDelay=4200;
  const result=page.getByRole('region',{name:'创作产物'});
  const downloadPromise=page.waitForEvent('download');
  await result.locator('figure').filter({hasText:'素材包'}).getByRole('button',{name:'下载产物'}).click();
  await pollOnce();
  check(await result.getByRole('button',{name:'下载中…'}).count()===1,'poll cancelled download');
  const download=await downloadPromise;
  check(download.suggestedFilename()==='sources.zip','download naming failure');
  check(h.assetRequests.some(a=>a.id==='demo_sources_zip'&&a.authorization==='Bearer mock-browser-token'),'download missing authorization');
  h.assetDelay=0;
  reports.push('authenticated download survives same-version polling');
  h.runs=copy(h.fixture.runs_by_id);
  for (const width of [1440,400]) for (const dark of [false,true]) {
    await page.setViewportSize({width,height:900});
    await page.goto(`${baseUrl}/agent-studio?run=demo_v3_patch`);
    await patch.waitFor();
    await page.evaluate(value=>document.documentElement.classList.toggle('dark',value),dark);
    await patch.getByRole('button',{name:'获取当前范围报价'}).click();
    await approve.waitFor();
    const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth,overflow:[...document.querySelectorAll('main *')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.right>innerWidth+1}).slice(0,5).map(el=>({tag:el.tagName,class:el.className}))}));
    check(layout.scroll<=width && layout.body<=width && layout.overflow.length===0,`horizontal overflow ${JSON.stringify(layout)}`);
    layouts.push({dark,...layout});
  }
  check(h.pageErrors.length===0,`browser errors ${h.pageErrors}`);
  check(h.blocked.every(url=>url.startsWith('https://fonts.googleapis.com/')),'unexpected API or external route');
  }

  // A's acknowledgement must not supersede a newer user selection of B.
  {
    h.runs=copy(h.fixture.runs_by_id);
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(`${baseUrl}/agent-studio?run=demo_v3_review`);
    const approve=page.getByRole('button',{name:'批准版本 2 并执行',exact:true});
    await approve.waitFor({timeout:3000});
    h.actionDelay=450;h.detailDelays.demo_v3_input=1000;
    const actionCount=h.actions.length,detailCount=h.detailResponses.length;
    try {
      await approve.click({timeout:2000});
      await waitForCondition(()=>h.actions.length>actionCount,'race A approval did not start',2000);
      const history=page.getByRole('navigation',{name:'创作记录',exact:true});
      await history.getByRole('button').filter({hasText:h.fixture.runs_by_id.demo_v3_input.text}).click({timeout:2000});
      await waitForCondition(()=>h.detailResponses.slice(detailCount).some(item=>item.id==='demo_v3_input'),
        'race B detail did not return',4000);
      const body=h.actions[actionCount];
      const accepted=h.actionResponses.find(item=>item.request_key===body.request_key);
      const selected=h.detailResponses.slice(detailCount).find(item=>item.id==='demo_v3_input');
      check(accepted && selected.startedAt<accepted.at && accepted.at<selected.at,
        'selection race did not exercise B request before A acknowledgement before B response');
      await page.getByRole('radio',{name:/白色手绘/}).waitFor({timeout:2000});
      check(new URL(page.url()).searchParams.get('run')==='demo_v3_input','A response stole B selection');
      check(await page.getByTestId('v3-plan-board').count()===0,'B clarification was replaced by A plan');
      reports.push('pending B selection survives earlier A approval acknowledgement');
    } finally {h.actionDelay=0;h.detailDelays={};}
  }

  // A list requested before approval must not roll history back when it returns late.
  {
    h.runs=copy(h.fixture.runs_by_id);
    const initialResponses=h.listResponseCount;
    await page.goto(`${baseUrl}/agent-studio?run=demo_v3_review`);
    const approve=page.getByRole('button',{name:'批准版本 2 并执行',exact:true});
    await approve.waitFor({timeout:3000});
    await waitForCondition(()=>h.listResponseCount>initialResponses,'initial history did not arrive',3000);
    await approve.scrollIntoViewIfNeeded({timeout:2000});
    const before=h.listCount;
    h.listDelay=800;
    try {
      await waitForCondition(()=>h.listCount>before,'delayed history poll did not start',5000);
      const stale=h.listRecords.find(item=>item.number>before);
      check(stale?.statuses.demo_v3_review==='awaiting_plan_review' && !stale.respondedAt,
        'history race did not capture pre-approval state');
      const actionCount=h.actions.length;
      await approve.click({timeout:2000});
      await page.getByText('操作已提交，等待后台处理。',{exact:true}).waitFor({timeout:2000});
      await waitForCondition(()=>Boolean(stale.respondedAt),'delayed history did not return',2000);
      const accepted=h.actionResponses.find(item=>item.request_key===h.actions[actionCount]?.request_key);
      check(accepted && accepted.at<stale.respondedAt,'old history did not arrive after approval');
      await page.waitForTimeout(100);
      const selected=page.getByRole('navigation',{name:'创作记录',exact:true}).locator('button[aria-current="true"]');
      const text=await selected.textContent({timeout:2000});
      check(text.includes('执行中') && !text.includes('等待计划审核'),'late history rolled approved run status back');
      check(new URL(page.url()).searchParams.get('run')==='demo_v3_review','late history changed selection');
      reports.push('late pre-approval list snapshot cannot roll history status back');
    } finally {h.listDelay=0;}
  }

  // Composer validation must block empty requests without sending any API call.
  {
    await page.goto(`${baseUrl}/agent-studio`);
    const input = page.getByRole('textbox', {name: '想做什么？', exact: true});
    const start = page.getByRole('button', {name: '开始创作', exact: true});
    await input.waitFor();
    check(await start.isDisabled(), 'empty composer enabled submission');
    await input.fill('   ');
    check(await start.isDisabled(), 'whitespace composer enabled submission');
    const blockedBefore = h.blocked.length;
    await input.press('Control+Enter');
    await page.getByText('请先用文字描述需求，Agent 需要知道你想做什么', {exact: true}).waitFor();
    check(h.blocked.length === blockedBefore, 'empty shortcut attempted an API request');
    await input.fill('演示：生成一张温室纸船插画。');
    check(await start.isEnabled(), 'valid text did not enable the composer');
    await input.fill('');
    check(await start.isDisabled(), 'clearing the text left submission enabled');
    reports.push('empty and whitespace text disabled; keyboard shortcut cannot create a task');
  }
  // History compatibility is a read-only rendering check, not a v1/v2 API rewrite.
  {
    for (const version of [1, 2]) {
      await page.goto(`${baseUrl}/agent-studio?run=demo_legacy_v${version}`);
      await page.getByRole('heading', {name: `历史 v${version} 创作记录 · 浏览器演示`, exact: true}).waitFor();
      check(await page.getByTestId('v3-run-panel').count() === 0, `v${version} history entered the v3 panel`);
      check(await page.getByTestId('v3-plan-board').count() === 0, `v${version} history received v3 approval controls`);
      check(await page.getByText('旧版创作记录', {exact: true}).count() === (version === 1 ? 1 : 0), `v${version} legacy label mismatch`);
      await page.getByText('你的需求', {exact: true}).waitFor();
    }
    reports.push('v1 and v2 history retain the legacy panel without v3 approval controls');
  }
  check(h.pageErrors.length === 0, `Unexpected page errors: ${h.pageErrors.join('; ')}`);
  check(h.blocked.every(url => url.startsWith('https://fonts.googleapis.com/')), `Unexpected blocked requests: ${h.blocked.join('; ')}`);
  return {baseUrl, reports, layouts, pageErrors: h.pageErrors,
    actionCount: h.actions.length, quoteCount: h.quotes.length,
    blocked: {unexpected: h.blocked.filter(url => !url.startsWith('https://fonts.googleapis.com/')).length, externalFonts: h.blocked.length}};
}
