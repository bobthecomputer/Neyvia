"""Dictation providers: where the speech is turned into words while Paul talks.

local   Phonon-2 on this PC (default, offline). Handled by neyvia_dictation itself.
openai  OpenAI Realtime transcription over a WebSocket with an OpenAI API key (streaming deltas).
codex   Codex app-server's experimental ``thread/realtime`` voice session, signed in with ChatGPT.

Cloud providers share one small contract: ``feed(pcm16k)`` as audio arrives, ``snapshot()`` for the
words so far ({partial, stable, provisional, hypothesis_seq}) and ``finish()`` for the final text.
``stable`` holds only completed segments; deltas of a segment still being heard are provisional.
Neyvia's prompt policy (neyvia_dictation.stream) is the same for every provider.
No ChatGPT/Codex login token is read or forwarded here: the Codex route only talks to the
official ``codex app-server`` process, which uses its own sign-in.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

RATE = 16000
CLOUD_RATE = 24000
OPENAI_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
OPENAI_MODEL = "gpt-live-transcribe"
FINISH_WAIT_S = 8.0
CODEX_PLAN_REASON = ("Codex voice needs Codex signed in with an OpenAI API key; a ChatGPT plan sign-in isn't accepted "
                     "for voice. Use the OpenAI (API key) choice instead.")
PROBE_TTL_S = 60.0
FAIL_TTL_S = 60.0

LABELS = {
    "local": "Local (offline)",
    "openai": "OpenAI (API key)",
    "codex": "OpenAI via Codex sign-in (experimental)",
    "browser": "Browser speech input",
}


_COMMIT = object()


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- availability

_health = {}   # provider -> (monotonic time, message) of the last failure
_probe_cache = {}  # codex sign-in probe


def note_failure(provider: str, message: str) -> None:
    _health[provider] = (time.monotonic(), message)


def note_success(provider: str) -> None:
    _health.pop(provider, None)


def recent_failure(provider: str) -> str:
    seen = _health.get(provider)
    if seen and time.monotonic() - seen[0] < FAIL_TTL_S:
        return seen[1]
    return ""


def openai_key(root) -> str:
    """The OpenAI API key from the environment or Neyvia's provider secret store. Never logged or returned."""
    value = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if value:
        return value
    try:
        from .web_backend import _load_persisted_provider_secrets
        return str(_load_persisted_provider_secrets(Path(root)).get("openai") or "").strip()
    except Exception:  # noqa: BLE001 - a missing store is just "no key"
        return ""


def _local_only() -> bool:
    try:
        from .local_network_policy import enabled
        return bool(enabled())
    except Exception:  # noqa: BLE001
        return False


def _openai_url(settings: dict) -> str:
    url = (os.environ.get("NEYVIA_DICTATION_OPENAI_URL") or settings.get("openaiUrl") or OPENAI_URL).strip()
    parts = urlsplit(url)
    host = parts.hostname or ""
    ok = (parts.scheme == "wss" and host == "api.openai.com") or (parts.scheme == "ws" and host in {"127.0.0.1", "localhost", "::1"})
    if not ok:
        raise ProviderError("The OpenAI dictation address must be wss://api.openai.com (or a local test server).", "bad_url")
    return url


def codex_binary() -> str:
    return os.environ.get("NEYVIA_CODEX_BIN") or shutil.which("codex") or ""


def _popen_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def codex_probe(force: bool = False) -> dict:
    """Is the Codex CLI there, and is it signed in with ChatGPT? Uses account/read only (no token is returned by it)."""
    seen = _probe_cache.get("codex")
    if seen and not force and time.monotonic() - seen[0] < PROBE_TTL_S:
        return seen[1]
    binary = codex_binary()
    if not binary:
        result = {"ok": False, "reason": "The Codex CLI isn't installed on this PC."}
    else:
        try:
            with CodexRpc(binary) as rpc:
                rpc.initialize()
                account = rpc.call("account/read", {"refreshToken": False}, timeout=15)
            kind = ((account or {}).get("account") or {}).get("type")
            if kind == "apiKey":
                result = {"ok": True, "signIn": "apiKey"}
            elif kind == "chatgpt":
                # Observed with codex-cli 0.160: thread/realtime refuses plan sign-ins ("realtime conversation requires API key auth").
                result = {"ok": False, "signIn": "chatgpt", "reason": CODEX_PLAN_REASON}
            else:
                result = {"ok": False, "reason": "Codex isn't signed in. Run `codex login`, then try again."}
        except ProviderError as error:
            result = {"ok": False, "reason": str(error)}
    _probe_cache["codex"] = (time.monotonic(), result)
    return result


_probing = threading.Lock()


def _probe_in_background() -> None:
    def work():
        try:
            codex_probe(force=True)
        finally:
            _probing.release()
    if _probing.acquire(blocking=False):
        threading.Thread(target=work, name="dictation-codex-probe", daemon=True).start()


def describe(root, settings: dict, local_state: str = "") -> list[dict]:
    """The choices for Settings: id, label, whether usable right now and, when not, one plain sentence why."""
    offline = _local_only()
    rows = [{"id": "local", "label": LABELS["local"], "available": local_state not in {"missing", "error"},
             "reason": "" if local_state not in {"missing", "error"} else "The local speech engine isn't installed or failed to start.",
             "offline": True, "streaming": True, "needs": "Nothing. Runs on this PC."}]
    key = bool(openai_key(root))
    reason = "Local-only is on, so nothing leaves this PC." if offline else (
        "" if key else "Needs an OpenAI API key (set OPENAI_API_KEY or add it under providers).")
    reason = reason or recent_failure("openai")
    rows.append({"id": "openai", "label": LABELS["openai"], "available": not reason, "reason": reason, "offline": False,
                 "streaming": True, "needs": "An OpenAI API key. Billed per minute by OpenAI, separate from a ChatGPT plan.",
                 "model": settings.get("openaiModel") or OPENAI_MODEL})
    if offline:
        reason = "Local-only is on, so nothing leaves this PC."
    elif not codex_binary():
        reason = "The Codex CLI isn't installed on this PC."
    else:
        cached = _probe_cache.get("codex")
        if not cached or time.monotonic() - cached[0] > PROBE_TTL_S:
            _probe_in_background()
            reason = "Checking how Codex is signed in…"
        else:
            reason = "" if cached[1].get("ok") else cached[1].get("reason", "")
    reason = reason or recent_failure("codex")
    rows.append({"id": "codex", "label": LABELS["codex"], "available": not reason, "reason": reason, "offline": False,
                 "streaming": True, "experimental": True,
                 "needs": "Codex signed in with ChatGPT. Uses Codex's own voice session; experimental and may change.",
                 "checked": "codex" in _probe_cache})
    rows.append({"id": "browser", "label": LABELS["browser"], "available": True, "reason": "", "offline": False,
                 "streaming": True, "clientSide": True, "needs": "A browser with speech recognition. Sends audio to the browser vendor."})
    return rows


def choose(root, settings: dict, local_state: str = "") -> tuple[str, str]:
    """(provider id to use, plain note when the chosen one isn't usable and we fell back to local)."""
    wanted = str(settings.get("provider") or "local")
    if wanted not in {"openai", "codex"}:
        return "local", ""
    row = next((item for item in describe(root, settings, local_state) if item["id"] == wanted), None)
    if row and row["available"]:
        return wanted, ""
    return "local", f"{LABELS[wanted]} isn't available: {row['reason'] if row else 'unknown provider'} Using the local engine."


# ---------------------------------------------------------------- shared text assembly

def resample_16k_to_24k(pcm: bytes) -> bytes:
    """Linear interpolation, 16 kHz to 24 kHz, signed 16-bit mono."""
    if not pcm:
        return b""
    import numpy as np
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32)
    if samples.size == 0:
        return b""
    count = int(samples.size * CLOUD_RATE / RATE)
    positions = np.arange(count, dtype=np.float32) * (RATE / CLOUD_RATE)
    out = np.interp(positions, np.arange(samples.size, dtype=np.float32), samples)
    return np.clip(out, -32768, 32767).astype("<i2").tobytes()


class Transcript:
    """Segments in arrival order. A segment is provisional (deltas so far) until its completed text arrives."""

    def __init__(self):
        self.lock = threading.Lock()
        self.order = []
        self.text = {}
        self.done = set()
        self.version = 0
        self.t0 = time.perf_counter()
        self.events = []  # (ms since start, kind, words so far)
        self.first_word_ms = None

    def _mark(self, kind: str) -> None:
        now = round((time.perf_counter() - self.t0) * 1000)
        words = len(self.joined().split())
        if words and self.first_word_ms is None:
            self.first_word_ms = now
        self.events.append((now, kind, words))

    def joined(self, only_done: bool = False) -> str:
        parts = []
        for key in self.order:
            if only_done and key not in self.done:
                break  # a completed segment after an unfinished one can't be locked yet
            parts.append(self.text[key].strip())
        return " ".join(part for part in parts if part)

    def delta(self, key: str, text: str) -> None:
        with self.lock:
            if key in self.done:
                return
            if key not in self.text:
                self.order.append(key)
                self.text[key] = ""
            self.text[key] += text
            self.version += 1
            self._mark("delta")

    def complete(self, key: str, text: str | None = None) -> None:
        with self.lock:
            if key not in self.text:
                self.order.append(key)
                self.text[key] = ""
            if text is not None and (text.strip() or not self.text[key].strip()):
                self.text[key] = text
            self.done.add(key)
            self.version += 1
            self._mark("segment")

    def snapshot(self) -> dict:
        with self.lock:
            partial = self.joined()
            stable = self.joined(only_done=True)
            provisional = partial[len(stable):].strip() if partial.startswith(stable) else partial
            return {"partial": partial, "stable": stable, "provisional": provisional, "hypothesis_seq": self.version}

    def settled(self) -> bool:
        with self.lock:
            return bool(self.order) and all(key in self.done for key in self.order)


class CloudStream:
    """Common thread-safe plumbing: an audio queue, a transcript and a stop flag."""
    provider = ""

    def __init__(self):
        self.transcript = Transcript()
        self.audio = queue.Queue()
        self.error = ""
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.fed_ms = 0
        self.first_audio_at = None

    def feed(self, pcm: bytes) -> None:
        if self.error:
            raise ProviderError(self.error)
        if pcm:
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter()
            self.fed_ms += len(pcm) * 1000 // (2 * RATE)
            self.audio.put(pcm)

    def snapshot(self) -> dict:
        if self.error:
            raise ProviderError(self.error)
        return {**self.transcript.snapshot(), "audio_ms": self.fed_ms, "provider": self.provider}

    def finish(self, timeout: float = FINISH_WAIT_S) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def cancel(self) -> None:
        self.closed.set()
        self.audio.put(None)

    def stats(self) -> dict:
        t = self.transcript
        return {"first_word_ms": t.first_word_ms, "events": list(t.events), "provider": self.provider}

    def _wait_settled(self, timeout: float, quiet_s: float = 0.0) -> None:
        end = time.monotonic() + timeout
        quiet_from, last = time.monotonic(), self.transcript.version
        while time.monotonic() < end and not self.error:
            if self.transcript.settled():
                return
            if quiet_s:
                if self.transcript.version != last:
                    last, quiet_from = self.transcript.version, time.monotonic()
                elif self.transcript.order and time.monotonic() - quiet_from >= quiet_s:
                    return
            time.sleep(0.02)

    def _result(self, engine: str) -> dict:
        t = self.transcript
        with t.lock:
            for key in t.order:
                t.done.add(key)
        text = t.joined()
        return {"ok": True, "text": text, "engine": engine, "provider": engine, "audio_ms": self.fed_ms,
                "decode_ms": 0, "first_word_ms": t.first_word_ms, "device": "cloud",
                "stream_events": len(t.events)}


# ---------------------------------------------------------------- OpenAI Realtime transcription

class OpenAIStream(CloudStream):
    provider = "openai"

    def __init__(self, key: str, settings: dict):
        super().__init__()
        from websockets.sync.client import connect
        import numpy  # noqa: F401 - the resampler's first use would otherwise delay the first spoken words
        self.model = str(settings.get("openaiModel") or OPENAI_MODEL)
        self.live = "live" in self.model
        url = _openai_url(settings)
        try:
            self.ws = connect(url, additional_headers={"Authorization": f"Bearer {key}"}, open_timeout=8,
                              max_size=2 ** 22, ping_interval=20)
        except Exception as error:  # noqa: BLE001
            raise ProviderError(_connect_message(error), "connect_failed") from error
        self.sent = 0
        self.commits = 0
        self.last_item = ""
        session = {"type": "transcription", "audio": {"input": {
            "format": {"type": "audio/pcm", "rate": CLOUD_RATE},
            "transcription": {"model": self.model},
            # live model: we commit at release so deltas flow while talking; others segment on pauses
            "turn_detection": None if self.live else {"type": "server_vad", "silence_duration_ms": 450}}}}
        self.ws.send(json.dumps({"type": "session.update", "session": session}))
        threading.Thread(target=self._read, name="dictation-openai-read", daemon=True).start()
        threading.Thread(target=self._write, name="dictation-openai-write", daemon=True).start()

    def _write(self) -> None:
        try:
            while not self.closed.is_set():
                pcm = self.audio.get()
                if pcm is None:
                    return
                if pcm is _COMMIT:
                    self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    self.commits += 1
                    continue
                up = resample_16k_to_24k(pcm)
                self.sent += len(up)
                self.ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(up).decode()}))
        except Exception as error:  # noqa: BLE001
            self._fail(error)

    def _read(self) -> None:
        try:
            for raw in self.ws:
                event = json.loads(raw)
                kind = event.get("type", "")
                key = event.get("item_id") or self.last_item or "item"
                if kind == "conversation.item.input_audio_transcription.delta":
                    self.last_item = key
                    self.transcript.delta(key, str(event.get("delta") or ""))
                elif kind == "conversation.item.input_audio_transcription.completed":
                    self.last_item = key
                    self.transcript.complete(key, str(event.get("transcript") or ""))
                elif kind == "error":
                    detail = event.get("error") or {}
                    if detail.get("code") == "input_audio_buffer_commit_empty":
                        continue
                    raise ProviderError(_api_message(detail))
            if not self.closed.is_set():
                self._fail(ProviderError("OpenAI closed the dictation connection."))
        except Exception as error:  # noqa: BLE001
            if not self.closed.is_set():
                self._fail(error)

    def _fail(self, error) -> None:
        if not self.error and not self.closed.is_set():
            self.error = str(error) if isinstance(error, ProviderError) else _connect_message(error)
            note_failure("openai", self.error)

    def finish(self, timeout: float = FINISH_WAIT_S) -> dict:
        if self.sent:
            self.audio.put(_COMMIT)  # the writer sends it after every queued piece of audio
        if self.error:
            raise ProviderError(self.error)
        self._wait_settled(timeout, quiet_s=2.0)
        if self.error and not self.transcript.joined():
            raise ProviderError(self.error)
        self.cancel()
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        note_success("openai")
        return self._result("openai")

    def cancel(self) -> None:
        super().cancel()
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def _api_message(detail: dict) -> str:
    code = str(detail.get("code") or "")
    if code in {"invalid_api_key", "incorrect_api_key"}:
        return "OpenAI rejected the API key."
    if code in {"insufficient_quota", "billing_hard_limit_reached"}:
        return "The OpenAI account is out of credit."
    if code == "rate_limit_exceeded":
        return "OpenAI is rate limiting dictation right now."
    return str(detail.get("message") or "OpenAI dictation failed.")[:200]


def _connect_message(error) -> str:
    text = str(error)
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in (401, 403) or "401" in text or "403" in text:
        return "OpenAI rejected the API key."
    if status == 404 or "404" in text:
        return "OpenAI didn't accept the transcription session (model or address not available to this key)."
    return "OpenAI can't be reached right now."


# ---------------------------------------------------------------- Codex app-server realtime

class CodexRpc:
    """Newline-delimited JSON-RPC to ``codex app-server`` over stdio (the documented app-server transport)."""

    def __init__(self, binary: str):
        try:
            self.process = subprocess.Popen([binary, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=_popen_flags(), text=True,
                                            encoding="utf-8", bufsize=1)
        except OSError as error:
            raise ProviderError("The Codex CLI couldn't be started.") from error
        self.next_id = 1
        self.pending = {}
        self.lock = threading.Lock()
        self.notifications = queue.Queue()
        self.dead = threading.Event()
        threading.Thread(target=self._read, name="dictation-codex-read", daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read(self) -> None:
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "id" in message and ("result" in message or "error" in message) and "method" not in message:
                    holder = self.pending.get(message["id"])
                    if holder:
                        holder["answer"] = message
                        holder["event"].set()
                elif "method" in message and "id" in message:
                    # A request from the server (approval, tools). Dictation grants nothing.
                    self._send({"id": message["id"], "error": {"code": -32601, "message": "Not supported by dictation"}})
                elif "method" in message:
                    self.notifications.put(message)
        finally:
            self.dead.set()
            for holder in list(self.pending.values()):
                holder["event"].set()

    def _send(self, message: dict) -> None:
        with self.lock:
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                raise ProviderError("The Codex voice session closed.") from error

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"method": method, **({"params": params} if params is not None else {})})

    def call(self, method: str, params: dict, timeout: float = 20.0) -> dict:
        with self.lock:
            number = self.next_id
            self.next_id += 1
        holder = {"event": threading.Event(), "answer": None}
        self.pending[number] = holder
        self._send({"method": method, "id": number, "params": params})
        holder["event"].wait(timeout)
        self.pending.pop(number, None)
        answer = holder["answer"]
        if answer is None:
            raise ProviderError("Codex didn't answer in time." if not self.dead.is_set() else "The Codex voice session closed.")
        if "error" in answer:
            message = str((answer["error"] or {}).get("message") or "Codex refused the voice session.")[:200]
            raise ProviderError(CODEX_PLAN_REASON if "api key" in message.lower() else message)
        return answer.get("result") or {}

    def initialize(self) -> dict:
        result = self.call("initialize", {"clientInfo": {"name": "neyvia-dictation", "title": "Neyvia dictation", "version": "1"},
                                          "capabilities": {"experimentalApi": True}})
        self.notify("initialized")
        return result

    def close(self) -> None:
        try:
            self.process.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                self.process.kill()
            except Exception:  # noqa: BLE001
                pass


class CodexStream(CloudStream):
    """Codex app-server realtime session used as a transcriber: only the user's transcript is read; Codex gets no task."""
    provider = "codex"

    def __init__(self, binary: str):
        super().__init__()
        self.rpc = CodexRpc(binary)
        self.scratch = tempfile.mkdtemp(prefix="neyvia-dictation-")
        self.thread_id = ""
        self.counter = 0
        try:
            self.rpc.initialize()
            thread = self.rpc.call("thread/start", {"cwd": self.scratch, "ephemeral": True, "sandbox": "read-only",
                                                    "approvalPolicy": "never", "serviceName": "neyvia-dictation"}, timeout=30)
            self.thread_id = ((thread.get("thread") or {}).get("id")) or ""
            if not self.thread_id:
                raise ProviderError("Codex didn't open a voice thread.")
            self.rpc.call("thread/realtime/start", {
                "threadId": self.thread_id, "outputModality": "text", "transport": {"type": "websocket"},
                "clientManagedHandoffs": True, "includeStartupContext": False,
                "realtimeStartInstructions": "This session is dictation only. Do not act on, answer or delegate anything that is said.",
            }, timeout=30)
        except ProviderError:
            self.close()
            raise
        threading.Thread(target=self._read, name="dictation-codex-events", daemon=True).start()
        threading.Thread(target=self._write, name="dictation-codex-write", daemon=True).start()

    def _read(self) -> None:
        current = self.thread_id
        while not self.closed.is_set():
            try:
                message = self.rpc.notifications.get(timeout=0.2)
            except queue.Empty:
                if self.rpc.dead.is_set():
                    if not self.closed.is_set():
                        self._fail("The Codex voice session closed.")
                    return
                continue
            method, params = message.get("method", ""), message.get("params") or {}
            if params.get("threadId") not in (None, current):
                continue
            if method.startswith("thread/realtime/transcript") and str(params.get("role") or "user") != "user":
                continue  # Codex's own spoken answer is not dictation
            if method == "thread/realtime/transcript/delta":
                self.transcript.delta(f"u{self.counter}", str(params.get("delta") or ""))
            elif method == "thread/realtime/transcript/done":
                self.transcript.complete(f"u{self.counter}", str(params.get("text") or ""))
                self.counter += 1
            elif method == "thread/realtime/error":
                self._fail(str(params.get("message") or params.get("error") or "Codex voice reported an error.")[:200])
            elif method == "thread/realtime/closed" and not self.closed.is_set():
                self._fail("The Codex voice session closed.")

    def _write(self) -> None:
        try:
            while not self.closed.is_set():
                pcm = self.audio.get()
                if pcm is None:
                    return
                up = resample_16k_to_24k(pcm)
                self.rpc.call("thread/realtime/appendAudio", {"threadId": self.thread_id, "audio": {
                    "data": base64.b64encode(up).decode(), "numChannels": 1, "sampleRate": CLOUD_RATE,
                    "samplesPerChannel": len(up) // 2}}, timeout=10)
        except ProviderError as error:
            self._fail(str(error))

    def _fail(self, message: str) -> None:
        if not self.error and not self.closed.is_set():
            if "api key" in message.lower():
                message = CODEX_PLAN_REASON
                _probe_cache["codex"] = (time.monotonic(), {"ok": False, "signIn": "chatgpt", "reason": message})
            self.error = message
            note_failure("codex", message)

    def finish(self, timeout: float = FINISH_WAIT_S) -> dict:
        try:
            if not self.error:
                end = time.monotonic() + 3
                while not self.audio.empty() and time.monotonic() < end:
                    time.sleep(0.02)
                try:
                    self.rpc.call("thread/realtime/stop", {"threadId": self.thread_id}, timeout=5)
                except ProviderError:
                    pass
                self._wait_settled(timeout, quiet_s=1.5)
            if self.error and not self.transcript.joined():
                raise ProviderError(self.error)
            note_success("codex")
            return self._result("codex")
        finally:
            self.close()

    def close(self) -> None:
        self.closed.set()
        self.audio.put(None)
        self.rpc.close()
        shutil.rmtree(getattr(self, "scratch", ""), ignore_errors=True)

    def cancel(self) -> None:
        self.close()


def open_stream(root, provider: str, settings: dict) -> CloudStream:
    if provider == "openai":
        key = openai_key(root)
        if not key:
            raise ProviderError("There's no OpenAI API key.", "no_key")
        return OpenAIStream(key, settings)
    if provider == "codex":
        binary = codex_binary()
        if not binary:
            raise ProviderError("The Codex CLI isn't installed on this PC.")
        return CodexStream(binary)
    raise ProviderError("Unknown dictation provider.")
