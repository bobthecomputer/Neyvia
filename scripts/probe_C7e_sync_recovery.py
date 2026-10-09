"""Diagnose the existing C7 native recovery contract using actual REST status."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.port != 48748:
        parser.error('This native contract requires explicit REST port 48748 and TCP port 48749')
    args.output.resolve().relative_to(REPO / 'scripts/evidence')
    root = REPO / '.agent_control/proofs/c7e-sync-probe' / uuid.uuid4().hex
    from grant_agent.edge_fixture_c7d_local import _isolate
    _isolate(root, args.port, allow_loopback=True)
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.proof_ports import configure_ports
    configure_ports(list(range(48741, 48750)))
    def audit(event, values):
        if event in {'socket.connect', 'socket.bind'}:
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'} or address[1] not in range(48741, 48750):
                raise PermissionError('Assigned owned loopback ports only')
    sys.addaudithook(audit)
    from grant_agent.edge_fixture_c7d_syncthing import observe
    from grant_agent.proof_contracts import source_digest
    bindings = {name: source_digest(REPO / name) for name in
                ('src/grant_agent/edge_fixture_c7d_syncthing.py', 'src/grant_agent/folder_sync.py', 'scripts/probe_C7e_sync_recovery.py')}
    samples = deque(maxlen=5)
    failures = deque(maxlen=5)
    original = urllib.request.urlopen
    class StatusResponse:
        def __init__(self, response): self.response = response
        def __enter__(self): self.response.__enter__(); return self
        def __exit__(self, *values): return self.response.__exit__(*values)
        def __getattr__(self, name): return getattr(self.response, name)
        def read(self, *values):
            raw = self.response.read(*values)
            samples.append(json.loads(raw))
            return raw
    def status_tap(request, *values, **options):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        try:
            response = original(request, *values, **options)
        except OSError as error:
            if url.startswith('http://127.0.0.1:48748/'):
                failures.append({'url': url, 'error': str(error), 'type': type(error).__name__})
            raise
        return StatusResponse(response) if url == 'http://127.0.0.1:48748/rest/db/status?folder=owned0' else response
    urllib.request.urlopen = status_tap
    row = {'id': 'c7e-sync-recovery-probe.adapters.sync.recovery.empty', 'contracts': ['adapters.sync.recovery'], 'category': 'empty'}
    try:
        row.update(status='passed', detail=observe(REPO, root, 'empty', 'adapters.sync.recovery'))
    except Exception as error:
        row.update(status='failed', detail={'error': str(error), 'type': type(error).__name__})
    finally:
        urllib.request.urlopen = original
    import shutil
    usage = shutil.disk_usage(root)
    report = {'schema': 'neyvia.c7e-sync-recovery-probe.v1', 'ok': row['status'] == 'passed', 'explicitPort': args.port,
              'root': str(root), 'rows': [row], 'actualFolderStatus': list(samples),
              'actualRequestFailures': list(failures),
              'disk': {'freeBytes': usage.free, 'totalBytes': usage.total}, 'sourceBindings': bindings,
              'sourceStable': all(source_digest(REPO / name) == expected for name, expected in bindings.items()),
              'boundary': 'Unmodified existing C7 recovery builder and native service; passive status-body tap. No generated credential/config files opened; no timeout or free-space policy changed.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': report['ok'], 'case': row, 'lastActualFolderStatus': list(samples)[-1] if samples else None, 'actualRequestFailures': list(failures), 'disk': report['disk']}))
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
