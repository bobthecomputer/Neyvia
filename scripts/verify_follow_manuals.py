"""Live manual registration, execution and loud schema-drift checks."""
import argparse
import copy
import http.cookiejar
import json
import sys
from pathlib import Path
from urllib.request import Request, HTTPCookieProcessor, build_opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--item', choices=['settings', 'drift', 'remote'], required=True)
    args = parser.parse_args()
    assert 48441 <= args.port <= 48449
    base = f'http://127.0.0.1:{args.port}'
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, value):
        with client.open(Request(base + path, data=json.dumps(value).encode(), headers={'Content-Type':'application/json'}), timeout=120) as response:
            return json.load(response)
    post('/api/auth/local-session', {})
    def tool(name, value):
        row = post('/api/ui/tools/call', {'tool':'neyvia.' + name, 'arguments':value})
        assert row['ok'] and row['data']['ok'], row
        return row['data']['result']
    index = tool('manual.index', {})
    assert args.item == 'drift' or any(row['id'] == args.item for row in index['manuals'])
    ids = [row['id'] for row in index['manuals']] if args.item == 'drift' else [args.item]
    verified = []
    for identity in ids:
        value = tool('manual.validate', {'id':identity})
        verified.append({'id':identity, 'grounded': value.get('grounded', True)})
    if args.item == 'settings':
        run = tool('manual.run', {'id':'settings', 'chapter':'overview', 'procedure':'read-preferences', 'inputs':{}})
        assert run['status'] == 'completed', run
    elif args.item == 'remote':
        observation = tool('manual.observe', {'id':'remote', 'chapter':'user-side', 'state':'connections', 'inputs':{}})
        assert observation, observation
    sys.path.insert(0, str(Path('src').resolve()))
    from grant_agent.neyvia_manuals import get_manual, validate
    from grant_agent.native_tools import NativeToolRegistry
    registry = NativeToolRegistry(Path('.agent_control/follow/manual-proof'))
    identity = 'settings' if args.item in {'settings', 'drift'} else 'remote'
    data = copy.deepcopy(get_manual(identity)[2])
    action = next(iter(next(iter(data['chapters'].values()))['actions'].values()))
    data['schemas'][action['schema']]['required'] = ['FOLLOW-deliberate-drift']
    try:
        validate(data, registry)
    except ValueError as error:
        assert 'schema' in str(error).lower(), str(error)
        loud = str(error)
    else:
        raise AssertionError('Drift was silently accepted')
    receipt = {'item':args.item, 'port':args.port, 'passed':True, 'manuals':verified, 'schemaDriftRefused':loud,
               'execution': 'read-preferences completed' if args.item == 'settings' else 'observational live validation'}
    Path(f'scripts/evidence/FOLLOW-{args.item}-manual.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'item':args.item, 'passed':True, 'validated':len(verified)}))


if __name__ == '__main__':
    main()
