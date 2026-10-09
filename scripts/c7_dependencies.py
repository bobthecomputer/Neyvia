"""Explicit, workspace-owned C7 dependencies; never install into System Python."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[1]


def configure():
    value = os.environ.get('NEYVIA_C7_DEPENDENCY_ROOT')
    if not value:
        return None
    root = Path(value).resolve()
    root.relative_to(REPO / '.agent_control/C7e')
    if not (root / 'PIL/__init__.py').is_file():
        raise ValueError('Explicit task Pillow dependency is unavailable')
    sys.path.insert(0, str(root))
    return root


def provision():
    data = tomllib.loads((REPO / 'uv.lock').read_text(encoding='utf8'))
    package = next(p for p in data['package'] if p['name'] == 'pillow')
    wheel = next(w for w in package['wheels'] if 'cp313-cp313-win_amd64.whl' in w['url'])
    if wheel['size'] > 8 * 1024 * 1024:
        raise ValueError('Locked dependency exceeds the reviewed 8 MB limit')
    root = REPO / '.agent_control/C7e'
    root.mkdir(parents=True, exist_ok=True)
    target = root / wheel['url'].rsplit('/', 1)[1]
    if not target.exists():
        with urllib.request.urlopen(wheel['url'], timeout=30) as response:
            raw = response.read(wheel['size'] + 1)
        if len(raw) != wheel['size'] or 'sha256:' + hashlib.sha256(raw).hexdigest() != wheel['hash']:
            raise ValueError('Locked wheel bytes differ; no substitute is permitted')
        target.write_bytes(raw)
    if 'sha256:' + hashlib.sha256(target.read_bytes()).hexdigest() != wheel['hash']:
        raise ValueError('Saved wheel differs from the lock')
    destination = root / 'dependencies'
    with zipfile.ZipFile(target) as archive:
        for info in archive.infolist():
            path = (destination / info.filename).resolve()
            path.relative_to(destination.resolve())
            if info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('Wheel symlinks are not admitted')
        archive.extractall(destination)
    os.environ['NEYVIA_C7_DEPENDENCY_ROOT'] = str(destination)
    configure()
    from PIL import Image, __version__
    if __version__ != package['version']:
        raise ValueError('Loaded Pillow differs from the exact lock')
    Image.new('RGB', (16, 16)).save(root / 'dependency-check.png')
    report = {'schema': 'neyvia.c7e-dependency.v1', 'ok': True, 'package': 'pillow', 'version': __version__,
              'bytes': target.stat().st_size, 'sha256': wheel['hash'].split(':')[1], 'wheel': target.relative_to(REPO).as_posix(),
              'dependencyRoot': str(destination), 'systemInstalled': False, 'lockedWheelVerified': True}
    (REPO / 'scripts/evidence/C7e-dependency.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    provision()
