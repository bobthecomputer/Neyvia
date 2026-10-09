"""Re-run AUD4's exact 37 surfaces / 185 criteria on two source boundaries.

Fresh CL observations, grounded manual validation, conserved fixture bytes and
retained source-bound real receipts are separate evidence classes. Historical
AUD4 colours never seed the branch-before or branch-after matrix.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
METHOD = Path(r'C:\Users\user\Projects\plans\logs\audit4-cl.md')
ORIGINAL = Path(r'C:\Users\user\Projects\nx-audit4\scripts\evidence\AUD4.json')
AXES = ['semantic-state', 'cl-actions-goal-checks', 'executable-manual-use', 'side-right-pane', 'defining-mechanism']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_failure(value):
    if isinstance(value, dict):
        if value.get('schema') == 'fluxio.native_tool_receipt.v1' and value.get('ok') is False:
            return True
        return any(native_failure(child) for child in value.values())
    if isinstance(value, list):
        return any(native_failure(child) for child in value)
    return False


def source_hashes(source):
    paths = list((source / 'src/grant_agent').rglob('*.py'))
    paths += list((source / 'manuals/cl').glob('*.cl')) + list((source / 'manuals').glob('*.manual.json'))
    paths += [source / 'config' / name for name in ('neyvia_manuals.json', 'neyvia_apps.json', 'fixcl_manual_cache.json', 'neyvia_remote.json')]
    paths += [source / 'docs/standard/1.1/primer.md']
    return {path.relative_to(source).as_posix(): sha(path) for path in sorted(paths) if path.is_file()}


SURFACE_FAMILIES = {
    0: ['notes', 'workspace'], 1: ['native'], 2: ['notes'], 3: ['notes', 'workspace'],
    4: ['cua'], 5: ['runtime', 'session', 'codex', 'claude'], 6: ['app', 'voice'],
    7: ['app_sdk'], 8: ['pane', 'view'], 9: ['pane', 'browser'], 10: ['browser'],
    11: ['web', 'workflow'], 12: ['cua'], 13: ['cua'], 14: ['remote'],
    15: ['devices'], 16: ['notes'], 17: ['files'], 18: ['workspace'], 19: ['workflow', 'web'],
    20: ['web'], 21: ['perception'], 22: ['pdf'], 23: ['image'], 24: ['mobile'],
    25: ['gamedev'], 26: ['scroll'], 27: ['video'], 28: ['app'],
    29: ['lab', 'evolver', 'experiment', 'quality'], 30: ['skill', 'taste'],
    31: ['manual'], 32: ['efficiency', 'context', 'semantic', 'laya'],
    33: ['agents', 'conductor', 'mission', 'session', 'nightshift', 'schedule', 'autopilot'],
    34: ['settings', 'onboarding'], 35: ['dictation', 'voice'], 36: ['verify']}

# These are explicit unfinished product boundaries, not an assertion that all
# blocked tools need an outside account. A local fixture can exercise many.
FRONTIER_BOUNDARIES = {
    'codex.plugins.call': ('local-integration', True, 'Configured plugin dispatch lacks a fresh tool-specific postcondition; a disposable local plugin peer can prove transport only'),
    'host.inspect_preview': ('local-native-window', True, 'Fresh isolated application preview identity/visibility/content observer is missing; ordinary desktop inspection is outside this task'),
    'host.launch': ('local-native-window', True, 'No owned alternate desktop/new-window-set admission and fresh launched-instance receipt; visible desktop launch prohibited'),
    'host.launch_file': ('local-native-window', True, 'File association can launch a desktop window; no isolated instance/loaded-content effect observer'),
    'host.stop': ('local-native-window', True, 'Exact process/window ownership and fresh stopped-instance observation need an isolated fixture'),
    'laya.native.neyvia_navigation': ('outside-runtime', False, 'Installed LAYA/native navigation runtime is not connected to an assigned local proof port; no live product navigation authority'),
    'neyvia.agents.limits': ('local-owner-store', True, 'Limits update needs exact scoped durable owner readback and preserved unrelated agent limits'),
    'neyvia.app.open': ('local-rendered-alias', True, 'App route dispatch needs exact mounted app/runtime/content acknowledgement; registry label is insufficient'),
    'neyvia.app_sdk.preview': ('local-rendered-app', True, 'Generated project needs actual owned preview server, loaded artifact hash and mounted runtime acknowledgement'),
    'neyvia.app_sdk.verify': ('local-verifier', True, 'Actual generated app verifier result needs fresh project/build inputs and conserved artifacts; no witness retained'),
    'neyvia.artifact.open': ('local-rendered-alias', True, 'Artifact open needs current artifact bytes/hash and exact mounted content acknowledgement'),
    'neyvia.autopilot.get': ('local-reconciling-owner', True, 'Getter can reconcile/write job state; exact owner revision/conservation needs scoped admission'),
    'neyvia.autopilot.resume': ('local-provider-loop', True, 'Actual resumed durable job/provider work and fresh post-resume state have no admitted observer'),
    'neyvia.autopilot.start': ('local-provider-loop', True, 'Actual bounded job/provider loop needs owner grant, budget and fresh progress/completion receipt; declarations insufficient'),
    'neyvia.autopilot.stop': ('local-owner-store', True, 'Exact saved autopilot run, stopped status/reason and conserved prior work need a fresh durable fixture observer'),
    'neyvia.browser.capture': ('local-browser-artifact', True, 'Owned Obscura capture can be exercised locally; durable output image/hash and exact live tab/frame observer are missing'),
    'neyvia.browser.promote': ('outside-desktop-runtime', False, 'Actual connected WebView2 runtime on an authorized isolated desktop is required; visible windows are forbidden, so preserve the headless page and retain runtime-unavailable refusal'),
    'neyvia.browser.decide': ('local-consent-store', True, 'Exact live tab consent choice and saved grant/revocation must be freshly read; no site action inferred from permission'),
    'neyvia.conductor.control': ('local-provider-loop', True, 'Exact scoped existing turn control needs fresh durable job state and provider acknowledgement'),
    'neyvia.conductor.get': ('local-reconciling-owner', True, 'Durable conductor read/reconcile needs scoped owner state and explicit no-new-work boundary'),
    'neyvia.conductor.plan': ('local-provider-loop', True, 'Plan creation may start workers; actual bounded local provider plan/task graph needs fresh durable receipts'),
    'neyvia.cua.action': ('outside-native-input', False, 'No authorized isolated native target/window/input driver; ordinary desktop input forbidden'),
    'neyvia.dictation.transcribe': ('outside-asr', False, 'No real speech fixture/microphone and admitted ASR provider/model on assigned ports; text grammar is separate'),
    'neyvia.evolver.run': ('local-evaluation-loop', True, 'Real bounded candidate evaluation needs fresh experiment/artifact hashes and actual outcome evidence; local records are not improvement'),
    'neyvia.folder.open': ('local-native-window', True, 'Current opener can invoke desktop file manager; owned Files-pane alternative and mounted acknowledgement are missing'),
    'neyvia.gamedev.action': ('outside-editor', False, 'Actual selected editor session/action and frame/receipt need an installed connected engine; no engine process launched'),
    'neyvia.gamedev.asset_validate': ('local-validator', True, 'Installed Khronos validator + disposable glTF could prove validity; fresh source hash/result owner binding is missing'),
    'neyvia.gamedev.receipt': ('local-reconciling-owner', True, 'Receipt read can expire requests and change session inspection state; initializer also starts bridge, so not pure readonly'),
    'neyvia.gamedev.receipts': ('local-reconciling-owner', True, 'Receipt listing invokes deadline reconciliation; needs explicit local bridge initialization and preserved unrelated records'),
    'neyvia.gamedev.sessions': ('local-service-initializer', True, 'First bridge access initializes SQLite/disconnects prior sessions/starts websocket; needs explicit owned ports and exact retained session state'),
    'neyvia.gamedev.status': ('local-service-initializer', True, 'Bridge initialization has effects; engine detection itself is not a build/interact/export journey'),
    'neyvia.gamedev.setup': ('outside-editor', False, 'Bridge install requires an exact installed editor/project; no copies into external editors under this scope'),
    'neyvia.image.generate': ('outside-model', False, 'Actual image model/account generation and fresh pixel/source observation absent; local HTTP contract peer is not generated image proof'),
    'neyvia.manual.observe': ('local-owner-store', True, 'Saved manual feedback/benchmark report needs exact manual version, source and fresh persisted report observation'),
    'neyvia.manual.project': ('local-owner-store', True, 'Materialized project artifact needs fresh exact generated bytes/hash and original manual conservation'),
    'neyvia.mobile.build': ('outside-sdk', False, 'Actual Android build requires installed SDK/tools; no package build and device-compatible output proof'),
    'neyvia.mobile.install': ('outside-device', False, 'Actual connected phone/emulator and installed package receipt required; no device connection'),
    'neyvia.mobile.preview': ('outside-device', False, 'Actual owned phone/emulator frame/input journey required; launching a visible emulator is prohibited'),
    'neyvia.mobile.setup': ('outside-sdk', False, 'SDK/toolchain setup unproved; large extras/installers may exceed the download and launch limits'),
    'neyvia.native.runtime.self-check': ('local-release-verifier', True, 'Native self-check must prove actual bounded runtime path; no pytest launch or full release promotion permitted'),
    'neyvia.notes.open': ('local-rendered-alias', True, 'Exact note bytes and current mounted editor acknowledgement required; queued open event insufficient'),
    'neyvia.notify': ('local-rendered-notification', True, 'Actual rendered notification identity/content acknowledgement is missing; bus emission alone is not display'),
    'neyvia.onboarding.open': ('local-rendered-alias', True, 'Actual owned onboarding route/mount acknowledgement missing'),
    'neyvia.pane.observe': ('conditional-observation', True, 'Lazy empty-argument inventory may lack owning manual contract; actual scoped pane observation is separate from admitting a pane mutation'),
    'neyvia.remote.snapshot': ('conditional-outside-observation', False, 'Only explicit connectionId + int windowId is audited readonly; actual consented remote agent/window is missing'),
    'neyvia.scroll.concepts': ('outside-model', False, 'Actual model-produced concept extraction needs fresh bounded model output/corpus evidence; fixtures cannot prove teaching quality'),
    'neyvia.scroll.generate': ('outside-model', False, 'Real model course generation/job completion and conserved source/archive need provider account/model; imported local pack proof is separate'),
    'neyvia.settings.setup': ('local-installation', True, 'General runtime/setup installs need exact existing versions, bounded downloads and durable result; pinned sidebar provisioning is separate'),
    'neyvia.settings.network_check': ('local-network-fixture', True, 'Actual checked selected provider/endpoint result must bind assigned peer URL and fresh response; no public account check inferred'),
    'neyvia.verify': ('local-release-verifier', True, 'Actual branch verification report must be generated and source-bound; artifact integrity alone is not C7/C8 release correctness'),
    'neyvia.verify.status': ('conditional-reconciling-observation', True, 'Actual status may reconcile/write verifier owner state or lack lazy manual contract; no completed branch-wide verifier inferred'),
    'neyvia.view.arrange': ('local-rendered-layout', True, 'Exact requested pane layout/geometry must be observed in the mounted owned renderer'),
    'neyvia.view.float': ('local-rendered-layout', True, 'Floating surface needs isolated runtime/geometry acknowledgement; visible desktop windows forbidden'),
    'neyvia.view.scene': ('local-rendered-layout', True, 'Exact requested scene and mounted child/runtime identities lack a fresh observer'),
    'neyvia.voice.command': ('local-command-routing', True, 'Grammar dispatch routes many effects; each resolved intent needs its own fresh effect/receipt and replay-conservation gate'),
    'preview.annotate': ('local-preview-artifact', True, 'Exact persisted annotation geometry/content must bind the freshly captured source artifact'),
    'preview.screenshot': ('local-preview-artifact', True, 'Actual owned browser screenshot/source runtime and output bytes/hash need fresh observation; no desktop capture'),
    'preview.taste': ('local-visual-evaluation', True, 'Actual visual review needs fresh rendered input/hash and specific judged evidence; a generic score is insufficient'),
    'skill.live.iterate': ('local-skill-loop', True, 'Real skill edit/evaluate iteration needs fresh source/deliverable hashes, exact rule outcomes and unchanged keeper files'),
    'video.digest': ('local-video-artifact', True, 'Real disposable video inspection/digest could run locally; exact source/frame/time and persisted digest observation missing'),
    'web.fetch': ('local-document-effect', True, 'Actual local HTTP fetch exists; fresh immutable handle/source bytes and citation-owner effect gate/manual still needed')}
FRONTIER_BOUNDARIES['work.state'] = ('local-owner-initializer', True, 'Nominal state read creates the initial durable work JSON; exact initialized body/revision and conservation need a mutation receipt')
FRONTIER_BOUNDARIES.update({
    'neyvia.browser.history_clear': ('local-native-profile', True, 'Actual canonical profile history deletion and matching native cleanup callback must be observed; saved cleanup-pending is not cleared native history'),
    'neyvia.browser.permission_answer': ('outside-native-consent', False, 'Requires an actual native permission request and the human owner choice, followed by native acknowledgement; background per-action approvals are forbidden'),
    'neyvia.browser.permissions': ('outside-native-consent', False, 'Requires exact native pending/answered permission identity and current runtime; a fabricated permission request is not native browser consent'),
    'neyvia.browser.reader': ('outside-native-browser', False, 'Reader extraction is implemented by the connected WebView2 runtime; headless Obscura refuses this operation, and ordinary visible browsers are forbidden'),
    'neyvia.browser.shield': ('outside-native-browser', False, 'Native WebView2 hostname filtering requires owner authority and actual blocked-request counters; saved configuration alone does not prove protection'),
    'neyvia.cua.adapt': ('local-native-procedure', True, 'Requires a real isolated native application journey, checked owned document fields and saved grounded learned procedure; arbitrary UI recordings are not executable native contracts'),
    'neyvia.cua.flow': ('local-native-procedure', True, 'Requires replay of the exact admitted native procedure against a fresh owned document/window, with native field and persisted-file checks'),
    'neyvia.feedback.submit': ('local-feedback-owner', True, 'Requires exact saved feedback body, target run and source identity with fresh durable readback; storing criticism does not prove model improvement'),
    'neyvia.lessons.revert': ('local-lesson-owner', True, 'Requires a selected saved promoted lesson, exact revert status and conservation of unrelated skill/lesson versions'),
    'neyvia.nativeapp.close': ('local-native-document', True, 'Requires exact owned isolated Office process/document and fresh closed-instance receipt; background native ownership must be established before closing'),
    'neyvia.nativeapp.edit': ('local-native-document', True, 'Requires real owned Office document native fields, exact requested changes and unchanged unrelated cells/paragraphs; fixture JSON is insufficient'),
    'neyvia.nativeapp.open': ('local-native-document', True, 'Requires installed Office COM and an owned hidden document instance under the native isolated worker; ordinary desktop windows are forbidden'),
    'neyvia.nativeapp.persist': ('local-native-document', True, 'Requires actual Office save/reopen and exact native content/file receipt under the existing owned hidden session'),
    'neyvia.prompt.amplify': ('local-prompt-owner', True, 'Requires current prompt identity, real bounded selected-provider candidate, visible review and retained original text; no automatic send or hidden provider substitution'),
    'neyvia.prompt.edit': ('local-prompt-owner', True, 'Requires the exact staged prompt edit identity, mounted composer content and undo/conservation journey; generating alternative text is not a composer effect'),
})

FAMILY_SOURCE = {'codex': 'native_tools.py', 'host': 'native_tools.py', 'intelligence': 'model_tool_intelligence.py',
    'lab': 'improvement_tools.py', 'laya': 'native_tools.py', 'nas': 'native_tools.py', 'agents': 'native_tools.py',
    'app': 'neyvia_voice.py', 'app_sdk': 'neyvia_app_sdk.py', 'artifact': 'neyvia_workspace_tools.py',
    'autopilot': 'neyvia_autopilot.py', 'browser': 'neyvia_browser.py', 'conductor': 'neyvia_conductor.py',
    'cua': 'neyvia_cua.py', 'dictation': 'neyvia_dictation.py', 'evolver': 'neyvia_evolver.py',
    'folder': 'neyvia_workspace_tools.py', 'gamedev': 'neyvia_gamedev.py', 'image': 'neyvia_image_tools.py',
    'manual': 'neyvia_manuals.py', 'mobile': 'neyvia_mobile_studio.py', 'native': 'native_tools.py',
    'notes': 'neyvia_notes_tools.py', 'notify': 'neyvia_workspace_tools.py', 'onboarding': 'neyvia_settings.py',
    'pane': 'neyvia_panes.py', 'perception': 'neyvia_perception.py', 'remote': 'neyvia_remote.py',
    'scroll': 'neyvia_scroll.py', 'settings': 'neyvia_settings.py', 'verify': 'proof_verifier.py',
    'view': 'neyvia_workspace_tools.py', 'voice': 'neyvia_voice.py', 'preview': 'native_tools.py',
    'skill': 'cl_skill.py', 'video': 'video_tools.py', 'web': 'web_documents.py'}

LOCAL_OWNER_GAPS = {
    'behavior': 'Exact caller-reported experiment route/inputs/output record, distinct from verified measured behavior',
    'experiment': 'Exact frozen artifact bytes, launch/reset recipe and conserved restore fixture',
    'experience': 'Exact saved work-scoped comparison/investigation/note/trace record; user reports remain reported',
    'quality': 'Exact frozen acceptance criteria and saved instrument/comparison/challenge/repair/history/summary record; no model quality inference',
    'taste': 'Exact saved criteria/review evidence and protected artifact hashes; no rendered beauty claim',
    'orchestration': 'Actual parsed local plan artifact, exact bytes/hash and saved recipe; no worker task completion inferred',
    'context': 'Exact lossless archived transcript/protected instructions and retrievable conserved source bytes',
    'efficiency': 'Exact persisted cascade/transition/provenance metrics and owner revisions; no inference efficiency claim from records',
    'dictation': 'Exact saved vocabulary/style or processed prompt/context state; no microphone/transcription claim',
    'onboarding': 'Exact saved/mode/probe/admission/setup state and preserved unrelated settings; no installed app or model inferred',
    'impact': 'Exact actual repository source/change provenance in a disposable fixture; no unrelated worktree mutation',
    'time': 'Actual local clock/context observation; weather/account extras need a separately admitted source',
    'environment': 'Actual selected bounded local interpreter/environment/tool files and checksum/version readiness; no global interpreter changes',
    'manual': 'Exact canonical version, persisted frontier/feedback/compiled-plan/recovery bytes and real nested completion; declarations insufficient',
    'session': 'Exact durable provider/session state and actual local peer input/completion; no public model outcome inferred',
    'claude': 'Exact enabled flag/imported disabled asset manifest plus conserved owned SKILL bytes; no external model call inferred',
    'codex': 'Exact imported disabled asset/tool manifest and owned bytes; plugin execution requires its own postcondition',
    'mission': 'Exact source-bound prerequisite graph, paused/stopped/redirected owner state and preserved unrelated task records',
    'nightshift': 'Exact scoped dormant job/arming/stop/budget state and owner grant; no live provider loop inferred',
    'mobile': 'Actual selected local starter project files/hash and retained approval; SDK/device journeys separate',
    'evolver': 'Exact saved experiment/score/closure artifacts; a retained reported score is not demonstrated improvement',
    'semantic': 'Actual persisted evidence artifact checksums/provenance verification; semantic claims remain unproved',
    'devices': 'Actual paired single-file endpoint bytes, exact transfer identity/status/hash, no overwrite and fresh conservation'}
FAMILY_SOURCE.update({name: 'improvement_tools.py' for name in ('behavior', 'experiment', 'experience', 'quality', 'taste', 'orchestration', 'context')})
FAMILY_SOURCE.update(efficiency='neyvia_efficiency.py', impact='native_tools.py', time='neyvia_context_tools.py',
    environment='neyvia_environment.py', session='neyvia_workspace_tools.py', claude='native_tools.py',
    mission='neyvia_workspace_tools.py', nightshift='nightshift.py', semantic='semantic_tools.py', devices='neyvia_devices.py')
FAMILY_SOURCE['work'] = 'adaptive_work.py'


def frontier_boundaries(snapshot):
    source = Path(snapshot['sourceRoot'])
    rows = []
    for item in snapshot['actionInventory']:
        if item['effectStatus'] != 'frontier':
            continue
        name = item['tool']
        boundary = FRONTIER_BOUNDARIES.get(name)
        if name.startswith('nas.'):
            boundary = ('prohibited-by-user', False, 'NAS operations explicitly forbidden; no credential/runbook access or sync is attempted')
        elif name.startswith('intelligence.'):
            boundary = ('local-undefined-effect', True, name.rsplit('.', 1)[1] + ' needs a defined exact owning artifact/state transition and fresh conservation observer; a self-reported answer/brief is not the requested effect')
        elif name.startswith('lab.'):
            boundary = ('local-undefined-evaluation', True, name.rsplit('.', 1)[1] + ' needs exact frozen inputs, actual evaluation/journey outcomes and source-bound fresh comparison; no general causal/learning claim from saved records')
        elif name.startswith('neyvia.perception.browser.'):
            boundary = ('local-browser-alias', True, 'Perception ' + name.rsplit('.', 1)[1] + ' must bind the actual owned browser DOM/frame/runtime effect; adjacent browser adapter does not admit this alias')
        elif boundary is None and item['family'] in LOCAL_OWNER_GAPS:
            boundary = ('local-subject-bound-owner', True, name.rsplit('.', 1)[1] + ': ' + LOCAL_OWNER_GAPS[item['family']])
        if boundary is None:
            boundary = ('unclassified-explicit-gap', True, 'No precise boundary established for this newly encountered tool; requires owner inspection, not an external-dependency assumption')
        filename = FAMILY_SOURCE.get(item['family'], 'native_tools.py')
        relative = 'src/grant_agent/' + filename
        path = source / relative
        if not path.is_file():
            relative = 'src/grant_agent/native_tools.py'
            path = source / relative
        lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
        needle = name.removeprefix('neyvia.')
        line = next((index + 1 for index, value in enumerate(lines) if needle in value), None)
        rows.append({**item, 'boundaryCategory': boundary[0], 'localUnfinished': boundary[1],
            'preciseMissingMechanism': boundary[2], 'sourceEvidence': {'path': relative, 'line': line,
                'sha256': snapshot['sourceHashesAtStart'].get(relative)},
            'classificationEvidence': {'path': 'src/grant_agent/cl/effects.py', 'line': 38,
                'sha256': snapshot['sourceHashesAtStart']['src/grant_agent/cl/effects.py']},
            'inventoryArguments': {}, 'typedCodecDeclared': next(row['typedCodec'] for row in snapshot['families'] if row['family'] == item['family'])})
    return rows


def family(tool):
    return tool.removeprefix('neyvia.').split('.')[0]


def git_blobs(names):
    request = ''.join('152a5368:' + relative.replace('\\', '/') + '\n' for relative in names).encode()
    raw = subprocess.run(['git', 'cat-file', '--batch'], input=request, cwd=REPO, capture_output=True,
                         creationflags=0x08000000, check=True).stdout
    result, offset = {}, 0
    for relative in names:
        limit = raw.index(b'\n', offset)
        header = raw[offset:limit].decode()
        offset = limit + 1
        if header.endswith(' missing'):
            result[relative] = None
            continue
        size = int(header.rsplit(' ', 1)[1])
        result[relative] = raw[offset:offset + size]
        offset += size + 1
    return result


def retained(args):
    """Revalidate bytes, not agent reports or the historical audit colours."""
    evidence = REPO / 'scripts/evidence'
    paths = sorted(evidence.glob('FIXCL2-*.json'))
    if args.label == 'after':
        paths += sorted(evidence.glob('FIXCL3-*.json'))
        if getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'}:
            paths += sorted(evidence.glob('FIXCL4-*.json'))
            paths += [path for path in sorted((evidence / 'FIXCL4-regression').glob('*.json'))
                      if 'first-attempt' not in path.name and 'browser-ipc' not in path.name]
        if getattr(args, 'wave', 'FIXCL3') in {'FIXCL5', 'FIXCL6', 'FIXCL7'}:
            paths += sorted(evidence.glob('FIXCL5-*.json'))
            paths += [path for path in sorted((evidence / 'FIXCL5-regression').glob('*.json'))
                      if 'first-attempt' not in path.name and 'browser-ipc' not in path.name]
        if args.wave in {'FIXCL6', 'FIXCL7'}:
            paths += sorted(evidence.glob('FIXCL6-*.json'))
        if args.wave == 'FIXCL7':
            paths += sorted(evidence.glob('FIXCL7-*.json'))
        paths += [path for path in sorted((evidence / 'FIXCL3-regression').glob('*.json'))
                  if 'first-attempt' not in path.name and 'browser-ipc' not in path.name]
    proofs, boundaries = {}, {}
    candidates = []
    pinned = git_blobs([path.relative_to(REPO).as_posix() for path in paths]) if args.label == 'before' else {}
    for path in paths:
        if 'AUD4' in path.name:
            continue
        raw_receipt = pinned.get(path.relative_to(REPO).as_posix()) if args.label == 'before' else path.read_bytes()
        if raw_receipt is None:
            continue
        proof = json.loads(raw_receipt)
        start = proof.get('sourceHashesAtStart', proof.get('sourceHashes', {}))
        end = proof.get('sourceHashesAtEnd', start)
        if not isinstance(start, dict) or not start:
            continue
        candidates.append((path, proof, start, end, hashlib.sha256(raw_receipt).hexdigest()))
    object_hashes = {}
    if args.label == 'before':
        names = sorted({relative for _, _, start, _, _ in candidates for relative in start})
        for relative, blob in git_blobs(names).items():
            if blob is None:
                object_hashes[relative] = None
                continue
            object_hashes[relative] = {'gitBlob': hashlib.sha256(blob).hexdigest(),
                'windowsCheckoutCRLF': hashlib.sha256(blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest()}
    for path, proof, start, end, receipt_hash in candidates:
        receipt_name = path.relative_to(evidence).as_posix()
        mismatches, crlf_bindings = [], []
        for relative, digest in start.items():
            if args.label == 'before':
                forms = object_hashes[relative]
                observed = forms and forms['gitBlob']
                if forms and digest != observed and digest == forms['windowsCheckoutCRLF']:
                    crlf_bindings.append(relative)
                    observed = digest
            else:
                target = REPO / relative
                observed = sha(target) if target.resolve().is_relative_to(REPO) and target.is_file() else None
            if digest != observed:
                mismatches.append(relative)
        stable = start == end
        valid = stable and not mismatches
        boundaries[receipt_name] = {'sourceBound': valid, 'receiptSha256': receipt_hash, 'sourceCount': len(start),
            'receiptLocation': 'git:152a5368:scripts/evidence/' + receipt_name if args.label == 'before' else 'scripts/evidence/' + receipt_name,
            'sourceUnchangedDuringRun': stable, 'sourceMismatches': mismatches,
            'exactWindowsCheckoutCRLFBindings': crlf_bindings,
            'comparison': 'actual git 152a5368 blobs' if args.label == 'before' else 'fresh current worktree bytes',
            'passingChecks': [key for key, value in proof.get('checks', {}).items() if value is True],
            'failedChecks': [key for key, value in proof.get('checks', {}).items() if value is not True]}
        if valid:
            proofs[receipt_name] = proof
    return proofs, boundaries


def positive_uses(proofs, label='after'):
    found = []
    def add(use, receipt, pointer):
        if not isinstance(use, dict) or not use.get('effectChecks') or not use.get('tool'):
            return
        found.append({'receipt': receipt, 'pointer': pointer, 'tool': use['tool'], 'manual': use.get('manual'),
            'owningManual': (use.get('owningManual') or {}).get('manual'), 'procedure': use.get('procedure'),
            'actionIdentity': use.get('actionIdentity'), 'sourceSha256': use.get('sourceSha256'),
            'source': use.get('source'), 'effectSourceBindings': use.get('effectSourceBindings', {}),
            'owningManualBinding': use.get('owningManual')})
    def visit(value, receipt, pointer, all_checks):
        if isinstance(value, dict):
            if value.get('ok') is False:
                return
            if value.get('ok') is True and value.get('manualUse') and not native_failure(value.get('result')):
                checks = value.get('checks')
                if checks is None or all(item.get('passed') is True for item in checks if isinstance(item, dict)):
                    uses = value['manualUse'] if isinstance(value['manualUse'], list) else [value['manualUse']]
                    for index, use in enumerate(uses):
                        add(use, receipt, pointer + '/manualUse/' + str(index))
            positive = value.get('positiveCL')
            if isinstance(positive, dict) and positive.get('ok') is True and not native_failure(positive):
                for index, use in enumerate(value.get('manualReceipt', [])):
                    add(use, receipt, pointer + '/manualReceipt/' + str(index))
            if all_checks:
                for field in ('manualReceipts', 'manualUses'):
                    for index, use in enumerate(value.get(field, [])):
                        add(use, receipt, pointer + '/' + field + '/' + str(index))
            for key, child in value.items():
                if key in {'sourceHashesAtStart', 'sourceHashesAtEnd', 'manualUse', 'manualReceipt'}:
                    continue
                visit(child, receipt, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'), all_checks)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, receipt, pointer + '/' + str(index), all_checks)
    for receipt, proof in proofs.items():
        checks = proof.get('checks', {})
        visit(proof, receipt, '', bool(checks) and all(value is True for value in checks.values()))
    found = list({(row['receipt'], row['pointer'], row['tool']): row for row in found}.values())
    accepted, rejected = [], []
    hashes = {}
    for row in found:
        bindings = {'src/grant_agent/cl/' + name: digest for name, digest in row['effectSourceBindings'].items()}
        if row.get('source') and row.get('sourceSha256'):
            bindings[row['source'].replace('\\', '/')] = row['sourceSha256']
        owner = row.get('owningManualBinding') or {}
        if owner.get('source') and owner.get('sourceSha256'):
            bindings[owner['source'].replace('\\', '/')] = owner['sourceSha256']
        if label == 'after':
            mismatch = []
            for relative, digest in bindings.items():
                if not relative.startswith(('src/grant_agent/cl/', 'manuals/cl/')):
                    mismatch.append(relative + ': outside canonical module/manual binding')
                    continue
                if relative not in hashes:
                    target = (REPO / relative).resolve()
                    hashes[relative] = sha(target) if target.is_relative_to(REPO) and target.is_file() else None
                if digest != hashes[relative]:
                    mismatch.append(relative)
            if not row['effectSourceBindings']:
                mismatch.append('effectSourceBindings: missing')
            if mismatch:
                rejected.append({**row, 'bindingMismatches': mismatch})
                continue
        accepted.append(row)
    return accepted, rejected


def assess(args):
    snapshot = json.loads(args.snapshots.read_bytes())
    if snapshot['label'] != args.label or not all(snapshot['checks'].values()):
        raise ValueError('Fresh source snapshot did not pass its gates')
    source = args.source_dir.resolve()
    if snapshot['sourceHashesAtStart'] != source_hashes(source):
        raise ValueError('Fresh source snapshot drifted; re-run it')
    original = json.loads(ORIGINAL.read_bytes())
    proofs, boundaries = retained(args)
    uses, rejected_uses = positive_uses(proofs, args.label)
    pdf_runtime = proofs.get('FIXCL3-obscura-runtime.json', {}) if args.label == 'after' else {}
    pdf_visual_gap = (pdf_runtime.get('visualReady') is False and
                      pdf_runtime.get('visualChecks', {}).get('nativeTransformPixels') is False)
    pdf_receipt = next((name for name in ('FIXCL7-renderer-pdf.json','FIXCL6-renderer-pdf.json','FIXCL5-renderer-pdf.json','FIXCL4-renderer-pdf.json') if name in proofs), 'FIXCL4-renderer-pdf.json')
    faithful_pdf = proofs.get(pdf_receipt, {}) if getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'} else {}
    faithful_pdf_checks = faithful_pdf.get('checks', {})
    faithful_pdf_ready = (faithful_pdf.get('ok') is True and
                          faithful_pdf_checks.get('pdf.completedAllSixJourneys') is True and
                          faithful_pdf_checks.get('pdfFixtureContainsRealGraphicsAndImages') is True and
                          faithful_pdf_checks.get('sourceUnchanged') is True and
                          faithful_pdf_checks.get('builtArtifactUnchanged') is True)
    if faithful_pdf_ready:
        pdf_visual_gap = False
    faithful_pdf_evidence = {'receipt': pdf_receipt, 'checks': list(faithful_pdf_checks)}
    pdf_visual_evidence = {'receipt': 'FIXCL3-obscura-runtime.json', 'pointer': '/observed/canvas'}
    def passed(name, *checks):
        names = [name.replace('FIXCL2-', 'FIXCL3-'),
                 'FIXCL3-regression/' + name.removeprefix('FIXCL2-'), name] if args.label == 'after' else [name]
        if getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'} and args.label == 'after':
            names.insert(0, name.replace('FIXCL2-', 'FIXCL4-').replace('FIXCL3-', 'FIXCL4-'))
            names.insert(0, 'FIXCL4-regression/' + name.removeprefix('FIXCL2-').removeprefix('FIXCL3-'))
            if args.wave in {'FIXCL5', 'FIXCL6', 'FIXCL7'}:
                names.insert(0, name.replace('FIXCL2-', 'FIXCL5-').replace('FIXCL3-', 'FIXCL5-'))
                names.insert(0, 'FIXCL5-regression/' + name.removeprefix('FIXCL2-').removeprefix('FIXCL3-'))
            if args.wave in {'FIXCL6', 'FIXCL7'}:
                names.insert(0, name.replace('FIXCL2-', 'FIXCL6-').replace('FIXCL3-', 'FIXCL6-').replace('FIXCL4-', 'FIXCL6-'))
        if args.wave == 'FIXCL7':
            names.insert(0, name.replace('FIXCL2-', 'FIXCL7-').replace('FIXCL3-', 'FIXCL7-').replace('FIXCL4-', 'FIXCL7-').replace('FIXCL5-', 'FIXCL7-'))
            aliases = {'FIXCL2-frontier-local':'FIXCL7-frontier', 'FIXCL3-manual':'FIXCL7-manual-execution'}
            if name in aliases: names.insert(0, aliases[name])
        for identity in dict.fromkeys(names):
            receipt = identity + '.json'
            proof = proofs.get(receipt)
            if proof and all(proof.get('checks', {}).get(key) is True for key in checks):
                return {'receipt': receipt, 'checks': list(checks)}
        return None
    rows = []
    side_missing = {4, 12, 13, 14, 24, 25}
    no_app = {27, 28}
    for index, old in enumerate(original['matrix']):
        snap = snapshot['snapshots'][str(index)]
        evidence = [{'receipt': args.snapshots.name, 'pointer': '/snapshots/' + str(index)}]
        relevant = [use for use in uses if family(use['tool']) in SURFACE_FAMILIES[index]]
        explicit_action = None
        if index == 10:
            explicit_action = passed('FIXCL2-browser', 'cl_open_and_done', 'cl_manual_procedure_and_done', 'stale_revision_refused')
        elif index == 17:
            explicit_action = passed('FIXCL2-frontier-local', 'all_actions', 'missing_refused', 'source_unchanged')
        elif index == 26:
            explicit_action = passed('FIXCL2-documents', 'scroll_cl_import_and_done', 'scroll_cl_pack_and_done', 'scroll_corrupt_archive_refused')
        elif index == 22 and args.label == 'after':
            explicit_action = faithful_pdf_evidence if faithful_pdf_ready else passed('FIXCL3-renderer', 'pdf.open.freshCL', 'pdf.actualTwoPages', 'pdf.actualReady')
        cells = []
        def cell(status, finding, extra=()):
            cells.append({'axis': AXES[len(cells)], 'status': status, 'finding': finding,
                          'evidence': evidence + list(extra)})
        semantic = snap['typedRows'] and not native_failure(snap['result'])
        if index == 20:
            doc = passed('FIXCL2-documents', 'web_passages_typed_read', 'web_cite_typed_read')
            if not doc and getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'}:
                doc = passed('FIXCL4-research', 'sourceUnchanged', 'actualPublicFetch-semantics',
                             'actualPublicFetch-caching', 'exactClCitation-challenge',
                             'exactClCitation-insufficient', 'exactClCitation-no-store', 'exactClCitation-no-cache')
            semantic = bool(doc)
            if doc:
                evidence.append(doc)
        cell('G' if semantic else ('R' if index == 4 or index in no_app else 'A'),
             'Fresh bounded typed E rows from the owning CL observer; empty states prove projection only' if semantic else
             'No semantic CL surface in admitted direct driver transport' if index == 4 else
             'Complete application semantic state is absent' if index in no_app else
             'No successful typed CL observation for this exact surface; inventory or adjacent proxy is partial')
        if index in {0, 16}:
            cell('G', 'Real notes procedure, exact independently read bytes, fresh done G and false-goal refusal',
                 [{'receipt': args.snapshots.name, 'pointer': '/transcripts/notesProcedure'}])
        elif explicit_action:
            cell('G', 'Real CL action and explicit done G with independent effect and refusal checks retained in the source-bound harness receipt', [explicit_action])
        elif relevant:
            cell('G', 'Bounded owning effect(s) actually called through CL with fresh effect predicates; unexecuted family actions remain separate', relevant)
        else:
            tools = [tool for tool in snapshot['actionInventory'] if tool['family'] in SURFACE_FAMILIES[index]]
            gap = index == 4 or index in no_app or bool(tools) and all(tool['effectStatus'] == 'frontier' for tool in tools)
            cell('R' if gap else 'A', 'No admitted local effect witness for the named mechanism; available read-only observations and static adapter declarations do not prove an effect')
        manual = old.get('manual')
        validation = snapshot['manualValidation'].get(manual, {})
        used = [use for use in relevant if manual in {use.get('manual'), use.get('owningManual')}]
        if index in {0, 16}:
            cell('G', 'Canonical notes.write-and-pin executable procedure actually loaded and completed',
                 [{'receipt': args.snapshots.name, 'pointer': '/transcripts/notesProcedure'}])
        elif index == 10 and validation.get('ok') is True and passed('FIXCL2-browser', 'manual_obscura_open_completed', 'cl_manual_procedure_and_done'):
            cell('G', 'Exact browser.open-obscura-tab owning procedure actually completed and actual DOM observed',
                 [passed('FIXCL2-browser', 'manual_obscura_open_completed', 'cl_manual_procedure_and_done')])
        elif used and validation.get('ok') is True:
            cell('G', 'Exact owning executable manual used by the retained source-bound positive CL action', used)
        elif not manual:
            cell('R', 'No executable manual for this complete application entry')
        elif validation.get('ok') is False and 'PermissionError' not in validation.get('errorType', ''):
            cell('R', 'Actual grounded manual validation failed: ' + validation.get('error', '')[:300],
                 [{'receipt': args.snapshots.name, 'pointer': '/manualValidation/' + manual}])
        else:
            cell('A', 'Manual schema validation or guarded availability is partial; no exact owning procedure use retained',
                 [{'receipt': args.snapshots.name, 'pointer': '/manualValidation/' + manual}])
        renderer = passed('FIXCL3-renderer' if args.label == 'after' else 'FIXCL2-renderer',
                          'file.ackArrives', 'file.doneAfterAck', 'browserOwned.ackArrives', 'browserOwned.doneAfterAck')
        mounted_sdk = passed('FIXCL4-sdk-mount', 'sdk.previewActualPositiveCL', 'sdk.exactMountedFrame',
            'sdk.actualMountedControlChangesState', 'sdk.nativeAppPixelsPresent', 'sdk.currentManualEffectReceipt',
            'sdk.mountedObservationManualContract',
            'sdk.changedSourceRefusesDone', 'sdk.occludedFrameRefusesDone', 'sdk.unmountedRuntimeRefusesDone')
        if index in {7, 24} and mounted_sdk:
            cell('G', 'Actual mounted Phone child realm identity, SDK increment and native iframe pixels, with source drift, occlusion and unmount refusals; no physical device build claim', [mounted_sdk])
        elif index in {8, 9, 10, 18} and renderer:
            cell('G', 'Actual built Neyvia UI in owned Obscura: displayed content, mounted runtime identity and exact fresh renderer acknowledgement; real SSE frames relayed through EventSource stand-in', [renderer])
        elif index == 22 and faithful_pdf_ready:
            cell('G', 'Real PDF vector/font/image page pixels painted into the owned Neyvia canvas with exact raster digest, text search and highlights; all six CL journeys completed', [faithful_pdf_evidence])
        elif index == 22 and pdf_visual_gap:
            cell('R', 'Actual owned Obscura native canvas ignores translate pixels and lacks getTransform; parsed page count/readiness cannot prove a rendered PDF', [pdf_visual_evidence])
        elif index == 22 and explicit_action:
            cell('A', 'PDF parser/owner acknowledgement passed, but no genuine native canvas pixel/transform proof; page count/readiness do not prove rendered PDF content', [explicit_action])
        elif index in side_missing:
            cell('R', 'Required outside/native device runtime or isolated rendered application is not available in this authority; no window/input journey claimed')
        else:
            cell('A', 'Exact rendered side-pane journey is unexecuted or only adjacent content was rendered; event dispatch is insufficient')
        mechanism = None
        detail = 'Partial local seams only; the full named defining journey has not been executed'
        if index in {0, 16}:
            mechanism = {'receipt': args.snapshots.name, 'pointer': '/transcripts/notesProcedure'}
            detail = 'Actual note bytes and fresh explicit completion, with false-goal refusal'
        elif index == 1:
            mechanism = {'receipt': args.snapshots.name, 'pointer': '/snapshots/1'}
            detail = 'Real native catalog and exact schemas; discovery does not imply every effect is available'
        elif index == 2 and snap['result'].get('ok') is True:
            mechanism = evidence[0]
            detail = 'Actual initialize/tools-call JSON-RPC handler and typed CL read, in-process; no spawned stdio transport claim'
        elif index == 3:
            mechanism = passed('FIXCL2-authority', 'issuedOwnerSessionValidBeforeHTTP', 'ownerMutationExactBytesAndPin', 'guestForbidden', 'rawMutationCannotBypassCL')
            detail = 'Real authenticated owner HTTP, independent bytes and guest/raw bypass denials; separate plugin catalog boundary'
        elif index == 7:
            verified_sdk = passed('FIXCL4-browser-sdk', 'sdk-verify.positiveCL', 'sdk-verify.driftRefused',
                'sdk-verify.restorationRevalidates', 'sdk-source.driftRefused', 'sdk-source.restorationRevalidates')
            if mounted_sdk and verified_sdk:
                mechanism = mounted_sdk
                detail = 'Generated SDK app verifies against real shared state and actual mounted increment/pixels; source and screenshot drift withdraw completion'
        elif index in {8, 9}:
            mechanism = renderer
            detail = 'Fresh mounted content acknowledged by the actual built pane in owned Obscura; no desktop WebView2 claim'
        elif index == 10:
            mechanism = passed('FIXCL2-browser', 'real_first_page_content', 'fill_exact_dom_value', 'click_changed_actual_dom', 'navigation_actual_second_page', 'cl_manual_procedure_and_done')
            detail = 'Actual hidden Neyvia Obscura DOM open/fill/click/navigate/back/pin/close; local fixtures only'
            if not mechanism and args.label == 'after':
                mechanism = passed('FIXCL3-renderer', 'browserOwned.runtimeIsAnOwnedTab', 'browserOwned.showsThePage', 'browserOwned.doneAfterAck')
                detail = 'Actual built Browser pane opens an owned headless Obscura tab, displays local page content and completes after exact fresh acknowledgement; full DOM action set/WebView2 remain separate'
        elif index == 15 and args.label == 'after':
            mechanism = passed('FIXCL3-device-pdf', 'actualOwnerPairingAndDpapi', 'fetchPositiveClWitness', 'sendPositiveClWitness', 'sameMetadataChangedRemoteBytesInvalidateDone', 'revokedPairRefusesNewCopy')
            detail = 'Actual production DPAPI pairing, HTTP chunk/upload transport and conserved single-file hashes between disposable local peers; physical second PC still unexecuted'
        elif index == 17:
            mechanism = passed('FIXCL2-frontier-local', 'all_actions', 'source_unchanged')
            detail = 'Actual file pin/rename/move/restore and fresh independent state, with stale/missing refusals; recycle-bin desktop integration unexecuted'
        elif index == 20:
            mechanism = passed('FIXCL2-documents', 'web_local_http_fetch_real', 'web_passages_typed_read', 'web_cite_typed_read', 'web_cached_source_unchanged')
            detail = 'Real local HTTP fetch, immutable handle, passages and exact citation; public search/answer accuracy unexecuted'
            if not mechanism and getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'}:
                mechanism = passed('FIXCL4-research', 'sourceUnchanged', 'actualPublicFetch-semantics',
                                   'actualPublicFetch-caching', 'exactClCitation-challenge',
                                   'exactClCitation-insufficient', 'exactClCitation-no-store', 'exactClCitation-no-cache',
                                   'fabricatedCitationRefused', 'changedEvidenceRefusesCompletion')
                detail = 'Actual public RFC documents, immutable handles, bounded passages and four exact cited clauses; source URLs were supplied, and DuckDuckGo discovery remains failed'
        elif index == 19 and getattr(args, 'wave', 'FIXCL3') in {'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'}:
            mechanism = passed('FIXCL4-research', 'sourceUnchanged', 'actualPublicFetch-semantics',
                               'actualPublicFetch-caching', 'fourPublicGoldAnswers', 'requestedSolActualUsage',
                               'positiveResearchClDone', 'exactClCitation-challenge', 'exactClCitation-insufficient',
                               'exactClCitation-no-store', 'exactClCitation-no-cache', 'fabricatedCitationRefused',
                               'changedEvidenceRefusesCompletion', 'restoredEvidenceCompletes')
            detail = 'Actual public RFC fetch/passages/citations and requested GPT-6 Luna answers passed four frozen gold facts, compiled research completion and forged/drift refusals; supplied source URLs do not prove search discovery or browser feature parity'
        elif index == 22 and args.label == 'after':
            if faithful_pdf_ready:
                mechanism = faithful_pdf_evidence
                detail = 'Actual faithful source-bound PDF canvas pixels, page/zoom/search/text and rectangle highlights with fresh CL completion and drift refusals'
            else:
                detail = 'Actual local PDF metadata/text extraction is proven; native canvas rendering/transform capability, highlights/search and complete PDF visual journey remain unproved'
        elif index == 31 and args.label == 'after':
            mechanism = passed('FIXCL3-manual', 'compile_cl_completed_from_three_distinct_real_runs',
                               'script_cl_completed_fresh_body', 'recover_cl_completed_new_verified_effect', 'source_unchanged')
            detail = 'Actual source-bound manual compile/run and recovery; promotion or general model improvement is not inferred'
        red = index in {4, 11, 12, 13, 14, 19, 24, 25, 27, 28, 36} or index == 15 and args.label == 'before' or index == 22 and pdf_visual_gap
        cell('G' if mechanism else 'R' if red else 'A', detail if mechanism else
             'Concrete defining gap: ' + {
                 4: 'direct driver rejects the assigned proof port and bypasses the CL host',
                 11: 'public evidence-producing Search/fusion workflow has no retained real benchmark',
                 12: 'isolated native application/driver journey unavailable', 13: 'isolated live native frame/input loop unavailable',
                 14: 'no approved remote desktop agent/device connection', 15: 'no actual peer transfer witness at baseline',
                 19: 'no public research-to-answer pipeline run', 24: 'no Android SDK/device build/install/user journey',
                 22: 'actual native Canvas2D transform/getTransform failure prevents faithful PDF raster rendering; metadata/text extraction works',
                 25: 'no Godot/Unity/Roblox/Blender editor build/interact/export journey',
                 27: 'inspection tools do not implement the complete video editing application',
                 28: 'Coming registry entries do not implement these applications',
                 36: 'full C7/C8 release matrix has not been run on this branch'}.get(index, detail) if red else detail,
             [mechanism] if mechanism else [pdf_visual_evidence] if index == 22 and pdf_visual_gap else relevant[:3])
        rows.append({'surface': old['surface'], 'owner': old['owner'], 'manual': manual, 'cells': cells})
    counts = Counter(cell['status'] for row in rows for cell in row['cells'])
    family_rows = deepcopy(snapshot['families'])
    for row in family_rows:
        row['positiveCLWitnesses'] = [use for use in uses if family(use['tool']) == row['family']]
        row['witnessedTools'] = sorted({use['tool'] for use in row['positiveCLWitnesses']})
        row['freshBoundedObservations'] = [{'receipt': args.snapshots.name, 'pointer': '/snapshots/' + str(index),
            'typedRows': snapshot['snapshots'][str(index)]['typedRows']}
            for index in range(37) if (row['family'] in SURFACE_FAMILIES[index] or row['family'] == 'cl' and index in {0, 2})
            and snapshot['snapshots'][str(index)]['result'].get('ok') is True
            and not native_failure(snapshot['snapshots'][str(index)]['result'])]
        row['boundary'] = 'Typed codec / static effect status / manual binding are declarations; only listed source-bound positive CL witnesses prove their exact bounded effects'
    apps = deepcopy(snapshot['apps'])
    for app in apps:
        app['positiveExactAppWitnesses'] = [use for use in uses if app['id'] in {use['manual'], use['owningManual']}]
        app['renderedCompleteApplicationProven'] = False
        app['exactManualValidationDetail'] = snapshot['manualValidation'].get(app['id'], {'status': 'unregistered'})
    result = {'schema': 'neyvia.FIXCL3.AUD4.matrix.v1', 'label': args.label,
        'method': {'path': str(METHOD), 'sha256': sha(METHOD), 'surfaces': 37, 'cells': 185,
                   'legend': {'G': 'named bounded mechanism passed a real call', 'A': 'partial or unexecuted defining journey', 'R': 'concrete gap, substitute or unavailable required mechanism'}},
        'originalHistoricalOnly': {'source': str(ORIGINAL), 'sha256': sha(ORIGINAL), 'counts': {'G': 16, 'A': 89, 'R': 80}},
        'sourceBoundary': {'root': str(source), 'baselineCommit': '152a5368' if args.label == 'before' else None,
                           'sourceHashes': snapshot['sourceHashesAtStart']},
        'freshSnapshot': {'receipt': args.snapshots.name, 'sha256': sha(args.snapshots)},
        'auditHarness': {'path': 'scripts/fixcl3_aud4_matrix.py', 'sha256': sha(Path(__file__))},
        'counts': dict(counts), 'matrix': rows, 'families': family_rows, 'apps': apps,
        'retainedReceiptBoundaries': boundaries, 'positiveManualUses': uses,
        'rejectedPositiveManualUses': rejected_uses,
        'maskedNativeFailures': [{'surface': index, 'receipt': args.snapshots.name, 'pointer': '/snapshots/' + str(index),
            'outerReportedSuccess': snapshot['snapshots'][str(index)]['result'].get('ok') is True,
            'boundary': 'A failed native receipt is never a semantic success even if outer CL says ok and projects an empty E row'}
            for index in range(37) if native_failure(snapshot['snapshots'][str(index)]['result'])],
        'frontierBreakdown': dict(Counter(row['effectStatus'] for row in snapshot['actionInventory'])),
        'remainingFrontierBoundaries': frontier_boundaries(snapshot),
        'checks': {'exact37Surfaces': len(rows) == 37, 'exact185Cells': sum(len(row['cells']) for row in rows) == 185,
                   'countsTotal185': sum(counts.values()) == 185, 'historicalRatingsNotCopied': True,
                   'freshSnapshotSourceUnchanged': snapshot['sourceHashesAtStart'] == source_hashes(source),
                   'completeNativeRegistryAppendix': sum(row['tools'] for row in family_rows) == snapshot['nativeCatalogCount'],
                   'allAppEntriesIncluded': len(apps) == len(snapshot['apps'])},
        'limitations': ['No external account/device authority; native input, microphone, Android and engine editors unexecuted.',
                        'Local peer/provider/PDF fixtures prove their exact local boundaries; real devices/accounts remain distinct.',
                        'Source drift invalidates retained receipts; rejected maps and failed named checks are kept above.',
                        'No full C7/C8 product release proof; this is the exact AUD4 surface matrix, not release promotion.']}
    if args.label == 'after':
        result['checks']['allRemainingFrontierHaveSpecificBoundary'] = all(row['boundaryCategory'] != 'unclassified-explicit-gap' for row in result['remainingFrontierBoundaries'])
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    frontier_result = {'schema': 'neyvia.FIXCL3.AUD4.frontier-boundaries.v1', 'label': args.label,
        'matrixReceipt': args.output.name, 'matrixSha256': sha(args.output), 'breakdown': result['frontierBreakdown'],
        'remaining': result['remainingFrontierBoundaries'],
        'boundaryCategories': dict(Counter(row['boundaryCategory'] for row in result['remainingFrontierBoundaries'])),
        'localUnfinished': sum(row['localUnfinished'] for row in result['remainingFrontierBoundaries']),
        'outsideOrProhibited': sum(not row['localUnfinished'] for row in result['remainingFrontierBoundaries']),
        'inventoryBoundary': 'Exact leaf inventory after the same 37 AUD4 observations; args={} deliberately remains conservative for scoped/overloaded observers'}
    args.output.with_name(args.output.stem + '-frontier.json').write_text(json.dumps(frontier_result, indent=2) + '\n', encoding='utf-8', newline='\n')
    lines = ['# FIXCL3 AUD4 ' + args.label, '',
        'Exact original 37 surfaces × five criteria: ' + str(counts['G']) + ' green, ' + str(counts['A']) + ' amber, ' + str(counts['R']) + ' red.', '',
        'Historical AUD4 16/89/80 is separate. Green proves the named bounded real call; amber is partial/unexecuted, red is a concrete gap. No release promotion is claimed.', '',
        '| Surface | Semantic CL | CL effects + goals | Manual used | Side pane | Defining mechanism |',
        '|---|---|---|---|---|---|']
    for row in rows:
        lines.append('| ' + row['surface'].replace('|', '\\|') + ' | ' + ' | '.join(cell['status'] for cell in row['cells']) + ' |')
    lines += ['', '## Exact cell findings', '']
    for row in rows:
        lines += ['### ' + row['surface'], '']
        for cell in row['cells']:
            refs = ', '.join(ref['receipt'] + '#' + ref.get('pointer', '/checks/' + ','.join(ref.get('checks', []))) for ref in cell['evidence'])
            lines.append('- ' + cell['axis'] + ' **' + cell['status'] + '**: ' + cell['finding'] + ' Evidence: ' + refs)
        lines.append('')
    lines += ['## Complete family appendix', '',
        'The actual source registry has ' + str(len(family_rows)) + ' families. Every tool, manual binding, static effect classification and exact witnessed tool is retained in the JSON. Witness coverage does not imply the remaining family actions are proven.', '',
        '| Family | Tools | Manual-bound | Typed codec | Effect classifications | Positive witnessed tools |', '|---|---:|---:|---|---|---|']
    for row in family_rows:
        lines.append('| ' + row['family'] + ' | ' + str(row['tools']) + ' | ' + str(row['manualBoundTools']) + ' | ' + str(row['typedCodec']) + ' | ' + json.dumps(row['effectClassifications']) + ' | ' + ', '.join(row['witnessedTools']) + ' |')
    lines += ['', '## Complete app registry appendix', '',
        'Registry ready/coming labels are declarations. Exact manual use is reported separately from a complete rendered app journey; none is inferred from a catalog entry.', '',
        '| App | Registry status | Exact manual registered | Exact manual validated | Positive exact manual witnesses | Complete rendered app |', '|---|---|---|---|---:|---|']
    for app in apps:
        lines.append('| ' + app['id'] + ' | ' + str(app.get('status', app.get('state', 'declared'))) + ' | ' + str(app['exactManualRegistered']) + ' | ' + str(app['exactManualValidated']) + ' | ' + str(len(app['positiveExactAppWitnesses'])) + ' | Unexecuted |')
    lines += ['', '## Remaining outside boundaries', '']
    lines += ['- ' + value for value in result['limitations']]
    args.output.with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(args.output), 'counts': dict(counts), 'sourceBoundReceipts': len(proofs), 'positiveManualUses': len(uses), 'checks': result['checks']}))
    return 0 if all(result['checks'].values()) else 1


def worker(args):
    source = args.source_dir.resolve()
    if source != REPO and not source.is_relative_to(REPO / '.agent_control/fixcl3-baseline'):
        raise ValueError('Audit imports only this worktree or its source archive')
    sys.path.insert(0, str(source / 'src'))
    root = source / '.agent_control/proofs' / ('FIXCL3-AUD4-' + args.label + '-' + str(time.time_ns()))
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
        FLUXIO_RUNTIME_AUTO_UPDATE='0', FLUXIO_WORKSPACE_ROOT=str(root), NEYVIA_SERVICE_PORT=str(args.port),
        NEYVIA_PROOF_CREDENTIAL_GUARD='1', NEYVIA_NOTES_DIR=str(root / 'notes'), PYTHONUTF8='1')
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default(); prepare_broker_fixture(root)
    blocked = []
    def audit(event, values):
        if event == 'subprocess.Popen':
            dependency = [sys.executable, '-c', 'import pypdf']
            command = values[1]
            if command != dependency and command != subprocess.list2cmdline(dependency):
                blocked.append({'kind': 'process', 'reason': 'Only installed hidden system-Python pypdf dependency import permitted'})
                raise PermissionError('Snapshot audit admits only the exact installed hidden pypdf dependency check')
        if event in {'socket.connect', 'socket.bind'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] != args.port):
                blocked.append({'kind': 'network', 'reason': 'Outside explicit assigned loopback port'})
                raise PermissionError('Snapshot audit permits only its explicit local port')
    sys.addaudithook(audit)
    started = source_hashes(source)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.cl.effects import inventory
    from grant_agent.cl.codecs import CODECS
    from grant_agent.neyvia_manuals import records, get_manual, validate
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.web_backend import FluxioWebBackend
    backend = FluxioWebBackend(root, root / 'static')
    workspace_for(root, backend)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL3-AUD4-' + args.label, permission_mode='workspace')
    protocol = Protocol(gateway, lazy_manuals=True)
    state_file = root / 'fixture.txt'
    state_file.write_bytes(b'# Actual bounded AUD4 fixture bytes\n')
    skill_file = root / 'SKILL.md'
    skill_file.write_text('---\nname: aud4-disposable\ndescription: Preserve exact disposable audit fixture bytes.\n---\nRead the fixture, preserve it, and report its exact observed bytes.\n', encoding='utf-8')
    gateway.native.call('neyvia.notes.write', {'path': 'audit.md', 'body': 'original AUD4 fixture'})
    note_body = 'Fresh actual AUD4 note bytes'
    note_lines = 'G: notes.read(path="audit.md").body == ' + json.dumps(note_body) + '\nrun notes.write-and-pin(path="audit.md",body=' + json.dumps(note_body) + ',replace_note="replace")\ndone()'
    note_run = protocol.run(note_lines, action_id='AUD4-note-procedure-' + args.label)
    note_path = root / 'notes/audit.md'
    independent = {'exists': note_path.is_file(), 'bytes': note_path.read_text(encoding='utf-8') if note_path.is_file() else None}
    false = Protocol(gateway, lazy_manuals=True).run('G: notes.read(path="audit.md").body == "never written by this audit"\ndone()', action_id='AUD4-false-goal-' + args.label)
    specs = gateway.native._specs
    snapshots = {}
    commands = {
        0: 'notes.read(path="audit.md")', 1: None, 2: None, 3: 'time.now()', 4: None,
        5: 'runtime.list()', 6: 'voice.commands()', 7: 'app_sdk.state(project="missing-sdk-fixture")',
        8: 'pane.observe()', 9: 'pane.observe()', 10: 'browser.state()', 11: 'browser.state()',
        12: 'cua.state()', 13: 'cua.state()', 14: 'remote.state()', 15: 'devices.list()',
        16: 'notes.read(path="audit.md")', 17: 'files.list(path=' + json.dumps(str(root)) + ')',
        18: 'workspace.read(path="fixture.txt")', 19: 'workflow.check(manual="research",report={},evidence={},outcomeQuality=0,tokens=1)',
        20: 'web.search(query="AUD4 disposable fixture",limit=1)',
        21: 'perception.observe(layer="file",source={"path":' + json.dumps(str(state_file)) + '})',
        22: 'pdf.state()', 23: 'image.state()', 24: 'mobile.status()', 25: 'gamedev.state()',
        26: 'scroll.state()', 27: None, 28: None, 29: 'lab.state()', 30: 'skill.live.read(path=' + json.dumps(str(skill_file)) + ')',
        31: 'manual.index()', 32: 'efficiency.metrics()', 33: 'agents.state()', 34: 'settings.get()',
        35: 'voice.commands()', 36: 'verify.status()'}
    # No public web query is actually made: absence of a local source corpus
    # remains an explicit unexecuted research boundary. Documents are covered
    # by source-bound local HTTP fetch/cite receipts below.
    commands[20] = None
    for index, command in commands.items():
        try:
            if index == 1:
                answer = {'ok': True, 'kind': 'native-catalog', 'tools': [{'name': name, 'mutability': spec.mutability_class,
                    'schema': spec.input_schema} for name, spec in sorted(specs.items())]}
            elif index == 2:
                from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
                server = CompactNeyviaMCPServer(root, permission_mode='read-only', session_id='AUD4')
                initialized = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'AUD4', 'version': '1'}}})
                observed = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'neyvia.cl', 'arguments': {'lines': 'notes.read(path="audit.md")', 'actionId': 'AUD4-MCP-read-' + args.label}}})
                answer = {'ok': 'result' in initialized and observed.get('result', {}).get('isError') is not True,
                          'kind': 'in-process-real-mcp', 'initialize': initialized, 'result': observed,
                          'text': observed.get('result', {}).get('structuredContent', {}).get('text', '')}
            elif index == 4:
                from grant_agent.neyvia_cua_mcp import CuaMCPServer
                try:
                    CuaMCPServer(f'http://127.0.0.1:{args.port}')
                except ValueError as exc:
                    answer = {'ok': False, 'kind': 'actual-direct-cua-admission', 'error': str(exc), 'status': 'refused-before-network'}
                else:
                    answer = {'ok': True, 'kind': 'direct-cua-admitted', 'boundary': 'Constructor only; no native action was sent'}
            elif command:
                answer = protocol.run(command, action_id='AUD4-surface-' + args.label + '-' + str(index))
            else:
                answer = {'ok': False, 'status': 'not-executed', 'reason': 'No complete local defining app journey under this audit authority; source and exact receipt boundaries retained'}
        except Exception as exc:
            answer = {'ok': False, 'status': 'failed', 'errorType': type(exc).__name__, 'error': str(exc)[:1200]}
        snapshots[str(index)] = {'command': command, 'result': answer,
            'typedRows': bool(answer.get('ok') is True and re.search(r'^E (?!object\b|generic\b)\S+ ', answer.get('text', ''), re.M)),
            'genericFallback': 'generic' in answer.get('text', '').lower() and 'Q ' in answer.get('text', '')}
        print(json.dumps({'surface': index, 'ok': answer.get('ok'), 'typed': snapshots[str(index)]['typedRows']}), flush=True)
    manuals, bindings = {}, defaultdict(list)
    for record in records():
        identity = record['id']
        try:
            record, digest, document = get_manual(identity, root)
            validation = validate(document, gateway.native)
            manuals[identity] = {'ok': True, 'sha256': digest, 'validation': validation, 'procedureCount': sum(len(ch['procedures']) for ch in document['chapters'].values())}
            for chapter_id, chapter in document['chapters'].items():
                for key, action in chapter['actions'].items():
                    bindings[action['tool']].append({'manual': identity, 'chapter': chapter_id, 'action': key})
        except Exception as exc:
            manuals[identity] = {'ok': False, 'errorType': type(exc).__name__, 'error': str(exc)[:1200]}
    action_inventory = inventory(protocol)
    families = defaultdict(list)
    for row in action_inventory:
        families[row['family']].append(row)
    family_rows = [{'family': name, 'tools': len(rows), 'manualBoundTools': sum(bool(bindings.get(row['tool'])) for row in rows),
                    'typedCodec': name in CODECS, 'effectClassifications': dict(Counter(row['effectStatus'] for row in rows)),
                    'manuals': sorted({binding['manual'] for row in rows for binding in bindings.get(row['tool'], [])}),
                    'toolsDetail': rows} for name, rows in sorted(families.items())]
    managed = [{'tool': name, 'family': 'cl', 'effectStatus': 'managed_protocol_host',
                'boundary': 'CL compound dispatch is not a separate leaf effect adapter'}
               for name in specs if name not in {row['tool'] for row in action_inventory}]
    if managed:
        family_rows.append({'family': 'cl', 'tools': len(managed),
            'manualBoundTools': sum(bool(bindings.get(row['tool'])) for row in managed),
            'typedCodec': snapshots['0']['typedRows'], 'effectClassifications': {'managed_protocol_host': len(managed)},
            'manuals': sorted({binding['manual'] for row in managed for binding in bindings.get(row['tool'], [])}),
            'toolsDetail': managed})
        family_rows.sort(key=lambda row: row['family'])
    registry = json.loads((source / 'config/neyvia_apps.json').read_bytes())
    apps = [{**app, 'suite': suite['id'], 'exactManualRegistered': app['id'] in manuals,
             'exactManualValidated': manuals.get(app['id'], {}).get('ok') is True,
             'boundary': 'Registry ready/coming labels are declarations; no rendered application journey inferred'}
            for suite in registry['suites'] for app in suite['apps']]
    result = {'schema': 'neyvia.FIXCL3.AUD4.snapshots.v1', 'label': args.label, 'sourceRoot': str(source), 'root': str(root),
              'port': args.port, 'snapshots': snapshots, 'manualValidation': manuals, 'families': family_rows, 'apps': apps,
              'actionInventory': action_inventory, 'nativeCatalogCount': len(specs),
              'managedHostToolsExcludedFromLeafInventory': managed,
              'checks': {'exact37SurfacesAttempted': len(snapshots) == 37,
                'notesProcedurePassed': note_run.get('ok') is True, 'independentNoteBytes': independent['bytes'] == note_body,
                'falseGoalRefused': false.get('ok') is False, 'sourcesUnchanged': started == source_hashes(source)},
              'transcripts': {'notesProcedure': note_run, 'independentNoteBytes': independent, 'falseGoal': false},
              'sourceHashesAtStart': started, 'sourceHashesAtEnd': source_hashes(source), 'guardRefusals': blocked,
              'boundary': 'Fresh real local CL/registry/manual observations; no windows, provider credentials, public search, native input or outside peer; positive retained mechanism receipts assessed separately'}
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(args.output), 'checks': result['checks'], 'actions': len(action_inventory), 'families': len(family_rows), 'apps': len(apps)}))
    return 0 if all(result['checks'].values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--source-dir', type=Path, default=REPO)
    parser.add_argument('--label', choices=['before', 'after'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshots', type=Path, help='Assess retained real receipts against this already fresh snapshot')
    parser.add_argument('--wave', choices=['FIXCL3', 'FIXCL4', 'FIXCL5', 'FIXCL6', 'FIXCL7'], default='FIXCL3', help='Include only the selected wave and earlier source-bound real witnesses')
    args = parser.parse_args()
    if args.port not in (range(48781, 48790) if args.wave in {'FIXCL6', 'FIXCL7'} else range(48821, 48830)):
        parser.error('Explicit assigned port required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return assess(args) if args.snapshots else worker(args)


if __name__ == '__main__':
    raise SystemExit(main())
