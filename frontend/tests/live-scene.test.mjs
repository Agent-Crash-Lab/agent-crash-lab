import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {purchaseTopology} from '../dist/topologies.js';
import {frameFor} from '../dist/topology.js';
import {sceneEvents, escapeHtml} from '../dist/live-api.js';

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
function workspace(page) {
  const elements=new Map();let mounted=0,paused=0;
  const host={querySelector(selector){
    if(!elements.has(selector))elements.set(selector,{textContent:'',innerHTML:'',scrollTop:0});
    return elements.get(selector);
  }};
  const context={purchaseTopology,frameFor,sceneEvents,esc:escapeHtml,
    mountScene(){mounted++;},pauseScene(){paused++;}};
  const app=vm.runInNewContext(source+`;host=testHost;page=testPage;({state,renderEvents})`,{...context,testHost:host,testPage:page});
  return {...app,element:s=>host.querySelector(s),mounted:()=>mounted,paused:()=>paused};
}

test('live opens an idle 3D structure without claiming a run or enabling replay/export',()=>{
  const ui=workspace('live');ui.renderEvents();
  assert.equal(ui.mounted(),1);assert.equal(ui.state.run,null);
  assert.match(ui.element('[data-live-count]').textContent,/실행 전/);
  assert.equal(ui.element('[data-live-play]').disabled,true);
  assert.equal(ui.element('[data-live-export]').disabled,true);
  assert.match(ui.element('[data-live-events]').innerHTML,/시험을 시작하면/);
});

test('live and analysis render actual events while other pages pause the scene',()=>{
  for(const page of ['live','execution','prepare']){
    const ui=workspace(page);
    ui.state.run={run_id:'RUN-1'};
    ui.state.events=[{run_id:'RUN-1',event_id:'EV-1',sequence:1,event_type:'TOOL_CALLED',node_id:'mcp'}];
    ui.renderEvents();
    assert.equal(ui.mounted(),page==='prepare'?0:1);
    assert.equal(ui.paused(),page==='prepare'?1:0);
    assert.equal(ui.element('[data-live-play]').disabled,false);
    assert.equal(ui.element('[data-live-export]').disabled,false);
    assert.match(ui.element('[data-live-events]').innerHTML,/TOOL_CALLED/);
  }
});
