"""Bounded real Codex provider call; saved login stays inside the official CLI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs


def run():
    area = ROOT / '.agent_control/proofs/C8/c8f-provider'
    area.mkdir(parents=True, exist_ok=True)
    command = shutil.which('codex.cmd') or shutil.which('codex')
    if not command:
        raise RuntimeError('The signed-in Codex CLI is unavailable')
    marker = 'C8f real provider sidebar reply'
    prompt = 'Do not call tools. Reply with exactly: ' + marker
    args = [command, 'exec', '--model', 'gpt-6.1-sol', '-c', 'model_reasoning_effort="low"',
            '-c', 'project_doc_max_bytes=0', '--sandbox', 'read-only', '--json',
            '--skip-git-repo-check', '-C', str(area), prompt]
    completed = subprocess.run(args, cwd=area, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180, **hidden_windows_subprocess_kwargs())
    events = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith('{')]
    answers = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
               and e.get('item', {}).get('type') == 'agent_message']
    usage = [e['usage'] for e in events if e.get('type') == 'turn.completed']
    thread = next((e.get('thread_id') for e in events if e.get('type') == 'thread.started'), None)
    receipt = {'schema': 'neyvia.c8f.provider.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'provider': 'Official locally signed-in Codex CLI', 'model': 'gpt-6.1-sol', 'effort': 'low',
        'exitCode': completed.returncode, 'threadId': thread, 'answer': answers[-1] if answers else None,
        'usage': usage, 'passed': completed.returncode == 0 and answers == [marker] and bool(usage),
        'prompt': prompt, 'sourceSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'events': events, 'credentialsReadByHarness': False,
        'boundary': 'Actual returned provider reply; sidebar consumption is verified separately',
        'stderrRetained': False}
    target = ROOT / 'scripts/evidence/C8f-provider.json'
    if target.exists():
        previous = target.read_bytes()
        (area / (hashlib.sha256(previous).hexdigest() + '.json')).write_bytes(previous)
    target.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: receipt[k] for k in ('passed', 'threadId', 'usage', 'exitCode')}))
    return receipt['passed']


if __name__ == '__main__':
    raise SystemExit(0 if run() else 1)
