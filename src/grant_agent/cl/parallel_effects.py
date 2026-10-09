"""Subject-bound Parallel effects: reread durable state, broker runs and Git."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .. import neyvia_parallel as parallel
from .. import neyvia_parallel_git as vcs
from .effects import _call

SUPPORTED = {'neyvia.' + name for name in parallel.MUTATIONS}


def readonly(name, args):
    return True if name == 'neyvia.parallel.state' else None


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    if name.endswith('.start'):
        return {'priorIds': [p.stem for p in parallel.store(protocol.gateway.root).glob('parallel-*.json')]}
    return parallel.load(protocol.gateway.root, args['run'])


def verify(protocol, name, args, value, before):
    identity = args.get('run') or value.get('run', {}).get('id')
    fresh = _call(protocol, 'neyvia.parallel.state', {'run': identity})['run']
    op = name.rsplit('.', 1)[1]
    if op == 'start':
        return (identity not in before['priorIds'] and fresh['goal'] == args['goal'].strip() and
                [r['id'] for r in fresh['tracks']] == [t['id'] for t in args['tracks']] and
                all(Path(r['worktree']).is_dir() and r['runId'] and r['session'] and
                    vcs.git(r['worktree'], 'branch', '--show-current').stdout.strip() == r['branch']
                    for r in [fresh['main'], *fresh['tracks']]))
    if op in {'ask', 'answer', 'done'}:
        row = parallel.track(fresh, args['track'])
        if op == 'ask':
            return any(q['question'] == args['question'] and q['delivery'] for q in row['questions'])
        if op == 'answer':
            return any(q['answer'] == args['answer'] and q['answeredAt'] and q['delivery'] and
                       (not args.get('questionId') or q['id'] == args['questionId']) for q in row['questions'])
        return (row['summary'] == args['summary'] and row['state'] in {'done', 'merged', 'conflict'} and
                vcs.clean(row['worktree']) and vcs.ahead(row['worktree'], fresh['baseCommit']) > 0)
    if op in {'merge', 'resolved'}:
        valid = all(vcs.merged(fresh['repo'], r['branch'], fresh['integrationBranch'])
                    for r in fresh['tracks'] if r['state'] == 'merged')
        if op == 'resolved':
            previous = before['conflict']
            return bool(previous) and valid and parallel.track(fresh, previous['track'])['state'] == 'merged'
        return valid and fresh['state'] in {'working', 'conflict', 'ready', 'checks_failed'}
    if op == 'finish':
        if not fresh['settings']['allowFinish']:
            return fresh['state'] == 'ready' and fresh['finish'] is None
        return bool(fresh['finish']) and vcs.git(fresh['repo'], 'rev-parse', 'HEAD').stdout.strip() == fresh['finish']['commit']
    if op == 'stop':
        return fresh['state'] == 'stopped' and all(r['liveState'] not in parallel.ACTIVE for r in [fresh['main'], *fresh['tracks']])
    if op == 'settle':
        registered = {p.replace('\\', '/').casefold() for p in vcs.worktrees(fresh['repo'])}
        rows = [fresh['main'], *fresh['tracks']]
        outcomes = {r['track']: r for r in (fresh.get('receipt') or {}).get('tracks', [])}
        return fresh['state'] == 'settled' and all(not Path(r['worktree']).exists() and
                r['worktree'].replace('\\', '/').casefold() not in registered and
                outcomes.get(r['id'], {}).get('status') == 'removed' and
                outcomes[r['id']]['worktree'] == r['worktree'] and
                outcomes[r['id']]['branchStatus'] in {'deleted', 'kept', 'absent'} for r in rows)
    return False


def checks_for(protocol, name, args):
    if name not in SUPPORTED or (protocol.scope is not None and 'neyvia.parallel.state' not in protocol.scope):
        return []
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(args.get('run') or args.get('repo')),
             'bindSubject': lambda arguments, value, previous: name + ':' + str(arguments.get('run') or value['run']['id']),
             'observerTool': 'neyvia.parallel.state', 'subject': deepcopy(args),
             'expectation': 'Fresh saved subject, live session and Git observations match the requested Parallel action',
             'check': lambda arguments, value, previous: verify(protocol, name, arguments, value, previous)}]
