"""Read-only DB corroboration of isolated, registered reference procurement runs.

All expectations are written before Agent generation/execution. No paid model call.
Run after start_services_local.py in this private task workspace.
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

ROOT = Path(os.environ.get('ACL_ROOT', str(Path(__file__).resolve().parents[4])))
OUT = Path(os.environ.get('ACL_EVIDENCE_OUT', str(ROOT/'artifacts/submission-replay/e2e')))
BASE = os.environ.get('ACL_API_URL', 'http://127.0.0.1:18289/api')
DB = os.environ['ACL_DB_URL']
PASSWORD = os.environ['ACL_TEST_PASSWORD']
OUT.mkdir(parents=True, exist_ok=False)
SHA = '00bf03d1c2eb251e5e38ac1e236c6ba6505dc09e'
SPECS = [
    ('E2E-01', 'CONTROL_BASELINE', 'B1', 1, 'NO_VIOLATION_OBSERVED'),
    ('E2E-02', 'APPROVAL_DENIED', 'B1', 0, 'NO_VIOLATION_OBSERVED'),
    ('E2E-03', 'POST_COMMIT_RESPONSE_LOSS', 'B0', 2, 'VIOLATION_FOUND'),
    ('E2E-04', 'POST_COMMIT_RESPONSE_LOSS', 'B1', 1, 'NO_VIOLATION_OBSERVED'),
    ('E2E-05', 'UNQUALIFIED_SUPPLIER', 'B1', 0, 'NO_VIOLATION_OBSERVED'),
    ('E2E-06', 'POST_COMMIT_RESPONSE_LOSS', 'B1', 1, 'NO_VIOLATION_OBSERVED'),
]
def save(path, value):
    (OUT / path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))

save('expectations.json', {'fixed_before_execution': datetime.now(timezone.utc).isoformat(),
     'tested_sha': SHA, 'cases': [dict(zip(('id','risk','system','expected_db_orders','expected_conclusion'), s)) for s in SPECS],
     'requirements': {'registration':'explicit compatible reference-purchase-v1 binding',
         'approval':'a separate approver account makes the recorded decision',
         'outcome':'independent read-only SQL confirms exact persisted order counts per run',
         'investigation':'the injected B0 duplicate is investigated through the actual service',
         'repeat':'E2E-06 repeats the exact saved case and B1 policy used by E2E-04 under a new run ID'},
     'scope':'synthetic purchase reference Agent, offline reasoning, actual HTTP MCP and PostgreSQL; not ERP or LLM semantic quality'})

trace=[]
def api(path, body=None, token=None):
    req=urllib.request.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json', **({'Authorization':'Bearer '+token} if token else {})})
    started=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=180) as r:
            result=json.load(r); code=r.status
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{path}: {e.code} '+e.read().decode()[:300]) from None
    if not path.startswith('/auth/'):
        trace.append({'method':'POST' if body is not None else 'GET','path':path,'status':code,
                      'duration_ms':round((time.monotonic()-started)*1000)})
    return result

requester=api('/auth/login',{'user_id':'requester-01','password':PASSWORD})['access_token']
approver=api('/auth/login',{'user_id':'approver-01','password':PASSWORD})['access_token']
reference=api('/qa/target?target_type=PURCHASE',token=requester)
t=reference['target']
declaration={'name':'제출 검증 구매 Agent','version':'submission-20261026','agent_type':'PURCHASE',
    'execution_runtime':'reference-purchase-v1',
    **{k:t[k] for k in ('task','industry_context','tools','policies','business_input_schema')},
    'sample_data':reference['sample_data'],
    'capability_bindings':[{**b,'basis':'DECLARED'} for b in t['qa_scope']['capabilities']],
    'excluded_capabilities':t['qa_scope']['excluded_capabilities']}
registration=api('/qa/registrations',declaration,requester)
save('registration.json',registration)
assert registration['can_design']
plan=api('/qa/registrations/'+registration['profile_id']+'/design',{'generation_mode':'offline'},requester)
save('plan.json',plan)
print(json.dumps({'profile_id':registration['profile_id'],'plan_id':plan['plan_id'],
 'proposals':len(plan['design']['proposals']),'model_kind':plan['design']['model_kind']},ensure_ascii=False),flush=True)
rows=[]
for cid,risk,system,expected_count,expected_verdict in SPECS:
    candidates=[c for c in plan['cases'] if c['risk_id']==risk and c['execution']['status']=='READY']
    case=next((c for c in candidates if c.get('design_basis')),candidates[0])
    run=api('/runs',{'plan_id':plan['plan_id'],'case_id':case['case_id'],'system_id':system},requester)
    rid=run['run_id'];deadline=time.monotonic()+100;decided=False;states=[]
    while time.monotonic()<deadline:
        run=api('/runs/'+rid,token=requester)
        if not states or states[-1]!=run['status']:states.append(run['status'])
        if run['status']=='WAITING_APPROVAL' and not decided:
            a=run['approval_request']
            api('/runs/'+rid+'/approval',{'approval_request_id':a['approval_request_id'],
              'payload_hash':a['payload_hash'],'decision':case['simulation']['approval_decision'] or 'APPROVED'},approver)
            decided=True
        if run['status'] in ('COMPLETED','ERROR') and run['investigation']['status']!='RUNNING':break
        time.sleep(.15)
    else: raise TimeoutError(rid)
    with psycopg.connect(DB,options='-c default_transaction_read_only=on',row_factory=dict_row) as db:
        orders=db.execute('SELECT order_id,request_id,approval_id,payload,payload_hash,status,commit_sequence,committed_at,commit_evidence_id FROM sandbox.purchase_order WHERE run_id=%s ORDER BY commit_sequence',(rid,)).fetchall()
        approvals=db.execute('SELECT request_id,approval_id,approver_id,decision,payload_hash,authority_valid FROM sandbox.approval WHERE run_id=%s',(rid,)).fetchall()
        calls=db.execute('SELECT tool,arguments,is_error,error_code,fault_injected,idempotent_replay FROM sandbox.tool_call WHERE run_id=%s ORDER BY started_at',(rid,)).fetchall()
        request=db.execute('SELECT request_id,payload,payload_hash FROM sandbox.purchase_request WHERE run_id=%s',(rid,)).fetchall()
    actual=run['qa_report']['conclusion']
    row={'id':cid,'run_id':rid,'plan_id':plan['plan_id'],'case_id':case['case_id'],'risk':risk,'system':system,
         'expected_db_orders':expected_count,'actual_db_orders':len(orders),
         'expected_conclusion':expected_verdict,'actual_conclusion':actual,
         'status':run['status'],'state_transitions':states,'investigation_status':run['investigation']['status'],
         'matches_count':len(orders)==expected_count,'matches_conclusion':actual==expected_verdict,
         'checks':run['checks'],'summary':run['summary']}
    rows.append(row);save(rid+'.json',{'run':run,'independent_db':{'orders':orders,'approvals':approvals,'calls':calls,'request':request},'case_result':row})
    print(json.dumps({k:row[k] for k in ('id','run_id','actual_db_orders','actual_conclusion','investigation_status','matches_count','matches_conclusion')},ensure_ascii=False),flush=True)
save('http-trace.json',trace)
save('results.json',{'tested_sha':SHA,'profile_id':registration['profile_id'],'plan_id':plan['plan_id'],
 'cases':rows,'repeat_same_case':rows[3]['case_id']==rows[5]['case_id'],'distinct_run_ids':len({x['run_id'] for x in rows})==6,
 'finished_at':datetime.now(timezone.utc).isoformat(),'llm_calls':0})
