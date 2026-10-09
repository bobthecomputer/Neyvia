"""A short, owned Git note journey through Neyvia's native application tools."""
from __future__ import annotations

import time
import uuid
from pathlib import Path


CONTRACTS = ("p22.applications.git-note-journey",)


def self_check(root=None):
    """Revise and save a Unicode note, then check stale and persisted states."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    state_root = repo / ".agent_control" / "p22" / "applications-journey" / uuid.uuid4().hex
    state_root.mkdir(parents=True, exist_ok=False)
    from . import cua_native_procedures as native

    guard_log = state_root / "guard.jsonl"
    original_guard = native.ZeroDisturbanceGuard

    class IsolatedGuard(original_guard):
        def __init__(self, *args, **kwargs):
            kwargs["external_log"] = guard_log
            super().__init__(*args, **kwargs)

    native.ZeroDisturbanceGuard = IsolatedGuard
    hosted = native.hosted_native_applications(state_root)
    session = None

    def call(operation, arguments):
        return hosted.request(operation, arguments)

    try:
        opened = call("open", {"app": "Git"})
        session = opened["sessionId"]
        if opened.get("source") != "real Git CLI on owned disposable repository":
            raise ValueError("The journey did not open a new owned Git repository")

        first = "Résumé — first saved revision"
        latest = "Résumé — latest saved revision"
        call("edit", {"sessionId": session, "value": first})
        if not call("observe", {"sessionId": session, "expected": first, "persisted": False})["ok"]:
            raise ValueError("The owned Git note did not expose its first edited text")
        call("persist", {"sessionId": session})
        first_saved = call("observe", {"sessionId": session, "expected": first, "persisted": True})
        if not first_saved["ok"] or not first_saved["artifact"]["clean"]:
            raise ValueError("The first note revision did not survive Git commit and readback")

        path = state_root / ".agent_control" / "native-applications" / session / "note.txt"
        before_invalid = path.read_bytes()
        try:
            call("edit", {"sessionId": session, "value": "invalid\nrevision"})
        except ValueError:
            pass
        else:
            raise ValueError("Git accepted multiline note content")
        if path.read_bytes() != before_invalid:
            raise ValueError("Rejected multiline input changed the saved note")

        call("edit", {"sessionId": session, "value": latest})
        stale = call("observe", {"sessionId": session, "expected": first, "persisted": True})
        current = call("observe", {"sessionId": session, "expected": latest, "persisted": False})
        if stale["ok"] or not current["ok"]:
            raise ValueError("A newer edit did not invalidate the stale saved view")
        saved = call("persist", {"sessionId": session})
        observed = call("observe", {"sessionId": session, "expected": latest, "persisted": True})
        if not saved["ok"] or not observed["ok"] or not observed["artifact"]["clean"]:
            raise ValueError("The latest Unicode note did not survive a clean Git commit and independent readback")
        if observed["artifact"]["committedText"] != latest:
            raise ValueError("Git HEAD does not contain the latest visible note text")
        cleanup = call("close", {"sessionId": session})
        session = None
        if not cleanup["ok"]:
            raise ValueError("The owned native session or its disturbance guard did not close cleanly")
        return {
            "ok": True,
            "contracts": list(CONTRACTS),
            "cases": [{"id": CONTRACTS[0], "ok": True, "durationMs": round((time.perf_counter() - started) * 1000)}],
            "reopenedFromGitHead": True,
            "unicodePreserved": True,
            "staleSavedViewRefused": True,
            "rejectedMultilinePreservedBytes": True,
            "ownedProcessesExited": all(row.get("exitCode") == 0 for row in cleanup["cleanup"]["processes"]),
            "boundary": "Production native Git tool journey in a disposable repository; no editor UI or Office COM claim",
        }
    finally:
        if session is not None:
            try:
                call("close", {"sessionId": session})
            except Exception:
                pass
        hosted.shutdown()
        native.ZeroDisturbanceGuard = original_guard
