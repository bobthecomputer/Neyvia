import json,uuid
from pathlib import Path
from grant_agent.proof_credential_guard import install,prepare_broker_fixture
root=Path('.agent_control/proofs/FIX-video-'+uuid.uuid4().hex).resolve();root.mkdir(parents=True)
install(root);prepare_broker_fixture(root)
from grant_agent.proofs_e_sv import _check_video
rows=[]
def run(name,contracts,action):
    try: rows.append({'name':name,'contracts':contracts,'passed':True,'observed':action()})
    except Exception as exc: rows.append({'name':name,'passed':False,'error':str(exc)})
_check_video(root,run)
from grant_agent.action_executor import HybridExecutionAdapter
from grant_agent.models import PlannedStep
adapter=HybridExecutionAdapter();policy=adapter.build_policy('builder');scope=adapter.prepare_scope(root,'FIX-video',requested_scope='direct')
source=str(root/'verify'/'hermes-test.mp4')
for title,description,expected in [('Analyze video','Create model-readable video evidence for '+source,'native_tool'),('Verify output','Verify generated media '+source,'test_run')]:
    result=adapter.build_action_proposal(PlannedStep(step_id='intent',title=title,description=description),'Review video storyboard and scene changes',root,['node --version'],'hermes',scope,policy)
    rows.append({'name':title,'passed':result.kind==expected,'observed':{'kind':result.kind,'args':result.args}})
receipt={'schema':'neyvia.FIX.video.v1','passed':all(row['passed'] for row in rows),'checks':rows,'boundary':'Actual FFmpeg media inspection/digest and real planner calls; no video model inference.'}
Path('scripts/evidence/FIX-video.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
print(json.dumps(receipt));raise SystemExit(not receipt['passed'])
