"""Fast production workspace report to durable Outputs journey."""
from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

CONTRACTS = ("p22.workspace.output-journey",)


def require(condition, detail):
    if not condition:
        raise ValueError("Contract p22.workspace.output-journey: " + detail)


def self_check(root=None):
    """Write, publish, reopen and supersede a real report in an isolated workspace."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    supplied = Path(root).expanduser().resolve() if root else Path("D:/NeyviaRuns/P22/workspace-journey").resolve()
    allowed_root = Path("D:/NeyviaRuns/P22").resolve()
    require(supplied.is_relative_to(allowed_root),
            "scratch root must stay under D:/NeyviaRuns/P22")
    state_root = (supplied / uuid.uuid4().hex).resolve()
    require(state_root.is_relative_to(allowed_root),
            "per-run state root must stay under D:/NeyviaRuns/P22")
    state_root.mkdir(parents=True, exist_ok=False)
    from .native_tools import NativeToolRegistry
    from .neyvia_workspace_tools import WorkspaceTools

    registry = NativeToolRegistry(state_root)
    service = WorkspaceTools(state_root)
    session_id = "p22-workspace-" + uuid.uuid4().hex
    run_id = "p22-output-" + uuid.uuid4().hex
    request_id = "p22-report-" + uuid.uuid4().hex
    relative = "report.md"
    report = "# Release notes\n\nThe report was saved through the workspace action.\n"
    revised = "# Release notes\n\nThe reviewed report has a corrected result.\n"
    try:
        before_events = service.bus.since()
        cursor = int(before_events[-1]["id"]) if before_events else 0

        write_receipt = registry.call("workspace.write", {"path": relative, "content": report})
        created = write_receipt.get("result", {})
        require(write_receipt.get("ok") and created.get("ok") and created.get("status") == "created" and created.get("readbackVerified"),
                "workspace.write must create the report and verify its persisted bytes")
        first_hash = hashlib.sha256(report.encode("utf-8")).hexdigest()
        require(created.get("sha256") == first_hash and (state_root / relative).read_text(encoding="utf-8") == report,
                "the durable file bytes and returned SHA-256 must match the report")

        published = service.call("artifact.publish", {
            "path": relative, "kind": "report", "title": "Release notes",
            "sessionId": session_id, "runId": run_id, "requestId": request_id,
            "metadata": {"producer": "workspace-journey"},
        })
        require(published.get("ok") and published["artifact"]["sha256"] == first_hash
                and published["artifact"]["sessionId"] == session_id
                and published["artifact"]["runId"] == run_id,
                "the Outputs publication must retain exact report bytes and session/run provenance")
        first_id = published["artifact"]["id"]

        rows = service.call("artifact.list", {"sessionId": session_id, "runId": run_id, "limit": 10})
        require(rows.get("total") == 1 and [row["id"] for row in rows.get("artifacts", [])] == [first_id],
                "filtered Outputs listing must expose this report and no unrelated workspace output")
        available = service.call("artifact.get", {"id": first_id})
        require(available.get("availability") == "available" and available["currentSha256"] == first_hash,
                "a fresh output read must verify the exact saved bytes")

        retry = service.call("artifact.publish", {
            "path": relative, "kind": "report", "title": "Release notes",
            "sessionId": session_id, "runId": run_id, "requestId": request_id,
            "metadata": {"producer": "workspace-journey"},
        })
        require(retry.get("ok") and retry.get("replayed") is True
                and retry["artifact"]["id"] == first_id and "event" not in retry,
                "an identical request retry must reuse its publication without a second event")
        retry_events = service.bus.since(cursor)
        published_events = [event for event in retry_events if event["action"] == "artifact.published"]
        require(len(published_events) == 1 and published_events[0]["payload"]["artifact"]["id"] == first_id,
                "the durable observer must record one publication for both calls")

        change_receipt = registry.call("workspace.write", {
            "path": relative, "content": revised, "expectedSha256": first_hash,
        })
        changed = change_receipt.get("result", {})
        revised_hash = hashlib.sha256(revised.encode("utf-8")).hexdigest()
        require(change_receipt.get("ok") and changed.get("ok") and changed.get("status") == "updated"
                and changed.get("sha256") == revised_hash and changed.get("readbackVerified"),
                "the reviewed compare-and-swap write must save and verify the revised report")
        stale = service.call("artifact.get", {"id": first_id})
        require(stale.get("availability") == "changed" and stale.get("currentSha256") == revised_hash,
                "the original publication must report changed bytes after the report is revised")
        refused = service.call("artifact.open", {"id": first_id})
        require(refused.get("ok") is False and refused.get("status") == "conflict",
                "opening a publication whose bytes changed must be refused before pane creation")
        after_refusal = service.bus.since(cursor)
        require(not any(event["action"] == "pane.show" for event in after_refusal),
                "a changed-byte refusal must not enqueue a preview pane")

        latest = service.call("artifact.publish", {
            "path": relative, "kind": "report", "title": "Release notes",
            "sessionId": session_id, "runId": run_id, "requestId": request_id + "-revised",
            "metadata": {"producer": "workspace-journey"},
        })
        require(latest.get("ok") and latest["artifact"]["sha256"] == revised_hash
                and latest["artifact"].get("previousId") == first_id,
                "a revised report must create a new linked output version")
        opened = service.call("artifact.open", {"id": latest["artifact"]["id"]})
        require(opened.get("ok") and opened.get("status") == "pending_renderer"
                and opened.get("event", {}).get("action") == "pane.show",
                "the available version must create the guarded artifact pane request")
        request = opened["event"]["payload"]
        require(request.get("kind") == "artifact" and request.get("target") == str((state_root / relative).resolve())
                and opened.get("preview", {}).get("kind") == "markdown"
                and opened.get("preview", {}).get("text") == revised,
                "the artifact pane must carry the exact revised Markdown bytes from its guarded read")
        case = {"id": "workspace.output-journey", "contracts": list(CONTRACTS), "ok": True,
                "publishedId": first_id, "revisedId": latest["artifact"]["id"],
                "replayEvents": len(published_events), "staleOpenRefused": True,
                "paneStatus": opened["status"]}
        return {"ok": True, "contracts": list(CONTRACTS), "cases": [case], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root),
                "frontier": "Runs actual workspace.write and Outputs services with SQLite state and the native event bus. It proves exact-byte gating and a pane request, not a mounted or visible browser renderer."}
    except Exception as error:
        return {"ok": False, "contracts": list(CONTRACTS), "cases": [{"id": "workspace.output-journey",
                "contracts": list(CONTRACTS), "ok": False, "error": str(error)}], "failures": [str(error)],
                "durationMs": round((time.perf_counter() - started) * 1000, 3), "stateRoot": str(state_root)}
    finally:
        service.close()
