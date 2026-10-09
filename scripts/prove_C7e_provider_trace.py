"""C7 diagnostic cases observing actual finite-peer output and adapter states."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from grant_agent.proof_ports import c7_port_block
    c7_port_block(args.port)
    from grant_agent.edge_fixture_c7d_local import _isolate
    from grant_agent.edge_fixture_c7d_control import _provider_turn
    from grant_agent import proofs_a_providers as observers
    from grant_agent.connected_sessions import claude_stream as stream
    root = REPO / '.agent_control/proofs' / ('c7e-provider-trace-' + uuid.uuid4().hex)
    _isolate(root, args.port)
    events, lock = [], threading.Lock()
    start = time.monotonic()
    category = None

    def note(**fields):
        with lock:
            events.append({'category': category, 'elapsedMs': round((time.monotonic() - start) * 1000, 2), **fields})

    original_event, original_start = observers._Events.__call__, stream.start_process

    def event(self, value):
        note(boundary='adapter-event', eventType=value.get('type'), state=value.get('state'), runId=value.get('runId'))
        return original_event(self, value)

    class ObservedOutput:
        def __init__(self, original, process):
            self.original, self.process = original, process

        def readline(self, *args):
            raw = self.original.readline(*args)
            try:
                value = json.loads(raw.decode('utf8')) if raw else {}
            except (ValueError, UnicodeError):
                value = {}
            note(boundary='stdout-line' if raw else 'stdout-eof', pid=self.process.pid,
                 lineType=value.get('type'), subtype=value.get('subtype'), exitCode=self.process.poll())
            return raw

        def __getattr__(self, name):
            return getattr(self.original, name)

    def spawn(*args, **kwargs):
        process = original_start(*args, **kwargs)
        note(boundary='child-start', pid=process.pid)
        process.stdout = ObservedOutput(process.stdout, process)
        return process

    rows = []
    observers._Events.__call__, stream.start_process = event, spawn
    try:
        for category in ('concurrency', 'interrupted'):
            area = root / category
            area.mkdir()
            try:
                detail = _provider_turn(area, category, 'providers.claude.lifecycle')
                rows.append({'id': 'C7.provider-output-trace.' + category, 'category': category, 'status': 'passed', 'detail': detail})
            except Exception as error:
                rows.append({'id': 'C7.provider-output-trace.' + category, 'category': category, 'status': 'failed',
                             'errorType': type(error).__name__, 'error': str(error)})
    finally:
        observers._Events.__call__, stream.start_process = original_event, original_start
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    report = {'schema': 'neyvia.c7e-provider-trace.v1', 'ok': all(r['status'] == 'passed' for r in rows),
              'explicitPort': args.port, 'cases': rows, 'events': events,
              'sourceBindings': {name: hashlib.sha256((REPO / name).read_text(encoding='utf8').encode()).hexdigest()
                                 for name in ('src/grant_agent/edge_fixture_c7d_control.py', 'src/grant_agent/connected_sessions/claude_stream.py', 'scripts/prove_C7e_provider_trace.py')},
              'boundary': 'Actual finite owned stdio children and production adapter, observing only event kinds and timing; no payloads, provider authentication, rendered proof or full-family closure.'}
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': report['ok'], 'cases': [(r['category'], r['status']) for r in rows], 'events': len(events)}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
