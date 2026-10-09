"""Fresh pinned-environment identity and declared task output byte witnesses."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from .record_effects import _files, _identity, _json, _path, _sources
from .effects import _measure_file

SUPPORTED = {'environment.create', 'environment.run'}


def _store(protocol):
    from ..shared_environments import SharedEnvironmentStore
    return SharedEnvironmentStore(protocol.gateway.root)


def _probe(python):
    from ..subprocess_utils import hidden_windows_subprocess_kwargs
    result = subprocess.run([str(python), '-c', "import json,sys; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'basePrefix':sys.base_prefix,'version':sys.version,'implementation':sys.implementation.name}))"],
        capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
    if result.returncode != 0:
        raise ValueError('Fresh environment interpreter observation failed')
    return json.loads(result.stdout)


def _output_paths(protocol, args):
    rows = args.get('outputs')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('CL environment execution requires declared fresh output file hashes')
    paths = {}
    for row in rows:
        path = _path(protocol, row['path'])
        if path == Path(protocol.gateway.root).resolve() or '.agent_control' in path.relative_to(protocol.gateway.root).parts:
            raise ValueError('Task outputs must be outside environment and protocol control state')
        digest = row['sha256'].lower()
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or str(path) in paths:
            raise ValueError('Unique task output paths and SHA256 hashes are required')
        paths[str(path)] = digest
    return paths


def _manifest(protocol, args):
    store = _store(protocol)
    path = _path(protocol, args['manifestPath'])
    path.relative_to(store.base)
    _measure_file(path.parent)
    return store, path, store._load(path)


def _script(protocol, args):
    argv = args.get('args')
    if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or any(not isinstance(v, str) or len(v) > 4096 for v in argv):
        raise ValueError('Bounded interpreter arguments are required')
    if argv[0].startswith('-'):
        raise ValueError('CL environment execution requires a saved scoped Python script; inline code and modules remain frontier')
    path = _path(protocol, argv[0])
    if path.suffix.lower() != '.py' or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError('CL environment execution requires a bounded existing Python source file')
    return {'path': str(path), 'sha256': _measure_file(path)['sha256']}


def snapshot_for(protocol, name, args):
    store = _store(protocol)
    if name == 'environment.create':
        lock = _path(protocol, args['lockPath'])
        if not lock.is_file() or lock.stat().st_size > 1_000_000:
            raise ValueError('Environment lock must be a bounded scoped file')
        directory = _path(protocol, store.base / _identity(args['environmentId']))
        _measure_file(directory)
        manifests = {str(p): _measure_file(_path(protocol, p)) for p in directory.glob('*/manifest.json')}
        return {'lock': _measure_file(lock), 'manifests': manifests}
    store, path, manifest = _manifest(protocol, args)
    output_paths = _output_paths(protocol, args)
    return {'manifest': manifest, 'manifestFile': _measure_file(path),
            'interpreter': _measure_file(_path(protocol, manifest['python'])),
            'script': _script(protocol, args), 'files': _files(protocol, path.parent),
            'outputs': {p: _measure_file(_path(protocol, p)) for p in output_paths}, 'outputHashes': output_paths}


def _create(protocol, args, value, before):
    from ..shared_environments import _hash
    store = _store(protocol)
    reported = value.get('environment')
    if not isinstance(reported, dict) or reported.get('reused') is not False:
        return False
    path = _path(protocol, reported['manifestPath'])
    path.relative_to(store.base / _identity(args['environmentId']))
    _measure_file(path.parent)
    manifest = store._load(path)
    if str(path) in before['manifests'] or {k: v for k, v in reported.items() if k != 'reused'} != manifest:
        return False
    if _measure_file(_path(protocol, args['lockPath'])) != before['lock'] or manifest['lockSha256'] != before['lock']['sha256']:
        return False
    if _measure_file(_path(protocol, path.parent / 'requirements.lock'))['sha256'] != before['lock']['sha256']:
        return False
    if manifest['environmentId'] != args['environmentId'] or value.get('artifacts') != [str(path)]:
        return False
    source = _probe(sys.executable)
    interpreter = {'executable': source['executable'], 'version': source['version'], 'implementation': source['implementation']}
    import platform
    expected_fp = _hash({'lockSha256': before['lock']['sha256'], 'interpreter': interpreter, 'platform': platform.platform()})
    if manifest['interpreter'] != interpreter or manifest['fingerprint'] != expected_fp or path.parent.name != expected_fp:
        return False
    fresh = _probe(manifest['python'])
    return (Path(fresh['prefix']).resolve() == (path.parent / 'venv').resolve() and
            Path(fresh['executable']).resolve() == Path(manifest['python']).resolve() and
            fresh['basePrefix'] == source['basePrefix'] and fresh['version'] == source['version'])


def _run(protocol, args, value, before):
    from ..shared_environments import _hash
    store, manifest_path, manifest = _manifest(protocol, args)
    if manifest != before['manifest'] or _measure_file(manifest_path) != before['manifestFile']:
        return False
    if _measure_file(_path(protocol, manifest['python'])) != before['interpreter'] or _script(protocol, args) != before['script']:
        return False
    if any(row.get('exists') for row in before['outputs'].values()):
        return False  # An old matching file cannot witness a new process effect.
    for path, expected in before['outputHashes'].items():
        fresh = _measure_file(_path(protocol, path))
        if fresh.get('kind') != 'file' or fresh.get('sha256') != expected:
            return False
    path = _path(protocol, value.get('receiptPath', ''))
    if path.parent != manifest_path.parent or not path.name.startswith('run-') or path.suffix != '.json':
        return False
    receipt = _json(protocol, path)
    if value != {**receipt, 'ok': receipt.get('exitCode') == 0, 'artifacts': [str(path)]}:
        return False
    expected = {'arguments': args['args'], 'command': [manifest['python'], *args['args']], 'script': before['script'],
        'interpreterSha256': before['interpreter']['sha256'], 'declaredOutputs': args['outputs'],
        'fingerprint': manifest['fingerprint'], 'python': manifest['python'], 'status': 'completed', 'exitCode': 0}
    if any(receipt.get(k) != v for k, v in expected.items()):
        return False
    request = {'manifestPath': str(manifest_path), 'fingerprint': manifest['fingerprint'], 'arguments': args['args'],
        'script': before['script'], 'interpreterSha256': before['interpreter']['sha256'], 'declaredOutputs': args['outputs']}
    return (receipt.get('requestHash') == _hash(request) and str(path) not in before['files'] and
            _files(protocol, path.parent) == {**before['files'], str(path): _measure_file(path)})


def checks_for(protocol, name, args):
    if name not in SUPPORTED or name == 'environment.run' and not args.get('outputs'):
        return []
    def verify(arguments, value, before):
        if not isinstance(value, dict) or not isinstance(before, dict):
            return False
        try:
            return (_create if name == 'environment.create' else _run)(protocol, arguments, value, before)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return False
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
        'subjectKey': name + ':' + str(args.get('environmentId') or args.get('manifestPath')),
        'observerTool': 'fresh-interpreter-and-output-bytes', 'subject': {'environment': args.get('environmentId') or args.get('manifestPath')},
        'expectation': 'Fresh pinned interpreter identity or exact declared newly written task bytes from the argv-bound saved script', 'check': verify}]
