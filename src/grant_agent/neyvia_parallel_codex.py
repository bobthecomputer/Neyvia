"""Scoped Codex dynamic tools, backed by the same native owner as Claude's mod."""
from __future__ import annotations

import json
from pathlib import Path

from .neyvia_parallel import DEFINITIONS


def thread_tools(cwd):
    if not cwd or '.neyvia-worktrees' not in Path(cwd).parts:
        return {}
    # Expose coordination only in a saved owned Parallel worktree.
    from .neyvia_workspace_tools import workspace_for
    from .neyvia_parallel import store
    service = workspace_for(Path(cwd))
    folder = Path(cwd).resolve()
    owned = False
    for path in store(service.bus.root).glob('parallel-*.json'):
        run = json.loads(path.read_text(encoding='utf-8'))
        if any(Path(r['worktree']).resolve() == folder for r in [run['main'], *run['tracks']]):
            owned = True
            break
    if not owned:
        return {}
    return {'dynamicTools': [{'type': 'function', 'name': 'neyvia_' + name.replace('.', '_'), 'description': description,
                             'inputSchema': {'type': 'object', 'properties': props, 'required': required}}
                            for name, description, props, required in DEFINITIONS if name != 'parallel.start']}


def call(root, cwd, tool, arguments):
    from .neyvia_workspace_tools import workspace_for
    from .neyvia_parallel import load, call as parallel_call
    names = {'neyvia_' + name.replace('.', '_'): name for name, *_ in DEFINITIONS if name != 'parallel.start'}
    name = names.get(tool)
    if not name or not isinstance(arguments, dict) or not arguments.get('run'):
        raise ValueError('Select this session own Parallel run')
    service = workspace_for(root)
    run = load(service.bus.root, arguments['run'])
    folder = Path(cwd).resolve()
    own = next((r for r in [run['main'], *run['tracks']] if Path(r['worktree']).resolve() == folder), None)
    if own is None:
        raise ValueError('This session does not own a worktree in that run')
    if own['id'] != 'main' and (name not in {'parallel.ask', 'parallel.done', 'parallel.state'} or
                               name != 'parallel.state' and arguments.get('track') != own['id']):
        raise ValueError('Workers can observe, ask and report done only for their own track')
    # Native owner has the same preconditions and postconditions used by the CL adapter.
    return parallel_call(service, name, arguments)
