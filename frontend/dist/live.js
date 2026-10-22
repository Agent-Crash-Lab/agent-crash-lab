import {api, mergeEvents, isFinished, sceneEvents, escapeHtml as esc, testsForAgent, normalizeDraft, startPayload, runGuidance, nextActionHint, preparedPurchaseSample, completedSystemRuns, qaReportMarkup, qaReportDocument, qaReportCollectionDocument, reviewMarkup, repairMarkup, followupMarkup} from './live-api.js?v=0.14.0';
import {registrationMarkup,parseTools,exampleDeclaration,fillDeclaration,renderToolBindings,collectDeclaration,profileAnalysis,capabilityLabel,registeredCaseReady} from './qa-targets.js?v=0.14.0';
import {purchaseTopology} from './topologies.js?v=0.14.0';
import {mountScene, pauseScene} from './scene.js?v=0.14.0';
import {frameFor} from './topology.js?v=0.14.0';

const graph = {...purchaseTopology, version:'live-topology-v1', nodes:[...purchaseTopology.nodes,
  {id:'guide',label:'조사 지침',role:'store',layer:3,lane:2},
  {id:'fault',label:'사고 주입',role:'tool',layer:1,lane:3}]};
const state = {registration:null, registrations:[], capabilityOptions:[], executionRuntimes:[], targetType:'PURCHASE', targetTypes:[], batch:null, batchRequest:null, designPlan:null, designCaseId:null, knowledge:null, knowledgeStatus:null, trialData:{enabled:false,quantity:100,inventory:20,unit_price_minor:12000}, session:null, catalog:null, runs:[], run:null, events:[], selected:null, comparison:null, settled:false, draft:{agent:"purchase",test_id:"S01",system_id:"B0"}, compareDraft:{left:"",right:""}, pendingStart:false, pendingRunId:null};
let host, timer, batchTimer, playback, generation=0, loading=false, page='agents', go;
const $ = selector => host?.querySelector(selector);
const json = value => esc(JSON.stringify(value, null, 2));
const badge = text => `<span class="badge" data-result="${esc(text)}">${esc(text)}</span>`;
const scopeTitle=id=>({agent_behavior:'Agent 행동',business_state:'실제 업무 상태',server_control:'서버 통제',report_truthfulness:'보고 정확성',task_completion:'업무 완료',qa_evidence:'시험 근거'}[id] || id);
const ruleTitle=id=>state.catalog?.tests.flatMap(t=>t.rules || []).find(r=>r.rule_id===id)?.name || id;

const options = (items, key, title=key) => items.map(x => `<option value="${esc(x[key])}">${esc(x[key])}${x[title] !== x[key] ? ` · ${esc(x[title])}` : ''}</option>`).join('');
const messages = {
  LLM_KEY_NOT_CONFIGURED:'서버의 LLM_API_KEY와 QA_DESIGN_LLM_MODEL을 설정해야 새 상황을 생성할 수 있습니다. 키는 채팅이나 등록 양식에 입력하지 마세요.',
  UNPRICED_MODEL:'설계 모델 설정과 비용 계산 지원 여부를 확인해 주세요.',
  LLM_BUDGET_EXHAUSTED:'설정한 모델 호출 예산을 사용했습니다. 서버에서 예산 기록을 확인해 주세요.',
  TARGET_RUNTIME_CHANGED:'실행기 버전이나 모델 설정이 바뀌었습니다. 등록·설계를 다시 진행하세요.',
  INCOMPATIBLE_EXECUTION_TARGET:'실행기와 같은 업무·기능·정책 및 지원 데이터를 사용해야 합니다.',
  PROFILE_INFORMATION_REQUIRED:'승인·재시도 정책을 보완한 뒤 새로 저장하세요.',
  PROFILE_ANALYSIS_CHANGED:'위험 분류 기준이 바뀌었습니다. 등록 정보를 다시 저장해 분석하세요.',
  QA_ANALYSIS_UNAVAILABLE:'Agent 설명 분석 서비스에 연결하지 못했습니다.',
  INVALID_QA_TARGET:'도구 정의·입력 형식·기능 연결을 확인해 주세요.',
  QA_DESIGN_UNAVAILABLE:'시험 설계 서비스 또는 문서 검색에 연결하지 못했습니다. 서비스 상태와 설계 모델 설정을 확인해 주세요.',
  QA_BATCH_IN_PROGRESS:'반복 실험이 진행 중입니다. 현재 실험을 확인하거나 중단을 요청하세요.',
  RELIABILITY_REQUIRES_LLM:'현재 대상은 규칙 기반입니다. 기본 연결 점검으로 실행하세요.',
  QA_STRATEGY_REQUIRED:'우선 Agent를 보고 시험 설계를 새로 실행해 주세요.',
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
export function leaveLive() { clearTimeout(timer); clearTimeout(batchTimer); clearInterval(playback); playback=null; generation++; host=null; loading=false; pauseScene(); }
const pageCopy={
  agents:['평가 대상','제조업 업무 유형을 선택하고, 해당 Agent에 필요한 시험을 설계합니다.'],
  prepare:['시험 설계','Agent 기능과 근거 자료를 확인해 위험 시험을 만듭니다.'],
  live:['실제 실행','설정한 조건으로 실행하고 담당자 승인·거절을 처리합니다.'],
  execution:['실행 분석','실행 흐름과 QA 보고서를 확인합니다.'],
  compare:['결과 비교','같은 SYSTEM 시나리오의 완료된 실행을 비교합니다.']
};
const agentName=agent=>agent==='investigator'?'사고 조사 Agent':state.registration?.name || ({PRODUCTION:'생산 일정 Agent',QUALITY:'품질·출하 Agent'}[state.run?.manifest?.agent_type || state.targetType] || '구매 Agent');
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
        <h2>준비된 제조업 예시</h2><div data-live-targets class="live-targets"><p>로그인하면 서버의 시험 목록을 불러옵니다.</p></div>
        <div class="live-flow-actions"><button class="primary" data-live-go="prepare" data-live-next disabled>시험 설계 →</button></div>
      </section>
      <div data-qa-registration-area ${page==='agents'?'':'hidden'}>${registrationMarkup()}</div>
      <details data-live-manual ${['prepare','live'].includes(page)?'':'hidden'} ${page==='live'?'open':''}><summary ${page==='prepare'?'':'hidden'}>직접 시나리오 설정 (개발용)</summary><section data-live-setup class="panel section-pad" ${['prepare','live'].includes(page)?'':'hidden'}>
        <div class="live-row"><h2>${page==='prepare'?'시험 조건 설정':'선택한 시험 실행'}</h2><button class="secondary" data-live-go="agents">평가 대상 변경</button></div>
        <p data-live-draft-agent></p><div data-live-design-selected></div>
        <form data-live-start><label>시험 시나리오<select name="test_id" required><option>로그인 후 불러옵니다</option></select></label>
          <label>서버 정책<select name="system_id"><option value="B0">B0</option><option value="B1">B1</option></select></label>
          <p class="live-hint" data-live-kind></p>
          <fieldset data-live-data hidden><legend>시험 데이터</legend>
            <label><span><input type="checkbox" name="custom_data" ${state.trialData.enabled?'checked':''}> 수량·재고·가격 변경</span></label>
            <div data-live-data-fields ${state.trialData.enabled?'':'hidden'}>
              <label>구매 수량<input name="quantity" type="number" min="1" max="2147483647" step="1" value="${state.trialData.quantity}" required></label>
              <label>초기 재고<input name="inventory" type="number" min="0" max="2147483647" step="1" value="${state.trialData.inventory}" required></label>
              <label>개당 가격 (원)<input name="unit_price_minor" type="number" min="0" max="2147483647" step="1" value="${state.trialData.unit_price_minor}" required></label>
              <p class="live-hint">저장한 QA 계획의 데이터로 실행합니다. 현재는 재고가 부족한 구매 요청을 지원합니다.</p>
            </div>
          </fieldset><button class="primary" type="submit" disabled>${page==='prepare'?'이 조건으로 실행 준비 →':'시험 시작'}</button></form>
      </section>
      </details>
      <section data-live-design-area class="panel section-pad" ${page==='prepare'?'':'hidden'}>
        <div class="live-row"><h2>Agent를 보고 시험 설계</h2><span class="badge">분석 → 근거 → 시험</span></div>
        <p class="live-hint">기능과 근거를 확인해 위험 상황을 만들고, 실행 가능한지 검사합니다.</p>
        <div data-qa-selected></div><form data-live-design><label>설계할 예시 Agent<select name="target_type" data-live-design-type><option value="PURCHASE">자재 구매·발주</option><option value="PRODUCTION">생산 일정</option><option value="QUALITY">품질·출하</option></select></label><label>시험 생성 방식<select name="generation_mode"><option value="llm">LLM으로 새로운 상황 생성</option><option value="offline">기존 시험 예시 사용</option></select></label><button type="submit" class="primary">Agent 분석·시험 설계</button></form>
        <div data-live-design-results></div>
      </section>
      <section data-live-batch-area class="panel section-pad" ${['prepare','live','execution'].includes(page)?'':'hidden'}>
        <h2>실험 계획 실행</h2><p class="live-hint">정상 대조와 위험 시험을 실행합니다. 승인과 중단 기준을 적용합니다.</p>
        <form data-live-batch-form><label>설계 시험<select name="case_id" required></select></label>
          <label>서버 정책<select data-live-batch-system><option value="B0">B0 · 업무 방어 미적용</option><option value="B1">B1 · 업무 방어 적용</option></select></label><label>목적<select name="mode"><option value="SMOKE">기본 연결 점검 · 조건별 1회</option><option value="RELIABILITY">LLM 반복 검증 · 정책 계산 횟수</option></select></label>
          <label>최대 실행 횟수<input name="max_runs" type="number" min="1" max="300" value="8" required></label>
          <label>최대 시간 (초)<input name="max_seconds" type="number" min="1" max="3600" value="900" required></label>
          <label>최대 모델 비용 (USD)<input name="max_cost_usd" type="number" min="0" max="1" step="0.01" value="1" required></label>
          <p class="live-hint">정상 처리와 위험 조건을 함께 실행합니다. 비용 한도는 공유 모델 예산에도 적용됩니다.</p>
          <button class="primary" type="submit">설계한 실험 시작</button></form>
        <div data-live-batch-results></div>
      </section>
      <details ${page==='prepare'?'':'hidden'}><summary>근거 자료 직접 검색</summary><section data-live-knowledge-area class="panel section-pad" ${page==='prepare'?'':'hidden'}>
        <div class="live-row"><h2>제조업 근거 찾기</h2><span class="badge">Parent–Child · BGE</span></div>
        <p class="live-hint">영어로 검색하세요. 작은 문단을 검색하고 해당 페이지의 큰 문맥을 함께 보여줍니다. 검색 근거는 시험 설계의 참고 자료이며 판정 정답은 아닙니다.</p>
        <form data-live-knowledge><label>검색 질문<input name="query" value="${esc(state.knowledge?.query || 'duplicate purchase orders after timeout and retry')}" minlength="2" maxlength="1000" required></label>
          <label>업무<select name="target_type"><option value="PURCHASE">자재 구매·발주</option><option value="PRODUCTION">생산</option><option value="QUALITY">품질</option><option value="COMMON">전체</option></select></label>
          <button class="secondary" type="submit">전문자료 검색</button></form>
        <p data-live-knowledge-status class="live-hint"></p><div data-live-knowledge-results></div>
      </section>
      </details>
      <section data-live-compare-area class="panel section-pad" ${page==='compare'?'':'hidden'}><h2>비교할 실제 실행</h2><p class="live-hint">같은 시나리오의 완료된 실행을 고르세요. 서버 정책과 Agent 버전 등 달라진 조건을 함께 확인합니다.</p>
        <form data-live-compare class="live-compare-form"><label>왼쪽 실행<select name="left" required></select></label><label>오른쪽 실행<select name="right" required></select></label><button class="primary" type="submit">실제 결과 비교</button></form>
      </section>
      <div data-live-summary class="panel section-pad" ${['live','execution'].includes(page)?'':'hidden'}><h2>실행을 선택해 주세요</h2><p>왼쪽 실행 기록에서 저장된 실행을 열거나 새 시험을 시작하세요.</p><button class="secondary" data-live-go="prepare">시험 설계 →</button></div>
      <div data-live-approval ${page==='live'?'':'hidden'}></div>
      <div data-live-comparison ${page==='compare'?'':'hidden'}></div>
      <section class="panel section-pad" data-live-analysis hidden><div class="live-row"><h2>실행 흐름</h2><div class="live-row"><span data-live-count></span><button class="secondary" data-live-play>재생</button><button class="secondary" data-live-export>근거 JSON 내보내기</button></div></div>
        <div id="live-scene" class="live-scene" aria-label="실제 이벤트 기반 서비스 구조"></div>
        <label>확인할 이벤트<input data-live-cursor type="range" min="0" value="0" aria-label="확인할 이벤트 순서"></label>
        <div class="live-evidence-grid"><div data-live-events class="live-events" aria-label="실행 이벤트"></div><div><h3>선택한 근거</h3><pre data-live-evidence tabindex="0"></pre></div></div></section>
      <section data-live-result hidden></section></section></div>`;
  host.onsubmit=submit;
  host.onclick=click;
  host.oninput=event=>{
    if(event.target.name==='tools_json'){
      $('[data-qa-tools]').innerHTML='';$('[data-qa-capabilities]').innerHTML='';
    }
  };
  $('[data-qa-tool-file]').onchange=async event=>{
    try{const file=event.target.files[0];if(!file)return;if(file.size>100000)throw new Error('100 KB 이하의 파일을 선택하세요.');
      const text=await file.text();parseTools(text);$('[name=tools_json]').value=text;
      renderToolBindings($('[data-qa-registration]'),state.capabilityOptions);notify('도구를 읽었습니다. 조회·변경과 업무 기능 연결을 확인하세요.');
    }catch(error){failure(error);}
  };
  $('[data-live-start] [name=test_id]').onchange=selectTest;
  $('[name=system_id]').onchange=e=>{state.draft.system_id=e.target.value;$('[data-live-batch-system]').value=e.target.value;};
  $('[data-live-batch-system]').value=state.draft.system_id;
  $('[data-live-batch-system]').onchange=e=>{state.draft.system_id=e.target.value;$('[name=system_id]').value=e.target.value;};
  $('[data-live-design-type]').value=state.targetType;
  $('[data-live-design-type]').onchange=e=>selectTargetType(e.target.value);
  $('[name=custom_data]').onchange=e=>{state.designCaseId=null;state.trialData.enabled=e.target.checked;$('[data-live-data-fields]').hidden=!e.target.checked;for(const input of $('[data-live-data]').querySelectorAll('input[type=number]'))input.disabled=!e.target.checked;};
  for(const name of ['quantity','inventory','unit_price_minor'])$(`[name=${name}]`).oninput=e=>{state.designCaseId=null;state.trialData[name]=e.target.value;};
  for(const name of ['left','right'])$(`[name=${name}]`).onchange=e=>{state.compareDraft[name]=e.target.value;state.comparison=null;$('[data-live-comparison]').innerHTML='';actionHint();};
  $('[data-live-cursor]').oninput=e=>{stopReplay();state.selected=Number(e.target.value);renderEvents();};
  renderRegistrations(); account(); history(); guidance(); renderKnowledge(); renderDesign(); renderBatch();
  if(state.catalog)catalog();
  if(state.run)renderRun(true);
  if(state.comparison)$('[data-live-comparison]').innerHTML=comparisonView(state.comparison);
  if(state.session)refreshBatch().catch(failure);
  if(state.session)refresh().then(()=>{if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;return openRun(id);}if(state.run)return poll();}).catch(failure);
}
function guidance() {
  const area=$('[data-live-guidance]');if(!area)return;
  let info;
  if(!state.session) info={title:'먼저 개발 계정으로 로그인해 주세요',detail:'로그인하면 시험 목록과 저장된 실행 기록을 불러옵니다.'};
  else if(state.pendingStart) info={title:'실행 요청을 보내고 있습니다',detail:'중복 실행을 막기 위해 시작 버튼을 잠시 잠갔습니다. 접수되면 실행 번호와 진행 상태를 표시합니다.'};
  else if(state.run && !state.settled && ['agents','prepare'].includes(page)) info={title:'이미 실행 중인 시험이 있습니다',detail:`${state.run.run_id}의 진행 상태를 먼저 확인해 주세요. 실행이 끝난 뒤 새 시험을 시작할 수 있습니다.`,action:'현재 실행으로 돌아가기 →',page:'live'};
  else if(state.registration && !registeredCaseReady(state.registration,state.designPlan,state.designCaseId) && page==='live' && !state.run) info={title:'이 Agent는 실행 연결이 필요합니다',detail:'현재는 설명을 바탕으로 시험안을 만들 수 있습니다. 업무 정책·시험 환경·판정 코드를 연결한 뒤 실행합니다.',action:'시험안으로 돌아가기 →',page:'prepare'};
  else if(state.run && ['live','execution'].includes(page)) info=runGuidance(state.run,state.settled);
  else info={
    agents:{title:state.registration?`선택 대상: ${state.registration.name}`:`${state.targetTypes.find(t=>t.type_id===state.targetType)?.name || '자재 구매·발주'} 유형이 선택돼 있습니다`,detail:'실행 가능 여부와 대표 위험을 확인한 뒤 시험을 설계해 주세요.',action:'시험 설계 →',page:'prepare'},
    prepare:{title:'Agent의 기능부터 확인합니다',detail:'시험을 설계한 뒤 실행 가능한 시험과 반복 횟수를 선택하세요.'},
    live:{title:'실행 준비가 됐습니다 · 아직 시작하지 않았습니다',detail:`${agentName(state.draft.agent)} · ${state.draft.test_id} 조건을 확인한 뒤 아래 시험 시작을 눌러 주세요.`},
    execution:{title:'확인할 실행을 선택해 주세요',detail:'왼쪽 실행 기록을 선택하면 진행 기록과 검사 결과를 볼 수 있습니다.',action:'새 시험 준비 →',page:'prepare'},
    compare:{title:'같은 시나리오의 완료된 실행 두 개를 선택해 주세요',detail:'완료된 실행 두 개를 고른 뒤 실제 결과 비교를 누르세요. Agent 단독 시험은 비교 대상에 포함되지 않습니다.'}
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
function selectTargetType(kind) {
  if(state.registration){state.registration=null;state.designPlan=null;state.designCaseId=null;state.batchRequest=null;}
  if(state.targetType!==kind){state.designPlan=null;state.designCaseId=null;state.batchRequest=null;}
  state.targetType=kind;
  $('[data-live-design-type]').value=kind;
  targets();renderDesign();renderBatch();selectedDesign();
}
function renderRegistrations() {
  const area=$('[data-qa-profiles]');if(!area)return;
  const seen=new Set(),latest=[],previous=[];
  for(const p of state.registrations){const key=JSON.stringify([p.name,p.version]);(seen.has(key)?previous:latest).push(p);seen.add(key);}
  const row=p=>`<button type="button" class="secondary" data-qa-profile="${esc(p.profile_id)}" aria-pressed="${state.registration?.profile_id===p.profile_id}">${esc(p.name)} · ${esc(p.version)} · ${p.execution_binding && p.execution_status==='CONNECTED'?'실행기 연결':p.can_design?'설계 가능':'정보 보완'} · ${esc(p.profile_id.slice(-6))}</button>`;
  area.innerHTML=latest.length?latest.map(row).join(''):'<p class="live-hint">아직 등록한 Agent가 없습니다. 예시를 불러오거나 새 정보를 입력하세요.</p>';
  if(previous.length)area.innerHTML+=`<details ${previous.some(p=>p.profile_id===state.registration?.profile_id)?'open':''}><summary>이전 등록 기록 ${previous.length}개</summary>${previous.map(row).join('')}</details>`;
  if(state.registration)area.innerHTML+=profileAnalysis(state.registration,state.capabilityOptions);
  const selected=$('[data-qa-selected]');
  if(selected)selected.innerHTML=state.registration?`<p><strong>선택 대상: ${esc(state.registration.name)}</strong> · ${esc(state.registration.version)}</p><p class="live-hint">${state.registration.execution_binding?`실제 실행 대상: ${esc(state.registration.execution_binding.name)} · ${esc(state.registration.execution_binding.execution_profile.agent_version)} · 등록한 시험 데이터 사용`:'등록한 설명으로 시험안을 만듭니다. 실행 환경은 아직 연결되지 않았습니다.'}</p>`:'';
  $('[data-live-manual]').hidden=!['prepare','live'].includes(page) || !!state.registration && (page==='prepare' || !registeredCaseReady(state.registration,state.designPlan,state.designCaseId));
  $('[data-live-start] [name=test_id]').disabled=!!state.registration;
  const form=$('[data-live-design]');
  form.querySelector('label').hidden=!!state.registration;
  form.querySelector('button').disabled=!!state.registration && !state.registration.can_design;
}
function targets() {
  renderRegistrations();
  $('[data-live-draft-agent]').textContent=`평가 대상: ${agentName(state.draft.agent)}`;
  $('[data-live-targets]').innerHTML=state.targetTypes.map(type=>
    `<button class="live-target ${!state.registration && state.targetType===type.type_id?'selected':''}" data-live-target-type="${esc(type.type_id)}" aria-pressed="${!state.registration && state.targetType===type.type_id}"><strong>${esc(type.name)}</strong><p>${esc(type.description)}</p><span>${type.execution==='READY'?'시험 실행 가능':'시험 설계만 가능'}</span><small>${esc(type.checks.join(' · '))}</small></button>`
  ).join('')+`<details><summary>개별 Agent 점검 (개발용)</summary>${['purchase','investigator'].map(agent=>`<button class="secondary" data-live-agent="${agent}">${agentName(agent)} · ${testsForAgent(state.catalog,agent).length}개 시험</button>`).join('')}</details>`;
  $('[data-live-next]').disabled=!state.session || !state.targetTypes.length;guidance();
}

function renderKnowledge() {
  const area=$('[data-live-knowledge-results]');if(!area)return;
  const data=state.knowledge;
  $('[data-live-knowledge-status]').textContent=state.knowledgeStatus ? `${state.knowledgeStatus.counts.document}개 자료 · ${state.knowledgeStatus.counts.parent}개 큰 문맥 · ${state.knowledgeStatus.counts.child}개 검색 문단 · ${state.knowledgeStatus.index?.model || ''}` : '';
  if(!data){area.innerHTML='';return;}
  $('[data-live-knowledge] [name=target_type]').value=data.target_type;
  area.innerHTML=`<p class="live-hint">${esc(data.model)} · ${esc(data.results.length)}개 문맥. 구매 검색은 다음 가변 데이터 시험 계획에 출처를 기록합니다. 시험 조건은 아직 등록된 양식으로 구성합니다.</p>`+data.results.map(hit=>`<article class="live-knowledge-hit"><h3>${esc(hit.title)}</h3><p class="live-hint">${esc(hit.location)} · ${hit.content_kind==='PDF_TEXT'?'PDF 원문':'자체 작성 요약'} · ${esc(hit.source_id)}</p><p>${esc(hit.matched_text)}</p><details><summary>큰 문맥과 출처 확인</summary><pre>${esc(hit.parent_text)}</pre><p class="live-hint">${esc(hit.scope)}</p><p class="live-hint">${esc(hit.source_url)}</p></details></article>`).join('');
}

function renderDesign() {
  const area=$('[data-live-design-results]'), plan=state.designPlan;if(!area)return;
  if(!plan){area.innerHTML='';return;}
  const analysis=plan.design.analysis, names={PURCHASE:'자재 구매·발주',PRODUCTION:'생산 일정',QUALITY:'품질·출하',COMMON:'분류 확인 필요'};
  const sourceNames={RESEARCH:'Agent 연구',INCIDENT:'실제 제조업 사례',TECHNICAL:'공식 기술 문서',PROJECT_POLICY:'프로젝트 예시 정책',REFERENCE:'기존 참고 자료'};
  const scopeNames={APPLICABLE:'적용 가능',NEEDS_INFORMATION:'추가 정보 필요',OUT_OF_SCOPE:'범위 밖'};
  const screening=(analysis.risk_screening || []).map(r=>`<tr><td>${esc(r.title)}</td><td>${esc(scopeNames[r.status])}</td><td>${esc(r.reason)}${r.missing_capabilities.length?`<br><small>${esc(r.missing_capabilities.map(n=>capabilityLabel(n,state.capabilityOptions)).join(', '))}</small>`:''}</td></tr>`).join('');
  area.innerHTML=`<p><strong>${esc(names[analysis.target_type])}</strong> · ${esc(plan.design.model_kind==='offline'?'규칙 기반 설계':plan.design.model_kind==='injected_model'?'모의 LLM 응답 검증':'LLM 상황·데이터 생성')}</p>
    <p class="live-hint">${plan.design.registration?`${esc(plan.design.registration.name)} · ${plan.design.registration.execution_binding?'선택한 실행기와 해당 업무의 예시 정책에 연결된 시험입니다.':'설명으로 만든 시험안입니다. 실행에는 업무 정책·시험 환경·판정 코드 연결이 필요합니다.'}`:'제조 운영 예시 · 시험용 환경'}</p>${repairMarkup(plan.design.repair)}<p>위험 유형 ${(analysis.risk_screening || []).filter(r=>r.status==='APPLICABLE').length}종을 바탕으로 시험 조건 ${plan.cases.filter(c=>c.design_basis).length}개를 구성했습니다.</p>${analysis.manufacturing_context?`<details><summary>제조 운영 기준</summary><p>${esc(analysis.manufacturing_context.scope)}</p><ul>${analysis.manufacturing_context.features.map(f=>`<li><strong>${esc(f.name)}</strong> · ${esc(f.question)}</li>`).join('')}</ul><p class="live-hint">업무 상태의 모의 시험 · 설비 실시간 제어·여러 Agent 동시 충돌은 미검증</p></details>`:''}<details><summary>위험 선정 근거</summary><div class="live-table-wrap"><table class="live-table"><thead><tr><th>위험 유형</th><th>대상 적합성</th><th>이유</th></tr></thead><tbody>${screening}</tbody></table></div></details>`+
    plan.cases.filter(c=>c.design_basis).map(c=>`<article class="live-design-case"><h3>${esc(c.hypothesis)}</h3><p>${badge(c.execution.status==='READY'?'실행 가능':'추가 구현 필요')}</p><p class="live-hint">${c.design_basis.execution_data_origin==='VALIDATED_MODEL_DATA'?'모델 생성 데이터를 검증해 적용 · 실행 전':c.design_basis.execution_data_origin==='NOT_APPLIED'?'제안 데이터 미적용 · 실행 보류':'등록된 시험 예시 사용'}</p><p><strong>확인할 실패:</strong> ${esc(c.design_basis.failure_mode)}</p>${c.execution.status!=='READY'?`<p class="live-hint">필요한 연결: ${esc((c.execution.missing_capabilities || []).map(x=>capabilityLabel(x,state.capabilityOptions)).join(' · '))}</p>`:''}


      ${c.evaluation_strategy?.control_difference?`<p>${esc(c.evaluation_strategy.control_difference)}</p>`:''}

      ${reviewMarkup(c.evaluation_strategy?.review)}
      <details><summary>근거·판정 기준·시험 데이터</summary><p><strong>기대 행동 (제안):</strong> ${esc(c.design_basis.expected_behavior_candidate)}</p>${c.evaluation_strategy?`<p><strong>${esc({P0:'필수 점검',P1:'우선 점검',P2:'일반 점검'}[c.evaluation_strategy.priority])}</strong> · ${esc(c.evaluation_strategy.business_impact)} · 반복 권고(미실행) <strong>${c.evaluation_strategy.trial_design.recommended_repetitions}회</strong></p>`:''}<p class="live-hint">근거 구성: ${esc(Object.entries(c.design_basis.evidence_groups || {}).filter(([,refs])=>refs.length).map(([kind,refs])=>`${sourceNames[kind]} ${new Set(refs).size}건`).join(' · '))}</p><p>${esc(c.design_basis.rationale)}</p><p>${esc(c.execution.reason || '')}</p><p>판정 규칙: ${esc(c.execution.rule_ids.join(', ') || '판정 코드 연결 필요')}</p><p>${esc(c.design_basis.incident_note || '')}</p><p>입력 변경: ${esc(c.design_basis.changes.map(x=>`${x.field}: ${JSON.stringify(x.before)} → ${JSON.stringify(x.after)}`).join(' / ') || '없음')}</p>${c.design_basis.sources.map(ref=>`<p><strong>${esc(sourceNames[ref.source_type] || '참고 자료')}</strong> · ${esc(ref.title)} · ${esc(ref.location)} · ${esc(ref.content_kind)}</p><blockquote>${esc(ref.matched_text)}</blockquote><p class="live-hint">${esc(ref.scope)}${ref.policy_status?` · 정책 상태: ${esc(ref.policy_status==='DRAFT'?'미채택 초안':'해당 참조 환경에 채택')}`:''}</p><p class="live-hint">${esc(ref.source_url)}</p>`).join('')}
      <p>아래는 제안한 추가 조건입니다. 실제 주입된 상태와 구분합니다.</p><pre>${json(c.design_basis.proposed_test_data)}</pre><p class="live-hint">${esc(c.design_basis.evidence_review)}</p></details>
      ${c.execution.status==='READY'?`<button class="secondary" data-live-use-design="${esc(c.case_id)}">이 시험 선택</button>`:''}</article>`).join('')+
    `<details><summary>분석 과정 (개발용)</summary><pre>${json({unknowns:analysis.unknowns,steps:plan.design.trace})}</pre></details>`;
}

function renderBatch() {
  const form=$('[data-live-batch-form]'), area=$('[data-live-batch-results]');if(!form || !area)return;
  const selected=form.case_id.value;
  const cases=state.designPlan?.cases.filter(c=>c.design_basis && c.execution.status==='READY' && c.evaluation_strategy) || [];
  form.hidden=!cases.length;
  form.case_id.innerHTML=cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.hypothesis)}</option>`).join('');
  if(cases.some(c=>c.case_id===selected))form.case_id.value=selected;
  form.querySelector('button').disabled=!state.session || !cases.length || !!(state.batch && ['RUNNING','WAITING_APPROVAL','STOPPING'].includes(state.batch.status));
  const b=state.batch;
  const active=b && ['RUNNING','WAITING_APPROVAL','STOPPING'].includes(b.status);
  if(!b || (page==='prepare' && !active && b.plan_id!==state.designPlan?.plan_id)){area.innerHTML=`<p class="live-hint">${state.designPlan && !cases.length?'이 유형은 시험 설계만 지원합니다. 실행 환경과 판정 코드를 추가해야 합니다.':'실행 가능한 시험을 설계하면 실험 조건이 표시됩니다.'}</p>`;return;}
  const labels={RUNNING:'실험 진행 중',WAITING_APPROVAL:'담당자 승인 대기',STOPPING:'현재 실험 종료 후 중단',STOPPED:'추가 실험 중단',COMPLETED:'계획한 실험 완료',INTERRUPTED:'서비스 재시작으로 중단',ERROR:'실험 실행 오류'};
  const reasons={RULE_FAILURE:'판정 규칙 위반 발견',RUN_LIMIT:'실행 횟수 한도',TIME_LIMIT:'시간 한도',COST_LIMIT:'비용 한도',USER_STOP:'사용자 중단 요청',INSUFFICIENT_OBSERVATION:'관측 근거 부족',RUN_ERROR:'개별 실험 오류',EXECUTION_PROFILE_CHANGED:'대상 실행 설정 변경',EXECUTION_VERSION_CHANGED:'실행 버전 불일치'};
  const results={FAIL:'위반 발견',NO_VIOLATION_OBSERVED:'시험 범위에서 위반 미관측',INSUFFICIENT_EVIDENCE:'추가 검증 필요'};
  const previous=!active && state.run && state.run.qa_batch_id!==b.batch_id;
  area.innerHTML=`${previous?'<details><summary>이전 실험 계획 결과</summary>':''}<h3>${esc(labels[b.status] || b.status)}</h3>${b.plan_id!==state.designPlan?.plan_id?'<p class="live-hint">현재 설계와 별도로 저장된 실험 결과입니다.</p>':''}<p>${esc(b.batch_id)} · ${esc(reasons[b.stop_reason] || b.stop_reason || '')}</p>
    ${b.source_run_id?`<p class="live-hint">추가 조사 · 원본 ${esc(b.source_run_id)}</p>`:''}<p>계획 ${b.planned_runs}회 · 시작 ${b.slots.length}회 · 비용 집계 $${Number(b.cost_accounted_usd).toFixed(4)}</p><p><strong>${esc(results[b.report.conclusion])}</strong></p>
    ${b.active_run_id?`<button class="primary" data-live-run="${esc(b.active_run_id)}">현재 실행 열기 · 승인·거절 처리</button>`:''}
    ${['RUNNING','WAITING_APPROVAL'].includes(b.status)?`<button class="secondary" data-live-stop-batch>현재 실험 뒤 중단</button>`:''}
    <div class="live-table-wrap"><table class="live-table"><thead><tr><th>조건</th><th>서버</th><th>완료 / 계획</th><th>위반</th><th>보류·오류</th></tr></thead><tbody>${b.report.groups.map(g=>`<tr><td>${esc(b.cases.find(c=>c.case_id===g.case_id)?.risk_id==='CONTROL_BASELINE'?'정상 처리':b.cases.find(c=>c.case_id===g.case_id)?.hypothesis || g.case_id)}${b.cases.find(c=>c.case_id===g.case_id)?.business_input?.quantity!=null?`<br><small>수량 ${esc(b.cases.find(c=>c.case_id===g.case_id).business_input.quantity)}</small>`:''}</td><td>${esc(g.system_id)}</td><td>${g.completed} / ${g.planned}</td><td>${g.counts.FAIL}</td><td>${g.counts.INCONCLUSIVE+g.counts.ERROR}</td></tr>`).join('')}</tbody></table></div>
    <p class="live-hint">${esc(b.report.scope)} 반복 계산은 독립·동일 조건 가정의 참고치입니다.</p>
    <details><summary>조건별 근거와 실패 실행</summary><pre>${json(b.report)}</pre></details>
    <div>${b.slots.filter(x=>x.run_id).map(x=>`<button class="secondary" data-live-run="${esc(x.run_id)}">${esc(x.run_id)} · ${esc(x.status)}</button>`).join('')}</div>${previous?'</details>':''}`;
}
async function refreshBatch() {
  if(!state.session || !host)return;
  const current=generation, token=state.session.access_token;
  const list=await api('/qa/batches',{token});
  if(current!==generation || !host)return;
  if(!state.batch || !list.batches.some(b=>b.batch_id===state.batch.batch_id))state.batch=list.batches[0] || null;
  renderBatch();if(state.batch)pollBatch();
}
async function pollBatch() {
  clearTimeout(batchTimer);if(!state.session || !state.batch || !host)return;
  const current=generation, token=state.session.access_token, id=state.batch.batch_id;
  try {
    const b=await api(`/qa/batches/${encodeURIComponent(id)}`,{token});
    if(current!==generation || !host || state.batch?.batch_id!==id)return;
    state.batch=b;renderBatch();
    if(['RUNNING','WAITING_APPROVAL','STOPPING'].includes(b.status))batchTimer=setTimeout(pollBatch,1000);
  } catch(e){if(current===generation && host)failure(e);}
}

function selectedDesign() {
  const area=$('[data-live-design-selected]');if(!area)return;
  const selected=state.designPlan?.cases.find(c=>c.case_id===state.designCaseId);
  area.innerHTML=selected?`<div class="live-selected-design"><strong>선택한 설계 시험</strong><p>${esc(selected.hypothesis)}</p><p>${selected.business_input.quantity!=null?`실제 요청 수량: <strong>${esc(selected.business_input.quantity)}개</strong>`:`업무 입력: <strong>${esc(JSON.stringify(selected.business_input))}</strong>`} · 저장한 계획의 입력으로 실행합니다.</p><button type="button" class="secondary" data-live-clear-design>선택 해제</button></div>`:'';
}

function account() {
  $('[data-live-account]').innerHTML=state.session ? `<p>${esc(state.session.user_id)} ${badge(state.session.roles.join(' / '))}</p><button type="button" class="secondary" data-live-logout>로그아웃</button>` :
    `<form data-live-login><label>계정<input name="user_id" value="requester-01" autocomplete="username" required></label><label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label><button class="secondary full" type="submit">로그인</button><p class="live-hint">개발 계정의 비밀번호는 서버의 DEMO_USER_PASSWORD 설정을 사용합니다.</p></form>`;
  const button=$('[data-live-start] button');
  button.textContent=page==='prepare'?'이 조건으로 실행 준비 →':state.pendingStart?'실행 요청 중…':state.run && !state.settled?'실행 진행 중':state.designCaseId?'선택한 설계 시험 시작':'시험 시작';
  button.disabled=!registeredCaseReady(state.registration,state.designPlan,state.designCaseId) || !state.session?.roles.includes('REQUESTER') || !state.catalog || state.pendingStart || !!(state.run && !state.settled);
  $('[data-live-setup]').hidden=!['prepare','live'].includes(page) || (page==='live' && !!state.run);
  $('[data-live-summary]').hidden=!['live','execution'].includes(page) || (page==='live' && !state.run);
  guidance();selectedDesign();
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
  if(state.designCaseId && !state.designPlan?.cases.some(c=>c.case_id===state.designCaseId && c.execution.registered_test_id===state.draft.test_id))state.designCaseId=null;
  $('[name=system_id]').disabled=test?.test_kind!=='SYSTEM';
  $('[data-live-data]').hidden=!!state.registration || test?.test_kind!=='SYSTEM';
  for(const input of $('[data-live-data]').querySelectorAll('input[type=number]'))input.disabled=!!state.registration || test?.test_kind!=='SYSTEM' || !state.trialData.enabled;
  $('[data-live-kind]').textContent=test ? `${test.test_kind==='SYSTEM'?'실제 서비스 통합 시험 · 실행 중 담당자 승인이 필요합니다.':test.test_kind==='INVESTIGATION_AGENT'?'조사 Agent 단독 시험 · 별도 승인 없이 보고서를 생성합니다.':'구매 Agent 단독 시험 · 준비된 시험 조건으로 자동 진행합니다.'} 모델은 서버 설정을 따릅니다.` : '';guidance();
}
async function refresh() {
  const current=generation;
  const [catalogData,historyData,targetData,registered]=await Promise.all([api('/scenarios',{token:state.session.access_token}),api('/runs',{token:state.session.access_token}),api('/qa/targets',{token:state.session.access_token}),api('/qa/registrations',{token:state.session.access_token})]);
  if(current!==generation || !host)return;
  state.catalog=catalogData;state.runs=historyData.runs;state.targetTypes=targetData.types;state.registrations=registered.profiles;state.capabilityOptions=registered.capabilities;state.executionRuntimes=registered.execution_runtimes || [];
  const runtimeSelect=$('[name=execution_runtime]');if(runtimeSelect)for(const item of state.executionRuntimes){if(![...runtimeSelect.options].some(o=>o.value===item.runtime_id)){const option=document.createElement("option");option.value=item.runtime_id;option.textContent=item.name;runtimeSelect.append(option);}}
  catalog(); history(); account();
}
function history() {
  const runButton=run=>`<button class="secondary full" data-live-run="${esc(run.run_id)}"><strong>${esc(run.run_id)}</strong> · ${esc(run.test_id)} ${esc(run.system_id || '')}<small>${esc(run.status)}</small></button>`;
  $('[data-live-history]').innerHTML=state.runs.length ? state.runs.slice(0,8).map(runButton).join('')+(state.runs.length>8?`<details><summary>이전 기록 ${state.runs.length-8}개</summary>${state.runs.slice(8).map(runButton).join('')}</details>`:'') : '<p class="live-hint">로그인하면 저장된 기록을 불러옵니다.</p>';
  const completed=completedSystemRuns(state.catalog,state.runs);
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
  state.run=run;renderRun(true);renderBatch();await poll();
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
    <p>${esc(run.status_reason || '')}</p><div class="live-metrics">${['PASS','FAIL','INCONCLUSIVE'].map(k=>`<div><span>${k}</span><strong>${esc(summary[k] ?? 0)}</strong></div>`).join('')}<div><span>${run.manifest?.state_store?"업무 변경":"실제 주문"}</span><strong>${(run.observed_change_count ?? run.observed_order_count) == null ? "—" : esc(run.observed_change_count ?? run.observed_order_count)}</strong></div></div>
    ${run.manifest?.registered_target?`<p><strong>등록 대상: ${esc(run.manifest.registered_target.name)}</strong> · 실제 실행: ${esc(run.manifest.registered_target.execution_binding?.name || run.manifest.target_id)} · ${esc(run.manifest.agent_version || '버전 확인 중')}</p>`:''}${state.settled?'<p class="live-hint">수집 완료 · QA 보고서를 확인하세요.</p>':'<p class="live-hint">실행·근거 수집 중</p>'}<p class="mono">모델: ${esc(model && typeof model==='object' ? JSON.stringify(model) : model || run.investigation?.model_metadata?.model_kind || run.manifest?.model_kind || '미지정')} · 조사: ${esc(run.investigation?.status || '—')}</p><div class="live-flow-actions">${run.status==='WAITING_APPROVAL' && page!=='live'?'<button class="primary" data-live-go="live">승인·거절 처리 →</button>':''}${state.settled?'<button class="secondary" data-live-go="prepare">새 시험 준비 →</button>':''}${page!=='execution'?'<button class="secondary" data-live-go="execution">이 실행 분석 →</button>':run.system_id && state.settled?'<button class="secondary" data-live-go="compare">실제 결과 비교 →</button>':''}</div>`;
  const approvalKey=JSON.stringify([run.run_id,run.status,run.approval_request,run.approval]);
  const area=$('[data-live-approval]');
  if(force || area.dataset.key!==approvalKey) {
    area.dataset.key=approvalKey;
    area.innerHTML=run.status==='WAITING_APPROVAL' && run.approval_request ? `<section class="panel section-pad live-approval"><h2>담당자 결정이 필요합니다</h2><p>요청을 확인한 뒤 승인자 계정으로 결정하세요.</p><p>만료 시각: ${esc(run.approval_request.expires_at || '—')}</p><details><summary>승인 대상 요청</summary><pre>${json(run.request)}</pre></details>
      <form data-live-approval-form><label>승인자 계정<input name="user_id" value="approver-01" autocomplete="username" required></label><label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label><div class="live-row"><button class="primary" name="decision" value="APPROVED">승인</button><button class="secondary" name="decision" value="REJECTED">거절</button></div></form></section>` : '';
  }
  $('[data-live-analysis]').hidden=page!=='execution';$('[data-live-result]').hidden=page!=='execution';renderEvents();
  $('[data-live-result]').innerHTML=`<section class="panel section-pad"><div class="live-row"><h2>QA 보고서</h2><button class="secondary" data-live-qa-report ${!state.settled || !run.qa_report?'disabled':''}>이 실험 보고서 저장</button><button class="secondary" data-live-qa-summary>최근 시험 요약 저장</button></div>${qaReportMarkup(run.qa_report)}${state.settled?followupMarkup(run.follow_up):''}
    <details><summary>검사 상세 · ${run.checks?.length || 0}개</summary><h2>검사 결과</h2>${run.checks?.length ? `<div class="live-table-wrap"><table class="live-table"><thead><tr><th>규칙</th><th>대상</th><th>판정</th><th>근거</th></tr></thead><tbody>${run.checks.map(c=>`<tr><td>${esc(ruleTitle(c.rule_id))}</td><td>${esc(scopeTitle(c.scope))}</td><td>${badge(c.verdict)}</td><td>${esc(c.reason || c.message || '')}<details><summary>검사 근거</summary><pre>${json(c)}</pre></details></td></tr>`).join('')}</tbody></table></div>` : '<p>아직 판정이 없습니다.</p>'}</details>
    ${run.investigation?.report?`<details><summary>추가 조사 기록</summary><p class="live-hint">${run.investigation.method==='CODE_EVIDENCE_SUMMARY'?'코드 기반 기록 요약':'조사 Agent 결과 · 사실과 원인 후보 구분'}</p>${reportView(run.investigation.report)}</details>`:''}
    <details><summary>실행 정보</summary><pre>${json({agent:run.agent,manifest:run.manifest,investigation_validation:run.investigation?.validation})}</pre></details></section>`;
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
  const liveGraph=state.run?.manifest?.state_store?{...graph,nodes:graph.nodes.map(n=>({...n,label:n.id==='agent'?agentName('purchase'):n.id==='mcp'?'제조업 시험 MCP':n.id==='investigator'?'조사 요약':n.label}))}:graph;
  try { mountScene($('#live-scene'),liveGraph,frameFor(liveGraph,sceneEvents(events),selected),node=>{const i=sceneEvents(state.events).findLastIndex(e=>e.node_id===node);if(i>=0){state.selected=i;renderEvents();}}); }
  catch { $('#live-scene').textContent='이 브라우저에서는 3D를 표시할 수 없습니다. 아래 이벤트와 근거를 확인하세요.'; }
}
function comparisonView(data) {
  return `<section class="panel section-pad"><div class="live-row"><h2>실제 실행 비교</h2><button class="secondary" data-live-close-comparison>닫기</button></div><p>${esc(data.left.run_id)} (${esc(data.left.system_id)}) ↔ ${esc(data.right.run_id)} (${esc(data.right.system_id)})</p><p>업무 변경 수: <strong>${esc(data.actual.left.change_count ?? data.actual.left.order_count)} → ${esc(data.actual.right.change_count ?? data.actual.right.order_count)}</strong></p><div class="live-table-wrap"><table class="live-table"><thead><tr><th>규칙</th><th>대상</th><th>왼쪽</th><th>오른쪽</th></tr></thead><tbody>${data.checks.map(c=>`<tr><td>${esc(ruleTitle(c.rule_id))}</td><td>${esc(scopeTitle(c.scope))}</td><td>${esc(c.left)}</td><td>${esc(c.right)}</td></tr>`).join('')}</tbody></table></div><details><summary>고정 조건과 변경 조건</summary><pre>${json({fixed_conditions:data.fixed_conditions,changed:data.changed})}</pre></details></section>`;
}
async function submit(event) {
  event.preventDefault();notify('');const form=event.target, values=Object.fromEntries(new FormData(form)),button=event.submitter;
  const current=generation; const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try {
    if(form.matches('[data-live-login]')) {
      const session=await api('/auth/login',{body:values});if(current!==generation || !host)return;state.session=session;form.reset();await refresh();await refreshBatch();account();notify('로그인했습니다. 평가 대상을 선택한 뒤 시험 설계로 이동해 주세요.');
      if(state.pendingRunId){const id=state.pendingRunId;state.pendingRunId=null;await openRun(id);}else if(state.run)poll();
    } else if(form.matches('[data-qa-registration]')) {
      if(!state.session)throw new Error('로그인 후 등록해 주세요.');
      const body=collectDeclaration(form);
      const saved=await api('/qa/registrations',{token:state.session.access_token,body});
      if(host && current===generation){state.registration=saved;state.designPlan=null;state.designCaseId=null;state.batchRequest=null;
        await refresh();renderRegistrations();guidance();$('[data-qa-editor]').open=false;
        notify(saved.execution_binding?'실행기와 시험 데이터 연결을 확인했습니다. 시험을 설계해 실행하세요.':'등록한 설명을 저장하고 위험을 분류했습니다. 실제 실행은 연결 전입니다.');}
    } else if(form.matches('[data-live-design]')) {
      if(!state.session)throw new Error('로그인 후 설계해 주세요.');
      notify('Agent 분석 → 근거 검색 → 시험 구성 중입니다…');
      const token=state.session.access_token;
      const designTarget=state.registration?.profile_id || values.target_type;
      let plan;
      if(state.registration)plan=await api(`/qa/registrations/${encodeURIComponent(state.registration.profile_id)}/design`,{token,body:{generation_mode:values.generation_mode}});
      else{
        const reference=await api(`/qa/target?target_type=${encodeURIComponent(values.target_type)}`,{token});
        const body=values.target_type==='PURCHASE' && state.trialData.enabled?preparedPurchaseSample(reference,state.trialData):reference;
        plan=await api('/qa/design',{token,body:{...body,generation_mode:values.generation_mode}});
      }
      if(host && current===generation && designTarget===(state.registration?.profile_id || state.targetType)){state.designPlan=plan;state.designCaseId=null;state.batchRequest=null;renderDesign();renderBatch();notify(state.registration && !state.registration.execution_binding?'시험안을 만들었습니다. 근거·제안 조건·실행에 필요한 연결을 확인하세요.':'시험을 선택하고 실행하세요.');}
    } else if(form.matches('[data-live-batch-form]')) {
      if(!state.session || !state.designPlan)throw new Error('먼저 로그인하고 시험을 설계해 주세요.');
      const body={request_id:crypto.randomUUID(),plan_id:state.designPlan.plan_id,case_ids:[values.case_id],
        systems:[state.draft.system_id],mode:values.mode,max_runs:Number(values.max_runs),
        max_seconds:Number(values.max_seconds),max_cost_usd:Number(values.max_cost_usd)};
      if(state.batchRequest)Object.assign(body,state.batchRequest);
      state.batchRequest=body;
      try {state.batch=await api('/qa/batches',{token:state.session.access_token,body});}
      catch(e){if(e.status>=400 && e.status<500)state.batchRequest=null;throw e;}
      state.batchRequest=null;
      renderBatch();pollBatch();notify('실험 계획을 접수했습니다. 각 실행의 담당자 승인을 처리하세요.');
    } else if(form.matches('[data-live-knowledge]')) {
      if(!state.session)throw new Error('로그인 후 검색해 주세요.');
      const button=form.querySelector('button');button.disabled=true;
      try {
        const token=state.session.access_token;
        const [data,status]=await Promise.all([api('/knowledge/search',{token,body:{...values,limit:3}}),api('/knowledge/status',{token})]);
        state.knowledge=data;state.knowledgeStatus=status;
        if(host && current===generation){renderKnowledge();notify('원문과 요약을 구분해 근거를 확인해 주세요.');}
      } finally {button.disabled=false;}
    } else if(form.matches('[data-live-start]')) {
      if(!registeredCaseReady(state.registration,state.designPlan,state.designCaseId))throw new Error('등록 대상과 일치하는 실행 가능한 시험을 선택하세요.');
      if(page==='prepare'){if(!state.run || state.settled){state.run=null;state.events=[];state.selected=null;state.settled=false;}go('live');return;}
      if(state.pendingStart)return;
      let body=startPayload(state.catalog,state.draft);
      state.pendingStart=true;account();guidance();
      try {
        const token=state.session.access_token;
        if(body.system_id && state.designCaseId && state.designPlan){
          body={plan_id:state.designPlan.plan_id,case_id:state.designCaseId,system_id:body.system_id};
        } else if(body.system_id && state.trialData.enabled){
          const reference=await api('/qa/target',{token});
          const prepared=preparedPurchaseSample(reference,state.trialData);
          if(state.knowledge?.target_type==='PURCHASE'){prepared.knowledge_query=state.knowledge.query;prepared.knowledge_target_type='PURCHASE';}
          const plan=await api('/qa/plans',{token,body:prepared});
          const selected=plan.cases.find(c=>c.execution.registered_test_id===body.test_id && c.execution.status==='READY');
          if(!selected)throw new Error('이 데이터로 실행할 수 없는 시험입니다. 조건을 다시 확인하세요.');
          body={plan_id:plan.plan_id,case_id:selected.case_id,system_id:body.system_id};
        }
        const result=await api('/runs',{token,body});
        if(!host || !state.session){state.pendingRunId=result.run_id;return;}
        notify(`${result.run_id} 실행이 접수됐습니다. 아래에서 진행 상태를 확인하세요.`);await openRun(result.run_id);
        if(['live','execution'].includes(page))$('[data-live-guidance]')?.scrollIntoView({block:'start'});
      } finally {state.pendingStart=false;if(host){account();guidance();}}
    } else if(form.matches('[data-live-approval-form]')) {
      const run=state.run, decision=button.value;
      const approver=await api('/auth/login',{body:values});form.password.value='';
      await api(`${run.manifest?.state_store?"/qa":""}/runs/${encodeURIComponent(run.run_id)}/approval`,{token:approver.access_token,body:{approval_request_id:run.approval_request.approval_request_id,payload_hash:run.approval_request.payload_hash,decision}});
      notify(decision==='APPROVED'?'승인했습니다. 실행 결과를 기다려 주세요.':'거절했습니다. 실행 결과를 기다려 주세요.');
      await poll();
    } else if(form.matches('[data-live-compare]')) {
      state.comparison=null;$('[data-live-comparison]').innerHTML='';
      const result=await api(`/comparisons?${new URLSearchParams(values)}`,{token:state.session?.access_token});
      if(current===generation && host){state.comparison=result;state.compareDraft=values;$('[data-live-comparison]').innerHTML=comparisonView(result);actionHint();}
    }
  } catch(error) { if(host)failure(error); }
  finally {buttons.forEach(b=>b.disabled=false);if(host){renderRegistrations();account();renderBatch();}}
}
function click(event) {
  const target=event.target.closest('button');if(!target)return;
  if(target.hasAttribute('data-live-logout')) {state.registration=null;state.registrations=[];state.capabilityOptions=[];state.batch=null;state.batchRequest=null;state.designPlan=null;state.designCaseId=null;state.targetTypes=[];state.session=null;state.catalog=null;state.run=null;state.events=[];state.runs=[];state.comparison=null;state.compareDraft={left:'',right:''};state.pendingRunId=null;const element=host;leaveLive();mountLive(element,page,go);notify('로그아웃했습니다.');}
  if(target.hasAttribute('data-qa-parse')){
    try{renderToolBindings($('[data-qa-registration]'),state.capabilityOptions);notify('도구별 조회·변경과 업무 기능 연결을 확인하세요.');}catch(error){failure(error);}
  }
  if(target.hasAttribute('data-qa-example')){
    if(!state.session){notify('로그인 후 예시를 불러오세요.',true);return;}
    api(`/qa/target?target_type=${encodeURIComponent($('[data-qa-registration]').elements.agent_type.value)}`,{token:state.session.access_token}).then(example=>{
      const data=exampleDeclaration(example);fillDeclaration($('[data-qa-registration]'),data);
      renderToolBindings($('[data-qa-registration]'),state.capabilityOptions,data);
      notify('선택한 업무 예시를 새 등록용으로 채웠습니다. 기능 확인 수준은 등록자 설명으로 기록합니다.');
    }).catch(failure);
  }
  if(target.hasAttribute('data-qa-profile')){
    state.registration=state.registrations.find(p=>p.profile_id===target.dataset.qaProfile);
    state.designPlan=null;state.designCaseId=null;state.batchRequest=null;targets();renderDesign();renderBatch();
  }
  if(target.hasAttribute('data-qa-edit') && state.registration){
    fillDeclaration($('[data-qa-registration]'),state.registration.input);
    renderToolBindings($('[data-qa-registration]'),state.capabilityOptions,state.registration.input);
    $('[data-qa-editor]').open=true;$('[data-qa-editor]').scrollIntoView({block:'start'});
  }
  if(target.hasAttribute('data-qa-plan'))go('prepare');
  if(target.hasAttribute('data-live-follow-up')) {
    target.disabled=true;
    api(`/qa/runs/${encodeURIComponent(state.run.run_id)}/follow-up`,{token:state.session.access_token,body:{}})
      .then(b=>{state.batch=b;renderBatch();pollBatch();notify('추가 실험을 연결했습니다. 각 실행의 승인 요청을 확인하세요.');})
      .catch(failure).finally(()=>{target.disabled=false;});
  }
  if(target.hasAttribute('data-live-stop-batch'))api(`/qa/batches/${encodeURIComponent(state.batch.batch_id)}/stop`,{token:state.session.access_token,body:{}}).then(b=>{state.batch=b;renderBatch();pollBatch();}).catch(failure);
  if(target.hasAttribute('data-live-clear-design')){state.designCaseId=null;account();}
  if(target.hasAttribute('data-live-use-design')){
    const selected=state.designPlan?.cases.find(c=>c.case_id===target.dataset.liveUseDesign);
    if(selected?.execution.status==='READY'){
      if(!state.run || state.settled){state.run=null;state.events=[];state.selected=null;state.settled=false;}
      state.designCaseId=selected.case_id;
      state.draft={...state.draft,agent:'purchase',test_id:selected.execution.registered_test_id};catalog();
      notify(`설계 시험을 선택했습니다. 저장한 업무 입력으로 실행합니다.`);go('live');
    }
  }
  if(target.hasAttribute('data-live-run')){stopReplay();if(!['live','execution'].includes(page))go('execution');openRun(target.dataset.liveRun).catch(failure);}
  if(target.hasAttribute('data-live-refresh')) {if(state.session)refresh().catch(failure);else notify('먼저 로그인해 주세요.',true);}
  if(target.hasAttribute('data-live-event')) {stopReplay();state.selected=Number(target.dataset.liveEvent);renderEvents();}
  if(target.hasAttribute('data-live-show-approval')){$('[data-live-approval]').scrollIntoView({block:'start'});$('[data-live-approval-form] input')?.focus({preventScroll:true});}
  if(target.hasAttribute('data-live-show-results')){$('[data-live-result]').tabIndex=-1;$('[data-live-result]').focus({preventScroll:true});$('[data-live-result]').scrollIntoView({block:'start'});}
  if(target.hasAttribute('data-live-go'))go(target.dataset.liveGo);
  if(target.hasAttribute('data-live-target-type'))selectTargetType(target.dataset.liveTargetType);
  if(target.hasAttribute('data-live-agent')){state.draft=normalizeDraft(state.catalog,{...state.draft,agent:target.dataset.liveAgent,test_id:''});catalog();}
  if(target.hasAttribute('data-live-play'))toggleReplay();
  if(target.hasAttribute('data-live-export'))exportRun();
  if(target.hasAttribute('data-live-qa-report') && state.run?.qa_report && state.settled){
    const content=qaReportDocument(state.run.qa_report,state.events);
    const url=URL.createObjectURL(new Blob([content],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`${state.run.run_id}-qa-report.html`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  if(target.hasAttribute('data-live-qa-summary'))exportQaSummary(target).catch(failure);
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


async function exportQaSummary(button) {
  if(!state.session)return;
  const current=generation,token=state.session.access_token;
  button.disabled=true;notify('최근 완료 시험을 모으고 있습니다…');
  try {
    const recent=await api('/runs?limit=50',{token});
    const selected=completedSystemRuns(state.catalog,recent.runs).slice(0,20);
    const reports=[];
    for(let i=0;i<selected.length;i+=4){
      const runs=await Promise.all(selected.slice(i,i+4).map(r=>api(`/runs/${encodeURIComponent(r.run_id)}`,{token})));
      for(const run of runs)if(run.qa_report && ['PURCHASE','PRODUCTION','QUALITY'].includes(run.qa_report.target.type))reports.push(run.qa_report);
    }
    if(current!==generation || state.session?.access_token!==token)return;
    if(!reports.length)throw new Error('요약할 완료 시험이 없습니다.');
    const url=URL.createObjectURL(new Blob([qaReportCollectionDocument(reports)],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='manufacturing-qa-summary.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    notify(`완료 시험 ${reports.length}개의 요약을 저장했습니다.`);
  } finally {if(button.isConnected)button.disabled=false;}
}
