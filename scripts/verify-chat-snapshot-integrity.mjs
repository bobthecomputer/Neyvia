import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const result = spawnSync(resolveNeyviaPython(root).python, ['-c', `
import json, tempfile
from pathlib import Path
from grant_agent.mission_control import _build_runtime_compartments_snapshot
with tempfile.TemporaryDirectory(prefix='neyvia-chat-integrity-') as folder:
    root = Path(folder)
    directory = root / '.agent_control' / 'runtime_compartments'
    directory.mkdir(parents=True)
    answer = 'Full reply. ' * 1600 + 'END OF ANSWER'
    payload = {'sessionId':'integrity', 'messages':[{'turnId':'answer', 'role':'assistant', 'text':answer}], 'toolTimeline':[{'text':'tool output ' * 1000}]}
    (directory / 'integrity.json').write_text(json.dumps(payload))
    item = _build_runtime_compartments_snapshot(root, [])['items'][0]
    assert item['messages'][0]['text'] == answer
    assert len(item['toolTimeline'][0]['text']) == 1200
    print(json.dumps({'ok':True,'answerCharacters':len(answer),'answerPreserved':True,'toolPreviewBounded':True}))
`], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, 'src') }, encoding: 'utf8', timeout: 30000 });
assert.equal(result.status, 0, result.stderr || String(result.error));
const receipt = JSON.parse(result.stdout);
const output = path.join(root, 'proof/chat-truncation-20260928');
mkdirSync(output, { recursive: true });
writeFileSync(path.join(output, 'snapshot-integrity.json'), JSON.stringify(receipt, null, 2));
console.log(JSON.stringify(receipt));
