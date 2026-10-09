"""Revalidate captured production licenses after non-production manifest edits.

Retain original wheel metadata and export provenance. This does not claim a
fresh CPython 3.12 install or cover optional dependency groups.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.dependency_inventory import DependencyInventory


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    capture_path = ROOT / 'scripts/evidence/FOLLOW-license-python-metadata.json'
    evidence_path = ROOT / 'config/neyvia_dependency_license_evidence.json'
    original_bytes = capture_path.read_bytes()
    capture = json.loads(original_bytes)
    baseline_bytes = subprocess.check_output(['git','show',args.baseline_ref + ':pyproject.toml'], cwd=ROOT)
    variants = [baseline_bytes, baseline_bytes.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')]
    if not any(digest(raw) == capture['pyprojectSha256'] for raw in variants):
        raise ValueError('Historical manifest does not match the original capture')
    current_bytes = (ROOT / 'pyproject.toml').read_bytes()
    baseline = tomllib.loads(baseline_bytes.decode())
    current = tomllib.loads(current_bytes.decode())
    for key in ('name','version','dependencies','requires-python'):
        if baseline['project'].get(key) != current['project'].get(key):
            raise ValueError('Production manifest changed: ' + key)
    if baseline.get('tool',{}).get('uv') != current.get('tool',{}).get('uv'):
        raise ValueError('Resolution configuration changed')
    if digest((ROOT / 'uv.lock').read_bytes()) != capture['uvLockSha256']:
        raise ValueError('Captured lockfile changed')
    raw_export = args.export.read_bytes()
    selected = DependencyInventory._target_requirements(raw_export.decode())
    if selected != DependencyInventory._target_requirements(capture['rawLockedExport']):
        raise ValueError('Frozen production target projection differs from the captured export')
    provenance = {
        'kind':'unchanged-production-projection', 'baselineRef':args.baseline_ref,
        'originalManifestSha256':capture['pyprojectSha256'],
        'originalCaptureSha256':digest(original_bytes),
        'currentManifestSha256':digest(current_bytes),
        'frozenExportSha256':digest(raw_export), 'productionPackageCount':len(selected),
        'scope':'Windows CPython 3.12 production only; original wheel metadata retained',
        'optionalGroupsNotCovered':sorted(current['project'].get('optional-dependencies',{})),
        'lockedResolutionRecheck':'unavailable offline; frozen unchanged lock projection checked',
    }
    if args.apply:
        capture['pyprojectSha256'] = digest(current_bytes)
        capture['sourceRevalidation'] = provenance
        capture_path.write_text(json.dumps(capture,indent=2) + '\n',encoding='utf-8')
        evidence = json.loads(evidence_path.read_text())
        evidence['python']['pyprojectSha256'] = capture['pyprojectSha256']
        evidence['python']['metadataCaptureSha256'] = digest(capture_path.read_bytes())
        evidence_path.write_text(json.dumps(evidence,indent=2) + '\n',encoding='utf-8')
        inventory = DependencyInventory(ROOT)
        inventory.write(args.receipt.with_name('inventory.json'))
        inventory.verify_written(args.receipt.with_name('inventory.json'),require_critical_resolved=True)
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps({'ok':True,'applied':args.apply,**provenance},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'applied':args.apply,'productionPackageCount':len(selected)}))


if __name__ == '__main__':
    main()
