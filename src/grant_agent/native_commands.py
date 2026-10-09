"""Bounded execution and discovery for local native commands."""

from __future__ import annotations

import codecs
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs


DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 120_000
DEFAULT_OUTPUT_CHARS = 12_000
MAX_OUTPUT_CHARS = 50_000
MIN_OUTPUT_CHARS = 128
_READ_CHUNK = 8192


def _resolve_executable(shell: str) -> str:
    if shell == "python":
        executable = str(Path(sys.executable).resolve())
    elif shell == "powershell":
        candidates = ("pwsh", "powershell") if os.name == "nt" else ("pwsh",)
        executable = None
        for candidate in candidates:
            executable = shutil.which(candidate)
            if executable:
                break
    elif shell == "cmd":
        executable = shutil.which("cmd.exe") or shutil.which("cmd") if os.name == "nt" else None
    elif shell == "bash":
        executable = shutil.which("bash")
    else:
        raise ValueError(f"Unsupported command shell: {shell}")
    if not executable:
        raise RuntimeError(f"The requested shell '{shell}' is not available on this system.")
    return str(Path(executable).resolve())


def _select_shell(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.name == "nt":
        for candidate in ("pwsh", "powershell"):
            if shutil.which(candidate):
                return "powershell"
        raise RuntimeError("No PowerShell executable is available for shell='auto'.")
    if shutil.which("bash"):
        return "bash"
    raise RuntimeError("No Bash executable is available for shell='auto'.")


def _build_argv(shell: str, executable: str, command: str) -> list[str]:
    if shell == "python":
        return [executable, "-c", command]
    if shell == "powershell":
        utf8_setup = "$utf8 = New-Object System.Text.UTF8Encoding($false); [Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
        return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", utf8_setup + command]
    if shell == "bash":
        return [executable, "--noprofile", "--norc", "-c", command]
    if shell == "cmd":
        return [executable, "/d", "/s", "/c", command]
    raise ValueError(f"Unsupported command shell: {shell}")


def _read_bounded(stream, limit: int, sink: dict[str, Any], key: str) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    kept: list[str] = []
    kept_chars = 0
    overflow = False
    try:
        while True:
            data = stream.read(_READ_CHUNK)
            if not data:
                break
            decoded = decoder.decode(data)
            if decoded:
                room = limit - kept_chars
                if room > 0:
                    kept.append(decoded[:room])
                    kept_chars += min(len(decoded), room)
                if len(decoded) > room:
                    overflow = True
        tail = decoder.decode(b"", final=True)
        if tail:
            room = limit - kept_chars
            if room > 0:
                kept.append(tail[:room])
                kept_chars += min(len(tail), room)
            if len(tail) > room:
                overflow = True
    finally:
        try:
            stream.close()
        except OSError:
            pass
    sink[key] = "".join(kept)
    sink[f"{key}Truncated"] = overflow


def _repair_utf16_misdecode(text: str) -> str:
    """Undo UTF-16 output read as UTF-8 (every other character a NUL).

    Some Windows tools ignore the console code page. Their ASCII text then
    arrives with a NUL after every letter, which neither people nor models can read.
    """
    nulls = text.count(chr(0))
    if not nulls or nulls < len(text) // 5:
        return text
    return text.replace(chr(0xFEFF), "").replace(chr(0), "")


def _stop_process_tree(process: subprocess.Popen[bytes]) -> bool:
    try:
        if os.name == "nt":
            stopped = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            tree_stopped = stopped.returncode == 0
        else:
            os.killpg(process.pid, signal.SIGKILL)
            tree_stopped = True
    except (OSError, subprocess.TimeoutExpired):
        tree_stopped = False
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    return tree_stopped


def execute_local_command(arguments: dict[str, Any], *, default_cwd: str | Path) -> dict[str, Any]:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    requested_shell = arguments.get("shell", "auto")
    if requested_shell not in {"auto", "powershell", "python", "bash", "cmd"}:
        raise ValueError("shell must be auto, powershell, python, bash, or cmd")
    shell = _select_shell(requested_shell)

    cwd_value = arguments.get("cwd") or str(default_cwd)
    cwd = Path(str(cwd_value)).expanduser()
    if not cwd.is_absolute():
        cwd = Path(default_cwd) / cwd
    cwd = cwd.resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("cwd must identify an existing directory")

    timeout_ms = arguments.get("timeoutMs", DEFAULT_TIMEOUT_MS)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise ValueError(f"timeoutMs must be an integer between 1 and {MAX_TIMEOUT_MS}")
    max_output_chars = arguments.get("maxOutputChars", DEFAULT_OUTPUT_CHARS)
    if isinstance(max_output_chars, bool) or not isinstance(max_output_chars, int) or not MIN_OUTPUT_CHARS <= max_output_chars <= MAX_OUTPUT_CHARS:
        raise ValueError(f"maxOutputChars must be an integer between {MIN_OUTPUT_CHARS} and {MAX_OUTPUT_CHARS}")

    executable = _resolve_executable(shell)
    argv = _build_argv(shell, executable, command)
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    # wsl.exe writes UTF-16 to pipes unless asked for UTF-8.
    child_env["WSL_UTF8"] = "1"
    captures: dict[str, Any] = {}
    started = time.perf_counter()
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        bufsize=0,
        start_new_session=os.name != "nt",
        **hidden_windows_subprocess_kwargs(new_process_group=True),
    )
    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=_read_bounded, args=(process.stdout, max_output_chars, captures, "stdout"), daemon=True),
        threading.Thread(target=_read_bounded, args=(process.stderr, max_output_chars, captures, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    tree_stopped: bool | None = None
    try:
        process.wait(timeout=timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        timed_out = True
        tree_stopped = _stop_process_tree(process)
    except BaseException:
        _stop_process_tree(process)
        raise
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for reader in readers:
            reader.join(timeout=5)
    capture_incomplete = any(reader.is_alive() for reader in readers)
    if capture_incomplete:
        _stop_process_tree(process)
        for reader in readers:
            reader.join(timeout=1)

    duration_ms = max(1, int((time.perf_counter() - started) * 1000))
    stdout = _repair_utf16_misdecode(str(captures.get("stdout", "")))
    stderr = _repair_utf16_misdecode(str(captures.get("stderr", "")))
    output_was_truncated = bool(captures.get("stdoutTruncated") or captures.get("stderrTruncated"))
    if len(stdout) + len(stderr) > max_output_chars:
        output_was_truncated = True
        stdout_budget = max_output_chars // 2
        stderr_budget = max_output_chars - stdout_budget
        stdout = stdout[:stdout_budget]
        stderr = stderr[:stderr_budget]
        remaining = max_output_chars - len(stdout) - len(stderr)
        if remaining and len(stdout) < max_output_chars:
            extra = min(remaining, max_output_chars - len(stdout))
            stdout = stdout + str(captures.get("stdout", ""))[len(stdout):len(stdout) + extra]
            remaining -= extra
        if remaining and len(stderr) < max_output_chars:
            stderr = stderr + str(captures.get("stderr", ""))[len(stderr):len(stderr) + remaining]
    exit_code = process.returncode
    ok = not timed_out and not capture_incomplete and exit_code == 0
    if timed_out:
        status = "timed_out"
    elif capture_incomplete:
        status = "capture_incomplete"
    elif ok:
        status = "completed"
    else:
        status = "failed"
    if timed_out:
        error = f"Command timed out after {timeout_ms} ms."
    elif capture_incomplete:
        error = "Command output capture was incomplete."
    elif exit_code != 0:
        error = f"Command exited with code {exit_code}."
    else:
        error = ""
    return {
        "ok": ok,
        "status": status,
        "error": error,
        "shell": shell,
        "command": command,
        "resolvedExecutable": executable,
        "cwd": str(cwd),
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "durationMs": duration_ms,
        "truncated": output_was_truncated,
        "stdoutTruncated": bool(captures.get("stdoutTruncated") or len(stdout) < len(str(captures.get("stdout", "")))),
        "stderrTruncated": bool(captures.get("stderrTruncated") or len(stderr) < len(str(captures.get("stderr", "")))),
        "timedOut": timed_out,
        "processTreeStopped": tree_stopped,
        "captureIncomplete": capture_incomplete,
    }


def _available(name: str) -> str | None:
    return shutil.which(name)


def inspect_local_environment(*, default_cwd: str | Path) -> dict[str, Any]:
    shells: dict[str, str | None] = {
        "powershell": _available("pwsh") or _available("powershell"),
        "cmd": (_available("cmd.exe") or _available("cmd")) if os.name == "nt" else None,
        "bash": _available("bash"),
    }
    return {
        "ok": True,
        "status": "observed",
        "operatingSystem": platform.system(),
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "workspaceRoot": str(Path(default_cwd).resolve()),
        "python": {"executable": str(Path(sys.executable).resolve()), "version": platform.python_version()},
        "executables": {
            "node": _available("node"),
            "git": _available("git"),
            "python": str(Path(sys.executable).resolve()),
            "shells": shells,
        },
        "environmentValuesIncluded": False,
    }
