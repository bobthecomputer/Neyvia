"""Resolve proof-share catalog/generated joins from preserved authored sources."""
import argparse
import json
from pathlib import Path
import subprocess
from int3_resolve_ms import ROOT, stage

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--through',required=True,choices=list('abcde'))
    args=parser.parse_args()
    unresolved=subprocess.check_output(['git','diff','--name-only','--diff-filter=U'],cwd=ROOT,text=True).splitlines()
    if '.gitattributes' in unresolved:
        rows={};comments=[]
        for n in (2,3):
            for line in stage(n,'.gitattributes').splitlines():
                if not line or line.startswith('#'):
                    if n==2:comments.append(line)
                    continue
                rows.setdefault(line.split()[0],line)
        (ROOT/'.gitattributes').write_text('\n'.join([*comments,*rows.values()])+'\n')
    file='config/neyvia_manuals.json'
    if file in unresolved:
        a,b=[json.loads(stage(n,file)) for n in (2,3)]
        entries={row['id']:row for row in a['manuals']}
        for row in b['manuals']:entries.setdefault(row['id'],row)
        a['manuals']=list(entries.values())
    else:a=json.loads((ROOT/file).read_text())
    for row in a['manuals']:row['clSource']='manuals/cl/'+row['id']+'.cl'
    (ROOT/file).write_text(json.dumps(a,indent=2)+'\n')
    # These are generated, never authored conflict inputs. Temporarily restore
    # retained views so the renderer can run; compilation replaces them below.
    generated=[file for file in unresolved if file.startswith(('manuals/','docs/manuals/','plugins/neyvia/skills/'))]
    for file in generated:
        previous=stage(2,file)
        if previous is not None:(ROOT/file).write_text(previous,encoding='utf-8')
    from int3_contracts import main as contract_main
    original=list(__import__('sys').argv)
    for mode in ('merge-map','port-contracts'):
        __import__('sys').argv=['int3_contracts.py',mode,'--through',args.through,'--write',
                              '--receipt',str(ROOT/f'scripts/evidence/int3/checks/0{5+"abcde".index(args.through)}-proofs-{args.through}/{mode}.json')]
        contract_main()
    __import__('sys').argv=original
    print(json.dumps({'through':args.through,'generatedInputsDiscarded':len(generated),'manuals':len(a['manuals'])}))

if __name__=='__main__':main()
