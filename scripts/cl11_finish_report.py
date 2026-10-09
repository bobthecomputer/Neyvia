"""Append method and transcript evidence without regrading the frozen cohort."""
from pathlib import Path
import json
import statistics
import argparse
from collections import Counter

REPO = Path(__file__).resolve().parents[1]
COHORT = REPO/'.agent_control/cl11/scored-1'
REPORT = REPO/'docs/evidence/cl-benchmark-1.1.md'
MARKER = '\n## Lead evidence review\n'

def comparison_table(manifest, runs, semantic):
    """Describe supplied evidence and observed checks without claiming cognition."""
    lines = ['## Per-action native comparison', '',
             'Tokens to completion use successful valid runs; action means use all valid attempts. Recorded post-C and G counts are totals. Successful preconditions are not separately counted by the frozen runner, so these are not exhaustive check totals. ',
             'Host I receipts establish information supplied after the action, not agent understanding or a successful undo. ',
             'Native knowledge judgments are bounded manual transcript observations. Unknown never means unavailable.', '',
             '| Task | Arm/model | Tokens to completion | Actions mean | Check evidence | Impact evidence | Undo evidence | Success |',
             '|---|---|---:|---:|---|---|---|---|']
    for task in manifest['nativeTasks']:
        for arm, model in (('b','gpt-6-luna'),('b','gpt-6.1-sol'),('codex-alone','gpt-6-luna'),('claude-alone','haiku')):
            rows = [r for r in runs if r['task']==task and r['arm']==arm and r['model']==model and r['valid']]
            successes = [r for r in rows if r['success']]
            tokens = f"{statistics.mean(r['tokens']['total'] for r in successes):.1f}" if successes else 'no completion'
            actions = f"{statistics.mean(r.get('actionCount',len(r['actions'])) for r in rows):.1f}" if rows else 'unavailable'
            if arm == 'b':
                impacts, undo = 0, Counter()
                goals = 0
                for row in rows:
                    for action in row['actions']:
                        result = action.get('result') or {}
                        goals += sum(len(x.get('goalChecks',[])) + int(bool(x.get('goal')))
                                     for x in result.get('results',[]))
                        for line in result.get('text','').splitlines():
                            if not line.startswith('I '):
                                continue
                            impacts += 1
                            try:
                                value, _ = json.JSONDecoder().raw_decode(line[2:])
                                undo[value.get('undo','unknown')] += 1
                            except (ValueError,AttributeError):
                                undo['unparsed detail handle'] += 1
                check = f"{sum(r.get('checkCount',0) for r in rows)} post-C; {goals} G evaluations"
                impact = f"host I supplied {impacts} lines; understanding unproven"
                recovery = '; '.join(f'{k}: {v}' for k,v in sorted(undo.items())) or 'no action evidence'
                recovery += '; availability unproven by this count'
            else:
                reviewed = [r for r in semantic.get('runs',[]) if r['task']==task and r['harness']==arm]
                checked = [r for r in reviewed if r['semanticReview']['reviewStatus']=='reviewed_visible_transcript']
                check = (f"{sum(r['explicitPredicateToolCalls'] for r in checked)} predicate attempts; "
                         f"{sum(r['predicateZeroExit'] for r in checked)} attested zero exits; "
                         f"{sum(r['completedReviewedStateReadbacks'] for r in checked)} completed text readbacks") if checked else 'not semantically reviewed'
                impact_counts = Counter(r['semanticReview']['impactKnown']['value'] for r in checked)
                impact = '; '.join(f'{k}: {v}' for k,v in sorted(impact_counts.items())) or 'unknown'
                undo_counts = Counter(r['semanticReview']['undoAvailable']['value'] for r in checked)
                recovery = 'action-specific availability ' + ('; '.join(f'{k}: {v}' for k,v in sorted(undo_counts.items())) or 'unknown')
                if any(not r['valid'] and r['task']==task and r['arm']==arm for r in runs):
                    check += ' (includes deadline-invalid attempt transcripts)'
            lines.append(f"| {task} | {arm}/{model} | {tokens} | {actions} | {check} | {impact} | {recovery} | {len(successes)}/{len(rows)} valid |")
    return '\n'.join(lines)+'\n\n'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,default=COHORT)
    parser.add_argument('--report',type=Path,default=REPORT)
    args = parser.parse_args()
    manifest = json.loads((args.cohort/'manifest.json').read_text(encoding='utf-8'))
    summary = json.loads((args.cohort/'summary.json').read_text(encoding='utf-8'))
    runs = summary['runs']
    native = json.loads((REPO/'scripts/evidence/CL11-native-review.json').read_text(encoding='utf-8'))
    semantic_path = REPO/'scripts/evidence'/('CL11-native-semantic-review-cohort-2.json' if args.cohort.name=='scored-2' else 'CL11-native-semantic-review.json')
    semantic = json.loads(semantic_path.read_text(encoding='utf-8')) if semantic_path.exists() else {}
    lines = [MARKER, '', 'The frozen grader and raw results remain unchanged. Native transcript review is an evidence index, not semantic regrading. ',
             'The main comparison reports host post-effect C counts; preconditions and whole-goal evaluations are additional. ',
             'Native event counts are tool calls, while CL counts include underlying procedure actions. A shell macro may contain several effects. ',
             'The earlier regression list uses all-attempt means; it must not be read as tokens to successful completion.', '',
             '| Task | Native harness | Runs | Explicit predicate attempts | Post-effect readback candidates | Impact evidence | Undo evidence |',
             '|---|---|---:|---:|---:|---|---|']
    for row in native['perTaskHarness']:
        lines.append(f"| {row['task']} | {row['harness']} | {row['runsAvailable']} | {row['explicitPredicateAttempts']} | {row['postEffectReadbackCandidates']} | "+
                     ('mentions requiring review' if row['impactMentionsRequiringReview'] else 'missing')+' | '+
                     ('mentions requiring review' if row['undoMentionsRequiringReview'] else 'missing')+' |')
    lines += ['', 'A readback candidate is not a passed assertion. Explicit predicates retain execution evidence and event-line references in ',
              '[CL11-native-review.json](../../scripts/evidence/CL11-native-review.json). Missing knowledge evidence remains unknown.', '',
              '### Successful-completion token comparisons', '']
    comparisons = 0
    for task in manifest['nativeTasks']:
        for model in ('gpt-6-luna','gpt-6.1-sol'):
            cl = [r for r in runs if r['task']==task and r['arm']=='b' and r['model']==model and r['valid'] and r['success']]
            for arm in ('codex-alone','claude-alone'):
                other = [r for r in runs if r['task']==task and r['arm']==arm and r['valid'] and r['success']]
                if not cl or not other:
                    lines.append(f'- Task {task}, b/{model} vs {arm}: successful-completion token comparison unavailable ({len(cl)} vs {len(other)} completions).')
                    continue
                comparisons += 1
                left = statistics.mean(r['tokens']['total'] for r in cl)
                right = statistics.mean(r['tokens']['total'] for r in other)
                lines.append(f'- Task {task}, b/{model} vs {arm}: {left:.1f} vs {right:.1f} provider tokens to completion; CL is '+('worse.' if left>right else 'no higher.'))
    lines += ['', f'{comparisons} comparisons have successful outcomes on both sides. Failure rates and unavailable comparisons remain separate gates.', '',
              '### Result and iteration decision', '',
              f"All {summary['completed']}/{summary['expected']} scheduled slots were attempted; {len(summary['invalid'])} invalid slots remain explicitly listed. ",
              'Passing local mechanism journeys do not establish a passed benchmark or general production desktop availability. ',
              'The scored inputs were not tuned. Any correction discovered from these results requires a fresh cohort; valid failures are not rerolled.', '',
              '### Applied method', '', (REPO/'scripts/evidence/cl11-method-notes.md').read_text(encoding='utf-8'), '',
              'Raw result/prompt/answer/provider event files and original failed development receipts are indexed with byte hashes in ',
              '[CL11.json](../../scripts/evidence/CL11.json) and its raw evidence index.']
    if args.cohort.name == 'scored-2':
        first = json.loads((REPO/'.agent_control/cl11/scored-1/summary.json').read_text(encoding='utf-8'))
        lines += ['', '### Preserved first cohort and repair boundary', '',
                  f"The [first complete report](cl-benchmark-1.1-cohort-1.md) retains {first['completed']}/{first['expected']} attempts and {len(first['invalid'])} invalid slots. ",
                  'It was committed as `6a644511` before the single repair in `7b174909`. Its source/provenance, native receipt, and JSON-envelope limitations remain disclosed; no original grades were edited.', '',
                  'The cohorts have different source/goal/checker hashes after the documented integrity repairs. Their table is descriptive; it does not isolate a causal performance improvement from model variability or the strengthened success criteria.', '',
                  '| Cohort | Arm/model | Valid | Successes | Mean provider tokens |',
                  '|---|---|---:|---:|---:|']
        for name, data in (('scored-1',first),('scored-2',summary)):
            for key, group in data['groups'].items():
                passed = sum(r['success'] for r in data['runs'] if r['valid'] and r['arm']+'/'+r['model']==key)
                tokens = group['tokens']['mean'] if group['tokens'] else None
                lines.append(f"| {name} | {key} | {group['valid']} | {passed} | {tokens} |")
        lines += ['', 'The first native task-22 Haiku repetition-2 success was visually inspected: the actual window field and label both show 42. ',
                  'That confirms this one baseline outcome beyond its writable state receipt. No blanket regrading of first-cohort native outcomes is claimed.', '',
                  'The repaired-cohort native task-22 Haiku repetition-2 outcome was also independently inspected: the actual textbox contains 42 and the native label reads Applied: 42. Its screenshot hash is linked in CL11.json.', '',
                  'The source-only experiment stops after this one repair iteration. A failed efficiency or native comparison gate remains a failed or unproven gate.']
    base = args.report.read_text(encoding='utf-8').split(MARKER)[0]
    base = base.replace(f"Completed {summary['completed']}/{summary['expected']} scheduled runs;",
                        f"Attempted {summary['completed']}/{summary['expected']} scheduled slots;")
    base = '\n'.join(line for line in base.splitlines() if not line.startswith('**Outcome:** '))+'\n'
    main_valid = sum(r['valid'] for r in runs if r['arm'] in {'a','b','c'})
    native_valid = sum(r['valid'] for r in runs if r['arm'].endswith('-alone'))
    def success_count(arm,model):
        rows = [r for r in runs if r['arm']==arm and r['model']==model and r['valid']]
        return f"{sum(r['success'] for r in rows)}/{len(rows)}"
    outcome = (f"**Outcome:** Benchmark has not passed. Main arms: {main_valid}/396 valid; native baselines: {native_valid}/60 valid. "
               f"Luna-b {success_count('b','gpt-6-luna')} vs Luna-a {success_count('a','gpt-6-luna')}; "
               f"Sol-b {success_count('b','gpt-6.1-sol')} vs Sol-a {success_count('a','gpt-6.1-sol')}. "
               "The success gate uses the authored CI rule, which allows Sol's lower observed count because its CI touches zero. "
               f"The small-model gate fails both requirements: mean tokens {summary['groups']['b/gpt-6-luna']['tokens']['mean']:.1f} "
               f"vs {summary['groups']['c/gpt-6.1-sol']['tokens']['mean']:.1f}, with success "
               f"{success_count('b','gpt-6-luna')} vs {success_count('c','gpt-6.1-sol')}. "
               "Unknown per-action knowledge and incomplete native sessions keep the full native comparison unproven.")
    base_lines = base.splitlines()
    base_lines[4:4] = [outcome,'']
    base = '\n'.join(base_lines)+'\n'
    start = base.index('## Per-action native comparison')
    end = base.find('### CL actions that compare worse')
    if end < 0:
        end = base.index('### All-attempt effort differences')
    base = base[:start]+comparison_table(manifest,runs,semantic)+base[end:]
    base = base.replace('### CL actions that compare worse',
                        '### All-attempt effort differences (including failures)')
    lines += ['', '### Remaining native projection defect', '',
              'Final raw-receipt inspection found bracketed native IDs (`[id=...]`) still visible in rendered accessibility text. The earlier `native_ids_hidden_in_text` check searches only for a space-prefixed ` id=` and misses this spelling. ',
              'See [CL11-projection-review.json](../../scripts/evidence/CL11-projection-review.json) for exact result and rendered-text hashes. This projection requirement remains incomplete; automatic argument refusal is separately proven. The runtime stays frozen and scores are unchanged after the one repair iteration.', '',
              '### Native semantic review scope', '',
              f"The active-cohort semantic receipt indexes {semantic.get('indexedRuns',semantic.get('reviewedRuns',0))}/60 native transcripts; {semantic.get('reviewedRuns',0)} have exact-hash manual annotations. ",
              f"See [{semantic_path.name}](../../scripts/evidence/{semantic_path.name}). Predicate attempts and returned errors are not complete-goal passes. ",
              'Host post-C counts, G evaluations, native predicates and state readbacks remain distinct. Native action-specific undo availability may remain unknown even after an independent successful outcome. ',
              'The per-action knowledge/availability gate remains unproven wherever those observations are unknown. No score or confidence interval was changed by this display review.']
    output = base+'\n'.join(lines)+'\n'
    args.report.write_text('\n'.join(line.rstrip() for line in output.splitlines())+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'completed':summary['completed'],'successfulComparisons':comparisons,'report':str(args.report)}))

if __name__ == '__main__':
    main()
