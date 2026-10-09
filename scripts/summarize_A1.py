"""Verify and bind the A1 real-call receipts to reviewable source/artifact bytes."""
from pathlib import Path
import hashlib
import json
import sys
sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent import app_sdk as sdk
from grant_agent.durability import atomic_write_json

def main():
    path=REPO/'scripts/evidence/A1.json'
    value=sdk.read(path);wiring=sdk.read(REPO/'scripts/evidence/A1-wiring.json');exports=sdk.read(REPO/'scripts/evidence/A1-exports.json')
    checks={
        'liveModelProposal':value['luna']['passed'] and value['luna']['requestedModel']=='gpt-6-luna',
        'realFeature':value['feature']['ok'], 'brokenBuildRefused':not value['broken']['ok'],
        'negativeObserverGoal':any(not row['goal']['passed'] for row in value['broken']['journey']),
        'canonicalCLDoneRefused':value['clDoneBroken']['doneStatus']=='refused',
        'canonicalCLDoneRepaired':value['clDoneRepaired']['doneStatus']=='ok',
        'nativeGoal':value['native']['ok'],
        'nativeBackgroundPreserved':all(row['foregroundPreserved'] and row['cursorPreserved'] for row in value['native']['nativeDeliveries']),
        'nativeStateSameAsUI':value['nativeStateTool']['state']['count']==1,
        'independentUserAndAgent':value['sharedState']['state']['count']==2 and 'Count: 2' in value['sharedUserObservation']['text'],
        'mobileTransportAndDesktop':wiring['ok'] and wiring['desktopAllowed'] and wiring['mobileRealGoal']['ok'],
        'autopilotCompleted':wiring['autopilotExecution']['run']['status']=='completed',
        'autopilotBrokenReadmissionBlocked':wiring['autopilotBrokenExecution']['run']['status']=='blocked',
        'claimsReleased':not wiring['activeClaims']['claims'],
        'portableAndDeviceExport':exports['ok'] and exports['movedHost']['ok'] and exports['deviceReloadState']['count']==2,
    }
    if not all(checks.values()):raise ValueError('A1 gate failed: '+str([name for name,passed in checks.items() if not passed]))
    run=REPO/value['run']
    if sdk.source_hashes(run/'generated-app')!=value['repaired']['sourceHashes']:raise ValueError('Committed app source snapshot differs from repaired live source')
    if sdk.source_hashes(run/'generated-desktop')!=value['native']['sourceHashes']:raise ValueError('Committed native source differs from observed build')
    value['acceptance']={'definingMechanism':True,'fullPlatformProof':False,'checks':checks,
        'modelCalls':1,'proposalReplay':value.get('replayedModelProposal'),
        'sampleSource':str((run/'generated-app').relative_to(REPO)),
        'nativeSource':str((run/'generated-desktop').relative_to(REPO)),
        'wiringReceipt':'scripts/evidence/A1-wiring.json','exportReceipt':'scripts/evidence/A1-exports.json',
        'missing':['CL 1.1 default runtime awaits integration; the proof explicitly used the read-only peer checkout',
                   'Expo native execution, physical iOS/Android, signed distribution',
                   'Rendered Neyvia shell/device-frame proof (Chrome and IAB unavailable)'],
        'needsPaul':{'mobileBuildAdmission':wiring['mobileNativeAdmission'],'expo':exports['expoBuild']},
        'modelBoundary':'One real gpt-6-luna proposal through the manual and audited CLI route; final run explicitly replays its code. Provider events do not attest weights; no comparative efficiency claim.'}
    owned=[REPO/name for name in ('.gitattributes','config/neyvia_manuals.json','manuals/app-sdk.manual.json','docs/manuals/app-sdk.md','docs/app-sdk.md','scripts/fluxio-cli.mjs','scripts/neyvia-cli.mjs','scripts/app_sdk.py','scripts/prove_A1.py','scripts/prove_A1_exports.py','scripts/prove_A1_wiring.py','scripts/summarize_A1.py')]
    owned+=list((REPO/'config/app_sdk').rglob('*'))
    owned += [REPO/'src/grant_agent'/name for name in ('app_sdk.py','app_sdk_server.py','neyvia_app_sdk.py','desktop_bridge.py','neyvia_autopilot.py','neyvia_mobile_studio.py','neyvia_workspace_tools.py','web_backend.py')]
    value['implementationHashesLF']={str(p.relative_to(REPO)).replace('\\','/'):hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in owned if p.is_file()}
    artifacts=[p for p in (REPO/'scripts/evidence').glob('A1*') if p.is_file() and p!=path]
    artifacts+=list((REPO/'scripts/evidence/A1-runs').rglob('*'))
    value['artifactHashes']={str(p.relative_to(REPO)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts if p.is_file()}
    atomic_write_json(path,value)
    print(json.dumps({'definingMechanism':True,'fullPlatformProof':False,'gates':len(checks),'artifacts':len(value['artifactHashes']),'sourceFiles':len(value['implementationHashesLF'])}))

if __name__=='__main__':main()
