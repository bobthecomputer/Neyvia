"""Compare the exact surviving Node test declarations and failures."""
import hashlib
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(label):
    directory = ROOT / 'scripts/evidence/int3/checks' / label
    result = json.loads((directory / 'results.json').read_text())['node']
    log = (directory / 'node.log').read_text(encoding='utf-8')
    normal = log.replace(str(ROOT / '.agent_control/int3/baseline-complete-src'), str(ROOT))
    declarations = [re.sub(r' \([^\n]*ms\)$', '', line)[2:]
                    for line in normal.splitlines() if line.startswith(('✔ ', '✖ '))]
    failures = sorted(set(line for line in declarations
                          if 'neyvia_browser_authority_contract.test.mjs' in line))
    counts = {key: int(re.search(r'ℹ ' + key + r' (\d+)', log)[1])
              for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped')}
    return {'counts': counts, 'declarations': declarations,
            'failures': failures, 'exitCode': result['exitCode'],
            'seconds': result['seconds'],
            'logSha256': hashlib.sha256((directory / 'node.log').read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='baseline-node-remaining')
    parser.add_argument('--after', default='final-node-remaining')
    args = parser.parse_args()
    before, after = read(args.baseline), read(args.after)
    matched = before['declarations'] == after['declarations']
    known = (before['counts']['fail'] == after['counts']['fail'] == 1
             and before['failures'] == after['failures'] and bool(after['failures']))
    result = {'baselineLabel': args.baseline, 'afterLabel': args.after,
              'baseline': before, 'after': after, 'sameDeclarations': matched,
              'noNewFailures': matched and known and before['counts'] == after['counts'],
              'knownFailure': 'Authoritative checkout .venv is absent; original and integrated Node file both fail.'}
    output = ROOT / 'scripts/evidence/int3/node-comparison.json'
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'sameDeclarations': matched, 'noNewFailures': result['noNewFailures']}))
    return int(not result['noNewFailures'])


if __name__ == '__main__':
    raise SystemExit(main())
