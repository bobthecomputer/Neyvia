import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = process.cwd();
const { python } = resolveNeyviaPython(repo);
const source = String.raw`
import json
import asyncio
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / 'src'))
from agents import OpenAIProvider
from agents.exceptions import ModelBehaviorError
from agents.models.chatcmpl_stream_handler import ChatCmplStreamHandler, _BufferedToolCall
from agents.tool_context import ToolContext
from openai import AsyncOpenAI
from grant_agent.neyvia_agent import NeyviaAgentConfig, _failure_for_agent_exception, build_neyvia_agent

try:
    ChatCmplStreamHandler._buffered_tool_call_delta(_BufferedToolCall(index=0))
except ModelBehaviorError as exc:
    result = _failure_for_agent_exception(
        exc, max_turns=4, session_id='safe-fixture',
        session_database=Path('private-session-location-do-not-serialize'),
    )
    print(json.dumps({key: result.get(key) for key in ('code', 'exceptionType', 'diagnostic', 'origin')}))
else:
    raise AssertionError('Expected the SDK to reject a buffered tool call without an id')

async def verify_legacy_goal_call_when_goal_mode_is_off():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / '.agent_control').mkdir()
        config = NeyviaAgentConfig(
            root=root, session_id='compatibility-probe', model='deepseek-v4.1-flash',
            provider_id='opencode-go', base_url='http://127.0.0.1',
            transport='chat-completions', enable_specialists=False,
            situation_interface=False, goal_mode=False,
        )
        provider = OpenAIProvider(
            openai_client=AsyncOpenAI(api_key='disposable', base_url='http://127.0.0.1/v1'),
            use_responses=False,
        )
        agent, run_config, gateway = build_neyvia_agent(config, provider=provider)
        tool = next((item for item in agent.tools if item.name == 'neyvia_goal'), None)
        assert tool is not None, 'ordinary chat must retain the historical Goal tool schema'
        legacy_call = ToolContext(
            context=None, tool_name=tool.name, tool_arguments='{}',
            tool_call_id='legacy-goal-call', agent=agent, run_config=run_config,
        )
        result = await tool.on_invoke_tool(legacy_call, json.dumps({
            'action': 'complete', 'goal': 'fixture only', 'acceptance': 'must not mutate',
        }))
        payload = json.loads(result)
        assert payload.get('status') == 'goal_mode_disabled'
        assert gateway.goal_loop.state is None
        assert not gateway.goal_loop.path.exists()

asyncio.run(verify_legacy_goal_call_when_goal_mode_is_off())
`;
const run = spawnSync(python, ['-c', source], { cwd: repo, encoding: 'utf8', timeout: 15000 });
assert.equal(run.status, 0, run.stderr || 'diagnostic probe failed');
const result = JSON.parse(run.stdout.trim());
assert.equal(result.code, 'missing_tool_call_id');
assert.equal(result.exceptionType, 'ModelBehaviorError');
assert.equal(result.diagnostic, 'missing_tool_call_id');
assert.ok(Array.isArray(result.origin.frames) && result.origin.frames.length > 0);
assert.ok(result.origin.frames.some(frame => frame.file === 'chatcmpl_stream_handler.py' && frame.function === '_buffered_tool_call_delta'));
assert.ok(result.origin.frames.every(frame => Object.keys(frame).sort().join(',') === 'file,function,line'));
assert.equal(JSON.stringify(result).includes('private-session-location-do-not-serialize'), false);
console.log(JSON.stringify({ status: 'passed', diagnostic: result.diagnostic,
  origin: result.origin.frames.find(frame => frame.file === 'chatcmpl_stream_handler.py'),
  legacyGoalCallWhenOff: 'returned goal_mode_disabled without checkpoint mutation' }));
