"""Explicit R2 resolution retains LAYA stores and adds the Paul-intent run domain."""
import json
from int3_resolve_ms import ROOT, stage

def main():
    file='src/grant_agent/neyvia_evolver.py'
    source=stage(2,file)
    old='RUN_DOMAINS = ("manual_compression", "cl_skill", "manual_compression_v2", "cl_skill_v2", "cl_skill_v3")'
    assert source.count(old)==1
    source=source.replace(old,old[:-1]+', "paul_intent")')
    (ROOT/file).write_text(source,encoding='utf-8')
    file='scripts/run_t13_evolution.py'
    (ROOT/file).write_text(stage(3,file),encoding='utf-8')
    file='.gitattributes'
    rows={}
    comments=[]
    for n in (2,3):
        for line in stage(n,file).splitlines():
            if not line or line.startswith('#'):
                if n==2:comments.append(line)
                continue
            if line.split()[0] not in rows:rows[line.split()[0]]=line
    (ROOT/file).write_text('\n'.join([*comments,*rows.values()])+'\n',encoding='utf-8')
    file='docs/research/results.jsonl'
    rows={}
    for n in (2,3):
        for line in stage(n,file).splitlines():
            if not line.strip():continue
            row=json.loads(line)
            if row['id'] in rows and rows[row['id']] != row:raise ValueError('Different measured row: '+row['id'])
            rows[row['id']]=row
    (ROOT/file).write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows.values()),encoding='utf-8')
    from efficiency_log import render
    (ROOT/'docs/research/efficiency-log.md').write_text(render(list(rows.values())),encoding='utf-8')
    out=ROOT/'scripts/evidence/int3/merge-r2.json'
    out.write_text(json.dumps({'retained':'LAYA per-domain stores and existing run guards',
                              'added':'paul_intent run domain and worker route', 'measurementRows':len(rows)},indent=2)+'\n')

if __name__=='__main__':main()
