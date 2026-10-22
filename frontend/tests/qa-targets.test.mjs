import test from 'node:test';
import assert from 'node:assert/strict';
import {parseTools, exampleDeclaration, profileAnalysis} from '../dist/qa-targets.js';

test('MCP tools/list imports hints as declarations and does not guess names',()=>{
  const tools=parseTools(JSON.stringify({result:{tools:[
    {name:'get_inventory',inputSchema:{type:'object'}},
    {name:'lookup',inputSchema:{type:'object'},annotations:{readOnlyHint:true}},
    {name:'create',inputSchema:{type:'object'},annotations:{readOnlyHint:false}}
  ]}}));
  assert.equal(tools[0].effect,'');assert.equal(tools[1].effect,'READ');assert.equal(tools[2].effect,'WRITE');
});
test('invalid and duplicate tool definitions are rejected',()=>{
  for(const text of ['{','{}','[]',JSON.stringify([{name:'x',inputSchema:{}},{name:'x',inputSchema:{}}]),JSON.stringify([{name:'x'}])])assert.throws(()=>parseTools(text));
});
test('reference import downgrades assurance and never copies adapter registration',()=>{
  const data=exampleDeclaration({target:{target_version:'1',simulation_adapter:'reference-purchase-v1',tools:[],qa_scope:{capabilities:[{name:'order_write',tool_name:'create',basis:'EXECUTION_VERIFIED'}]}},sample_data:{}});
  assert.equal(data.capability_bindings[0].basis,'DECLARED');assert.equal(data.simulation_adapter,undefined);
});
test('analysis distinguishes proposals, missing facts and runtime evidence and escapes input',()=>{
  const html=profileAnalysis({name:'<script>',version:'1',can_design:false,analysis:{risk_screening:[{title:'Retry',status:'NEEDS_INFORMATION',reason:'Policy unknown',missing_capabilities:[]}]}});
  assert.ok(!html.includes('<script>'));assert.match(html,/추가 정보 1개/);assert.match(html,/실제 코드·권한 확인 전/);assert.match(html,/data-qa-plan disabled/);
});


test('registered execution requires the same connected profile and a ready selected case',async()=>{
  const {registeredCaseReady}=await import('../dist/qa-targets.js');
  const registration={profile_id:'P1',execution_status:'CONNECTED',execution_binding:{runtime_id:'reference-purchase-v1'}};
  const plan={design:{registration:{profile_id:'P1',execution_binding:{runtime_id:'reference-purchase-v1'}}},cases:[{case_id:'C1',execution:{status:'READY'}}]};
  assert.equal(registeredCaseReady(registration,plan,'C1'),true);
  assert.equal(registeredCaseReady(registration,plan,'other'),false);
  assert.equal(registeredCaseReady({...registration,profile_id:'P2'},plan,'C1'),false);
  assert.equal(registeredCaseReady({...registration,execution_status:'ADAPTER_REQUIRED'},plan,'C1'),false);
  assert.equal(registeredCaseReady(registration,{...plan,cases:[{case_id:'C1',execution:{status:'UNSUPPORTED'}}]},'C1'),false);
});
