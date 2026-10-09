"""Seal independently inspectable FIXCL receipts without promoting their scope."""
from __future__ import annotations
import hashlib
import json
import argparse
from pathlib import Path
import subprocess

REPO=Path(__file__).resolve().parents[1]
EVIDENCE=REPO/'scripts/evidence'
AUDIT=Path(r'C:\Users\user\Projects\nx-audit4\scripts\evidence\AUD4.json')


def read(name):
    return json.loads((EVIDENCE/name).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def layer_receipts():
    """Bind each owning-layer commit to successful real native and MCP actions."""
    sources = ['FIXCL-transports-sealed.json', 'FIXCL-transports-supplemental.json', 'FIXCL-host-frozen.json', 'FIXCL-recycle.json']
    proofs = {name: read(name) for name in sources}
    witnesses = {'native': [], 'MCP': []}
    def collect(value, receipt, pointer, transport):
        if isinstance(value, dict):
            use = value.get('manualUse')
            if value.get('ok') is True and isinstance(use, dict) and any(check.startswith('effect-') for check in use.get('checkIds', [])):
                witnesses[transport].append({'receipt': receipt, 'pointer': pointer + '/manualUse', 'use': use})
            for key, child in value.items():
                collect(child, receipt, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'), transport)
        elif isinstance(value, list):
            for n, child in enumerate(value):
                collect(child, receipt, pointer + '/' + str(n), transport)
    for name, proof in proofs.items():
        if not all(proof['checks'].values()): raise ValueError('Unpassed proof: ' + name)
        collect(proof['transcripts'], name, '/transcripts', 'native')
        if 'spawnedMCP' in proof:
            collect(proof['spawnedMCP'], name, '/spawnedMCP', 'MCP')
        if 'stdio' in proof:
            collect(proof['stdio'], name, '/stdio', 'MCP')
        # Compiled procedures return step checks, not each step's full action
        # envelope. Bind their real manual-use bus events to the successful
        # fixture identity and fresh completion in the actual transport reply.
        for case in proof.get('selectedCases', []):
            for transport, key, identity in (('native', 'layer_'+case, 'fixture-'+case+':'),
                                             ('MCP', 'mcp_layer_'+case, 'mcp-fixture-'+case+':')):
                value = proof['transcripts'].get(key, {}).get('value', {})
                suffix = ''
                if transport == 'MCP':
                    value = value.get('result', {}).get('structuredContent', {})
                    suffix = '/result/structuredContent'
                if value.get('ok') is not True or value.get('doneStatus') != 'ok': continue
                for ordinal, use in enumerate(proof.get('manualUses', [])):
                    if use['actionIdentity'].startswith(identity) and any(check.startswith('effect-') for check in use.get('checkIds', [])):
                        witnesses[transport].append({'receipt':name, 'pointer':'/manualUses/'+str(ordinal), 'use':use,
                            'completionPointer':'/transcripts/'+key+'/value'+suffix})
    mapping = {'notes':16, 'files':17, 'workspace':18, 'tools-depth':18, 'image-studio':23,
               'outputs':0, 'settings':34, 'neyvia':8, 'transparency':8,
               'neyvia-reference':33, 'awareness':33, 'agents':33, 'app-sdk':7}
    baseline = json.loads(AUDIT.read_text(encoding='utf-8'))
    for layer, matrix_index in mapping.items():
        source = REPO / 'manuals/cl' / (layer + '.cl')
        digest = sha(source)
        effect_digest = sha(REPO/'src/grant_agent/cl/effects.py')
        selected = {transport: [row for row in rows if row['use']['manual'] == layer and row['use']['sourceSha256'] == digest and row['use']['effectSourceSha256'] == effect_digest] for transport, rows in witnesses.items()}
        if any(not rows for rows in selected.values()): raise ValueError('Missing real layer transport: ' + layer)
        selected = {transport: list({row['use']['usageId']:row for row in rows}.values()) for transport, rows in selected.items()}
        receipt = {'schema':'neyvia.FIXCL.layer.v1', 'layer':layer,
                   'status':'native_and_MCP_verified_HTTP_readonly_frontier',
                   'sourceSha256':digest, 'artifactSha256':sha(REPO/'manuals'/(layer+'.manual.json')),
                   'before':baseline['matrix'][matrix_index],
                   'after':{'manualUse':'Exact current owning source and applicable procedure bound per successful action',
                            'effects':'Host-bound fresh subject predicates checked after action and at done',
                            'semanticState':'Authored typed scalar/reference rows and bounded projections'},
                   'successfulActionWitnesses':selected,
                   'proofSha256':{name:sha(EVIDENCE/name) for name in sources},
                   'httpPluginBoundary':'Existing read-only scope verified by transport receipts; this layer has no proved HTTP mutation grant.'}
        (EVIDENCE/('FIXCL-layer-'+layer+'.json')).write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'layers':len(mapping),'nativeAndMCPWitnesses':{key:len(rows) for key,rows in witnesses.items()}}))


def main():
    baseline=json.loads(AUDIT.read_text(encoding='utf-8'))
    primary=['FIXCL-transports-sealed.json','FIXCL-transports-supplemental.json',
             'FIXCL-host-frozen.json','FIXCL-negative.json','FIXCL-cold-process.json',
             'FIXCL-codec-invariants.json','FIXCL-manual-compile-final.json','FIXCL-manual-preservation.json','FIXCL-recycle.json']
    proofs={name:read(name) for name in primary}
    for name,proof in proofs.items():
        checks=proof.get('checks',{})
        if isinstance(checks,dict) and not all(checks.values()):
            raise ValueError('Unpassed receipt: '+name+' '+str([key for key,value in checks.items() if not value]))
        if proof.get('ok') is False or proof.get('equal') is False:
            raise ValueError('Unpassed receipt: '+name)
    host=proofs['FIXCL-host-frozen.json']
    transport=proofs['FIXCL-transports-sealed.json']
    supplement=proofs['FIXCL-transports-supplemental.json']
    assert host['backendStopped'] and transport['transportsBackendStopped'] and supplement['transportsBackendStopped']
    for proof, count in ((transport, 12), (supplement, 8)):
        assert len(proof['selectedCases']) == count and len(proof['spawnedMCP']) == count
        assert all(child['exitCode'] == 0 for child in proof['spawnedMCP'].values())
        assert proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    assert all(row['n'] >= 5 for row in proofs['FIXCL-cold-process.json']['latency'].values())
    for row in proofs['FIXCL-manual-compile-final.json']['results']:
        assert row['equal'], row['id']
        # The compiler hashes decoded text with normalized newlines; owning
        # action receipts and the Git-byte receipt separately bind raw bytes.
        text_digest=hashlib.sha256(Path(row['source']).read_text(encoding='utf-8').encode()).hexdigest()
        assert text_digest == row['source_sha256'], row['id']
    for row in proofs['FIXCL-manual-preservation.json']['manuals']:
        assert row['preservesExistingCanonicalCLRecords'], row['manual']
        assert sha(REPO/'manuals/cl'/(row['manual']+'.cl')) == row['sourceSha256'], row['manual']
    product={str(p.relative_to(REPO)).replace('\\','/'):sha(p) for p in (REPO/'src/grant_agent/cl').glob('*.py')}
    product['src/grant_agent/neyvia_impact.py']=sha(REPO/'src/grant_agent/neyvia_impact.py')
    for name in ('FIXCL-transports-sealed.json','FIXCL-transports-supplemental.json','FIXCL-host-frozen.json','FIXCL-cold-process.json','FIXCL-recycle.json'):
        proof=proofs[name]
        hashes=proof.get('sourceHashesAtStart',proof.get('sourceHashes',{}))
        for path,digest in hashes.items():
            path=path.replace('\\','/')
            if sha(REPO/path)!=digest:
                raise ValueError('Source byte drift: '+name+' '+path)
    inventory=supplement.get('effectInventory',[])
    if not inventory: raise ValueError('Current action inventory missing')
    statuses={status:sum(row['effectStatus']==status for row in inventory) for status in ('grounded_adapter','read_only','frontier')}
    layers=[json.loads(path.read_text(encoding='utf-8')) for path in EVIDENCE.glob('FIXCL-layer-*.json')]
    assert len(layers) == 13
    exercised=sorted({row['use']['tool'].removeprefix('neyvia.') for layer in layers
                      for rows in layer['successfulActionWitnesses'].values() for row in rows})
    unexercised=sorted({row['tool'].removeprefix('neyvia.') for row in inventory
                       if row['effectStatus']=='grounded_adapter'} - set(exercised))
    # Each named row retains the original audit cells. Only its observed boundary
    # is advanced: a request, empty state or durable preference is not a renderer.
    updates={
      0:({0:'G',1:'G',2:'G',4:'G'},'Notes bytes/pin, fresh effect completion, stale/manual/unchecked refusal; admission and procedure percentiles measured','FIXCL-host-frozen.json'),
      2:({0:'G',1:'G',2:'G',4:'G'},'Actual spawned JSON-RPC processes exercise eleven effect journeys with exact fixture readback and one strict setup-frontier refusal','FIXCL-transports-sealed.json'),
      3:({0:'G',1:'A',2:'A',4:'G'},'Nine real typed HTTP/plugin observations plus false-goal/scope/mutation refusals; existing read-only gateway preserved','FIXCL-transports-sealed.json'),
      7:({0:'G',1:'A',2:'G',4:'A'},'Real generation and web build compare fresh source/artifact hashes; running rendered reducer action remains unproved','FIXCL-transports-sealed.json'),
      8:({0:'G',1:'A',2:'G',4:'R'},'Durable theme/layout/ambient/transparency preferences observed; unchecked pane actions refused; renderer acknowledgement unproved','FIXCL-transports-supplemental.json'),
      16:({0:'G',1:'G',2:'G',4:'G'},'Real Notes write/pin/folder, exact bytes, manual action receipts and adverse fresh completion','FIXCL-host-frozen.json'),
      17:({0:'G',1:'G',2:'G',4:'G'},'Actual move/mkdir/trash/undo conserve exact bytes; Recycle Bin restoration and changed-restoration refusal exercised through CL and MCP','FIXCL-recycle.json'),
      18:({0:'G',1:'G',2:'G',4:'G'},'Actual hash-checked patch and write; source bytes checked through CL and spawned MCP','FIXCL-transports-supplemental.json'),
      21:({0:'G',1:'A',2:'A',4:'A'},'Real bounded file observation in semantic rows; other perception layers unproved','FIXCL-host-frozen.json'),
      22:({0:'G',1:'A',2:'A',4:'A'},'Real empty PDF state projected; PDF open/read/highlight journey and effect observer remain frontier','FIXCL-host-frozen.json'),
      23:({0:'G',1:'G',2:'G',4:'G'},'Pixel crop and approved export conserve source, compare dimensions and exported bytes; provider generation unproved','FIXCL-transports-sealed.json'),
      24:({0:'G',1:'R',2:'A',4:'R'},'Actual Mobile status projected; device/package/runtime effects unproved','FIXCL-host-frozen.json'),
      25:({0:'G',1:'R',2:'A',4:'R'},'Actual Game Dev status projected; editor/runtime/build effects unproved','FIXCL-host-frozen.json'),
      33:({0:'G',1:'A',2:'G',4:'A'},'Stored plans, timers, notification schedules and watches checked on their exact subjects; provider/job execution unproved','FIXCL-transports-supplemental.json'),
      34:({0:'G',1:'A',2:'G',4:'A'},'Exact approved settings patch and durable preferences checked; setup lacks a renderer observer and is refused before dispatch; local-only network journey unproved','FIXCL-transports-sealed.json'),
    }
    matrix=[]
    for index,(changes,boundary,receipt) in updates.items():
        row=baseline['matrix'][index]
        matrix.append({'surface':row['surface'],'owner':row['owner'],'before':row['cells'],
                       'after':[{'criterion':n,'status':changes.get(n,cell['status']),
                                 'changedByFIXCL':n in changes,'boundary':boundary if n in changes else cell['finding'],
                                 'evidence':receipt if n in changes else cell['evidence']} for n,cell in enumerate(row['cells'])]})
    supporting=sorted(p.name for p in EVIDENCE.glob('FIXCL*.json') if p.name!='FIXCL.json')
    commits=subprocess.check_output(['git','log','c3b1948bb662fc16fe7986bd297a6c8ace939203..HEAD','--format=%H %s'],cwd=REPO,text=True).splitlines()
    receipt={'schema':'neyvia.FIXCL.v1','status':'partial_with_concrete_frontiers',
       'baseline':{'head':baseline['auditedHead'],'AUD4Sha256':sha(AUDIT),
                   'reportSha256':sha(Path(r'C:\Users\user\Projects\plans\logs\audit4-cl.md')),
                   'notesColdProcedureMs':baseline['transcripts']['cl_notes_procedure']['elapsedMs'],
                   'baselineNotesSamples':1,'baselineNotesPercentilesAvailable':False},
       'fixes':{'F2':'Authored owner codecs, scalar typed relations, stable refs, bounded immutable projections and subject deltas',
                'F4':'Mandatory fresh subject/content/pixel/hash/durable-state checks; unmapped or unresolved effects block dispatch/completion',
                'F5':'Canonical manual owner and applicable procedure admitted per action; source/version/action/check IDs saved in use receipts; stale owner cannot substitute another workflow',
                'F14':'Source-owner scanning prunes generated/evidence/link trees; dependency enrichment uses bounded asynchronous queue/cache after required checks'},
       'coverage':{'registeredActions':len(inventory),'statuses':statuses,'actionInventory':inventory,
                   'inventoryBoundary':supplement['inventoryBoundary'],
                   'actuallyExercisedEffectActions':exercised,'adaptersWithoutActualActionJourney':unexercised,
                   'nativeAndSpawnedMCPJourneys':transport['selectedCases'],
                   'supplementalJourneys':supplement['selectedCases'],
                   'httpPluginBoundary':'Nine actual read families, scope/goal/mutation refusals. No new mutation grant was added.'},
       'latency':{'firstProcedureMs':host['transcripts']['cl_notes_procedure']['elapsedMs'],
                  'procedureAdmissionAndWarm':host['latency'],
                  'coldProcessAndWarmTransport':proofs['FIXCL-cold-process.json']['latency'],
                  'impactBefore':{key:value for key,value in read('FIXCL-latency-before.json').items() if key in {'sourceSha256','cold','warm'}},
                  'impactAfter':{key:value for key,value in read('FIXCL-latency-verified.json').items() if key in {'sourceSha256','cold','warm'}},
                  'asynchronousMechanism':'FIXCL-latency-mechanism-verified.json',
                  'limits':'Nearest-rank percentiles; five cold and ten warm procedure/process samples. Process timing includes startup/imports; baseline procedure has only one sample. No hard cold-start SLA or isolated-system timing claim.'},
       'matrixBeforeAfter':matrix,'productSourceHashes':product,
       'receipts':{name:{'sha256':sha(EVIDENCE/name),'primary':name in primary} for name in supporting},
       'localCommits':commits,
       'limitations':['HTTP/plugin mutation journey requires an explicit owner-scoped grant; current standalone gateway is read-only and plugin scope excludes several owned families.',
                      'Unmapped effects remain frontier; this does not implement every native action or every app.',
                      'Setup is refused because its old timestamp-only predicate cannot prove a reopened wizard. Renderer acknowledgement, running SDK reducer, provider/job outcomes, native/device/peer effects and unexercised procedures remain unproved.',
                      'Other-session CUA/browser/research/contracts/inception implementation surfaces were not edited; their product effect work remains with their owners.'],
       'authority':{'branch':'track/fix-cl','ports':list(range(48821,48830)),
                    'publish':False,'push':False,'merge':False,'NAS':False,'visibleWindows':False,
                    'newCommands':[],'registration':'Existing neyvia.cl/native gateway, authenticated HTTP/plugin adapter and spawned stdio MCP paths; no new public endpoint or desktop command.'}}
    (EVIDENCE/'FIXCL.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'receipt':'scripts/evidence/FIXCL.json','status':receipt['status'],'coverage':statuses,'commits':len(commits),'primaryReceiptsVerified':len(primary)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layers',action='store_true')
    args=parser.parse_args()
    layer_receipts() if args.layers else main()
