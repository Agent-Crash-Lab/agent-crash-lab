import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as topology from '../dist/topology.js';
import {progressEventsMarkup} from '../dist/live-api.js';
import * as registry from '../dist/registry.js';
import {referenceTargetTypes,targetTypeMeta,renderChainSvg} from '../dist/live.js';
import {purchaseTopology,investigationTopology,registrationExample} from '../dist/topologies.js';
const clone=structuredClone;
const source=fs.readFileSync(new URL('../dist/app.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').split("document.addEventListener(")[0];
function application(document,timers={}){return vm.runInNewContext(source+`;render=()=>{};toast=message=>{state.lastToast=message;};({state,eventsFor,checksFor,loadDemo,selectAgent,verifyAgent,open3DDemo,agentView,executionView,prepareView,compareView,withDraft,structureView,renderCoachmark,navigate,tutorialMilestone,tutorialGuideSteps,setTutorialGuideStep,demoTargetsView,openDemoSample,generateDemoProposals,chooseScenario,finishDemoApproval,demoRunView,practiceTutorial})`,{document,referenceTargetTypes,targetTypeMeta,renderChainSvg,progressEventsMarkup,...registry,restoreProfiles:()=>{},...topology,structuredClone,setTimeout,clearTimeout,...timers,history:{replaceState(){}},console});}

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
 const app=application();app.open3DDemo();assert.equal(app.state.mode,'spatial');assert.equal(app.state.tab,'execution');const current=clone(app.state.run.topology);
 app.selectAgent('investigator');assert.equal(app.state.agentId,'purchase');assert.deepEqual(clone(app.state.run.topology),current);
 app.verifyAgent();app.loadDemo();assert.equal(app.state.agentId,'investigator');assert.equal(app.state.mode,'spatial');assert.equal(app.state.run.topology.nodes.length,6);
 assert.notEqual(app.state.run.topology,registry.agents.investigator.topology);
 assert.match(app.executionView(),/실행 흐름/);assert.doesNotMatch(app.executionView(),/disabled title="조사/);
 app.selectAgent('purchase');assert.equal(app.state.run.topology.version,'investigation-topology-v1');
});
test('all playback positions render with structure context and HTML in registered labels is escaped',()=>{
 const app=application();
 for(const id of ['purchase','investigator']){app.selectAgent(id);app.verifyAgent();for(const scenario of registry.agents[id].scenarios){app.state.draft.scenario=scenario;app.loadDemo();for(let cursor=0;cursor<app.eventsFor().length;cursor++){app.state.cursor=cursor;assert.doesNotMatch(app.executionView(),/undefined/);}assert.doesNotMatch(app.compareView(),/undefined/);}}
 const input=clone(registrationExample);input.name='<img src=x onerror=alert(1)>';registry.registerProfile(input,{setItem(){}});app.selectAgent(input.id);
 assert.ok(!app.agentView().includes('<img src=x'));assert.ok(app.structureView().includes('&lt;img'));app.state.previewMode='timeline';assert.match(app.structureView(),/data-preview-node/);assert.doesNotMatch(app.structureView(),/id="structure-host"/);
 delete registry.agents[input.id];
});


test('tutorial removes cross-mode, comparison and structure entry actions',()=>{
 const app=application();
 for(const html of [app.agentView(),app.withDraft(app.prepareView),app.tutorialMilestone('agents')]){
  assert.doesNotMatch(html,/실제 실행으로 이동|결과 비교|data-tab="live"|data-action="structure"/);
 }
 assert.match(app.withDraft(app.prepareView),/data-action="demo-generate"/);
 assert.match(app.agentView(),/data-action="demo-prepare"/);
});

test('each tutorial page has detailed reading steps without running work or navigating',()=>{
 const app=application();
 for(const stage of ['agents','prepare','live','execution']){
  app.navigate(stage);
  assert.ok(app.tutorialGuideSteps(stage).length>=3);
  assert.match(app.tutorialMilestone(stage),/이 화면에서 직접 해보기/);
  assert.match(app.tutorialMilestone(stage),/다음 설명/);
  app.setTutorialGuideStep(1);
  assert.equal(app.state.tutorialGuideIndex[stage],1);
  assert.equal(app.state.tab,stage);
  assert.equal(app.state.tutorialTour,true);
 }
 assert.equal(app.state.verified.purchase,undefined);assert.equal(app.state.run,null);
 app.setTutorialGuideStep(-1);assert.equal(app.state.tutorialGuideIndex.execution,1);
 app.navigate('agents');app.verifyAgent();assert.equal(app.state.verified.purchase.ok,true);
 assert.equal(app.state.tab,'agents');assert.equal(app.state.run,null);
});

test('demo target screen mirrors live types while keeping practice and sample runs on purchase',()=>{
 const app=application();
 for(const type of ['PURCHASE','PRODUCTION','QUALITY']){
  app.state.demoTargetType=type;
  const html=app.demoTargetsView();
  assert.match(html,new RegExp(`data-demo-target-type="${type}" aria-pressed="true"`));
  assert.match(html,/최근 실행/);assert.match(html,/저장된 데모 예시/);
  assert.equal(app.state.run,null);assert.equal(app.state.verified.purchase,undefined);
 }
 app.openDemoSample('S03','B1');
 assert.equal(app.state.run.agentId,'purchase');assert.equal(app.state.run.config,'B1');
 assert.equal(app.state.demoTargetType,'PURCHASE');assert.equal(app.state.tab,'execution');
 assert.ok(app.checksFor().every(c=>c.result==='PASS'));
});

test('changing tutorial pages brings the new heading and instructions into view',()=>{
 let focused=0,scrolled=0;
 const heading={focus:()=>focused++,scrollIntoView:options=>{assert.equal(options.block,'start');scrolled++;}};
 const app=application({querySelector:()=>heading});
 app.navigate('prepare');app.navigate('execution');
 assert.equal(focused,2);assert.equal(scrolled,2);assert.equal(heading.tabIndex,-1);
});

test('manual verification, page transitions and explanation buttons reopen the current tutorial',()=>{
 const app=application();app.state.tutorialTour=false;app.verifyAgent();
 assert.equal(app.state.tutorialTour,true);assert.equal(app.state.tutorialGuideIndex.agents,2);
 for(const page of ['prepare','live','execution','agents']){
  app.state.tutorialTour=false;app.state.tutorialGuideIndex[page]=2;app.navigate(page);
  assert.equal(app.state.tutorialTour,true);assert.equal(app.state.tutorialGuideIndex[page],0);
  app.state.tutorialTour=false;app.setTutorialGuideStep(1);assert.equal(app.state.tutorialTour,true);
 }
 assert.equal(app.state.run,null);
});

test('page instruction disclosure has an explicit accessible collapse control',()=>{
 const app=application();
 assert.match(app.tutorialMilestone('prepare'),/aria-expanded="false"/);
 assert.match(app.tutorialMilestone('prepare'),/class="tutorial-guide-content" hidden/);
 app.state.tutorialGuideExpanded.prepare=true;
 assert.match(app.tutorialMilestone('prepare'),/aria-expanded="true"/);
 assert.match(app.tutorialMilestone('prepare'),/간략히 보기/);
 assert.match(app.tutorialMilestone('execution'),/aria-expanded="false"/);
});


test('proposal feedback and execution decisions use fixtures without API calls',()=>{
 let finish;
 const app=application(undefined,{setTimeout:callback=>{finish=callback;return 1;},api:()=>{throw new Error('Tutorial must not call API');},fetch:()=>{throw new Error('Tutorial must not fetch');}});
 app.generateDemoProposals();assert.equal(app.state.demoDesignStatus,'loading');
 assert.match(app.withDraft(app.prepareView),/시험 제안을 준비하고/);
 finish();assert.equal(app.state.demoDesignStatus,'ready');assert.equal(app.state.demoSelected,false);
 app.chooseScenario('S03');app.state.draft.config='B1';app.loadDemo();
 assert.equal(app.state.tab,'live');assert.equal(app.state.config,'B1');assert.equal(app.state.demoStarted,false);
 assert.match(app.demoRunView('live'),/실행 준비/);
 assert.doesNotMatch(app.demoRunView('live'),/scene-host|scrubber|원문|JSON|data-demo-run-scenario|data-demo-run-config/);
 assert.doesNotMatch(app.demoRunView('live'),/live-analysis-shell/);
 assert.ok(app.demoRunView('execution').indexOf('live-analysis-shell')<app.demoRunView('execution').indexOf('demo-qa-report'));
 app.state.demoStarted=true;app.finishDemoApproval(true);
 assert.equal(app.state.demoApproval,'APPROVED');assert.equal(app.state.cursor,app.eventsFor().length-1);
 assert.ok(app.checksFor().every(c=>c.result==='PASS'));
 app.finishDemoApproval(false);assert.equal(app.state.scenario,'S02');
 assert.ok(app.eventsFor().some(e=>e.type==='APPROVAL_REJECTED'));
});

test('production and quality fixture events map to the same stage and produce domain checks',()=>{
 const app=application();
 for(const [type,scenario] of [['PRODUCTION','P03'],['QUALITY','Q03']]){
  app.state.demoTargetType=type;app.state.draft.scenario=scenario;app.loadDemo();
  assert.ok(topology.mapEvents(app.state.run.topology,app.eventsFor()).every(e=>e.ok));
  assert.ok(app.checksFor().some(c=>c.result==='FAIL'));
  assert.doesNotMatch(app.demoRunView('live'),/undefined|발주/);
 }
});


test('proposal tour previews results before generation and practice resets to the initial screen',()=>{
 let finish;
 const app=application(undefined,{setTimeout:callback=>{finish=callback;return 1;}});
 app.navigate('prepare');
 assert.match(app.withDraft(app.prepareView),/<div  class="design-board/);
 assert.doesNotMatch(app.withDraft(app.prepareView),/class="design-empty"/);
 app.practiceTutorial();
 assert.match(app.withDraft(app.prepareView),/<div hidden class="design-board/);
 for(const index of [0,1,2,3]){
  app.setTutorialGuideStep(index);
  const html=app.withDraft(app.prepareView);
  assert.match(html,/<div  class="design-board/);
  assert.ok(html.indexOf('data-action="load"')<html.indexOf('class="design-selection"'));
  assert.equal(app.state.demoDesignStatus,'idle');assert.equal(app.state.run,null);
 }
 app.generateDemoProposals();
 app.practiceTutorial();finish();
 assert.equal(app.state.demoDesignStatus,'idle');assert.equal(app.state.demoSelected,false);
 assert.equal(app.state.tutorialTour,false);assert.equal(app.state.tutorialGuideIndex.prepare,0);
 assert.match(app.withDraft(app.prepareView),/<div hidden class="design-board/);
 app.generateDemoProposals();finish();
 assert.equal(app.state.demoDesignStatus,'ready');
 assert.match(app.withDraft(app.prepareView),/<div  class="design-board/);
});
