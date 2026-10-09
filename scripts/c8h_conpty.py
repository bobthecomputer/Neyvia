"""Bounded ConPTY desktop diagnostic; never switches desktops or shows UI."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
LOG = Path(r'C:\Users\user\Projects\plans\logs\window-guard.jsonl')


def windows(extra_desktop=None, owned_pids=()):
    u = C.WinDLL('user32', use_last_error=True)
    k = C.WinDLL('kernel32', use_last_error=True)
    u.GetThreadDesktop.argtypes = [W.DWORD]; u.GetThreadDesktop.restype = W.HANDLE
    u.OpenInputDesktop.argtypes = [W.DWORD, W.BOOL, W.DWORD]; u.OpenInputDesktop.restype = W.HANDLE
    u.GetUserObjectInformationW.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    u.IsWindowVisible.argtypes = [W.HWND]
    u.CloseDesktop.argtypes = [W.HANDLE]
    u.OpenDesktopW.argtypes = [W.LPCWSTR, W.DWORD, W.BOOL, W.DWORD]; u.OpenDesktopW.restype = W.HANDLE
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    u.EnumDesktopWindows.argtypes = [W.HANDLE, callback_type, W.LPARAM]
    def name(handle):
        buffer = C.create_unicode_buffer(256); needed = W.DWORD()
        if not u.GetUserObjectInformationW(handle, 2, buffer, C.sizeof(buffer), C.byref(needed)):
            raise C.WinError(C.get_last_error())
        return buffer.value
    current = u.GetThreadDesktop(k.GetCurrentThreadId())
    input_desktop = u.OpenInputDesktop(0, False, 0x41)
    if not input_desktop:
        raise C.WinError(C.get_last_error())
    result = {'pid': os.getpid(), 'threadDesktop': name(current), 'inputDesktop': name(input_desktop), 'windows': []}
    extra = u.OpenDesktopW(extra_desktop, 0, False, 0x41) if extra_desktop else None
    try:
        seen = set()
        for handle in (current, input_desktop, extra):
            if not handle:
                continue
            desktop_name = name(handle)
            if desktop_name in seen:
                continue
            seen.add(desktop_name)
            @callback_type
            def callback(hwnd, _):
                pid = W.DWORD(); u.GetWindowThreadProcessId(hwnd, C.byref(pid))
                cls = C.create_unicode_buffer(256); u.GetClassNameW(hwnd, cls, len(cls))
                if pid.value == os.getpid() or pid.value in owned_pids or cls.value == 'PseudoConsoleWindow':
                    result['windows'].append({'hwnd': int(hwnd), 'pid': pid.value, 'class': cls.value,
                        'desktop': desktop_name, 'visible': bool(u.IsWindowVisible(hwnd))})
                return True
            C.set_last_error(0)
            if not u.EnumDesktopWindows(handle, callback, 0) and C.get_last_error():
                raise C.WinError(C.get_last_error())
    finally:
        u.CloseDesktop(input_desktop)
        if extra:
            u.CloseDesktop(extra)
    return result


def contract():
    """Executable CL contract: actual ConPTY IO, desktop HWNDs and refusal."""
    import threading
    from grant_agent.private_conpty import PrivateConPTY, _Console
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    root = ROOT / '.agent_control/proofs/C8/c8h-conpty-contract' / uuid.uuid4().hex
    root.mkdir(parents=True)
    before = LOG.read_bytes()
    guard = ZeroDisturbanceGuard().start()
    terminal = None
    result = {'schema': 'neyvia.c8h.conpty-contract.v1', 'passed': False}
    chunks = []; ready = threading.Event(); replied = threading.Event()
    try:
        script = "import ctypes,os; ctypes.windll.kernel32.GetConsoleWindow(); print('C8H_READY',flush=True); s=input(); print('C8H_REPLY:'+s,flush=True); z=os.get_terminal_size(); print('C8H_SIZE:'+str(z.columns)+'x'+str(z.lines),flush=True); input()"
        terminal = PrivateConPTY.spawn([sys.executable, '-u', '-c', script], cwd=str(root), env=dict(os.environ))
        guard.register_pid(terminal.pid)
        result['pid'] = terminal.pid; result['desktop'] = terminal.desktop
        def read():
            try:
                while True:
                    chunks.append(terminal.read())
                    text = ''.join(chunks)
                    if 'C8H_READY' in text:
                        ready.set()
                    if 'C8H_REPLY:real-conpty-739' in text and 'C8H_SIZE:111x33' in text:
                        replied.set()
            except (EOFError, OSError):
                pass
        reader = threading.Thread(target=read, daemon=True); reader.start()
        if not ready.wait(10):
            raise RuntimeError('Actual ConPTY client did not become ready')
        terminal.setwinsize(33, 111)
        terminal.write('real-conpty-739\r')
        if not replied.wait(10):
            raise RuntimeError('Actual ConPTY client did not echo the input')
        result['observation'] = windows(terminal.desktop)
        result['inputEscapes'] = [w for w in result['observation']['windows'] if
            w['pid'] in (terminal.pid, terminal._host.pid) and w['desktop'] == result['observation']['inputDesktop']]
        result['output'] = ''.join(chunks)
        result['resizeObserved'] = 'C8H_SIZE:111x33' in result['output']
        try:
            _Console({})
        except RuntimeError as exc:
            result['inputDesktopRefused'] = str(exc) == 'ConPTY requires a private process desktop'
        else:
            raise RuntimeError('Input-desktop ConPTY owner was admitted')
        terminal.terminate(force=True); reader.join(3)
        result['ownedProcessStopped'] = terminal.closed
        # The escaped caller used a Windows venv redirector, not the ConPTY
        # API itself. Exercise the production launcher with that same process
        # boundary and a harmless disposable program, without loading ASR.
        import venv
        from grant_agent.neyvia_dictation import _spawn
        from grant_agent.local_network_policy import stop_child
        engine = root / 'engine'; engine.mkdir()
        marker = engine / 'launch.json'
        (engine / 'phonon2_engine.py').write_text("import ctypes,json,os,time\nfrom pathlib import Path\nk=ctypes.WinDLL('kernel32');k.GetConsoleWindow.restype=ctypes.c_void_p\nPath('launch.json').write_text(json.dumps({'pid':os.getpid(),'console':k.GetConsoleWindow() or 0}))\ntime.sleep(30)\n")
        venv.EnvBuilder(with_pip=False).create(root / 'venv')
        previous_ports = os.environ.get('NEYVIA_PROOF_ALLOWED_PORTS')
        from c8_scope import fixture_port
        terminal_port = fixture_port()
        os.environ['NEYVIA_PROOF_ALLOWED_PORTS'] = '[' + str(terminal_port) + ']'
        launched = None
        try:
            launched = _spawn(root, engine, root / 'venv/Scripts/python.exe', {'port': terminal_port, 'device': 'cpu'})
            if launched is None:
                raise RuntimeError('Disposable venv launch did not return its owned process')
            guard.register_pid(launched.pid)
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            actual = json.loads(marker.read_text())
            result['dictationLauncher'] = {'actualChild': actual, 'redirectorPid': launched.pid,
                'secondStartSuppressed': _spawn(root, engine, root / 'venv/Scripts/python.exe', {'port': terminal_port, 'device': 'cpu'}) is None,
                'boundary': 'Production launcher and real Windows venv redirector; disposable console observation, no ASR/model/service proof'}
            if actual['console'] != 0 or not result['dictationLauncher']['secondStartSuppressed']:
                raise RuntimeError('Venv launcher allocated a console or admitted a duplicate start')
        finally:
            if launched:
                result['dictationLauncherStopped'] = stop_child(launched)
            if previous_ports is None:
                os.environ.pop('NEYVIA_PROOF_ALLOWED_PORTS', None)
            else:
                os.environ['NEYVIA_PROOF_ALLOWED_PORTS'] = previous_ports
        result['passed'] = bool(ready.is_set() and replied.is_set() and not result['inputEscapes']
            and result['inputDesktopRefused'] and result['ownedProcessStopped'] and result['dictationLauncherStopped'])
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if terminal:
            terminal.terminate(force=True)
        result['guard'] = guard.close()
        result['guardLogUnchanged'] = before == LOG.read_bytes()
        result['passed'] = result['passed'] and result['guard']['ok'] and result['guardLogUnchanged']
        result['sourceSha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            'src/grant_agent/private_conpty.py', 'src/grant_agent/neyvia_dictation.py', 'scripts/c8h_conpty.py')}
        Path('conpty-contract.json').write_text(json.dumps(result, indent=2) + '\n')
    if not result['passed']:
        raise RuntimeError(result.get('error', 'ConPTY containment contract failed'))
    return result


def raw_probe():
    k = C.WinDLL('kernel32', use_last_error=True)
    class Coord(C.Structure):
        _fields_ = [('x', C.c_short), ('y', C.c_short)]
    k.CreatePipe.argtypes = [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD]
    k.CreatePseudoConsole.argtypes = [Coord, W.HANDLE, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    k.CreatePseudoConsole.restype = C.c_long
    k.ClosePseudoConsole.argtypes = [W.HANDLE]
    k.CloseHandle.argtypes = [W.HANDLE]
    handles = [W.HANDLE() for _ in range(4)]
    console = W.HANDLE()
    before = windows()
    try:
        for start in (0, 2):
            if not k.CreatePipe(C.byref(handles[start]), C.byref(handles[start + 1]), None, 0):
                raise C.WinError(C.get_last_error())
        hr = k.CreatePseudoConsole(Coord(80, 24), handles[0], handles[3], 0, C.byref(console))
        if hr < 0:
            raise RuntimeError('CreatePseudoConsole HRESULT ' + hex(hr & 0xffffffff))
        time.sleep(.1)
        during = windows()
        baseline = {w['hwnd'] for w in before['windows']}
        return {'api': 'kernel32.CreatePseudoConsole', 'before': before, 'during': during,
                'newWindows': [w for w in during['windows'] if w['hwnd'] not in baseline]}
    finally:
        if console:
            k.ClosePseudoConsole(console)
        for handle in handles:
            if handle:
                k.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--private-child', action='store_true')
    args = parser.parse_args()
    output = args.receipt.resolve()
    if not output.is_relative_to(ROOT / 'scripts/evidence'):
        parser.error('Task-local evidence required')
    if args.private_child:
        output.write_text(json.dumps(raw_probe(), indent=2) + '\n')
        return 0
    from grant_agent.cua_desktop import AgentDesktop
    area = ROOT / '.agent_control/proofs/C8/c8h-conpty' / uuid.uuid4().hex
    area.mkdir(parents=True)
    executable = area / 'python.exe'
    shutil.copy2(sys.executable, executable)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    child_receipt = output.with_name(output.stem + '-private.json')
    argv = [str(executable), str(Path(__file__).resolve()), '--private-child', '--receipt', str(child_receipt)]
    before = LOG.read_bytes()
    result = {'schema': 'neyvia.c8h.conpty-diagnostic.v1', 'input': raw_probe()}
    with AgentDesktop(profile_root=area) as desktop:
        desktop.admit_pinned_console(argv, digest)
        proc = desktop.launch(argv, cwd=ROOT, env={'PYTHONHOME': str(Path(sys.executable).parent),
            'PATH': str(Path(sys.executable).parent) + ';' + os.environ['PATH']})
        result['privateExitCode'] = proc.wait(10)
        result['private'] = json.loads(child_receipt.read_text())
    result['guardLogUnchanged'] = LOG.read_bytes() == before
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('privateExitCode', 'guardLogUnchanged')}))
    return 0 if result['privateExitCode'] == 0 and result['guardLogUnchanged'] else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        if '--private-child' in sys.argv:
            Path(sys.argv[sys.argv.index('--receipt') + 1]).write_text(json.dumps({'error': traceback.format_exc()}))
        raise
