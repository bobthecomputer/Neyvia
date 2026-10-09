"""Supplement the missing early related check with exact first-merge source."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REF = 'bc2ddba5'


def main():
    target = ROOT / '.agent_control/int3/laya-retrospective-src'
    if target.exists():
        raise SystemExit('Historical check snapshot already exists')
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', REF], cwd=ROOT, text=True).splitlines()
    selected = [name for name in paths if name.startswith('src/') and name.endswith('.py')]
    selected += ['manuals/cl/notes.cl', 'tests/test_intcl_manual_sources.py', 'tests/test_cl_config_validation.py']
    hashes = {}
    batch = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for name in selected:
        batch.stdin.write(f'{REF}:{name}\n'.encode())
        batch.stdin.flush()
        header = batch.stdout.readline().decode().strip().split()
        if len(header) != 3:
            raise ValueError('Historical source missing: ' + name)
        body = batch.stdout.read(int(header[2]))
        if batch.stdout.read(1) != b'\n':
            raise ValueError('Invalid object boundary')
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        hashes[name] = hashlib.sha256(body).hexdigest()
    batch.stdin.close()
    if batch.wait() != 0:
        raise ValueError('Git object reader failed')
    manifest = {'snapshot': str(target), 'ref': REF, 'workingBytes': False,
                'hashes': hashes, 'files': len(hashes),
                'boundary': 'Retrospective targeted check of original first merge, not a contemporaneous after-merge receipt or complete source snapshot.'}
    (target.parent / 'laya-retrospective-snapshot.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/int3_pytest_run.py'),
                             '--source', str(target), '--label', 'laya-retrospective',
                             'tests/test_intcl_manual_sources.py', 'tests/test_cl_config_validation.py'], cwd=ROOT)
    outcome = json.loads((target.parent / 'laya-retrospective.outcomes.json').read_text(encoding='utf-8'))
    mismatch = [name for name, digest in hashes.items()
                if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest]
    receipt = {'commit': REF, 'exitCode': result.returncode, 'selected': outcome['selected_ids'],
               'failed': outcome['failed_ids'], 'sourceIntegrity': not mismatch, 'mismatches': mismatch,
               'boundary': manifest['boundary']}
    (ROOT / 'scripts/evidence/int3/laya-retrospective.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))
    return result.returncode or int(bool(mismatch))


if __name__ == '__main__':
    raise SystemExit(main())
