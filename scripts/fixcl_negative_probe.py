"""Real refusal journeys against disposable Notes, manuals and pane requests."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from fixcl_verify import REPO, guards, environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    if args.port not in range(48821,48830): parser.error('Assigned ports only')
    root=REPO/'.agent_control/proofs'/('FIXCL-negative-'+str(time.time_ns()))
    root.mkdir(parents=True); guards(root); environment(root,args.port)
    import os
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.ui_command_bus import bus_for
    prepare_broker_fixture(root)
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL-negative',permission_mode='workspace')
    gateway.native.call('neyvia.notes.folder',{'folder':str(root/'notes')})
    gateway.native.call('neyvia.notes.write',{'path':'audit.md','body':'before'})
    host=Protocol(gateway)
    proof={'schema':'neyvia.FIXCL.negative.v1','root':str(root),'transcripts':{},'checks':{}}
    source='G: notes.read(path="audit.md").body == "effect bytes"\nnotes.write(path="audit.md",body="effect bytes")\ndone()'
    value=host.run(source,action_id='bound-effect')
    proof['transcripts']['writeDone']=value
    proof['checks']['writeDone']=value['ok']
    row=next(r for r in value['results'] if r.get('name')=='notes.write')
    proof['checks']['manualBound']=bool(row['manualUse']['sourceSha256'] and row['manualUse']['procedure'] and 'effect-notes-write' in row['manualUse']['checkIds'])
    note=root/'notes/audit.md'
    note.write_bytes(b'wrong external bytes')
    changed=host.completion()
    proof['transcripts']['afterExternalByteChange']=changed
    proof['checks']['corruptEffectRefusesCompletion']=changed['status']=='incomplete' and any(not check['passed'] for check in changed['goalChecks'])
    versions=root/'.neyvia/manual-versions'
    raw=(json.dumps(host.manual_documents['notes'],indent=2)+'\n').encode()
    digest=hashlib.sha256(raw).hexdigest()
    (versions/'notes').mkdir(parents=True)
    artifact=versions/'notes'/(digest+'.json')
    artifact.write_bytes(raw)
    (versions/'notes.json').write_text(json.dumps({'sha256':digest}),encoding='utf-8')
    current=Protocol(gateway)
    original=artifact.read_bytes()
    artifact.write_bytes(b'{}')
    try:
        stale=current.run('G: notes.read(path="audit.md").body == "forbidden"\nnotes.write(path="audit.md",body="forbidden")',action_id='changed-manual')
        proof['transcripts']['changedManual']=stale
        proof['checks']['changedManualRefused']=not stale['ok'] and stale['status']=='frontier' and note.read_bytes()==b'wrong external bytes'
        workflow = current.run('run handoff-recovery.record-blocked(path="audit.md",message="#blocked forbidden",source=' + json.dumps(str(root/'source.txt')) + ',target=' + json.dumps(str(root/'target.txt')) + ',receipt="record")', action_id='stale-owner-workflow')
        proof['transcripts']['staleOwnerWorkflow'] = workflow
        proof['checks']['workflowCannotBypassStaleOwner'] = not workflow['ok'] and note.read_bytes() == b'wrong external bytes' and current.manual_use('neyvia.notes.write', {'path':'audit.md','body':'#blocked forbidden','mode':'append'}, procedure='handoff-recovery.record-blocked') is None
    finally:
        artifact.write_bytes(original)
    frontier=Protocol(gateway)
    existing=bus_for(root).since(0)
    cursor=max((int(event['id']) for event in existing),default=0)
    denied=frontier.run('G: time.now()["unixSeconds"] > 0\npane.show(kind="browser",target="https://example.invalid")',action_id='no-renderer-proof')
    proof['transcripts']['paneWithoutRenderer']=denied
    events=bus_for(root).since(cursor)
    proof['checks']['uncheckedPaneRefusedBeforeDispatch']=not denied['ok'] and not any(event['action'].startswith('pane.') for event in events)
    after_refusal=frontier.run('done()')
    proof['transcripts']['doneAfterUncheckedPane']=after_refusal
    proof['checks']['uncheckedAttemptCannotUseWeakGoal']=not after_refusal['ok']
    restored=Protocol(gateway)
    saved=frontier._completion_snapshot()
    restored.host.restore_completion_bindings(saved['bindings'])
    restored.host.goals=list(frontier.host.goals)
    proof['checks']['pendingAttemptSurvivesRestore']=not restored.run('done()')['ok']
    generated=Protocol(gateway)
    created=generated.run('G: time.now()["unixSeconds"] > 0\nnotes.write(title="First generated title",body="first generated body")\nnotes.write(title="Second generated title",body="second generated body")\ndone()',action_id='two-generated-notes')
    proof['transcripts']['twoGeneratedNotes']=created
    bodies=[binding for binding in generated.host.effect_bindings.values() if binding['name']=='notes.write']
    proof['checks']['generatedNotesHaveDistinctSubjects']=created['ok'] and len(bodies)==2 and len({row['subjectKey'] for row in bodies})==2
    first=next(row for row in bodies if row['args']['title']=='First generated title')
    first_file=Path(first['value']['file'])
    proof['checks']['generatedTitleBytes']=first_file.read_bytes()==b'# First generated title\n\nfirst generated body'
    first_file.write_bytes(b'corrupted first generated note')
    after_generated=generated.run('done()')
    proof['transcripts']['afterFirstGeneratedNoteChanged']=after_generated
    proof['checks']['earlierGeneratedSubjectStillChecked']=not after_generated['ok']
    claims=Protocol(gateway)
    claimed=claims.run('G: time.now()["unixSeconds"] > 0\nwork.claim(files=["first.txt"],intent="first intent",agent="FIXCL")\nwork.claim(files=["second.txt"],intent="second intent",agent="FIXCL")\ndone()',action_id='two-claims')
    proof['transcripts']['twoClaims']=claimed
    bound=[row for row in claims.host.effect_bindings.values() if row['name']=='work.claim']
    proof['checks']['claimsHaveDistinctSubjects']=claimed['ok'] and len(bound)==2
    identity=bound[0]['value']['claim']['id']
    released=claims.run('work.release(id='+json.dumps(identity)+')\ndone()',action_id='release-one-claim')
    proof['transcripts']['releaseOneClaim']=released
    proof['checks']['releaseSupersedesItsClaim']=released['ok'] and len(claims.host.effect_bindings)==2
    oversized = root / 'oversized-tree'
    oversized.mkdir()
    for n in range(2001):
        (oversized / str(n)).write_bytes(b'')
    destination = root / 'refused-tree-move'
    bounded = Protocol(gateway).run('G: time.now()["unixSeconds"] > 0\nfiles.move(source=' + json.dumps(str(oversized)) + ',to=' + json.dumps(str(destination)) + ')\ndone()', action_id='bounded-tree')
    proof['transcripts']['oversizedTreeMove']=bounded
    proof['checks']['oversizedTreeRefusedBeforeMutation']=not bounded['ok'] and oversized.is_dir() and not destination.exists() and '2000' in json.dumps(bounded)
    setup_host = Protocol(gateway)
    setup_before = bus_for(root).get('settings.setup', {})
    setup = setup_host.run('G: time.now()["unixSeconds"] > 0\nsettings.setup()\ndone()', action_id='setup-needs-renderer')
    proof['transcripts']['setupWithoutRenderer'] = setup
    proof['checks']['setupWithoutRendererRefusedBeforeDispatch'] = not setup['ok'] and 'frontier' in json.dumps(setup) and bus_for(root).get('settings.setup', {}) == setup_before
    setup_done = setup_host.run('G: time.now()["unixSeconds"] > 0\ndone()', action_id='setup-weak-goal')
    proof['transcripts']['setupWeakGoal'] = setup_done
    proof['checks']['setupAttemptBlocksWeakCompletion'] = not setup_done['ok']
    proof['sourceHashes']={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (REPO/'src/grant_agent/cl').glob('*.py')}
    output=REPO/'scripts/evidence/FIXCL-negative.json'
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'receipt':str(output),'checks':proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


if __name__=='__main__': raise SystemExit(main())
