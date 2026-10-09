"""Process-local socket boundary for owned C8 services and journey workers."""
import sys
import socket
from pathlib import Path
import os


def assigned_ports():
    raw = os.environ.get('NEYVIA_C8_PORTS', '')
    if not raw:
        raise ValueError('C8 requires an explicit NEYVIA_C8_PORTS assignment')
    ports = {int(p) for p in raw.split(',')}
    if not ports or any(not 48871 <= p <= 48889 for p in ports):
        raise ValueError('C8 requires explicitly assigned ports in 48871-48889')
    return ports


def fixture_ports(exclude=()):
    """Return only task-declared, currently free fixture sockets."""
    excluded = {int(p) for p in exclude}
    excluded.update(int(p) for p in os.environ.get('NEYVIA_C8_RESERVED_PORTS', '').split(',') if p)
    available = []
    for port in sorted(assigned_ports() - excluded):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) != 0:
                available.append(port)
    return available


def fixture_port(exclude=()):
    ports = fixture_ports(exclude)
    if not ports:
        raise RuntimeError('No free explicitly assigned C8 fixture port remains')
    return ports[0]


def run_root(repo):
    return Path(os.environ.get('NEYVIA_C8_RUN_ROOT', Path(repo) / '.agent_control/proofs/C8')).resolve()


def install(*, allow_children=True, writable_root=None, headless_driver_source=None):
    ports = assigned_ports()
    writable_root = Path(writable_root).resolve() if writable_root else None
    driver_paths = None
    import os
    if os.name == 'nt':
        import subprocess
        original_init = subprocess.Popen.__init__
        def hidden_init(self, *args, **kwargs):
            import shutil
            command = args[0] if args else kwargs.get('args')
            if isinstance(command, (list, tuple)) and command and command[0] in {'git', 'node', 'powershell', 'taskkill'}:
                installed_tool = shutil.which(command[0])
                if installed_tool:
                    pinned = [str(Path(installed_tool).resolve()), *command[1:]]
                    if args:
                        args = (pinned, *args[1:])
                    else:
                        kwargs['args'] = pinned
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            original_init(self, *args, **kwargs)
        # Also cover admitted original host proofs, whose legacy subprocess
        # helpers do not all supply Windows flags themselves.
        subprocess.Popen.__init__ = hidden_init
    if headless_driver_source:
        import importlib.util
        import subprocess
        package = Path(importlib.util.find_spec('playwright').origin).parent
        driver_paths = ((package / 'driver/node.exe').resolve(), (package / 'driver/package/cli.js').resolve())
        headless_driver_source = str(Path(headless_driver_source).resolve())

    def vector(args):
        command = args[1]
        if isinstance(command, (list, tuple)):
            return command
        if isinstance(command, str):
            import ctypes
            count = ctypes.c_int()
            parse = ctypes.windll.shell32.CommandLineToArgvW
            parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
            parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
            values = parse(command, ctypes.byref(count))
            if not values:
                return []
            try:
                return [values[index] for index in range(count.value)]
            finally:
                ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
                ctypes.windll.kernel32.LocalFree(ctypes.cast(values, ctypes.c_void_p))
        return []

    def admitted_driver(args):
        if not driver_paths or len(args) < 2:
            return False
        command = vector(args)
        if len(command) != 3 or Path(command[0]).resolve() != driver_paths[0] or Path(command[1]).resolve() != driver_paths[1] or command[2] != 'run-driver':
            return False
        # Playwright starts its driver on an asyncio/greenlet stack, so the
        # caller stack cannot confer authority. c8_headless separately refuses
        # headed launches and fences every browser context to its own origin.
        return True

    def admitted_helper(args):
        if not headless_driver_source or len(args) < 2:
            return False
        command = vector(args)
        if not command:
            return False
        executable = Path(command[0]).resolve()
        source = Path(headless_driver_source).parent
        if admitted_capacity_worker(args, command, executable, source):
            return True
        if executable == Path(sys.executable).resolve():
            if (len(command) == 5 and command[1] == '-B'
                    and Path(command[2]).resolve() == source.parents[1] / 'scripts/c8e_extra_effects.py'
                    and command[3] == '--nightshift-command'
                    and Path(command[4]).resolve() == writable_root / 'c8/command.txt'
                    and args[2] and Path(args[2]).resolve() == writable_root):
                return True
            if (len(command) == 6 and Path(command[1]).resolve() == source.parents[1] / 'scripts/c8e_onboarding.py'
                    and command[2] == '--root' and Path(command[3]).resolve() == writable_root
                    and command[4] == '--pack-id' and command[5] in {'base', 'pack.creator-sdk'}):
                return True
            if command[1:] == ['-c', 'import pypdf']:
                return True
            if len(command) == 2 and Path(command[1]).resolve() == source / 'pdf_document_worker.py':
                return True
            if len(command) == 3 and Path(command[1]).resolve() == source / 'research.py' and command[2] == '--search-worker':
                return True
            fixed = "from pathlib import Path; Path('manual-terminal-proof.txt').write_text('manual terminal returned 739', encoding='utf-8')"
            probes = {"import runpy; runpy.run_path('scripts/c8e_bug_checks.py')['run']('" + mode + "', '.')"
                      for mode in ('host-runtime', 'nearby-send-runtime', 'neyvia-core', 'runtime-provider')}
            probes.add("from pathlib import Path; Path('runtime-child.txt').write_text('C8e actual hidden child output', encoding='utf-8')")
            probes.add("import runpy; runpy.run_path('scripts/c8e_extra_effects.py')['nightshift_command']('c8/command.txt')")
            probes.update("import runpy; runpy.run_path('scripts/c8e_design_checks.py')['run']('" + mode + "', '.')"
                          for mode in ('build', 'craft', 'details-lab', 'details-shell', 'details-kit'))
            if command[1:] in (['-c', fixed], *(['-c', value] for value in probes)):
                return bool(args[2]) and Path(args[2]).resolve() == writable_root
            if (len(command) in {7, 8} and Path(command[1]).resolve() == source.parents[1] / 'scripts/verify_proofs.py'
                    and command[2:4] == ['--worker', '--root'] and Path(command[4]).resolve() == writable_root
                    and command[5] == '--area' and command[6] in {'proofs-e-models', 'proofs-e-shell', 'proofs-e-chat', 'proofs-b-engine', 'proofs-b-harness'}
                    and (len(command) == 7 or command[7] == '--skip-manuals')):
                return True
            if (len(command) >= 10 and (len(command) - 8) % 2 == 0
                    and Path(command[1]).resolve() == source.parents[1] / 'scripts/verify_proofs.py'
                    and command[2:4] == ['--worker', '--root'] and Path(command[4]).resolve() == writable_root
                    and command[5:8] == ['--area', 'proofs-b-adapters', '--skip-manuals']
                    and all(command[index] == '--adapter-chapter' for index in range(8, len(command), 2))
                    and len(set(command[9::2])) == len(command[9::2])
                    and set(command[9::2]) <= {'git', 'handoff', 'html', 'ocr', 'publication', 'sync', 'release'}):
                return True
            return False
        if executable == writable_root / 'c8/obscura.exe':
            terminal_port = os.environ.get('NEYVIA_C8_TERMINAL_PORT', '')
            return bool(terminal_port) and command[1:] == ['serve', '--host', '127.0.0.1', '--port', terminal_port, '--user-agent',
                    'NeyviaAgent/1.0 (Automation; Obscura)', '--max-connections', '8', '--allow-private-network']
        import shutil
        import re
        git = shutil.which('git')
        if (git and executable == Path(git).resolve() and len(command) == 5
                and command[1:4] == ['rev-parse', '--verify', '--end-of-options']
                and re.fullmatch(r'[0-9a-f]{40}\^\{commit\}', command[4])
                and args[2] and Path(args[2]).resolve().is_relative_to(writable_root / '.agent_control/proofs')
                and Path(args[2]).resolve().parts[-2:] == ('git', 'repository')):
            return True
        if (git and executable == Path(git).resolve() and len(command) == 4
                and command[1:3] == ['rev-parse', '--verify']
                and re.fullmatch(r'[0-9a-f]{40}\^\{commit\}', command[3])
                and args[2] and Path(args[2]).resolve().is_relative_to(writable_root / '.agent_control/proofs')
                and Path(args[2]).resolve().parts[-2:] == ('git', 'repository')):
            return True
        ffmpeg = shutil.which('ffmpeg')
        if (ffmpeg and executable == Path(ffmpeg).resolve() and len(command) == 14
                and command[1:8] == ['-nostdin', '-hide_banner', '-loglevel', 'error',
                                     '-protocol_whitelist', 'file,pipe', '-i']
                and Path(command[8]).resolve() == writable_root / 'c8/known-video.mp4'
                and command[9] == '-vf'
                and re.fullmatch(r'select=eq\(n\\,[0-9]{1,6}\),scale=1600:1600:force_original_aspect_ratio=decrease', command[10])
                and command[11:13] == ['-frames:v', '1']
                and Path(command[13]).resolve().is_relative_to(writable_root / '.neyvia/perception-video')
                and Path(command[13]).name == 'frame.png'):
            return True
        rg = shutil.which('rg')
        if rg and executable == Path(rg).resolve() and '--json' in command and '--no-config' in command and '--' in command:
            files = command[command.index('--') + 2:]
            return bool(files) and all(Path(value).resolve().is_relative_to(writable_root) for value in files)
        node = shutil.which('node')
        if node and executable == Path(node).resolve() and len(command) == 3:
            return (Path(command[1]).resolve() == source.parents[1] / 'scripts/c8e_verify_slim.mjs'
                    and Path(command[2]).resolve().is_relative_to(source.parents[1] / '.agent_control/proofs/C8')
                    and Path(command[2]).name == 'receipt.json')
        if node and executable == Path(node).resolve() and len(command) == 9:
            return (Path(command[1]).resolve() == (source.parents[1] / 'node_modules/vite/bin/vite.js').resolve()
                    and command[2:4] == ['build', '--config'] and Path(command[4]).resolve() == writable_root / '.agent_control/c8e-build.config.mjs'
                    and command[5:8] == ['--configLoader', 'runner', '--outDir']
                    and Path(command[8]).resolve() == writable_root / '.agent_control/build-check'
                    and args[2] and Path(args[2]).resolve() == source.parents[1])
        if (executable == (source.parents[1] / 'node_modules/@esbuild/win32-x64/esbuild.exe').resolve()
                and len(command) == 5 and Path(command[1]).resolve().is_relative_to(writable_root)
                and command[2] in {'--loader:.css=css', '--loader:.jsx=jsx'}
                and command[3:] == ['--log-level=error', '--color=false']):
            return True
        if node and executable == Path(node).resolve() and len(command) == 4:
            return (Path(command[1]).resolve() == source.parents[1] / 'scripts/gamedev/validate-asset.cjs'
                    and Path(command[2]).resolve().is_relative_to(writable_root) and Path(command[3]).resolve() == writable_root)
        return False

    def admitted_capacity_worker(args, command, executable, source):
        """Only one original, fenced capacity worker and its owned cleanup."""
        import hashlib
        import json
        import re
        import shutil
        from datetime import datetime
        fixture = writable_root / 'c8/browser-capacity-fixture.json'
        if not fixture.is_file():
            return False
        helper = source.parents[1] / 'scripts/c8e_browser_checks.py'
        fence = writable_root / 'c8/harness-fence/sitecustomize.py'
        fence_text = ('import os\ntry:\n'
                      ' from c8e_browser_checks import install_capacity_worker\n'
                      ' install_capacity_worker()\n'
                      'except BaseException:\n os._exit(73)\n')
        try:
            marker = json.loads(fixture.read_text(encoding='utf-8'))
            if (marker.get('schema') != 'neyvia.c8e.capacity-fixture.v1'
                    or marker.get('root') != str(writable_root)
                    or marker.get('helperSha256') != hashlib.sha256(helper.read_bytes()).hexdigest()
                    or marker.get('fenceSha256') != hashlib.sha256(fence_text.encode()).hexdigest()
                    or fence.read_text(encoding='utf-8') != fence_text):
                return False
            worker = source / 'harness_job_worker.py'

            def owned_job(job):
                return (job.get('schema') == 'neyvia.harness_job.v1'
                        and re.fullmatch(r'harness-job-[a-z0-9_-]{1,88}', job.get('id', ''))
                        and job.get('request', {}).get('c8eCapacityOnly') is True
                        and job['request'].get('exactRoute') is True
                        and job['request'].get('allowRuntimeFallback') is False
                        and Path(job.get('workspacePath', '')).resolve() == writable_root)

            if (executable == Path(sys.executable).resolve() and len(command) == 6
                    and Path(command[1]).resolve() == worker and command[2] == '--root'
                    and Path(command[3]).resolve() == writable_root and command[4] == '--job-id'
                    and re.fullmatch(r'harness-job-[a-z0-9_-]{1,88}', command[5])
                    and args[2] and Path(args[2]).resolve() == writable_root):
                job = json.loads((writable_root / '.agent_control/harness_jobs' / (command[5] + '.json')).read_text(encoding='utf-8'))
                environment = args[3] if len(args) > 3 else None
                pythonpath = str(environment.get('PYTHONPATH', '')).split(os.pathsep) if isinstance(environment, dict) else []
                paths = {Path(value).resolve() for value in pythonpath if value}
                return (owned_job(job) and job['id'] == command[5] and job.get('status') == 'queued'
                        and fence.parent in paths and paths <= {fence.parent, source.parents[0], source.parents[1] / 'scripts'})

            powershell = shutil.which('powershell')
            taskkill = shutil.which('taskkill')
            query = (powershell and executable == Path(powershell).resolve() and len(command) == 5
                     and command[1:4] == ['-NoProfile', '-NonInteractive', '-Command'])
            kill = (taskkill and executable == Path(taskkill).resolve() and len(command) == 5
                    and command[1] == '/PID' and command[3:] == ['/T', '/F'])
            match = re.fullmatch(r"\(Get-CimInstance Win32_Process -Filter 'ProcessId = ([0-9]+)'\)\.CommandLine", command[4]) if query else None
            pid = int(match[1]) if match else int(command[2]) if kill and command[2].isdigit() else None
            if pid is None:
                return False
            import psutil
            process = psutil.Process(pid)
            actual = process.cmdline()
            for path in (writable_root / '.agent_control/harness_jobs').glob('harness-job-*.json'):
                job = json.loads(path.read_text(encoding='utf-8'))
                if not owned_job(job) or job.get('pid') != pid:
                    continue
                expected = [str(Path(sys.executable).resolve()), str(worker), '--root', str(writable_root), '--job-id', job['id']]
                recorded = job.get('workerCommand')
                if not isinstance(recorded, list) or len(actual) != 6 or len(recorded) != 6:
                    continue
                def normalized(vector):
                    return [str(Path(value).resolve()) if index in {0, 1, 3} else value for index, value in enumerate(vector)]
                started = datetime.fromisoformat(job['startedAt'].replace('Z', '+00:00')).timestamp()
                if (normalized(actual) == expected and normalized(recorded) == expected
                        and Path(process.cwd()).resolve() == writable_root
                        and abs(process.create_time() - started) < 5):
                    return True
        except Exception:
            # Missing/malformed receipts, inaccessible processes and PID exit
            # races all deny authority; no cleanup target is guessed.
            return False
        return False
    socket_source = str(Path(socket.__file__).resolve())
    def private_socketpair():
        # Windows asyncio uses the standard library's private socketpair for
        # wakeups. It is not a service and is closed by the event loop.
        frame = sys._getframe(1)
        while frame:
            if frame.f_code.co_name in {"socketpair", "_fallback_socketpair"} and str(Path(frame.f_code.co_filename).resolve()) == socket_source:
                return True
            frame = frame.f_back
        return False
    def audit(event, args):
        # A general manual can name a home folder or absolute export path.
        # The product remains unchanged; this task's disposable backend
        # refuses mutations escaping the particular journey's state root.
        if writable_root:
            writes = []
            if event == 'open' and args and isinstance(args[0], (str, bytes)):
                mode = args[1] if len(args) > 1 else None
                flags = args[2] if len(args) > 2 else 0
                if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & 0x703):
                    writes = [args[0]]
            elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate'}:
                writes = [args[0]]
            elif event in {'os.rename', 'os.link', 'os.symlink'}:
                writes = list(args[:2])
            for value in writes:
                if isinstance(value, (str, bytes)):
                    if event == 'open' and str(value).upper() in {'NUL', 'B\'NUL\''}:
                        continue  # Windows null device creates no file or child.
                    target = Path(value.decode() if isinstance(value, bytes) else value).resolve()
                    if not target.is_relative_to(writable_root):
                        raise PermissionError('C8 disposable filesystem scope refuses mutation outside journey state')
        if not allow_children and event in {"subprocess.Popen", "os.system", "os.startfile", "os.startfile/2", "os.spawn"} and not (event == 'subprocess.Popen' and (admitted_driver(args) or admitted_helper(args))):
            raise PermissionError("C8 headless backend scope does not grant child-process or desktop launches")
        if event in {"socket.connect", "socket.bind"} and len(args) > 1 and isinstance(args[1], tuple):
            host, port = args[1][:2]
            if host in {"127.0.0.1", "localhost", "::1"} and private_socketpair():
                return
            if host not in {"127.0.0.1", "localhost", "::1"} or int(port) not in ports:
                raise PermissionError("C8 socket scope permits only assigned loopback ports")
        if event == "socket.getaddrinfo" and args and args[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise PermissionError("C8 does not resolve external hosts")
    sys.addaudithook(audit)
