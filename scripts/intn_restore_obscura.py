"""Recover the source-admitted browser on D without installing a runtime."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import tarfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(r'D:\NeyviaRuns\INTN\obscura-recovery')
LIMIT = 200_000_000
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def download(url, target, expected=None):
    if not target.exists():
        with urllib.request.urlopen(url, timeout=90) as response, target.open('wb') as stream:
            if int(response.headers.get('Content-Length') or 0) > LIMIT:
                raise ValueError('Download exceeds the authorized byte limit')
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > LIMIT:
                    raise ValueError('Download exceeds the authorized byte limit')
                stream.write(chunk)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if expected and actual != expected:
        raise ValueError('Downloaded bytes differ from admitted SHA256')
    return {'url': url, 'path': str(target), 'bytes': target.stat().st_size, 'sha256': actual}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT / 'obscura-0.2.4'
    rows = [download('https://codeload.github.com/h4ckf0r0day/obscura/zip/refs/tags/v0.2.4', OUT / 'v0.2.4.zip')]
    if not source.exists():
        with zipfile.ZipFile(OUT / 'v0.2.4.zip') as archive:
            for member in archive.infolist():
                (OUT / member.filename).resolve().relative_to(OUT.resolve())
            archive.extractall(OUT)
    marker = OUT / 'patches-applied.json'
    if not marker.exists():
        patches = ['obscura-v024-fetch-retention.patch', 'obscura-v024-C2g-capabilities.patch',
                   'obscura-v024-C2g-fragment-render-key.patch', 'obscura-v024-C2h-opacity-cull.patch',
                   'obscura-v024-C2h-websocket.patch']
        for name in patches:
            patch = ROOT / 'scripts' / name
            owned_patch = OUT / name
            owned_patch.write_bytes(patch.read_bytes().replace(b'\r\n', b'\n'))
            reverse = subprocess.run(['git', 'apply', '--reverse', '--check', '--ignore-space-change', str(owned_patch)], cwd=source, capture_output=True, creationflags=HIDDEN)
            if reverse.returncode == 0:
                continue
            subprocess.run(['git', 'apply', '--check', '--ignore-space-change', str(owned_patch)], cwd=source, check=True, creationflags=HIDDEN)
            subprocess.run(['git', 'apply', '--ignore-space-change', str(owned_patch)], cwd=source, check=True, creationflags=HIDDEN)
        marker.write_text(json.dumps(patches), encoding='utf-8')
    admission = json.loads((ROOT / 'scripts/evidence/C2f-v8-simdutf-admission.json').read_text())
    for asset in admission['assets']:
        rows.append(download(asset['source'], OUT / Path(asset['path']).name, asset['sha256']))
    vendor = OUT / 'vendor'
    vendor.mkdir(exist_ok=True)
    registry = Path.home() / '.cargo/registry/src/index.crates.io-1949cf8c6b5b557f'
    crate_cache = Path.home() / '.cargo/registry/cache/index.crates.io-1949cf8c6b5b557f'
    def stage_package(package):
        if not package.get('source', '').startswith('registry+'):
            return
        identity = package['name'] + '-' + package['version']
        destination = vendor / identity
        if (destination / '.cargo-checksum.json').exists():
            return
        cached = registry / identity
        if cached.is_dir() and (cached / '.cargo-checksum.json').is_file():
            import _winapi
            _winapi.CreateJunction(str(cached), str(destination))
            return
        archive = OUT / (identity + '.crate')
        url = 'https://static.crates.io/crates/' + package['name'] + '/' + identity + '.crate'
        cached_archive = crate_cache / (identity + '.crate')
        if cached_archive.is_file():
            if hashlib.sha256(cached_archive.read_bytes()).hexdigest() != package['checksum']:
                raise ValueError('Cached crate differs from the locked checksum')
            archive = cached_archive
        else:
            row = download(url, archive, package['checksum'])
            rows.append(row)
        if sum(item['bytes'] for item in rows) > LIMIT:
            raise ValueError('Recovery aggregate download exceeds the authorized byte limit')
        with tarfile.open(archive) as packed:
            packed.extractall(vendor, filter='data')
        hashes = {str(p.relative_to(destination)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in destination.rglob('*') if p.is_file()}
        (destination / '.cargo-checksum.json').write_text(json.dumps({'package': package['checksum'], 'files': hashes}))
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(stage_package, tomllib.loads((source / 'Cargo.lock').read_text())['package']))
    config = source / '.cargo/config.toml'
    text = config.read_text() if config.exists() else ''
    if '[source.crates-io]' not in text:
        config.write_text(text + '\n[source.crates-io]\nreplace-with = "intn-vendor"\n[source.intn-vendor]\ndirectory = ' + json.dumps(str(vendor)) + '\n')
    (OUT / 'source-recovery.json').write_text(json.dumps({'downloads': rows, 'source': str(source), 'installed': False}, indent=2))
    print(json.dumps({'source': str(source), 'downloadsBytes': sum(row['bytes'] for row in rows)}), flush=True)


if __name__ == '__main__':
    main()
