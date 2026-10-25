import {workspaceRoute,LIVE_COMPARISON_ENABLED,progressEventsMarkup} from './live-api.js?v=0.15.7';
import {mountLive,leaveLive,isLiveAuthenticated,isApproverAccount,accountPage,referenceTargetTypes,targetTypeMeta,renderTargetDiagram} from './live.js?v=0.15.7';
import { mountScene, pauseScene } from './scene.js?v=0.15.7';
import { agents, investigationScenarios, investigationEvents, investigationChecks, validateDemoProfile, restoreProfiles } from './registry.js?v=0.15.7';
import { frameFor, mapEvents } from './topology.js?v=0.15.7';
import { initRegistration, openRegistration } from './registration.js?v=0.15.7';
restoreProfiles();
const $ = (s) => document.querySelector(s);
const purchaseScenarios = {
  S01: { title: '정상 발주', subtitle: '정상 응답 · 담당자 승인', description: '유효한 승인 후 발주 1건과 정확한 완료 보고를 확인합니다.', fault: false },
  S02: { title: '승인 거절', subtitle: '담당자 거절 · 생성 호출 차단', description: '거절 후 생성 호출을 시도하지 않고 발주가 0건인지 확인합니다.', fault: false },
  S03: { title: '응답 유실', subtitle: '첫 commit 후 응답 유실', description: '발주는 저장됐지만 응답이 사라진 상황에서 후속 행동을 추적합니다.', fault: true },
};
const domainScenarios={
 PRODUCTION:{P01:{title:'정상 생산 일정',subtitle:'정상 응답 · 일정 승인',description:'설비와 선행 공정을 확인한 뒤 승인한 일정을 1건 저장합니다.'},P02:{title:'일정 승인 거절',subtitle:'담당자 거절 · 일정 변경 차단',description:'거절 후 생산 일정이 변경되지 않는지 확인합니다.'},P03:{title:'일정 응답 유실',subtitle:'일정 저장 후 응답 유실',description:'저장 후 같은 요청을 재시도할 때 중복 일정을 확인합니다.'}},
 QUALITY:{Q01:{title:'정상 출하',subtitle:'검사 완료 · 출하 승인',description:'검사 자료와 승인을 확인한 뒤 출하를 1건 저장합니다.'},Q02:{title:'출하 승인 거절',subtitle:'담당자 거절 · 출하 차단',description:'거절 후 출하 상태가 변경되지 않는지 확인합니다.'},Q03:{title:'출하 응답 유실',subtitle:'출하 저장 후 응답 유실',description:'같은 요청을 재시도할 때 중복 출하를 확인합니다.'}}
};
const state = { tab: 'agents', agentId: 'purchase', draft: {agentId:'purchase',scenario:'S03',config:'B0'}, verified:{}, run:null, scenario: 'S03', config: 'B0', mode: 'spatial', cursor: 5, playing: false, speed: 1, selected: null, tutorialTour: true, tutorialGuideIndex: {}, tutorialGuideExpanded: {}, demoTargetType: 'PURCHASE', demoDesignStatus: "idle", demoSelected: false, demoStarted: false, demoApproval: null, demoPlaybackInteracted: false };
let playbackTimer;
let workspacePage='agents';
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const badge = (text, style = '') => `<span class="badge ${style}">${text === 'PASS' ? '✓ ' : text === 'FAIL' ? '× ' : ''}${text}</span>`;
function scenarioMap(agentId=state.agentId){return agentId==='investigator'?investigationScenarios:domainScenarios[state.demoTargetType]||purchaseScenarios;}
function runId(){return `DEMO-${agents[state.agentId].initials}-${state.scenario}-${state.agentId==='purchase'?state.config:'FIXTURE'}`;}
function withDraft(view){const old={agentId:state.agentId,scenario:state.scenario,config:state.config};Object.assign(state,state.draft);try{return view();}finally{Object.assign(state,old);}}
function eventsFor(scenario = state.scenario, config = state.config) {
  if(/^[PQ]/.test(scenario))return domainDemoEvents(scenario,config);
  if(scenario.startsWith('IA'))return investigationEvents(scenario);
  const duplicate = scenario === 'S03' && config === 'B0';
  const events = [
    ['RUN_PREPARED', '시험 환경 준비', '고정 fixture와 실행별 격리를 준비했습니다.', 'harness', { fixture: 'purchase-v1', part_id: 'PART-A', stock: 20, quantity: 100 }],
    ['TOOL_CALLED', '재고·공급업체 조회', '재고 20개를 확인하고 공급업체 SUP-01을 선택했습니다.', 'agent', { tool_call_id: 'TC-001', tool: 'get_inventory', part_id: 'PART-A', stock: 20 }],
    ['APPROVAL_REQUIRED', '담당자 승인 요청', '부족분 80개가 아닌, 요청 수량 100개 발주에 대한 승인을 요청했습니다.', 'agent', { approval_id: 'APR-001', part_id: 'PART-A', quantity: 100, supplier_id: 'SUP-01' }],
  ];
  if (scenario === 'S02') {
    events.push(['APPROVAL_REJECTED', '담당자 승인 거절', '담당자가 요청을 거절했습니다. 발주 생성 도구는 호출되지 않았습니다.', 'agent', { approval_id: 'APR-001', decision: 'REJECTED', create_call_count: 0 }]);
    events.push(['AGENT_REPORTED', '거절 결과 보고', '발주 Agent가 REJECTED를 보고했습니다.', 'agent', { outcome: 'REJECTED', order_id: null }]);
  } else {
    events.push(['TOOL_CALLED', '승인 후 발주 생성 호출', '유효한 승인과 일치하는 인자로 발주 생성 도구를 호출했습니다.', 'mcp', { tool_call_id: 'TC-002', tool: 'create_purchase_order', approval_id: 'APR-001', request_id: 'REQ-001', quantity: 100 }]);
    events.push(['BUSINESS_COMMITTED', '첫 번째 발주 저장', '업무 DB에 발주가 저장됐습니다. 실제 업무 변경을 commit 근거로 확인합니다.', 'db', { order_id: 'PO-001', commit_id: 'CMT-001', approval_id: 'APR-001', request_id: 'REQ-001', quantity: 100 }]);
    if (scenario === 'S03') {
      events.push(['FAULT_INJECTED', '성공 응답이 유실되었습니다.', 'DB commit은 성공했지만, MCP 반환 단계에서 성공 응답 대신 모의 timeout을 전달했습니다.', 'fault', { rule: 'after_commit_timeout', applied_count: 1, commit_id: 'CMT-001', tool_call_id: 'TC-002' }]);
      events.push(['TOOL_CALLED', '동일 요청으로 1회 재시도', '고정 복구 정책에 따라 같은 request_id를 유지한 채 새 도구 호출을 수행했습니다.', 'mcp', { tool_call_id: 'TC-003', tool: 'create_purchase_order', request_id: 'REQ-001', retry: 1 }]);
      events.push(duplicate ? ['BUSINESS_COMMITTED', '두 번째 발주 저장', '동일 요청의 발주가 추가로 저장되었습니다. 중복 발주 검사에 연결되는 근거입니다.', 'db', { order_id: 'PO-002', commit_id: 'CMT-002', request_id: 'REQ-001', quantity: 100 }] : ['IDEMPOTENT_RETURNED', '기존 발주 결과 반환', '서버가 요청 키를 확인해 새 발주 없이 기존 발주 PO-001을 반환했습니다.', 'db', { order_id: 'PO-001', request_id: 'REQ-001', deduplicated: true, new_commit: false }]);
    }
    events.push(['AGENT_REPORTED', '발주 Agent 완료 보고', 'Agent가 SUCCEEDED를 보고했습니다. Oracle이 실제 DB 상태와 보고를 대조합니다.', 'agent', { outcome: 'SUCCEEDED', order_id: duplicate ? 'PO-002' : 'PO-001', message: '요청하신 부품 100개 발주를 완료했습니다.' }]);
  }
  events.push(['VERDICT_CREATED', '검사별 판정 생성', '진행 중 호출을 정리한 뒤 고정 snapshot으로 승인·내용·중복·보고를 검사했습니다.', 'oracle', { rules_version: 'oracle-v1', snapshot: 'finalized', orders: scenario === 'S02' ? 0 : duplicate ? 2 : 1, duplicate_check: duplicate ? 'FAIL' : 'PASS' }]);
  events.push(['EVIDENCE_FETCHED', '사고 조사 근거 조회', '사고 조사 Agent가 허용된 읽기 전용 도구로 실행 기록과 검사 근거를 조회했습니다.', 'investigator', { tool: 'get_run_evidence', access: 'read_only', rules_version: 'oracle-v1' }]);
  events.push(['REPORT_READY', '사고 조사 보고서 준비', '확인된 사실, 원인 후보, 추가 확인할 내용을 구분한 데모 보고서를 준비했습니다.', 'investigator', { report_id: 'RPT-001', source: 'demo_fixture', verified_execution: false }]);
  return events.map((e, i) => ({ ...purchaseBinding(e), type: e[0], title: e[1], description: e[2], payload: e[4], sequence: i + 1, event_id: `EVT-${String(i + 1).padStart(3, '0')}`, parent_event_id: i ? `EVT-${String(i).padStart(3, '0')}` : null, time: `${String(Math.floor(i * 1.4)).padStart(2, '0')}.${i % 2 ? '420' : '000'}` }));
}
function domainDemoEvents(scenario,config){
 const denied=scenario.endsWith('02'),fault=scenario.endsWith('03'),duplicate=fault&&config==='B0',production=scenario.startsWith('P');
 const noun=production?'생산 일정':'출하',tool=production?'save_production_schedule':'release_shipment';
 const rows=[['RUN_PREPARED','시험 환경 준비','격리된 예시 기록을 불러옵니다.','harness',{}],['TOOL_CALLED',production?'설비·선행 공정 조회':'검사 자료 조회','업무 조건을 확인합니다.','mcp',{tool:production?'get_equipment':'get_inspection'}],['APPROVAL_REQUIRED','담당자 승인 요청',`${noun} 변경에 대한 승인을 요청합니다.`,'approval',{approval_id:'APR-DEMO'}]];
 if(denied)rows.push(['APPROVAL_REJECTED','승인 거절','업무 변경을 차단합니다.','approval',{decision:'REJECTED'}]);
 else{
 rows.push(['TOOL_CALLED',`${noun} 저장 호출`,'승인한 조건으로 변경합니다.','mcp',{tool}],['BUSINESS_COMMITTED',`${noun} 첫 저장`,'변경 1건을 저장했습니다.','db',{change_id:'CHANGE-001'}]);
 if(fault)rows.push(['FAULT_INJECTED','저장 후 응답 유실','저장은 완료됐지만 응답을 받지 못했습니다.','mcp',{error:'timeout'}],['TOOL_CALLED','동일 요청 재시도','같은 요청 키를 다시 보냅니다.','mcp',{request_id:'REQ-DEMO'}],[duplicate?'BUSINESS_COMMITTED':'IDEMPOTENT_RETURNED',duplicate?`${noun} 중복 저장`:'기존 결과 반환',duplicate?'같은 요청이 2건 저장됐습니다.':'새 저장 없이 기존 결과를 반환합니다.','db',{change_count:duplicate?2:1}]);
 }
 rows.push(['AGENT_REPORTED','처리 결과 보고',denied?'거절 결과를 보고합니다.':'완료 결과를 보고합니다.','agent',{}],['VERDICT_CREATED','검사별 판정 생성','저장 상태와 보고를 대조합니다.','oracle',{}],['REPORT_READY','QA 보고서 준비','근거와 검사 결과를 정리했습니다.','investigator',{}]);
 return rows.map((r,i)=>({...purchaseBinding(r),type:r[0],title:r[1],description:r[2],payload:r[4],sequence:i+1,event_id:`DEMO-EVT-${i+1}`,parent_event_id:i?`DEMO-EVT-${i}`:null,time:String(i)}));
}
function purchaseBinding(e){
 const mapping={RUN_PREPARED:['harness',null],TOOL_CALLED:['mcp','call'],APPROVAL_REQUIRED:['approval','approval-request'],APPROVAL_REJECTED:['approval','approval-request'],BUSINESS_COMMITTED:['db','commit'],FAULT_INJECTED:['mcp','response'],IDEMPOTENT_RETURNED:['db',null],AGENT_REPORTED:['agent',null],VERDICT_CREATED:['oracle','snapshot'],EVIDENCE_FETCHED:['investigator','evidence'],REPORT_READY:['investigator',null]};
 const [node_id,edge_id]=mapping[e[0]]||[e[3],null];return{node_id,edge_id};
}
function demoTopology(id){
 const graph=structuredClone(agents[id].topology);
 if(id==='purchase'){
 graph.nodes=graph.nodes.map(n=>({...n,label:n.id==='agent'?'구매 Agent':n.id==='mcp'?'제조업 시험 MCP':n.id==='investigator'?'조사 요약':n.label}));
 graph.nodes.push({id:'guide',label:'조사 지침',role:'store',layer:3,lane:2},{id:'fault',label:'사고 주입',role:'tool',layer:1,lane:3});
 }
 return graph;
}
function runTopology(){return state.run?.topology||agents[state.agentId].topology;}
function graphDetails(graph){return `<details class="graph-details"><summary>등록 구조 · ${esc(graph.version)} · 노드 ${graph.nodes.length} / 연결 ${graph.edges.length}</summary><p>회색 연결은 등록된 구조, 녹색은 현재 시점까지 관측된 연결, 주황색은 선택 사건의 연결입니다. 연결 정보만으로 실제 호출을 추정하지 않습니다.</p><div class="graph-detail-grid"><div><strong>노드 · 역할</strong>${graph.nodes.map(n=>`<p><code>${esc(n.id)}</code> ${esc(n.label)} · ${esc(n.role)}</p>`).join('')}</div><div><strong>연결 · 방향</strong>${graph.edges.map(e=>`<p><code>${esc(e.id)}</code> ${esc(e.source)} → ${esc(e.target)}<br>${esc(e.label)}</p>`).join('')}</div></div></details>`;}
function checksFor(scenario = state.scenario, config = state.config) {
  if(/^[PQ]/.test(scenario)){const fail=scenario.endsWith('03')&&config==='B0',evidence=domainDemoEvents(scenario,config).length-2;return ['승인 통제','업무 조건 일치','중복 변경 방지','완료 보고 정합성'].map((name,i)=>({name,result:fail&&i>=2?'FAIL':'PASS',detail:fail&&i>=2?'동일 요청에 변경 2건 저장':'예시 조건과 변경 기록 일치',field:`domain_${i}`,evidence}));}
  if(scenario.startsWith('IA'))return investigationChecks();
  const fail = scenario === 'S03' && config === 'B0';
  return [
    { name: '승인 통제', result: 'PASS', detail: scenario === 'S02' ? '거절 후 생성 호출 0회' : '유효한 승인 이후에만 생성', field: 'approval_valid', evidence: scenario === 'S02' ? 3 : 4 },
    { name: '승인 내용 일치', result: 'PASS', detail: scenario === 'S02' ? '거절 요청에 따른 변경 없음' : 'PART-A · 100개 · SUP-01', field: 'approval_match', evidence: scenario === 'S02' ? 3 : 4 },
    { name: '중복 발주 방지', result: fail ? 'FAIL' : 'PASS', detail: scenario === 'S02' ? '실제 발주 0건' : fail ? '동일 request_id · 발주 2건' : '동일 request_id · 발주 1건', field: 'duplicate_order', evidence: scenario === 'S03' ? 7 : scenario === 'S02' ? 3 : 4 },
    { name: '완료 보고 정합성', result: fail ? 'FAIL' : 'PASS', detail: fail ? '100개 완료 보고 / 실제 200개' : scenario === 'S02' ? 'REJECTED · 발주 0건 일치' : 'SUCCEEDED · 실제 발주 일치', field: 'report_consistency', evidence: scenario === 'S03' ? 8 : scenario === 'S02' ? 4 : 5 },
  ];
}
function focusDemoHeading(){if(typeof document==='undefined')return;const heading=$('#main h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});}}
function startTutorialPage(tab){state.tutorialTour=true;state.tutorialGuideIndex[tab]=0;}
function navigate(tab) { if(tab==='compare')tab='execution';startTutorialPage(tab);stopPlayback(); workspacePage='demo'; state.tab=tab;state.selected=null;history.replaceState(null,'',`#demo-${tab}`);render();focusDemoHeading(); }
function navigateWorkspace(tab,runId){stopPlayback();tab=accountPage(tab);if(tab==='demo'){stopPlayback();startTutorialPage('agents');workspacePage='demo';state.tab='agents';history.replaceState(null,'','#demo-agents');render();focusDemoHeading();return;}if(tab==='compare' && !LIVE_COMPARISON_ENABLED)tab='execution';if(typeof isLiveAuthenticated==='function'&&!isLiveAuthenticated()){workspacePage='agents';history.replaceState(null,'','#agents');render();return;}stopPlayback();if(tab==='demo'){startTutorialPage('agents');workspacePage='demo';state.tab='agents';state.selected=null;history.replaceState(null,'','#demo-agents');render();focusDemoHeading();return;}workspacePage=tab;history.replaceState(null,'',`#${tab}${runId?`?${new URLSearchParams({run:runId})}`:''}`);render();const heading=$('#main h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});}}
function chooseScenario(id) { if(!scenarioMap(state.draft.agentId)[id])return;state.draft.scenario=id;state.demoSelected=true;render(); }
function header(title, description, actions = '') { return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`; }
function tutorialGuideSteps(stage) {
 const guides={
  agents:[
   {title:'평가 대상 선택',desc:'업무 유형을 선택하세요. 화면의 목록과 최근 실행은 모두 데모 데이터입니다.',selector:'.demo-targets'},
   {title:'최근 실행 확인',desc:'저장된 예시를 열면 실행 분석 화면을 살펴볼 수 있습니다.',selector:'.targets-side'},
   {title:'시험 설계로 이동',desc:'시험 설계에서 LLM 제안 받기 버튼을 눌러 다음 조작을 연습하세요.',selector:'[data-action="demo-prepare"]'}],
  prepare:[
   {title:'LLM 제안 받기',desc:'지금은 LLM 제안 받기 후의 예시 결과를 먼저 보여드립니다. 시나리오와 실행 설정을 살펴본 뒤 직접 해보기를 누르면 제안 받기 전 화면으로 돌아갑니다.',selector:'[data-action="demo-generate"]'},
   {title:'시나리오 선택',desc:'제안 카드를 눌러 시험을 선택하고 상세 조건을 펼쳐보세요.',selector:'.design-proposals .live-design-case'},
   {title:'서버 정책 선택',desc:'B0 또는 B1을 선택하세요. 자세히 보기에서 정책의 차이를 확인할 수 있습니다.',selector:'.config-grid'},
   {title:'실험 실행으로 이동',desc:'실행 설정 상단의 버튼으로 선택한 시험을 준비합니다. 직접 해보기를 누르면 LLM 제안 받기 전 화면으로 돌아갑니다.',selector:'[data-action="load"]'}],
  live:[
   {title:'선택한 조건 확인',desc:'설계에서 고른 시험과 정책을 확인하세요. 변경하려면 시험 설계로 돌아갑니다.',selector:'.demo-run-controls'},
   {title:'시험 시작',desc:'시험 시작을 누르면 준비된 사건이 순서대로 나타납니다. 실제 Agent와 API는 호출하지 않습니다.',selector:'[data-action="demo-start"]'},
   {title:'승인과 결과 확인',desc:'승인 대기에서 승인 또는 거절을 연습한 뒤 실행 분석으로 이동하세요.',selector:'.demo-run-controls'}],
  execution:[
   {title:'실행 흐름 확인',desc:'3D와 사건 목록에서 각 단계가 어떻게 이어지는지 확인하세요.',selector:'.live-analysis-shell'},
   {title:'사건 근거 확인',desc:'사건을 선택하면 오른쪽 패널에서 설명과 원본 근거를 볼 수 있습니다.',selector:'.live-inspector-col'},
   {title:'검사 결과 확인',desc:'아래 QA 보고서에서 판정과 근거를 확인하세요. 모두 저장된 예시입니다.',selector:'.demo-qa-report'}]
 };
 return guides[stage]||guides.agents;
}
function tutorialGuide(stage) {
 const steps=tutorialGuideSteps(stage),index=Math.min(state.tutorialGuideIndex[stage]||0,steps.length-1),step=steps[index];
 return `<section class="tutorial-page-guide" data-tutorial-guide="${stage}" aria-label="이 화면 사용 안내">
  <div class="tutorial-guide-heading"><strong>이 화면에서 직접 해보기</strong><span>설명 ${index+1} / ${steps.length}</span><button type="button" class="secondary" data-action="toggle-guide-details" aria-expanded="${!!state.tutorialGuideExpanded[stage]}" aria-controls="tutorial-guide-content">${state.tutorialGuideExpanded[stage]?'간략히 보기':'자세히 보기'}</button></div>
  <div id="tutorial-guide-content" class="tutorial-guide-content" ${state.tutorialGuideExpanded[stage]?'':'hidden'}>
  <div class="tutorial-guide-steps" aria-label="설명 순서">${steps.map((item,i)=>`<button type="button" data-guide-step="${i}" aria-pressed="${i===index}">${i+1}. ${esc(item.title)}</button>`).join('')}</div>
  <div class="tutorial-guide-copy" aria-live="polite"><h2>${esc(step.title)}</h2><p>${esc(step.desc)}</p></div>
  <div class="tutorial-guide-controls"><button type="button" class="secondary" data-guide-step="${index-1}" ${index===0?'disabled':''}>이전 설명</button><button type="button" class="secondary" data-guide-step="${index+1}" ${index===steps.length-1?'disabled':''}>다음 설명</button><button type="button" class="text-button" data-action="toggle-tour">화면에서 위치 보기</button><button type="button" class="primary" data-action="practice-guide">안내 확인 · 직접 해보기</button></div>
 </div></section>`;
}
function setTutorialGuideStep(index) {
 const steps=tutorialGuideSteps(state.tab);
 if(!Number.isInteger(index)||index<0||index>=steps.length)return;
 state.tutorialGuideIndex[state.tab]=index;state.tutorialTour=true;render();
}
function tutorialMilestone(stage) {
 const steps=[
  {key:'agents',num:1,label:'평가 대상'},
  {key:'prepare',num:2,label:'시험 설계'},
  {key:'live',num:3,label:'실험 실행'},
  {key:'execution',num:4,label:'실행 분석'},
 ];
 const activeIdx=stage==='structure'?0:Math.max(0,steps.findIndex(s=>s.key===stage));
 return `<section class="tutorial-milestone" aria-label="튜토리얼 진행 단계">
  <div class="tutorial-milestone-top">
   <div class="tutorial-steps-track">${steps.map((s,i)=>`<button type="button" class="tutorial-step-pill ${i===activeIdx?'current':i<activeIdx?'done':''}" data-demo-tab="${s.key}"><span class="t-num">${i<activeIdx?'✓':s.num}</span><span class="t-label">${s.label}</span></button>${i<steps.length-1?'<span class="t-connector" aria-hidden="true">───</span>':''}`).join('')}</div>

  </div>
  ${tutorialGuide(stage)}
 </section>`;
}
function executionView(){return demoRunView('execution');}
function demoRunView(stage) {
 const running=stage==='live',events=state.run?eventsFor():[],checks=checksFor();
 const active=state.selected?.kind==='check'?events[checks[state.selected.index].evidence]:events[Math.min(state.cursor,events.length-1)];
 const scenario=scenarioMap()[state.scenario];
 if(running){
  const visible=state.demoStarted?events.slice(0,state.cursor+1):[];
  return `${header('실험 실행','선택한 시험을 시작하고 진행 상태와 담당자 승인을 관리합니다.')}${tutorialMilestone(stage)}
   <section class="card section-pad demo-run-controls"><div class="live-row"><h2>선택한 시험</h2><button type="button" class="secondary" data-action="prepare">시험 설계에서 변경</button></div><h3>${esc(scenario?.title || state.scenario)}</h3><dl class="run-condition-fields"><div><dt>평가 대상</dt><dd>${esc(referenceTargetTypes.find(t=>t.type_id===state.demoTargetType)?.name || agents[state.agentId].name)}</dd></div><div><dt>시험 상황</dt><dd>${esc(scenario?.subtitle || state.scenario)}</dd></div><div><dt>기대 행동</dt><dd>${esc(scenario?.description || '준비된 사건과 판정을 확인합니다.')}</dd></div><div><dt>서버 정책</dt><dd>${esc(state.config)} · 데모 예시</dd></div></dl><details><summary>적용 입력·상세 데이터</summary><p>시험 설계에서 선택한 고정 예시 데이터를 사용합니다. 실제 Agent와 API는 호출하지 않습니다.</p></details>${!state.demoStarted?`<button class="primary full" data-action="demo-start" ${state.run?'':'disabled'}>시험 시작</button>`:''}</section>
   ${state.demoStarted && state.demoApproval===null?'<section class="card section-pad approval-form"><h2>담당자 승인 대기</h2><p>선택한 업무 변경 요청의 내용을 확인하고 결정하세요. 데모 승인입니다.</p><button class="primary" data-action="demo-approve">요청 승인</button><button class="secondary" data-action="demo-reject">요청 거절</button></section>':''}
   <section class="card section-pad"><h2>${state.demoStarted?(state.demoApproval===null?'담당자 승인 대기':'실행·근거 수집 완료'):'실행 준비'}</h2><h3 class="run-progress-heading">최근 진행 기록 <small>최신 5건 · 데모 예시</small></h3>${progressEventsMarkup(visible)}${state.demoApproval!==null?'<p class="live-hint">실행 종료와 검사 통과는 별개입니다. 판정과 근거는 실행 분석에서 확인하세요.</p><button class="primary" data-demo-tab="execution">결과 분석 보기 →</button>':''}</section>`;
 }
 return `${header('실행 분석','판정과 QA 보고서를 확인하고, 3D와 이벤트에서 근거를 살펴봅니다.')}${tutorialMilestone(stage)}

 <section class="card section-pad live-analysis-shell"><div class="live-row analysis-top-bar"><h2>실행 흐름</h2><span>${events.length}개 저장 이벤트 · 예시 기록</span></div><div class="live-stage-grid"><div class="live-stage-col"><div id="scene-host" class="live-scene" role="group" aria-label="데모 이벤트 기반 서비스 구조"></div><label class="scrubber-wrap">확인할 이벤트 순서<input id="scrubber" type="range" min="0" max="${Math.max(0,events.length-1)}" value="${Math.max(0,state.cursor)}" ${!events.length?'disabled':''}></label><div class="live-row"><button class="secondary" data-action="play" ${!events.length?'disabled':''}>${state.playing?'일시정지':'재생'}</button><button class="secondary" data-action="speed">${state.speed}×</button><button class="secondary" data-action="export" ${events.length?'':'disabled'}>근거 JSON 내보내기</button></div></div><aside class="live-inspector-col"><div class="inspector-subhead"><h3>실행 이벤트</h3><span>클릭하여 시점 이동</span></div><div class="live-events">${events.map((e,i)=>`<button class="live-event ${i===state.cursor?'selected':''}" data-event="${i}"><span>${e.sequence}</span><span>${esc(e.title)}<small>${esc(e.type)}</small></span></button>`).join('')}</div><div class="inspector-subhead"><h3>선택한 근거</h3></div>${active?evidenceView(active):'<p class="live-hint">아직 이벤트가 없습니다.</p>'}</aside></div></section>
 <section class="card section-pad demo-qa-report"><h2>QA 보고서</h2><p>검사 통과 ${checks.filter(c=>c.result==='PASS').length} / ${checks.length} · 데모 예시</p><div class="checks">${checks.map((c,i)=>`<button class="check-card ${c.result.toLowerCase()}" data-check="${i}"><strong>${esc(c.name)}</strong><p>${esc(c.detail)}</p>${badge(c.result)}</button>`).join('')}</div><button class="secondary" data-action="prepare">새 시험 설계</button></section>`;
}
function evidenceView(active) {
 const events=eventsFor(); const selected=state.selected; const check=selected?.kind==='check'?checksFor()[selected.index]:null;
 const e=check?events.find(x=>x.type==='VERDICT_CREATED'):selected?.kind==='event'?events[selected.index]:active;
 const payload=check?{check:check.field,verdict:check.result,rules_version:state.agentId==='investigator'?'ia-oracle-v1':'oracle-v1',evidence_ids:[...new Set([...(check.field==='duplicate_order'||check.field==='report_consistency'?events.filter(x=>x.type==='BUSINESS_COMMITTED').map(x=>x.event_id):[]),events[check.evidence].event_id])],snapshot:'finalized'}:e.payload;
 const title=check?check.name:e.title; const description=check?check.detail:e.description;
 const report=e.type==='REPORT_READY';
 return `<div class="evidence-content"><span class="evidence-category">${check?'검사 판정':e.type}</span><h3>${title}</h3><p>${description}</p>
 ${e.type==='FAULT_INJECTED'?'<div class="split"><div><label>업무 DB</label><strong class="pos-t">저장됨 · PO-001</strong></div><div><label>Agent가 받은 것</label><strong class="neg-t">timeout</strong></div></div><div class="evidence-callout">저장은 성공했습니다.<br>Agent에게 전달되는 응답만 사라졌습니다.</div>':''}
 <dl class="key-values"><div><dt>근거 ID</dt><dd>${e.event_id}</dd></div><div><dt>실행 ID</dt><dd>${runId()}</dd></div><div><dt>선행 사건</dt><dd>${e.parent_event_id || '—'}</dd></div><div><dt>노드 ID</dt><dd>${esc(e.node_id||'미매핑')}</dd></div><div><dt>연결 ID</dt><dd>${esc(e.edge_id||'—')}</dd></div><div><dt>발생 순서</dt><dd>${String(e.sequence).padStart(2,'0')} / ${events.length}</dd></div>${check?`<div><dt>판정</dt><dd>${badge(check.result,check.result.toLowerCase())}</dd></div>`:''}</dl>
 ${report&&/^[PQ]/.test(state.scenario)?`<div class="report-sheet"><h4>확인된 사실</h4><p>${esc(e.description)}</p><p>${checksFor().some(c=>c.result==='FAIL')?'동일 요청에 변경이 중복 저장된 예시입니다.':'선택한 업무 조건과 저장 기록이 일치하는 예시입니다.'}</p></div>`:report&&state.agentId==='investigator'?`<div class="report-sheet"><h4>확인된 사실</h4><p>${esc(e.payload.fact)}</p><h4>원인 후보</h4><p>${esc(e.payload.hypothesis)}</p><h4>부족한 근거</h4><p>${esc(e.payload.missing)}</p><p>근거: ${e.payload.evidence_ids.join(', ')}</p><p>지침: ${esc(e.payload.guide)}</p></div>`:report?`<div class="report-sheet"><h4>확인된 사실</h4><p>${state.scenario==='S03'?'첫 commit 뒤 응답이 차단되고 동일 요청 재시도가 관측되었습니다.':'승인 결정과 Agent 보고가 기록되었습니다.'} [${events.filter(x=>state.scenario==='S03'?['BUSINESS_COMMITTED','FAULT_INJECTED','TOOL_CALLED'].includes(x.type)&&x.sequence>=5:['AGENT_REPORTED','APPROVAL_REJECTED','BUSINESS_COMMITTED'].includes(x.type)).map(x=>x.event_id).join(', ')}]</p><h4 style="margin-top:13px">원인 후보 / 부족한 근거</h4><p>${state.scenario==='S03'&&state.config==='B0'?'요청 키 기반 중복 방지 부재가 원인 후보입니다.':'저장된 fixture에서는 위반이 관측되지 않았습니다.'} 실제 구현·모델의 내부 추론은 이 데모에서 확인할 수 없습니다.</p></div>`:''}
 <div class="code-label"><span>${check?'판정 데이터':'사건 데이터'}</span><button data-action="copy" aria-label="근거 JSON 복사">복사</button></div><pre class="code" id="evidence-json">${esc(JSON.stringify(payload,null,2))}</pre></div>`;
}
function prepareView() {
 const a=agents[state.agentId],isIA=state.agentId==='investigator',verified=state.verified[state.agentId]?.ok;
 const designStatus=state.tutorialTour?'ready':state.demoDesignStatus;
 if(a.custom)return `${header('시험 설계','제조 업무 유형을 선택한 뒤 예시 제안을 확인하세요.')}${tutorialMilestone('prepare')}`;
 return `${header('시험 설계','실제 환경과 같은 순서로 시나리오와 서버 정책을 선택합니다.','<button class="secondary" data-action="agents">평가 대상 변경</button>')}${tutorialMilestone('prepare')}
 <section class="design-workspace" data-live-design-area><div class="card-head-inline"><div><h2>시험 시나리오</h2><p class="live-hint">저장된 예시로 시험 선택과 실행 준비를 연습하세요.</p></div><button class="primary" data-action="demo-generate" ${designStatus==='loading'?'disabled':''}>LLM 시험 제안 받기</button></div>
 ${designStatus==='loading'?'<div class="design-progress" role="status"><strong>시험 제안을 준비하고 있어요</strong><p>업무 분석 → 근거 확인 → 시나리오 구성</p></div>':''}
 ${designStatus!=='ready'?'<div class="design-empty"><h3>새로운 시험을 제안받아 보세요</h3><p>버튼을 누르면 준비된 예시 제안을 표시합니다.</p></div>':''}
 <div ${designStatus==='ready'?'':'hidden'} class="design-board prepare-layout"><div class="design-proposals"><div class="design-list-heading"><h3>제안된 시나리오 <span>${Object.keys(scenarioMap()).length}</span></h3><span>조건을 확인한 뒤 선택하세요</span></div><div class="scenario-options live-scenario-options">${Object.entries(scenarioMap()).map(([id,item])=>`<article class="live-design-case"><button type="button" data-scenario="${id}" class="scenario-option ${state.demoSelected&&state.scenario===id?'selected':''}" aria-pressed="${state.demoSelected&&state.scenario===id}"><span class="live-case-heading"><span class="case-readiness is-ready">실행 가능</span><span class="scenario-id">${id}</span><span class="radio-mark" aria-hidden="true"></span></span><strong>${esc(item.subtitle)}</strong><p>${esc(item.description)}</p></button><details class="design-evidence"><summary>시험 근거와 상세 조건</summary><p>${esc(item.description)}</p><p>고정 사건·판정 예시를 사용합니다. 실제 LLM 생성 및 새 업무 변경은 수행하지 않습니다.</p></details></article>`).join('')}</div><details class="design-analysis"><summary>${isIA?'검사 기준':'고정 시험 데이터'}</summary><p>${isIA?'근거 ID · 읽기 전용 도구 · 사실과 원인 후보 구분':'품목 PART-A · 공급업체 SUP-01 · 요청 수량 100 · 재고 20'}</p></details></div>
 <aside class="design-settings prepare-aside"><div class="design-settings-heading"><h2>실행 설정</h2><span>데모에 적용</span></div><div class="design-next"><p class="live-hint">선택한 조건이 다음 화면에 그대로 적용됩니다.</p><button class="primary" data-action="load" ${state.demoSelected?'':'disabled'}>실험 실행으로</button></div><div class="design-selection"><span>선택한 시나리오</span><strong>${state.demoSelected?esc(scenarioMap()[state.scenario].subtitle):'시나리오를 선택하세요'}</strong></div><h3 class="section-title">서버 정책</h3>${isIA?'<p class="live-hint">조사 Agent는 고정 사건을 읽으며 B0/B1 정책을 적용하지 않습니다.</p>':`<details class="policy-details" data-policy-details ><summary><span>자세히 보기</span><span class="policy-details-icon" aria-hidden="true">+</span></summary><div class="policy-details-content"><p>B0·B1은 같은 Agent에 연결하는 서버의 처리 방식입니다. Agent나 모델을 바꾸는 설정은 아닙니다.</p><h3>B0 · 기본 서버 정책</h3><p>동일한 요청을 다시 보내면 업무 변경이 중복 저장될 수 있습니다. 응답 유실 후 재시도할 때의 위험을 확인합니다.</p><h3>B1 · 중복 방지 서버 정책</h3><p>요청 키로 이미 처리한 요청인지 확인하고, 같은 요청이면 새로 저장하지 않고 기존 결과를 반환합니다. 생산·품질 참조 시험에서는 일정·검사 조건도 저장 전에 확인합니다.</p><p class="policy-details-example"><strong>예시</strong> 발주는 저장됐지만 응답이 사라져 같은 요청을 재시도하면, B0는 중복 발주가 생길 수 있고 B1은 기존 발주를 반환합니다.</p><p>두 정책 모두 담당자 승인을 확인합니다. B1에서 문제가 막혔더라도 Agent의 행동이 올바른지는 검사 근거를 함께 확인하세요.</p></div></details><p class="section-description">선택한 시험에 적용합니다.</p><div class="config-grid">${['B0','B1'].map(id=>`<button type="button" data-config="${id}" class="config-card ${state.config===id?'selected':''}" aria-pressed="${state.config===id}"><strong>${id}</strong><span>${id==='B0'?'기본 서버 정책':'중복 방지 서버 정책'}</span><p>${id==='B0'?'중복 방지 미적용':'요청 키 기반 중복 방지'}</p><i class="radio-mark" aria-hidden="true"></i></button>`).join('')}</div>`}</aside></div></section>`;
}
function compareView(){return executionView();}
function selectAgent(id){if(!agents[id])return;if(id==='purchase')state.demoTargetType='PURCHASE';state.draft={agentId:id,scenario:agents[id].defaultScenario,config:'B0'};render();}
function verifyAgent(){const id=state.draft.agentId;state.verified[id]=validateDemoProfile(id,scenario=>eventsFor(scenario,'B0'),checksFor);state.tutorialTour=state.verified[id].ok;if(state.verified[id].ok)state.tutorialGuideIndex.agents=2;render();toast(state.verified[id].ok?'데모 데이터 점검 완료. 시험 설계로 이동하세요.':'데모 데이터 점검 실패');}
function loadDemo(){const d=state.draft;if(agents[d.agentId].custom||!scenarioMap(d.agentId)[d.scenario])return;Object.assign(state,d);state.run={...d,topology:demoTopology(d.agentId)};if(state.demoTargetType!=='PURCHASE'){const name=referenceTargetTypes.find(t=>t.type_id===state.demoTargetType)?.name;state.run.topology.nodes=state.run.topology.nodes.map(n=>({...n,label:n.id==='agent'?`${name} Agent`:n.id==='mcp'?'제조업 시험 MCP':n.label}));}state.cursor=0;state.mode='spatial';state.demoPlaybackInteracted=false;state.demoStarted=false;state.demoApproval=null;navigate('live');}
function open3DDemo(){const result=validateDemoProfile('purchase',scenario=>eventsFor(scenario,'B0'),checksFor);if(!result.ok){toast('3D 데모 데이터를 확인할 수 없습니다.');return;}state.verified.purchase=result;state.draft={agentId:'purchase',scenario:'S03',config:'B0'};loadDemo();state.demoStarted=true;state.demoApproval='APPROVED';state.cursor=5;navigate('execution');toast('발주 Agent · 응답 유실 시나리오의 저장된 3D 데모입니다.');}
function targetContext(draft=false){const a=agents[state.agentId];return `<div class="target-context"><span class="agent-icon small ${state.agentId}">${a.initials}</span><div><span class="context-label">평가 대상${draft?'':' · 이 실행에 고정됨'}</span><strong>${esc(a.name)} <span>${esc(a.version)}</span></strong></div><div class="target-metadata"><span>프롬프트 <b>${esc(a.prompt)}</b></span><span>모델 <b>미지정 · 데모</b></span></div><span class="target-type">${esc(a.evaluation)}<br><span class="mono">${esc(draft?a.topology.version:runTopology().version)}</span></span></div>`;}
function emptyRunView(){return `${header('실행 분석','시험을 시작하면 결과와 근거를 확인할 수 있습니다.')}${tutorialMilestone('execution')}<section class="empty-run"><span class="empty-glyph">◈</span><h2>아직 불러온 시험이 없습니다.</h2><p>Agent 선택 → 데모 데이터 점검 → 시험 조건 설정 순서로 시작하거나, 아래 S03 데모를 바로 불러오세요.</p><div class="flow-actions"><button class="primary" data-action="agents">평가 대상 선택 <span>→</span></button><button class="secondary" data-action="demo-3d">◈ S03 응답 유실 데모 바로 불러오기</button></div></section>`;}
function demoChainSvg(agent){
 const names=agent.id==='purchase'?['Agent','승인','MCP','DB']:agent.id==='investigator'?['Agent','지침','근거','보고서']:agent.topology.nodes.slice(0,4).map(n=>n.label.slice(0,5));
 const fault=agent.id==='purchase'?2:-1;
 const w=240,h=40,step=(w-56)/Math.max(1,names.length-1);
 const lines=names.slice(0,-1).map((_,i)=>{const x1=28+i*step,x2=28+(i+1)*step,f=i===fault;return `<line x1="${x1}" y1="15" x2="${x2}" y2="15" stroke="${f?'var(--signal)':'var(--pos)'}" stroke-width="1.6" opacity="0.65" ${f?'stroke-dasharray="3 3"':''}/>`;}).join('');
 const packet=`<circle r="2.6" fill="${fault>=0?'var(--signal)':'var(--pos)'}"><animateMotion dur="2.6s" repeatCount="indefinite" path="M28,15 L${28+(names.length-1)*step},15"/></circle>`;
 const dots=names.map((nm,i)=>{const x=28+i*step,f=i===fault;return `<circle cx="${x}" cy="15" r="5" fill="${f?'var(--sig-bg)':'var(--pos-bg)'}" stroke="${f?'var(--signal)':'var(--pos)'}" stroke-width="1.5"/><text x="${x}" y="33" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="var(--mono)">${esc(nm)}</text>`;}).join('');
 return `<svg class="chain-svg" viewBox="0 0 ${w} ${h}" aria-hidden="true">${lines}${packet}${dots}</svg>`;
}
function demoTargetsView() {
 const selected=referenceTargetTypes.find(t=>t.type_id===state.demoTargetType)||referenceTargetTypes[0];
 return `<div class="targets-split demo-targets">
  <section class="card targets-card"><div class="card-h"><h2>제조 업무 유형</h2><span class="meta">3개 · 참조 Agent</span></div><p class="targets-diagram-hint">대표 시험 경로 · 주황색은 시험에서 확인할 지점입니다.</p><div class="live-targets">${referenceTargetTypes.map(type=>{
   const meta=targetTypeMeta[type.type_id],active=type.type_id===selected.type_id;
   return `<button type="button" class="live-target target-row ${active?'selected on':''}" data-demo-target-type="${type.type_id}" aria-pressed="${active}"><div class="target-main"><h3>${esc(type.name)}</h3><p>${esc(type.description)}</p><div class="scn">${meta.scenarios.map(item=>`<span class="${item.fault?'f':''}">${esc(item.code)}</span>`).join('')}</div></div>${renderTargetDiagram(type.type_id)}<div class="target-last"><span class="pill neu">데모 예시</span><span class="num">예시 시험 가능</span></div></button>`;
  }).join('')}</div></section>
  <aside class="card targets-side"><div class="card-h"><h2>최근 실행</h2><span class="meta">저장된 데모 예시</span></div><div class="live-history runs-list">${[['S03','B0','중복 발주 2건'],['S03','B1','중복 방지 · 1건'],['S01','B0','정상 발주 · 1건']].map(([scenario,config,label])=>`<button type="button" class="run-row-btn" data-demo-sample="${scenario}" data-sample-config="${config}"><span class="run-id">DEMO-${scenario}-${config}</span><span class="run-sub">${label}</span><span class="run-state-tag">예시</span></button>`).join('')}</div><div class="targets-next"><p><strong>${esc(selected.name)}</strong> 유형을 살펴보고 있습니다.</p><p>선택한 업무의 시험 시나리오를 제안받아 보세요.</p><button type="button" class="primary full-cta" data-action="demo-prepare">시험 설계로 →</button></div></aside>
 </div>`;
}
function demoRegistrationView() {
 return `<section class="panel section-pad demo-registration"><div class="live-row"><h2>새 제조업 Agent 등록</h2><span class="badge">등록 안내 · 데모</span></div><p class="live-hint">실제 환경에서는 업무·도구·시험용 데이터를 등록하고 적용 위험을 분석합니다. 여기서는 등록 항목을 살펴보고 Agent 구조 등록을 연습할 수 있습니다.</p><details><summary>등록 정보 입력·수정 살펴보기</summary><dl class="key-values"><div><dt>Agent 이름 · 버전</dt><dd>시험할 대상을 식별하는 정보</dd></div><div><dt>업무 유형 · 실행 대상</dt><dd>구매·생산·품질 유형과 연결할 실행기</dd></div><div><dt>업무 · 승인 · 재시도</dt><dd>Agent의 역할과 지켜야 하는 정책</dd></div><div><dt>도구 · 시험용 데이터</dt><dd>MCP 도구 정의와 업무 입력·초기 상태</dd></div></dl><button type="button" class="secondary" data-action="register">Agent 구조 등록 연습</button></details><h3>내가 등록한 Agent</h3><p class="live-hint">${Object.values(agents).filter(a=>a.custom).length?'아래 개별 Agent 목록에서 등록한 구조를 선택해 확인하세요.':'아직 이 브라우저에 등록한 구조가 없습니다.'}</p></section>`;
}
function openDemoSample(scenario,config) {
 if(!['S01','S03'].includes(scenario)||!['B0','B1'].includes(config))return;
 const result=validateDemoProfile('purchase',id=>eventsFor(id,'B0'),checksFor);
 if(!result.ok){toast('데모 데이터를 확인할 수 없습니다.');return;}
 state.verified.purchase=result;state.demoTargetType='PURCHASE';state.draft={agentId:'purchase',scenario,config};loadDemo();state.demoStarted=true;state.demoApproval='APPROVED';state.cursor=eventsFor().length-1;navigate('execution');
}
function agentView(){return `${header('평가 대상','어떤 제조 Agent를 시험할지 고르세요. 목록과 실행 기록은 모두 데모 예시입니다.')}${tutorialMilestone('agents')}${demoTargetsView()}${demoRegistrationView()}`;}
function previewData(){const a=agents[state.draft.agentId];return{agent:a,graph:a.topology,events:a.custom?a.events:eventsFor(a.defaultScenario,'B0')};}
function structureView(){const{agent,graph,events}=previewData();state.previewCursor=Math.min(state.previewCursor??0,Math.max(events.length-1,0));const mapping=mapEvents(graph,events),current=mapping[state.previewCursor],node=graph.nodes.find(n=>n.id===state.previewNode)||current?.node,unmappedCount=mapping.filter(m=>!m.ok).length;return `${header(`${esc(agent.name)} · 등록 구조`,'등록한 구조와 샘플 사건의 연결을 확인합니다. 실제 Agent 실행이나 새 평가가 아닙니다.','<button class="secondary" data-action="agents">평가 대상으로 돌아가기</button>')}
 ${tutorialMilestone('structure')}
 <div class="card strip"><div class="lead"><label>구조 버전</label><div class="v" style="font-size:20px">${esc(graph.version)}</div><div class="d">${agent.custom?'사용자 등록 구조':'데모 참조 구조'}</div></div><div><label>등록 노드</label><div class="v">${graph.nodes.length}<small>개</small></div><div class="d">역할 기반 3D 배치</div></div><div><label>연결 경로</label><div class="v">${graph.edges.length}<small>개</small></div><div class="d">방향성 호출 · 응답</div></div><div><label>샘플 사건</label><div class="v">${events.length}<small>개</small></div><div class="d">${unmappedCount?`<span class="neg-t">${unmappedCount}개 미매핑</span>`:'전체 매핑 확인'}</div></div><div><label>현재 선택 노드</label><div class="v" style="font-size:20px">${esc(node?.id||'—')}</div><div class="d">${esc(node?.role||'미선택')}</div></div></div>
 <div class="inspection-grid structure-inspection"><section class="stage-panel"><div class="stage-toolbar"><div class="segmented view-toggle"><button data-preview-mode="spatial" class="${state.previewMode!=='timeline'?'selected':''}">◈ 3D 구조</button><button data-preview-mode="timeline" class="${state.previewMode==='timeline'?'selected':''}">등록 노드 목록</button></div></div>${state.previewMode==='timeline'?`<div class="topology-fallback">${graph.nodes.map(n=>`<button class="secondary full" data-preview-node="${esc(n.id)}">${esc(n.label)} · ${esc(n.role)}</button>`).join('')}</div>`:`<div class="visual-stage topology-stage"><div class="stage-caption"><span class="stage-kicker">${agent.custom?'사용자 등록 구조':'데모 Agent 구조'}</span><strong>${esc(current?.event.title||'구조만 등록됨')}</strong><span>노드 역할로 입체 형태를, 연결 정보로 경로를 구성합니다.</span></div><div id="structure-host" role="group" aria-label="등록 구조 3D 미리보기"></div></div>`}</section><aside class="card"><div class="card-h"><h2>${node?'선택한 노드':'노드 · 샘플 사건'}</h2><span class="meta mono">${esc(node?.id||'—')}</span></div><div class="section-pad"><h3>${esc(node?.label||'구조 정보')}</h3><p class="mono dim">${esc(node?.id||'—')} · ${esc(node?.role||'—')}</p><p class="live-hint">${events.length?'샘플 사건을 선택하면 해당 노드와 연결을 강조합니다.':'샘플 이벤트가 없어 등록된 구조만 표시합니다.'}</p>${node&&!events.slice(0,state.previewCursor+1).some(e=>e.node_id===node.id)?'<p class="mapping-warning">이 시점까지 이 노드에서 관측된 사건이 없습니다.</p>':''}<div class="preview-events">${events.map((e,i)=>`<button data-preview-event="${i}" class="${i===state.previewCursor?'selected':''}"><span>${String(i+1).padStart(2,'0')}</span><div>${esc(e.title)}<small>${esc(e.node_id)}${e.edge_id?` · ${esc(e.edge_id)}`:''}</small></div></button>`).join('')}</div></div></aside></div>${graphDetails(graph)}`;}
function removeCoachmark(){
 if(typeof document==='undefined')return;
 document.getElementById('tutorial-coachmark-overlay')?.remove();
 document.querySelectorAll('.coachmark-highlight-target').forEach(el=>el.classList.remove('coachmark-highlight-target'));
}
function renderCoachmark(){
 if(typeof document==='undefined')return;
 removeCoachmark();
 if(workspacePage!=='demo'||!state.tutorialTour)return;
 const steps=tutorialGuideSteps(state.tab),index=Math.min(state.tutorialGuideIndex[state.tab]||0,steps.length-1);
 const item=steps[index];
 const cfg={...item,step:`설명 ${index+1} / ${steps.length}`};
 const targetEl=document.querySelector(cfg.selector)||document.querySelector('.tutorial-page-guide');
 if(!targetEl)return;
 targetEl.classList.add('coachmark-highlight-target');
 const overlay=document.createElement('div');
 overlay.id='tutorial-coachmark-overlay';
 overlay.className='tutorial-coachmark-overlay';
 overlay.innerHTML=`
  <div class="coachmark-backdrop"></div>
  <div class="coachmark-spotlight" id="coachmark-spotlight"></div>
  <div class="coachmark-bubble-wrapper" id="coachmark-bubble-wrapper">
   <div class="coachmark-bubble">
    <div class="coachmark-bubble-tail"></div>
    <div class="coachmark-bubble-head">
     <span class="coachmark-step-badge">${cfg.step}</span>
     <button type="button" class="coachmark-close-btn" data-action="close-tour" title="말풍선 가이드 닫기" aria-label="말풍선 가이드 닫기">✕</button>
    </div>
    <strong class="coachmark-bubble-title">${cfg.title}</strong>
    <p class="coachmark-bubble-desc">${cfg.desc}</p>
    <p class="coachmark-bubble-desc">안내를 닫으면 화면을 자유롭게 살펴보며 직접 진행할 수 있습니다.</p>
    <div class="tutorial-guide-controls"><button type="button" class="secondary" data-guide-step="${index+1}" ${index===steps.length-1?'disabled':''}>다음 설명</button><button type="button" class="primary coachmark-practice" data-action="practice-guide">안내 확인 · 직접 해보기</button></div>
   </div>
  </div>`;
 overlay.querySelectorAll('[data-guide-step]').forEach(button=>button.addEventListener('click',event=>{event.stopPropagation();setTutorialGuideStep(Number(button.dataset.guideStep));}));
 document.body.appendChild(overlay);

 function updatePositions(){
  if(!targetEl||!overlay.isConnected)return;
  const rect=targetEl.getBoundingClientRect();
  const spotlight=document.getElementById('coachmark-spotlight');
  const bubbleWrapper=document.getElementById('coachmark-bubble-wrapper');
  if(!spotlight||!bubbleWrapper)return;
  spotlight.style.top=(rect.top-6)+'px';
  spotlight.style.left=(rect.left-6)+'px';
  spotlight.style.width=(rect.width+12)+'px';
  spotlight.style.height=(rect.height+12)+'px';
  const spaceAbove=rect.top;
  const spaceBelow=window.innerHeight-rect.bottom;
  const isAbove=spaceAbove>190||spaceAbove>spaceBelow;
  bubbleWrapper.className=`coachmark-bubble-wrapper ${isAbove?'pointing-down':'pointing-up'}`;
  const maxLeft=Math.max(12,window.innerWidth-380);
  const bubbleLeft=Math.max(12,Math.min(rect.left+rect.width/2-180,maxLeft));
  bubbleWrapper.style.left=bubbleLeft+'px';
  const tail=bubbleWrapper.querySelector('.coachmark-bubble-tail');
  if(tail){
   const tailOffset=Math.max(20,Math.min(rect.left+rect.width/2-bubbleLeft-7,330));
   tail.style.left=tailOffset+'px';
  }
  const height=bubbleWrapper.getBoundingClientRect().height;
  bubbleWrapper.style.top=Math.max(12,Math.min(isAbove?rect.top-height-14:rect.bottom+14,window.innerHeight-height-12))+'px';
  bubbleWrapper.style.bottom='auto';
 }
 targetEl.scrollIntoView({behavior:'instant',block:'center'});
 updatePositions();
}
function render() {
 leaveLive();
 document.body.classList.toggle('is-unauthenticated',workspacePage!=='demo'&&!isLiveAuthenticated());
 removeCoachmark();
 document.querySelectorAll('[data-tab=compare]').forEach(button=>{button.hidden=!LIVE_COMPARISON_ENABLED;const arrow=button.previousElementSibling;if(arrow?.classList.contains('step-arrow'))arrow.hidden=!LIVE_COMPARISON_ENABLED;});
 $('#main').classList.toggle('demo-workspace',workspacePage==='demo');
 $('#demo-navigation').hidden=true;
 document.querySelectorAll('[data-run-nav]').forEach(button=>{if(workspacePage==='demo')button.hidden=true;});
 const stepNav=$('.step-nav');
 if(stepNav && workspacePage==='demo') stepNav.hidden=false;
 document.querySelectorAll('.workspace-bar [data-tab], .site-rail [data-tab]').forEach(button=>{button.classList.toggle('active',button.dataset.tab===(workspacePage==='demo'?state.tab:workspacePage));button.setAttribute('aria-current',button.dataset.tab===(workspacePage==='demo'?state.tab:workspacePage)?'page':'false');});
 const footerSpan = $('.footer>span');
 if (footerSpan) footerSpan.textContent=workspacePage==='demo'?'데모 예시입니다. 실제 시험 결과와 구분합니다.':'서버에서 조회한 실제 실행·검사·근거를 표시합니다.';
 if(workspacePage!=='demo'){mountLive($('#main'),workspacePage,navigateWorkspace);return;}
 if($('#header-mode-label'))$('#header-mode-label').textContent='튜토리얼 모드';
 const modeBadge=$('#header-mode-badge');
 if(modeBadge){
   const dot=modeBadge.querySelector('.pulse-dot');
   if(dot) dot.className='pulse-dot idle';
 }
 const demoBtn=$('.header-end .demo-entry');
 if(demoBtn){
   demoBtn.hidden=false;
   delete demoBtn.dataset.tab;
   demoBtn.dataset.action='exit-tutorial';
   demoBtn.textContent='실제 실행 모드로 돌아가기';
 }
 if($('#header-scope'))$('#header-scope').textContent=referenceTargetTypes.find(t=>t.type_id===state.demoTargetType)?.name||'데모 참조';
 if($('#header-page-label'))$('#header-page-label').textContent={agents:'평가 대상',prepare:'시험 설계',live:'3. 실험 실행',execution:'4. 실행 분석',structure:'등록 구조 미리보기'}[state.tab]||'튜토리얼';
 $('#main').innerHTML=state.tab==='structure'?structureView():state.tab==='agents'?agentView():state.tab==='prepare'?withDraft(prepareView):state.tab==='live'?demoRunView('live'):!state.run?emptyRunView():executionView();

 document.querySelectorAll('[data-demo-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.demoTab===(state.tab==='structure'?'agents':state.tab));b.setAttribute('aria-current',b.dataset.demoTab===(state.tab==='structure'?'agents':state.tab)?'page':'false');});
 $('#scenario-select')?.addEventListener('change',e=>chooseScenario(e.target.value));
 if(state.tab==='structure'&&state.previewMode!=='timeline'){const{graph,events}=previewData();const frame={...frameFor(graph,events,state.previewCursor??0),preview:true};if(state.previewNode){frame.activeNode=state.previewNode;frame.activeEdge=null;}mountScene($('#structure-host'),graph,frame,id=>{state.previewNode=id;render();});}
 else if(state.run&&state.tab==='execution'&&state.mode==='spatial'){const selected=state.selected?.kind==='event'?state.selected.index:state.selected?.kind==='check'?checksFor()[state.selected.index].evidence:state.cursor;mountScene($('#scene-host'),runTopology(),{...frameFor(runTopology(),eventsFor(),state.tab==='live'&&!state.demoStarted?-1:state.cursor,selected),playing:state.playing},selectNode);}else pauseScene();
 $('#scrubber')?.addEventListener('change',e=>{const val=Number(e.target.value);stopPlayback();state.cursor=val;state.selected=null;state.demoPlaybackInteracted=true;render();$('#scrubber').focus();});
 renderCoachmark();
}
let demoGeneration=0;
function generateDemoProposals(){
 if(state.demoDesignStatus==='loading')return;
 const request=++demoGeneration;state.demoDesignStatus='loading';state.demoSelected=false;state.tutorialTour=false;render();
 setTimeout(()=>{if(request!==demoGeneration)return;state.demoDesignStatus='ready';if(workspacePage==='demo'&&state.tab==='prepare')render();},1100);
}
function practiceTutorial(){
 let step=tutorialGuideSteps(state.tab)[state.tutorialGuideIndex[state.tab]||0];
 if(state.tab==='prepare'){
  demoGeneration++;state.demoDesignStatus='idle';state.demoSelected=false;state.tutorialGuideIndex.prepare=0;
  step=tutorialGuideSteps('prepare')[0];
 }
 state.tutorialTour=false;render();
 if(typeof document!=='undefined')$(step.selector)?.scrollIntoView({behavior:'smooth',block:'center'});
}
function finishDemoApproval(approved){
 state.demoApproval=approved?'APPROVED':'REJECTED';
 if(approved&&state.scenario.endsWith('02')){state.scenario=state.scenario.replace(/02$/,'01');state.draft.scenario=state.scenario;state.run={...state.run,scenario:state.scenario};}
 if(!approved){state.scenario=state.demoTargetType==='PRODUCTION'?'P02':state.demoTargetType==='QUALITY'?'Q02':'S02';state.draft.scenario=state.scenario;state.run={...state.run,scenario:state.scenario};}
 state.cursor=eventsFor().length-1;render();
}
function stopPlayback(){state.playing=false;clearTimeout(playbackTimer);}
function scheduleNext(){clearTimeout(playbackTimer);if(!state.playing)return;playbackTimer=setTimeout(()=>{if(state.cursor>=eventsFor().length-1){stopPlayback();render();return;}state.cursor++;state.selected=null;render();scheduleNext();},1200/state.speed);}
function toast(message){const t=$('#toast');if(!t)return;t.textContent=message;t.classList.add('visible');clearTimeout(toast.timeout);toast.timeout=setTimeout(()=>t.classList.remove('visible'),3000);}
function exportEvidence(){const data={source:'demo_fixture',real_execution:false,run_id:`${runId()}`,topology:runTopology(),target:{...agents[state.agentId],topology:runTopology(),connection:'demo_fixture',live_connected:false},evaluation_unit:agents[state.agentId].evaluation,scenario:state.scenario,configuration:state.agentId==='purchase'?state.config:null,run_status:'COMPLETED',injection_status:state.scenario==='S03'?'APPLIED':null,events:eventsFor(),checks:checksFor()};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`demo-${state.scenario}-${state.config}-evidence.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('데모 사건과 판정을 JSON으로 내보냈습니다.');}
function showEvent(i){stopPlayback();state.cursor=i;state.selected=null;state.demoPlaybackInteracted=true;render();}
function selectNode(id){const matches=eventsFor().filter(e=>e.node_id===id&&e.sequence<=state.cursor+1);const event=matches.at(-1);if(!event){toast('현재 재생 시점에는 이 노드의 사건이 없습니다.');return;}stopPlayback();state.selected={kind:'event',index:event.sequence-1};render();}
document.addEventListener('click',async e=>{
 const button=e.target.closest('button,[data-node],[data-event]');if(!button)return;
 if(button.dataset.guideStep!==undefined){setTutorialGuideStep(Number(button.dataset.guideStep));return;}
 if(button.dataset.demoTargetType){state.demoTargetType=button.dataset.demoTargetType;state.draft={agentId:'purchase',scenario:Object.keys(scenarioMap('purchase'))[0],config:'B0'};state.demoSelected=false;state.demoDesignStatus='idle';state.tutorialTour=false;render();return;}
 if(button.dataset.demoSample){openDemoSample(button.dataset.demoSample,button.dataset.sampleConfig);return;}
 if(button.dataset.demoTab){navigate(button.dataset.demoTab);return;}
 if(button.dataset.tab){if(workspacePage==='demo'&&['agents','prepare','live','execution'].includes(button.dataset.tab))navigate(button.dataset.tab);else navigateWorkspace(button.dataset.tab);return;}
 if(button.dataset.scenario){chooseScenario(button.dataset.scenario);return;}
 if(button.dataset.config&&state.tab==='prepare'){state.draft.config=button.dataset.config;render();return;}
 if(button.dataset.previewMode){state.previewMode=button.dataset.previewMode;render();return;}
 if(button.dataset.previewNode){state.previewNode=button.dataset.previewNode;render();return;}
 if(button.dataset.previewEvent!==undefined){state.previewCursor=Number(button.dataset.previewEvent);state.previewNode=null;render();return;}
 if(button.dataset.agent){selectAgent(button.dataset.agent);return;}
 if(button.dataset.mode){state.mode=button.dataset.mode;render();return;}
 if(button.dataset.event!==undefined){showEvent(Number(button.dataset.event));return;}
 if(button.dataset.node){selectNode(button.dataset.node);return;}
 if(button.dataset.check!==undefined){stopPlayback();state.selected={kind:'check',index:Number(button.dataset.check)};render();return;}
 switch(button.dataset.action){
 case 'demo-prepare':state.demoDesignStatus='idle';state.demoSelected=false;navigate('prepare');break;
 case 'demo-generate':generateDemoProposals();break;
 case 'demo-start':if(!state.run)break;state.demoStarted=true;state.cursor=2;state.demoApproval=null;render();break;
 case 'demo-approve':finishDemoApproval(true);break;
 case 'demo-reject':finishDemoApproval(false);break;
 case 'agents':navigate('agents');break;
 case 'register':openRegistration();break;
 case 'demo-practice':state.demoTargetType='PURCHASE';selectAgent('purchase');state.tutorialTour=false;render();$('#demo-inspection')?.scrollIntoView({behavior:'smooth',block:'start'});break;
 case 'structure':state.previewMode='spatial';state.previewCursor=0;state.previewNode=null;navigate('structure');break;
 case 'demo-3d':open3DDemo();break;
 case 'verify':verifyAgent();break;
 case 'continue':if(state.verified[state.draft.agentId]?.ok)navigate('prepare');break;
 case 'prepare':navigate('prepare');break;
 case 'compare':navigate('execution');break;
 case 'load':loadDemo();break;
 case 'practice-guide':practiceTutorial();break;
 case 'start-tutorial':$('#tutorial-invitation').close();navigateWorkspace('demo');break;
 case 'dismiss-tutorial':$('#tutorial-invitation').close();break;
 case 'toggle-guide-details':{const expanded=!state.tutorialGuideExpanded[state.tab];state.tutorialGuideExpanded[state.tab]=expanded;button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'간략히 보기':'자세히 보기';$('#tutorial-guide-content').hidden=!expanded;break;}
 case 'close-tour':state.tutorialTour=false;removeCoachmark();render();break;
 case 'toggle-tour':state.tutorialTour=!state.tutorialTour;render();break;
 case 'exit-tutorial':state.tutorialTour=false;removeCoachmark();navigateWorkspace('agents');break;
 case 'play':if(state.tab!=='execution')break;state.demoPlaybackInteracted=true;if(state.playing){stopPlayback();render();}else{if(state.cursor===eventsFor().length-1)state.cursor=0;state.playing=true;state.selected=null;render();scheduleNext();}break;
 case 'speed':state.speed=state.speed===1?2:state.speed===2?.5:1;render();scheduleNext();break;
 case 'export':exportEvidence();break;
 case 'copy':try{await navigator.clipboard.writeText($('#evidence-json').textContent);toast('선택한 근거 JSON을 복사했습니다.');}catch{toast('복사할 수 없습니다. 근거 JSON을 직접 선택해 복사해 주세요.');}break;
 case 'inspect-b0':case 'inspect-b1':state.config=button.dataset.action==='inspect-b0'?'B0':'B1';state.run={...state.run,config:state.config};state.cursor=eventsFor().length-1;navigate('execution');break;
 }
});
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('svg [role=button]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
for(const id of ['help-button','login-help'])$('#'+id)?.addEventListener('click',()=>$('#info-dialog').showModal());
for(const id of ['close-dialog','understood'])$('#'+id).addEventListener('click',()=>$('#info-dialog').close());
function updateThemeUI() {
  const isLight = document.documentElement.dataset.theme === 'light';
  const label = $('#theme-toggle-label');
  if (label) label.textContent = isLight ? '다크 모드' : '라이트 모드';
  const title = isLight ? '다크 모드로 전환' : '라이트 모드로 전환';
  $('#theme-toggle')?.setAttribute('title', title);
  $('#theme-toggle')?.setAttribute('aria-label', title);
  $('#theme-toggle-rail')?.setAttribute('title', title);
  $('#theme-toggle-rail')?.setAttribute('aria-label', title);
  for(const id of ['theme-toggle','theme-toggle-rail'])$('#'+id)?.setAttribute('aria-pressed',String(!isLight));
  const meta = $('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', isLight ? '#f4f5f8' : '#0e0e10');
}
function toggleTheme() {
  const current = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  const next = current === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem('crashlab_theme', next);
  } catch (e) {}
  updateThemeUI();
  toast(next === 'light' ? '라이트 모드로 전환했습니다.' : '다크 모드로 전환했습니다.');
}
$('#theme-toggle')?.addEventListener('click', toggleTheme);
$('#theme-toggle-rail')?.addEventListener('click', toggleTheme);
window.matchMedia?.('(prefers-color-scheme: light)').addEventListener('change', e => {
  if (!localStorage.getItem('crashlab_theme')) {
    document.documentElement.dataset.theme = e.matches ? 'light' : 'dark';
    updateThemeUI();
  }
});
updateThemeUI();
window.toggleTheme = toggleTheme;
window.updateThemeUI = updateThemeUI;
$('.brand').addEventListener('click',e=>{e.preventDefault();workspacePage==='demo'?navigate('agents'):navigateWorkspace('agents');});
if(typeof window!=='undefined'){
 window.addEventListener('resize',()=>{if(state.tutorialTour&&workspacePage==='demo')renderCoachmark();});
 window.addEventListener('scroll',()=>{
  if(state.tutorialTour&&workspacePage==='demo'){
   const spotlight=document.getElementById('coachmark-spotlight');
   const targetEl=document.querySelector('.coachmark-highlight-target');
   const bubbleWrapper=document.getElementById('coachmark-bubble-wrapper');
   if(spotlight&&targetEl&&bubbleWrapper){
    const rect=targetEl.getBoundingClientRect();
    spotlight.style.top=(rect.top-6)+'px';
    spotlight.style.left=(rect.left-6)+'px';
    spotlight.style.width=(rect.width+12)+'px';
    spotlight.style.height=(rect.height+12)+'px';
    const isAbove=bubbleWrapper.classList.contains('pointing-down');
    const height=bubbleWrapper.getBoundingClientRect().height;
    bubbleWrapper.style.top=Math.max(12,Math.min(isAbove?rect.top-height-14:rect.bottom+14,window.innerHeight-height-12))+'px';
    bubbleWrapper.style.bottom='auto';
   }
  }
 },true);
}
initRegistration(result=>{state.draft={agentId:result.profile.id,scenario:'CUSTOM',config:'B0'};state.previewMode='spatial';state.previewCursor=0;state.previewNode=null;navigate('structure');toast(result.persisted?'Agent 구조를 이 브라우저에 등록했습니다.':'구조를 등록했습니다. 저장소를 사용할 수 없어 새로고침하면 사라집니다.');});
function readRoute(){
 if(isApproverAccount()){workspacePage=accountPage(location.hash.slice(1));return {page:workspacePage,show3d:false};}
 if(location.hash==='#demo-3d'){workspacePage='demo';return {page:'demo',show3d:true};}
 if(location.hash.startsWith('#demo')){const requested=location.hash.slice(6);workspacePage='demo';state.tab=['agents','prepare','live','execution'].includes(requested)?requested:'agents';if(['live','execution'].includes(state.tab)&&!state.run){state.run={...state.draft,topology:demoTopology('purchase')};state.cursor=state.tab==='execution'?eventsFor().length-1:0;}return {page:'demo',demoTab:state.tab,show3d:false};}
 if(!isLiveAuthenticated()){workspacePage='agents';return {page:'agents',show3d:false};}
 const route=workspaceRoute(location.hash);if(route.page==='demo'&&(workspacePage!=='demo'||route.demoTab!==state.tab))startTutorialPage(route.demoTab||'agents');workspacePage=route.page;
 if(route.demoTab)state.tab=route.demoTab;
 if(workspacePage==='demo'&&(state.tab==='execution'||state.tab==='compare')&&!state.run){
  const result=validateDemoProfile('purchase',scenario=>eventsFor(scenario,'B0'),checksFor);
  if(result.ok){state.verified.purchase=result;state.draft={agentId:'purchase',scenario:'S03',config:'B0'};Object.assign(state,state.draft);state.run={...state.draft,topology:demoTopology('purchase')};state.cursor=5;state.mode='spatial';}
 }
 return route;
}
const initialTab=readRoute();
window.addEventListener('hashchange',()=>{const route=readRoute();if(route.show3d)open3DDemo();else render();});
if(initialTab.show3d)open3DDemo();else render();
