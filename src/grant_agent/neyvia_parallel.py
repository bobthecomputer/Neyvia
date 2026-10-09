"""Parallel branches, one durable run with connected sessions and ordered Git merges.

HTTP GET /api/ui/parallel[?run=id], POST {operation,...args} uses the standard
UI envelope {ok:true,data:Result}. Result is {ok:true,runs:[Run]} for list,
{ok:true,run:Run} otherwise. Start adds worktrees:[{track,worktree,branch}] and
sessions:{main:session|null,workers:{track:session|null}}. Settle adds receipt.
Run={id,repo,goal,base,baseCommit,integrationBranch,integrationWorktree,createdAt,
updatedAt,state,main:Lane,tracks:[Lane],mergeOrder:[id],conflict,checks,settings,
finish,receipt,error,logPath}. Lane={id,title,brief,agent,model,effort,worktree,
branch,session,runId,liveState,lastActivity,pendingRequest,error,state,questions,
commitsAhead,summary,mergeResult}. Questions={id,question,answer,askedAt,
answeredAt,delivery}. Conflict={track,previousTracks,files,summaries,sides}.
Checks={passed,command,exitCode,output,commit}. Receipt={removed,deletedBranches,
keptBranches,worktrees,tracks:[{track,worktree,status,method,branch,branchStatus,
error?}]}. Run may add startFailure:{settleable:true}; Lane may add
checkoutReady:bool (false only before initial checkout, before any session).
Exact types/actions:
plans/logs/PARALLEL-contract.md.
State and JSONL events live in backend-root/.agent_control/parallel.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from copy import deepcopy
from pathlib import Path
import re
import subprocess
import threading
import uuid

from .harness_jobs import _atomic_write_json
from . import neyvia_parallel_git as vcs

TEXT = {'type': 'string', 'minLength': 1}
ROUTE = {'type': 'object', 'properties': {
    'agent': {'type': 'string', 'enum': ['claude-code', 'codex', 'opencode']},
    'model': TEXT, 'effort': {'type': 'string', 'enum': ['low', 'medium', 'high']}}, 'additionalProperties': False}
TRACK = {'type': 'object', 'properties': {**ROUTE['properties'], 'id': TEXT, 'title': TEXT, 'brief': TEXT},
         'required': ['id', 'title', 'brief'], 'additionalProperties': False}
DEFINITIONS = [
    ('parallel.start', 'Start a main agent and 1–8 workers in separate branches and worktrees.',
     {'repo': TEXT, 'base': TEXT, 'goal': TEXT, 'tracks': {'type': 'array', 'items': TRACK, 'minItems': 1, 'maxItems': 8},
      'main': ROUTE, 'allowFinish': {'type': 'boolean'}, 'checkCommand': TEXT,
      'checkTimeoutSeconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600},
      'sparsePaths': {'type': 'array', 'items': TEXT, 'minItems': 1}}, ['repo', 'goal', 'tracks']),
    ('parallel.state', 'Observe saved runs, current session activity and Git state.', {'run': TEXT}, []),
    ('parallel.ask', 'Send a worker question to the main agent through the connected inbox.', {'run': TEXT, 'track': TEXT, 'question': TEXT}, ['run', 'track', 'question']),
    ('parallel.answer', 'Deliver the main agent answer to the worker, including mid-turn.', {'run': TEXT, 'track': TEXT, 'answer': TEXT, 'questionId': TEXT}, ['run', 'track', 'answer']),
    ('parallel.done', 'Verify a clean committed worker branch and merge when all tracks are done.', {'run': TEXT, 'track': TEXT, 'summary': TEXT}, ['run', 'track', 'summary']),
    *[('parallel.' + op, description, {'run': TEXT}, ['run']) for op, description in [
        ('merge', 'Merge ready worker branches in track order; pause and notify on conflict.'),
        ('resolved', 'Verify staged conflict resolution, commit the merge and continue.'),
        ('settle', 'Stop owned sessions and safely remove clean worktrees; retain unmerged branches.'),
        ('stop', 'Stop only this run main and worker sessions, preserving branches and worktrees.')]],
    ('parallel.finish', 'With checks passed and allowFinish enabled, integrate into the clean base checkout.',
     {'run': TEXT, 'into': TEXT}, ['run']),
]
MUTATIONS = {row[0] for row in DEFINITIONS} - {'parallel.state'}
ACTIVE = {'queued', 'running', 'waiting_approval', 'waiting_input'}
_locks = {}
_lock = threading.Lock()
_tails = {}
_tail_reads = set()
_observations = {}
_observing = set()


def listen(service):
    if getattr(service, '_parallel_listener', False):
        return
    service._parallel_listener = True
    def receive(event):
        item = event.get('item') or {}
        data = item.get('data') or {}
        text = data.get('text') or data.get('output') or data.get('title')
        if text:
            for identity in (event.get('runId'), event.get('sessionId')):
                if identity:
                    _tails[(str(service.bus.root), identity)] = str(text)[-500:]
    service.broker().add_event_listener(receive)


def activity(service, row):
    key = (str(service.bus.root), row['session'])
    cached = _tails.get((str(service.bus.root), row['runId'])) or _tails.get(key)
    if cached:
        return cached
    # Adapter transcript reads can take 30 s. Never put them on the 2 s pane/mod poll.
    if row['session'] and key not in _tail_reads:
        _tail_reads.add(key)
        def read():
            try:
                items = service.broker().read(row['session'], limit=5).get('items', [])
                texts = [str(i.get('data', {}).get('text') or i.get('data', {}).get('title') or i.get('kind') or '') for i in items]
                _tails[key] = (texts[-1] if texts else '')[-500:]
            except Exception as exc:
                _tails[key] = 'Activity unavailable: ' + str(exc)[:150]
            finally:
                _tail_reads.discard(key)
        threading.Thread(target=read, name='parallel-tail', daemon=True).start()
    return row['lastActivity']


def now():
    return datetime.now(timezone.utc).isoformat()


def run_lock(root, identity):
    with _lock:
        return _locks.setdefault((str(Path(root).resolve()), identity), threading.RLock())


def store(root):
    path = Path(root) / '.agent_control' / 'parallel'
    path.mkdir(parents=True, exist_ok=True)
    return path


def load(root, identity):
    if not re.fullmatch(r'parallel-[a-f0-9]{12}', str(identity or '')):
        raise ValueError('Choose a saved parallel run')
    path = store(root) / (identity + '.json')
    if not path.exists():
        raise ValueError('Parallel run not found')
    return json.loads(path.read_text(encoding='utf-8'))


def save(root, run, event, details=None):
    run['updatedAt'] = now()
    _atomic_write_json(store(root) / (run['id'] + '.json'), run)
    with Path(run['logPath']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': run['updatedAt'], 'event': event, 'details': details or {}}) + '\n')


def route(args):
    app = args.get('agent', 'claude-code')
    if app not in {'claude-code', 'codex', 'opencode'}:
        raise ValueError('Choose claude-code, codex or opencode')
    model = args.get('model') or {'claude-code': 'claude-haiku-5-5', 'codex': 'gpt-6.1-sol'}.get(app)
    if app == 'opencode' and not model:
        raise ValueError('Select an explicit OpenCode model')
    effort = args.get('effort', 'low')
    if effort not in {'low', 'medium', 'high'}:
        raise ValueError('Choose low, medium or high effort')
    return {'agent': app, 'model': model, 'effort': effort}


def options(lane):
    return {'model': lane['model'], 'effort': lane['effort'],
            **({'transport': 'terminal'} if lane['agent'] == 'claude-code' else {})}


def lane(identity, title, brief, selected, folder, branch):
    return {'id': identity, 'title': title, 'brief': brief, **selected, 'worktree': str(folder), 'branch': branch,
            'session': None, 'runId': None, 'liveState': None, 'lastActivity': '', 'pendingRequest': None,
            'error': None, 'state': 'starting', 'questions': [], 'commitsAhead': 0, 'summary': None, 'mergeResult': None}


def observe(service, run):
    broker = service.broker()
    listen(service)
    rows = [run['main'], *run['tracks']]
    # Live events and the owning run store are fresh observations. Provider
    # discovery/recovery belongs to connection listing, not every CL predicate.
    current = broker._latest_runs([r['session'] for r in rows if r['session']], recover=False)
    for row in rows:
        if row['runId']:
            live = current.get(row['session']) or broker.get_run(row['runId'])
            row['runId'] = live['runId']
            row.update(session=live.get('sessionId') or row['session'], liveState=live['state'],
                       pendingRequest=live.get('pendingRequest'), error=live.get('error'))
        row['lastActivity'] = activity(service, row)
        if Path(row['worktree']).exists():
            try:
                row['commitsAhead'] = vcs.ahead(row['worktree'], run['baseCommit'])
            except (FileNotFoundError, ValueError):
                if vcs.worktree_status(run['repo'], run['id'], row['worktree']) != 'orphan':
                    raise
                row['error'] = 'Worktree metadata missing; settle can remove this orphan'
                if vcs.git(run['repo'], 'show-ref', '--verify', 'refs/heads/' + row['branch'], check=False).returncode == 0:
                    row['commitsAhead'] = vcs.ahead(run['repo'], run['baseCommit'], row['branch'])
    return run


def pane_state(service, run):
    """Return atomic state immediately; session/Git enrichment runs off the poll."""
    key = (str(service.bus.root), run['id'])
    with _lock:
        cached = _observations.get(key)
        result = deepcopy(cached) if cached and cached['updatedAt'] == run['updatedAt'] else run
        if key not in _observing and run['state'] != 'settled':
            _observing.add(key)
            def refresh():
                try:
                    value = observe(service, deepcopy(run))
                    with _lock:
                        _observations[key] = value
                finally:
                    with _lock:
                        _observing.discard(key)
            threading.Thread(target=refresh, name='parallel-state', daemon=True).start()
    return result


def deliver(service, run, row, text):
    broker = service.broker()
    if row['runId']:
        live = broker._latest_runs([row['session']], recover=False).get(row['session']) if row['session'] else None
        live = live or broker.get_run(row['runId'])
        row['runId'] = live['runId']
        row['session'] = live.get('sessionId') or row['session']
        if live['state'] in ACTIVE:
            if live.get('canSteer'):
                broker.steer(row['runId'], text)
                return {'delivery': 'steered', 'runId': row['runId']}
            if row['agent'] == 'claude-code' and row['session']:
                from .claude_code_activity import message
                return message(service, {'to': row['session'], 'text': text, 'from': run['id']})
            raise ValueError('This active session cannot receive a message; retry when idle')
    if not row['session']:
        raise ValueError('Session has not started yet')
    live = broker.send(row['session'], text, 'parallel-msg-' + uuid.uuid4().hex, options(row))
    row['runId'] = live['runId']
    row['liveState'] = live['state']
    return {'delivery': 'new turn', 'runId': live['runId']}


def start(service, args):
    repo = service.safe_path(args['repo'])
    reserved = repo / '.neyvia-worktrees'
    if reserved.is_symlink() or reserved.is_junction():
        raise ValueError('The reserved worktree container must not be a reparse point')
    if Path(vcs.git(repo, 'rev-parse', '--show-toplevel').stdout.strip()).resolve() != repo:
        raise ValueError('Choose the repository checkout root')
    if not vcs.clean(repo):
        raise ValueError('Commit or preserve dirty checkout work before starting')
    if vcs.git(repo, 'ls-files', '.neyvia-worktrees').stdout.strip():
        raise ValueError('The reserved worktree container is tracked')
    tracks = args.get('tracks')
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 8:
        raise ValueError('Supply 1–8 tracks')
    ids = [t.get('id') for t in tracks]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}', str(i)) or i == 'main' for i in ids):
        raise ValueError('Unique track IDs required; main is reserved')
    goal = str(args.get('goal') or '').strip()
    if not goal or any(not str(t.get(k) or '').strip() for t in tracks for k in ('title', 'brief')):
        raise ValueError('Supply the goal and each track title and brief')
    current = vcs.git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False).stdout.strip()
    base = str(args.get('base') or current or 'HEAD')
    if base.startswith('-') or not base.strip():
        raise ValueError('Choose a Git base reference')
    commit = vcs.git(repo, 'rev-parse', '--verify', base + '^{commit}').stdout.strip()
    timeout = args.get('checkTimeoutSeconds', 300)
    if type(timeout) is not int or not 1 <= timeout <= 3600 or type(args.get('allowFinish', False)) is not bool:
        raise ValueError('Invalid check timeout or allowFinish')
    identity = 'parallel-' + uuid.uuid4().hex[:12]
    container = repo / '.neyvia-worktrees' / identity
    if (repo / '.neyvia-worktrees').is_symlink() or (repo / '.neyvia-worktrees').is_junction():
        raise ValueError('Worktree container cannot be a reparse point')
    integration = 'parallel/' + identity + '/main'
    main = lane('main', 'Main agent', goal, route(args.get('main') or {}), container / 'main', integration)
    workers = [lane(t['id'], t['title'], t['brief'], route(t), container / t['id'],
                    'parallel/' + identity + '/' + t['id']) for t in tracks]
    # Policies and availability are checked before creating any worktrees.
    from .neyvia_runtime import enforce
    from .connected_sessions.broker import ConnectedBroker
    run = {'id': identity, 'repo': str(repo), 'goal': goal, 'base': base, 'baseCommit': commit,
           'integrationBranch': integration, 'integrationWorktree': main['worktree'], 'createdAt': now(),
           'updatedAt': now(), 'state': 'starting', 'main': main, 'tracks': workers, 'mergeOrder': ids,
           'conflict': None, 'checks': None, 'settings': {'allowFinish': args.get('allowFinish', False),
           'checkCommand': args.get('checkCommand'), 'checkTimeoutSeconds': timeout},
           'finish': None, 'receipt': None, 'error': None, 'logPath': str(store(service.bus.root) / (identity + '.jsonl'))}
    with run_lock(service.bus.root, identity):
        save(service.bus.root, run, 'start.accepted')
        try:
            for row in [main, *workers]:
                enforce(service.bus.root, row['agent'], ConnectedBroker._turn_options(options(row)))
            for app in dict.fromkeys(row['agent'] for row in [main, *workers]):
                service.broker()._adapter(app, for_start=True)
            container.mkdir(parents=True)
            exclude = Path(vcs.git(repo, 'rev-parse', '--git-path', 'info/exclude').stdout.strip())
            if not exclude.is_absolute():
                exclude = repo / exclude
            existing = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
            # Claude's terminal owner spools here. Preserve every existing local exclusion.
            additions = [p for p in ('/.neyvia-worktrees/', '/.agent_control/private-conpty/') if p not in existing.splitlines()]
            if additions:
                exclude.parent.mkdir(parents=True, exist_ok=True)
                with exclude.open('a', encoding='utf-8') as stream:
                    stream.write('\n' + '\n'.join(additions) + '\n')
            listen(service)
            sparse = args.get('sparsePaths')
            # Explicit sparse scope takes precedence; large tracked trees reuse existing cone scope.
            if not sparse and len(vcs.git(repo, 'ls-files').stdout.splitlines()) > 20000:
                sparse = (vcs.git(repo, 'sparse-checkout', 'list', check=False).stdout.splitlines()
                          or vcs.git(repo, 'ls-tree', '-d', '--name-only', commit).stdout.splitlines() or ['.'])
            for row in [main, *workers]:
                row['checkoutReady'] = False
                save(service.bus.root, run, 'worktree.creating', {'track': row['id']})
                vcs.git(repo, 'worktree', 'add', *(['--no-checkout'] if sparse else []), '-b', row['branch'], row['worktree'], commit)
                if sparse:
                    vcs.git(row['worktree'], 'sparse-checkout', 'set', '--cone', *sparse)
                    vcs.git(row['worktree'], 'checkout', row['branch'])
                row['checkoutReady'] = True
                save(service.bus.root, run, 'worktree.created', {'track': row['id']})
            common = ('Parallel run ' + identity + '. Work only in your assigned worktree. No push, publish, '
                      'install or delegation. Use ToolSearch to discover neyvia parallel tools. Keep turns short. ')
            duties = ('You are the main agent. Workers: ' + json.dumps([{k: w[k] for k in ('id', 'title', 'brief', 'worktree', 'branch')} for w in workers]) +
                      '. Answer worker questions with neyvia.parallel.answer {run,track,answer}. Backend owns ordered merges. '
                      'When notified of conflict, resolve and git add in this integration worktree, then call neyvia.parallel.resolved {run}. '
                      'Do not edit worker worktrees or merge manually. Start by briefly acknowledging; later messages resume this session.')
            for row in [main, *workers]:
                prompt = common + (duties + '\nGoal: ' + goal if row is main else
                         'You are worker ' + row['id'] + '. Main session: ' + str(main['session']) + '. Brief: ' + row['brief'] +
                         '\nWhen blocked call neyvia.parallel.ask {run:"' + identity + '",track:"' + row['id'] + '",question}. '
                         'When done commit on your branch, then call neyvia.parallel.done {run:"' + identity + '",track:"' + row['id'] + '",summary}.')
                live = service.broker().new(row['agent'], row['worktree'], prompt, identity + '-' + row['id'], options(row))
                row.update(session=live.get('sessionId'), runId=live['runId'], liveState=live['state'], state='working')
                save(service.bus.root, run, 'session.started', {'track': row['id'], 'runId': row['runId']})
            run['state'] = 'working'
            save(service.bus.root, run, 'start.completed')
        except Exception as exc:
            # The saved scope includes every planned tree, including a Git add
            # that failed halfway. Settle can recover orphans and absent lanes.
            run.update(state='failed', error=str(exc), startFailure={'settleable': True})
            save(service.bus.root, run, 'start.failed', {'error': str(exc)})
            raise ValueError('Parallel start failed; inspect retained run ' + identity + ': ' + str(exc)) from exc
    return {'ok': True, 'run': run, 'worktrees': [{'track': r['id'], 'worktree': r['worktree'], 'branch': r['branch']} for r in [main, *workers]],
            'sessions': {'main': main['session'], 'workers': {r['id']: r['session'] for r in workers}}}


def checks(service, run):
    run['state'] = 'checking'
    save(service.bus.root, run, 'checks.started')
    command = run['settings']['checkCommand']
    if not command:
        config = Path(run['integrationWorktree']) / '.neyvia' / 'parallel.json'
        if config.is_file():
            command = json.loads(config.read_text(encoding='utf-8')).get('checkCommand')
    if command:
        try:
            result = subprocess.run(command, shell=True, cwd=run['integrationWorktree'], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=run['settings']['checkTimeoutSeconds'])
            receipt = {'passed': result.returncode == 0, 'command': command, 'exitCode': result.returncode,
                       'output': (result.stdout + result.stderr)[-30000:]}
        except subprocess.TimeoutExpired:
            receipt = {'passed': False, 'command': command, 'exitCode': None, 'output': 'Check command exceeded configured timeout'}
    else:
        from .claude_code_host import stop, session_for_run
        raw = session_for_run(run['main']['runId'])
        if not raw:
            receipt = {'passed': False, 'command': None, 'exitCode': None, 'output': 'No main Claude Stop gate available; configure checkCommand'}
        else:
            gate = stop(service.bus.root, {'session': raw})
            receipt = {'passed': bool(gate.get('receipt', {}).get('passed')), 'command': None,
                       'exitCode': None, 'output': json.dumps(gate)}
    run.update(checks=receipt, state='ready' if receipt['passed'] else 'checks_failed')
    receipt['commit'] = vcs.git(run['integrationWorktree'], 'rev-parse', 'HEAD').stdout.strip()
    save(service.bus.root, run, 'checks.completed', receipt)


def merge(service, run):
    if run['conflict']:
        return
    folder = run['integrationWorktree']
    if not Path(folder).exists() or not vcs.clean(folder):
        raise ValueError('Integration worktree must be clean before merge')
    run['state'] = 'merging'
    for row in run['tracks']:
        if row['state'] in {'merged', 'settled'}:
            continue
        if row['state'] != 'done':
            run['state'] = 'working'
            save(service.bus.root, run, 'merge.waiting', {'track': row['id']})
            return
        if not vcs.clean(row['worktree']) or vcs.ahead(row['worktree'], run['baseCommit']) < 1:
            raise ValueError('Done branch changed; inspect worker ' + row['id'])
        row['state'] = 'merging'
        save(service.bus.root, run, 'merge.started', {'track': row['id']})
        result = vcs.git(folder, 'merge', '--no-ff', '--no-edit', row['branch'], check=False)
        if result.returncode:
            files = vcs.git(folder, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
            if not files:
                row['state'] = 'done'
                run['state'] = 'failed'
                run['error'] = result.stderr or result.stdout
                save(service.bus.root, run, 'merge.failed')
                raise ValueError(run['error'])
            previous = [r['id'] for r in run['tracks'] if r['state'] == 'merged']
            conflict = {'track': row['id'], 'previousTracks': previous, 'files': files,
                        'summaries': {r['id']: r['summary'] for r in run['tracks'] if r['id'] in [*previous, row['id']]},
                        'sides': vcs.conflict_sides(folder, files)}
            row.update(state='conflict', mergeResult={'status': 'conflict', 'files': files})
            run.update(state='conflict', conflict=conflict)
            save(service.bus.root, run, 'merge.conflict', conflict)
            text = ('Parallel conflict in run ' + run['id'] + '. Resolve in ' + folder + ', stage, then call CL: run parallel.resolved(run=' + repr(run['id']) +
                    ') followed by done(). Full files, sides and summaries are in parallel.state. ' + json.dumps(conflict)[:2500])
            for target in [run['main'], *[r for r in run['tracks'] if r['id'] in [*previous, row['id']]]]:
                try:
                    notification = text if target is run['main'] else ('Main agent owns this conflict. Do not edit the integration worktree or resolve it yourself. ' + text)
                    delivery = deliver(service, run, target, notification)
                    save(service.bus.root, run, 'conflict.delivered', {'track': target['id'], **delivery})
                except Exception as exc:
                    save(service.bus.root, run, 'conflict.delivery_failed', {'track': target['id'], 'error': str(exc)})
            return
        row.update(state='merged', mergeResult={'status': 'merged', 'commit': vcs.git(folder, 'rev-parse', 'HEAD').stdout.strip()})
        save(service.bus.root, run, 'merge.completed', {'track': row['id'], **row['mergeResult']})
    checks(service, run)


def track(run, identity):
    row = next((r for r in run['tracks'] if r['id'] == identity), None)
    if row is None:
        raise ValueError('Unknown worker track')
    return row


def stop_sessions(service, run):
    for row in [run['main'], *run['tracks']]:
        if row['runId']:
            broker = service.broker()
            live = broker._latest_runs([row['session']], recover=False).get(row['session']) if row['session'] else None
            live = live or broker.get_run(row['runId'])
            row['runId'] = live['runId']
            row.update(liveState=live['state'], pendingRequest=live.get('pendingRequest'), error=live.get('error'))
            if live['state'] in ACTIVE:
                stopped = service.broker().stop(row['runId'])
                row['liveState'] = stopped['state']
                if stopped['state'] in ACTIVE:
                    raise ValueError('Session is stopping; retry settle after it is idle: ' + row['id'])


def action(service, run, op, args, *, owner_approved=False):
    if op in {'ask', 'answer', 'done'}:
        row = track(run, args['track'])
    if op == 'ask':
        if row['state'] not in {'working', 'asking'}:
            raise ValueError('This worker has already completed its track')
        question = next((q for q in row['questions'] if q['answer'] is None and q['question'] == args['question']), None)
        if question is None:
            question = {'id': uuid.uuid4().hex[:12], 'question': args['question'], 'answer': None,
                        'askedAt': now(), 'answeredAt': None, 'delivery': None}
            row['questions'].append(question)
            row['state'] = 'asking'
            save(service.bus.root, run, 'question.recorded', {'track': row['id'], **question})
        if not question['delivery']:
            question['delivery'] = deliver(service, run, run['main'], 'Worker ' + row['id'] + ' asks in run ' + run['id'] +
                                           ': ' + args['question'] + '. Reply using parallel.answer {run,track,answer}.')
    elif op == 'answer':
        question = next((q for q in reversed(row['questions']) if q['answer'] is None and
                         (not args.get('questionId') or q['id'] == args['questionId'])), None)
        if not question:
            raise ValueError('No unanswered question for this track')
        delivery = deliver(service, run, row, 'Main answer in run ' + run['id'] + ': ' + args['answer'])
        answered = now()
        for pending in row['questions']:
            if pending['answer'] is None and pending['question'] == question['question']:
                pending.update(answer=args['answer'], answeredAt=answered, delivery=delivery)
        if row['state'] == 'asking' and not any(q['answer'] is None for q in row['questions']):
            row['state'] = 'working'
    elif op == 'done':
        if row['state'] in {'done', 'merged', 'settled'}:
            return
        if not vcs.clean(row['worktree']) or vcs.ahead(row['worktree'], run['baseCommit']) < 1:
            raise ValueError('Done requires a clean worktree and at least one commit beyond base')
        if any(q['answer'] is None for q in row['questions']):
            raise ValueError('Answer pending questions before done')
        row.update(state='done', summary=args['summary'], commitsAhead=vcs.ahead(row['worktree'], run['baseCommit']))
        save(service.bus.root, run, 'worker.done', {'track': row['id'], 'summary': row['summary']})
        if all(r['state'] in {'done', 'merged'} for r in run['tracks']):
            merge(service, run)
    elif op == 'merge':
        merge(service, run)
    elif op == 'resolved':
        conflict = run['conflict']
        if not conflict:
            raise ValueError('No merge conflict is pending')
        folder = run['integrationWorktree']
        vcs.verify_resolution(folder, conflict['files'])
        vcs.git(folder, 'rev-parse', '--verify', 'MERGE_HEAD')
        vcs.git(folder, 'commit', '--no-edit')
        if not vcs.clean(folder):
            raise ValueError('Integration worktree is dirty after resolution')
        row = track(run, conflict['track'])
        row.update(state='merged', mergeResult={'status': 'merged', 'commit': vcs.git(folder, 'rev-parse', 'HEAD').stdout.strip()})
        run['conflict'] = None
        save(service.bus.root, run, 'conflict.resolved', {'track': row['id'], **row['mergeResult']})
        merge(service, run)
    elif op == 'finish':
        if run['finish']:
            return
        if run['state'] != 'ready' or not run['checks'] or not run['checks']['passed']:
            raise ValueError('Finish requires all merges and passing checks')
        if not run['settings']['allowFinish'] and not owner_approved:
            return
        into = args.get('into') or run['base']
        if into != run['base'] or vcs.git(run['repo'], 'symbolic-ref', '--short', 'HEAD').stdout.strip() != into:
            raise ValueError('Finish only into the original base checked out in the main repository')
        if not vcs.clean(run['repo']) or not vcs.clean(run['integrationWorktree']):
            raise ValueError('Finish requires clean main and integration checkouts')
        head = vcs.git(run['integrationWorktree'], 'rev-parse', 'HEAD').stdout.strip()
        if head != run['checks'].get('commit'):
            raise ValueError('Integration changed after checks; rerun merge/checks before finish')
        if owner_approved:
            save(service.bus.root, run, 'finish.owner_approved', {'into': into, 'commit': head})
        # A diverged base needs a new reviewed run; never leave an unmanaged conflict in main.
        vcs.git(run['repo'], 'merge', '--ff-only', run['integrationBranch'])
        run.update(state='finished', finish={'into': into, 'commit': vcs.git(run['repo'], 'rev-parse', 'HEAD').stdout.strip()})
    elif op == 'stop':
        stop_sessions(service, run)
        run['state'] = 'stopped'
    elif op == 'settle':
        rows = [*run['tracks'], run['main']]
        receipt = run['receipt'] or {'removed': [], 'deletedBranches': [], 'keptBranches': [], 'worktrees': []}
        run['receipt'] = receipt
        outcomes = {item['track']: item for item in receipt.setdefault('tracks', [])}
        for r in rows:
            outcomes.setdefault(r['id'], {'track': r['id'], 'worktree': r['worktree'], 'branch': r['branch'],
                                          'status': 'pending', 'branchStatus': 'pending'})
        receipt['tracks'] = list(outcomes.values())
        stop_sessions(service, run)
        def uninitialized(r):
            return bool(run.get('startFailure') and r.get('checkoutReady') is False and not r['runId'] and
                        vcs.git(run['repo'], 'rev-parse', r['branch'], check=False).stdout.strip() == run['baseCommit'])
        # Check all dirt before removing any tree, preserving partial work on refusal.
        blocked = {}
        dirty = []
        for r in rows:
            try:
                if vcs.worktree_status(run['repo'], run['id'], r['worktree']) == 'dirty' and not uninitialized(r):
                    dirty.append(r['id'])
                    raise ValueError('Settle refuses uncommitted work: ' + r['id'])
            except Exception as exc:
                blocked[r['id']] = str(exc)
                outcomes[r['id']].update(status='failed', error=str(exc))
        if dirty:
            raise ValueError('Settle refuses uncommitted work: ' + ', '.join(dirty))
        errors = []
        for r in rows:
            outcome = outcomes[r['id']]
            try:
                if r['id'] in blocked:
                    raise ValueError(blocked[r['id']])
                removed = vcs.remove_worktree(run['repo'], run['id'], r['worktree'], uninitialized=uninitialized(r))
                # Retain the original recovery method across retries.
                if outcome.get('status') != 'removed':
                    outcome.update(removed)
                outcome.pop('error', None)
                if r['worktree'] not in receipt['removed']:
                    receipt['removed'].append(r['worktree'])
                r['state'] = 'settled'
                exists = vcs.git(run['repo'], 'show-ref', '--verify', 'refs/heads/' + r['branch'], check=False).returncode == 0
                unused = run.get('startFailure') and vcs.git(run['repo'], 'rev-parse', r['branch'], check=False).stdout.strip() == run['baseCommit']
                if exists and (unused or (r is not run['main'] and vcs.merged(run['repo'], r['branch'], run['integrationBranch']))):
                    vcs.git(run['repo'], 'branch', '-D', r['branch'])
                    if r['branch'] not in receipt['deletedBranches']:
                        receipt['deletedBranches'].append(r['branch'])
                    outcome['branchStatus'] = 'deleted'
                elif exists:
                    if r['branch'] not in receipt['keptBranches']:
                        receipt['keptBranches'].append(r['branch'])
                    outcome['branchStatus'] = 'kept'
                elif r['branch'] in receipt['deletedBranches']:
                    outcome['branchStatus'] = 'deleted'
                else:
                    outcome['branchStatus'] = 'absent'
            except Exception as exc:
                outcome.update(status='failed', error=str(exc))
                errors.append(r['id'] + ': ' + str(exc))
            receipt['tracks'] = list(outcomes.values())
            save(service.bus.root, run, 'settle.track', outcome)
        vcs.git(run['repo'], 'worktree', 'prune', '--expire', 'now')
        receipt['worktrees'] = vcs.worktrees(run['repo'])
        if errors:
            raise ValueError('Settle could not clean every track; inspect receipt: ' + '; '.join(errors))
        owned = str(Path(run['repo']) / '.neyvia-worktrees' / run['id']).replace('\\', '/').casefold()
        if any(p.replace('\\', '/').casefold().startswith(owned + '/') for p in receipt['worktrees']):
            raise ValueError('Owned worktree registration remains')
        container = Path(run['repo']) / '.neyvia-worktrees' / run['id']
        if container.exists():
            container.rmdir()
        parent = container.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        run['state'] = 'settled'
    else:
        raise ValueError('Unknown parallel operation')
    save(service.bus.root, run, op + '.completed', {'track': args.get('track')})


def call(service, name, args, *, owner_approved=False, pane=False):
    op = name.removeprefix('parallel.')
    from jsonschema import Draft202012Validator
    definition = next((r for r in DEFINITIONS if r[0] == 'parallel.' + op), None)
    if definition is None:
        raise ValueError('Unknown parallel operation')
    validator = Draft202012Validator({'type': 'object', 'properties': definition[2],
                                     'required': definition[3], 'additionalProperties': False})
    invalid = next(validator.iter_errors(args), None)
    if invalid:
        location = '.'.join(str(p) for p in invalid.absolute_path) or '$'
        raise ValueError('Invalid Parallel arguments at ' + location + ': ' + invalid.validator)
    root = service.bus.root
    observer = pane_state if pane else observe
    if op == 'state' and not args.get('run'):
        runs = []
        for path in sorted(store(root).glob('parallel-*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            runs.append(observer(service, load(root, path.stem)))
        return {'ok': True, 'runs': runs}
    if op == 'state':
        # Atomic snapshots let the pane inspect a long start/merge/stop in progress.
        return {'ok': True, 'run': observer(service, load(root, args['run']))}
    if op == 'start':
        return start(service, args)
    with run_lock(root, args.get('run')):
        run = load(root, args.get('run'))
        if op != 'state':
            if run['state'] == 'settled' and op != 'settle':
                raise ValueError('This run is settled')
            try:
                action(service, run, op, args, owner_approved=owner_approved)
            except Exception as exc:
                save(root, run, op + '.failed', {'error': str(exc)})
                raise
        result = {'ok': True, 'run': observe(service, run)}
        if op == 'finish' and not run['settings']['allowFinish'] and not run['finish']:
            result['needsApproval'] = True
        if op == 'settle':
            result['receipt'] = run['receipt']
        return result
