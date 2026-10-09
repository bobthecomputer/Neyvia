// Real C9b owner HTTP journey. The active-run case is explicitly controlled.
import {readFile, writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {resolve, dirname} from 'node:path';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(repo, 'scripts/evidence/C9b-runs/runtime');
const receiptPath = resolve(repo, 'scripts/evidence/C9b-http.json');
const base = 'http://127.0.0.1:48761';
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const source = JSON.parse(await readFile(resolve(repo, 'scripts/evidence/C9b-source.json'), 'utf8'));
const observeDraft = process.argv.includes('--observe-draft');
const resumeDraft = observeDraft || process.argv.includes('--resume-draft');
let previousReceipt;
const record = {schema: 'neyvia.c9b-http-proof.v1', at: new Date().toISOString(), port: 48761,
  sourceRun: source.runId, sourceSession: source.sessionId,
  boundary: 'Actual Luna output run, production HTTP dispatch/store; feedback text is controlled verifier input, not a recorded Paul vote. Active refusal uses a separate controlled live-owner RunStore record.',
  checks: [], events: [], limitations: []};
try {
  const previous = JSON.parse(await readFile(receiptPath, 'utf8'));
  previousReceipt = previous;
  record.priorFailures = [...(previous.priorFailures || []), ...(previous.passed === false ?
    [{at: previous.at, error: previous.error, checks: previous.checks?.filter(c => !c.passed), draftJob: previous.draftJob, limitations: previous.limitations}] : [])];
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
let cookie = '', fixture, cursor;
const env = {...process.env, PYTHONDONTWRITEBYTECODE: '1'};
const checkpoint = () => writeFile(receiptPath, JSON.stringify(record, null, 2) + '\n');
async function http(path, body, authenticated = true) {
  const response = await fetch(base + path, {method: 'POST', headers: {'Content-Type': 'application/json', ...(authenticated && cookie ? {Cookie: cookie} : {})},
    body: JSON.stringify(body), signal: AbortSignal.timeout(30_000)});
  return {status: response.status, json: await response.json(), response};
}
async function api(command, payload) {
  const started = performance.now();
  const r = await http('/api/backend', {command, payload});
  return {status: r.status, body: r.json, elapsedMs: Math.round(performance.now() - started)};
}
function check(name, condition, detail = {}) {
  record.checks.push({name, passed: Boolean(condition), ...detail});
  console.log(JSON.stringify({check: name, passed: Boolean(condition)}));
  if (!condition) throw new Error('Failed: ' + name);
}
async function child(code, args = []) {
  const p = spawn(python, ['-u', '-c', code, ...args], {cwd: repo, env, windowsHide: true});
  let output = '', errors = '';
  p.stdout.on('data', x => {output += x;});
  p.stderr.on('data', x => {errors += x;});
  await new Promise((ok, fail) => {p.once('error', fail); p.once('close', c => c === 0 ? ok() : fail(new Error(errors.slice(0, 500) || `Process exited ${c}`)));});
  return JSON.parse(output.trim());
}
try {
  const login = await http('/api/auth/local-session', {}, false);
  cookie = login.response.headers.getSetCookie().map(x => x.split(';')[0]).join('; ');
  check('local owner sign-in', login.status === 200 && Boolean(cookie), {status: login.status});
  const anonymous = await http('/api/backend', {command: 'task_feedback_get_command', payload: {runId: source.runId}}, false);
  check('unauthenticated feedback refused', anonymous.status === 401 || anonymous.status === 403, {status: anonymous.status, code: anonymous.json.code});
  const subscription = await api('connected_events_poll_command', {waitSeconds: 0});
  check('connected cursor acquired before feedback mutations', subscription.status === 200 && Number.isSafeInteger(subscription.body.data.cursor));
  cursor = subscription.body.data.cursor;
  const goodBody = {runId: source.runId, sessionId: source.sessionId, verdict: 'good', reason: '', reasonSource: 'typed', requestId: randomUUID()};
  let priorFeedbackId;
  if (resumeDraft) {
    if (previousReceipt?.sourceRun !== source.runId) throw new Error('Resume requires the same actual source run');
    record.carriedValidationAt = previousReceipt.at;
    record.checks.push(...previousReceipt.checks.filter(c => c.passed && !['local owner sign-in', 'unauthenticated feedback refused',
      'connected cursor acquired before feedback mutations', 'new request replaces feedback and queues drafting',
      'feedback saved event on connected cursor', 'new process reload preserves replacement verdict and lesson count', 'lesson list limit enforced'].includes(c.name)));
    record.goodFeedbackId = previousReceipt.goodFeedbackId;
    if (observeDraft) {
      record.events = previousReceipt.events || [];
      cursor = record.events.at(-1)?.cursor ?? cursor;
    }
    const current = await api('task_feedback_get_command', {runId: source.runId});
    if (current.status !== 200) throw new Error('Existing source feedback could not be read');
    priorFeedbackId = current.body.data.feedback.id;
  } else {
  // A generated disposable account on this owned scratch backend verifies the
  // account boundary. Its random password and cookies stay only in memory.
  const username = 'c9b-other-' + randomUUID().slice(0, 8);
  const password = randomUUID() + randomUUID();
  const created = await api('accounts_update_command', {op: 'create', username, displayName: 'C9b controlled non-owner', password});
  check('controlled non-owner account created in scratch host', created.status === 200, {status: created.status});
  const ownerCookie = cookie;
  const foreignLogin = await http('/api/auth/login', {username, password}, false);
  check('controlled non-owner authenticated', foreignLogin.status === 200);
  cookie = foreignLogin.response.headers.getSetCookie().map(x => x.split(';')[0]).join('; ');
  for (const [command, payload] of [
    ['task_feedback_get_command', {runId: source.runId}],
    ['task_feedback_submit_command', {runId: source.runId, sessionId: source.sessionId, verdict: 'wrong', requestId: randomUUID()}],
    ['lesson_list_command', {runId: source.runId}],
    ['lesson_revert_command', {lessonId: 'controlled-private-probe', requestId: randomUUID()}],
  ]) {
    const refusal = await api(command, payload);
    check('non-owner refused ' + command, refusal.status === 403 && refusal.body.code === 'owner_required' && !refusal.body.data,
      {status: refusal.status, code: refusal.body.code});
  }
  await http('/api/auth/logout', {});
  cookie = ownerCookie;
  const good = await api('task_feedback_submit_command', goodBody);
  check('actual terminal run good feedback saved', good.status === 200 && good.body.data.feedback.verdict === 'good', {elapsedMs: good.elapsedMs, status: good.status, ...(good.status === 200 ? {} : {response: good.body})});
  record.goodFeedbackId = good.body.data.feedback.id;
  priorFeedbackId = good.body.data.feedback.id;
  const retry = await api('task_feedback_submit_command', goodBody);
  check('same request idempotent', retry.status === 200 && retry.body.data.feedback.id === good.body.data.feedback.id);
  const conflict = await api('task_feedback_submit_command', {...goodBody, verdict: 'wrong'});
  check('conflicting retry refused', conflict.status === 409 && conflict.body.code === 'request_id_conflict', {status: conflict.status, code: conflict.body.code});
  const mismatch = await api('task_feedback_submit_command', {...goodBody, sessionId: source.sessionId + '-different', requestId: randomUUID()});
  check('different session refused', mismatch.status === 403 && mismatch.body.code === 'session_mismatch', {status: mismatch.status, code: mismatch.body.code});
  const read = await api('task_feedback_get_command', {runId: source.runId});
  check('get returns durable feedback', read.status === 200 && read.body.data.feedback.id === good.body.data.feedback.id);
  const evidence = read.body.data.feedback;
  check('saved exact source output hashes and task', JSON.stringify(evidence.outputs) === JSON.stringify(source.outputs) && evidence.taskText === source.task.task,
    {outputs: evidence.outputs, doneStatus: evidence.doneStatus});
  for (const output of evidence.outputs) {
    const bytes = await readFile(resolve(evidence.workspaceRoot, output.path));
    check('source bytes independently hash checked ' + output.path, createHash('sha256').update(bytes).digest('hex') === output.sha256);
  }
  // Read after asynchronous accepted-output insertion, through another process.
  let accepted;
  for (let i = 0; i < 10; i++) {
    accepted = await child("import sys,json,sqlite3; from pathlib import Path; sys.path.insert(0,'src'); from grant_agent.task_feedback import FeedbackStore; root=Path(sys.argv[1]); feedback=FeedbackStore(root).get(sys.argv[2]); db=sqlite3.connect(root/'.neyvia/lessons/store.sqlite3'); print(json.dumps({'feedbackId':feedback['id'],'accepted':db.execute('SELECT COUNT(*) FROM accepted WHERE id=?',(sys.argv[2],)).fetchone()[0]})); db.close()", [root, source.runId]);
    if (accepted.accepted) break;
    await new Promise(r => setTimeout(r, 500));
  }
  check('new process reads saved feedback and accepted good run', accepted.feedbackId === good.body.data.feedback.id && accepted.accepted === 1, accepted);
  const activeId = 'c9b-controlled-active-' + randomUUID();
  fixture = spawn(python, ['-u', '-c', "import sys,json,time; from pathlib import Path; sys.path.insert(0,'src'); from grant_agent.connected_sessions.runs import RunStore,iso; from grant_agent.external_chat_inventory import _host; from grant_agent.connected_sessions.registry import make_session_id; root=Path(sys.argv[1]); identity=sys.argv[2]; data={'runId':identity,'sessionId':make_session_id('neyvia',_host()['deviceId'],identity),'app':'neyvia','state':'queued','startedAt':iso(time.time()),'updatedAt':iso(time.time()),'taskText':'CONTROLLED active-state refusal fixture','workspaceRoot':str(root),'outputs':[]}; store=RunStore(root/'.agent_control/connected_chats.sqlite3','controlled-http-fixture',lambda value:True); store.claim(data,identity,None,is_free=lambda value:True,register=lambda:None,unregister=lambda:None); data['state']='running'; store.save(data); print(json.dumps(data),flush=True); sys.stdin.readline(); data['state']='cancelled'; store.save(data)", root, activeId], {cwd: repo, env, windowsHide: true});
  let active = '', fixtureError = '';
  fixture.stderr.on('data', x => {fixtureError += x;});
  await new Promise((ok, fail) => {const timer = setTimeout(() => fail(new Error('Controlled fixture startup timeout ' + fixtureError.slice(0, 200))), 30_000); fixture.once('error', fail); fixture.stdout.on('data', x => {active += x; if (active.includes('\n')) {clearTimeout(timer); ok();}});});
  active = JSON.parse(active.trim());
  const activeRefusal = await api('task_feedback_submit_command', {runId: active.runId, sessionId: active.sessionId, verdict: 'wrong', requestId: randomUUID()});
  check('controlled active run refused', activeRefusal.status === 409 && activeRefusal.body.code === 'run_active', {status: activeRefusal.status, code: activeRefusal.body.code, fixtureRun: active.runId});
  fixture.stdin.end('\n');
  await new Promise(r => fixture.once('close', r));
  fixture = null;
  }
  for (const [name, command, payload] of [
    ['object verdict rejected as invalid input', 'task_feedback_submit_command', {...goodBody, requestId: randomUUID(), verdict: {}}],
    ['array lesson state rejected as invalid input', 'lesson_list_command', {state: []}],
    ['reason length limit enforced', 'task_feedback_submit_command', {...goodBody, requestId: randomUUID(), reason: 'x'.repeat(4001)}],
  ]) {
    const invalid = await api(command, payload);
    check(name, invalid.status === 400 && invalid.body.code === 'invalid_request', {status: invalid.status, code: invalid.body.code,
      ...(invalid.status === 400 ? {} : {response: invalid.body})});
  }
  const replacement = {...goodBody, requestId: randomUUID(), verdict: 'not_quite', reasonSource: 'dictated',
    reason: 'CONTROLLED VERIFIER FEEDBACK: Put a specific title on the first line, put the proposed action before the explanation, and give the one-week test one clear measurable success number. Preserve the original word limit.'};
  let updated;
  if (observeDraft) {
    updated = await api('task_feedback_get_command', {runId: source.runId});
    check('observe existing real drafted feedback', updated.status === 200 && updated.body.data.feedback.id === priorFeedbackId && updated.body.data.feedback.reason === replacement.reason);
  } else {
    updated = await api('task_feedback_submit_command', replacement);
    check('new request replaces feedback and queues drafting', updated.status === 200 && updated.body.data.feedback.id !== priorFeedbackId && updated.body.data.feedback.reasonSource === 'dictated' && updated.body.data.lessons.length === 0, {elapsedMs: updated.elapsedMs});
  }
  record.feedbackId = updated.body.data.feedback.id;
  record.feedbackReason = replacement.reason;
  await checkpoint();
  let lessons = [], job;
  const deadline = Date.now() + 230_000;
  while (Date.now() < deadline) {
    const events = await api('connected_events_poll_command', {cursor, waitSeconds: 1});
    if (events.status !== 200) throw new Error('Event polling failed ' + events.status);
    cursor = events.body.data.cursor;
    record.events.push(...events.body.data.events.filter(e => ['feedback.saved', 'lesson.state'].includes(e.type) && e.runId === source.runId));
    const list = await api('lesson_list_command', {runId: source.runId, limit: 200});
    lessons = list.body.data.lessons.filter(l => l.evidence.feedbackId === record.feedbackId);
    job = await child("import sys,json; sys.path.insert(0,'src'); from grant_agent.lesson_evolver import service_for; print(json.dumps(service_for(sys.argv[1]).job(sys.argv[2])))", [root, record.feedbackId]);
    if (['completed', 'failed'].includes(job?.state)) {
      // A draft may commit between the preceding list read and job read.
      const refreshed = await api('lesson_list_command', {runId: source.runId, limit: 200});
      lessons = refreshed.body.data.lessons.filter(l => l.evidence.feedbackId === record.feedbackId);
    }
    record.draftJob = job;
    record.lessons = lessons;
    await checkpoint();
    if (lessons.length && lessons.every(l => l.state !== 'testing' && Boolean(l.reason)) || !lessons.length && ['failed', 'completed'].includes(job?.state)) break;
    console.log(JSON.stringify({draft: job?.state || 'pending', elapsedSeconds: Math.round((Date.now() - (deadline - 230_000))/1000)}));
  }
  check('feedback saved event on connected cursor', record.events.some(e => e.type === 'feedback.saved' && e.verdict === 'not_quite' && e.at === updated.body.data.feedback.at));
  if (lessons.length) {
    check('real asynchronous configured-model lessons stored', lessons.every(l => l.draft.model === 'gpt-6-luna' && l.draft.tokens.total > 0 && l.evidence.words === replacement.reason && l.cl.includes('M lesson ' + JSON.stringify(replacement.reason))), {count: lessons.length, states: lessons.map(l => l.state)});
    check('lesson state events on connected cursor', record.events.some(e => e.type === 'lesson.state' && e.lessonId === lessons[0].id));
    record.modelReceipts = [];
    for (const lesson of lessons) {
      const path = resolve(lesson.draft.receiptPath);
      const directory = resolve(root, '.neyvia/autopilot-model');
      if (!path.startsWith(directory + '\\')) throw new Error('Draft model receipt outside owned runtime');
      const bytes = await readFile(path);
      const model = JSON.parse(bytes);
      check('independent model usage receipt ' + lesson.id, model.status === 'completed' && model.model === 'gpt-6-luna' && JSON.stringify(model.tokens) === JSON.stringify(lesson.draft.tokens));
      record.modelReceipts.push({path, sha256: createHash('sha256').update(bytes).digest('hex'), tokens: model.tokens, elapsedMs: model.elapsedMs});
    }
    check('automatic testing refused failed calibrated judge', lessons.every(l => l.state === 'quarantined' && l.reason === 'Frozen pairwise judge failed calibration') && record.events.some(e => e.type === 'lesson.state' && e.state === 'testing') && record.events.some(e => e.type === 'lesson.state' && e.state === 'quarantined' && e.reason === 'Frozen pairwise judge failed calibration'));
    const refusal = await api('lesson_revert_command', {lessonId: lessons[0].id, requestId: randomUUID()});
    check('unpromoted lesson revert refused', refusal.status === 409 && refusal.body.code === 'lesson_revert_refused', {status: refusal.status, code: refusal.body.code, message: refusal.body.message || refusal.body.error});
  } else {
    record.limitations.push('No candidates became available: actual drafting job ' + JSON.stringify(job));
  }
  const durable = await child("import sys,json,sqlite3; from pathlib import Path; sys.path.insert(0,'src'); from grant_agent.task_feedback import FeedbackStore,public_feedback; root=Path(sys.argv[1]); feedback=FeedbackStore(root).get(sys.argv[2]); db=sqlite3.connect(root/'.neyvia/lessons/store.sqlite3'); accepted=db.execute('SELECT COUNT(*) FROM accepted WHERE id=?',(sys.argv[2],)).fetchone()[0]; db.close(); print(json.dumps({'feedbackId':feedback['id'],'summary':public_feedback(root,sys.argv[2]),'acceptedCount':accepted}))", [root, source.runId]);
  check('new process reload preserves replacement verdict and lesson count', durable.feedbackId === record.feedbackId && durable.summary.verdict === 'not_quite' && durable.summary.lessonCount === lessons.length, durable);
  check('negative resubmission removes previously accepted output', durable.acceptedCount === 0, {acceptedCount: durable.acceptedCount});
  const badLimit = await api('lesson_list_command', {limit: 201});
  check('lesson list limit enforced', badLimit.status === 400 && badLimit.body.code === 'invalid_request');
  record.limitations.push('Promotion and successful revert remain unproven because both real judge calibrations failed. Original source doneStatus was refused; transport output availability does not imply CL completion.');
  record.passed = record.checks.every(x => x.passed) && lessons.length > 0;
} catch (error) {
  record.error = String(error);
  record.passed = false;
  process.exitCode = 1;
} finally {
  if (fixture) fixture.stdin.end('\n');
  if (cookie) {
    try { await http('/api/auth/logout', {}); }
    catch (error) { record.limitations.push('Owned HTTP logout failed: ' + String(error)); }
  }
  await checkpoint();
  console.log(JSON.stringify({receipt: receiptPath, passed: record.passed, error: record.error}));
}
