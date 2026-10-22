import { registerProfile } from './registry.js?v=0.13.1';
import { validateRegistration } from './topology.js?v=0.13.1';
import { registrationExample } from './topologies.js?v=0.13.1';
let dialog;
export function initRegistration(onRegistered){
 dialog=document.createElement('dialog');dialog.className='registration-dialog';dialog.id='registration-dialog';dialog.setAttribute('aria-labelledby','registration-title');
 dialog.innerHTML=`<form id="registration-form"><div class="registration-heading"><div><span class="eyebrow">구조와 샘플 이벤트</span><h2 id="registration-title">Agent 구조 등록</h2></div><button type="button" id="registration-close" class="secondary" aria-label="등록 창 닫기">닫기</button></div><p>Agent 이름·버전과 노드·연결·역할을 함께 등록합니다. 구조는 이 브라우저에 저장되며 실제 Agent 연결이나 실행은 하지 않습니다.</p><div class="registration-guide"><strong>노드</strong> id · label · role · layer · lane(선택)<br><strong>연결</strong> id · source · target · label<br><strong>샘플 이벤트</strong> event_id · sequence · node_id · edge_id(선택) · type · title</div><div class="registration-heading"><label for="registration-json">등록 정보 JSON</label><button type="button" class="text-button" id="registration-example">리서치 Agent 예시 채우기</button></div><textarea id="registration-json" rows="17" spellcheck="false" required aria-describedby="registration-help"></textarea><p id="registration-help">role: agent, runner, approval, tool, database, store, report, reviewer · layer: 0~5 · 최대 노드 16개 / 연결 32개 / 이벤트 200개. events를 비우면 구조만 미리볼 수 있습니다. 인증정보를 입력하지 마세요.</p><div id="registration-feedback" role="status" aria-live="polite"></div><div class="flow-actions"><button type="button" class="secondary" id="registration-validate">구조와 이벤트 점검</button><button type="submit" class="primary">등록하고 3D 보기 →</button></div></form>`;
 document.body.append(dialog);
 const textarea=dialog.querySelector('textarea'),feedback=dialog.querySelector('#registration-feedback');
 textarea.addEventListener('input',()=>feedback.replaceChildren());
 const show=(messages,ok)=>{feedback.className=ok?'registration-valid':'registration-errors';feedback.replaceChildren();for(const message of messages){const p=document.createElement('p');p.textContent=message;feedback.append(p);}};
 function parse(){try{if(textarea.value.length>100000)throw new Error('등록 정보는 100 KB 이하로 입력하세요.');return JSON.parse(textarea.value);}catch(e){show([e instanceof SyntaxError?'JSON 형식을 확인하세요.':e.message],false);return null;}}
 dialog.querySelector('#registration-example').addEventListener('click',()=>{textarea.value=JSON.stringify(registrationExample,null,2);feedback.replaceChildren();});
 dialog.querySelector('#registration-close').addEventListener('click',()=>dialog.close());
 dialog.querySelector('#registration-validate').addEventListener('click',()=>{const input=parse();if(!input)return;const r=validateRegistration(input);show(r.ok?['구조와 이벤트 매핑이 유효합니다. 실제 실행 API는 검사하지 않았습니다.']:r.errors,r.ok);});
 dialog.querySelector('form').addEventListener('submit',event=>{event.preventDefault();const input=parse();if(!input)return;const r=registerProfile(input);if(!r.ok){show(r.errors,false);return;}dialog.close();onRegistered(r);});
 textarea.value=JSON.stringify(registrationExample,null,2);
}
export function openRegistration(){dialog.showModal();}
