import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {purchaseTopology} from '../dist/topologies.js';
import {escapeHtml} from '../dist/live-api.js';

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
function workspace(){
 const headerButton={},user={querySelector:()=>headerButton},routes=[];
 const document={body:{classList:{toggle(){}}},querySelector:()=>null,querySelectorAll:()=>[],getElementById:id=>id==='header-user'?user:null};
 const app=vm.runInNewContext(source+`;go=tab=>routes.push(tab);({state,syncShellChrome,leaveLive,isLiveAuthenticated,click})`,{
  purchaseTopology,document,routes,esc:escapeHtml,clearTimeout(){},clearInterval(){},pauseScene(){},leaveApprover(){}});
 Object.assign(app.state,{session:{user_id:'requester-01',roles:['REQUESTER']},registration:{name:'User target'},registrations:[{}],catalog:{},run:{run_id:'RUN-1'},runs:[{}],events:[{}],designPlan:{},designCaseId:'CASE-1',batch:{},batchRequest:{},pendingRunId:'RUN-1'});
 return {...app,headerButton,routes};
}

test('header logout works after leaving live for the tutorial and clears account data',()=>{
 const ui=workspace();ui.syncShellChrome();ui.leaveLive();ui.headerButton.onclick();
 assert.equal(ui.isLiveAuthenticated(),false);assert.deepEqual(ui.routes,['agents']);
 for(const key of ['registration','catalog','run','designPlan','designCaseId','batch','batchRequest','pendingRunId'])assert.equal(ui.state[key],null,key);
 for(const key of ['registrations','runs','events'])assert.equal(ui.state[key].length,0,key);
});

test('in-page logout uses the same cleanup and returns to the login route',()=>{
 const ui=workspace();const button={hasAttribute:name=>name==='data-live-logout'};
 ui.click({target:{closest:()=>button}});
 assert.equal(ui.isLiveAuthenticated(),false);assert.deepEqual(ui.routes,['agents']);
 assert.equal(ui.state.designPlan,null);assert.equal(ui.state.registrations.length,0);
});
