"""Awareness: a shared work board (who works on which files), the impact map and the intent checklist.

The board is a small JSON file in the workspace state root so every process (the PC service, the desktop
bridge, an MCP server per agent) sees the same claims. A claim never blocks anyone: it tells the next agent
who is already in a file and why, so edits stay small or get coordinated.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .ui_command_bus import now, state_root

TEXT = {"type": "string"}
FILES = {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 100}
from .neyvia_intent_plan import PLAN_FIELDS
DEFINITIONS = [
    ("work.claim", "Say which files you are about to change and why, so other agents see it. Never blocks; returns who "
                   "else already claimed overlapping files. Re-claiming the same files as the same agent refreshes it.",
     {"files": FILES, "intent": TEXT, "agent": TEXT, "chat": TEXT, "app": TEXT}, ["files", "intent"]),
    ("work.release", "Release a claim when your change is committed or abandoned.", {"id": TEXT}, ["id"]),
    ("work.list", "Read the work board: active claims (agent, chat, files, intent, since). Pass files to see only the "
                  "claims that overlap them.", {"files": {"type": "array", "items": TEXT}, "agent": TEXT}, []),
    ("impact", "Given changed files (or none: the repository's uncommitted changes), list what they connect to: UI "
               "commands, backend handlers, desktop bridge, Tauri, tests and manuals, plus broken links.",
     {"paths": {"type": "array", "items": TEXT}, "gaps": {"type": "boolean"}}, []),
    ("intent.checklist", "Turn a long (often dictated) request into a checklist of asks. Returns a prompt and a JSON "
                         "schema for you to fill; no model is called.", {"text": TEXT}, ["text"]),
    ("plan.update", "Publish or update your model-authored intent checklist. Use the same sessionId when known; an empty plan clears it. No hidden model call.", PLAN_FIELDS, ["plan"]),
]

AWARENESS_COMMANDS = frozenset({"work_board_list_command", "work_board_claim_command", "work_board_release_command", "impact_map_command"})
STALE_HOURS = 12
MAX_CLAIMS = 200
_lock = threading.Lock()


# ---------------------------------------------------------------- the board store

def board_path(root) -> Path:
    return state_root(Path(root)) / ".neyvia" / "work-board.json"


class _FileLock:
    """A cross-process lock beside the board; a lock older than 10 s is from a dead writer."""

    def __init__(self, path: Path):
        self.path = path.with_suffix(".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 10:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("The work board is busy; try again")
                time.sleep(0.02)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"schema": "neyvia.work-board.v1", "claims": list(data.get("claims") or []), "released": list(data.get("released") or [])}


def _write(path: Path, data: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _norm(value) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text or len(text) > 400:
        raise ValueError("Each file is a non-empty path under 400 characters")
    return text


def _key(path: str) -> str:
    return path.casefold().rstrip("/*")


def overlaps(left: str, right: str) -> bool:
    """Same file, or one is a folder that contains the other; absolute and relative forms match by suffix."""
    from .proofs_awareness import check_overlap
    result = _overlaps(left, right)
    check_overlap(left, right, result)
    return result


def _overlaps(left: str, right: str) -> bool:
    a, b = _key(left), _key(right)
    if a == b or b.startswith(a + "/") or a.startswith(b + "/"):
        return True
    absolute = lambda p: ":" in p[:3] or p.startswith("/")
    if absolute(a) != absolute(b):
        long, short = (a, b) if absolute(a) else (b, a)
        return long.endswith("/" + short) or ("/" + short + "/") in (long + "/")
    return False


def _age_minutes(since: str) -> int:
    try:
        started = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds() // 60))


def _owner_live(root, claim):
    """A persisted run beats an age heuristic, including after a backend crash."""
    import sqlite3
    path = state_root(Path(root)) / ".agent_control" / "connected_chats.sqlite3"
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            db.row_factory = sqlite3.Row
            if claim.get("runId"):
                row = db.execute("SELECT * FROM connected_session_runs WHERE run_id=?", (claim["runId"],)).fetchone()
            elif claim.get("chat"):
                # Mod claims use raw Claude ids; broker claims use canonical ids.
                row = db.execute("SELECT * FROM connected_session_runs WHERE session_key=? OR session_key LIKE ? "
                                 "ORDER BY started DESC LIMIT 1", (claim["chat"], "%:" + claim["chat"])).fetchone()
            else:
                return None
        if row is None:
            return None
        if row["state"] not in {"queued", "running", "waiting_approval", "waiting_input"}:
            return False
        from .chat_run_control import process_started_at
        started = process_started_at(row["pid"])
        return started is not None and not (started and row["owner_started"] and abs(started - row["owner_started"]) > 2)
    except (OSError, sqlite3.Error):
        return None  # unavailable ownership evidence never revokes a live claim


def _view(claim: dict, root=None) -> dict:
    age = _age_minutes(claim.get("since", ""))
    inactivity = _age_minutes(claim.get("updatedAt") or claim.get("since", ""))
    live = _owner_live(root, claim) if root is not None else None
    return {**claim, "ageMinutes": age, "stale": not live if live is not None else inactivity >= STALE_HOURS * 60}


def _brief(claim: dict, files) -> dict:
    shared = [path for path in claim["files"] if any(overlaps(path, other) for other in files)]
    return {"id": claim["id"], "agent": claim["agent"], "chat": claim.get("chat"), "intent": claim["intent"],
            "since": claim["since"], "files": shared}


def claim(root, args: dict) -> dict:
    raw = args.get("files")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
        raise ValueError("files is a list of 1-100 paths")
    files = list(dict.fromkeys(_norm(value) for value in raw))
    intent = " ".join(str(args.get("intent") or "").split())
    if not 1 <= len(intent) <= 300:
        raise ValueError("intent is one short sentence (1-300 characters): what you change and why")
    agent = " ".join(str(args.get("agent") or "").split())[:80] or "agent"
    chat = str(args.get("chat") or "").strip()[:200] or None
    app = str(args.get("app") or "").strip()[:40] or None
    path = board_path(root)
    with _lock, _FileLock(path):
        from .proofs_awareness import before, after
        capture = before("work.claim", args, root, locked=True)
        board = _read(path)
        same = next((row for row in board["claims"] if row["agent"] == agent and row.get("chat") == chat
                     and {_key(f) for f in row["files"]} == {_key(f) for f in files}), None)
        others = [_brief(row, files) for row in board["claims"]
                  if row is not same and not _view(row, root)["stale"] and not (row["agent"] == agent and row.get("chat") == chat)
                  and any(overlaps(a, b) for a in row["files"] for b in files)]
        if same:
            same.update(intent=intent, updatedAt=now(), **({"app": app} if app else {}))
            record, refreshed = same, True
        else:
            if len(board["claims"]) >= MAX_CLAIMS:
                raise ValueError(f"The board holds {MAX_CLAIMS} claims; release finished ones first")
            record = {"id": "w-" + uuid.uuid4().hex[:10], "agent": agent, "chat": chat, "app": app, "files": files,
                      "intent": intent, "since": now(), "updatedAt": now()}
            board["claims"].append(record)
            refreshed = False
        if args.get("runId"):
            record["runId"] = str(args["runId"])[:120]
        _write(path, board)
        result = {"ok": True, "claim": _view(record, root), "refreshed": refreshed, "overlaps": others}
        after("work.claim", args, result, root, capture)
    message = ("Claimed. " if not refreshed else "Claim refreshed. ") + (
        "Also in these files: " + "; ".join(f"{row['agent']} ({row['intent']})" for row in others)
        + ". Keep your edit small and additive, or coordinate." if others else "Nobody else is in these files.")
    return {**result, "message": message}


def release(root, args: dict) -> dict:
    identity = str(args.get("id") or "").strip()
    if not identity:
        raise ValueError("id is required (from work.claim or work.list)")
    path = board_path(root)
    with _lock, _FileLock(path):
        from .proofs_awareness import before, after
        capture = before("work.release", args, root, locked=True)
        board = _read(path)
        row = next((item for item in board["claims"] if item["id"] == identity), None)
        if not row:
            raise ValueError("No active claim with that id; see work.list")
        board["claims"].remove(row)
        board["released"] = ([{**row, "releasedAt": now()}] + board["released"])[:30]
        _write(path, board)
        result = {"ok": True, "released": row["id"], "files": row["files"], "message": "Released " + ", ".join(row["files"][:3])
                  + (f" and {len(row['files']) - 3} more" if len(row["files"]) > 3 else "")}
        after("work.release", args, result, root, capture)
    return result


def board_list(root, args: dict | None = None) -> dict:
    args = args or {}
    board = _read(board_path(root))
    claims = [_view(row, root) for row in board["claims"]]
    files = [_norm(value) for value in (args.get("files") or [])]
    if files:
        claims = [row for row in claims if any(overlaps(a, b) for a in row["files"] for b in files)]
    if args.get("agent"):
        claims = [row for row in claims if row["agent"] == args["agent"]]
    claims.sort(key=lambda row: row["since"], reverse=True)
    result = {"ok": True, "claims": claims, "count": len(claims), "stale": sum(row["stale"] for row in claims),
              "recentlyReleased": board["released"][:5], "staleAfterHours": STALE_HOURS, "observedAt": now()}
    from .proofs_awareness import check_list
    check_list(args, result, board, root)
    return result


def release_owner(root, *, run_id=None, session=None):
    """Release only this turn's claims; raw and canonical Claude session ids agree."""
    if run_id == "adhoc":
        run_id = None  # each external session owns its own claims
    if not run_id and not session:
        return []
    path = board_path(root)
    if not path.exists():
        return []
    with _lock, _FileLock(path):
        board = _read(path)
        matched = [row for row in board["claims"] if
                   (run_id and row.get("runId") == run_id) or
                   (not row.get("runId") and session and row.get("chat") in {session, session.rsplit(":", 1)[-1]})]
        if matched:
            board["claims"] = [row for row in board["claims"] if row not in matched]
            board["released"] = ([{**row, "releasedAt": now(), "reason": "Owning turn ended"} for row in matched]
                                 + board["released"])[:30]
            _write(path, board)
        return [row["id"] for row in matched]


# ---------------------------------------------------------------- intent checklist

INTENT_SCHEMA = {
    "type": "object", "required": ["items"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "required": ["ask", "doneWhen", "status"], "properties": {
            "ask": {"type": "string", "description": "One concrete ask, imperative, plain words"},
            "quote": {"type": "string", "description": "The words of the message it comes from"},
            "kind": {"type": "string", "enum": ["build", "fix", "remove", "check", "explain", "plan", "decide"]},
            "doneWhen": {"type": "string", "description": "CL 1.1 observer G expression proving the result Paul would see or use; publish it with the plan"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
            "needsPaul": {"type": "boolean", "description": "True if it needs his decision, sign-in, install or spend"}}}},
        "dropped": {"type": "array", "items": {"type": "object", "properties": {"quote": {"type": "string"}, "why": {"type": "string"}}}},
        "questions": {"type": "array", "items": {"type": "string"}, "description": "Only what blocks; ask once, together"},
    },
}
INTENT_RULES = """1. It is often dictated. Read through sound-alikes and fix them silently when the topic fits (the manual of Paul below gives the odds): cloud/clothe code = Claude Code; code x/codec = Codex; Nevia/NYVIA/nvidia native, any odd word ending in VIA = Neyvia (Native); team = theme (near light/dark); scale = skill (near agents); spoon = spawn; pi pass/by pass = bypass; tail/age scale = Tailscale; get up = GitHub; RMS/LMS = Hermes; NASA/the mask = NAS (about files); five or limit = 5-hour limit; T3 cloud = T3 Code; whisper tree = Whisper v3; "those X work" = "does X work"; L-A-Y-A spelled out = LAYA. Repeated passages are one ask, not two.
2. Later words win, but only for what they name. "forget what I said about X", "no actually", "scratch that", "oh it's the browser, sorry" drop X alone (put X under dropped with the reason); an ask next to X stays. If you cannot tell what a correction covers, keep the ask and add one question.
3. Keep the scope he gives. "do a plan for this one" is a plan, not a build; "maybe", "if you want" stay optional (say so in the ask); "prepare the push, we push later" means prepare only.
4. His questions are asks: "is X good enough?", "does X work?", "can you spawn agents?" become check or explain items answered with evidence.
5. Not asks: permissions ("you can spawn agents"), praise, thanks, thinking aloud. Constraints ("don't make a branch") ride on the ask they limit, or become one item when they stand alone.
6. One ask per item, in his order. Split "and also" lists; never fold one topic into another. Keep his words in quote.
7. Implied asks count: if he complains something is broken or useless, the ask is to fix or remove it and prove it.
8. doneWhen proves the user-visible result with a CL 1.1 read-only observer expression, never "code written" or "report made". Publish it as optional doneWhen on each plan step; the host checks it before done(). If the observer is unmapped, report that frontier rather than inventing a condition.
9. needsPaul only for decisions, sign-ins, installs over 200 MB, spending, promotion to live, or global config.
10. questions only for what truly blocks; everything else gets a reasonable reversible assumption."""
INTENT_PROMPT = """Turn Paul's message into a checklist of asks. Fill the schema; do not answer the asks yet.
Rules:
""" + INTENT_RULES + """
{manual}
After filling it, publish each ask as {step: ask, status} via Native update_plan(plan_json), MCP plan_update(plan), or Claude Code's TaskCreate/TaskUpdate (TodoWrite on older versions). Keep it updated after verified progress; blocked asks remain pending with an explanation.
Message:
<<<
{text}
>>>"""


def intent_checklist(args: dict) -> dict:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text is the message to turn into a checklist")
    if len(text) > 40000:
        raise ValueError("text is limited to 40,000 characters; split the message")
    from .paul_manual import brief, profile
    manual = brief(level=2)
    prompt = INTENT_PROMPT.replace("{manual}", manual).replace("{text}", text)
    return {"ok": True, "prompt": prompt, "schema": INTENT_SCHEMA,
            "manual": "neyvia.manual.load(id='working-with-paul', chapter='reading' or 'intent')",
            "paulManual": {"rules": len(profile()["rules"]), "judgements": len(profile()["judgements"]), "applied": bool(manual)},
            "providerCalls": 0}


# ---------------------------------------------------------------- tool and command entry points

def call(service, name: str, args: dict) -> dict:
    root = service.bus.root
    if name == "work.claim":
        return claim(root, args)
    if name == "work.release":
        return release(root, args)
    if name == "work.list":
        return board_list(root, args)
    if name == "impact":
        from .neyvia_impact import impact
        return impact(args.get("paths") or [], gaps=args.get("gaps", True))
    if name == "intent.checklist":
        return intent_checklist(args)
    if name == "plan.update":
        from .neyvia_intent_plan import publish_plan
        return publish_plan(root, args)
    raise ValueError("Unknown awareness action")


def handle_command(root, command: str, payload: dict) -> dict:
    payload = payload or {}
    if command == "work_board_list_command":
        return board_list(root, payload)
    if command == "work_board_claim_command":
        return claim(root, {**payload, "agent": payload.get("agent") or "Paul"})
    if command == "work_board_release_command":
        return release(root, payload)
    if command == "impact_map_command":
        from .neyvia_impact import impact
        return impact(payload.get("paths") or [], gaps=payload.get("gaps", True))
    raise ValueError("Unknown awareness command")
