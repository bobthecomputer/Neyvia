"""Repair six owned manual contracts and prove strict grounding on actual registry reads."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
LAYERS=('efficiency','onboarding','tools-depth','dictation','runtime-provider','neyvia')

def references(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in {'$input','$path'}: yield item
            else: yield from references(item)
    elif isinstance(value,list):
        for item in value: yield from references(item)

def repair(layer,registry):
    from grant_agent.cl.manuals import cl_to_manual, _source_lines
    from grant_agent.cl.schema import schema_to_type
    path=REPO/'manuals'/(layer+'.manual.json'); clpath=REPO/'manuals/cl'/(layer+'.cl')
    original=path.read_bytes(); rawsource=clpath.read_bytes(); data=json.loads(original)
    text=rawsource.decode().replace('\r\n','\n')
    if cl_to_manual(text)!=data: raise ValueError(layer+' canonical projection differs before repair')
    lines=text.splitlines(keepends=True)
    header=json.loads(lines[2][len('-- @manual '):]); metadata=header['tool_metadata']
    changes=[]; updated=set(); newtypes=[]; changed_schemas=set()
    for chapter_key,chapter in data['chapters'].items():
        for key,action in chapter['actions'].items():
            live=registry.describe(action['tool'])['inputSchema']
            schema_key=action['schema']
            if data['schemas'][schema_key]!=live:
                old=deepcopy(data['schemas'][schema_key]); data['schemas'][schema_key]=deepcopy(live)
                if schema_key not in changed_schemas:
                    alias='fixcl3_ground_'+str(len(newtypes)+1)
                    header['schemas'][schema_key]=alias
                    newtypes.append('T '+alias+' '+schema_to_type(live)+'\n')
                    changed_schemas.add(schema_key)
                    changes.append({'kind':'exact-live-action-schema','tool':action['tool'],'schema':schema_key,'before':old,'after':live})
        for key,procedure in chapter['procedures'].items():
            before=deepcopy(procedure['inputs'])
            referenced=set(references(procedure['steps']))
            if layer=='neyvia' and key=='set-sidebar-policy':
                live=registry.describe('neyvia.sidebar.policy')['inputSchema']
                procedure['inputs']['properties']['policy']=deepcopy(live['properties']['policy'])
            required=procedure['inputs'].get('required',[])
            declared=procedure['inputs'].get('properties',{})
            if referenced-set(declared): raise ValueError('Unknown procedure input reference')
            procedure['inputs']['required']=required+[key for key in declared if key in referenced and key not in required]
            if procedure['inputs']!=before:
                updated.add((chapter_key,'procedures',key))
                changes.append({'kind':'executable-procedure-inputs','chapter':chapter_key,'procedure':key,'before':before,'after':deepcopy(procedure['inputs'])})
    for chapter_key,chapter in data['chapters'].items():
        for key,action in chapter['actions'].items():
            if action['schema'] in changed_schemas: updated.add((chapter_key,'actions',key))
    if changes:
        output=lines[:2]+['-- @manual '+json.dumps(header,sort_keys=True,separators=(',',':'))+'\n']+newtypes
        index=3
        while index<len(lines):
            line=lines[index]
            if line.startswith('-- @record '):
                record=json.loads(line[len('-- @record '):])
                identity=(record['chapter'],record['section'],record['key'])
                if identity in updated:
                    chapter=data['chapters'][record['chapter']]
                    row=chapter[record['section']][record['key']]
                    record['data']=row
                    # Parameter declaration order affects positional CL calls.
                    # Keep the row's existing order when replacing packed records.
                    output.append('-- @record '+json.dumps(record,separators=(',',':'))+'\n')
                    output.extend(value+'\n' for value in _source_lines(record['section'],record['key'],row,chapter,data['schemas'],layer,metadata,version='1.1'))
                    index+=1
                    while index<len(lines) and not lines[index].startswith(('-- @record ','L ','T ','-- @proof ')): index+=1
                    continue
            output.append(line); index+=1
        text=''.join(output)
        if cl_to_manual(text)!=data: raise ValueError(layer+' repaired source does not reconstruct exact JSON')
        for target,content,raw in ((path,json.dumps(data,indent=2,ensure_ascii=False)+'\n',original),(clpath,text,rawsource)):
            ending='\r\n' if b'\r\n' in raw else '\n'
            target.write_bytes(content.replace('\n',ending).encode())
    return changes

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--repair',action='store_true')
    parser.add_argument('--output',type=Path,default=REPO/'scripts/evidence/FIXCL3-manual-grounding.json')
    args=parser.parse_args()
    if args.port!=48828: parser.error('Metadata proof uses explicit assigned port48828; no listener')
    from fixcl_verify import guards,environment
    root=REPO/'.agent_control/proofs'/('FIXCL3-manual-grounding-'+str(time.time_ns()));root.mkdir(parents=True)
    guards(root);environment(root,args.port);os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_manuals import get_manual,validate,unwrap
    from grant_agent.cl.manuals import cl_to_manual
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace')
    registry=gateway.native
    before={}
    for layer in LAYERS:
        try: before[layer]={'ok':True,'validation':validate(get_manual(layer,root)[2],registry)}
        except Exception as error: before[layer]={'ok':False,'type':type(error).__name__,'error':str(error)}
    changes={layer:repair(layer,registry) for layer in LAYERS} if args.repair else {}
    paths=[Path(__file__),REPO/'src/grant_agent/manual_contracts.py',REPO/'src/grant_agent/neyvia_manuals.py',REPO/'src/grant_agent/native_tools.py']
    paths += [REPO/'manuals'/name for layer in LAYERS for name in (layer+'.manual.json','cl/'+layer+'.cl')]
    hashes=lambda:{path.relative_to(REPO).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    proof={'schema':'neyvia.fixcl3-manual-grounding.v1','root':str(root),'port':args.port,'before':before,'changes':changes,
        'sourceHashesAtStart':hashes(),'checks':{},'validation':{},'nativeReceipts':{},'negativeCases':{},
        'limitations':['This layer proves exact schemas, procedure templating and real registry manual validation. Defining action effects are re-proven by their existing local journey probes after manual source freeze.']}
    checks=proof['checks']
    for layer in LAYERS:
        try:
            record,digest,data=get_manual(layer,root)
            checks[layer+'-lossless-canonical-projection']=cl_to_manual((REPO/record['clSource']).read_text(encoding='utf-8'))==json.loads((REPO/record['path']).read_bytes())
            validation=validate(data,registry)
            proof['validation'][layer]={'sha256':digest,'result':validation}
            checks[layer+'-strict-grounded-validation']=validation['grounded'] is True
            receipt=registry.call('neyvia.manual.validate',{'id':layer})
            proof['nativeReceipts'][layer]=receipt
            result=unwrap(receipt)
            checks[layer+'-actual-native-validation-read']=receipt['ok'] is True and result['manuals']==[validation]
            bad=deepcopy(data)
            if layer=='neyvia':
                entry=bad['chapters']['sessions']['procedures']['set-sidebar-policy']
                entry['inputs']['properties']['policy']={'type':'object'}
            else:
                candidates=[row for chapter in bad['chapters'].values() for row in chapter['procedures'].values()
                    if set(references(row['steps'])) & set(row['inputs'].get('required',[]))]
                entry=candidates[-1]
                key=next(key for key in references(entry['steps']) if key in entry['inputs']['required'])
                entry['inputs']['required'].remove(key)
            try:
                validate(bad,registry); negative={'rejected':False}
            except ValueError as error: negative={'rejected':True,'error':str(error)}
            proof['negativeCases'][layer]=negative
            checks[layer+'-validator-still-rejects-ungrounded-template']=negative['rejected'] is True
            schemas={action['tool']:registry.describe(action['tool'])['inputSchema'] for chapter in data['chapters'].values() for action in chapter['actions'].values()}
            proof['validation'][layer]['actualRegisteredSchemas']=schemas
        except Exception as error:
            proof['validation'][layer]={'error':str(error),'type':type(error).__name__}
            checks[layer+'-complete']=False
        print(json.dumps({'layer':layer,'validation':proof['validation'][layer].get('result'),'error':proof['validation'][layer].get('error')}),flush=True)
    proof['sourceHashesAtEnd']=hashes();checks['source-unchanged-during-validation']=proof['sourceHashesAtStart']==hashes()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':all(checks.values()),'checks':checks,'receipt':str(args.output)}))
    raise SystemExit(0 if all(checks.values()) else 1)

if __name__=='__main__':main()
