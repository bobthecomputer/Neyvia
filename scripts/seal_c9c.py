"""Seal named sanitized proof artifacts; never traverse account/private stores."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts/evidence"
RUNS = OUT / "C9c-runs"

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding="utf-8"))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--implementation-commit",required=True)
    args=p.parse_args()
    commit=subprocess.check_output(["git","rev-parse",args.implementation_commit],cwd=REPO,text=True).strip()
    source_paths=subprocess.check_output(["git","diff-tree","--no-commit-id","--name-only","-r",commit],cwd=REPO,text=True).splitlines()
    sources=[]
    for name in source_paths:
        path=REPO/name
        if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8'),filename=name)
        blob=subprocess.check_output(["git","show",commit+":"+name],cwd=REPO)
        if blob!=path.read_bytes():raise ValueError("Committed source differs from sealed working bytes: "+name)
        sources.append({"path":name,"sha256":sha(path),"bytes":path.stat().st_size})
    names=("C9c-judge","C9c-lifecycle","C9c-voting","C9c-voting-native","C9c-independent-outcomes","C9c-cleanup")
    receipts={name:read(OUT/(name+'.json')) for name in names}
    assert receipts['C9c-judge']['passed'] and receipts['C9c-lifecycle']['passed']
    assert receipts['C9c-voting']['pageContractChecksPassed'] and receipts['C9c-voting-native']['passed']
    assert receipts['C9c-independent-outcomes']['passed'] and receipts['C9c-cleanup']['passed']
    lifecycle=receipts['C9c-lifecycle']
    for name,expected in lifecycle['sourceHashes'].items():
        if sha(REPO/name)!=expected:raise ValueError("Lifecycle source binding changed: "+name)
    judge=receipts['C9c-judge']['calibration']
    assert len(judge['leaveOneOut'])==18 and not judge['passed'] and judge['actualPreferenceCount']==0
    assert len(receipts['C9c-judge']['round3']['comparisons'])==2
    normalization=[]
    for name,expected in receipts['C9c-voting']['sourceHashes'].items():
        path=REPO/name.replace('\\','/')
        raw=path.read_bytes()
        if sha(path)!=expected:
            if hashlib.sha256(raw.replace(b'\n',b'\r\n')).hexdigest()!=expected:
                raise ValueError("Voting source binding changed beyond line endings: "+name)
            normalization.append({"path":name,"observedSha256":expected,"committedSha256":sha(path),"difference":"CRLF to LF only"})
    raw=set()
    # These directories contain only output receipts and anonymous rubric data.
    for scope in (RUNS/'judge',RUNS/'lifecycle'):
        raw.update(scope.glob('**/.neyvia/autopilot-model/*.json'))
    raw.update((RUNS/'judge/.neyvia/lessons/rubric').glob('*.json'))
    raw.update((RUNS/'judge/.neyvia/lessons').glob('preference-judge*.json'))
    raw.add(RUNS/'judge/.neyvia/lessons/rubric-observations.json')
    raw.update((RUNS/'judge/images').glob('*.png'))
    raw.update((RUNS/'voting-images').glob('*.png'))
    for scope in (RUNS/'lifecycle',RUNS/'runtime/.neyvia/lessons/trials'):
        raw.update(scope.glob('**/.neyvia/autopilot-model/*.json'))
        for path in scope.glob('**/replay*.json'):
            raw.add(path)
            for name in read(path).get('files',{}):
                output=(path.parent/name).resolve()
                if not output.is_relative_to(path.parent.resolve()):raise ValueError('Output escaped replay')
                raw.add(output)
        raw.update(scope.glob('**/trial.json'))
    lessons=RUNS/'runtime/.neyvia/lessons'
    raw.update(lessons.glob('suites/*.json'))
    for path in lessons.glob('*.json'):
        # Only known lesson/suite exports; no databases or account stores.
        if path.name=='suite.json' or read(path).get('schema')=='neyvia.lesson.v1': raw.add(path)
    raw.update(lessons.glob('*.cl'))
    raw.update((RUNS/'lead-outcomes').glob('**/lookup.py'))
    raw.update((RUNS/'lead-outcomes').glob('**/score.py'))
    index=[{"path":path.relative_to(REPO).as_posix(),"bytes":path.stat().st_size,"sha256":sha(path)} for path in sorted(raw)]
    if sum(r['bytes'] for r in index)>120_000_000:raise ValueError('Bounded raw proof exceeds120MB')
    archive=OUT/'C9c-raw.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
        for path in sorted(raw):bundle.write(path,path.relative_to(REPO).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for row in index:
            assert hashlib.sha256(bundle.read(row['path'])).hexdigest()==row['sha256']
    closed=[]
    for port in range(48761,48770):
        with socket.socket() as probe:
            probe.settimeout(.2)
            if probe.connect_ex(('127.0.0.1',port))==0:raise ValueError('Owned proof port remains open: '+str(port))
            closed.append(port)
    contract=(Path(r'C:\Users\user\Projects\plans\15-handoff.md')).read_text(encoding='utf-8').split('## C9\n',1)[1].split('\n## ',1)[0]
    summary={"schema":"neyvia.C9c-proof.v1","at":datetime.now(timezone.utc).isoformat(),"branch":"track/c5-noslop",
        "implementationCommit":commit,"status":"Defining local rubric/voting/objective lifecycle proven; learned taste admission remains unproven",
        "acceptance":{"rubricFirst":True,"freshLunaImageCritique":True,"explicitPreferenceCollectedBeforeReveal":True,
            "nativeVoteReload":True,"beneficialPromotion":True,"oneClickRevert":True,"behavioralRevert":True,
            "harmfulLessonRejected":True,"ownBuildsRecycled":True},
        "agreement":{"identityProxyLOO":{"correct":sum(x['correct'] for x in judge['leaveOneOut']),"count":18,"rate":judge['agreement']},
            "equalRubricProxyRate":judge['rubricAgreement'],"explicitTrainingPreferences":judge['actualPreferenceCount'],
            "round3Spoken":{"correct":sum(p['agreesWithSpokenVerdict'] for p in receipts['C9c-judge']['round3']['comparisons']),"count":2},
            "r6VotesSha256":sha(REPO/'proof/preference-pairs-r6-votes.json'),"learnedGateAdmitted":False},
        "lifecycleBoundary":lifecycle['limitations'],"independentExecutableRecipes":len(receipts['C9c-independent-outcomes']['records']),
        "remaining":["Reliable learned taste discrimination and sufficient explicit blind preference data",
            "Broad cross-task regression/generalization beyond the frozen inventory fixture",
            "Complete pointer/keyboard/touch and light/dark checks for historical visual outputs",
            "Obscura0.2.3 origin storage does not survive reload; native WebView2 vote reload proven",
            "Shared cloud voting/publication was not exercised"],
        "adverseReceipts":[p.name for p in sorted(OUT.glob('C9c*failure.json'))],
        "commands":{c:{"tool":t,"registrations":["task_feedback.COMMANDS/TOOLS","connected_sessions.api.CONNECTED_COMMANDS/owner handler",
            "web_backend dispatch","desktop_bridge.ALLOWED_DESKTOP_COMMANDS","Tauri call_desktop_backend_command",
            "neyvia_workspace_tools FEEDBACK_DEFINITIONS/call"]} for c,t in [('task_feedback_submit_command','neyvia.feedback.submit'),
            ('task_feedback_get_command','neyvia.feedback.get'),('lesson_list_command','neyvia.lessons.list'),('lesson_revert_command','neyvia.lessons.revert')]},
        "contractUnderC9":contract,"sourceLineNormalization":normalization,"sources":sources,
        "receipts":[{"path":str((OUT/(n+'.json')).relative_to(REPO)),"sha256":sha(OUT/(n+'.json'))} for n in names],
        "raw":{"path":str(archive.relative_to(REPO)),"sha256":sha(archive),"bytes":archive.stat().st_size,"files":index},
        "closedPorts":closed,"authority":{"push":False,"merge":False,"NAS":False,"downloads":False,"visibleInputDesktopAllowed":False},
        "desktopGuard":{"finalOwnedVisibleWindows":receipts['C9c-judge']['desktopGuard']['ownedVisibleWindows'],
            "earlierHiddenFlagFailuresPreserved":True,"isolation":"CreateProcessW lpDesktop plus actual HWND observation on dedicated desktop"}}
    (OUT/'C9c.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({"sealed":str(OUT/'C9c.json'),"rawFiles":len(index),"archiveBytes":archive.stat().st_size,"sourceFiles":len(sources)}))

if __name__=='__main__':main()
