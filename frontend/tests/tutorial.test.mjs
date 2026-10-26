import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {workspaceRoute} from '../dist/live-api.js';

const source=readFileSync(new URL('../dist/app.js',import.meta.url),'utf8');
const guides=source.slice(source.indexOf('function tutorialGuideSteps('),source.indexOf('function tutorialGuide(stage)'));
function steps(state,stage){return vm.runInNewContext(guides+';tutorialGuideSteps(stage)',{state,stage});}

test('run guidance follows start, approval and completion states',()=>{
 const before=steps({demoStarted:false,demoApproval:null},'live');
 assert.equal(before[1].selector,'[data-action="demo-start"]');
 assert.equal(before[2].selector,'[data-action="demo-start"]');
 const waiting=steps({demoStarted:true,demoApproval:null},'live');
 assert.equal(waiting[1].selector,'.demo-run-progress');
 assert.equal(waiting[2].selector,'.approval-form');
 for(const demoApproval of ['APPROVED','REJECTED']){
  assert.equal(steps({demoStarted:true,demoApproval},'live')[2].selector,'[data-demo-tab="execution"].primary');
 }
});

test('registered structure has its own guidance',()=>{
 const guide=steps({},'structure');
 assert.ok(guide.every(step=>step.selector.startsWith('.structure-inspection')));
 assert.ok(guide.every(step=>!step.desc.includes('LLM')));
});

test('missing or hidden targets do not produce an unrelated coachmark',()=>{
 const logic=source.slice(source.indexOf('function renderCoachmark(){'),source.indexOf('function render() {'));
 for(const target of [null,{getClientRects:()=>[]}]){
  let removed=0;
  vm.runInNewContext(logic+';renderCoachmark()',{
   document:{querySelector:()=>target},removeCoachmark(){removed++;},
   workspacePage:'demo',state:{tutorialTour:true,tab:'agents',tutorialGuideIndex:{}},
   tutorialGuideSteps:()=>[{selector:'.missing'}]
  });
  assert.equal(removed,1);
 }
});


test('tutorial run list bookmarks remain inside the tutorial',()=>{
 assert.deepEqual(workspaceRoute('#demo-runs'),{page:'demo',demoTab:'runs',show3d:false});
});
