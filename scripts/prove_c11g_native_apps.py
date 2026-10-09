"""Real Office tool journeys and learned grounded compiler replay, no GUI input."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cua_native_procedures import APPLICATIONS, SCHEMAS
from grant_agent.native_tools import NativeToolRegistry
from grant_agent import neyvia_manuals as manuals
from grant_agent.manual_compiler import compile_procedure, run_compiled
from run_c11_cohort import write_receipt


def create_manual():
    inputs = {'type': 'object', 'properties': {'sessionId': {'type': 'string'},
        **{'value' + str(i): {'type': 'string'} for i in range(1, 6)}},
        'required': ['sessionId', *['value' + str(i) for i in range(1, 6)]], 'additionalProperties': False}
    chapter = {'title': 'Owned native document, version and render workflow', 'state': {},
        'actions': {}, 'checks': {}, 'procedures': {}, 'judge': {},
        'pitfalls': [{'failure': 'New-process ownership or guard fails', 'recovery': 'Refuse the session; never use an existing instance'}],
        'frontier': ['Firefox-family screenshot checks validate the rendered color and visible heading ink, not OCR text',
            'Pixel preview and UIA interaction are separate from these application-native tools'],
        'guidance': ['Only host-owned token files and hidden COM instances; compilation never removes native verifiers or guard checks']}
    steps = []
    for i in range(1, 6):
        name = 'revision' + str(i)
        chapter['actions'][name] = {'tool': 'neyvia.nativeapp.edit', 'schema': 'edit',
            'returns': {'type': 'object'}, 'pre': 'Owned hidden document and successful guard',
        'effect': 'Revise the owned native draft, Git note or browser card input', 'reversible': True}
        chapter['checks'][name] = {'tool': 'neyvia.nativeapp.observe',
            'args': {'sessionId': {'$input': 'sessionId'}, 'expected': {'$input': 'value' + str(i)}, 'persisted': False},
            'expect': {'path': 'ok', 'op': 'eq', 'value': True}}
        steps.append({'action': name, 'args': {'sessionId': {'$input': 'sessionId'}, 'value': {'$input': 'value' + str(i)}},
            'save': name, 'check': name})
    chapter['actions']['persist'] = {'tool': 'neyvia.nativeapp.persist', 'schema': 'persist', 'returns': {'type': 'object'},
        'pre': 'Token-owned draft', 'effect': 'Save and reopen a document, commit a local note, or render a card', 'reversible': True}
    chapter['checks']['persist'] = {'tool': 'neyvia.nativeapp.observe',
        'args': {'sessionId': {'$input': 'sessionId'}, 'expected': {'$input': 'value5'}, 'persisted': True},
        'expect': {'path': 'ok', 'op': 'eq', 'value': True}}
    steps.append({'action': 'persist', 'args': {'sessionId': {'$input': 'sessionId'}}, 'save': 'persist', 'check': 'persist'})
    chapter['procedures']['revise-save-reopen'] = {'goal': 'Revise an owned memo, budget, slide deck, versioned note or browser card; persist and independently verify the artifact', 'inputs': inputs, 'steps': steps}
    data = {'schema': 'neyvia.manual.v1', 'id': 'native-applications', 'kind': 'environment', 'schemas': SCHEMAS, 'chapters': {'office': chapter}}
    path = ROOT / 'manuals/native-applications.manual.json'
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Native application manual CL roundtrip differs')
    (ROOT / 'manuals/cl/native-applications.cl').write_text(source, encoding='utf-8', newline='\n')
    index_path = ROOT / 'config/neyvia_manuals.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    if not any(row['id'] == data['id'] for row in index['manuals']):
        index['manuals'].append({'id': data['id'], 'path': 'manuals/native-applications.manual.json',
            'clSource': 'manuals/cl/native-applications.cl',
            'description': 'Owned Office, shell, Git, note export and browser render workflows with grounded learned replay'})
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    else:
        for row in index['manuals']:
            if row['id'] == data['id']:
                row['clSource'] = 'manuals/cl/native-applications.cl'
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def run(receipt, selection=None):
    area = ROOT / '.agent_control/c11g-native-learning' / uuid.uuid4().hex
    area.mkdir(parents=True)
    registry = NativeToolRegistry(area, nas_root=area / '.local-unused')
    host = SimpleNamespace(bus=SimpleNamespace(root=area))
    runtime = registry.native_applications
    result = {'schema': 'neyvia.c11g.native-learning.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'boundary': 'application-native COM/shell tools and real Xournal++ PDF export, not UIA or pixel interaction', 'apps': [],
        'root': str(area), 'tokens': 0, 'sourceSha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('src/grant_agent/cua_native_procedures.py', 'src/grant_agent/cua_office.py', 'src/grant_agent/cua_desktop.py',
                'src/grant_agent/cua_guard.py', 'src/grant_agent/native_tools.py',
                'manuals/native-applications.manual.json', 'manuals/cl/native-applications.cl',
                'scripts/prove_c11g_native_apps.py')}}
    manuals.validate(manuals.get_manual('native-applications')[2], registry)
    selected = [app for app in APPLICATIONS if selection is None or app in selection]
    for app in selected:
        row = {'app': app, 'ok': False, 'uncompiledRuns': [], 'tokens': 0}
        result['apps'].append(row)
        identity = None
        try:
            opened = runtime.open({'app': app})
            identity = opened['sessionId']
            row['ownership'] = opened['ownership']
            inputs = {'sessionId': identity, **{'value' + str(i): app + ' project revision ' + str(i) + ' ' + identity for i in range(1, 6)}}
            args = {'id': 'native-applications', 'chapter': 'office', 'procedure': 'revise-save-reopen', 'inputs': inputs}
            dispatch = lambda tool, arguments, action_id='': getattr(runtime, tool.rsplit('.', 1)[1])(arguments)
            for _ in range(3):
                outcome = manuals.run(host, args, registry, dispatch)
                row['uncompiledRuns'].append(outcome)
                if not outcome['ok']:
                    raise RuntimeError(outcome.get('error', 'Native grounded run failed'))
            plan = compile_procedure(host, {**args, 'minRuns': 3}, registry)
            row['compiledPlan'] = plan
            row['replay'] = run_compiled(host, {'scriptId': plan['scriptId'], 'inputs': inputs}, registry, dispatch)
            row['independentFinalCheck'] = runtime.observe({'sessionId': identity, 'expected': inputs['value5'], 'persisted': True})
            row['ok'] = bool(plan['zeroToken'] and row['replay']['ok'] and row['independentFinalCheck']['ok'])
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            if not identity and runtime.failed_opens:
                row['failedOpeningGuard'] = runtime.failed_opens[-1]
        finally:
            if identity:
                row['close'] = runtime.close({'sessionId': identity})
                row['ok'] = row['ok'] and row['close']['ok']
            write_receipt(receipt, result)
        print(json.dumps({'app': app, 'ok': row['ok'], 'error': row.get('error')}), flush=True)
    result['appsWithVerifiedCompiledZeroTokenFlow'] = sum(row['ok'] for row in result['apps'])
    result['ok'] = result['appsWithVerifiedCompiledZeroTokenFlow'] == len(selected)
    result['sourceDrift'] = [name for name, sha in result['sourceSha256'].items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha]
    result['ok'] = result['ok'] and not result['sourceDrift']
    write_receipt(receipt, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--create-manual', action='store_true')
    parser.add_argument('--apps', nargs='*', choices=APPLICATIONS)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'scripts/evidence/C11g-apps-native.json')
    args = parser.parse_args()
    if args.create_manual:
        create_manual()
    else:
        raise SystemExit(0 if run(args.receipt, args.apps)['ok'] else 2)
