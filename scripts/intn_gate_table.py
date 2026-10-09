"""Render the release gate table from its single JSON record; never infer a pass."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'scripts/evidence/INTN-gates.json'
record = json.loads(source.read_text(encoding='utf-8'))
rows = ['# Release gate table', '', 'Local candidate only. Overall release gate: **' + ('PASS' if record['releaseGate'] else 'FAIL') + '**.', '',
        '| Gate | Result | Observed scope or remaining requirement | Receipt |', '| --- | --- | --- | --- |']
for name, gate in record['gates'].items():
    receipt = gate['receipt']
    target = Path(receipt) if Path(receipt).is_absolute() else ROOT / receipt
    detail = gate.get('scope', gate.get('reason', '')).replace('|','\\|').replace('\n',' ')
    rows.append('| ' + name + ' | ' + gate['status'] + ' | ' + detail + ' | [receipt](<' + target.as_posix() + '>) |')
(source.parent/'INTN-gates.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
print(json.dumps({'rows':len(record['gates']),'releaseGate':record['releaseGate']}))
