#!/usr/bin/env node
'use strict';
// An independent semantic review is an input, never inferred from executor status.
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sha = path => hash(fs.readFileSync(path));
const norm = value => String(value ?? '').replace(/\s+/gu, ' ').trim();
const taskPath = 'scripts/evidence/C2-webvoyager-tasks.json';
const referencePath = 'scripts/evidence/C2-webvoyager-references.json';
const expectedTasks = 'f66cd0713f3634e4db44164bc940e3f2d79e564a98dd0ad05ccc0d7ba1fe2be4';
function quantile(values, q) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (q === .5 && sorted.length) return (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2;
  return sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * q) - 1)] : null;
}
function linearQuantile(values, q) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * q;
  const lower = Math.floor(position), upper = Math.ceil(position);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}
function loadObservations(task) {
  return (task?.observations ?? []).map(ref => {
    // Large release-gate runs keep observations on D:; C2_EVIDENCE_ROOT names that one root.
    const root = path.resolve(process.env.C2_EVIDENCE_ROOT || 'scripts/evidence');
    const resolved = path.resolve(ref.path);
    if (!resolved.startsWith(root + path.sep)) throw Error(`Observation outside evidence scope: ${ref.path}`);
    if (sha(ref.path) !== ref.sha256) throw Error(`Observation hash mismatch: ${ref.path}`);
    const value = JSON.parse(fs.readFileSync(ref.path));
    return { ref, value };
  });
}
function evidence(locator, observations) {
  const rows = observations.filter(row => !locator.path || row.ref.path === locator.path);
  for (const row of rows) {
    const field = locator.field ?? 'text';
    const structured = typeof row.value[field] === 'object';
    const content = structured ? JSON.stringify(row.value[field]) : norm(row.value[field]);
    const wanted = structured ? locator.quote : norm(locator.quote);
    const start = content.indexOf(wanted);
    if (wanted && start >= 0) return {
      path: row.ref.path, sha256: row.ref.sha256, url: row.value.url ?? row.ref.url,
      field, quote: wanted, verifiedSha256: true, whitespaceNormalized: !structured,
      capturedAt: row.value.capturedAt ?? row.ref.capturedAt ?? null,
    };
  }
  throw Error(`Reviewed fresh evidence missing: ${JSON.stringify(locator)}`);
}
function answerDigest(task) {
  return hash(JSON.stringify({ answer: task?.answer ?? null, status: task?.status ?? null, reason: task?.reason ?? null }));
}
function grade(runPath, reviewPath, outPath) {
  const run = JSON.parse(fs.readFileSync(runPath));
  const frozen = JSON.parse(fs.readFileSync(taskPath));
  const references = JSON.parse(fs.readFileSync(referencePath));
  if (sha(taskPath) !== expectedTasks) throw Error('Frozen task set changed');
  if (run.taskSetSha256 && run.taskSetSha256 !== expectedTasks) throw Error('Executor task set differs');
  if (run.tasks.length !== 36 || new Set(run.tasks.map(t => t.id)).size !== 36) throw Error('Exactly 36 unique tasks required');
  if (!run.finishedAt || run.tasks.some(t => !t.finishedAt)) throw Error('Cannot grade a partial run');
  const review = reviewPath ? JSON.parse(fs.readFileSync(reviewPath)) : { reviews: {} };
  if (review.runSha256 && review.runSha256 !== sha(runPath)) throw Error('Independent review is not bound to this run');
  const rows = frozen.tasks.map(goal => {
    const task = run.tasks.find(t => t.id === goal.id);
    if (!task || task.goal !== goal.goal || task.startUrl !== goal.startUrl) throw Error(`Frozen task differs: ${goal.id}`);
    const observations = loadObservations(task);
    const decision = review.reviews[goal.id];
    const base = {
      id: goal.id, goal: goal.goal, executorStatus: task.status,
      startedAt: task.startedAt ?? null, finishedAt: task.finishedAt ?? null,
      acquisitionElapsedMs: task.elapsedMs ?? null,
      deterministicExecutionElapsedMs: task.elapsedMs ?? null,
      answerReturnedAt: task.answerReturnedAt ?? null,
      answerExtractionMs: task.extractionMs ?? null,
      semanticActionSteps: task.steps ?? null,
      apiCalls: (run.calls ?? []).filter(call => call.taskId === goal.id).length,
      endToEndGoalElapsedMs: task.goalFinishedAt ? Date.parse(task.goalFinishedAt) - Date.parse(task.startedAt) : null,
      tokens: task.tokens ?? null, paidModelCostUSD: task.paidModelCostUSD ?? null,
      localComputeCostUSD: null, engineeringTokens: null, engineeringCostUSD: null,
      answer: task.answer ?? null, answerSha256: answerDigest(task),
      observationIntegrity: observations.map(row => ({ ...row.ref, verified: true })),
      reference: { path: referencePath + '#' + goal.id, type: references.answers[goal.id]?.type ?? null },
      timing: task.timing ?? null,
    };
    if (!decision) return { ...base, outcome: 'ungraded', success: false, evidenceCoverageComplete: false, clauses: [], reason: 'Fresh observations await independent clause review.' };
    if (decision.answerSha256 !== base.answerSha256) throw Error(`Review answer digest mismatch: ${goal.id}`);
    const clauses = decision.clauses.map(clause => ({ ...clause, evidence: (clause.evidence ?? []).map(locator => evidence(locator, observations)) }));
    const complete = clauses.length > 0 && clauses.every(clause => clause.met && clause.evidence.length > 0);
    if (decision.evidenceCoverageComplete && !complete) throw Error(`Complete coverage without all-clause evidence: ${goal.id}`);
    const hasReturnedAnswer = task.answer !== undefined && task.answer !== null && String(task.answer).trim() !== '';
    if (decision.outcome === 'passed' && (!complete || !hasReturnedAnswer)) throw Error(`Pass requires a returned answer and every clause: ${goal.id}`);
    if (decision.outcome === 'passed' && task.ownerHandoff) throw Error(`Owner-assisted access walls remain needs_owner: ${goal.id}`);
    const extraction = decision.postRunExtraction ?? null;
    if (extraction?.evidence) extraction.evidence = extraction.evidence.map(locator => evidence(locator, observations));
    const ownerBoundaryEvidence = (decision.ownerBoundaryEvidence ?? []).map(locator => evidence(locator, observations));
    if (decision.ownerBoundary?.priorReceiptPath && sha(decision.ownerBoundary.priorReceiptPath) !== decision.ownerBoundary.priorReceiptSha256) throw Error(`Owner boundary receipt changed: ${goal.id}`);
    return { ...base, outcome: decision.outcome, success: decision.outcome === 'passed', reason: decision.reason, clauses,
      endToEndGoalElapsedMs: decision.outcome === 'passed' && task.answerReturnedAt ? Date.parse(task.answerReturnedAt) - Date.parse(task.startedAt) : base.endToEndGoalElapsedMs,
      evidenceCoverageComplete: !!decision.evidenceCoverageComplete,
      missingClauses: [...clauses.filter(c => !c.met).map(c => c.requirement), ...(decision.answerMissingClauses ?? [])],
      postRunExtraction: extraction, ownerBoundaryEvidence, ownerBoundary: decision.ownerBoundary ?? null,
      answerForm: decision.answerForm ?? null, reference: { ...base.reference, comparison: decision.referenceComparison ?? null } };
  });
  const summary = Object.fromEntries(['passed', 'failed', 'needs_owner', 'ungraded'].map(k => [k, rows.filter(row => row.outcome === k).length]));
  const metrics = {
    deterministicTaskLatencyP50Ms: quantile(rows.map(r => r.deterministicExecutionElapsedMs), .5),
    deterministicTaskLatencyP95Ms: quantile(rows.map(r => r.deterministicExecutionElapsedMs), .95),
    linearInterpolationP95Ms: linearQuantile(rows.map(r => r.deterministicExecutionElapsedMs), .95),
    quantileMethod: 'Median averages the middle pair; primary p95 uses nearest rank. The separately named linearInterpolationP95Ms interpolates at (n-1)*q.',
    acquisitionLatencyP50Ms: quantile(rows.map(r => r.acquisitionElapsedMs), .5),
    acquisitionLatencyP95Ms: quantile(rows.map(r => r.acquisitionElapsedMs), .95),
    endToEndGoalLatencyP50Ms: quantile(rows.map(r => r.endToEndGoalElapsedMs), .5),
    endToEndGoalLatencyP95Ms: quantile(rows.map(r => r.endToEndGoalElapsedMs), .95),
    endToEndGoalTimingMeasured: rows.filter(r => r.endToEndGoalElapsedMs !== null).length,
    evidenceCoverageComplete: rows.filter(r => r.evidenceCoverageComplete).length,
    latencyTargetProven: rows.every(r => r.endToEndGoalElapsedMs !== null) && quantile(rows.map(r => r.endToEndGoalElapsedMs), .5) < 30000,
    successTargetMet: summary.passed === 36,
    successFractionAllTasks: summary.passed / 36,
    successFractionNonOwnerTasks: summary.passed / (36 - summary.needs_owner),
    measuredExecutionTokens: rows.every(r => r.tokens !== null) ? rows.reduce((total, row) => total + row.tokens, 0) : null,
    measuredPaidProviderCostUSD: rows.every(r => r.paidModelCostUSD !== null) ? rows.reduce((total, row) => total + row.paidModelCostUSD, 0) : null,
    costBoundary: 'Per-task deterministic execution tokens and paid provider cost only; engineering/adviser tokens, operator time and local CPU/electricity cost are unmetered.',
  };
  const report = {
    schema: 'neyvia.C2f.independent-grades@1', gradedAt: new Date().toISOString(), draft: summary.ungraded > 0,
    run: { path: runPath, sha256: sha(runPath) }, taskSet: { path: taskPath, sha256: sha(taskPath) },
    references: { path: referencePath, sha256: sha(referencePath), executorAccess: false },
    executorSourcesAtReview: ['scripts/c2f_replay.cjs', 'scripts/c2f_answers.cjs'].map(sourcePath => ({ path: sourcePath, sha256: sha(sourcePath) })),
    executorSourceBoundary: 'Source hashes observed at review time; execution-time admission and runtime source binding are separately established by the final run seal.',
    grader: { identity: review.graderIdentity || 'Separate post-run evidence review; reviewer identity not supplied', source: { path: 'scripts/c2f_grade.cjs', sha256: sha('scripts/c2f_grade.cjs') },
      review: reviewPath ? { path: reviewPath, sha256: sha(reviewPath) } : null,
      method: review.method || 'Separate post-run clause review bound to exact executor answer/status/reason and every fresh observation SHA. Passage matching locates reviewed proof; never awards a semantic pass automatically.' },
    protocol: { allClausesRequired: true, noCachedAnswers: true,
      negativeAnswers: 'Absence requires complete exact topic/date/filter/order coverage.',
      latestAndRanking: 'Require current dated/ordered/complete-set evidence, not a single acquired page.',
      utcRunDate: run.startedAt?.slice(0, 10) ?? null,
      relativeDates: 'Evaluate relative dates against the final run UTC date; a previously learned URL with stale date parameters does not establish the current date window.',
      postRunExtraction: 'Grader-created fresh fact extraction is separate from a returned executor answer and never retroactively changes end-to-end task latency or success.',
      taskTimer: 'Execution elapsed includes recorded executor extraction before answerReturnedAt and finishedAt; later independent grading and owned tab teardown are excluded. Complete-goal latency is reported only for independently passed returned answers.',
      stickyGoogleNews: 'Prior owner-needed CAPTCHA remains owner-needed, without an attempted bypass.' },
    summary, metrics, grades: rows,
  };
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ out: outPath, summary, metrics }));
  return report;
}
module.exports = { grade, loadObservations, norm, sha, answerDigest, evidence };
if (require.main === module) {
  const args = process.argv.slice(2);
  const get = (flag, fallback) => args.includes(flag) ? args[args.indexOf(flag) + 1] : fallback;
  try { grade(get('--run'), get('--review', null), get('--out', 'scripts/evidence/C2f-grades.json')); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
