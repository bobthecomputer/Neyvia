"""Real Windows terminals without AllocConsole or an input-desktop broker.

The ConPTY owner is a pinned Python process on a new private desktop. Control
and output use an authenticated local named pipe; no TCP ports are allocated.
"""
from __future__ import annotations

import codecs
import ctypes as C
from ctypes import wintypes as W
import hashlib
from multiprocessing.connection import Client, Listener
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import uuid


class _Coord(C.Structure):
    _fields_ = [('x', C.c_short), ('y', C.c_short)]


class _Console:
    def __init__(self, config):
        from grant_agent.cua_desktop import _STARTUPINFO, _PROCESSINFO
        self.k = k = C.WinDLL('kernel32', use_last_error=True)
        self.u = u = C.WinDLL('user32', use_last_error=True)
        u.GetThreadDesktop.argtypes = [W.DWORD]; u.GetThreadDesktop.restype = W.HANDLE
        u.GetUserObjectInformationW.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
        desktop = C.create_unicode_buffer(256); needed = W.DWORD()
        if not u.GetUserObjectInformationW(u.GetThreadDesktop(k.GetCurrentThreadId()), 2,
                desktop, C.sizeof(desktop), C.byref(needed)) or not desktop.value.startswith('Neyvia-C11-'):
            raise RuntimeError('ConPTY requires a private process desktop')
        self.desktop = desktop.value
        signatures = {
            'CreatePipe': ([C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD], W.BOOL),
            'CreatePseudoConsole': ([_Coord, W.HANDLE, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)], C.c_long),
            'ResizePseudoConsole': ([W.HANDLE, _Coord], C.c_long),
            'ClosePseudoConsole': ([W.HANDLE], None),
            'CloseHandle': ([W.HANDLE], W.BOOL),
            'ReadFile': ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            'WriteFile': ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            'InitializeProcThreadAttributeList': ([C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)], W.BOOL),
            'UpdateProcThreadAttribute': ([C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p], W.BOOL),
            'DeleteProcThreadAttributeList': ([C.c_void_p], None),
            'CreateProcessW': ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                C.c_void_p, W.LPCWSTR, C.c_void_p, C.POINTER(_PROCESSINFO)], W.BOOL),
            'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
            'GetExitCodeProcess': ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(k, name); fn.argtypes = args; fn.restype = result
        self.handles = [W.HANDLE() for _ in range(4)]
        self.console = W.HANDLE(); self.process = _PROCESSINFO()
        self.closed = False
        self._console_lock = threading.Lock()
        class StartupEx(C.Structure):
            _fields_ = [('startup', _STARTUPINFO), ('attributes', C.c_void_p)]
        attrs = None
        attributes_initialized = False
        try:
            for index in (0, 2):
                if not k.CreatePipe(C.byref(self.handles[index]), C.byref(self.handles[index + 1]), None, 0):
                    raise C.WinError(C.get_last_error())
            rows, cols = config['dimensions']
            hr = k.CreatePseudoConsole(_Coord(cols, rows), self.handles[0], self.handles[3], 0, C.byref(self.console))
            if hr < 0:
                raise RuntimeError('CreatePseudoConsole failed: ' + hex(hr & 0xffffffff))
            # ConPTY owns duplicates of its pipe ends; only our read/write ends remain.
            for index in (0, 3):
                k.CloseHandle(self.handles[index]); self.handles[index] = W.HANDLE()
            size = C.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
            attrs = C.create_string_buffer(size.value)
            if not k.InitializeProcThreadAttributeList(attrs, 1, 0, C.byref(size)):
                raise C.WinError(C.get_last_error())
            attributes_initialized = True
            # The pseudo-console attribute takes the HPCON value, not its address.
            if not k.UpdateProcThreadAttribute(attrs, 0, 0x00020016, self.console, C.sizeof(W.HANDLE), None, None):
                raise C.WinError(C.get_last_error())
            startup = StartupEx(); startup.startup.cb = C.sizeof(startup)
            startup.startup.lpDesktop = 'WinSta0\\' + self.desktop
            startup.attributes = C.cast(attrs, C.c_void_p)
            argv = config['argv']
            if Path(argv[0]).suffix.lower() in {'.cmd', '.bat'}:
                argv = [os.environ.get('COMSPEC', 'C:\\Windows\\System32\\cmd.exe'), '/d', '/s', '/c',
                    subprocess.list2cmdline(argv)]
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment = C.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(config['env'].items())) + '\0\0')
            if not k.CreateProcessW(None, command, None, None, False, 0x00080000 | 0x00000400,
                    environment, config['cwd'], C.byref(startup), C.byref(self.process)):
                raise C.WinError(C.get_last_error())
            k.CloseHandle(self.process.hThread); self.process.hThread = None
            self.pid = int(self.process.dwProcessId)
        except BaseException:
            self.close()
            raise
        finally:
            if attributes_initialized:
                k.DeleteProcThreadAttributeList(attrs)

    def read(self):
        buffer = C.create_string_buffer(16384); count = W.DWORD()
        if not self.k.ReadFile(self.handles[2], buffer, len(buffer), C.byref(count), None):
            if C.get_last_error() in (109, 232, 6):
                return b''
            raise C.WinError(C.get_last_error())
        return buffer.raw[:count.value]

    def write(self, text):
        data = text.encode('utf-8'); offset = 0
        while offset < len(data):
            count = W.DWORD()
            if not self.k.WriteFile(self.handles[1], data[offset:], len(data) - offset, C.byref(count), None):
                raise C.WinError(C.get_last_error())
            offset += count.value

    def resize(self, rows, cols):
        if self.k.ResizePseudoConsole(self.console, _Coord(cols, rows)) < 0:
            raise RuntimeError('ResizePseudoConsole failed')

    def exitstatus(self):
        if not self.process.hProcess or self.k.WaitForSingleObject(self.process.hProcess, 0) != 0:
            return None
        code = W.DWORD()
        if not self.k.GetExitCodeProcess(self.process.hProcess, C.byref(code)):
            raise C.WinError(C.get_last_error())
        return code.value

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.hProcess:
            if self.exitstatus() is None:
                self.k.TerminateProcess(self.process.hProcess, 1)
                self.k.WaitForSingleObject(self.process.hProcess, 3000)
            self.k.CloseHandle(self.process.hProcess); self.process.hProcess = None
        self.close_console()
        for handle in self.handles:
            if handle:
                self.k.CloseHandle(handle)

    def close_console(self):
        with self._console_lock:
            if self.console:
                # A draining reader stays active while ConPTY shuts down.
                self.k.ClosePseudoConsole(self.console); self.console = W.HANDLE()


def _worker(address, auth):
    connection = Client(address, family='AF_PIPE', authkey=bytes.fromhex(auth))
    console = None
    lock = threading.Lock()
    def send(value):
        with lock:
            connection.send(value)
    try:
        console = _Console(connection.recv())
        send({'kind': 'ready', 'pid': console.pid, 'desktop': console.desktop})
        def drain():
            decoder = codecs.getincrementaldecoder('utf-8')('replace')
            try:
                while True:
                    data = console.read()
                    if not data:
                        break
                    send({'kind': 'output', 'text': decoder.decode(data)})
            except (OSError, EOFError):
                pass
            finally:
                try:
                    send({'kind': 'eof', 'exitstatus': console.exitstatus()})
                except (OSError, EOFError):
                    pass
        threading.Thread(target=drain, daemon=True).start()
        def finish():
            console.k.WaitForSingleObject(console.process.hProcess, 0xffffffff)
            # Closing the pseudoconsole after its client exits makes the output
            # pipe reach EOF; the independent draining thread avoids deadlock.
            if console.console and not console.closed:
                console.close_console()
        threading.Thread(target=finish, daemon=True).start()
        while True:
            message = connection.recv()
            if message['op'] == 'write':
                console.write(message['text'])
            elif message['op'] == 'resize':
                console.resize(message['rows'], message['cols'])
            elif message['op'] == 'close':
                break
    except (EOFError, OSError):
        pass
    except Exception as exc:
        send({'kind': 'error', 'error': type(exc).__name__})
    finally:
        if console:
            console.close()
        connection.close()


class PrivateConPTY:
    """The small terminal interface consumed by panes and Claude's TUI reader."""
    @classmethod
    def spawn(cls, argv, cwd=None, env=None, dimensions=(24, 80)):
        from .cua_desktop import AgentDesktop
        from .local_network_policy import child_start
        if os.name != 'nt':
            raise RuntimeError('Private ConPTY requires Windows')
        if len(dimensions) != 2 or any(not isinstance(v, int) or not 0 < v <= 32767 for v in dimensions):
            raise ValueError('Positive ConPTY dimensions required')
        if not argv:
            raise ValueError('ConPTY requires a client command')
        if os.environ.get('NEYVIA_PROOF_CREDENTIAL_GUARD') == '1':
            from .proof_credential_guard import check_process
            check_process(argv)
        instance = cls()
        instance._condition = threading.Condition(); instance._send_lock = threading.Lock()
        instance._output = ''; instance._eof = False; instance.exitstatus = None
        instance.closed = False; instance._error = None
        area = Path(cwd or os.getcwd()).resolve() / '.agent_control/private-conpty' / uuid.uuid4().hex
        area.mkdir(parents=True)
        source_python = Path(sys.executable)
        if source_python.name.lower() == 'pythonw.exe':
            source_python = source_python.with_name('python.exe')
        executable = area / 'python.exe'; shutil.copy2(source_python, executable)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        auth = os.urandom(32)
        address = r'\\.\pipe\Neyvia-ConPTY-' + uuid.uuid4().hex
        listener = Listener(address, family='AF_PIPE', authkey=auth)
        accepted = queue.Queue()
        def accept():
            try:
                accepted.put(listener.accept())
            except BaseException as exc:
                accepted.put(exc)
        threading.Thread(target=accept, daemon=True).start()
        instance._desktop = AgentDesktop(profile_root=area)
        worker = [str(executable), str(Path(__file__).resolve()), '--worker', address, auth.hex()]
        instance._desktop.admit_pinned_console(worker, digest)
        try:
            # Resolve the actual installed Python home even inside a pinned host.
            python_home = Path(sys.base_prefix)
            with child_start():
                instance._host = instance._desktop.launch(worker, cwd=cwd, env={
                    'PYTHONHOME': str(python_home), 'PATH': str(python_home) + ';' + os.environ['PATH']})
            connection = accepted.get(timeout=10)
            if isinstance(connection, BaseException):
                raise connection
            instance._connection = connection
            connection.send({'argv': list(argv), 'cwd': str(Path(cwd or os.getcwd()).resolve()),
                'env': dict(env or os.environ), 'dimensions': dimensions})
            if not connection.poll(10):
                raise TimeoutError('Private ConPTY startup timed out')
            ready = connection.recv()
            if ready['kind'] != 'ready':
                raise RuntimeError('Private ConPTY startup failed: ' + ready.get('error', 'no ready receipt'))
            instance.pid = ready['pid']; instance.desktop = ready['desktop']
            threading.Thread(target=instance._receive, daemon=True).start()
            return instance
        except BaseException:
            instance.terminate(force=True)
            raise
        finally:
            listener.close()

    def _receive(self):
        try:
            while True:
                message = self._connection.recv()
                with self._condition:
                    if message['kind'] == 'output':
                        # Keep a stalled consumer bounded while preserving terminal
                        # bytes: pipe backpressure pauses the producer, without loss.
                        self._condition.wait_for(lambda: len(self._output) < 1024 * 1024 or self.closed)
                        if self.closed:
                            return
                        self._output += message['text']
                    elif message['kind'] == 'eof':
                        self._eof = True; self.exitstatus = message['exitstatus']
                    elif message['kind'] == 'error':
                        self._error = message['error']; self._eof = True
                    self._condition.notify_all()
                if self._eof:
                    return
        except (EOFError, OSError):
            with self._condition:
                self._eof = True; self._condition.notify_all()

    def read(self, size=4096):
        with self._condition:
            self._condition.wait_for(lambda: self._output or self._eof or self.closed)
            if not self._output:
                if self._error:
                    raise OSError('Private ConPTY worker failed: ' + self._error)
                raise EOFError()
            result, self._output = self._output[:size], self._output[size:]
            self._condition.notify_all()
            return result

    def _send(self, message):
        with self._send_lock:
            if self.closed:
                raise OSError('Private ConPTY is closed')
            self._connection.send(message)

    def write(self, text):
        self._send({'op': 'write', 'text': text})
        return len(text)

    def setwinsize(self, rows, cols):
        if not 0 < rows <= 32767 or not 0 < cols <= 32767:
            raise ValueError('Positive ConPTY dimensions required')
        self._send({'op': 'resize', 'rows': rows, 'cols': cols})

    def isalive(self):
        return not self.closed and not self._eof and self._host.poll() is None

    def terminate(self, force=False):
        if self.closed:
            return True
        if hasattr(self, '_connection'):
            try:
                self._send({'op': 'close'})
                self._host.wait(3)
            except (OSError, EOFError, subprocess.TimeoutExpired):
                pass
            self._connection.close()
        self.closed = True
        self._desktop.close()
        with self._condition:
            self._eof = True; self._condition.notify_all()
        return True

    close = terminate


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        raise SystemExit('Private ConPTY worker requires its local pipe')
    _worker(sys.argv[2], sys.argv[3])
