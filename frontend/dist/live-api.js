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


export function workspaceRoute(hash) {
  const value=hash.replace(/^#/, '') || 'agents';
  if(['agents','prepare','live','execution','compare'].includes(value))return {page:value};
  if(value==='demo' || value.startsWith('demo-')) {
    const tab=value.slice(5);
    return {page:'demo',demoTab:['agents','prepare','execution','compare','structure'].includes(tab)?tab:'agents',show3d:value==='demo-3d'};
  }
  return {page:'agents'};
}

// Guidance follows observed server state; a finished process is not a passing verdict.
export function runGuidance(run, settled=false) {
  if (run.status === 'ERROR') return {title:'실행이 오류로 종료됐습니다', detail:'자동으로 다시 실행하지 않습니다. 실행 분석에서 오류와 마지막 기록을 확인해 주세요.', action:'오류 기록 확인 →', page:'execution'};
  if (run.status === 'WAITING_APPROVAL') return {title:'담당자 승인을 기다리고 있습니다', detail:'아직 발주하지 않았습니다. 실제 실행 화면에서 승인 대상을 확인한 뒤 승인하거나 거절해 주세요.', action:'승인·거절 처리 →', page:'live'};
  if (run.investigation?.status === 'RUNNING') return {title:'사고 조사 보고서를 작성하고 있습니다', detail:'실행은 접수됐습니다. 근거와 지침을 조회해 보고서를 작성 중이며, 완료되면 이 화면에 표시합니다.', action:'조사 진행 보기 →', page:'execution'};
  if (run.status === 'COMPLETED' && settled) {
    const failed=run.summary?.FAIL || 0, unknown=run.summary?.INCONCLUSIVE || 0;
    return {title:'실행과 결과 수집이 끝났습니다', detail:run.investigation?.status === 'ERROR' ? '조사 보고서 생성에 실패했습니다. 실행 분석에서 검사 결과와 오류 기록을 확인해 주세요.' : failed || unknown ? `실패 ${failed}건 · 판정 보류 ${unknown}건이 있습니다. 실행 분석에서 검사 근거${run.investigation?.report?'와 조사 보고서':''}를 확인해 주세요.` : '실행 분석에서 검사 결과'+(run.investigation?.report?'와 조사 보고서':'와 실행 근거')+'를 확인해 주세요.', action:'결과 확인 →', page:'execution'};
  }
  const copy={PREPARING:['실행을 준비하고 있습니다','요청이 접수됐습니다. 시험 환경을 준비한 뒤 Agent를 실행합니다.'],EVALUATING:['실행 결과를 검사하고 있습니다','Agent 처리가 끝나 검사 결과와 근거를 수집하고 있습니다. 잠시 기다려 주세요.'],COMPLETED:['마지막 실행 기록을 수집하고 있습니다','검사 결과와 이벤트를 모두 받은 뒤 완료 상태를 안내합니다.']};
  const [title,detail]=copy[run.status] || ['Agent가 실행 중입니다','요청이 접수됐습니다. 도구 호출과 모델 응답을 기다리고 있습니다. 승인이 필요하면 이곳에 안내합니다.'];
  return {title,detail,action:'진행 기록 보기 →',page:'execution'};
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
    prepare:{selector:'[data-live-start] button',text:'조건을 확인했다면 다음으로 이동하세요. 아직 실행되지 않습니다.'},
    live:{selector:'[data-live-start] button',text:'이 버튼을 누르면 선택한 조건으로 실제 실행을 시작합니다.'},
    execution:{selector:'[data-live-history]',text:'확인할 실행 기록을 선택해 주세요.'},
    compare:comparison?null:{selector:'[data-live-compare]',text:'같은 시나리오의 완료된 실행 두 개를 고른 뒤 비교해 주세요.'}
  }[page] || null;
}
