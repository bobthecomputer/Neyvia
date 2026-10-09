"""App aliases complete only when their exact text mounts in the owned renderer."""
from __future__ import annotations

from . import renderer_effects
import time

SUPPORTED = {'neyvia.app.open', 'neyvia.artifact.open'}


def _binding(protocol, name, args):
    from ..neyvia_workspace_tools import workspace_for
    workspace = workspace_for(protocol.gateway.root)
    if name == 'neyvia.app.open':
        from ..neyvia_voice import resolve
        intent, payload = resolve(workspace, {'intent': 'app.open', 'args': dict(args)}, {})
        if intent == 'app.open':
            return {'app': payload}
        if intent != 'pane.show':
            return None
        if payload.get('kind') != 'file':
            return {'pane': payload}
        publication = None
    else:
        from ..neyvia_outputs import get
        result = get(workspace, args)
        if not result.get('ok') or result.get('availability') != 'available':
            return None
        publication = result['artifact']
        payload = {'kind': 'artifact', 'target': publication['path']}
        # Binary/image previews have a different content projection and need
        # their own retained renderer witness before admission here.
        from ..neyvia_panes import _guard, HTML_EXT, MARKDOWN_EXT
        from ..neyvia_files_tools import IMAGE_EXT
        suffix = _guard(workspace.bus.root, payload['target']).suffix.lower()
        # Do not invoke HTML preview classification here: it creates a token.
        # These exclusions follow the owner's preview-kind precedence; the
        # bounded decoder below decides whether the remaining file is text.
        if suffix in set(HTML_EXT) | set(MARKDOWN_EXT) | set(IMAGE_EXT) | {'.pdf'}:
            return None
    digest = renderer_effects._content(workspace.bus.root, 'file', payload['target'])
    if digest is None:
        return None
    return {'pane': payload, 'textHash': digest, 'publication': publication}


def snapshot_for(protocol, name, args):
    return _binding(protocol, name, args)


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    binding = _binding(protocol, name, args)
    if binding is None:
        return []
    if 'app' in binding:
        if protocol.scope is not None and 'neyvia.view.state' not in protocol.scope:
            return []
        def mounted(arguments, value, previous):
            from .fixcl4_render_effects import observe
            from ..ui_command_bus import bus_for
            deadline = time.monotonic() + 8
            while True:
                current = observe(bus_for(protocol.gateway.root))
                event = value.get('event', {})
                delivered = next((row for row in current.get('deliveries', []) if row['id'] == str(event.get('id'))), None)
                stage = current.get('dom', {}).get('stage', {})
                if (previous == binding and _binding(protocol, name, arguments) == binding
                        and current.get('fresh') and current.get('dom', {}).get('mounted')
                        and delivered and delivered['action'] == 'app.open' and delivered['payload'] == binding['app']
                        and stage.get('mounted') and stage.get('app') == binding['app']['app']
                        and current.get('stage') == {'type': 'app', **binding['app']}
                        and value.get('_appRuntime', current['runtimeId']) == current['runtimeId']):
                    value['_appRuntime'] = current['runtimeId']
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(.05)
        return [{'name': 'effect-mounted-app', 'observer': True, 'effect': True,
                 'observerTool': 'neyvia.view.state', 'subject': dict(args), 'subjectKey': 'app:' + binding['app']['app'],
                 'expectation': 'The requested ready app mounted in the fresh shell that delivered this exact event', 'check': mounted}]
    checks = renderer_effects.checks_for(protocol, 'neyvia.pane.show', binding['pane'])
    for row in checks:
        pane_check = row['check']
        def verify(arguments, value, previous, pane_check=pane_check):
            fresh = _binding(protocol, name, arguments)
            if fresh != binding or previous != binding:
                return False
            if name == 'neyvia.artifact.open' and value.get('artifact') != binding['publication']:
                return False
            fresh_renderer = renderer_effects._observe(protocol, value.get('event', {}).get('id'))
            if 'textHash' in binding and fresh_renderer.get('acknowledged') and fresh_renderer.get('contentHash') != binding['textHash']:
                return False
            return pane_check(binding['pane'], value, previous)
        row.update(name='effect-app-text-renderer', subject=dict(args), check=verify,
                   expectation='Exact unchanged app/publication bytes mounted in the same fresh visible renderer runtime')
    return checks
