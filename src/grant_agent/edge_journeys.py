"""Real local effect/restart journeys for the adversarial contract campaign."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def offline_endpoint_error(port):
    """Observe bounded TCP unavailability; an accepting listener is never offline."""
    import socket
    try:
        connection = socket.create_connection(('127.0.0.1', port), timeout=1)
    except (ConnectionRefusedError, TimeoutError) as error:
        return error
    connection.close()
    raise ValueError('Assigned offline endpoint unexpectedly connected')


def run(root):
    from .native_tools import NativeToolRegistry
    from .action_receipts import NativeActionStore
    from .neyvia_workspace_tools import workspace_for
    from .neyvia_settings import get, update, SettingsConflict
    from .neyvia_awareness import claim, board_list, release
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(identity, category, contracts, action):
        try:
            detail = action()
            rows.append({"id": identity, "category": category, "contracts": contracts, "status": "passed", "detail": detail})
        except Exception as exc:
            rows.append({"id": identity, "category": category, "contracts": contracts, "status": "failed", "detail": type(exc).__name__ + ": " + str(exc)[:400]})

    registry = NativeToolRegistry(root / "workspace", nas_root=root)
    registry.root.mkdir(exist_ok=True)

    def write(args):
        answer = registry.call("workspace.write", args)
        if not answer["ok"]:
            raise ValueError(answer.get("error", "workspace write failed"))
        return answer["result"]

    def empty():
        value = write({"path": "empty.txt", "content": ""})
        if (registry.root / "empty.txt").read_bytes() != b"" or not value["readbackVerified"]:
            raise ValueError("Empty UTF-8 file differs")
        return {"bytes": value["bytes"], "readbackVerified": True}
    record("workspace-empty", "empty", ["c7.workspace.rejected-preserves"], empty)

    def rejected():
        results = []
        for name, args in (
            ("huge", {"content": "x" * (1024 * 1024 + 1)}),
            ("nul", {"content": "a\x00b"}),
            ("surrogate", {"content": "\ud800"}),
            ("missing-cas", {"content": "abc", "expectedSha256": "a" * 64}),
        ):
            parent = registry.root / ("reject-" + name)
            result = registry.call("workspace.write", {"path": parent.name + "/file.txt", **args})
            if result["ok"] or parent.exists():
                raise ValueError(name + " rejected request changed filesystem")
            results.append({"case": name, "ok": result["ok"], "phase": result["proofs"]["phase"], "parentAbsent": True})
        return results
    record("workspace-rejected-no-directories", "huge", ["c7.workspace.rejected-preserves"], rejected)

    def unicode():
        body = "雪🙂e\u0301\u202e\r\nsecond\rthird\n"
        result = write({"path": "unicode.txt", "content": body})
        raw = (registry.root / "unicode.txt").read_bytes()
        if raw != body.encode("utf-8") or result["sha256"] != hashlib.sha256(raw).hexdigest():
            raise ValueError("UTF-8/newline bytes changed")
        return {"bytes": len(raw), "sha256": result["sha256"]}
    record("workspace-unicode-bytes", "unicode", ["c7.workspace.rejected-preserves"], unicode)

    def stale():
        path = registry.root / "unicode.txt"
        before = path.read_bytes()
        rejected = registry.call("workspace.write", {"path": "unicode.txt", "content": "overwrite", "expectedSha256": "a" * 64})
        if rejected["ok"] or path.read_bytes() != before:
            raise ValueError("Stale CAS overwrote source")
        return {"refused": True, "bytesPreserved": True}
    record("workspace-stale-hash", "stale", ["c7.workspace.rejected-preserves"], stale)

    service = workspace_for(root / "settings")

    def settings_race():
        import threading
        revision = get(service)["revision"]
        ready = threading.Barrier(2)
        def contender(theme):
            ready.wait(timeout=10)
            try:
                return update(service, {"theme": theme}, revision)["revision"]
            except SettingsConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contender, ("morning", "sunset")))
        final = get(service)
        if results.count("conflict") != 1 or final["revision"] != revision + 1:
            raise ValueError("Expected exactly one CAS winner")
        return {"outcomes": results, "finalRevision": final["revision"]}
    record("settings-concurrent-cas", "concurrency", ["settings.revision-cas", "settings.canonical-mirrors"], settings_race)

    def settings_stale():
        before = get(service)
        try:
            update(service, {"theme": "forest"}, before["revision"] - 1)
        except SettingsConflict:
            if get(service) != before:
                raise ValueError("Stale settings request changed state")
            return {"refused": True, "revision": before["revision"]}
        raise ValueError("Stale settings revision accepted")
    record("settings-stale", "stale", ["settings.revision-cas"], settings_stale)

    def settings_empty():
        before = get(service)
        try:
            update(service, {}, before["revision"])
        except ValueError:
            if get(service) != before:
                raise ValueError("Empty patch changed state")
            return {"refused": True, "eventsUnchanged": True}
        raise ValueError("Empty patch accepted")
    record("settings-empty", "empty", ["settings.invalid-preserves"], settings_empty)

    def work_unicode():
        receipt = claim(root / "board", {"files": ["雪/café.txt", "雪/café.txt"], "intent": "Unicode owned claim 🙂", "agent": "c7"})
        listed = board_list(root / "board")
        if listed["count"] != 1 or listed["claims"][0]["files"] != ["雪/café.txt"]:
            raise ValueError("Claim normalization lost Unicode or uniqueness")
        release(root / "board", {"id": receipt["claim"]["id"]})
        if board_list(root / "board")["count"]:
            raise ValueError("Release did not persist")
        return {"uniquePaths": 1, "released": True}
    record("awareness-unicode", "unicode", ["awareness.claim.persisted", "awareness.list.projection", "awareness.release.persisted"], work_unicode)

    def interruption():
        target = root / "crash"
        target.mkdir()
        code = '''import os,sys
from pathlib import Path
from grant_agent.action_receipts import NativeActionStore
root=Path(sys.argv[1])
def effect():
    (root/'effect.txt').write_text('exactly once',encoding='utf-8')
    os._exit(23)
NativeActionStore(root,'c7-crash').execute('intent-1','workspace.write',{'content':'exactly once'},effect)
'''
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        child = subprocess.run([sys.executable, "-c", code, str(target)], env=env, capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
        if child.returncode != 23 or (target / "effect.txt").read_text(encoding="utf-8") != "exactly once":
            raise ValueError("Owned child did not exit at the effect/receipt boundary")
        store = NativeActionStore(target, "c7-crash")
        invoked = []
        answer = store.execute("intent-1", "workspace.write", {"content": "exactly once"}, lambda: invoked.append(True))
        if invoked or answer.get("ok") is not False or answer.get("status") not in {"action_uncertain", "uncertain"}:
            raise ValueError("Interrupted effect replayed or reported success")
        return {"childExit": child.returncode, "effectBytes": (target / "effect.txt").stat().st_size, "resumeStatus": answer["status"], "replayedEffects": len(invoked)}
    record("action-crash-resume", "interrupted", ["proofs-e-host.action-once"], interruption)

    def permission():
        from .neyvia_agent import NeyviaToolGateway
        target = root / "read-only"
        target.mkdir()
        from .proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(target)
        gateway = NeyviaToolGateway(target, allow_mutations=False, permission_mode="read-only")
        answer = gateway.call_native("workspace.write", {"path": "forbidden.txt", "content": "forbidden"})
        if (target / "forbidden.txt").exists() or answer.get("ok") is not False:
            raise ValueError("Read-only gateway permitted mutation")
        return {"refused": True, "fileAbsent": True, "status": answer.get("status")}
    record("gateway-read-only", "permissions", ["c7.gateway.read-only"], permission)

    def offline():
        port = int(os.environ["NEYVIA_C7_PORT"])
        # TIME_WAIT can prevent binding a port with no listener. A failed TCP
        # connection is the observation; HTTP response timeouts cannot admit it.
        error = offline_endpoint_error(port)
        store = NativeActionStore(root / "offline", "c7-offline")
        answer = store.execute("offline-1", "workspace.write", {"content": "local"}, lambda: {"ok": True, "status": "created"})
        replay = NativeActionStore(root / "offline", "c7-offline").execute("offline-1", "workspace.write", {"content": "local"}, lambda: {"ok": False})
        if answer.get("ok") is False or replay.get("ok") is False or not replay.get("duplicateSuppressed"):
            raise ValueError("Offline action receipt did not survive restart")
        return {"port": port, "networkError": type(error).__name__, "failurePhase": "tcp-connect", "durableReplay": True}
    record("offline-receipt-restart", "offline", ["proofs-e-host.action-once"], offline)
    return rows
