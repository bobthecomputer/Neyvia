"""Bind changed integration source bytes without rewriting historical run outcomes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl

def digest(path,lf=False):
    data=path.read_bytes()
    return hashlib.sha256(data.replace(b'\r\n',b'\n') if lf else data).hexdigest()

def main():
    path=ROOT/'manuals/cl/design.cl'
    source=path.read_text(encoding='utf-8')
    data=cl_to_manual(source)
    fact=("Morning uses canopy light on warm paper #f5f1e6, forest ink #17221a, deep leaf #245a35 and mid leaf #3a774b. "
          "One low sun at top-left lights selected rows and cards (#fffdf9/white); green-grey --nx-shade falls down-right. "
          "The moss-paper sidebar shades #ebe9da to #dfe5d1; leaf light pools bottom-right. Sun warmth and komorebi appear only during activity. "
          "Running text uses ochre #7a4f08; bright amber stays in dots and fills. Check text contrast at 4.5:1 or better. "
          "The App SDK template, details kit and Scroll Study share this recipe; source: docs/NEYVIA_BRAND.md, R3 Morning.")
    if fact not in data['chapters']['tokens-themes']['guidance']:
        data['chapters']['tokens-themes']['guidance'].append(fact)
        metadata=json.loads(next(line[11:] for line in source.splitlines() if line.startswith('-- @manual ')))['tool_metadata']
        source=manual_to_cl(data,metadata)
        assert cl_to_manual(source)==data
        path.write_text(source,encoding='utf-8')
    changes={}
    for file,key,lf in [('A1.json','implementationHashesLF',True),('A3B.json','sourceHashes',False)]:
        path=ROOT/'scripts/evidence'/file
        value=json.loads(path.read_text(encoding='utf-8'))
        before={}
        for relative,old in value[key].items():
            target=(ROOT/relative).resolve()
            if not target.is_relative_to(ROOT):raise ValueError('Non-workspace source binding: '+relative)
            if not target.is_file():raise ValueError('Missing bound source: '+relative)
            new=digest(target,lf)
            if old!=new:
                before[relative]=old
                value[key][relative]=new
        value.setdefault('integrationReseals',[]).append({'task':'INT3','at':datetime.now(timezone.utc).isoformat(),
                'priorChangedHashes':before,'boundary':'Current integration source binding; historical run results/fixtures retained. Fresh INT3 proof is separate.'})
        path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        changes[file]=list(before)
    out=ROOT/'scripts/evidence/int3/r3-reseal.json'
    out.write_text(json.dumps({'changedBindings':changes,'r3VersionSelected':[
        'apps/scroll-study/www/styles.css','config/app_sdk/web/index.html',
        'web/src/neyvia/next/details/kit/demo.html','web/src/neyvia/next/details/kit/details.css'],
        'newRenderedProof':False,'browserInventory':{'apps':[],'browsers':[]}},indent=2)+'\n')
    print(json.dumps({file:len(rows) for file,rows in changes.items()}))

if __name__=='__main__':main()
