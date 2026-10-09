"""Recover original emitted manual receipts from passing, source-current journeys.

This reads retained evidence only. It does not execute effects, fabricate manual
uses, reinterpret failed goals, or claim a stopped renderer is still mounted.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
from fixcl3_aud4_matrix import REPO, source_hashes

EXPECTED = {
    'FIXCL4-render-aliases.json': {
        'neyvia.folder.open':'folder-open.positiveCL', 'neyvia.notes.open':'notes-open.positiveCL',
        'neyvia.notify':'notify.positiveCL', 'neyvia.onboarding.open':'onboarding-open.positiveCL',
        'neyvia.view.arrange':'arrange.positiveCL', 'neyvia.view.float':'float.positiveCL',
        'neyvia.view.scene':'scene.positiveCL', 'neyvia.voice.command':'voice-notes.positiveCL'},
    'FIXCL4-render-media.json': {
        'preview.annotate':'preview-annotate.positiveCL', 'preview.screenshot':'preview-screenshot.positiveCL',
        'preview.taste':'preview-taste.positiveCL', 'skill.live.iterate':'skill-live-iterate.positiveCL',
        'video.digest':'video-digest.positiveCL'},
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    retained_inputs = [Path(__file__),*[REPO/'scripts/evidence'/name for name in EXPECTED]]
    def snapshot_bindings():
        return {**source_hashes(REPO),**{path.relative_to(REPO).as_posix():sha(path) for path in retained_inputs}}
    start = snapshot_bindings()
    checks, uses, provenance = {}, [], []
    for name, expected in EXPECTED.items():
        path = REPO/'scripts/evidence'/name
        proof = json.loads(path.read_bytes())
        sources = proof.get('sourceHashesAtStart', proof.get('sourceHashes', {}))
        current = bool(sources) and sources == proof.get('sourceHashesAtEnd', sources)
        current = current and all((REPO/key).resolve().is_relative_to(REPO) and
            (REPO/key).is_file() and sha(REPO/key)==digest for key,digest in sources.items())
        passing = proof.get('ok') is True and bool(proof.get('checks')) and all(value is True for value in proof['checks'].values())
        checks[name+'.passingSourceCurrentJourney'] = current and passing
        if not current or not passing: continue
        root = Path(proof['root']).resolve()
        if not root.is_relative_to(REPO/'.agent_control/proofs'): raise ValueError('Only task-owned retained stores allowed')
        database = root/'.agent_control/ui_commands.sqlite3'
        before = sha(database)
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            events = db.execute("SELECT id,payload FROM events WHERE action='cl.manual.use' ORDER BY id").fetchall()
        selected = []
        for identity, raw in events:
            row = json.loads(raw)
            if row.get('tool') not in expected or row.get('status')!='admitted' or not row.get('effectChecks'): continue
            if proof['checks'].get(expected[row['tool']]) is not True: continue
            bindings = {'src/grant_agent/cl/'+key:value for key,value in row.get('effectSourceBindings',{}).items()}
            bindings[row['source'].replace('\\','/')] = row['sourceSha256']
            if not row.get('effectSourceBindings') or any(start.get(key)!=value for key,value in bindings.items()): continue
            selected.append({'eventId':identity,'tool':row['tool'],'usageId':row['usageId']})
            uses.append(row)
        checks[name+'.everyRequestedOriginalManualEvent'] = set(expected) <= {row['tool'] for row in selected}
        checks[name+'.retainedStoreConserved'] = sha(database)==before
        provenance.append({'proof':name,'proofSha256':sha(path),'store':str(database),'storeSha256':before,'events':selected})
    end = snapshot_bindings()
    checks['sourceUnchanged'] = start==end
    result = {'schema':'neyvia.FIXCL5.manual-witness-recovery.v1','ok':all(checks.values()),
        'checks':checks,'manualReceipts':uses,'provenance':provenance,
        'sourceHashesAtStart':start,'sourceHashesAtEnd':end,
        'boundary':'Original durable events joined to their actual passing CL goals and unchanged source-bound journey receipts; no effects replayed and no current live renderer claimed.'}
    output = REPO/'scripts/evidence/FIXCL5-manual-witnesses.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':result['ok'],'manualEvents':len(uses),'checks':checks}))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
