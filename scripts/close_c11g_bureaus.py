"""Release only empty, inactive Bureau UUIDs recorded by this task's receipts."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cua_bureau import VirtualDesktopLibrary, _GUID
from grant_agent.cua_guard import ZeroDisturbanceGuard
from run_c11_cohort import write_receipt


def identities(value):
    if isinstance(value, dict):
        if value.get('library') == 'https://github.com/Ciantic/VirtualDesktopAccessor' and value.get('desktopId'):
            yield value['desktopId']
        for child in value.values():
            yield from identities(child)
    elif isinstance(value, list):
        for child in value:
            yield from identities(child)


def run():
    evidence = ROOT / 'scripts/evidence'
    ownership = {}
    for path in sorted(set(evidence.glob('C11g-bureau-*.json')) |
                       set((evidence / 'C11g-runs').glob('*.json'))):
        record = json.loads(path.read_text(encoding='utf-8'))
        # A receipt from another lane/session cannot authorize release.
        if 'desktopBefore' not in record or 'launch' not in record:
            continue
        for identity in identities(record):
            ownership.setdefault(identity, {'receipt': path.relative_to(ROOT).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    guard = ZeroDisturbanceGuard().start()
    library = None
    result = {'schema': 'neyvia.c11g.bureau-cleanup.v1', 'ownedReceiptIds': ownership, 'desktops': [], 'ok': False}
    try:
        area = ROOT / '.agent_control'
        library = VirtualDesktopLibrary(area / 'c11-bureau/VirtualDesktopAccessor.dll', area)
        user = C.WinDLL('user32')
        for identity, proof in ownership.items():
            library.desktop_id = _GUID.from_buffer_copy(uuid.UUID(identity).bytes_le)
            row = {'desktopId': identity, 'ownership': proof, 'cleanup': library.remove(user)}
            result['desktops'].append(row)
        result['ok'] = all(row['cleanup']['removed'] for row in result['desktops'])
    finally:
        if library:
            library.dll.close()
        result['guard'] = guard.close()
        result['ok'] = result['ok'] and result['guard']['ok']
        write_receipt(evidence / 'C11g-bureau-cleanup.json', result)
    print(json.dumps({'ok': result['ok'], 'desktops': result['desktops']}))
    return result['ok']


if __name__ == '__main__':
    raise SystemExit(0 if run() else 2)
