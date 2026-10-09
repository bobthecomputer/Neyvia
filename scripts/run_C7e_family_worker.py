"""Run one compiled family contract, logging only into its owned evidence area."""
import argparse
import contextlib
import json
import hashlib
from pathlib import Path
import sys
import traceback
import prove_C7e_compiled


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', required=True)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    base = Path(__file__).resolve().parents[1]
    logs = base / '.agent_control/C7e/compiled-families'
    logs.mkdir(parents=True, exist_ok=True)
    output = base / 'scripts/evidence' / ('C7e-' + args.family + '-compiled.json')
    sys.argv = ['prove_C7e_compiled.py', '--port', str(args.port), '--manual', 'C7e-' + args.family,
                '--chapter', 'pure' if args.family == 'pure' else 'campaign', '--procedure', 'run-family',
                '--family', args.family, '--output', str(output)]
    if output.exists():
        raw = output.read_bytes()
        previous = json.loads(raw)
        backup = output.with_name(output.stem + '-before-' + hashlib.sha256(raw).hexdigest()[:12] + '.json')
        if backup.exists() and backup.read_bytes() != raw:
            raise ValueError('Historical compiled report differs')
        backup.write_bytes(raw)
        if (previous.get('manual'), previous.get('family'), previous.get('explicitPort')) == ('C7e-' + args.family, args.family, args.port):
            sys.argv.extend(['--replay-from', str(backup)])
    workspace = logs / (args.family + '.workspace.json')
    if '--replay-from' not in sys.argv and workspace.is_file():
        saved = json.loads(workspace.read_bytes())
        if (saved.get('family'), saved.get('port')) == (args.family, args.port):
            selected = Path(saved['root']).resolve()
            selected.relative_to(base / '.agent_control/proofs/c7e-compiled')
            sys.argv.extend(['--resume-root', str(selected)])
    with (logs / (args.family + '.log')).open('w', encoding='utf8') as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                prove_C7e_compiled.main()
            except BaseException as error:
                traceback.print_exc()
                (logs / (args.family + '.failure.json')).write_text(json.dumps({
                    'family': args.family, 'explicitPort': args.port, 'ok': False,
                    'errorType': type(error).__name__, 'error': str(error),
                    'boundary': 'Failed compiled procedure; no passing family proof claimed'}, indent=2) + '\n', encoding='utf8')
                raise
