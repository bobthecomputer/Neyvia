"""Matched Luna evaluation bridge; only the disposable task target is exposed.

Both lanes use identical semantic actions. The screenshot lane receives pixels
only; UIA/DOM remains below the driver for targeting, never sent to that model.
This is an evidence harness, not a second UIA implementation.
"""
import base64
import json
import os
from pathlib import Path
import sys
import traceback
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
import grant_agent
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent import manual_state
from grant_agent.neyvia_perception import call, native, browsers
from grant_agent.neyvia_manuals import get_manual, render


class Bridge:
    def __init__(self, config):
        self.cfg = config
        self.root = Path(config['root'])
        self.workspace = workspace_for(self.root)
        self.log = self.root / 'calls.jsonl'
        self.latest = None
        if config['task'] == 'native':
            grant_agent.__path__.append(str(Path(config['t16Source']) / 'grant_agent'))
            from grant_agent.neyvia_cua import service_for
            self.cua = service_for(self.root)
            sid = self.cua.request('open', {'apps': ['powershell.exe'], 'chatId': 't18-proof', 'app': 'codex'}, owner=True)['id']
            self.source = {'sessionId': sid, 'window_id': config['window_id']}
        elif config['task'] == 'web':
            self.source = {'browserId': call(self.workspace, 'perception.browser.open', {'url': config['url']})['browserId']}
        else:
            self.source = {'path': config['path']}

    def tools(self):
        common = [
            {'name': 'observe', 'description': 'Observe only the current task target.', 'inputSchema': {'type': 'object', 'properties': {}}},
            {'name': 'manual', 'description': 'Read the grounded manual for this layer.', 'inputSchema': {'type': 'object', 'properties': {}}},
        ]
        if self.cfg['lane'] == 'text':
            common.append({'name': 'project', 'description': 'Bounded JSON Pointer read of an observation handle; /state is the source state.',
                           'inputSchema': {'type': 'object', 'properties': {'handle': {'type': 'string'}, 'path': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}, 'required': ['handle', 'path']}})
        if self.cfg['task'] in {'native', 'web'}:
            common.append({'name': 'act', 'description': 'Act only on the disposable app. Observe first. Fill the single editable field or click an exact visible label; ambiguity fails.',
                           'inputSchema': {'type': 'object', 'properties': {'action': {'enum': ['fill', 'click']}, 'text': {'type': 'string'}, 'label': {'type': 'string'}}, 'required': ['action']}})
        return common

    def invoke(self, name, args):
        task, lane = self.cfg['task'], self.cfg['lane']
        layer = {'native': 'window', 'web': 'browser', 'image': 'image'}[task]
        if name == 'manual':
            _, _, manual = get_manual('perception', self.root / '.neyvia')
            value = {'notation': render(manual['chapters'][layer], manual['schemas']), 'lane': lane,
                     'actions': 'Use act(fill,text) for the single field and act(click,label) for an exact button. Refresh after actions.'}
        elif name == 'project' and lane == 'text':
            value = call(self.workspace, 'perception.project', args)
        elif name == 'observe':
            if lane == 'text':
                if task == 'image':
                    value = {'ok': True, 'handle': self.cfg['handle'], 'mode': 'handle', 'layer': 'image', 'hint': 'Project /state/charts, /state/text or /state/layout.'}
                else:
                    value = call(self.workspace, 'perception.observe', {'layer': layer, 'source': self.source, 'stream': 'evaluation'})
                self.latest = value
            elif task == 'native':
                capture = self.cua.request('capture', self.source)
                image = Path(capture['path']).read_bytes()
                self.latest = capture
                return self.record(name, args, {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(image).decode()}]})
            elif task == 'web':
                browser = browsers(self.workspace)
                # Recording below uses this same owned Playwright context.
                def screenshot():
                    return browser.sessions[self.source['browserId']]['page'].screenshot()
                image = browser.worker.submit(screenshot).result(timeout=15)
                self.latest = {'observed': True}
                return self.record(name, args, {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(image).decode()}]})
            else:
                image = (self.root / self.cfg['path']).read_bytes()
                return self.record(name, args, {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(image).decode()}]})
        elif name == 'act' and task in {'native', 'web'}:
            if not self.latest:
                raise ValueError('Observe before acting')
            if task == 'native':
                current = self.cua.request('inspect', self.source)
                if args['action'] == 'fill':
                    candidates = [e for e in current['elements'] if e.get('role') in {'Edit', 'Document'} and 'set_value' in e.get('actions', [])]
                else:
                    candidates = [e for e in current['elements'] if e.get('label') == args.get('label') and e.get('role') == 'Button']
                if len(candidates) != 1:
                    raise ValueError('Semantic target must be unique')
                a = {'window_id': self.source['window_id'], 'element_token': candidates[0]['element_token']}
                tool = 'set_value' if args['action'] == 'fill' else 'click'
                if args['action'] == 'fill':
                    a['value'] = args['text']
                value = self.cua.request('action', {**self.source, 'tool': tool, 'args': a})
                after = self.cua.request('inspect', self.source)
                (self.root / 'final-state.json').write_text(json.dumps(after), encoding='utf-8')
            else:
                current = browsers(self.workspace).run('observe', self.source['browserId'])
                if args['action'] == 'fill':
                    candidates = [e for e in current['elements'] if 'fill' in e['actions'] and not e['secret']]
                else:
                    candidates = [e for e in current['elements'] if e['name'] == args.get('label') and 'click' in e['actions']]
                if len(candidates) != 1:
                    raise ValueError('Semantic target must be unique')
                value = call(self.workspace, 'perception.browser.action', {**self.source, 'revision': current['revision'],
                    'element': candidates[0]['id'], 'action': args['action'], 'value': args.get('text', '')})
                (self.root / 'final-state.json').write_text(json.dumps(value['observation']), encoding='utf-8')
                if lane == 'screenshot':
                    value = {'ok': value['ok'], 'action': args['action']}  # no text-state leak
            self.latest = None
        else:
            raise ValueError('Tool outside evaluation scope')
        return self.record(name, args, {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]})

    def record(self, name, args, result):
        safe = {'name': name, 'arguments': args, 'image': any(c['type'] == 'image' for c in result['content']),
                'texts': [c['text'] for c in result['content'] if c['type'] == 'text']}
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(safe, ensure_ascii=False) + '\n')
        return result

    def close(self):
        if hasattr(self, 'cua'):
            self.cua.shutdown()
        if hasattr(self.workspace, '_perception_browser'):
            self.workspace._perception_browser.close()


def main():
    bridge = Bridge(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    try:
        for line in sys.stdin:
            req = json.loads(line)
            if 'id' not in req:
                continue
            try:
                method = req['method']
                if method == 'initialize':
                    result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 't18-bounded-proof', 'version': '1'}}
                elif method == 'tools/list':
                    result = {'tools': bridge.tools()}
                elif method == 'tools/call':
                    result = bridge.invoke(req['params']['name'], req['params'].get('arguments', {}))
                elif method == 'ping':
                    result = {}
                else:
                    raise ValueError('Unsupported method')
                reply = {'jsonrpc': '2.0', 'id': req['id'], 'result': result}
            except Exception as exc:
                reply = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}}
            print(json.dumps(reply), flush=True)
    finally:
        bridge.close()

if __name__ == '__main__':
    main()
