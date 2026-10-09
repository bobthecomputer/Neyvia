"""Generated durable conversation and synthetic account-session journeys.

The builder opens real SQLite stores and independently queries their durable
rows. It never launches an agent/provider, uses credentials, or needs a network.
Every binding follows the operation actually perturbed, rather than a prefix.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

TEXT = {"empty": "", "huge": "bounded large conversation payload " * 4096,
        "unicode": "雪🙂 café e\u0301 שלום العربية \u0000"}
CATEGORIES = ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
PREFIX = "neyvia-core.conversation-"
FAMILIES = {
    "turns": [PREFIX + "turns", PREFIX + "activity"],
    "pages": [PREFIX + "pages"],
    "receipts": [PREFIX + "receipts"],
    "deletion": [PREFIX + "deletion"],
    "import": [PREFIX + "import"],
    "question": [PREFIX + "question"],
    "auth": ["neyvia-core.account-session-binding", "proofs-e-wz.auth-issuance",
             "proofs-e-wz.auth-renewal", "proofs-e-wz.auth-rejection"],
}
SUPPORTED = set().union(*map(set, FAMILIES.values()))
STAMP = "2026-10-04T10:00:00Z"
LATER = "2026-10-04T11:00:00Z"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def refused(action, types=(ValueError, KeyError, RuntimeError, sqlite3.Error)):
    try:
        action()
    except types as error:
        return {"type": type(error).__name__, "reason": str(error)[:300]}
    raise AssertionError("Adverse operation unexpectedly succeeded")


def parallel(action, count=4):
    gate = threading.Barrier(count)
    def worker(index):
        gate.wait(timeout=10)
        return action(index)
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(worker, range(count)))


def state(store):
    """Independent logical byte comparison including indexes and projections."""
    with database(store.database_path) as db:
        return {table: sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}


def database(path):
    return closing(sqlite3.connect(path, isolation_level=None))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()


@contextmanager
def denied(path):
    """Actual Windows sharing denial on one owned database, with no ACL edits."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    require(handle != ctypes.c_void_p(-1).value, f"Owned database denial failed: {ctypes.get_last_error()}")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def new_store(root):
    from .neyvia_conversations import NeyviaConversationStore
    return NeyviaConversationStore(root)


def create(store, identity="owned", mode="automatic"):
    return store.create_conversation(conversation_id=identity, title_mode=mode, now=STAMP)


def append(store, cid="owned", tid="first", text="Durable owned turn", **options):
    return store.append_turn(cid, role="user", content=text, turn_id=tid, now=STAMP, **options)


def crash(root, family):
    completed = subprocess.run([sys.executable, "-m", "grant_agent.edge_fixture_core",
        "--worker", family, "--root", str(root), "--port", os.environ["NEYVIA_C7_PORT"]],
        capture_output=True, text=True, encoding="utf-8", timeout=40,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs())
    require(completed.returncode == 23, f"Owned {family} writer did not exit after durable effect: {completed.stderr[-800:]}")
    return completed.returncode


def import_process_race(root):
    """Three real process writers start against one previously empty store."""
    target = root / "process-race"
    store = new_store(target)
    processes = []
    try:
        for _ in range(3):
            processes.append(subprocess.Popen([sys.executable, "-m", "grant_agent.edge_fixture_core",
                "--worker", "import-race", "--root", str(target), "--port", os.environ["NEYVIA_C7_PORT"]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf8",
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs()))
        deadline = time.monotonic() + 20
        while len(list(target.glob("ready-*"))) != 3 and time.monotonic() < deadline:
            require(all(p.poll() is None for p in processes), "Owned import writer exited before race barrier")
            time.sleep(0.02)
        require(len(list(target.glob("ready-*"))) == 3, "Owned import workers never reached race barrier")
        (target / "go").write_text("owned race authorized", encoding="utf8")
        results = []
        for process in processes:
            output, errors = process.communicate(timeout=30)
            require(process.returncode == 0, f"Owned simultaneous import failed: {errors[-500:]}")
            results.append(json.loads(output))
        require(sum(r["importedConversations"] for r in results) == 1 and sum(r["importedTurns"] for r in results) == 2,
                "Process migration growth receipts overlap or undercount actual unique identities")
        durable = new_store(target).get_conversation("legacy", include_turns=True)
        require({r["turnId"] for r in durable["turns"]} == {"legacy-0", "legacy-1"}, "Process import lost unique durable turn identities")
        return {"processes": 3, "receipts": results, "durableTurnCount": 2, "stateSha256": fingerprint(state(store))}
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def _turns(root, category):
    store = new_store(root)
    base = create(store)
    text = TEXT.get(category, "Durable owned turn")
    if category == "empty":
        before = state(store)
        error = refused(lambda: append(store, text=""))
        require(state(store) == before, "Empty append changed durable state")
        empty_title = store.create_conversation(conversation_id="empty-title", title="", title_mode="suggest", now=STAMP)
        store.append_turn("empty-title", role="assistant", content="Owned heartbeat", meaningful=False, turn_kind="heartbeat", now=LATER)
        observed = new_store(root).get_conversation("empty-title")
        require(observed["title"] == "New conversation" and observed["generatedTitle"] == "Owned heartbeat" and observed["updatedAt"] == empty_title["updatedAt"] and observed["lastMeaningfulActivityAt"] == empty_title["lastMeaningfulActivityAt"], "Empty-title heartbeat changed meaningful timestamps or lost suggested-title policy")
        return FAMILIES["turns"], {"refusal": error, "preservedStateSha256": fingerprint(before), "emptyTitleHeartbeatPreserved": True}
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: append(store), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied append changed durable state")
        return [PREFIX + "turns", PREFIX + "activity"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    if category == "interrupted":
        code = crash(root, "turns")
        turn = new_store(root).get_turn("first")
        require(turn["content"] == text, "Committed turn did not survive owned writer exit")
    elif category == "concurrency":
        revision = base["revision"]
        def compete(index):
            try:
                return {"turn": append(store, tid=f"cas-{index}", text=text, expected_revision=revision)}
            except RuntimeError as error:
                return {"conflict": str(error)}
        results = parallel(compete)
        require(sum("turn" in result for result in results) == 1, "Same-revision writers did not conserve one winner")
        require(sum("conflict" in result for result in results) == 3, "CAS loser did not report conflict")
        turn = next(result["turn"] for result in results if "turn" in result)
    else:
        turn = append(store, text=text, expected_revision=base["revision"], idempotent=True)
    after = store.get_conversation("owned", include_turns=True)
    require(after["revision"] == base["revision"] + 1 and len(after["turns"]) == 1,
            "Append lost exactly-once revision or identity")
    require(after["turns"][0]["content"] == text.strip(), "Turn content changed in durable storage")
    if category == "stale":
        before = state(store)
        refused(lambda: append(store, tid="stale", expected_revision=base["revision"]))
        replay = append(store, text=text, expected_revision=base["revision"], idempotent=True)
        require(replay == turn and state(store) == before, "Idempotent replay changed durable state")
        refused(lambda: append(store, text="Different authored payload", idempotent=True))
        require(state(store) == before, "Different same-ID reuse changed durable state")
    # Check both automatic and suggest title policies with exact expected text.
    from .neyvia_conversations import generated_title
    require(after["title"] == generated_title(text), "Automatic title differs from exact supplied text")
    if category != "stale":
        suggestion = create(store, "suggested", "suggest")
        append(store, "suggested", "heartbeat", text=text, meaningful=False)
        result = store.get_conversation("suggested")
        require(result["title"] == "New conversation" and result["generatedTitle"] == generated_title(text),
                "Suggested title escaped policy or was not durable")
        require(result["updatedAt"] == suggestion["updatedAt"] and result["lastMeaningfulActivityAt"] == suggestion["lastMeaningfulActivityAt"],
                "Heartbeat advanced meaningful timestamps")
    return FAMILIES["turns"], {"revision": after["revision"], "turnIds": [r["turnId"] for r in after["turns"]],
            "contentBytes": len(text.encode()), "contentSha256": hashlib.sha256(text.encode()).hexdigest(),
            "stateSha256": fingerprint(state(store))}


def _pages(root, category):
    store = new_store(root)
    create(store)
    if category == "empty":
        page = store.get_conversation_page("owned", turn_limit=0)
        require(page["turns"] == [] and page["turnPage"]["totalTurns"] == 0 and page["turnPage"]["turnLimit"] == 1,
                "Empty page fabricated history or failed lower clamp")
        return FAMILIES["pages"], {"page": page["turnPage"]}
    count = 203 if category == "huge" else 9
    text = TEXT["unicode"] if category == "unicode" else "Page content"
    for index in range(count):
        append(store, tid=f"page-{index:03d}", text=f"{text} {index}")
    if category == "interrupted":
        crash(root, "pages")
        count += 1
        store = new_store(root)
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: store.get_conversation_page("owned"), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied page changed durable state")
        return FAMILIES["pages"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    def traverse(_=0):
        cursor, pages, observed = "", [], []
        for _ in range(count + 1):
            page = store.get_conversation_page("owned", turn_limit=200000 if category == "huge" else 4, before_turn_id=cursor)
            pairs = [(row["createdAt"], row["turnId"]) for row in page["turns"]]
            require(pairs == sorted(pairs), "Page is not chronological")
            require(page["turnPage"]["totalTurns"] == count and page["turnPage"]["returnedTurns"] == len(pairs), "Page count differs from durable rows")
            pages.append(page["turnPage"])
            observed.extend(row["turnId"] for row in page["turns"])
            cursor = page["turnPage"]["beforeTurnId"]
            if not cursor:
                break
        require(len(observed) == count and len(set(observed)) == count, "Exclusive cursor lost or duplicated a turn")
        return observed, pages
    traversals = parallel(traverse) if category == "concurrency" else [traverse()]
    if category == "stale":
        first = store.get_conversation_page("owned", turn_limit=4)
        cursor = first["turnPage"]["beforeTurnId"]
        expected = store.get_conversation_page("owned", turn_limit=4, before_turn_id=cursor)["turns"]
        store.append_turn("owned", role="user", content="Newer appended turn", turn_id="z-newer", now=LATER)
        actual = store.get_conversation_page("owned", turn_limit=4, before_turn_id=cursor)["turns"]
        require(actual == expected, "Historical cursor was invalidated or overlapped a later append")
        other = create(store, "other")
        refused(lambda: store.get_conversation_page(other["conversationId"], before_turn_id=cursor))
    return FAMILIES["pages"], {"durableTurnCount": count, "traversalIds": traversals[0][0], "pages": traversals[0][1], "readers": len(traversals)}


def _receipts(root, category):
    store = new_store(root)
    create(store)
    create(store, "other")
    if category == "empty":
        require(store.list_turn_receipts("owned") == [], "Empty receipt index invented receipt")
        append(store)
        refused(lambda: store.get_turn_receipt("owned", "first"))
        return FAMILIES["receipts"], {"emptyIndex": True, "turnWithoutReceiptRefused": True}
    receipt = {"schema": "fluxio.turn_receipt.v1", "status": "completed", "runtime": "owned-fixture", "provenance": TEXT.get(category, "real local runtime result")}
    def write(index):
        return append(store, tid=f"receipt-{index}", text="PRIVATE TRANSCRIPT CONTENT", metadata={"runtimeResult": {"compartment": {"turnReceipt": {**receipt, "id": index}}}})
    count = 4 if category == "concurrency" else 1
    if category == "concurrency":
        parallel(write)
    elif category == "interrupted":
        crash(root, "receipts")
    else:
        write(0)
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: store.list_turn_receipts("owned"), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied receipt read changed durable state")
        return FAMILIES["receipts"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    reopened = new_store(root)
    rows = reopened.list_turn_receipts("owned")
    require(len(rows) == count and len({r["turnId"] for r in rows}) == count, "Receipt indexes lost or duplicated identity")
    for row in rows:
        require(set(row) == {"turnId", "conversationId", "createdAt", "receipt"}, "Receipt exposes transcript fields")
        require(reopened.get_turn_receipt("owned", row["turnId"]) == row, "Receipt cannot reopen nested runtime provenance")
        require(row["receipt"] == {**receipt, "id": int(row["turnId"].split("-")[-1])}, "Receipt changed exact nested provenance")
    before = state(store)
    refused(lambda: store.get_turn_receipt("other", rows[0]["turnId"]))
    require(state(store) == before, "Cross-conversation receipt refusal changed storage")
    if category == "stale":
        append(store, tid="later", text="A newer unrelated private turn")
        require(store.get_turn_receipt("owned", rows[0]["turnId"]) == rows[0], "Saved receipt identity resolved to newer text")
    require("PRIVATE TRANSCRIPT CONTENT" not in json.dumps(rows), "Receipt result leaks turn text")
    return FAMILIES["receipts"], {"receiptCount": len(rows), "receiptSha256": fingerprint(rows), "crossConversationRefused": True}


def _deletion(root, category):
    store = new_store(root)
    count = 4 if category == "concurrency" else 1
    if category == "empty":
        before = state(store)
        error = refused(lambda: store.delete_conversation(""))
        require(state(store) == before, "Empty deletion changed durable state")
        return FAMILIES["deletion"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    text = "indexed deletion sentinel " + TEXT.get(category, "owned decision")
    for index in range(count):
        cid = f"delete-{index}"
        create(store, cid)
        append(store, cid, f"delete-turn-{index}", text=text)
        store.put_context_atom(cid, kind="decision", content=text, now=STAMP)
    require(store.search("deletion sentinel")["results"], "Deletion fixture did not enter search")
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: store.delete_conversation("delete-0", now=LATER), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied deletion changed durable state")
        return FAMILIES["deletion"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    if category == "concurrency":
        parallel(lambda index: store.delete_conversation(f"delete-{index}", now=LATER))
    elif category == "interrupted":
        crash(root, "deletion")
    else:
        store.delete_conversation("delete-0", now=LATER)
    reopened = new_store(root)
    require(not reopened.search("deletion sentinel")["results"] and not reopened.retrieve_context("deletion sentinel")["items"], "Deleted context remains discoverable")
    with database(reopened.database_path) as db:
        tombstones = db.execute("SELECT conversation_id,status,deleted_at FROM conversations ORDER BY conversation_id").fetchall()
        atoms = db.execute("SELECT deleted_at FROM context_atoms").fetchall()
    require(len(tombstones) == count and all(r[1:] == ("deleted", LATER) for r in tombstones), "Deleted conversation lost exact tombstone")
    require(len(atoms) == count and all(r == (LATER,) for r in atoms), "Deletion failed to retire context in transaction")
    if category == "stale":
        before = state(store)
        refused(lambda: store.delete_conversation("delete-0", now="2026-10-04T12:00:00Z"))
        refused(lambda: append(store, "delete-0", "post-delete"))
        require(state(store) == before, "Stale deleted identity rewrote tombstone or admitted turn")
    return FAMILIES["deletion"], {"tombstones": tombstones, "retiredAtoms": len(atoms), "stateSha256": fingerprint(state(reopened))}


def legacy(category):
    text = TEXT.get(category, "legacy search sentinel durable turn")
    if category == "empty":
        return {}
    count = 12 if category == "huge" else 2
    return {"chatSessions": [{"id": "legacy", "title": "Recovered owned thread", "createdAt": STAMP}],
            "chatSessionTranscripts": {"legacy": [{"id": f"legacy-{index}", "role": "user", "title": text, "createdAt": STAMP} for index in range(count)] + [{"id": "pending", "title": "not yet durable", "pending": True}]}}


def _import(root, category):
    store = new_store(root)
    payload = legacy(category)
    if category == "empty":
        before = state(store)
        result = store.import_legacy_state(payload)
        require(result["importedConversations"] == result["importedTurns"] == 0 and state(store) == before, "Empty migration invented durable identities")
        return FAMILIES["import"], {"migration": result}
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: store.import_legacy_state(payload), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied import changed durable identities")
        return FAMILIES["import"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    if category == "concurrency":
        results = parallel(lambda _: store.import_legacy_state(payload))
        require(sum(r["importedConversations"] for r in results) == 1 and sum(r["importedTurns"] for r in results) == 2,
                "Thread migration growth receipts overlap or undercount actual unique identities")
        process_race = import_process_race(root)
    elif category == "interrupted":
        crash(root, "import")
        results = [store.import_legacy_state(payload)]
    else:
        results = [store.import_legacy_state(payload)]
    before = state(store)
    replay = new_store(root).import_legacy_state(payload)
    require(replay["importedConversations"] == replay["importedTurns"] == 0 and state(store) == before, "Migration replay created duplicate identities or changed storage")
    expected = payload["chatSessionTranscripts"]["legacy"][:-1]
    turns = new_store(root).get_conversation("legacy", include_turns=True)["turns"]
    require({r["turnId"] for r in turns} == {r["id"] for r in expected}, "Migration lost identity or imported pending placeholder")
    require(all(r["content"] == expected[0]["title"].strip() for r in turns), "Migration changed exact authored text")
    if category == "stale":
        append(store, "legacy", "fresh", text="Newer authored durable turn")
        before = state(store)
        stale = store.import_legacy_state(payload)
        require(state(store) == before and stale["importedTurns"] == 0, "Old JSON snapshot overwrote newer conversation source")
    return FAMILIES["import"], {"imports": results, "replay": replay, "durableTurnIds": [r["turnId"] for r in turns], "stateSha256": fingerprint(state(store)),
                              **({"crossProcess": process_race} if category == "concurrency" else {})}


def _question(root, category):
    store = new_store(root)
    create(store)
    text = TEXT.get(category, "Which owned source establishes this conclusion?")
    if category == "empty":
        # Current API has no empty question admission check before creating the
        # branch; demand transactionally unchanged state on refused creation.
        before = state(store)
        error = refused(lambda: store.create_question_branch("owned", question="", now=STAMP))
        require(state(store) == before, "Empty question refusal left orphaned durable branch without initial user turn")
        return FAMILIES["question"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    if category == "permissions":
        before = state(store)
        with denied(store.database_path):
            error = refused(lambda: store.create_question_branch("owned", question=text, now=STAMP), (sqlite3.Error, OSError))
        require(state(store) == before, "Sharing-denied question branch changed durable state")
        return FAMILIES["question"], {"refusal": error, "preservedStateSha256": fingerprint(before)}
    if category == "concurrency":
        results = parallel(lambda _: store.create_question_branch("owned", question=text, now=STAMP))
    elif category == "interrupted":
        crash(root, "question")
        results = [r for r in store.list_conversations() if r.get("branchKind") == "question"]
    else:
        results = [store.create_question_branch("owned", question=text, now=STAMP)]
    for branch in results:
        reopened = new_store(root).get_conversation(branch["conversationId"], include_turns=True)
        require(reopened["parentConversationId"] == "owned" and reopened["capabilityPolicy"]["readOnly"] and len(reopened["turns"]) == 1 and reopened["turns"][0]["content"] == text.strip(), "Question lost parent, exact user turn or durable read-only policy")
        for action in ["file.write", "email.send", "shell.exec", "", "purchase.commit"]:
            require(not store.action_allowed(branch["conversationId"], action)["allowed"], "Question branch granted mutation")
        require(store.action_allowed(branch["conversationId"], "file.read")["allowed"], "Question branch refused declared read")
    require(len(results) == (4 if category == "concurrency" else 1), "Concurrent question branch identities were lost")
    return FAMILIES["question"], {"branchCount": len(results), "ids": [r["conversationId"] for r in results], "parent": "owned", "mutationRefused": True}


def _auth(root, category):
    from .web_auth_sessions import WebAuthSessions, WEB_AUTH_SESSION_RENEW_AFTER_SECONDS
    current = [1000000.0]
    identities = {"owned": "synthetic account v1"}
    store = WebAuthSessions(root, auth_identity="synthetic shared fingerprint", user_identity=identities.get, clock=lambda: current[0])
    if category == "empty":
        with database(store.path) as db:
            before = db.execute("SELECT * FROM web_auth_sessions").fetchall()
        error = refused(lambda: store.issue({}))
        require(store.lookup("") is None, "Empty token authenticated")
        with database(store.path) as db:
            require(db.execute("SELECT * FROM web_auth_sessions").fetchall() == before, "Empty session issuance changed storage")
        token = store.issue({"username": "owned", "displayName": "", "role": "account"}, user_agent="", address="")
        public = store.lookup(token)
        with database(store.path) as db:
            saved = db.execute("SELECT identity_hash,username FROM web_auth_sessions WHERE token_hash=?", (store._token_hash(token),)).fetchone()
        require(public["username"] == "owned" and saved == (store._identity_for("owned"), "owned") and public["displayName"] == "owned", "Empty metadata lookup lost accepted exact account/session binding")
        return ["proofs-e-wz.auth-issuance", "neyvia-core.account-session-binding"], {"refusal": error, "emptyTokenAuthenticated": False, "emptyMetadataSessionBound": True}
    label = TEXT.get(category, "Synthetic account")
    def issue(_=0):
        return store.issue({"username": "owned", "displayName": label, "role": "account"}, user_agent=label, address=label)
    if category == "permissions":
        token = issue()
        expired = issue()
        current[0] += WEB_AUTH_SESSION_RENEW_AFTER_SECONDS + 301
        with database(store.path) as db:
            db.execute("UPDATE web_auth_sessions SET expires_at=? WHERE token_hash=?", (current[0] - 1, store._token_hash(expired)))
        with database(store.path) as db:
            before = db.execute("SELECT * FROM web_auth_sessions").fetchall()
        with denied(store.path):
            error = refused(issue, (sqlite3.Error, OSError))
            denied_lookup = refused(lambda: store.lookup(token), (sqlite3.Error, OSError))
            denied_rejection = refused(lambda: store.lookup(expired), (sqlite3.Error, OSError))
        with database(store.path) as db:
            require(db.execute("SELECT * FROM web_auth_sessions").fetchall() == before, "Sharing-denied issuance changed sessions")
        public = store.lookup(token)
        require(public["username"] == "owned" and store.lookup(expired) is None, "Account session failed to recover real lookup/renewal/rejection after OS denial")
        with database(store.path) as db:
            require(db.execute("SELECT expires_at,last_seen FROM web_auth_sessions").fetchall() == [(current[0] + store.ttl_seconds, current[0])], "Retried renewal/rejection not durably exact")
        return FAMILIES["auth"], {"refusal": error, "lookupRefusal": denied_lookup, "rejectionRefusal": denied_rejection, "preservedSessionCount": len(before), "renewalAndRejectionRecovered": True}
    tokens = parallel(issue) if category == "concurrency" else [issue()]
    require(len(set(tokens)) == len(tokens), "Concurrent issuance repeated a bearer")
    with database(store.path) as db:
        rows = db.execute("SELECT token_hash,identity_hash,username,display_name,user_agent,address FROM web_auth_sessions").fetchall()
    require(len(rows) == len(tokens) and all(len(r[0]) == 64 and r[3] == label and r[4] == label[:300] and r[5] == label[:80] for r in rows), "Session issuance lost exact payload or documented string bounds")
    require(all(token not in json.dumps(rows) for token in tokens), "Storage persisted bearer token instead of digest")
    current[0] += WEB_AUTH_SESSION_RENEW_AFTER_SECONDS + 301
    publics = parallel(lambda index: store.lookup(tokens[index])) if category == "concurrency" else [store.lookup(tokens[0])]
    require(all(p["username"] == "owned" and p["displayName"] == label and len(p["sessionId"]) == 16 for p in publics), "Accepted lookup lost principal/public identity")
    with database(store.path) as db:
        expiries = db.execute("SELECT expires_at,last_seen FROM web_auth_sessions").fetchall()
    require(all(r == (current[0] + store.ttl_seconds, current[0]) for r in expiries), "Renewal was not durably written")
    if category == "interrupted":
        # Child lookup starts from a legacy shared row and exits before sending
        # a result; reopen must observe upgraded binding and renewal.
        token = tokens[0]
        expired_token = issue()
        with database(store.path) as db:
            db.execute("UPDATE web_auth_sessions SET identity_hash=?, expires_at=?, last_seen=? WHERE token_hash=?",
                       (store._identity_hash, 1000000.0 + store.ttl_seconds, 1000000.0, store._token_hash(token)))
            db.execute("UPDATE web_auth_sessions SET expires_at=? WHERE token_hash=?",
                       (current[0] - 1, store._token_hash(expired_token)))
        marker = root / "worker-token.json"
        marker.write_text(json.dumps({"token": token, "rejectToken": expired_token, "clock": current[0]}), encoding="utf8")
        crash(root, "auth")
        marker.unlink()
        reopened = WebAuthSessions(root, auth_identity="synthetic shared fingerprint", user_identity=identities.get, clock=lambda: current[0])
        require(reopened.lookup(token)["username"] == "owned", "Accepted session upgrade did not survive child exit")
        with database(store.path) as db:
            require(db.execute("SELECT identity_hash FROM web_auth_sessions").fetchone()[0] == store._identity_for("owned"), "Legacy shared identity was not durably upgraded")
            require(db.execute("SELECT expires_at,last_seen FROM web_auth_sessions").fetchall() == [(current[0] + store.ttl_seconds, current[0])], "Child renewal/rejection was not durable before writer exit")
        marker.write_text(json.dumps({"clock": current[0]}), encoding="utf8")
        crash(root, "auth-issuance")
        added = json.loads(marker.read_text(encoding="utf8"))["issuedToken"]
        marker.unlink()
        accepted = reopened.lookup(added)
        require(accepted["username"] == "owned", "Committed issuance did not survive process exit before acknowledgement")
        tokens.append(added)
    identities["owned"] = "synthetic account v2"
    rejected = parallel(lambda index: store.lookup(tokens[index])) if category == "concurrency" else [store.lookup(token) for token in tokens]
    require(all(p is None for p in rejected), "Changed account identity kept old session valid")
    with database(store.path) as db:
        require(db.execute("SELECT COUNT(*) FROM web_auth_sessions").fetchone()[0] == 0, "Rejected session stayed persisted")
    if category == "stale":
        fresh_token = store.issue({"username": "owned", "displayName": "current identity", "role": "account"})
        fresh_public = store.lookup(fresh_token)
        with database(store.path) as db:
            stored_identity = db.execute("SELECT identity_hash FROM web_auth_sessions WHERE token_hash=?", (store._token_hash(fresh_token),)).fetchone()[0]
        require(fresh_public["username"] == "owned" and stored_identity == store._identity_for("owned"), "Fresh issuance reused stale removed account identity")
    identities = (["neyvia-core.account-session-binding", "proofs-e-wz.auth-rejection", "proofs-e-wz.auth-issuance"] if category == "stale"
                  else FAMILIES["auth"] if category == "interrupted"
                  else FAMILIES["auth"])
    return identities, {"issuedSessionCount": len(tokens), "storedBearerCount": 0, "renewalPersisted": True, "changedIdentityRejected": True, "sessionIds": [p["sessionId"] for p in publics]}


BUILDERS = {"turns": _turns, "pages": _pages, "receipts": _receipts, "deletion": _deletion, "import": _import, "question": _question, "auth": _auth}


def run(root, contracts, categories, families=None):
    rows = []
    for family, builder in BUILDERS.items():
        if families and family not in families:
            continue
        for category in categories:
            if category == "offline" or family == "question" and category == "stale":
                continue
            target = root / f"{family}-{category}-{uuid.uuid4().hex[:8]}"
            target.mkdir(parents=True, exist_ok=False)
            started = time.monotonic()
            row = {"id": f"core:{family}:{category}", "category": category,
                   "contracts": [c for c in FAMILIES[family] if c in contracts], "scratchRoot": str(target),
                   "boundary": "real production SQLite operation, independent durable rows and actual owned process exit or OS sharing refusal"}
            try:
                identities, detail = builder(target, category)
                row.update(status="passed", contracts=[c for c in identities if c in contracts], detail=detail)
            except Exception as error:
                row.update(status="failed", error=f"{type(error).__name__}: {error}")
                print(json.dumps({"failure": row["id"], "error": row["error"]}), flush=True)
            row["durationMs"] = round((time.monotonic() - started) * 1000, 2)
            if row["contracts"]:
                rows.append(row)
    return rows


def blocker(contract, category):
    if contract["id"] in SUPPORTED and category == "offline":
        return {"kind": "not_applicable", "reason": "Audited owner uses selected-root local SQLite and supplied account identities only; no network/provider request or endpoint exists in this exact durable-store claim."}
    if contract["id"] == PREFIX + "question" and category == "stale":
        return {"kind": "not_applicable", "reason": "Question branch action_allowed reads current durable policy; this exact owner accepts no revision or cached authorization token. Turn CAS and account identity revocation are exercised separately."}
    return None


def isolate(root, port):
    from .proof_ports import c7_port_block
    c7_port_block(port)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        location = root / "home" / name.lower()
        location.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(location)
    os.environ.update(NEYVIA_C7_PORT=str(port), NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_TOOL_AUTO_UPDATE="0")
    for name in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(name, None)
    from .proof_credential_guard import install
    install(root)
    def audit(event, args):
        if event in {"socket.connect", "socket.bind"}:
            raise PermissionError("Core durable-store fixtures have no network authority")
    sys.addaudithook(audit)


def worker(root, family):
    if family == "import-race":
        store = new_store(root)
        (root / f"ready-{os.getpid()}").write_text("ready", encoding="utf8")
        deadline = time.monotonic() + 20
        while not (root / "go").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        require((root / "go").exists(), "Owned import barrier timed out")
        print(json.dumps(store.import_legacy_state(legacy("concurrency"))), flush=True)
        return
    if family in {"auth", "auth-issuance"}:
        from .web_auth_sessions import WebAuthSessions
        saved = json.loads((root / "worker-token.json").read_text(encoding="utf8"))
        store = WebAuthSessions(root, auth_identity="synthetic shared fingerprint", user_identity=lambda _: "synthetic account v1", clock=lambda: saved["clock"])
        if family == "auth-issuance":
            token = store.issue({"username": "owned", "displayName": "owned interrupted issuance", "role": "account"})
            (root / "worker-token.json").write_text(json.dumps({"issuedToken": token}), encoding="utf8")
            os._exit(23)
        require(store.lookup(saved["token"]), "Owned upgrade worker could not authenticate synthetic token")
        require(store.lookup(saved["rejectToken"]) is None, "Owned rejection worker accepted expired synthetic token")
    else:
        store = new_store(root)
        if family == "turns": append(store)
        elif family == "pages": append(store, tid="z-child", text="Child persisted page")
        elif family == "receipts": append(store, tid="receipt-0", text="PRIVATE TRANSCRIPT CONTENT", metadata={"runtimeResult": {"compartment": {"turnReceipt": {"schema": "fluxio.turn_receipt.v1", "status": "completed", "runtime": "owned-fixture", "provenance": "real local runtime result", "id": 0}}}})
        elif family == "deletion": store.delete_conversation("delete-0", now=LATER)
        elif family == "import": store.import_legacy_state(legacy("interrupted"))
        elif family == "question": store.create_question_branch("owned", question="Which owned source establishes this conclusion?", now=STAMP)
    os._exit(23)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=(*BUILDERS, "import-race", "auth-issuance"))
    parser.add_argument("--family", action="append", choices=tuple(BUILDERS))
    parser.add_argument("--category", action="append", choices=CATEGORIES)
    args = parser.parse_args()
    isolate(args.root.resolve(), args.port)
    if args.worker:
        worker(args.root, args.worker)
        return 0
    require(args.output is not None, "Standalone campaign requires output receipt")
    from .edge_contracts import inventory
    _, contracts = inventory()
    repo = Path(__file__).resolve().parents[2]
    names = ["src/grant_agent/edge_fixture_core.py", "src/grant_agent/neyvia_conversations.py", "src/grant_agent/semantic_missions.py", "src/grant_agent/turn_compartment.py", "src/grant_agent/harness_jobs.py", "src/grant_agent/web_auth_sessions.py", "src/grant_agent/proofs_d_neyvia.py", "src/grant_agent/proofs_e_wz.py"]
    bindings = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
    started = time.monotonic()
    rows = run(args.root, contracts, args.category or CATEGORIES, args.family)
    source_stable = bindings == {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
    passed = {(c, row["category"]) for row in rows if row["status"] == "passed" for c in row["contracts"]}
    report = {"schema": "neyvia.c7c.core-fixtures.v1", "ok": source_stable and all(row["status"] == "passed" for row in rows),
              "sourceStable": source_stable, "sourceBindings": bindings, "rows": rows, "passedPairs": len(passed),
              "explicitPort": args.port, "networkAuthority": False, "durationMs": round((time.monotonic() - started) * 1000, 2)}
    args.output.resolve().relative_to(repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"ok": report["ok"], "passedPairs": len(passed), "failures": [r for r in rows if r["status"] == "failed"], "durationMs": report["durationMs"]}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
