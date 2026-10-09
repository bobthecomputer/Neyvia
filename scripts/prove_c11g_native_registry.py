"""Exercise the actual registered native tool surface with retained tool receipts."""
from pathlib import Path
import hashlib
import json
import sys
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import unwrap
from run_c11_cohort import write_receipt

area = ROOT / '.agent_control/c11g-native-registry' / uuid.uuid4().hex
registry = NativeToolRegistry(area, nas_root=area / '.unused-local')
receipt = {'schema': 'neyvia.c11g.native-registry.v1', 'calls': [],
    'sourceSha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'src/grant_agent/cua_native_procedures.py', 'src/grant_agent/cua_guard.py',
        'src/grant_agent/native_tools.py', 'manuals/native-applications.manual.json',
        'scripts/prove_c11g_native_registry.py')}}
def call(operation, args):
    result = registry.call('neyvia.nativeapp.' + operation, args)
    receipt['calls'].append(result)
    return unwrap(result)

identity = None
try:
    identity = call('open', {'app': 'Command Prompt'})['sessionId']
    marker = 'Registry owned note ' + identity
    call('edit', {'sessionId': identity, 'value': marker})
    call('persist', {'sessionId': identity})
    call('observe', {'sessionId': identity, 'expected': marker, 'persisted': True})
finally:
    if identity:
        call('close', {'sessionId': identity})
receipt['sourceDrift'] = [name for name, sha in receipt['sourceSha256'].items()
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha]
receipt['ok'] = len(receipt['calls']) == 5 and all(row['ok'] for row in receipt['calls']) and not receipt['sourceDrift']
write_receipt(ROOT / 'scripts/evidence/C11g-apps-native-registry.json', receipt)
print(json.dumps({'ok': receipt['ok'], 'registeredCallsCompleted': len(receipt['calls'])}))
raise SystemExit(0 if receipt['ok'] else 2)
