"""Real native host refusal journey; guards remain active through final receipt."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cua_native_procedures import NativeApplications
from run_c11_cohort import write_receipt

runtime = NativeApplications(ROOT / '.agent_control/c11g-native-refusal' / uuid.uuid4().hex)
opened = runtime.open({'app': 'Command Prompt'})
identity = opened['sessionId']
row = {'schema': 'neyvia.c11g.native-refusal.v1', 'at': datetime.now(timezone.utc).isoformat(),
    'app': 'Command Prompt', 'opened': opened, 'refusedBeforeDispatch': False,
    'sourceSha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'src/grant_agent/cua_native_procedures.py', 'src/grant_agent/cua_guard.py',
        'src/grant_agent/native_tools.py', 'manuals/native-applications.manual.json',
        'scripts/prove_c11g_native_failure.py')}}
try:
    try:
        runtime.edit({'sessionId': identity, 'value': 'unsafe & exit'})
    except ValueError as exc:
        row['refusedBeforeDispatch'] = not runtime.sessions[identity]['processes']
        row['error'] = str(exc)
    marker = 'Recovered disposable note ' + identity
    row['recoveredEdit'] = runtime.edit({'sessionId': identity, 'value': marker})
    row['recoveredPersistence'] = runtime.persist({'sessionId': identity})
    row['recoveredCheck'] = runtime.observe({'sessionId': identity, 'expected': marker, 'persisted': True})
finally:
    row['close'] = runtime.close({'sessionId': identity})
row['sourceDrift'] = [name for name, sha in row['sourceSha256'].items()
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha]
row['ok'] = row['refusedBeforeDispatch'] and row['recoveredCheck']['ok'] and row['close']['ok'] and not row['sourceDrift']
write_receipt(ROOT / 'scripts/evidence/C11g-apps-native-refusal.json', row)
print(json.dumps({'ok': row['ok'], 'guardOk': row['close']['guard']['ok']}))
raise SystemExit(0 if row['ok'] else 2)
