import {describeError,showError,clearError,api, escapeHtml as esc, qaReportDocument} from './live-api.js?v=0.15.8';

const titles={approvals:'승인 목록',requests:'관리자 요청 사항',reports:'보고서 목록'};
const statusNames={WAITING_APPROVAL:'승인 대기',COMPLETED:'실행 완료',ERROR:'실행 오류',RUNNING:'실행 중',CREATED:'접수',APPROVED:'승인',REJECTED:'거절'};
const time=value=>{const date=new Date(value);return value && !Number.isNaN(date.valueOf())?date.toLocaleString('ko-KR'):'미기록';};
const label=value=>statusNames[value] || value || '미기록';
const empty=text=>`<p class="approver-empty">${esc(text)}</p>`;
const requestNames={item_id:'자재',quantity:'수량',supplier_id:'공급원',unit_price_minor:'단가 (최소 화폐 단위)',currency:'통화',machine_id:'설비',operation_id:'작업',start_min:'시작 (분)',end_min:'종료 (분)',lot_id:'로트',request_id:'요청 번호',request_version:'요청 버전'};
export function requestMarkup(request) {
  return request && typeof request==='object'?`<dl class="approver-request-fields">${Object.entries(request).map(([key,value])=>`<div><dt>${esc(requestNames[key] || key)}</dt><dd>${esc(typeof value==='object'?JSON.stringify(value):value)}</dd></div>`).join('')}</dl>`:empty('저장된 요청 내용이 없습니다.');
}
export function decisionAvailable(run,userId,now=Date.now()) {
  return run.status==='WAITING_APPROVAL' && !!run.approval_request && run.created_by!==userId && Date.parse(run.approval_request.expires_at)>now;
}
export function reportVerdict(run) {
  const counts=run.summary || {}, findings=run.qa_report?.findings || [];
  if((counts.FAIL || 0)>0 || findings.some(f=>f.verdict==='FAIL'))return '기준 미충족';
  if(run.qa_report?.conclusion==='INSUFFICIENT_EVIDENCE' || (counts.INCONCLUSIVE || 0)>0 || findings.some(f=>f.verdict==='INCONCLUSIVE'))return '확인 필요';
  return (counts.PASS || 0)>0?'기준 충족':'판정 미확인';
}
function requestCard(run,userId,page) {
  const pending=run.status==='WAITING_APPROVAL', available=decisionAvailable(run,userId);
  return `<article class="approver-entry"><header><div><h2>${esc(run.test_id)} · ${esc(run.request?.request_id || run.run_id)}</h2><p class="live-hint">요청자 ${esc(run.created_by || '미기록')} · ${esc(time(run.created_at))}</p></div><span class="badge">${esc(label(run.approval?.decision || run.status))}</span></header>
    ${requestMarkup(run.request)}
    <p class="live-hint">승인 만료 ${esc(time(run.approval_request?.expires_at))} · <span class="mono">${esc(run.run_id)}</span></p>
    ${page==='approvals' && pending?`<div class="approval-actions"><button type="button" class="primary" data-decision="APPROVED" data-run="${esc(run.run_id)}" ${available?'':'disabled'}>요청 승인</button><button type="button" class="secondary danger-btn" data-decision="REJECTED" data-run="${esc(run.run_id)}" ${available?'':'disabled'}>요청 거절</button></div>${!available?`<p class="live-hint">${run.created_by===userId?'자신이 만든 요청은 승인할 수 없습니다.':'승인 기한이 지났습니다. 관리자가 새 시험을 실행해야 합니다.'}</p>`:''}`:''}
    ${page==='requests' && pending?'<button type="button" class="secondary" data-approver-go="approvals">승인 목록에서 결정하기</button>':''}</article>`;
}
function reportCard(run) {
  const r=run.qa_report,n=r.narrative || {},verdict=reportVerdict(run);
  return `<article class="approver-entry approver-report"><header><div><h2>${esc(r.test?.title || run.test_id)}</h2><p class="live-hint">${esc(n.agent_type_name || r.target?.name || 'Agent')} · ${esc(time(run.created_at))} · ${esc(run.run_id)}</p></div><span class="badge" data-result="${verdict==='기준 미충족'?'FAIL':verdict==='기준 충족'?'PASS':'INCONCLUSIVE'}">${verdict}</span></header>
    <p class="approver-conclusion">${esc(n.meaning || r.summary || '상세 판정을 확인해 주세요.')}</p>
    <dl class="approver-report-grid"><div><dt>시험 상황</dt><dd>${esc((n.scenario_steps || []).join(' ') || r.test?.title || '미기록')}</dd></div><div><dt>기대 행동</dt><dd>${esc(n.expected_behavior || '미기록')}</dd></div><div><dt>Agent의 실제 행동</dt><dd>${esc(n.agent_action || '미기록')}</dd></div><div><dt>실제 업무 결과</dt><dd>${esc(n.business_result || '미기록')}</dd></div></dl>
    <p class="live-hint">검사 기준: 충족 ${esc(run.summary?.PASS || 0)} · 미충족 ${esc(run.summary?.FAIL || 0)} · 판정 보류 ${esc(run.summary?.INCONCLUSIVE || 0)}</p>
    <details><summary>확인이 필요한 항목 · 근거 · 검증 한계</summary>${r.findings?.length?`<ul>${r.findings.map(f=>`<li><strong>${esc(f.verdict==='FAIL'?'미충족':'확인 필요')}</strong> ${esc(f.readable_reason || f.reason || f.rule_id)}<small>근거: ${esc((f.evidence_ids || []).join(', ') || '미기록')}</small></li>`).join('')}</ul>`:'<p>기록된 미충족·보류 항목이 없습니다.</p>'}<p>${esc(n.provenance || '')}</p><ul>${(r.limitations || []).map(text=>`<li>${esc(text)}</li>`).join('')}</ul></details>
    <button type="button" class="secondary" data-report-download="${esc(run.run_id)}">상세 보고서 저장</button></article>`;
}
export function approverListMarkup(runs,page,userId,query='') {
  const filtered=runs.filter(run=>page==='reports'?!!run.qa_report:!!run.approval_request)
    .filter(run=>!query || JSON.stringify(run).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  if(page==='reports')return filtered.map(reportCard).join('') || empty('조건에 맞는 완료된 QA 보고서가 없습니다.');
  if(page==='requests')return filtered.map(run=>requestCard(run,userId,page)).join('') || empty('관리자가 보낸 승인 요청이 없습니다.');
  const pending=filtered.filter(run=>run.status==='WAITING_APPROVAL'),history=filtered.filter(run=>run.status!=='WAITING_APPROVAL');
  return `<h2 class="approver-list-title">결정 대기 · ${pending.length}건</h2>${pending.map(run=>requestCard(run,userId,page)).join('') || empty('현재 결정할 승인 요청이 없습니다.')}<details class="approver-history"><summary>이전 승인 요청 · ${history.length}건</summary>${history.map(run=>requestCard(run,userId,page)).join('') || empty('이전 승인 요청이 없습니다.')}</details>`;
}
let cleanup;
let decisionOwner,decisions=new Map();
export function leaveApprover(){cleanup?.();cleanup=null;}
export function mountApprover(host,page,session,go,logout) {
  leaveApprover();
  if(decisionOwner!==session.user_id){decisions.clear();decisionOwner=session.user_id;}
  let active=true,runs=[],signature='',timer,busy=false,query='';
  const controller=new AbortController();
  cleanup=()=>{active=false;clearTimeout(timer);controller.abort();host.removeEventListener('click',click);};
  const descriptions={approvals:'관리자의 업무 변경 요청을 확인하고 승인 또는 거절하세요.',requests:'관리자가 QA 실행 중 보낸 승인 요청의 내용과 처리 상태입니다.',reports:'관리자가 수행한 QA 시험을 상황·기대 행동·실제 결과로 정리했습니다.'};
  host.innerHTML=`<section class="approver-workspace"><div class="page-header"><div><h1>${titles[page]}</h1><p>${descriptions[page]}</p></div><button type="button" class="secondary" data-approver-refresh>새로고침</button></div><p class="live-hint">최근 실행 200건과 모든 승인 대기 요청을 표시합니다. QA 결과는 각 시험 조건에 한정됩니다.</p><label class="approver-search">${page==='reports'?'보고서':'요청'} 검색<input type="search" placeholder="시험명, 요청자, 실행 번호로 검색" data-approver-search></label><p data-approver-message role="status" aria-live="polite">목록을 불러오는 중입니다…</p><div data-approver-list></div></section>`;
  const message=host.querySelector('[data-approver-message]'),list=host.querySelector('[data-approver-list]');
  const render=()=>{list.innerHTML=approverListMarkup(runs,page,session.user_id,query);for(const [id,retry] of decisions){const card=Array.from(list.querySelectorAll('.approver-entry')).find(el=>el.querySelector('[data-run]')?.dataset.run===id);if(!card)continue;card.querySelectorAll('[data-decision]').forEach(el=>{el.disabled=el.dataset.decision!==retry.decision;el.textContent=el.disabled?'다른 결정 선택 불가':'동일 결정으로 재개 요청';});if(retry.error)showError(card,describeError(retry.error,{runId:id}),{key:'decision',action:`data-resume-run="${esc(id)}"`});}};
  host.querySelector('[data-approver-search]').oninput=event=>{query=event.target.value;render();};
  async function refresh(manual=false){
    clearTimeout(timer);
    try {
      const data=await api('/qa/approver/runs',{token:session.access_token,signal:controller.signal});
      if(!active)return;
      const next=JSON.stringify(data.runs);
      runs=data.runs;
      if(signature!==next && !busy){signature=next;render();}
      const pill=document.getElementById('header-approval-pill'),pending=runs.filter(r=>r.status==='WAITING_APPROVAL').length;
      if(pill){pill.hidden=!pending;const text=pill.querySelector('span');if(text)text.textContent=`승인 대기 ${pending}`;}
      if(manual || message.textContent==='목록을 불러오는 중입니다…')message.textContent=`${time(new Date().toISOString())} 기준으로 불러왔습니다.`;
      clearError(host,'read');list.removeAttribute('data-stale');const header=document.getElementById('header-mode-label');if(header)header.textContent=`API 응답 확인 · ${time(new Date().toISOString())}`;
    }catch(error){if(!active)return;if(error.status===401){logout();return;}list.dataset.stale='true';showError(host,describeError(error,{title:'승인 목록 갱신 실패',action:'다시 불러오기'}),{key:'read',action:'data-approver-refresh'});const header=document.getElementById('header-mode-label');if(header)header.textContent='일부 조회 실패';}
    finally{if(active)timer=setTimeout(refresh,5000);}
  }
  async function click(event){
    const button=event.target.closest('button');if(!button || busy)return;
    if(button.hasAttribute('data-approver-go')){go(button.dataset.approverGo);return;}
    if(button.hasAttribute('data-approver-refresh')){button.disabled=true;await refresh(true);if(active)button.disabled=false;return;}
    if(button.hasAttribute('data-report-download')){
      const run=runs.find(r=>r.run_id===button.dataset.reportDownload);if(!run?.qa_report)return;
      try{const url=URL.createObjectURL(new Blob([qaReportDocument(run.qa_report)],{type:'text/html;charset=utf-8'}));
      const link=document.createElement('a');link.href=url;link.download=`${run.run_id}-QA.html`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);clearError(button.parentElement,'download');}catch(error){showError(button.parentElement,describeError(error,{title:'보고서 다운로드 실패',action:'다시 저장'}),{key:'download',focus:true,action:`data-report-download="${esc(run.run_id)}"`});}return;
    }
    if(button.hasAttribute('data-resume-run')){const next=Array.from(list.querySelectorAll('[data-run]')).find(el=>el.dataset.run===button.dataset.resumeRun && !el.disabled);next?.click();return;}
    if(!button.hasAttribute('data-decision'))return;
    const run=runs.find(r=>r.run_id===button.dataset.run);if(!run || !decisions.has(run.run_id) && !decisionAvailable(run,session.user_id))return;
    const retry=decisions.get(run.run_id);if(retry && retry.decision!==button.dataset.decision)return;
    const body=retry?.body || {approval_request_id:run.approval_request.approval_request_id,payload_hash:run.approval_request.payload_hash,decision:button.dataset.decision};
    busy=true;list.querySelectorAll('[data-decision]').forEach(el=>{el.disabled=true;});
    try {
      await api(`${run.simulation?'/qa':''}/runs/${encodeURIComponent(run.run_id)}/approval`,{token:session.access_token,body});
      decisions.delete(run.run_id);clearError(host,`decision-${run.run_id}`);if(active)message.textContent=`요청을 ${button.dataset.decision==='APPROVED'?'승인':'거절'}했습니다.`;
    }catch(error){if(active){
      if(error.status===401){logout();return;}
      if(error.details?.decision_saved)decisions.set(run.run_id,{decision:body.decision,body,error});
      showError(host,describeError(error,{write:true,runId:run.run_id}),{key:`decision-${run.run_id}`,focus:true,action:error.details?.decision_saved?`data-resume-run="${esc(run.run_id)}"`:'data-approver-refresh'});
    }}
    finally {busy=false;if(active){signature='';render();await refresh();}}
  }
  host.addEventListener('click',click);refresh();
}
