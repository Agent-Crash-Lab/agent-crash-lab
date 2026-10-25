// Only public user-session tokens cross this boundary; internal headers are server-owned.
export async function api(path, {token, body, signal} = {}) {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST', signal, cache: 'no-store',
    headers: {Accept:'application/json', ...(token ? {Authorization:`Bearer ${token}`} : {}),
      ...(body === undefined ? {} : {'Content-Type':'application/json'})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})
  });
  let data;
  try { data = await response.json(); }
  catch {
    const error = new Error(`API 응답을 읽을 수 없습니다 (${response.status}). MCP·Harness 연결을 확인해 주세요.`);
    error.status=response.status; throw error;
  }
  if (!response.ok) {
    const error = new Error(data.error?.message || data.error?.code || `요청 실패 (${response.status})`);
    error.code = data.error?.code; error.status = response.status; error.details = data.error?.details;
    throw error;
  }
  return data;
}
export function mergeEvents(existing, incoming, runId) {
  const bySequence = new Map(existing.map(event => [event.sequence, event]));
  for (const event of incoming) {
    if (event.run_id !== runId || !Number.isInteger(event.sequence) || event.sequence < 1) throw new Error('실행 이벤트 형식이 맞지 않습니다.');
    bySequence.set(event.sequence, event);
  }
  return [...bySequence.values()].sort((a,b) => a.sequence - b.sequence);
}
export function isFinished(run) {
  return ['COMPLETED','ERROR'].includes(run.status) && run.investigation?.status !== 'RUNNING';
}
export function sceneEvents(events) {
  return events.map(event => ({...event, type:event.event_type, title:event.event_type,
    // An approval decision is shown at the approval node; the original node remains in raw evidence.
    node_id:event.event_type.startsWith('APPROVAL_') ? 'approval' : event.node_id}));
}
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function caseReadinessLabel(execution) {
  if(execution.status==='READY')return '실행 가능';
  const missing=execution.missing_capabilities || [];
  if(missing.includes('generated_data_validation'))return '시험 데이터 보완 필요';
  if(missing.some(x=>['design_prerequisites','design_review'].includes(x)))return '시험 조건 보완 필요';
  if(missing.some(x=>['supporting_evidence','research_evidence','adopted_business_policy'].includes(x)))return '근거·정책 보완 필요';
  return '실행 기능 연결 필요';
}

export function caseBlockerMarkup(execution) {
  if(execution.status==='READY')return '';
  const reason=execution.reason==='Requires a registered target/data adapter and code evaluator'
    ? '이 시험을 재현할 실행기·시험 데이터와 결과 판정 기능이 연결되지 않았습니다.'
    : execution.reason || '구체적인 보류 사유가 제공되지 않았습니다. 상세 조건의 필요 항목을 확인하세요.';
  return `<div class="case-blocker"><p><strong>실행 보류 사유:</strong> ${escapeHtml(reason)}</p><p class="live-hint">아래 상세 조건에서 필요한 보완 항목을 확인하세요. 다른 실행 가능한 시험을 선택할 수 있습니다.</p></div>`;
}


export const agentForTest = test => test.test_kind === 'INVESTIGATION_AGENT' ? 'investigator' : 'purchase';
export function testsForAgent(catalog, agent) {
  return catalog.tests.filter(test => agentForTest(test) === agent);
}
export function normalizeDraft(catalog, draft) {
  const agent = draft.agent === 'investigator' ? 'investigator' : 'purchase';
  const tests = testsForAgent(catalog, agent);
  const test = tests.find(test => test.test_id === draft.test_id) || tests[0];
  const system = catalog.systems.find(system => system.system_id === draft.system_id) || catalog.systems[0];
  return {agent, test_id:test?.test_id || '', system_id:system?.system_id || ''};
}
export function startPayload(catalog, draft) {
  const test = testsForAgent(catalog, draft.agent).find(test => test.test_id === draft.test_id);
  if (!test) throw new Error('선택한 평가 대상의 시나리오를 다시 확인해 주세요.');
  if (test.test_kind === 'SYSTEM' && !catalog.systems.some(system => system.system_id === draft.system_id)) throw new Error('서버 정책을 선택해 주세요.');
  return {test_id:test.test_id, ...(test.test_kind === 'SYSTEM' ? {system_id:draft.system_id} : {})};
}

export function designStartPayload(catalog, plan, caseId, systemId) {
  const selected=plan?.cases.find(c=>c.case_id===caseId);
  if (!plan?.plan_id || selected?.execution.status!=='READY') throw new Error('실행 가능한 설계 시험을 먼저 선택해 주세요.');
  if (!catalog?.systems.some(s=>s.system_id===systemId)) throw new Error('시험 설계에서 서버 정책을 확인해 주세요.');
  return {plan_id:plan.plan_id,case_id:caseId,system_id:systemId};
}

export const runDestination = run => ['COMPLETED','ERROR'].includes(run.status) ? 'execution' : 'live';
export function progressEventsMarkup(events) {
  const names={RUN_STATUS_CHANGED:'실행 상태 변경',RUN_STARTED:'시험 시작',AGENT_DISPATCHED:'Agent 실행 시작',AGENT_STEP:'Agent 처리',TOOL_CALLED:'도구 호출',AGENT_TOOL_CALLED:'도구 호출',TOOL_RESPONDED:'도구 응답 수신',AGENT_TOOL_RESPONDED:'도구 응답 수신',APPROVAL_REQUESTED:'담당자 승인 요청',AGENT_WAITING_APPROVAL:'담당자 승인 대기',APPROVAL_DECIDED:'담당자 승인·거절',AGENT_APPROVAL_RECEIVED:'승인 결정 수신',SCENARIO_STATE_CHANGED:'시험 상태 변경',BUSINESS_COMMITTED:'업무 변경 저장',FAULT_INJECTED:'예외 적용',FAULT_APPLIED:'예외 적용',IDEMPOTENT_RETURNED:'기존 처리 결과 반환',AGENT_FINISHED:'Agent 처리 종료',RUN_FINISHED:'시험 처리 종료',SNAPSHOT_FINALIZED:'최종 업무 상태 확인',VERDICT_CREATED:'검사 결과 기록',REPORT_READY:'보고서 작성 완료'};
  return events.length?`<ol class="run-progress-events">${events.slice(-5).reverse().map(e=>{
    const date=new Date(e.occurred_at), time=Number.isNaN(date.getTime())?e.occurred_at || '':date.toLocaleTimeString('ko-KR');
    return `<li><span class="mono">#${escapeHtml(e.sequence)}</span><strong>${escapeHtml(names[e.event_type || e.type] || '실행 기록')}</strong><time datetime="${escapeHtml(e.occurred_at || '')}">${escapeHtml(time)}</time></li>`;
  }).join('')}</ol>`:'<p class="live-hint">서버에서 진행 기록을 받으면 표시합니다.</p>';
}


// Temporarily hide real-run comparison; keep its implementation for reactivation.
export const LIVE_COMPARISON_ENABLED = false;

export function workspaceRoute(hash) {
  const [path,query]=hash.replace(/^#/, '').split('?');
  const value=path || 'agents';
  const runId=new URLSearchParams(query).get('run');
  if(['live','execution'].includes(value) && runId)return {page:value,runId};
  if(value==='compare' && !LIVE_COMPARISON_ENABLED)return {page:'execution'};
  if(['agents','prepare','live','execution','runs','compare','approvals','requests','reports'].includes(value))return {page:value};
  if(value==='demo' || value.startsWith('demo-')) {
    const tab=value.slice(5);
    return {page:'demo',demoTab:['agents','prepare','execution','compare','structure'].includes(tab)?tab:'agents',show3d:value==='demo-3d'};
  }
  return {page:'agents'};
}

export function runListMarkup(runs, catalog, selectedId) {
  const labels={PREPARING:'실행 준비 중',RUNNING:'실행 중',WAITING_APPROVAL:'담당자 승인 대기',EVALUATING:'결과 검사 중',COMPLETED:'실행 완료',ERROR:'실행 오류'};
  return runs.map(run=>{
    const test=catalog?.tests.find(test=>test.test_id===run.test_id);
    const date=new Date(run.created_at);
    const time=Number.isNaN(date.getTime())?'시각 미상':date.toLocaleString('ko-KR',{dateStyle:'medium',timeStyle:'short'});
    const summary=run.summary || {}, count=(summary.PASS || 0)+(summary.FAIL || 0)+(summary.INCONCLUSIVE || 0);
    const verdict=run.status==='ERROR'?'오류 기록 확인':count?`통과 ${summary.PASS || 0} · 미충족 ${summary.FAIL || 0} · 보류 ${summary.INCONCLUSIVE || 0}`:'아직 판정이 없습니다';
    return `<article class="run-record" data-status="${escapeHtml(run.status)}" ${run.run_id===selectedId?'data-selected="true"':''}>
      <div class="run-record-id"><span class="mono">${escapeHtml(run.run_id)}</span>${run.run_id===selectedId?'<small>열어 본 실행</small>':''}</div>
      <div class="run-record-info"><h3>${escapeHtml(test?.title || run.test_id)}</h3><p>${escapeHtml(run.test_id)}${run.system_id?` · ${escapeHtml(run.system_id)}`:''}${run.created_by?` · 요청자 ${escapeHtml(run.created_by)}`:''}</p><time datetime="${escapeHtml(run.created_at || '')}">${escapeHtml(time)}</time></div>
      <div class="run-record-state"><strong>${escapeHtml(labels[run.status] || run.status)}</strong><small>${escapeHtml(verdict)}</small></div>
      <button type="button" class="secondary" data-live-run="${escapeHtml(run.run_id)}" aria-label="${escapeHtml(run.run_id)} ${runDestination(run)==='live'?'실험 실행 열기':'실행 분석 열기'}">${run.status==='WAITING_APPROVAL'?'승인 대기 확인':runDestination(run)==='live'?'진행 상태 보기':'실행 분석 열기'} →</button>
    </article>`;
  }).join('');
}

// Guidance follows observed server state; a finished process is not a passing verdict.
export function runGuidance(run, settled=false, page='execution') {
  if (run.status === 'ERROR') return {title:'실행이 오류로 종료됐습니다', detail:'자동으로 다시 실행하지 않습니다. 실행 분석에서 오류와 마지막 기록을 확인해 주세요.', action:'오류 기록 확인 →', page:'execution'};
  if (run.status === 'WAITING_APPROVAL') return {title:'담당자 승인을 기다리고 있습니다', detail:'업무 변경 요청과 내용을 확인한 뒤 승인자 계정으로 승인하거나 거절해 주세요.', action:'승인 처리로 이동 →', page:'live'};
  if (run.investigation?.status === 'RUNNING') return {title:'사고 조사 보고서를 작성하고 있습니다', detail:'근거와 지침을 조회해 보고서를 작성 중입니다. 완료 후 실행 분석에서 확인할 수 있습니다.', page:'live'};
  if (run.status === 'COMPLETED' && settled) {
    if(page==='live')return {title:'실행과 근거 수집이 끝났습니다',detail:'실행 종료와 검사 통과는 별개입니다. 실행 분석에서 판정과 근거를 확인하세요.',action:'결과 분석 보기 →',page:'execution'};
    const failed=run.summary?.FAIL || 0, unknown=run.summary?.INCONCLUSIVE || 0;
    return {title:'실행과 결과 수집이 끝났습니다', detail:run.investigation?.status === 'ERROR' ? '조사 보고서 생성에 실패했습니다. 실행 분석에서 검사 결과와 오류 기록을 확인해 주세요.' : failed || unknown ? `미충족 기준 ${failed}개 · 판정 보류 ${unknown}개가 있습니다. 실행 분석에서 검사 근거${run.investigation?.report?'와 조사 보고서':''}를 확인해 주세요.` : '실행 분석에서 검사 결과'+(run.investigation?.report?'와 조사 보고서':'와 실행 근거')+'를 확인해 주세요.', action:'결과 확인 →', page:'execution'};
  }
  const copy={PREPARING:['실행을 준비하고 있습니다','요청이 접수됐습니다. 시험 환경을 준비한 뒤 Agent를 실행합니다.'],EVALUATING:['실행 결과를 검사하고 있습니다','Agent 처리가 끝나 검사 결과와 근거를 수집하고 있습니다. 잠시 기다려 주세요.'],COMPLETED:['마지막 실행 기록을 수집하고 있습니다','검사 결과와 이벤트를 모두 받은 뒤 완료 상태를 안내합니다.']};
  const [title,detail]=copy[run.status] || ['Agent가 실행 중입니다','요청이 접수됐습니다. 도구 호출과 모델 응답을 기다리고 있습니다. 승인이 필요하면 이곳에 안내합니다.'];
  return {title,detail,page:'live'};
}

export function nextActionHint({page, session, run, settled, pendingStart, comparison}) {
  if (!session) return {selector:'[data-live-login] button', text:'계정과 비밀번호를 입력한 뒤 로그인해 주세요.'};
  if (pendingStart) return null;
  if (run && !settled && ['agents','prepare'].includes(page)) return {selector:'[data-live-guidance] .primary', text:'진행 중인 실행으로 돌아가 상태를 확인해 주세요.'};
  if (run && ['live','execution'].includes(page)) {
    if (run.status==='WAITING_APPROVAL') return page==='live'
      ? {selector:'[data-live-approval-form]',text:'승인 대상과 내용을 확인한 뒤, 승인자 계정으로 승인 또는 거절해 주세요.'}
      : {selector:'[data-live-guidance] .primary',text:'담당자 결정이 필요합니다. 여기서 승인 화면으로 이동하세요.'};
    if (settled) return page==='execution'
      ? {selector:'[data-live-show-results]',text:'실행이 끝났습니다. 여기서 검사 결과와 보고서를 확인하세요.'}
      : {selector:'[data-live-guidance] .primary',text:'실행이 끝났습니다. 결과 확인으로 이동해 주세요.'};
    return null;
  }
  return {
    agents:{selector:'[data-live-next]',text:'Agent를 선택했다면, 여기서 시험 조건을 설정하세요.'},
    prepare:{selector:'[data-live-design] button',text:'Agent를 분석해 필요한 시험을 설계하세요.'},
    live:{selector:'[data-live-start] button',text:'이 버튼을 누르면 선택한 조건으로 실제 실행을 시작합니다.'},
    execution:{selector:'[data-live-history]',text:'확인할 실행 기록을 선택해 주세요.'},
    compare:comparison?null:{selector:'[data-live-compare]',text:'같은 시나리오의 완료된 실행 두 개를 고른 뒤 비교해 주세요.'}
  }[page] || null;
}


// Transform only the adapter-supported values; source inputs remain immutable.
export function preparedPurchaseSample(reference, values) {
  const quantity=Number(values.quantity), inventory=Number(values.inventory), price=Number(values.unit_price_minor);
  if (![quantity,inventory,price].every(n=>Number.isSafeInteger(n) && n>=0 && n<=2147483647) || quantity<=inventory)
    throw new Error('구매 수량은 재고보다 큰 정수, 재고·가격은 0 이상의 정수로 입력하세요.');
  const sample=structuredClone(reference.sample_data);
  sample.business_input.quantity=quantity;
  sample.business_input.unit_price_minor=price;
  sample.initial_state.request=structuredClone(sample.business_input);
  sample.initial_state.parts.find(p=>p.part_id===sample.business_input.part_id && p.plant_id===sample.business_input.plant_id).inventory=inventory;
  sample.initial_state.suppliers.find(s=>s.supplier_id===sample.business_input.supplier_id).unit_price_minor=price;
  return {target:reference.target,sample_data:sample};
}

export function completedSystemRuns(catalog, runs) {
  const supported=new Set((catalog?.tests || []).filter(t=>t.test_kind==='SYSTEM').map(t=>t.test_id));
  return runs.filter(run=>supported.has(run.test_id) && run.status==='COMPLETED');
}

export function reviewMarkup(review) {
  if(!review)return '';
  const esc=escapeHtml;
  const decision={ACCEPT_FOR_BINDING:'실행 연결 검사로 진행',NEEDS_INFORMATION:'보완 필요',REJECT:'시험안 수정 필요'};
  const names={policy_alignment:'기대 행동과 정책 일치',evidence_relevance:'문헌 적합성',scenario_consistency:'상황 일관성'};
  const scoreNames={domain_fit_score:'업무/Agent 기능 적합',causal_path_score:'인과·실패 경로',constraint_score:'제약·도구 경로',evidence_score:'단계 문헌 근거'};
  const values={ALIGNED:'일치',CONFLICT:'정책과 충돌',UNCLEAR:'보완 필요',SUPPORTED:'근거 있음',IRRELEVANT:'근거 부적합',COHERENT:'일관됨',CONTRADICTORY:'조건 상충'};
  const scores=Object.entries(review.assessment || {}).map(([key,value])=>`<li>${esc(names[key] || key)}: ${esc(values[value] || value)}</li>`).join('');
  const stageNames={MANUFACTURING:'1. 제조업 제약·영향',AGENTIC:'2. 에이전틱 실패 경로'};
  const stages=(review.stages || []).map(stage=>{
    const criteria=Object.entries(stage.assessment || {}).map(([k,v])=>`${esc(names[k] || k)}: ${esc(values[v] || v)}`).join(' · ');
    const numeric=stage.scores?`${stage.score_total}/8 · `+Object.entries(stage.scores).map(([key,value])=>`${scoreNames[key] || key} ${value}/2`).join(' · '):'점수 없음';
    const scoreReasons=Object.entries(stage.score_reasons || {}).map(([key,value])=>`<li>${esc(scoreNames[key] || key)}: ${esc(value)}</li>`).join('');
    return `<li><strong>${esc(stageNames[stage.stage] || stage.stage)}</strong> · ${esc(stage.status==='SKIPPED'?'앞 단계 보완 후 진행':decision[stage.decision] || stage.decision)}<p class="live-hint">점수 ${esc(numeric)} · 통과 기준: 각 1점 이상, 합계 6/8 이상</p>${criteria?`<p class="live-hint">${criteria}</p>`:''}<details><summary>점수·판단 근거</summary>${scoreReasons?`<ul>${scoreReasons}</ul>`:''}<ul>${(stage.reasons || []).map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul><small>근거: ${(stage.evidence_ids || []).map(esc).join(', ') || '미검토'}</small></details></li>`;
  }).join('');
  const method=review.method==='CODE_PREREQUISITES'?'코드 사전 검사':review.method==='OFFLINE_METADATA_CHECK'?'오프라인 출처 연결 검사 · 문단 의미 미검증':'시험안 검토 기록';
  return `<details><summary>시험안 검토: ${esc(decision[review.decision] || review.decision)}</summary><p class="live-hint">${method} · 대상 Agent의 합격 판정이 아닙니다.</p>${stages?`<ol>${stages}</ol>`:`${scores?`<ul>${scores}</ul>`:''}<ul>${(review.reasons || []).map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul>`}</details>`;
}

export function scenarioMarkup(basis={}) {
  const esc=escapeHtml;
  const normal=basis.normal_use_scenario;
  const labels={MAINTENANCE:'설비 정비 전환',OVERLAP:'작업 시간 중복',PREDECESSOR_DELAY:'선행 공정 지연',MISSING_RECORD:'필수 검사 원자료 누락',FAILED_RECORD:'검사 원자료 불합격',FAILED_CERTIFICATE:'성적서 불합격',UNQUALIFIED_SOURCE:'공급 자격 없음',RESPONSE_LOSS:'저장 후 응답 유실',APPROVAL_DENIED:'승인 거절',INITIAL:'실행 초기',AFTER_APPROVAL_BEFORE_WRITE:'승인 직후·변경 전',NONE:'없음',NORMAL:'정상'};
  if(!normal) {
    const old=basis.morphology;
    return old?.business_condition?`<details><summary>상황을 만든 조합</summary><p>${[old.tool_name,old.business_condition,old.event,old.phase].map(v=>esc(labels[v] || v)).join(' → ')}</p></details>`:'';
  }
  const exceptions=basis.exceptions || [];
  return `<details><summary>정상 업무와 적용 예외</summary><p><strong>정상 사용 시나리오:</strong> ${esc(normal.normal_goal)}</p><p>${esc(normal.task)}</p><p><strong>정상 기대 행동:</strong> ${esc(normal.normal_expected_behavior)}</p><p>조회 정보: ${esc((normal.information_basis || []).join(', '))} · 변경 도구: ${esc(normal.tool_name)}</p><p><strong>적용할 예외:</strong></p><ul>${exceptions.map(e=>`<li>${esc(labels[e.condition] || e.condition)} · ${esc(labels[e.phase] || e.phase)}${e.execution_support==='UNSUPPORTED'?' · 실행 연결 필요':''}</li>`).join('')}</ul></details>`;
}

// One summary is shared by the screen and the downloadable QA report.
export function qaReportMarkup(report) {
  if(!report)return '<p class="live-hint">결과 수집 중</p>';
  const esc=escapeHtml, list=items=>`<ul>${items.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`;
  const scope={agent_behavior:'Agent 행동',business_state:'DB 상태',server_control:'서버 통제',report_truthfulness:'보고 정확성',qa_evidence:'시험 근거'};
  const coverage={OBSERVED:'기록 확인',PARTIAL:'일부 확인',NOT_TESTED:'미검증'};
  const refs=items=>items.length?`<ul>${items.map(s=>{
    const url=s.source_url || s.url || '';
    return `<li>${/^https:\/\//.test(url)?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.source_id)}</a>`:esc(s.title || s.source_id || '출처 미기록')}${s.location?` · ${esc(s.location)}`:''}</li>`;
  }).join('')}</ul>`:'<p>별도 출처 미기록</p>';
  const n=report.narrative;

  return `<div class="live-qa-report"><h3>${esc(report.summary)}</h3>${report.source_run_id?`<p class="live-hint">추가 조사 실험 · 원본 ${esc(report.source_run_id)}</p>`:''}
    ${n?`<h4>1. 어떤 Agent를 시험했나요?</h4><p><strong>${esc(n.agent_type_name)}</strong> · ${esc(n.agent_role)}</p>
      <h4>2. 어떤 위험 상황을 만들었나요?</h4><p><strong>${esc(report.test.title)}</strong></p><ol>${n.scenario_steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol><p><strong>기대 행동:</strong> ${esc(n.expected_behavior)}</p>
      <h4>3. 실제 결과는 어땠나요?</h4><table class="live-table"><tbody><tr><th>Agent의 행동</th><td>${esc(n.agent_action)}</td></tr><tr><th>실제 업무 처리</th><td>${esc(n.business_result)}</td></tr><tr><th>Agent가 보고한 결과</th><td>${esc(n.agent_reported_result)}</td></tr></tbody></table>
      <h4>4. 이 결과는 무엇을 뜻하나요?</h4><p>${esc(n.meaning)}</p><p class="live-hint">${esc(n.provenance)}</p>`:`<p>${esc(report.test.title)}</p>`}
    <p class="live-hint">미충족 기준 ${esc(report.results.failed_checks)}개 · 실제 업무 변경 ${esc(report.results.changes ?? '미확인')}건. 기준 개수는 사고 건수가 아닙니다.</p>
    <p class="live-hint">이번 시험 조건에 한정한 결과입니다.</p>
    ${scenarioMarkup(report.test)}
    ${report.findings.length?`<details><summary>미충족·보류 기준과 근거</summary><ul>${report.findings.map(f=>`<li><strong>${esc(scope[f.scope] || f.scope)} · ${esc(f.verdict)}</strong> ${esc(f.readable_reason || f.reason || f.rule_id)}<details><summary>근거</summary><small>${esc((f.evidence_ids || []).join(', '))}</small></details></li>`).join('')}</ul></details>`:''}
    ${report.domain.coverage.length?`<details><summary>제조 운영 검증 범위</summary><div class="live-table-wrap"><table class="live-table"><thead><tr><th>관점</th><th>확인 수준</th><th>시험 범위</th></tr></thead><tbody>${report.domain.coverage.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(coverage[c.status])}</td><td>${esc(c.execution_scope)}<br><small>미검증: ${esc(c.not_tested)}</small></td></tr>`).join('')}</tbody></table></div></details>`:''}
    ${reviewMarkup(report.test.design_review)}${repairMarkup(report.test.design_repair)}
    <details><summary>시험 조건·판정 근거</summary><p>${esc(report.domain.scope || '저장된 개별 시험 범위')}</p><p>판정: ${esc(report.test.required_rules.join(', '))}</p><pre>${esc(JSON.stringify(report.test,null,2))}</pre><h4>시험에 인용한 자료</h4>${refs(report.test_sources)}<h4>도메인 배경 자료</h4>${refs(report.domain.background_sources)}<p>배경 자료 자체를 합격 기준으로 사용하지 않습니다.</p></details>
    <details><summary>검증 한계</summary>${list(report.limitations)}</details></div>`;
}

export function qaReportDocument(report, events=[]) {
  const esc=escapeHtml;
  const eventNames={RUN_STATUS_CHANGED:'실행 상태 변경',AGENT_DISPATCHED:'Agent 실행 시작',TOOL_CALLED:'도구 호출',TOOL_RESPONDED:'도구 응답',APPROVAL_DECIDED:'담당자 승인·거절',SCENARIO_STATE_CHANGED:'시험 상태 변경',BUSINESS_COMMITTED:'업무 변경 저장',AGENT_FINISHED:'Agent 실행 종료',SNAPSHOT_FINALIZED:'최종 업무 상태 확인',VERDICT_CREATED:'검사 결과 기록'};
  const timeline=events.map(e=>`<tr><td>${esc(e.sequence)}</td><td>${esc(eventNames[e.event_type] || '실행 기록')}<small>${esc(e.event_type)}</small></td><td>${esc(e.occurred_at || '')}</td><td>${esc((e.evidence_ids || []).join(', '))}</td></tr>`).join('');
  const checks=report.checks.map(c=>`<tr><td>${esc(c.rule_id)}</td><td>${esc(c.scope)}</td><td>${esc(c.verdict)}</td><td>${esc(c.reason || '')}<br>${esc((c.evidence_ids || []).join(', '))}</td></tr>`).join('');
  return `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(report.run_id)} QA 보고서</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;font:15px/1.7 system-ui,sans-serif;color:#1f2937}h1,h2,h3{line-height:1.4}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px;text-align:left;border-bottom:1px solid #d1d5db;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f4f6;padding:16px}small{display:block;color:#6b7280}details{margin:16px 0}summary{font-weight:600}a{color:#315e51}@media print{body{margin:0}details{break-inside:avoid}a{color:inherit}}</style><h1>제조 운영 Agent QA 보고서</h1><p>${esc(report.run_id)} · ${esc(report.created_at || '')}</p><p>대상: ${esc(report.target.name || report.target.runtime_id || '미기록')} · 버전 ${esc(report.target.agent_version || '미기록')}</p>${qaReportMarkup(report)}<h2>검사 상세</h2><table><thead><tr><th>규칙</th><th>대상</th><th>판정</th><th>근거</th></tr></thead><tbody>${checks}</tbody></table><h2>실행 타임라인</h2><p>저장 이벤트 순서이며 실제 물리적 인과관계를 단독으로 증명하지 않습니다.</p><table><thead><tr><th>순번</th><th>사건</th><th>시각</th><th>근거 ID</th></tr></thead><tbody>${timeline}</tbody></table></html>`
    .replace(/<details>/g,'<details open>');
}


export function qaReportCollectionDocument(reports) {
  const esc=escapeHtml;
  const rows=reports.map(r=>`<tr><td>${esc(r.run_id)}</td><td>${esc(r.narrative?.agent_type_name || r.target.type_name || '유형 미확인')}<small>버전 ${esc(r.target.agent_version || '미기록')} · 서버 ${esc(r.test.system_id || '미기록')}</small></td><td>${esc(r.test.title)}</td><td>${esc(r.narrative?.agent_action || '상세 확인 필요')}</td><td>${esc(r.narrative?.business_result || '상세 확인 필요')}</td><td>${esc(r.summary)}</td></tr>`).join('');
  const body=`<h1>제조 운영 Agent QA 결과 요약</h1><p>조회가 허용된 최근 완료 시험 중 최대 20개 · ${reports.length}개 수록. 진행 중·실행 오류·개별 기능 시험은 제외합니다.</p><p>서로 다른 Agent·버전·시험 상황을 모은 목록입니다. 전체 성공률이나 도입 승인으로 해석하지 않습니다.</p><table><thead><tr><th>실험</th><th>Agent 유형</th><th>위험 상황</th><th>Agent 행동</th><th>실제 업무 처리</th><th>판정</th></tr></thead><tbody>${rows}</tbody></table>${reports.map(r=>`<section><h2>${esc(r.run_id)} · ${esc(r.narrative?.agent_type_name || '유형 미확인')}</h2>${qaReportMarkup(r)}</section>`).join('')}`;
  return `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>제조 운영 Agent QA 결과 요약</title><style>body{max-width:1200px;margin:32px auto;padding:0 24px;font:15px/1.7 system-ui,sans-serif;color:#1f2937}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px;text-align:left;vertical-align:top;border-bottom:1px solid #d1d5db}section{margin-top:48px;border-top:2px solid #789087}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f4f6;padding:12px}small{display:block;color:#6b7280}summary{font-weight:600}details{margin:12px 0}@media print{section{break-before:page}}</style>${body}</html>`;
}


export function repairMarkup(repair) {
  if(!repair || !repair.attempts || !repair.feedback?.length)return '';
  const labels={REPAIRED:'수정 후 실행 연결 확인',PARTIALLY_REPAIRED:'일부 보완 필요',NOT_REPAIRED:'보완 필요',BUDGET_EXHAUSTED:'비용 한도로 수정 중단',REPAIR_UNAVAILABLE:'수정 요청 실패',INVALID_REPAIR:'수정안 검사 실패'};
  return `<details><summary>시험안 보완 ${escapeHtml(repair.attempts)}회 · ${escapeHtml(labels[repair.status] || repair.status)}</summary><p>보류된 시험만 최대 1회 수정합니다. 실행 결과나 합격 판정이 아닙니다.</p><ul>${(repair.feedback || []).map(f=>`<li>${escapeHtml(f.proposal_id)}: ${(f.reasons || []).map(escapeHtml).join(' · ')}</li>`).join('')}</ul></details>`;
}

export function followupMarkup(proposal) {
  if(!proposal || proposal.status!=='READY')return '';
  return `<section class="panel section-pad"><h3>조사 후 추가 실험</h3><p>${escapeHtml(proposal.question)}</p><p class="live-hint">정상 대조 1회 + 원래 위험 조건 1회 · 동일 Agent·입력·서버 설정 · 매 실행 담당자 승인</p><details><summary>제안 근거</summary><p>${escapeHtml(proposal.reason)}</p><p>${(proposal.rule_ids || []).map(escapeHtml).join(', ')} · ${(proposal.evidence_ids || []).map(escapeHtml).join(', ')}</p></details><button class="secondary" data-live-follow-up>${proposal.batch_id?'추가 실험 보기':'추가 실험 실행'}</button></section>`;
}
