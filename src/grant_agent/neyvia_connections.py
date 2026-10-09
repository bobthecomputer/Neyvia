"""One honest list of every way Neyvia can reach a model, with a proven one-click connect.

Each connection is a harness CLI (Claude Code, Codex, OpenCode, Kimi, gptme), the API keys Neyvia
holds, or a local model server. The state comes from each tool's own status command
(``claude auth status``, ``codex login status`` ...), never from reading credential files.

States: ``connected`` (signed in), ``needs-signin``, ``not-installed``, ``broken`` (the tool or
server is there but does not answer, with the reason).

Connect: a signed-out tool gets one click that opens that provider's own sign-in in the person's
terminal (Neyvia never types or reads credentials). A signed-in tool can be *proven*: one real
prompt that must be answered using one real tool call (reading a file that holds a one-time word
only a tool call can return), run through the same connected-session broker chats use.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .harness_auth_inventory import _probe_row, _run, probe_timed_out, reset_probe_timeout
from . import connections_install

SCHEMA = "neyvia.connections/v1"
DEFINITIONS = [
    ("connections.inspect", "Read one live Connections card, install progress, sign-in and round-trip receipt. Never returns credentials.",
     {"id": {"type": "string"}, "force": {"type": "boolean"}}, ["id"]),
    ("connections.install", "Install a harness hidden after the person clicks Install and consents to this exact pending approval. Never supply consent on their behalf.",
     {"id": {"type": "string"}, "approvalId": {"type": "string"}, "consent": {"type": "boolean"}, "fromClick": {"type": "boolean"}}, ["id", "fromClick"]),
    ("connections.connect", "Open the provider's own sign-in after an explicit person click; watch the Connections card for completion.",
     {"id": {"type": "string"}, "fromClick": {"type": "boolean"}}, ["id", "fromClick"]),
    ("connections.prove", "Run the real Test it round trip on a signed-in harness, after the person requests it.",
     {"id": {"type": "string"}, "fromClick": {"type": "boolean"}}, ["id", "fromClick"]),
]
CACHE_SECONDS = 45.0
PROOF_SECONDS = 300.0
RECEIPT_KEY = "connections.proofs"

# id -> how to describe and drive it. ``harness`` is the harness_registry id the sign-in probe uses.
SPECS: tuple[dict[str, Any], ...] = (
    {"id": "claude-code", "label": "Claude Code", "about": "Your Claude plan, through Claude Code.", "harness": "claude-code",
     "command": "claude", "app": "claude-code", "signin": ["claude", "auth", "login"], "signinLabel": "Sign in with Claude",
     "install": "npm install -g @anthropic-ai/claude-code", "proofModel": "claude-haiku-5-5", "docs": "https://code.claude.com/docs/en/quickstart"},
    {"id": "codex", "label": "Codex", "about": "Your ChatGPT plan, through Codex.", "harness": "codex",
     "command": "codex", "app": "codex", "signin": ["codex", "login"], "signinLabel": "Sign in with ChatGPT",
     "install": "npm install -g @openai/codex", "proofModel": "", "docs": "https://developers.openai.com/codex/cli"},
    {"id": "opencode", "label": "OpenCode", "about": "Open-source coding agent with your own providers.", "harness": "opencode",
     "command": "opencode", "app": "opencode", "signin": ["opencode", "auth", "login"], "signinLabel": "Connect a provider",
     "install": "npm install -g opencode-ai", "proofModel": "", "docs": "https://opencode.ai/docs"},
    {"id": "kimi-code", "label": "Kimi Code", "about": "Moonshot's Kimi coding agent.", "harness": "kimi-code",
     "command": "kimi", "app": None, "nativeProof": True, "signin": ["kimi", "login"], "signinLabel": "Sign in with Kimi",
     "install": "uv tool install kimi-cli", "proofModel": "", "docs": "https://moonshotai.github.io/kimi-cli/"},
    {"id": "gptme", "label": "gptme", "about": "Terminal agent that uses your API keys.", "harness": "gptme",
     "command": "gptme", "app": None, "nativeProof": True, "signin": None, "install": "uv tool install gptme", "proofModel": "", "docs": "https://gptme.org/docs/"},
)
KEY_PROVIDERS = (("openai", "OpenAI"), ("anthropic", "Anthropic"), ("openrouter", "OpenRouter"),
                 ("minimax", "MiniMax"), ("opencode-go", "OpenCode Go"), ("kimi-code", "Kimi"))
LOCAL_SERVERS = (("ollama", "Ollama", "http://127.0.0.1:11434/api/tags", "models", "ollama"),
                 ("lmstudio", "LM Studio", "http://127.0.0.1:1234/v1/models", "data", "lms"))

_lock = threading.RLock()
_cache: dict[str, Any] = {"at": 0.0, "value": None, "running": False, "partial": {}}
_proving: dict[str, dict[str, Any]] = {}
_signing: set[str] = set()


def _signin_receipt(root: Path, ident: str) -> dict[str, Any]:
    from .ui_command_bus import bus_for
    receipt = bus_for(root).get("connections.signin:" + ident, {}) or {}
    if ident == "kimi-code" and receipt.get("ok"):
        # Legacy Kimi has no status command. Its own logout removes this file;
        # inspect presence only, so a past login cannot survive a later logout.
        share = Path(os.environ.get("KIMI_SHARE_DIR") or Path.home() / ".kimi")
        if not (share / "credentials" / "kimi-code.json").is_file():
            return {**receipt, "ok": False, "state": "signed-out"}
    return receipt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _which(command: str, root: Path) -> str:
    from .runtimes.base import runtime_which
    try:
        return connections_install.command(command, root) or runtime_which(command, root) or shutil.which(command) or ""
    except Exception:  # noqa: BLE001 - a lookup problem is "not found"
        return shutil.which(command) or ""


def _terminal_argv(argv: list[str], title: str) -> list[str]:
    """A Windows Terminal tab that runs the provider's own sign-in and stays open afterwards."""
    return ["wt", "-w", "new", "--title", title, "cmd", "/k", subprocess.list2cmdline(argv)]


# --------------------------------------------------------------------------------- one connection

def _harness_card(spec: dict[str, Any], root: Path, keys: dict[str, bool]) -> dict[str, Any]:
    command = _which(spec["command"], root)
    card: dict[str, Any] = {"id": spec["id"], "kind": "harness", "label": spec["label"], "about": spec["about"], "docs": spec.get("docs"),
                            "provable": bool(spec.get("app") or spec.get("nativeProof")), "version": "", "state": "not-installed", "why": "", "fix": None}
    if not command:
        card.update(why=f"{spec['label']} is not on this PC.", fix={"kind": "install", "label": "Install", "command": spec["install"]})
        return card
    # The version and the sign-in are asked at the same time: starting a CLI can take half a minute on a busy PC.
    version_box: dict[str, Any] = {}
    asker = threading.Thread(target=lambda: version_box.update(result=_run(command, ["--version"], root, 90.0)), daemon=True)
    asker.start()
    row = {"harnessId": spec["harness"], "installed": True, "command": command,
           "providerConfigured": keys.get("kimi-code") if spec["id"] == "kimi-code" else None}
    reset_probe_timeout()
    probe = _probe_row(row, root)
    timed_out = probe_timed_out()
    asker.join(95)
    code, version = version_box.get("result", (124, ""))
    card["version"] = version.splitlines()[0][:60] if version and code == 0 else ""
    if spec["id"] == "kimi-code" and "no longer maintained" in version.lower():
        card.update(state="broken", why="This Kimi package only shows a migration notice. Retry to install the working legacy CLI.",
                    fix={"kind": "install", "label": "Retry", "command": spec["install"]})
        return card
    if code not in (0, 124):
        card.update(state="broken", why=(version or f"{spec['label']} did not start.")[:200], fix={"kind": "install", "label": "Reinstall", "command": spec["install"]})
        return card
    if timed_out:  # a slow answer on a busy PC says nothing about the sign-in
        card.update(state="broken", why=f"{spec['label']} was too slow to answer. This PC is busy: check again in a moment.", slow=True,
                    fix={"kind": "recheck", "label": "Check again", "command": ""})
        return card
    auth = probe.get("authState")
    if spec["id"] == "kimi-code" and _signin_receipt(root, spec["id"]).get("ok"):
        auth = "configured-unverified"
        probe["evidence"] = "Kimi's own login completed. Test it to confirm access."
    if spec["id"] == "gptme":
        have = [label for key, label in KEY_PROVIDERS if key in {"openai", "anthropic", "openrouter"} and keys.get(key)]
        auth = "authenticated-live" if have else "provider-setup-required"
        probe["evidence"] = ("Uses your " + ", ".join(have) + " key.") if have else "gptme needs an API key."
    if auth in {"authenticated-live", "configured-unverified"}:
        card.update(state="connected", why=probe.get("evidence") or "Signed in.")
    elif auth in {"account-action-required", "provider-setup-required", "route-setup-required"}:
        card["state"] = "needs-signin"
        card["why"] = {"claude-code": "Not signed in to Claude.", "codex": "Not signed in to ChatGPT.", "opencode": "No provider connected yet.",
                       "kimi-code": "Not signed in to Kimi.", "gptme": "No API key to use yet."}.get(spec["id"], "Not signed in.")
        if spec.get("signin"):
            argv = [command if i == 0 else part for i, part in enumerate(spec["signin"])]
            native_login = spec["id"] == "kimi-code"
            card["fix"] = {"kind": "provider" if native_login else "terminal", "label": spec["signinLabel"],
                           "command": subprocess.list2cmdline(spec["signin"]), "note": spec.get("signinNote", ""),
                           "argv": [command, "login", "--json"] if native_login else _terminal_argv(argv, spec["label"] + " sign-in")}
        else:
            card["fix"] = {"kind": "keys", "label": "Add an API key", "command": ""}
    else:
        card.update(state="broken", why=(probe.get("evidence") or "Its status could not be read.")[:200],
                    fix={"kind": "recheck", "label": "Check again", "command": ""})
    return card


def _keys_card(keys: dict[str, bool]) -> dict[str, Any]:
    have = [label for key, label in KEY_PROVIDERS if keys.get(key)]
    card = {"id": "api-keys", "kind": "keys", "label": "API keys", "about": "Pay-as-you-go keys Neyvia can use directly.",
            "provable": False, "version": "", "docs": None, "have": have}
    if have:
        card.update(state="connected", why=", ".join(have) + (" key saved." if len(have) == 1 else " keys saved."), fix={"kind": "keys", "label": "Add or change keys", "command": ""})
    else:
        card.update(state="needs-signin", why="No keys saved yet.", fix={"kind": "keys", "label": "Add an API key", "command": ""})
    return card


def _local_card(root: Path) -> dict[str, Any]:
    card = {"id": "local-models", "kind": "local", "label": "Local models", "about": "Models running on this PC, free and private.",
            "provable": False, "version": "", "docs": None, "state": "not-installed", "why": "No local model server found.", "fix": None, "servers": []}
    for ident, label, url, field, command in LOCAL_SERVERS:
        installed = bool(_which(command, root))
        count, error = 0, ""
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:  # noqa: S310 - fixed loopback URL
                count = len(json.loads(response.read(2_000_000)).get(field) or [])
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
        card["servers"].append({"id": ident, "label": label, "installed": installed, "running": not error, "models": count})
    running = [row for row in card["servers"] if row["running"] and row["models"]]
    installed = [row for row in card["servers"] if row["installed"] or row["running"]]
    if running:
        total = sum(row["models"] for row in running)
        card.update(state="connected", why=f"{running[0]['label']} answered with {total} model{'s' if total != 1 else ''}.")
    elif installed:
        first = installed[0]
        if first["running"]:
            card.update(state="needs-signin", why=f"{first['label']} is running but has no model yet.",
                        fix={"kind": "link", "label": "Get a model", "command": "", "url": "https://ollama.com/library"})
        else:
            card.update(state="broken", why=f"{first['label']} is installed but not running.",
                        fix={"kind": "terminal", "label": f"Start {first['label']}", "command": "ollama serve",
                             "argv": _terminal_argv(["ollama", "serve"], "Ollama")} if first["id"] == "ollama" else None)
    else:
        card["fix"] = {"kind": "link", "label": "Get Ollama", "command": "", "url": "https://ollama.com/download"}
    return card


STATES = frozenset({"checking", "installing", "connected", "needs-signin", "not-installed", "broken"})
_SECRET_WORDS = ("secret", "password", "apikey", "api_key", "accesstoken", "access_token", "refreshtoken")


def check_cards(cards: list[dict[str, Any]]) -> None:
    """The invariants of what the screen is told; raises ``ValueError`` naming the first card that breaks one."""
    seen = set()
    for card in cards:
        ident = card.get("id")
        if ident in seen or card.get("state") not in STATES:
            raise ValueError(f"connection {ident}: a repeated id or unknown state")
        seen.add(ident)
        state, fix = card["state"], card.get("fix")
        if state != "checking" and not str(card.get("why") or "").strip():
            raise ValueError(f"connection {ident}: {state} without a plain reason")
        if state in ("needs-signin", "not-installed") and not (fix and fix.get("label")):
            raise ValueError(f"connection {ident}: {state} without a next step")
        if state == "installing" and (fix or not card.get("install", {}).get("line")):
            raise ValueError(f"connection {ident}: installation without progress or with an overlapping action")
        if fix and fix.get("kind") == "terminal" and not (fix.get("argv") and fix["argv"][0] == "wt" and fix.get("command")):
            raise ValueError(f"connection {ident}: a sign-in that does not open the person's terminal")
        if fix and fix.get("kind") == "provider" and (ident != "kimi-code" or fix.get("argv", [])[1:] != ["login", "--json"]):
            raise ValueError(f"connection {ident}: an unsupported provider sign-in route")
        if card.get("proof") and state != "connected":
            raise ValueError(f"connection {ident}: a test receipt on a connection that is not signed in")
        if card.get("provable") and state == "connected" and fix:
            raise ValueError(f"connection {ident}: a connected harness offering a fix")
        text = json.dumps({key: value for key, value in card.items() if key != "proof"}, default=str).lower()
        if any(word in text for word in _SECRET_WORDS):
            raise ValueError(f"connection {ident}: secret-looking text in what the screen is told")


# --------------------------------------------------------------------------------------- reading

def _key_presence(backend: Any) -> dict[str, bool]:
    ids = [key for key, _ in KEY_PROVIDERS]
    try:
        return {key: bool(value) for key, value in backend._fresh_provider_auth_presence(ids).items()}
    except Exception:  # noqa: BLE001 - keys unreadable means "none shown", never a crash
        return {}


def _receipts(service: Any) -> dict[str, Any]:
    try:
        value = service.bus.get(RECEIPT_KEY, {})
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


ORDER = tuple(spec["id"] for spec in SPECS) + ("api-keys", "local-models")
LABELS = {spec["id"]: spec["label"] for spec in SPECS} | {"api-keys": "API keys", "local-models": "Local models"}
LAST_KEY = "connections.last"


def _placeholder(ident: str) -> dict[str, Any]:
    return {"id": ident, "kind": "pending", "label": LABELS[ident], "about": "", "provable": False, "version": "", "docs": None,
            "state": "checking", "why": "Looking…", "fix": None}


def _measure(backend: Any, service: Any, publish: Any) -> None:
    """Probe everything in parallel; ``publish(card)`` is called as each one finishes, so a slow tool never hides the others."""
    root = Path(service.bus.root)
    keys = _key_presence(backend)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_harness_card, spec, root, keys): spec["id"] for spec in SPECS}
        futures[pool.submit(_local_card, root)] = "local-models"
        publish(_keys_card(keys))
        for future in as_completed(futures):
            try:
                publish(future.result())
            except Exception as exc:  # noqa: BLE001 - one tool failing is that tool's card, not the screen's
                ident = futures[future]
                publish({**_placeholder(ident), "state": "broken", "why": f"{type(exc).__name__}: its check failed.", "fix": {"kind": "recheck", "label": "Check again", "command": ""}})


def _refresh(backend: Any, service: Any) -> None:
    started = time.monotonic()
    fresh: dict[str, dict[str, Any]] = {}

    def publish(card: dict[str, Any]) -> None:
        with _lock:
            before = (_cache["value"] or {}).get("byId", {}).get(card["id"])
            # A check that ran out of time keeps the last answer we had (marked stale) instead of flipping the card.
            if card.get("slow") and before and not before.get("slow"):
                card = {**before, "stale": True}
            fresh[card["id"]] = card
            _cache["partial"] = dict(fresh)

    try:
        _measure(backend, service, publish)
        with _lock:
            _cache.update(at=time.monotonic(), value={"checkedAt": _now(), "tookMs": round((time.monotonic() - started) * 1000), "byId": dict(fresh)}, partial={})
        try:
            service.bus.put(LAST_KEY, {"checkedAt": _now(), "byId": {k: v for k, v in fresh.items() if not v.get("slow")}})
        except Exception:  # noqa: BLE001
            pass
    finally:
        with _lock:
            _cache["running"] = False
            _cache["partial"] = {}


def _known(service: Any) -> dict[str, dict[str, Any]]:
    """The last finished reading (in memory, else the one saved on disk) so the screen is never empty on reopening."""
    with _lock:
        if _cache["value"]:
            return dict(_cache["value"]["byId"])
    try:
        saved = service.bus.get(LAST_KEY, {})
        return {k: {**v, "stale": True} for k, v in (saved.get("byId") or {}).items()} if isinstance(saved, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _card(service: Any, ident: str) -> dict[str, Any] | None:
    with _lock:
        live = (_cache.get("partial") or {}).get(ident)
    card = live or _known(service).get(ident)
    if card and ident == "kimi-code" and _signin_receipt(Path(service.bus.root), ident).get("ok"):
        return {**card, "state": "connected", "fix": None, "why": "Kimi's own login completed. Test it to confirm access."}
    return card


def status(backend: Any, service: Any, *, force: bool = False) -> dict[str, Any]:
    """Fast: whatever is known right now. Older than 45 s is re-read in the background; each card arrives as its check finishes."""
    with _lock:
        stale = force or _cache["value"] is None or time.monotonic() - _cache["at"] > CACHE_SECONDS
        start = stale and not _cache["running"]
        if start:
            _cache["running"] = True
    if start:
        threading.Thread(target=_refresh, args=(backend, service), name="connections-probe", daemon=True).start()
        time.sleep(0.4)
    known = _known(service)
    with _lock:
        partial = dict(_cache.get("partial") or {})
        checking = _cache["running"]
        checked = (_cache["value"] or {}).get("checkedAt")
        took = (_cache["value"] or {}).get("tookMs")
    receipts = _receipts(service)
    cards = []
    for ident in ORDER:
        card = _card(service, ident) or partial.get(ident) or known.get(ident)
        pending = checking and ident not in partial
        if card is None:
            card = _placeholder(ident)
        shown = dict(card)
        if pending and card["state"] != "checking":
            shown["refreshing"] = True
        shown["proof"] = receipts.get(ident) if card["state"] == "connected" else None  # a receipt only counts while it still works
        shown["proving"] = _proving.get(ident)
        if ident in connections_install.PACKAGES:
            job = connections_install.progress(service, ident)
            shown["updates"] = connections_install.update_label(Path(service.bus.root), ident)
            shown["install"] = job
            if job and job["state"] == "installing":
                shown.update(state="installing", why=job["line"], fix=None, proof=None, refreshing=False)
            elif job and job["state"] == "failed":
                shown.update(state="broken", why=job["line"], fix={"kind": "install", "label": "Retry"}, proof=None)
            elif (job and job["state"] == "completed" and checking and card.get("version") != job["version"]
                  and (datetime.now(timezone.utc) - datetime.fromisoformat(job["completedAt"])).total_seconds() < 120):
                shown.update(state="needs-signin", why="Installed and checked. Not signed in yet.", version=job["version"],
                             fix={"kind": "recheck", "label": "Check sign-in"}, refreshing=True)
            if shown["state"] == "connected":
                _signing.discard(ident)
            shown["signingIn"] = ident in _signing
            shown["signin"] = _signin_receipt(Path(service.bus.root), ident) or None
        cards.append(shown)
    check_cards(cards)
    ready = sum(card["state"] == "connected" for card in cards)
    return {"ok": True, "schema": SCHEMA, "checkedAt": checked, "tookMs": took, "checking": checking, "cards": cards,
            "summary": {"connected": ready, "total": len(cards), "pending": sum(card["state"] == "checking" for card in cards),
                        "proven": sum(bool(card.get("proof") and card["proof"].get("ok")) for card in cards)}}


# ----------------------------------------------------------------------------------------- connect

def connect(service: Any, args: dict[str, Any]) -> dict[str, Any]:
    """The click on "Sign in with X": open that provider's own sign-in in the person's terminal."""
    if args.get("fromClick") is not True:
        raise ValueError("Connect is for the person to start: use the button on the connection")
    ident = str(args.get("id") or "")
    card = _card(service, ident)
    fix = (card or {}).get("fix") or {}
    if not card or fix.get("kind") not in {"terminal", "provider"} or not fix.get("argv"):
        raise ValueError("That connection has nothing to open")
    if ident == "kimi-code" and not args.get("dryRun"):
        with _lock:
            if ident in _signing:
                return {"ok": True, "launched": False}
            _signing.add(ident)
        root = Path(service.bus.root)
        service.bus.put("connections.signin:" + ident, {"state": "pending", "startedAt": _now()})

        def signin() -> None:
            ok = False
            try:
                done = connections_install.run_hidden([_which("kimi", root), "login", "--json"], root, lambda _: None)
                events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
                ok = done.returncode == 0 and any(event.get("type") == "success" for event in events)
                service.bus.put("connections.signin:" + ident, {"ok": ok, "state": "completed" if ok else "failed", "at": _now()})
            except Exception:  # provider errors never expose raw login output
                service.bus.put("connections.signin:" + ident, {"ok": False, "state": "failed", "at": _now()})
            finally:
                with _lock:
                    _signing.discard(ident)
                    _cache["at"] = 0.0
                if not ok:
                    service.bus.emit("notify", {"level": "warning", "message": "Kimi sign-in did not finish. Please try Sign in again."})

        threading.Thread(target=signin, name="connections-kimi-signin", daemon=True).start()
        return {"ok": True, "launched": True, "note": "Finish on Kimi's own page. This card updates automatically."}
    launched = False
    if not args.get("dryRun"):
        subprocess.Popen(fix["argv"], close_fds=True)  # noqa: S603 - argv built from our own table
        launched = True
        with _lock:
            _signing.add(ident)
            _cache["at"] = 0.0  # the next reading looks again, so the card turns green once the sign-in finishes
    return {"ok": True, "argv": fix["argv"], "command": fix.get("command"), "launched": launched,
            "note": "Finish signing in in the terminal window, then come back: this card updates by itself."}


# ------------------------------------------------------------------------------------------ prove

def _lowest_mode(options: dict[str, Any]) -> str | None:
    modes = [str(row.get("id")) for row in options.get("permissionModes") or [] if isinstance(row, dict)]
    for wanted in ("plan", "read-only", "readOnly", "ask", "default", "workspace-read"):
        if wanted in modes:
            return wanted
    return modes[0] if modes else None


def _text_of(items: list[dict[str, Any]]) -> tuple[str, int]:
    text, tools = "", 0
    for item in items:
        kind = item.get("kind")
        if kind == "tool":
            tools += 1
        elif kind == "assistant":
            data = item.get("data") or {}
            text = str(data.get("text") or data.get("content") or json.dumps(data))
    return text, tools


def _wait_run(broker: Any, run_id: str, deadline: float) -> dict[str, Any]:
    from .connected_sessions.runs import TERMINAL_STATES
    while time.monotonic() < deadline:
        run = broker.get_run(run_id)
        if run.get("state") in TERMINAL_STATES:
            return run
        time.sleep(1.0)
    try:
        broker.stop(run_id)
    except Exception:  # noqa: BLE001
        pass
    return {**broker.get_run(run_id), "state": "timeout"}


def _when_free(call: Any, seconds: float = 120.0) -> Any:
    """A chat that just finished can still read as busy for a moment (the app is closing the turn): ask again for up to two minutes."""
    end = time.monotonic() + seconds
    while True:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() > end or "working elsewhere" not in str(exc) and "busy" not in str(exc).lower():
                raise
            time.sleep(4.0)


# What a Codex check turns off. Codex otherwise sends the person's whole setup (plugins, browser and computer-use
# tools, skills, agents) with every request: measured 237k input tokens through the chat path, 129k with project
# docs off, 32.7k with the list below (one prompt, one file read). Measured on codex-cli 0.154.0.
_CODEX_OFF = ("apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access", "computer_use", "goals", "hooks",
              "image_generation", "in_app_browser", "memories", "multi_agent", "multi_agent_v2", "personality", "plugins",
              "remote_plugin", "skill_search", "sleep_tool", "tool_suggest", "view_image", "skill_mcp_dependency_install",
              "mentions_v2", "guardian_approval", "collaboration_modes", "fast_mode", "in_app_chat", "in_app_local_automation",
              "workspace_dependencies", "tool_search_always_defer_mcp_tools", "steer", "tool_call_mcp_elicitation", "shell_snapshot")


def _codex_native(root: Path) -> str:
    """The real codex.exe behind the npm shim (a .cmd cannot take an exact argument list)."""
    import glob
    import re
    shim = _which("codex", root)
    if not shim:
        return ""
    folders = [Path(shim).parent / "node_modules/@openai/codex/node_modules"]
    try:
        text = Path(shim).read_text(encoding="utf-8", errors="replace")
        for target in re.findall(r'"([^"]+node_modules[\\/]\.bin[\\/]codex\.cmd)"', text):
            folders.append(Path(target).parent.parent)
    except OSError:
        pass
    for folder in folders:
        found = sorted(glob.glob(str(folder / "@openai/codex-win32-x64/vendor/*/bin/codex.exe")))
        if found:
            return found[-1]
    return ""


def _prove_codex_exec(service: Any, spec: dict[str, Any]) -> bool:
    """The cheap Codex check: ``codex exec`` in an empty scratch folder with the person's extras off, one file read.

    Returns False when the native Codex program cannot be found (the caller then uses the chat path).
    """
    exe = _codex_native(Path(service.bus.root))
    if not exe:
        return False
    ident, started = spec["id"], time.monotonic()
    receipt: dict[str, Any] = {"id": ident, "at": _now(), "ok": False, "steps": [], "kind": "round-trip", "route": "codex exec, extras off"}

    def step(name: str, ok: bool, detail: str) -> None:
        receipt["steps"].append({"step": name, "ok": ok, "detail": detail[:300]})
        _proving[ident] = {"step": name, "startedAt": receipt["at"]}

    try:
        folder = Path(service.bus.root) / ".neyvia" / "connections" / "check-codex-exec"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():
            old.unlink()
        word = "neyvia-" + secrets.token_hex(4)
        (folder / "connection-check.txt").write_text(word, encoding="utf-8")
        argv = [exe, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-C", str(folder),
                "-c", "mcp_servers={}", "-c", "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
                "-c", "include_apply_patch_tool=false", "-c", "skills.bundled.enabled=false"]
        for feature in _CODEX_OFF:
            argv += ["--disable", feature]
        argv.append("-")
        step("start", True, "Codex in an empty folder, read-only, plugins and extra tools off")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        prompt = f"Use your shell tool to read {folder / 'connection-check.txt'}. On Windows use Get-Content -LiteralPath. Reply with only the exact file text."
        done = subprocess.run(argv, input=prompt, cwd=str(folder), capture_output=True,  # noqa: S603
                              text=True, encoding="utf-8", errors="replace", timeout=PROOF_SECONDS, creationflags=flags, check=False)
        tools, text, usage = 0, "", {}
        for line in done.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                tools += int(item.get("exit_code") == 0)
            elif event.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = str(item.get("text") or "")
            elif event.get("type") == "turn.completed":
                usage = event.get("usage") or {}
        receipt["usage"] = {"inputTokens": usage.get("input_tokens"), "cachedInputTokens": usage.get("cached_input_tokens"),
                            "outputTokens": usage.get("output_tokens")}
        step("tool call", tools > 0, f"{tools} tool call(s) in the turn")
        step("answer", word in text, "The reply contained the one-time word." if word in text else "The reply did not contain the word.")
        receipt["ok"] = tools > 0 and word in text
    except subprocess.TimeoutExpired:
        step("error", False, f"Codex did not finish within {int(PROOF_SECONDS)} s")
    except Exception as exc:  # noqa: BLE001
        step("error", False, f"{type(exc).__name__}: {exc}")
    finally:
        receipt["ms"] = round((time.monotonic() - started) * 1000)
        try:
            stored = service.bus.get(RECEIPT_KEY, {})
            stored = stored if isinstance(stored, dict) else {}
            stored[ident] = receipt
            service.bus.put(RECEIPT_KEY, stored)
        except Exception:  # noqa: BLE001
            pass
        _proving.pop(ident, None)
    return True


def _native_round_trip(service: Any, spec: dict[str, Any], folder: Path, prompt: str) -> tuple[str, int]:
    """Use the existing external harness bridge, its read-only isolation and event parser."""
    import sys
    from .harness_registry import merge_harness_launch_env
    env = merge_harness_launch_env(Path(service.bus.root), spec["id"], base_env=connections_install.environment(folder))
    if spec["id"] == "gptme" and service.backend:
        # The supported keys stay in the child environment, never a file, argv or receipt.
        service.backend._fresh_provider_auth_presence(["openai", "anthropic", "openrouter"])
        with service.backend._provider_secrets_lock:
            for provider, name in (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
                value = service.backend.provider_secrets.get(provider)
                if value:
                    env[name] = value
    argv = [sys.executable, str(Path(__file__).with_name("external_cli_bridge.py")), "--runtime", spec["id"],
            "--command", _which(spec["command"], folder), "--prompt", prompt, "--mode", "chat",
            "--permission-mode", "read-only", "--workspace-root", str(folder)]
    done = connections_install.run_hidden(argv, folder, lambda _: None, timeout=PROOF_SECONDS, env=env)
    tools, text = 0, ""
    for line in done.stdout.splitlines():
        if not line.startswith("FLUXIO_EVENT:"):
            continue
        event = json.loads(line.removeprefix("FLUXIO_EVENT:"))
        if event.get("kind") == "runtime.tool":
            tools += 1
        elif event.get("kind") == "runtime.model_message":
            text = str(event.get("message") or "")
    if done.returncode:
        raise RuntimeError("The harness could not complete its test. Check the provider sign-in, API key and available plan credit, then try again.")
    return text, tools


def _prove_worker(service: Any, spec: dict[str, Any], long_chat: bool) -> None:
    ident = spec["id"]
    if ident == "codex" and not long_chat and _prove_codex_exec(service, spec):
        return
    started = time.monotonic()
    receipt: dict[str, Any] = {"id": ident, "at": _now(), "ok": False, "steps": [], "kind": "round-trip"}

    def step(name: str, ok: bool, detail: str) -> bool:
        receipt["steps"].append({"step": name, "ok": ok, "detail": detail[:300]})
        _proving[ident] = {"step": name, "startedAt": receipt["at"]}
        return ok

    try:
        folder = Path(service.bus.root) / ".neyvia" / "connections" / f"check-{ident}"
        folder.mkdir(parents=True, exist_ok=True)
        word = "neyvia-" + secrets.token_hex(4)
        (folder / "connection-check.txt").write_text(word, encoding="utf-8")
        if spec.get("nativeProof"):
            step("start", True, f"{spec['label']} in an isolated scratch folder, read-only")
            text, tools = _native_round_trip(service, spec, folder, "Read connection-check.txt with your file tool. Reply with only its exact text.")
            step("tool call", tools > 0, f"{tools} tool call(s) in the turn")
            step("answer", word in text, "The reply contained the one-time word." if word in text else "The reply did not contain the word.")
            receipt["ok"] = tools > 0 and word in text
            return
        broker = service.broker()
        options: dict[str, Any] = {}
        for _attempt in range(2):  # the app's first answer after a cold start can be slow; the chat itself does not need it
            try:
                options = broker.provider_options(spec["app"])
                break
            except Exception:  # noqa: BLE001
                options = {}
        mode = _lowest_mode(options)
        model = spec.get("proofModel") or None
        request: dict[str, Any] = {k: v for k, v in {"model": model, "permissionMode": mode}.items() if v}
        step("start", True, f"{spec['label']} chat in a scratch folder, {mode or 'default'} mode" + (f", {model}" if model else ""))
        mission = ("Mission: connection check. Checklist: [x] read connection-check.txt  [ ] report the word. "
                   if long_chat else "")
        prompt = (mission + "Use your file-reading tool to read connection-check.txt in the current folder, "
                  "then reply with only the exact text it contains.")
        run = broker.new(spec["app"], str(folder), prompt, "conn-" + secrets.token_hex(6), request)
        run = _wait_run(broker, run["runId"], started + PROOF_SECONDS)
        session = run.get("sessionId")
        receipt.update(runId=run.get("runId"), sessionId=session, model=run.get("model"), usage=run.get("usage"))
        if run.get("state") != "completed":
            step("answer", False, f"The run ended {run.get('state')}: {run.get('error') or 'no answer'}")
            return
        page = broker.read(session) if session else {"items": []}
        text, tools = _text_of(page.get("items") or [])
        step("tool call", tools > 0, f"{tools} tool call(s) in the turn")
        step("answer", word in text, "The reply contained the one-time word." if word in text else "The reply did not contain the word.")
        receipt["ok"] = tools > 0 and word in text
        if long_chat and receipt["ok"]:
            receipt["kind"] = "round-trip+long-chat"
            compact = _when_free(lambda: broker.compact(session, request))
            done = _wait_run(broker, compact["runId"], started + PROOF_SECONDS * 2)
            step("compact", done.get("state") == "completed", f"Compaction {done.get('state')}")
            if done.get("state") == "completed":
                follow = _when_free(lambda: broker.send(session, "Which checklist item is still open, and what was the word in connection-check.txt? Answer in one line.",
                                                        "conn-" + secrets.token_hex(6), request))
                after = _wait_run(broker, follow["runId"], started + PROOF_SECONDS * 3)
                page = broker.read(session)
                text, _ = _text_of(page.get("items") or [])
                kept = word in text and "report" in text.lower()
                step("after compaction", after.get("state") == "completed" and kept,
                     "Mission checklist and the word survived the compaction." if kept else "The reply lost the checklist or the word.")
                receipt["ok"] = receipt["ok"] and kept
    except Exception as exc:  # noqa: BLE001 - the proof reports why, it never crashes the service
        receipt["ok"] = False
        step("error", False, f"{type(exc).__name__}: {exc}")
    finally:
        receipt["ms"] = round((time.monotonic() - started) * 1000)
        try:
            stored = service.bus.get(RECEIPT_KEY, {})
            stored = stored if isinstance(stored, dict) else {}
            stored[ident] = receipt
            service.bus.put(RECEIPT_KEY, stored)
        except Exception:  # noqa: BLE001
            pass
        _proving.pop(ident, None)


def prove(service: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Run the real round trip for a signed-in harness, in the background. Poll status for the receipt."""
    if args.get("fromClick") is not True:
        raise ValueError("Testing uses your plan: use the Test button on the connection")
    ident = str(args.get("id") or "")
    spec = next((row for row in SPECS if row["id"] == ident), None)
    if not spec or not (spec.get("app") or spec.get("nativeProof")):
        raise ValueError("Neyvia can only test a supported harness")
    if args.get("longChat") and spec.get("nativeProof"):
        raise ValueError("This harness supports the tiny round-trip test; long-chat tests need a connected-session adapter.")
    card = _card(service, ident)
    with _lock:
        if not card or card["state"] != "connected":
            raise ValueError(f"{spec['label']} is not signed in, so there is nothing to test yet")
        if ident in _proving:
            return {"ok": True, "started": False, "proving": _proving[ident]}
        _proving[ident] = {"step": "start", "startedAt": _now()}
    thread = threading.Thread(target=_prove_worker, args=(service, spec, bool(args.get("longChat"))), name=f"connections-prove-{ident}", daemon=True)
    thread.start()
    return {"ok": True, "started": True, "proving": _proving.get(ident)}


def request(backend: Any, service: Any, body: dict[str, Any], method: str) -> dict[str, Any]:
    if method == "GET":
        return status(backend, service)
    operation = body.get("operation")
    if operation == "status":
        return status(backend, service, force=bool(body.get("force")))
    if operation == "connect":
        return connect(service, body)
    if operation == "cancel-signin":
        _signing.discard(str(body.get("id") or ""))
        return {"ok": True}
    if operation == "install":
        def finished(ident: str) -> None:
            spec = next(row for row in SPECS if row["id"] == ident)
            card = _harness_card(spec, Path(service.bus.root), _key_presence(backend))
            with _lock:
                if _cache["value"]:
                    _cache["value"]["byId"][ident] = card
                _cache["partial"][ident] = card
                _cache["at"] = 0.0
        return connections_install.install(service, body, finished)
    if operation == "prove":
        return prove(service, body)
    raise ValueError("Use status, install, connect, cancel-signin or prove")


def call(service: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "connections.inspect":
        result = status(service.backend, service, force=bool(args.get("force")))
        card = next((row for row in result["cards"] if row["id"] == args["id"]), None)
        if not card:
            raise ValueError("Unknown connection")
        return {"ok": True, **card, "installed": bool(card.get("version")) and card["state"] != "installing"}
    return request(service.backend, service, {**args, "operation": name.split(".", 1)[1]}, "POST")
