"""Check rendered CL text in existing scored receipts; never regrade runs."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
rows = []
for path in sorted((ROOT/'.agent_control/cl11/scored-2').glob('task-*/*/b/rep-*/result.json')):
    run = json.loads(path.read_text(encoding='utf-8'))
    for index, action in enumerate(run['actions']):
        rendered = (action.get('result') or {}).get('text', '')
        matches = re.findall(r'\[id=\d+\b', rendered)
        if matches:
            rows.append({'resultPath':path.relative_to(ROOT).as_posix(),
                         'resultSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'actionIndex':index, 'proposal':action.get('proposal'),
                         'renderedTextSha256':hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
                         'bracketedNativeIds':len(matches)})
receipt = {'cohort':'scored-2', 'allPassed':not rows,
           'checks':{'rendered_bracketed_native_ids_hidden':not rows},
           'affectedActions':len(rows),
           'affectedRuns':len({r['resultPath'] for r in rows}),
           'scope':'Existing rendered model text only. The earlier space-prefixed id check misses [id=...] native tree metadata. Frozen runtime and benchmark outcomes are unchanged; transport-field refusal is a separate property.',
           'findings':rows}
(ROOT/'scripts/evidence/CL11-projection-review.json').write_text(
    json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:v for k,v in receipt.items() if k!='findings'}))
