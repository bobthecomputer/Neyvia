"""Execute the authored CL release harness against bounded owned observers."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from grant_agent.cl_skill import Output, _parse_skill, run_checks, receipt_lines

class ReleaseOutput(Output):
    facts = None
    def observe(self, case):
        if case != 'storage': raise ValueError('Unknown release fixture')
        if self.facts is None:
            result = subprocess.run(['node', str(REPO/'scripts/rel_storage_observer.mjs')],
                cwd=REPO, capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode: raise RuntimeError(result.stderr[-2000:])
            self.facts = json.loads(result.stdout)
        return self.facts
    def calls(self):
        return {**super().calls(), 'release.observe': self.observe}

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args(); a.out.mkdir(parents=True, exist_ok=True)
manual = REPO/'manuals/cl/rel-release-harness.cl'
skill = _parse_skill(manual); output = ReleaseOutput([manual], out_dir=a.out)
result = run_checks(skill, output)
result['observations'] = output.facts
(a.out/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(receipt_lines(skill,result))
raise SystemExit(0 if result['status']=='ok' else 1)
