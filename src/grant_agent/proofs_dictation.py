"""Executable dictation policy contracts shared by every production entry point.

These checks observe the actual result and persisted policy. They neither contact
speech engines nor send editor commands. Scratch procedures use the real parser.
"""
from __future__ import annotations

import re
import time
from pathlib import Path


CONTRACTS = (
    "dictation.names.persisted", "dictation.names.scoped", "dictation.prompt.structure",
    "dictation.prompt.commands", "dictation.prompt.route", "dictation.stream.preallocation",
    "dictation.provider.partials", "dictation.provider.finalise", "dictation.provider.fallback",
)


def _require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_prompt(text, history, final, aliases, stable, result):
    """Check the language, preview and command/text boundary after every parse."""
    from .neyvia_prompt_dictation import _COMMANDS, _QUOTED

    _require(result.get("requiresPreview") is True, "dictation.prompt.structure", "commands require preview")
    segments = result.get("segments")
    _require(isinstance(segments, list), "dictation.prompt.structure", "segments must be ordered")
    _require(all(isinstance(s, dict) and s.get("type") in {"text", "command"} for s in segments),
             "dictation.prompt.structure", "segment kind must be text or command")
    _require(all(isinstance(s.get("text"), str) for s in segments if s["type"] == "text"),
             "dictation.prompt.structure", "text segment must carry text")
    _require(all(s.get("op") in set(_COMMANDS.values()) for s in segments if s["type"] == "command"),
             "dictation.prompt.commands", "unknown editor command")
    _require(result.get("commands") == [{"op": s["op"]} for s in segments if s["type"] == "command"],
             "dictation.prompt.commands", "commands must equal the ordered command segments")
    _require(result.get("text") == " ".join(s["text"] for s in segments if s["type"] == "text"),
             "dictation.prompt.structure", "prompt must contain only text segments")
    language = result.get("language")
    _require(language in {"en", "fr", "mixed", "unknown"}, "dictation.prompt.route", "unknown language label")
    _require(result.get("route") == ("qwen" if language in {"fr", "mixed"} else "phonon2"),
             "dictation.prompt.route", "French/mixed must use the multilingual route")
    if not final and not stable:
        _require(result["text"] == text and result["commands"] == [] and result.get("fixes") == [],
                 "dictation.prompt.commands", "live hypotheses must remain literal previews")
    if final:
        whole = _COMMANDS.get(text.casefold().strip(" \t.,;!?"))
        if whole:
            _require(result["text"] == "" and result["commands"] == [{"op": whole}],
                     "dictation.prompt.commands", "a whole command must not become prompt words")
        # Terminal commands outside quotes must be extracted, even after text.
        end = re.search(r"(?i)\b(send it|send that|send|envoie-le|envoie le|envoie|delete the last sentence|delete last sentence|supprime la dernière phrase)\b[.!?,;]*\s*$", text)
        quoted = list(_QUOTED.finditer(text))
        if end and not any(q.start() <= end.start() < q.end() for q in quoted):
            expected = _COMMANDS[end[1].casefold()]
            _require(bool(result["commands"]) and result["commands"][-1]["op"] == expected,
                     "dictation.prompt.commands", "terminal command was omitted")


def before(tool, args, root):
    from . import neyvia_dictation as d

    tool = tool.removeprefix("neyvia.")
    if tool == "dictation.names":
        return {"custom": d._read_policy(root, "names", {}), "path": str(d._policy_path(root, "names").resolve())}
    if tool == "dictation.process":
        return {"history": args.get("history", d.language_history(root)), "aliases": d._name_map(root)}
    return {}


def after(tool, args, result, root, capture):
    from . import neyvia_dictation as d
    from .neyvia_prompt_dictation import BUILTIN_NAMES

    tool = tool.removeprefix("neyvia.")
    if tool == "dictation.process":
        final = args.get("final", True) is not False
        check_prompt(args.get("text", ""), capture["history"], final, capture["aliases"], False, result)
        _require(result.get("stable") == (result["text"] if final else "")
                 and result.get("provisional") == ("" if final else result["text"]),
                 "dictation.prompt.structure", "stable/provisional must match the finality boundary")
    elif tool == "dictation.names":
        expected = {key: list(value) for key, value in capture["custom"].items()}
        action = args.get("action") or "list"
        if action in {"add", "remove"}:
            canonical = str(args.get("to") or "").strip()
            canonical = next((n for n in BUILTIN_NAMES if n.casefold() == canonical.casefold()), canonical)
            aliases = args.get("from") or []
            aliases = [aliases] if isinstance(aliases, str) else aliases
            aliases = {a.casefold().strip() for a in aliases}
            prior = set(expected.get(canonical, []))
            changed = prior | aliases if action == "add" else prior - aliases
            if changed:
                expected[canonical] = sorted(changed)
            else:
                expected.pop(canonical, None)
        actual = d._read_policy(root, "names", {})
        _require(actual == expected, "dictation.names.persisted", "persisted aliases differ from the requested mutation")
        _require(str(d._policy_path(root, "names").resolve()) == capture["path"],
                 "dictation.names.scoped", "policy location changed during the action")
        rows = {r["to"]: r for r in result.get("names", [])}
        _require(set(rows) == set(BUILTIN_NAMES) | set(expected), "dictation.names.persisted", "name observer omitted a row")
        for name in rows:
            _require(set(rows[name]["from"]) == set(BUILTIN_NAMES.get(name, [])) | set(expected.get(name, [])),
                     "dictation.names.persisted", "name observer differs from persisted aliases")


def validate_stream(op, sid, seq, body):
    """Precondition executes before settings, timers, locks or engine allocation."""
    if op not in {"append", "finish", "cancel"}:
        raise ValueError("Unknown dictation step")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", sid or ""):
        raise ValueError("Bad dictation id")
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("Send dictation audio in smaller pieces")
    if len(body) % 2 or int(seq) < 0:
        raise ValueError("Audio must be signed 16-bit mono PCM with a nonnegative sequence")


def _scripted_realtime(words, drop_after=None, split_items=False):
    """A loopback server that plays the OpenAI Realtime transcription protocol (one word per audio piece), so
    streaming order, finalisation and fallback are checked without any network or key."""
    import base64
    import json
    import threading
    from websockets.sync.server import serve

    log = []

    def handle(ws):
        spoken, item, appended = [], "item_1", 0
        for raw in ws:
            event = json.loads(raw)
            log.append(event["type"])
            if event["type"] == "input_audio_buffer.append":
                _require(len(base64.b64decode(event["audio"])) % 2 == 0, "dictation.provider.partials", "odd PCM sent to the provider")
                if appended < len(words):
                    if split_items and appended == len(words) // 2:
                        ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": item,
                                            "transcript": "".join(spoken).strip() + "."}))
                        item, spoken = "item_2", []
                    spoken.append(words[appended] + " ")
                    ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.delta", "item_id": item, "delta": spoken[-1]}))
                appended += 1
                if drop_after is not None and appended >= drop_after:
                    ws.close()
                    return
            elif event["type"] == "input_audio_buffer.commit":
                ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": item,
                                    "transcript": "".join(spoken).strip()}))

    from .proof_ports import proof_port
    server = serve(handle, "127.0.0.1", proof_port(48462))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"ws://127.0.0.1:{server.socket.getsockname()[1]}/v1/realtime?intent=transcription", log


def _recorded_pieces(count):
    """250 ms pieces of the recorded sample (proof/dictation-stream/sample.wav) when present, else silence."""
    import wave
    path = Path(__file__).resolve().parents[2] / "proof" / "dictation-stream" / "sample.wav"
    if path.is_file():
        with wave.open(str(path), "rb") as handle:
            pcm = handle.readframes(handle.getnframes())
        return [pcm[i * 8000:(i + 1) * 8000] for i in range(count)]
    return [b"\x00\x00" * 4000] * count


class _closed_engine_port:
    """Point both speech-engine URLs at a reserved, never-listening loopback port.

    The policy self-check never contacts or launches a speech engine: neither the
    user's real engine on its default port nor any other service. Binding without
    listen reserves the port and refuses every connection. An isolated proof
    declares its explicit ports; the reservation must be one of them.
    """
    KEYS = ("NEYVIA_DICTATION_ENGINE_URL", "NEYVIA_DICTATION_QWEN_URL")

    def __enter__(self):
        import json
        import os
        import socket
        from .proof_ports import proof_port
        declared = json.loads(os.environ.get("NEYVIA_PROOF_ALLOWED_PORTS") or "[]")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # The deliberately closed local-engine address and the scripted cloud
        # provider coexist. Never reserve the provider's explicitly mapped port.
        provider_port = proof_port(48462)
        for port in [value for value in declared if value != provider_port] or ([0] if not declared else []):
            try:
                self.socket.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
        else:
            self.socket.close()
            raise RuntimeError("No explicitly assigned proof port is free to reserve for the closed speech engine")
        url = "http://127.0.0.1:%d" % self.socket.getsockname()[1]
        self.saved = {key: os.environ.get(key) for key in self.KEYS}
        os.environ.update({key: url for key in self.KEYS})
        return url

    def __exit__(self, *exc):
        import os
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.socket.close()
        return False


def provider_checks(root, d):
    """Streaming provider contracts: partial ordering, finalisation, fallback. Scripted provider, fake local engine."""
    import os
    import time
    from . import neyvia_dictation_providers as p

    try:
        import websockets.sync.server  # noqa: F401
    except ImportError:
        return [], ["websockets is not installed, so the scripted provider checks were skipped."]
    checks = []
    saved_key, saved_post, saved_env = p.openai_key, d._post, os.environ.get("NEYVIA_DICTATION_OPENAI_URL")
    p.openai_key = lambda _root: "scripted-key-not-real"
    pieces = _recorded_pieces(7)

    def settle(seconds=0.15):
        time.sleep(seconds)

    try:
        # partial ordering: settled words never go backwards; only completed segments lock; deltas are provisional
        transcript = p.Transcript()
        transcript.delta("a", "open the")
        transcript.delta("b", "write a")
        transcript.complete("b", "Write a note.")
        _require(transcript.snapshot()["stable"] == "", "dictation.provider.partials", "a later segment locked past an unfinished one")
        transcript.complete("a", "Open the settings.")
        snap = transcript.snapshot()
        _require(snap["stable"] == "Open the settings. Write a note." and snap["provisional"] == "",
                 "dictation.provider.partials", "completed segments did not lock in order")
        transcript.delta("a", "ignored")
        _require("ignored" not in transcript.snapshot()["partial"], "dictation.provider.partials", "a finished segment was edited by a stray delta")
        server, url, log = _scripted_realtime(["please", "open", "the", "settings", "page", "now"], split_items=True)
        os.environ["NEYVIA_DICTATION_OPENAI_URL"] = url
        d.write_settings(root, {"provider": "openai"})
        seen = []

        def heard(words, timeout=10.0):
            # Provider events arrive asynchronously. Wait (bounded) for this
            # stream's own transcript instead of a fixed sleep, so a busy
            # low-priority host cannot turn delivery latency into a false
            # ordering failure. The ordering itself is still checked below.
            key = (str(d.state_root(Path(root)).resolve()), "provproof1")
            deadline = time.time() + timeout
            while time.time() < deadline:
                cloud = (d._sessions.get(key) or {}).get("cloud")
                if cloud is not None and len(cloud.snapshot()["partial"].split()) >= words:
                    return
                settle(0.02)
            cloud = (d._sessions.get(key) or {}).get("cloud")
            observed = {"serverEvents": list(log), "sentBytes": getattr(cloud, "sent", None),
                        "partial": cloud.transcript.snapshot()["partial"] if cloud is not None else None,
                        "error": getattr(cloud, "error", None)}
            raise ValueError("Contract dictation.provider.partials: %d provider words did not arrive within %.0f s; observed %r"
                             % (words, timeout, observed))

        for number, piece in enumerate(pieces[:6]):
            answer = d.stream(root, "provproof1", "append", number, piece, history=[])
            _require(answer["provider"] == "openai" and answer["final"] is False, "dictation.provider.partials", "stream did not use the chosen provider")
            seen.append(answer)
            heard(number + 1)
        counts = [len(a["partial"].split()) for a in seen]
        _require(counts == sorted(counts), "dictation.provider.partials", "live words went backwards")
        last = d.stream(root, "provproof1", "append", 6, pieces[6], history=[])
        _require(len(last["partial"].split()) >= 4 and last["stable"] and last["provisional"],
                 "dictation.provider.partials", "a completed segment did not lock while the next stayed grey")
        checks.append({"contract": "dictation.provider.partials", "ok": True, "wordCounts": counts})
        final = d.stream(root, "provproof1", "finish", 7, b"", history=[])
        _require(final["final"] is True and final["provider"] == "openai" and "input_audio_buffer.commit" in log
                 and final["text"].lower().startswith("please open the") and "settings" in final["text"].lower(),
                 "dictation.provider.finalise", "finish did not commit and return the final text")
        _require(final.get("requiresPreview") is True, "dictation.provider.finalise", "final dictation skipped the preview policy")
        checks.append({"contract": "dictation.provider.finalise", "ok": True})
        server.shutdown()

        # fallback 1: no key -> local engine with one plain sentence
        p.openai_key = lambda _root: ""
        posted = []
        d._post = lambda url, body, **kw: posted.append((url.rsplit("/v1/stream/", 1)[1], len(body))) or {"ok": True, "partial": "hello", "stable": ""}
        answer = d.stream(root, "provproof2", "append", 0, pieces[0], history=[])
        _require(answer["provider"] == "local" and "OpenAI API key" in answer["providerNote"] and posted[0][0] == "provproof2/append?seq=0",
                 "dictation.provider.fallback", "a missing key did not fall back to the local engine with a note")
        # fallback 2: the provider dies mid-dictation -> local engine gets all audio so far, numbered from 0
        p.openai_key = lambda _root: "scripted-key-not-real"
        server, url, _ = _scripted_realtime(["alpha", "beta", "gamma"], drop_after=2)
        os.environ["NEYVIA_DICTATION_OPENAI_URL"] = url
        posted.clear()
        d._post = lambda url, body, **kw: posted.append((url.rsplit("/v1/stream/", 1)[1], len(body))) or {
            "ok": True, "partial": "alpha beta gamma", "stable": "", "text": "alpha beta gamma", "engine": "phonon2"}
        d.stream(root, "provproof3", "append", 0, pieces[0], history=[])
        d.stream(root, "provproof3", "append", 1, pieces[1], history=[])
        deadline = time.time() + 3
        while time.time() < deadline and not any(s.get("cloud") and s["cloud"].error for s in d._sessions.values()):
            settle(0.05)
        answer = d.stream(root, "provproof3", "append", 2, pieces[2], history=[])
        _require(answer["provider"] == "local" and "stopped" in answer["providerNote"]
                 and posted[0] == ("provproof3/append?seq=0", len(pieces[0]) + len(pieces[1]) + len(pieces[2])),
                 "dictation.provider.fallback", "mid-dictation failure did not replay all audio to the local engine")
        closing = d.stream(root, "provproof3", "finish", 3, b"", history=[])
        _require(posted[1][0] == "provproof3/finish?seq=1" and closing["provider"] == "local" and closing["warning"],
                 "dictation.provider.fallback", "the local finish was misnumbered or silent about the fallback")
        server.shutdown()
        os.environ.pop("NEYVIA_DICTATION_OPENAI_URL", None)  # pinned address; local-only blocks cloud
        try:
            p._openai_url({"openaiUrl": "wss://evil.example.com/v1/realtime"})
        except p.ProviderError:
            pass
        else:
            raise ValueError("Contract dictation.provider.fallback: a foreign dictation address was accepted")
        saved_local = p._local_only
        p._local_only = lambda: True
        try:
            rows = {row["id"]: row for row in p.describe(root, {}, "ready")}
            _require(rows["openai"]["available"] is False and rows["local"]["available"] is True
                     and p.choose(root, {"provider": "openai"}, "ready")[0] == "local",
                     "dictation.provider.fallback", "local-only did not block the cloud provider")
        finally:
            p._local_only = saved_local
        # Codex voice: a ChatGPT plan sign-in is reported as unusable (observed: realtime needs API key auth)
        class PlanRpc:
            def __init__(self, binary): pass
            def __enter__(self): return self
            def __exit__(self, *exc): pass
            def initialize(self): return {}
            def call(self, method, params, timeout=0): return {"account": {"type": "chatgpt", "planType": "pro"}}
        saved_rpc, saved_bin = p.CodexRpc, p.codex_binary
        p.CodexRpc, p.codex_binary = PlanRpc, lambda: "codex"
        try:
            probe = p.codex_probe(force=True)
            d.write_settings(root, {"provider": "codex"})
            _require(probe["ok"] is False and "API key" in probe["reason"] and p.choose(root, d.read_settings(root), "ready")[0] == "local",
                     "dictation.provider.fallback", "a ChatGPT plan sign-in was offered for Codex voice")
        finally:
            p.CodexRpc, p.codex_binary = saved_rpc, saved_bin
            p._probe_cache.pop("codex", None)
        checks.append({"contract": "dictation.provider.fallback", "ok": True})
    finally:
        p.openai_key, d._post = saved_key, saved_post
        if saved_env is None:
            os.environ.pop("NEYVIA_DICTATION_OPENAI_URL", None)
        else:
            os.environ["NEYVIA_DICTATION_OPENAI_URL"] = saved_env
        d._sessions.clear()
        d.write_settings(root, {"provider": "local"})
    return checks, []


def self_check(root):
    """Run policy observers/procedures against disposable, isolated real state."""
    from . import neyvia_dictation as d
    from .neyvia_prompt_dictation import process_prompt

    started = time.perf_counter()
    root = Path(root) / "dictation"
    _require(d.state_root(root) == root.resolve(), "dictation.names.scoped",
             "scratch self-check requires NEYVIA_UI_STATE_ROOT to be unset")
    root.mkdir(parents=True, exist_ok=True)
    checks = []
    def checked(identity, procedure):
        procedure()
        checks.append({"contract": identity, "ok": True})

    def names_procedure():
        d.names(root, {"action": "add", "to": "INT6", "from": ["in six"]})
        result = d.process(root, {"text": "um in six new line send it", "history": ["en"], "final": True})
        _require("INT6" in result["text"], "dictation.names.persisted", "new alias not used by prompt policy")
        _require("send it" not in result["text"].casefold() and {"op": "send"} in result["commands"],
                 "dictation.prompt.commands", "send command leaked into prompt words")
        other = d.process(root / "other", {"text": "in six", "history": ["en"]})
        _require("INT6" not in other["text"], "dictation.names.scoped", "alias leaked to another scratch workspace")
        d.names(root, {"action": "remove", "to": "INT6", "from": ["in six"]})
        _require(not any(r["to"] == "INT6" for r in d.names(root, {})["names"]),
                 "dictation.names.persisted", "last alias removal left a custom row")
    checked("dictation.names.persisted", names_procedure)
    checks.append({"contract": "dictation.names.scoped", "ok": True})
    checks.append({"contract": "dictation.prompt.commands", "ok": True})

    def french_procedure():
        result = process_prompt("bonjour je voudrais modifier le document", ["fr"])
        _require(result["language"] in {"fr", "mixed"} and result["route"] == "qwen",
                 "dictation.prompt.route", "French fixture was not routed to multilingual recognition")
    checked("dictation.prompt.route", french_procedure)

    def stream_procedure():
        snapshot = dict(d._sessions)
        for op, body, expected in [("append", b"x", "signed 16-bit"), ("wrong", b"", "Unknown dictation step")]:
            try:
                d.stream(root, "int6-audio", op, 0, body)
            except ValueError as error:
                _require(expected in str(error), "dictation.stream.preallocation", "wrong rejection reason")
            else:
                raise ValueError("Contract dictation.stream.preallocation: rejected audio was accepted")
            _require(d._sessions == snapshot, "dictation.stream.preallocation", "rejected audio allocated stream state")
    checked("dictation.stream.preallocation", stream_procedure)

    def preview_procedure():
        preview = d.process(root, {"text": "send it", "history": ["en"], "final": False})
        _require(preview["text"] == "send it" and preview["commands"] == [],
                 "dictation.prompt.structure", "unfinished speech emitted an editor command")
        literal = d.process(root, {"text": 'please type "send it" here', "history": ["en"]})
        _require(literal["commands"] == [], "dictation.prompt.commands", "quoted speech became a command")
    checked("dictation.prompt.structure", preview_procedure)
    with _closed_engine_port():
        provider_results, provider_skips = provider_checks(root, d)
    checks.extend(provider_results)
    rejected = []
    # Feed corrupted observations to the same production postcondition, proving
    # it rejects the defect rather than merely recording that it was invoked.
    observed = process_prompt("please build it send it", ["en"])
    for field, replacement, identity in [
        ("requiresPreview", False, "dictation.prompt.structure"),
        ("commands", [], "dictation.prompt.commands"),
        ("route", "qwen", "dictation.prompt.route"),
    ]:
        invalid = {**observed, field: replacement}
        try:
            check_prompt("please build it send it", ["en"], True, {}, False, invalid)
        except ValueError as error:
            _require(identity in str(error), identity, "defective observation failed for an unrelated reason")
            rejected.append({"contract": identity, "field": field, "rejected": True})
        else:
            raise ValueError(f"Contract {identity}: corrupted observation was accepted")
    persisted = d._read_policy(root, "names", {})
    for payload in [
        {"action": "remove", "to": "Neyvia", "from": ["nevia"]},
        {"action": "add", "to": "OTHER", "from": ["nevia"]},
    ]:
        try:
            d.names(root, payload)
        except ValueError:
            _require(d._read_policy(root, "names", {}) == persisted,
                     "dictation.names.persisted", "rejected built-in mutation changed the dictionary")
        else:
            raise ValueError("Contract dictation.names.persisted: built-in alias mutation was accepted")
    rejected.append({"contract": "dictation.names.persisted", "builtinMutationAttempts": 2, "rejected": True})
    return {"ok": not provider_skips, "contracts": sorted({row['contract'] for row in checks if row.get('ok') is True}), "checks": checks,
            "rejections": rejected,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
            "frontier": ["Speech-engine health/start/transcription procedures need separately authorized ASR; this policy self-check never contacts or launches engines.",
                         "The OpenAI Realtime provider is exercised against a scripted loopback server; the live OpenAI endpoint needs a user-supplied API key.",
                         *provider_skips]}
