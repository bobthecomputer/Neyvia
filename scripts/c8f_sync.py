"""Native Syncthing actions through Neyvia's selected producer and CL manual."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.proof_ports import configure_ports
from grant_agent.proof_credential_guard import install, prepare_broker_fixture
from grant_agent.native_tools import NativeToolRegistry
from grant_agent import neyvia_manuals as manuals
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from c8_scope import assigned_ports


def run(ports):
    install_hidden_subprocess_default()
    root = ROOT / '.agent_control/proofs/C8/c8f-sync' / uuid.uuid4().hex
    root.mkdir(parents=True)
    install(root)
    prepare_broker_fixture(root)
    if len(ports) != 6 or len(set(ports)) != 6 or any(p not in assigned_ports() for p in ports):
        raise ValueError('Six distinct assigned C8 fixture ports required')
    configure_ports(ports)
    os.environ.update(NEYVIA_PROOF_AGENT_DESKTOP='1', NEYVIA_COORDINATOR_AUTOSTART='0',
        FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_TOOL_AUTO_UPDATE='0')
    registry = NativeToolRegistry(root)
    host = SimpleNamespace(bus=SimpleNamespace(root=root))
    producer = registry.call('neyvia.verify', {'areas': ['proofs-b-adapters'],
        'adapterChapters': ['sync'], 'includeManuals': False})
    report = producer.get('result', {})
    if not isinstance(report, dict) or not isinstance(report.get('areas'), list):
        raise RuntimeError('Selected verifier returned no actual area report')
    reader = manuals.run(host, {'id': 'proofs-b-adapters', 'chapter': 'proofs-b-native-sync',
        'procedure': 'read-latest', 'inputs': {}}, registry,
        lambda tool, args, action_id='': manuals.unwrap(registry.call(tool, args)))
    actual = [json.loads(p.read_text(encoding='utf-8')) for p in root.rglob('native-sync/receipt.json')]
    receipt = {'schema': 'neyvia.c8f.native-sync.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'id': 'proofs-b-adapters/proofs-b-native-sync/read-latest', 'producer': report,
        'reader': reader, 'nativeReceipts': actual, 'root': str(root.relative_to(ROOT)),
        'sourceSha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            'scripts/c8f_sync.py', 'src/grant_agent/proofs_b_adapters.py',
            'manuals/cl/proofs-b-adapters.cl')},
        'boundary': 'Actual pinned native Syncthing configuration and refusals on the C11 private desktop; no NAS or remote-device synchronization'}
    areas = report.get('areas', [])
    receipt['passed'] = (reader.get('ok') is True and len(areas) == 1 and areas[0].get('ok') is True
        and bool(actual) and all(r.get('ok') and r.get('ownedProcessStopped')
                               and r.get('guard', {}).get('ok') for r in actual))
    (ROOT / 'scripts/evidence/C8f-sync.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps({'passed': receipt['passed'], 'reader': reader.get('status'),
        'nativeReceipts': len(actual), 'areas': [(a.get('area'), a.get('ok')) for a in areas]}))
    return receipt['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ports', required=True, nargs=6, type=int)
    raise SystemExit(0 if run(parser.parse_args().ports) else 1)
