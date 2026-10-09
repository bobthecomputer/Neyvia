"""Fast CL gate outcomes and migrated configuration authority cases."""
from dataclasses import replace
import json
from pathlib import Path
import time

CONTRACTS = ("p22.impact", "p22.uncovered", "p22.permission-validation", "p22.laya-advisory")


def glance_ports(root):
    import socket
    from .laya_glance_gate import request_ports
    from .proof_ports import proof_port
    from .browser_ports import parse_ports
    allocated=(proof_port(48461),proof_port(48462))
    if parse_ports(f'{allocated[0]}-{allocated[1]}')!=set(allocated):
        raise ValueError('Browser port range changed the caller allocation')
    request={'assignedPorts':list(allocated),'ports':{'backend':allocated[0],'engine':allocated[1]}}
    ports=request_ports(request)
    with socket.socket() as observer:
        observer.bind(('127.0.0.1',ports[0]))
        observer.listen(1)
        with socket.create_connection(('127.0.0.1',ports[0]),timeout=1) as client:
            peer,_=observer.accept()
            with peer:
                client.sendall(b'caller-owned-glance')
                received=peer.recv(64)
    if ports!=allocated or received!=b'caller-owned-glance':
        raise ValueError('Glance changed the caller allocation or lost its local observation')
    for bad in [{'assignedPorts':[47881,allocated[1]]},
                {'assignedPorts':[allocated[0],allocated[0]]},
                {'assignedPorts':list(allocated),'ports':[allocated[1],allocated[0]]}]:
        try:request_ports(bad)
        except ValueError:pass
        else:raise ValueError('Glance accepted conflicting or unowned socket authority')
    for bad in ([47881,allocated[0]],[True,allocated[0]],'49089-49081'):
        try:parse_ports(bad)
        except ValueError:pass
        else:raise ValueError('Browser accepted public, noninteger or reversed port authority')
    return {'ports':list(ports),'received':received.decode(),'conflictingAndPublicPortsRefused':True}


def asyncio_wakeup(root):
    import asyncio
    from .proof_ports import configure_asyncio, selected_ports, ALLOWED_ENV
    import os
    async def observe():
        loop=asyncio.get_running_loop()
        event=asyncio.Event()
        loop.call_soon_threadsafe(event.set)
        await asyncio.wait_for(event.wait(),1)
        return loop._ssock.getsockname()[1]
    port=asyncio.run(observe())
    admitted = json.loads(os.environ[ALLOWED_ENV]) if ALLOWED_ENV in os.environ else list(set(selected_ports().values()))
    if port not in admitted:
        raise ValueError('Asyncio wake-up used a port outside the worker allocation')
    try:configure_asyncio([47881,49085])
    except ValueError:pass
    else:raise ValueError('Asyncio accepted a public or undeclared wake-up port')
    return {'crossThreadSignalDelivered':True,'wakeUpPort':port,'publicPortRefused':True}


def coverage_model(root):
    from .contract_coverage import model, uncovered_by_module, classify, SymbolOwners
    repo=Path(__file__).resolve().parents[2]
    root=Path(root); (root/'config').mkdir(parents=True,exist_ok=True)
    policy=json.loads((repo/'config/contract_path_policy.json').read_text(encoding='utf-8'))
    (root/'config/contract_path_policy.json').write_text(json.dumps(policy),encoding='utf-8')
    modules=[{'id':'owned','files':['src/owned.py','src/companion.py'],'dependencies':[],
              'contracts':['owned.outcome','modules.verify-map']},
             {'id':'unproved','files':['src/unproved.py'],'dependencies':['owned'],'contracts':['modules.verify-map']}]
    (root/'config/neyvia.modules.json').write_text(json.dumps({'modules':modules}),encoding='utf-8')
    paths=['scripts/evidence/history.json','docs/design.md','src/companion.py','src/unproved.py',
           'config/neyvia.modules.json','unclassified.extension']
    result=model(root,paths,{'owned.outcome':{'checkedAt':['src/owned.py'],'impact':[]},
                           'modules.verify-map':{'checkedAt':[],'impact':[]}},lambda ref:{ref})
    if result['outcomes']['owned'] != {'owned.outcome'} or result['outcomes']['unproved']:
        raise ValueError('Module map sentinel gained outcome coverage or the companion lost its module outcome')
    if result['origins']['config/neyvia.modules.json'] != 'scripts/generate_module_map.py':
        raise ValueError('Generated output lost its generator obligation')
    if result['classes']['scripts/evidence/history.json']['kind'] != 'no behaviour':
        raise ValueError('Recorded evidence gained a behavior obligation')
    if result['classes']['unclassified.extension']['kind'] != 'unknown':
        raise ValueError('Unknown content was silently exempted')
    groups=uncovered_by_module(['src/unproved.py','unclassified.extension'],result['classes'],result['owners'])
    if groups.get('unproved') != ['src/unproved.py'] or 'unmapped:.' not in groups:
        raise ValueError('Uncovered code lost module provenance')
    for path in ['../outside.py','C:/outside.py','/absolute.py']:
        if classify(path,policy)['kind'] != 'unknown':raise ValueError('Non-repository path was admitted')
    source=root/'src/grant_agent'; source.mkdir(parents=True)
    (source/'facade.py').write_text('from .implementation import execute as run\nfrom .implementation import Mixin\nfrom .unrelated import Other\nclass Facade(Mixin, Other):\n    pass\n',encoding='utf-8')
    (source/'implementation.py').write_text('def execute():\n    return "observed"\nclass Mixin:\n    def read(self):\n        return "observed"\n',encoding='utf-8')
    (source/'unrelated.py').write_text('class Other:\n    def other(self):\n        return "unrelated"\n',encoding='utf-8')
    files={str(path.relative_to(root).as_posix()) for path in source.glob('*.py')}
    resolver=SymbolOwners(root,files)
    expected={'src/grant_agent/facade.py','src/grant_agent/implementation.py'}
    if resolver.sites('grant_agent.facade.run') != expected or resolver.sites('facade.Facade.read') != expected:
        raise ValueError('Named reexport or inherited method lost its exact implementation owner')
    if resolver.sites('facade.Facade.missing') or resolver.sites('facade.run') & {'src/grant_agent/unrelated.py'}:
        raise ValueError('An unrelated import or nonexistent method gained coverage')
    if classify('scripts/new_campaign.py',policy)['kind'] != 'behaviour':
        raise ValueError('An undeclared new script inherited an offline exemption')
    # An actual Git move supplies provenance; an edited rewrite supplies none.
    import subprocess
    from unittest.mock import patch
    from . import contract_gate as gate
    fixture=root/'rename-source';(fixture/'src').mkdir(parents=True)
    def commit_git(*arguments):
        return subprocess.check_output(['git','-c','user.name=P22 fixture','-c','user.email=p22@invalid',
            '-c','commit.gpgsign=false',*arguments],cwd=fixture,text=True,encoding='utf-8').strip()
    commit_git('init','-q')
    (fixture/'src/old.py').write_text('def read():\n    return "kept"\n',encoding='utf-8')
    (fixture/'src/rewrite.py').write_text('old behavior\n',encoding='utf-8')
    commit_git('add','.');commit_git('commit','-qm','baseline')
    base=commit_git('rev-parse','HEAD')
    (fixture/'src/old.py').rename(fixture/'src/companion.py')
    (fixture/'src/rewrite.py').rename(fixture/'src/changed.py')
    (fixture/'src/changed.py').write_text('new behavior\n',encoding='utf-8')
    commit_git('add','.');commit_git('commit','-qm','move and rewrite')
    with patch.object(gate,'REPO',fixture):renames=gate.exact_renames(base)
    if renames!={'src/old.py':'src/companion.py'}:
        raise ValueError('Exact move provenance was lost or a changed rewrite was admitted')
    (root/'src/companion.py').write_text('Observed current owner',encoding='utf-8')
    moved=model(root,['src/old.py'],{'owned.outcome':{'checkedAt':['src/owned.py'],'impact':[]}},
                lambda ref:{ref},renames=renames)
    if (moved['origins']['src/old.py']!='src/companion.py' or not moved['outcomes']['owned']
            or uncovered_by_module(['src/old.py'],moved['classes'],moved['owners'])!={'owned':['src/old.py']}):
        raise ValueError('Moved code lost its actual current module or outcome obligation')
    return {'moduleOutcomeInherited':True,'sentinelCannotCoverCode':True,'generatedObligationPreserved':True,
            'evidenceExempt':True,'unknownUncovered':True,'uncoveredGrouped':True,'namedImplementationResolved':True,
            'newScriptsNotExempt':True,'exactMoveUsesCurrentOwner':True,'rewritesNeverWaived':True}


def module_discovery(root):
    from types import SimpleNamespace
    from . import neyvia_modules as modules
    service=SimpleNamespace(bus=SimpleNamespace(root=Path(root)))
    identity='backend.module_map'
    found=modules.call(service,'modules.list',{'query':identity})
    if found['total'] != 1 or found['modules'][0]['id'] != identity:
        raise ValueError('Generated module ownership did not reach exact module search')
    owner=modules.call(service,'modules.get',{'id':identity})['module']
    path='src/grant_agent/module_map.py'
    if path not in owner['files'] or not owner['enabled'] or 'p22.module-discovery' not in owner['outcomeContracts']:
        raise ValueError('Generated owner lost its source or availability')
    source=modules.call(service,'modules.source',{'id':identity,'path':path})
    if 'def generate' not in source['text']:
        raise ValueError('Module discovery returned unrelated source content')
    try: modules.call(service,'modules.source',{'id':identity,'path':'src/grant_agent/neyvia_agent.py'})
    except ValueError: pass
    else: raise ValueError('Module source reader admitted another owner')
    return {'searchFoundExactOwner':True,'sourceContentReturned':True,'unrelatedSourceRefused':True}


def _gate_and_authority(root):
    from .contract_gate import select, assigned_ports, output_root, laya_admitted
    from .neyvia_agent import NeyviaAgentConfig
    started = time.perf_counter()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    selected = select(["web/src/neyvia/next/nxPdfModel.js", "src/grant_agent/p22_unmapped.py"])
    if not {"pdf.page", "pdf.search", "pdf.zoom", "pdf.text-geometry"} <= selected["contracts"].keys():
        raise ValueError("Real PDF module change lost its authored outcome contracts")
    if selected["uncovered"] != ["src/grant_agent/p22_unmapped.py"]:
        raise ValueError("A covered neighbour hid an uncovered change")
    archive = [f'scripts/evidence/p22-archive/{index}.json' for index in range(10000)]
    with_archive = select([*archive, 'web/src/neyvia/next/nxPdfModel.js', 'src/grant_agent/p22_unmapped.py'])
    if with_archive['contracts'].keys() != selected['contracts'].keys() or with_archive['uncovered'] != selected['uncovered']:
        raise ValueError('A large evidence archive changed product coverage or hid an unmapped source')
    grants = ("neyvia.notes.write", "neyvia.notes.pin")
    original = NeyviaAgentConfig(root=root, session_id="p22-validation", allow_mutations=True, native_mutation_tools=grants)
    first = original.validated()
    if first.native_mutation_tools != grants or first.validated() is not first or first.validated().native_mutation_tools != grants:
        raise ValueError("Repeated validation changed inferred mutation grants")
    capped = replace(original, permission_mode="workspace").validated()
    if capped.native_mutation_tools != () or capped.validated().native_mutation_tools != ():
        raise ValueError("Workspace cap acquired mutation grants")
    if replace(first, permission_mode="read-only").validated().allow_mutations:
        raise ValueError("Read-only copy retained mutation authority")
    try:
        replace(first, max_turns=0).validated()
    except ValueError as error:
        if "max_turns" not in str(error):
            raise
    else:
        raise ValueError("Invalid turn budget was accepted")
    assigned_ports((48887, 48888))
    for ports in ((47881, 48888), (48887, 48887), (49090, 49091)):
        try:
            assigned_ports(ports)
        except ValueError:
            pass
        else:
            raise ValueError('Gate accepted unassigned or duplicate ports')
    output_root('D:/NeyviaRuns/P22/contract-fixture')
    try:
        output_root(Path(__file__).resolve().parents[2] / '.agent_control/p22/forbidden-build')
    except ValueError:
        pass
    else:
        raise ValueError('Gate accepted build output outside D:/NeyviaRuns')
    unavailable = {'status': 'not available', 'ok': False}
    if laya_admitted(unavailable) or not laya_admitted(unavailable, True) or laya_admitted({'status': 'failed', 'ok': False}, True):
        raise ValueError('LAYA pending policy admitted a failed hook or silently waived an unavailable hook')
    observed = []
    for status in ('not available', 'failed', 'uncertain'):
        result = {'status': status, 'ok': False, 'findings': [{'verdict': 'looks broken', 'reason': 'policy fixture'}]}
        before = json.dumps(result, sort_keys=True)
        strict = laya_admitted(result)
        advisory = laya_admitted(result, advisory=True)
        if strict or not advisory or laya_admitted(result, advisory='true'):
            raise ValueError('Glance findings blocked explicit advisory policy or silently enabled it')
        if json.dumps(result, sort_keys=True) != before:
            raise ValueError('Advisory policy changed or erased the observed findings')
        observed.append({'status': status, 'strict': strict, 'advisory': advisory, 'findingsPreserved': True})
    report = {"ok": True, "contracts": list(CONTRACTS), "checks": [
        {"contract": "p22.impact", "outcome": "four real PDF model contracts selected"},
        {"contract": "p22.uncovered", "outcome": "unmapped neighbour explicitly refused"},
        {"contract": "p22.permission-validation", "outcome": "all three migrated authority cases preserve or reduce grants"},
        {"contract": "p22.laya-advisory", "outcome": "explicit advisory policy retains unavailable, failed and uncertain findings; strict defaults still refuse", "observed": observed}],
        "elapsedMs": round((time.perf_counter() - started) * 1000)}
    (root / "fast-contracts.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def self_check(root):
    from .contract_gate import wants
    from .proofs_runtime_edges import budget, releases, workspace, codex_threads, oauth_owner, plan_hold
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();cases=[]
    for name,identities,action in [('glance-ports',('p22.glance-ports',),glance_ports),
                                  ('asyncio-wakeup',('p22.asyncio-wakeup',),asyncio_wakeup),
                                  ('coverage-model',('p22.coverage-model',),coverage_model),
                                  ('module-discovery',('p22.module-discovery',),module_discovery),
                                  ('selection-and-authority',CONTRACTS,_gate_and_authority),
                                  ('runtime-budget',('p22.runtime-budget',),budget),
                                  ('release-parsing',('p22.release-parsing',),releases),
                                  ('workspace-selection',('p22.workspace-selection',),workspace),
                                  ('codex-threads',('p22.codex-threads',),codex_threads),
                                  ('oauth-owner',('p22.oauth-owner',),oauth_owner),
                                  ('plan-hold',('p22.plan-hold',),plan_hold)]:
        if not wants(identities):continue
        try:
            details=action(root/name)
            cases.append({'id':name,'contracts':list(identities),'ok':True,'observed':details})
        except Exception as error:
            cases.append({'id':name,'contracts':list(identities),'ok':False,'error':str(error)})
    report={'ok':bool(cases) and all(case['ok'] for case in cases),'cases':cases,
            'contracts':sorted({identity for case in cases if case['ok'] for identity in case['contracts']}),
            'durationMs':round((time.perf_counter()-started)*1000)}
    (root/'fast-contracts.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
