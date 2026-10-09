"""Authored C8d fixture catalog; materialize only disposable task-local inputs.

This is authoring data, not a schema-default synthesizer or proof generator.
Dynamic identities must come from real setup calls. Missing external state is a
prerequisite failure; no fixture may impersonate a completed product receipt.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def registration_names():
    """Read inert schema factories; never construct a runtime registry/service."""
    from grant_agent.native_tools import NativeToolRegistry, NativeToolSpec
    from grant_agent.neyvia_workspace_tools import tool_specs as workspace_specs
    from grant_agent.workspace_patches import tool_spec as patch_spec
    from grant_agent.web_documents import tool_specs as document_specs
    from grant_agent.neyvia_pdf_tools import tool_specs as pdf_specs
    from grant_agent.workflow_manuals import tool_specs as workflow_specs
    from grant_agent.neyvia_notes_tools import tool_specs as notes_specs
    from grant_agent.neyvia_files_tools import tool_specs as files_specs
    from grant_agent.neyvia_onboarding import tool_specs as onboarding_specs
    from grant_agent.neyvia_devices import tool_specs as device_specs
    names={spec.name for spec in NativeToolRegistry._build_specs()}
    names.add(patch_spec(NativeToolSpec).name)
    for factory in (workspace_specs,document_specs,pdf_specs,workflow_specs,notes_specs,files_specs,onboarding_specs,device_specs):
        names.update(spec.name for spec in factory(NativeToolSpec))
    names.update({'neyvia.native.runtime.observe','neyvia.native.runtime.self-check'})
    return names


def author():
    from grant_agent.neyvia_inception import inventory, validate_bindings
    from grant_agent.neyvia_manuals import get_manual
    catalog = inventory()
    previous = json.loads((ROOT / 'config/inception_journeys.json').read_text(encoding='utf-8'))
    old = previous
    registered = registration_names()
    inputs = {}
    metadata = {}

    def put(identity, values, **extra):
        inputs[identity] = values
        metadata[identity] = extra

    def setup(tool, args, save='seed'):
        return {'tool': tool, 'args': args, 'save': save}

    def file(path, content):
        return {'path': path, 'content': content}

    def dynamic(path):
        return {'$result': path}

    def deferred_input(identity, row, field):
        """Name the real context owner and receipt; never invent an input value."""
        if identity.startswith('C7e-') or identity.startswith('edge-contracts/'):
            return {'reason':'The sealed campaign runner must allocate this port and produce a fresh family receipt.',
                    'owner':'C7e gate integrator','requiredReceipt':'C7e sealed report plus source-bound campaign receipt for this exact family'}
        if identity.startswith(('browser/', 'research-assistant/', 'perception/browser/')):
            return {'reason':'This field must come from an admitted Opus-owned Obscura/source journey; no external tab, network research, or synthetic receipt is permitted here.',
                    'owner':'Opus browser/research gate','requiredReceipt':'Fresh Obscura-owned tab or cited-source receipt bound to this exact contract'}
        if identity.startswith('computer-use/'):
            return {'reason':'A live private C11 session/window identity is required; this fixture author must not invent a session or element token.',
                    'owner':'C11 computer-use gate','requiredReceipt':'Fresh isolated-desktop session and observation receipt for this contract'}
        if identity.startswith('remote/'):
            return {'reason':'A real owner-authorized remote connection and window must be observed by the C11 desktop gate; static connection/window IDs are not evidence.',
                    'owner':'C11 remote-computer gate','requiredReceipt':'Fresh owner-authorized isolated-desktop connection/window receipt for this exact contract'}
        if identity == 'tools-depth/tools/cited-research' or identity == 'tools-depth/tools/fetch-owned-http-body':
            return {'reason':'A source-owned network tab/citation and bounded fetch receipt must be supplied by the browser/research gate.',
                    'owner':'Opus browser/research gate','requiredReceipt':'Fresh Obscura/cited-source request and response receipt bound to this contract'}
        if identity == 'workspace/terminal/execute-scoped-command':
            return {'reason':'The typed command cannot run in the current C8 route because no approved child-process/terminal containment adapter is admitted.',
                    'owner':'C8 terminal runner owner','requiredReceipt':'C8-owned isolated child-process adapter receipt proving candidate-root containment and bounded timeout/output'}
        if identity.startswith('game-dev/'):
            return {'reason':'The actual editor project/session affinity must be created and observed by the admitted 3D Studio bridge.',
                    'owner':'3D Studio gate','requiredReceipt':'Disposable editor project plus real bridge heartbeat or same-request completion receipt'}
        if identity.startswith('image-studio/'):
            return {'reason':'This field needs a real Image Studio asset/project observer; image-effect evidence cannot be inferred from dimensions or a default project.',
                    'owner':'Image Studio C8 integrator','requiredReceipt':'Explicit-layer asset input plus fresh owning image/view observer for this contract'}
        if identity.startswith(('cross-pc/', 'nearby-send-runtime/')):
            return {'reason':'A verified paired peer and exact transfer/share context are absent; no real peer discovery or transfer is authorized by a disposable local fixture.',
                    'owner':'Paul / peer authority','requiredReceipt':'Owner-approved disposable peer receipt bound to the exact transfer and destination'}
        if identity.startswith(('runtime-provider/', 'local-host/', 'native-applications/')):
            return {'reason':'A real host/provider session or explicitly approved child-process context is required; fixture generation must not create or authenticate it.',
                    'owner':'Paul / host authority','requiredReceipt':'Fresh owner-authorized session/tool receipt for the exact scoped operation'}
        if identity.startswith(('local-media/', 'local-browser-sdk/', 'local-rendering/')):
            return {'reason':'The procedure requires a real rendered/media artifact or mounted app observation not producible as a text fixture.',
                    'owner':'C8 rendered-journey integrator','requiredReceipt':'Fresh task-local rendered/media artifact and owning observer receipt for this procedure'}
        if identity.startswith(('local-records/', 'local-evaluations/', 'local-mechanisms/', 'local-integrity/', 'local-environment/')):
            return {'reason':'A contract-specific isolated local record/evaluation seed is missing; use the actual owner API and fresh read-back before admission.',
                    'owner':'Local contract fixture author','requiredReceipt':'Disposable owner-API state seed and fresh exact-contract read-back receipt'}
        if identity.startswith('adaptive-work/work/record-'):
            return {'reason':'This action appends persistent work state, but CL defines no disposable identity initializer, independent observer, or cleanup lifecycle.',
                    'owner':'Adaptive Work owner','requiredReceipt':'Task-local disposable work identity, read-back observer, and verified cleanup lifecycle'}
        if identity == 'creative-records/local-records/record-situation-define':
            return {'reason':'A situation field must come from an isolated candidate-root store and its registered exact-revision observer; no persistent owner state is supplied by this fixture.',
                    'owner':'Creative Records owner','requiredReceipt':'Fresh candidate-root situation state and source-bound effect observer receipt for this field'}
        if identity == 'creative-records/local-records/record-attention-create':
            return {'reason':'A proposal field must come from a bounded disposable fixture and its registered owner-state observer; no provider response or run result is implied.',
                    'owner':'Creative Records owner','requiredReceipt':'Fresh candidate-root proposal state and exact owner-effect observer receipt for this field'}
        if identity == 'creative-records/local-records/record-attention-observe':
            return {'reason':'This action appends caller-reported observations; synthetic provider response, route, latency, or cost would be false.',
                    'owner':'Creative Records owner','requiredReceipt':'Real authorized provider/API observation receipt plus independent state read-back'}
        if identity.startswith('manuals-next/'):
            return {'reason':'A real disposable manual/project/version handle and source-bound lifecycle state are required; no handle or patch result is fabricated.',
                    'owner':'Connected Language fixture author','requiredReceipt':'Task-local compiled manual or version receipt created through the owning API and verified by its observer'}
        if identity.startswith(('autopilot/', 'conductor/', 'nightshift/', 'mission-plan/')):
            return {'reason':'The action requires a real task/run/mission identity and any ensuing work must remain dormant and task-local.',
                    'owner':'C8 local workflow integrator','requiredReceipt':'Fresh exact-owner creation/status receipt for a disposable dormant workflow'}
        if identity.startswith(('memory/', 'efficiency/learned-capabilities/')):
            return {'reason':'The action needs an isolated memory/learning episode with actual owner-store read-back; do not prefill a predicted answer or receipt.',
                    'owner':'LAYA local-state integrator','requiredReceipt':'Fresh task-root episode receipt and exact state/query check for this field'}
        if identity.startswith('app-sdk/'):
            return {'reason':'A real disposable App Factory project or running preview must be created by the owning API before this field is usable.',
                    'owner':'App Factory local fixture author','requiredReceipt':'Fresh task-root SDK project/preview state produced by the App Factory owner'}
        if identity.startswith('mobile-studio/'):
            return {'reason':'A disposable mobile project or isolated no-device probe setting must be supplied by the Mobile Studio owner.',
                    'owner':'Mobile Studio local fixture author','requiredReceipt':'Fresh task-root mobile project/status receipt with device discovery disabled'}
        if identity.startswith('design/'):
            return {'reason':'This procedure needs its exact design specimen/render or human judgement; static input values cannot stand in for it.',
                    'owner':'Design C8 integrator','requiredReceipt':'Fresh row-specific component/specimen render and observer receipt, or explicit human judgement'}
        return {'reason':f'No contract-specific disposable value for required field {field!r} is authored yet; obtain it from the owning local API and verify it before dispatch.',
                'owner':'C8 fixture author','requiredReceipt':f'Fresh owner-API input/state receipt for {identity} field {field}'}

    def deferred_judge(identity, judge):
        if identity.startswith(('C7e-', 'edge-contracts/')):
            return {'reason':'The sealed edge-contract campaign decision must come from its executing gate owner, not a static fixture choice.',
                    'owner':'C7e gate integrator','requiredReceipt':'Fresh C7e campaign decision receipt for this exact judgement'}
        if identity.startswith(('browser/', 'research-assistant/')):
            return {'reason':'This decision requires the actual browser owner or cited-source adjudication; the fixture author cannot decide it.',
                    'owner':'Opus browser/research gate','requiredReceipt':'Fresh owner/source review receipt for this exact judgement'}
        owners = (
            (('computer-use/',), 'C11 computer-use gate', 'Fresh isolated-desktop observation and authorized human decision receipt'),
            (('game-dev/',), '3D Studio gate', 'Fresh editor scene/action observation and decision receipt'),
            (('image-studio/',), 'Image Studio gate', 'Fresh explicit-layer image/project observation and decision receipt'),
            (('app-sdk/',), 'App Factory gate', 'Fresh task-local SDK/toolchain observation and decision receipt'),
            (('mobile-studio/',), 'Mobile Studio gate', 'Fresh task-local project observation with device discovery disabled'),
            (('design/',), 'Neyvia design reviewer', 'Human review of the exact rendered/design specimen for this judgement'),
            (('manuals-next/',), 'Connected Language reviewer', 'Human review of the exact compiled manual/version state for this judgement'),
            (('memory/', 'efficiency/learned-capabilities/'), 'LAYA local-state reviewer', 'Fresh task-root learning episode and authorized choice receipt'),
            (('onboarding/', 'slim-installer/'), 'Paul / install authority', 'Explicit install/release authority decision for this exact action'),
        )
        for prefixes, owner, receipt in owners:
            if identity.startswith(prefixes):
                return {'reason':'This authored judgement belongs to the owning capability reviewer and must not be selected by a generated fixture.',
                        'owner':owner,'requiredReceipt':receipt}
        return {'reason':'This authored judgement belongs to the contract owner and must not be selected by a generated fixture.',
                'owner':'C8 source owner','requiredReceipt':'Explicit owner judgement for '+identity+'/'+judge}

    disposable = [file('c8/input.txt', 'C8 journey artifact\n'), file('c8/data.json', '{"answer":739}\n')]
    put('efficiency/cascade/extract-and-confirm', {'path':'c8/data.json','field':'/answer','expectedJson':'739'}, files=disposable)
    # This is an actual local JSON source for the authored extract action, not
    # a precomputed answer receipt. The procedure has no independent check, so
    # keep that missing proof route explicit instead of claiming coverage.
    put('efficiency/cascade/extract-local-json',
        {'path':'c8/data.json','field':'/answer','strategy':'cascade','useScript':True},
        files=[file('c8/data.json','{"answer":739}\n')],
        prerequisites=['The authored procedure has no independent check contract; it can read this disposable JSON input but cannot prove exact extraction, cache, or telemetry postconditions.'])
    put('efficiency/laya/verify-with-laya', {'question':'page_done','evidence':{}},
        prerequisites=['The authored verify procedure has no independent check contract; an empty evidence object exercises the real missing-evidence route but cannot establish answer correctness.'])
    put('sidebar/overview/preview-subjects', {'ids':[]})
    put('sidebar/overview/confirm-preview', {'previewId':'runtime-setup-preview'}, setup=[setup('neyvia.sidebar.preview', {'ids':[]}, 'preview')], dynamicInputs={'previewId':dynamic('preview.previewId')})
    put('sidebar/overview/undo-grouping', {'undoId':'runtime-setup-undo'}, setup=[setup('neyvia.sidebar.preview', {'ids':[]}, 'preview'),setup('neyvia.sidebar.confirm', {'previewId':dynamic('preview.previewId'),'confirmed':True}, 'confirmed')], dynamicInputs={'undoId':dynamic('confirmed.undoId')})
    put('computer-use/drive/set-field-and-verify', {'window_id':0,'element_token':'C11-fresh-token','label':'Text','expected':'C8 isolated desktop proof'})
    put('computer-use/test-loop/launch-check-handoff', {'app':'notepad','window_id':0,'label':'Text','expected':'C8 isolated desktop proof'})
    put('neyvia/panes/show-work-artifact', {'kind':'file','target':'${root}/c8/input.txt'}, files=disposable)
    put('neyvia/panes/suggest-command', {'command':'Write-Output "C8 command suggestion"'})
    put('neyvia/projects/open-project-folder', {'path':'${root}/c8'}, files=disposable)
    for procedure in ['move-chat','rename-and-confirm']:
        values = {'id':'C8-retained-owned-chat','project':None} if procedure=='move-chat' else {'id':'C8-retained-owned-chat','title':'C8 renamed disposable chat'}
        put('neyvia/sessions/'+procedure, values, prerequisites=['A real owned connected-session identity from an already completed local harness run; no paid chat or provider substitution is authorized by this fixture.'])
    put('neyvia/settings/choose-density', {'level':'calm'})
    for manual in ['neyvia','neyvia-reference']:
        put(manual+'/time/start-timer', {'id':'c8-timer','label':'C8 task-local timer'})
        put(manual+'/time/lap-and-stop', {'id':'c8-timer','lapId':'c8-lap','label':'C8 completed checkpoint'}, setup=[setup('neyvia.timer.start', {'id':'c8-timer','label':'C8 task-local timer'})])
    mission = {'id':'c8-mission','goal':'Store a dormant local proof mission','folder':'${root}/c8','tasks':[{'id':'c8-dormant','prompt':'Read only the local C8 artifact and report its text.','folder':'${root}/c8','harness':'codex','model':'gpt-6.1-sol','owner':'Codex','permissionMode':'read-only','needs':[],'requiresGpu':False}],'acceptanceChecks':['The local artifact contains C8 journey artifact.'],'budget':{'maxTokens':1000,'maxTaskSeconds':60}}
    put('neyvia-reference/missions/draft-mission', {key:value for key,value in mission.items() if key not in {'id','budget'}}, files=disposable)
    for procedure in ['supervise-mission','verify-retained-status']:
        values={'id':'c8-mission'} if procedure=='supervise-mission' else {'id':'c8-mission','index':0,'status':'draft'}
        put('neyvia-reference/missions/'+procedure, values, setup=[setup('neyvia.mission.create',mission)], files=disposable)
    watch={'runId':'C8-retained-owned-run','requestId':'c8-watch','message':'C8 owned run completed','states':['completed']}
    put('neyvia-reference/proactivity/watch-run',watch, prerequisites=['A retained actual connected run, not an invented completed result.'])
    put('neyvia-reference/proactivity/verify-retained-status', {'index':0,'id':'c8-watch','status':'armed'}, prerequisites=['A watch armed through neyvia.watch.create against an actual retained run.'])
    put('neyvia-reference/schedule/remind-after', {'seconds':3600,'prompt':'C8 local notification only','requestId':'c8-reminder'})
    put('neyvia-reference/schedule/verify-effect-schedule-after',
        {'seconds':31536000,'prompt':'C8 disposable one-year local reminder','scope':{},'requestId':'c8-effect-after'})
    put('neyvia-reference/schedule/verify-effect-schedule-create',
        {'when':'2099-01-01T00:00:00+00:00','prompt':'C8 disposable future local reminder','scope':{},'requestId':'c8-effect-create'})
    put('neyvia-reference/schedule/verify-effect-schedule-cancel', {},
        setup=[setup('neyvia.schedule.create',{'when':'2099-01-01T00:00:00+00:00','prompt':'C8 disposable future local reminder','scope':{},'requestId':'c8-schedule-cancel'},'schedule')],
        dynamicInputs={'id':dynamic('schedule.schedule.id')})
    reminder={'when':'2099-01-01T00:00:00+00:00','prompt':'C8 cancellation proof','scope':{},'requestId':'c8-reminder'}
    for procedure in ['cancel-pending','verify-retained-status']:
        values={'id':'c8-reminder'} if procedure=='cancel-pending' else {'index':0,'id':'c8-reminder','status':'waiting'}
        put('neyvia-reference/schedule/'+procedure, values, setup=[setup('neyvia.schedule.create',reminder,'reminder')], dynamicInputs={'id':dynamic('reminder.schedule.id')})
    put('workspace/files/read-and-confirm', {'path':'c8/input.txt','phrase':'C8 journey artifact'}, files=disposable)
    put('workspace/files/create-and-confirm', {'path':'c8/created.txt','content':'C8 newly created artifact\n'})
    put('workspace/files/create-and-read', {'path':'c8/created.txt','content':'C8 newly created artifact\n'})
    put('workspace/files/replace-and-read', {'path':'c8/input.txt','content':'C8 guarded replacement\n'}, files=disposable)
    put('workspace/files/verify-effect-workspace-write', {'path':'c8/effect-write.txt','content':'C8 bounded write effect\n'})
    put('neyvia/projects/create-folder', {'name':'C8 fixture project','path':'c8-project'})
    put('neyvia/projects/create-default-project', {'name':'C8 disposable default project'})
    put('neyvia/panes/place-window', {'id':'notes','placement':'side'})
    put('neyvia/panes/place-right-panel', {'id':'notes'})
    put('neyvia/settings/verify-effect-view-theme', {'theme':'light'})
    put('neyvia/settings/verify-effect-view-layout', {'level':'calm'})
    put('neyvia/settings/verify-effect-view-ambient', {'on':False})
    put('neyvia/time/verify-effect-timer-start', {'id':'c8-effect-timer','label':'C8 local timer'})
    put('neyvia/time/verify-effect-timer-lap', {'id':'c8-effect-timer','label':'C8 checkpoint','lapId':'c8-effect-lap'})
    put('neyvia/time/verify-effect-timer-stop', {'id':'c8-effect-timer'})
    put('notes/overview/verify-effect-notes-write', {'body':'# C8 disposable note\n'})
    put('notes/overview/verify-effect-notes-folder', {'folder':'c8-fixture'})
    put('notes/overview/verify-effect-notes-pin', {'path':'c8-effect.md'})
    put('files/overview/verify-effect-files-mkdir', {'path':'c8-fixture-dir'})
    put('files/overview/verify-effect-files-move', {'from':'c8/move-source.txt','to':'c8/move-target.txt'},files=[file('c8/move-source.txt','C8 move input\n')])
    put('files/overview/verify-effect-files-trash', {'path':'c8/trash-input.txt'},files=[file('c8/trash-input.txt','C8 disposable trash input\n')])
    put('pdf/overview/set-visible-zoom', {'scale':1.25})
    put('onboarding/overview/save-local-choices', {'apps':['notes'],'completed':True,'interests':['coding'],'packs':[],'runtime':'available','tier':'local'})
    put('workspace/files/find-source', {'query':'C8 journey artifact','includeGlob':'c8/*.txt'},files=disposable)
    for procedure in ['find-and-highlight','open-and-read','verify-visible-highlight']:
        values={'source':'${root}/c8/source.pdf','page':1,'phrase':'C8 journey artifact'}
        if procedure=='verify-visible-highlight': values['markIndex']=0
        put('pdf/overview/'+procedure,values,files=[{'path':'c8/source.pdf','kind':'pdf','text':'C8 journey artifact'}],setup=([setup('neyvia.pdf.open',{'source':'${root}/c8/source.pdf','page':1}),setup('neyvia.pdf.highlight',{'page':1,'text':'C8 journey artifact'})] if procedure=='verify-visible-highlight' else []))
    put('notes/overview/capture-tagged-idea', {'path':'c8-idea.md','idea':'C8 captured idea #journey\n','tag':'journey'},setup=[setup('neyvia.notes.write',{'path':'c8-idea.md','body':'# C8 disposable note\n'})])
    for procedure in ['tidy-with-undo','rename-and-check','undo-last-tidy']:
        values={'from':'${root}/c8/original.txt','to':'${root}/c8/renamed.txt'}
        values['originalName' if procedure=='undo-last-tidy' else 'name']='original.txt' if procedure=='undo-last-tidy' else 'renamed.txt'
        put('files/overview/'+procedure, values, files=[file('c8/original.txt','C8 disposable file\n')],setup=([setup('neyvia.files.move',{'from':'${root}/c8/original.txt','to':'${root}/c8/renamed.txt'})] if procedure=='undo-last-tidy' else []))
    image=[{'path':'c8/source.png','kind':'png','width':64,'height':48}]
    put('image-studio/overview/open-inspect', {'source':'${root}/c8/source.png','width':64}, files=image)
    put('image-studio/overview/crop-for-composition', {'source':'${root}/c8/source.png','x':8,'y':6,'width':32,'height':24},files=image)
    put('image-studio/overview/export-reviewed-image', {'path':'${root}/c8/export.png'},files=image,setup=[setup('neyvia.image.open',{'source':'${root}/c8/source.png'})])
    put('mobile-studio/overview/set-phone-frame', {'device':'pixel-9','orientation':'portrait'})
    put('mobile-studio/overview/build-chosen-platform', {'project':'${root}/c8-mobile','platform':'android'},setup=[setup('neyvia.app_sdk.new',{'path':'c8-mobile','name':'C8 Mobile','kind':'web'})],prerequisites=['Installed Android JDK/SDK/Gradle toolchain and a production buildable native project; do not install or download missing tools.'])
    put('awareness/overview/claim-and-review', {'files':['c8/input.txt'],'intent':'Inspect the disposable C8 artifact and release this local claim.'},files=disposable,deadlineSeconds=300)
    put('awareness/overview/verify-effect-work-claim', {'files':['c8/input.txt'],'intent':'Inspect the disposable C8 artifact.'},files=disposable)
    put('awareness/overview/verify-effect-work-release', {},
        setup=[setup('neyvia.work.claim',{'files':['c8/input.txt'],'intent':'Read the disposable C8 C8 binding artifact and release the local claim.'},'claim')],
        dynamicInputs={'id':dynamic('claim.claim.id')},files=disposable)
    put('awareness/prompt-amplification/prepare', {'requestId':'c8-local-amplification','text':'Read the disposable C8 artifact and state whether it contains the required phrase.'})
    put('neyvia-reference/renderer/show-observed-pane', {'kind':'file','target':'${root}/c8/input.txt'},files=disposable)
    for identity in ['awareness/overview/intent-template','working-with-paul/intent/scope-asks','working-with-paul/overview/intent-template','working-with-paul/reading/read-message']:
        put(identity,{'text':'Build and verify all local C8 journeys in this worktree. Preserve dirty work, commit locally, never push. Use the newest local copy. Do the reversible task yourself; do not drive my desktop.'})
    put('working-with-paul/overview/review-delivery',{'paths':['c8/input.txt']},files=disposable,deadlineSeconds=300)
    for identity in ['onboarding/overview/save-choices','onboarding/proofs-d-downloader/save-and-observe']:
        put(identity,{'interests':['notes','coding'],'completed':True})
    put('onboarding/overview/stage-chosen-pack', {'packId':'c8-local-fixture'}, prerequisites=['A real local pack manifest with matching SHA256 and signature, configured only in this candidate root; no global install and no external download.'])
    put('cross-pc/overview/read-remote-range', {'device':'c8-owner-paired-device','path':'c8/input.txt','offset':0,'length':32},prerequisites=['Owner-paired disposable remote PC and shared file. No discovery, Tailscale changes, credentials, or real peer contact without a scoped fixture.'])
    put('cross-pc/overview/take-file',{'device':'c8-owner-paired-device','from':'c8/input.txt','to':'${root}/c8/received.txt'},files=disposable,prerequisites=['Owner-paired disposable remote PC and read share; absent pairing is an environment failure.'])
    put('cross-pc/overview/send-to-inbox',{'device':'c8-owner-paired-device','from':'${root}/c8/input.txt'},files=disposable,prerequisites=['Owner-paired disposable remote PC and exact transfer approval for its inbox; never send to a real unapproved peer.'])
    put('cross-pc/overview/verify-taken-file',{'id':'c8-actual-take-transfer','to':'${root}/c8/received.txt','size':20},prerequisites=['A real completed Take receipt with returned transfer ID, source SHA256 and destination size. Never synthesize transfer success.'])
    put('tools-depth/tools/guarded-edit',{'path':'c8/input.txt','edits':[{'start':0,'end':2,'text':'C8d','expectedText':'C8'}],'expectedContent':'C8d journey artifact\n'},files=disposable)
    patch_source='C8 local patch fixture v1\n'
    put('tools-depth/tools/verify-effect-workspace-patch',
        {'path':'c8/workspace-patch.txt','expectedSha256':hashlib.sha256(patch_source.encode('utf-8')).hexdigest(),
         'edits':[{'start':0,'end':len(patch_source.encode('utf-8')),'text':'C8 local patch fixture v2\n','expectedText':patch_source}]},
        files=[file('c8/workspace-patch.txt',patch_source)])
    put('tools-depth/tools/cited-research',{'url':'${url}','query':'Neyvia'})
    # Check an actual component pair. Global token declarations and the shared
    # primitive backdrop have contracts distinct from component-only lint rules.
    css='web/src/neyvia/next/nxConductor.css'
    jsx='web/src/neyvia/next/NxConductor.jsx'
    for identity,values in {
        'design/accessibility/check-access':{'cssPath':css,'jsxPath':jsx},
        'design/check-loop/check-render':{'url':'${url}/control?ui=next','waitFor':'.nx-root'},
        'design/check-loop/check-component':{'cssPath':css,'jsxPath':jsx,'url':'${url}/control?ui=next','waitFor':'.nx-root'},
        'design/copy/review-copy':{'jsxPath':jsx},
        'design/craft/craft-check':{'requestPath':'.agent_control/craft/requests/c8.json','request':json.dumps({'files':[css,jsx],'url':'${url}','journal':'c8/craft.cl','skill':'manuals/skills/design-craft.cl'})},
        'design/details/prove-details':{'request':json.dumps({'url':'${url}','out':'proof/a2-details'})},
        'design/direction/find-references':{'query':'quiet compact operator interfaces'},
        'design/layout/phone-check':{'cssPath':css,'url':'${url}/control?ui=next','waitFor':'.nx-root'},
        'design/motion/check-motion':{'cssPath':css},
        'design/primitives/pick-primitive':{'jsxPath':jsx},
        'design/surfaces/new-pane':{'kind':'file','target':'${root}/c8/input.txt'},
        'design/surfaces/new-app-screen':{'appId':'notes'},
        'design/tokens-themes/theme-component':{'cssPath':css,'jsxPath':jsx},
    }.items(): put(identity,values)
    put('design/learned-capabilities/prove-pixel-advice',
        {'before':'${root}/c8/rendered-before.png','after':'${root}/c8/rendered-after.png'},
        prerequisites=['Requires two real rendered PNG captures under this isolated run root; the current fixture writer only admits bounded UTF-8 text and must not synthesize image files or pixel measurements.'])
    put('manuals-next/versions/inspect-history', {'id':'notes'})
    put('dictation/overview/transcribe-file',{'path':'${root}/c8/silence.wav','engine':'auto'},files=[{'path':'c8/silence.wav','kind':'wav','seconds':1}],prerequisites=['A ready installed local ASR engine; silence is an explicit audio fixture, never a fabricated transcription.'])
    put('dictation/prompts/teach-a-name',{'heard':'codex c eight fixture','aliases':['codex c eight fixture'],'name':'Codex C8 Fixture'})
    put('dictation/prompts/check-a-command',{'text':'undo that','op':'undo'})
    put('dictation/prompts/check-stays-text',{'text':'We should send it tomorrow after the review.'})
    put('autopilot/overview/verify-run',{'runId':'c8-actual-autopilot-run'},prerequisites=['A real completed autopilot run returned by production autopilot.start and independently verified; no model calls or generated completed receipts in fixtures.'])
    put('outputs/overview/publish-and-open',{'path':'c8/input.txt','kind':'file','requestId':'c8-publish'},files=disposable)
    put('outputs/overview/verify-effect-artifact-publish',{'path':'c8/input.txt'},files=disposable)
    put('outputs/navigation/request-pane',{'target':'${root}/c8/input.txt'},files=disposable)
    put('perception/navigation/request-pane',{'target':'${root}/c8/input.txt'},files=disposable)
    goal={'requestId':'c8-conductor','goal':'Read the disposable C8 artifact and verify its phrase.','folder':'${root}/c8','acceptanceChecks':['The exact phrase C8 journey artifact is present.'],'maxRuntimeSeconds':30}
    put('conductor/jobs/plan-goal',goal,files=disposable,prerequisites=['An available authorized local planning model; planning may contact the configured provider, never silently substitute it.'])
    put('conductor/jobs/inspect-job',{'id':'c8-actual-conductor-job'},prerequisites=['A returned actual conductor.plan job ID; fixtures do not fabricate planned jobs.'])
    for layer in ['app','browser','file','image','os','video','window']:
        source={'tool':'neyvia.settings.get','arguments':{}} if layer=='app' else {'path':'c8/input.txt'}
        extra={'files':disposable}
        if layer=='browser':
            source={'browserId':'runtime-setup-browser'}
            extra={'setup':[setup('neyvia.perception.browser.open',{'url':'${url}'},'browser')],'dynamicInputs':{'source':{'browserId':dynamic('browser.browserId')}}}
        if layer=='image': source={'path':'c8/source.png'};extra={'files':image,'prerequisites':['An installed local visual perception provider; image text/layout must be observed, never prefilled as a successful perception receipt.']}
        if layer=='video': source={'path':'c8/source.png','frame':0};extra={'files':image,'prerequisites':['A supported video frame source and installed visual provider; PNG-as-frame is an explicit unsupported-input probe if no provider accepts it.']}
        if layer=='os':source={};extra={}
        if layer=='window':source={'window_id':0};extra={}
        for procedure in ['read-layer','read-and-review']:put('perception/'+layer+'/'+procedure,{'source':source},**extra)
    # This procedure only observes renderer state after a visible PDF has been
    # opened and acknowledged. C8 has no registered PDF effect observer, so it
    # must not try to manufacture that UI state through setup actions.
    metadata['pdf/overview/verify-visible-highlight']={
        'setup':[],
        'dynamicInputs':{},
        'prerequisites':['A real PDF renderer/app must open the disposable source, render the selected highlight, and acknowledge it before these source-bound state checks can run; no registered C8 PDF effect observer can create that visible state.']
    }
    put('game-dev/bridges/review-completed-action', {'requestId':'c8-actual-editor-action'},prerequisites=['A completed real editor bridge action performed on the C11 agent desktop; never create editor action receipts by fixture.'])
    put('game-dev/bridges/validate-export-before-engine-load', {'path':'${root}/c8/scene.gltf'},files=[file('c8/scene.gltf',json.dumps({'asset':{'version':'2.0','generator':'C8 disposable fixture'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'name':'C8 node'}]}))])
    put('nightshift/board/chain-two',{'firstId':'c8-first','firstPrompt':'Read C8 local artifact.','secondId':'c8-second','secondPrompt':'Verify C8 local artifact.','folder':'${root}/c8','harness':'codex','model':'gpt-6.1-sol'},files=disposable)
    put('nightshift/board/tick-file',{'id':'c8-tick','path':'${root}/c8/input.txt'},files=disposable,setup=[setup('neyvia.nightshift.create',{'id':'c8-tick','prompt':'Read C8 local artifact.','folder':'${root}/c8','harness':'codex','model':'gpt-6.1-sol'})])
    put('nightshift/board/night-budget',{'nightSeconds':60,'holdPercent':80})
    put('transparency/overview/choose-detail',{'level':'everything'})
    put('transparency/overview/verify-effect-choose',{'level':'everything'})
    for procedure in ['stage-reviewed','record-review','record-blocked','capture-once','restore-selected']:
        source='${root}/c8/draft.md' if procedure!='restore-selected' else '${root}/c8/staged.md'
        target='${root}/c8/staged.md' if procedure!='restore-selected' else '${root}/c8/draft.md'
        put('handoff-recovery/intake/'+procedure,{'path':'c8-handoff.md','message':'\n# C8 '+procedure+'\nTask-local handoff receipt.\n','source':source,'target':target},files=[file('c8/staged.md' if procedure=='restore-selected' else 'c8/draft.md','C8 selected draft\n')],setup=[setup('neyvia.notes.write',{'path':'c8-handoff.md','body':'# C8 disposable handoff\n'})])
    put('mission-plan/orchestration/prepare',{'planPath':'${root}/c8/plan.md','folder':'${root}/c8','acceptanceChecks':['C8 artifact inspected.']},files=[file('c8/plan.md','# C8 dormant plan\n\n## §0 Shared rules\nUse only disposable local files. Never start work.\n| Track | Worktree | Backend | Vite |\n|---|---|---|---|\n| fixture | ${root}/c8 | assigned at runtime | assigned at runtime |\n\n## §1 fixture: inspect artifact\nRead the C8 artifact.\n')],prerequisites=['An actual disposable Git checkout under the isolated root, required by mission.from_plan; no fake .git marker.'])
    put('slim-installer/overview/inspect-release',{'path':'c8/actual-slim-release.json'},prerequisites=['An actual installer release receipt with build provenance and hashes; cannot use a fabricated release report.'])
    put('inception/release/inspect-release',{},priorReport='scripts/evidence/C8c.json')
    for chapter in ['overview','user-side']:put('remote/'+chapter+'/observe-allowed-window',{'connectionId':'C11-owner-allowed-remote','windowId':0})
    put('browser/backend/observe-tab',{'tabId':'runtime-setup-tab'},setup=[setup('neyvia.browser.open',{'url':'${url}','engine':'obscura'},'tab')],dynamicInputs={'tabId':dynamic('tab.tab.id')})
    put('browser/backend/open-native-tab',{'url':'${url}'})
    put('browser/backend/promote-task',{'tabId':'C11-owned-obscura-tab'})
    for procedure in ['verify','inspect']:
        values={'project':'${root}/c8-sdk'}
        seeds=[setup('neyvia.app_sdk.new',{'path':'c8-sdk','name':'C8 SDK','kind':'web'})]
        extra={}
        if procedure=='verify':
            values['url']='runtime-setup-sdk-url'
            seeds.append(setup('neyvia.app_sdk.preview',{'project':'${root}/c8-sdk','port':'${port}'},'preview'))
            extra['dynamicInputs']={'url':dynamic('preview.url')}
        put('app-sdk/overview/'+procedure,values,setup=seeds,**extra)
    put('scroll-generator/overview/validate-pack',{'pack':'c8-study'},files=[file('c8/study.md','# C8 Study\nA triangle has three sides.\n')],setup=[setup('neyvia.scroll.import',{'paths':['${root}/c8/study.md'],'packId':'c8-study','title':'C8 Study','subject':'geometry'})],prerequisites=['A genuinely generated and independently reviewed study pack from the imported source; importing a source alone cannot manufacture valid generated cards.'])
    put('scroll-generator/overview/import-notes',{'packId':'c8-import','paths':['${root}/c8/study.md']},files=[file('c8/study.md','# C8 Study\nA triangle has three sides.\n')])
    for procedure in ['preview-pack','export-pack']:
        put('scroll-generator/overview/'+procedure,{'pack':'c8-import'},setup=[setup('neyvia.scroll.import',{'paths':['${root}/c8/study.md'],'packId':'c8-import','title':'C8 Study','subject':'geometry'})],files=[file('c8/study.md','# C8 Study\nA triangle has three sides.\n')],dynamicInputs={'pack':dynamic('seed.packId')})
    put('language/overview/check-file',{'path':'c8/input.txt'},files=disposable)
    put('language/overview/check-text',{'text':'C8 journey artifact'})
    put('voice/overview/inspect-command',{'text':'open notes'})
    put('settings/overview/propose-change',{'patch':{'density':'calm'},'expectedRevision':0},setup=[setup('neyvia.settings.get',{},'preferences')],dynamicInputs={'expectedRevision':dynamic('preferences.revision')})
    put('settings/overview/verify-effect-propose',{'patch':{'density':'calm'},'expectedRevision':0},setup=[setup('neyvia.settings.get',{},'preferences')],dynamicInputs={'expectedRevision':dynamic('preferences.revision')})
    put('settings/overview/check-local-only', {}, setup=[setup('neyvia.settings.get', {}, 'prefs'), setup('backend:settings_update_command', {'patch': {'localOnly': True}, 'expectedRevision': dynamic('prefs.revision')}, 'localOnly')])

    put('adaptive-work/work/record-focus',
        {'workId':'c8-focus-fixture','text':'C8 disposable focus fixture; no work is claimed complete.'})
    put('adaptive-work/work/record-problem',
        {'workId':'c8-problem-fixture','text':'C8 disposable unresolved problem fixture.','blocker':'C8 fixture blocker remains open; no resolution is claimed.'})
    put('adaptive-work/work/record-constraint',
        {'workId':'c8-constraint-fixture','text':'C8 disposable constraint fixture; scoped to this candidate root.'})
    put('creative-records/local-records/record-situation-define',
        {'workId':'c8-situation-fixture','task':'C8 disposable situation proposal fixture.',
         'constraints':['Keep all effects inside this fresh candidate root.'],
         'acceptance':['The exact proposal is saved at revision 1.'],'expectedRevision':0})
    put('creative-records/local-records/record-attention-create',
        {'workId':'c8-attention-fixture',
         'arguments':{'experiment_id':'c8-attention-proposal',
                      'baseline_input':'C8 baseline prompt fixture',
                      'variant_input':'C8 variant prompt fixture',
                      'acceptance':{'kind':'response_contains','text':'C8 fixture marker'},
                      'requested_route':{},'budget':{'maxCalls':1}}})
    put('local-records/records/record-behavior-create',
        {'workId':'c8-behavior-work','experimentId':'c8-behavior-proposal',
         'baselineInput':'C8 baseline input fixture','variantInput':'C8 variant input fixture',
         'acceptance':{'kind':'response_contains','text':'C8 fixture marker'},
         'requestedRoute':{},'budget':{'maxCalls':1}})

    metadata.update({
        'creative-records/local-records/record-attention-observe': {'prerequisites':['No independent check and no real authorized provider/API observation is included.']},
    })

    native={
        'computer-use/drive/set-field-and-verify':('cua.inspect','Inspect an owner-allowed Notepad window on the isolated agent desktop, obtain its fresh Text element token, then cua.action(set_value).'),
        'computer-use/drive/@check/driver-ready':('cua.status','Observe isolated T16 driver readiness without binding UIA to Paul\'s input desktop.'),
        'computer-use/test-loop/launch-check-handoff':('cua.action','launch_app(notepad) must set STARTUPINFO.lpDesktop to the C11 agent desktop before app creation.'),
        'perception/os/read-layer':('perception.observe','layer=os requests T16 system_info; must use the C11 agent desktop provider.'),
        'perception/os/read-and-review':('perception.observe','layer=os requests T16 system_info; must use the C11 agent desktop provider.'),
        'perception/window/read-layer':('perception.observe','layer=window requests T16 inspect_window for a real isolated desktop window ID.'),
        'perception/window/read-and-review':('perception.observe','layer=window requests T16 inspect_window for a real isolated desktop window ID.'),
        'remote/overview/observe-allowed-window':('remote.snapshot','Snapshot an owner-allowed remote connection/window backed by C11 isolated desktop capture.'),
        'remote/user-side/observe-allowed-window':('remote.snapshot','Snapshot an owner-allowed remote connection/window backed by C11 isolated desktop capture.'),
        'browser/backend/open-native-tab':('browser.open','engine=webview2 creates a native webview; launch it only on the C11 agent desktop.'),
        'browser/backend/promote-task':('browser.promote','Promote the actual headless tab into visible WebView2 only on the C11 agent desktop.'),
        'native-runtime/native-runtime-proofs/observe-and-prove':('native-runtime.self-check','Native runtime proof cohort launches apps; every created window must be on C11 agent desktop.'),
        'proofs-b-desktop/@manual':('desktop proof observer','Observe desktop engine state and native action proof on the isolated C11 desktop; the manual has no executable procedures.'),
    }
    result={}
    missing_inputs=[]
    missing_decisions=[]
    resolved_prerequisites={
        'adaptive-work/work/record-focus',
        'adaptive-work/work/record-problem',
        'adaptive-work/work/record-constraint',
        'creative-records/local-records/record-situation-define',
        'creative-records/local-records/record-attention-create',
        'local-records/records/record-behavior-create',
    }
    for row in catalog['rows']:
        identity=row['id']
        _,_,manual=get_manual(row['manual'])
        chapter=manual.get('chapters',{}).get(row.get('chapter'),{})
        explicit=inputs.get(identity,old.get(identity,{}).get('inputs',{}))
        if (identity in native or identity.startswith(('computer-use/','browser/','research-assistant/','cross-pc/','remote/','perception/browser/'))
                or identity in {'tools-depth/tools/cited-research','tools-depth/tools/fetch-owned-http-body',
                                'autopilot/overview/verify-run','conductor/jobs/inspect-job',
                                'game-dev/bridges/review-completed-action','slim-installer/overview/inspect-release',
                                'onboarding/overview/stage-chosen-pack'}):
            # Remove legacy stand-ins such as window_id=0, invented run IDs,
            # dummy tab IDs and owner-device names before validating missing
            # slots. Those values cannot satisfy a live authority boundary.
            explicit={}
        if row.get('procedure')=='verify-and-record' and identity not in inputs and identity not in old:
            explicit={'report':{'events':[],'result':{}},'evidence':{},'outcomeQuality':0,'tokens':1}
            metadata[identity]={'prerequisites':['Actual hash-bound host evidence, independent task quality assessment and transport-reported usage are required. Empty report/evidence explicitly requests the missing-evidence failure path and cannot prove adherence.']}
        if not isinstance(explicit,dict):
            explicit={}
        required_inputs=set(row.get('inputs',{}).get('required',[]))
        blocked_dynamic_boundary=(identity in native or identity.startswith(('computer-use/','browser/','research-assistant/','cross-pc/','remote/','perception/browser/')))
        dynamic_specs=metadata.get(identity,{}).get('dynamicInputs',old.get(identity,{}).get('dynamicInputs',{}))
        if blocked_dynamic_boundary:
            # Never treat an owner-controlled browser/session result as a
            # local setup-derived value when the route below will be removed.
            dynamic_specs={}
        dynamic_fields=set(dynamic_specs) if isinstance(dynamic_specs,dict) else set()
        if isinstance(explicit,dict) and dynamic_fields:
            explicit=dict(explicit)
            for field in dynamic_fields:
                explicit.pop(field,None)
        missing_fields=required_inputs-set(explicit)-dynamic_fields
        deferred_inputs={field:deferred_input(identity,row,field) for field in sorted(missing_fields)}
        chosen={}
        deferred_judges={}
        # The prior registry has no source-bound decision receipts; do not
        # promote its static choice-table values into executable inputs.
        prior_decisions={}
        for name,judge in row.get('judges',{}).items():
            # Every authored judgement stays deferred until its real owner acts.
            value=prior_decisions.get(name)
            if value in judge['options']:
                chosen[name]=value
            else:
                deferred_judges[name]=deferred_judge(identity,name)
        for name,value in chosen.items():
            if value not in row['judges'][name]['options']:
                if value is None:
                    missing_decisions.append(identity+'/'+name)
                else:
                    raise ValueError('Invalid authored decision '+identity+'/'+name)
        tools=[]
        for step in row.get('steps',[]):
            if 'action' in step:
                tool=chapter.get('actions',{}).get(step['action'],{}).get('tool',step['action'])
                tools.append({'action':step['action'],'tool':tool,'registered':tool in registered})
        for check in row.get('checkContracts',{}).values():
            tools.append({'check':True,'tool':check['tool'],'registered':check['tool'] in registered})
        copies=set()
        for item in list(row.get('steps',[]))+list(row.get('checkContracts',{}).values()):
            path=item.get('args',{}).get('path')
            if isinstance(path,str) and (ROOT/path).is_file():copies.add(path)
        for value in explicit.values():
            if isinstance(value,str) and (ROOT/value).is_file():copies.add(value)
        source_fixtures=[]
        unbounded_source_copies=[]
        source_bytes=0
        for source in sorted(copies):
            candidate=ROOT/source
            try:
                if candidate.is_symlink() or candidate.is_junction():
                    raise ValueError('symlink or junction source')
                candidate=candidate.resolve()
                candidate.relative_to(ROOT.resolve())
                if not candidate.is_file():
                    raise ValueError('not a plain file')
                raw=candidate.read_bytes()
                if len(raw)>65536 or b'\0' in raw:
                    raise ValueError('over 64 KiB or binary')
                content=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
                source_bytes+=len(content.encode('utf-8'))
                source_fixtures.append(file(Path(source).as_posix(),content))
            except (OSError,UnicodeDecodeError,ValueError):
                unbounded_source_copies.append(source)
        fixture_files=list(metadata.get(identity,{}).get('files',old.get(identity,{}).get('files',[])))
        fixture_paths={entry.get('path') for entry in fixture_files if isinstance(entry,dict)}
        combined_files=fixture_files+[entry for entry in source_fixtures if entry['path'] not in fixture_paths]
        combined_bytes=sum(len(entry.get('content','').encode('utf-8')) for entry in combined_files if isinstance(entry,dict) and isinstance(entry.get('content',''),str))
        if len(combined_files)>16 or combined_bytes>262144 or source_bytes>262144:
            unbounded_source_copies.extend(entry['path'] for entry in source_fixtures)
            source_fixtures=[]
            combined_files=fixture_files
        procedure=chapter.get('procedures',{}).get(row.get('procedure')) if row['kind']=='procedure' else None
        if procedure:
            authored_actions=[step['action'] for step in procedure.get('steps',[]) if 'action' in step]
            authored_goals=[procedure['goal']]
        else:
            authored_actions=['Open the candidate in a headless T18 session',
                              'Inspect the source-bound '+identity+' contract and preserve its explicit boundary']
            authored_goals=row['checks'] or [row.get('goal','Observe authoritative manual state and report missing executable procedure')]
        binding={'sourceHash':row['sourceHash'],'journey':'manual','inputs':explicit,'decisions':chosen,'actions':authored_actions,'goals':authored_goals,'toolAvailability':tools,'scope':{'root':'${root}','network':'Only explicit task-local URL or prerequisite-approved provider','desktop':'Headless only; no Paul input desktop'},**metadata.get(identity,{})}
        if combined_files:
            binding['files']=combined_files
        else:
            binding.pop('files',None)
        if unbounded_source_copies:
            binding.setdefault('prerequisites',[]).append(
                'C8 blocked: source inputs exceed the bounded regular UTF-8 fixture contract: '+', '.join(sorted(set(unbounded_source_copies)))+'; owning CL/C8 source fixture receipt is required.')
        if procedure:
            # This exact current observer mapping is rechecked by the C8 worker
            # before any dispatch; it cannot be supplied by a generic goal.
            binding['contracts']=row.get('checkContracts',{})
            from grant_agent.cl.effects import supported as effect_supported
            unobserved=[]
            forbidden=('.terminal.','.cua.','.remote.','.browser.','.nas.','.gamedev.',
                       '.game_dev.','.native.','.web.','.research.','.image.generate',
                       '.mobile.build','.mobile.install','.app_sdk.build','.app_sdk.install',
                       '.provider.auth','.settings.propose','.files.trash')
            for action_step in procedure.get('steps',[]):
                if 'action' not in action_step:
                    continue
                action=chapter.get('actions',{}).get(action_step['action'],{})
                tool=action.get('tool')
                if not tool or any(token in ('.'+tool) for token in forbidden):
                    unobserved.append(action_step['action']+' ('+(tool or 'missing typed tool')+' requires an unadmitted C8 boundary)')
                elif not action_step.get('check') and not row.get('checkContracts') and not effect_supported(tool):
                    unobserved.append(action_step['action']+' ('+tool+' has no admitted owning effect observer)')
            if unobserved:
                binding.setdefault('prerequisites',[]).append(
                    'C8 blocked: '+', '.join(unobserved)+'; an owning effect observer or separately admitted runner is required before dispatch.')
        if deferred_inputs:
            binding['deferredInputs']=deferred_inputs
        if deferred_judges:
            binding['deferredJudges']=deferred_judges
        if identity in native:
            tool,step=native[identity]
            binding.setdefault('prerequisites',[]).append(
                'C8 blocked: '+tool+' requires the isolated C11 agent desktop. '+step)
        if row['kind']=='manual-without-procedures' and identity not in native:
            binding['prerequisites']=['The authoritative manual declares no executable procedure. Observe its declared state/tool, classify the missing executable journey as a journey source-authoring gap; do not invent a successful procedure.']
        if identity in old:
            generated_prerequisites=binding.get('prerequisites',[])
            binding={**binding,**old[identity]}
            binding['sourceHash']=row['sourceHash']
            binding['journey']='manual'
            binding['inputs']=explicit
            binding['decisions']=chosen
            for field in ('setup','dynamicInputs','deadlineSeconds'):
                if field in metadata.get(identity,{}):
                    binding[field]=metadata[identity][field]
            if identity in native or identity.startswith(('computer-use/','browser/','research-assistant/','cross-pc/','remote/','perception/browser/')):
                binding.pop('setup',None)
                binding.pop('dynamicInputs',None)
            if combined_files:
                binding['files']=combined_files
            else:
                binding.pop('files',None)
            if deferred_inputs:
                binding['deferredInputs']=deferred_inputs
            else:
                binding.pop('deferredInputs',None)
            if deferred_judges:
                binding['deferredJudges']=deferred_judges
            else:
                binding.pop('deferredJudges',None)
            if procedure:
                binding['actions']=authored_actions
                binding['goals']=authored_goals
                binding['contracts']=row.get('checkContracts',{})
            if deferred_inputs:
                binding['inputs']=explicit
                binding['deferredInputs']=deferred_inputs
            if deferred_judges:
                binding['decisions']=chosen
                binding['deferredJudges']=deferred_judges
            for field in ('nativeOnly','gitProjects','priorReport','sourceCopies'):
                binding.pop(field,None)
            inherited_prerequisites=([] if identity in resolved_prerequisites
                                     else old[identity].get('prerequisites',[]))
            authored_prerequisites=metadata.get(identity,{}).get('prerequisites',[])
            if old[identity].get('gitProjects'):
                authored_prerequisites=[*authored_prerequisites,
                    'C8 blocked: mission.from_plan requires a real disposable Git checkout in the candidate root; the legacy gitProjects metadata cannot manufacture one.']
            if old[identity].get('priorReport'):
                authored_prerequisites=[*authored_prerequisites,
                    'C8 blocked: the legacy priorReport path is not a fresh source-bound journey receipt; a current owner-produced report is required.']
            if old[identity].get('nativeOnly') and identity not in native:
                authored_prerequisites=[*authored_prerequisites,
                    'C8 blocked: legacy nativeOnly authority is not admitted by this headless route; use the named isolated native owner gate.']
            if identity in resolved_prerequisites:
                binding.pop('prerequisites',None)
            if generated_prerequisites or inherited_prerequisites or authored_prerequisites:
                binding['prerequisites']=list(dict.fromkeys([*generated_prerequisites,*inherited_prerequisites,*authored_prerequisites]))
        if procedure and binding.get('prerequisites'):
            binding['prerequisites']=list(dict.fromkeys(binding['prerequisites']))
        result[identity]=binding
    validation=validate_bindings(catalog,result)
    if not validation['valid'] or validation['unbound']:raise ValueError(validation)
    return result


if __name__=='__main__':
    bindings=author()
    (ROOT/'config/inception_journeys.json').write_bytes((json.dumps(bindings,indent=2,ensure_ascii=False)+'\n').encode('utf-8'))
    print(json.dumps({'bindings':len(bindings),'nativeWaiting':sum('nativeOnly' in row for row in bindings.values()),'prerequisiteRows':sum(bool(row.get('prerequisites')) for row in bindings.values())}))
