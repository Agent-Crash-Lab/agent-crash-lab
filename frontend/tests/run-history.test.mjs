import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import * as api from '../dist/live-api.js';
import {purchaseTopology} from '../dist/topologies.js';
const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
const logic=source.slice(source.indexOf('function startDesignProgress('),source.indexOf('function click(event)'));

test('run list and individual run URLs survive route parsing, including encoded IDs',()=>{
 assert.deepEqual(api.workspaceRoute('#runs'),{page:'runs'});
 for(const page of ['live','execution'])assert.deepEqual(api.workspaceRoute(`#${page}?run=RUN%2F001`),{page,runId:'RUN/001'});
 assert.deepEqual(api.workspaceRoute('#execution?run='),{page:'execution'});
});

test('each saved run has its own analysis action, status, conditions and escaped labels',()=>{
 const runs=[{run_id:'RUN-001',test_id:'S01',status:'WAITING_APPROVAL',system_id:'B0',created_at:'2026-10-25T01:00:00Z'},
  {run_id:'RUN-002',test_id:'S01',status:'COMPLETED',created_by:'<admin>',summary:{FAIL:1},created_at:'bad'},
  {run_id:'RUN-<script>',test_id:'S01',status:'ERROR'}];
 const html=api.runListMarkup(runs,{tests:[{test_id:'S01',title:'<발주 시험>'}]},'RUN-001');
 for(const text of ['data-live-run="RUN-001"','data-live-run="RUN-002"','담당자 승인 대기','실행 완료','미충족 1','실행 오류','S01 · B0','열어 본 실행','시각 미상','&lt;발주 시험&gt;','&lt;admin&gt;','RUN-&lt;script&gt;'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/<script>|<admin>|<발주 시험>/);
});

test('run links fetch current state and open control or analysis with the selected run URL',async()=>{
 for(const [status,destination] of [['RUNNING','live'],['WAITING_APPROVAL','live'],['COMPLETED','execution'],['ERROR','execution']]){
  const routes=[];
  const ui=vm.runInNewContext(source+`;host={querySelector:()=>null};go=(...args)=>routes.push(args);({state,click})`,{...api,purchaseTopology,routes,clearInterval(){},esc:api.escapeHtml,api:async()=>({status}),failure(error){throw error;}});
  ui.state.session={access_token:'session'};ui.state.run={run_id:'RUN-old'};
  const button={dataset:{liveRun:'RUN-001'},hasAttribute:name=>name==='data-live-run'};
  await ui.click({target:{closest:()=>button}});
  assert.equal(ui.state.pendingRunId,'RUN-001');assert.deepEqual(routes.map(args=>Array.from(args)),[[destination,'RUN-001']]);
 }
});

test('a slower run-link lookup cannot replace the most recently selected run',async()=>{
 const requests=[],routes=[];
 const ui=vm.runInNewContext(source+`;host={querySelector:()=>null};go=(...args)=>routes.push(args);({state,openRunDestination})`,{...api,purchaseTopology,routes,clearInterval(){},esc:api.escapeHtml,api:()=>new Promise(resolve=>requests.push(resolve))});
 ui.state.session={access_token:'session'};
 const first=ui.openRunDestination('RUN-001'),second=ui.openRunDestination('RUN-002');
 requests[1]({status:'RUNNING'});await second;requests[0]({status:'COMPLETED'});await first;
 assert.deepEqual(routes.map(args=>Array.from(args)),[['live','RUN-002']]);
});

test('requester login always offers the tutorial, defaults to targets, and preserves bookmarked runs',async()=>{
 for(const [hash,runs,expected] of [['#execution?run=RUN-001',[{}],['execution','RUN-001']],['#agents',[{}],['agents']],['#runs',[{}],['agents']],['#agents',[],['agents']]]){
  const routes=[];let tutorials=0;
  const context={...api,location:{hash},FormData:class { *[Symbol.iterator](){yield ['user_id','requester-01'];} },
   resolved(){},showFailures(){},generation:1,host:{},state:{approvalRetries:{},approvalUnknown:{},session:null,runs},isApproverAccount:()=>false,notify(){},failure(error){throw error;},renderRegistrations(){},account(){},renderBatch(){},
   api:async()=>({access_token:'session'}),refresh:async()=>{},refreshBatch:async()=>{},go:(...args)=>routes.push(args),
   document:{getElementById:()=>({showModal(){tutorials++;}})}};
  const {submit}=vm.runInNewContext(logic+';({submit})',context);
  await submit({preventDefault(){},target:{matches:s=>s==='[data-live-login]',querySelectorAll:()=>[],reset(){}}});
  assert.deepEqual(routes,expected?[expected]:[]);assert.equal(tutorials,1);
  if(expected?.[1])assert.equal(context.state.pendingRunId,'RUN-001');
 }
});

test('list reads send search, status and page and discard an older response after filters change',async()=>{
 const requests=[];let scheduled=0;
 const context={...api,URLSearchParams,purchaseTopology,esc:api.escapeHtml,
  api:url=>new Promise(resolve=>requests.push({url,resolve})),
  clearTimeout(){},setTimeout(){scheduled++;},testHost:{}};
 const ui=vm.runInNewContext(source+`;host=testHost;page='runs';renderRunList=()=>{};({state,refreshRunList})`,context);
 ui.state.session={access_token:'session'};ui.state.runList.q='RUN-001';ui.state.runList.offset=20;
 const old=ui.refreshRunList();
 ui.state.runList.status='WAITING_APPROVAL';ui.state.runList.offset=0;
 const latest=ui.refreshRunList();
 const url=new URL(requests[1].url,'http://local');
 assert.equal(url.searchParams.get('q'),'RUN-001');assert.equal(url.searchParams.get('status'),'WAITING_APPROVAL');assert.equal(url.searchParams.get('offset'),'0');
 requests[1].resolve({runs:[{run_id:'RUN-new'}],has_more:false});await latest;
 requests[0].resolve({runs:[{run_id:'RUN-stale'}],has_more:true});await old;
 assert.equal(ui.state.runList.runs[0].run_id,'RUN-new');assert.equal(ui.state.runList.hasMore,false);assert.equal(scheduled,1);
});

test('switching runs clears old evidence and ignores the slower previous selection',async()=>{
 const requests=[],urls=[],polled=[];
 const context={...api,URLSearchParams,purchaseTopology,esc:api.escapeHtml,testHost:{querySelector:()=>({})},
  api:url=>new Promise(resolve=>requests.push({url,resolve})),clearTimeout(){},
  window:{history:{replaceState:(_state,_title,url)=>urls.push(url)}}};
 const ui=vm.runInNewContext(source+`;host=testHost;page='execution';renderRun=()=>{};renderBatch=()=>{};poll=async()=>polled.push(state.run.run_id);({state,openRun})`,{...context,polled});
 ui.state.session={access_token:'session'};ui.state.events=[{run_id:'old'}];
 const first=ui.openRun('RUN-001'),second=ui.openRun('RUN-002');
 assert.equal(ui.state.events.length,0);assert.equal(ui.state.settled,false);
 requests[1].resolve({run_id:'RUN-002'});await second;
 requests[0].resolve({run_id:'RUN-001'});await first;
 assert.equal(ui.state.run.run_id,'RUN-002');assert.deepEqual(polled,['RUN-002']);assert.deepEqual(urls,['#execution?run=RUN-002']);
});
