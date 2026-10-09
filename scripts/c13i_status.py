"""Bounded R12 status projection; never scans browser profiles or model streams."""
from pathlib import Path
import ctypes
import json
import sys
REPO=Path(__file__).resolve().parents[1]
RAW=Path('D:/NeyviaRuns/r12')
def read(path):return json.loads(Path(path).read_bytes())
def alive(pid):
    kernel=ctypes.windll.kernel32
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return False
    try:
        status=ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(status))) and status.value==259
    finally:kernel.CloseHandle(handle)
def main():
    names=sys.argv[1:] or ['fusion-T1','fusion-T2','sol-T1','sol-T2','baseline-T2']
    rows=[]
    for name in names:
        file=RAW/(name+'-job.json')
        if not file.exists():continue
        job=read(file)
        logs={}
        for field in ['stdout','stderr']:
            p=Path(job[field])
            logs[field]=p.read_text(encoding='utf-8',errors='replace')[-1200:] if p.exists() else ''
        task=name[-2:]
        arm='baseline' if name.startswith('baseline') else 'fusion-v2' if name.startswith('fusion') else 'luna-alone' if name.startswith('luna') else 'sol-alone'
        summary_path=REPO/'proof/r12'/arm/task/'summary.json'
        row={'job':name,'pid':job['pid'],'running':alive(job['pid']),**logs}
        if summary_path.exists():
            summary=read(summary_path)
            report_path=Path(summary['reportPath'])
            report=read(report_path)
            row['summary']={k:summary.get(k) for k in ['complete','rounds','artifactSha256']}
            row['summary'].update(quality=summary['quality']['quality'],blocks=summary['checks']['blocks'],
                reportFreshForJob=report_path.stat().st_mtime>=job['startedAt'],
                driver=report.get('verificationDriverSha256'),
                coverage=[{'variant':v['viewport']+'-'+v['theme'],'passed':v['passed'],
                    'counts':[v['exercised'],v['discovered']],
                    'failed':[{'id':c['id'],'failed':[m['mode'] for m in c['modes'] if not m.get('effect')],
                        'missing':sorted({'pointer','keyboard','touch'}-{m['mode'] for m in c['modes']})}
                        for c in v['controls'] if c.get('dead') or c.get('undecided')]}
                    for v in report['variants']])
        if row.get('summary') and not row['summary']['reportFreshForJob']:
            row['summary']={'staleForThisJob':True,'quality':row['summary']['quality'],'complete':row['summary']['complete']}
        render_roots=[RAW/arm/task/name/'render' for name in ['final','accepted-current']]
        render_roots += [p/'render' for p in sorted((RAW/arm/task).glob('round-*'),key=lambda p:int(p.name.split('-')[1]))[-2:]]
        captures=[p for folder in render_roots for p in folder.glob('*.png') if p.stat().st_mtime>=job['startedAt']]
        if captures:
            latest=max(captures,key=lambda p:p.stat().st_mtime)
            row['latestCapture']={'name':latest.name,'writtenAtUnix':latest.stat().st_mtime,'captures':len(captures)}
        rows.append(row)
    print(json.dumps(rows))
if __name__=='__main__':main()
