"""Dictation: speech to prompt text with the local Phonon-2 engine, shared with the dictation service.

The engine (phonon2_engine.py in the dictation repo) is a small localhost process with its own Python
(the dictation venv has torch + CUDA). Neyvia starts it on demand, hidden; it stays warm while used and exits after 20 idle minutes. The PC
service owns streaming sessions and proxies audio for browsers, phones and the desktop bridge.

English prompts use Phonon-2; French/mixed utterances use the configured local multilingual
recognizer. Both paths pass through the same prompt cleanup/command policy. No math conversion.
"""
from __future__ import annotations

import base64
import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .ui_command_bus import state_root
from . import neyvia_dictation_providers as providers
from .neyvia_prompt_dictation import BUILTIN_NAMES, agreed_prefix, frontier_text, process_prompt, revision_span

TEXT = {"type": "string"}
ENGINE_PORT = 48113
IDLE_EXIT_MINUTES = 20.0
QWEN_URL = "http://127.0.0.1:48114"
RATE = 16000
MAX_AUDIO_BYTES = 20 * 60 * RATE * 2  # 20 minutes of 16-bit mono
START_GRACE_S = 120.0  # a started engine gets this long to load before we start another

DEFINITIONS = [
    ("dictation.status", "Is the local speech engine (Phonon-2) ready? Returns state (off, starting, ready, error, "
                         "missing), device (cuda/cpu), the engine URL and whether the Qwen path is reachable. "
                         "start=true starts the engine if it is off.", {"start": {"type": "boolean"}}, []),
    ("dictation.transcribe", "Turn an audio file (wav/flac/ogg, any rate) into text with the local engine. "
                             "Automatic English/French/mixed routing, prompt cleanup and spoken edit commands.",
     {"path": TEXT, "engine": {"type": "string", "enum": ["auto", "phonon2", "qwen"]}, "history": {"type": "array", "items": TEXT, "maxItems": 20}}, ["path"]),
    ("dictation.process", "Clean a final prompt utterance and parse spoken edits; returns editor actions, never sends. Live final=false text stays provisional.",
     {"text": TEXT, "history": {"type": "array", "items": TEXT, "maxItems": 20}, "final": {"type": "boolean"}}, ["text"]),
    ("dictation.names", "Read or extend prompt sound-alike aliases. Built-in aliases cannot be removed.",
     {"action": {"type": "string", "enum": ["list", "add", "remove"]}, "to": TEXT, "from": {"type": ["string", "array"], "items": TEXT}}, []),
]
COMMANDS = frozenset({"dictation_status_command", "dictation_transcribe_command", "dictation_settings_command",
                      "dictation_stream_command", "dictation_process_command", "dictation_names_command", "dictation_redecode_command"})

_start_lock = threading.Lock()
_qwen_seen = {}  # per configured URL; no probes of unrelated services
_sessions = {}
_sessions_lock = threading.Lock()
_policy_lock = threading.RLock()
_active_audio = {}


def _audio_operation(operation):
    @functools.wraps(operation)
    def guarded(root, *args, **kwargs):
        from .local_network_policy import transition
        key = str(state_root(Path(root)).resolve())
        with transition(False):
            _active_audio[key] = _active_audio.get(key, 0) + 1
        try:
            return operation(root, *args, **kwargs)
        finally:
            with transition(False):
                _active_audio[key] -= 1
    return guarded


def _audio_busy(root):
    key = str(state_root(Path(root)).resolve())
    with _sessions_lock:
        return bool(_active_audio.get(key)) or any(k[0] == key and not session["finished"]
                                                 for k, session in _sessions.items())


def _expire_session(key, session) -> None:
    with _sessions_lock:
        if _sessions.get(key) is not session:
            return
        remaining = 180 - (time.monotonic() - session["touched"])
        if remaining <= 0:
            _sessions.pop(key, None)
            return
    timer = threading.Timer(remaining + .1, _expire_session, args=(key, session))
    timer.daemon = True
    timer.start()


def _policy_path(root, name: str) -> Path:
    return state_root(Path(root)) / ".neyvia" / ("dictation-" + name + ".json")


def _read_policy(root, name: str, default):
    try:
        value = json.loads(_policy_path(root, name).read_text(encoding="utf-8"))
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_policy(root, name: str, value) -> None:
    path = _policy_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def language_history(root) -> list[str]:
    rows = _read_policy(root, "history", [])
    return [row["language"] for row in rows[-20:] if isinstance(row, dict) and row.get("language") in {"en", "fr", "mixed"}]


def _remember_language(root, language: str) -> None:
    if language not in {"en", "fr", "mixed"}:
        return
    with _policy_lock:
        rows = _read_policy(root, "history", [])
        rows.append({"language": language, "at": time.time()})
        _write_policy(root, "history", rows[-20:])


def names(root, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Name dictionary changes need a JSON object")
    action = payload.get("action") or "list"
    if action not in {"list", "add", "remove"}:
        raise ValueError("Unknown name dictionary action")
    with _policy_lock:
        from .proofs_dictation import before, after
        capture = before("dictation.names", payload, root)
        custom = _read_policy(root, "names", {})
        if action != "list":
            canonical = str(payload.get("to") or "").strip()
            canonical = next((name for name in BUILTIN_NAMES if name.casefold() == canonical.casefold()), canonical)
            aliases = payload.get("from") or []
            aliases = [aliases] if isinstance(aliases, str) else aliases
            if not canonical or len(canonical) > 100 or not isinstance(aliases, list) or not aliases or len(aliases) > 30 or any(not isinstance(a, str) or not a.strip() or len(a) > 100 for a in aliases):
                raise ValueError("Supply a name and one or more short spoken aliases")
            aliases = [a.casefold().strip() for a in aliases]
            builtins = {a.casefold() for a in BUILTIN_NAMES.get(canonical, [])}
            if action == "remove" and any(a in builtins for a in aliases):
                raise ValueError("Built-in names can be extended, not removed")
            if action == "add":
                claimed = {a: name for source in (BUILTIN_NAMES, custom) for name, rows in source.items() for a in rows}
                if any(a in claimed and claimed[a] != canonical for a in aliases):
                    raise ValueError("That alias already belongs to another name")
                custom[canonical] = sorted(set(custom.get(canonical, [])) | set(aliases))
            elif canonical in custom:
                custom[canonical] = [a for a in custom[canonical] if a not in aliases]
                if not custom[canonical]:
                    custom.pop(canonical)
            _write_policy(root, "names", custom)
        result = {"names": [{"to": name, "from": sorted(set(BUILTIN_NAMES.get(name, [])) | set(custom.get(name, []))),
                            "builtin": name in BUILTIN_NAMES} for name in sorted(set(BUILTIN_NAMES) | set(custom))]}
        after("dictation.names", payload, result, root, capture)
        return result


def _name_map(root) -> dict:
    return {alias: row["to"] for row in names(root, {})["names"] for alias in row["from"]}


def _qwen_url(settings: dict) -> str:
    return _local_url(os.environ.get("NEYVIA_DICTATION_QWEN_URL", "").strip().rstrip("/") or str(settings.get("qwenUrl") or QWEN_URL).rstrip("/"))


def _local_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Prompt dictation engines must run locally on this PC")
    if os.environ.get('NEYVIA_PROOF_CREDENTIAL_GUARD') == '1':
        ports = json.loads(os.environ.get('NEYVIA_PROOF_ALLOWED_PORTS', '[]'))
        if parsed.port not in ports:
            raise ValueError('Isolated proof refuses a speech engine outside its explicit ports')
    return url


def _qwen_health(settings: dict) -> dict:
    url = _qwen_url(settings)
    checked, reachable = _qwen_seen.get(url, (0, {}))
    if time.time() - checked > 30:
        reachable = _get(url + "/health", timeout=0.4) or {}
        _qwen_seen[url] = (time.time(), reachable)
    return reachable


def _qwen_up(settings: dict) -> bool:
    health = _qwen_health(settings)
    return bool(health) and health.get("ok", True) is not False and health.get("state", "ready") == "ready"


def process(root, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Dictation processing needs a JSON object")
    from .proofs_dictation import before, after
    capture = before("dictation.process", payload, root)
    final = payload.get("final", True) is not False
    answer = process_prompt(payload.get("text", ""), capture["history"], final, capture["aliases"])
    if final:
        _remember_language(root, answer["language"])
    warning = ""
    if answer["route"] == "qwen" and not _qwen_up(read_settings(root)):
        warning = "That sounded French. The French engine isn't running, so check the text."
    result = {**answer, "final": final, "stable": answer["text"] if final else "", "provisional": "" if final else answer["text"],
              "revision": None, "engine": payload.get("engine") or "phonon2", "redecode": None, "route_note": warning, "timings": {}}
    after("dictation.process", payload, result, root, capture)
    return result


# ---------------------------------------------------------------- settings and discovery

def _settings_path(root) -> Path:
    return state_root(Path(root)) / ".neyvia" / "dictation.json"


def read_settings(root) -> dict:
    try:
        saved = json.loads(_settings_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return saved if isinstance(saved, dict) else {}


def write_settings(root, patch: dict) -> dict:
    allowed = {"engineDir", "python", "port", "qwenFallback", "qwenUrl", "enabled", "names", "device", "provider", "openaiModel", "openaiUrl", "partialEveryS"}
    current = read_settings(root)
    current.update({key: value for key, value in (patch or {}).items() if key in allowed})
    if str(current.get("provider") or "local") not in {"local", "openai", "codex", "browser"}:
        raise ValueError("Unknown dictation provider")
    _qwen_url(current)
    _engine_url(current)
    path = _settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=1), encoding="utf-8")
    return current


def _engine_url(settings: dict) -> str:
    override = os.environ.get("NEYVIA_DICTATION_ENGINE_URL", "").strip().rstrip("/")
    return _local_url(override or f"http://127.0.0.1:{int(settings.get('port') or ENGINE_PORT)}")


def _engine_dir(settings: dict) -> Path | None:
    candidates = [settings.get("engineDir"), os.environ.get("NEYVIA_DICTATION_ENGINE_DIR"),
                  str(Path.home() / "Projects" / "dictation-phonon2")]
    for candidate in candidates:
        if candidate and (Path(candidate) / "phonon2_engine.py").is_file():
            return Path(candidate)
    return None


def _engine_python(settings: dict, engine_dir: Path | None) -> Path | None:
    """The dictation venv's Python (torch + CUDA). Neyvia's own Python has no CUDA torch."""
    if settings.get("python") and Path(settings["python"]).is_file():
        return Path(settings["python"])
    if engine_dir is None:
        return None
    names = ["Scripts/python.exe", "bin/python"]
    for venv in [engine_dir / ".venv", *sorted(engine_dir.parent.glob("dictation-workbench*/.venv"))]:
        for name in names:
            if (venv / name).is_file():
                return venv / name
    return None


# ---------------------------------------------------------------- engine process

def _get(url: str, timeout: float = 0.8) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, ValueError):
        return None


def _post(url: str, body: bytes, content_type: str = "application/octet-stream", timeout: float = 60.0) -> dict:
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            answer = json.loads(error.read())
        except ValueError:
            answer = {}
        raise DictationError(answer.get("error") or f"The speech engine answered {error.code}",
                             code="engine_busy" if error.code == 503 else "engine_error") from error
    except OSError as error:
        raise DictationError("The speech engine isn't running.", code="engine_off") from error


class DictationError(RuntimeError):
    def __init__(self, message: str, code: str = "engine_error"):
        super().__init__(message)
        self.code = code


def _stamp_path(root) -> Path:
    return state_root(Path(root)) / ".neyvia" / "dictation-engine.start"


def status(root, start: bool = False, probe: bool = False) -> dict:
    settings = read_settings(root)
    if probe:
        providers.codex_probe(force=True)
    url = _engine_url(settings)
    health = _get(url + "/v1/health")
    engine_dir = _engine_dir(settings)
    python = _engine_python(settings, engine_dir)
    result = {"engine": "phonon2", "url": url, "enabled": settings.get("enabled", True) is not False,
              "engineDir": str(engine_dir) if engine_dir else None, "python": str(python) if python else None,
              "qwenFallback": settings.get("qwenFallback", True) is not False}
    if health:
        result.update(state=health.get("state"), device=health.get("device"), error=health.get("error") or "",
                      loadMs=health.get("load_ms"), served=health.get("served"), pid=health.get("pid"))
    elif engine_dir is None or python is None:
        result.update(state="missing", error="The speech engine isn't installed on this PC (phonon2_engine.py and "
                      "the dictation Python were not found). Set them in dictation settings.")
    else:
        started_at = _read_stamp(root)
        starting = started_at and time.time() - started_at < START_GRACE_S
        if start and result["enabled"] and not starting and providers.choose(root, settings)[0] == "local":
            _spawn(root, engine_dir, python, settings)
            starting = True
        result.update(state="starting" if starting else "off", error="")
    result["qwen"] = bool(result["qwenFallback"] and _qwen_up(settings))
    result["languages"] = ["en", "fr", "mixed"] if result["qwen"] else ["en"]
    result["partialStability"] = "committed-pieces"
    result["engines"] = {"phonon2": result.get("state"), "qwen": result["qwen"]}
    result["qwenPcm"] = bool(_qwen_health(settings).get("pcm16")) if result["qwen"] else False
    result["recentLanguage"] = (language_history(root) or [None])[-1]
    result["providers"] = providers.describe(root, settings, str(result.get("state") or ""))
    active, note = providers.choose(root, settings, str(result.get("state") or ""))
    result.update(provider=active, providerWanted=str(settings.get("provider") or "local"), providerNote=note, localState=result.get("state"))
    if active != "local":
        result["state"] = "ready"  # the cloud provider streams; the local engine isn't needed (and isn't started)
        result["partialStability"] = "completed-segments"
    return result


def _read_stamp(root) -> float:
    try:
        return float(_stamp_path(root).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0.0


def _spawn(root, engine_dir: Path, python: Path, settings: dict):
    if os.environ.get('NEYVIA_PROOF_CREDENTIAL_GUARD') == '1' and not engine_dir.resolve().is_relative_to(Path(root).resolve()):
        raise DictationError('Isolated proof refuses a speech engine outside its disposable root', code='engine_scope')
    with _start_lock:
        if _get(_engine_url(settings) + "/v1/health"):
            return
        started_at = _read_stamp(root)
        if started_at and time.time() - started_at < START_GRACE_S:
            return
        stamp = _stamp_path(root)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
        log = open(stamp.with_name("dictation-engine.log"), "ab")  # noqa: SIM115 - handed to the child
        flags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS makes Windows ignore CREATE_NO_WINDOW. A venv
            # redirector can then start its Python child in a visible brokered
            # pseudo-console. Retain the hidden console and pipe transport.
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("PYTHONPATH", None)  # Neyvia's path must not leak into the dictation venv
        # Words appear as they are spoken: refresh the live preview about every 0.4 s (the engine's own default is 0.7 s).
        env.setdefault("PHONON2_PARTIAL_EVERY_S", str(max(0.2, min(1.5, float(settings.get("partialEveryS") or 0.4)))))
        if str(settings.get("device") or "cpu") == "cpu":
            # Excessive BLAS threads stall short speech decodes on a busy PC.
            env.setdefault("OMP_NUM_THREADS", "4")
            env.setdefault("MKL_NUM_THREADS", "4")
        # Free the GPU when nobody dictates for a while; the weight cache brings it back in about 2 s.
        idle_minutes = float(settings.get("idleExitMinutes", IDLE_EXIT_MINUTES))
        from .local_network_policy import register_idle_child, stop_child
        process = subprocess.Popen([str(python), str(engine_dir / "phonon2_engine.py"), "--port", str(int(settings.get("port") or ENGINE_PORT)),
                          "--device", str(settings.get("device") or "cpu"),
                          "--idle-exit-minutes", str(idle_minutes)],
                         cwd=str(engine_dir), stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                         creationflags=flags, close_fds=True)
        log.close()
        def stop_owned():
            if _audio_busy(root):
                return False
            stopped = stop_child(process)
            if stopped:
                _stamp_path(root).unlink(missing_ok=True)
            return stopped
        register_idle_child(process, kind="Dictation engine", busy=lambda: _audio_busy(root), stop=stop_owned)
        return process


def stop(root) -> dict:
    url = _engine_url(read_settings(root))
    try:
        _post(url + "/v1/shutdown", b"", timeout=3)
    except DictationError:
        pass
    try:
        _stamp_path(root).unlink()
    except OSError:
        pass
    return {"ok": True}


# ---------------------------------------------------------------- audio

@_audio_operation
def stream(root, sid: str, op: str, seq: int, body: bytes, history=None) -> dict:
    from .proofs_dictation import validate_stream
    validate_stream(op, sid, seq, body)
    history = language_history(root) if history is None else history
    process_prompt("", history)  # validate before allocating session state
    settings = read_settings(root)
    key = (str(state_root(Path(root)).resolve()), sid)
    with _sessions_lock:
        now = time.monotonic()
        for expired in [k for k, s in _sessions.items() if now - s["touched"] > 180]:
            _sessions.pop(expired, None)
        if key not in _sessions:
            if sum(not s["finished"] for s in _sessions.values()) >= 16:
                raise ValueError("Too many open dictations")
            if len(_sessions) >= 32:
                oldest = min((k for k, s in _sessions.items() if s["finished"]), key=lambda k: _sessions[k]["touched"])
                _sessions.pop(oldest)["pcm"].clear()
            _sessions[key] = {"pcm": bytearray(), "seq": -1, "touched": now, "lock": threading.Lock(),
                              "partial": "", "stable": "", "rawStable": "", "hypothesis": None,
                              "history": list(history), "finished": False}
            timer = threading.Timer(180.1, _expire_session, args=(key, _sessions[key]))
            timer.daemon = True
            timer.start()
        session = _sessions[key]
    with session["lock"]:
        session["touched"] = time.monotonic()
        if op != "cancel" and "provider" not in session:
            _pick_provider(root, session, settings)
        if op == "cancel":
            session["finished"] = True
            session["cancelled"] = True
            session["pcm"].clear()
            if session.get("cloud"):
                session["cloud"].cancel()
                session["cloud"] = None
                session["last"] = {"ok": True, "cancelled": True}
                return session["last"]
            try:
                result = _post(f"{_engine_url(settings)}/v1/stream/{sid}/cancel", b"", timeout=3)
            except DictationError:
                result = {"ok": True, "cancelled": True}
            session["last"] = result
            return result
        if session["finished"]:
            if op == "finish" and not session.get("cancelled") and seq == session["seq"] and "last" in session:
                return {**session["last"], "duplicate": True}
            raise ValueError("This dictation already finished or was cancelled")
        duplicate = seq <= session["seq"]
        if not duplicate and seq != session["seq"] + 1:
            raise ValueError("Dictation audio arrived out of order")
        if not duplicate and len(session["pcm"]) + len(body) > MAX_AUDIO_BYTES:
            raise ValueError("That recording is longer than 20 minutes")
        with _sessions_lock:
            if not duplicate and sum(len(s["pcm"]) for s in _sessions.values()) + len(body) > 128 * 1024 * 1024:
                raise ValueError("Dictation memory is full; finish or cancel another recording")
        if duplicate and op == "finish":
            raise ValueError("Finish needs the next audio sequence")
        result = _stream_step(root, session, sid, op, int(seq), body, settings, duplicate)
        if not duplicate:
            session["pcm"].extend(body)
            session["seq"] = seq
        if op == "finish":
            session["finished"] = True
            try:
                result = _finalize(root, result, bytes(session["pcm"]), session["history"], allow_redecode=True)
                result.update(sid=sid, seq=seq, final=True, revision=revision_span(session["stable"], result["stable"]),
                              provider=session.get("provider", "local"))
                if session.get("providerNote") and not result.get("warning"):
                    result["warning"] = result["route_note"] = session["providerNote"]
                session["stable"] = result["stable"]
                session["last"] = result
                session["touched"] = time.monotonic()
            except Exception:
                session["pcm"].clear()
                raise
            return result
        partial = str(result.get("partial") or "")
        committed = str(result.get("stable") or result.get("committed_text") or "")
        hypothesis = result.get("hypothesis_seq")
        new_decode = hypothesis != session["hypothesis"] if hypothesis is not None else partial != session["partial"]
        agreed = agreed_prefix(session["partial"], partial) if new_decode and not duplicate else ""
        # An unchanged cached reply is not a second decode; only new hypotheses count.
        raw_stable, provisional = frontier_text(session["rawStable"], partial, committed, agreed, new_decode)
        cleaned = process_prompt(raw_stable, session["history"], final=False, names=_name_map(root), stable=True)
        stable = cleaned["text"]
        revision = revision_span(session["stable"], stable)
        if new_decode:
            session["partial"], session["hypothesis"] = partial, hypothesis
        session["stable"], session["rawStable"] = stable, raw_stable
        return {**result, **cleaned, "sid": sid, "seq": seq, "final": False, "partial": (stable + " " + provisional).strip(),
                "stable": stable, "provisional": provisional, "revision": revision,
                "provider": session.get("provider", "local"), "providerNote": session.get("providerNote", "")}


def _pick_provider(root, session: dict, settings: dict) -> None:
    """Choose where this dictation is decoded. A cloud provider that can't open falls back to the local engine."""
    session["provider"], session["cloud"], session["providerNote"] = "local", None, ""
    wanted, note = providers.choose(root, settings)
    session["providerNote"] = note
    if wanted == "local":
        return
    try:
        session["cloud"] = providers.open_stream(root, wanted, settings)
        session["provider"] = wanted
    except providers.ProviderError as error:
        providers.note_failure(wanted, str(error))
        session["providerNote"] = f"{providers.LABELS[wanted]} isn't available: {error} Using the local engine."


def _stream_step(root, session: dict, sid: str, op: str, seq: int, body: bytes, settings: dict, duplicate: bool) -> dict:
    """One audio piece to the chosen provider. The local engine numbers its pieces from 0 after a mid-dictation fallback."""
    cloud = session.get("cloud")
    if cloud is not None:
        try:
            if duplicate:
                return {"ok": True, "duplicate": True, **cloud.snapshot()}
            cloud.feed(body)
            if op == "finish":
                result = cloud.finish()
                session["cloud"] = None
                return result
            return cloud.snapshot()
        except providers.ProviderError as error:
            # The cloud went away mid-dictation: the local engine takes over with everything heard so far.
            cloud.cancel()
            session["cloud"], session["provider"] = None, "local"
            session["providerNote"] = f"{providers.LABELS.get(cloud.provider, 'The cloud provider')} stopped ({error}). Finished with the local engine."
            session["engine_base"] = seq
            body = bytes(session["pcm"]) + body
    local_seq = seq - int(session.get("engine_base", 0))
    return _post(f"{_engine_url(settings)}/v1/stream/{sid}/{op}?seq={local_seq}", body, timeout=120)


def _finalize(root, answer: dict, pcm: bytes | None = None, history=None, path: str = "", allow_redecode=False) -> dict:
    history = language_history(root) if history is None else history
    parsed = process_prompt(answer.get("text") or "", history, names=_name_map(root))
    if (parsed["language"] == "unknown" or parsed["language_source"] == "history") and answer.get("language") in {"en", "fr"} and float(answer.get("language_confidence") or 0) >= .8:
        parsed.update(language=answer["language"], language_confidence=answer["language_confidence"], language_source="engine",
                      route="qwen" if answer["language"] == "fr" else "phonon2")
    settings = read_settings(root)
    warning = ""
    redecode_request = None
    route_started = time.perf_counter()
    if parsed["route"] == "qwen" and answer.get("engine") not in {"qwen", "openai", "codex"}:
        if settings.get("qwenFallback", True) is not False and _qwen_up(settings):
            try:
                if allow_redecode and parsed["language_confidence"] < .8:
                    redecode_request = {"engine": "qwen", "reason": "Recheck French/mixed speech with the local multilingual recognizer."}
                else:
                    again = _qwen_file(root, path) if path else _qwen_pcm(root, pcm or b"")
                    answer = {**answer, **again}
                    parsed = process_prompt(answer.get("text") or "", history, names=_name_map(root))
            except DictationError as error:
                warning = str(error)
        else:
            warning = "That sounded French. The French engine isn't running, so check the text."
    _remember_language(root, parsed["language"])
    timings = {key: value for key, value in answer.items() if key.endswith("_ms")}
    timings["route_ms"] = round((time.perf_counter() - route_started) * 1000)
    return {**answer, **parsed, "stable": parsed["text"], "provisional": "", "warning": warning, "route_note": warning,
            "redecode": redecode_request, "revision": None, "final": True,
            "timings": timings, "routeAvailable": not warning, "requiresPreview": True}


@_audio_operation
def redecode(root, sid: str) -> dict:
    key = (str(state_root(Path(root)).resolve()), sid)
    with _sessions_lock:
        session = _sessions.get(key)
    if not session or not session["finished"] or time.monotonic() - session["touched"] > 180 or not session.get("last", {}).get("redecode"):
        raise ValueError("No pending local re-decode; the audio may have expired")
    with session["lock"]:
        answer = _finalize(root, _qwen_pcm(root, bytes(session["pcm"])), history=session["history"])
        answer.update(sid=sid, seq=session["seq"], revision=revision_span(session["stable"], answer["stable"]))
        session["last"], session["stable"] = answer, answer["stable"]
        session["touched"] = time.monotonic()
        return answer


@_audio_operation
def transcribe_pcm(root, pcm: bytes, engine: str = "auto", language: str = "", history=None) -> dict:
    if len(pcm) > MAX_AUDIO_BYTES:
        raise ValueError("That recording is longer than 20 minutes")
    if len(pcm) % 2:
        raise ValueError("Audio must be signed 16-bit mono PCM")
    if engine not in {"auto", "phonon2", "qwen"}:
        raise ValueError("Unknown speech engine")
    if engine == "qwen":
        return _finalize(root, _qwen_pcm(root, pcm, language), history=history)
    url = _engine_url(read_settings(root))
    return _finalize(root, _post(url + "/v1/transcribe", pcm, timeout=120), pcm, history)


def _qwen_pcm(root, pcm: bytes, language: str = "") -> dict:
    settings = read_settings(root)
    # The legacy Qwen service only accepts audio_path. Do not silently spill a
    # recorded prompt to disk to satisfy that older API. Require its PCM capability.
    if not _qwen_health(settings).get("pcm16"):
        raise DictationError("The French engine can't check this recording. Check the text.", "qwen_pcm_unavailable")
    answer = _post(_qwen_url(settings) + "/asr", json.dumps({"pcm": base64.b64encode(pcm).decode("ascii"),
                   "sample_rate": RATE, "mode": "note", "speech_language": language}).encode(), "application/json", timeout=180)
    return {**answer, "engine": "qwen", "text": answer.get("normalized") or answer.get("transcript") or answer.get("text") or ""}


def _qwen_file(root, path: str, language: str = "") -> dict:
    source = Path(path).expanduser()
    body = json.dumps({"audio_path": str(source.resolve()), "mode": "note",
                       **({"speech_language": language} if language else {})}).encode()
    try:
        answer = _post(_qwen_url(read_settings(root)) + "/asr", body, "application/json", timeout=180)
    except DictationError as error:
        raise DictationError("The French engine isn't running on this PC.", code="qwen_off") from error
    return {"ok": True, "engine": "qwen", "text": answer.get("normalized") or answer.get("transcript") or "",
            "decode_ms": round(answer.get("asr_latency_ms") or 0), "total_ms": round(answer.get("end_to_end_latency_ms") or 0)}


@_audio_operation
def transcribe_file(root, path: str, engine: str = "auto", language: str = "", history=None) -> dict:
    source = Path(path).expanduser()
    if not source.is_file():
        raise ValueError(f"No audio file at {source}")
    if engine not in {"auto", "phonon2", "qwen"}:
        raise ValueError("Unknown speech engine")
    if engine == "qwen":
        return _finalize(root, _qwen_file(root, path, language), history=history)
    url = _engine_url(read_settings(root))
    return _finalize(root, _post(url + "/v1/transcribe", json.dumps({"audio_path": str(source.resolve())}).encode(), "application/json", timeout=300),
                     history=history, path=path)


# ---------------------------------------------------------------- entry points

def call(service, name: str, args: dict) -> dict:
    root = service.bus.root
    if name == "dictation.status":
        return status(root, start=bool(args.get("start")))
    if name == "dictation.transcribe":
        return transcribe_file(root, str(args.get("path") or ""), str(args.get("engine") or "auto"), history=args.get("history"))
    if name == "dictation.process":
        return process(root, args)
    if name == "dictation.names":
        return names(root, args)
    raise ValueError("Unknown dictation action")


def handle_command(root, command: str, payload: dict) -> dict:
    """Desktop bridge and /api/backend. Audio here is base64 PCM (the desktop's Qwen fallback, small files)."""
    payload = payload or {}
    if payload.get("_expectedStateRoot") and Path(payload["_expectedStateRoot"]).resolve() != state_root(Path(root)).resolve():
        raise DictationError("The desktop is connected to a different workspace's dictation service.", "state_root_mismatch")
    if command == "dictation_process_command":
        return process(root, payload)
    if command == "dictation_names_command":
        return names(root, payload)
    if command == "dictation_redecode_command":
        return redecode(root, str(payload.get("sid") or ""))
    if command == "dictation_stream_command":
        return stream(root, str(payload.get("sid") or ""), str(payload.get("op") or ""), int(payload.get("seq") or 0),
                      base64.b64decode(str(payload.get("pcm") or ""), validate=True), payload.get("history"))
    if command == "dictation_status_command":
        return status(root, start=bool(payload.get("start")), probe=bool(payload.get("probe")))
    if command == "dictation_settings_command":
        if payload.get("stop"):
            return stop(root)
        saved = write_settings(root, payload.get("settings") or {})
        return {"settings": saved, "status": status(root)}
    if command == "dictation_transcribe_command":
        if payload.get("path"):
            return transcribe_file(root, str(payload["path"]), str(payload.get("engine") or "auto"), str(payload.get("language") or ""), payload.get("history"))
        pcm = base64.b64decode(str(payload.get("pcm") or ""), validate=True)
        return transcribe_pcm(root, pcm, str(payload.get("engine") or "auto"), str(payload.get("language") or ""), payload.get("history"))
    raise ValueError("Unknown dictation command")


def respond_command(handler, root, command, payload):
    """Keep desktop-command failures consistent with dictation HTTP routes."""
    from .web_backend import _json_response
    try:
        result = handle_command(root, command, payload)
    except DictationError as error:
        _json_response(handler, 503, {"ok": False, "error": str(error), "code": error.code})
    except (ValueError, TypeError) as error:
        _json_response(handler, 400, {"ok": False, "error": str(error)})
    else:
        _json_response(handler, 200, {"ok": True, "data": result})


def serve_http(backend, handler, parsed, method: str) -> None:
    """/api/ui/dictation/... for browsers and phones: raw 16 kHz mono 16-bit PCM bodies, JSON answers."""
    from urllib.parse import parse_qs

    from .web_backend import _json_response

    parts = parsed.path.removeprefix("/api/ui/dictation/").strip("/").split("/")
    query = parse_qs(parsed.query)
    length = int(handler.headers.get("content-length") or 0)
    if length < 0 or length > MAX_AUDIO_BYTES:
        _json_response(handler, 413, {"ok": False, "error": "That recording is too long"})
        return
    body = handler.rfile.read(length) if method == "POST" and length else b""
    try:
        if parts == ["status"] and method == "GET":
            result = status(backend.root, start=(query.get("start") or ["0"])[0] == "1", probe=(query.get("probe") or ["0"])[0] == "1")
        elif parts == ["settings"] and method == "POST":
            patch = json.loads(body or b"{}")
            result = {"settings": write_settings(backend.root, patch.get("settings") or {}), "status": status(backend.root)}
        elif parts == ["process"] and method == "POST":
            result = process(backend.root, json.loads(body))
        elif parts == ["names"] and method == "POST":
            result = names(backend.root, json.loads(body))
        elif parts == ["names"] and method == "GET":
            result = names(backend.root, {})
        elif len(parts) == 2 and parts[0] == "redecode" and method == "POST":
            result = redecode(backend.root, parts[1])
        elif len(parts) == 3 and parts[0] == "stream" and method == "POST":
            result = stream(backend.root, parts[1], parts[2], int((query.get("seq") or ["0"])[0]), body,
                            json.loads(query["history"][0]) if "history" in query else None)
        elif parts == ["transcribe"] and method == "POST":
            result = transcribe_pcm(backend.root, body, (query.get("engine") or ["auto"])[0], (query.get("language") or [""])[0],
                                   json.loads(query["history"][0]) if "history" in query else None)
        else:
            _json_response(handler, 404, {"ok": False, "error": "Unknown dictation path"})
            return
        _json_response(handler, 200, {"ok": True, "data": result})
    except DictationError as error:
        _json_response(handler, 503, {"ok": False, "error": str(error), "code": error.code})
    except (ValueError, TypeError) as error:
        _json_response(handler, 400, {"ok": False, "error": str(error)})
