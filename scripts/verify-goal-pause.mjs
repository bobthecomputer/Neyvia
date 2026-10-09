import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';

const code = String.raw`
import json,tempfile
from pathlib import Path
from grant_agent.goal_loop import GoalLoop, GOAL_TOOL_DESCRIPTION
from grant_agent.native_goals import NativeGoalStore

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    loop=GoalLoop(root,'chat')
    loop.activate('Finish the authorized repair and verify it')
    loop.update('progress',evidence='Inspected the current failure',next_action='Apply the repair')
    paused=loop.update('pause')
    assert paused['checkpoint']['status']=='paused'
    assert loop.after_round(requests=1,pending_question=False) is None
    assert loop.stop_reason=='paused'
    resumed=GoalLoop(root,'chat')
    checkpoint=resumed.update('inspect')['checkpoint']
    assert checkpoint['status']=='paused'
    assert checkpoint['nextAction']=='Apply the repair'
    resumed.activate('Continue the paused repair')
    assert resumed.state['previousUnfinishedGoal']['goal']=='Finish the authorized repair and verify it'
    assert resumed.state['previousUnfinishedGoal']['nextAction']=='Apply the repair'
    assert 'explicitly asks' in GOAL_TOOL_DESCRIPTION

    store=NativeGoalStore(root)
    scheduled=store.create('Scheduled goal',schedule_seconds=60)
    store.heartbeat(scheduled['goalId'],status='paused',next_action='Wait for user')
    assert store.get(scheduled['goalId'])['status']=='paused'
    assert all(item['goalId']!=scheduled['goalId'] for item in store.due())
    print(json.dumps({'passed':True,'pausePersists':True,'runStops':True,'resumptionContextPreserved':True,'scheduledPauseNotDue':True}))
`;

const proc = spawnSync('python', ['-c', code], {
  cwd: process.cwd(),
  env: {...process.env, PYTHONPATH: path.join(process.cwd(), 'src')},
  encoding: 'utf8',
  timeout: 10000,
});
assert.equal(proc.status, 0, proc.stderr);
console.log(proc.stdout.trim());
