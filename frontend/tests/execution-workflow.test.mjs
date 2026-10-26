import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import * as api from '../dist/live-api.js';
import {purchaseTopology} from '../dist/topologies.js';
import {registeredCaseReady} from '../dist/qa-targets.js';

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
const catalog={systems:[{system_id:'B0'},{system_id:'B1'}]};
const selected={case_id:'generated-1',hypothesis:'설계 시험 <1>',execution:{status:'READY'},business_input:{quantity:37},design_basis:{expected_behavior_candidate:'중복 저장하지 않는다'}};
const plan={plan_id:'saved-plan',cases:[selected]};

function workspace(page){
 const elements=new Map();
 const host={querySelector(selector){
  if(!elements.has(selector))elements.set(selector,{dataset:{},innerHTML:'',hidden:false,remove(){},insertAdjacentHTML(){},parentElement:{prepend(){}},after(){}});
  return elements.get(selector);
 }};
 const ui=vm.runInNewContext(source+`;host=testHost;page=testPage;guidance=()=>{};actionHint=()=>{};renderEvents=()=>{};({state,selectedDesign,renderRun,renderBatch})`,{...api,esc:api.escapeHtml,purchaseTopology,registeredCaseReady,testHost:host,testPage:page});
 return {...ui,element:selector=>host.querySelector(selector)};
}

test('saved-plan execution sends exactly the selected IDs and rejects missing or blocked selection',()=>{
 assert.deepEqual(api.designStartPayload(catalog,plan,'generated-1','B1'),{plan_id:'saved-plan',case_id:'generated-1',system_id:'B1'});
 for(const [candidate,id,policy] of [[null,null,'B0'],[plan,null,'B0'],[plan,'other','B0'],[{...plan,cases:[{...selected,execution:{status:'UNSUPPORTED'}}]},'generated-1','B0'],[plan,'generated-1','unknown']]){
  assert.throws(()=>api.designStartPayload(catalog,candidate,id,policy));
 }
});

test('live progress keeps only the latest five real events, translates names and hides unknown payloads',()=>{
 const events=Array.from({length:8},(_,i)=>({sequence:i+1,event_type:i===7?'UNKNOWN_<script>':'BUSINESS_COMMITTED',occurred_at:'<badtime>',payload:{secret:'not displayed'}}));
 const html=api.progressEventsMarkup(events);
 assert.equal((html.match(/<li>/g)||[]).length,5);
 assert.doesNotMatch(html,/#1<|#2<|#3<|UNKNOWN|secret|<script>|<badtime>/);
 assert.match(html,/업무 변경 저장/);assert.match(html,/실행 기록/);assert.match(html,/&lt;badtime&gt;/);
 assert.ok(html.indexOf('#8')<html.indexOf('#4'));
});

test('conditions stay pinned to the saved run after another plan, target or policy is selected',()=>{
 const ui=workspace('live');
 ui.state.designPlan=plan;ui.state.designCaseId=selected.case_id;ui.state.draft.system_id='B0';
 ui.state.run={run_id:'RUN-original',test_id:'S03',system_id:'B1',manifest:{registered_target:{name:'Original Agent'},server_policy_version:'saved-policy'},qa_case:{...selected,hypothesis:'Saved scenario',business_input:{quantity:91}}};
 ui.selectedDesign();
 const html=ui.element('[data-live-design-selected]').innerHTML;
 assert.match(html,/Saved scenario|Original Agent|B1 · saved-policy|91/);
 assert.doesNotMatch(html,/설계 시험 &lt;1&gt;|>37<|선택 해제|<input|<select|<pre/);
 ui.state.designPlan=null;ui.state.registration={name:'Other Agent'};ui.state.targetType='QUALITY';ui.selectedDesign();
 assert.equal(ui.element('[data-live-design-selected]').innerHTML,html);
});

test('live renders approval and progress without verdict or analysis, and preserves approval form on polling',()=>{
 const ui=workspace('live');
 ui.state.run={run_id:'RUN-1',test_id:'S03',system_id:'B0',status:'WAITING_APPROVAL',request:{quantity:37},approval_request:{expires_at:'tomorrow'},summary:{PASS:5,FAIL:3}};
 ui.renderRun();
 assert.match(ui.element('[data-live-approval]').innerHTML,/data-live-approval-form/);
 assert.doesNotMatch(ui.element('[data-live-approval]').innerHTML,/<pre>/);
 assert.match(ui.element('[data-live-summary]').innerHTML,/최근 진행 기록|담당자 승인 대기/);
 assert.doesNotMatch(ui.element('[data-live-summary]').innerHTML,/PASS|FAIL|검사 판정/);
 assert.equal(ui.element('[data-live-analysis]').hidden,true);
 assert.equal(ui.element('[data-live-result]').hidden,true);
 // A polling tick must not replace an approval form being filled in.
 ui.element('[data-live-approval]').innerHTML='password entry in progress';ui.renderRun();
 assert.equal(ui.element('[data-live-approval]').innerHTML,'password entry in progress');
});

test('analysis exposes existing evidence and report without approval inputs; unsettled results stay pending',()=>{
 const ui=workspace('execution');
 ui.state.run={run_id:'RUN-1',test_id:'S03',status:'WAITING_APPROVAL',approval_request:{},summary:{},checks:[]};
 ui.renderRun();
 assert.doesNotMatch(ui.element('[data-live-approval]').innerHTML,/input|data-live-approval-form/);
 assert.match(ui.element('[data-live-summary]').innerHTML,/승인 처리로 이동/);
 assert.equal(ui.element('[data-live-analysis]').hidden,false);
 assert.equal(ui.element('[data-live-result]').hidden,false);
 assert.match(ui.element('[data-live-result]').innerHTML,/data-live-qa-report disabled/);
 const done=api.runGuidance({status:'COMPLETED',summary:{FAIL:7}},true,'live');
 assert.match(done.action,/결과 분석 보기/);assert.doesNotMatch(done.detail,/7|통과 0/);
 assert.match(api.runGuidance({status:'COMPLETED'},false,'live').title,/수집/);
});

function submitting(){
 const calls=[],errors=[],opened=[];let finish;
 const host={querySelector:()=>null};
 const context={...api,esc:api.escapeHtml,purchaseTopology,registeredCaseReady,testHost:host,
  FormData:class { *[Symbol.iterator](){yield ['case_id','forged-other-case'];} },
  api:(path,options)=>{calls.push({path,body:options.body});return new Promise(resolve=>{finish=resolve;});},
  errors,opened,crypto:{randomUUID:()=> 'stable-request'},
 };
 const ui=vm.runInNewContext(source+`;host=testHost;page='live';notify=()=>{};failure=e=>errors.push(e.message);account=()=>{};guidance=()=>{};renderRegistrations=()=>{};renderBatch=()=>{};pollBatch=()=>{};openRun=async id=>opened.push(id);({state,submit})`,context);
 Object.assign(ui.state,{session:{access_token:'session',roles:['REQUESTER']},catalog,designPlan:plan,designCaseId:selected.case_id});
 const event=selector=>({preventDefault(){},target:{matches:s=>s===selector,querySelectorAll:()=>[]}});
 return {...ui,calls,errors,opened,event,finish:result=>finish(result)};
}

test('start handler sends the saved selection once even when submitted twice while awaiting a response',async()=>{
 const ui=submitting(),first=ui.submit(ui.event('[data-live-start]'));
 await ui.submit(ui.event('[data-live-start]'));
 assert.equal(ui.calls.length,1);
 assert.equal(JSON.stringify(ui.calls[0]),JSON.stringify({path:'/runs',body:{plan_id:'saved-plan',case_id:'generated-1',system_id:'B0'}}));
 ui.finish({run_id:'RUN-new'});await first;
 assert.deepEqual(ui.opened,['RUN-new']);assert.equal(ui.state.pendingStart,false);assert.deepEqual(ui.errors,[]);
});

test('missing or blocked selection never falls back to a fixed scenario request',async()=>{
 for(const selectedId of [null,'missing']){
  const ui=submitting();ui.state.designCaseId=selectedId;
  await ui.submit(ui.event('[data-live-start]'));
  assert.equal(ui.calls.length,0);assert.equal(ui.errors.length,1);
 }
});

test('repeat experiments ignore form case overrides and use the same saved selection and policy',async()=>{
 const ui=submitting(),request=ui.submit(ui.event('[data-live-batch-form]'));
 assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].path,'/qa/batches');
 assert.equal(ui.calls[0].body.plan_id,'saved-plan');
 assert.equal(JSON.stringify(ui.calls[0].body.case_ids),'["generated-1"]');
 assert.equal(JSON.stringify(ui.calls[0].body.systems),'["B0"]');
 ui.finish({batch_id:'BATCH-1'});await request;assert.deepEqual(ui.errors,[]);
});

test('approval and rejection submit the decision for the same stored run with the approver session',async()=>{
 for(const [decision,simulation] of [['APPROVED',false],['REJECTED',true]]){
  const calls=[];let passwordCleared=false;
  const ui=vm.runInNewContext(source+`;host={};page='live';notify=()=>{};failure=e=>{throw e;};account=()=>{};renderRegistrations=()=>{};renderBatch=()=>{};poll=async()=>{};({state,submit})`,{
   ...api,esc:api.escapeHtml,purchaseTopology,
   FormData:class { *[Symbol.iterator](){yield ['user_id','approver-01'];yield ['password','test-password'];} },
   api:async(path,options)=>{calls.push({path,...options});return {access_token:'approver-session'};},
  });
  ui.state.session={access_token:'requester-session'};
  ui.state.run={run_id:'RUN-original',manifest:simulation?{state_store:'simulation'}:{},approval_request:{approval_request_id:'AP-original',payload_hash:'saved-hash'}};
  const form={matches:s=>s==='[data-live-approval-form]',querySelectorAll:()=>[],password:{set value(value){passwordCleared=value==='';}}};
  await ui.submit({preventDefault(){},target:form,submitter:{value:decision}});
  assert.equal(calls[1].path,`${simulation?'/qa':''}/runs/RUN-original/approval`);
  assert.equal(calls[1].token,'approver-session');
  assert.equal(calls[1].body.decision,decision);assert.equal(calls[1].body.payload_hash,'saved-hash');
  assert.equal(passwordCleared,true);
 }
});
