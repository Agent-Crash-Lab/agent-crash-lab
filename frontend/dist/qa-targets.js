import {escapeHtml as esc} from './live-api.js?v=0.15.0';

export function parseTools(text) {
  if(new TextEncoder().encode(text).length>100000)throw new Error('도구 정의는 100 KB 이하로 입력해 주세요.');
  let data;try{data=JSON.parse(text);}catch{throw new Error('도구 정의 JSON 형식을 확인해 주세요.');}
  const tools=Array.isArray(data)?data:data.tools || data.result?.tools;
  if(!Array.isArray(tools) || !tools.length || tools.length>30)throw new Error('도구를 1~30개 입력해 주세요.');
  const names=new Set();
  return tools.map(t=>{
    if(!t || typeof t.name!=='string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(t.name) || names.has(t.name))throw new Error('도구 이름이 올바르지 않거나 중복됩니다.');
    names.add(t.name);
    const schema=t.input_schema || t.inputSchema;
    if(!schema || typeof schema!=='object' || Array.isArray(schema))throw new Error(`${t.name}: 입력 스키마가 필요합니다.`);
    const effect=['READ','WRITE'].includes(t.effect)?t.effect:t.annotations?.readOnlyHint===true?'READ':t.annotations?.readOnlyHint===false?'WRITE':'';
    return {name:t.name,description:typeof t.description==='string'?t.description:'',input_schema:schema,effect};
  });
}

export function exampleDeclaration(example, name='등록 예시 Agent') {
  const t=example.target;
  return {name,version:t.target_version,agent_type:t.agent_type || 'PURCHASE',task:t.task,
    industry_context:t.industry_context,tools:t.tools,policies:t.policies,
    business_input_schema:t.business_input_schema,sample_data:example.sample_data,
    capability_bindings:(t.qa_scope?.capabilities || []).map(b=>({...b,basis:'DECLARED'})),
    excluded_capabilities:t.qa_scope?.excluded_capabilities || []};
}

export function registrationMarkup() {
  return `<section class="panel section-pad" data-qa-register>
    <div class="live-row"><h2>새 제조업 Agent 등록</h2><span class="badge">설명 분석 · 실행 연결 전</span></div>
    <p class="live-hint">업무와 도구를 등록해 시험안을 만듭니다. 구매·생산·품질 예시 실행기를 선택하거나, 운영자가 연결한 외부 Agent를 시험할 수 있습니다.</p>
    <details data-qa-editor><summary>등록 정보 입력·수정</summary>
    <form data-qa-registration>
      <p class="live-hint">변경 내용은 저장 후 반영됩니다. 기존 등록 기록은 유지하고 새 기록을 만듭니다.</p>
      <div class="qa-form-grid"><label>Agent 이름<input name="name" minlength="2" maxlength="80" required></label><label>버전<input name="version" maxlength="64" value="1.0.0" required></label>
      <label>업무 유형<select name="agent_type"><option value="PURCHASE">자재 구매·발주</option><option value="PRODUCTION">생산 일정</option><option value="QUALITY">품질·출하</option><option value="COMMON">미분류·공통</option></select></label></div>
      <label>실제로 실행할 대상<select name="execution_runtime"><option value="">설계만 진행 (실행 연결 없음)</option><option value="reference-purchase-v1">플랫폼 구매 Agent 사용</option><option value="reference-production-v1">플랫폼 생산 Agent 사용</option><option value="reference-quality-v1">플랫폼 품질 Agent 사용</option></select></label>
      <p class="live-hint">실행기는 해당 업무 예시의 도구·입력·정책을 사용합니다. 외부 Agent 연결은 운영자 설정이 필요하며 임의의 URL은 실행하지 않습니다.</p>
      <label>Agent가 하는 일<textarea name="task" rows="2" maxlength="1500" required></textarea></label>
      <label>제조업 업무 조건<textarea name="industry_context" rows="2" maxlength="1500" required></textarea></label>
      <div class="qa-form-grid"><label>변경 전 담당자 승인<select name="approval_required"><option value="">아직 모름</option><option value="true">필요</option><option value="false">불필요</option></select></label>
      <label>변경 도구 재시도 최대 횟수<input name="max_write_retries" type="number" min="0" max="10" step="1" placeholder="모르면 비워 두세요"></label></div>
      <label>MCP 도구 정의 JSON<textarea name="tools_json" rows="6" spellcheck="false" required placeholder='{"tools":[{"name":"...","inputSchema":{"type":"object"},"annotations":{"readOnlyHint":true}}]}'></textarea></label>
      <label>JSON 파일에서 가져오기<input type="file" accept=".json,application/json" data-qa-tool-file></label>
      <button class="secondary" type="button" data-qa-parse>도구 읽기·기능 연결</button>
      <div data-qa-tools></div><div data-qa-capabilities></div>
      <details><summary>업무 입력 형식·시험용 데이터 (필수)</summary>
        <label>업무 입력 JSON Schema<textarea name="schema_json" rows="4" spellcheck="false" required>{"type":"object"}</textarea></label>
        <label>시험용 업무 입력 JSON<textarea name="input_json" rows="4" spellcheck="false" required>{}</textarea></label>
        <label>시험 환경의 초기 상태 JSON<textarea name="state_json" rows="4" spellcheck="false" required>{}</textarea></label>
        <p class="live-hint">실제 고객·설비 정보 대신 시험용 데이터를 사용하세요. 저장 시 입력 형식을 검사하며, 데이터 간 업무 관계는 실행 환경을 연결한 뒤 검사합니다.</p>
      </details>
      <div class="live-flow-actions"><button class="primary" type="submit">저장하고 적용 위험 분석</button><button class="secondary" type="button" data-qa-example>선택한 업무 예시로 채우기</button></div>
    </form></details>
    <h3>내가 등록한 Agent</h3><div data-qa-profiles></div>
  </section>`;
}

export function fillDeclaration(form, data) {
  for(const name of ['name','version','agent_type','task','industry_context'])form.elements[name].value=data[name] || '';
  form.elements.execution_runtime.value=data.execution_runtime || "";
  form.elements.approval_required.value=data.policies?.approval_required==null?'':String(data.policies.approval_required);
  form.elements.max_write_retries.value=data.policies?.max_write_retries ?? '';
  for(const [name,value] of Object.entries({tools_json:data.tools,schema_json:data.business_input_schema,input_json:data.sample_data?.business_input,state_json:data.sample_data?.initial_state}))form.elements[name].value=JSON.stringify(value || {},null,2);
}

export function renderToolBindings(form, options, data=null) {
  const tools=parseTools(form.elements.tools_json.value);
  form.querySelector('[data-qa-tools]').innerHTML=`<h3>도구별 조회·변경 확인</h3><p class="live-hint">MCP의 readOnlyHint는 작성자의 설명입니다. 실제 권한을 확인한 결과가 아닙니다. 표시가 없으면 직접 선택하세요.</p>`+tools.map((t,i)=>`<label>${esc(t.name)}<select data-qa-effect="${i}" required><option value="">구분 필요</option><option value="READ" ${t.effect==='READ'?'selected':''}>조회</option><option value="WRITE" ${t.effect==='WRITE'?'selected':''}>변경 가능</option></select></label>`).join('');
  form.querySelector('[data-qa-capabilities]').innerHTML=`<details open><summary>어떤 업무 기능을 수행하나요?</summary><p class="live-hint">이름만으로 기능을 추정하지 않습니다. 도구를 연결하거나, 해당 기능이 없다고 확인해 주세요.</p><div class="qa-form-grid">${options.map(c=>{
    const selected=data?.capability_bindings?.find(b=>b.name===c.name)?.tool_name || (data?.excluded_capabilities?.includes(c.name)?'__excluded__':'');
    return `<label>${esc(c.label)}<select data-qa-cap="${esc(c.name)}"><option value="">아직 모름</option><option value="__excluded__" ${selected==='__excluded__'?'selected':''}>기능 없음 (확인)</option>${tools.map(t=>`<option value="${esc(t.name)}" ${selected===t.name?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label>`;
  }).join('')}</div></details>`;
  return tools;
}

function object(text,label) {let value;try{value=JSON.parse(text);}catch{throw new Error(`${label}: JSON 형식을 확인해 주세요.`);}if(!value || typeof value!=='object' || Array.isArray(value))throw new Error(`${label}: JSON 객체를 입력해 주세요.`);return value;}
export function collectDeclaration(form) {
  const v=Object.fromEntries(new FormData(form));
  const tools=parseTools(v.tools_json).map((t,i)=>({...t,effect:form.querySelector(`[data-qa-effect="${i}"]`)?.value || t.effect}));
  if(tools.some(t=>!t.effect))throw new Error('도구 읽기를 누른 뒤 조회·변경 구분을 확인해 주세요.');
  const capability_bindings=[],excluded_capabilities=[];
  for(const select of form.querySelectorAll('[data-qa-cap]')){
    if(select.value==='__excluded__')excluded_capabilities.push(select.dataset.qaCap);
    else if(select.value)capability_bindings.push({name:select.dataset.qaCap,tool_name:select.value,basis:'DECLARED'});
  }
  return {execution_runtime:v.execution_runtime || null,name:v.name.trim(),version:v.version.trim(),agent_type:v.agent_type,task:v.task.trim(),industry_context:v.industry_context.trim(),tools,
    policies:{approval_required:v.approval_required===''?null:v.approval_required==='true',max_write_retries:v.max_write_retries===''?null:Number(v.max_write_retries)},
    business_input_schema:object(v.schema_json,'입력 형식'),sample_data:{business_input:object(v.input_json,'업무 입력'),initial_state:object(v.state_json,'초기 상태')},capability_bindings,excluded_capabilities};
}

export function capabilityLabel(name, options=[]) {
  return options.find(c=>c.name===name)?.label || {
    adopted_business_policy:'해당 업무의 채택 정책', design_review:'설계 검토 보완', design_prerequisites:'시험안 사전 검사',
    domain_state_injection:'시험 상태·오류 주입',domain_rule_evaluator:'업무 판정 코드',
    research_evidence:'연구 근거', approval_control:'승인 제어',state_observation:'업무 상태 관측',
    tool_trace:'도구 호출 기록',post_commit_fault_injection:'처리 후 오류 주입',
    control_baseline:'정상 대조 환경',source_eligibility_state:'공급 자격 상태'
  }[name] || name;
}

export function registeredCaseReady(registration, plan, caseId) {
  if(!registration)return true;
  return registration.execution_status==='CONNECTED' &&
    plan?.design?.registration?.profile_id===registration.profile_id &&
    plan?.design?.registration?.execution_binding?.runtime_id===registration.execution_binding?.runtime_id &&
    plan?.cases.some(c=>c.case_id===caseId && c.execution.status==='READY');
}

export function profileAnalysis(profile, options=[]) {
  const a=profile.analysis, labels={APPLICABLE:'시험 후보',NEEDS_INFORMATION:'추가 정보 필요',OUT_OF_SCOPE:'범위 밖'};
  const count=status=>(a.risk_screening || []).filter(r=>r.status===status).length;
  return `<article class="qa-profile-analysis"><h3>${esc(profile.name)} · ${esc(profile.version)}</h3>
    <p><strong>시험 후보 ${count('APPLICABLE')}개</strong> · 추가 정보 ${count('NEEDS_INFORMATION')}개 · 범위 밖 ${count('OUT_OF_SCOPE')}개</p>
    <p class="live-hint">${profile.execution_binding && profile.execution_status==='CONNECTED'?`실제 실행 대상: ${esc(profile.execution_binding.name || "플랫폼 구매 Agent")} · ${esc(profile.execution_binding.execution_profile.agent_version)} · 예시 정책 적용`:'등록자 설명 기준 · 실제 코드·권한 확인 전 · 실행 환경 연결 필요'}</p>
    ${!profile.can_design?'<p class="live-error">승인·재시도 정책을 입력해야 시험을 설계할 수 있습니다. 등록 정보를 보완해 다시 저장하세요.</p>':''}
    <div class="live-table-wrap"><table class="live-table"><thead><tr><th>위험</th><th>분류</th><th>판단 근거</th></tr></thead><tbody>${(a.risk_screening || []).map(r=>`<tr><td>${esc(r.title)}</td><td>${esc(labels[r.status])}</td><td>${esc(r.reason)}${r.missing_capabilities.length?`<br><small>필요 기능: ${esc(r.missing_capabilities.map(n=>capabilityLabel(n,options)).join(', '))}</small>`:''}</td></tr>`).join('')}</tbody></table></div>
    <p class="live-hint">업무·조건·행동을 조합해 최대 3개를 제안하고, 제조업 위험 → Agent 행동 위험 순서로 검토합니다. 시험 후보가 곧 실행 가능 또는 검증 완료를 뜻하지 않습니다.</p>
    <button type="button" class="primary" data-qa-plan ${profile.can_design?'':'disabled'}>이 Agent의 시험 설계 →</button>
    <button type="button" class="secondary" data-qa-edit>등록 정보 보완</button>
  </article>`;
}
