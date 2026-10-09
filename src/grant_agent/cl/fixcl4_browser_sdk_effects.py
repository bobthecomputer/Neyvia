"""Actual owned browser sessions, SDK runtime verification and LAYA receipts.

Visible WebView2 promotion remains outside this adapter: a queued import is
not an observed transfer. Advisory decisions never authorize browser actions.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from .creative_effects import _owned
from .effects import _measure_file

SUPPORTED = {'neyvia.perception.browser.open', 'neyvia.perception.browser.action',
             'neyvia.perception.browser.close', 'neyvia.app_sdk.verify',
             'neyvia.app_sdk.preview', 'neyvia.browser.decide'}


def readonly(name, args=None):
    return True if name in {'neyvia.perception.browser.observe', 'neyvia.app_sdk.toolchain'} else None


def supported(name, args=None):
    return name in SUPPORTED


def _workspace(protocol):
    from ..neyvia_workspace_tools import workspace_for
    return workspace_for(protocol.gateway.root)


def _browser(protocol):
    from ..neyvia_browser import service_for
    return service_for(protocol.gateway.root)


def _sessions(protocol):
    from ..neyvia_perception import browsers
    return browsers(_workspace(protocol))


def _engine(protocol):
    engine = _browser(protocol).headless
    if not engine or not engine.status().get('connected'):
        raise ValueError('The live configured Neyvia browser is required')
    return {'pid':engine.process.pid, 'endpoint':engine.endpoint}


def _path(protocol, raw):
    path = Path(raw)
    return _owned(protocol, path if path.is_absolute() else Path(protocol.gateway.root) / path)


def _file(protocol, raw):
    path = _path(protocol, raw)
    value = _measure_file(path)
    if value.get('kind') != 'file':
        raise ValueError('A retained owning file is required')
    return path, value


def _json(protocol, raw):
    path, _ = _file(protocol, raw)
    return json.loads(path.read_bytes())


def _project(protocol, args):
    from ..app_sdk import confined, descriptor, source_hashes
    project = _path(protocol, confined(protocol.gateway.root, args['project']))
    return project, descriptor(project), source_hashes(project)


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    engine = _engine(protocol)
    if name.startswith('neyvia.perception.browser.'):
        sessions = _sessions(protocol)
        if sessions.headless is not _browser(protocol).headless:
            raise ValueError('Perception must use the configured Neyvia engine')
        ids = list(sessions.sessions)
        if name.endswith('.open'):
            # Creation order selects only the session this owner just opened.
            # Keep the native observation available to the host's stamp filler.
            observed = sessions.run('observe', ids[-1]) if ids else {}
            return {**observed, 'engine':engine,'ids':ids}
        sid = args['browserId']
        if name.endswith('.close') and sid not in sessions.sessions:
            return {'engine':engine,'ids':ids,'browserId':sid,'closed':True}
        observed = sessions.run('observe', sid)
        row = sessions.sessions[sid]
        if name.endswith('.action'):
            target = next((e for e in observed['elements'] if e['id'] == args['element']), None)
        else:
            target = None
        return {**observed, 'engine':engine,'ids':ids,'observed':observed,'target':target,
                'pageIdentity':id(row['page']),'contextIdentity':id(row['context'])}
    if name.startswith('neyvia.app_sdk.'):
        project, info, hashes = _project(protocol, args)
        return {'engine':engine,'project':str(project),'descriptor':info,'sourceHashes':hashes}
    from .browser_effects import _live
    browser = _browser(protocol)
    if browser.laya_client is None:
        raise ValueError('Attach the actual local LAYA service before asking it to decide')
    _live(browser,args['tabId'])
    return {'engine':engine,'projection':browser.projection(args['tabId']),
            'state':deepcopy(browser.state),'endpoint':browser.laya_client.hook.endpoint}


def _perception(protocol, name, args, value, before):
    sessions = _sessions(protocol)
    if _engine(protocol) != before['engine'] or sessions.headless is not _browser(protocol).headless:
        return False
    sid = args.get('browserId') or value.get('browserId')
    if name.endswith('.close'):
        pages = sessions.worker.submit(lambda:[id(page) for context in sessions.browser.contexts for page in context.pages]).result(timeout=10)
        return (value.get('closed') == sid and sid not in sessions.sessions and
                before['pageIdentity'] not in pages and
                set(sessions.sessions) == set(before['ids']) - {sid})
    if sid not in sessions.sessions:
        return False
    current = sessions.run('observe', sid)
    row = sessions.sessions[sid]
    from ..perception_browser import origin
    if origin(current['url']) != row['origin']:
        return False
    if name.endswith('.open'):
        return (sid not in before['ids'] and set(sessions.sessions) == set(before['ids']) | {sid} and
                value.get('url') == current['url'] == args['url'] and
                bool(current['revision']) and row['page'].is_closed() is False)
    if row['page'] is None or id(row['page']) != before['pageIdentity'] or id(row['context']) != before['contextIdentity']:
        return False
    from ..action_receipts import _safe_tool_result
    if value.get('observation') != _safe_tool_result(current) or value.get('action') != args['action'] or value.get('element') != args['element']:
        return False
    if current['revision'] == before['observed']['revision']:
        return False
    if args['action'] == 'fill':
        target = next((e for e in current['elements'] if e['id'] == args['element']), None)
        return target is not None and not target['secret'] and target['value'] == args.get('value','')
    return (current.get('text'),current.get('elements'),current.get('url')) != (
        before['observed'].get('text'),before['observed'].get('elements'),before['observed'].get('url'))


def _verify(protocol, args, value, before):
    from ..app_sdk import source_hashes, read, state_api
    project = Path(before['project'])
    receipt = _json(protocol, value['receipt'])
    if receipt != read(project/'.neyvia/latest-verification.json') or not receipt.get('ok') or receipt.get('status') != 'verified':
        return False
    from ..action_receipts import _safe_tool_result
    # Native receipts intentionally omit credential-bearing fields. Compare
    # that projection while independently checking the complete owner receipt.
    if any(value.get(k) != v for k,v in _safe_tool_result(receipt).items()) or receipt['sourceHashes'] != before['sourceHashes'] or source_hashes(project) != before['sourceHashes']:
        return False
    contract = read(project/'host-contract.json')
    if [row['step'] for row in receipt['journey']] != contract['journey'] + args.get('steps',[]):
        return False
    if any(row['goal'].get('passed') is not True for row in receipt['journey']) or not all(row['result'].get('passed') is True for row in receipt['checks']):
        return False
    if receipt['url'] != args['url'] or state_api(project)['count'] != receipt['journey'][-1]['step']['expect']:
        return False
    _, png = _file(protocol, receipt['screenshot'])
    from ..native_tools import NativeToolRegistry
    return (receipt['completion'] == 'R done ok +G' and png.get('bytes',0)>0 and
            min(NativeToolRegistry._png_dimensions(Path(receipt['screenshot'])))>0)


def _preview(protocol, args, value, before):
    from ..app_sdk import source_hashes, AppBrowser
    from ..neyvia_mobile_studio import state, TOKENS_KEY
    from .fixcl4_render_effects import observe
    from ..ui_command_bus import bus_for
    service = _workspace(protocol)
    saved = state(service)
    event = value.get('event') or {}
    current = observe(service.bus)
    delivered = next((row for row in current.get('deliveries',[]) if row['id']==str(event.get('id'))),None)
    frame = current.get('dom',{}).get('phone',{})
    requested = urlsplit(value.get('url',''))
    if (not value.get('ok') or not value.get('preview',{}).get('ready') or
        saved.get('project') != before['project'] or saved.get('device') != args.get('device',saved.get('device')) or
        not current.get('fresh') or not delivered or delivered['action'] != 'mobile.preview' or
        delivered['payload'] != event.get('payload') or frame.get('mounted') is not True or
        current.get('dom',{}).get('setup',{}).get('mounted') is True or
        (value.get('_sdkRuntime') and value['_sdkRuntime'] != current.get('runtimeId'))):
        return False
    if not any(urlsplit(row.get('src','')).path == requested.path and urlsplit(row.get('src','')).netloc == requested.netloc
               and row.get('width',0)>0 and row.get('height',0)>0
               and row.get('visibility',{}).get('visible') is True
               and row.get('runtime',{}).get('path') == requested.path
               and row.get('runtime',{}).get('instance') == before['descriptor']['instance']
               and bool(row.get('runtime',{}).get('text','').strip()) for row in frame.get('frames',[])):
        return False
    tokens = service.bus.get(TOKENS_KEY,{}) or {}
    token = requested.path.removeprefix('/api/ui/mobile-preview/').split('/')[0]
    if tokens.get(token) != before['project'] or source_hashes(Path(before['project'])) != before['sourceHashes']:
        return False
    browser = AppBrowser(value['url'],root=protocol.gateway.root)
    try:
        matched = browser.sdk('identity') == before['descriptor']['instance'] and bool(browser.observe()['text'])
        if matched: value['_sdkRuntime'] = current['runtimeId']
        return matched
    finally:
        browser.close()


def _decide(protocol, args, value, before):
    from .browser_effects import _live
    from ..laya_client.contracts import digest
    browser = _browser(protocol)
    _live(browser,args['tabId'])
    current = browser.projection(args['tabId'])
    receipt = _json(protocol,value['decisionReceipt'])
    decision = value.get('decision')
    _, measured = _file(protocol,value['decisionReceipt'])
    if not isinstance(decision,dict) or measured['sha256'] != value.get('decisionSha256'):
        return False
    with urlopen(before['endpoint']+'/v1/health',timeout=2) as response:
        health = json.load(response)
    answers = decision.get('answers',{})
    if not answers or any(row.get('answer') not in row.get('p',{}) or row.get('policy') not in {'answer','answer+postcheck','escalate','ask'}
                          or abs(sum(row.get('p',{}).values())-1)>1e-5 for row in answers.values()):
        return False
    return (value.get('available') is True and receipt.get('response') == decision and
            receipt.get('tabId') == args['tabId'] and receipt.get('question') == args['question'] and
            receipt.get('context') == args.get('context',{}) and receipt.get('endpoint') == before['endpoint'] and
            receipt.get('projection') == current == before['projection'] and
            decision.get('t20',{}).get('projection_digest') == digest(current) and
            decision.get('t20',{}).get('advisory_only') is True and
            decision.get('observation',{}).get('revision') == current['revision'] and
            health.get('identity') == decision.get('identity') and health.get('weights_frozen') is True and
            bool(decision.get('decision_id')) and decision.get('durable') is True and
            _engine(protocol) == before['engine'])


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    def check(arguments,value,previous):
        try:
            if not isinstance(value,dict) or not isinstance(previous,dict) or value.get('ok') is False:
                return False
            if name.endswith('.preview'):
                deadline = time.monotonic() + 8
                while not _preview(protocol,arguments,value,previous):
                    if time.monotonic() >= deadline: return False
                    time.sleep(.1)
                valid = True
            else:
                valid = (_perception(protocol,name,arguments,value,previous) if name.startswith('neyvia.perception.') else
                     _verify(protocol,arguments,value,previous) if name.endswith('.verify') else
                     _decide(protocol,arguments,value,previous))
            if not valid:
                return False
            files = [value['receipt']] if name.endswith('.verify') else [value['decisionReceipt']] if name.endswith('.decide') else []
            if name.endswith('.verify'): files.append(value['screenshot'])
            measured = {raw:_file(protocol,raw)[1] for raw in files}
            # Factory closures are recreated during completion. Retain the
            # first measured hashes in the host's action binding, so subsequent
            # checks compare against the original bytes rather than new bytes.
            key = '_browserSDKEffectFiles'
            if key not in value: value[key] = measured
            return value[key] == measured
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):
            return False
    subject = name+':'+str(args.get('browserId') or args.get('tabId') or args.get('project') or args.get('url'))
    rows = [{'name':'effect-'+name.replace('.','-'),'observer':True,'effect':True,
             'subjectKey':subject,'bindSubject':lambda arguments,value,previous:subject,
             'observerTool':'actual-neyvia-browser+fresh-owner-state-and-artifact-bytes',
             'subject':deepcopy(args),'expectation':'The exact actual runtime and retained owning evidence show this requested effect','check':check}]
    if name == 'neyvia.perception.browser.action':
        def fresh(arguments, value, previous):
            target = previous.get('target') or {}
            return (previous['observed']['revision'] == arguments['revision'] and
                    bool(target) and not target.get('secret') and target.get('enabled') is True and
                    arguments['action'] in target.get('actions', []))
        rows.insert(0, {'name':'fresh-private-browser-observation','observer':True,'effect':False,'pre':True,'check':fresh})
    return rows
