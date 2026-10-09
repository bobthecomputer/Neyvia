"""One-command, source-current AUD4 regeneration through compiled CL journeys.

Run with system Python and --port 48781. Unchanged successful or failed runs are
reused only while their complete source and executable hashes still match.
--all replays everything; --only selects a repair batch. No historical receipt
is rehashed into fresh evidence. Compiled workers preserve original assertions.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / 'scripts/evidence'
SCRATCH = REPO / '.agent_control/fixcl7'
PORTS = range(48781, 48790)
PROBES = {
    **{name: (f'fixcl2_{name}_probe.py', []) for name in ('terminal', 'work', 'creative', 'coordination', 'semantic', 'durable', 'frontier')},
    'sidebar': ('fixcl2_sidebar_frontier_probe.py', []),
    **{name: (f'fixcl3_{name.replace("-", "_")}_probe.py', []) for name in (
        'core', 'records', 'mechanisms', 'environment', 'configuration', 'projection', 'jobs',
        'manual-execution', 'manual-grounding', 'authority', 'documents')},
    **{name: (f'fixcl4_{name}_probe.py', []) for name in ('evaluation', 'evolver', 'host', 'conductor')},
    'services': ('fixcl4_services_probe.py', ['--skip-native']),
    'browser-sdk': ('fixcl4_browser_sdk_probe.py', ['--skip-laya']),
    'provider': ('fixcl4_provider_probe.py', []),
    'renderer-pdf': ('fixcl4_render_pdf_probe.py', []),
    'renderer': ('fixcl3_renderer_probe.py', []),
    'sdk-mount': ('fixcl4_sdk_mount_probe.py', []),
    'browser': ('fixcl2_browser_probe.py', []),
    'device-pdf': ('fixcl3_device_pdf_probe.py', []),
}

_hashes = {}
def sha(path):
    # Every command starts with an empty cache and reads the actual bytes.
    # Repeated owners can share unchanged inputs within that one invocation;
    # edits during a batch invalidate the entry. No persistent stat-only proof.
    stamp = path.stat()
    key = (str(path), stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size)
    if key not in _hashes: _hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _hashes[key]

def sources():
    paths = list((REPO / 'src/grant_agent').rglob('*.py'))
    paths += list((REPO / 'src/grant_agent').rglob('*.js'))
    for folder, pattern in [('manuals', '*.json'), ('manuals/cl', '*.cl'), ('config', '*.json'), ('config/app_sdk', '*'), ('web/src', '*')]:
        paths += [p for p in (REPO / folder).rglob(pattern) if p.is_file()
                  and not any(word in p.name.lower() for word in ('credential', 'secret', 'password', 'token'))]
    paths += [REPO / 'scripts/fixcl_verify.py', REPO / 'scripts/build_app_sdk_runtime.mjs']
    paths += [REPO / 'scripts' / v[0] for v in PROBES.values()]
    return {p.relative_to(REPO).as_posix(): sha(p) for p in sorted(set(paths))}

def compile_probe(name):
    path = REPO / 'scripts' / PROBES[name][0]
    tree = ast.parse(path.read_text(encoding='utf-8'))
    class Relocate(ast.NodeTransformer):
        def visit_Constant(self, node):
            value = node.value
            if type(value) is int and 48821 <= value <= 48830: value -= 40
            elif isinstance(value, str):
                # Receipt paths/identities only. Source code and assertions stay intact.
                for wave in ('FIXCL2', 'FIXCL3', 'FIXCL4', 'FIXCL5', 'FIXCL6'):
                    if value.startswith('scripts/evidence/') and value.endswith('.json') and '-before.json' not in value:
                        value = value.replace(wave, 'FIXCL7')
                for port in range(48821, 48830): value = value.replace(str(port), str(port - 40))
            return ast.copy_location(ast.Constant(value), node)
    tree = ast.fix_missing_locations(Relocate().visit(tree))
    identity = hashlib.sha256((ast.dump(tree) + sys.version).encode()).hexdigest()
    target = SCRATCH / 'compiled' / (identity + '.marshal')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists(): target.write_bytes(marshal.dumps(compile(tree, str(path), 'exec')))
    return path, target

def dependencies(name, receipt, current):
    # Owner receipts declare the sources they exercised. Add shared CL finish
    # and compiler dependencies, then compare those exact recorded bytes. UI
    # changes must not force unrelated backend journeys to run again.
    proof = json.loads(receipt.read_bytes()) if receipt.is_file() else {}
    declared = proof.get('sourceHashesAtStart', proof.get('sourceHashes', {}))
    if not declared: return current
    names = {p.replace('\\','/') for p in declared}
    names.update(p for p in current if p.startswith('src/grant_agent/cl/'))
    names.update(('src/grant_agent/cl_deliverables.py','src/grant_agent/neyvia_language.py',
        'config/fixcl_manual_cache.json','config/neyvia_manuals.json','scripts/fixcl_verify.py',
        'scripts/'+PROBES[name][0]))
    if name in {'browser-sdk','sdk-mount'}:
        names.update(('scripts/build_app_sdk_runtime.mjs','src/grant_agent/neyvia_mobile_preview_helper.js'))
        names.update(p for p in current if p.startswith('config/app_sdk/'))
    if name == 'device-pdf': names.add('config/neyvia_remote.json')
    return {p:current[p] if p in current else sha(REPO/p) for p in sorted(names)}

def argv_for(name, args):
    path = REPO / 'scripts' / PROBES[name][0]
    text = path.read_text(encoding='utf-8')
    argv = []
    renderer = name in {'renderer', 'renderer-pdf', 'sdk-mount'}
    if renderer:
        argv = ['--backend-port', str(args.port), '--ui-port', str(args.port+1), '--pane-port', str(args.port+2),
                '--fixture-port', str(args.port+3), '--ipc-port', str(args.port+4), '--ipc-port', str(args.port+5),
                '--ipc-port', str(args.port+6), '--dist', str(args.dist), '--obscura', str(args.obscura), '--wave', 'FIXCL7']
    else:
        fixed = {'configuration':48784, 'projection':48789, 'manual-grounding':48788,
                 'documents':48789, 'coordination':48788, 'semantic':48789, 'terminal':48782}
        if "'--port'" in text: argv += ['--port', str(fixed.get(name, args.port))]
        if "'--output'" in text: argv += ['--output', str(OUT / f'FIXCL7-{name}.json')]
        if "'--root'" in text: argv += ['--root', str(SCRATCH / ('runtime-' + name))]
        if name == 'browser-sdk':
            argv += ['--port', str(args.port), '--browser-port', str(args.port+1), '--ipc-port', str(args.port+2),
                     '--laya-port', str(args.port+3), '--obscura', str(args.obscura),
                     '--laya-source', str(REPO), '--laya-model', str(SCRATCH / 'unused-model')]
        if name == 'browser': argv = ['--engine-port','48785','--fixture-port','48786']
        if name == 'device-pdf': argv = ['--ports','48787','48788']
    return [*argv, *PROBES[name][1]]

def worker(args):
    path, compiled = compile_probe(args.worker)
    sys.path[:0] = [str(REPO / 'scripts'), str(REPO / 'src')]
    # Refuse accidental outside ports and visible subprocesses even in legacy probes.
    def guard(event, values):
        if event in {'socket.bind', 'socket.connect'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in PORTS):
                raise PermissionError('FIXCL7 admits only explicit assigned loopback ports')
    sys.addaudithook(guard)
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install_hidden_subprocess_default()
    if args.worker == 'browser' and os.name == 'nt':
        import socket
        def assigned_pair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
            listener = socket.socket(socket.AF_INET, type, proto)
            client = socket.socket(socket.AF_INET, type, proto)
            try:
                listener.bind(('127.0.0.1', 48787)); listener.listen(1)
                client.connect(('127.0.0.1', 48787)); accepted, _ = listener.accept()
                return accepted, client
            except BaseException:
                client.close(); raise
            finally: listener.close()
        socket.socketpair = assigned_pair
    # Wrappers use the same explicitly assigned rendering ports and wave.
    sys.argv = [str(path), *argv_for(args.worker, args)]
    scope = {'__name__': 'fixcl7_compiled_worker', '__file__': str(path), '__package__': None}
    exec(marshal.loads(compiled.read_bytes()), scope)
    if args.worker == 'browser': scope['EXE'] = args.obscura
    if 'main' in scope: raise SystemExit(scope['main']())
    else:
        # Scripts without a main function retain their own executable guard.
        scope['__name__'] = '__main__'
        exec(marshal.loads(compiled.read_bytes()), scope)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--obscura', type=Path, default=SCRATCH/'obscura-target/release/obscura.exe')
    parser.add_argument('--dist', type=Path, default=SCRATCH / 'render-dist')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--only')
    parser.add_argument('--worker', choices=PROBES)
    args = parser.parse_args()
    if args.port != PORTS.start: parser.error('Base port must be 48781; all workers use explicit 48781–48789')
    if args.worker: return worker(args)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0',
               FLUXIO_WATCHDOG_AUTOSTART='0', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    def run(argv, log, timeout=600):
        with log.open('w', encoding='utf-8') as stream:
            try:
                return subprocess.run(argv, cwd=REPO, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).returncode
            except subprocess.TimeoutExpired: return 124
    state_path = OUT / 'FIXCL7-regeneration.json'
    state = json.loads(state_path.read_bytes()) if state_path.exists() else {'schema':'neyvia.receipt-regeneration.v1', 'probes':{}}
    cache_path = REPO / 'config/fixcl_manual_cache.json'
    cache = json.loads(cache_path.read_bytes())
    bindings = {**cache['compiler'], 'config/neyvia_manuals.json':cache['indexSourceSha256']}
    for manual in cache['manuals'].values():
        bindings[manual['source']] = manual['sourceSha256']
        bindings[manual['artifact']] = manual['artifactSha256']
    if any(not (REPO / p).is_file() or sha(REPO / p) != digest for p,digest in bindings.items()):
        code = run([sys.executable,str(REPO/'scripts/build_fixcl_manual_cache.py')],SCRATCH/'manual-cache.log')
        if code: raise RuntimeError('Manual compilation failed; see manual-cache.log')
    current = sources()
    selection = args.only.split(',') if args.only else list(PROBES)
    if any(n not in PROBES for n in selection): parser.error('Unknown probe selection')
    rendered = {'browser-sdk','renderer','renderer-pdf','sdk-mount'} & set(selection)
    ui_sources = {name:digest for name,digest in current.items() if name.startswith('web/')}
    if rendered and (not args.dist.is_dir() or state.get('uiSources') != ui_sources):
        config = SCRATCH/'vite.verify.config.mjs'
        config.write_text("import config from '../../vite.config.mjs';\nimport { resolve } from 'node:path';\nexport default env => ({ ...config(env), cacheDir: resolve('.agent_control/fixcl7/vite-cache') });\n",encoding='utf-8')
        code = run(['node',str(REPO/'node_modules/vite/bin/vite.js'),'build','--config',str(config),'--configLoader','runner','--outDir',str(args.dist)],SCRATCH/'build.log')
        if code: raise RuntimeError('Actual UI build failed; see build.log')
        state['uiSources'] = ui_sources
    for name in selection:
        # Repairs can land during a long batch. Bind each run to the tree it
        # actually starts on, rather than the batch's earlier snapshot.
        current = sources()
        receipt = OUT / f'FIXCL7-{"evaluations" if name == "evaluation" else name}.json'
        previous = state['probes'].get(name, {})
        compiled_path, code = compile_probe(name)
        bindings = {**dependencies(name,receipt,current), 'executable:python':sha(Path(sys.executable))}
        if name in {'browser-sdk','renderer','renderer-pdf','sdk-mount','browser'}:
            bindings['executable:obscura'] = sha(args.obscura)
        if name in {'browser-sdk','renderer','renderer-pdf','sdk-mount'}:
            bindings.update({'dist:'+p.relative_to(args.dist).as_posix():sha(p) for p in args.dist.rglob('*') if p.is_file()})
        if (not args.all and all(previous.get('sourceHashes',{}).get(p) == digest for p,digest in bindings.items())
                and previous.get('compiledSha256') == sha(code) and receipt.exists()
                and previous.get('receiptSha256') == sha(receipt)):
            print(json.dumps({'probe':name, 'status':'current', 'exitCode':previous['exitCode']}), flush=True); continue
        if receipt.exists():
            archive = SCRATCH / 'previous' / str(time.time_ns()); archive.mkdir(parents=True)
            receipt.replace(archive / receipt.name)
        started = time.monotonic()
        log = SCRATCH / (name + '.log')
        cmd = [sys.executable, str(Path(__file__)), '--worker', name, '--port', str(args.port), '--obscura', str(args.obscura), '--dist', str(args.dist)]
        print(json.dumps({'probe':name, 'status':'running'}), flush=True)
        exit_code = run(cmd, log)
        # Every wrapper writes this wave directly. Historical bytes stay intact.
        if not receipt.exists() and exit_code == 0: exit_code = 1
        proof = json.loads(receipt.read_bytes()) if receipt.exists() else {'checks':{'freshReceiptPresent':False}, 'error':'No fresh receipt; see worker log'}
        bindings = {**dependencies(name,receipt,current), **{p:digest for p,digest in bindings.items()
            if p.startswith(('executable:','dist:'))}}
        row = {'sourceHashes':bindings, 'compiledSha256':sha(code), 'receiptSha256':sha(receipt) if receipt.exists() else None,
               'exitCode':exit_code, 'seconds':round(time.monotonic()-started,3), 'log':log.relative_to(REPO).as_posix(),
               'failedChecks':[k for k,v in proof.get('checks',{}).items() if v is not True]}
        state['probes'][name] = row
        state_path.write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'probe':name, **{k:row[k] for k in ('exitCode','seconds','failedChecks')}}), flush=True)
    snapshot = OUT / 'FIXCL7-AUD4-after-snapshots.json'
    audit = OUT / 'FIXCL7-AUD4-after.json'
    audit_bindings = {**sources(), 'scheduler':sha(Path(__file__)), 'assessor':sha(REPO/'scripts/fixcl3_aud4_matrix.py'),
                     **{p.name:sha(p) for p in OUT.glob('FIXCL7-*.json')
                     if 'AUD4' not in p.name and p.name not in {state_path.name,'FIXCL7-cache-proof.json','FIXCL7-C7-cases.json'}}}
    if (not args.all and state.get('auditSources') == audit_bindings and audit.exists()
            and state.get('auditSha256') == sha(audit) and snapshot.exists()
            and state.get('snapshotSha256') == sha(snapshot)):
        print(json.dumps({'counts':json.loads(audit.read_bytes())['counts'],'audit':'current'}),flush=True)
        state_path.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8'); return
    for extra, dest in [([], snapshot), (['--snapshots',str(snapshot)],audit)]:
        code = run([sys.executable,str(REPO/'scripts/fixcl3_aud4_matrix.py'),'--port',str(PORTS.stop-1),'--wave','FIXCL7',
                    '--label','after','--output',str(dest),*extra],SCRATCH/('audit-'+dest.stem+'.log'))
        if code:
            print(json.dumps({'auditExitCode':code,'path':str(dest)}),flush=True)
            raise RuntimeError('Fresh audit generation failed; see audit log')
    if audit.exists():
        state.update(auditSources=audit_bindings,auditSha256=sha(audit),snapshotSha256=sha(snapshot))
        state_path.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'counts':json.loads(audit.read_bytes()).get('counts')}),flush=True)

if __name__ == '__main__': main()
