async (page) => {
  // Run with browser_run_code_unsafe filename. Entire API is in-memory; no providers.
  const base = 'http://localhost:4173', errors = [], unexpected = [], actions = [], layouts = [];
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const asset = id => ({artifact_id:id,mime_type:'image/png',preview_url:`/api/artifacts/${id}/preview`});
  const run = {run_id:'v9_choice_mock',schema_version:3,text:'三张候选中选一张做动画（Mock）',status:'awaiting_gate',
    created_at:'2026-10-19T10:00:00Z',updated_at:'2026-10-19T10:00:00Z',budget_limit:100,estimated_spent:3,
    planning_budget:{limit:20,spent:1},repair_budget:{limit:0,committed:0,remaining:0},resume_count:0,
    attachments:[],agents:[],steps:[],patches:[],results:[],plan_issues:[],action_pending:false,mock:true,
    plan:{plan_version:1,title:'选择候选图',goal:'确认后仅把所选图片交给下游',stages:[],nodes:[
      {id:'choice',tool:'select_image',gate:'choice',inputs:{candidate_artifact_ids:['a','b','c']},params:{}},
      {id:'clip',tool:'animate_shot',inputs:{first_frame_artifact_id:{ref:'choice.image'},prompt:'跳舞'},params:{duration:5},model_id:'demo-video'}]},
    nodes:[{node_id:'choice',tool:'select_image',gate:'choice',gate_approved:false,status:'pending',depends_on:[],artifacts:[],
      choice:{ready:true,choice_digest:'a'.repeat(64),candidates:['a','b','c'].map(asset),selected_artifact_id:null}},
      {node_id:'clip',tool:'animate_shot',status:'pending',depends_on:['choice'],artifacts:[]}],
    estimates:{total_credits:8,video_seconds:5,generated_video_seconds:5,nodes:[{node_id:'choice',estimated_cost:0},{node_id:'clip',estimated_cost:5,output_video_seconds:5}]},
    summary:{steps_total:2,steps_success:0,steps_failed:0}};
  let fail = false;
  await page.goto('about:blank'); await page.unroute('**/*');
  const onError = e => errors.push(e.message);
  page.on('pageerror', onError);
  await page.addInitScript(() => {
    if (location.protocol !== 'http:') return;
    localStorage.setItem('auth',JSON.stringify({accessToken:'mock',user:{id:1,username:'Mock'}}));
    localStorage.setItem('settings',JSON.stringify({language:'zh',darkMode:false}));
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (url.origin !== base) return route.abort();
    if (!path.startsWith('/api/')) return route.continue();
    const send = data => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({success:true,data})});
    if (path === '/api/health') return send({status:'ok',mode:'mock',agent_mode:true});
    if (path === '/api/models') return send({models:[]});
    if (path === '/api/auth/me') return send({id:1,username:'Mock'});
    if (path === '/api/agent/runs') return send({items:[run]});
    if (path === '/api/agent/runs/v9_choice_mock') return send(run);
    if (path.endsWith('/steps')) return send({items:[],page:1,per_page:30,total:0});
    if (/^\/api\/artifacts\/[abc]\/preview$/.test(path)) return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII=','base64')});
    if (path.endsWith('/actions')) {
      actions.push(request.postDataJSON());
      if (fail) { fail=false; return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({success:false,error:{code:'MOCK_RETRY',message:'模拟网络错误'}})}); }
      return send({...run,action_pending:true});
    }
    unexpected.push(path); return route.abort();
  });
  await page.goto(`${base}/agent-studio?run=v9_choice_mock`);
  await page.getByTestId('v3-plan-board').waitFor();
  const confirm = page.getByRole('button',{name:'确认所选图片',exact:true});
  assert(await confirm.isDisabled(),'no automatic first-candidate selection');
  assert(await page.getByRole('radio').count() === 3,'three candidates shown');
  await page.getByRole('radio',{name:'候选 2',exact:true}).check();
  // A list poll at the same revision must preserve the user's edit.
  await page.waitForResponse(r => r.url().endsWith('/api/agent/runs'),{timeout:9000});
  assert(await page.getByRole('radio',{name:'候选 2',exact:true}).isChecked(),'equivalent poll keeps selection');
  run.nodes[0].choice.choice_digest = 'b'.repeat(64);
  await page.waitForResponse(r => r.url().endsWith('/api/agent/runs'),{timeout:9000});
  await page.waitForTimeout(100);
  assert(await confirm.isDisabled(),'new digest clears selection');
  await page.getByRole('radio',{name:'候选 3',exact:true}).check();
  for (const width of [1440,400]) for (const dark of [false,true]) {
    await page.setViewportSize({width,height:950});
    await page.evaluate(value => document.documentElement.classList.toggle('dark',value),dark);
    const overflow = await page.evaluate(() => Math.max(document.body.scrollWidth,document.documentElement.scrollWidth) > window.innerWidth);
    assert(!overflow,`no overflow ${width}/${dark}`); layouts.push({width,dark,overflow});
  }
  fail=true; await confirm.click();
  await page.getByRole('alert').filter({hasText:'模拟网络错误'}).waitFor();
  const first = actions[0];
  assert(first.selected_artifact_id==='c' && first.choice_digest===run.nodes[0].choice.choice_digest && first.plan_version===1,'bound selected payload');
  await confirm.click();
  await page.waitForTimeout(150);
  assert(actions.length===2 && actions[1].request_key===first.request_key,'retry uses original key');
  assert(!unexpected.length && !errors.length,'no unexpected API or page errors');
  page.off('pageerror', onError);
  await page.goto('about:blank');
  return {passed:true,checks:8,layouts,actions,unexpected,errors};
}
