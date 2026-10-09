import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';

const root = mkdtempSync(join(tmpdir(), 'neyvia-desktop-fastpaths-'));
const agentControl = join(root, '.agent_control');
mkdirSync(agentControl, { recursive: true });
writeFileSync(join(agentControl, 'conversation_state.json'), JSON.stringify({
  schema: 'fluxio.conversation_state.v1',
  activeChatSessionId: 'session-1',
  chatSessions: [{ id: 'session-1', title: 'Existing thread', createdAt: '2026-09-25T00:00:00Z', updatedAt: '2026-09-25T00:00:00Z' }],
  chatSessionTranscripts: { 'session-1': [{ id: 'turn-1', role: 'assistant', title: 'Existing answer', createdAt: '2026-09-25T00:00:01Z' }] },
}), 'utf8');

const python = process.env.PYTHON || 'python';
const cliProbe = (command, payload) => {
  const started = performance.now();
  const result = spawnSync(python, ['-m', 'grant_agent.desktop_bridge', '--root', root], {
    input: JSON.stringify({ command, payload }),
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: ['src', process.env.PYTHONPATH].filter(Boolean).join(';') },
    timeout: 30000,
  });
  assert.equal(result.status, 0, `${command} CLI failed\n${result.stdout}\n${result.stderr}`);
  const envelope = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(envelope.ok, true, `${command} returned ${envelope.error}`);
  return { command, elapsedMs: Math.round(performance.now() - started), data: envelope.data };
};
const program = String.raw`import json, pathlib, sys
from grant_agent.desktop_bridge import dispatch_desktop_command
root = pathlib.Path(sys.argv[1])
out = {}
out['bootstrap'] = dispatch_desktop_command(root, 'get_conversation_state_command', {
    'summaryMode':'bootstrap', 'activeChatSessionId':'session-1', 'turnLimit':1
})
out['session'] = dispatch_desktop_command(root, 'get_conversation_session_state_command', {
    'sessionId':'session-1', 'turnLimit':1
})
out['saved'] = dispatch_desktop_command(root, 'save_conversation_state_command', {
    'mergeExistingTranscripts':True,
    'activeChatSessionId':'session-2',
    'chatSessions':[{'id':'session-2','title':'Remote thread','createdAt':'2026-09-25T00:01:00Z','updatedAt':'2026-09-25T00:01:00Z'}],
    'chatSessionTranscripts':{'session-2':[{'id':'turn-2','role':'user','title':'New question','createdAt':'2026-09-25T00:01:01Z'}]}
})
out['afterSave'] = dispatch_desktop_command(root, 'get_conversation_state_command', {'summaryMode':'bootstrap','activeChatSessionId':'session-2'})
out['prompt'] = dispatch_desktop_command(root, 'get_agent_prompt_library_command', {})
out['promptReset'] = dispatch_desktop_command(root, 'reset_agent_prompt_library_command', {
    'role':'common', 'expectedRevision':out['prompt']['revision']
})
out['promptAfter'] = dispatch_desktop_command(root, 'get_agent_prompt_library_command', {})
print(json.dumps(out, ensure_ascii=True, separators=(',',':')))
`;

try {
  const result = spawnSync(python, ['-c', program, root], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: ['src', process.env.PYTHONPATH].filter(Boolean).join(';') },
    timeout: 30000,
  });
  assert.equal(result.status, 0, `Desktop state fastpath probe failed (${result.status})\n${result.stdout}\n${result.stderr}`);
  const probe = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(probe.bootstrap.summaryMode, 'bootstrap');
  assert.equal(probe.bootstrap.chatSessionTranscripts['session-1'][0].title, 'Existing answer');
  assert.equal(probe.session.sessionId, 'session-1');
  assert.equal(probe.session.turns[0].id, 'turn-1');
  assert.equal(probe.saved.chatSessions.some(row => row.id === 'session-1'), true);
  assert.equal(probe.saved.chatSessions.some(row => row.id === 'session-2'), true);
  assert.equal(probe.afterSave.chatSessionTranscripts['session-2'][0].title, 'New question');
  assert.equal(probe.prompt.schema, 'neyvia.agent_prompt_library.v1');
  assert.equal(probe.promptReset.revision, probe.prompt.revision + 1);
  assert.equal(probe.promptAfter.revision, probe.promptReset.revision);
  const timings = [
    cliProbe('get_conversation_state_command', { summaryMode: 'bootstrap', activeChatSessionId: 'session-1', turnLimit: 1 }),
    cliProbe('get_conversation_session_state_command', { sessionId: 'session-1', turnLimit: 1 }),
    cliProbe('get_agent_prompt_library_command', {}),
  ];
  process.stdout.write(`desktop state fastpath verification passed; fresh CLI timings: ${timings.map(row => `${row.command}=${row.elapsedMs}ms`).join(', ')}\n`);
} finally {
  rmSync(root, { recursive: true, force: true });
}
