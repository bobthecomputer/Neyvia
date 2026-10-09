"""Import reviewed screenshots once; hold out whole application surfaces before querying.

The review's top-ten summaries repeat detailed findings and are not new episodes.
Broad shell findings apply across surfaces and prevent treating unmentioned states
as clean. Missing/ambiguous image mappings are reported, never invented.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.laya_glance import learn, DOMAIN
from grant_agent.laya_instant import store

PLACEMENTS=('bubble-peek-isolated','side-floating','bubble-peek','dragging','bubble','main','full','side')


def surface(name):
    name=re.sub(r'-(dark|light|night|sunset)-(desktop|phone).*$', '', name)
    name=re.sub(r'-phone$', '', name)
    for p in PLACEMENTS:
        if name.endswith('-'+p):
            return name[:-len(p)-1]
    return name


def findings(directory):
    result=[]
    for part in sorted(directory.glob('part-*.md')):
        heading=''
        for number,line in enumerate(part.read_text(encoding='utf-8-sig').splitlines(),1):
            if line.startswith('## '):heading=line[3:]
            if not re.match(r'^- \*\*P[123]\*\*',line):continue
            result.append({'id':f'{part.stem}:{number}','reason':line,'section':heading,'source':str(part),'line':number})
    return result


def match(row, images):
    text=row['reason'].lower()
    context=(row['section']+' '+text).lower()
    apps=sorted({surface(p.stem) for p in images},key=len,reverse=True)
    named=[app for app in apps if app in context or app.replace('-',' ') in context]
    # Scope by review slice first. Shared shell defects are not clean negatives.
    slices={'part-A':('3d-studio','agent-view','app-factory','app-preview','asset-checks','awareness','browser','cua-preview'),
            'part-B':('files','godot','hill-climb','image-studio','laya'),
            'part-C':('mobile-studio','notes','pdf','playtest','research'),
            'part-D':('scroll-generator','terminal')}
    candidates=[p for p in images if surface(p.stem) in (named or slices[row['id'].split(':')[0]])]
    explicit=[p for p in candidates if p.stem.removesuffix('-phone') in text]
    if explicit:candidates=explicit
    elif 'phone' in text and 'desktop' not in text:candidates=[p for p in candidates if p.stem.endswith('-phone')]
    elif 'desktop' in text and 'phone' not in text:candidates=[p for p in candidates if not p.stem.endswith('-phone')]
    for placement in PLACEMENTS:
        if placement in text and not explicit:
            narrowed=[p for p in candidates if '-'+placement in p.stem]
            if narrowed:candidates=narrowed
            break
    theme=next((t for t in ('light','dark','sunset','night') if t in text), 'dark')
    preferred=[p for p in candidates if p.parent.name==theme]
    return sorted(preferred or candidates)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=REPO)
    p.add_argument('--data',type=Path,default=Path('D:/NeyviaRuns'))
    p.add_argument('--inventory-only',action='store_true')
    a=p.parse_args()
    rows=findings(a.data/'ui-review')
    images=list((a.data/'tour/final-verified-theme').glob('*/*.png'))
    archive=[]
    for row in rows:
        matches=match(row,images)
        archive.append({**row,'screenshot':str(matches[0]) if matches else None,
                        'surface':surface(matches[0].stem) if matches else None,
                        'mapping':'review-scope representative; not a pixel annotation',
                        'candidates':len(matches),'label':'broken'})
    after=[]
    for folder in ('ui-fix','ui-fix2'):
        for image in (a.data/folder).rglob('*.png'):
            top=image.relative_to(a.data/folder).parts[0].lower()
            if not (top.startswith('after-') or top in {'after','img-after'}):continue
            if image.stat().st_size == 0:continue
            after.append({'id':'after:'+str(image.relative_to(a.data)), 'screenshot':str(image),
                          'surface':surface(image.stem),'reason':'Fixed after screenshot supplied by UI fix track; not independently exhaustively reviewed.',
                          'label':'fine','mapping':'fix-track negative'})
    # A surface is assigned before its labels or pixels are consulted.
    for row in archive+after:
        row['split']='holdout' if int(hashlib.sha256(str(row['surface']).encode()).hexdigest()[:8],16)%4==0 else 'train'
    output=REPO/'scripts/evidence/LAYAG-corpus.json'
    output.write_text(json.dumps({'findings':archive,'after':after,'negativePolicy':'No unmentioned-state negatives: shared shell findings cover the screenshot background.'},indent=2),encoding='utf-8')
    summary={'findings':len(rows),'mapped':sum(bool(r['screenshot']) for r in archive),'after':len(after),
             'splits':dict(Counter(r['split'] for r in archive+after)), 'root':str(a.root)}
    if not a.inventory_only:
        local=store(str(a.root))
        learned=0
        with local.import_batch():
            for row in archive+after:
                if not row['screenshot']:continue
                result=learn(a.root,row['screenshot'],row['label'],row['reason'],'LAYAG:'+row['id'],surface=row['surface'],split=row['split'])
                learned+=int(result.get('learned',False))
                if learned and learned%25==0:print(f'Appended {learned} labelled screenshots (pending atomic commit)',flush=True)
        summary['writes']=learned
        summary['episodes']=sum(r['domain']==DOMAIN for r in local.rows)
    print(json.dumps(summary))
    (REPO/'scripts/evidence/LAYAG-ingest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')

if __name__=='__main__':main()
