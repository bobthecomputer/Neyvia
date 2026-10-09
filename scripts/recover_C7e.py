"""Preserve inherited C7d observations without promoting diagnostics to proof."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    entries = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard', '-z', 'scripts/evidence/C7d*'], cwd=REPO, capture_output=True, check=True).stdout.decode().split('\0')
    entries = sorted({p for p in entries if p} | {'scripts/evidence/C7d-native-completion.json'})
    archive = REPO / 'scripts/evidence/C7e-recovered.zip'
    manifest = []
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer:
        for name in entries:
            path = (REPO / name).resolve()
            path.relative_to(REPO / 'scripts/evidence')
            raw = path.read_bytes()
            classification = 'historical observation; no current proof claim'
            if path.suffix == '.json':
                value = json.loads(raw)
                bindings = value.get('sourceBindings', {}) if isinstance(value, dict) else {}
                current = bool(bindings) and all(sha((REPO / p).read_text(encoding='utf8').encode()) == digest for p, digest in bindings.items())
                classification = 'current source-bound observation' if current else classification
                if isinstance(value, dict) and (value.get('ok') is False or any(r.get('status') == 'failed' for r in value.get('rows', []) if isinstance(r, dict))):
                    classification = 'failure diagnostic; never passing proof'
            manifest.append({'path': name, 'sha256': sha(raw), 'bytes': len(raw), 'classification': classification})
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            writer.writestr(info, raw)
        writer.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')))
    with zipfile.ZipFile(archive) as reader:
        for row in manifest:
            if sha(reader.read(row['path'])) != row['sha256']:
                raise ValueError('Recovery archive differs: ' + row['path'])
    fresh = REPO / 'scripts/evidence/C7e-native-completion.json'
    value = json.loads(fresh.read_bytes())
    if not value['ok'] or not value['sourceStable'] or value['passedPairs'] != 106:
        raise ValueError('Native completion rerun did not pass')
    (REPO / 'scripts/evidence/C7d-native-completion.json').write_bytes(fresh.read_bytes())
    report = {'schema': 'neyvia.c7e-recovery.v1', 'ok': True, 'explicitPort': args.port,
              'archive': {'path': archive.relative_to(REPO).as_posix(), 'sha256': sha(archive.read_bytes()), 'bytes': archive.stat().st_size},
              'files': len(manifest), 'uncompressedBytes': sum(r['bytes'] for r in manifest),
              'manifest': 'manifest.json', 'allRecoveredBytesVerified': True,
              'nativeCompletion': {'path': fresh.relative_to(REPO).as_posix(), 'sha256': sha(fresh.read_bytes()), 'passedPairs': 106},
              'boundary': 'Historical observations retained separately; no diagnostic, archive hash or model result supplies rendered proof.'}
    (REPO / 'scripts/evidence/C7e-recovery.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
