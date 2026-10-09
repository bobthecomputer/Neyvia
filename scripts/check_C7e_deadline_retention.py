"""Check deadline-receipt retention contracts using disposable local metadata."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
sys.path.insert(0, str(REPO / 'src'))

import prune_C7e as retention
from grant_agent.edge_fixture_catalog import BUILDERS


def run(output):
    cases = []

    def record(identity, action, expected):
        try:
            value = action()
        except Exception as exc:
            value = type(exc).__name__
        ok = expected(value)
        cases.append({'id': identity, 'status': 'passed' if ok else 'failed'})
        if not ok:
            raise AssertionError(identity + ': ' + repr(value))

    names = list(BUILDERS)
    states = [{'family': name, 'state': 'pending_unobserved', 'casesTotal': 1,
               'fixtureCasesTotal': 1, 'authorityCasesTotal': 0, 'passing': 0,
               'failing': 0, 'blocked': 0, 'builtUnverified': 0, 'unbuilt': 1}
              for name in names]
    report = {'schema': 'neyvia.c7e-deadline.v1', 'ok': True, 'complete': False,
              'fixturesComplete': False, 'fixtureCompletion': 'not_claimed', 'explicitPort': 48741,
              'sourceCurrent': True, 'proofRoots': ['.agent_control/proofs/c7/scratch-check'],
              'completedFamilies': 0, 'familyReceipts': [], 'familyStates': states,
              'caseTotals': {'casesTotal': len(states), 'passing': 0, 'failing': 0,
                             'blocked': 0, 'builtUnverified': 0, 'unbuilt': len(states)},
              'caseInventory': {'path': 'scripts/evidence/scratch-inventory.json', 'sha256': 'a' * 64},
              'authorityReceipt': {'path': 'scripts/evidence/C7d-authority.json', 'sha256': 'b' * 64},
              'unsealedCaseProgress': [], 'unsealedDiagnosticsAreCompletionEvidence': False}

    record('deadline.retention.accepts-exact44-incomplete',
           lambda: retention._deadline_shape(report, names) is report, lambda value: value is True)
    complete = {**report, 'complete': True}
    record('deadline.retention.refuses-completion-claim',
           lambda: retention._deadline_shape(complete, names), lambda value: value == 'ValueError')
    short = {**report, 'familyStates': states[:-1]}
    record('deadline.retention.refuses-missing-family',
           lambda: retention._deadline_shape(short, names), lambda value: value == 'ValueError')
    lying = {**report, 'caseTotals': {**report['caseTotals'], 'passing': 1}}
    record('deadline.retention.refuses-passing-total-inflation',
           lambda: retention._deadline_shape(lying, names), lambda value: value == 'ValueError')
    claimed = {**report, 'unsealedCaseProgress': [{'family': names[0], 'completionReceipt': True, 'counts': {}}]}
    record('deadline.retention.refuses-progress-as-receipt',
           lambda: retention._deadline_shape(claimed, names), lambda value: value == 'ValueError')

    proof_root = (REPO / '.agent_control/proofs/c7').resolve()
    with tempfile.TemporaryDirectory(prefix='c7e-retention-check-', dir=proof_root) as temp:
        scratch = Path(temp)
        selected = scratch / 'semantic-fixtures' / 'sessions.receipt.json'
        selected.parent.mkdir()
        selected.write_text('{}', encoding='utf-8')
        record('deadline.retention.accepts-selected-proof-reference',
               lambda: retention._repo_reference(selected.relative_to(REPO).as_posix(), proof_root) == selected.resolve(),
               lambda value: value is True)
        record('deadline.retention.refuses-evidence-reference-as-proof-root',
               lambda: retention._repo_reference('scripts/evidence/C7d-authority.json', proof_root),
               lambda value: value == 'ValueError')
        clean = REPO / 'scripts/compact_C7d_evidence.py'
        record('deadline.retention.accepts-committed-clean-reference',
               lambda: retention.require_committed([clean]) is None, lambda value: value is True)
        untracked = scratch / 'untracked.json'
        untracked.write_text('{}', encoding='utf-8')
        record('deadline.retention.refuses-uncommitted-reference',
               lambda: retention.require_committed([untracked]), lambda value: value == 'ValueError')

    result = {'schema': 'neyvia.c7e-deadline-retention-check.v1',
              'ok': all(case['status'] == 'passed' for case in cases),
              'cases': cases, 'caseCount': len(cases),
              'boundary': 'Metadata and committed-path checks only; no pruning applied. C7 task-local scope only; no service-wide Neyvia retention behavior is established.'}
    target = Path(output).resolve()
    target.relative_to((REPO / 'scripts/evidence').resolve())
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/C7e-deadline-retention-check.json')
    args = parser.parse_args()
    print(json.dumps(run(args.output)))


if __name__ == '__main__':
    main()
