import os
"""Independent mutations at the actual planner binding boundary. Real retrieved baseline;
no LLM inference, no business execution, no product changes."""
import copy,json,time
from pathlib import Path
from harness.planning import QaPlanner
from harness.reporting import qa_report
from harness.evaluation import run_result
R=Path(os.environ.get('ACL_ROOT', str(Path(__file__).resolve().parents[4])));O=Path(os.environ.get('ACL_EVIDENCE_OUT', str(Path.cwd()/'artifacts/submission-replay/scenario-guards')));O.mkdir(parents=True,exist_ok=True)
base=json.loads(Path(os.environ.get('ACL_DESIGN_INPUT', str(Path.cwd()/'artifacts/submission-replay/current-offline-design.json'))).read_text())
p=json.loads((R/'qa/examples/targets/agents.json').read_text())['agents']['PURCHASE'];planner=QaPlanner(R)
specs=[('valid','READY'),('invented_source','BLOCKED'),('missing_agentic_stage','BLOCKED'),('wrong_stage_order','BLOCKED'),('wrong_score_total','BLOCKED'),('zero_critical_score','BLOCKED'),('unregistered_tool','BLOCKED'),('stale_policy_hash','BLOCKED'),('source_version_changed','BLOCKED'),('false_source_text','BLOCKED'),('fabricated_quote','BLOCKED'),('forged_text_and_quote','BLOCKED')]
(O/'expectations.json').write_text(json.dumps({'fixed_at':time.time(),'cases':specs,'basis':'A bound plan must retain two ordered reviews, exact score arithmetic, registered tools and current verified evidence. Changed citation bytes/version must not retain trusted readiness.'},indent=2))
rows=[]
for name,expected in specs:
 d=copy.deepcopy(base);s=d['reviews'][0]['stages'][0]
 if name=='invented_source':d['proposals'][0]['evidence_ids']=['FABRICATED']
 if name=='missing_agentic_stage':d['reviews'][0]['stages']=d['reviews'][0]['stages'][:1]
 if name=='wrong_stage_order':d['reviews'][0]['stages'].reverse()
 if name=='wrong_score_total':s['score_total']=99
 if name=='zero_critical_score':s['scores']['evidence_score']=0;s['score_total']=6
 if name=='unregistered_tool':d['proposals'][0]['tool_name']='self_approve'
 if name=='stale_policy_hash':d['test_policy_hash']='stale'
 if name in ('source_version_changed','false_source_text'):
  ids=set(d['proposals'][0]['evidence_ids']);hit=next(x for x in d['sources'] if x['document_id'] in ids and x['source_type']!='PROJECT_POLICY')
  hit['version' if name=='source_version_changed' else 'matched_text']='Unverified fabricated value'
 if name=='fabricated_quote':s['score_reasons']['evidence_quote']='Fabricated independent text not in the source'
 if name=='forged_text_and_quote':
  hit=next(x for x in d['sources'] if x['document_id']==s['evidence_ids'][0]);hit['matched_text']='Fabricated independent text';s['score_reasons']['evidence_quote']=hit['matched_text']
 row={'id':name,'expected':expected,'level':'PLANNER_OBJECT_MUTATION'}
 try:
  plan=planner.build_designed(p['target'],p['sample_data'],d)
  cases=[c for c in plan['cases'] if c.get('design_basis')];target=next(c for c in cases if c['design_basis']['proposal_id']==d['proposals'][0]['proposal_id'])
  row.update(actual='READY' if target['execution']['status']=='READY' else 'BLOCKED',execution=target['execution'])
 except Exception as e:row.update(actual='BLOCKED',error=str(e),error_type=type(e).__name__)
 row['matches']=row['actual']==expected;rows.append(row);print(name,row['actual'],row['matches'])
(O/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
