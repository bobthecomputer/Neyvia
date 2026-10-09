"""Recover first-cohort display after the nullable native-result renderer error.

No runtime source, frozen input, task outcome, or recorded metric is changed.
"""
from pathlib import Path
import inspect
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl import benchmark11 as benchmark

cohort = REPO / '.agent_control/cl11/scored-1'
manifest = json.loads((cohort / 'manifest.json').read_text(encoding='utf-8'))
benchmark.ensure_frozen(manifest)
results = [json.loads(path.read_text(encoding='utf-8'))
           for path in sorted(cohort.glob('task-*/*/*/rep-*/result.json'))]
summary = benchmark.summarize(manifest, results)
benchmark._write(cohort / 'summary.json', {**summary, 'runs': results})
source = inspect.getsource(benchmark.render_report)
old = 'a.get("result", {}).get("text", "")'
assert source.count(old) == 1
exec(compile(source.replace(old, '(a.get("result") or {}).get("text", "")'),
             '<nullable-result display repair>', 'exec'), benchmark.__dict__)
report = benchmark.render_report(manifest, results, summary)
report += ('\n## Display recovery\n\nThe original renderer stopped at a native action with a null result. '
           'This report was rebuilt from unchanged raw results using a display-only null guard. '
           'The original execution continued and saved individual receipts.\n')
for path in (cohort / 'report.md', REPO / 'docs/evidence/cl-benchmark-1.1.md'):
    path.write_text(report, encoding='utf-8', newline='\n')
print(json.dumps({'completed': len(results), 'gates': summary['gates']}))
