import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
const code=String.raw`
import json,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from grant_agent.goal_loop import GoalLoop
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);loop=GoalLoop(root,'chat');loop.activate('Fix and verify the parser')
 loop.update('progress',evidence='Reproduced invalid input',next_action='Repair tokenizer')
 restarted=GoalLoop(root,'chat')
 assert restarted.state is None and restarted.update('inspect')['checkpoint']['nextAction']=='Repair tokenizer'
 restarted.activate('Yes, continue with UTF-8')
 assert restarted.state['previousUnfinishedGoal']['goal']=='Fix and verify the parser'
 restarted.started-=24*3600
 for stamp in (1,2):
  restarted.observe([SimpleNamespace(type='tool_call_output_item',tool_name='read',output=json.dumps({'content':'unchanged','receiptId':str(stamp),'at':stamp}))])
 assert len(restarted.observations)==1
 assert restarted.after_round(requests=100,pending_question=False,final_output='First attempt') is not None
 assert restarted.after_round(requests=100,pending_question=False,final_output='Different hypothesis') is not None
 assert restarted.stop_reason==''
 restarted.update('blocked',blocker='Required test fixture is absent',evidence='Checked both supplied locations')
 assert restarted.after_round(requests=1,pending_question=False) is None
 assert restarted.stop_reason=='blocked'
 print(json.dumps({'passed':True,'durableCheckpoint':True,'existingGoalRetainedOnFollowup':True,'noAutomaticTimeOrTotalTurnCutoff':True,'receiptMetadataDoesNotCountAsProgress':True,'concreteBlockerRetained':True}))
`;
const proc=spawnSync('python',['-c',code],{cwd:process.cwd(),env:{...process.env,PYTHONPATH:path.join(process.cwd(),'src')},encoding:'utf8',timeout:10000});
assert.equal(proc.status,0,proc.stderr);console.log(proc.stdout.trim());
