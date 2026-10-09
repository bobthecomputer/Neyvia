"""Fresh Obscura tab and DOM effects for the integrated browser owner.

Queued WebView2 commands and LAYA advice remain outside this module. Captures
require an actual owned native page and its independently reopened PNG receipt.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


SUPPORTED = {'neyvia.browser.open', 'neyvia.browser.tab', 'neyvia.browser.action', 'neyvia.browser.capture'}
_TAB_OPS = {'navigate', 'back', 'forward', 'close', 'update', 'activate'}
_DOM_ACTIONS = {'click', 'fill', 'select'}


def _service(protocol):
    from ..neyvia_browser import service_for
    return service_for(protocol.gateway.root)


def _supported(name, args):
    if name == 'neyvia.browser.open':
        return args.get('engine') == 'obscura'
    if name == 'neyvia.browser.tab':
        return args.get('op') in _TAB_OPS
    if name == 'neyvia.browser.capture':
        return True
    return name == 'neyvia.browser.action' and args.get('action') in _DOM_ACTIONS


def _live(service, tab_id):
    tab = service.tab({'tabId': tab_id})
    if tab.get('engine') != 'obscura' or not tab.get('live') or not service.headless or not service.headless.status()['connected']:
        raise ValueError('An actual live Obscura tab is required')
    current = service.headless.run(tab['profileId'], 'observe', tab_id)
    projected = service.projection(tab_id)
    if any(projected.get(key) != value for key, value in current.items()):
        raise ValueError('Integrated browser projection drifted from actual engine DOM')
    if current.get('url') != tab.get('url') or current.get('title') != tab.get('title'):
        raise ValueError('Tab identity disagrees with actual engine')
    return current


def _persisted(service):
    saved = json.loads(service.path.read_text(encoding='utf-8'))
    return saved == service.state


def snapshot_for(protocol, name, args):
    if not _supported(name, args):
        return None
    service = _service(protocol)
    with service.lock:
        if not service.headless or not service.headless.status()['connected']:
            raise ValueError('Browser effect requires the installed live headless engine')
        state = deepcopy(service.state)
        if name == 'neyvia.browser.open':
            return {'state': state}
        tab = deepcopy(service.tab(args))
        if tab.get('engine') != 'obscura':
            return None
        current = _live(service, tab['id']) if name == 'neyvia.browser.action' or args.get('op') != 'close' else None
        if name == 'neyvia.browser.capture':
            worker = service.headless.profiles[tab['profileId']]
            captures = service.directory / 'captures'
            existing = sorted(path.name for path in captures.iterdir()) if captures.exists() else []
            if len(existing) > 2000:
                raise ValueError('Browser capture inventory exceeds the observation bound')
            return {'state':state,'tab':tab,'projection':current,'files':existing,
                'enginePid':service.headless.process.pid,'engineEndpoint':service.headless.endpoint,
                'pageIdentity':str(id(worker.pages[tab['id']]['page']))}
        if name == 'neyvia.browser.action':
            if current['revision'] != args.get('revision'):
                raise ValueError('Browser action projection is stale')
            target = next((row for row in current.get('elements', []) if str(row.get('id')) == str(args.get('element'))), None)
            if not target or target.get('secret') or args.get('action') not in target.get('actions', []):
                raise ValueError('Browser action target is absent or protected')
        else:
            target = None
        return {'state': state, 'tab': tab, 'projection': current, 'target': target}


def _check(protocol, name, args, value, before):
    if not isinstance(before, dict) or not isinstance(value, dict) or value.get('ok') is False:
        return False
    service = _service(protocol)
    with service.lock:
        if name == 'neyvia.browser.capture':
            return _check_capture(service, args, value, before)
        if not _persisted(service) or service.state['revision'] <= before['state']['revision']:
            return False
        if name == 'neyvia.browser.open':
            tab_id = value.get('tabId')
            if not tab_id or tab_id in {tab['id'] for tab in before['state']['tabs']}:
                return False
            tab = service.tab({'tabId': tab_id})
            current = _live(service, tab_id)
            return (len(service.state['tabs']) == len(before['state']['tabs']) + 1 and
                    service.state['tabs'][:-1] == before['state']['tabs'] and
                    service.state['activeTabId'] == tab_id and
                    tab == value.get('tab') and tab.get('engine') == 'obscura' and
                    tab.get('status') == 'live' and tab.get('url') == args['url'] and
                    current.get('readyState') == 'complete' and bool(current.get('revision')))
        tab_id = args['tabId']
        if name == 'neyvia.browser.tab' and args['op'] == 'close':
            if any(tab['id'] == tab_id for tab in service.state['tabs']):
                return False
            if service.projections.get(tab_id) is not None:
                return False
            worker = service.headless.profiles.get(before['tab']['profileId']) if service.headless else None
            return bool(worker and tab_id not in worker.pages and
                        len(service.state['tabs']) == len(before['state']['tabs']) - 1)
        tab = service.tab({'tabId': tab_id})
        if tab.get('engine') != 'obscura' or any(
                row != next((item for item in before['state']['tabs'] if item['id'] == row['id']), row)
                for row in service.state['tabs'] if row['id'] != tab_id):
            return False
        if name == 'neyvia.browser.tab' and args['op'] in {'update', 'activate'}:
            if args['op'] == 'activate':
                return service.state['activeTabId'] == tab_id and tab == before['tab']
            expected = deepcopy(before['tab'])
            for field in ('spaceId', 'pinned'):
                if field in args:
                    expected[field] = args[field]
            return tab == expected and value.get('tab') == expected
        current = _live(service, tab_id)
        observed = value.get('observation') or {}
        if observed.get('revision') != current.get('revision') or observed.get('url') != current.get('url'):
            return False
        if name == 'neyvia.browser.tab':
            if args['op'] == 'navigate' and (current['url'] != args.get('url') or current['url'] == before['tab']['url']):
                return False
            if args['op'] in {'back', 'forward'} and current['url'] == before['tab']['url']:
                return False
            history = service.state['history']
            old = before['state']['history']
            return (len(history) == len(old) + 1 and history[:-1] == old and
                    history[-1].get('tabId') == tab_id and history[-1].get('url') == current['url'] and
                    tab.get('status') == 'live' and current.get('readyState') == 'complete')
        if (before['projection']['revision'] != args['revision'] or
                before['projection']['revision'] == current['revision'] or
                current.get('readyState') != 'complete'):
            return False
        if args['action'] in {'fill', 'select'}:
            target = next((row for row in current.get('elements', []) if str(row.get('id')) == str(args['element'])), None)
            if not target or target.get('secret') or target.get('value') != args.get('value', ''):
                return False
        else:
            if (current.get('text'), current.get('url'), current.get('elements')) == (
                    before['projection'].get('text'), before['projection'].get('url'), before['projection'].get('elements')):
                return False
        return value.get('status') == 'done' and tab.get('status') == 'live'


def _check_capture(service, args, value, before):
    from PIL import Image
    from .effects import _measure_file
    if not _persisted(service) or service.state != before['state']:
        return False
    tab = service.tab(args)
    current = _live(service, tab['id'])
    worker = service.headless.profiles[tab['profileId']]
    if (tab != before['tab'] or service.headless.process.pid != before['enginePid'] or
        service.headless.endpoint != before['engineEndpoint'] or
        str(id(worker.pages[tab['id']]['page'])) != before['pageIdentity'] or
        current['revision'] != before['projection']['revision']):
        return False
    directory = (service.directory / 'captures').resolve()
    path = Path(value['path']).resolve()
    path.relative_to(directory)
    receipt_path = Path(value['receiptPath']).resolve()
    if receipt_path != path.with_suffix('.json') or path.name in before['files'] or receipt_path.name in before['files']:
        return False
    receipt = json.loads(receipt_path.read_bytes())
    actual = _measure_file(path)
    if actual.get('sha256') != receipt.get('sha256') or actual.get('bytes') != receipt.get('bytes') or actual.get('bytes',0)>32*1024*1024:
        return False
    with Image.open(path) as png:
        dimensions = png.size
        png.verify()
    action = service.actions.get(value.get('captureId'))
    expected_receipt = {key:item for key,item in value.items() if key not in {'ok','status','receiptPath'}}
    return bool(receipt == expected_receipt and action and action.get('status') == 'done' and
        action.get('receipt') == receipt and action.get('receiptPath') == str(receipt_path) and
        receipt.get('engine') == 'obscura' and receipt.get('enginePid') == before['enginePid'] and
        receipt.get('engineEndpoint') == before['engineEndpoint'] and receipt.get('pageIdentity') == before['pageIdentity'] and
        receipt.get('profileId') == tab['profileId'] and receipt.get('tabId') == args['tabId'] and
        receipt.get('sourceRevision') == current['revision'] and receipt.get('url') == current['url'] and
        actual.get('sha256') == receipt.get('sha256') and actual.get('bytes') == receipt.get('bytes') and
        dimensions == (receipt.get('width'),receipt.get('height')) and receipt.get('mime') == 'image/png')


def checks_for(protocol, name, args):
    if name not in SUPPORTED or not _supported(name, args):
        return []
    if name != 'neyvia.browser.open':
        try:
            if _service(protocol).tab(args).get('engine') != 'obscura':
                return []
        except (ValueError, KeyError):
            return []
    field = ('active' if name == 'neyvia.browser.tab' and args.get('op') == 'activate' else
             'pinned' if name == 'neyvia.browser.tab' and args.get('op') == 'update' else 'document')
    def bind(arguments, value, previous):
        return 'browser:' + str(arguments.get('tabId') or value.get('tabId')) + ':' + field
    def check(arguments, value, previous):
        try:
            return _check(protocol, name, arguments, value, previous)
        except (OSError, KeyError, TypeError, ValueError, RuntimeError, SyntaxError):
            return False
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': 'browser:' + str(args.get('tabId') or args.get('url')) + ':' + field,
             'bindSubject': bind, 'observerTool': 'neyvia.browser.state+actual-obscura-dom',
             'subject': {key: deepcopy(args[key]) for key in ('tabId', 'op', 'url', 'revision', 'element', 'action', 'value') if key in args},
             'expectation': 'Fresh owning tab state and installed engine DOM both show the requested subject effect',
             'check': check}]
