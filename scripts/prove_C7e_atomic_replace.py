"""Generate C7 contracts over actual Windows sharing denial and durable replacement."""
import argparse
import hashlib
import json
import os
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
    if os.name != 'nt':
        raise RuntimeError('Actual Windows sharing handles required')
    from grant_agent.edge_fixture_host_runtime import _sharing
    from grant_agent import durability
    root = REPO / '.agent_control/proofs' / ('c7e-atomic-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    rows = []
    for lifetime in ('transient', 'permanent'):
        for kind in ('text', 'bytes'):
            target = root / (lifetime + '-' + kind + '.json')
            before, after = b'original complete record\n', 'updated 雪 complete record\n'.encode('utf8')
            target.write_bytes(before)
            ready, release = threading.Event(), threading.Event()
            failures = []

            def deny():
                try:
                    with _sharing(target):
                        ready.set()
                        release.wait(.2 if lifetime == 'transient' else 10)
                except BaseException as error:
                    failures.append(str(error))
                    ready.set()

            thread = threading.Thread(target=deny)
            thread.start()
            if not ready.wait(5) or failures:
                raise RuntimeError('Actual sharing fixture failed: ' + str(failures))
            denied = False
            started = time.monotonic()
            try:
                if kind == 'text':
                    durability.atomic_write_text(target, after.decode('utf8'))
                else:
                    durability.atomic_write_bytes(target, after)
            except PermissionError:
                denied = True
            finally:
                release.set()
                thread.join(5)
            expected_denial = lifetime == 'permanent'
            valid = (denied == expected_denial and target.read_bytes() == (before if expected_denial else after)
                     and not list(root.glob('.' + target.name + '.*.tmp')) and not thread.is_alive() and not failures)
            rows.append({'id': 'C7.atomic-replace.' + lifetime + '.' + kind,
                         'category': 'permissions' if expected_denial else 'concurrency',
                         'status': 'passed' if valid else 'failed',
                         'checks': {'actualWindowsSharingHandle': True, 'permanentDenial': expected_denial,
                                    'observedDenial': denied, 'exactFinalBytes': target.read_bytes() == (before if expected_denial else after),
                                    'temporaryFilesCleaned': not list(root.glob('.' + target.name + '.*.tmp'))},
                         'durationMs': round((time.monotonic() - started) * 1000, 2)})
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    report = {'schema': 'neyvia.c7e-atomic-replace.v1', 'ok': all(r['status'] == 'passed' for r in rows),
              'explicitPort': args.port, 'cases': rows,
              'sourceBindings': {name: hashlib.sha256((REPO / name).read_text(encoding='utf8').encode()).hexdigest()
                                 for name in ('src/grant_agent/durability.py', 'scripts/prove_C7e_atomic_replace.py')},
              'boundary': 'Actual Windows file sharing and production atomic writers; no rendered or matrix coverage claimed.'}
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': report['ok'], 'passing': sum(r['status'] == 'passed' for r in rows), 'failing': sum(r['status'] != 'passed' for r in rows)}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
