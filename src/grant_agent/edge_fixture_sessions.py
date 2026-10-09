"""Generative connected-session fixtures on isolated local files and real stores.

No provider is replaced with a canned handler. Parser projections consume
generated provider inputs; Git operations run real Git; native pages read the
real conversation store, and crash cases end real owned Python processes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

TEXT = {"empty": "", "huge": "generated " * 12000,
        "unicode": "雪🙂e\u0301\u202e العربية"}
FAMILIES = {
    "events": {"sessions.events.stamp", "sessions.events.bounds", "sessions.events.cursor", "sessions.events.wait"},
    "runs": {"sessions.run.request", "sessions.run.lifecycle"},
    "recovery": {"sessions.run.recovery"},
    "seen": {"sessions.broker.unread"},
    "workspace": {"sessions.workspace.state", "sessions.workspace.cache", "sessions.workspace.diff", "sessions.workspace.confirm", "sessions.workspace.action", "sessions.workspace.cli", "sessions.folders.catalogue"},
    "native": {"sessions.neyvia.payload", "sessions.neyvia.category", "sessions.neyvia.summary", "sessions.neyvia.page", "native.goal", "native.unsupported", "native.payload", "native.route", "native.permission", "native.context"},
    "native-items": {"sessions.neyvia.tools", "sessions.neyvia.items", "native.live", "native.outcome"},
    "codex": {"sessions.codex.sequence", "sessions.codex.text", "sessions.codex.diff", "sessions.codex.permissions", "sessions.codex.requests", "sessions.codex.media", "sessions.codex.origin", "sessions.codex.rollout", "providers.codex.input", "providers.codex.integrations"},
    "refusals": {"sessions.broker.refusals", "sessions.api.state_root", "sessions.workspace.remote", "sessions.workspace.checks"},
    "writer": {"providers.codex.lock"},
}
SUPPORTED = set().union(*FAMILIES.values())


def _require(value, message):
    if not value:
        raise AssertionError(message)


def _refused(call, codes):
    try:
        call()
    except Exception as exc:
        _require(getattr(exc, "code", None) in codes, f"unexpected refusal: {type(exc).__name__}: {exc}")
        return getattr(exc, "code")
    raise AssertionError("invalid request admitted")


def blocker(contract, category):
    identity = contract["id"]
    if identity in {"sessions.neyvia.page", "sessions.neyvia.payload"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": f"The audited {identity} owner is a synchronous projection with no accepted task, worker or completion publisher. Repeating its input after an unrelated interruption would be a false binding, so interruption evidence stays with the durable run/live-stream owners."}
    if identity in {"native.context", "native.payload", "native.route", "native.goal", "native.permission", "native.unsupported", "native.live"}:
        if category == "offline" and identity in {"native.context", "native.payload", "native.route", "native.goal", "native.permission", "native.unsupported", "native.live"}:
            return {"kind": "not_applicable", "reason": f"The audited {identity} owner is exercised against an owned conversation store or in-memory LiveTurn only; the selected invariant has no provider, remote device or transport dependency. The fixture independently observes stored rows, returned projections and refusal codes."}
        if category == "interrupted" and identity in {"native.context", "native.payload", "native.route", "native.permission", "native.unsupported"}:
            return {"kind": "not_applicable", "reason": f"The audited {identity} owner is synchronous and has no accepted task/completion boundary to interrupt. Repeated projections do not count as interruption evidence; actual worker interruption is covered by durable run and live-stream fixtures."}
        if category == "permissions" and identity == "native.live":
            return {"kind": "not_applicable", "reason": "LiveTurn.apply projects supplied in-memory stream events and has no filesystem read or protected mutation. Durable permission denial is checked at the goal metadata writer and session stream reader."}
        if category == "concurrency" and identity == "native.context":
            return {"kind": "not_applicable", "reason": "_last_context_usage is a bounded synchronous lookup for one conversation; independent concurrent route/payload projections and live-turn updates are exercised, but context lookup itself owns no mutable shared state or write to race."}
    pure = FAMILIES["codex"] - {"sessions.codex.rollout"} | {"sessions.neyvia.category", "sessions.broker.refusals", "sessions.workspace.remote", "sessions.workspace.checks", "sessions.neyvia.tools", "sessions.neyvia.items", "native.outcome"}
    if identity in pure and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        if (category == "permissions" and identity in {"sessions.codex.permissions", "sessions.codex.requests"}) or (category == "stale" and identity == "providers.codex.integrations"):
            return None
        return {"kind": "not_applicable", "reason": f"{identity} checks an in-memory conversion of supplied values at {contract.get('checkedAt', [])}; it has no owner grant, persisted revision, network transport or interrupted worker for {category}."}
    if identity in FAMILIES["events"] and category in {"permissions", "offline", "interrupted"}:
        return {"kind": "not_applicable", "reason": "EventBuffer is an in-process volatile cursor ring; this invariant has no filesystem grants, network endpoint or durable interrupted effect. Close/wakeup is exercised in its wait fixtures."}
    if identity == "providers.codex.lock" and category == "offline":
        return {"kind": "not_applicable", "reason": "active_writer probes a selected existing local OS byte lock only; it has no network endpoint or provider connection."}
    return None


def _events(root, category, text):
    from .connected_sessions.events import EventBuffer, _size
    buffer = EventBuffer("fixture-host", max_events=7, max_bytes=4096, max_event_bytes=1024, start_cursor=100)
    initial = buffer.since(None)
    _require(initial == ([], 100, False), "new subscriber replayed history")
    if category == "concurrency":
        gate = threading.Barrier(4)
        def writer(index):
            gate.wait(timeout=5)
            return [buffer.publish({"type": "notice", "sessionId": f"session-{index}", "text": f"{index}:{n}"}) for n in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            published = [row for group in pool.map(writer, range(4)) for row in group]
        _require(sorted(e["cursor"] for e in published) == list(range(101, 149)), "concurrent cursors lost or duplicated events")
    else:
        published = [buffer.publish({"type": "notice", "sessionId": "owned", "text": text, "short": "kept", "index": n}) for n in range(12 if category in {"huge", "stale"} else 2)]
    ring = list(buffer._ring)
    _require(buffer._bytes == sum(_size(e) for _, e, _ in ring) <= 4096 and len(ring) <= 7, "evicted ring byte accounting differs")
    _require(all(e["hostDeviceId"] == "fixture-host" and _size(e) <= 1024 for e in published), "event identity or size bound differs")
    _require(all(e.get("short") == "kept" and e.get("truncated") for e in published) if category == "huge" else True, "huge payload dropped short metadata or truncation receipt")
    for cursor in (ring[0][0] - 1, buffer.head(), buffer.head() + 1, 0):
        events, head, resync = buffer.since(cursor)
        expected_resync = not ring[0][0] - 1 <= cursor <= buffer.head()
        expected_events = [] if expected_resync else [e for n, e, _ in ring if n > cursor]
        _require((events, head, resync) == (expected_events, buffer.head(), expected_resync), "cursor retained window/resync wrong")
    waiter_ready = threading.Event()
    def wait():
        waiter_ready.set()
        return buffer.wait(buffer.head(), .5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(wait)
        waiter_ready.wait(2)
        time.sleep(.02)
        before = buffer.head()
        event = buffer.publish({"type": "notice", "sessionId": "wake", "text": text[:100]})
        received = future.result(2)
        _require(received == ([event], before + 1, False), "blocking subscriber failed to wake with exact published event")
        future = pool.submit(wait)
        time.sleep(.02)
        buffer.close()
        _require(future.result(2) == ([], buffer.head(), False), "close failed to release observer")
    return {"published": len(published) + 1, "retained": len(buffer._ring), "bytes": buffer._bytes, "head": buffer.head(), "concurrentWriters": 4 if category == "concurrency" else 1}


def _run_data(run, session, text):
    return {"runId": run, "sessionId": session, "app": "neyvia", "state": "queued", "pendingRequest": None,
            "error": None, "canStop": True, "canSteer": True, "message": text}


def _runs(root, category, text):
    from .connected_sessions.broker import ConnectedBroker, _LiveRun, MAX_MESSAGE_CHARS
    from .connected_sessions.registry import make_session_id
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
    try:
        sid = make_session_id("neyvia", broker.host["deviceId"], "owned-" + text[:64])
        records = []
        gate = threading.Barrier(2) if category == "concurrency" else None
        def claim(index):
            data = _run_data(f"request-{index}", sid, text)
            run = _LiveRun(data, None, "turn")
            if gate:
                gate.wait(timeout=5)
            try:
                admitted = broker.store.claim(data, f"fingerprint-{index}", 0, is_free=lambda _: False,
                                              register=lambda: broker._live.update({data["runId"]: run}),
                                              unregister=lambda: broker._live.pop(data["runId"], None))
                records.append((data, run))
                return admitted
            except Exception as exc:
                _require(getattr(exc, "code", None) == "session_busy", "competing claim refused for wrong reason")
                return False
        if gate:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(claim, range(2)))
            _require(sum(results) == 1, "two competing claims own one session")
        else:
            _require(claim(0), "initial run claim refused")
        data, run = records[0]
        _require(broker.store.load(data["runId"]) == data, "durable run differs from requested identity/message")
        _refused(lambda: broker.store.has_request(data["runId"], "changed-fingerprint"), {"request_id_conflict"})
        _require(broker.store.has_request(data["runId"], "fingerprint-" + data["runId"].split("-")[-1]), "matching request lost replay identity")
        for state in ("running", "waiting_input", "waiting_approval", "completed"):
            pending = {"requestId": "pending", "kind": "question" if state == "waiting_input" else "approval"} if state.startswith("waiting") else None
            broker._set_state(run, state, pending=pending)
            actual = broker.get_run(data["runId"])
            _require(actual["state"] == state and actual["pendingRequest"] == pending and (state != "completed" or not actual["canStop"] and not actual["canSteer"]), "broker state lost identity or terminal safety")
            _require(broker.store.load(data["runId"])["state"] == state, "broker state not durable")
        _require(not broker._set_state(run, "running"), "late event revived retired run")
        # Real broker early refusal, without importing or executing a provider.
        invalid_message = "" if category == "empty" else "x" * (MAX_MESSAGE_CHARS + 1) if category == "huge" else None
        if invalid_message is not None:
            _refused(lambda: broker.send(sid, invalid_message, "new-request"), {"invalid_message"})
        _refused(lambda: broker.send(make_session_id("neyvia", "other-host", "other"), text[:1000] or "message", "foreign-request"), {"wrong_device"})
        _require(len(broker.store.active()) == 0, "refused request acquired provider ownership")
        return {"durableRuns": len(records), "competingClaims": 2 if gate else 1, "terminal": "completed", "lateRevival": False}
    finally:
        broker.close()


def _seen(root, category, text):
    from .connected_sessions.seen import SeenStore
    store = SeenStore(root)
    sid = "session-" + text
    store.baseline([(sid, "2026-10-04T00:00:00Z")])
    _require(not store.unread(sid, "2026-10-04T00:00:00Z", 100), "initial inventory marked historical items unread")
    store.mark(sid, 5, "2026-10-04T00:00:00Z")
    restored = SeenStore(root)
    _require(not restored.unread(sid, "2026-10-04T00:00:00Z", 5) and restored.unread(sid, "2026-10-04T00:00:00Z", 6), "persisted sequence comparison differs")
    _require(restored.unread(sid, "2026-10-04T00:00:02Z", 5) and not restored.unread(sid, "2026-10-03T23:59:00Z", 5), "persisted seen timestamp loses staleness ordering")
    if category == "concurrency":
        gate = threading.Barrier(4)
        def mark(i):
            gate.wait(5)
            store.mark(f"other-{i}", i, None)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(mark, range(4)))
        saved = SeenStore(root)
        _require(all(saved.get(f"other-{i}")["seq"] == i for i in range(4)), "concurrent seen writes lost another session")
    return {"seenSha256": hashlib.sha256(store.path.read_bytes()).hexdigest(), "characters": len(text)}


def _recovery(root, category, text):
    from .connected_sessions.broker import ConnectedBroker
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
    dbpath = broker.db_path
    data = _run_data("owned-interrupted", "owned-session", text)
    data.update(state="queued", pendingRequest=None)
    supplied = root / "generated-request.json"
    supplied.write_text(json.dumps(data), encoding="utf-8")
    script = ("import os,sys,json; from pathlib import Path; from grant_agent.connected_sessions.runs import RunStore; "
              "s=RunStore(Path(sys.argv[1]),'child-owner',lambda _:True); d=json.loads(Path(sys.argv[2]).read_text()); "
              "s.claim(d,'exact-request',0,is_free=lambda _:False,register=lambda:None,unregister=lambda:None); os._exit(23)")
    try:
        child = subprocess.run([sys.executable, "-c", script, str(dbpath), str(supplied)], capture_output=True, timeout=40, **hidden_windows_subprocess_kwargs())
        _require(child.returncode == 23, "owned recovery worker never reached durable claim boundary")
        before = broker.store.load(data["runId"])
        _require(before == data, "worker changed durable request payload before interruption")
        cursor = broker.events.head()
        recovered = broker.recover()
        _require(len(recovered) == 1 and recovered[0]["state"] == "interrupted" and recovered[0]["pendingRequest"] is None
                 and recovered[0]["message"] == text and "did not resend" in recovered[0]["error"], "recovered owner lost payload, uncertainty or no-resend reason")
        _require(broker.store.has_request(data["runId"], "exact-request") and broker.recover() == [] and broker.store.load(data["runId"]) == recovered[0], "recovery replayed effects or lost durable terminal receipt")
        events, _, resync = broker.events.since(cursor)
        _require(not resync and len(events) == 1 and events[0]["type"] == "run.state"
                 and events[0]["runId"] == data["runId"] and events[0]["state"] == "interrupted"
                 and events[0]["pendingRequest"] is None, "broker recovery lost exact public terminal event")
        return {"childExit": 23, "requestCharacters": len(text), "recovered": len(recovered), "recoveryEvents": len(events), "resend": False}
    finally:
        broker.close()


def _git(root, *arguments):
    process = subprocess.run([shutil.which("git"), "-c", "user.name=C7 fixture", "-c", "user.email=c7@example.invalid", "-c", "core.autocrlf=false", *arguments], cwd=root, capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
    _require(process.returncode == 0, f"fixture Git failed {arguments[:2]}: {process.stderr.decode('utf-8', 'replace')[:300]}")
    return process.stdout.decode("utf-8", "replace")


def _workspace(root, category, text):
    # Git-only child PATH makes real gh discovery unavailable rather than
    # replacing network/account probes with a canned result.
    git = shutil.which("git")
    _require(git is not None, "Git unavailable for real repository fixture")
    child_env = dict(os.environ)
    child_env.update(PATH=str(Path(git).parent), HOME=str(root / "home"), USERPROFILE=str(root / "home"),
                     GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    command = [sys.executable, "-c", "import json,sys; from pathlib import Path; from grant_agent.edge_fixture_sessions import _workspace_inside; print(json.dumps(_workspace_inside(Path(sys.argv[1]),sys.argv[2])))", str(root), category]
    child = subprocess.run(command, capture_output=True, timeout=120, env=child_env, **hidden_windows_subprocess_kwargs())
    _require(child.returncode == 0, child.stderr.decode("utf-8", "replace")[-2000:])
    return json.loads(child.stdout)


def _workspace_inside(root, category):
    from .connected_sessions import workspace as w, folders
    text = TEXT.get(category, "generated " + category)
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    filename = "file-雪.txt" if category == "unicode" else "file.txt"
    path = repo / filename
    path.write_text("before\n", encoding="utf-8")
    _git(repo, "add", "--", filename)
    _git(repo, "commit", "-m", "baseline")
    (repo / ".git/config").write_text((repo / ".git/config").read_text(encoding="utf-8") + "\n[user]\n\tname = C7 fixture\n\temail = c7@example.invalid\n", encoding="utf-8")
    path.write_text(text + "\nafter\n", encoding="utf-8")
    w.invalidate(str(repo))
    first = w.workspace_state(str(repo))
    _require(first["branch"] == "main" and first["repo"]["root"] == str(repo) and first["changes"][0]["path"] == filename, "Git state differs from actual repository")
    _require(first["changes"][0]["status"] == "modified" and first["changes"][0]["deletions"] == 1 and not first["gh"]["installed"], "observed changes or confined GH discovery differs")
    info = folders._git_info(repo)
    _require(info["branch"] == "main", "folder branch disagrees with Git")
    first["changes"].clear()
    _require(w.workspace_state(str(repo))["changes"], "caller changed shared cached observation")
    if category == "stale":
        old = w.workspace_state(str(repo))
        path.write_text(path.read_text(encoding="utf-8") + "newer unseen line\n", encoding="utf-8")
        _require(w.workspace_state(str(repo)) == old, "TTL cache unexpectedly changed its admitted observation")
        w.invalidate(str(repo))
        newer = w.workspace_state(str(repo))
        _require(newer["changes"][0]["additions"] == old["changes"][0]["additions"] + 1, "invalidate retained stale Git observation")
    patch = w.file_diff(str(repo), filename)
    _require("before" in patch["patch"] and "after" in patch["patch"], "actual file delta lost changed content")
    if category == "huge":
        path.write_text("\n".join(str(n) + " " + "x" * 100 for n in range(4000)), encoding="utf-8")
        large = w.file_diff(str(repo), filename)
        _require(large["truncated"] and large["patch"].endswith("[diff truncated]\n"), "huge real patch has no truncation marker")
        for n in range(310):
            (repo / f"untracked-{n:03}.txt").write_text("generated\n")
        w.invalidate(str(repo))
        state = w.workspace_state(str(repo))
        _require(len(state["changes"]) == 300 and state["changesTruncated"], "huge actual Git changes exceeded bound")
    head = _git(repo, "rev-parse", "HEAD").strip()
    for confirm in (False, None, 1, "true", {}):
        _refused(lambda: w.git_action(str(repo), "commit", message="should not write", confirm=confirm), {"confirmation_required"})
    _require(_git(repo, "rev-parse", "HEAD").strip() == head, "confirmation refusal changed repository")
    for escape in ("../outside.txt", str(root / "outside.txt")):
        _refused(lambda: w.file_diff(str(repo), escape), {"path_outside_workspace", "path_outside_repo", "invalid_path", "no_file", "file_not_found"})
    if category in {"empty", "huge"}:
        message = "" if category == "empty" else "x" * 5001
        _refused(lambda: w.git_action(str(repo), "commit", message=message, confirm=True), {"message_required"})
    literal = "literal 雪; $(never-run) `untouched`"
    result = w.git_action(str(repo), "commit", message=literal, confirm=True)
    _require(result["ok"] and _git(repo, "log", "-1", "--format=%B").strip() == literal, "production commit changed literal message or did not execute")
    _require(path.read_bytes() == _git(repo, "show", f"HEAD:{filename}").encode("utf-8"), "committed bytes differ from selected file")
    return {"gitHead": _git(repo, "rev-parse", "HEAD").strip(), "patchBytes": len(patch["patch"].encode()), "confinedGhUnavailable": True, "literalCommit": True}


def _native_goal_interrupted(root, cid):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .neyvia_conversations import NeyviaConversationStore
    before = NeyviaConversationStore(root).get_conversation(cid)
    program = '''import sys,os
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from grant_agent.neyvia_conversations import NeyviaConversationStore
from grant_agent.connected_sessions.neyvia import NeyviaAdapter
root=Path(sys.argv[1]);store=NeyviaConversationStore(root);original=store._connection
@contextmanager
def interrupted():
 with original() as db:
  db.set_trace_callback(lambda sql:os._exit(47) if sql.strip().upper()=='COMMIT' else None)
  yield db
store._connection=interrupted
adapter=NeyviaAdapter(SimpleNamespace(root=root,neyvia_mcp=SimpleNamespace(conversations=store)))
adapter.goal(adapter._sid(sys.argv[2]),'set','actual interrupted metadata write')
'''
    result = subprocess.run([sys.executable, '-c', program, str(root), cid], capture_output=True,
                            text=True, timeout=30,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                            **hidden_windows_subprocess_kwargs())
    _require(result.returncode == 47 and NeyviaConversationStore(root).get_conversation(cid) == before,
             'Interrupted production native goal write persisted partial metadata: ' + result.stderr[-500:])
    return {'childExit': 47, 'goalMetadataRollback': True}


def _native(root, category, text):
    from .neyvia_conversations import NeyviaConversationStore
    from .connected_sessions.neyvia import NeyviaAdapter, classify, conversation_runtime
    from .connected_sessions.model import TurnOptions
    store = NeyviaConversationStore(root)
    adapter = NeyviaAdapter(SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=store)))
    row = store.create_conversation(title=text, metadata={"workspacePath": str(root / "project")})
    cid = row["conversationId"]
    count = 14 if category == "huge" else 4
    original = []
    for n in range(count):
        content = (text[:1000] + f" turn {n}").strip()
        role = "user" if n % 2 == 0 else "assistant"
        saved = store.append_turn(cid, role=role, content=content, turn_id=f"turn-{n:04}", now=f"2026-10-04T00:00:{n:02}Z")
        original.append((saved["turnId"], role, content))
    sid = adapter._sid(cid)
    page = adapter.read(sid, limit=3 if category == "huge" else 200)
    _require([i.data["text"] for i in page.items] == [r[2] for r in original][-len(page.items):] and len({i.id for i in page.items}) == len(page.items), "native page differs from durable input order")
    boundary = page.items[-1].seq
    if category == "stale":
        store.append_turn(cid, role="user", content="newer durable turn", turn_id="turn-newer", now="2026-10-04T00:01:00Z")
        original.append(("turn-newer", "user", "newer durable turn"))
    earlier = adapter.read(sid, before_seq=boundary, limit=200)
    _require(all(i.seq < boundary for i in earlier.items), "native earlier cursor is not exclusive")
    fresh = adapter.read(sid, cursor=str(boundary), limit=200)
    _require([i.data["text"] for i in fresh.items] == (["newer durable turn"] if category == "stale" else []), "native cursor replayed old items or lost newer durable turn")
    _require(adapter.goal(sid, "set", text) == {"state": "set", "text": None, "goalMode": True}, "goal switch persisted supplied free text")
    restored = NeyviaAdapter(SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=NeyviaConversationStore(root))))
    _require(restored.goal(sid, "get") == {"state": "set", "text": None, "goalMode": True}, "goal did not survive reopen")
    _require(adapter.goal(sid, "clear", text) is None and store.get_conversation(cid)["metadata"]["goalMode"] is False, "goal clear not durable")
    _refused(lambda: adapter.answer("run", "request", {}), {"not_supported"})
    hybrid = store.create_conversation(metadata={"runtime": "codex"})
    _refused(lambda: adapter.goal(adapter._sid(hybrid["conversationId"]), "set", text), {"not_supported"})
    if category == "concurrency":
        goals = [store.create_conversation(title=f"goal-{n}") for n in range(8)]
        def set_goal(item):
            sid = adapter._sid(item["conversationId"])
            return adapter.goal(sid, "set", text), adapter.goal(sid, "get")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(set_goal, goals))
        _require(all(a == {"state": "set", "text": None, "goalMode": True} and b == a for a, b in results),
                 "concurrent durable native goal updates diverged")
        denied_ids = [adapter._sid(store.create_conversation(metadata={"runtime": "codex"})["conversationId"]) for _ in range(8)]
        def reject_hybrid(sid):
            return _refused(lambda: adapter.goal(sid, "set", text), {"not_supported"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            refusals = list(pool.map(reject_hybrid, denied_ids))
        _require(len(refusals) == 8 and all(store.get_conversation(adapter._conversation_id(sid))["metadata"].get("goalMode") is None for sid in denied_ids),
                 "concurrent unsupported goal requests were admitted or mutated metadata")
    for runtime, expected in (("", ("native", None)), ("neyvia-agent", ("native", "neyvia-agent")), ("codex", ("hybrid", "codex")), ("mixed-routes", ("hybrid", None))):
        _require(classify(runtime) == expected, "native/hybrid classification differs")
    _require(conversation_runtime({"metadata": {"routeSnapshot": [{"runtime": "codex"}, {"runtime": "claude-code"}]}}) == "mixed-routes", "mixed routes invented a single runtime")
    attachments = adapter._attachments([] if category == "empty" else [{"name": "fixture-雪.png", "mime": "image/png", "data": base64.b64encode((text or "bytes").encode()).decode()}])
    options = TurnOptions(model="generated-model-" + text[:128], effort="high", permission_mode="read-only")
    route = adapter._route(cid, options)
    mode = adapter._permission_mode(options, route[0])
    payload = adapter._payload(cid, text, mode, attachments, route, str(root / "selected"), store.get_conversation(cid), ("user-new", "assistant-new"), "2026-10-04T01:00:00Z")
    _require(payload["message"] == text and payload["attachments"] == attachments and payload["workspacePath"] == str(root / "selected") and payload["history"] == [{"role": r[1], "text": r[2]} for r in original[-8:]], "composer payload/history does not project real stored state")
    _require(payload["userTurnId"] != payload["assistantTurnId"] and not payload["workspaceToolsAllowed"], "payload broadens readonly permission or conflates IDs")
    _refused(lambda: adapter._attachments([{"data": "not valid !!", "mime": "image/png"}]), {"invalid_image"})
    _refused(lambda: adapter._permission_mode(TurnOptions(permission_mode="invented"), "neyvia-agent"), {"invalid_permission_mode"})
    context = adapter._last_context_usage(cid)
    _require(context.used_tokens is None, "missing provider usage invented token count")
    adverse = {}
    if category == 'interrupted':
        adverse.update(_native_goal_interrupted(root, cid))
    if category == "concurrency":
        gate = threading.Barrier(8)
        def observe(_):
            gate.wait(timeout=5)
            return (adapter._route(cid, options), adapter._permission_mode(options, route[0]),
                    adapter._payload(cid, text, mode, attachments, route, str(root / "selected"),
                                     store.get_conversation(cid), ("user-new", "assistant-new"), "2026-10-04T01:00:00Z"),
                    adapter._last_context_usage(cid))
        with ThreadPoolExecutor(max_workers=8) as pool:
            observations = list(pool.map(observe, range(8)))
        _require(all(r == route and p == mode and v == payload and c == context for r, p, v, c in observations),
                 "concurrent native route/permission/payload projections diverged")
        adverse["concurrentProjections"] = len(observations)
    if category == "stale":
        store.set_goal_mode(cid, True)
        old_goal = adapter.goal(sid, "get")
        store.set_goal_mode(cid, False)
        fresh_goal = NeyviaAdapter(SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=NeyviaConversationStore(root)))).goal(sid, "get")
        _require(old_goal["goalMode"] is True and fresh_goal is None, "fresh goal read retained stale durable metadata")
        store.append_turn(cid, role="assistant", content="new route", turn_id="turn-route-newer",
                          now="2026-10-04T02:00:00Z", metadata={"runtimeResult": {"runtime": "claude-code", "route": {"provider": "owned-provider", "model": "owned-model", "effort": "low"}}})
        refreshed = NeyviaAdapter(SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=NeyviaConversationStore(root))))
        fresh_route = refreshed._route(cid, TurnOptions())
        _require(fresh_route == ("claude-code", "owned-provider", "owned-model", "default") and fresh_route != route,
                 "fresh route read reused older durable route metadata")
        stream = root / ".agent_control" / "chat_streams" / "turn-route-newer.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(json.dumps({"at": "2026-10-04T02:00:01Z", "data": {"eventType": "context.usage", "inputTokens": 37, "contextTokens": 4096, "triggerTokens": 3500}}) + "\n", encoding="utf-8")
        fresh_context = refreshed._last_context_usage(cid)
        _require(fresh_context.used_tokens == 37 and fresh_context.window_tokens == 4096,
                 "fresh context read missed newly durable provider usage")
        adverse["freshDurableReads"] = {"route": fresh_route[0], "contextTokens": fresh_context.used_tokens, "goalCleared": fresh_goal is None}
        _require(adapter._permission_mode(TurnOptions(permission_mode='workspace'), 'neyvia-agent') == 'workspace'
                 and adapter._permission_mode(options, route[0]) == mode,
                 'Current permission request reused an older mode or changed prior options')
        hybrid_cid = hybrid['conversationId']
        with store._connection() as db:
            db.execute('UPDATE conversations SET metadata_json=? WHERE conversation_id=?',
                       (json.dumps({'runtime': 'neyvia-agent'}), hybrid_cid))
            db.commit()
        _require(adapter.goal(adapter._sid(hybrid_cid), 'set', text)['goalMode'] is True,
                 'Changed native runtime retained an obsolete unsupported-goal refusal')
    if category == "permissions":
        from .edge_fixture_missions import exclusive
        from .edge_fixture_native import _reject
        import sqlite3
        with exclusive(store.database_path):
            _reject(lambda: adapter._route(cid, TurnOptions()), (OSError, sqlite3.Error))
            try:
                adapter.goal(sid, 'set', text)
            except (OSError, sqlite3.Error):
                pass
            else:
                raise AssertionError("OS-denied durable goal metadata write was accepted")
        _require(store.get_conversation(cid)["metadata"].get("goalMode") is False,
                 "OS-denied goal metadata write was not refused")
        stream = root / ".agent_control" / "chat_streams" / (original[-1][0] + '.jsonl')
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(json.dumps({"at": "2026-10-04T03:00:00Z", "data": {"eventType": "context.usage", "inputTokens": 81}}) + "\n", encoding="utf-8")
        _require(adapter._last_context_usage(cid).used_tokens == 81,
                 'Permission fixture did not first observe the targeted provider stream')
        with exclusive(stream):
            denied_context = adapter._last_context_usage(cid)
        _require(json.loads(stream.read_text(encoding="utf-8"))["data"]["inputTokens"] == 81 and denied_context.used_tokens is None,
                 "OS-denied context stream read leaked stale or fabricated usage")
    return {"persistedTurns": len(original), "pageItems": len(page.items), "goalReopened": True,
            "historyCount": len(payload["history"]), "contextTokens": context.used_tokens, **adverse}


def _native_items(root, category, text):
    from .connected_sessions.neyvia_items import turn_items, tool_item, tool_category, LiveTurn
    from .connected_sessions.neyvia import NeyviaAdapter, _Run
    outcomes = {}
    for status in ("completed", "failed", "cancelled", "interrupted"):
        turn = {"turnId": "stored-" + status, "role": "assistant", "content": text, "metadata": {"runtimeResult": {"status": status}}}
        items, _ = turn_items(turn, 3)
        _require(len({i.seq for i in items}) == len(items) and items[-1].data["text"] == text, "stored native items lost text or sequence uniqueness")
        _require(items[-1].kind == ("assistant" if status == "completed" else "notice"), "stored outcome falsely claims assistant success")
        live = LiveTurn("session", "turn", 3)
        emitted = []
        terminal_status = "stop_unconfirmed" if status == "interrupted" else status
        error = NeyviaAdapter._finish(_Run("run", "conversation", "turn", live), {"result": {"status": terminal_status, "error": text}}, emitted.append)
        _require(error is None and all(e["sessionId"] == "session" and e["runId"] == "run" for e in emitted), "native finish changed returned identity")
        _require(not emitted if status == "completed" else len(emitted) == 1, "native finish omitted/duplicated terminal receipt")
        outcomes[status] = items[-1].kind
    call = {"tool": "workspace.read", "input": json.dumps({"path": "fixture-雪.txt"}), "output": text, "status": "started", "error": ""}
    item = tool_item(call, "tool", 1, None, finished=True)
    _require(item.data["status"] == "error" and item.data["note"] == "No result was recorded for this call." and len(item.data["output"]) <= 8192, "unresolved tool remains running or loses output bound")
    names = {"mcp": "mcp_shell_read", "command": "shell.read", "edit": "edit.web", "web": "web.search",
             "search": "search.read", "read": "read.agent", "agent": "delegate", "other": "opaque"}
    for expected, name in names.items():
        name += "-" + text[:128]
        _require(tool_category(name) == expected, "native category ignores ordered matching")
        body = {"toolResult": {"stdout": text, "content": text, "stderr": "", "exit_code": 0, "duration_ms": 23}}
        recorded = {"tool": name, "input": json.dumps({"path": "fixture-雪.txt", "command": text}),
                    "output": json.dumps(body, ensure_ascii=False), "status": "completed", "error": ""}
        mapped = tool_item(recorded, "nested-" + expected, 4, None, finished=True)
        expected_output = text if expected in {"command", "read"} else recorded["output"]
        _require(mapped.data["status"] == "ok" and mapped.data["category"] == expected and mapped.data["output"] == expected_output[:8192]
                 and mapped.data["exitCode"] == 0 and mapped.data["durationMs"] == 23, "nested native tool result loses observed output or status/timing")
    count = 140 if category == "huge" else 3 if text else 0
    activity = [{"kind": "reasoning_summary", "id": f"public-{n}", "text": text} for n in range(count)]
    activity.append({"kind": "thinking_text", "source": "private", "text": "private-only-content"})
    turn = {"turnId": "activity", "role": "assistant", "content": text, "metadata": {"turnReceipt": {"activitySegments": activity}}}
    projected, _ = turn_items(turn, 4)
    _require(len(projected) == (100 if count > 99 else count + 1) and len({row.seq for row in projected}) == len(projected), "activity exceeds native slot budget or collides")
    _require(all(row.data.get("summary") == text[:8192] for row in projected if row.kind == "reasoning")
             and "private-only-content" not in json.dumps([row.public() for row in projected]), "activity exposes private/unbounded reasoning")
    if count > 99:
        _require(any(row.kind == "notice" and "42 more activity rows" in row.data["text"] for row in projected), "excess activity has no exact omission receipt")
    live = LiveTurn("session", "turn", 2)
    events = live.apply([{"kind": "runtime.answer_delta", "message": text}, {"kind": "runtime.answer_delta", "message": "suffix"}])
    _require(live.items["turn"].data["text"] == text + "suffix", "live deltas do not append exact content")
    private = live.apply([{"kind": "runtime.thinking_delta", "message": text, "data": {"source": "private"}}])
    _require(private == [], "private reasoning emitted public rows")
    if category == "concurrency":
        turns = [LiveTurn(f"session-{n}", f"turn-{n}", 1) for n in range(8)]
        gate = threading.Barrier(len(turns))
        def apply(index):
            gate.wait(timeout=5)
            return turns[index].apply([{"kind": "runtime.answer_delta", "message": f"reply-{index}"}])
        with ThreadPoolExecutor(max_workers=len(turns)) as pool:
            output = list(pool.map(apply, range(len(turns))))
        _require(all(len(rows) == 1 and rows[-1]["sessionId"] == f"session-{n}"
                      and turns[n].items[f"turn-{n}"].data["text"] == f"reply-{n}"
                      for n, rows in enumerate(output)), "concurrent native live turns crossed identity or text")
    if category == "interrupted":
        failure = LiveTurn("session-failed", "turn-failed", 1).apply(
            [{"kind": "runtime.stream_error", "message": "fixture interrupted"}])
        _require(any(row["type"] == "item.added" and row["item"]["kind"] == "notice"
                     and row["item"]["data"]["level"] == "error" for row in failure),
                 "interrupted live stream omitted its bounded visible error")
    live.apply([{"kind": "runtime.answer_start", "data": {"responseId": "new"}}])
    _require(live.items["turn"].data["text"] == "", "new response identity did not clear old draft")
    if category == "stale":
        old_state = LiveTurn("session-stale", "turn-stale", 2)
        old_state.apply([{"kind": "runtime.answer_delta", "message": "old stream content"}])
        _require(old_state.items["turn-stale"].data["text"] == "old stream content", "initial live stream state was not observed")
        old_state.apply([{"kind": "runtime.answer_start", "data": {"responseId": "fresh-response"}},
                         {"kind": "runtime.answer_delta", "message": "fresh stream content"}])
        _require(old_state.items["turn-stale"].data["text"] == "fresh stream content",
                 "fresh live response continued stale draft content")
    return {"outcomes": outcomes, "liveEmitted": len(events), "toolState": item.data["status"], "toolCategories": len(names), "activityInput": count, "activityItems": len(projected)}


def _codex(root, category, text):
    from .connected_sessions import codex_items as c
    from .connected_sessions.codex import _build_input, build_integrations, MAX_IMAGE_BYTES
    for ordinal in (0, 1, 10000):
        for index in (-1, 0, 1, 100000):
            for sub in (0, 1, 2, 3):
                seq = c.make_seq(ordinal, index, sub)
                _require(seq == ordinal * 8192 + min(max(index, 0), 2047) * 4 + sub and c.ordinal_from_seq(seq) == ordinal, "Codex sequence arithmetic loses slot/ordinal")
    _require(c.uuid7_ms(text) is None, "generated empty/huge/unicode token invented a UUID7 clock")
    clipped = c.clip(text, 64)
    raw = text.encode()
    expected = text if len(raw) <= 64 else raw[:64].decode("utf-8", "ignore")
    _require(clipped == (expected if len(raw) <= 64 else expected + f"\n[... {len(text) - len(expected)} more characters omitted]"), "Codex text clip does not conserve UTF8 character count")
    token = c.media_token(text)
    _require(token == hashlib.sha256(text.encode()).hexdigest(), "opaque media reference identity differs")
    _require(c.classify_origin("/owned/project/" + text) == "user" and c.classify_origin("/owned/.agent_control/" + text) == "neyvia-harness", "Codex origin invents harness attribution")
    for mode in ("ask", "auto", "full"):
        values = c.turn_permission_params(mode)
        _require(isinstance(values, dict) and values, "permission mapping absent")
    _require(c.turn_permission_params("invented") == {} and c.thread_permission_params("invented") == {}, "unknown permission choice gained authority")
    params = {"command": text, "cwd": str(root)}
    pending = c.public_request("item/commandExecution/requestApproval", params, "request")
    _require(pending["requestId"] == "request" and pending["decision"] is None and set(pending["choices"]) <= {"approve", "deny", "cancel"}, "pending request invented a decision or persistent grant")
    for decision, expected in (("approve", "accept"), ("deny", "decline"), ("cancel", "cancel"), (text, "decline")):
        result = c.server_request_result("item/commandExecution/requestApproval", params, {"decision": decision})
        _require(result == {"decision": expected}, "action approval granted another wire scope")
    permission_request = {"permissions": {"network": True, "filesystem": {"read": [str(root)]}}}
    requested = c.server_request_result("item/permissions/requestApproval", permission_request, {"decision": "approve", "permissions": {"unrequested": True}})
    _require(requested == {"permissions": permission_request["permissions"], "scope": "turn"}, "permission approval widened declared grant or persisted it beyond the turn")
    changes = [{"path": "fixture-雪.txt", "kind": {"type": "update"}, "diff": "-before\n+" + text + "\n+after\n"}]
    projected = c.diff_from_changes(changes, str(root), limit=100)
    _require(projected["files"][0]["path"] == "fixture-雪.txt", "Codex patch path loses original relative target")
    rollout = root / "rollout.jsonl"
    data = [{"type": "fixture", "payload": text}, {"type": "fixture", "payload": "final"}]
    rollout.write_text("\n".join(json.dumps(r) for r in data) + "\n{incomplete", encoding="utf-8")
    tail = c.read_tail_rows(rollout, 1024 if category == "huge" else 200000)
    _require(tail and tail[-1] == data[-1] and all(isinstance(r, dict) for r in tail), "rollout tail inferred partial/oversized JSON rows")
    image_data = base64.b64encode((text or "image").encode()).decode()
    images = [] if category == "empty" else [{"mime": "image/png", "data": image_data}]
    parts = _build_input(text, images)
    _require(parts == ([{"type": "text", "text": text, "text_elements": []}] if text else []) + ([{"type": "image", "url": "data:image/png;base64," + image_data}] if images else []), "Codex input changed exact text or image data")
    _refused(lambda: _build_input("message", [{"mime": "image/png", "data": "invalid base64 !"}]), {"invalid_image"})
    _refused(lambda: _build_input("message", [{"mime": "image/unsupported", "data": image_data}]), {"invalid_image"})
    _refused(lambda: _build_input("message", [{"mime": "image/png", "data": ""}]), {"invalid_image"})
    if category == "huge":
        boundary_data = base64.b64encode(b"x" * MAX_IMAGE_BYTES).decode()
        boundary = _build_input(text, [{"mime": "image/png", "data": boundary_data}])
        _require(boundary[0]["text"] == text and boundary[1]["url"].endswith(boundary_data), "exact decoded image-size boundary refused or changed bytes")
        over = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
        _refused(lambda: _build_input(text, [{"mime": "image/png", "data": over}]), {"image_too_large"})
    installed = {"marketplaces": [{"plugins": [{"id": "owned", "name": text or "fixture", "installed": True, "enabled": True, "availability": "AVAILABLE"}, {"id": "not-installed", "installed": False}]}]}
    plugins, servers, index = build_integrations(installed, [], [])
    _require(len(plugins) == 1 and plugins[0]["id"] == "plugin:owned" and len(index) == 1, "uninstalled integration advertised")
    integration_states = {}
    for observed, expected in (("starting", "starting"), ("disabled", "disabled"), ("failed", "error"), ("authenticationRequired", "needs_sign_in"), ("connected", "connected")):
        server = {"name": "owned-server", "pluginId": "owned", "runtimeStatus": observed, "authStatus": "loggedIn", "tools": {}}
        projected, server_rows, _ = build_integrations(installed, [server], [])
        integration_states[observed] = projected[0]["state"]
        _require(projected[0]["state"] == expected and server_rows[0]["state"] == expected, f"plugin projects sole owned {observed} server as {projected[0]['state']}")
    mixed_states = {}
    for observations, expected in ((("starting", "connected"), "starting"), (("disabled", "disabled"), "disabled"),
                                   (("connected", "disabled"), "connected"), (("authenticationRequired", "starting"), "needs_sign_in"),
                                   (("failed", "authenticationRequired", "connected"), "error")):
        observed_servers = [{"name": f"owned-{n}", "pluginId": "owned", "runtimeStatus": state,
                             "authStatus": "loggedIn", "tools": {}} for n, state in enumerate(observations)]
        snapshot, _, _ = build_integrations(installed, observed_servers, [])
        _require(snapshot[0]["state"] == expected, f"owned server mixture {observations} projected as {snapshot[0]['state']}")
        mixed_states[",".join(observations)] = snapshot[0]["state"]
    observed_servers = [{"name": "owned-changing", "pluginId": "owned", "runtimeStatus": "starting", "authStatus": "loggedIn", "tools": {}}]
    before, _, _ = build_integrations(installed, observed_servers, [])
    observed_servers[0]["runtimeStatus"] = "connected"
    after, _, _ = build_integrations(installed, observed_servers, [])
    _require(before[0]["state"] == "starting" and after[0]["state"] == "connected", "re-observation retained stale integration state or mutated earlier snapshot")
    return {"sequencesChecked": 48, "textBytes": len(raw), "rolloutRows": len(tail), "inputParts": len(parts), "integrationCount": len(plugins),
            "integrationStates": integration_states,
            "mixedIntegrationStates": mixed_states, "resnapshotStates": [before[0]["state"], after[0]["state"]],
            "imageRefusals": ["malformed-base64", "unsupported-mime", "empty-image"] + (["decoded-max-plus-one"] if category == "huge" else []),
            "decodedImageBoundaryBytes": MAX_IMAGE_BYTES if category == "huge" else None}


def _refusals(root, category, text):
    from .connected_sessions.registry import ConnectedError, as_connected
    from .connected_sessions.api import _check_state_root
    from .connected_sessions.workspace import _github_from_remote, _strip_credentials, _checks_summary
    backend = SimpleNamespace(root=root)
    _check_state_root(backend, {"_expectedStateRoot": str(root)})
    other = root / "other"
    other.mkdir()
    _refused(lambda: _check_state_root(backend, {"_expectedStateRoot": str(other)}), {"wrong_state_root"})
    original = ConnectedError("session_busy", text or "busy", 409, owner="app")
    _require(as_connected(original, "fallback") is original, "coded refusal lost status/owner identity")
    fallback = as_connected(ValueError(text), "fallback", "failed", 502)
    _require(fallback.code == "fallback" and fallback.status == 502 and len(fallback.message) <= 507, "uncoded error lost bounded fallback")
    fake = "synthetic-user:synthetic-pass@"  # generated data only, never a credential file.
    url = "https://" + fake + "github.com/fixture/repository.git"
    _require(_strip_credentials(url) == "https://github.com/fixture/repository.git" and _github_from_remote(url) == {"owner": "fixture", "name": "repository", "url": "https://github.com/fixture/repository"}, "remote URL leaks supplied userinfo")
    _require(_github_from_remote("https://example.invalid/" + text) is None, "unsupported remote invented GitHub identity")
    cases = [([], None), ([{"status": "COMPLETED", "conclusion": "SUCCESS", "name": text}], "passing"), ([{"status": "QUEUED", "name": text}], "pending"), ([{"status": "QUEUED", "name": text}, {"conclusion": "FAILURE", "name": text}], "failing")]
    for raw, expected in cases:
        _require(_checks_summary(raw) == expected, "check rollup loses failure/pending precedence")
    return {"wrongStateRootRefused": True, "syntheticUserinfoRemoved": True, "rollups": len(cases), "refusalCharacters": len(text)}


def _writer(root, category, text):
    from .connected_sessions.codex_writer import active_writer
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    home = root / "isolated-home"
    rollout = home / "sessions" / "owned.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    _require(active_writer("owned", rollout) is None, "legacy store invented a writer")
    directory = home / "thread-writer-locks"
    directory.mkdir()
    _require(active_writer("owned", rollout) is False, "missing lock invented ownership")
    thread = "owned-雪" if category == "unicode" else "owned"
    path = directory / (thread + ".lock")
    payload = b"" if category == "empty" else b"x" * 65536 if category == "huge" else text.encode()
    path.write_bytes(payload)
    if category == "stale":
        os.utime(path, (1, 1))
    script = ("import sys,os,msvcrt; f=open(sys.argv[1],'rb+'); "
              "msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); print('READY',flush=True); "
              "sys.stdin.buffer.read(1); os._exit(23 if sys.argv[2]=='interrupted' else 0)")
    process = subprocess.Popen([sys.executable, "-c", script, str(path), category], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
    try:
        _require(process.stdout.readline().strip() == b"READY", "actual writer did not acquire OS byte lock")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                locked = list(pool.map(lambda _: active_writer(thread, rollout), range(12)))
            _require(all(value is True for value in locked), "competing read-only probes lost real OS writer")
        else:
            _require(active_writer(thread, rollout) is True, "real separate OS writer was not observed")
        process.communicate(b"q", timeout=5)
        _require(process.returncode == (23 if category == "interrupted" else 0), "owned writer did not finish expected lifecycle")
        _require(active_writer(thread, rollout) is False and path.read_bytes() == payload, "writer probe changed bytes or leaked ownership after OS release")
        _require(active_writer("../invalid", rollout) is None, "invalid lock target leaves scoped home")
        return {"writerPid": process.pid, "writerExit": process.returncode, "observedLocked": True, "released": True,
                "unchangedLockSha256": hashlib.sha256(payload).hexdigest(), "lockBytes": len(payload)}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def run(root, contracts, categories):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    extra = {"events": {"concurrency", "stale"}, "runs": {"concurrency", "stale", "permissions"}, "recovery": {"interrupted"},
             "seen": {"concurrency", "stale"}, "native": {"stale", "permissions", "concurrency", "interrupted", "offline"},
             "native-items": {"concurrency", "interrupted", "stale"}, "workspace": {"stale", "permissions"},
             "refusals": {"stale", "permissions"}, "writer": {"concurrency", "interrupted", "stale"}, "codex": {"permissions", "stale"}}
    builders = {"events": _events, "runs": _runs, "recovery": _recovery, "seen": _seen, "workspace": _workspace,
                "native": _native, "native-items": _native_items, "codex": _codex, "refusals": _refusals, "writer": _writer}
    for family, identities in FAMILIES.items():
        bound = sorted(identities & contracts.keys())
        if not bound:
            continue
        for category in categories:
            if category not in TEXT and category not in extra.get(family, set()):
                continue
            selected = bound
            category_bindings = {
                ("native", "stale"): {"sessions.neyvia.page", "native.context", "native.goal", "native.route", "native.permission", "native.unsupported", "native.payload", "sessions.neyvia.payload"},
                ("native", "permissions"): {"native.permission", "native.unsupported", "native.payload", "native.context", "native.goal", "native.route", "sessions.neyvia.payload"},
                ("native", "concurrency"): {"native.context", "native.goal", "native.payload", "native.route", "native.permission", "native.unsupported"},
                ("native", "interrupted"): {'native.goal'},
                ("native", "offline"): set(),
                ("workspace", "stale"): {"sessions.workspace.state", "sessions.workspace.cache", "sessions.workspace.diff"},
                ("workspace", "permissions"): {"sessions.workspace.confirm", "sessions.workspace.diff", "sessions.workspace.action"},
                ("runs", "permissions"): {"sessions.run.request"},
                ("refusals", "stale"): {"sessions.api.state_root"},
                ("refusals", "permissions"): {"sessions.api.state_root"},
                ("codex", "permissions"): {"sessions.codex.permissions", "sessions.codex.requests"},
                ("codex", "stale"): {"providers.codex.integrations"},
            }
            if (family, category) in category_bindings:
                selected = [i for i in selected if i in category_bindings[family, category]]
            if not selected:
                continue
            scratch = Path(tempfile.mkdtemp(prefix=f"{family}-{category}-", dir=root))
            row = {"id": f"sessions:{family}:{category}", "category": category, "contracts": selected,
                   "boundary": "actual production owner, generated inputs, independently observed local semantic values/files/SQLite effects"}
            try:
                detail = builders[family](scratch, category, TEXT.get(category, "generated " + category))
                row.update(status="passed", detail=detail)
            except Exception as exc:
                row.update(status="failed", detail=f"{type(exc).__name__}: {exc}", fixtureRoot=str(scratch))
            rows.append(row)
    return rows
