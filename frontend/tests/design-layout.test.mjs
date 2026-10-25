import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {purchaseTopology} from '../dist/topologies.js';
import * as api from '../dist/live-api.js';
const esc=api.escapeHtml;

const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
function workspace(){
 const area={innerHTML:'',querySelector:()=>({open:true})};
 const host={querySelector:()=>area};
 return {...vm.runInNewContext(source+';host=testHost;({state,renderDesign})',{...api,testHost:host,purchaseTopology,esc,repairMarkup:()=>'',reviewMarkup:()=>'',scenarioMarkup:()=>''}),area};
}
function scenario(id,status){return {
 case_id:id,hypothesis:`<${id}>`,execution:{status,rule_ids:[],missing_capabilities:[]},
 design_basis:{expected_behavior_candidate:'검증할 기대 행동',changes:[],sources:[]}
};}

test('design selection summary escapes labels and preserves readiness and evidence',()=>{
 const ui=workspace();
 ui.state.designPlan={design:{analysis:{target_type:'PURCHASE'},trace:[]},cases:[scenario('ready','READY'),scenario('blocked','ADAPTER_REQUIRED')]};
 ui.state.designCaseId='ready';ui.renderDesign();
 assert.ok(ui.area.innerHTML.indexOf('data-live-design-next')<ui.area.innerHTML.indexOf('class="design-selection"'));
 assert.match(ui.area.innerHTML,/선택한 시나리오<\/span><strong>&lt;ready&gt;/);
 assert.match(ui.area.innerHTML,/data-live-use-design="ready" aria-pressed="true" >/);
 assert.match(ui.area.innerHTML,/data-live-use-design="blocked" aria-pressed="false" disabled/);
 assert.match(ui.area.innerHTML,/실행 기능 연결 필요/);
 assert.match(ui.area.innerHTML,/<\/button><div class="case-blocker">/);
 assert.match(ui.area.innerHTML,/실행 보류 사유:/);
 assert.match(ui.area.innerHTML,/시험 근거와 상세 조건/);
 assert.match(ui.area.innerHTML,/data-policy-details open/);
 assert.doesNotMatch(ui.area.innerHTML,/<ready>/);
});

test('empty design gives a next action without creating or selecting a scenario',()=>{
 const ui=workspace();ui.renderDesign();
 assert.match(ui.area.innerHTML,/새로운 시험을 제안받아 보세요/);
 assert.equal(ui.state.designCaseId,null);assert.equal(ui.state.designPlan,null);
});
