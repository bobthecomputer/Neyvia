"""Real mission/cache calls plus unchanged-state checks at the production boundary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    root = REPO / '.agent_control/proofs' / ('c7d-cache-race-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    for key in ('HOME', 'USERPROFILE', 'CODEX_HOME', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        folder = root / 'home' / key.lower()
        folder.mkdir(parents=True)
        os.environ[key] = str(folder)
    for key in ('NEYVIA_UI_STATE_ROOT', 'NEYVIA_UI_BACKEND_URL', 'FLUXIO_WORKSPACE_ROOT', 'FLUXIO_CLUSTER_ROOT', 'FLUXIO_CONTROL_PROJECT_ROOT'):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), FLUXIO_WATCHDOG_AUTOSTART='0',
                      NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_CONTROL_ROOM_FAST='1',
                      FLUXIO_MISSION_ACTION_COMPACT='1', PYTHONPATH=str(REPO / 'src'))
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.proof_ports import configure_ports
    configure_ports(list(range(48741, 48750)))
    def audit(event, values):
        if event in {'socket.bind', 'socket.connect'}:
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'} or address[1] not in range(48741, 48750):
                raise PermissionError('Assigned loopback fixture only')
    sys.addaudithook(audit)
    from grant_agent import proofs_c_control as checks
    from grant_agent.mission_control import ControlRoomStore
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_contracts import source_digest, ContractViolation
    from grant_agent.edge_contracts import inventory, CATEGORIES
    from grant_agent.edge_fixture_c7d_control import run
    names = ['scripts/prove_C7d_cache_race.py', 'src/grant_agent/proofs_c_control.py',
             'src/grant_agent/mission_control.py', 'src/grant_agent/edge_fixture_c7d_control.py',
             'src/grant_agent/cli.py', 'src/grant_agent/durability.py', 'src/grant_agent/proofs_c_missions.py']
    bindings = {name: source_digest(REPO / name) for name in names}
    path = root / 'cache.json'
    atomic_write_json(path, {'revision': 'old'})
    original = ControlRoomStore._load_json(path, {})
    original_capture = checks.capture
    captured = []
    def replace_after_capture(kind, inputs):
        before = original_capture(kind, inputs)
        if kind == 'cache' and inputs['path'] == path:
            captured.append(before)
            atomic_write_json(path, {'revision': 'new Unicode 雪🙂'})
            ControlRoomStore._invalidate_json_cache(path)
        return before
    checks.capture = replace_after_capture
    try:
        changed = ControlRoomStore._load_json(path, {})
    finally:
        checks.capture = original_capture
    assert changed == {'revision': 'new Unicode 雪🙂'} and changed is not original
    assert captured[0]['cached'][2] is original
    assert captured[0]['stamp'] != (path.stat().st_mtime_ns, path.stat().st_size)
    default = {}
    inputs = {'path': path, 'default': default}
    unchanged = ControlRoomStore._load_json(path, default)
    assert ControlRoomStore._load_json(path, default) is unchanged
    negative_checks = []
    def refused(name, result, before):
        try:
            checks.check('cache', inputs, result, before)
        except ContractViolation as error:
            negative_checks.append({'case': name, 'refused': True, 'error': str(error)})
        else:
            raise AssertionError('Unchanged-state invariant weakened: ' + name)
    refused('unchanged-object-copy', dict(unchanged), checks.capture('cache', inputs))
    ControlRoomStore._invalidate_json_cache(path)
    before = checks.capture('cache', inputs)
    freshly_parsed = ControlRoomStore._load_json(path, default)
    ControlRoomStore._invalidate_json_cache(path)
    refused('unchanged-parse-not-published', freshly_parsed, before)
    _, contracts = inventory()
    rows = run(root / 'mission-docs', contracts, CATEGORIES, families=['mission-docs-state'])
    assert len(rows) == 8 and all(row['status'] == 'passed' for row in rows), rows
    previous = REPO / '.agent_control/proofs/c7/51e221fcf75f48f1ba32f9070bf21a45/semantic-fixtures/c7d-control.receipt.json'
    previous_data = json.loads(previous.read_text(encoding='utf8'))
    failures = [row for row in previous_data['rows'] if row['id'] == 'c7d-control.a-cli.preferences.docs.concurrency']
    assert len(failures) == 1 and failures[0]['status'] == 'failed'
    stable = bindings == {name: source_digest(REPO / name) for name in names}
    assert stable
    report = {'schema': 'neyvia.c7d-cache-race.v1', 'ok': True, 'explicitPort': args.port,
              'root': str(root), 'sourceBindings': bindings, 'sourceStable': stable,
              'before': {'path': previous.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(previous.read_bytes()).hexdigest(), 'failedCases': failures},
              'actualReplacementBetweenCaptureAndRead': True, 'unchangedObjectReused': True,
              'strictNegativeChecks': negative_checks, 'missionDocsCases': rows,
              'boundary': 'Actual production cache reader and atomic replacement, eight existing mission-result fixtures. Timing hook changes only replacement scheduling. No rendered, provider or live service claim.'}
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'missionDocsPassed': len(rows), 'strictRefusals': len(negative_checks), 'sourceStable': stable}))

if __name__ == '__main__':
    main()
