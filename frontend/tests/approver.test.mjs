import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {decisionAvailable,reportVerdict,approverListMarkup} from '../dist/approver.js';
import {workspaceRoute} from '../dist/live-api.js';
import {purchaseTopology} from '../dist/topologies.js';

const pending={run_id:'RUN-1',test_id:'Q01',created_by:'admin',status:'WAITING_APPROVAL',approval_request:{expires_at:'2030-01-01T00:00:00Z'},request:{lot_id:'<script>',quantity:2}};
test('approval requires pending state, another requester and an unexpired request',()=>{
 const now=Date.parse('2026-01-01');
 assert.equal(decisionAvailable(pending,'approver',now),true);
 assert.equal(decisionAvailable(pending,'admin',now),false);
 assert.equal(decisionAvailable({...pending,status:'COMPLETED'},'approver',now),false);
 assert.equal(decisionAvailable(pending,'approver',Date.parse('2031-01-01')),false);
 assert.equal(decisionAvailable({...pending,approval_request:{expires_at:'invalid'}},'approver',now),false);
});
test('approver routes cannot enter workflow or tutorial and requester cannot enter approver views',()=>{
 const source=readFileSync(new URL('../dist/live.js',import.meta.url),'utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'');
 const ui=vm.runInNewContext(source+';({state,accountPage})',{purchaseTopology});
 ui.state.session={roles:['APPROVER']};
 for(const route of ['agents','prepare','live','execution','demo','demo-3d'])assert.equal(ui.accountPage(route),'approvals');
 for(const page of ['approvals','requests','reports']){assert.equal(ui.accountPage(page),page);assert.equal(workspaceRoute(`#${page}`).page,page);}
 ui.state.session={roles:['REQUESTER']};assert.equal(ui.accountPage('reports'),'agents');assert.equal(ui.accountPage('prepare'),'prepare');
});
test('approval and admin request views escape content and only approval view has decision controls',()=>{
 const approvals=approverListMarkup([pending],'approvals','approver');
 assert.match(approvals,/data-decision="APPROVED"/);assert.match(approvals,/&lt;script&gt;/);assert.doesNotMatch(approvals,/<script>/);
 const requests=approverListMarkup([pending],'requests','approver');
 assert.match(requests,/요청자 admin/);assert.doesNotMatch(requests,/data-decision=/);
 assert.match(approverListMarkup([pending],'requests','approver','missing'),/보낸 승인 요청이 없습니다/);
});
test('readable reports distinguish failure and missing evidence from pass counts',()=>{
 const run={...pending,status:'COMPLETED',summary:{PASS:4},qa_report:{conclusion:'INSUFFICIENT_EVIDENCE',summary:'근거 부족',test:{title:'출하 시험'},narrative:{agent_type_name:'품질 Agent',expected_behavior:'불합격 보류',agent_action:'출하 시도',business_result:'실제 출하 0건',meaning:'추가 확인 필요'},findings:[],limitations:['이번 시험 한정']}};
 assert.equal(reportVerdict(run),'확인 필요');
 assert.equal(reportVerdict({...run,summary:{FAIL:1}}),'기준 미충족');
 assert.equal(reportVerdict({summary:{PASS:1},qa_report:{conclusion:'NO_VIOLATION_OBSERVED'}}),'기준 충족');
 const html=approverListMarkup([pending,run],'reports','approver');
 for(const text of ['시험 상황','기대 행동','실제 업무 결과','실제 출하 0건','이번 시험 한정','상세 보고서 저장'])assert.ok(html.includes(text));
 assert.doesNotMatch(html,/data-decision=/);
});
