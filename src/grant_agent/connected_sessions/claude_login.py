"""Claude Code's own sign-in, finished from any device.

``claude auth login`` prints a claude.com link and waits at "Paste code here". This keeps that
process running on the PC (one at a time, for up to 15 minutes), returns the link, and later
writes the code the user pasted to its input, exactly as a terminal would. The code is passed
through once and never logged or stored; tokens stay in Claude Code's own credential store.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..subprocess_utils import hidden_windows_subprocess_kwargs
from .claude_stream import ClaudeSessionError
from ..proofs_a_providers import checked

LOGIN_TTL_SECONDS = 15 * 60
START_TIMEOUT_SECONDS = 25
FINISH_TIMEOUT_SECONDS = 45
PROMPT = "Paste code here"
_URL = re.compile(r"https://claude\.(?:com|ai)/\S*oauth\S*")
_CODE = re.compile(r"^[A-Za-z0-9._~#=-]{10,512}$")


# Refusals carry a code the broker turns into its error responses.
LoginError = ClaudeSessionError


class CliLogin:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._out: list[str] = []
        self._started = 0.0

    def _pump(self, proc: subprocess.Popen, out: list[str]) -> None:
        stream = proc.stdout
        while stream is not None:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
            if not chunk:
                return
            out.append(chunk.decode("utf-8", "replace"))
            if sum(len(part) for part in out) > 64 * 1024:
                del out[:-8]

    def _stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
        self._proc = None

    def start(self, cli: list[str], cwd: Path, env: dict[str, str]) -> str:
        """Start a fresh sign-in and return its link."""
        with self._lock:
            self._stop()
            out: list[str] = []
            try:
                proc = subprocess.Popen([*cli, "auth", "login"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, cwd=str(cwd), env=env, **hidden_windows_subprocess_kwargs())
            except OSError as exc:
                raise LoginError("sign_in_failed", "Claude Code's sign-in couldn't start.") from exc
            threading.Thread(target=self._pump, args=(proc, out), name="claude-login", daemon=True).start()
            deadline = time.monotonic() + START_TIMEOUT_SECONDS
            while time.monotonic() < deadline and proc.poll() is None:
                text = "".join(out)
                found = _URL.search(text)
                if found and PROMPT in text:
                    self._proc, self._out, self._started = proc, out, time.monotonic()
                    return found.group(0)
                time.sleep(0.1)
            if proc.poll() is None:
                proc.kill()
            raise LoginError("sign_in_failed", "Claude Code's sign-in didn't show a link. Try again.")

    @checked("providers.claude.login")
    def finish(self, code: Any) -> str:
        """Hand the pasted code to the waiting sign-in; returns Claude Code's short failure note, or ""."""
        value = str(code or "").strip()
        if not _CODE.fullmatch(value):
            raise LoginError("invalid_code", "That doesn't look like the code from Claude's page. Copy the whole code.")
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None or time.monotonic() - self._started > LOGIN_TTL_SECONDS:
                self._stop()
                raise LoginError("sign_in_expired", "That sign-in has ended. Start it again.")
            mark = len("".join(self._out))
            try:
                assert proc.stdin is not None
                proc.stdin.write((value + "\r\n").encode("utf-8"))
                proc.stdin.flush()
            except OSError as exc:
                self._stop()
                raise LoginError("sign_in_expired", "That sign-in has ended. Start it again.") from exc
            try:
                proc.wait(FINISH_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            reply = "".join(self._out)[mark:]
            ok = proc.poll() == 0
            self._stop()
        if ok:
            return ""
        note = next((line.strip() for line in reply.splitlines() if "fail" in line.lower() or "error" in line.lower()), "")
        return note.replace(value, "")[:160]
