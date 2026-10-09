"""Disposable inputs for real FIXCL transport journeys; no fake observer values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def journeys(root: Path, suffix: str = ''):
    from PIL import Image
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    prefix = 'effects' + suffix
    folder = root / prefix
    folder.mkdir(exist_ok=True)
    text = folder / 'source.txt'
    text.write_bytes(b'Original exact bytes\n')
    image = folder / 'source.png'
    Image.new('RGB', (8, 6), (15, 60, 180)).save(image)
    digest = hashlib.sha256(text.read_bytes()).hexdigest()
    rel = text.relative_to(root).as_posix()
    moved = folder / 'moved.txt'
    sdk = prefix + '-sdk'
    quote = json.dumps
    cases = []
    def add(key, goal, calls, expected):
        cases.append({'id': key, 'lines': 'G effect: ' + goal + '\n' + '\n'.join(calls) + '\ndone()', 'expected': expected})
    add('workspace-patch', 'workspace.read(path=' + quote(rel) + ')["content"] == "Changed exact bytes\\n"',
        ['workspace.patch(path=' + quote(rel) + ', expectedSha256=' + quote(digest) + ', edits=[{"start":0,"end":8,"text":"Reviewed","expectedText":"Original"}])',
         'run tools-depth.verify-effect-workspace-patch(path='+quote(rel)+', expectedSha256='+quote(hashlib.sha256(b'Reviewed exact bytes\n').hexdigest())+', edits=[{"start":0,"end":8,"text":"Changed","expectedText":"Reviewed"}])'],
        {'file': str(text), 'bytes': 'Changed exact bytes\n','manualOwner':'tools-depth'})
    add('files-move-undo', 'files.stat(path=' + quote(str(text)) + ',preview=True)["preview"] == "Changed exact bytes\\n"',
        ['files.move(source=' + quote(str(text)) + ', to=' + quote(str(moved)) + ')', 'files.undo()'],
        {'file': str(text), 'bytes': 'Changed exact bytes\n', 'absent': str(moved)})
    add('image-crop', 'image.state()["requested"]["dimensions"]["width"] == 4 and image.state()["requested"]["dimensions"]["height"] == 3',
        ['run image.verify-effect-image-open(source=' + quote(str(image)) + ')', 'image.crop(region={"x":1,"y":2,"width":4,"height":3})'],
        {'source': str(image), 'dimensions': [4, 3], 'sourceSha256': hashlib.sha256(image.read_bytes()).hexdigest(),
         'compiledProcedures':['image.verify-effect-image-open']})
    add('image-export', 'files.stat(path=' + quote(str(folder / 'export.png')) + ')["size"] != None',
        ['image.export(path=' + quote(str(folder / 'export.png')) + ')'],
        {'file': str(folder / 'export.png'), 'requiresFixtureApproval': True, 'exactCurrentImageBytes': True})
    add('artifact-publish', 'artifact.list()["total"] > 0',
        ['artifact.publish(path=' + quote(rel) + ',kind="report",title="FIXCL effect bytes",requestId=' + quote(prefix + '-artifact') + ')'],
        {'path': str(text), 'sha256': hashlib.sha256(b'Changed exact bytes\n').hexdigest(), 'kind': 'report'})
    add('timer-lifecycle', 'timer.read(id=' + quote(prefix) + ')["timer"]["status"] == "stopped" and timer.read(id=' + quote(prefix) + ')["timer"]["lapCount"] == 1',
        ['timer.start(id=' + quote(prefix) + ',label="Effect fixture",phase="verification")',
         'timer.lap(id=' + quote(prefix) + ',lapId="measured",label="Actual checkpoint")',
         'timer.stop(id=' + quote(prefix) + ')'],
        {'timer': prefix, 'status': 'stopped', 'laps': 1})
    add('schedule-lifecycle', 'schedule.list()["schedules"][0]["status"] == "cancelled"',
        ['schedule.after(requestId=' + quote(prefix) + ',seconds=3600,prompt="Fixture notification only",scope={})',
         'schedule.cancel(id=' + quote(prefix) + ')'],
        {'schedule': prefix, 'status': 'cancelled', 'scope': {}})
    add('settings-setup', 'time.now()["unixSeconds"] > 0', ['settings.setup()'],
        {'frontier': True, 'boundary': 'wizard effect has no renderer observer; refuse dispatch and completion despite true time goal'})
    add('settings-theme', 'settings.get()["settings"]["theme"] == "morning"', ['view.theme(theme="light")'],
        {'theme': 'morning', 'boundary': 'canonical durable preference'})
    add('work-claim', 'work.list()["count"] == 1',
        ['work.claim(files=[' + quote(rel) + '],intent="Verify fixture bytes",agent="FIXCL")'],
        {'files': [rel], 'intent': 'Verify fixture bytes', 'agent': 'FIXCL'})
    add('plan-update', 'time.now()["unixSeconds"] > 0',
        ['plan.update(plan=[{"step":"Verify fixture bytes","status":"in_progress"}])'],
        {'sessionId': prefix, 'plan': [{'text': 'Verify fixture bytes', 'status': 'in_progress'}], 'boundary': 'factory exact-plan fresh G; time goal is supplemental'})
    add('sdk-create-build', 'app_sdk.describe(project=' + quote(sdk) + ')["receipts"]["build"]["platform"] == "web"',
        ['run app_sdk.verify-effect-sdk-new(path=' + quote(sdk) + ',name="FIXCL local app",kind="web")',
         'run app_sdk.verify-effect-sdk-build(project=' + quote(sdk) + ',platform="web")'],
        {'project': str(root / sdk), 'name': 'FIXCL local app', 'kind': 'web', 'verifyBuildArtifactSha256': True,
         'compiledProcedures':['app_sdk.verify-effect-sdk-new','app_sdk.verify-effect-sdk-build']})
    return cases


def supplemental_journeys(root: Path, suffix: str = ''):
    """Opt-in owner journeys, preserving the original twelve default cells."""
    from datetime import datetime, timedelta, timezone
    from PIL import Image
    root = Path(root).resolve()
    prefix = 'effects-supp' + suffix
    folder = root / prefix
    folder.mkdir(exist_ok=True)
    quote = json.dumps
    cases = []
    def add(key, goal, calls, expected, complete=True):
        lines = 'G effect: ' + goal + '\n' + '\n'.join(calls)
        cases.append({'id': key, 'lines': lines + ('\ndone()' if complete else ''), 'expected': expected})
    rel = (folder / 'write.txt').relative_to(root).as_posix()
    add('workspace-write', 'workspace.read(path='+quote(rel)+')["content"] == "Supplement bytes\\n"',
        ['workspace.write(path='+quote(rel)+',content="Supplement bytes\\n")'],
        {'file':str(folder/'write.txt'), 'bytes':'Supplement bytes\n'})
    notes = folder / 'notes'
    first, second = prefix+'-One', prefix+'-Two'
    first_body = '# '+first+'\n\nFirst fixture\n\nAppended fixture\n'
    second_body = '# '+second+'\n\nFirst fixture\n'
    add('notes-folder-generated',
        'notes.read(path='+quote(first+'.md')+')["body"] == '+quote(first_body)+
        ' and notes.read(path='+quote(second+'.md')+')["body"] == '+quote(second_body)+
        ' and notes.read(path='+quote(first+'.md')+')["pinned"] == True',
        ['notes.folder(folder='+quote(str(notes))+')',
         'notes.write(body="First fixture\\n",title='+quote(first)+')',
         'notes.write(body="First fixture\\n",title='+quote(second)+')',
         'notes.write(path='+quote(first+'.md')+',body="Appended fixture\\n",mode="append")',
         'notes.pin(path='+quote(first+'.md')+')'],
        {'notesFolder':str(notes), 'filesBytes':{str(notes/(first+'.md')):first_body, str(notes/(second+'.md')):second_body}})
    add('view-preferences', 'settings.get()["settings"]["density"] == "workshop" and view.transparency.state()["transparency"] == "minimal"',
        ['view.layout(level="workshop")','view.transparency(level="minimal")','view.ambient(on=False)'],
        {'density':'workshop','transparency':'minimal','ambient':False, 'boundary':'persisted preferences; renderer acknowledgement unclaimed'})
    created = folder/'new-folder'
    add('files-mkdir-undo', 'files.list(path='+quote(str(folder))+')["path"] == '+quote(str(folder)),
        ['files.mkdir(path='+quote(str(created))+')','files.undo()'], {'absent':str(created)})
    image = folder/'source.png'
    source = Image.new('RGB',(8,6))
    source.putdata([(x*23,y*31,(x+y)*13) for y in range(6) for x in range(8)])
    source.save(image)
    edit = folder/'edit.png'
    Image.new('RGBA',(5,4),(90,40,20,128)).save(edit)
    region = {'x':1,'y':1,'width':3,'height':2}
    add('image-resize-composite', 'image.state()["requested"]["dimensions"]["width"] == 5 and image.state()["requested"]["dimensions"]["height"] == 4',
        ['image.open(source='+quote(str(image))+')','image.resize(width=5,height=4)',
         'image.composite(edit='+quote(str(edit))+',region='+quote(region)+')'],
        {'source':str(image),'sourceSha256':hashlib.sha256(image.read_bytes()).hexdigest(),
         'dimensions':[5,4],'compositeEdit':str(edit),'compositeRegion':region})
    claim_files = [(folder/'claimed.txt').relative_to(root).as_posix()]
    add('work-release', 'work.list(files='+quote(claim_files)+')["count"] == 0',
        ['work.claim(files='+quote(claim_files)+',intent="Supplement release fixture",agent="FIXCL")'],
        {'releaseClaimFor':claim_files}, complete=False)
    add('settings-proposal', 'settings.get()["settings"]["density"] == "grove"',
        ['settings.propose(patch={"density":"grove"},expectedRevision=OBSERVED_REVISION)'],
        {'approvalPatch':{'density':'grove'},'requiresFixtureApproval':True,'settingsPatch':{'density':'grove'}})
    run_id = 'run-'+prefix
    when = (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    add('schedule-watch-lifecycle', 'watch.list()["watches"][0]["status"] == "cancelled"',
        ['schedule.create(requestId='+quote(prefix)+',when='+quote(when)+',prompt="Retained fixture only",scope={})',
         'schedule.cancel(id='+quote(prefix)+')',
         'watch.create(requestId='+quote(prefix)+',runId='+quote(run_id)+',message="Fixture watch only",states=["completed"])',
         'watch.cancel(id='+quote(prefix)+')'],
        {'schedule':prefix,'watch':prefix,'queuedRunFixture':run_id,'when':when,
         'boundary':'actual retained connected run admitted without a worker and recovered as interrupted; watch arm/cancel and schedule persistence only, no provider execution'})
    return cases
