"""Remaining session contracts on generated state and owned local transports."""
from __future__ import annotations
import argparse
from contextlib import ExitStack, contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

from .edge_fixture_local import require, refused
from .edge_contracts import CATEGORIES

MODULE = "grant_agent.edge_fixture_c7d_sessions"
REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "owned bounded " * 10000, "unicode": "雪🙂e\u0301\u202e العربية"}
# Finite public protocol copied from the control family's CLAUDE_LOCAL_PEER.
# It is fixture input, and never attests an installed model/provider response.
CLAUDE_LOCAL_PEER = r'''
import json,os,sys,uuid
from pathlib import Path
root=Path(os.environ['C7D_PEER_ROOT']); mode=os.environ.get('C7D_PEER_MODE','turn')
def send(value):
    print(json.dumps(value,ensure_ascii=True),flush=True)
if 'agents' in sys.argv:
    print('[]');sys.exit(0)
sid='owned-'+uuid.uuid4().hex
if '--resume' in sys.argv:
    sid='unexpected-copy' if mode=='fork' else sys.argv[sys.argv.index('--resume')+1]
records=[]
for line in sys.stdin:
    value=json.loads(line);records.append(value)
    if value.get('type')=='user':
        content=value['message']['content'][0]['text'];break
send({'type':'system','subtype':'init','session_id':sid,'model':'owned-protocol'})
if mode in ('reply','interrupt'):
    send({'type':'control_request','request_id':'owned-approval','request':{'subtype':'can_use_tool','tool_name':'Bash','input':{'command':'owned literal'},'tool_use_id':'owned-tool'}})
    for line in sys.stdin:
        value=json.loads(line);records.append(value)
        if value.get('type')=='control_response':
            if value['response']['response'].get('interrupt'):
                (root/('wire-'+sid+'.json')).write_text(json.dumps(records),encoding='utf8');os._exit(23)
            break
    send({'type':'control_request','request_id':'owned-question','request':{'subtype':'can_use_tool','tool_name':'AskUserQuestion','input':{'questions':[{'question':'Owned question','header':'Owned','options':[{'label':'A','description':'Owned'}],'multiSelect':False}]},'tool_use_id':'owned-question-tool'}})
    for line in sys.stdin:
        value=json.loads(line);records.append(value)
        if value.get('type')=='control_response':break
(root/('wire-'+sid+'.json')).write_text(json.dumps(records),encoding='utf8')
send({'type':'assistant','session_id':sid,'message':{'id':'owned-assistant','model':'owned-protocol','content':[{'type':'text','text':content}]}})
send({'type':'result','subtype':'success','is_error':False,'session_id':sid,'result':content,'usage':{'input_tokens':1,'output_tokens':1}})
'''
EXCLUDED = {"sessions.api.allowlist", "sessions.broker.catalogue", "sessions.broker.read", "sessions.broker.media", "sessions.broker.options", "sessions.broker.registry"}
IDS = {"sessions." + value for value in ("api.authority", "api.forward", "api.media", "api.poll", "api.response", "api.sse", "api.state_root", "broker.controls", "broker.unread", "codex.rollout", "events.subscription", "folders.availability", "folders.catalogue", "folders.confirm", "folders.filter", "neyvia.page", "neyvia.payload", "neyvia.summary", "opencode.inventory", "run.lifecycle", "run.recovery", "run.request", "run.watchdog", "workspace.action", "workspace.cache", "workspace.cli", "workspace.confirm", "workspace.diff", "workspace.github", "workspace.state")}
INTENDED = {identity: set(CATEGORIES) for identity in IDS}
for suffix, categories in {
    "api.state_root": "concurrency interrupted offline", "broker.unread": "interrupted permissions offline",
    "codex.rollout": "concurrency interrupted permissions offline stale", "folders.catalogue": "concurrency interrupted permissions offline stale",
    "neyvia.page": "concurrency interrupted permissions offline", "neyvia.payload": "concurrency interrupted offline",
    "neyvia.summary": "concurrency interrupted permissions offline stale", "run.lifecycle": "interrupted permissions offline",
    "run.recovery": "concurrency permissions offline stale", "run.request": "interrupted offline",
    "workspace.action": "concurrency interrupted offline stale", "workspace.cache": "concurrency interrupted permissions offline",
    "workspace.cli": "concurrency interrupted permissions offline stale", "workspace.confirm": "concurrency interrupted offline stale",
    "workspace.diff": "concurrency interrupted offline", "workspace.state": "concurrency interrupted permissions offline",
}.items(): INTENDED["sessions." + suffix] = set(categories.split())

def text(category): return TEXT.get(category, "owned local observation")

def blocker(contract, category):
    identity = contract["id"]
    reason = None
    if identity in {"sessions.neyvia.payload", "sessions.neyvia.summary"} and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        reason = "Exact _attachments/_payload or _summary projects current supplied composer/row/context values. _summary attention classification consumes the supplied row; it does not reread a conversation revision. Neither invokes a provider, admits a prior state token, persists a writer journal or decides an OS grant. Saved-page and actual turn effects are distinct owners."
    elif identity in {"sessions.api.state_root", "sessions.neyvia.page", "sessions.codex.rollout", "sessions.folders.catalogue", "sessions.folders.filter", "sessions.workspace.state", "sessions.workspace.cache", "sessions.workspace.diff"} and category in {"interrupted", "offline"}:
        reason = "This exact owner reads selected local paths/SQL/Git bytes, returns a cached detached observation or computes a supplied expected-root comparison. It starts no network request and publishes no durable mutation or resumable result journal. Interrupted provider turns and repository writers remain separate invariants."
    elif identity == "sessions.broker.unread" and category == "offline":
        reason = "SeenStore.unread compares local timestamps/sequence numbers against its selected persisted marker; it has no remote endpoint or provider invocation."
    elif identity == "sessions.run.lifecycle" and category == "offline":
        reason = "Exact _set_state/public_run terminal projection consumes current local run fields and writes the local run record; it performs no endpoint request. Actual adapter start/control connectivity belongs to broker request/control contracts."
    elif identity in {"sessions.events.subscription", "sessions.run.watchdog"} and category in {"interrupted", "permissions", "offline"}:
        reason = ("subscription owns an in-process unique-token set and lexical finally cleanup; it has no durable journal, external grant or endpoint" if identity.endswith("subscription") else "watchdog selection examines current in-process state/stop flag/last-output values, then interrupts only a selected owned adapter; selection owns no grant, endpoint or resumable writer journal")
    elif identity == "sessions.folders.confirm" and category in {"concurrency", "interrupted", "offline", "stale"}:
        reason = "Unconfirmed clone/worktree refusal precedes any process, directory or network operation. It consumes current confirm/repository/branch arguments, with no prior revision or resumable effect; confirmed Git execution is separate."
    elif identity == "sessions.folders.availability" and category in CATEGORIES:
        reason = "The exact absent-GitHub-CLI invariant accepts zero payload arguments. With an explicitly empty executable-discovery path, github_status reports unavailable and github_repos never accesses an account. No input collection, grant, endpoint, shared mutation, durable writer or prior revision is admitted; finite CLI projections are separately exercised by workspace.github."
    elif identity in {"sessions.workspace.confirm"} and category in {"concurrency", "interrupted", "offline", "stale"}:
        reason = "git_action's literal-True confirmation refusal returns before any Git child or filesystem mutation, using only current supplied confirmation. Confirmed mutations and observer caches remain separate invariants."
    elif identity == "sessions.opencode.inventory" and category in {"interrupted", "offline"}:
        reason = "OpenCodeAdapter.read reads only selected generated saved SQL history and current native CLI presence, returning an in-memory page. It performs no provider call, network, document mutation or resumable writer publication. Actual ACP provider execution is separate."
    elif identity in {"sessions.workspace.action", "sessions.workspace.cli"} and category == "stale":
        reason = "Exact current Git/finite CLI invocation and exit-status projection accepts no original revision or cached authorization token. Its caller supplies current argv/confirmation; observer TTL/invalidation and remote publication are separate owners."
    elif identity in {"sessions.api.authority", "sessions.api.response", "sessions.api.poll", "sessions.api.sse", "sessions.api.media"} and category == "offline":
        reason = "This exact incoming local HTTP owner consumes an already accepted authenticated request and selected local broker/store bytes; it never opens a provider endpoint. A closed client socket is exercised under interrupted, while service-unavailable dialing belongs to api.forward. No provider-offline applicability is inferred from a saved model or attachment."
    if reason:
        return {"kind": "not_applicable", "reason": f"Audited {identity} at {contract.get('checkedAt', [])}: {reason}"}
    return None

def _isolate(root, port):
    root = Path(root).resolve()
    require(root.is_relative_to(REPO / ".agent_control/proofs"), "Generated session proof root required")
    from .proof_ports import c7_port_block
    c7_port_block(port)
    root.mkdir(parents=True, exist_ok=True)
    for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / key.lower(); directory.mkdir(parents=True, exist_ok=True); os.environ[key] = str(directory)
    for key in ("CODEX_HOME", "NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WEB_BACKEND_URL", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_C7_PORT=str(port), NEYVIA_CONNECTED_SERVICE_PORT=str(port), NEYVIA_WEB_PORT=str(port), FLUXIO_WEB_PORT=str(port), NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", CLAUDE_CONFIG_DIR=str(root / "claude"), OPENCODE_DATA_DIR=str(root / "opencode"), NEYVIA_PROJECTS_DIR=str(root / "projects"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", PYTHONIOENCODING="utf-8")
    from .proof_credential_guard import install
    install(root)
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    original = subprocess.Popen
    class HiddenProcess(original):
        def __init__(self, *args, **kwargs):
            for key, value in hidden_windows_subprocess_kwargs().items():
                if key == "creationflags": kwargs[key] = kwargs.get(key, 0) | value
                else: kwargs.setdefault(key, value)
            super().__init__(*args, **kwargs)
    subprocess.Popen = HiddenProcess
    def guard(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            address = values[1] if event != "socket.getaddrinfo" else (values[0], values[1])
            if tuple(address[:2]) != ("127.0.0.1", port): raise PermissionError("Session proofs permit only the explicit owned loopback port")
    sys.addaudithook(guard)

def _subscriptions(root, category, identity):
    from .connected_sessions.broker import ConnectedBroker, MAX_SUBSCRIBERS
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
    try:
        def observe():
            with broker.subscription():
                with broker._lock: return bool(broker._subscribers)
        require(observe() and not broker._subscribers, "Subscription leaked after success")
        try:
            with broker.subscription(): raise ValueError("Owned lexical refusal")
        except ValueError: pass
        require(not broker._subscribers, "Subscription leaked after refusal")
        if category == "huge":
            with ExitStack() as stack:
                for _ in range(MAX_SUBSCRIBERS): stack.enter_context(broker.subscription())
                require(len(broker._subscribers) == MAX_SUBSCRIBERS, "Subscription cap lost unique tokens")
                from .connected_sessions.registry import ConnectedError
                refused(lambda: stack.enter_context(broker.subscription()), (ConnectedError,))
            require(not broker._subscribers, "Capacity refusal leaked active tokens")
        elif category == "concurrency":
            barrier = threading.Barrier(8); tokens = []
            def hold(_):
                with broker.subscription():
                    barrier.wait(timeout=5)
                    with broker._lock: tokens.append(len(broker._subscribers))
                    barrier.wait(timeout=5)
            with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(hold, range(8)))
            require(tokens == [8] * 8 and not broker._subscribers, "Concurrent subscriptions lost uniqueness or release")
        elif category == "stale":
            with broker.subscription(): old = set(broker._subscribers)
            with broker.subscription(): require(not old.intersection(broker._subscribers), "Retired subscription token was reused")
        return {"successAndRefusalReleased": True, "cap": MAX_SUBSCRIBERS, "providerExecution": False}
    finally: broker.close()

def _rollout(root, category, identity):
    from .connected_sessions.codex_items import read_tail_rows, rollout_activity
    from .edge_fixture_preferences_skills import denied_file
    path = root / "owned-rollout.jsonl"
    current = {"type": "event_msg", "timestamp": time.time(), "payload": {"type": "task_started", "turn_id": "owned-current"}}
    path.write_text(json.dumps(current) + "\n", encoding="utf-8")
    before = path.read_bytes()
    def action(): return read_tail_rows(path, 200000)
    require(action() == [current], "Bounded rollout did not preserve complete dictionary row")
    if category == "permissions":
        with denied_file(path): require(action() == [], "Denied rollout bytes became an active source")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: require(list(pool.map(lambda _: action(), range(8))) == [[current]] * 8, "Concurrent bounded tails changed one source")
    elif category == "interrupted":
        program = "import os,sys;f=open(sys.argv[1],'ab');f.write(b'{\"unfinished\":');f.flush();os.fsync(f.fileno());os._exit(23)"
        completed = subprocess.run([sys.executable, "-c", program, str(path)], capture_output=True, timeout=15, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 23 and action() == [current], "Interrupted writer's partial tail became an observed row")
    elif category == "stale":
        ended = {**current, "payload": {"type": "task_complete", "turn_id": "owned-current"}}
        path.write_text(json.dumps(ended) + "\n", encoding="utf-8")
        require(action() == [ended], "Tail reused a previous start marker after terminal replacement")
    return {"completeRows": len(action()), "beforeSha256": hashlib.sha256(before).hexdigest(), "providerExecution": False}

def _watchdog(root, category, identity):
    from .connected_sessions.broker import ConnectedBroker, _LiveRun
    from .edge_fixture_sessions import _run_data
    from .connected_sessions.registry import make_session_id
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False, idle_watchdog_seconds=1)
    children = []; calls = []
    class OwnedChild:
        def __init__(self):
            self.child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
            children.append(self.child)
        def interrupt(self, run_id):
            self.child.terminate(); self.child.wait(timeout=5); calls.append(run_id)
    try:
        sid = make_session_id("neyvia", broker.host["deviceId"], "owned")
        now = time.monotonic(); selected = []
        for index, state in enumerate(("queued", "running", "waiting_input", "waiting_approval", "completed")):
            data = _run_data(f"watchdog-{index}", sid + str(index), text(category))
            data["state"] = state
            adapter = OwnedChild() if state in {"queued", "running"} else None
            live = _LiveRun(data, adapter, "turn"); live.last_output = now - 2
            if state == "waiting_approval": data["pendingRequest"] = {"requestId": "owned", "kind": "approval"}
            if state == "waiting_input": data["pendingRequest"] = {"requestId": "owned", "kind": "question"}
            if state == "completed": live.terminal = True
            if category == "empty" and state == "queued": live.last_output = now
            if category == "stale" and state == "queued": live.stop_requested = True
            broker._live[data["runId"]] = live
            if state in {"queued", "running"} and not live.stop_requested and now - live.last_output >= 1: selected.append(data["runId"])
        if category == "concurrency":
            barrier = threading.Barrier(8)
            def inspect(_): barrier.wait(5); broker._watchdog(now)
            with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(inspect, range(8)))
        else: broker._watchdog(now)
        deadline = time.monotonic() + 5
        while len(calls) < len(selected) and time.monotonic() < deadline: time.sleep(.01)
        require(len(calls) == len(selected) and set(calls) == set(selected) and all(broker._live[run].data["state"] == "interrupted" for run in selected), "Watchdog repeated an interruption, interrupted an exempt state or missed selected idle owner")
        broker._watchdog(now + 5); require(len(calls) == len(selected) and set(calls) == set(selected), "Watchdog interrupted a retired owner again")
        return {"actualOwnedChildrenInterrupted": len(calls), "waitingStatesExempt": True, "providerExecution": False}
    finally:
        broker.close()
        for child in children:
            if child.poll() is None: child.terminate(); child.wait(timeout=5)

def _case(root, category, identity):
    if identity == "sessions.events.subscription": return _subscriptions(root, category, identity)
    if identity == "sessions.codex.rollout": return _rollout(root, category, identity)
    if identity == "sessions.run.watchdog": return _watchdog(root, category, identity)
    if identity.startswith("sessions.workspace."): return _workspace(root, category, identity)
    if identity.startswith("sessions.folders."): return _folders(root, category, identity)
    if identity == "sessions.broker.unread": return _seen(root, category, identity)
    if identity == "sessions.neyvia.page": return _native_page(root, category, identity)
    if identity == "sessions.opencode.inventory": return _opencode(root, category, identity)
    if identity.startswith("sessions.api."): return _http(root, category, identity)
    if identity in {"sessions.run.lifecycle", "sessions.run.request", "sessions.run.recovery", "sessions.broker.controls"}: return _broker(root, category, identity)
    raise ValueError("Session mechanism not yet implemented: " + identity)

def _root_comparison(root, category):
    from .connected_sessions.api import _check_state_root
    from .connected_sessions.registry import ConnectedError
    backend = SimpleNamespace(root=root)
    _check_state_root(backend, {}); _check_state_root(backend, {"_expectedStateRoot": str(root)})
    foreign = root / "foreign"; foreign.mkdir()
    def wrong(_=0):
        try: _check_state_root(backend, {"_expectedStateRoot": str(foreign)})
        except ConnectedError as error:
            require(error.code == "wrong_state_root" and error.status == 409, "Root mismatch lost exact refusal"); return error.code
        raise AssertionError("Root mismatch was accepted")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: require(list(pool.map(wrong, range(8))) == ["wrong_state_root"] * 8, "Concurrent root refusals changed")
    else: wrong()
    return {"samePhysicalRootAccepted": True, "foreignRoot409": True, "dispatches": 0}

def _await(broker, run_id, state, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        record = broker.get_run(run_id)
        if record["state"] == state: return record
        if record["state"] in {"failed", "interrupted", "cancelled"} and record["state"] != state:
            raise AssertionError("Actual local run settled unexpectedly: " + repr(record))
        time.sleep(.02)
    raise AssertionError("Actual local run never settled: " + repr(broker.get_run(run_id)))

def _broker_recovery(root, category):
    from .connected_sessions.broker import ConnectedBroker
    from .connected_sessions.runs import RunStore
    from .edge_fixture_sessions import _run_data
    from .edge_fixture_preferences_skills import denied_file
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
    data = _run_data("owned-dead-request", "owned-local-session", "owned before interruption")
    path = root / "request.json"; path.write_text(json.dumps(data), encoding="utf8")
    program = "import os,sys,json;from pathlib import Path;from grant_agent.proof_credential_guard import install;install(Path(sys.argv[1]).parents[1]);from grant_agent.connected_sessions.runs import RunStore;s=RunStore(Path(sys.argv[1]),'owned-dead-child',lambda _:True);d=json.loads(Path(sys.argv[2]).read_text(encoding='utf8'));s.claim(d,'owned-fingerprint',0,is_free=lambda _:False,register=lambda:None,unregister=lambda:None);os._exit(23)"
    try:
        child = subprocess.run([sys.executable, "-c", program, str(broker.db_path), str(path)], capture_output=True, timeout=20, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23 and broker.store.load(data["runId"]) == data, "Actual abruptly exited writer did not durably claim exact request")
        if category == "permissions":
            before = broker.db_path.read_bytes()
            with denied_file(broker.db_path): refused(broker.recover, (sqlite3.Error, OSError))
            require(broker.db_path.read_bytes() == before and broker.store.load(data["runId"]) == data, "Denied recovery changed prior durable owner")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: batches = list(pool.map(lambda _: broker.recover(), range(8)))
            require(sum(len(batch) for batch in batches) == 1, "Concurrent recovery published one dead owner more than once")
        else: require(len(broker.recover()) == 1, "Dead owner was not recovered once")
        saved = broker.store.load(data["runId"])
        require(saved["state"] == "interrupted" and saved["pendingRequest"] is None and "did not resend" in saved["error"] and not broker._live, "Recovery fabricated execution or lost uncertainty")
        require(broker.store.has_request(data["runId"], "owned-fingerprint") and not broker.recover(), "Recovered fingerprint replay was lost")
        if category == "stale":
            from .chat_run_control import process_started_at
            live_child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], **hidden_windows_subprocess_kwargs())
            try:
                actual_start = process_started_at(live_child.pid); require(actual_start and actual_start > 0, "Actual selected child process clock unavailable")
                stale_data = {**data, "runId": "owned-recycled-identity", "sessionId": "owned-recycled-session"}
                with broker.store.connect() as db:
                    db.execute("INSERT INTO connected_session_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (stale_data["runId"], stale_data["sessionId"], "neyvia", "stale-fingerprint", "queued", live_child.pid, "different-owner", actual_start + 10000, time.time(), time.time(), json.dumps(stale_data)))
                recovered = broker.recover()
                require(len(recovered) == 1 and recovered[0]["state"] == "interrupted" and live_child.poll() is None, "Different recorded process clock retained stale ownership or signaled replacement process")
            finally:
                if live_child.poll() is None: live_child.terminate(); live_child.wait(timeout=5)
        return {"actualWriterExit": 23, "durableState": "interrupted", "replayed": False, "recoveryEffects": 1, "permissionsRecoveryPreservedPrior": category == "permissions"}
    finally: broker.close()

def _broker(root, category, identity):
    if identity == "sessions.run.recovery" or identity == "sessions.run.request" and category == "interrupted": return _broker_recovery(root, category)
    from .connected_sessions.broker import ConnectedBroker
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.registry import ConnectedError
    peer = root / "owned-stdio-peer.py"; peer.write_text(CLAUDE_LOCAL_PEER, encoding="utf8")
    config = root / "owned-config"; config.mkdir()
    mode = "interrupt" if category == "interrupted" else "reply"
    adapter = ClaudeAdapter(state_root=root, config_dir=config, cli_path=[sys.executable, str(peer)], context_probe=False, interrupt_grace=.1, idle_timeout=8, pending_timeout=8,
                            extra_env={"C7D_PEER_MODE": mode, "C7D_PEER_ROOT": str(root), "NEYVIA_UI_BACKEND_URL": "http://127.0.0.1:" + os.environ["NEYVIA_C7_PORT"]})
    broker = ConnectedBroker(root, adapters={"claude-code": adapter}, load_defaults=False, autostart=False, list_ttl=0)
    def refusal(callback, codes):
        try: callback()
        except ConnectedError as error:
            require(error.code in codes, "Actual broker refusal changed code: " + error.code); return error.code
        raise AssertionError("Actual broker accepted refused operation")
    try:
        if category == "offline":
            peer.rename(root / "retired-peer.py")
            code = refusal(lambda: broker.new("claude-code", str(root), "owned endpoint unavailable", "owned-offline-request"), {"adapter_unavailable"})
            require(not broker.store.active() and not broker._live and not list(root.glob("wire-*.json")), "Missing local stdio peer started a turn")
            return {"actualFinitePeerAbsent": True, "refusal": code, "startedChildren": 0, "installedProviderExecuted": False}
        run = broker.new("claude-code", str(root), "owned request 雪", "owned-control-request")
        waiting = _await(broker, run["runId"], "waiting_approval")
        require(waiting["sessionId"] and waiting["pendingRequest"]["requestId"] == "owned-approval", "Actual stdio approval lost requested identity")
        if category == "interrupted":
            broker.stop(run["runId"])
            final = _await(broker, run["runId"], "interrupted")
            refusal(lambda: broker.answer(run["runId"], "owned-approval", {"decision": "approve"}), {"request_not_pending"})
            require(broker.stop(run["runId"]) == final, "Stopping retired actual turn changed identity or controls")
            return {"actualOwnedPeerStopped": True, "terminal": final["state"], "retiredApprovalRefused": True, "installedProviderExecuted": False}
        if category in {"empty", "permissions"}:
            refusal(lambda: broker.answer(run["runId"], "owned-approval", {"decision": "unknown"}), {"invalid_response"})
        if category == "stale": refusal(lambda: broker.answer(run["runId"], "retired-approval", {"decision": "approve"}), {"request_not_pending"})
        response = {"decision": "deny" if category == "permissions" else "approve", "answers": {"owned-" + str(i): text(category)[:30000] for i in range(60 if category == "huge" else 1)}}
        if category == "concurrency":
            barrier = threading.Barrier(4)
            def answer(_):
                barrier.wait(5)
                try: broker.answer(run["runId"], "owned-approval", response); return "answered"
                except ConnectedError as error:
                    require(error.code in {"request_already_answered", "request_not_pending"}, "Competing broker answer lost exact refusal"); return "refused"
            with ThreadPoolExecutor(max_workers=4) as pool: winners = list(pool.map(answer, range(4)))
            require(winners.count("answered") == 1, "Actual broker approval was consumed more than once")
        else: broker.answer(run["runId"], "owned-approval", response)
        refusal(lambda: broker.answer(run["runId"], "owned-approval", response), {"request_not_pending", "request_already_answered"})
        question = _await(broker, run["runId"], "waiting_input")
        require(question["pendingRequest"]["requestId"] == "owned-question", "Actual follow-up question lost pending identity")
        broker.answer(run["runId"], "owned-question", {"decision": "approve", "answers": {"q0": text(category)[:30000] or "owned answer"}})
        final = _await(broker, run["runId"], "completed")
        require(final["sessionId"] == waiting["sessionId"] and final["pendingRequest"] is None and not final["canStop"] and not final["canSteer"], "Actual completed control run retained pending request/active controls")
        deadline = time.monotonic() + 3
        while broker.store.load(run["runId"])["state"] != "completed" and time.monotonic() < deadline: time.sleep(.02)
        require(broker.store.load(run["runId"])["state"] == "completed", "Actual terminal control run was not durable after worker settled")
        require(broker.stop(run["runId"]) == final, "Retired actual turn was stopped again")
        wire = json.loads(next(root.glob("wire-*.json")).read_text(encoding="utf8"))
        replies = [row for row in wire if row.get("type") == "control_response"]
        require(len(replies) == 2, "Actual stdio peer received duplicate approvals")
        return {"actualFiniteStdioReplies": 2, "durableTerminal": "completed", "duplicateApprovalRefused": True, "installedProviderExecuted": False, "suppliedProtocolPeer": True}
    finally: broker.close()

@contextmanager
def _http_host(root):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse
    import_started = time.monotonic()
    from .web_backend import _json_response
    host_import_ms = round((time.monotonic() - import_started) * 1000, 3)
    from .connected_sessions import api, broker as module
    from .connected_sessions.claude import ClaudeAdapter
    config = root / "owned-config"; config.mkdir()
    peer = root / "owned-inventory-peer.py"; peer.write_text("print('[]')\n", encoding="utf8")
    adapter = ClaudeAdapter(state_root=root, config_dir=config, cli_path=[sys.executable, str(peer)], context_probe=False)
    key = os.path.normcase(str(root.resolve()))
    class Backend:
        username = "owned-subject"
        def __init__(self): self.root = root; self.dispatches = 0; self.logouts = 0; self.break_dispatch = False; self.auth_refused = False; self.failure_text = "Owned finite dispatch failure"; self.coded_error = None; self.delay_dispatch = False; self.entered = threading.Event(); self.release = threading.Event(); self.responded = threading.Event(); self.unexpected = []
        def authenticated_session(self, handler):
            value = handler.headers.get("X-Owned-Subject")
            if "owned-session=1" in (handler.headers.get("Cookie") or ""): value = self.username
            return {"username": value} if value else None
        def is_authenticated(self, handler): return bool(self.authenticated_session(handler))
        def dispatch(self, command, body):
            self.dispatches += 1
            if self.delay_dispatch: self.entered.set(); require(self.release.wait(5), "Owned socket scheduling hold timed out")
            if self.break_dispatch: raise RuntimeError(self.failure_text)
            if self.coded_error is not None: raise self.coded_error
            return api.handle_connected_command(self, command, body)
    backend = Backend()
    backend.host_import_ms = host_import_ms
    backend.response_times_ms = []
    broker = module.ConnectedBroker(root, backend=backend, adapters={"claude-code": adapter}, load_defaults=False, autostart=False, ring_events=8, ring_bytes=16384, start_cursor=0)
    with module._BROKERS_LOCK: require(key not in module._BROKERS, "Owned host root already registered"); module._BROKERS[key] = broker
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *_): pass
        def do_GET(self):
            if backend.delay_dispatch: backend.entered.set(); require(backend.release.wait(5), "Owned GET scheduling hold timed out")
            try: api.serve_connected_get(backend, self, urlparse(self.path))
            except Exception as error: backend.unexpected.append(type(error).__name__)
            finally: backend.responded.set()
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/api/auth/local-session":
                self.send_response(403 if backend.auth_refused else 200)
                self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", "11")
                if not backend.auth_refused: self.send_header("Set-Cookie", "owned-session=1; Path=/; HttpOnly")
                self.end_headers(); self.wfile.write(b'{"ok":true}'); return
            if self.path == "/api/auth/logout": backend.logouts += 1; _json_response(self, 200, {"ok": True}); return
            try: api.respond_connected_command(self, backend, body.get("command", ""), body.get("payload", {}))
            except Exception as error: backend.unexpected.append(type(error).__name__)
            finally: backend.responded.set()
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ["NEYVIA_C7_PORT"])), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield broker, backend, adapter
    finally:
        broker.close(); server.shutdown(); server.server_close(); thread.join(5)
        with module._BROKERS_LOCK: module._BROKERS.pop(key, None)

def _http(root, category, identity):
    if identity == "sessions.api.state_root": return _root_comparison(root, category)
    import http.client
    from urllib.parse import urlencode
    from .connected_sessions import forward
    from .connected_sessions.registry import make_session_id
    port = int(os.environ["NEYVIA_C7_PORT"])
    if identity == "sessions.api.forward" and category == "offline":
        with _http_host(root): pass
        value = forward.forward_connected_command(root, "connected_events_poll_command", {})
        require(value["code"] == "pc_service_offline", "Closed actual owned host became a live forward")
        return {"actualOwnedHostClosed": True, "code": value["code"], "explicitPort": port}
    def request(method, path, body=None, subject="owned-subject", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        request_started = time.monotonic()
        values = {"Content-Type": "application/json", **(headers or {})}
        if subject is not None: values["X-Owned-Subject"] = subject
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, values)
        try:
            response = conn.getresponse(); raw = response.read(); result = (response.status, dict(response.getheaders()), raw)
            backend.response_times_ms.append(round((time.monotonic() - request_started) * 1000, 3))
            return result
        except TimeoutError as error:
            raise AssertionError("Actual response exceeded unchanged 5s deadline: " + repr({"hostImportMs": backend.host_import_ms, "handlerCompleted": backend.responded.is_set(), "handlerErrors": backend.unexpected})) from error
        finally: conn.close()
    def command(name="connected_events_poll_command", payload=None, subject="owned-subject"):
        return request("POST", "/api/backend", {"command": name, "payload": payload or {}}, subject)
    with _http_host(root) as (broker, backend, adapter):
        if category == "interrupted" and identity in {"sessions.api.response", "sessions.api.poll", "sessions.api.authority"}:
            backend.delay_dispatch = True
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("POST", "/api/backend", json.dumps({"command": "connected_events_poll_command", "payload": {"waitSeconds": 0}}).encode(), {"Content-Type": "application/json", "X-Owned-Subject": "owned-subject"})
            require(backend.entered.wait(5), "Actual interrupted client never dispatched")
            connection.close(); backend.release.set()
            require(backend.responded.wait(5) and not backend.unexpected and not broker._subscribers, "Closed actual client caused unhandled response or leaked subscription")
            return {"actualClientClosedBeforeResponse": True, "unhandledResponseErrors": 0, "subscriptionsReleased": True}
        if identity == "sessions.api.authority":
            status, _, raw = request("GET", "/api/connected/events", subject=None)
            require(status == 401 and json.loads(raw)["loginRequired"] and not broker._subscribers, "Anonymous stream crossed authentication or acquired capacity")
            for subject in (None, "owned-guest"):
                status, _, raw = command("connected_session_send_command", {"id": "invalid", "message": "owned"}, subject)
                require(status == 403 and json.loads(raw)["code"] == "owner_required" and backend.dispatches == 0, "Foreign subject dispatched owner command")
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:
                    replies = list(pool.map(lambda _: command("connected_session_send_command", {"id": "invalid", "message": "owned"}, "owned-guest"), range(8)))
                require(all(row[0] == 403 for row in replies) and backend.dispatches == 0, "Concurrent foreign subjects acquired owner dispatch")
            status, _, raw = command("connected_session_send_command", {"id": "invalid", "message": "owned"})
            require(status != 403 and backend.dispatches == 1 and not broker.store.active(), "Owner subject was denied before exact semantic refusal")
            return {"anonymous401": True, "foreignSubject403BeforeDispatch": True, "authenticationIssuer": "Explicit finite supplied subject boundary"}
        if identity == "sessions.api.media":
            sid = make_session_id("claude-code", broker.host["deviceId"], "owned-session")
            selected = root / "selected-bytes.bin"; selected.write_bytes((text(category) or "owned").encode("utf8")[:8192]); raw = selected.read_bytes()
            name = "owned-雪.bin"; mime = "application/x-owned-unknown" if category in {"permissions", "unicode"} else "image/png"
            token = hashlib.sha256(raw).hexdigest(); adapter._live_media[token] = (raw, mime)
            if mime != "image/png":
                from .connected_sessions.neyvia import NeyviaAdapter
                from .neyvia_conversations import NeyviaConversationStore
                backend.neyvia_mcp = SimpleNamespace(conversations=NeyviaConversationStore(root))
                class OwnedFileMedia(NeyviaAdapter):
                    def read_media(self, session, reference):
                        if reference != token: raise FileNotFoundError("Unknown owned media reference")
                        return selected.read_bytes(), mime, name
                broker.register_adapter("neyvia", lambda given: OwnedFileMedia(given))
                sid = make_session_id("neyvia", broker.host["deviceId"], "owned-media-hook")
            path = "/api/connected/media?" + urlencode({"session": sid, "media": token})
            def observe(_=0):
                status, headers, body = request("GET", path)
                require(status == 200 and body == raw and headers.get("X-Content-Type-Options") == "nosniff" and headers.get("Content-Security-Policy") == "default-src 'none'; sandbox", "Actual attachment HTTP changed selected bytes/security headers: " + repr((status, headers, body[:500])))
                require(headers["Content-Type"] == (mime if mime == "image/png" else "application/octet-stream"), "Unknown active MIME lost safe fallback")
                require(headers["Cache-Control"] == "private, no-store" and int(headers["Content-Length"]) == len(raw), "Media response lost private no-store or byte count")
                if mime != "image/png":
                    from urllib.parse import quote
                    require(headers["Content-Disposition"] == "attachment; filename*=UTF-8''" + quote(name, safe=""), "Nonimage media lost exact quoted filename")
                return status
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(observe, range(4)))
            else: observe()
            if category == "interrupted":
                backend.delay_dispatch = True; backend.responded.clear()
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path, headers={"X-Owned-Subject": "owned-subject"})
                require(backend.entered.wait(5), "Actual media client never reached selected GET")
                connection.close(); backend.release.set()
                require(backend.responded.wait(5) and not backend.unexpected, "Closed media client leaked unhandled selected response")
            elif category == "stale":
                adapter._live_media.clear(); status, _, missing = request("GET", path)
                require(status == 404 and json.loads(missing)["code"] in {"media_not_found", "session_unavailable"} and missing != raw, "Retired selected media leaked cached bytes")
            elif category == "permissions":
                from .edge_fixture_preferences_skills import denied_file
                with denied_file(selected):
                    status, _, missing = request("GET", path)
                    require(status == 404 and json.loads(missing)["code"] == "media_not_found", "Actual denied selected file returned private bytes")
            return {"actualSelectedBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "safeMime": True, "rendered": False, "providerExecution": False}
        if identity == "sessions.api.forward":
            require(forward.service_port() == port, "Forward resolved outside explicit assigned port")
            payload = {"payload": {"waitSeconds": 0, "cursor": broker.head()}}
            result = forward.forward_connected_command(root, "connected_events_poll_command", payload)
            require(result["events"] == [] and backend.logouts == 1, "Actual forward lost unwrapped data or cookie logout")
            foreign = root / "foreign"; foreign.mkdir(); result = forward.forward_connected_command(foreign, "connected_events_poll_command", {})
            require(result["code"] == "wrong_state_root" and backend.logouts == 2, "Wrong-root forward lost coded HTTP409 or logout")
            if category == "permissions":
                backend.auth_refused = True; result = forward.forward_connected_command(root, "connected_events_poll_command", {})
                require(result["code"] == "pc_service_auth", "Finite authentication refusal became success")
            elif category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: forward.forward_connected_command(root, "connected_events_poll_command", payload), range(4)))
                require(all(value["events"] == [] for value in results) and backend.logouts == 6, "Concurrent forwards lost independent cookie cleanup")
            elif category in {"empty", "huge", "unicode"}:
                result = forward.forward_connected_command(root, "connected_events_poll_command", {"waitSeconds": text(category), "cursor": 0})
                require("code" in result if text(category) else "events" in result, "Forward error/data boundary changed")
            elif category == "interrupted":
                backend.break_dispatch = True; result = forward.forward_connected_command(root, "connected_events_poll_command", {})
                require(result["code"] == "internal_error" and backend.logouts == 3, "Interrupted dispatch lost coded refusal or final logout")
            return {"actualLoopbackCookieForward": True, "logouts": backend.logouts, "explicitPort": port, "localAuthenticationIssuer": "Finite supplied protocol peer", "remoteSignIn": False}
        if identity == "sessions.api.response":
            status, _, raw = command(); require(status == 200 and json.loads(raw)["ok"] and json.loads(raw)["data"]["events"] == [], "Actual response lost data wrapper")
            status, _, raw = command("owned-unknown-command"); require(status == 404 and json.loads(raw)["code"] == "unknown_command", "Actual coded refusal lost status")
            from .connected_sessions.registry import ConnectedError
            backend.coded_error = ConnectedError("owned_busy", "Supplied local refusal", 409, owner="owned-peer", ownerDetail={"kind": "finite-protocol"})
            status, _, raw = command(); coded = json.loads(raw)
            require(status == 409 and coded["code"] == "owned_busy" and coded["owner"] == "owned-peer" and coded["ownerDetail"] == {"kind": "finite-protocol"}, "Actual coded response lost supplied owner details")
            backend.coded_error = None
            backend.break_dispatch = True; backend.failure_text = text(category); status, _, raw = command(); result = json.loads(raw)
            require(status == 500 and result["code"] == "internal_error" and len(result["message"]) <= 300 and "Traceback" not in raw.decode(), "Unexpected failure leaked traceback or became success")
            return {"actualHttpStatuses": [200, 404, 409, 500], "suppliedRefusalOwnerDetailsRetained": True, "boundedMachineCodes": True, "actualHostImportMsBeforeListen": backend.host_import_ms, "actualResponseTimesMs": backend.response_times_ms, "responseDeadlineSeconds": 5}
        if identity == "sessions.api.poll":
            cursor = broker.head(); event = broker._publish({"type": "owned.event", "text": text(category)[:8192]})
            payload = {"cursor": cursor, "waitSeconds": 0}
            if category == "unicode":
                status, _, raw = command(payload={**payload, "waitSeconds": text(category)})
                require(status == 400 and json.loads(raw)["code"] == "invalid_request", "Invalid numeric wait was accepted")
            else:
                if category == "huge": payload["waitSeconds"] = 1e100
                elif category == "empty": payload["waitSeconds"] = -1
                if category == "stale":
                    for index in range(20): broker._publish({"type": "owned.overflow", "index": index})
                def observe(_=0):
                    status, _, raw = command(payload=payload); value = json.loads(raw)
                    require(status == 200 and value["ok"], "Actual event poll refused current subscription")
                    if category == "stale": require(value["data"].get("resync"), "Old ring cursor hid a gap")
                    else: require(value["data"]["events"][0]["cursor"] == event["cursor"], "Exclusive poll cursor lost actual event")
                    return value
                if category == "concurrency":
                    with ThreadPoolExecutor(max_workers=4) as pool: rows = list(pool.map(observe, range(4)))
                    require(rows == [rows[0]] * 4, "Concurrent same-cursor polls diverged")
                else: observe()
            require(not broker._subscribers, "Poll leaked subscription after response")
            return {"actualEventCursor": event["cursor"], "subscriptionsReleased": True, "ringCapacity": 8}
        if identity == "sessions.api.sse":
            broker._publish({"type": "owned.prior"}); cursor = broker.head()
            if category == "stale":
                for index in range(20): broker._publish({"type": "owned.overflow", "index": index})
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/connected/events?cursor=0", headers={"X-Owned-Subject": "owned-subject", "Last-Event-ID": str(cursor)})
            response = conn.getresponse(); require(response.status == 200 and response.getheader("Content-Type").startswith("text/event-stream"), "Actual SSE handshake failed")
            initial = [response.readline().decode() for _ in range(3)]; require(initial == [": connected\n", "retry: 3000\n", "\n"], "SSE initial framing differs")
            if category == "stale":
                response.readline(); resync = response.readline().decode(); response.readline()
                require(json.loads(resync[6:]) == {"type": "resync", "cursor": broker.head()}, "Stale actual SSE socket hid ring gap")
            extra_streams = []
            if category == "concurrency":
                for _ in range(3):
                    extra_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    extra_conn.request("GET", "/api/connected/events", headers={"X-Owned-Subject": "owned-subject", "Last-Event-ID": str(cursor)})
                    extra_response = extra_conn.getresponse()
                    require(extra_response.status == 200 and [extra_response.readline().decode() for _ in range(3)] == initial, "Concurrent SSE handshake changed initial framing")
                    extra_streams.append((extra_conn, extra_response))
                require(len(broker._subscribers) == 4, "Actual concurrent socket streams lost subscriber uniqueness")
            event = broker._publish({"type": "owned.event", "text": text(category)[:8192]})
            id_line = response.readline().decode(); data_line = response.readline().decode(); end = response.readline().decode()
            require(id_line == f"id: {event['cursor']}\n" and data_line.startswith("data: ") and json.loads(data_line[6:]) == event and end == "\n", "Actual SSE cursor/JSON frame differs from actual event")
            for extra_conn, extra_response in extra_streams:
                require(extra_response.readline().decode() == id_line and extra_response.readline().decode() == data_line and extra_response.readline().decode() == end, "Concurrent actual SSE socket lost one shared event")
                extra_response.close(); extra_conn.close()
            response.close(); conn.close()
            deadline = time.monotonic() + 3
            while broker._subscribers and time.monotonic() < deadline: time.sleep(.02)
            require(not broker._subscribers, "Actual disconnected SSE client leaked capacity")
            return {"actualSocketFrameCursor": event["cursor"], "utf8Exact": True, "disconnectedSubscriptionReleased": True}
    if category == "offline":
        value = forward.forward_connected_command(root, "connected_events_poll_command", {})
        require(value["code"] == "pc_service_offline", "Closed owned host became a live forward")

def _git(root, *args):
    git = shutil.which("git"); require(bool(git), "Actual Git executable required")
    result = subprocess.run([git, "-c", "user.name=C7d", "-c", "user.email=c7d@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_windows_subprocess_kwargs())
    require(result.returncode == 0, "Owned Git failed: " + result.stderr[:500]); return result.stdout

def _repository(root):
    area = root / "repo"; area.mkdir(); _git(area, "init", "-q", "-b", "main")
    for key, value in (("user.name", "C7d"), ("user.email", "c7d@example.invalid"), ("commit.gpgsign", "false")):
        _git(area, "config", key, value)
    (area / "owned.txt").write_text("baseline\n", encoding="utf-8"); _git(area, "add", "--", "owned.txt"); _git(area, "commit", "-q", "-m", "owned baseline")
    return area

def _finite_cli(root, name, program):
    """Actual compiled argv relay to a finite Python public-protocol peer."""
    source = root / (name + "-peer.py"); source.write_text(program, encoding="utf-8")
    def cs(value): return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
    code = r'''using System;using System.Diagnostics;using System.Threading;
class OwnedPeer {static string Q(string s){return "\""+s.Replace("\\","\\\\").Replace("\"","\\\"")+"\"";}
static int Main(string[] args){Console.OutputEncoding=new System.Text.UTF8Encoding(false);var p=new Process();p.StartInfo.FileName=PYTHON;p.StartInfo.Arguments=Q(SOURCE);foreach(var a in args)p.StartInfo.Arguments+=" "+Q(a);p.StartInfo.UseShellExecute=false;p.StartInfo.CreateNoWindow=true;p.StartInfo.RedirectStandardOutput=true;p.StartInfo.RedirectStandardError=true;p.StartInfo.StandardOutputEncoding=System.Text.Encoding.UTF8;p.StartInfo.StandardErrorEncoding=System.Text.Encoding.UTF8;p.Start();var t=new Thread(()=>{Console.Error.Write(p.StandardError.ReadToEnd());});t.Start();Console.Write(p.StandardOutput.ReadToEnd());p.WaitForExit();t.Join();return p.ExitCode;}}'''.replace("PYTHON", cs(sys.executable)).replace("SOURCE", cs(source))
    cs_source = root / (name + ".cs"); cs_source.write_text(code, encoding="utf-8")
    executable = root / (name + ".exe")
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    require(compiler.is_file(), "Installed local C# compiler required for finite CLI transport")
    result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(executable), str(cs_source)], capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    require(result.returncode == 0 and executable.is_file(), "Finite CLI relay build failed: " + result.stdout[:800])
    return executable

def _github(root, category):
    from .connected_sessions import workspace as owner
    repo = _repository(root); _git(repo, "remote", "add", "origin", "https://github.com/owned/local-projection.git")
    policy = root / "finite-policy.json"; log = root / "finite-argv.jsonl"
    script = ("import os,sys,json\nfrom pathlib import Path\n" + f"p=Path({str(policy)!r});log=Path({str(log)!r})\n" + "args=sys.argv[1:]\nwith log.open('a',encoding='utf-8') as f:f.write(json.dumps(args,ensure_ascii=False)+'\\n')\nstate=json.loads(p.read_text(encoding='utf-8'))\nif args[:2]==['auth','status']:sys.exit(0 if state['authenticated'] else 1)\nif args[:2]==['pr','view']:\n if state.get('interrupted'):sys.stderr.write('Owned peer interrupted before JSON publication');sys.stderr.flush();os._exit(23)\n if state['view'] is None:sys.stderr.write('no pull requests found');sys.exit(1)\n print(json.dumps(state['view'],ensure_ascii=False));sys.exit(0)\nif args[:2]==['pr','create']:print(state['created']);sys.exit(0)\nsys.exit(2)\n")
    gh = _finite_cli(root, "gh", script)
    git = shutil.which("git"); previous = os.environ.get("PATH", "")
    os.environ["PATH"] = str(root) + os.pathsep + str(Path(git).parent)
    view = {"number": 7, "title": text(category)[:4096], "url": "https://github.com/owned/local-projection/pull/7", "state": "OPEN", "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}
    def configure(auth=True, value=view, interrupted=False):
        policy.write_text(json.dumps({"authenticated": auth, "view": value, "created": view["url"], "interrupted": interrupted}, ensure_ascii=False), encoding="utf-8"); log.write_text("", encoding="utf-8"); owner.invalidate(); owner._GH_CACHE.clear()
    try:
        configure(); result = owner.workspace_state(str(repo))
        require(result["pullRequest"]["number"] == 7 and result["pullRequest"]["title"] == view["title"] and result["pullRequest"]["checks"] == "passing", "Finite public CLI JSON lost PR projection")
        configure(False); result = owner.workspace_state(str(repo))
        calls = [json.loads(row) for row in log.read_text(encoding="utf-8").splitlines()]
        require(not result["gh"]["authenticated"] and not result["pullRequest"] and all(row[:2] != ["pr", "view"] for row in calls), "Signed-out finite peer was asked for PR data")
        configure(value=None); result = owner.workspace_state(str(repo)); require(not result["pullRequest"] and "pullRequestError" not in result, "Absent finite PR was reported as failure")
        configure(); title = "owned literal 雪; `scalar`"; body = text(category)[:8192]
        created = owner.git_action(str(repo), "create_pr", confirm=True, title=title, body=body)
        calls = [json.loads(row) for row in log.read_text(encoding="utf-8").splitlines()]
        argv = next(row for row in calls if row[:2] == ["pr", "create"])
        require(created["ok"] and argv[argv.index("--title") + 1] == title and argv[argv.index("--body") + 1] == body, "Finite local PR call split literal text or misreported output")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: rows = list(pool.map(lambda _: owner.workspace_state(str(repo)), range(4)))
            require(all(row["repo"]["root"] == str(repo) for row in rows), "Concurrent public CLI projections changed repository identity")
        elif category == "permissions":
            configure(False); refused(lambda: owner.git_action(str(repo), "create_pr", confirm=True, title=title, body=body), (owner.WorkspaceError,))
        elif category == "offline":
            gh.rename(root / "unavailable-peer.exe"); owner.invalidate(); owner._GH_CACHE.clear()
            require(not owner.workspace_state(str(repo))["gh"]["installed"], "Absent configured peer retained CLI availability")
        elif category == "stale":
            configure(value={**view, "number": 8}); require(owner.workspace_state(str(repo))["pullRequest"]["number"] == 8, "Current finite peer retained stale PR identity")
        elif category == "interrupted":
            configure(interrupted=True); current = owner.workspace_state(str(repo))
            require(current["pullRequest"] is None and current["pullRequestError"] == "Owned peer interrupted before JSON publication", "Actually exited CLI peer fabricated a complete PR result")
        return {"finitePublicCliOnly": True, "actualRemoteAccountAccess": False, "actualRemotePrCreated": False, "literalArgv": True}
    finally: os.environ["PATH"] = previous

def _workspace(root, category, identity):
    from .connected_sessions import workspace as owner
    from .edge_fixture_preferences_skills import denied_file
    if identity == "sessions.workspace.github": return _github(root, category)
    repo = _repository(root); path = repo / "owned.txt"; path.write_text(text(category) + "\nchanged\n", encoding="utf-8")
    git = shutil.which("git"); os.environ["PATH"] = str(Path(git).parent)
    owner.invalidate(); before = owner.workspace_state(str(repo))
    require(before["branch"] == "main" and before["changes"][0]["path"] == "owned.txt" and not before["gh"]["installed"], "Actual selected Git state differs or ambient account CLI was used")
    if identity == "sessions.workspace.action":
        if category == "concurrency":
            barrier = threading.Barrier(4)
            def commit(_): barrier.wait(timeout=5); return owner.git_action(str(repo), "commit", message="Owned competing commit", confirm=True)
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(commit, range(4)))
            require(sum(row["ok"] for row in results) == 1 and _git(repo, "rev-list", "--count", "HEAD").strip() == "2", "Competing Git commits fabricated winners or repeated one effect")
        elif category == "interrupted":
            program = "import os,sys;from grant_agent.proof_credential_guard import install;install(sys.argv[1]);from grant_agent.connected_sessions.workspace import git_action;r=git_action(sys.argv[1],'commit',message='Owned before caller exit',confirm=True);assert r['ok'];os._exit(23)"
            completed = subprocess.run([sys.executable, "-c", program, str(repo)], capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
            require(completed.returncode == 23 and _git(repo, "rev-list", "--count", "HEAD").strip() == "2" and not _git(repo, "status", "--porcelain").strip(), "Caller exit lost committed Git bytes or implicitly replayed effect")
        else:
            raw = owner._run([sys.executable, "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:" + os.environ["NEYVIA_C7_PORT"] + "/owned-offline',timeout=1)"], repo, 5)
            result = owner._action_result(raw); require(not result["ok"] and raw["code"] != 0, "Closed owned endpoint CLI error became action success")
    elif identity == "sessions.workspace.cli":
        if category == "interrupted":
            raw = owner._run([sys.executable, "-c", "import time;print('owned before timeout',flush=True);time.sleep(30)"], repo, .1)
            require(raw.get("timedOut") and raw["code"] is None, "Actual finite child timeout was hidden")
        else:
            command = [sys.executable, "-c", "import json,os;print(json.dumps({k:os.environ.get(k) for k in ['GIT_TERMINAL_PROMPT','GH_PROMPT_DISABLED','GCM_INTERACTIVE']}))"]
            raw = owner._run(command, repo, 5); require(raw["code"] == 0, "Actual finite child failed")
            values = json.loads(raw["out"]); require(values["GIT_TERMINAL_PROMPT"] == "0" and values["GH_PROMPT_DISABLED"] == "1", "CLI prompt-disabled environment was lost")
    elif category == "permissions":
        with _acl_read_denied(repo / ".git/HEAD", root):
            refused((repo / ".git/HEAD").read_bytes, (OSError,))
            raw = owner._git(str(repo), "status", "--porcelain=v2", "--branch", "-z")
            expected = owner._parse_status(raw["out"])["branch"].get("head") if raw["code"] == 0 else None
            owner.invalidate(); result = owner.workspace_state(str(repo)); require(result.get("branch") == expected, "Workspace observer differs from actual permission-scoped Git result")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(lambda _: owner.file_diff(str(repo), "owned.txt") if identity.endswith("diff") else owner.workspace_state(str(repo)), range(8)))
        require(results == [results[0]] * 8, "Concurrent local observers diverged on immutable selected Git bytes")
    if identity.endswith("cache"):
        detached = owner.workspace_state(str(repo)); detached["changes"].clear(); require(owner.workspace_state(str(repo))["changes"], "Caller mutated shared cached observation")
        path.write_text("new selected generation\n", encoding="utf-8"); owner.invalidate(str(repo)); require("new selected generation" in owner.file_diff(str(repo), "owned.txt")["patch"], "Invalidation retained prior Git bytes")
    return {"actualGitHead": _git(repo, "rev-parse", "HEAD").strip(), "ambientAccountCliAbsent": True, "providerExecution": False}

@contextmanager
def _acl_read_denied(path, root):
    path = path.resolve(); root = root.resolve()
    path.relative_to(root); root.relative_to(REPO / ".agent_control/proofs")
    original = path.read_bytes()
    ready = root / "acl-ready"; release = root / "acl-release"; script = root / "owned-acl.ps1"
    script.write_text(r'''param([string]$TargetPath,[string]$ReadyPath,[string]$ReleasePath)
$ErrorActionPreference='Stop'
$taskAcl=[System.IO.File]::GetAccessControl($TargetPath)
$taskOriginal=$taskAcl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)
$taskSid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$taskRule=New-Object System.Security.AccessControl.FileSystemAccessRule($taskSid,[System.Security.AccessControl.FileSystemRights]::ReadData,[System.Security.AccessControl.AccessControlType]::Deny)
try {
 $taskAcl.AddAccessRule($taskRule)
 [System.IO.File]::SetAccessControl($TargetPath,$taskAcl)
 [System.IO.File]::WriteAllText($ReadyPath,'ready')
 $taskDeadline=[DateTime]::UtcNow.AddSeconds(30)
 while(![System.IO.File]::Exists($ReleasePath) -and [DateTime]::UtcNow -lt $taskDeadline){Start-Sleep -Milliseconds 25}
} finally {
 $taskRestored=New-Object System.Security.AccessControl.FileSecurity
 $taskRestored.SetSecurityDescriptorSddlForm($taskOriginal,[System.Security.AccessControl.AccessControlSections]::Access)
 [System.IO.File]::SetAccessControl($TargetPath,$taskRestored)
 if([System.IO.File]::GetAccessControl($TargetPath).GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access) -ne $taskOriginal){throw 'Exact generated file DACL restoration failed'}
}
Write-Output 'restored'
''', encoding="utf-8")
    powershell = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    child = subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(path), str(ready), str(release)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline: time.sleep(.02)
        require(ready.exists(), "Owned generated-file DACL setup failed")
        yield
    finally:
        release.write_text("release", encoding="utf-8")
        output, error = child.communicate(timeout=35)
        require(child.returncode == 0 and b"restored" in output, "Exact DACL recovery failed: " + error.decode("utf-8", "replace")[-700:])
        require(path.read_bytes() == original, "Restored generated Git HEAD changed bytes")

def _folders(root, category, identity):
    from .connected_sessions import folders as owner
    from .edge_fixture_preferences_skills import denied_file
    projects = root / "projects"; projects.mkdir(exist_ok=True); os.environ["NEYVIA_PROJECTS_DIR"] = str(projects); owner._CACHE.clear()
    if identity == "sessions.folders.confirm":
        for confirmation in (False, None, 0):
            error = refused(lambda: owner.clone("owned/generated", confirm=confirmation), (ValueError,))
            require("confirmation" in error["message"], "Unconfirmed valid clone reached a different refusal")
            error = refused(lambda: owner.create_worktree(str(root), "owned-branch", confirm=confirmation), (ValueError,))
            require("confirmation" in error["message"], "Unconfirmed worktree reached a different refusal")
        require(not list(projects.iterdir()), "Unconfirmed folder mutation created a target")
        return {"confirmationRefusals": 6, "targetDirectoriesCreated": 0}
    selected = projects / "owned-project"; selected.mkdir(); (selected / ".git").mkdir()
    (selected / ".git/HEAD").write_text("ref: refs/heads/owned-雪\n", encoding="utf-8")
    (selected / ".git/config").write_text('[remote "origin"]\n url = https://github.com/owned/project.git\n', encoding="utf-8")
    recent = [{"path": str(root / ("recent-" + str(index))), "name": text(category)[:128] + str(index)} for index in range(64 if category == "huge" else 2)]
    action = lambda: owner.candidates(recent, "" if category in {"empty", "huge"} else text(category)[:128]) if identity.endswith("filter") else owner.local_projects()
    value = action()
    if identity.endswith("filter"):
        require(len(value["recent"]) <= 8 and len(value["local"]) <= 30, "Folder projections exceeded declared limits")
    else: require(value[0]["branch"] == "owned-雪" and value[0]["github"] == "owned/project", "Selected local Git metadata projection differs")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: require(list(pool.map(lambda _: action(), range(8))) == [value] * 8, "Concurrent folder projection changed one metadata source")
    elif category == "permissions":
        owner._CACHE.clear()
        with denied_file(selected / ".git/config"):
            rows = owner.local_projects(); require(rows[0]["github"] is None, "Unreadable selected remote metadata retained GitHub identity")
    elif category == "stale":
        (selected / ".git/HEAD").write_text("ref: refs/heads/current\n", encoding="utf-8")
        require(owner.local_projects()[0]["branch"] == "owned-雪", "Declared folder TTL cache was silently replaced")
        owner._CACHE.clear(); require(owner.local_projects()[0]["branch"] == "current", "Cleared cache retained earlier Git HEAD metadata")
    return {"selectedMetadataOnly": True, "accountAccess": False, "recentInputs": len(recent)}

def _seen(root, category, identity):
    from .connected_sessions.seen import SeenStore
    from .edge_fixture_preferences_skills import denied_file
    owner = SeenStore(root); owner.mark("owned", 1, "2026-10-04T00:00:00Z"); before = owner.path.read_bytes()
    if category == "permissions":
        with denied_file(owner.path):
            owner.mark("owned", 2, "2026-10-04T00:00:01Z")
        require(owner.path.read_bytes() == before, "Denied seen-marker replacement changed prior persisted bytes")
    else:
        program = "import os,sys;from grant_agent.proof_credential_guard import install;install(sys.argv[1]);from grant_agent.connected_sessions.seen import SeenStore;s=SeenStore(sys.argv[1]);s.mark('owned',2,'2026-10-04T00:00:01Z');os._exit(23)"
        child = subprocess.run([sys.executable, "-c", program, str(root)], capture_output=True, timeout=20, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23 and not SeenStore(root).unread("owned", "2026-10-04T00:00:01Z", 2), "Observed saved marker was lost after caller interruption")
    return {"priorMarkerSha256": hashlib.sha256(before).hexdigest(), "providerExecution": False}

def _native_page(root, category, identity):
    from .neyvia_conversations import NeyviaConversationStore
    from .connected_sessions.neyvia import NeyviaAdapter
    from .edge_fixture_preferences_skills import denied_file
    store = NeyviaConversationStore(root); row = store.create_conversation(title="Owned native history")
    cid = row["conversationId"]
    for index in range(8): store.append_turn(cid, role="user" if index % 2 == 0 else "assistant", content="Owned saved " + str(index), turn_id="saved-" + str(index), now=f"2026-10-04T00:00:{index:02}Z")
    adapter = NeyviaAdapter(SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=store))); sid = adapter._sid(cid)
    action = lambda: adapter.read(sid, limit=4)
    page = action(); require(len(page.items) == 4 and len({row.seq for row in page.items}) == 4, "Saved native page lost stable exclusive sequence")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: pages = list(pool.map(lambda _: action(), range(8)))
        require([[row.id for row in value.items] for value in pages] == [[row.id for row in page.items]] * 8, "Concurrent saved native pages changed IDs")
    elif category == "permissions":
        database = next((root / ".agent_control").rglob("*.sqlite3"))
        with denied_file(database): refused(action, (OSError, sqlite3.Error))
    return {"savedLocalTurns": 8, "pageItems": 4, "providerExecution": False}

def _opencode(root, category, identity):
    from .connected_sessions.opencode import OpenCodeAdapter
    from .external_chat_inventory import _host
    from .connected_sessions.registry import make_session_id
    from .edge_fixture_preferences_skills import denied_file
    data = root / "opencode"; data.mkdir(); os.environ["OPENCODE_DATA_DIR"] = str(data)
    git = shutil.which("git"); os.environ["PATH"] = str(Path(git).parent)
    database = data / "opencode.db"
    count = 64 if category == "huge" else 0 if category == "empty" else 4
    with sqlite3.connect(database) as conn:
        conn.executescript("CREATE TABLE session(id TEXT,title TEXT,directory TEXT,time_created INTEGER,time_updated INTEGER);CREATE TABLE message(id TEXT,session_id TEXT,data TEXT,time_created INTEGER);CREATE TABLE part(id TEXT,message_id TEXT,data TEXT,time_created INTEGER);")
        conn.execute("INSERT INTO session VALUES(?,?,?,?,?)", ("owned", text(category), str(root), 1000000, 1000001))
        for index in range(count):
            conn.execute("INSERT INTO message VALUES(?,?,?,?)", (str(index), "owned", json.dumps({"role": "assistant", "modelID": "supplied-model", "providerID": "supplied-policy-input"}), index))
            conn.execute("INSERT INTO part VALUES(?,?,?,?)", ("p" + str(index), str(index), json.dumps({"type": "text", "text": text(category)[:4096] + str(index)}, ensure_ascii=False), index))
    conn.close()
    adapter = OpenCodeAdapter(root); sid = make_session_id("opencode", _host()["deviceId"], "owned")
    action = lambda: adapter.read(sid, limit=8)
    page = action(); require(not page.session.capabilities.continue_session and len(page.items) <= 8, "Saved history fabricated installed provider execution or lost page bound")
    if count: require(any(item.kind == "reasoning" and item.data.get("availability") != "available" for item in adapter.read(sid, limit=200).items), "Saved assistant without reasoning lost truthful availability notice")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: pages = list(pool.map(lambda _: action(), range(4)))
        require([[row.id for row in value.items] for value in pages] == [[row.id for row in page.items]] * 4, "Concurrent saved OpenCode pages changed IDs")
    elif category == "permissions":
        with denied_file(database):
            observed = action(); require(not observed.items, "Denied OpenCode database produced saved private items")
    elif category == "stale":
        with sqlite3.connect(database) as conn:
            conn.execute("INSERT INTO message VALUES('new','owned',?,999)", (json.dumps({"role": "user"}),)); conn.execute("INSERT INTO part VALUES('p-new','new',?,999)", (json.dumps({"type": "text", "text": "Fresh current saved item"}),))
        fresh = adapter.read(sid, cursor=page.cursor, limit=200); require(any(item.data.get("text") == "Fresh current saved item" for item in fresh.items), "Exclusive saved cursor lost newer current item")
    return {"savedMessages": count, "pageItems": len(page.items), "installedProviderExecuted": False, "unknownReasoningHonest": True}

def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    rows = []
    if "sessions.folders.availability" in contracts:
        from .connected_sessions import folders
        original_path = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = str(Path(root) / "owned-empty-executable-root")
            status = folders.github_status(); require(not status["installed"] and not status["authenticated"], "Absent CLI fabricated availability")
            require(folders.github_repos() == [], "Absent CLI fabricated account repositories")
            from .proof_contracts import source_digest
            diagnostic = {"id": "diagnostic:absent-github-cli", "semanticCase": False, "status": "passed", "proofScope": "local_semantic", "sourceBindings": {"src/grant_agent/connected_sessions/folders.py": source_digest(REPO / "src/grant_agent/connected_sessions/folders.py")}, "detail": {"actualAbsentCli": True, "accountAccess": False, "dimensionalApplicability": False}}
            (Path(root) / "diagnostic-folder-availability.json").write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf8")
        finally: os.environ["PATH"] = original_path
    for identity in sorted(IDS & contracts.keys()):
        for category in categories:
            if category not in INTENDED[identity]: continue
            if blocker(contracts[identity], category): continue
            area = Path(root) / (identity + "-" + category + "-" + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            completed = subprocess.run([sys.executable, "-m", MODULE, "--port", os.environ["NEYVIA_C7_PORT"], "--case", str(area), identity, category], capture_output=True, text=True, encoding="utf-8", timeout=120, **hidden_windows_subprocess_kwargs())
            try: value = json.loads(completed.stdout)
            except ValueError: value = {"status": "failed", "detail": completed.stderr[-2500:]}
            if value.get("status") == "failed" and completed.stderr: value["childStderr"] = completed.stderr[-2500:]
            rows.append({"id": "c7d-sessions:" + identity + ":" + category, "contracts": [identity], "category": category, **value, "scratchRoot": str(area), "proofScope": "local_semantic", "boundary": "Exact selected local session owner; no rendered, installed-provider, remote-login or credential proof"})
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--port", type=int, required=True); parser.add_argument("--output", type=Path); parser.add_argument("--case", nargs=3); parser.add_argument("--contracts", nargs="*"); parser.add_argument("--categories", nargs="*", choices=CATEGORIES)
    args = parser.parse_args()
    if args.case:
        root, identity, category = args.case; _isolate(Path(root), args.port)
        try: value = {"status": "passed", "detail": _case(Path(root), category, identity)}
        except Exception as exc:
            import traceback
            value = {"status": "failed", "detail": {"error": str(exc)[:1800], "type": type(exc).__name__, "traceback": traceback.format_exc()[-2500:]}}
        print(json.dumps(value)); return
    if not args.output: parser.error("--output required")
    root = REPO / ".agent_control/proofs/c7d-sessions" / uuid.uuid4().hex; _isolate(root, args.port)
    from .edge_contracts import inventory
    from .proof_contracts import source_digest
    all_contracts = inventory()[1]; wanted = set(args.contracts or IDS)
    selected = {identity: all_contracts[identity] for identity in wanted}; categories = args.categories or CATEGORIES
    names = ["edge_fixture_c7d_sessions", "edge_fixture_sessions", "edge_fixture_local", "proofs_a_sessions", "proofs_a_providers", "proofs_e_wz", "proof_credential_guard", "subprocess_utils", "external_chat_inventory", "neyvia_conversations", "web_backend", "connected_chat_media", "chat_run_control", "connected_sessions/broker", "connected_sessions/registry", "connected_sessions/model", "connected_sessions/runs", "connected_sessions/seen", "connected_sessions/events", "connected_sessions/codex_items", "connected_sessions/neyvia", "connected_sessions/workspace", "connected_sessions/folders", "connected_sessions/opencode", "connected_sessions/opencode_history", "connected_sessions/opencode_acp", "connected_sessions/api", "connected_sessions/forward", "connected_sessions/claude", "connected_sessions/claude_stream", "connected_sessions/claude_items", "connected_sessions/claude_transcript", "durability"]
    bindings = {"src/grant_agent/" + name + ".py": source_digest(REPO / ("src/grant_agent/" + name + ".py")) for name in names}
    rows = run(root, selected, categories)
    audits = [{"contract": identity, "category": category, **reason} for identity, contract in selected.items() for category in categories if category in INTENDED[identity] and (reason := blocker(contract, category))]
    stable = all(source_digest(REPO / path) == digest for path, digest in bindings.items())
    diagnostics = [str(root / "diagnostic-folder-availability.json")] if (root / "diagnostic-folder-availability.json").exists() else []
    args.output.resolve().relative_to(REPO); args.output.write_text(json.dumps({"schema": "neyvia.c7d-sessions.raw.v1", "sourceBindings": bindings, "sourceStable": stable, "root": str(root), "explicitPort": args.port, "rows": rows, "audits": audits, "diagnostics": diagnostics}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": sum(row["status"] == "passed" for row in rows), "failed": sum(row["status"] == "failed" for row in rows), "audits": len(audits), "sourceStable": stable}))

if __name__ == "__main__": main()
