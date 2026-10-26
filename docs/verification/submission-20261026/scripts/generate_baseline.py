import os
import asyncio,json,sys
from pathlib import Path
from agents.config import Settings
from agents.scenario.design import design_qa, DesignRequest
ROOT=Path(os.environ.get('ACL_ROOT', str(Path(__file__).resolve().parents[4])))
OUT=Path(os.environ.get('ACL_BASELINE_OUT', str(Path.cwd()/'artifacts/submission-replay')))
sys.path.insert(0,str(ROOT/'agents/tests'))
from test_design import found
async def main():
 p=json.loads((ROOT/'qa/examples/targets/agents.json').read_text())['agents']['PURCHASE']
 settings=Settings(_env_file=None,agent_project_root=ROOT,agent_state_dir=OUT/'state',internal_api_token='independent-probe',agent_model_mode='offline',qa_design_model_mode='offline',llm_api_key='')
 d=await design_qa(settings,DesignRequest(target=p['target'],sample_data=p['sample_data']),search=found)
 (OUT/'current-offline-design.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
 print({'model_kind':d['model_kind'],'proposals':len(d['proposals']),'review_decisions':[x['decision'] for x in d['reviews']]})
asyncio.run(main())
