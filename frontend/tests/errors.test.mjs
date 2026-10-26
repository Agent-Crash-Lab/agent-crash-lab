import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {purchaseTopology} from '../dist/topologies.js';
import * as helpers from '../dist/live-api.js';
import {captureForms,restoreForms,describeError,errorMarkup} from '../dist/errors.js';

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
function workspace(extra={}){
 return vm.runInNewContext(source+`;host=testHost;go=(...args)=>routes.push(args);({state,failure,resolved,expireSession,refresh,pollBatch,submit})`,{
  ...helpers,purchaseTopology,testHost:{querySelector:()=>null,querySelectorAll:()=>[]},routes:[],
  leaveApprover(){},clearTimeout(){},clearInterval(){},setTimeout(){return 1;},...extra
 });
}
test('error copy separates credentials, unknown writes, saved decisions and configuration',()=>{
 assert.match(describeError({status:401},{auth:true}).title,/로그인/);
 assert.equal(describeError({transport:true},{write:true}).severity,'pending');
 assert.match(describeError({code:'INVALID_RESPONSE'},{write:true}).title,/접수 여부/);
 assert.match(describeError({details:{decision_saved:true}},{write:true}).action,/동일 결정/);
 assert.match(describeError({code:'LLM_BUDGET_EXHAUSTED'}).description,/예산/);
 assert.doesNotMatch(errorMarkup(describeError({message:'password=secret',code:'<script>secret</script>'})),/password=secret|<script>|secret/);
 const markup=errorMarkup({title:'<img>',description:'<script>',action:'재시도'},'data-retry');
 assert.match(markup,/&lt;img&gt;/);assert.doesNotMatch(markup,/<script>/);
});

test('one successful operation cannot erase another operation error',()=>{
 const ui=workspace();
 ui.failure({status:503},{key:'approval'});ui.failure({transport:true},{key:'targets'});
 ui.resolved('targets');
 assert.ok(ui.state.errors.approval);assert.equal(ui.state.errors.targets,undefined);
});

test('auxiliary authentication does not expire requester session; own 401 does',()=>{
 const routes=[];const ui=workspace({routes});
 ui.state.session={user_id:'requester-01',roles:['REQUESTER'],access_token:'private'};
 ui.failure({status:401},{key:'approval',auth:true,auxiliary:true});
 assert.equal(ui.state.session.user_id,'requester-01');
 ui.failure({status:401});
 assert.equal(ui.state.session,null);assert.equal(ui.state.resume.userId,'requester-01');
 assert.equal(ui.state.resume.access_token,undefined);assert.equal(routes.length,1);
});

test('partial refresh keeps successful resources and prior failed resource data',async()=>{
 // Rendering is outside this state transition test.
 const run=vm.runInNewContext(source+`;host=testHost;state.session={access_token:'test'};state.targetTypes=[{type_id:'previous'}];catalog=history=account=renderRunList=showFailures=()=>{};({state,refresh})`,{
  ...helpers,purchaseTopology,testHost:{querySelector:()=>null,querySelectorAll:()=>[]},api:async path=>{if(path==='/qa/targets')throw {status:503};return path==='/scenarios'?{tests:[],systems:[]}:path==='/runs'?{runs:[{run_id:'new'}]}:{profiles:[],capabilities:[]};}
 });
 await run.refresh();assert.equal(run.state.runs[0].run_id,'new');assert.equal(run.state.targetTypes[0].type_id,'previous');assert.equal(run.state.readStatus.targets.failed,true);assert.equal(run.state.readStatus.history.failed,false);
});

test('batch read failure schedules reconnect without replaying a write',async()=>{
 const delays=[];let calls=0;
 const ui=workspace({api:async()=>{calls++;throw {transport:true};},setTimeout:(_fn,delay)=>delays.push(delay)});
 ui.state.session={access_token:'test'};ui.state.batch={batch_id:'batch'};
 await ui.pollBatch();assert.equal(calls,1);assert.deepEqual(delays,[3000]);
});

test('form memory excludes passwords and restores values without submitting',()=>{
 const fields=[{name:'name',value:'작성 중',type:'text'},{name:'password',value:'secret',type:'password'},{name:'decision',value:'APPROVED',type:'submit'}];
 const form={attributes:[{name:'data-registration'}],elements:fields,matches:()=>false,querySelectorAll:()=>[]};
 const saved=captureForms({querySelectorAll:()=>[form]});
 assert.equal(saved[0].fields.length,1);assert.doesNotMatch(JSON.stringify(saved),/secret|APPROVED/);
 fields[0].value='';restoreForms({querySelector:()=>form},saved);assert.equal(fields[0].value,'작성 중');
});

test('same identity restores work without tutorial or submission; different identity resets it',async()=>{
 for(const same of [true,false]){
  const routes=[],calls=[];let tutorial=0;
  const context={...helpers,purchaseTopology,testHost:{querySelector:()=>null,querySelectorAll:()=>[]},routes,
   clearTimeout(){},clearInterval(){},leaveApprover(){},pauseScene(){},
   FormData:class{*[Symbol.iterator](){yield ['user_id','requester-01'];yield ['password','new-password'];}},
   api:async(path)=>{calls.push(path);return {user_id:same?'requester-01':'someone-else',roles:['REQUESTER'],access_token:'new-token'};},
   document:{getElementById:()=>({showModal(){tutorial++;}})}};
  const ui=vm.runInNewContext(source+`;host=testHost;go=(...args)=>routes.push(args);renderRegistrations=account=renderBatch=()=>{};({state,submit})`,context);
  ui.state.resume={userId:'requester-01',roles:'REQUESTER',page:'live',runId:'RUN-1',forms:[{fields:[{name:'name',value:'saved'}]}]};
  ui.state.designCaseId='old-case';
  const form={matches:s=>s==='[data-live-login]',querySelectorAll:()=>[],reset(){}};
  await ui.submit({preventDefault(){},target:form});
  assert.deepEqual(calls,['/auth/login']);assert.equal(tutorial,0);
  if(same){assert.equal(ui.state.restore[0].fields[0].value,'saved');assert.equal(routes[0][0],'live');assert.equal(routes[0][1],'RUN-1');}
  else{assert.equal(ui.state.designCaseId,null);assert.equal(ui.state.restore,null);assert.equal(routes.at(-1)[0],'agents');}
 }
});

test('malformed server responses and network writes are reported without replay',async()=>{
 const savedFetch=globalThis.fetch;let calls=0;
 try{
  globalThis.fetch=async()=>{calls++;return {ok:true,status:200,json:async()=>null};};
  await assert.rejects(helpers.api('/runs',{body:{test_id:'S01'}}),e=>e.code==='INVALID_RESPONSE');
  assert.equal(calls,1);
  globalThis.fetch=async()=>{calls++;throw new TypeError('Failed to fetch');};
  await assert.rejects(helpers.api('/runs',{body:{test_id:'S01'}}),e=>e.transport && describeError(e,{write:true}).severity==='pending');
  assert.equal(calls,2);
 }finally{globalThis.fetch=savedFetch;}
});
