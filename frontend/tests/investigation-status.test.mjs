import test from 'node:test';
import assert from 'node:assert/strict';
import {investigationLabel, isFinished} from '../dist/live-api.js';

test('investigation distinguishes a passing run, ongoing work and connection failure',()=>{
  const run={status:'COMPLETED',summary:{PASS:8,FAIL:0,INCONCLUSIVE:0},investigation:{status:'NOT_REQUESTED'}};
  assert.match(investigationLabel(run),/생략.*실패·판정 보류 없음/);
  run.investigation={status:'RUNNING'};
  assert.equal(isFinished(run),false);
  assert.match(investigationLabel(run),/진행 중/);
  run.investigation={status:'ERROR',status_reason:'LLM_BUDGET_EXHAUSTED'};
  assert.equal(isFinished(run),true);
  assert.match(investigationLabel(run),/예산 소진.*판정은 보존/);
  run.investigation={status:'READY',method:'CODE_EVIDENCE_SUMMARY',agent_status:'ERROR'};
  assert.match(investigationLabel(run),/연결 실패.*근거 요약/);
  run.investigation={status:'READY',validation:{passed:false}};
  assert.match(investigationLabel(run),/근거 확인 필요/);
  run.investigation={status:'READY',validation:{passed:true}};
  assert.match(investigationLabel(run),/추가 조사 완료/);
});
