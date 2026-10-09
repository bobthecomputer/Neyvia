"""Validate and commit each completed compiled family independently."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from retain_C7e_compiled import REPO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', action='append', default=[])
    parser.add_argument('--pool', type=Path, action='append', default=[],
                        help='Commit successful completed families from an owned worker pool')
    args = parser.parse_args()
    families = list(args.family)
    for path in args.pool:
        path = path.resolve()
        path.relative_to(REPO / '.agent_control/C7e')
        pool = json.loads(path.read_bytes())
        for row in pool['finished']:
            if row['ok'] and row['family'] not in families:
                families.append(row['family'])
    if not families:
        parser.error('At least one completed family is required')
    directory = REPO / 'scripts/evidence/C7e-compiled-families'
    directory.mkdir(exist_ok=True)
    for family in families:
        evidence = REPO / 'scripts/evidence' / ('C7e-' + family + '-compiled.json')
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        target = directory / (family + '.json')
        if target.exists():
            previous = json.loads(target.read_bytes())
            if previous['families'][0]['evidence']['sha256'] == digest:
                continue
            historical = target.with_name(family + '-before-' + hashlib.sha256(target.read_bytes()).hexdigest()[:12] + '.json')
            if historical.exists() and historical.read_bytes() != target.read_bytes():
                raise ValueError('Historical compiled retention differs')
            historical.write_bytes(target.read_bytes())
        subprocess.run([sys.executable, str(REPO / 'scripts/retain_C7e_compiled.py'), '--port', '48743',
                        '--family', family, '--output', str(target)], cwd=REPO, check=True, capture_output=True)
        files = [target, evidence, *evidence.parent.glob(evidence.stem + '-before-*.json'),
                 *directory.glob(family + '-before-*.json')]
        subprocess.run(['git', 'add', '--', *[str(path.relative_to(REPO)) for path in files]], cwd=REPO, check=True, capture_output=True)
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO)
        if changed.returncode:
            subprocess.run(['git', 'commit', '-qm', 'Prove compiled C7e ' + family + ' family contracts', '-m',
                            'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'], cwd=REPO, check=True, capture_output=True)
        value = json.loads(target.read_bytes())['families'][0]
        print(json.dumps({'family': family, 'cases': value['cases'], 'counts': value['counts'],
                          'commit': subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, text=True).strip()}), flush=True)


if __name__ == '__main__':
    main()
