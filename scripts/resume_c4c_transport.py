"""Repeat both arms of the lock-interrupted pair; re-review repaired metadata."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from run_c4c import frozen,ARTIFACTS
def main():
    original=REPO/'.agent_control/c4/c4c-frozen-terminal'
    assert (original/'collection-recovery.json').is_file()
    base,freeze=frozen('c4c-transport-repairs')
    def run_arm(item):
        arm,port=item
        command=[sys.executable,str(REPO/'scripts/run_c4c.py'),'--job','--run-id',base.name,
                 '--task','t1-ui','--rep','1','--arm',arm,'--port',str(port),'--budget','8000','--max-turns','24']
        completed=subprocess.run(command,cwd=REPO,**hidden_windows_subprocess_kwargs())
        assert completed.returncode==0
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run_arm,[('efficient',48731),('control',48732)]))
    for task_id,rep in [('hc2-dates',1),('t4-browse',2)]:
        task=next(t for t in freeze['tasks'] if t['id']==task_id)
        for arm in ('efficient','control'):
            source=original/f'rep-{rep}'/arm/task_id;dest=base/f'rep-{rep}'/arm/task_id
            dest.mkdir(parents=True,exist_ok=False);(dest/'workspace').mkdir()
            row=json.loads((source/'result.json').read_text(encoding='utf-8'))
            row['reviewInputSource']={'path':(source/'result.json').relative_to(REPO).as_posix(),
                'sha256':hashlib.sha256((source/'result.json').read_bytes()).hexdigest(),
                'scope':'Artifact/grade copy for review only; no model execution trial'}
            (dest/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
            (dest/'.review-only').write_text('No execution trial; existing artifact copy for corrected blinded review',encoding='utf-8')
            for name in task.get('files') or ARTIFACTS[task_id]:
                candidate=source/'workspace'/name
                if candidate.is_file():shutil.copy2(candidate,dest/'workspace'/name)
    result=subprocess.run([sys.executable,str(REPO/'scripts/judge_c4c.py'),'--run-id',base.name,'--workers','2'],cwd=REPO,**hidden_windows_subprocess_kwargs())
    assert result.returncode==0
    replacements={'trials':{'t1-ui/1':{arm:(base/'rep-1'/arm/'t1-ui/result.json').relative_to(REPO).as_posix() for arm in ('efficient','control')}},
        'reviews':{name:(base/'judges'/name/'result.json').relative_to(REPO).as_posix() for name in ('1-t1-ui','1-hc2-dates','2-t4-browse')},
        'reason':'Windows byte-lock read interrupted t1 control before acceptance. Repeat both arms once; use no successful-only selection. Other two deadline failures retain their model traces with restored metadata and identical checks. Re-review all three affected pairs.',
        'excludedOriginalTrials':[{'task':'t1-ui','repetition':1,'arm':arm,'receipt':(original/'rep-1'/arm/'t1-ui/result.json').relative_to(REPO).as_posix()} for arm in ('efficient','control')]}
    for path in replacements['reviews'].values():assert (REPO/path).is_file()
    (original/'pair-replacements.json').write_text(json.dumps(replacements,indent=2),encoding='utf-8')
    print(json.dumps(replacements,indent=2))
if __name__=='__main__':main()
