import os
"""Independent output-validator probes. Scripted model and synthetic tools, not LLM quality."""
import asyncio,copy,json,time
from pathlib import Path
from types import SimpleNamespace
from agents.qa.investigation import build_investigation_graph
R=Path(os.environ.get('ACL_ROOT', str(Path(__file__).resolve().parents[4])));O=Path(os.environ.get('ACL_EVIDENCE_OUT', str(Path.cwd()/'artifacts/submission-replay/investigation-guards')));O.mkdir(parents=True,exist_ok=True)
specs=[('valid','ACCEPT'),('unknown_evidence','REJECT'),('wrong_target','REJECT'),('unretrieved_source','REJECT'),('wrong_source_version','REJECT'),('hidden_missing','REJECT'),('foreign_snapshot','REJECT'),('false_count_valid_id','REJECT'),('false_approval_valid_id','REJECT'),('empty_evidence','REJECT')]
(O/'expectations.json').write_text(json.dumps({'fixed_at':time.time(),'reason':'Evidence existence is necessary but a fact contradicted by its cited snapshot must not be accepted as a verified report. No requirement to diagnose an unavailable root cause.','cases':specs},indent=2))
async def check(name,expected):
 target='INV-GUARD';snapshot={'run_id':target,'orders':[],'approvals':[{'decision':'REJECTED'}],'snapshot_complete':name!='hidden_missing','snapshot_evidence_ids':['SNAP-GUARD']}
 if name=='foreign_snapshot':snapshot['orders']=[{'run_id':'OTHER'}]
 async def call(tool,args):
  if tool=='get_failed_checks':return {'run_id':target,'checks':[{'rule_id':'R05','verdict':'FAIL','reason':'승인 거절 후 시도, 서버 차단','evidence_ids':['BLOCKED-GUARD']}]}
  if tool=='get_business_state':return snapshot
  if tool=='get_run_trace':return {'events':[{'event_type':'TOOL_RESPONDED','evidence_ids':['BLOCKED-GUARD'],'payload':{'server_blocked':True}}]}
  if tool=='search_failure_guides':return {'results':[{'document_id':'guide','version':'1','location':'p1','resource_uri':'guide://guide/1'}]}
 async def resource(uri):return '사실은 원본 관측과 일치해야 한다.'
 class Model:
  async def generate(self,prompt,context):
   result={'target_run_id':target,'facts':[{'text':'발주 0건이며 승인은 거절되었습니다.','evidence_ids':['SNAP-GUARD']}],'cause_candidates':[],'missing_evidence':[],'improvements':[{'text':'승인 거절 시 생성하지 않도록 확인합니다.','sources':[{'document_id':'guide','version':'1','location':'p1'}]}],'retest_scenario_ids':['S02']}
   if name=='unknown_evidence':result['facts'][0]['evidence_ids']=['FAKE']
   if name=='wrong_target':result['target_run_id']='OTHER'
   if name=='unretrieved_source':result['improvements'][0]['sources'][0]['document_id']='UNSEEN'
   if name=='wrong_source_version':result['improvements'][0]['sources'][0]['version']='2'
   if name=='false_count_valid_id':result['facts'][0]['text']='실제 발주는 999건 저장되었습니다.'
   if name=='false_approval_valid_id':result['facts'][0]['text']='담당자가 승인했으며 승인에 문제가 없습니다.'
   if name=='empty_evidence':result['facts'][0]['evidence_ids']=[]
   return result
 ctx=SimpleNamespace(run_id=name,secrets=[],store=SimpleNamespace(get=lambda _:{}),step=lambda _:None,event=lambda *args:None,call=call,resource=resource)
 row={'id':name,'expected':expected,'level':'SCRIPTED_MODEL_VALIDATOR','input':snapshot}
 try:row.update(actual='ACCEPT',output=(await build_investigation_graph(ctx,None,Model()).ainvoke({'target_run_id':target}))['result'])
 except Exception as e:row.update(actual='REJECT',error_type=type(e).__name__,error=str(e))
 row['matches']=row['actual']==expected;return row
async def main():
 rows=[]
 for name,exp in specs:
  row=await check(name,exp);rows.append(row);print(name,row['actual'],row['matches'])
 (O/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
asyncio.run(main())
