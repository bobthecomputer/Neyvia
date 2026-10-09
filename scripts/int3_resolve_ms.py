"""Reviewed structural M/S resolution; CL sources supply all manual semantics."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl

def stage(n, path):
    run = subprocess.run(['git', 'show', f':{n}:{path}'], cwd=ROOT, capture_output=True)
    return run.stdout.decode('utf-8').replace('\r\n', '\n') if not run.returncode else None

def merge(base, ours, theirs, at=''):
    if ours == theirs or theirs == base:
        return copy.deepcopy(ours)
    if ours == base:
        return copy.deepcopy(theirs)
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base = base if isinstance(base, dict) else {}
        return {key: merge(base.get(key), ours.get(key), theirs.get(key), at+'/'+key)
                if key in ours and key in theirs else copy.deepcopy((ours if key in ours else theirs)[key])
                for key in dict.fromkeys([*ours, *theirs])}
    if isinstance(ours, list) and isinstance(theirs, list):
        # Facts retain their authored order; independent new guidance is appended.
        # This is semantic chapter data, never source-line conflict resolution.
        result = copy.deepcopy(ours)
        for fact in theirs:
            if fact not in result:
                result.append(copy.deepcopy(fact))
        return result
    if at == '/kind':
        return 'workflow'  # M/S adds executable methods; retained environment chapters remain callable.
    raise ValueError('Needs explicit semantic decision: '+at+' '+repr((base,ours,theirs)))

def main():
    reviews = {}
    files = ['src/grant_agent/desktop_bridge.py', 'src/grant_agent/neyvia_ui_api.py',
             'src/grant_agent/neyvia_workspace_tools.py', 'src/grant_agent/web_backend.py']
    for file in files:
        path = ROOT/file
        text = path.read_text(encoding='utf-8')
        blocks = list(re.finditer(r'^<<<<<<< ours\n(.*?)^=======\n(.*?)^>>>>>>> theirs\n', text, re.M|re.S))
        # Reviewed conflicts: ours retains SDK/Evolver/game-dev/remote guards;
        # M/S Scroll alternatives are identical except quotes. New workflow wiring
        # outside those conflicts remains the true three-way result.
        text = re.sub(r'^<<<<<<< ours\n(.*?)^=======\n(.*?)^>>>>>>> theirs\n', lambda m:m[1], text, flags=re.M|re.S)
        path.write_text(text,encoding='utf-8',newline='\n')
        reviews[file] = {'blocks':len(blocks),'decision':'Retain current SDK, Evolver, workspace affinity and remote behavior; keep nonconflicting M/S wiring.'}
    for file in ['manuals/cl/design.cl','manuals/cl/hill-climb.cl','manuals/cl/scroll-generator.cl']:
        texts = [stage(n,file) for n in (1,2,3)]
        docs = [cl_to_manual(t) if t else {} for t in texts]
        data = merge(*docs)
        metadata = {}
        # Existing mutability is authoritative; M/S's old `none` metadata must
        # never erase the current artifact/external-action approval classes.
        for text in (texts[2],texts[1]):
            header = next(line for line in text.splitlines() if line.startswith('-- @manual '))
            metadata.update(json.loads(header[11:]).get('tool_metadata',{}))
        source = manual_to_cl(data, metadata)
        if cl_to_manual(source) != data: raise ValueError('Roundtrip: '+file)
        (ROOT/file).write_text(source,encoding='utf-8',newline='\n')
        reviews[file] = {'chapters':list(data['chapters']),'decision':'Compiled parent CL documents merged by chapter/schema identity; current approval classes retained.'}
    file='config/neyvia_manuals.json'
    a,b = [json.loads(stage(n,file)) for n in (2,3)]
    rows = {row['id']:row for row in a['manuals']}
    for row in b['manuals']:
        if row['id'] not in rows: rows[row['id']]=row
    for row in rows.values(): row['clSource']='manuals/cl/'+row['id']+'.cl'
    a['manuals']=list(rows.values())
    (ROOT/file).write_text(json.dumps(a,indent=2)+'\n',encoding='utf-8')
    file='.gitattributes'
    rows = {}
    comments=[]
    for n in (2,3):
        for line in stage(n,file).splitlines():
            if not line or line.startswith('#'):
                if n==2: comments.append(line)
                continue
            key=line.split()[0]
            if key not in rows: rows[key]=line
    (ROOT/file).write_text('\n'.join([*comments,*rows.values()])+'\n',encoding='utf-8')
    file='docs/research/results.jsonl'
    rows = {}
    for n in (2,3):
        for line in stage(n,file).splitlines():
            if not line.strip():continue
            row=json.loads(line)
            if row['id'] in rows and rows[row['id']] != row:raise ValueError('Conflicting measurement: '+row['id'])
            rows[row['id']]=row
    (ROOT/file).write_text(''.join(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n' for row in rows.values()),encoding='utf-8')
    from efficiency_log import render
    (ROOT/'docs/research/efficiency-log.md').write_text(render(list(rows.values())),encoding='utf-8')
    # Compiled/generated artifacts are regenerated separately before staging.
    path=ROOT/'scripts/evidence/int3/merge-ms.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(reviews,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'manuals':3,'measurements':len(rows),'reviewed':len(reviews)}))

if __name__=='__main__':main()
