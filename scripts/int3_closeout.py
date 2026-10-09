"""Assemble INT3 acceptance from completed real receipts, retaining limitations."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / '.agent_control/int3'
EVIDENCE = ROOT / 'scripts/evidence/int3'
BASE = 'a18870b7602998728859ffcf25c7af6d497e53ea'
MERGES = [
    ('bc2ddba5', 'track/laya-evolver-hook', '01-laya'),
    ('10af1961', 'track/m-s-manuals-study', '02-ms'),
    ('fda1333f', 'track/r2-intent', '03-r2'),
    ('107ed2a1', 'track/r3-light', '04-r3'),
    ('0a3a0933', 'track/proofs-a', '05-proofs-a'),
    ('8991f570', 'track/proofs-b', '06-proofs-b'),
    ('2109dd72', 'track/proofs-c', '07-proofs-c'),
    ('da9b73dd', 'track/proofs-d', '08-proofs-d'),
    ('cd3f6247', 'track/proofs-e', '09-proofs-e'),
]


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def binding(path):
    file = ROOT / path
    return {'path': file.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main():
    runtime = read('scripts/evidence/int3/runtime/http-journeys.json')
    verification = runtime.get('checks', {}).get('manualVerifier', {})
    comparison = read('scripts/evidence/int3/pytest/comparison.json')
    node = read('scripts/evidence/int3/node-comparison.json')
    checks = read('scripts/evidence/int3/checks/final-acceptance/results.json')
    survival = read('scripts/evidence/int3/contract-survival-final.json')
    retention = read('scripts/evidence/int3/lost-lines-review.json')
    dispatch = read('scripts/evidence/int3/dispatch-returns.json')
    luna = read('scripts/evidence/int3/luna-b-confirmation/verification.json')
    luna_hashes = read('scripts/evidence/int3/luna-b-confirmation/lead-hash-verification.json')
    laya_check = read('scripts/evidence/int3/laya-retrospective.json')
    gates = {
        'allRequestedMerges': all(git('merge-base', '--is-ancestor', sha, 'HEAD') == '' for sha, _, _ in MERGES),
        'compiled': checks['compile']['exitCode'] == 0,
        'viteBuilt': checks['build']['exitCode'] == 0,
        'nodeNoNewFailures': node['noNewFailures'],
        'pytestNoNewFailures': comparison['noNewFailures'],
        'retiredContractsSurvive': survival['survival'],
        'semanticIdentityRetention': retention['passed'],
        'dispatchReturns': not dispatch['missing'],
        'productionHTTPJourneys': runtime['ok'],
        'allFortyAreas': len(verification.get('areas', [])) == 40 and all(row['ok'] for row in verification.get('areas', [])),
        'currentBoundContracts': verification.get('contractsOk') is True and verification.get('sourceStable') is True,
        'sixOriginalLunaTasks': luna['passed'] == luna['tasks'] == 6 and luna_hashes['independentlyVerified'],
        'firstMergeSupplementaryCheck': laya_check['exitCode'] == 0 and laya_check['sourceIntegrity'] and len(laya_check['selected']) == 7,
    }
    if not all(gates.values()):
        raise SystemExit('Incomplete acceptance gates: ' + ', '.join(key for key, value in gates.items() if not value))
    archive = EVIDENCE / 'pytest'
    archive.mkdir(exist_ok=True)
    for label in ('baseline-remaining', 'baseline-safe', 'baseline-signaled', 'final-full', 'final-current', 'final-logged', 'signal-guard-crash-case', 'final-safe'):
        for suffix in ('.invocation.json', '.outcomes.json', '.outcomes.json.coverage.json',
                       '.pytest.log', '.module-proof.jsonl', '.guard.jsonl'):
            source = CONTROL / (label + suffix)
            if source.is_file():
                shutil.copyfile(source, archive / source.name)
    for name in ('pytest-subworker-stop.json', 'pytest-repaired-early-stop.json', 'proof-subworker-stop.json',
                 'proof-orphan-chrome.json', 'pytest-unicode-early-stop.json', 'proof-unicode-early-stop.json'):
        if (CONTROL / name).is_file():
            shutil.copyfile(CONTROL / name, EVIDENCE / name)
    paths = [p for p in EVIDENCE.rglob('*') if p.is_file()]
    wire = runtime['checks']['wireInventory']
    coverage = verification['coverage']
    report = {
        'schema': 'neyvia.INT3.integration.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'branch': git('branch', '--show-current'), 'baseline': BASE, 'sourceHead': git('rev-parse', 'HEAD'),
        'accepted': True, 'acceptanceGates': gates,
        'merges': [{'commit': git('rev-parse', sha), 'branch': branch,
                    'checks': read(f'scripts/evidence/int3/checks/{label}/results.json')}
                   for sha, branch, label in MERGES],
        'firstMergeSupplementaryPytest': laya_check,
        'mechanisms': {
            'layaEvolver': runtime['checks']['evolver'], 'workflowManuals': runtime['checks']['workflow'],
            'intent': runtime['checks']['intent'], 'scrollStudy': runtime['checks']['scrollStudy'],
            'manuals': {'authority': 'manuals/cl/*.cl CL1.1 sources, compiled JSON and regenerated docs/plugin skills',
                        'contracts': survival['compiledContracts'], 'retiredFiles': survival['deletedFiles'],
                        'retiredCases': survival['deletedCases'], 'lostManualIdentities': len(retention['missingManualEntries'])},
        },
        'proofs': {'areas': len(verification['areas']), 'durationMs': verification['durationMs'],
                   'contractsOk': verification['contractsOk'], 'completeMigration': verification['complete'],
                   'failures': verification['failures'], 'blockedGenericManualChecks': verification['blocked'],
                   'coverage': coverage, 'currentSourceBindings': verification['sourceBindings'],
                   'boundary': verification['timingScope']},
        'HTTP': {'port': 48651, 'advertisedToolCalls': len(wire['advertisedToolsAttempted']),
                 'literalRouteCalls': len(wire['literalRouteCalls']), 'boundary': wire['boundary']},
        'luna': {'model': luna['exactRequestedModel'], 'passed': luna['passed'], 'tasks': luna['tasks'],
                 'latencyMs': luna['totalLatencyMs'], 'tokens': luna['totalTokens'], 'boundary': luna['claimBoundary']},
        'pytest': {'baseline': comparison['baseline'], 'after': comparison['after'],
                   'newFailures': comparison['newFailures'], 'matchedEnvironment': comparison['matchedEnvironment'],
                   'lineCoverage': comparison['lineCoverage'], 'boundary': comparison['coverageBoundary']},
        'node': {'counts': node['after']['counts'], 'knownFailure': node['knownFailure']},
        'limitations': [
            'Manual test-to-proof migration remains partial; remaining files and blocked generic procedures are explicit in coverage.',
            'Tool inventory calls prove owner refusal before dispatch; unsigned route calls prove transport/auth responses, not positive execution of every tool or dynamic route.',
            'Rust Evolver runs prove paired CPU trials, durable promotion and deduplication; no model weight training or general quality gain is claimed.',
            'Luna smoke tasks use original goals, seeds and budgets; task17 retains its recorded visual cache provenance.',
            'The first LAYA merge lacks a contemporaneous related pytest receipt; a retrospective seven-test check of its exact original source passed, with integrity verified.',
            'The raw first full pytest run had eleven new failures and an explicitly recorded owned subworker stop; the fresh final run supplies acceptance.',
            'Three intermediate full processes crashed with Windows access violations, including one without asynchronous exception injection. The matched acceptance pair uses source-only coverage tracing and identical Python pending-signal deadlines, preserving 120 seconds and recording the native-blocking limitation.',
            'Local source and receipts only; no NAS, public release, service restart, push or merge-out.',
        ],
        'safety': {'allowedPorts': list(range(48651, 48660)), 'noCredentialFilesRead': True,
                   'noNASSync': True, 'noDownloadsOver200MB': True, 'noProviderSubstitution': True},
        'evidenceFiles': [binding(p.relative_to(ROOT)) for p in sorted(paths)],
    }
    output = ROOT / 'scripts/evidence/INT3.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'accepted': True, 'gates': gates, 'receipt': str(output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
