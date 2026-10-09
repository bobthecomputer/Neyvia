#!/usr/bin/env node
'use strict';
// Curated causal audit of the frozen C2c run. Never supplies reference answers.
// Labels below come from reviewed traces, observations and independent grading,
// not regex guesses over executor excuses. Assertions keep key findings falsifiable.
const fs = require('node:fs');
const crypto = require('node:crypto');
const categories = ['planning','search_box','filters','pagination','table_reading','timing','extraction','answer_formatting','grader_disagreement','access_wall','engine'];
const input = 'scripts/evidence/C2c-webvoyager.json';
const gradesPath = 'scripts/evidence/C2c-webvoyager-grades.json';
const output = 'scripts/evidence/C2d-failure-audit.json';
const sha = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const load = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const c = (primary, secondary, mechanism, repair, uncertainty = null) => ({ primary, secondary, mechanism, repair, uncertainty });
const cases = {
  'Apple--0': c('engine', ['extraction','planning'], 'Four verified links reach comparison and shop product pages, but observations retain product names and FAQ/legal text without usable model prices or configuration controls.', 'Allow normal public page resources and observe dynamic product price/configuration readiness before extraction.', 'Snapshots establish missing values, not whether blocked resources, parser scope or page timing caused their absence.'),
  'Apple--1': c('engine', ['planning'], 'Following the observed Support link reaches support.apple.com with usable Search Support and Submit controls; the action returns origin_boundary and execution stops.', 'Grant the observed public destination explicitly, then continue within its origin.'),
  'Apple--2': c('planning', ['search_box','extraction'], 'One combined historical-product query returns 876 results dominated by current products; no result is opened and no price/chip comparison is acquired.', 'Search each requested product precisely, inspect observed historical Newsroom or specifications links, then collect both sides.'),
  'Huggingface--0': c('planning', ['filters','pagination','extraction'], 'Sentiment filter and newest-update ordering show current models on the first result page. No model card or history is opened and no older pages are visited, so March 2023 is never verified.', 'Use the date constraint to plan candidate discovery and inspect model history; do not substitute newest sorting for historical date filtering.'),
  'Huggingface--2': c('planning', ['filters','pagination','extraction'], 'Translation filter plus recently-created order provides a first list of new models, but no card is opened for licensing, release date or popularity evidence. Updated timestamps do not prove release dates.', 'Inspect candidate cards/history and license, apply an explicit popularity criterion, retain all conjunctive constraints.'),
  'BBC News--1': c('planning', ['extraction'], 'Only three article ages are compared on an editorial health page. The independent grader accepts the article and summary but rejects proof that it is latest; the answer itself narrows the claim to latest found.', 'Use a chronological category feed or complete date-ordered search coverage; do not claim global latest from three editorial cards.'),
  'BBC News--2': c('search_box', ['planning','engine'], 'Only Earth, Science and Natural Wonders sections are explored. Site search appears in text but has no actionable retained search control; the requested topic/time intersection is not acquired.', 'Restore public resources and usable search observation, then search the exact topic and verify dates.', 'No qualifying article absence is proved, and the specific reason for the missing search control is unmeasured.'),
  'GitHub--0': c('engine', ['search_box','planning'], 'Observed Search button click returns effect_unconfirmed, then unrelated Trending is opened; neither the topical query nor star-sorted matching set exists.', 'Restore normal public scripts and search interaction; run the topical query and verify stars ordering.', 'No retained network trace attributes modal failure to a specific blocked resource.'),
  'GitHub--1': c('engine', ['search_box','filters'], 'Search button has no verified effect after refresh; no query or update/language filters are applied.', 'Restore normal search behavior, use exact query plus language and updated-date constraints.', 'No retained network trace attributes modal failure to a specific blocked resource.'),
  'Coursera--0': c('engine', ['search_box','filters','planning'], 'Filled query is retained, but clicking Search changes homepage query parameters while repeating homepage content. A later catalog visit supplies no matching filtered course.', 'Restore normal public client behavior; verify actual results before beginner/duration/provider checks.', 'A retained intermediate Search id becomes Clear search after filling; rebind by semantic control after every action.'),
  'Coursera--2': c('engine', ['search_box','pagination','planning'], 'Show 8 more returns effect_unconfirmed; filling the query then clicking Search repeats the same language catalog with a query parameter and no specialization results.', 'Restore public client behavior, search first, then open specialization and extract its entire course list.'),
  'ESPN--2': c('grader_disagreement', ['planning'], 'Captured complete current preseason schedule begins October 5, outside October 2-4. The executor honestly reports no qualifying game; strict frozen grader fails the presupposed score/highlight clauses.', 'Retain frozen task and strict grade; report the unavailable live-date premise explicitly, never invent a game.', 'This is task/live-data incompatibility under the existing rubric, not evidence that a different answer or browser repair can create the requested event.'),
};
for (const id of ['Google Search--0','Google Search--1','Google Search--2']) cases[id] = c('planning', ['search_box','extraction'], 'Executor claims no submit control, but the final captured form exposes element 18, role button, empty name, nonempty value Advanced Search or Recherche avancée, actions click. No attempt to click that observed button is recorded.', 'Include input button value in semantic labels; recognize and click the retained submit control.');
for (const id of ['Wolfram Alpha--0','Wolfram Alpha--1','Wolfram Alpha--2']) cases[id] = c('engine', ['search_box'], 'Input fill returns fetch failed and the following Compute click returns effect_unconfirmed; unchanged observations have no computed result. The run records a missing standard value setter as the backend diagnosis.', 'Repair the actual input setter route, verify the input value, then submit and wait for result evidence.', 'Trace contains transport failure; setter-specific diagnosis also relies on the executor receipt and dedicated fill-repair receipt.');
for (const id of ['Booking--0','Booking--1','Booking--2']) cases[id] = c('engine', ['search_box','timing'], 'Repeated observations have empty title, whitespace-only text and zero elements; there is no captured login, CAPTCHA or access wall. No hotel search can start.', 'Allow legitimate public page resources and verify nonblank readiness before interacting.', 'Blank rendering is proved. Specific network/resource failure is not established by the snapshots.');
for (const id of ['Cambridge Dictionary--0','Cambridge Dictionary--1','Cambridge Dictionary--2']) cases[id] = c('access_wall', ['engine','search_box'], 'Captured page reports Please allow ads on this site, Allow Ads to Continue and Vital API blocked; baseline grader records skip. Same-origin-only request policy aborts public third-party resources, so this may be a self-induced page failure.', 'Revisit with legitimate public page resources enabled; preserve automation disclosure and respect any remaining real access challenge.', 'Observed wall is certain; self-induced resource blocking is a code-supported hypothesis requiring a fresh run. Baseline skip grade is unchanged.');
function audit() {
  const run = load(input), grades = load(gradesPath);
  const rows = run.tasks.map(t => {
    const grade = grades.grades.find(g => g.id === t.id);
    if (!grade) throw Error('Missing grade ' + t.id);
    const observations = t.observations.map(ref => {
      if (sha(ref.path) !== ref.sha256) throw Error('Observation integrity failed: ' + ref.path);
      return { ref, value: load(ref.path) };
    });
    const classification = cases[t.id] || (grade.success ? c(null, [], 'All requested clauses passed independent grading with retained observations.', null) : null);
    if (!classification) throw Error('Unreviewed failure ' + t.id);
    if (classification.primary && !categories.includes(classification.primary)) throw Error('Invalid category');
    if (t.id.startsWith('Google Search--')) {
      const button = observations.at(-1).value.elements.find(e => e.role === 'button' && e.value && e.actions.includes('click'));
      if (!button || button.id !== '18') throw Error('Google submit finding no longer matches captured evidence');
    }
    if (t.id.startsWith('Booking--') && observations.some(o => o.value.text.trim() || o.value.totalElements !== 0)) throw Error('Booking blank finding changed');
    const trace = (t.trace || []).map(s => {
      const a = s.action || {}, before = observations.find(o => o.value.revision === a.revision);
      const element = before?.value.elements.find(e => String(e.id) === String(a.element));
      return { action: a.action, element: a.element, label: element ? (element.name || element.value || '') : null, error: s.error || s.response?.error || null, status: s.response?.status || null, verified: s.response?.verification?.verified ?? null, ms: s.ms };
    });
    const apiMs = (t.calls || []).reduce((sum, index) => sum + (run.calls[index]?.ms || 0), 0);
    return { id: t.id, outcome: grade.outcome, ...classification, missingClauses: grade.missingClauses, executorReason: t.reason || null, evidence: observations.map(o => ({ ...o.ref, title: o.value.title, textLength: o.value.text.length, elementCount: o.value.totalElements, truncated: o.value.truncated, tablesTruncated: o.value.tablesTruncated, verifiedSha256: true })), trace, latency: { elapsedMs: t.elapsedMs, retainedAPICallMs: apiMs, outsideRetainedCallsMs: Math.max(0, (t.elapsedMs || 0) - apiMs), boundary: 'Outside calls includes model decisions, operator/tool orchestration, parallel queuing and any unrecorded work; it is not isolated model latency.' } };
  });
  if (rows.length !== 36 || new Set(rows.map(r => r.id)).size !== 36) throw Error('Frozen 36-task completeness failed');
  const counts = Object.fromEntries(categories.map(key => [key, { primary: rows.filter(r => r.primary === key).length, secondary: rows.filter(r => r.secondary.includes(key)).length }]));
  const report = { schema: 'neyvia.C2d.failure-audit@1', auditedAt: new Date().toISOString(), frozenTaskSetSha256: run.taskSetSha256, inputs: [{ path: input, sha256: sha(input) }, { path: gradesPath, sha256: sha(gradesPath) }], method: 'Human reviewed each failed/skipped task trace and retained observations plus independent clause grading. Curated case decisions are executable, snapshot hashes verified, no reference answer copied. Baseline grades remain unchanged.', categories: counts, summary: { total: rows.length, passed: rows.filter(r => r.outcome === 'success').length, failed: rows.filter(r => r.outcome === 'failed').length, skipped: rows.filter(r => r.outcome === 'skipped').length }, commonMechanism: { path: 'src/grant_agent/browser_obscura.py', observation: '_open aborts every request whose origin differs from the opening URL, including public scripts/resources. This can prevent ordinary sites from rendering/hydrating; assets are not agent permission grants.', boundary: 'Code establishes the policy; captured snapshots do not identify individual failed requests. Fresh runs are required to establish task-specific causality.' }, categoriesWithNoDemonstratedFailure: categories.filter(k => !counts[k].primary && !counts[k].secondary), tasks: rows };
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ output, summary: report.summary, categories: counts }));
  return report;
}
module.exports = { audit };
async function main() {
  const report = audit();
  const args = process.argv.slice(2), files = [];
  let tariff = null;
  for (let i = 0; i < args.length; i += 2) {
    if (args[i] === '--session') files.push(args[i + 1]);
    else if (args[i] === '--tariff') tariff = JSON.parse(args[i + 1]);
    else throw Error('Supported audit flags: --session <rollout.jsonl> (repeatable), --tariff <explicit JSON>');
  }
  if (files.length) {
    const { meter } = require('./c2d_token_meter.cjs');
    report.baselineCodexUsage = await meter({ run: load(input), files, cwd: process.cwd(), tariff });
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ unionTokens: report.baselineCodexUsage.unionTokens, ambiguousTasks: report.baselineCodexUsage.tasks.filter(t => t.attribution === 'ambiguous_overlap').length, estimatedUSD: tariff ? 'explicit tariff only' : null }));
  }
}
if (require.main === module) main().catch(e => { console.error(e.message); process.exitCode = 1; });
