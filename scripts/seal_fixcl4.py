"""Seal current FIXCL4 evidence, including every remaining local/external gap."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from fixcl3_aud4_matrix import REPO, retained, positive_uses, source_hashes

EVIDENCE = REPO / 'scripts/evidence'
OUTSIDE = {
    'laya.native.neyvia_navigation': ('Installed LAYA navigation runtime plus an owned app session on an assigned port', 'Navigate a disposable app via real typed decisions; observe the selected route, control effect and final content.'),
    'nas.file.send': ('Paul authorizes scoped NAS access and supplies a runtime-owned paired endpoint', 'Send an owned fixture into the allowed inbox; independently compare destination SHA-256 and prove overwrite refusal.'),
    'nas.message.receive': ('Paul authorizes scoped NAS messaging and an authenticated peer account', 'Receive a uniquely identified peer message; prove exact content, single delivery and revoked-peer denial.'),
    'nas.message.send': ('Paul authorizes scoped NAS messaging and an authenticated peer account', 'Send a unique message; independently observe the destination inbox identity/content and revoked-peer denial.'),
    'nas.transfer': ('Paul authorizes scoped NAS transfer and a paired device with a selected inbox', 'Interrupt/resume an owned transfer; compare end-to-end SHA-256 and prove unrelated files survive.'),
    'neyvia.cua.action': ('An authorized isolated native app desktop and connected input driver', 'Operate a real target control; capture fresh UIA/window/frame state and prove wrong/stale-target refusal without foreground changes.'),
    'neyvia.dictation.transcribe': ('A consented recording or microphone and actual installed ASR engine on an assigned port', 'Stream actual audio into Neyvia, inspect provisional/final words, cancellation and measured end-to-text latency.'),
    'neyvia.gamedev.action': ('Installed selected Unity/Godot/Roblox/Blender editor and authorized project bridge', 'Edit a disposable scene/script, play/interact/stop and inspect native output/frame and exact session-affinity denial.'),
    'neyvia.gamedev.setup': ('Installed selected editor and permission to add its bridge to a disposable project', 'Install without overwriting keeper files; connect the editor and execute a real edit/play/receipt journey.'),
    'neyvia.image.generate': ('A connected image model or provider account and authorized generation budget', 'Generate actual pixels, observe source parameters/output SHA-256 and render the saved result; retain provider failure.'),
    'neyvia.mobile.build': ('Installed Android/iOS SDK and authorized toolchain/project', 'Build a real APK/IPA, independently inspect package contents/signing and launch it on a compatible target.'),
    'neyvia.mobile.install': ('A consented connected phone or owned emulator and a valid built package', 'Install, launch and interact on the actual device; verify package/version and retain installation denial.'),
    'neyvia.mobile.preview': ('An owned phone/emulator or authorized isolated device runtime', 'Show its actual current frame, forward touch/rotation and observe the resulting app state without a desktop window.'),
    'neyvia.mobile.setup': ('Paul approves required SDK installation and any download exceeding 200 MB', 'Install only the selected toolchain; detect exact versions, build an owned package and prove launch on a target.'),
    'neyvia.remote.snapshot': ('A consented second PC/remote agent and explicitly allowed window', 'Capture its actual frame, bind device/window identity and show revocation/wrong-window denial.'),
    'neyvia.scroll.concepts': ('Actual connected teaching model/provider account and reviewed source corpus', 'Extract concepts from the real corpus with grounded citations, retain exact model/tokens and inspect incorrect-source refusal.'),
    'neyvia.scroll.generate': ('Actual connected teaching model/provider account and approved bounded generation', 'Generate a course, open the saved pack, exercise prerequisite/quiz ordering and prove questions never precede their material.'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830): parser.error('Explicit assigned port required')
    args.label = 'after'; args.wave = 'FIXCL4'
    matrix_path = EVIDENCE / 'FIXCL4-AUD4-after.json'
    snapshot_path = EVIDENCE / 'FIXCL4-AUD4-after-snapshots.json'
    matrix = json.loads(matrix_path.read_bytes())
    snapshot = json.loads(snapshot_path.read_bytes())
    baseline = json.loads((EVIDENCE / 'FIXCL3.json').read_bytes())
    frontier_before = json.loads((EVIDENCE / 'FIXCL3-AUD4-after-frontier.json').read_bytes())
    proofs, boundaries = retained(args)
    uses, rejected_uses = positive_uses(proofs)
    witnesses = {use['tool'].removeprefix('neyvia.') for use in uses}
    inventory = snapshot['actionInventory']
    current = {row['tool']: row for row in inventory}
    remaining = [row for row in matrix['remainingFrontierBoundaries'] if row.get('localUnfinished')]
    closed = []
    for row in frontier_before['remaining']:
        if not row['localUnfinished']: continue
        name = row['tool']; state = current.get(name, {})
        if state.get('effectStatus') == 'grounded_adapter' and name.removeprefix('neyvia.') in witnesses:
            closed.append({'tool': name, 'status': 'positive-source-bound-CL-effect', 'manualUses': [use for use in uses if use['tool'] == name]})
        elif state.get('effectStatus') == 'read_only':
            closed.append({'tool': name, 'status': 'audited-read-only', 'boundary': 'Read classification is separate from a mutating positive effect witness; exact read journey retained in layer receipt.'})
    outside = [{'tool': name, 'needs': need, 'proofJourney': journey, 'line': name + ' — needs ' + need + '; proof: ' + journey} for name, (need, journey) in OUTSIDE.items()]
    (EVIDENCE / 'FIXCL4-outside-boundaries.txt').write_text('\n'.join(row['line'] for row in outside) + '\n', encoding='utf-8', newline='\n')
    cold_path = EVIDENCE / 'FIXCL4-cold.json'
    cold = json.loads(cold_path.read_bytes()) if cold_path.is_file() else {}
    latency = cold.get('latency', {})
    p50 = latency.get('coldProcess', {}).get('p50Ms')
    cold_current = cold_path.name in proofs and all(cold.get('checks', {}).values())
    new_supported = [name for name, row in current.items() if row['effectStatus'] == 'grounded_adapter' and any(old['tool'] == name and old['effectStatus'] == 'frontier' for old in frontier_before['remaining'])]
    missing_witnesses = [name for name in new_supported if name.removeprefix('neyvia.') not in witnesses]
    counts = matrix['counts']
    checks = {'full185CellMatrixRerun': sum(counts.values()) == 185 and all(matrix['checks'].values()),
              'freshSnapshotSourceCurrent': snapshot['sourceHashesAtStart'] == source_hashes(REPO),
              'allNewEffectAdaptersHavePositiveCLWitnesses': not missing_witnesses,
              'all49LocalGapsClosed': len(closed) == 49 and not remaining,
              'coldP50Under2500Ms': isinstance(p50, (int, float)) and p50 < 2500,
              'coldReceiptSourceCurrentAndAllChecksPassed': cold_current,
              'all17OutsideBoundaryJourneysExplicit': len(outside) == 17,
              'zeroRedCells': counts.get('R', 0) == 0}
    commits = subprocess.run(['git', 'log', '--format=%h %s', 'df5f8e9b..HEAD'], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    result = {'schema': 'neyvia.FIXCL4.v1', 'status': 'complete' if all(checks.values()) else 'partial_with_explicit_gaps',
        'baseline': {'commit': 'df5f8e9b', 'AUD4': baseline['AUD4']['after']['counts'], 'frontierActions': 66, 'localGaps': 49, 'outsideBoundaries': 17, 'coldP50Ms': 3902.32},
        'checks': checks, 'AUD4': {'counts': counts, 'receipt': matrix_path.name, 'sha256': sha(matrix_path),
            'redCells': [{'surface': row['surface'], **cell} for row in matrix['matrix'] for cell in row['cells'] if cell['status'] == 'R']},
        'coverage': {'statuses': dict(Counter(row['effectStatus'] for row in inventory)), 'closedLocalGaps': closed,
            'closedLocalGapCount': len(closed), 'remainingLocalGaps': remaining, 'newAdaptersWithoutPositiveWitness': missing_witnesses},
        'latency': latency, 'outsideBoundaries': outside, 'sourceHashes': snapshot['sourceHashesAtStart'], 'localCommits': commits,
        'receipts': boundaries, 'rejectedPositiveManualUses': rejected_uses,
        'limitations': ['Every count is from the fresh complete AUD4 matrix; historical colours and stale effect/source receipts are not promoted.',
            'Read-only classification does not prove initialization or mutation; each layer records its actual conservation and failure boundary.',
            'No public release, NAS synchronization, push, merge or external device/account journey is claimed.']}
    output = EVIDENCE / 'FIXCL4.json'
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'status': result['status'], 'AUD4': counts, 'closedLocal': len(closed), 'remainingLocal': len(remaining), 'coldP50Ms': p50, 'checks': checks}))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__': raise SystemExit(main())
