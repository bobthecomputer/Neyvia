"""Log one existing C7 fixture family on its owned private desktop."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import traceback
import run_C7e_family


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    area = repo / '.agent_control/C7e/final-local-families'
    area.mkdir(parents=True, exist_ok=True)
    output = repo / 'scripts/evidence' / ('C7-final-' + args.family + '.json')
    sys.argv = ['run_C7e_family.py', '--family', args.family, '--port', str(args.port), '--output', str(output)]
    with (area / (args.family + '.log')).open('w', encoding='utf8') as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                raise SystemExit(run_C7e_family.main())
            except SystemExit:
                raise
            except BaseException as error:
                traceback.print_exc()
                (area / (args.family + '.failure.json')).write_text(json.dumps({
                    'family': args.family, 'port': args.port, 'errorType': type(error).__name__,
                    'error': str(error), 'ok': False}) + '\n', encoding='utf8')
                raise
