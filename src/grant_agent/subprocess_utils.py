from __future__ import annotations

import functools
import os
import subprocess
import signal
from pathlib import Path
from typing import Any


def capture_bounded_process(args, *, cwd, env, input_text, timeout):
    """Capture a bounded executor, including partial output after a timeout.

    Stop the owned process tree before draining pipes. Never include the command
    (which can contain private instructions) in an exception or recovery record.
    A stopped process does not imply that its external side effects were undone.
    """
    process = subprocess.Popen(
        args, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", start_new_session=os.name != "nt",
        **hidden_windows_subprocess_kwargs(new_process_group=True),
    )
    timed_out = False
    tree_stopped = None
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        def decoded(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        stdout, stderr = decoded(exc.stdout), decoded(exc.stderr)
        try:
            if os.name == "nt":
                stopped = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, timeout=10, check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
                tree_stopped = stopped.returncode == 0
            else:
                os.killpg(process.pid, signal.SIGKILL)
                tree_stopped = True
        except (OSError, subprocess.TimeoutExpired):
            tree_stopped = False
        if process.poll() is None:
            process.kill()
        try:
            # communicate returns the complete captured stream, not just a tail.
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            tree_stopped = False
            for pipe in (process.stdout, process.stderr):
                if pipe:
                    pipe.close()
    return {"stdout": stdout, "stderr": stderr, "returncode": process.poll(),
            "timedOut": timed_out, "processTreeStopped": tree_stopped}


def stable_working_path(path: str | os.PathLike[str]) -> Path:
    """Return an absolute cwd without replacing a Windows mapped drive by UNC.

    ``Path.resolve()`` expands mapped NAS drives such as ``Y:`` into a UNC path.
    Windows ``cmd.exe`` cannot use a UNC current directory and silently falls back
    to the Windows directory, so shell-based package commands then run in the
    wrong project.  Drive-letter paths are already unambiguous and should remain
    drive-letter paths; other platforms keep their canonical resolved behavior.
    """

    candidate = Path(path).expanduser()
    if os.name == "nt" and candidate.drive and not str(candidate).startswith("\\\\"):
        return candidate.absolute()
    return candidate.resolve()


def hidden_windows_subprocess_kwargs(
    *,
    new_process_group: bool = False,
) -> dict[str, Any]:
    if os.name != "nt":
        from .proofs_e_wz import check_hidden_kwargs
        check_hidden_kwargs({}, False, new_process_group)
        return {}

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    payload: dict[str, Any] = {"creationflags": flags}
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        startupinfo = startupinfo_type()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        payload["startupinfo"] = startupinfo
    from .proofs_e_wz import check_hidden_kwargs
    check_hidden_kwargs(payload, True, new_process_group)
    return payload


def background_creationflags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )


# ``creationflags`` is the 14th positional Popen parameter (after ``self``).
_POPEN_CREATIONFLAGS_POSITION = 13
_HIDDEN_DEFAULT_MARKER = "_neyvia_hidden_default"


def _hidden_popen_init(original, no_window: int):
    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        original_kwargs = dict(kwargs)
        if len(args) <= _POPEN_CREATIONFLAGS_POSITION and not kwargs.get("creationflags"):
            kwargs["creationflags"] = no_window
        from .proofs_e_wz import check_spawn_flags
        check_spawn_flags(args, original_kwargs, args, kwargs, no_window)
        original(self, *args, **kwargs)

    setattr(__init__, _HIDDEN_DEFAULT_MARKER, True)
    return __init__


def install_hidden_subprocess_default() -> bool:
    """Make ``subprocess.Popen`` start console children without a window on Windows.

    A backend without a console (pythonw, a detached or service launch) makes
    every console child it starts, such as git.exe or wsl.exe, open a visible
    console window. This is the safety net behind ``hidden_windows_subprocess_kwargs``:
    it wraps ``Popen.__init__`` to add ``CREATE_NO_WINDOW`` only when the caller
    passed no creationflags, so explicit flags (CREATE_NEW_CONSOLE for a login
    terminal, DETACHED_PROCESS) are never overridden. ``run``, ``check_output``
    and asyncio subprocesses go through ``Popen`` and are covered too. Calling it
    again is a no-op, and it does nothing off Windows. Returns True when the
    default is active.
    """
    from .proofs_e_wz import check_hidden_install
    original = subprocess.Popen.__init__
    if os.name != "nt":
        check_hidden_install(original, subprocess.Popen.__init__, False, False)
        return False
    if getattr(original, _HIDDEN_DEFAULT_MARKER, False):
        check_hidden_install(original, subprocess.Popen.__init__, True, True)
        return True
    subprocess.Popen.__init__ = _hidden_popen_init(
        original, getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    check_hidden_install(original, subprocess.Popen.__init__, True, True)
    return True



def split_process_command(command: str) -> list[str]:
    """Decode the platform command line produced by shell_join/list2cmdline."""
    import shlex
    if not command.strip():
        return []
    if os.name != "nt":
        return shlex.split(command)
    import ctypes
    from ctypes import wintypes
    argc = ctypes.c_int()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    parse = shell32.CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv = parse(command, ctypes.byref(argc))
    if not argv:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(argv)


def windows_pid_alive(pid: int) -> bool | None:
    """Check Windows process state without depending on tasklist permissions."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        process_query_limited_information = 0x1000
        still_active = 259
        handle = open_process(process_query_limited_information, False, int(pid))
        if not handle:
            error = ctypes.get_last_error()
            if error == 5:  # Access denied still proves that the PID exists.
                return True
            if error == 87:  # Invalid parameter means there is no such PID.
                return False
            return None
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return None
            return exit_code.value == still_active
        finally:
            close_handle(handle)
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return None



def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return windows_pid_alive(pid) is True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True
