"""Inventory every authored CL proof/check and retained Python case without pytest."""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def write_audit(path,report):
    def encode(value):return json.dumps(value,separators=(',',':'))
    fields=[]
    for key,value in report.items():
        rendered='[\n'+',\n'.join(encode(row) for row in value)+'\n]' if key in {'contracts','pythonFiles'} else encode(value)
        fields.append(encode(key)+':'+rendered)
    path.write_text('{\n'+',\n'.join(fields)+'\n}\n',encoding='utf-8')


def classify(manual, chapter, identity, row):
    text = json.dumps(row)
    if manual.startswith("C7") or "edge" in manual:
        return "edge-case", "Generated C7 family; substantive outcome assertions remain in the owning builder"
    expect = row.get("expect", {})
    raw_path = expect.get("path", "")
    path = json.dumps(raw_path)
    if expect.get("op") in {"exists", "not_null", "truthy"} and not raw_path or expect.get("op") == "schema" and expect.get("schema") == {"not": {"type": "null"}}:
        return "vacuous", "Object existence does not establish a user outcome"
    if any(term in path.lower() for term in ("sha256", "hash", "digest")):
        if manual == 'cross-pc' and isinstance(expect.get('value'),dict):
            return 'edge-case', 'Fresh delivered-byte integrity compared with the actual input; retain the transport boundary'
        return "vacuous", "Digest-only obligation"
    if row.get("tool") == "workspace.read":
        target = str(row.get("args", {}).get("path", ""))
        if target.startswith(("scripts/evidence/", "docs/evidence/", "proof/")) or target.endswith((".jsx", ".js", ".css", ".py", ".cl", ".json")):
            return "vacuous", "Saved receipt, source text or fixture alone is not a fresh observed outcome"
    if expect.get("op") == "exists" or expect.get("value") is None and expect.get("op") in {"ne", "neq"}:
        return "vacuous", "Existence-only obligation"
    schema = expect.get('schema', {})
    if expect.get('op') == 'schema' and schema and set(schema) <= {'type', 'minItems'}:
        return 'vacuous', 'A type or minimum list size alone does not establish the requested behaviour'
    return "outcome", "Value/effect comparison; candidate classification requires the runner to observe the claimed behaviour"


def audit(snapshot=None):
    from grant_agent.cl.manuals import cl_to_manual
    rows = []
    authored = []
    for path in sorted((REPO / "manuals/cl").glob("*.cl")):
        source = path.read_text(encoding="utf-8")
        if '-- @manual ' not in source:
            for number, line in enumerate(source.splitlines(), 1):
                if line.startswith('C '):
                    rows.append({"manual": path.stem, "id": str(number), "kind": "check", "classification": "outcome", "claim": line, "reason": "CL skill judgement, validated separately by cl_compile_manuals"})
            continue
        manual = cl_to_manual(source)
        header = json.loads(next(line[len('-- @manual '):] for line in source.splitlines() if line.startswith('-- @manual ')))
        authored.append({"data": manual, "metadata": header['tool_metadata']})
        for chapter, data in manual["chapters"].items():
            for identity, check in data["checks"].items():
                kind, reason = classify(manual["id"], chapter, identity, check)
                rows.append({"manual": manual["id"], "chapter": chapter, "id": identity, "kind": "check", "classification": kind, "reason": reason, "tool": check["tool"], "expect": check["expect"]})
        for proof in manual.get("proofs", {}).get("contracts", []):
            kind = "edge-case" if manual["id"].startswith("C7") or any("edge_fixture" in site or 'proofs_runtime_edges' in site for site in proof["checkedAt"]) else "outcome"
            rows.append({"manual": manual["id"], "id": proof["id"], "kind": "proof", "classification": kind, "checkedAt": proof["checkedAt"], "claim": proof["claim"]})
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    old = {row["path"]: row for row in inventory["files"]}
    files = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        relative = path.relative_to(REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        cases=[]
        def collect(node,parents=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child.name.startswith('test_'):
                    cases.append('.'.join((*parents,child.name)))
                else:collect(child,(*parents,child.name) if isinstance(child,ast.ClassDef) else parents)
        collect(tree)
        mapped = old.get(relative, {})
        files.append({"path": relative, "cases": cases, "mappedCases": [{key:case.get(key) for key in ['name','contract_ids','checked_at','self_checks']} for case in mapped.get("cases", [])], "disposition": mapped.get("disposition", "unmapped")})
    if snapshot:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(authored), encoding='utf-8')
    return {"schema": "neyvia.p22-contract-audit.v1", "manuals": len(list((REPO / "manuals/cl").glob("*.cl"))),
            "counts": dict(Counter(row["classification"] for row in rows)), "proofs": sum(row["kind"] == "proof" for row in rows),
            "checks": sum(row["kind"] == "check" for row in rows), "pytestFiles": len(files), "contracts": rows, "pythonFiles": files,
            "boundary": "All CL records inventoried; outcome is a value/effect comparison candidate, not fresh runtime proof. Historical test mappings do not authorize deletion."}


def rewrite(snapshot):
    """Regenerate only from the previously verified authored records."""
    from copy import deepcopy
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    rows = json.loads(snapshot.read_text(encoding='utf-8'))
    workspace = next(row['data'] for row in rows if row['data']['id'] == 'workspace')
    terminal = next(chapter['actions'][key] for chapter in workspace['chapters'].values() for key in chapter['actions'] if chapter['actions'][key]['tool'] == 'terminal.exec')
    for row in rows:
        data = row['data']
        if data['id'] == 'pdf':
            chapter = data['chapters']['overview']
            for key, path, value in [('canvas-not-blank','outcome.nonBlank',True), ('text-layer-ready','outcome.textLayerPresent',True), ('fresh-page','fresh',True)]:
                chapter['checks'][key] = {'tool':'neyvia.pdf.state','args':{},'expect':{'op':'eq','path':path,'value':value}}
            chapter['checks']['text-layer-phrase'] = {'tool':'neyvia.pdf.state','args':{},'expect':{'op':'contains','path':'outcome.text','value':{'$input':'phrase'}}}
            chapter['procedures']['verify-rendered-page'] = {'goal':'The current mounted page has real ink and the requested phrase in its selectable text layer',
                'inputs':{'type':'object','properties':{'phrase':{'type':'string','minLength':1}},'required':['phrase'],'additionalProperties':False},
                'steps':[{'action':'pdf.state','args':{},'check':key,'save':'observed'+str(index)} for index,key in enumerate(['fresh-page','canvas-not-blank','text-layer-ready','text-layer-phrase'])]}
        if data['id'] == 'design':
            schema = {'type':'object','properties':{},'additionalProperties':False}
            data['schemas']['neyvia.view.state'] = schema
            row['metadata']['neyvia.view.state'] = {'mutability_class':'read'}
            chapter = {key:{} for key in ['state','actions','checks','procedures','judge']}
            chapter.update(title='Fast mounted surface outcomes',pitfalls=[],frontier=[],guidance=[])
            chapter['actions']['observe'] = {'tool':'neyvia.view.state','schema':'neyvia.view.state','pre':'The owned shell is mounted','effect':'Read current rendered surface observations','returns':{'type':'object'},'reversible':True}
            for key,field in [('panels-opaque','panelsOpaque'),('chips-unclipped','chipsUnclipped'),('visible-copy-clean','copyClean')]:
                chapter['checks'][key] = {'tool':'neyvia.view.state','args':{},'expect':{'op':'eq','path':'state.dom.outcomes.'+field,'value':True}}
                chapter['procedures']['verify-'+key] = {'goal':key,'inputs':schema,'steps':[{'action':'observe','args':{},'check':key,'save':'observed'}]}
            chapter['checks']['fresh'] = {'tool':'neyvia.view.state','args':{},'expect':{'op':'eq','path':'state.fresh','value':True}}
            for procedure in chapter['procedures'].values(): procedure['steps'].insert(0,{'action':'observe','args':{},'check':'fresh','save':'fresh'})
            data['chapters']['fast-outcomes'] = chapter
        if data['id'] == 'proofs':
            ids = ['p22.impact','p22.uncovered','p22.permission-validation']
            declarations = [{'id':identity,'phase':'post','claim':claim,'checkedAt':sites,'impact':['Fast contract gate and configuration authority']} for identity,claim,sites in [
                ('p22.impact','Changed source selects its authored outcome contracts through real dependency edges',['grant_agent.contract_gate.select','scripts/gate.py','scripts/cl_compile_manuals.py']),
                ('p22.uncovered','A covered neighbour never hides an unmapped changed source',['grant_agent.contract_gate.select','scripts/p22_contract_audit.py']),
                ('p22.permission-validation','Repeated configuration validation never increases the callers mutation authority',['grant_agent.neyvia_agent.NeyviaAgentConfig.validated','grant_agent.proofs_fast_contracts.self_check'])]]
            data['proofs']['contracts'].extend(declarations)
            (REPO/'config/proofs/fast-contracts.json').write_text(json.dumps({'area':'fast-contracts','module':'grant_agent.proofs_fast_contracts','self_check':'self_check','contracts':declarations,'coverage':[]},indent=2)+'\n',encoding='utf-8')
            data['schemas']['terminal.exec'] = deepcopy(workspace['schemas'][terminal['schema']])
            row['metadata']['terminal.exec'] = {'mutability_class':'external_action'}
            chapter = {key:{} for key in ['state','actions','checks','procedures','judge']}
            chapter.update(title='Fast impact gate',pitfalls=[],frontier=['LAYA glance is owned by the separate LAYA session; missing is not a pass.'],guidance=['Run gate.py --since the last accepted release. No full suite or tour is needed.'])
            chapter['actions']['run'] = deepcopy(terminal)
            chapter['actions']['run']['schema'] = 'terminal.exec'
            chapter['checks']['outcomes'] = {'tool':'workspace.read','args':{'path':'.agent_control/p22/cl-cases/fast-contracts/state/fast-contracts.json','maxChars':10000},'expect':{'op':'schema','path':'content','schema':{'type':'string','pattern':'"ok"\\s*:\\s*true'}}}
            # Reuse the grounded read schema from the release-integration chapter.
            read = next(action for ch in data['chapters'].values() for action in ch['actions'].values() if action['tool']=='workspace.read')
            chapter['actions']['read'] = deepcopy(read)
            chapter['procedures']['verify-fast-cases'] = {'goal':'Run current impact and authority outcome witnesses, then inspect their new receipt','inputs':{'type':'object','properties':{},'additionalProperties':False},'steps':[
                {'action':'run','args':{'command':'& '+repr(str(Path(sys.executable)))+' scripts/gate.py --since HEAD --paths src/grant_agent/proofs_fast_contracts.py --skip-build --root .agent_control/p22/cl-cases','cwd':str(REPO),'shell':'powershell','timeoutMs':60000,'maxOutputChars':1000},'save':'ran'},
                {'action':'read','args':{'path':'.agent_control/p22/cl-cases/fast-contracts/state/fast-contracts.json','maxChars':10000},'save':'observed','check':'outcomes'}]}
            data['chapters']['fast-contracts'] = chapter
        source = manual_to_cl(data, tool_metadata=row['metadata'])
        if cl_to_manual(source) != data: raise ValueError('CL rewrite changed typed record: '+data['id'])
        (REPO/'manuals/cl'/ (data['id']+'.cl')).write_text(source,encoding='utf-8',newline='\n')
        (REPO/'manuals'/ (data['id']+'.manual.json')).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')


def retire_vacuous():
    """Retire stale receipts; retain fresh byte integrity and replace live stops/setup."""
    import re
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    design_source=(REPO/'manuals/cl/design.cl').read_text(encoding='utf-8')
    design_header=json.loads(next(line[11:] for line in design_source.splitlines() if line.startswith('-- @manual ')))
    view_schema=cl_to_manual(design_source)['schemas']['neyvia.view.state']
    changes=[]
    for path in sorted((REPO/'manuals/cl').glob('*.cl')):
        old=path.read_bytes(); source=old.decode('utf-8')
        if '-- @manual ' not in source:continue
        data=cl_to_manual(source);header=json.loads(next(line[11:] for line in source.splitlines() if line.startswith('-- @manual ')))
        changed=False
        for name,chapter in data['chapters'].items():
            removed=set()
            for identity,row in list(chapter['checks'].items()):
                kind,reason=classify(data['id'],name,identity,row)
                if kind!='vacuous':continue
                if data['id']=='autopilot' and identity=='autopilot-stop-observed':
                    row['expect']={'op':'eq','path':'run.status','value':'stopped'}
                    operation='rewrite: actual stopped run'
                elif data['id']=='settings' and identity=='setup-requested':
                    data['schemas']['neyvia.view.state']=view_schema
                    header['tool_metadata']['neyvia.view.state']=design_header['tool_metadata']['neyvia.view.state']
                    row.update(tool='neyvia.view.state',args={},expect={'op':'schema','path':'state','schema':{
                        'type':'object','required':['fresh','dom'],'properties':{'fresh':{'const':True},'dom':{
                            'type':'object','required':['setup'],'properties':{'setup':{'type':'object','required':['mounted'],'properties':{'mounted':{'const':True}}}}}}}})
                    operation='rewrite: mounted setup'
                else:
                    chapter['checks'].pop(identity);removed.add(identity);operation='delete'
                changes.append({'manual':data['id'],'chapter':name,'check':identity,'operation':operation,'reason':reason});changed=True
            for identity,procedure in list(chapter['procedures'].items()):
                if not any(step.get('check') in removed for step in procedure['steps']):continue
                retained=[step.get('check') for step in procedure['steps'] if step.get('check') and step.get('check') not in removed]
                if not retained:
                    chapter['procedures'].pop(identity)
                    changes.append({'manual':data['id'],'chapter':name,'procedure':identity,'operation':'delete','reason':'No fresh outcome remains'})
                else:
                    for step in procedure['steps']:
                        if step.get('check') in removed:step.pop('check')
        if not changed:continue
        generated=manual_to_cl(data,tool_metadata=header['tool_metadata']);chunks=generated.split('\nL ');prefix=chunks[0];sections={}
        for chunk in chunks[1:]:
            ident=chunk.split(' ',1)[0]
            if ident==data['id']:prefix+='\nL '+chunk
            else:sections[ident]=chunk
        order=re.findall(r'^L ('+re.escape(data['id'])+r'\.[\w-]+) v',source,re.M)
        generated=prefix+''.join('\nL '+sections[key] for key in order)
        newline='\r\n' if old.count(b'\r\n')>old.count(b'\n')/2 else '\n'
        path.write_bytes(generated.replace('\r\n','\n').replace('\n',newline).encode('utf-8'))
        artifact=REPO/'manuals'/(data['id']+'.manual.json');previous=artifact.read_bytes()
        def ordered(now,old):
            if isinstance(now,dict) and isinstance(old,dict):return {key:ordered(now[key],old.get(key)) for key in [*old,*[key for key in now if key not in old]] if key in now}
            return now
        text=json.dumps(ordered(data,json.loads(previous)),indent=2,ensure_ascii=False)+ ('\n' if previous.endswith(b'\n') else '')
        artifact.write_bytes(text.replace('\n','\r\n' if previous.count(b'\r\n')>previous.count(b'\n')/2 else '\n').encode('utf-8'))
    ledger=REPO/'scripts/evidence/P22-retired-checks.json'
    previous=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else []
    known={(row.get('manual'),row.get('chapter'),row.get('check'),row.get('procedure')) for row in previous}
    previous.extend(row for row in changes if (row.get('manual'),row.get('chapter'),row.get('check'),row.get('procedure')) not in known)
    ledger.write_text(json.dumps(previous,indent=2)+'\n',encoding='utf-8')
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "scripts/evidence/P22-contract-audit.json")
    parser.add_argument("--snapshot", type=Path, help="Preserve source-decoded records for reviewed CL projection repair")
    parser.add_argument("--rewrite-snapshot", type=Path)
    parser.add_argument('--retire-vacuous',action='store_true')
    args = parser.parse_args()
    if args.rewrite_snapshot:
        rewrite(args.rewrite_snapshot)
    if args.retire_vacuous:
        retire_vacuous()
    report = audit(args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # One record per line keeps the complete audit reviewable without repeating
    # eighty thousand lines of historical receipt metadata.
    write_audit(args.output,report)
    print(json.dumps({key: report[key] for key in ("manuals", "counts", "proofs", "checks", "pytestFiles")}))
