const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const known={
 TARGET_RUNTIME_CHANGED:'실행기 버전이나 모델 설정이 바뀌었습니다. 등록·설계를 다시 진행하세요.',
 INCOMPATIBLE_EXECUTION_TARGET:'실행기와 같은 업무·기능·정책 및 지원 데이터를 사용해야 합니다.',
 PROFILE_INFORMATION_REQUIRED:'승인·재시도 정책을 보완한 뒤 새로 저장하세요.',
 PROFILE_ANALYSIS_CHANGED:'위험 분류 기준이 바뀌었습니다. 등록 정보를 다시 저장해 분석하세요.',
 QA_ANALYSIS_UNAVAILABLE:'Agent 설명 분석 서비스에 연결하지 못했습니다.',
 QA_DESIGN_UNAVAILABLE:'시험 설계 서비스 또는 문서 검색에 연결하지 못했습니다. 서비스 상태와 설계 모델 설정을 확인해 주세요.',
 QA_BATCH_IN_PROGRESS:'반복 실험이 진행 중입니다. 현재 실험을 확인하거나 중단을 요청하세요.',
 RELIABILITY_REQUIRES_LLM:'현재 대상은 규칙 기반입니다. 기본 연결 점검으로 실행하세요.',
 QA_STRATEGY_REQUIRED:'우선 Agent를 보고 시험 설계를 새로 실행해 주세요.',
 UNAUTHORIZED:'로그인이 필요하거나 세션이 만료되었습니다. 다시 로그인해 주세요.',
 RUN_FINALIZED:'이미 종료된 실행입니다. 새 시험을 시작해 주세요.',
 NOT_COMPARABLE:'동일한 SYSTEM 시나리오의 완료된 실행 두 개를 선택해 주세요.',
 RUN_NOT_COMPLETED:'두 실행이 모두 완료된 뒤 비교해 주세요.',
 LLM_KEY_NOT_CONFIGURED:'서버의 설계 모델과 API 키 설정을 관리자에게 요청하세요.',
 LLM_BUDGET_EXHAUSTED:'모델 호출 예산을 사용했습니다. 관리자에게 예산 확인을 요청하세요.',
 UNPRICED_MODEL:'설계 모델의 비용 계산 설정을 확인해 주세요.',
 LLM_INPUT_LIMIT:'대상 설명과 시험 범위를 줄인 뒤 다시 설계하세요.',
 INIT_FAILED:'시험 환경 준비에 실패했습니다. 서비스 설정과 마지막 기록을 확인하세요.',
 INJECTION_ERROR:'시험용 예외를 적용하지 못했습니다. 예외 주입 설정을 확인하세요.',
 APPROVAL_WAIT_EXPIRED:'승인 대기 시간이 지났습니다. 새 시험을 준비하세요.',
 AGENT_SERVER_ERROR:'Agent 실행이 오류로 종료됐습니다. 마지막 이벤트를 확인하세요.',
 ORACLE_ERROR:'검사 결과 생성에 실패했습니다. 실행 근거를 확인하세요.',
 APPROVAL_TIMEOUT:'승인 기한이 지나 실행을 종료했습니다. 새 시험을 준비하세요.',
 HARNESS_RESTARTED:'시험 서비스가 재시작돼 실행이 중단됐습니다. 마지막 기록을 확인하세요.',
 PREPARE_FAILED:'시험 환경 준비에 실패했습니다. 환경 설정과 마지막 기록을 확인하세요.',
 APPROVAL_EXPIRED:'승인 기한이 지났습니다. 새 시험을 준비하세요.',
 RUN_TIMEOUT:'실행 제한 시간을 넘었습니다. 마지막 기록을 확인하세요.',
 HARNESS_UNAVAILABLE:'시험 환경에 연결하지 못했습니다. 서비스 상태를 확인하세요.',
 FAULT_INJECTION_FAILED:'시험용 예외를 적용하지 못했습니다. 실행 기록을 확인하세요.',
 RUN_IN_PROGRESS:'진행 중인 실행을 먼저 확인하세요.',
 PERMISSION_DENIED:'이 계정에는 작업 권한이 없습니다.',
 INVALID_QA_TARGET:'업무 입력과 도구 정의, 실행기 연결을 확인하세요.'
};
export function describeError(error={},context={}) {
 const ambiguous=context.write && (error.transport || error.code==='INVALID_RESPONSE' || ['MCP_UNAVAILABLE','HARNESS_UNAVAILABLE'].includes(error.code) || error.status>=500 && !known[error.code] && !error.details?.decision_saved);
 const saved=error.details?.decision_saved;
 const configured=/LLM_KEY|BUDGET|UNPRICED|CONFIGURED/.test(error.code||'');
 const fields=error.fields || {};
 if(error.code==='VALIDATION_ERROR' && typeof error.message==='string'){const field=error.message.match(/^invalid body\.([a-z_]+)$/)?.[1];const names={name:'name',version:'version',task:'task',max_runs:'max_runs',max_seconds:'max_seconds',max_cost_usd:'max_cost_usd'};if(names[field])fields[names[field]]='값과 입력 형식을 확인하세요.';}
 const fieldDescription=Object.values(fields).join(' ');
 return {severity:ambiguous?'pending':'error',title:saved?'결정은 저장됐지만 실행 재개에 실패했습니다':ambiguous?'접수 여부 확인 필요':context.auth?'로그인하지 못했습니다':context.previous?'새 제안 생성 실패 · 이전 제안 표시 중':context.title || '작업을 완료하지 못했습니다',
  description:saved?'저장된 결정으로 실행 재개를 다시 요청하세요. 반대 결정은 보낼 수 없습니다.':ambiguous?'요청은 서버에 저장됐을 수 있습니다. 저장 상태를 먼저 확인하세요. 자동으로 다시 보내지 않습니다.':context.auth?'계정과 비밀번호를 확인하고 다시 로그인하세요.':known[error.code] || fieldDescription || context.description || (error.status===403?'이 계정에는 작업 권한이 없습니다.':error.status===401?'세션이 만료되었습니다. 다시 로그인하세요.':error.transport?'서버에 연결하지 못했습니다. 네트워크와 서비스 상태를 확인하세요.':error.code==='INVALID_RESPONSE'?'서버 응답을 읽지 못했습니다. 잠시 후 다시 불러오세요.':error.status>=500?'서버에서 처리하지 못했습니다. 잠시 후 저장 상태를 확인하세요.':'입력과 작업 조건을 확인하고 다시 시도하세요.'),
  action:saved?'동일 결정으로 재개 요청':ambiguous?'저장 상태 확인':configured?'설정 확인 안내':context.auth?'로그인 다시 시도':context.action || '다시 확인',code:typeof error.code==='string' && /^[A-Z][A-Z0-9_]{0,80}$/.test(error.code)?error.code:undefined,status:error.status,runId:context.runId,fields};
}
export function errorMarkup(info,action='') {
 return `<section class="error-panel" data-severity="${esc(info.severity||'error')}" tabindex="-1" role="region" aria-label="${esc(info.title)}"><span class="error-icon" aria-hidden="true">${info.severity==='pending'?'△':'!'}</span><div><strong>${esc(info.title)}</strong><p>${esc(info.description)}</p>${action?`<button type="button" class="secondary" ${action}>${esc(info.action)}</button>`:''}${info.code||info.runId||info.status?`<details><summary>오류 상세</summary><dl><dt>코드</dt><dd>${esc(info.code||'미제공')}</dd><dt>HTTP 상태</dt><dd>${esc(info.status||'응답 없음')}</dd>${info.runId?`<dt>실행 번호</dt><dd>${esc(info.runId)}</dd>`:''}</dl></details>`:''}</div></section>`;
}
export function showError(container,info,{focus=false,action='',key='operation'}={}) {
 if(!container?.querySelector)return;
 let slot=container.querySelector(`[data-error-slot="${key}"]`);
 if(!slot){slot=document.createElement('div');slot.dataset.errorSlot=key;slot.setAttribute('aria-live','polite');container.append(slot);}
 const markup=errorMarkup(info,action);
 if(slot.innerHTML!==markup)slot.innerHTML=markup;
 if(focus){for(let node=slot.parentElement;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;slot.querySelector('.error-panel')?.focus();}
 return slot;
}
export function clearError(container,key='operation') {container?.querySelector?.(`[data-error-slot="${key}"]`)?.remove();}
export function markFields(form,fields) {
 for(const [name,message] of Object.entries(fields)){
  const input=Array.from(form.elements||[]).find(el=>el.name===name);if(!input)continue;
  input.setAttribute('aria-invalid','true');
  const id=`field-error-${name.replace(/[^\w-]/g,'-')}`;
  let note=form.querySelector(`[id="${id}"]`);if(!note){note=document.createElement('p');note.id=id;note.className='field-error';note.dataset.fieldError='true';input.after(note);}note.textContent=message;
  input.setAttribute('aria-describedby',[input.getAttribute('aria-describedby'),id].filter(Boolean).join(' '));
  for(let node=input.parentElement;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
 }
 const first=form.querySelector('[aria-invalid="true"]');first?.focus();
}
export function captureForms(root) {
 return Array.from(root?.querySelectorAll?.('form')||[]).filter(form=>!form.matches('[data-live-login]')).map(form=>({attributes:Array.from(form.attributes).filter(a=>a.name.startsWith('data-')).map(a=>a.name),fields:Array.from(form.elements).filter(el=>el.name && !['password','file','submit','button'].includes(el.type)).map(el=>({name:el.name,value:el.value,checked:el.checked,type:el.type})),expanded:!!form.closest?.('details')?.open,open:Array.from(form.querySelectorAll('details')).map(el=>el.open)}));
}
export function restoreForms(root,snapshots) {
 for(const saved of snapshots||[]){const form=root?.querySelector(saved.attributes.map(name=>`[${name}]`).join(''));if(!form)continue;
  for(const field of saved.fields){const input=Array.from(form.elements).find(el=>el.name===field.name && el.type===field.type && (el.type!=='radio'||el.value===field.value));if(input){input.value=field.value;if(['checkbox','radio'].includes(field.type))input.checked=field.checked;}}
  if(saved.expanded && form.closest?.('details'))form.closest('details').open=true;
  Array.from(form.querySelectorAll('details')).forEach((el,i)=>{el.open=!!saved.open[i];});
 }
}
