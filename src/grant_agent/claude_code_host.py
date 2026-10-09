"""Neyvia's side of the Claude Code mod: the endpoints under ``/api/ui/claude-code/mod/`` (plan 29 section A).

The mod (``plugins/neyvia``) runs inside Claude Code and keeps no decisions of its own. It asks this module for the
static prompt section, the tool list, the rules, the stop gate and the changed-state notes, and it reports back.
Everything is keyed on the Claude session id, because plan-limits runs start a new ``claude`` per turn and the run
id changes every time. Nothing here approves a tool call; approvals stay with the person in Neyvia.

Two ideas keep the plan's token use low: the static text is built once and is byte-identical across turns (it can
sit in the cached prefix), and everything that changes (work board, memory recall, queued messages, attention) travels
as a small diff that the mod adds as model-only context.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .ui_command_bus import now

VERSION = "1"
ADHOC = "adhoc"
MAX_SECTION = 6000
MAX_STATE_TEXT = 1200
MAX_BLOCKS = 2
STOP_SECONDS = 20
CORE = ("activity", "message", "tools.search", "tools.describe", "tools.call", "manual.run", "plan.update", "laya.glance")
# These are the model-facing neyvia.* tools the mod serves. PORTED.md in the plugin says why the others are left out
# (approve/decline, claude.mods, nas.*, credentials and approval-gated spenders such as image.generate or video render).
PORTED = frozenset({
    "comments.list", "comments.add", "comments.resolve", "comments.send",
    "verify", "verify.status",
    "browser.state", "browser.open", "browser.tab", "browser.observe", "browser.action", "browser.history", "browser.downloads",
    "browser.decide", "browser.receipt", "browser.promote", "browser.capture", "browser.wait", "browser.task.pause",
    "onboarding.state", "onboarding.recommend", "onboarding.open",
    "cl", "cl.describe", "state", "attention.list", "notify", "manual.index", "manual.load", "manual.observe", "manual.run",
    "manual.validate", "manual.frontier", "manual.patches", "manual.project", "manual.versions", "manual.patch.apply",
    "manual.demote", "manual.recovery.bind", "manual.recover", "manual.compile", "manual.compiled", "manual.script.run",
    "autopilot.start", "autopilot.get", "autopilot.list", "autopilot.stop", "autopilot.resume",
    "parallel.start", "parallel.state", "parallel.ask", "parallel.answer", "parallel.done",
    "parallel.merge", "parallel.resolved", "parallel.finish", "parallel.settle", "parallel.stop",
    "folder.list", "folder.open", "folder.create", "project.create",
    "artifact.publish", "artifact.list", "artifact.get", "artifact.open", "app.open",
    "remote.state", "remote.windows", "remote.snapshot", "remote.log",
    "gamedev.status", "gamedev.sessions", "gamedev.receipt", "gamedev.receipts", "gamedev.state", "gamedev.asset_validate",
    "session.new", "session.rename", "session.pin", "session.move", "session.archive", "session.cluster",
    "pane.show", "pane.observe", "view.state", "view.place", "view.layout", "view.arrange", "view.scene", "view.float",
    "view.theme", "view.transparency", "view.transparency.state", "terminal.list", "terminal.read",
    "settings.get", "settings.propose", "settings.setup", "settings.network_check",
    "schedule.create", "schedule.list", "schedule.cancel", "schedule.after",
    "watch.create", "watch.list", "watch.cancel",
    "time.now", "time.budget", "timer.start", "timer.read", "timer.lap", "timer.stop", "timer.list",
    "mission.list", "mission.create", "mission.control", "runtime.list", "lab.state",
    "evolver.state", "evolver.lineage", "evolver.receipt", "evolver.genome", "evolver.run", "evolver.job",
    "scroll.import", "scroll.concepts", "scroll.generate", "scroll.job", "scroll.validate", "scroll.review", "scroll.pack",
    "scroll.preview", "scroll.send", "scroll.stats", "scroll.state",
    "pdf.state", "pdf.open", "pdf.goto", "pdf.search", "pdf.highlight", "pdf.extract_text", "pdf.zoom",
    "image.state", "image.open", "image.crop", "image.resize", "image.composite", "image.export",
    "claude.runs", "work.claim", "work.release", "work.list", "impact", "intent.checklist", "plan.update",
    "agents.state", "agents.limits", "agents.overview", "activity", "message",
    "nightshift.summary",
    "modules.list", "modules.get", "modules.source", "modules.validate",
    "marketplace.list", "marketplace.get", "marketplace.read", "marketplace.install", "marketplace.set", "marketplace.update",
    "efficiency.laya_verify",
    # LAYA looks and the read side of video/scene judging (plan 29 section 2, item 1). Rendering and learning stay out.
    "scene.vocabulary", "scene.transcribe", "laya.judge", "laya.glance", "laya.glance_contracts", "laya.glance_proof",
    "video.timeline", "video.transcribe", "video.judge", "video.contracts", "video.contact_sheet",
})
# Never offered, whatever the catalog says.
EXCLUDED = frozenset({"image.generate", "claude.mods", "claude.open_cli", "video.render", "video.improve", "video.studio"})
# These run straight through the gateway: they are the mod's own coordination verbs, not CL-guarded world changes.
DIRECT = frozenset({"activity", "message", "plan.update", "work.claim", "work.release", "work.list", "intent.checklist",
                    "notify", "claude.runs", "agents.state", "agents.limits", "agents.overview", "mission.list"})
ROLES = (
    {"name": "scout", "description": "Fast read-only exploration: find files, read code, answer where and what.",
     "prompt": "You explore and report. Read, search and summarize; never edit files. Answer in a few lines with file paths.",
     "model": "haiku", "effort": "low", "tools": ["Read", "Grep", "Glob", "Bash"]},
    {"name": "builder", "description": "Implements one well-scoped change and checks it runs.",
     "prompt": "You implement exactly the change you are given, keep the diff small, run what proves it works, and report what changed.",
     "model": "sonnet", "effort": "medium"},
    {"name": "verifier", "description": "Independently checks finished work against its goal and reports failures.",
     "prompt": "You verify, you do not fix. Run the real behavior, compare against the stated goal, and list each failure with evidence.",
     "model": "opus", "effort": "high", "tools": ["Read", "Grep", "Glob", "Bash"]},
)
_SESSION = re.compile(r"[A-Za-z0-9_-]{1,100}")
_RUN = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_lock = threading.RLock()
_sent: dict[str, dict[str, Any]] = {}      # session -> {"hash": ..., "parts": {...}} last state sent
_links: dict[str, dict[str, Any]] = {}     # session -> {"run": ..., "adhoc": bool, "cwd": ..., "at": ...}
_memory: dict[str, str] = {}               # run id -> recall section to deliver as context
_notes: dict[str, str] = {}                # run id -> the long intent-checklist note for a many-asks message
_mailbox: dict[str, list[dict[str, Any]]] = {}   # session -> queued messages (events)
_blocks: dict[str, int] = {}               # session -> stop blocks so far this session
_serial = [0]
_writer = None
_mirror: dict[str, dict[str, Any]] = {}    # session -> {"items": [{text,status}], "at": monotonic}: the checklist as last published


def _later(fn, *args):
    """SQLite commits take 0.3-1.5 s on a busy disk; the mod never waits for one. Writes run in order on one worker."""
    global _writer
    from concurrent.futures import ThreadPoolExecutor
    with _lock:
        if _writer is None:
            _writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mod-host-write")

    def run():
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001 - a failed display write must not take the worker down
            pass
    return _writer.submit(run)


def remember_checklist(session: str, rows: list[dict[str, Any]]) -> None:
    with _lock:
        _mirror[session] = {"items": [{"text": str(r.get("text") or r.get("step") or ""), "status": r.get("status")} for r in rows],
                            "at": time.monotonic()}


def _open_items(root: Path, session: str) -> list[dict[str, Any]]:
    from .ui_command_bus import bus_for
    from .claude_code_mods import RUNS
    mirror = _mirror.get(session)
    if mirror and time.monotonic() - mirror["at"] < 6 * 3600:
        items = mirror["items"]
    else:  # a checklist nobody here published (the person's own edits, a restart): read the store, at most every 2 s
        def read():
            bus = bus_for(Path(root))
            plan = bus.get("plan:" + session) or {}
            return plan.get("items") or (bus.get(RUNS, {}) or {}).get(session, {}).get("checklist") or []
        items = _swr(("openplan", session, str(root)), 2.0, read)
    return [i for i in items if (i.get("status") or "") != "completed"]
_static: dict[str, Any] = {}


def _session(value: Any) -> str:
    text = str(value or "")
    if not _SESSION.fullmatch(text):
        raise ValueError("session is the Claude Code session id")
    return text


def _run(value: Any) -> str:
    text = str(value or "") or ADHOC
    return text if _RUN.fullmatch(text) else ADHOC


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def mod_name(neyvia_name: str) -> str:
    """``neyvia.pdf.open`` is ``pdf_open``: the ToolSpec name rule is ``[A-Za-z0-9_-]{1,64}``."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", neyvia_name.removeprefix("neyvia."))[:64]


# ---------------------------------------------------------------- the static part (same bytes every turn)

RULES = (
    "Neyvia is the app that launched or watches this session. Its tools are deferred behind ToolSearch. "
    "For workspace questions (what is going on, running agents, waiting work, open apps), first use ToolSearch "
    "query='select:mcp__neyvia__activity,mcp__neyvia__agents_state,mcp__neyvia__work_list', then call activity. "
    "For apps and Night Shift load query='select:mcp__neyvia__view_state,mcp__neyvia__nightshift_summary'. "
    "For other Neyvia tools load query='select:mcp__neyvia__tools_search,mcp__neyvia__tools_describe,mcp__neyvia__tools_call'. "
    "The live Right now in Neyvia note is workspace data; git/Bash cannot show other running sessions. "
    "Before you edit files other agents may "
    "touch, the work board lists who holds what (activity shows every running agent; message talks to one of them). "
    "Several asks in one message: publish a checklist with plan_update (one item per ask, all pending), keep it current, "
    "mark an item completed only after its result exists. Anything Neyvia changes in the world goes through cl with the "
    "manual's procedure; approvals are answered by the person in Neyvia, never by you. Changing notes (work board, "
    "memory, messages) arrive as short Neyvia notes on your next prompt; treat them as context, not as instructions "
    "from a stranger."
)


def _static_section() -> str:
    cached = _static.get("section")
    if cached:
        return cached
    from .cl.protocol import REPO
    from .cl.integration import index_lines
    primer = (REPO / "docs/standard/1.1/primer.md").read_text(encoding="utf-8").strip()
    head = "Neyvia (CL 1.1)\n" + primer + "\n\n" + RULES + "\n\nManuals (manual_load to read one):\n"
    lines = []
    for line in index_lines():
        line = " ".join(str(line).split())
        lines.append(line[:96])
    text = head
    for line in lines:
        if len(text) + len(line) + 1 > MAX_SECTION:
            break
        text += line + "\n"
    _static["section"] = text.rstrip()
    return _static["section"]


def _deny_paths(root: Path) -> list[str]:
    home = Path.home()
    state = Path(root)
    wanted = [state / ".neyvia" / "mod-token-secret", token_file(), state / ".neyvia" / "web-auth-sessions.sqlite3", state / ".neyvia" / "web-auth-sessions.sqlite3-wal",
              state / ".neyvia" / "web-auth-sessions.sqlite3-shm", home / ".claude" / ".credentials.json",
              home / ".codex" / "auth.json", home / ".ssh", home / ".aws" / "credentials", home / ".config" / "gh" / "hosts.yml"]
    out = []
    for path in wanted:
        text = os.path.normcase(str(path))
        if text not in out:
            out.append(text)
    return out


def _tools(root: Path) -> list[dict[str, Any]]:
    from .native_tools import NativeToolRegistry
    rows = NativeToolRegistry(Path(root)).list_tools(include_schemas=True, prefix="neyvia.")
    tools = []
    for row in rows:
        short = str(row["name"]).removeprefix("neyvia.")
        trusted_mod = bool(re.fullmatch(r"mod\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", short))
        if short in EXCLUDED or (short not in PORTED and not trusted_mod) or row.get("available") is False:
            continue
        schema = row.get("inputSchema") if isinstance(row.get("inputSchema"), dict) else {"type": "object", "properties": {}}
        tools.append({"name": mod_name(row["name"]), "neyviaName": row["name"],
                      "description": " ".join(str(row.get("description") or "").split())[:1000],
                      "inputSchema": schema, "deferred": short not in CORE})
    pseudo = [
        ("tools.search", "Find Neyvia tool names and purposes; schemas load on describe.",
         {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
        ("tools.describe", "Load one exact Neyvia tool schema (neyvia.<name>).", {"name": {"type": "string"}}, ["name"]),
        ("tools.call", "Call a discovered Neyvia tool; existing approvals apply.",
         {"tool": {"type": "string"}, "arguments": {"type": "object"}}, ["tool", "arguments"]),
    ]
    for short, description, props, required in pseudo:
        tools.append({"name": mod_name(short), "neyviaName": "neyvia." + short, "description": description,
                      "inputSchema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
                      "deferred": False})
    tools.sort(key=lambda row: row["name"])
    return tools


# ---------------------------------------------------------------- caches: the hot paths never touch SQLite or the registry

_swr_lock = threading.Lock()
_swr_cache: dict[Any, list[Any]] = {}   # key -> [value, computed_at, refreshing]
STATIC_TTL = 120.0


def _swr(key: Any, ttl: float, compute) -> Any:
    """Last value at once; recomputed in the background when older than ``ttl`` (the first call computes in place)."""
    with _swr_lock:
        entry = _swr_cache.get(key)
        if entry is not None and time.monotonic() - entry[1] < ttl:
            return entry[0]
        if entry is not None and entry[2]:
            return entry[0]
        if entry is not None:
            entry[2] = True

            def refresh():
                try:
                    value = compute()
                    with _swr_lock:
                        _swr_cache[key] = [value, time.monotonic(), False]
                except Exception:  # noqa: BLE001 - keep serving the last value
                    with _swr_lock:
                        entry[2] = False
            threading.Thread(target=refresh, name="mod-host-refresh", daemon=True).start()
            return entry[0]
    value = compute()
    with _swr_lock:
        _swr_cache[key] = [value, time.monotonic(), False]
    return value


def _pack(root: Path) -> dict[str, Any]:
    """The static part of the bootstrap, built once and refreshed in the background; its digest is the cheap version stamp."""
    key = ("pack", str(Path(root).resolve()))

    def build():
        body = {"version": VERSION, "section": {"text": _static_section()}, "tools": _tools(root),
                "denyPaths": _deny_paths(root), "roles": [dict(role) for role in ROLES], "contracts": ["checklist"]}
        body["digest"] = _digest(body)
        return body
    return _swr(key, STATIC_TTL, build)


GATE_SETTING = "claudeCodeGate"


def _setting(root: Path, key: str) -> bool:
    from .ui_command_bus import bus_for
    return _swr(("setting", key, str(root)), 5.0,
                lambda: (bus_for(Path(root)).get(key, {}) or {}).get("enabled", True) is not False)


def _gate_enabled(root: Path) -> bool:
    return _setting(root, GATE_SETTING)


_board_memo: dict[str, Any] = {}


def _board_rows(root: Path) -> tuple[Any, list[dict[str, Any]]]:
    """Work-board claims, re-read only when the board file changed (a stat is the stamp)."""
    from .neyvia_awareness import board_list, board_path
    try:
        stat = board_path(root).stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    memo = _board_memo.get(str(root))
    if memo and memo[0] == stamp and time.monotonic() - memo[2] < 1:
        return stamp, memo[1]
    try:
        rows = [row for row in board_list(root, {})["claims"] if not row["stale"]]
    except Exception:  # noqa: BLE001
        rows = []
    _board_memo[str(root)] = (stamp, rows, time.monotonic())
    return stamp, rows


def _claim_rows(root: Path, session: str) -> list[dict[str, Any]]:
    return [row for row in _board_rows(root)[1] if row.get("chat") not in {session} and
            not (session and str(row.get("chat") or "").endswith(":" + session))]


def _board_lines(root: Path, session: str) -> list[str]:
    return [f"{row['agent']} edits {', '.join(row['files'])} ({row['intent']}) since {row['since'][11:16]}" for row in _claim_rows(root, session)]


def _plan_text(root: Path, session: str) -> str | None:
    from .ui_command_bus import bus_for
    from .connected_sessions.plan import plan_summary

    mirror = _mirror.get(session)
    if mirror:
        rows = mirror["items"]
        done = sum(1 for r in rows if r.get("status") == "completed")
        now_row = next((r for r in rows if r.get("status") == "in_progress"), None)
        return f"Checklist {done}/{len(rows)}" + (f", now: {now_row['text']}" if now_row else "") if rows else None

    def read():
        summary = plan_summary(bus_for(Path(root)).get("plan:" + session))
        return None if not summary else f"Checklist {summary['done']}/{summary['total']}" + (f", now: {summary['current']}" if summary.get("current") else "")
    return _swr(("plan", session, str(root)), 3.0, read)


def _attention_text(root: Path) -> str | None:
    def read():
        try:
            from .neyvia_attention import call as attention
            from .neyvia_workspace_tools import workspace_for
            listing = attention(workspace_for(root, _ctx.get("backend")), {})
            rows = listing.get("items") or listing.get("attention") or []
            return "Needs the person: " + "; ".join(str(r.get("title") or r.get("text") or r)[:80] for r in rows[:3]) if rows else None
        except Exception:  # noqa: BLE001 - attention is a nicety; a failure is cached as "nothing" like a success
            return None
    return _swr(("attention", str(root)), 20.0, read)


def _parts(root: Path, session: str, *, quiet: bool = False) -> dict[str, str]:
    parts: dict[str, str] = {}
    from .claude_code_activity import live_context
    live = live_context(root, session, _ctx.get("backend"))
    if live:
        parts["live"] = live
    board = _board_lines(root, session)
    parts["board"] = "Work board: " + ("; ".join(board) if board else "no other live claims.")
    link = _links.get(session) or {}
    memory = _memory.get(str(link.get("run") or ""))
    if memory:
        parts["memory"] = memory.strip()
    if not quiet:
        for key, text in (("checklist", _plan_text(root, session)), ("attention", _attention_text(root))):
            if text:
                parts[key] = text
    if not link.get("adhoc"):
        queued = [e for e in _mailbox.get(session, []) if not e.get("seen")]
        if queued:
            parts["messages"] = "Messages: " + " | ".join(f"{e.get('from') or 'Neyvia'}: {e['text']}" for e in queued)[:600]
    return parts


def state(root: Path, session: str, since: str | None, run: str | None = None) -> dict[str, Any]:
    session = _session(session)
    root = Path(root)
    with _lock:
        if run:
            link = _links.setdefault(session, {"run": _run(run), "adhoc": _run(run) == ADHOC, "at": now()})
            link["run"] = _run(run)
        parts = _parts(root, session)
        current = _digest(parts)
        last = _sent.get(session)
        if since and since == current:
            return {"hash": current, "diff": None}
        previous = last["parts"] if last and last["hash"] == since else {}
        changed = {key: text for key, text in parts.items() if previous.get(key) != text}
        removed = [key for key in previous if key not in parts]
        _sent[session] = {"hash": current, "parts": parts}
        if not changed and not removed:
            return {"hash": current, "diff": None}
        if "messages" in changed:
            for event in _mailbox.get(session, []):
                event["seen"] = True
        text = "\n".join(changed.values())[:MAX_STATE_TEXT]
        return {"hash": current, "diff": {"text": text, "parts": changed, "removed": removed}}


def bootstrap(root: Path, session: str, run: str | None, etag: str | None) -> tuple[int, dict[str, Any]]:
    """The If-None-Match comparison comes first, from a stamp built out of cached pieces, so a 304 costs microseconds."""
    session = _session(session)
    run = _run(run)
    root = Path(root)
    pack = _pack(root)
    with _lock:
        link = _links.setdefault(session, {"at": now()})
        first = not link.get("boot")
        link.update({"run": run, "adhoc": run == ADHOC, "at": now(), "boot": True})
        if first:
            _later(_mark_seen, root, session)
        claims = [{"path": f, "holder": row["agent"]} for row in _claim_rows(root, session) for f in row["files"]]
        context = [text for key, text in _parts(root, session, quiet=True).items() if key != "messages"]
        note = _notes.get(run, "")
        gate = _gate_enabled(root)
        stamp = _digest({"pack": pack["digest"], "claims": claims, "context": context, "note": note, "gate": gate})
    tag = '"' + stamp + '"'
    if etag and etag.strip() == tag:
        return 304, {"etag": tag}
    body = {"version": VERSION, "etag": tag, "section": pack["section"],
            "context": {"text": ("\n".join(context)[:MAX_STATE_TEXT * 2] + ("\n" + note if note else ""))},
            "tools": pack["tools"], "rules": {"denyPaths": pack["denyPaths"], "claims": claims},
            "gate": {"enabled": gate, "contracts": pack["contracts"]}, "roles": pack["roles"]}
    return 200, body


def warm(root: Path) -> None:
    """Build the caches before the first request needs them (called when the backend starts serving mod routes)."""
    if root in _warmed_roots:
        return
    _warmed_roots.add(root)
    publish_adhoc_token(Path(root))

    def build():
        _pack(Path(root))
        _board_rows(Path(root))
        try:
            from .claude_code_activity import live_context
            live_context(Path(root), "", _ctx.get("backend"))
            _attention_text(Path(root))
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=build, name="mod-host-warm", daemon=True).start()


# ---------------------------------------------------------------- tools

def _short(name: str) -> str:
    return str(name).removeprefix("neyvia.")


def call_tool(workspace, root: Path, body: dict[str, Any], *, auth: dict[str, Any], owner: str) -> dict[str, Any]:
    session = _session(body.get("session"))
    name = str(body.get("tool") or "")
    args = body.get("args") if isinstance(body.get("args"), dict) else body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
    if not name.startswith("neyvia."):
        return {"ok": False, "error": "tool is a neyvia.* name"}
    short = _short(name)
    catalog = {row["neyviaName"]: row for row in _pack(Path(root))["tools"]}
    if name not in catalog:
        return {"ok": False, "error": f"{name} is not a tool the Claude Code mod offers"}
    if _needs_renderer(short, args):
        try:
            workspace.bus.require_renderer(probe=True, principal=str(auth.get("username") or owner))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    if short == "tools.search":
        query = str(args.get("query") or "").casefold().split()
        limit = max(1, min(int(args.get("limit") or 8), 20))
        found = [row for row in catalog.values() if all(t in (row["neyviaName"] + " " + row["description"]).casefold() for t in query)]
        found.sort(key=lambda row: row["neyviaName"])
        return {"ok": True, "result": {"tools": [{"name": r["neyviaName"], "description": r["description"][:200]} for r in found[:limit]],
                                       "next": "tools_describe"}}
    if short == "tools.describe":
        row = catalog.get(str(args.get("name") or ""))
        if row is None:
            return {"ok": False, "error": "Unknown exact tool name; use tools_search."}
        return {"ok": True, "result": {"name": row["neyviaName"], "description": row["description"], "inputSchema": row["inputSchema"]}}
    if short == "tools.call":
        inner = str(args.get("tool") or "")
        inner_args = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        if inner not in catalog or _short(inner).startswith("tools."):
            return {"ok": False, "error": "Unknown exact tool name; describe a discovered tool first."}
        return call_tool(workspace, root, {"session": session, "tool": inner, "args": inner_args}, auth=auth, owner=owner)
    direct = _direct(workspace, Path(root), short, args, session)
    if direct is not None:
        return direct
    from .neyvia_cl import call_owner, owner_protocol
    try:
        if short in DIRECT:
            protocol = owner_protocol(workspace, auth, owner)
            if short == "work.claim":
                args = {**args, "chat": session}
            result = protocol.gateway.call_native(name, args)
        else:
            result = call_owner(workspace, name, args, session=auth, owner=owner)
            # Parallel's native mod buttons execute the owning observer-bound CL recipe.
            # This keeps the same grants and effect checks without requiring a second model call.
            if short.startswith("parallel.") and isinstance(result, dict) and result.get("status") == "cl_goal_required":
                recovery = result.get("recovery") or {}
                if recovery.get("tool") == "neyvia.cl":
                    result = call_owner(workspace, "neyvia.cl", {**recovery["arguments"], "scopeTools": sorted(catalog)},
                                        session=auth, owner=owner)
    except Exception as exc:  # noqa: BLE001 - the mod gets the reason, not a stack
        return {"ok": False, "error": str(exc)[:500]}
    if isinstance(result, dict) and result.get("schema") == "fluxio.native_tool_receipt.v1":
        result = result.get("result") if result.get("ok") is not False else {**result, "ok": False}  # the mod wants the value, not the receipt
    if isinstance(result, dict) and result.get("ok") is False:
        return {"ok": False, "error": str(result.get("error") or result.get("status") or "The tool failed")[:2000], "result": result}
    return {"ok": True, "result": result}


def _needs_renderer(short: str, args: dict) -> bool:
    """Refuse mod UI intents before cold CL loading or durable mutation."""
    tools = {'view.theme', 'view.arrange', 'view.scene', 'view.place', 'view.float',
             'pane.show', 'app.open', 'notes.open', 'onboarding.open'}
    if short in tools:
        return True
    if short != 'cl':
        return False
    procedures = {'neyvia.set-theme', 'neyvia.show-pane', 'neyvia.open-app',
                  'neyvia.open-notes', 'neyvia.arrange-view', 'neyvia.switch-scene'}
    calls = set(re.findall(r'\b([A-Za-z_][\w.-]*)\s*\(', str(args.get('lines') or '')))
    return bool(calls & (tools | {'neyvia.' + tool for tool in tools} | procedures))


def _direct(workspace, root: Path, short: str, args: dict[str, Any], session: str) -> dict[str, Any] | None:
    """The mod's own coordination verbs run in-process: no gateway, receipts or registry on the hot path."""
    try:
        if short == "activity":
            from .claude_code_activity import activity
            value = activity(workspace, args)
        elif short == "message":
            from .claude_code_activity import message
            value = message(workspace, {**args, "from": args.get("from") or "a Claude Code session", "_fromSession": session})
        elif short == "plan.update":
            from .neyvia_intent_plan import publish_plan
            # The checklist is keyed on the Claude session id, the same key the stop gate reads.
            sid = args.get("sessionId")
            payload = {**args, "sessionId": session if not sid or sid == "unscoped" else sid}
            from .neyvia_intent_plan import validate_plan
            steps = validate_plan(payload.get("plan"))
            if payload["sessionId"] == session:
                remember_checklist(session, [{"text": row["step"], "status": row["status"]} for row in steps])
            if any(row.get("doneWhen") for row in steps):
                value = publish_plan(root, payload)  # a doneWhen is checked against real observers before it is accepted
            else:
                _later(publish_plan, root, payload)  # four SQLite writes: stored in order, the gate already sees the mirror
                value = {"ok": True, "queued": True, "sessionId": payload["sessionId"], "providerCalls": 0,
                         "plan": {"items": [{"text": row["step"], "status": row["status"]} for row in steps]}}
        elif short in {"work.claim", "work.release", "work.list"}:
            from .neyvia_awareness import call
            link = _links.get(session) or {}
            run_id = link.get("run")
            value = call(workspace, short, {**args, "chat": session, "runId": run_id if run_id != ADHOC else None, "app": "claude-code"}
                         if short == "work.claim" else args)
        else:
            return None
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}
    if isinstance(value, dict) and value.get("ok") is False:
        return {"ok": False, "error": str(value.get("error") or "The tool failed")[:2000], "result": value}
    return {"ok": True, "result": value}


# ---------------------------------------------------------------- scoped mod tokens (no per-process sign-in)
#
# POST /api/auth/local-session costs 2-29 s on a busy disk (it issues a session row, then looks it up: three SQLite
# transactions with synchronous=FULL, each an fsync). A plan-limits run starts a new claude per turn, so the mod would pay
# that every turn. Instead Neyvia mints a token when it launches a run (env NEYVIA_MOD_TOKEN) and keeps one for the
# person's own sessions in a file the installed plugin reads. Both work on /api/ui/claude-code/mod/* only.

import hmac
import secrets

TOKEN_ENV = "NEYVIA_MOD_TOKEN"
TOKEN_FILE_ENV = "NEYVIA_MOD_TOKEN_FILE"
TOKEN_HEADER = "X-Neyvia-Mod-Token"
RUN_TOKEN_SECONDS = 12 * 3600
ADHOC_TOKEN_SECONDS = 30 * 24 * 3600
_secrets: dict[str, bytes] = {}
_revoked: set[str] = set()


def secret_path(root: Path) -> Path:
    return Path(root) / ".neyvia" / "mod-token-secret"


def _secret(root: Path) -> bytes:
    key = str(Path(root).resolve())
    if key not in _secrets:
        path = secret_path(root)
        try:
            _secrets[key] = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            path.parent.mkdir(parents=True, exist_ok=True)
            value = secrets.token_bytes(32)
            path.write_text(value.hex(), encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass
            _secrets[key] = value
    return _secrets[key]


def _sign(root: Path, run: str, expires: int) -> str:
    return hmac.new(_secret(root), f"{run}.{expires}".encode("utf-8"), "sha256").hexdigest()[:40]


def mint(root: Path, run_id: str, seconds: int = RUN_TOKEN_SECONDS) -> str:
    run = _run(run_id)
    expires = int(time.time()) + int(seconds)
    return f"{run}.{expires}.{_sign(root, run, expires)}"


def verify(root: Path, token: str | None) -> str | None:
    """The run id a valid, unexpired, unrevoked token belongs to (``adhoc`` for the person's own sessions)."""
    try:
        run, expires, signature = str(token or "").rsplit(".", 2)
        expires_at = int(expires)
    except ValueError:
        return None
    if run in _revoked or expires_at < time.time() or not _RUN.fullmatch(run):
        return None
    return run if hmac.compare_digest(signature, _sign(root, run, expires_at)) else None


def revoke(run_id: str) -> None:
    with _lock:
        _revoked.add(str(run_id))
        while len(_revoked) > 500:
            _revoked.pop()


def token_file() -> Path:
    return Path(os.environ.get(TOKEN_FILE_ENV) or Path.home() / ".neyvia" / "claude-mod.json")


def publish_adhoc_token(root: Path) -> Path | None:
    """The token the installed plugin reads for a session the person runs themselves (``{backend, token}``).

    Written when the real app serves (or when a proof sets NEYVIA_MOD_TOKEN_FILE), never into a home folder from a proof."""
    backend = os.environ.get("NEYVIA_UI_BACKEND_URL")
    if not backend or (os.environ.get("NEYVIA_ASSIGNED_PORTS") and not os.environ.get(TOKEN_FILE_ENV)):
        return None
    path = token_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"backend": backend, "token": mint(root, ADHOC, ADHOC_TOKEN_SECONDS), "mintedAt": now()})
        path.write_text(payload, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path
    except OSError:
        return None


# ---------------------------------------------------------------- the HTTP boundary

_session_memo: dict[str, tuple[float, dict[str, Any]]] = {}
SESSION_MEMO_SECONDS = 20.0
SESSION_HARD_SECONDS = 300.0
_rechecking: set = set()


def _fast_session(backend, handler) -> dict[str, Any] | None:
    """The same cookie check as ``backend.authenticated_session``, remembered for a few seconds (its SQLite lookup costs
    100-500 ms under load). A logout reaches this route within ``SESSION_HARD_SECONDS``."""
    from http import cookies
    header = handler.headers.get("Cookie") or ""
    parsed = cookies.SimpleCookie()
    try:
        parsed.load(header)
    except cookies.CookieError:
        return None
    from .web_backend import SESSION_COOKIE_NAME
    morsel = parsed.get(SESSION_COOKIE_NAME)
    if not morsel:
        return None
    token = morsel.value
    hit = _session_memo.get(token)
    if hit and time.monotonic() - hit[0] < SESSION_MEMO_SECONDS:
        return hit[1]
    if hit and time.monotonic() - hit[0] < SESSION_HARD_SECONDS:
        # Stale: answer now, check the store in the background (its SQLite lookup can stall for seconds on a busy disk).
        def recheck():
            try:
                again = backend.authenticated_session(handler)
            except Exception:  # noqa: BLE001
                return
            if again:
                _session_memo[token] = (time.monotonic(), again)
            else:
                _session_memo.pop(token, None)
        if token not in _rechecking:
            _rechecking.add(token)
            threading.Thread(target=lambda: (recheck(), _rechecking.discard(token)), daemon=True, name="mod-session-recheck").start()
        return hit[1]
    session = backend.authenticated_session(handler)
    if session:
        _session_memo[token] = (time.monotonic(), session)
        while len(_session_memo) > 32:
            _session_memo.pop(next(iter(_session_memo)))
    else:
        _session_memo.pop(token, None)
    return session


_warmed: set = set()
_warmed_roots: set = set()
_ctx: dict[str, Any] = {}


def serve_http(backend, handler, parsed, method) -> None:
    """``/api/ui/claude-code/mod/*``: payloads are top-level (plan 29 section A), authenticated like the other UI routes."""
    from urllib.parse import parse_qs
    from .web_backend import _json_response, _read_json_body
    root = Path(backend.root)
    if root not in _warmed:
        _warmed.add(root)
        warm(root)
    offered = handler.headers.get(TOKEN_HEADER)
    if offered:  # a scoped mod token: valid for these routes only, never as a general sign-in
        run = verify(Path(backend.root), offered)
        session = {"username": backend.username, "role": "account", "sessionId": "modtoken:" + run, "modToken": True} if run else None
    else:
        session = _fast_session(backend, handler)
    if not session:
        _json_response(handler, 401, {"ok": False, "loginRequired": True})
        return
    if method == "POST" and str(session.get("username") or "").casefold() != backend.username.casefold():
        _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required"})
        return
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    step = parsed.path.rsplit("/", 1)[1]
    root = Path(backend.root)
    _ctx["backend"] = backend
    try:
        if step == "bootstrap" and method == "GET":
            if str(session.get("username") or "").casefold() == backend.username.casefold():
                # Prepare authority-bound interpreter metadata while the
                # session-start hook is waiting, before the first UI intent.
                from .neyvia_cl import owner_protocol
                from .neyvia_workspace_tools import workspace_for
                protocol = owner_protocol(workspace_for(root, backend), session, backend.username)
                # Ground the common UI procedures during session setup, before
                # the model issues an action. This admits metadata only.
                with protocol.lock:
                    protocol._ensure_manuals('\n'.join('run neyvia.' + name + '()' for name in
                        ('set-theme', 'open-app', 'show-pane', 'start-named-timer')))
            code, payload = bootstrap(root, query.get("session"), query.get("run"), handler.headers.get("If-None-Match"))
            if code == 304:
                handler.send_response(304)
                handler.send_header("ETag", payload["etag"])
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
            _json_response(handler, 200, {"ok": True, **payload})
            return
        if step == "state" and method == "GET":
            result = {"ok": True, **state(root, query.get("session"), query.get("since"), query.get("run"))}
        elif step == "inbox" and method == "GET":
            result = {"ok": True, **inbox(root, query.get("session"), query.get("since"))}
        elif step == "tool" and method == "POST":
            from .neyvia_ui_api import bind_backend
            from .neyvia_workspace_tools import workspace_for
            bind_backend(backend)
            result = call_tool(workspace_for(root, backend), root, _read_json_body(handler), auth=session, owner=backend.username)
        elif step == "stop" and method == "POST":
            result = {"ok": True, **stop(root, _read_json_body(handler))}
        elif step == "report" and method == "POST":
            from .ui_command_bus import bus_for
            result = report(bus_for(root), _read_json_body(handler))
        else:
            _json_response(handler, 404, {"ok": False, "error": "Unknown Claude Code mod route"})
            return
        _json_response(handler, 200, result)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass
    except (ValueError, KeyError, TypeError) as exc:
        _json_response(handler, 400, {"ok": False, "error": str(exc)[:500]})
    except Exception as exc:  # noqa: BLE001
        _json_response(handler, 500, {"ok": False, "error": str(exc)[:500]})


# ---------------------------------------------------------------- stop gate

def stop(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    result = _stop(root, body)
    _later(_store_gate, Path(root), _session(body.get("session")), result.get("receipt"))  # a display extra, off the hot path
    return result


def _store_gate(root: Path, session: str, receipt: Any) -> None:
    from .ui_command_bus import bus_for
    from . import claude_code_mods as mods
    if not isinstance(receipt, dict):
        return
    bus = bus_for(root)
    with mods._lock:
        runs = bus.get(mods.RUNS, {}) or {}
        row = dict(runs.get(session) or {"session": session, "files": [], "checklist": [], "state": "idle"})
        row["gate"] = receipt
        runs[session] = row
        bus.put(mods.RUNS, runs)


def _stop(root: Path, body: dict[str, Any]) -> dict[str, Any]:
    from .ui_command_bus import bus_for
    from .claude_code_mods import RUNS
    session = _session(body.get("session"))
    root = Path(root)
    with _lock:
        so_far = _blocks.get(session, 0)
        if not _gate_enabled(root):
            return {"block": None, "failing": [], "receipt": _receipt(session, True, [], so_far, "gate off"), "blocksSoFar": so_far}
        failing: list[dict[str, str]] = []
        open_items = _open_items(root, session)
        if open_items:
            names = "; ".join(str(i.get("text") or i.get("step") or "")[:60] for i in open_items[:4])
            failing.append({"contract": "checklist",
                            "hint": f"{len(open_items)} checklist item(s) still open ({names}). Finish them, mark them completed, "
                                    "or say in your reply why one is blocked and leave it pending."})
        if not failing:
            return {"block": None, "failing": [], "receipt": _receipt(session, True, [], so_far, "all contracts passed"), "blocksSoFar": so_far}
        if so_far >= MAX_BLOCKS:
            return {"block": None, "failing": failing, "receipt": _receipt(session, False, failing, so_far, "unproven: block limit reached"),
                    "blocksSoFar": so_far, "unproven": True}
        _blocks[session] = so_far + 1
        reason = "Neyvia: " + " ".join(f"[{row['contract']}] {row['hint']}" for row in failing)
        return {"block": reason, "failing": failing, "receipt": _receipt(session, False, failing, so_far + 1, "blocked"),
                "blocksSoFar": so_far + 1}


def _receipt(session: str, passed: bool, failing: list[dict[str, str]], blocks: int, note: str) -> dict[str, Any]:
    return {"session": session, "at": now(), "passed": passed, "failing": [row["contract"] for row in failing],
            "blocks": blocks, "note": note}


# ---------------------------------------------------------------- inbox and messages

def queue_message(session: str, text: str, sender: str | None = None) -> dict[str, Any]:
    session = _session(session)
    with _lock:
        _serial[0] += 1
        event = {"id": f"{int(time.time() * 1000)}-{_serial[0]}", "kind": "message", "from": sender or "Neyvia",
                 "text": " ".join(str(text).split())[:2000]}
        box = _mailbox.setdefault(session, [])
        box.append(event)
        del box[:-50]
        return event


def inbox(root: Path, session: str, since: str | None) -> dict[str, Any]:
    session = _session(session)
    with _lock:
        events = _mailbox.get(session, [])
        if since:
            ids = [e["id"] for e in events]
            events = events[ids.index(since) + 1:] if since in ids else events
        claims = _claim_rows(Path(root), session)
        out = [{k: v for k, v in e.items() if k != "seen"} for e in events]
        if claims and (_links.get(session) or {}).get("adhoc") and not since:
            out.append({"id": "claims-" + _digest(claims), "kind": "claims",
                        "claims": [{"path": f, "holder": row["agent"]} for row in claims for f in row["files"]]})
        _links.setdefault(session, {"at": now()})["adhoc"] = True
        return {"events": out, "next": (events[-1]["id"] if events else since)}


def note_memory(run_id: str, section: str | None) -> None:
    """The memory recall for one Neyvia turn travels as mod context, not as text prepended to the person's message."""
    with _lock:
        if section and section.strip():
            _memory[str(run_id)] = (_memory[str(run_id)] + "\n" if _memory.get(str(run_id)) else "") + section
            while len(_memory) > 40:
                _memory.pop(next(iter(_memory)))


def note_turn(run_id: str, text: str) -> None:
    """The long intent note for a message with many asks: delivered once with the turn's first context, never in a diff."""
    with _lock:
        _notes[str(run_id)] = text
        while len(_notes) > 40:
            _notes.pop(next(iter(_notes)))


def forget_run(run_id: str) -> None:
    revoke(run_id)  # a run's token ends with the run
    with _lock:
        _memory.pop(str(run_id), None)
        _notes.pop(str(run_id), None)


SEEN_KEY = "claudeCodeModSeen"


def mod_loaded(root, session: str | None) -> bool:
    """True once the mod fetched its bootstrap in this Claude session (kept across restarts).

    Until then (a session's first turn, or a Claude Code that does not load mods) Neyvia keeps sending its own text,
    so a Claude Code without the mod never loses context."""
    if not session or not _SESSION.fullmatch(str(session)):
        return False
    if (_links.get(session) or {}).get("boot"):
        return True
    from .ui_command_bus import bus_for
    return bool((bus_for(Path(root)).get(SEEN_KEY, {}) or {}).get(session))


def _mark_seen(root: Path, session: str) -> None:
    from .ui_command_bus import bus_for
    bus = bus_for(Path(root))
    seen = bus.get(SEEN_KEY, {}) or {}
    if not seen.get(session):
        seen[session] = now()
        for stale in list(seen)[:-200]:
            seen.pop(stale, None)
        bus.put(SEEN_KEY, seen)


def session_for_run(run_id: str) -> str | None:
    with _lock:
        for session, link in _links.items():
            if link.get("run") == run_id:
                return session
    return None


# ---------------------------------------------------------------- reports

_HELD: dict[str, tuple[str, float]] = {}  # session -> reason Neyvia keeps its hands off (the person opened it in a terminal)


def report(bus, body: dict[str, Any]) -> dict[str, Any]:
    """One report from the mod; the rows live in ``claude_code_mods.record_report`` (the dashboard reads them)."""
    from .claude_code_mods import record_report
    session = _session(body.get("session"))
    kind = body.get("kind")
    body = {**body, "session": session}
    if kind == "edits":
        paths = body.get("paths") if isinstance(body.get("paths"), list) else []
        for path in paths[:50]:
            record_report(bus, {"session": session, "kind": "edit", "path": str(path)})
        return {"ok": True, "session": session, "kept": len(paths[:50])}
    if kind == "turn" and "state" not in body:
        body["state"] = "idle"
    if kind == "checklist":
        body["items"] = [{"text": row.get("text") or row.get("content") or row.get("subject") or row.get("step"),
                          "status": row.get("status")} for row in (body.get("items") or []) if isinstance(row, dict)]
    if kind == "checklist":
        remember_checklist(session, body["items"])
    if kind == "end" or kind == "turn" and body.get("state") in {"idle", "aborted", "error", "refusal"}:
        from .neyvia_awareness import release_owner
        link = _links.get(session) or {}
        release_owner(bus.root, run_id=link.get("run"), session=session)
    if kind != "end":
        _later(record_report, bus, body)  # validated and stored in order, off the request
        return {"ok": True, "session": session, "queued": True}
    # The final report follows earlier queued reports; a late working write
    # must not resurrect a session after its end was already committed.
    result = _later(record_report, bus, body).result(timeout=30)
    if kind == "end":
        with _lock:
            _HELD.pop(session, None)
            _mirror.pop(session, None)
            _blocks.pop(session, None)
            _sent.pop(session, None)
    return result


def hold(session: str, reason: str) -> None:
    with _lock:
        _HELD[_session(session)] = (reason, time.monotonic() + 6 * 3600)


def held(session: str) -> str | None:
    with _lock:
        row = _HELD.get(str(session))
        if row and row[1] < time.monotonic():
            _HELD.pop(str(session), None)
            return None
        return row[0] if row else None
