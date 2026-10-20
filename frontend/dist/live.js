import {api, mergeEvents, isFinished, sceneEvents, escapeHtml as esc, testsForAgent, normalizeDraft, startPayload, runGuidance, nextActionHint} from './live-api.js?v=0.6.2';
import {purchaseTopology} from './topologies.js?v=0.6.2';
import {mountScene, pauseScene} from './scene.js?v=0.6.2';
import {frameFor} from './topology.js?v=0.6.2';

const graph = {...purchaseTopology, version:'live-topology-v1', nodes:[...purchaseTopology.nodes,
  {id:'guide',label:'조사 지침',role:'store',layer:3,lane:2},
  {id:'fault',label:'사고 주입',role:'tool',layer:1,lane:3}]};
const state = {session:null, catalog:null, runs:[], run:null, events:[], selected:null, comparison:null, settled:false, draft:{agent:"purchase",test_id:"S01",system_id:"B0"}, compareDraft:{left:"",right:""}, pendingStart:false, pendingRunId:null};
let host, timer, playback, generation=0, loading=false, page='agents', go;
const $ = selector => host?.querySelector(selector);
const json = value => esc(JSON.stringify(value, null, 2));
const badge = text => `<span class="badge" data-result="${esc(text)}">${esc(text)}</span>`;
const options = (items, key, title=key) => items.map(x => `<option value="${esc(x[key])}">${esc(x[key])}${x[title] !== x[key] ? ` · ${esc(x[title])}` : ''}</option>`).join('');
const messages = {
  RUN_IN_PROGRESS:'다른 실행 또는 조사가 진행 중입니다. 실행 기록을 열어 확인해 주세요.',
  UNAUTHORIZED:'로그인이 필요하거나 세션이 만료되었습니다. 다시 로그인해 주세요.',
  PERMISSION_DENIED:'이 계정에는 필요한 권한이 없습니다.',
  HARNESS_UNAVAILABLE:'Harness에 연결할 수 없습니다. 서비스 상태를 확인해 주세요.',
  RUN_FINALIZED:'이미 종료된 실행입니다. 새 시험을 시작해 주세요.',
  NOT_COMPARABLE:'동일한 SYSTEM 시나리오의 완료된 실행 두 개를 선택해 주세요.',
  RUN_NOT_COMPLETED:'두 실행이 모두 완료된 뒤 비교해 주세요.'
};
function notify(message, error=false) {
  if (!$('[data-live-message]')) return;
  $('[data-live-message]').textContent=message;
  $('[data-live-message]').classList.toggle('live-error',error);
}
function failure(error) {
  if (error.status === 401) { state.session=null; clearTimeout(timer); if(host)account(); }
  notify(error.details?.decision_saved ? '결정은 저장됐지만 실행 재개 전달에 실패했습니다. 같은 결정을 다시 보내 주세요.' : messages[error.code] || error.message, true);
}
export function leaveLive() { clearTimeout(timer); clearInterval(playback); playback=null; generation++; host=null; loading=false; pauseScene(); }
const pageCopy={
  agents:['평가 대상','실제 서비스에서 제공하는 구매·조사 Agent와 시험 범위를 선택합니다.'],
  prepare:['시험 조건','선택한 Agent의 시나리오와 서버 정책을 설정합니다.'],
  live:['실제 실행','설정한 조건으로 실행하고 담당자 승인·거절을 처리합니다.'],
  execution:['실행 분석','선택한 실제 실행의 3D 흐름·이벤트·검사 근거·조사 보고서를 확인합니다.'],
  compare:['결과 비교','같은 SYSTEM 시나리오의 완료된 실행을 비교합니다.']
};
const agentName=agent=>agent==='investigator'?'사고 조사 Agent':'구매 Agent';
export function mountLive(element, selectedPage='agents', navigate) {
  host=element; page=selectedPage; go=navigate; generation++; loading=false;
  const [title,description]=pageCopy[page];
  host.innerHTML=`<div class="page-heading"><div><span class="eyebrow">CONNECTED WORKSPACE</span><h1>${title}</h1><p>${description}</p></div>${badge('실제 API')}</div>
    <p class="live-message" data-live-message role="status" aria-live="polite"></p>
    <div class="live-layout"><aside class="panel section-pad live-controls">
      <h2>계정</h2><div data-live-account></div>
      <hr><div class="live-row"><h3>실행 기록</h3><button type="button" class="secondary" data-live-refresh>새로고침</button></div>
      <div data-live-history class="live-history"></div>
    </aside><section class="live-content">
      <section class="live-guidance" data-live-guidance aria-label="현재 단계와 다음 행동"></section>
      <section data-live-target class="panel section-pad" ${page==='agents'?'':'hidden'}>
        <h2>실행할 Agent</h2><div data-live-targets class="live-targets"><p>로그인하면 서버의 시험 목록을 불러옵니다.</p></div>
        <div class="live-flow-actions"><button class="primary" data-live-go="prepare" data-live-next disabled>시험 조건 설정 →</button></div>
      </section>
      <section data-live-setup class="panel section-pad" ${['prepare','live'].includes(page)?'':'hidden'}>
        <div class="live-row"><h2>${page==='prepare'?'시험 조건 설정':'선택한 시험 실행'}</h2><button class="secondary" data-live-go="agents">평가 대상 변경</button></div>
        <p data-live-draft-agent></p>
        <form data-live-start><label>시험 시나리오<select name="test_id" required><option>로그인 후 불러옵니다</option></select></label>
          <label>서버 정책<select name="system_id"><option value="B0">B0</option><option value="B1">B1</option></select></label>
          <p class="live-hint" data-live-kind></p><button class="primary" type="submit" disabled>${page==='prepare'?'이 조건으로 실행 준비 →':'시험 시작'}</button></form>
      </section>
      <section data-live-compare-area class="panel section-pad" ${page==='compare'?'':'hidden'}><h2>비교할 실제 실행</h2><p class="live-hint">실행 종료 후 같은 시나리오의 B0 / B1을 선택하세요. 모델·프롬프트 등 다른 조건이 달라졌다면 비교 결과의 변경 조건에 표시됩니다.</p>
        <form data-live-compare class="live-compare-form"><label>왼쪽 실행<select name="left" required></select></label><label>오른쪽 실행<select name="right" required></select></label><button class="primary" type="submit">실제 결과 비교</button></form>
      </section>
      <div data-live-summary class="panel section-pad" ${['live','execution'].includes(page)?'':'hidden'}><h2>실행을 선택해 주세요</h2><p>왼쪽 실행 기록에서 저장된 실행을 열거나 새 시험을 시작하세요.</p><button class="secondary" data-live-go="prepare">시험 조건 설정 →</button></div>
      <div data-live-approval ${page==='live'?'':'hidden'}></div>
      <div data-live-comparison ${page==='compare'?'':'hidden'}></div>
      <section class="panel section-pad" data-live-analysis hidden><div class="live-row"><h2>실행 흐름</h2><div class="live-row"><span data-live-count></span><button class="secondary" data-live-play>재생</button><button class="secondary" data-live-export>근거 JSON 내보내기</button></div></div>
        <div id="live-scene" class="live-scene" aria-label="실제 이벤트 기반 서비스 구조"></div>
        <label>확인할 이벤트<input data-live-cursor type="range" min="0" value="0" aria-label="확인할 이벤트 순서"></label>
        <div class="live-evidence-grid"><div data-live-events class="live-events" aria-label="실행 이벤트"></div><div><h3>선택한 근거</h3><pre data-live-evidence tabindex="0"></pre></div></div></section>
      <section data-live-result hidden></section></section></div>`;
  host.onsubmit=submit;
  host.onclick=click;
  $('[data-live-start] [name=test_id]').onchange=selectTest;
  $('[name=system_id]').onchange=e=>{state.draft.system_id=e.target.value;};
  for(const name of ['left','right'])$(`[name=${name}]`).onchange=e=>{state.compareDraft[name]=e.target.value;state.comparison=null;$('[data-live-comparison]').innerHTML='';actionHint();};
  $('[data-live-cursor]').oninput=e=>{stopReplay();state.selected=Number(e.target.value);renderEvents();};
  account(); history(); guidance();
  if(state.catalog)catalog();
  if(state.run)renderRun(true);
  if(state.comparison)$('[data-live-comparison]').innerHTML=comparisonView(state.comparison);
  if(state.session)refresh().then(()=>{if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;return openRun(id);}if(state.run)return poll();}).catch(failure);
}
function guidance() {
  const area=$('[data-live-guidance]');if(!area)return;
  let info;
  if(!state.session) info={title:'먼저 개발 계정으로 로그인해 주세요',detail:'로그인하면 시험 목록과 저장된 실행 기록을 불러옵니다.'};
  else if(state.pendingStart) info={title:'실행 요청을 보내고 있습니다',detail:'중복 실행을 막기 위해 시작 버튼을 잠시 잠갔습니다. 접수되면 실행 번호와 진행 상태를 표시합니다.'};
  else if(state.run && !state.settled && ['agents','prepare'].includes(page)) info={title:'이미 실행 중인 시험이 있습니다',detail:`${state.run.run_id}의 진행 상태를 먼저 확인해 주세요. 실행이 끝난 뒤 새 시험을 시작할 수 있습니다.`,action:'현재 실행으로 돌아가기 →',page:'live'};
  else if(state.run && ['live','execution'].includes(page)) info=runGuidance(state.run,state.settled);
  else info={
    agents:{title:`${agentName(state.draft.agent)}가 선택돼 있습니다`,detail:'평가할 Agent를 확인했으면 시험 조건으로 이동해 시나리오를 선택해 주세요.',action:'시험 조건 설정 →',page:'prepare'},
    prepare:{title:'시험 조건을 정해 주세요',detail:'시나리오와 서버 정책을 선택하고 실행 준비로 이동하세요. 이 단계에서는 아직 실행하지 않습니다.'},
    live:{title:'실행 준비가 됐습니다 · 아직 시작하지 않았습니다',detail:`${agentName(state.draft.agent)} · ${state.draft.test_id} 조건을 확인한 뒤 아래 시험 시작을 눌러 주세요.`},
    execution:{title:'확인할 실행을 선택해 주세요',detail:'왼쪽 실행 기록을 선택하면 진행 기록과 검사 결과를 볼 수 있습니다.',action:'새 시험 준비 →',page:'prepare'},
    compare:{title:'같은 시나리오의 B0·B1 실행을 선택해 주세요',detail:'완료된 실행 두 개를 고른 뒤 실제 결과 비교를 누르세요. Agent 단독 시험은 비교 대상에 포함되지 않습니다.'}
  }[page];
  const key=JSON.stringify([page,info]);if(area.dataset.key===key){actionHint();return;}area.dataset.key=key;
  const steps=['agents','prepare','live','execution'];
  area.innerHTML=`<ol class="live-steps" aria-label="시험 진행 단계">${steps.map((step,i)=>`<li><button type="button" data-live-go="${step}" ${step===page?'aria-current="step"':''}>${i+1}. ${pageCopy[step][0]}</button></li>`).join('')}</ol><div class="live-guidance-copy" role="status" aria-live="polite" aria-atomic="true"><strong>${esc(info.title)}</strong><p>${esc(info.detail)}</p></div>${info.action && info.page!==page?`<button class="primary" data-live-go="${info.page}">${esc(info.action)}</button>`:''}${page==='live' && state.run?.status==='WAITING_APPROVAL'?'<button class="primary" data-live-show-approval>승인 요청 확인 ↓</button>':''}${page==='execution' && state.settled?'<button class="primary" data-live-show-results>검사 결과·보고서로 이동 ↓</button>':''}`;
  actionHint();
}
function actionHint() {
  const hint=nextActionHint({page,...state});
  const target=hint && $(hint.selector);
  const previous=$('[data-action-hint-anchor]');
  if(previous && target===previous.lastElementChild && previous.firstElementChild.textContent===hint?.text)return;
  if(previous){const control=previous.lastElementChild;control.removeAttribute('aria-describedby');previous.replaceWith(control);}
  if(!target || target.disabled || target.closest('[hidden]'))return;
  const anchor=document.createElement('div');anchor.className='live-action-anchor';anchor.dataset.actionHintAnchor='';
  const bubble=document.createElement('p');bubble.className='live-action-bubble';bubble.id='live-next-action-hint';bubble.textContent=hint.text;
  target.before(anchor);anchor.append(bubble,target);target.setAttribute('aria-describedby',bubble.id);
}
function targets() {
  $('[data-live-draft-agent]').textContent=`평가 대상: ${agentName(state.draft.agent)}`;
  $('[data-live-targets]').innerHTML=['purchase','investigator'].map(agent=>{
    const tests=testsForAgent(state.catalog,agent);
    return `<button class="live-target ${state.draft.agent===agent?'selected':''}" data-live-agent="${agent}" aria-pressed="${state.draft.agent===agent}"><strong>${agentName(agent)}</strong><p>${agent==='purchase'?'재고·공급업체 조회 → 승인 → 발주 → 완료 보고':'실패 검사·실행 기록·업무 상태·지침 조회 → 근거 기반 보고서'}</p><span>${tests.length}개 서버 제공 시험</span><small>${tests.map(t=>esc(t.test_id)).join(' · ')}</small></button>`;
  }).join('');
  $('[data-live-next]').disabled=!state.session || !testsForAgent(state.catalog,state.draft.agent).length;guidance();
}

function account() {
  $('[data-live-account]').innerHTML=state.session ? `<p>${esc(state.session.user_id)} ${badge(state.session.roles.join(' / '))}</p><button type="button" class="secondary" data-live-logout>로그아웃</button>` :
    `<form data-live-login><label>계정<input name="user_id" value="requester-01" autocomplete="username" required></label><label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label><button class="secondary full" type="submit">로그인</button><p class="live-hint">개발 계정의 비밀번호는 서버의 DEMO_USER_PASSWORD 설정을 사용합니다.</p></form>`;
  const button=$('[data-live-start] button');
  button.textContent=page==='prepare'?'이 조건으로 실행 준비 →':state.pendingStart?'실행 요청 중…':state.run && !state.settled?'실행 진행 중':'시험 시작';
  button.disabled=!state.session?.roles.includes('REQUESTER') || !state.catalog || state.pendingStart || !!(state.run && !state.settled);
  $('[data-live-setup]').hidden=!['prepare','live'].includes(page) || (page==='live' && !!state.run);
  $('[data-live-summary]').hidden=!['live','execution'].includes(page) || (page==='live' && !state.run);
  guidance();
}
function catalog() {
  state.draft=normalizeDraft(state.catalog,state.draft);
  $('[name=test_id]').innerHTML=options(testsForAgent(state.catalog,state.draft.agent),'test_id','title');
  $('[name=test_id]').value=state.draft.test_id;
  $('[name=system_id]').innerHTML=options(state.catalog.systems,'system_id','server_policy_version');
  $('[name=system_id]').value=state.draft.system_id;
  selectTest(); targets(); account();
}
function selectTest() {
  state.draft.test_id=$('[name=test_id]').value;
  const test=state.catalog?.tests.find(t=>t.test_id===$('[name=test_id]').value);
  $('[name=system_id]').disabled=test?.test_kind!=='SYSTEM';
  $('[data-live-kind]').textContent=test ? `${test.test_kind==='SYSTEM'?'실제 서비스 통합 시험 · 실행 중 담당자 승인이 필요합니다.':test.test_kind==='INVESTIGATION_AGENT'?'조사 Agent 단독 시험 · 별도 승인 없이 보고서를 생성합니다.':'구매 Agent 단독 시험 · 준비된 시험 조건으로 자동 진행합니다.'} 모델은 서버 설정을 따릅니다.` : '';guidance();
}
async function refresh() {
  const current=generation;
  const [catalogData,historyData]=await Promise.all([api('/scenarios',{token:state.session.access_token}),api('/runs',{token:state.session.access_token})]);
  if(current!==generation || !host)return;
  state.catalog=catalogData;state.runs=historyData.runs;
  catalog(); history(); account();
}
function history() {
  $('[data-live-history]').innerHTML=state.runs.length ? state.runs.map(run=>`<button class="secondary full" data-live-run="${esc(run.run_id)}"><strong>${esc(run.run_id)}</strong> · ${esc(run.test_id)} ${esc(run.system_id || '')}<small>${esc(run.status)}</small></button>`).join('') : '<p class="live-hint">로그인하면 저장된 기록을 불러옵니다.</p>';
  const completed=state.runs.filter(run=>run.test_id?.startsWith('S') && run.status==='COMPLETED');
  for(const name of ['left','right']) {
    const select=$(`[name=${name}]`), previous=state.compareDraft[name];
    select.innerHTML=options(completed.map(r=>({...r,title:`${r.test_id} ${r.system_id}`})),'run_id','title');
    if(completed.some(r=>r.run_id===previous))select.value=previous;
    else if(name==='right' && completed.length>1)select.selectedIndex=1;
    state.compareDraft[name]=select.value;
  }
}
async function openRun(id) {
  clearTimeout(timer);generation++;loading=false;
  state.events=[];state.selected=null;state.run=null;state.settled=false;
  $('[data-live-approval]').innerHTML='';$('[data-live-summary]').textContent='실행을 불러오는 중입니다…';$('[data-live-analysis]').hidden=true;$('[data-live-result]').innerHTML='';
  const current=generation;
  const run=await api(`/runs/${encodeURIComponent(id)}`,{token:state.session.access_token});
  if(current!==generation || !host)return;
  state.run=run;renderRun(true);await poll();
}
async function poll() {
  if(!host || !state.run || !state.session || loading)return;
  clearTimeout(timer); loading=true; const current=generation, id=state.run.run_id;
  try {
    const run=await api(`/runs/${encodeURIComponent(id)}`,{token:state.session.access_token});
    let events=state.events, page;
    do {
      page=await api(`/runs/${encodeURIComponent(id)}/events?after_sequence=${events.at(-1)?.sequence || 0}&limit=200`,{token:state.session.access_token});
      const next=mergeEvents(events,page.events,id);
      if(page.has_more && next.length===events.length)throw new Error('이벤트 조회가 진행되지 않습니다.');
      events=next;
    } while(page.has_more && current===generation);
    if(current!==generation || !host)return;
    state.run=run;state.events=events;state.settled=isFinished(run) && page.is_final;renderRun();account();
    if(isFinished(run) && page.is_final)await refresh();
    else timer=setTimeout(poll,1000);
  } catch(error) {
    if(current!==generation || !host)return;
    failure(error);
    // Reads can reconnect; a failed start or approval is never sent automatically.
    if(state.session)timer=setTimeout(poll,3000);
  } finally {if(current===generation)loading=false;}
}
function renderRun(force=false) {
  $('[data-live-summary]').hidden=!['live','execution'].includes(page);guidance();
  const run=state.run, summary=run.summary || {}, model=run.manifest?.model || run.investigation?.model_metadata?.model;
  $('[data-live-summary]').innerHTML=`<div class="live-row"><h2>${esc(run.run_id)} · ${esc(run.test_id)} ${esc(run.system_id || '')}</h2>${badge(run.status)}</div>
    <p>${esc(run.status_reason || '')}</p><div class="live-metrics">${['PASS','FAIL','INCONCLUSIVE'].map(k=>`<div><span>${k}</span><strong>${esc(summary[k] ?? 0)}</strong></div>`).join('')}<div><span>실제 주문</span><strong>${run.observed_order_count == null ? '—' : esc(run.observed_order_count)}</strong></div></div>
    ${state.settled?'<p class="live-hint">실행 종료와 검사 통과는 별개입니다. 아래 검사 결과와 근거를 확인해 주세요.</p>':'<p class="live-hint">진행 상태를 자동으로 확인하고 있습니다. 검사 결과와 주문 수는 수집이 끝나면 표시됩니다.</p>'}<p class="mono">모델: ${esc(model && typeof model==='object' ? JSON.stringify(model) : model || run.investigation?.model_metadata?.model_kind || run.manifest?.model_kind || '미지정')} · 조사: ${esc(run.investigation?.status || '—')}</p><div class="live-flow-actions">${run.status==='WAITING_APPROVAL' && page!=='live'?'<button class="primary" data-live-go="live">승인·거절 처리 →</button>':''}${state.settled?'<button class="secondary" data-live-go="prepare">새 시험 준비 →</button>':''}${page!=='execution'?'<button class="secondary" data-live-go="execution">이 실행 분석 →</button>':run.system_id && state.settled?'<button class="secondary" data-live-go="compare">실제 결과 비교 →</button>':''}</div>`;
  const approvalKey=JSON.stringify([run.run_id,run.status,run.approval_request,run.approval]);
  const area=$('[data-live-approval]');
  if(force || area.dataset.key!==approvalKey) {
    area.dataset.key=approvalKey;
    area.innerHTML=run.status==='WAITING_APPROVAL' && run.approval_request ? `<section class="panel section-pad live-approval"><h2>담당자 결정이 필요합니다</h2><p>요청 내용을 확인하고 승인자 계정으로 결정해 주세요. 승인하면 발주를 진행하고, 거절하면 발주 없이 종료합니다.</p><p>만료 시각: ${esc(run.approval_request.expires_at || '—')}</p><details><summary>승인 대상 요청</summary><pre>${json(run.request)}</pre></details>
      <form data-live-approval-form><label>승인자 계정<input name="user_id" value="approver-01" autocomplete="username" required></label><label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label><div class="live-row"><button class="primary" name="decision" value="APPROVED">승인</button><button class="secondary" name="decision" value="REJECTED">거절</button></div></form></section>` : '';
  }
  $('[data-live-analysis]').hidden=page!=='execution';$('[data-live-result]').hidden=page!=='execution';renderEvents();
  $('[data-live-result]').innerHTML=`<section class="panel section-pad"><h2>검사 결과</h2>${run.checks?.length ? `<div class="live-table-wrap"><table class="live-table"><thead><tr><th>규칙</th><th>대상</th><th>판정</th><th>근거</th></tr></thead><tbody>${run.checks.map(c=>`<tr><td>${esc(c.rule_id)}</td><td>${esc(c.scope)}</td><td>${badge(c.verdict)}</td><td>${esc(c.reason || c.message || '')}<details><summary>검사 근거</summary><pre>${json(c)}</pre></details></td></tr>`).join('')}</tbody></table></div>` : '<p>아직 판정이 없습니다.</p>'}
    <h2>조사 보고서</h2><p>${esc(run.investigation?.status || '—')}</p>${run.investigation?.report ? reportView(run.investigation.report) : `<p class="live-hint">${run.investigation?.status==='NOT_REQUESTED'?'이번 실행은 별도 조사 보고서를 생성하지 않습니다. 위 검사 결과와 실행 근거를 확인해 주세요.':run.investigation?.status==='ERROR'?'보고서 생성에 실패했습니다. 실행 기록에서 오류를 확인해 주세요.':'조사 보고서를 작성 중입니다. 완료되면 여기에 표시합니다.'}</p>`}
    <details><summary>Agent 결과·실행 조건</summary><pre>${json({agent:run.agent,manifest:run.manifest,investigation_validation:run.investigation?.validation,investigation_model:run.investigation?.model_metadata})}</pre></details></section>`;
  actionHint();
}
function reportView(report) {
  if(!report)return '<p class="live-hint">보고서가 도착하면 표시합니다.</p>';
  const list=items=>`<ul>${(items || []).map(text=>`<li>${esc(text)}</li>`).join('')}</ul>`;
  return `<h3>확인한 사실</h3><ul>${(report.facts || []).map(f=>`<li>${esc(f.text)}<small>${esc(f.evidence_ids?.join(', '))}</small></li>`).join('')}</ul><h3>원인 후보</h3>${list(report.cause_candidates)}<h3>부족한 증거</h3>${list(report.missing_evidence)}<h3>개선 제안</h3><ul>${(report.improvements || []).map(i=>`<li>${esc(i.text)}<small>${esc(i.sources?.map(s=>`${s.document_id}/${s.version} · ${s.location}`).join(', '))}</small></li>`).join('')}</ul><p>재시험: ${esc(report.retest_scenario_ids?.join(', '))}</p>`;
}
function renderEvents() {
  const events=state.events, selected=state.selected===null ? events.length-1 : Math.min(state.selected,events.length-1);
  $('[data-live-count]').textContent=`${events.length}개 저장 이벤트 · ${state.settled?'조회 완료':'1초마다 조회'}`;
  const cursor=$('[data-live-cursor]');cursor.max=Math.max(0,events.length-1);cursor.value=Math.max(0,selected);cursor.disabled=!events.length;
  const list=$('[data-live-events]'), scroll=list.scrollTop;
  list.innerHTML=events.map((e,i)=>`<button class="live-event ${i===selected?'selected':''}" data-live-event="${i}"><span class="mono">${e.sequence}</span><span>${esc(e.event_type)}<small>${esc(e.node_id)} · ${esc(e.occurred_at)}</small></span></button>`).join('');
  list.scrollTop=scroll;
  $('[data-live-evidence]').textContent=events[selected] ? JSON.stringify(events[selected],null,2) : '아직 이벤트가 없습니다.';
  if(page!=='execution'){pauseScene();return;}
  try { mountScene($('#live-scene'),graph,frameFor(graph,sceneEvents(events),selected),node=>{const i=sceneEvents(state.events).findLastIndex(e=>e.node_id===node);if(i>=0){state.selected=i;renderEvents();}}); }
  catch { $('#live-scene').textContent='이 브라우저에서는 3D를 표시할 수 없습니다. 아래 이벤트와 근거를 확인하세요.'; }
}
function comparisonView(data) {
  return `<section class="panel section-pad"><div class="live-row"><h2>실제 실행 비교</h2><button class="secondary" data-live-close-comparison>닫기</button></div><p>${esc(data.left.run_id)} (${esc(data.left.system_id)}) ↔ ${esc(data.right.run_id)} (${esc(data.right.system_id)})</p><p>주문 수: <strong>${esc(data.actual.left.order_count)} → ${esc(data.actual.right.order_count)}</strong></p><div class="live-table-wrap"><table class="live-table"><thead><tr><th>규칙</th><th>대상</th><th>왼쪽</th><th>오른쪽</th></tr></thead><tbody>${data.checks.map(c=>`<tr><td>${esc(c.rule_id)}</td><td>${esc(c.scope)}</td><td>${esc(c.left)}</td><td>${esc(c.right)}</td></tr>`).join('')}</tbody></table></div><details><summary>고정 조건과 변경 조건</summary><pre>${json({fixed_conditions:data.fixed_conditions,changed:data.changed})}</pre></details></section>`;
}
async function submit(event) {
  event.preventDefault();notify('');const form=event.target, values=Object.fromEntries(new FormData(form)),button=event.submitter;
  const current=generation; const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try {
    if(form.matches('[data-live-login]')) {
      const session=await api('/auth/login',{body:values});if(current!==generation || !host)return;state.session=session;form.reset();await refresh();account();notify('로그인했습니다. 평가 대상을 선택한 뒤 시험 조건으로 이동해 주세요.');
      if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;await openRun(id);}else if(state.run)poll();
    } else if(form.matches('[data-live-start]')) {
      if(page==='prepare'){if(!state.run || state.settled){state.run=null;state.events=[];state.selected=null;state.settled=false;}go('live');return;}
      if(state.pendingStart)return;
      const body=startPayload(state.catalog,state.draft);
      state.pendingStart=true;account();guidance();
      try {
        const result=await api('/runs',{token:state.session.access_token,body});
        if(!host || !state.session){state.pendingRunId=result.run_id;return;}
        notify(`${result.run_id} 실행이 접수됐습니다. 아래에서 진행 상태를 확인하세요.`);await openRun(result.run_id);
        if(['live','execution'].includes(page))$('[data-live-guidance]')?.scrollIntoView({block:'start'});
      } finally {state.pendingStart=false;if(host){account();guidance();}}
    } else if(form.matches('[data-live-approval-form]')) {
      const run=state.run, decision=button.value;
      const approver=await api('/auth/login',{body:values});form.password.value='';
      await api(`/runs/${encodeURIComponent(run.run_id)}/approval`,{token:approver.access_token,body:{approval_request_id:run.approval_request.approval_request_id,payload_hash:run.approval_request.payload_hash,decision}});
      notify(decision==='APPROVED'?'승인했습니다. 실행 결과를 기다려 주세요.':'거절했습니다. 실행 결과를 기다려 주세요.');
      await poll();
    } else if(form.matches('[data-live-compare]')) {
      state.comparison=null;$('[data-live-comparison]').innerHTML='';
      const result=await api(`/comparisons?${new URLSearchParams(values)}`,{token:state.session?.access_token});
      if(current===generation && host){state.comparison=result;state.compareDraft=values;$('[data-live-comparison]').innerHTML=comparisonView(result);actionHint();}
    }
  } catch(error) { if(host)failure(error); }
  finally {buttons.forEach(b=>b.disabled=false);if(host)account();}
}
function click(event) {
  const target=event.target.closest('button');if(!target)return;
  if(target.hasAttribute('data-live-logout')) {state.session=null;state.catalog=null;state.run=null;state.events=[];state.runs=[];state.comparison=null;state.compareDraft={left:'',right:''};state.pendingRunId=null;const element=host;leaveLive();mountLive(element,page,go);notify('로그아웃했습니다.');}
  if(target.hasAttribute('data-live-run')){stopReplay();if(!['live','execution'].includes(page))go('execution');openRun(target.dataset.liveRun).catch(failure);}
  if(target.hasAttribute('data-live-refresh')) {if(state.session)refresh().catch(failure);else notify('먼저 로그인해 주세요.',true);}
  if(target.hasAttribute('data-live-event')) {stopReplay();state.selected=Number(target.dataset.liveEvent);renderEvents();}
  if(target.hasAttribute('data-live-show-approval')){$('[data-live-approval]').scrollIntoView({block:'start'});$('[data-live-approval-form] input')?.focus({preventScroll:true});}
  if(target.hasAttribute('data-live-show-results')){$('[data-live-result]').tabIndex=-1;$('[data-live-result]').focus({preventScroll:true});$('[data-live-result]').scrollIntoView({block:'start'});}
  if(target.hasAttribute('data-live-go'))go(target.dataset.liveGo);
  if(target.hasAttribute('data-live-agent')){state.draft=normalizeDraft(state.catalog,{...state.draft,agent:target.dataset.liveAgent,test_id:''});catalog();}
  if(target.hasAttribute('data-live-play'))toggleReplay();
  if(target.hasAttribute('data-live-export'))exportRun();
  if(target.hasAttribute('data-live-close-comparison')){state.comparison=null;$('[data-live-comparison]').innerHTML='';actionHint();}
}

function stopReplay(){clearInterval(playback);playback=null;if(host)$('[data-live-play]').textContent='재생';}
function toggleReplay(){
  if(playback){stopReplay();return;}
  if(!state.events.length)return;
  state.selected=state.selected===null || state.selected>=state.events.length-1 ? 0 : state.selected;
  $('[data-live-play]').textContent='정지';renderEvents();
  playback=setInterval(()=>{
    if(!host || page!=='execution' || state.selected>=state.events.length-1){stopReplay();return;}
    state.selected++;renderEvents();
  },1000);
}
function exportRun(){
  if(!state.run)return;
  const data={source:'harness_api',run:state.run,events:state.events,sequence_scope:'HARNESS_GLOBAL'};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=`${state.run.run_id}-evidence.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
