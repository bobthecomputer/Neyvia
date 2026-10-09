"""CL descriptors; authenticated HTTP owners use the same host as MCP."""
from __future__ import annotations

TEXT = {"type": "string"}
DEFINITIONS = [
    ("cl.describe", "Read Connected Language at L0, L1 or L2 for a manual, family or exact action.",
     {"level": {"type": "integer", "minimum": 0, "maximum": 2}, "layer": TEXT, "chapter": TEXT, "name": TEXT, "primer": {"type": "boolean"},
      "task": {"type": "string", "maxLength": 2000, "description": "The current user intent, for learned manual routing."}}, []),
    ("cl", "Execute CL 1.1 Python-style calls; prefer run procedures. Host fills stamps and refs; done requires observer G. Original permissions apply.",
     {"lines": TEXT, "actionId": TEXT, "scopeTools": {"type":"array", "items":TEXT},
      "task": {"type": "string", "maxLength": 2000, "description": "The current user intent, for learned manual routing."}}, ["lines"]),
]


def call(workspace, name, args):
    from .neyvia_gateway import NeyviaToolGateway
    from .cl.protocol import Protocol
    if not hasattr(workspace, "cl_protocol"):
        gateway = NeyviaToolGateway(workspace.bus.root, allow_mutations=False, permission_mode="read-only")
        workspace.cl_protocol = Protocol(gateway, lazy_manuals=True)
    protocol = workspace.cl_protocol
    args = bind_task(protocol, args)
    if name == "cl.describe":
        return {"ok": True, "notation": "cl1.1", "text": protocol.describe(**args)}
    if name == "cl":
        return protocol.run(args["lines"], action_id=args.get("actionId", ""), scope_tools=args.get("scopeTools"))
    raise ValueError("Unknown CL operation")


def owner_protocol(workspace, session, owner):
    """The HTTP boundary supplies the verified session, never model arguments."""
    if (str(session.get("username") or "").casefold() != str(owner).casefold()
            or not session.get("sessionId")):
        raise PermissionError("An authenticated owner session is required")
    identity = str(session["sessionId"])
    with workspace.lock:
        protocols = getattr(workspace, "owner_cl_protocols", None)
        if protocols is None:
            workspace.owner_cl_protocols = protocols = {}
        if identity not in protocols:
            from .neyvia_gateway import NeyviaToolGateway
            from .cl.protocol import Protocol
            gateway = NeyviaToolGateway(workspace.bus.root, allow_mutations=True,
                action_scope="http-owner:" + identity, permission_mode="workspace")
            from .neyvia_memory_tools import context_for_backend
            from dataclasses import replace
            gateway.memory_context = replace(context_for_backend(workspace.backend, {}, str(session['username'])), channel='provider')
            protocols[identity] = Protocol(gateway, lazy_manuals=True)
            # Eviction drops only interpreter state. Native action identities,
            # manual uses and receipts remain durable in the selected workspace.
            if len(protocols) > 64:
                protocols.pop(next(iter(protocols)))
        return protocols[identity]


def call_owner(workspace, name, args, *, session, owner):
    protocol = owner_protocol(workspace, session, owner)
    if (name == 'neyvia.cl' and protocol.host is not None
            and protocol.host.done_status == 'ok'
            and protocol.host.done_generation == protocol.host.completion_generation
            and not protocol.host.task_goals and not protocol.host.pending_actions
            and str(args.get('lines', '')).lstrip().startswith('G:')):
        # A new explicit goal after verified completion starts another command.
        # Failed/pending commands and durable task goals cannot be discarded.
        # Keep the gateway's original authority and durable action receipts.
        from .cl.protocol import Protocol
        with workspace.lock:
            previous = protocol
            protocol = Protocol(previous.gateway, lazy_manuals=True)
            from .neyvia_manuals import catalog_stamp
            if previous.manual_catalog_stamp == catalog_stamp(include_manifest=True):
                # Reuse only source-current admission data. Goals, action IDs,
                # observers and completion state always belong to the new host.
                from copy import deepcopy
                protocol.contracts = deepcopy(previous.contracts)
                protocol.manual_actions = deepcopy(previous.manual_actions)
                protocol.manual_documents = deepcopy(previous.manual_documents)
                protocol.manual_catalog_stamp = previous.manual_catalog_stamp
            workspace.owner_cl_protocols[str(session['sessionId'])] = protocol
    if name in {'neyvia.cl', 'neyvia.cl.describe'}:
        args = bind_task(protocol, args)
    if name == "neyvia.cl.describe":
        return {"ok": True, "notation": "cl1.1", "text": protocol.describe(**args)}
    if name == "neyvia.cl":
        return protocol.run(args["lines"], action_id=args.get("actionId", ""),
                            scope_tools=args.get("scopeTools"))
    exact = protocol.resolve_name(name)
    if protocol._mutating(exact, args):
        return mutation_recovery(exact, args, protocol)
    return protocol.gateway.call_native(exact, args)


def mutation_recovery(name, args, protocol):
    """Give the refused caller one executable, observer-bound recovery call."""
    if name in {'neyvia.comments.add', 'neyvia.comments.resolve', 'neyvia.comments.send'}:
        short = name.removeprefix('neyvia.')
        if name == 'neyvia.comments.send' and args.get('sessionId'):
            # CL reserves sessionId for host-owned UI transport context; this is a chat destination.
            args = {('session' if key == 'sessionId' else key): value for key, value in args.items()}
        arguments = ', '.join(key + '=' + repr(value) for key, value in args.items())
        if short == 'comments.resolve':
            lines = 'G: comments.list(id=' + repr(args.get('id')) + ').comments[0].status == "resolved"\ndo ' + short + '(' + arguments + ')\ndone()'
        else:
            lines = 'G: comments.list().total > 0\ndo ' + short + '(' + arguments + ')\ndone()'
        return {'ok': False, 'status': 'cl_goal_required',
                'error': 'Execute this observer-bound comments action through neyvia.cl: ' + lines,
                'recovery': {'tool': 'neyvia.cl', 'arguments': {'lines': lines}}}
    if name.startswith('neyvia.parallel.'):
        from .neyvia_parallel import MUTATIONS
        if name in {'neyvia.' + action for action in MUTATIONS}:
            short = name.removeprefix('neyvia.')
            arguments = ', '.join(key + '=' + repr(value) for key, value in args.items())
            # Preserve optional arguments too; the owning manual and effect
            # observer still admit and verify the exact native action.
            if short == 'parallel.start':
                lines = 'G: parallel.state().runs != None\ndo ' + short + '(' + arguments + ')\ndone()'
            else:
                identity = repr(args.get('run'))
                lines = 'G: parallel.state(run=' + identity + ').run.id == ' + identity + '\ndo ' + short + '(' + arguments + ')\ndone()'
            return {'ok': False, 'status': 'cl_goal_required',
                    'error': 'Execute this observer-bound Parallel action through neyvia.cl: ' + lines,
                    'recovery': {'tool': 'neyvia.cl', 'arguments': {'lines': lines}}}
    from .neyvia_settings import THEMES
    from .cl.protocol import unwrap
    quote = repr
    identity = quote(args.get('id', ''))
    recipes = {
        'neyvia.timer.start': ('neyvia.start-named-timer',
            {'id': args.get('id'), 'name': args.get('label'), 'seconds': args.get('targetSeconds', 600)},
            f'timer.read(id={identity}).timer.status == "running"'),
        'neyvia.timer.lap': ('neyvia.lap-timer',
            {key: args.get(key) for key in ('id', 'lapId', 'label')},
            f'timer.read(id={identity}).timer.lapCount > 0'),
        'neyvia.timer.stop': ('neyvia.stop-timer', {'id': args.get('id')},
            f'timer.read(id={identity}).timer.status == "stopped"'),
        'neyvia.view.theme': ('neyvia.set-theme', {'theme': args.get('theme')},
            'settings.get().settings.theme == ' + quote(next((key for key, value in THEMES.items() if value == args.get('theme')), args.get('theme')))),
        'neyvia.pane.show': ('neyvia.show-pane', {'kind': args.get('kind'), 'target': args.get('target', '')},
            'pane.observe().mounted == True and pane.observe().visible == True and pane.observe().kind == ' + quote(args.get('kind'))),
        'neyvia.app.open': ('neyvia.open-app', {'app': args.get('app'), 'target': args.get('target', '')},
            'view.state().state.dom.mounted == True'),
    }
    if name == 'neyvia.timer.start' and 'targetSeconds' not in args:
        recipes[name] = ('neyvia.start-timer',
            {'id': args.get('id'), 'label': args.get('label')},
            f'timer.read(id={identity}).timer.status == "running"')
    if name == 'neyvia.view.arrange':
        layout = unwrap(protocol.gateway.call_native('neyvia.view.state', {})).get('state', {}).get('layout', {})
        recipes[name] = ('neyvia.arrange-view',
            {key: args.get(key, layout.get(key)) for key in ('order', 'dock', 'canopy', 'sidebarHidden', 'widgets')},
            'view.state().state.dom.mounted == True')
    recipe = recipes.get(name)
    if recipe is None:
        return {'ok': False, 'status': 'cl_goal_required',
                'error': 'Use neyvia.cl with an observer G and the current manual procedure; read neyvia.cl.describe(level=2, name=' + quote(name) + ') for the exact procedure.'}
    procedure, inputs, goal = recipe
    arguments = ', '.join(key + '=' + quote(value) for key, value in inputs.items())
    lines = f'G: {goal}\nrun {procedure}({arguments})\ndone()'
    return {'ok': False, 'status': 'cl_goal_required',
            'error': f'Use neyvia.cl with an observer G and the current manual procedure: run {procedure}({arguments}). Call neyvia.cl once with lines:\n{lines}',
            'recovery': {'tool': 'neyvia.cl', 'arguments': {'lines': lines}}}


def bind_task(protocol, args):
    """HTTP/MCP callers may bind the same intent native chat already supplies."""
    if 'task' not in args:
        return args
    task = args['task']
    if not isinstance(task, str) or not task.strip() or len(task) > 2000:
        raise ValueError('CL task must be nonempty user intent of at most 2000 characters')
    protocol.gateway.cl_task_text = task
    host = protocol.host
    if host is not None and host.task_text != task:
        host.task_text = task
        host.laya_route_verdict = None
        host.laya_route_learned = False
        host.routed_by_laya = None
    return {key: value for key, value in args.items() if key != 'task'}
