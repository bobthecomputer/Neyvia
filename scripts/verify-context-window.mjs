import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const result = spawnSync(resolveNeyviaPython(process.cwd()).python, ['-c', `
import json
from types import SimpleNamespace
from pathlib import Path
from agents.run_config import ModelInputData
from grant_agent.context_window import bounded_history
from grant_agent.prompt_contract import PromptContract,PromptContractError
from grant_agent.neyvia_agent import _failure_for_agent_exception
items=[]
for i in range(12):
 items.extend([{'role':'user','content':str(i)*1000},{'type':'function_call','call_id':str(i),'name':'read','arguments':'{}'},{'type':'function_call_output','call_id':str(i),'output':'x'*5000},{'role':'assistant','content':'done'}])
original=json.dumps(items)
bounded,omitted=bounded_history(items,character_budget=20000,item_budget=20)
assert omitted>0 and len(json.dumps(bounded))<21000
assert json.dumps(items)==original and bounded[-1]==items[-1]
calls={x['call_id'] for x in bounded if x.get('type')=='function_call'}
outputs={x['call_id'] for x in bounded if x.get('type')=='function_call_output'}
assert calls==outputs
short=[{'role':'user','content':'hi'}];assert bounded_history(short)==(short,0)
agent=SimpleNamespace(instructions='Exact user system prompt')
contract=PromptContract();contract.register(agent)
big=[{'role':'user','content':'old'*100000},*items]
data=SimpleNamespace(agent=agent,model_data=ModelInputData(input=big,instructions=agent.instructions))
filtered=contract(data)
assert filtered.instructions==agent.instructions and len(json.dumps(filtered.input))<len(json.dumps(big))
assert contract.receipt()['omittedHistoryRecords']>0
try:
 contract(SimpleNamespace(agent=agent,model_data=ModelInputData(input=[{'role':'system','content':'competing'}],instructions=agent.instructions)))
 raise AssertionError('competing instructions accepted')
except PromptContractError:pass
class BadRequestError(Exception):body={'message':'The prompt is too long: 1052286, model maximum context length: 1048571'}
failure=_failure_for_agent_exception(BadRequestError(),max_turns=12,session_id='fixture',session_database=Path('fixture.db'))
assert failure['code']=='context_window_exceeded' and 'plan usage' in failure['message']
print(json.dumps({'passed':True,'checks':['full stored history unchanged','complete tool pairs','exact system prompt','bounded replay','short history unchanged','context error classification']}))
`], {env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:30000});
assert.equal(result.status,0,result.stderr);
console.log(result.stdout.trim());

