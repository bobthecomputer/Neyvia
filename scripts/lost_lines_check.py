"""Report side-added lines missing after each first-parent integration merge.

This is a review aid, never a conflict resolver. Rewrites and generated views
need semantic review; a report alone does not prove lost behavior.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from functools import lru_cache


class GitObjects:
    """One read-only Git stream; deleted objects are an expected audit input."""
    def __init__(self):
        self.process = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    @lru_cache(maxsize=None)
    def read(self, revision, path):
        self.process.stdin.write(f'{revision}:{path}\n'.encode('utf-8'))
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode('utf-8').rstrip('\n')
        if header.endswith(' missing'):
            return ''
        size = int(header.rsplit(' ', 1)[1])
        value = self.process.stdout.read(size)
        if self.process.stdout.read(1) != b'\n':
            raise RuntimeError('Git object stream framing failed')
        return value.decode('utf-8', errors='replace')

    def close(self):
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.wait()

def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='replace').stdout

def check(ref, base):
    objects = GitObjects()
    findings = []
    missing_manual_entries = []
    revision = f'{base}..{ref}' if base else ref
    merges = git('log', '--first-parent', '--merges', '--format=%H', revision).splitlines()
    for sha in reversed(merges):
        parents = git('show', '-s', '--format=%P', sha).split()
        if len(parents) != 2:
            raise ValueError('Expected a two-parent merge: ' + sha)
        common = git('merge-base', *parents).strip()
        # Chapters/actions/procedures are keyed data, so formatting cannot hide
        # a dropped entry. Do not reconstruct their contents from line sets.
        merged_paths = set(git('ls-tree', '-r', '--name-only', sha, 'manuals').splitlines())
        for side in parents:
            paths = git('ls-tree', '-r', '--name-only', side, 'manuals').splitlines()
            for file in paths:
                if not file.endswith('.manual.json'):
                    continue
                before = json.loads(objects.read(side, file))
                after = json.loads(objects.read(sha, file)) if file in merged_paths else {}
                for chapter, data in before.get('chapters', {}).items():
                    retained = after.get('chapters', {}).get(chapter)
                    if retained is None:
                        missing_manual_entries.append({'merge':sha, 'side':side, 'file':file, 'entry':chapter})
                        continue
                    for family in ('actions', 'procedures', 'checks'):
                        for key in data.get(family, {}):
                            if key not in retained.get(family, {}):
                                missing_manual_entries.append({'merge':sha, 'side':side, 'file':file,
                                                               'entry':f'{chapter}/{family}/{key}'})
        files = set(git('diff', '--name-only', common, parents[0]).splitlines()) & set(git('diff', '--name-only', common, parents[1]).splitlines())
        for file in sorted(files):
            if not file.endswith(('.py', '.js', '.jsx', '.json', '.css', '.rs', '.md')):
                continue
            merged = Counter(objects.read(sha, file).splitlines())
            for side in parents:
                added = Counter(line[1:] for line in git('diff', '-U0', common, side, '--', file).splitlines()
                                if line.startswith('+') and not line.startswith('+++'))
                full = Counter(objects.read(side, file).splitlines())
                for line, count in added.items():
                    if len(line.strip()) < 4 or line.strip() in {'},', '),', '];'}:
                        continue
                    missing = min(full[line], count) - merged[line]
                    if missing > 0:
                        findings.append({'merge': sha, 'side': side, 'file': file,
                                         'missingCount': missing, 'line': line.strip()})
    objects.close()
    return {'ref': git('rev-parse', ref).strip(), 'base': base, 'merges': len(merges),
            'findings': findings, 'missingManualEntries': missing_manual_entries}

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--base', help='Exclude inherited merges before this integration baseline')
    parser.add_argument('--json', type=Path, help='Write complete review findings')
    args = parser.parse_args()
    result = check(args.ref, args.base)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for row in result['findings']:
        print(f"{row['merge'][:8]} | {row['file']} | missing x{row['missingCount']}: {row['line'][:110]}")
    print(f"Reviewed {result['merges']} merges; {len(result['findings'])} lines require semantic review")
    print(f"Missing manual chapters/actions/procedures/checks: {len(result['missingManualEntries'])}")
    return int(bool(result['missingManualEntries']))

if __name__ == '__main__':
    raise SystemExit(main())
