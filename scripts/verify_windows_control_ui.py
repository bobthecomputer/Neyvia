"""Cross-platform process/HTTP helpers for browser-proof verification scripts.

Historically this module hosted the Windows control-UI verification flow; the
capture scripts (verify_real_agent_conversation_proof.py) still import these
process-management helpers from here, so they are kept as a small, dependency
free utility module that works on Windows and POSIX hosts.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.subprocess_utils import background_creationflags, hidden_windows_subprocess_kwargs


def process_group_flags() -> int:
    """Popen creationflags that put the child in its own process group.

    On Windows this allows the whole tree to be stopped with taskkill; on
    POSIX creationflags are unused, so return 0.
    """
    if sys.platform == "win32":
        return background_creationflags()
    return 0


def stop_process_tree(process: subprocess.Popen | None, *, timeout: float = 10.0) -> None:
    """Terminate a Popen child and its descendants without raising."""
    if process is None or process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        # Best effort cleanup; never let teardown mask the real verification result.
        try:
            process.kill()
        except (OSError, subprocess.SubprocessError):
            pass


def wait_for_http(url: str, timeout: float = 30.0, *, interval: float = 0.5) -> int:
    """Poll a URL until it answers with any HTTP status; return the status code.

    Raises TimeoutError with the last failure detail if the deadline passes.
    """
    deadline = time.monotonic() + max(0.1, timeout)
    last_error: str = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=min(10.0, timeout)) as response:
                return int(response.status or 0)
        except urllib.error.HTTPError as exc:
            # The server is up; a 4xx/5xx still proves reachability.
            return int(exc.code)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(max(0.05, interval))
    raise TimeoutError(f"HTTP endpoint {url} did not answer within {timeout} seconds: {last_error}")
