"""Read only the newly owned Character Map field during the lead's Claude arm."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import time
import psutil
from c1_comparison_checker import load, safe_path, observe_fixture, check_fixture


class VisibleReadback:
    def __init__(self, fixture):
        self.fixture = fixture
        self.binding = fixture['runtime']
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        self.user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM,
            W.UINT, W.UINT, C.POINTER(C.c_size_t)]
        self.user.SendMessageTimeoutW.restype = W.LPARAM
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        self.user.EnumChildWindows.argtypes = [W.HWND, self.callback, W.LPARAM]

    def request(self, operation, args):
        if operation != 'inspect' or int(args['windowId']) != self.binding['hwnd']:
            raise ValueError('Read-only target binding differs')
        process = psutil.Process(self.binding['pid'])
        if process.create_time() != self.binding['processBirth'] or process.name().lower() != 'charmap.exe':
            raise ValueError('Owned process birth or application changed')
        owner = W.DWORD()
        self.user.GetWindowThreadProcessId(self.binding['hwnd'], C.byref(owner))
        if owner.value != process.pid:
            raise ValueError('Target window owner changed')
        fields = []
        @self.callback
        def visit(hwnd, _):
            cls = C.create_unicode_buffer(128)
            self.user.GetClassNameW(hwnd, cls, len(cls))
            if cls.value == 'Edit' or cls.value.lower().startswith('richedit'):
                pid = W.DWORD()
                self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
                if pid.value == process.pid:
                    fields.append(int(hwnd))
            return True
        self.user.EnumChildWindows(self.binding['hwnd'], visit, 0)
        if len(fields) != 1:
            raise ValueError('Character Map field missing or ambiguous')
        text = C.create_unicode_buffer(4096)
        result = C.c_size_t()
        if not self.user.SendMessageTimeoutW(fields[0], 0xD, len(text), C.cast(text, C.c_void_p).value,
                2, 500, C.byref(result)):
            raise ValueError('Fresh Character Map read timed out')
        return {'tree': [{'id': 'owned-field', 'role': 'Edit', 'value': text.value}],
            'revision': time.time_ns()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--hwnd', type=int, required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    fixture = load(args.fixture)
    if fixture['id'] != 'charmap-compose' or fixture['arm'] != 'claude_computer_use':
        raise ValueError('This read-only adapter belongs to Claude Character Map only')
    process = psutil.Process(args.pid)
    # Require a launch since the fixture was prepared. Existing user processes
    # cannot be adopted as disposable comparison targets.
    if process.create_time() < safe_path(fixture['manifest']).stat().st_mtime:
        raise ValueError('Process predates fresh fixture')
    fixture['runtime'] = {'hwnd': args.hwnd, 'pid': args.pid, 'processBirth': process.create_time()}
    reader = VisibleReadback(fixture)
    binding = {'worker': reader, 'windowId': args.hwnd, 'selector': {'id': 'owned-field', 'role': 'Edit'}}
    deadline = time.monotonic() + fixture['timeBudgetSeconds']
    while True:
        observe_fixture(fixture, runtime=binding)
        if not args.watch or time.monotonic() >= deadline:
            break
        time.sleep(.05)
    result = check_fixture(fixture)
    print(json.dumps(result))
    raise SystemExit(0 if result['ok'] else 1)
