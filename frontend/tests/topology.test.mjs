import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as topology from '../dist/topology.js';
import * as registry from '../dist/registry.js';
import {purchaseTopology,investigationTopology,registrationExample} from '../dist/topologies.js';
const clone=structuredClone;
const source=fs.readFileSync(new URL('../dist/app.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').split("document.addEventListener('click'")[0];
function application(){return vm.runInNewContext(source+`;render=()=>{};toast=message=>{state.lastToast=message;};({state,eventsFor,checksFor,loadDemo,selectAgent,verifyAgent,open3DDemo,agentView,executionView,prepareView,compareView,withDraft,structureView})`,{...registry,restoreProfiles:()=>{},...topology,structuredClone,setTimeout,clearTimeout,history:{replaceState(){}},console});}

test('all 9 demo scenarios map every event to the selected graph and retain check references',()=>{
 const app=application();
 for(const [id,agent] of Object.entries(registry.agents)){
  assert.ok(topology.validateTopology(agent.topology).ok);
  for(const scenario of agent.scenarios)for(const config of id==='purchase'?['B0','B1']:['B0']){
   const events=app.eventsFor(scenario,config);
   assert.ok(topology.mapEvents(agent.topology,events).every(m=>m.ok),`${scenario}/${config}`);
   assert.ok(app.checksFor(scenario,config).every(c=>events[c.evidence]));
  }
  assert.ok(registry.validateDemoProfile(id,s=>app.eventsFor(s,'B0'),app.checksFor).ok);
 }
});
test('different demo structures generate distinct platform counts, node sets and positions',()=>{
 const a=topology.layoutTopology(purchaseTopology),b=topology.layoutTopology(investigationTopology);
 assert.equal(a.platforms.length,4);assert.equal(b.platforms.length,3);
 assert.equal(a.nodes.length,7);assert.equal(b.nodes.length,6);
 assert.ok(a.nodes.some(n=>n.role==='database'));assert.ok(!b.nodes.some(n=>n.role==='database'||n.role==='approval'));
 for(const layout of [a,b]){assert.equal(new Set(layout.nodes.map(n=>n.position.join(','))).size,layout.nodes.length);assert.ok(layout.nodes.every(n=>n.position.every(Number.isFinite)));}
});
test('replay highlights only the mapped edge, counts committed records up to the cursor, and rewinds',()=>{
 const app=application(),events=app.eventsFor('S03','B0');
 const fault=topology.frameFor(purchaseTopology,events,5);
 assert.equal(fault.activeNode,'mcp');assert.equal(fault.activeEdge,'response');assert.equal(fault.fault,true);assert.equal(fault.commits.db,1);
 assert.equal(topology.frameFor(purchaseTopology,events,7).commits.db,2);
 assert.equal(topology.frameFor(purchaseTopology,events,2).commits.db,0);
 assert.ok(!topology.frameFor(purchaseTopology,events,2).observedEdges.includes('commit'));
 const guide=topology.frameFor(investigationTopology,app.eventsFor('IA01'),2);
 assert.equal(guide.activeNode,'guide');assert.equal(guide.activeEdge,'search-guide');assert.equal(guide.commits.db,undefined);
});
test('missing nodes, unknown edges and unrelated edge endpoints never fall back to another node',()=>{
 for(const event of [{node_id:'unknown'},{node_id:'agent',edge_id:'unknown'},{node_id:'agent',edge_id:'commit'}]){
  const frame=topology.frameFor(purchaseTopology,[event],0);
  assert.equal(frame.activeNode,null);assert.equal(frame.activeEdge,null);assert.equal(frame.unmapped.length,1);
 }
});
test('registration rejects duplicates, dangling links, invalid roles, invalid sequence and malformed events',()=>{
 const mutations=[x=>x.topology.nodes.push(clone(x.topology.nodes[0])),x=>x.topology.edges[0].target='missing',x=>x.topology.nodes[0].role='execute-script',x=>x.events[0].sequence=9,x=>x.events[0]=null,x=>x.events[0].node_id='missing',x=>x.events[0].edge_id='retrieve',x=>x.id='constructor',x=>x.topology.nodes[0].layer=NaN];
 for(const mutate of mutations){const x=clone(registrationExample);mutate(x);assert.equal(topology.validateRegistration(x).ok,false);}
 assert.ok(topology.validateRegistration(registrationExample).ok);
 const empty=clone(registrationExample);empty.events=[];assert.ok(topology.validateRegistration(empty).ok);assert.equal(topology.frameFor(empty.topology,[],0).activeNode,null);
});
test('registration stores a new profile, restores it and cannot overwrite a built-in',()=>{
 let saved;const storage={setItem(k,v){saved=v;},getItem(){return saved;}};
 const result=registry.registerProfile(registrationExample,storage);assert.ok(result.ok);assert.ok(result.persisted);
 const graph=clone(registry.agents['research-demo'].topology);delete registry.agents['research-demo'];registry.restoreProfiles(storage);
 assert.deepEqual(registry.agents['research-demo'].topology,graph);
 assert.equal(registry.registerProfile({...registrationExample,id:'purchase'},storage).ok,false);
 delete registry.agents['research-demo'];
});
test('switching draft Agent preserves current run and pins a topology snapshot; both demos open in 3D',()=>{
 const app=application();app.open3DDemo();assert.equal(app.state.mode,'spatial');const current=clone(app.state.run.topology);
 app.selectAgent('investigator');assert.equal(app.state.agentId,'purchase');assert.deepEqual(app.state.run.topology,current);
 app.verifyAgent();app.loadDemo();assert.equal(app.state.agentId,'investigator');assert.equal(app.state.mode,'spatial');assert.equal(app.state.run.topology.nodes.length,6);
 assert.notEqual(app.state.run.topology,registry.agents.investigator.topology);
 assert.match(app.executionView(),/3D 실행도/);assert.doesNotMatch(app.executionView(),/disabled title="조사/);
 app.selectAgent('purchase');assert.equal(app.state.run.topology.version,'investigation-topology-v1');
});
test('all playback positions render with structure context and HTML in registered labels is escaped',()=>{
 const app=application();
 for(const id of ['purchase','investigator']){app.selectAgent(id);app.verifyAgent();for(const scenario of registry.agents[id].scenarios){app.state.draft.scenario=scenario;app.loadDemo();for(let cursor=0;cursor<app.eventsFor().length;cursor++){app.state.cursor=cursor;assert.doesNotMatch(app.executionView(),/undefined/);}assert.doesNotMatch(app.compareView(),/undefined/);}}
 const input=clone(registrationExample);input.name='<img src=x onerror=alert(1)>';registry.registerProfile(input,{setItem(){}});app.selectAgent(input.id);
 assert.ok(app.agentView().includes('&lt;img'));assert.ok(!app.agentView().includes('<img src=x'));assert.ok(app.structureView().includes('&lt;img'));app.state.previewMode='timeline';assert.match(app.structureView(),/data-preview-node/);assert.doesNotMatch(app.structureView(),/id="structure-host"/);
 delete registry.agents[input.id];
});


test('demo profiles do not report the connected system as disconnected and link to real execution',()=>{
 const app=application();
 const profile=app.agentView();
 assert.ok(!profile.includes('실제 서버 미연결'));
 assert.ok(!profile.includes('미지정 / 미연결'));
 assert.ok(profile.includes('데모 참조 프로필'));
 assert.ok(profile.includes('data-tab="live"'));
 app.verifyAgent();
 const prepare=app.withDraft(app.prepareView);
 assert.ok(!prepare.includes('LIVE 시험 · 연결 필요'));
 assert.ok(prepare.includes('data-tab="live"'));
});


test('demo data check does not show a server connection failure notification',()=>{
 const app=application();app.verifyAgent();
 assert.equal(app.state.verified.purchase.ok,true);
 assert.equal(app.state.lastToast,'데모 데이터 점검 완료. 실제 시험은 ‘실제 실행’ 메뉴에서 시작하세요.');
 assert.ok(!app.agentView().includes('데모 연결 점검'));
 assert.ok(app.agentView().includes('데모 데이터 점검하기') || app.agentView().includes('다시 점검'));
});
