"""Write scripts/evidence/LAYAG-proof.json from grant_agent.laya_glance_proof.run()."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_glance_proof import run  # noqa: E402

report = run()
(ROOT / 'scripts/evidence/LAYAG-proof.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
print(json.dumps({k: ({n: (c['passed'], c['of']) for n, c in v.items()} if k == 'cases' else v) for k, v in report.items()}, indent=1))
