import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = mkdtempSync(path.join(tmpdir(), 'neyvia-prompt-dispatch-'));
const code = String.raw`
import io, json, os, sys
from pathlib import Path
from unittest.mock import patch
root=Path(sys.argv[1])
os.environ['NEYVIA_AGENT_PROMPT_FILE']=str(root/'prompts.json')
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_SECONDS']='15'
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_MAX_SECONDS']='30'
from grant_agent.agent_prompt_library import save_prompt_library, load_prompt_library
from grant_agent.web_backend import FluxioWebBackend, _chat_prompt, _agent_chat_runtime_timeout_seconds
from grant_agent import opencode_bridge
route={'runtime':'opencode','provider':'openrouter','model':'example/model'}
text='A scoped system prompt.\nPreserve accents: é 東京.'
library=load_prompt_library(root,**route)
scope=next(s['id'] for s in library['scopeOptions'] if s['kind']=='route')
save_prompt_library(root,{'expectedRevision':0,'scopeId':scope,**route,'role':'chat','instructions':text})
payload={**route,'message':'hello fixture','workspacePath':str(root)}
assert _chat_prompt(payload)==text+'\n\nhello fixture'
assert _chat_prompt({**payload,'_roleInstructionsInSystem':True})=='hello fixture'
assert text not in _chat_prompt({**payload,'runtime':'neyvia-agent'})
assert {_agent_chat_runtime_timeout_seconds({'effort':effort}) for effort in ['low','medium','high','ultra']}=={None}
assert _agent_chat_runtime_timeout_seconds({}) is None
assert _agent_chat_runtime_timeout_seconds({'runtimeTimeoutSeconds':200})==200
assert _agent_chat_runtime_timeout_seconds({'runtime_timeout_seconds':9999999})==9999999
assert _agent_chat_runtime_timeout_seconds({'runtimeTimeoutSeconds':0}) is None
backend=FluxioWebBackend.__new__(FluxioWebBackend)
for provider, model in [('deepseek','deepseek-chat'),('openai','gpt-example'),('deepinfra','deepseek-ai/DeepSeek-V3.2')]:
    exact=backend._chat_route({'runtime':'opencode','provider':provider,'model':model})
    assert exact['provider']==provider and exact['model']==model
    assert exact['model_id']==provider+'/'+model
promptfile=root/'prompt.md';promptfile.write_text(text,encoding='utf8')
capture={}
class Process:
    def __init__(self,args,**kwargs):
        capture['config']=json.loads(kwargs['env']['OPENCODE_CONFIG_CONTENT']);capture['args']=args
        self.stdout=io.StringIO(json.dumps({'type':'text','part':{'type':'text','text':'done'}})+'\n')
        self.stderr=io.StringIO('');self.returncode=0;self.pid=12345
    def wait(self,*a,**kw): return 0
    def poll(self): return 0
    def __enter__(self): return self
    def __exit__(self,*a): return False
with patch.object(opencode_bridge.subprocess,'Popen',Process), patch.object(opencode_bridge,'_popen_args',lambda args:args), patch('sys.stdout',new=io.StringIO()):
    result=opencode_bridge.run_opencode(opencode_command='fixture',prompt='hello fixture',model='openrouter/example/model',max_steps=8,instructions_file=str(promptfile))
agent=capture['config']['agent']['neyvia-harness']
assert agent['prompt']=='{file:'+promptfile.as_posix()+'}'
assert agent['steps']==8
assert 'openrouter/example/model' in capture['args']
assert text not in json.dumps(capture['config'])
assert result==0
print(json.dumps({'ok':True,'checks':['scoped_dispatch','system_channel_not_user_prefix','runtime_isolation','no_implicit_wall_clock_deadline_even_with_legacy_env','explicit_opt_in_timeout_without_implicit_cap','OpenCode_agent_prompt_file','exact_OpenCode_route','no_legacy_provider_aliases','nested_model_IDs','bounded_steps']}))
`;
try {
  const result = spawnSync(resolveNeyviaPython(repo).python, ['-c', code, fixture], {
    cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, 'src') }, encoding: 'utf8', timeout: 45000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  console.log(result.stdout.trim());
} finally { rmSync(fixture, { recursive: true, force: true }); }
