"""Exercise the actual Claude protocol driver with a confined CLI peer and slow consumer."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.connected_sessions.claude import ClaudeAdapter
from grant_agent.connected_sessions.claude_stream import ClaudeRun
from grant_agent.connected_sessions.model import TurnOptions
from grant_agent.proofs_a_providers import _Events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    source_names = ['src/grant_agent/connected_sessions/claude_stream.py',
                    'src/grant_agent/connected_sessions/claude.py',
                    'tests/fixtures/fake_claude_cli.py', 'scripts/verify_fix_provider_idle.py']
    def sources():
        return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_names}
    before = sources()
    root = ROOT / '.agent_control/fix/provider-idle' / uuid.uuid4().hex
    folder = root / 'work'
    folder.mkdir(parents=True)
    config = root / 'config'
    (config / 'projects/scratch').mkdir(parents=True)
    live = root / 'live.json'
    live.write_text('[]', encoding='utf-8')
    ClaudeRun.__init__.__kwdefaults__['shutdown_grace'] = .05
    checks = []
    for mode in ('slow-consumer', 'silent', 'explicit-interrupt'):
        driver = ClaudeAdapter(config_dir=config,
            cli_path=[sys.executable, str(ROOT / 'tests/fixtures/fake_claude_cli.py')],
            host={'deviceId': 'proofprovider01', 'deviceName': 'Scratch PC', 'kind': 'local'},
            agents_ttl=0, context_probe=False, idle_timeout=.7, interrupt_grace=.2,
            extra_env={'FAKE_CLAUDE_LOG': str(root / 'peer.jsonl'),
                       'FAKE_CLAUDE_AGENTS': str(live),
                       'FAKE_CLAUDE_SIGNED_IN': str(root / 'unused-sign-in.marker')})
        observer, outcome = _Events(), {}
        run_id = 'idle-' + mode
        delayed = False
        def emit(event):
            nonlocal delayed
            observer(event)
            if event['type'] == 'item.delta' and not delayed:
                delayed = True
                if mode == 'slow-consumer':
                    time.sleep(1.2)
                elif mode == 'explicit-interrupt':
                    driver.interrupt(run_id)
                    time.sleep(1.2)
        def run():
            try:
                outcome['session'] = driver.start_turn(None,
                    'SCN:silent' if mode == 'silent' else 'SCN:paced', TurnOptions(),
                    cwd=str(folder), run_id=run_id, emit=emit)
            except BaseException as error:
                outcome['error'] = repr(error)
        started = time.monotonic()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(18)
        overran = worker.is_alive()
        if overran:
            driver.interrupt(run_id)
            worker.join(6)
        states = observer.states()
        text = ''.join(item['data'].get('text', '') for item in observer.items() if item['kind'] == 'assistant')
        expected = 'completed' if mode == 'slow-consumer' else 'interrupted'
        checks.append({'name': mode, 'ok': not overran and not worker.is_alive()
                       and 'error' not in outcome and bool(states) and states[-1] == expected
                       and (mode != 'slow-consumer' or 'tick7' in text),
                       'states': states, 'expected': expected, 'text': text,
                       'seconds': round(time.monotonic() - started, 3),
                       'workerStopped': not worker.is_alive(), 'error': outcome.get('error')})
        if worker.is_alive():
            break
    receipt = {'boundary': 'actual protocol driver and real isolated CLI process; controlled peer, no live provider account',
               'phase': args.phase, 'checks': checks, 'sourceHashes': before,
               'sourceStable': before == sources(), 'fixture': str(root),
               'ok': len(checks) == 3 and all(row['ok'] for row in checks)}
    path = ROOT / f'scripts/evidence/FIXb-provider-idle-{args.phase}.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(path), 'ok': receipt['ok'], 'checks': checks}))
    return 0 if receipt['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
