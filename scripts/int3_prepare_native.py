"""Prepare the exact small upstream binary required by the existing B proof."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/syncthing/syncthing/releases/download/v2.1.5/syncthing-windows-amd64-v2.1.5.zip'
ARCHIVE_SHA = '39571e4d0900c2a2cab14c0b170f49751340a869e49734ccc8079d9b98a7974b'
EXECUTABLE_SHA = '36a0f7bc372f64fa7cc4f5654fa324c0dd9f7fef2e07565e00c6e1cf73f50344'


def main():
    base = ROOT/'.agent_control/proofs-b/native-syncthing'
    base.mkdir(parents=True, exist_ok=True)
    archive = base/'syncthing-windows-amd64-v2.1.5.zip'
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            assert int(response.headers['Content-Length']) == 11975789
            data = response.read(11975790)
        assert len(data) == 11975789 and hashlib.sha256(data).hexdigest() == ARCHIVE_SHA
        archive.write_bytes(data)
    data = archive.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ARCHIVE_SHA
    name = 'syncthing-windows-amd64-v2.1.5/syncthing.exe'
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        binary = package.read(name)
    assert hashlib.sha256(binary).hexdigest() == EXECUTABLE_SHA
    executable = base/name
    executable.parent.mkdir(parents=True, exist_ok=True)
    if executable.exists():
        assert executable.read_bytes() == binary
    else:
        executable.write_bytes(binary)
    receipt = {'source':URL, 'archiveBytes':len(data), 'archiveSha256':ARCHIVE_SHA,
               'executableBytes':len(binary), 'executableSha256':EXECUTABLE_SHA,
               'executable':executable.relative_to(ROOT).as_posix(),
               'boundary':'Verified task-local dependency; no installation, service startup, credentials or remote sync.'}
    (ROOT/'scripts/evidence/int3/native-preparation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
