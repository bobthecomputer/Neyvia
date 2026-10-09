"""Render the sealed, verified C4c evidence without inventing missing results."""
import json
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
def number(value):
    return 'unmeasured' if value is None else f'{value:,.3f}'
def interval(value):
    return 'unmeasured' if value is None else '['+', '.join(number(x) for x in value)+']'
def metric(value):
    return number(value['mean'])+' '+interval(value['ci95'])

def main():
    r=json.loads((REPO/'scripts/evidence/C4c.json').read_text(encoding='utf-8'))
    lines=['# C4c: paired broad-panel token study','',
        'The frozen study contains 18 original blind tasks, two repetitions and two arms. '
        'The native Character Map task is waiting for C11: its four rows contain zero native inputs and zero model calls. '
        'The remaining 68 rows are actual GPT-6 Luna medium runs through Neyvia\'s production CL gateway. '
        'No answer or preference keys were opened.','',
        'The efficient arm enables procedures, acknowledged state diffs, lossless archival compaction, ordered batching '
        'and the short stable prefix. The control disables all five, returns full observations/history and one call per turn, '
        'and uses a detailed prefix with a changing turn marker. Both use identical original tasks, inputs, '
        'postconditions, independent checks, model and 24-turn limit. This evaluates the combined intervention; '
        'it does not attribute a causal effect to each individual mechanism.','',
        'Tasks/arms were interleaved using seed 41729, in fresh roots. Four workers used ports 48733–48736; '
        'three freed workers drained later unstarted slots on 48731, 48732 and 48739 under the exclusive-root guard. '
        'Actual UI checks were serialized on fixture 48737 / Obscura 48738. No Chrome, Edge, visible windows, '
        'public service, supervisor, credentials or NAS was used. Source bytes were frozen before the matrix, '
        'copied into the archive and independently checked again when sealing. '
        'After all original trials returned, the collector was repaired for UTF-8 subprocess output, Windows byte-lock '
        'admission and retention of a completed CL receipt when a later quality call raises. The sealer accepts only '
        'these exact transport patches against the frozen source; C4 model/host mechanisms and task/check semantics '
        'remain identical. Frozen and patched source bytes/hashes are both retained.','',
        'Three original summaries lost their token metadata after collection errors. Their real 24/12/24-turn '
        'receipts and raw usage were recovered, with the original failed summaries preserved. One UI control '
        'run was actually interrupted by the byte-lock error. Both arms of that pair were repeated once in '
        'fresh roots; the two originals remain charged as overhead. The date and browsing runs had already '
        'reached their turn limit and remain failures after identical checks. Three affected pairs were '
        're-reviewed using corrected artifacts/grades; original reviews remain archived and charged. '
        'The canonical matrix still has exactly two paired repetitions per task. No successful-only selection '
        'or continuation of a failed model run is used.','',
        '## Observed outcome','',
        '| Arm | Completed | Total tokens | Cached input | Uncached input | Output | List-price equivalent |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for arm in ('efficient','control'):
        v=r['totals'][arm];t=v['tokens']
        lines.append(f"| {arm} | {v['successes']}/{v['attempts']} | {t['total']:,} | {t['cachedInput']:,} | {t['uncachedInput']:,} | {t['output']:,} | ${v['costUsd']:.6f} |")
    lines += ['',
        f"Total-token savings: {r['totalTokenSavingsPercent']:.2f}% (95% CI {interval(r['ci95']['totalTokenSavingsPercent'])}). "
        f"Cost savings: {r['costSavingsPercent']:.2f}% (95% CI {interval(r['ci95']['costSavingsPercent'])}). "
        f"Completion-rate difference, efficient minus control: 95% CI {interval(r['ci95']['successDifference'])}.",
        f"Objective check-fraction difference CI: {interval(r['ci95']['objectiveCheckFractionDifference'])}; "
        f"blinded rubric difference (0–4) CI: {interval(r['ci95']['blindedQualityDifference0to4'])}.",'',
        'These intervals resample 17 paired task clusters 10,000 times, keeping both repetitions together. '
        'Savings count failures as well as successes: they are observed attempt costs, not evidence of equal-quality '
        'completion. They describe this purposive panel, not all possible tasks. Per-task means use Student t '
        'intervals with one degree of freedom; observed completion rates use Wilson intervals. Domain bounds '
        'are clipped to zero / one / four where appropriate. With two runs, these intervals are usually very wide.','',
        f"Mechanism telemetry: `{json.dumps(r['mechanismTelemetry'],sort_keys=True)}`.",'',
        '## Low-budget bug repair','',
        'The original bug task requires preserving user-message order, placing the summary before the latest user '
        'message, counting empty content as zero, adding regressions and writing the report. '
        'The final procedure completed all four runs (two at 2,000 host tokens, two at 2,200). '
        f"Conditional observed success CI: {interval(r['pressureSuccessCi95'])}. "
        'Each ran the exact requested unittest workload and separate zero/one/multiple-user and token semantics. '
        'The lead also inspected the resulting source and regressions.','',
        'The diagnosis and repairs are specific and evidence-bounded:','',
        '- Source observations exposed JSON-escaped newlines as source, encouraging repeated projection/page reads. '
        'Source presentation now decodes losslessly into an explicitly untrusted DATA block; raw archival bytes remain unchanged.',
        '- A history read batched with a real tool call previously reached the production dispatcher as an unknown tool. '
        'The host now executes mixed recovery and production calls in order, stopping on the first failure.',
        '- Verified procedure receipts were easy to lose among compacted reads. The host retains exact P `ok +G` receipts '
        'and the last failed check/diagnostic. The executable context journey proves failure feedback survives later observations '
        'and proves a partial or injected source page cannot acknowledge unrelated state.',
        '- Models continued terminal inspection, reread verified edits or failed to create the report. '
        'The maintained bounded workflow supplies only workspace tools, explicitly says what P readback already proves, '
        'and calls `done()` immediately after the edits and report. The host then runs the actual regression and semantic '
        'checks and returns repair feedback. No code answer is supplied by the procedure.',
        '- Broader terminal tasks exposed a separate grounding gap: the CL observer expected a nonexistent terminal manual '
        'and did not expose the saved command result. The gateway now resolves the actual protocol owner, rereads the existing '
        'NativeActionStore record/result and verifies its hash, command and successful completion. The real system-Python '
        'journey proves stdout/exit code, corruption refusal and nonzero failure without weakening replay or permission guards.','',
        'The final four bounded runs needed no compaction. They establish the shorter workflow on this bug, '
        'not universal reliability or long-context model recovery. Earlier failed and partly successful pressure '
        'variants remain archived and charged as overhead; none were replaced by the final four.','',
        '| Budget | Repetition | Passed | Turns | Compactions | Total / cached tokens | Cost |',
        '|---:|---:|---|---:|---:|---:|---:|']
    for v in r['pressure']:
        lines.append(f"| {v['budget']} | {v['repetition']} | {v['passed']} | {v['contextMetrics']['turns']} | {v['contextMetrics']['compactions']} | {v['tokens']['total']:,} / {v['tokens']['cachedInput']:,} | ${v['costUsd']:.6f} |")
    lines += ['', '## Per-task outcomes and 95% intervals','',
        'Token cells give observed total / cached input sums, then per-run total and cached mean CIs. '
        'Cost cells give observed sum, then per-run mean CI. Objective quality is the fraction of executable '
        'task checks passed; it is not a universal quality scale. Blinded quality is the mean of correctness, '
        'completeness, clarity and finish ratings (each 0–4) under the frozen rubric. '
        'Native rows are unattempted, not failed trials. Exact input/output totals and all estimates are in '
        '[per-task.json](../../scripts/evidence/C4c/per-task.json).','',
        '| Task / arm | Tokens and cached input | Cost (USD) | Completed; success CI | Objective fraction CI | Blinded quality CI |',
        '|---|---|---|---|---|---|']
    for task in r['perTask']:
        for arm in ('efficient','control'):
            v=task['arms'][arm]
            if not v['attempts']:
                lines.append(f"| {task['task']} / {arm} | 0; waiting C11 | 0 | unattempted | unmeasured | unmeasured |")
                continue
            t=v['tokenTotals'];m=v['tokensPerRun']
            lines.append(f"| {task['task']} / {arm} | sum {t['total']:,} / {t['cachedInput']:,}; total/run {metric(m['total'])}; cached/run {metric(m['cachedInput'])} | sum ${v['totalCostUsd']:.6f}; per run {metric(v['costPerRun'])} | {v['successes']}/{v['attempts']}; {interval(v['successCi95'])} | {metric(v['objectiveCheckFraction'])} | {metric(v['blindedQuality0to4'])} |")
    whole=r['wholeObservedWork']
    lines += ['', '## Accounting, proof and limits','',
        f"All observed C4c work, including discarded matrices, diagnostics, pressure experiments and blinded reviews: "
        f"{whole['tokens']['total']:,} total tokens, {whole['tokens']['cachedInput']:,} cached input, "
        f"${whole['costUsd']:.6f} list-price equivalent. "
        f"{len(whole['incompleteUsagePaths'])} event files have no completed usage; their charge is an unknown lower bound. "
        'Lead/sub-agent session usage is unavailable and excluded. Cached input is already included in input; '
        'total is input plus output. Rates come from the frozen local price record, not an invoice.','',
        f"The blinded judge produced {r['judgeSuccessfulPairs']}/{r['judgePairs']} structured paired reviews. "
        'It saw anonymous artifacts and measured checks without arm identities or token counts. '
        'It is an uncalibrated Luna judgement, not a human preference panel. UI judging sees submitted code; '
        'actual rendering and interactions are checked separately by Neyvia\'s Obscura engine.','',
        'Proof is in [C4c.json](../../scripts/evidence/C4c.json), the hash-verified '
        '[run archive](../../scripts/evidence/C4c/runs.zip), its entry manifest, original provider events/proposals, '
        'saved action results, independent workload output and actual light/dark screenshots. '
        '[Windows transport](../../scripts/evidence/C4c-transport.json) proves the original byte-read refusal, '
        'correct lock waiting with bytes preserved, and UTF-8 stdout/stderr from a real failed command. '
        '[Context](../../scripts/evidence/C4c-context.json), '
        '[host](../../scripts/evidence/C4c-host.json) and '
        '[terminal](../../scripts/evidence/C4c-terminal.json) journeys prove recovery and rejection paths. '
        'The archive preserves unsuccessful trials as well as successful ones. The ledger receives one appended '
        'study entry after sealing; older C4b receipts remain unchanged.','']
    lines += ['- '+limit for limit in r['limits']]
    lines += ['- Programmatic button focus proves focusability; visible keyboard focus is still unverified.',
              '- No new backend/native command or UI IPC is added. `context.read(view="source")` is an existing '
              'CLI-host action registered in `execute_proposal` and documented in the short prefix/manual. '
              '`--full-mechanism-control` is registered in the efficient CLI parser and wired to runner ablation. '
              'Terminal uses the existing protocol tool, dispatcher, NativeActionStore and permission gates.',
              '- Paul need not open an app. Native proof awaits the C11 agent desktop; no release/push/merge is requested.','']
    (REPO/'docs/research/C4c.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Wrote docs/research/C4c.md from the sealed receipt')

if __name__=='__main__':main()
