"""Effects witnessed by the mounted shell, never by a queued bus ACK."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import time

SUPPORTED = {'neyvia.view.theme', 'neyvia.view.arrange', 'neyvia.view.scene', 'neyvia.view.float', 'neyvia.view.place',
             'neyvia.notes.open', 'neyvia.onboarding.open', 'neyvia.notify', 'neyvia.voice.command', 'neyvia.folder.open'}


def supported(name, args=None):
    return name in SUPPORTED


def report_state(root, state, client):
    from ..ui_command_bus import bus_for
    if not isinstance(state, dict) or len(json.dumps(state)) > 256 * 1024:
        raise ValueError('A shell observation must be a bounded object')
    if not isinstance(state.get('runtimeId'), str) or not state['runtimeId'].startswith('shell-'):
        raise ValueError('The mounted shell runtime is required')
    deliveries = state.get('deliveries')
    if not isinstance(deliveries, list) or len(deliveries) > 24:
        raise ValueError('Shell deliveries are bounded to 24')
    bus = bus_for(root)
    with bus.connect() as db:
        for delivery in deliveries:
            row = db.execute('SELECT action,payload FROM events WHERE id=?', (int(delivery['id']),)).fetchone()
            if row is None or row['action'] != delivery.get('action') or json.loads(row['payload']) != delivery.get('payload'):
                raise ValueError('Rendered delivery does not match the authenticated event')
    observed = {**deepcopy(state), 'observedAt': time.time(), 'clientId': client}
    bus.put('renderer:shell', observed)
    return {'ok': True, 'runtimeId': observed['runtimeId']}


def observe(bus):
    state = deepcopy(bus.get('renderer:shell') or {})
    age = time.time() - state.get('observedAt', 0)
    state['fresh'] = 0 <= age <= 2.5
    return state


def _bus(protocol):
    from ..ui_command_bus import bus_for
    return bus_for(protocol.gateway.root)


def snapshot_for(protocol, name, args):
    before = {'renderer': observe(_bus(protocol))}
    if name == 'neyvia.notes.open':
        from ..neyvia_notes_tools import read_note
        note = read_note(protocol.gateway.root, args)
        before['note'] = {'path':note['path'], 'bodyHash':hashlib.sha256(note['body'].encode()).hexdigest()}
    elif name == 'neyvia.folder.open':
        return _folder(protocol, args)
    return before


def _folder(protocol, args):
    from ..neyvia_files_tools import call_files
    from ..neyvia_workspace_tools import workspace_for
    path = str(workspace_for(protocol.gateway.root).safe_path(args['path']))
    listed = call_files(protocol.gateway.root, 'list', {'path':path})
    if listed.get('truncated'):
        raise ValueError('Folder effect requires a complete bounded listing')
    visible = [row for row in listed.get('entries', []) if not row.get('hidden')]
    content = '\n'.join([path, *[(('d' if row['kind'] == 'folder' else 'f') + ' ' + row['name']) for row in visible]])
    return {'path':path, 'listingHash':hashlib.sha256(content.encode()).hexdigest()}


def readonly(name, args):
    return True if name == 'neyvia.voice.command' and args.get('dryRun') is True else None


def _match(protocol, name, args, value, before, current):
    if not current.get('fresh') or current.get('dom', {}).get('mounted') is not True:
        return False
    event = value.get('event')
    if name == 'neyvia.voice.command':
        if value.get('status') != 'done' or value.get('replayed') or len(value.get('events', [])) != 1:
            return False
        event = value['events'][0]
    if not event or not event.get('id'):
        return False
    found = next((row for row in current.get('deliveries', []) if row['id'] == str(event['id'])), None)
    if not found or found['action'] != event['action'] or found['payload'] != event['payload']:
        return False
    pinned = value.get('_shellRuntime')
    if pinned and pinned != current['runtimeId']:
        return False
    payload, action, dom = event['payload'], event['action'], current['dom']
    if action == 'notes.open':
        from ..neyvia_notes_tools import read_note
        note = read_note(protocol.gateway.root, {'path': payload['path']})
        expected = hashlib.sha256(note['body'].encode()).hexdigest()
        matched = (current.get('stage', {}).get('app') == 'notes' and current['stage'].get('target') == note['path']
                   and dom.get('notes', {}).get('mounted') is True and dom['notes'].get('textHash') == expected)
        if name == 'neyvia.notes.open':
            matched = matched and before.get('note') == {'path':note['path'], 'bodyHash':expected}
    elif action == 'notify':
        old_ids = {row.get('id') for row in before.get('renderer', {}).get('dom', {}).get('notices', [])}
        pinned_notice = value.get('_shellNoticeId')
        notice = next((row for row in dom.get('notices', []) if row.get('text') == payload['message']
                       and (row.get('id') == pinned_notice if pinned_notice else row.get('id') not in old_ids)), None)
        matched = notice is not None
        if matched: value['_shellNoticeId'] = notice['id']
    elif action == 'app.open' and payload.get('app') == 'notes':
        matched = (current.get('stage') or {}).get('app') == 'notes' and dom.get('notes', {}).get('appMounted') is True
    elif action == 'stage.close':
        matched = current.get('stage') is None and bool(dom.get('regions'))
    elif action == 'onboarding.open':
        labels = {'welcome':'Welcome', 'runtimes':'Agents', 'interests':'Interests', 'tour':'Tour'}
        matched = (dom.get('setup', {}).get('mounted') is True and
                   labels.get(payload.get('step', 'welcome'), 'Welcome') in dom['setup'].get('step', ''))
    elif action == 'view.float':
        wanted = payload.get('floating') is not False
        matched = ((payload['id'] in current.get('bubbles', [])) == wanted and
                   (payload['id'] in dom.get('bubbles', [])) == wanted)
    elif action == 'view.place':
        identity, placement = payload['id'], payload['placement']
        window = next((row for row in current.get('windows', []) if row['id'] == identity), None)
        mounted = next((row for row in dom.get('windows', []) if row['id'] == identity), None)
        if placement == 'close':
            matched = window is None and mounted is None and identity not in dom.get('surfaceBubbles', [])
        else:
            matched = bool(window and window['placement'] == placement)
            matched = matched and (identity in dom.get('surfaceBubbles', []) if placement == 'bubble' else
                                   bool(mounted and mounted['placement'] == placement and mounted['visible']))
            if payload.get('side'):
                regions = {row['id']: row['x'] for row in dom.get('regions', [])}
                matched = matched and 'panel' in regions and 'main' in regions and (
                    regions['panel'] < regions['main'] if payload['side'] == 'left' else regions['panel'] > regions['main'])
    elif action == 'view.theme':
        matched = current.get('theme') == payload['theme'] and dom.get('theme') == payload['theme']
    elif action == 'view.arrange':
        layout = current.get('layout', {})
        matched = all(layout.get(key) == val for key, val in payload.items())
        present = sorted(dom.get('regions', []), key=lambda row:row['x'])
        ordered = [row['id'] for row in present]
        matched = matched and ordered == [key for key in layout.get('order', []) if key in ordered]
        if 'sidebarHidden' in payload:
            matched = matched and ('sidebar' not in ordered) == payload['sidebarHidden']
    elif action == 'view.scene':
        previous = before.get('renderer', {})
        if payload.get('save'):
            scene = current.get('scenes', {}).get(payload['save'].strip().lower().replace(' ', '-')) or {}
            matched = all(scene.get(key) == previous.get(key) for key in ('layout', 'density', 'theme'))
        else:
            presets = {'focus':('calm','off'), 'workshop':('workshop','auto'), 'cockpit':('grove','on')}
            selected = presets.get(payload.get('name'))
            scene = previous.get('scenes', {}).get(payload.get('name')) or {}
            matched = (current.get('density') == selected[0] and current.get('layout', {}).get('canopy') == selected[1]) if selected else (
                bool(scene) and all(current.get(key) == scene.get(key) for key in ('layout', 'density', 'theme')))
        matched = matched and bool(dom.get('regions'))
    else:
        return False
    if matched: value['_shellRuntime'] = current['runtimeId']
    return bool(matched)


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    if name == 'neyvia.folder.open':
        from . import renderer_effects
        binding = _folder(protocol, args)
        pane_args = {'kind':'file', 'target':binding['path']}
        checks = renderer_effects.checks_for(protocol, 'neyvia.pane.show', pane_args)
        for row in checks:
            pane_check = row['check']
            def folder_check(arguments, value, before, pane_check=pane_check):
                if before != binding or _folder(protocol, arguments) != binding:
                    return False
                report = renderer_effects._observe(protocol, value.get('event', {}).get('id'))
                if not report.get('acknowledged'): return None
                return report.get('contentHash') == binding['listingHash'] and pane_check(pane_args, value, before)
            row.update(name='effect-mounted-folder-listing', check=folder_check, subject=dict(args),
                       expectation='Current actual mounted folder listing equals the freshly reread visible directory entries')
        return checks
    if protocol.scope is not None and 'neyvia.view.state' not in protocol.scope:
        return []
    if name == 'neyvia.voice.command':
        from ..neyvia_voice import parse, resolve
        from ..neyvia_workspace_tools import workspace_for
        try:
            intent, payload = resolve(workspace_for(protocol.gateway.root), parse(args.get('text', ''), final=args.get('final', True)), args.get('context') or {})
        except Exception:
            return []
        # Each additional spoken effect needs its own mounted subject binding.
        if intent not in {'notes.open', 'onboarding.open', 'view.arrange', 'view.scene', 'view.float', 'notify', 'stage.close'} and not (intent == 'app.open' and payload.get('app') == 'notes'):
            return []
    def check(arguments, value, previous):
        deadline = time.monotonic() + (15 if name == 'neyvia.onboarding.open' else 8 if name == 'neyvia.notes.open' else 5)
        while True:
            if _match(protocol, name, arguments, value, previous or {}, observe(_bus(protocol))):
                return True
            if time.monotonic() >= deadline: return False
            time.sleep(.05)
    return [{'name':'effect-mounted-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer':True, 'effect':True, 'observerTool':'neyvia.view.state',
             'subject':dict(args), 'subjectKey':'shell:' + name.removeprefix('neyvia.'),
             'expectation':'Current mounted DOM and state bound to the exact delivered event, runtime and requested subject',
             'check':check}]
