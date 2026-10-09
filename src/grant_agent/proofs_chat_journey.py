"""Connected Chats journeys over disposable saved history and sidebar state."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def saved_history_and_sidebar(root):
    """Project native history, scoped work and cleanup/job state across reopen."""
    from .proof_credential_guard import install
    install(root)
    root = Path(root).resolve()
    from .connected_sessions.opencode_history import latest_model, read_items, tool_output

    # Provider-shaped transcript fixtures stay inside the explicitly admitted
    # nested proof tree; the guard still refuses any real account directory.
    db = root / ".agent_control" / "proofs" / "opencode" / "history.sqlite"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, data TEXT, time_created INTEGER);
            CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, data TEXT, time_created INTEGER);
        """)
        conn.execute("INSERT INTO message VALUES(?,?,?,?)", ("m-user", "native-session", json.dumps({"role":"user"}), 1))
        conn.execute("INSERT INTO message VALUES(?,?,?,?)", ("m-assistant", "native-session", json.dumps({"role":"assistant","modelID":"fixture-model","providerID":"local-fixture"}), 2))
        conn.execute("INSERT INTO part VALUES(?,?,?,?)", ("p-user", "m-user", json.dumps({"type":"text","text":"Please summarize the saved change."}), 1))
        conn.execute("INSERT INTO part VALUES(?,?,?,?)", ("p-tool", "m-assistant", json.dumps({"type":"tool","tool":"read","state":{"status":"completed","output":"A bounded local result"}}), 3))
    items = read_items(db, "native-session", "connected:fixture-session")
    if not items or [item.kind for item in items] != ["user", "reasoning", "tool"]:
        raise AssertionError(f"Saved native messages did not reopen in stable order: {[item.kind for item in items or []]}")
    if items[0].data.get("text") != "Please summarize the saved change." or items[-1].data.get("output") != "A bounded local result":
        raise AssertionError("History projection lost visible text or the saved tool result")
    if latest_model(db, "native-session") != "local-fixture/fixture-model" or tool_output(db, "native-session", "connected:fixture-session#p-tool") != "A bounded local result":
        raise AssertionError("Saved model metadata or exact tool output could not be reopened")
    if read_items(root / "missing.sqlite", "native-session", "connected:fixture-session") is not None:
        raise AssertionError("Missing native history was represented as an empty successful transcript")

    # A real durable work-board claim drives the Connected Chats note; the same
    # task's own claim is omitted, and successful edits alone appear as paths.
    from .neyvia_awareness import claim
    from .connected_sessions.work_board import turn_note, edited_paths
    claimed_file = str((root / "src" / "visible.py").resolve())
    claim(root, {"files":[claimed_file], "intent":"Update the visible chat result", "agent":"Reviewer", "chat":"other-session"})
    note = turn_note(root, str(root), "current-session")
    own_note = turn_note(root, str(root), "other-session")
    claimed_visible = claimed_file.replace("\\", "/")
    if f"Reviewer is editing {claimed_visible}" not in note or "Reviewer is editing" in own_note:
        raise AssertionError("Work-board note failed to show a peer claim or hide the current session's claim")
    cwd = root / "workspace"
    cwd.mkdir()
    edited = edited_paths({"kind":"tool","data":{"category":"edit","status":"ok","files":["src/visible.py"]}}, cwd)
    refused = edited_paths({"kind":"tool","data":{"category":"edit","status":"declined","files":["private.txt"]}}, cwd)
    if edited != [str((cwd / "src/visible.py").resolve())] or refused:
        raise AssertionError("Connected Chats attributed a declined action as an edit or lost a successful path")

    # Archive checks use fresh observer data. The fixture marker makes this a
    # known project; an excluded folder stays protected even when it exists.
    from .connected_sessions.sidebar_cleanup import SidebarSafetyObserver, archive_blocker, normalize_policy, stale
    project = root / "workspace" / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True, capture_output=True, timeout=5)
    (project / ".git" / "info" / "exclude").write_text("*\n", encoding="utf-8")
    excluded = root / "workspace" / "protected"
    excluded.mkdir()
    observer = SidebarSafetyObserver(projects=[{"path":str(project)}], allowed_roots=[str(root)], excluded_roots=[str(excluded)])
    observer.process_dirs = []
    safe = observer.observe(project)
    protected = observer.observe(excluded)
    policy = normalize_policy({"projectDays":21,"autoArchive":True})
    old = {"updated_at":"2020-01-01T00:00:00Z","project_known":safe["project_known"]}
    if not safe["project_known"] or safe["cleanup_safety"]["status"] != "observed" or archive_blocker({**old, **safe}) or not stale(old, policy, time.time()):
        raise AssertionError("Known inactive project did not produce an observable stale cleanup candidate")
    if protected["cleanup_safety"]["status"] != "protected_path" or archive_blocker({**old, **protected}) != "safety_unknown":
        raise AssertionError("Excluded folder became archiveable without fresh in-scope evidence")
    try:
        normalize_policy({"projectDays":0})
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid cleanup age silently changed the user's cleanup policy")

    # Quota refresh exercises the production concurrency, privacy projection,
    # and durable reopen path through finite local reader boundaries.
    from .connected_sessions.live_limits import LiveLimits, LimitsUnavailable
    now = datetime.now(timezone.utc)
    sample = {"app":"claude-code","window":"five_hour","label":"5-hour","usedPercent":23.0,
              "resetsAt":(now + timedelta(hours=3)).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "at":now.isoformat(timespec="seconds").replace("+00:00", "Z"),"source":"fixture-reader","status":None}
    def fail_private(_root):
        raise RuntimeError("private /account/C:/Users/example%20name internal-credential-id")
    def no_opencode_quota(_root):
        raise LimitsUnavailable("OpenCode session stats do not report subscription quota windows")
    readers = {"claude-code":lambda _root:[sample], "codex":fail_private, "opencode":no_opencode_quota}
    limits = LiveLimits(root, interval=60, readers=readers)
    limits.collect()
    visible = limits.snapshot()
    limits.close()
    reopened = LiveLimits(root, interval=60, readers=readers)
    after_reopen = reopened.snapshot()
    reopened.close()
    serialized = json.dumps(after_reopen, ensure_ascii=False)
    codex_status = next(row for row in after_reopen["providers"] if row["app"] == "codex")
    if len(visible["limits"]) != 1 or visible["limits"][0]["usedPercent"] != 23.0 or visible["limits"][0]["stale"]:
        raise AssertionError("Fresh measured quota did not reach the connected-chat sidebar")
    if codex_status["status"] != "error" or codex_status["error"] != "CLI limit refresh failed; retry in the CLI":
        raise AssertionError("Raw reader exception escaped the public quota status")
    if "private" in serialized or "internal-credential-id" in serialized or after_reopen["limits"] != visible["limits"]:
        raise AssertionError("Quota persistence leaked private reader details or failed to reopen the visible row")

    # Polling reads the actual durable job record and bounded checkout log;
    # malformed IDs and missing jobs fail closed without starting a worker.
    from .connected_sessions import folder_jobs
    job_id = uuid.uuid4().hex
    job_path = folder_jobs._path(root, job_id)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps({"jobId":job_id,"status":"running","path":str(project),"branch":"fixture","createdAt":time.time(),"pid":None}), encoding="utf-8")
    job_path.with_suffix(".log").write_text("Updating files: 42% (2/5)\n", encoding="utf-8")
    progress = folder_jobs.status(root, job_id)
    if progress["progress"] != 42 or progress["message"] != "Checking out files" or progress["path"] != str(project):
        raise AssertionError("Saved checkout progress did not reopen as the same bounded public job state")
    try:
        folder_jobs.status(root, "../../account")
    except ValueError as error:
        if str(error) != "That worktree job was not found.":
            raise
    else:
        raise AssertionError("Malformed job identity was accepted")

    return {"history":{"items":[item.kind for item in items],"textRetained":True,"toolOutputRetained":True,"missingSchemaRefused":True},
            "work":{"peerClaimVisible":True,"sameSessionClaimHidden":True,"declinedEditExcluded":True},
            "cleanup":{"knownProjectObserved":True,"excludedFolderRefused":True,"invalidPolicyRefused":True},
            "limits":{"freshRows":len(after_reopen["limits"]),"rawFailureRedacted":True,"reopened":True},
            "checkout":{"progress":progress["progress"],"publicMessage":progress["message"],"malformedIdentityRefused":True},
            "boundary":"Disposable transcript, work-board and job records; actual production readers/observers; no account, provider, Git checkout or network calls"}


CASES = (("p22.chat-history-sidebar-journey", saved_history_and_sidebar),)


def self_check(_scratch=None):
    from .contract_gate import wants
    state = Path(__file__).resolve().parents[2] / ".agent_control/p22/chat-journey" / uuid.uuid4().hex
    state.mkdir(parents=True)
    cases = []
    started = time.perf_counter()
    for identity, action in CASES:
        if not wants(identity):
            continue
        began = time.perf_counter()
        try:
            observed = action(state / identity)
            cases.append({"id":identity,"contracts":[identity],"ok":True,"observed":observed})
        except Exception as error:
            cases.append({"id":identity,"contracts":[identity],"ok":False,"error":str(error)})
        cases[-1]["durationMs"] = round((time.perf_counter() - began) * 1000)
    return {"area":"chat-journey","ok":bool(cases) and all(row["ok"] for row in cases),"cases":cases,
            "durationMs":round((time.perf_counter() - started) * 1000),"runtimeState":str(state)}
