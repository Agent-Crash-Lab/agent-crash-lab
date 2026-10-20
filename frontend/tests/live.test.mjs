import test from 'node:test';
import assert from 'node:assert/strict';
import {api, mergeEvents, isFinished, sceneEvents, escapeHtml, testsForAgent, normalizeDraft, startPayload, workspaceRoute, runGuidance, nextActionHint} from '../dist/live-api.js';

test('events resume by sequence, deduplicate and reject another run',()=>{
  const event=sequence=>({sequence,run_id:'RUN-1',event_type:'TOOL_CALLED',node_id:'mcp'});
  assert.deepEqual(mergeEvents([event(2)],[event(3),event(1),event(2)],'RUN-1').map(e=>e.sequence),[1,2,3]);
  assert.throws(()=>mergeEvents([],[{...event(1),run_id:'RUN-2'}],'RUN-1'));
  assert.throws(()=>mergeEvents([],[event(0)],'RUN-1'));
});
test('completed execution keeps observing an ongoing investigation',()=>{
  assert.equal(isFinished({status:'COMPLETED',investigation:{status:'RUNNING'}}),false);
  assert.equal(isFinished({status:'COMPLETED',investigation:{status:'READY'}}),true);
  assert.equal(isFinished({status:'WAITING_APPROVAL'}),false);
});
test('render adapter preserves raw evidence and leaves unknown nodes unmapped',()=>{
  const raw={event_type:'APPROVAL_DECIDED',node_id:'mcp',sequence:1};
  assert.equal(sceneEvents([raw])[0].node_id,'approval');assert.equal(raw.node_id,'mcp');
  assert.equal(sceneEvents([{event_type:'NEW_EVENT',node_id:'unknown'}])[0].node_id,'unknown');
  assert.equal(escapeHtml('<script>"&'), '&lt;script&gt;&quot;&amp;');
});
test('public requests send only session auth and do not retry ambiguous writes',async()=>{
  const original=globalThis.fetch;let calls=0;
  try {
    globalThis.fetch=async(url,options)=>{
      calls++;assert.equal(url,'/api/runs');assert.equal(options.headers.Authorization,'Bearer session');
      assert.equal(options.headers['X-Internal-Token'],undefined);
      assert.equal(options.method,'POST');
      return {ok:false,status:503,json:async()=>({error:{code:'HARNESS_RESUME_FAILED',details:{decision_saved:true}}})};
    };
    await assert.rejects(api('/runs',{token:'session',body:{test_id:'S01'}}),error=>error.status===503 && error.details.decision_saved);
    assert.equal(calls,1);
  } finally {globalThis.fetch=original;}
});

test('non-JSON gateway failure is reported without rendering server HTML',async()=>{
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async()=>({status:502,json:async()=>{throw new Error('<html>gateway failure</html>');}});
    await assert.rejects(api('/runs'),error=>error.status===502 && !error.message.includes('<html>'));
  } finally {globalThis.fetch=original;}
});


const catalog={systems:[{system_id:'B0'},{system_id:'B1'}],tests:[
  {test_id:'S01',test_kind:'SYSTEM'}, {test_id:'S03',test_kind:'SYSTEM'},
  {test_id:'PA03',test_kind:'PURCHASE_AGENT'}, {test_id:'IA01',test_kind:'INVESTIGATION_AGENT'}
]};
test('actual Agent selection filters the server catalog and preserves conditions between pages',()=>{
  assert.deepEqual(testsForAgent(catalog,'purchase').map(t=>t.test_id),['S01','S03','PA03']);
  assert.deepEqual(testsForAgent(catalog,'investigator').map(t=>t.test_id),['IA01']);
  const draft={agent:'purchase',test_id:'S03',system_id:'B1'};
  assert.deepEqual(normalizeDraft(catalog,draft),draft);
  assert.deepEqual(normalizeDraft(catalog,{...draft,agent:'investigator'}),{agent:'investigator',test_id:'IA01',system_id:'B1'});
});
test('real execution uses selected conditions and never sends a SYSTEM policy to unit tests',()=>{
  assert.deepEqual(startPayload(catalog,{agent:'purchase',test_id:'S03',system_id:'B1'}),{test_id:'S03',system_id:'B1'});
  assert.deepEqual(startPayload(catalog,{agent:'investigator',test_id:'IA01',system_id:'B0'}),{test_id:'IA01'});
  assert.deepEqual(startPayload(catalog,{agent:'purchase',test_id:'PA03',system_id:'B1'}),{test_id:'PA03'});
  assert.throws(()=>startPayload(catalog,{agent:'purchase',test_id:'IA01',system_id:'B1'}));
  assert.throws(()=>startPayload(catalog,{agent:'purchase',test_id:'S03',system_id:'unknown'}));
});


test('all main routes point to real pages and demo routes are isolated',()=>{
  for(const page of ['agents','prepare','live','execution','compare'])assert.deepEqual(workspaceRoute('#'+page),{page});
  assert.deepEqual(workspaceRoute(''),{page:'agents'});
  assert.deepEqual(workspaceRoute('#unknown'),{page:'agents'});
  assert.deepEqual(workspaceRoute('#demo-prepare'),{page:'demo',demoTab:'prepare',show3d:false});
  assert.deepEqual(workspaceRoute('#demo-3d'),{page:'demo',demoTab:'agents',show3d:true});
});


test('workflow distinguishes approval, report generation, final collection and failed checks',()=>{
  const waiting=runGuidance({status:'WAITING_APPROVAL'});
  assert.equal(waiting.page,'live');assert.match(waiting.detail,/아직 발주하지/);
  const investigating=runGuidance({status:'COMPLETED',investigation:{status:'RUNNING'}});
  assert.match(investigating.title,/작성/);assert.doesNotMatch(investigating.title,/끝났/);
  assert.match(runGuidance({status:'COMPLETED'},false).title,/수집/);
  const failed=runGuidance({status:'COMPLETED',summary:{FAIL:3,INCONCLUSIVE:1}},true);
  assert.match(failed.detail,/실패 3건/);assert.match(failed.detail,/판정 보류 1건/);
  assert.doesNotMatch(failed.detail,/보고서/);
  assert.match(runGuidance({status:'COMPLETED',investigation:{report:{}}},true).detail,/조사 보고서/);
  assert.match(runGuidance({status:'ERROR',investigation:{status:'RUNNING'}}).title,/오류/);
  assert.match(runGuidance({status:'COMPLETED',investigation:{status:'ERROR'}},true).detail,/실패/);
});


test('one action hint points to the actionable control and never prompts a second running start',()=>{
  const base={session:{},page:'live',settled:false};
  assert.match(nextActionHint({...base,session:null}).selector,/login/);
  assert.match(nextActionHint(base).selector,/start/);
  assert.equal(nextActionHint({...base,pendingStart:true}),null);
  assert.equal(nextActionHint({...base,run:{status:'RUNNING'}}),null);
  assert.match(nextActionHint({...base,run:{status:'WAITING_APPROVAL'}}).selector,/approval-form/);
  assert.match(nextActionHint({...base,page:'execution',run:{status:'WAITING_APPROVAL'}}).selector,/guidance/);
  assert.match(nextActionHint({...base,page:'execution',run:{status:'COMPLETED'},settled:true}).selector,/show-results/);
  assert.match(nextActionHint({...base,page:'prepare',run:{status:'RUNNING'}}).selector,/guidance/);
  assert.equal(nextActionHint({...base,page:'compare',comparison:{}}),null);
});
