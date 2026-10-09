"""Focused MCP-adjacent event boundary fixtures for C7d."""
from __future__ import annotations

from pathlib import Path


def claude_events(root: Path, category: str) -> dict:
    from .connected_sessions.claude_stream import ClaudeRun
    from .connected_sessions.claude_terminal import ClaudeTerminalRun
    from .connected_sessions.model import TurnOptions
    from .proofs_a_providers import check_event

    def require(condition: bool, detail: str) -> None:
        if not condition:
            raise AssertionError(detail)

    text = "" if category == "empty" else "é›ªðŸ™‚e\u0301 " * 20_000
    observed: list[dict] = []
    event = {"type": "item.delta", "runId": "owned-run", "sessionId": "owned-session",
             "itemId": "owned-item", "textDelta": text}

    stream = ClaudeRun(cli=["owned"], run_id="owned-run", session_id="owned-session", message="owned",
                       options=TurnOptions(), cwd=str(root), emit=observed.append, context_probe=False)
    stream._emit(dict(event))

    terminal = ClaudeTerminalRun(cli=["owned"], run_id="owned-run", session_id="owned-session", message="owned",
                                 options=TurnOptions(), cwd=str(root), emit=observed.append,
                                 projects=root, store_for=lambda *_: None, context_for=lambda *_: None,
                                 python="owned-python")
    terminal._emit(dict(event))

    require(len(observed) == 2 and observed == [event, event], "provider emitters dropped/altered empty or large targeted delta")
    for row in observed:
        check_event("claude", row)
        require(row["runId"] == "owned-run" and row["sessionId"] == "owned-session"
                and row["itemId"] == "owned-item" and row["textDelta"] == text,
                "provider event lost run/session identity, delta target, or exact text")
    return {"emitters": ["ClaudeRun", "ClaudeTerminalRun"], "events": len(observed),
            "deltaCharacters": len(text), "deltaBytes": len(text.encode("utf8")), "targetPreserved": True}


def core_protocol(server, category, text, request, call):
    from .edge_fixture_c7d_control import require
    from .edge_fixture_native import _sharing_denied
    from .neyvia_mcp import MCP_PROTOCOL_VERSION
    requested = "2024-10-07" if category == "stale" else text or MCP_PROTOCOL_VERSION
    initialized = request("initialize", {"protocolVersion": requested, "capabilities": {}})
    require(initialized["result"]["protocolVersion"] == requested and initialized["result"]["capabilities"]["tasks"]["requests"] == {"tools": {"call": {}}}, "MCP protocol/task negotiation changed")
    def observe():
        response = server.handle({"jsonrpc": "2.0", "id": "catalog", "method": "tools/list", "params": {"includeSchemas": False}})
        rows = response["result"]["tools"]
        names = [r["name"] for r in rows]
        require(names == sorted(names) and len(names) == len(set(names))
                and {"neyvia.time.budget", "neyvia.research.start"} <= set(names)
                and all("inputSchema" not in row for row in rows), "MCP catalog order/uniqueness/synchronous/durable surfaces changed")
        return response
    values = [observe(), observe()]
    require(values[0] == values[1] and server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None, "MCP catalog instability or initialized notification reply")
    if category == "permissions":
        with _sharing_denied(server.store.database_path):
            under_denial = request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}})
            denied_catalog = request("tools/list", {"includeSchemas": False})
        require(under_denial["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
                and denied_catalog["result"]["tools"] == values[0]["result"]["tools"]
                and server.store.list_tasks() == [], "read-only MCP protocol path touched denied durable task store")
        return observe, {"deniedStore": True, "protocolAndCatalogAvailable": True, "durableTasks": 0}
    return observe, None


def core_budget(server, category, text, request, call):
    from .edge_fixture_c7d_control import require
    from .edge_fixture_native import _sharing_denied
    from .neyvia_mcp import MCP_PROTOCOL_VERSION
    args = {"deadlineAt": "2999-01-01T00:00:00Z", "estimatedNextSeconds": 20, "verificationReserveSeconds": 10, "optional": True}
    def observe():
        value = server._call_tool({"name": "neyvia.time.budget", "arguments": args, "task": {"ttl": 60000}})
        require("task" not in value and value["structuredContent"]["shouldContinue"], "synchronous time budget was task-wrapped or refused available window")
        return value
    observe()
    if category == "permissions":
        with _sharing_denied(server.store.database_path):
            denied = request("tools/call", {"name": "neyvia.time.budget", "arguments": args, "task": {"ttl": 60000}})
        require(denied.get("error", {}).get("code") == -32602 and "synchronous decision" in denied["error"]["message"]
                and server.store.list_tasks() == [], "store permission denial was hidden or persisted an MCP task")
        return observe, {"deniedStore": True, "honestRpcRefusal": denied["error"], "durableTasks": 0}
    if category == "stale":
        expired = server._call_tool({"name": "neyvia.time.budget", "arguments": {**args, "deadlineAt": "2000-01-01T00:00:00Z"}, "task": {"ttl": 60000}})
        require(not expired["structuredContent"]["shouldContinue"]
                and "task" not in expired and server.store.list_tasks() == [], "stale expired deadline continued or created a task")
        return observe, {"expiredDeadlineStopped": True, "durableTasks": 0}
    if category == "empty":
        absent = call("neyvia.time.budget", {})
        require(absent["structuredContent"]["reason"] == "no_deadline" and absent["structuredContent"]["remainingSeconds"] is None and "task" not in absent, "absent deadline fabricated a budget or task")
    elif category == "huge":
        large = call("neyvia.time.budget", {**args, "estimatedNextSeconds": 1e20})
        require(not large["structuredContent"]["shouldContinue"] and large["structuredContent"]["requiredSeconds"] == 1e20 and "task" not in large, "large optional cost lost the synchronous stop decision")
    elif category == "unicode":
        invalid = request("tools/call", {"name": "neyvia.time.budget", "arguments": {**args, "deadlineAt": text}})
        require(invalid.get("error", {}).get("code") == -32602 and "task" not in invalid, "Unicode malformed deadline silently admitted or task-wrapped")
    require(server.store.list_tasks() == [], "synchronous time budget persisted an extension task")
    expired = call("neyvia.time.budget", {**args, "deadlineAt": "2000-01-01T00:00:00Z"})
    require(not expired["structuredContent"]["shouldContinue"] and "task" not in expired, "expired optional time budget kept running or wrapped task")
    return observe, None
