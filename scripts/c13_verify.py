"""Fresh CL completion checks and a compact, hash-bound C13d live receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT / 'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from grant_agent.taste_gate import digest, save
from c13_run import native_host


def bound(path):
    return {'path': str(path.relative_to(WT)), 'sha256': digest(path)}


def round_cost(folder, row):
    review = [json.loads(Path(item['path']).read_text(encoding='utf-8'))
              for item in row['evidenceFiles'] if Path(item['path']).name == 'usage.json']
    repair_folder = folder / ('repair-' + str(row['round'] - 1))
    repairs = [json.loads(path.read_text(encoding='utf-8')) for path in repair_folder.rglob('usage.json')]
    review_cost = sum(item['costUsd'] for item in review)
    repair_cost = sum(item['costUsd'] for item in repairs)
    repair_time = sum(item['elapsedSec'] for item in repairs)
    timing_path = repair_folder / 'timing.json'
    repair_wall = json.loads(timing_path.read_text(encoding='utf-8'))['elapsedSec'] if timing_path.is_file() else None
    draft_time = json.loads((folder / 'draft/usage.json').read_text(encoding='utf-8'))['elapsedSec']
    return {'costUsd': review_cost, 'repairCostUsd': repair_cost,
            'reviewReasoningEfforts': sorted({item.get('reasoningEffort','medium (original fixed configuration)') for item in review}),
            'repairReasoningEfforts': sorted({item.get('reasoningEffort','medium (original fixed configuration)') for item in repairs}),
            'iterationCostUsd': review_cost + repair_cost,
            'repairModelElapsedSec': repair_time, 'iterationElapsedSec': row['elapsedSec'] + repair_time,
            'repairModelTimeOverFirstDraft':repair_time/draft_time if repair_time and draft_time else None,
            'repairWallElapsedSec':repair_wall,
            'iterationWallElapsedSec':row['elapsedSec']+repair_wall if repair_wall is not None else None,
            'costBasis': 'review and preceding repair/search calls, including contract retries; list-price equivalent'}


def verify_task(task):
    folder = WT / 'proof/r7/arm-l' / task
    state_path = folder / 'host-state.json'
    if not state_path.exists():
        return {'task': task, 'complete': False, 'reason': 'No saved host checkpoint'}
    state = json.loads(state_path.read_text(encoding='utf-8'))
    host = native_host(folder / 'work', state['policy'])
    host.taste.restore_state(state)
    name = state['policy']['files'][0]
    host.goals.append("'<!doctype html' in workspace.read(path=" + repr(name) + ")[\"content\"].lower()")
    completion = host.execute('done("' + name + ' is ready")')
    save(folder / 'fresh-completion.json', completion)
    current = folder / 'work' / name
    final = WT / 'proof/r7/arm-l' / name
    rounds = host.taste.rounds.get(str(current.resolve()), [])
    usages = [json.loads(path.read_text(encoding='utf-8')) for path in folder.rglob('usage.json')]
    run_result = folder / 'result.json'
    draft_usage = json.loads((folder / 'draft/usage.json').read_text(encoding='utf-8'))
    browser_checks = list((folder / 'evidence').glob('current-browser-verification*/report.json'))
    browser_check = max(browser_checks, key=lambda path:path.stat().st_mtime) if browser_checks else folder / 'evidence/current-browser-verification/report.json'
    browser_result = json.loads(browser_check.read_text(encoding='utf-8')) if browser_check.is_file() else None
    lead_check = folder / 'lead-final-inspection.json'
    lead_result = json.loads(lead_check.read_text(encoding='utf-8')) if lead_check.is_file() else None
    return {'task': task, 'complete': completion['ok'] and final.is_file() and digest(final) == digest(current),
            'leadFinalInspection': bound(lead_check) if lead_result else None,
            'leadInspectionMatchesCurrentArtifact': lead_result['artifactSha256'] == digest(current) if lead_result else None,
            'currentBrowserVerification': bound(browser_check) if browser_result else None,
            'browserVerificationMatchesCurrentArtifact': browser_result['html_sha256'] == digest(current) if browser_result else None,
            'browserVerificationPassed': browser_result['passed'] if browser_result else None,
            'completion': bound(folder / 'fresh-completion.json'), 'artifact': bound(current),
            'finalArtifact': bound(final) if final.is_file() else None,
            'firstDraftRefused': not json.loads((folder / 'before-done.json').read_text(encoding='utf-8'))['ok'],
            'costUsd': sum(row['costUsd'] for row in usages),
            'costBasis': 'repository list-price equivalent of actual CLI tokens; not an invoice',
            'modelElapsedSec':sum(row['elapsedSec'] for row in usages),
            'firstDraftModelElapsedSec':draft_usage['elapsedSec'],'firstDraftCostUsd':draft_usage['costUsd'],
            'reasoningEfforts': sorted({row.get('reasoningEffort','medium (original fixed configuration)') for row in usages}),
            'taskWallElapsedSec':json.loads(run_result.read_text(encoding='utf-8')).get('taskElapsedSec') if run_result.is_file() else None,
            'timingScope':'Round times cover completed render/critic calls; iterationElapsedSec adds preceding repair/search model calls. Full iterationWallElapsedSec additionally includes host attestation/checkpoint only where a repair timing receipt exists; older wall values are null. Overall task wall time includes preserved interrupted attempts, debugging and resumes.',
            'rounds': [{'number': row['round'], 'inspectionOnly':row.get('inspectionOnly',False), 'quality': row['critique']['quality'],
                        'qualityGain': row['qualityGain'], 'elapsedSec': row['elapsedSec'],
                        **round_cost(folder, row), 'controlsPassed': row['interaction']['passed'],
                        'fidelity': row['fidelity'], 'anchorVerdict': row['critique']['anchorVerdict'],
                        'repair': row['change'], 'difference': bound(Path(row['differenceCl'])),
                        'renderReport': bound(Path(row['folder']) / 'render/report.json')}
                       for row in rounds], 'refusal': '' if completion['ok'] else completion['text']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=WT / 'scripts/evidence/C13d.json')
    args = parser.parse_args()
    install_hidden_subprocess_default()
    tasks = [verify_task(task) for task in ('T1', 'T2')]
    browser_paths = [WT / 'scripts/evidence' / name for name in
                     ('C13-browser.json', 'C13-browser-service.json', 'C13-browser-tests.json', 'C13-host-tests.json', 'C13-obscura-provision.json',
                      'C13-svg-api-probe.json', 'C13-svg-coordinates/manifest.json',
                      'C13-svg-hit-before/manifest.json', 'C13-svg-hit-after/manifest.json')]
    lesson_paths = list((WT / 'scripts/evidence/C13-lessons').glob('*/result.json'))
    lessons = [{**bound(path), 'accepted': json.loads(path.read_text(encoding='utf-8'))['admission']['accepted'],
                'suiteComplete': json.loads(path.read_text(encoding='utf-8'))['suiteComplete']}
               for path in lesson_paths]
    sources = subprocess.run(['git', 'status', '--short'], cwd=WT, capture_output=True, text=True, check=True).stdout
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=WT, capture_output=True, text=True, check=True).stdout.strip()
    calibration=json.loads((WT/'config/c13-judge.json').read_text(encoding='utf-8'))['calibration']
    receipt = {'schema': 'neyvia.C13d.v1', 'observedAtUtc': datetime.now(timezone.utc).isoformat(),
               'sourceRevision': revision,
               'tasksComplete': all(task['complete'] for task in tasks),
               'complete': all(task['complete'] for task in tasks) and any(lesson['accepted'] for lesson in lessons),
               'tasks': tasks, 'browser': [bound(path) for path in browser_paths if path.is_file()],
               'attestationBenchmark':bound(WT/'scripts/evidence/C13-attestation-benchmark.json') if (WT/'scripts/evidence/C13-attestation-benchmark.json').is_file() else None,
               'nativeRepairProfile':bound(WT/'scripts/evidence/C13-native-repair-profile.json') if (WT/'scripts/evidence/C13-native-repair-profile.json').is_file() else None,
               'lessonReplays': lessons, 'boundaries': {'ports': list(range(48801, 48810)),
               'browser': 'Neyvia non-stealth Obscura; explicit DOM input compatibility, no native/trusted touch claim',
               'promotion': 'branch-only local changes; no push, merge, NAS or public service action'},
               'calibration':{'agreed':calibration['agreed'],'total':calibration['total'],'agreement':calibration['agreement'],'scope':'weak text proxy is advisory; frozen rubric-first actual image critique gates completion'},
               'missing':([] if all(task['complete'] for task in tasks) else ['One or more live R7 tasks remain host-refused; see task refusal'])+([] if any(lesson['accepted'] for lesson in lessons) else ['No demonstrated C9 lesson admission: source quality flat and complete historical frozen suite unavailable']),
               'sourceStatus': sources}
    save(args.out, receipt)
    print(json.dumps({'complete': receipt['complete'], 'tasks': [{k: row[k] for k in ('task', 'complete', 'costUsd') if k in row} for row in tasks], 'receipt': str(args.out)}))


if __name__ == '__main__':
    main()
