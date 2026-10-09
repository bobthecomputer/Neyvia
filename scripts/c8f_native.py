"""Execute the frozen C8 native manuals against an owned C11 application."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from prove_c11_preview import run
from grant_agent import neyvia_manuals as manuals
from grant_agent.native_tools import NativeToolRegistry


def probe(scratch, request, call, sid, wid, state):
    registry = NativeToolRegistry(scratch)
    host = SimpleNamespace(bus=SimpleNamespace(root=scratch))
    calls, rows = [], []

    def dispatch(tool, args, action_id=''):
        if tool.startswith('neyvia.cua.'):
            value = call(tool.rsplit('.', 1)[1], {**args, 'sessionId': sid})
        else:
            with request('/api/backend', {'command': 'call_native_tool_command',
                'payload': {'tool': tool, 'arguments': args}}) as response:
                raw = json.load(response)
            if not raw.get('ok'):
                raise RuntimeError(str(raw))
            value = manuals.unwrap(raw['data'])
        calls.append({'tool': tool, 'arguments': args, 'value': value})
        return value

    def procedure(identity, chapter, name, inputs, decisions=None):
        start = len(calls)
        row = {'id': '/'.join((identity, chapter, name)), 'passed': False}
        rows.append(row)
        try:
            _, digest, manual = manuals.get_manual(identity)
            row['manualSourceHash'] = digest
            row['manualLoaded'] = True
            arguments = {'id': identity, 'chapter': chapter, 'procedure': name, 'inputs': inputs}
            row['result'] = manuals.run(host, arguments, registry, dispatch)
            if decisions and row['result'].get('status') == 'judge':
                row['judgeObservation'] = row['result']
                row['result'] = manuals.run(host, {**arguments,
                    'runId': row['result']['runId'], 'decisions': decisions}, registry, dispatch)
            row['passed'] = row['result'].get('ok') is True
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)[:1000]
        row['calls'] = calls[start:]
        return row

    observed = call('inspect', {'sessionId': sid, 'window_id': wid})
    field = next(e for e in observed['elements'] if e['label'] == 'Task input')
    marker = 'C8f native field ' + scratch.name
    row = procedure('computer-use', 'drive', 'set-field-and-verify',
        {'window_id': wid, 'element_token': field['element_token'], 'label': 'Task input', 'role': field['role'],
         'expected': marker}, {'right-element': 'act'})
    fresh = call('inspect', {'sessionId': sid, 'window_id': wid})
    value = next(e for e in fresh['elements'] if e['label'] == 'Task input')['value']
    row['independentReadback'] = value
    row['passed'] = row['passed'] and value == marker
    check = dispatch('neyvia.cua.state', {})
    rows.append({'id': 'computer-use/drive/@check/driver-ready',
        'passed': check.get('driver', {}).get('available') is True,
        'observed': check, 'boundary': 'Actual owned driver and returned native windows'})
    for layer in ('os', 'window'):
        source = {'sessionId': sid, **({'window_id': wid} if layer == 'window' else {})}
        for name in ('read-layer', 'read-and-review'):
            row = procedure('perception', layer, name, {'source': source},
                {'coverage': 'answer'} if name == 'read-and-review' else None)
            observation = dispatch('neyvia.perception.observe', {'layer': layer, 'source': source})
            projection = dispatch('neyvia.perception.project', {'handle': observation['handle'],
                'path': '/state', 'limit': 100})
            row['freshProjection'] = projection
            row['passed'] = row['passed'] and bool(projection)
    call('flow', {'sessionId': sid, 'window_id': wid, 'steps': [{
        'selector': {'role': 'Edit', 'label': 'Task input'}, 'tool': 'set_value',
        'args': {'value': 'initial'}, 'expect': [{'element': {'selector':
            {'role': 'Edit', 'label': 'Task input'}, 'value_equals': 'initial'}}]}]})
    return {'rows': rows, 'passed': all(r['passed'] for r in rows),
        'boundary': 'Executed production manuals and real HTTP/CUA readbacks on the C11 private desktop',
        'sourceSha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            'scripts/c8f_native.py', 'manuals/computer-use.manual.json', 'manuals/perception.manual.json')}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--debug-port', required=True, type=int)
    parser.add_argument('--native-only', action='store_true')
    args = parser.parse_args()
    from c8_scope import assigned_ports
    if any(p not in assigned_ports() for p in (args.port, args.debug_port)) or args.port == args.debug_port:
        parser.error('Distinct assigned C8 ports required')
    output = ROOT / ('scripts/evidence/C8f-native-manuals.json' if args.native_only else 'scripts/evidence/C8f-native.json')
    ok = run(args.port, args.debug_port, output, journey_probe=probe,
             scratch_parent=ROOT / '.agent_control/proofs/C8/c8f-native', render_ui=not args.native_only)
    if args.native_only:
        receipt = json.loads(output.read_text(encoding='utf-8'))
        ok = bool(receipt.get('additionalJourneys', {}).get('passed') and receipt.get('guard', {}).get('ok'))
        receipt['nativeManualsPassed'] = ok
        output.write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    raise SystemExit(0 if ok else 2)
