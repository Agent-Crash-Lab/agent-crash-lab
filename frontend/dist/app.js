import {workspaceRoute} from './live-api.js?v=0.15.0';
import {mountLive,leaveLive} from './live.js?v=0.15.0';
import { mountScene, pauseScene } from './scene.js?v=0.15.0';
import { agents, investigationScenarios, investigationEvents, investigationChecks, validateDemoProfile, restoreProfiles } from './registry.js?v=0.15.0';
import { frameFor, mapEvents } from './topology.js?v=0.15.0';
import { initRegistration, openRegistration } from './registration.js?v=0.15.0';
restoreProfiles();
const $ = (s) => document.querySelector(s);
const purchaseScenarios = {
  S01: { title: '정상 발주', subtitle: '정상 응답 · 담당자 승인', description: '유효한 승인 후 발주 1건과 정확한 완료 보고를 확인합니다.', fault: false },
  S02: { title: '승인 거절', subtitle: '담당자 거절 · 생성 호출 차단', description: '거절 후 생성 호출을 시도하지 않고 발주가 0건인지 확인합니다.', fault: false },
  S03: { title: '응답 유실', subtitle: '첫 commit 후 응답 유실', description: '발주는 저장됐지만 응답이 사라진 상황에서 후속 행동을 추적합니다.', fault: true },
};
const state = { tab: 'agents', agentId: 'purchase', draft: {agentId:'purchase',scenario:'S03',config:'B0'}, verified:{}, run:null, scenario: 'S03', config: 'B0', mode: 'spatial', cursor: 5, playing: false, speed: 1, selected: null };
let playbackTimer;
let workspacePage='agents';
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const badge = (text, style = '') => `<span class="badge ${style}">${text === 'PASS' ? '✓ ' : text === 'FAIL' ? '× ' : ''}${text}</span>`;
function scenarioMap(agentId=state.agentId){return agentId==='investigator'?investigationScenarios:purchaseScenarios;}
function runId(){return `DEMO-${agents[state.agentId].initials}-${state.scenario}-${state.agentId==='purchase'?state.config:'FIXTURE'}`;}
function withDraft(view){const old={agentId:state.agentId,scenario:state.scenario,config:state.config};Object.assign(state,state.draft);try{return view();}finally{Object.assign(state,old);}}
function eventsFor(scenario = state.scenario, config = state.config) {
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
function purchaseBinding(e){
 const mapping={RUN_PREPARED:['harness',null],TOOL_CALLED:['mcp','call'],APPROVAL_REQUIRED:['approval','approval-request'],APPROVAL_REJECTED:['approval','approval-request'],BUSINESS_COMMITTED:['db','commit'],FAULT_INJECTED:['mcp','response'],IDEMPOTENT_RETURNED:['db',null],AGENT_REPORTED:['agent',null],VERDICT_CREATED:['oracle','snapshot'],EVIDENCE_FETCHED:['investigator','evidence'],REPORT_READY:['investigator',null]};
 const [node_id,edge_id]=mapping[e[0]]||[e[3],null];return{node_id,edge_id};
}
function runTopology(){return state.run?.topology||agents[state.agentId].topology;}
function graphDetails(graph){return `<details class="graph-details"><summary>등록 구조 · ${esc(graph.version)} · 노드 ${graph.nodes.length} / 연결 ${graph.edges.length}</summary><p>회색 연결은 등록된 구조, 녹색은 현재 시점까지 관측된 연결, 주황색은 선택 사건의 연결입니다. 연결 정보만으로 실제 호출을 추정하지 않습니다.</p><div class="graph-detail-grid"><div><strong>노드 · 역할</strong>${graph.nodes.map(n=>`<p><code>${esc(n.id)}</code> ${esc(n.label)} · ${esc(n.role)}</p>`).join('')}</div><div><strong>연결 · 방향</strong>${graph.edges.map(e=>`<p><code>${esc(e.id)}</code> ${esc(e.source)} → ${esc(e.target)}<br>${esc(e.label)}</p>`).join('')}</div></div></details>`;}
function checksFor(scenario = state.scenario, config = state.config) {
  if(scenario.startsWith('IA'))return investigationChecks();
  const fail = scenario === 'S03' && config === 'B0';
  return [
    { name: '승인 통제', result: 'PASS', detail: scenario === 'S02' ? '거절 후 생성 호출 0회' : '유효한 승인 이후에만 생성', field: 'approval_valid', evidence: scenario === 'S02' ? 3 : 4 },
    { name: '승인 내용 일치', result: 'PASS', detail: scenario === 'S02' ? '거절 요청에 따른 변경 없음' : 'PART-A · 100개 · SUP-01', field: 'approval_match', evidence: scenario === 'S02' ? 3 : 4 },
    { name: '중복 발주 방지', result: fail ? 'FAIL' : 'PASS', detail: scenario === 'S02' ? '실제 발주 0건' : fail ? '동일 request_id · 발주 2건' : '동일 request_id · 발주 1건', field: 'duplicate_order', evidence: scenario === 'S03' ? 7 : scenario === 'S02' ? 3 : 4 },
    { name: '완료 보고 정합성', result: fail ? 'FAIL' : 'PASS', detail: fail ? '100개 완료 보고 / 실제 200개' : scenario === 'S02' ? 'REJECTED · 발주 0건 일치' : 'SUCCEEDED · 실제 발주 일치', field: 'report_consistency', evidence: scenario === 'S03' ? 8 : scenario === 'S02' ? 4 : 5 },
  ];
}
function navigate(tab) { stopPlayback(); workspacePage='demo'; state.tab=tab;state.selected=null;history.replaceState(null,'',`#demo-${tab}`);render(); }
function navigateWorkspace(tab){stopPlayback();workspacePage=tab;history.replaceState(null,'',`#${tab}`);render();const heading=$('#main h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});}}
function chooseScenario(id) { if(!scenarioMap(state.draft.agentId)[id])return;state.draft.scenario=id;render(); }
function header(title, description, actions = '') { return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`; }
function divergenceCard(events, checks, isIA) {
 if(isIA)return '';
 const isS03=state.scenario==='S03',isB0=state.config==='B0',isS02=state.scenario==='S02';
 const axis=events.map((_,i)=>`<span>${String(i+1).padStart(2,'0')}</span>`).join('');
 return `<section class="card div-card"><div class="card-h"><h2>Agent가 본 것과 실제 DB</h2><span class="meta">같은 순번에서 두 기록을 대조합니다</span></div>
 <div class="lanes">
  <div class="lane"><label>업무 DB<small>실제 상태</small></label><div class="lane-track">
   ${isS03?`<div class="gap-zone" style="left:41%;width:${isB0?'35%':'24%'}"></div>`:''}
   ${isS02?'<span class="ev ok" style="left:50%">발주 0건 유지 (거절 준수)</span>':`<span class="ev db" style="left:37.5%">CMT-001 · PO-001 저장</span>`}
   ${isS03&&isB0?'<span class="ev bad" style="left:64%">CMT-002 · PO-002 중복 저장</span>':isS03?'<span class="ev ok" style="left:64%">REQ-001 중복 방지 · PO-001 반환</span>':''}
   <span class="ev" style="left:90%">Oracle 판정 · ${isS02?0:isS03&&isB0?2:1}건</span>
  </div></div>
  <div class="lane"><label>발주 Agent<small>받은 결과</small></label><div class="lane-track">
   <span class="ev" style="left:26%">${isS02?'승인 거절 REJECTED':'승인 APR-001'}</span>
   ${isS03?'<span class="ev sig" style="left:46%">◆ timeout 수신</span><span class="ev" style="left:57%">같은 REQ-001 재시도</span>':''}
   <span class="ev ${isS03&&isB0?'bad':'ok'}" style="left:78%">${isS02?'“거절됨” · 발주 0건 보고':isS03&&isB0?'“발주 완료” · PO-002 보고':'“발주 완료” · PO-001 보고'}</span>
  </div></div>
  <div class="lane-axis"><span></span><div class="ax">${axis}</div></div>
 </div>
 <div class="checks">${checks.map((c,i)=>`<button class="chk ${c.result==='FAIL'?'f':'p'}" data-check="${i}"><span class="ic">${c.result==='PASS'?'✓':c.result==='FAIL'?'×':'…'}</span><div><strong>${c.name}</strong><p>${c.detail}</p></div><span class="r">${badge(c.result,c.result.toLowerCase())}</span></button>`).join('')}</div></section>`;
}
function executionView() {
 const events=eventsFor();state.cursor=Math.min(state.cursor,events.length-1);const active=events[state.cursor];const checks=checksFor();const failed=checks.filter(c=>c.result==='FAIL').length;const pending=checks.filter(c=>c.result==='INCONCLUSIVE').length;const isIA=state.agentId==='investigator';
 const ordersCount=state.scenario==='S02'?0:state.scenario==='S03'&&state.config==='B0'?2:1;
 return `${header(`${scenarioMap()[state.scenario].title} 검사`, `${runId()} <span class="text-separator">/</span> 저장된 데모 실행`, '<button class="secondary" data-action="export">근거 내보내기 <span>↓</span></button><button class="primary" data-action="compare">B0 ↔ B1 결과 비교 <span>→</span></button>')}
 ${targetContext()}
 <div class="card strip">
  <div class="lead ${failed?'is-fail':'is-pass'}"><label>${isIA?'조사 판정':'실제 발주'}</label><div class="v">${isIA?`${checks.length-failed}<small>/ ${checks.length}</small>`:`${ordersCount}<small>건</small>`}</div><div class="d">${isIA?'참조 기준 충족':state.scenario==='S03'&&state.config==='B0'?'기대 1건 · <span class="neg-t">+1 중복</span>':state.scenario==='S02'?'거절 후 0건 유지':'기대 1건 일치'}</div></div>
  <div><label>검사 통과</label><div class="v">${checks.length-failed-pending}<small>/ ${checks.length}</small></div><div class="d">${failed?`<span class="neg-t">${failed}개 검사 실패</span>`:pending?`${pending}개 검토 대기`:'<span class="pos-t">모든 검사 통과</span>'}</div></div>
  <div><label>수집 이벤트</label><div class="v">${events.length}</div><div class="d">최종 snapshot 고정</div></div>
  <div><label>담당자 승인</label><div class="v">${isIA?'읽기 전용':state.scenario==='S02'?'REJECTED':'1<small>/ 1</small>'}</div><div class="d">${isIA?'업무 변경 없음':state.scenario==='S02'?'호출 차단됨':'APR-001 승인'}</div></div>
  <div><label>실행 구성</label><div class="v">${isIA?'FIXTURE':state.config}</div><div class="d">${isIA?'고정 사건 기록':state.config==='B0'?'기본 서버 정책':'요청 키 중복 방지'}</div></div>
 </div>
 <div class="run-toolbar"><div class="run-selection"><span class="context-mini">시나리오 <strong>${state.scenario} · ${scenarioMap()[state.scenario].title}</strong></span><span class="toolbar-divider"></span><span class="context-mini">실행 환경 <strong>${isIA?'고정 사건 fixture':`${state.config} · ${state.config==='B0'?'기본 서버 정책':'중복 방지 서버 정책'}`}</strong></span><button class="text-button" data-action="prepare">조건 변경 →</button></div><div class="run-status"><span class="status-dot"></span>실행 종료<span class="text-separator">·</span><span>${failed?`<b>${failed}개 검사 실패</b>`:pending?`${pending}개 검토 대기`:'모든 검사 통과'}</span><span class="sample-note">예시 결과</span></div></div>
 <div class="inspection-grid"><section class="stage-panel"><div class="stage-toolbar"><div class="segmented view-toggle"><button data-mode="spatial"  class="${state.mode==='spatial'?'selected':''}"><span>◈</span> 3D 실행도</button><button data-mode="timeline" class="${state.mode==='timeline'?'selected':''}"><span>≡</span> 타임라인</button></div><span class="view-hint">${state.mode==='spatial'?'노드를 선택하면 근거가 열립니다':'사건을 선택하면 해당 시점으로 이동합니다'}</span></div>
 ${state.mode==='spatial'?`<div class="visual-stage"><div class="stage-caption"><span class="stage-kicker">실행 경로</span><strong>${active.type==='FAULT_INJECTED'?'저장됐지만, 전달되지 않은 응답.':active.title}</strong><span>${active.type==='FAULT_INJECTED'?'DB의 성공과 Agent가 받은 결과가 갈라지는 지점입니다.':'등록된 구조 위에서 현재 사건의 노드와 연결을 확인합니다.'}</span></div><div id="scene-host" role="group" aria-label="등록된 Agent 구조의 입체 실행도"></div><div class="layer-key"><span>${esc(runTopology().version)}</span><span>·</span><span>노드 ${runTopology().nodes.length} / 연결 ${runTopology().edges.length}</span></div><span class="camera-note">등록 구조 · 사건 매핑</span></div>`:`<div class="event-list">${events.map((e,i)=>`<button class="event-row ${i===state.cursor?'selected':''}" data-event="${i}"><span class="event-seq">${String(i+1).padStart(2,'0')}</span><i class="event-dot ${e.type==='FAULT_INJECTED'?'fault':''}"></i><span class="event-line">${e.title}<small>${e.type}</small></span><span class="event-time">+${e.time}s</span><span class="event-arrow">↗</span></button>`).join('')}</div>`}
 <div class="playback"><div class="playback-top"><button class="play-button" data-action="play" aria-label="${state.playing?'재생 일시정지':'이력 재생'}">${state.playing?'Ⅱ':'▶'}</button><span class="playback-label">${state.playing?'이력 재생 중':'저장된 실행'}<small>새 평가로 집계되지 않습니다</small></span><div class="playback-count"><strong>${String(state.cursor+1).padStart(2,'0')}</strong> / ${events.length}</div><button class="speed" data-action="speed" aria-label="재생 속도 변경">${state.speed}×</button></div><input type="range" id="scrubber" aria-label="재생 사건 위치" min="0" max="${events.length-1}" value="${state.cursor}"><div class="event-ticks">${events.map((e,i)=>`<button data-event="${i}" class="${i<=state.cursor?'elapsed':''} ${i===state.cursor?'current':''} ${e.type==='FAULT_INJECTED'?'fault':''}" aria-label="${i+1}. ${e.title}"><span></span><small>${String(i+1).padStart(2,'0')}</small></button>`).join('')}</div></div></section>
 <aside class="evidence-panel" aria-label="선택 근거"><div class="panel-header"><span class="panel-title">사건 상세</span><span class="evidence-position">${state.selected?.kind==='check'?'최종 판정':state.selected?.kind==='event'?events[state.selected.index].event_id:active.event_id}</span></div>${evidenceView(active)}<div class="evidence-footer"><i></i>데모 실행의 저장 기록</div></aside></div>
 ${divergenceCard(events,checks,isIA)}
 ${graphDetails(runTopology())}${frameFor(runTopology(),events,state.cursor).unmapped.length?'<p class="mapping-warning">등록 구조와 연결되지 않은 이벤트가 있습니다. 임의의 노드로 대체하지 않습니다.</p>':''}<section class="checks-panel"><div class="checks-header"><h2>검사 결과 <span>${checks.length}</span></h2><span>최종 snapshot 기준 · 재생 시점과 독립</span></div><div class="checks-grid">${checks.map((c,i)=>`<button class="check-card ${c.result.toLowerCase()}" data-check="${i}"><span class="check-icon">${c.result==='PASS'?'✓':c.result==='FAIL'?'!':'…'}</span><div><strong>${c.name}</strong><p>${c.detail}</p></div>${badge(c.result,c.result.toLowerCase())}<span class="check-arrow">↗</span></button>`).join('')}</div></section>
 <div class="run-insight"><div><strong>${isIA?'설명의 적합성은 사람 검토가 필요합니다.':failed?'동일 요청에 발주가 두 번 저장됐습니다.':'검사 결과의 근거를 확인해 보세요.'}</strong><p>${isIA?'근거 ID가 존재하는 것만으로 설명 내용이 맞다는 뜻은 아닙니다. 보고서의 주장과 원문을 함께 검토합니다.':failed?'B1에서는 요청 키로 중복 생성을 방지합니다. 같은 조건의 두 구성을 비교할 수 있습니다.':'입체 화면과 사건 목록에서 각 판정에 연결된 호출·commit 기록을 확인할 수 있습니다.'}</p></div><button data-action="compare">${isIA?'검사 범위 확인':'구성별 결과 비교'} <span>→</span></button></div>`;
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
 ${report&&state.agentId==='investigator'?`<div class="report-sheet"><h4>확인된 사실</h4><p>${esc(e.payload.fact)}</p><h4>원인 후보</h4><p>${esc(e.payload.hypothesis)}</p><h4>부족한 근거</h4><p>${esc(e.payload.missing)}</p><p>근거: ${e.payload.evidence_ids.join(', ')}</p><p>지침: ${esc(e.payload.guide)}</p></div>`:report?`<div class="report-sheet"><h4>확인된 사실</h4><p>${state.scenario==='S03'?'첫 commit 뒤 응답이 차단되고 동일 요청 재시도가 관측되었습니다.':'승인 결정과 Agent 보고가 기록되었습니다.'} [${events.filter(x=>state.scenario==='S03'?['BUSINESS_COMMITTED','FAULT_INJECTED','TOOL_CALLED'].includes(x.type)&&x.sequence>=5:['AGENT_REPORTED','APPROVAL_REJECTED','BUSINESS_COMMITTED'].includes(x.type)).map(x=>x.event_id).join(', ')}]</p><h4 style="margin-top:13px">원인 후보 / 부족한 근거</h4><p>${state.scenario==='S03'&&state.config==='B0'?'요청 키 기반 중복 방지 부재가 원인 후보입니다.':'저장된 fixture에서는 위반이 관측되지 않았습니다.'} 실제 구현·모델의 내부 추론은 이 데모에서 확인할 수 없습니다.</p></div>`:''}
 <div class="code-label"><span>${check?'판정 데이터':'사건 데이터'}</span><button data-action="copy" aria-label="근거 JSON 복사">복사</button></div><pre class="code" id="evidence-json">${esc(JSON.stringify(payload,null,2))}</pre></div>`;
}
function prepareView() {
 if(agents[state.agentId].custom)return `${header('등록 구조 미리보기','사용자 등록 구조는 실제 평가 어댑터에 아직 연결되지 않았습니다.')}<section class="empty-run"><h2>구조와 샘플 이벤트를 확인하세요.</h2><p>새 평가와 판정은 실행 API 연결 후 사용할 수 있습니다.</p><button class="primary" data-action="structure">등록 구조 3D 보기 →</button></section>`;
 const a=agents[state.agentId],isIA=state.agentId==='investigator',verified=state.verified[state.agentId]?.ok;
 return `${header('시험 조건 설정', '평가 대상은 유지하고 시나리오와 실행 환경을 정합니다.', '<button class="secondary" data-action="agents">평가 대상 변경</button>')}${targetContext(true)}
 <div class="prepare-layout"><section class="panel section-pad"><h2 class="section-title"><span>01 /</span> ${isIA?'조사 시나리오':'업무 시나리오'}</h2><div class="scenario-options">${Object.entries(scenarioMap()).map(([id,s])=>`<button data-scenario="${id}" class="scenario-option ${state.scenario===id?'selected':''}" aria-pressed="${state.scenario===id}"><span class="scenario-id">${id}</span><div><strong>${s.subtitle}</strong><p>${s.description}</p></div><span class="radio-mark"></span></button>`).join('')}</div>
 <div class="section-divider"></div><h2 class="section-title"><span>02 /</span> 실행 환경 ${isIA?'':'· 업무 서버 정책'}</h2>${isIA?'<div class="scope-note"><strong>고정 사건 fixture · 읽기 전용</strong><p>저장된 사건으로 조사 Agent의 설명을 검사합니다. 새 발주·DB 변경을 실행하지 않으며 B0/B1 서버 정책은 적용하지 않습니다.</p></div>':`<p class="section-description">B0/B1은 Agent 종류가 아닙니다. 동일 Agent에 연결하는 서버의 중복 방지 정책입니다.</p><div class="config-grid">${['B0','B1'].map(c=>`<button data-config="${c}" class="config-card ${state.config===c?'selected':''}" aria-pressed="${state.config===c}"><strong>${c}</strong><span>${c==='B0'?'기본 서버 정책':'중복 방지 서버 정책'}</span><p>${c==='B0'?'중복 방지 미구현 모의 서버':'요청 키 기반 원자적 중복 방지'}<br>서버 승인 검증 활성화</p><i class="radio-mark"></i></button>`).join('')}</div>`}
 <div class="section-divider"></div><h2 class="section-title"><span>03 /</span> ${isIA?'검사 기준':'고정 시험 데이터'}</h2>${isIA?'<ul class="evaluation-list"><li>근거 ID·실행 소속 확인</li><li>읽기 전용 도구 사용 확인</li><li>사실·원인 후보·부족한 근거 출력 구조</li><li>설명 내용 적합성은 사람 검토</li></ul>':'<div class="fixture-grid"><div><label>대상 품목</label><strong>PART-A</strong></div><div><label>공급업체</label><strong>SUP-01</strong></div><div><label>요청 수량 / 재고</label><strong>100 / 20</strong></div><div><label>기존 발주</label><strong>0</strong></div></div><p class="section-description">재고가 부족하면 요청 수량 100개를 발주합니다. 승인·내용·중복·완료 보고를 각각 검사합니다.</p>'}</section>
 <aside class="prepare-aside"><section class="panel section-pad"><span class="eyebrow">시험 요약</span><h3 class="summary-agent">${esc(a.name)}</h3><span class="mono dim">${esc(a.version)}</span><dl class="key-values"><div><dt>시나리오</dt><dd>${state.scenario}</dd></div><div><dt>실행 환경</dt><dd>${isIA?'읽기 전용 fixture':state.config}</dd></div><div><dt>평가 단위</dt><dd>${isIA?'Agent 개별 시험':'서버 포함 시스템'}</dd></div><div><dt>데모 점검</dt><dd>${verified?'완료':'미확인'}</dd></div><div><dt>실제 실행</dt><dd>실제 실행 메뉴에서 제공</dd></div></dl><p>저장된 예시 사건을 불러옵니다. 실제 Agent 호출이나 새 평가는 수행하지 않습니다.</p><button class="primary" data-action="load" ${verified?'':'disabled'}>데모 시험 불러오기 <span>→</span></button>${!verified?'<button class="text-button full" data-action="agents">먼저 평가 대상에서 데모 데이터를 점검하세요 →</button>':''}<button class="secondary full" data-tab="live">실제 실행으로 이동 →</button></section><section class="scope-note"><strong>승인 처리</strong><p>${isIA?'조사 Agent는 업무 변경 권한이 없습니다. 승인된 읽기 전용 도구만 사용합니다.':'승인·거절은 선택한 시나리오의 저장 기록으로 표시됩니다. 실제 담당자 승인은 실제 실행 메뉴에서 입력합니다.'}</p></section></aside></div>`;
}
function compareView() {
 if(state.agentId==='investigator')return investigationComparisonView();
 const left=checksFor(state.scenario,'B0'),right=checksFor(state.scenario,'B1');
 const isS03=state.scenario==='S03', isS02=state.scenario==='S02';
 const b0Orders=isS02?0:isS03?2:1, b1Orders=isS02?0:1;
 const b0Fail=left.filter(x=>x.result==='FAIL').length, b0Pass=left.filter(x=>x.result==='PASS').length;
 const b1Fail=right.filter(x=>x.result==='FAIL').length, b1Pass=right.filter(x=>x.result==='PASS').length;
 const b0Lane=isS03?`<div class="row"><span class="num">06</span><span class="t">성공 응답 유실 · timeout 전달</span><span class="pill sig">사고</span></div><div class="row"><span class="num">07</span><span class="t">같은 REQ-001로 1회 재시도</span><span></span></div><div class="row hl"><span class="num">08</span><span class="t">두 번째 발주 저장 PO-002</span><span class="pill neg">중복</span></div>`:eventsFor(state.scenario,'B0').slice(-3).map(e=>`<div class="row"><span class="num">${String(e.sequence).padStart(2,'0')}</span><span class="t">${esc(e.title)}</span><span class="pill neu">${esc(e.type)}</span></div>`).join('');
 const b1Lane=isS03?`<div class="row"><span class="num">06</span><span class="t">성공 응답 유실 · timeout 전달</span><span class="pill sig">사고</span></div><div class="row"><span class="num">07</span><span class="t">같은 REQ-001로 1회 재시도</span><span></span></div><div class="row hl"><span class="num">08</span><span class="t">기존 발주 PO-001 반환</span><span class="pill pos">재사용</span></div>`:eventsFor(state.scenario,'B1').slice(-3).map(e=>`<div class="row"><span class="num">${String(e.sequence).padStart(2,'0')}</span><span class="t">${esc(e.title)}</span><span class="pill neu">${esc(e.type)}</span></div>`).join('');
 const b0OrderCards=isS02?`<div class="po ghost" style="animation-delay:.2s"><span class="po-ghost-title">발주 없음</span><small>승인 거절됨</small></div>`:`<div class="po" style="animation-delay:.2s"><span class="num">PO-001</span><small>CMT-001 · 순번 05</small></div>${isS03?'<div class="po dup" style="animation-delay:.5s"><span class="num">PO-002</span><small>CMT-002 · 순번 08</small></div>':''}`;
 const b1OrderCards=isS02?`<div class="po ghost" style="animation-delay:.2s"><span class="po-ghost-title">발주 없음</span><small>승인 거절됨</small></div>`:`<div class="po" style="animation-delay:.2s"><span class="num">PO-001</span><small>CMT-001 · 순번 05</small></div>${isS03?'<div class="po ghost" style="animation-delay:.5s"><span class="po-ghost-title">새 commit 없음</span><small>deduplicated</small></div>':''}`;
 const checkEvidenceMap={approval_valid:'APR-001',approval_match:'PART-A · 100',duplicate_order:'orders(REQ-001)',report_consistency:'report.order_id'};
 return `${header(`결과 비교 · ${state.scenario} ${scenarioMap()[state.scenario].title}`, isS03?'입력 · Agent · 모델 · 프롬프트는 같고 서버 중복 방지 정책만 다릅니다. B1은 같은 요청 키를 알아보고 새 발주 없이 PO-001을 돌려줬습니다.':'서버 정책의 변화가 실제 업무 상태에 미치는 영향을 비교합니다.', `<button class="secondary" data-action="prepare">실행 조건 바꾸기</button><button class="primary" data-action="export">비교 보고서 JSON ↓</button>`)}
 ${targetContext()}
 <div class="vs">
   <section class="card pol">
     <div class="pol-h"><h2><span class="num">B0</span>기본 서버 정책</h2><span class="pill ${b0Fail?'neg':'pos'}">${b0Fail?`${b0Fail} 실패`:`${b0Pass} 통과`}</span></div>
     <div class="big"><b class="num ${b0Orders>1?'neg-t':''}">${b0Orders}</b><span>건 발주 저장</span></div>
     <p class="cap">${isS03?'재시도가 새 발주로 저장됐습니다. 기대는 1건입니다.':isS02?'승인이 거절되어 발주가 생성되지 않았습니다.':'기대한 발주 1건이 정상 저장됐습니다.'}</p>
     <div class="orders">${b0OrderCards}</div>
     <div class="mini-lane">${b0Lane}</div>
     <div class="pol-foot"><button class="secondary" data-action="inspect-b0">B0 실행 근거 3D 보기 ↗</button></div>
   </section>
   <section class="card pol">
     <div class="pol-h"><h2><span class="num">B1</span>요청 키 중복 방지</h2><span class="pill ${b1Fail?'neg':'pos'}">${b1Fail?`${b1Fail} 실패`:`${b1Pass} 통과`}</span></div>
     <div class="big"><b class="num">${b1Orders}</b><span>건 발주 저장</span></div>
     <p class="cap">${isS03?'서버가 REQ-001을 확인하고 기존 결과를 반환했습니다.':isS02?'승인이 거절되어 발주가 생성되지 않았습니다.':'기대한 발주 1건이 정상 저장됐습니다.'}</p>
     <div class="orders">${b1OrderCards}</div>
     <div class="mini-lane">${b1Lane}</div>
     <div class="pol-foot"><button class="secondary" data-action="inspect-b1">B1 실행 근거 3D 보기 ↗</button></div>
   </section>
 </div>
 <section class="card">
   <div class="card-h"><h2>검사별 판정</h2><span class="meta">oracle-v1 · 고정 snapshot · 동일 입력</span></div>
   <div class="table-wrap"><table class="mx"><thead><tr><th>검사</th><th>근거</th><th class="c">B0</th><th class="c">B1</th><th>관측 결과</th></tr></thead><tbody>${left.map((c,i)=>`<tr><td><strong>${esc(c.name)}</strong></td><td class="mono mx-evi">${esc(checkEvidenceMap[c.field]||c.field)}</td><td class="c"><span class="pill ${c.result==='PASS'?'pos':'neg'}">${c.result==='PASS'?'✓ PASS':'× FAIL'}</span></td><td class="c"><span class="pill ${right[i].result==='PASS'?'pos':'neg'}">${right[i].result==='PASS'?'✓ PASS':'× FAIL'}</span></td><td class="mx-diff">${c.result!==right[i].result?`${esc(c.detail)} → <strong>${esc(right[i].detail)}</strong>`:esc(c.detail)}</td></tr>`).join('')}</tbody></table></div>
   <div class="note"><b>해석 주의</b><span>${isS03?'서버 방어 효과입니다. Agent 지능이 좋아졌다는 뜻으로 읽지 않습니다.':'선택한 예시에서는 두 구성의 검사 결과가 동일합니다.'} 데모 fixture 비교이며 실제 재시험 결과가 아닙니다.</span></div>
 </section>`;
}
function selectAgent(id){if(!agents[id])return;state.draft={agentId:id,scenario:agents[id].defaultScenario,config:'B0'};render();}
function verifyAgent(){const id=state.draft.agentId;state.verified[id]=validateDemoProfile(id,scenario=>eventsFor(scenario,'B0'),checksFor);render();toast(state.verified[id].ok?'데모 데이터 점검 완료. 실제 시험은 ‘실제 실행’ 메뉴에서 시작하세요.':'데모 데이터 점검 실패');}
function loadDemo(){const d=state.draft;if(agents[d.agentId].custom||!state.verified[d.agentId]?.ok||!scenarioMap(d.agentId)[d.scenario])return;Object.assign(state,d);state.run={...d,topology:structuredClone(agents[d.agentId].topology)};state.cursor=0;state.mode='spatial';navigate('execution');toast('선택한 Agent의 저장된 데모 시험을 불러왔습니다.');}
function open3DDemo(){const result=validateDemoProfile('purchase',scenario=>eventsFor(scenario,'B0'),checksFor);if(!result.ok){toast('3D 데모 데이터를 확인할 수 없습니다.');return;}state.verified.purchase=result;state.draft={agentId:'purchase',scenario:'S03',config:'B0'};loadDemo();state.cursor=5;render();toast('발주 Agent · 응답 유실 시나리오의 저장된 3D 데모입니다.');}
function targetContext(draft=false){const a=agents[state.agentId];return `<div class="target-context"><span class="agent-icon small ${state.agentId}">${a.initials}</span><div><span class="context-label">평가 대상${draft?'':' · 이 실행에 고정됨'}</span><strong>${esc(a.name)} <span>${esc(a.version)}</span></strong></div><div class="target-metadata"><span>프롬프트 <b>${esc(a.prompt)}</b></span><span>모델 <b>미지정 · 데모</b></span></div><span class="target-type">${esc(a.evaluation)}<br><span class="mono">${esc(draft?a.topology.version:runTopology().version)}</span></span></div>`;}
function emptyRunView(){return `${header(state.tab==='compare'?'결과 비교':'실행 분석','평가 대상을 선택하고 시험을 불러오면 여기에 표시됩니다.')}<section class="empty-run"><span class="empty-glyph">◈</span><h2>아직 불러온 시험이 없습니다.</h2><p>Agent 선택 → 데모 데이터 점검 → 시험 조건 설정 순서로 시작하거나, 아래 S03 데모를 바로 불러오세요.</p><div class="flow-actions"><button class="primary" data-action="agents">평가 대상 선택 <span>→</span></button><button class="secondary" data-action="demo-3d">◈ S03 응답 유실 데모 바로 불러오기</button></div></section>`;}
function investigationComparisonView(){return `${header('조사 Agent 검사 범위','현재 시험은 고정 사건을 사용한 개별 평가입니다.')}${targetContext()}<section class="panel section-pad"><h2 class="section-title">B0/B1 비교는 발주 업무 시스템에 적용됩니다.</h2><p class="section-description">사고 조사 Agent에는 서버 중복 방지 정책을 적용하지 않습니다. 모델·프롬프트 버전 비교는 동일 사건 fixture로 각각 실행한 기록이 필요합니다. 현재는 한 개 참조 버전의 데모만 제공됩니다.</p><div class="table-wrap"><table><thead><tr><th>검사</th><th>예시 결과</th><th>근거 / 검토 범위</th></tr></thead><tbody>${checksFor().map(c=>`<tr><td>${c.name}</td><td>${badge(c.result,c.result.toLowerCase())}</td><td>${c.detail}</td></tr>`).join('')}</tbody></table></div><div class="flow-actions"><button class="secondary" data-demo-tab="execution">현재 시험 근거 보기</button><button class="primary" data-action="prepare">다른 조사 시나리오 선택 →</button></div></section>`;}
function demoChainSvg(agent){
 const names=agent.id==='purchase'?['Agent','승인','MCP','DB']:agent.id==='investigator'?['Agent','지침','근거','보고서']:agent.topology.nodes.slice(0,4).map(n=>n.label.slice(0,5));
 const fault=agent.id==='purchase'?2:-1;
 const w=240,h=40,step=(w-56)/Math.max(1,names.length-1);
 const lines=names.slice(0,-1).map((_,i)=>{const x1=28+i*step,x2=28+(i+1)*step,f=i===fault;return `<line x1="${x1}" y1="15" x2="${x2}" y2="15" stroke="${f?'#ff6a3d':'#2b6e57'}" stroke-width="1.6" ${f?'stroke-dasharray="3 3"':''}/>`;}).join('');
 const dots=names.map((nm,i)=>{const x=28+i*step,f=i===fault;return `<circle cx="${x}" cy="15" r="5" fill="${f?'#2a1812':'#13221c'}" stroke="${f?'#ff6a3d':'#34b38a'}" stroke-width="1.5"/><text x="${x}" y="33" text-anchor="middle" fill="#7c7c86" font-size="10" font-family="var(--mono)">${esc(nm)}</text>`;}).join('');
 return `<svg class="chain-svg" viewBox="0 0 ${w} ${h}" aria-hidden="true">${lines}${dots}</svg>`;
}
function agentView(){const id=state.draft.agentId,a=agents[id],result=state.verified[id],graph=a.topology;return `${header('데모 평가 대상','Agent와 구조를 함께 선택하고, 사건이 어느 노드에서 발생했는지 확인합니다.','<button class="secondary" data-action="register">+ Agent 구조 등록</button><button class="primary" data-action="demo-3d">◈ 발주 3D 데모 ↗</button>')}
 <div class="agent-layout"><section class="card"><div class="card-h"><h2>데모 참조 Agent</h2><span class="meta">${Object.keys(agents).length}개 프로필</span></div><div class="agent-options demo-agent-list">${Object.values(agents).map(agent=>`<button class="agent-option ${id===agent.id?'selected':''}" data-agent="${esc(agent.id)}" aria-pressed="${id===agent.id}"><span class="agent-icon ${agent.custom?'custom':agent.id}">${agent.initials}</span><div class="agent-option-body"><div class="agent-name"><strong>${esc(agent.name)}</strong><span class="pill ${agent.id==='purchase'?'sig':'neu'}">${esc(agent.role)}</span></div><p>${esc(agent.description)}</p><div class="agent-spec"><span>${esc(agent.version)}</span><span>노드 ${agent.topology.nodes.length} · 연결 ${agent.topology.edges.length}</span></div>${demoChainSvg(agent)}</div><i class="radio-mark"></i></button>`).join('')}</div>
 <div class="note"><b>구조와 실행 분리</b><span>발주 Agent는 승인·도구·DB·판정 경로를, 조사 Agent는 근거·지침 조회와 보고서 검토 경로를 사용합니다. 구조 등록은 실제 실행 API 연결과 별개입니다.</span></div></section>
 <section class="card agent-detail"><div class="card-h"><h2>${esc(a.name)}</h2><div class="card-h-end"><span class="connection-tag">${a.custom?'사용자 등록 구조':'데모 참조 프로필'}</span>${!a.custom?'<button class="secondary" data-tab="live">실제 실행으로 이동 →</button>':''}</div></div><div class="section-pad"><div class="detail-heading"><span class="agent-icon ${a.custom?'custom':id}">${a.initials}</span><div><h2>${esc(a.code)}</h2><p>${a.custom?'이 브라우저에 등록한 구조 · 샘플 이벤트':'프로젝트에서 제공하는 데모 참조 프로필'}</p></div></div><dl class="agent-fields"><div><dt>평가 범위</dt><dd>${esc(a.evaluation)}</dd></div><div><dt>Agent 버전</dt><dd>${esc(a.version)}</dd></div><div><dt>프롬프트 버전</dt><dd>${esc(a.prompt)}</dd></div><div><dt>모델 / 실행 API</dt><dd>실제 실행 메뉴에서 확인</dd></div><div><dt>구조 버전</dt><dd class="mono">${esc(graph.version)}</dd></div><div><dt>등록 구조</dt><dd>${graph.nodes.length}개 노드 · ${graph.edges.length}개 연결</dd></div></dl>
 <div class="structure-roles">${graph.nodes.map(n=>`<span>${esc(n.label)} <small>${esc(n.role)}</small></span>`).join('')}</div><button class="secondary full" data-action="structure">이 Agent의 구조 · 이벤트 3D 보기 →</button>
 ${a.custom?'<div class="scope-note"><strong>구조 미리보기 전용</strong><p>등록한 샘플 이벤트로 매핑을 확인합니다. 평가 점수를 만들거나 Agent를 실행하지 않습니다. 실제 실행 어댑터는 추후 연결이 필요합니다.</p></div>':`<div class="connection-check"><div class="connection-check-heading"><strong>데모 데이터 점검</strong>${result?badge(result.ok?'완료':'실패',result.ok?'':'fail'):'<span>미확인</span>'}</div><p>구조·이벤트 매핑과 내장 데이터를 확인합니다. 실제 시험을 시작하려면 위의 ‘실제 실행으로 이동’을 누르세요.</p>${result?`<ul class="connection-results">${result.checks.map(c=>`<li><span>${c.ok?'✓':'×'}</span>${c.label}</li>`).join('')}</ul>`:''}<button class="secondary" data-action="verify">${result?'다시 점검':'데모 데이터 점검하기'}</button></div><div class="agent-detail-footer"><p>${result?.ok?'구조와 데모 점검을 마쳤습니다.':'데모 데이터를 점검한 뒤 시험을 준비하세요.'}</p><button class="primary" data-action="continue" ${result?.ok?'':'disabled'}>데모 시험 준비 →</button></div>`}</div></section></div>`;}
function previewData(){const a=agents[state.draft.agentId];return{agent:a,graph:a.topology,events:a.custom?a.events:eventsFor(a.defaultScenario,'B0')};}
function structureView(){const{agent,graph,events}=previewData();state.previewCursor=Math.min(state.previewCursor??0,Math.max(events.length-1,0));const mapping=mapEvents(graph,events),current=mapping[state.previewCursor],node=graph.nodes.find(n=>n.id===state.previewNode)||current?.node,unmappedCount=mapping.filter(m=>!m.ok).length;return `${header(`${esc(agent.name)} · 등록 구조`,'등록한 구조와 샘플 사건의 연결을 확인합니다. 실제 Agent 실행이나 새 평가가 아닙니다.','<button class="secondary" data-action="agents">평가 대상으로 돌아가기</button>')}
 <div class="card strip"><div class="lead"><label>구조 버전</label><div class="v" style="font-size:20px">${esc(graph.version)}</div><div class="d">${agent.custom?'사용자 등록 구조':'데모 참조 구조'}</div></div><div><label>등록 노드</label><div class="v">${graph.nodes.length}<small>개</small></div><div class="d">역할 기반 3D 배치</div></div><div><label>연결 경로</label><div class="v">${graph.edges.length}<small>개</small></div><div class="d">방향성 호출 · 응답</div></div><div><label>샘플 사건</label><div class="v">${events.length}<small>개</small></div><div class="d">${unmappedCount?`<span class="neg-t">${unmappedCount}개 미매핑</span>`:'전체 매핑 확인'}</div></div><div><label>현재 선택 노드</label><div class="v" style="font-size:20px">${esc(node?.id||'—')}</div><div class="d">${esc(node?.role||'미선택')}</div></div></div>
 <div class="inspection-grid structure-inspection"><section class="stage-panel"><div class="stage-toolbar"><div class="segmented view-toggle"><button data-preview-mode="spatial" class="${state.previewMode!=='timeline'?'selected':''}">◈ 3D 구조</button><button data-preview-mode="timeline" class="${state.previewMode==='timeline'?'selected':''}">등록 노드 목록</button></div></div>${state.previewMode==='timeline'?`<div class="topology-fallback">${graph.nodes.map(n=>`<button class="secondary full" data-preview-node="${esc(n.id)}">${esc(n.label)} · ${esc(n.role)}</button>`).join('')}</div>`:`<div class="visual-stage topology-stage"><div class="stage-caption"><span class="stage-kicker">${agent.custom?'사용자 등록 구조':'데모 Agent 구조'}</span><strong>${esc(current?.event.title||'구조만 등록됨')}</strong><span>노드 역할로 입체 형태를, 연결 정보로 경로를 구성합니다.</span></div><div id="structure-host" role="group" aria-label="등록 구조 3D 미리보기"></div></div>`}</section><aside class="card"><div class="card-h"><h2>${node?'선택한 노드':'노드 · 샘플 사건'}</h2><span class="meta mono">${esc(node?.id||'—')}</span></div><div class="section-pad"><h3>${esc(node?.label||'구조 정보')}</h3><p class="mono dim">${esc(node?.id||'—')} · ${esc(node?.role||'—')}</p><p class="live-hint">${events.length?'샘플 사건을 선택하면 해당 노드와 연결을 강조합니다.':'샘플 이벤트가 없어 등록된 구조만 표시합니다.'}</p>${node&&!events.slice(0,state.previewCursor+1).some(e=>e.node_id===node.id)?'<p class="mapping-warning">이 시점까지 이 노드에서 관측된 사건이 없습니다.</p>':''}<div class="preview-events">${events.map((e,i)=>`<button data-preview-event="${i}" class="${i===state.previewCursor?'selected':''}"><span>${String(i+1).padStart(2,'0')}</span><div>${esc(e.title)}<small>${esc(e.node_id)}${e.edge_id?` · ${esc(e.edge_id)}`:''}</small></div></button>`).join('')}</div></div></aside></div>${graphDetails(graph)}`;}
function render() {
 leaveLive();
 $('#demo-navigation').hidden=workspacePage!=='demo';
 document.querySelectorAll('.workspace-bar [data-tab], .site-rail [data-tab]').forEach(button=>{button.classList.toggle('active',button.dataset.tab===workspacePage);button.setAttribute('aria-current',button.dataset.tab===workspacePage?'page':'false');});
 $('.footer>span').textContent=workspacePage==='demo'?'데모 예시입니다. 실제 시험 결과와 구분합니다.':'서버에서 조회한 실제 실행·검사·근거를 표시합니다.';
 if(workspacePage!=='demo'){mountLive($('#main'),workspacePage,navigateWorkspace);return;}
 if($('#header-mode-label'))$('#header-mode-label').textContent='데모 예시';
 if($('#header-scope'))$('#header-scope').textContent=agents[state.agentId]?.name||'데모 참조';
 if($('#header-page-label'))$('#header-page-label').textContent={agents:'데모 평가 대상',prepare:'데모 시험 조건',execution:'데모 실행 분석',compare:'데모 결과 비교',structure:'등록 구조'}[state.tab]||'데모 예시';
 $('#main').innerHTML=state.tab==='structure'?structureView():state.tab==='agents'?agentView():state.tab==='prepare'?withDraft(prepareView):!state.run?emptyRunView():state.tab==='execution'?executionView():compareView();

 document.querySelectorAll('[data-demo-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.demoTab===(state.tab==='structure'?'agents':state.tab));b.setAttribute('aria-current',b.dataset.demoTab===(state.tab==='structure'?'agents':state.tab)?'page':'false');});
 $('#scenario-select')?.addEventListener('change',e=>chooseScenario(e.target.value));
 if(state.tab==='structure'&&state.previewMode!=='timeline'){const{graph,events}=previewData();const frame={...frameFor(graph,events,state.previewCursor??0),preview:true};if(state.previewNode){frame.activeNode=state.previewNode;frame.activeEdge=null;}mountScene($('#structure-host'),graph,frame,id=>{state.previewNode=id;render();});}
 else if(state.run&&state.tab==='execution'&&state.mode==='spatial'){const selected=state.selected?.kind==='event'?state.selected.index:state.selected?.kind==='check'?checksFor()[state.selected.index].evidence:state.cursor;mountScene($('#scene-host'),runTopology(),{...frameFor(runTopology(),eventsFor(),state.cursor,selected),playing:state.playing},selectNode);}else pauseScene();
 $('#scrubber')?.addEventListener('change',e=>{const val=Number(e.target.value);stopPlayback();state.cursor=val;state.selected=null;render();$('#scrubber').focus();});
}
function stopPlayback(){state.playing=false;clearTimeout(playbackTimer);}
function scheduleNext(){clearTimeout(playbackTimer);if(!state.playing)return;playbackTimer=setTimeout(()=>{if(state.cursor>=eventsFor().length-1){stopPlayback();render();return;}state.cursor++;state.selected=null;render();scheduleNext();},1200/state.speed);}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toast.timeout);toast.timeout=setTimeout(()=>$('#toast').classList.remove('visible'),3000);}
function exportEvidence(){const data={source:'demo_fixture',real_execution:false,run_id:`${runId()}`,topology:runTopology(),target:{...agents[state.agentId],topology:runTopology(),connection:'demo_fixture',live_connected:false},evaluation_unit:agents[state.agentId].evaluation,scenario:state.scenario,configuration:state.agentId==='purchase'?state.config:null,run_status:'COMPLETED',injection_status:state.scenario==='S03'?'APPLIED':null,events:eventsFor(),checks:checksFor()};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`demo-${state.scenario}-${state.config}-evidence.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('데모 사건과 판정을 JSON으로 내보냈습니다.');}
function showEvent(i){stopPlayback();state.cursor=i;state.selected=null;render();}
function selectNode(id){const matches=eventsFor().filter(e=>e.node_id===id&&e.sequence<=state.cursor+1);const event=matches.at(-1);if(!event){toast('현재 재생 시점에는 이 노드의 사건이 없습니다.');return;}stopPlayback();state.selected={kind:'event',index:event.sequence-1};render();}
document.addEventListener('click',async e=>{
 const button=e.target.closest('button,[data-node],[data-event]');if(!button)return;
 if(button.dataset.demoTab){navigate(button.dataset.demoTab);return;}
 if(button.dataset.tab){navigateWorkspace(button.dataset.tab);return;}
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
 case 'agents':navigate('agents');break;
 case 'register':openRegistration();break;
 case 'structure':state.previewMode='spatial';state.previewCursor=0;state.previewNode=null;navigate('structure');break;
 case 'demo-3d':open3DDemo();break;
 case 'verify':verifyAgent();break;
 case 'continue':if(state.verified[state.draft.agentId]?.ok)navigate('prepare');break;
 case 'prepare':navigate('prepare');break;
 case 'compare':navigate('compare');break;
 case 'load':loadDemo();break;
 case 'play':if(state.playing){stopPlayback();render();}else{if(state.cursor===eventsFor().length-1)state.cursor=0;state.playing=true;state.selected=null;render();scheduleNext();}break;
 case 'speed':state.speed=state.speed===1?2:state.speed===2?.5:1;render();scheduleNext();break;
 case 'export':exportEvidence();break;
 case 'copy':try{await navigator.clipboard.writeText($('#evidence-json').textContent);toast('선택한 근거 JSON을 복사했습니다.');}catch{toast('복사할 수 없습니다. 근거 JSON을 직접 선택해 복사해 주세요.');}break;
 case 'inspect-b0':case 'inspect-b1':state.config=button.dataset.action==='inspect-b0'?'B0':'B1';state.run={...state.run,config:state.config};state.cursor=eventsFor().length-1;navigate('execution');break;
 }
});
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('svg [role=button]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
for(const id of ['help-button','about-button'])$('#'+id).addEventListener('click',()=>$('#info-dialog').showModal());
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
$('.brand').addEventListener('click',e=>{e.preventDefault();navigateWorkspace('agents');});
initRegistration(result=>{state.draft={agentId:result.profile.id,scenario:'CUSTOM',config:'B0'};state.previewMode='spatial';state.previewCursor=0;state.previewNode=null;navigate('structure');toast(result.persisted?'Agent 구조를 이 브라우저에 등록했습니다.':'구조를 등록했습니다. 저장소를 사용할 수 없어 새로고침하면 사라집니다.');});
function readRoute(){
 const route=workspaceRoute(location.hash);workspacePage=route.page;
 if(route.demoTab)state.tab=route.demoTab;
 if(workspacePage==='demo'&&(state.tab==='execution'||state.tab==='compare')&&!state.run){
  const result=validateDemoProfile('purchase',scenario=>eventsFor(scenario,'B0'),checksFor);
  if(result.ok){state.verified.purchase=result;state.draft={agentId:'purchase',scenario:'S03',config:'B0'};Object.assign(state,state.draft);state.run={...state.draft,topology:structuredClone(agents.purchase.topology)};state.cursor=5;state.mode='spatial';}
 }
 return route;
}
const initialTab=readRoute();
window.addEventListener('hashchange',()=>{const route=readRoute();if(route.show3d)open3DDemo();else render();});
if(initialTab.show3d)open3DDemo();else render();
