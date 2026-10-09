"""Run selected existing generated builders for focused repair and evidence."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    from grant_agent.edge_fixture_catalog import BUILDERS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--family', choices=BUILDERS, required=True)
    parser.add_argument('--contract', action='append')
    parser.add_argument('--category', action='append')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from c7_dependencies import configure
    dependency_root = configure()
    from grant_agent.proof_ports import c7_port_block, c7_run_root
    assigned_ports = c7_port_block(args.port)
    root = (c7_run_root() / 'families' if os.environ.get('NEYVIA_C7_RUN_ROOT')
            else REPO / '.agent_control/proofs/c7e-family') / uuid.uuid4().hex
    root.mkdir(parents=True)
    for name in ('HOME', 'USERPROFILE', 'CODEX_HOME', 'HERMES_HOME', 'OPENCLAW_STATE_DIR', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        target = root / 'home' / name.lower()
        target.mkdir(parents=True)
        os.environ[name] = str(target)
    for name in ('NEYVIA_UI_STATE_ROOT', 'NEYVIA_UI_BACKEND_URL', 'FLUXIO_WEB_BACKEND_URL', 'FLUXIO_WORKSPACE_ROOT', 'NEYVIA_NAS_ROOT', 'FLUXIO_NAS_ROOT'):
        os.environ.pop(name, None)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), PYTHONPATH=str(REPO / 'src'), PYTHONIOENCODING='utf-8', NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0')
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.proof_ports import configure_ports
    configure_ports(assigned_ports)
    def audit(event, values):
        if event in {'socket.connect', 'socket.bind'}:
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'} or address[1] not in assigned_ports:
                raise PermissionError('Owned assigned loopback ports only')
    sys.addaudithook(audit)
    from grant_agent.edge_contracts import inventory, CATEGORIES
    from grant_agent.edge_fixture_catalog import run, completed_receipts
    from grant_agent.edge_live_observations import LiveObservations
    _, contracts = inventory()
    if args.contract:
        contracts = {identity: contracts[identity] for identity in args.contract}
    categories = args.category or CATEGORIES
    if set(categories) - set(CATEGORIES):
        parser.error('Unknown category')
    rows = run(root / 'semantic-fixtures', contracts, categories, [args.family], live_observations=LiveObservations())
    receipts = completed_receipts(root / 'semantic-fixtures')
    report = {'schema': 'neyvia.c7e-family.v1', 'ok': all(r['status'] == 'passed' for r in rows),
              'sourceStable': True, 'explicitPort': args.port, 'root': str(root), 'family': args.family,
              'rows': rows, 'counts': dict(Counter(r['status'] for r in rows)), 'familyReceipts': receipts,
              'dependencyRoot': str(dependency_root) if dependency_root else None}
    if not args.output.resolve().is_relative_to(REPO / 'scripts/evidence'):
        args.output.resolve().relative_to(c7_run_root())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'family': args.family, 'counts': report['counts'], 'failures': [{'id': r['id'], 'detail': r.get('detail')} for r in rows if r['status'] == 'failed']}))
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
