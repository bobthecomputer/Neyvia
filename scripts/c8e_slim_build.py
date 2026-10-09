"""Produce a signed slim installer using only existing local offline tools."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
import tarfile
import uuid
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe')
PUBLIC = {'src', 'scripts', 'config', 'manuals', 'plugins', 'native', 'sdk', 'src-tauri'}
TOP = {'pyproject.toml', 'package.json', 'package-lock.json'}
PRIVATE = re.compile(r'(?:credential|password|api[_-]?key|secret|nas_codex2_|nas_access_runbook)', re.I)
SKIP = {'.agent_control', '.agent_runs', 'node_modules', '.git', 'target', 'build', 'dist', 'evidence', '__pycache__'}
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
CLI_CACHE = ROOT / '.agent_control/proofs/C8/c8e-tauri'


class _RegistryOnly(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != 'registry.npmjs.org':
            raise PermissionError('Public Tauri download left the official npm registry')
        return super().redirect_request(request, fp, code, message, headers, url)


def acquire_cli(*, download=False):
    """Two exact lockfile-pinned public archives, without npm or install hooks."""
    lock = json.loads((ROOT / 'package-lock.json').read_text(encoding='utf-8'))['packages']
    client = build_opener(ProxyHandler({}), _RegistryOnly())
    rows = []
    for package in ('cli', 'cli-win32-x64-msvc'):
        pinned = lock['node_modules/@tauri-apps/' + package]
        url = pinned['resolved']
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'registry.npmjs.org' or parsed.username or parsed.password:
            raise PermissionError('Only exact official npm registry lockfile URLs are authorized')
        with client.open(Request(url, method='HEAD'), timeout=30) as response:
            declared = response.headers.get('Content-Length')
        metadata_url = 'https://registry.npmjs.org/@tauri-apps/' + package + '/' + pinned['version']
        with client.open(metadata_url, timeout=30) as response:
            metadata = json.load(response)['dist']
        if metadata['integrity'] != pinned['integrity'] or metadata['tarball'] != url:
            raise ValueError('Official package metadata differs from the maintained lockfile')
        size = int(declared) if declared is not None else metadata['unpackedSize'] + 1_048_576
        rows.append({'package': '@tauri-apps/' + package, 'version': pinned['version'],
                     'url': url, 'metadataUrl': metadata_url, 'declaredSize': int(declared) if declared else None,
                     'publishedUnpackedSize': metadata['unpackedSize'], 'sizeBound': size, 'integrity': pinned['integrity']})
    if rows[0]['version'] != '2.10.0' or any(row['version'] != rows[0]['version'] for row in rows):
        raise ValueError('This proof admits only maintained lockfile Tauri CLI 2.10.0')
    total = sum(row['sizeBound'] for row in rows)
    if total > 40_000_000 or total + 91_567_205 > 200_000_000:
        raise ValueError('Public Tauri archives exceed their 40 MB C8 allocation')
    result = {'schema': 'neyvia.c8e.tauri-acquisition/v1', 'files': rows, 'totalBytes': total,
              'taskDownloadBytesIncludingMiniLM': total + 91_567_205, 'allocation': 40_000_000,
              'authority': 'Public official npm registry, exact repository lockfile SHA512, no install scripts, cookies, credentials or global installation'}
    if not download:
        return result
    CLI_CACHE.mkdir(parents=True, exist_ok=True)
    for row in rows:
        archive = CLI_CACHE / (row['package'].split('/')[-1] + '.tgz')
        if archive.exists():
            content = archive.read_bytes()
        else:
            with client.open(Request(row['url']), timeout=60) as response:
                declared = response.headers.get('Content-Length')
                if declared is not None and int(declared) > row['sizeBound']:
                    raise ValueError('Registry archive changed its declared transfer size')
                chunks, size = [], 0
                while data := response.read(min(1024 * 1024, row['sizeBound'] - size + 1)):
                    size += len(data)
                    if size > row['sizeBound']:
                        raise ValueError('Registry transfer exceeded its pinned declared size')
                    chunks.append(data)
                content = b''.join(chunks)
        observed = 'sha512-' + base64.b64encode(hashlib.sha512(content).digest()).decode()
        if len(content) > row['sizeBound'] or observed != row['integrity']:
            raise ValueError('Public Tauri archive does not match maintained lockfile SHA512')
        if not archive.exists():
            with archive.open('xb') as stream:
                stream.write(content)
        row['sha256'] = hashlib.sha256(content).hexdigest()
        row['size'] = len(content)
        target = CLI_CACHE / 'node_modules' / row['package']
        if not target.exists():
            target.mkdir(parents=True)
            with tarfile.open(archive, 'r:gz') as package:
                members = package.getmembers()
                if sum(member.size for member in members) > 200_000_000:
                    raise ValueError('Public archive exceeds extraction boundary')
                for member in members:
                    parts = Path(member.name).parts
                    if not parts or parts[0] != 'package' or any(part in ('..', '.') for part in parts) or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                        raise ValueError('Unsafe public archive member')
                    destination = target.joinpath(*parts[1:]).resolve()
                    destination.relative_to(target.resolve())
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                    elif len(parts) > 1:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with package.extractfile(member) as source, destination.open('xb') as sink:
                            shutil.copyfileobj(source, sink)
    result['totalBytes'] = sum(row['size'] for row in rows)
    result['taskDownloadBytesIncludingMiniLM'] = result['totalBytes'] + 91_567_205
    (CLI_CACHE / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def _public_file(path):
    relative = path.relative_to(ROOT)
    if any(part in SKIP for part in relative.parts) or path.is_symlink() or path.is_junction():
        return False
    if relative.parts[0] == '.codex':
        return relative.parts[:2] == ('.codex', 'skills') and path.name == 'SKILL.md'
    if path.name.startswith('.env'):
        return False
    from grant_agent.proof_credential_guard import check_access
    try:
        check_access(path)
    except PermissionError:
        return False
    return path.suffix.lower() in {'.py', '.js', '.mjs', '.ts', '.rs', '.cl'} or not PRIVATE.search(path.name)


def _copy_public(candidate):
    records = []
    selected = [ROOT / name for name in sorted(PUBLIC | {'.codex/skills'})]
    for directory in selected:
        if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
            continue
        directory.resolve().relative_to(ROOT)
        for current, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP and not (Path(current) / name).is_symlink()
                       and not (Path(current) / name).is_junction()]
            for name in files:
                source = Path(current) / name
                if not _public_file(source):
                    continue
                source.resolve().relative_to(ROOT)
                destination = candidate / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                records.append({'path': source.relative_to(ROOT).as_posix(), 'size': source.stat().st_size,
                                'sha256': _hash(source)})
    for name in TOP:
        shutil.copyfile(ROOT / name, candidate / name)
        records.append({'path': name, 'size': (ROOT / name).stat().st_size, 'sha256': _hash(ROOT / name)})
    # Public runtime imports may use the broker seam. Never copy saved accounts.
    (candidate / 'config/neyvia_secret_broker.json').write_text(
        '{"stack":{},"policy":{},"accounts":[],"handles":[],"destinations":[]}\n', encoding='utf-8')
    return records


def _installed_copy(source, target):
    if not source.exists():
        raise FileNotFoundError('Installed offline build prerequisite missing: ' + str(source))
    try:
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '.bin', '*.pyc'))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    except PermissionError as error:
        raise PermissionError('Installed public artifact copy refused before reading: ' + str(source)) from error


def _cargo_cache(candidate, task):
    installed = Path('C:/Users/user/.cargo/registry')
    registry = task / 'cargo-home/registry'
    _installed_copy(installed / 'index', registry / 'index')
    packages = tomllib.loads((candidate / 'src-tauri/Cargo.lock').read_text(encoding='utf-8'))['package']
    index = 'index.crates.io-1949cf8c6b5b557f'
    copied, missing = [], []
    for package in packages:
        if not package.get('source', '').startswith('registry+'):
            continue
        filename = package['name'] + '-' + package['version'] + '.crate'
        source = installed / 'cache' / index / filename
        if PRIVATE.search(filename):
            # Cross-platform lockfiles can include e.g. Linux dbus-secret-service.
            # Keep the saved-credential guard intact and let the Windows offline
            # build decide whether this excluded package is actually required.
            missing.append(filename + ' (saved-credential filename guard)')
            continue
        if not source.is_file():
            missing.append(filename)
            continue
        if _hash(source) != package['checksum']:
            raise RuntimeError('Cached Cargo package does not match maintained lockfile: ' + filename)
        _installed_copy(source, registry / 'cache' / index / filename)
        copied.append({'file': filename, 'size': source.stat().st_size, 'sha256': package['checksum']})
    return {'copied': copied, 'missing': missing}


def _environment(task, candidate, port, *, reuse=False):
    environment = dict(os.environ)
    for name in ('TAURI_SIGNING_PRIVATE_KEY', 'TAURI_SIGNING_PRIVATE_KEY_PASSWORD', 'TAURI_PRIVATE_KEY', 'TAURI_KEY_PASSWORD'):
        environment.pop(name, None)
    local = task / 'localappdata'
    local.mkdir(exist_ok=reuse)
    if not (local / 'tauri/NSIS').exists():
        _installed_copy(Path(os.environ['LOCALAPPDATA']) / 'tauri/NSIS', local / 'tauri/NSIS')
    bootstrap = Path(os.environ['LOCALAPPDATA']) / 'tauri/MicrosoftEdgeWebview2Setup.exe'
    if not (local / 'tauri' / bootstrap.name).exists():
        _installed_copy(bootstrap, local / 'tauri' / bootstrap.name)
    for name in ('temp', 'profile', 'cache'):
        (task / name).mkdir(exist_ok=reuse)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(candidate / 'src'),
        NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
        FLUXIO_RUNTIME_AUTO_UPDATE='0', NEYVIA_PROOF_CREDENTIAL_GUARD='1', NEYVIA_SLIM_PROOF_SCOPE='C8',
        NEYVIA_C8_PROOF_ROOT=str(ROOT / '.agent_control/proofs/C8'), NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{port}',
        NEYVIA_WEB_BACKEND_URL=f'http://127.0.0.1:{port}', NEYVIA_OBSCURA_API=f'http://127.0.0.1:{port}',
        CARGO_HOME=str(task / 'cargo-home'), CARGO_TARGET_DIR=str(candidate / 'src-tauri/target'), CARGO_NET_OFFLINE='true',
        CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2', RUSTUP_TOOLCHAIN='stable-x86_64-pc-windows-msvc',
        LOCALAPPDATA=str(local), TEMP=str(task / 'temp'), TMP=str(task / 'temp'), HOME=str(task / 'profile'),
        XDG_CACHE_HOME=str(task / 'cache'), HTTP_PROXY=f'http://127.0.0.1:{port}', HTTPS_PROXY=f'http://127.0.0.1:{port}',
        ALL_PROXY=f'http://127.0.0.1:{port}', NO_PROXY='127.0.0.1,localhost', npm_config_offline='true')
    # Select the installed compiler environment in a hidden child. It prints
    # only its environment into memory, never into a receipt or operator shell.
    batch = Path('C:/Program Files/Microsoft Visual Studio/18/Insiders/VC/Auxiliary/Build/vcvars64.bat')
    loader = task / 'compiler-env.cmd'
    loader.write_text('@echo off\ncall "' + str(batch) + '" >nul\nif errorlevel 1 exit /b %errorlevel%\nset\n', encoding='utf-8')
    selected = subprocess.run(['cmd.exe', '/d', '/c', str(loader)], env=environment,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', **HIDDEN)
    if selected.returncode:
        raise RuntimeError('Installed vcvars64 environment failed: ' + selected.stderr[-1000:])
    for line in selected.stdout.splitlines():
        if '=' in line and not line.startswith('='):
            name, value = line.split('=', 1)
            environment[name] = value
    rust = Path('C:/Users/user/.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin')
    environment['PATH'] = str(rust) + os.pathsep + environment.get('Path', environment.get('PATH', ''))
    return environment


def run(task, *, port, frontend, warm_task=None, reuse=False):
    from c8_scope import assigned_ports
    if port not in assigned_ports():
        raise ValueError('C8 slim proof requires an explicitly assigned task port')
    task = Path(task).resolve()
    task.relative_to(ROOT / '.agent_control/proofs/C8')
    if not re.fullmatch(r'slim-[0-9a-f]{32}', task.name):
        raise ValueError('Use a fresh nonce-bound C8 slim scratch directory')
    if reuse:
        prior_receipt = json.loads((task / 'receipt.json').read_text(encoding='utf-8'))
        if prior_receipt.get('task') != str(task) or not prior_receipt.get('steps'):
            raise ValueError('Stable compiler reuse requires an actual retained own producer receipt')
        attempt = task / 'attempts' / uuid.uuid4().hex
        attempt.mkdir(parents=True)
    else:
        task.mkdir(exist_ok=False)
        attempt = task
    sys.path.insert(0, str(ROOT / 'src'))
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    from grant_agent.proof_credential_guard import install
    install(task)
    frontend = Path(frontend).resolve()
    frontend.relative_to(ROOT / '.agent_control/C8e')
    if not (frontend / 'index.html').is_file():
        raise FileNotFoundError('Existing verified C8e frontend build is required')
    candidate = task / 'candidate'
    candidate.mkdir(exist_ok=reuse)
    receipt = {'schema': 'neyvia.c8e.slim-build/v1', 'task': str(task), 'candidate': str(candidate),
               'port': port, 'authority': 'Only public copied source, synthetic empty broker, ephemeral task signer, installed offline tools; installer is never launched',
               'steps': [], 'passed': False, 'attemptPath': str(attempt),
               'receiptPath': str(attempt / 'receipt.json')}
    from c8_desktop_guard import DesktopGuard
    guard = DesktopGuard()
    guard.start()
    try:
        receipt['publicSource'] = _copy_public(candidate)
        if reuse:
            # Preserve the previous frontend bytes while giving Tauri exactly
            # the latest build, without stale hashed assets inflating the bundle.
            shutil.move(str(candidate / 'web/dist'), str(attempt / 'prior-frontend'))
            _installed_copy(frontend, candidate / 'web/dist')
            receipt['stableCompilerReuse'] = {'sourceReceipt': str(task / 'receipt.json'),
                'boundary': 'Refresh public source and verified frontend; rerun actual pack staging, signing, Cargo build and installer packaging on stable own compiler paths'}
        else:
            _installed_copy(frontend, candidate / 'web/dist')
        cli_receipt = CLI_CACHE / 'receipt.json'
        if not cli_receipt.is_file():
            raise FileNotFoundError('Pinned Tauri2 public archive acquisition must complete separately before offline build')
        receipt['cliAcquisition'] = json.loads(cli_receipt.read_text(encoding='utf-8'))
        if not reuse:
            _installed_copy(CLI_CACHE / 'node_modules/@tauri-apps', candidate / 'node_modules/@tauri-apps')
            receipt['cargoCache'] = _cargo_cache(candidate, task)
        else:
            receipt['cargoCache'] = prior_receipt['cargoCache']
        if warm_task:
            warm = Path(warm_task).resolve()
            warm.relative_to(ROOT / '.agent_control/proofs/C8')
            if not re.fullmatch(r'slim-[0-9a-f]{32}', warm.name) or warm == task:
                raise ValueError('Only an earlier own nonce-bound C8 build can warm compiler dependencies')
            previous = json.loads((warm / 'receipt.json').read_text(encoding='utf-8'))
            if previous['task'] != str(warm) or not previous.get('steps'):
                raise ValueError('Warm native outputs require an actual retained producer receipt')
            prior = warm / 'candidate/src-tauri/target/release'
            for directory in ('.fingerprint', 'deps', 'build'):
                if (prior / directory).is_dir():
                    _installed_copy(prior / directory, candidate / 'src-tauri/target/release' / directory)
            receipt['warmCompilerDependencies'] = {'sourceTask': str(warm),
                'boundary': 'Cargo revalidates copied dependency outputs; application executable and installer/bundle are excluded'}
        environment = _environment(task, candidate, port, reuse=reuse)
        config_path = candidate / 'src-tauri/tauri.slim.conf.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        config['build'].update(beforeBuildCommand=None, beforeDevCommand=None, frontendDist='../web/dist', devUrl=f'http://127.0.0.1:{port}')
        config_path.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        key = attempt / 'ephemeral-release.pem'
        key.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        suffix = '-' + attempt.name if reuse else ''
        runtime = candidate / ('src-tauri/target/portable-python' + suffix)
        output = candidate / ('src-tauri/target/slim-release' + suffix)
        commands = [
            [str(PYTHON), '-B', str(candidate / 'scripts/package_onboarding_packs.py')],
            [str(PYTHON), '-B', str(candidate / 'scripts/stage_portable_python.py'), '--output', str(runtime), '--allow-existing-versions'],
            [shutil.which('node'), str(candidate / 'scripts/prepare_slim_release.mjs'), '--output', str(output),
             '--python-runtime', str(runtime), '--secret-key', str(key), '--version', '0.2.1',
             '--base-url', f'http://127.0.0.1:{port}/c8-slim/base/manifest.json', '--allow-local-proof', '--build'],
        ]
        for number, command in enumerate(commands):
            started = time.monotonic()
            log = attempt / ('step-' + str(number) + '.log')
            with log.open('wb') as stream:
                process = subprocess.Popen(command, cwd=candidate, env=environment, stdout=stream,
                                           stderr=subprocess.STDOUT, **HIDDEN)
                import psutil
                birth = psutil.Process(process.pid).create_time()
                timed_out, tree_stopped = False, None
                try:
                    process.wait(timeout=2400)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    owned = psutil.Process(process.pid)
                    if owned.create_time() != birth:
                        raise RuntimeError('Producer PID changed identity; no cleanup against an unbound process')
                    stopped = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                             capture_output=True, timeout=15, **hidden_windows_subprocess_kwargs())
                    tree_stopped = stopped.returncode == 0
                    process.wait(timeout=15)
            receipt['steps'].append({'command': command, 'exitCode': process.returncode,
                                    'elapsedMs': round((time.monotonic() - started) * 1000),
                                    'pid': process.pid, 'creationTime': birth,
                                    'timedOut': timed_out, 'ownedProcessTreeStopped': tree_stopped,
                                    'log': str(log), 'sha256': _hash(log)})
            if process.returncode:
                raise RuntimeError('Actual slim producer failed at step ' + str(number) + ': ' + log.read_text(encoding='utf-8', errors='replace')[-3000:])
        actual = json.loads((output / 'release-receipt.json').read_text(encoding='utf-8'))
        if actual['build'].get('executed') is not True or not actual['build'].get('artifacts'):
            raise RuntimeError('Signed pack staging did not execute a real installer build')
        for artifact in actual['build']['artifacts']:
            path = candidate / artifact['path']
            if path.stat().st_size != artifact['size'] or _hash(path) != artifact['sha256']:
                raise RuntimeError('Installer archive differs from the actual producer hash receipt')
        verifier = attempt / 'verify-packages.mjs'
        verifier.write_text("""import {readFileSync,statSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,output]=process.argv.slice(2);
const {checkSignedEnvelope}=await import(pathToFileURL(join(repo,'scripts/release-contracts.mjs')));
const receipt=JSON.parse(readFileSync(join(output,'release-receipt.json')));
const manifestPaths=receipt.packs.map(pack=>join(repo,pack.manifest));
const localPaths=new Set(manifestPaths);
for(const directory of readdirSync(join(output,'external')))manifestPaths.push(join(output,'external',directory,'manifest.json'));
const proofs=[];
for(const path of manifestPaths){const bytes=readFileSync(path),manifest=JSON.parse(bytes);
checkSignedEnvelope(bytes,`pack=${manifest.packId} version=${manifest.version}`,receipt.publicKey,readFileSync(path+'.minisig','utf8'));
let count=0,total=0;
if(localPaths.has(path))for(const file of manifest.files){
const directory=resolve(path,'..','files'),target=resolve(directory,file.path),rel=relative(directory,target);
if(rel.startsWith('..')||isAbsolute(rel))throw Error('Pack file escapes its signed payload');
const payload=readFileSync(target);if(payload.length!==file.size||createHash('sha256').update(payload).digest('hex')!==file.sha256)throw Error('Signed pack payload hash mismatch');count++;total+=payload.length;}
proofs.push({packId:manifest.packId,signatureVerified:true,verifiedPayloadFiles:count,verifiedPayloadBytes:total});}
console.log(JSON.stringify({passed:true,packages:proofs}));
""", encoding='utf-8')
        checked = subprocess.run([shutil.which('node'), str(verifier), str(candidate), str(output)],
                                 cwd=candidate, env=environment, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=300, **HIDDEN)
        if checked.returncode:
            raise RuntimeError('Fresh signed package verification failed: ' + checked.stderr[-1500:])
        receipt['freshPackageVerification'] = json.loads(checked.stdout)
        receipt.update(passed=True, releaseReceipt=actual, releaseReceiptPath=str(output / 'release-receipt.json'))
    except Exception as error:
        receipt['blockedReason'] = str(error)
    receipt['desktopGuard'] = guard.finish()
    receipt['desktopGuard']['coverage'] = 'Started before any producer child; PID and creation-time attribution'
    if not receipt['desktopGuard']['passed']:
        receipt['passed'] = False
        receipt['blockedReason'] = 'Owned producer desktop attribution guard failed; actual artifact observations retained'
    (attempt / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int)
    parser.add_argument('--frontend')
    parser.add_argument('--task')
    parser.add_argument('--warm-task')
    parser.add_argument('--reuse-task')
    parser.add_argument('--inspect-cli', action='store_true')
    parser.add_argument('--acquire-cli', action='store_true')
    args = parser.parse_args()
    if args.inspect_cli or args.acquire_cli:
        print(json.dumps(acquire_cli(download=args.acquire_cli)), flush=True)
        raise SystemExit(0)
    if args.port is None or not args.frontend:
        parser.error('--port and --frontend are required for an actual offline build')
    if args.reuse_task and (args.task or args.warm_task):
        parser.error('--reuse-task cannot be combined with --task or --warm-task')
    task = args.reuse_task or args.task or ROOT / '.agent_control/proofs/C8' / ('slim-' + uuid.uuid4().hex)
    result = run(task, port=args.port, frontend=args.frontend, warm_task=args.warm_task, reuse=bool(args.reuse_task))
    print(json.dumps({key: result[key] for key in ('task', 'passed', 'blockedReason', 'releaseReceiptPath', 'receiptPath') if key in result}), flush=True)
    raise SystemExit(0 if result['passed'] else 2)
