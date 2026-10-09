"""Generate C7 cases over the real manual client effect/stop handshake."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from grant_agent.proof_ports import c7_port_block
    c7_port_block(args.port)
    from grant_agent.edge_fixture_c7d_local import _isolate
    from grant_agent.edge_fixture_c7d_control_completion import _manual
    root = REPO / '.agent_control/proofs' / ('c7e-manual-marker-' + uuid.uuid4().hex)
    _isolate(root, args.port)
    rows = []
    for category in ('empty', 'huge', 'unicode', 'concurrency', 'interrupted', 'permissions', 'offline', 'stale'):
        case = root / category
        case.mkdir()
        try:
            detail = _manual(case, category, 'control.agents-manual')
            rows.append({'id': 'C7.manual-marker.' + category, 'category': category, 'status': 'passed', 'detail': detail})
        except Exception as error:
            rows.append({'id': 'C7.manual-marker.' + category, 'category': category, 'status': 'failed', 'error': str(error)})
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    report = {'schema': 'neyvia.c7e-manual-marker.v1', 'ok': all(r['status'] == 'passed' for r in rows),
              'explicitPort': args.port, 'cases': rows,
              'sourceBindings': {name: hashlib.sha256((REPO / name).read_text(encoding='utf8').encode()).hexdigest()
                                 for name in ('src/grant_agent/edge_fixture_c7d_control_completion.py', 'scripts/prove_C7e_manual_marker.py')},
              'boundary': 'Actual selected manual repository, production client and real stopped child; no rendered proof or matrix closure implied.'}
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': report['ok'], 'passing': sum(r['status'] == 'passed' for r in rows), 'failing': sum(r['status'] != 'passed' for r in rows)}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
