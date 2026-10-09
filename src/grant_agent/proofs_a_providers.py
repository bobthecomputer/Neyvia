"""Provider contracts and confined protocol observer procedures.

The scratch peers speak provider protocols but never call a model or account.
They exercise the production adapters, file readers, processes and hook script.
Their receipts establish host semantics, not external provider performance.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import functools
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


def require(condition, identity, message):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{identity}: {message}")


def checked(identity):
    """Preserve the owner's signature; check at every direct production call."""
    def decorate(action):
        signature = inspect.signature(action)
        @functools.wraps(action)
        def invoke(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            if identity == "providers.terminal.compact":
                arguments["_previous_stop"] = arguments["self"]._stop_at
            if identity == "providers.terminal.answer":
                # Decision consumption and its invariant are one transaction. The drain
                # thread may otherwise refill the cleared trust screen before validation.
                with arguments["self"]._lock:
                    arguments["_pending_before"] = arguments["self"]._pending.get(arguments["request_id"])
                    result = action(*bound.args, **bound.kwargs)
                    check(identity, arguments, result)
                    return result
            if identity == "providers.claude.live":
                arguments["_previous_cache"] = arguments["self"]._agents_cache
            if identity in {"providers.claude.lifecycle", "providers.codex.lifecycle"}:
                events = []
                original = arguments["emit"]
                def observe(event):
                    events.append(event)
                    if original:
                        original(event)
                bound.arguments["emit"] = observe
                arguments["_events"] = events
            try:
                result = action(*bound.args, **bound.kwargs)
            except BaseException as error:
                if identity == "providers.codex.goal":
                    expected = "invalid_action" if arguments["action"] not in {"get", "set", "clear"} else "goal_required" if arguments["action"] == "set" and not str(arguments["text"] or "").strip() else None
                    if expected:
                        require(getattr(error, "code", None) == expected, identity, "invalid goal request did not return precise refusal")
                if identity == "providers.codex.thread" and getattr(error, "__cause__", None) is not None:
                    raw = getattr(error.__cause__, "raw_message", "")
                    if re.search(r"not loaded|not found|no rollout|invalid thread id|unknown thread|does not exist", raw, re.I):
                        require(getattr(error, "code", None) == "session_not_found", identity, "missing provider thread did not translate to session_not_found")
                if identity == "providers.claude.lifecycle" and getattr(error, "code", None):
                    text = str(arguments["message"] or "").strip()
                    command = (text.split(None, 1) or [""])[0].lower()
                    expected = "empty_message" if not text and not arguments["options"].images else "message_too_long" if len(text) > 100000 else "unsupported_command" if command in {"/clear", "/reset", "/new", "/branch", "/fork", "/resume"} else None
                    if expected:
                        require(error.code == expected and not arguments["_events"], "providers.claude.request", "invalid input did not fail before turn events")
                raise
            check(identity, arguments, result)
            return result
        return invoke
    return decorate


def check(identity, a, result):
    """Independent invariants at shared host boundaries, without contents in errors."""
    from urllib.parse import quote
    if identity == "providers.claude.identity":
        host = a.get("host")
        if host:
            require(result == f"external:claude-code:{host['deviceId']}:{quote(str(a['session_id']), safe='-_.~')}", identity, "identity projection changed")
    elif identity == "providers.claude.origin":
        raw = str(a["cwd"] or "").replace("\\", "/").rstrip("/").casefold() + "/"
        roots = a.get("temp_roots")
        if roots is None:
            import tempfile
            roots = [tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", "")]
        expected = bool(a["cwd"]) and (any(part in raw for part in ("/.agent_control/", "/proof/", "evidence", "harness-comparison", "neyvia-claude-resume-proof", ".sandbox-scratch")) or any(raw.startswith(str(root).replace("\\", "/").rstrip("/").casefold() + "/") for root in roots if root))
        require(result is expected, identity, "origin disagrees with documented scratch roots")
    elif identity == "providers.claude.output":
        raw = a["text"].encode("utf-8", "replace")
        shown, truncated, length = result
        require(length == len(raw) and truncated is (len(raw) > a["limit"]), identity, "byte length or truncation changed")
        if truncated:
            head = raw[:int(a["limit"] * .7)].decode("utf-8", "ignore")
            tail = raw[-int(a["limit"] * .25):].decode("utf-8", "ignore")
            require(shown.startswith(head) and shown.endswith(tail) and f"{len(raw) - len(head.encode()) - len(tail.encode())} bytes omitted" in shown, identity, "head/tail or omission receipt changed")
        else:
            require(shown == a["text"], identity, "unbounded text changed")
    elif identity == "providers.claude.category":
        groups = {"command": {"Bash", "PowerShell", "BashOutput", "KillShell", "Monitor"}, "edit": {"Edit", "Write", "MultiEdit", "NotebookEdit"}, "read": {"Read", "NotebookRead"}, "search": {"Grep", "Glob", "LS", "ToolSearch"}, "web": {"WebFetch", "WebSearch"}, "agent": {"Agent", "Task"}}
        expected = "mcp" if a["name"].startswith("mcp__") else next((key for key, names in groups.items() if a["name"] in names), "other")
        require(result == expected, identity, "tool category changed")
    elif identity == "providers.claude.title":
        require(isinstance(result, str) and len(result) <= 120 and "\n" not in result, identity, "tool title is not compact")
    elif identity == "providers.claude.classify":
        kind, text, level = result
        require(kind in {"hidden", "prose", "notice"} and level in {"info", "warning", "error"}, identity, "unknown marker classification")
        require(kind != "hidden" or text == "", identity, "hidden marker leaked text")
        require(not re.search(r"<(system-reminder|local-command-caveat|user-prompt-submit-hook|ide_opened_file|ide_selection|ide_diagnostics)>", text), identity, "internal marker became prose")
    elif identity == "providers.claude.environment":
        from .connected_sessions.claude_stream import _HOST_SESSION_ENV
        extra = a["extra"] or {}
        require(all(key not in result or key in extra for key in _HOST_SESSION_ENV), identity, "outer session identity inherited")
        require("CLAUDE_CODE_DISABLE_THINKING" not in result and result.get("MAX_THINKING_TOKENS") != "0", identity, "thinking disabled in child")
        require(all(key in os.environ or key in extra for key in result), identity, "child invented an environment key")
    elif identity in {"providers.claude.argv", "providers.terminal.argv"}:
        options = a["options"]
        terminal = identity == "providers.terminal.argv"
        cli = a["cli"]
        prefix = [str(part) for part in cli] if isinstance(cli, (tuple, list)) else [str(cli)]
        require(result[:len(prefix)] == prefix, identity, "CLI prefix changed")
        if terminal:
            require("-p" not in result and result[-2:] == ["--", a["message"]] and result[result.index("--settings") + 1] == str(a["settings"]), identity, "interactive message/settings boundary changed")
        else:
            require("-p" in result and all(result[result.index(flag) + 1] == value for flag, value in (("--input-format", "stream-json"), ("--output-format", "stream-json"), ("--permission-prompt-tool", "stdio"))), identity, "stream transport flags changed")
        resumed = a["session_id"] if (a.get("resume") if terminal else a["session_id"]) else options.fork_from
        require(("--resume" in result) is bool(resumed), identity, "resume presence changed")
        if resumed:
            require(result[result.index("--resume") + 1] == resumed, identity, "wrong resumed chat")
        if options.fork_from and not (a.get("resume") if terminal else a["session_id"]):
            require("--fork-session" in result, identity, "branch flag absent")
        for field, flag in (("model", "--model"), ("effort", "--effort"), ("permission_mode", "--permission-mode")):
            value = getattr(options, field)
            if value:
                value = "manual" if field == "permission_mode" and value == "default" else value
                require(result[result.index(flag) + 1] == value, identity, "chosen option changed")
    elif identity == "providers.terminal.screen":
        require("\x1b" not in result and "\r" not in result, identity, "screen contains terminal control sequences")
    elif identity == "providers.claude.aggregate":
        agg = a["self"]
        totals = a["hints"].get("totals") or {}
        authoritative = a["hints"].get("syncResult") is not None
        expected = totals.get("outputTokens") if authoritative and totals.get("outputTokens") is not None else sum(agg.out_by_msg.values()) if agg.out_by_msg else totals.get("outputTokens")
        require(result["outputTokens"] == expected, identity, "repeated blocks double counted output")
        require(result["inputTokens"] == (totals.get("inputTokens") if authoritative and totals.get("inputTokens") is not None else agg.last_context if agg.last_context is not None else totals.get("inputTokens")), identity, "context became a running token sum")
    elif identity == "providers.claude.capabilities":
        owner, status = a["owner"], a["status"]
        installed = a["installed"] if a["installed"] is not None else a["self"]._cli() is not None
        busy = owner in {"app", "cli"} and (status != "idle" or owner == "cli")
        require(result.continue_session is (installed and not busy) and result.compact is (installed and not busy), identity, "competing writer enabled")
        require(result.new_session is bool(installed), identity, "missing CLI advertises a new chat")
    elif identity == "providers.claude.auth":
        require(set(result) == {"kind", "label"} and result["kind"] in {"subscription", "gateway", "api-key", "signed-out", "unknown"}, identity, "auth is not a public billing projection")
    elif identity == "providers.claude.transports":
        require([entry["id"] for entry in result] == ["print", "terminal"] and result[0]["default"] is True and result[1]["default"] is False and bool(result[1]["risk"]) and "account" in result[1]["risk"], identity, "transport defaults or consent disclosure changed")
        note = a["auth"].get("kind") not in {"subscription", "unknown"}
        require(all(bool(row["note"]) is note for row in result), identity, "billing notice changed")
    elif identity == "providers.claude.reply":
        reply, answers = result
        decision = a["decision"]
        require(reply.get("behavior") == ("allow" if decision == "approve" else "deny") and (decision != "cancel" or reply.get("interrupt") is True), identity, "approval reply changed")
        if decision == "approve" and a["pending"].kind == "question":
            questions = a["pending"].tool_input.get("questions") or []
            require(set(answers) == {f"q{i}" for i in range(len(questions))} and all(answers.values()), identity, "question answer missing")
            require(reply["updatedInput"]["answers"] == {str(q.get("question") or ""): answers[f"q{i}"] for i, q in enumerate(questions)}, identity, "question keys differ on wire")
    elif identity == "providers.rpc.backoff":
        conn = a["self"]
        delay = conn._backoff[min(conn._failures - 1, len(conn._backoff) - 1)] if conn._backoff else 0
        require(conn._next_start_at <= time.monotonic() + delay + .05 and conn._next_start_at >= time.monotonic() + delay - 1, identity, "retry backoff changed")
    elif identity == "providers.rpc.response":
        require(isinstance(a["result"], dict) and isinstance(a["generation"], int) and a["generation"] > 0, identity, "server answer has no typed connection generation")
        if "currentTimeAt" in a["result"]:
            require(set(a["result"]) == {"currentTimeAt"} and abs(a["result"]["currentTimeAt"]-time.time()) < 5, identity, "clock answer is not current epoch seconds")
    elif identity == "providers.codex.input":
        expected = ([{"type": "text", "text": a["text"], "text_elements": []}] if a["text"] else []) + [{"type": "image", "url": f"data:{image['mime']};base64,{image['data']}"} for image in a["images"]]
        require(result == expected, identity, "text/image transport payload changed")
    elif identity == "providers.codex.auth":
        require(set(result) == {"kind", "label"} and result["kind"] in {"subscription", "api-key", "signed-out", "unknown", "none-required", "other"}, identity, "auth disclosed nonpublic account fields")
    elif identity == "providers.codex.integrations":
        plugins, servers, index = result
        require(len({row["id"] for row in plugins}) == len(plugins) and all(row["state"] in {"connected", "needs_sign_in", "disabled", "starting", "error"} for row in plugins + servers), identity, "integration IDs/state invalid")
        installed = {f"plugin:{p.get('id')}" for market in a["installed"].get("marketplaces", []) for p in market.get("plugins", []) if p.get("installed")}
        require(all(row["id"] in installed for row in plugins if row["kind"] == "plugin"), identity, "uninstalled plugin advertised")
        sources = {f"plugin:{p.get('id')}": p for market in a["installed"].get("marketplaces", []) for p in market.get("plugins", []) if p.get("installed")}
        for row in plugins:
            if row["kind"] != "plugin":
                continue
            source = sources[row["id"]]
            owned = {server["state"] for server in servers if server.get("pluginId") == source.get("id")}
            if not source.get("enabled") or source.get("availability") != "AVAILABLE":
                expected = "disabled"
            elif owned:
                priority = next((state for state in ("error", "needs_sign_in", "starting") if state in owned), None)
                expected = priority or ("disabled" if owned == {"disabled"} else "connected")
            else:
                continue
            require(row["state"] == expected, identity, "plugin readiness differs from actual owned MCP server states")
    elif identity == "providers.codex.wire":
        params, method = a["params"] or {}, a["method"]
        require(isinstance(result, dict), identity, "RPC response is not an object")
        if method in {"thread/turns/list", "thread/list", "model/list", "project/list"}:
            rows = result.get("data") or []
            require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), identity, "paged response rows invalid")
            if params.get("limit"):
                require(len(rows) <= params["limit"], identity, "RPC page exceeded requested limit")
        if method == "turn/start":
            require(bool(params.get("threadId")) and bool(params.get("input")) and params.get("summary") == "detailed", identity, "turn input/thread/reasoning policy absent")
        if method == "thread/resume":
            require(params.get("excludeTurns") is True, identity, "resume fetched unbounded full transcript")
        if method == "turn/steer":
            require(bool(params.get("expectedTurnId")) and bool(params.get("input")), identity, "steer lost active-turn binding")
    elif identity == "providers.codex.list":
        require(len({row.id for row in result}) == len(result) and all(row.app == "codex" and row.id.startswith("external:codex:") for row in result), identity, "session identity duplicated/invalid")
        stamps = [row.updated_at for row in result]
        require(stamps == sorted(stamps, reverse=True), identity, "sessions not newest first")
        require(a["include_archived"] or not any(row.archived for row in result), identity, "default list leaked archived chats")
        require(all(not row.archived or not row.capabilities.continue_session for row in result), identity, "archived chat advertises continuation")
    elif identity == "providers.codex.page":
        seqs = [item.seq for item in result.items]
        require(seqs == sorted(seqs) and len(set(seqs)) == len(seqs) and len({item.id for item in result.items}) == len(result.items), identity, "page order/identity duplicated")
        require(a["before_seq"] is None or all(seq < a["before_seq"] for seq in seqs), identity, "earlier page overlaps cutoff")
        thread_id = a["self"]._thread_id(a["session_id"])
        if not a["self"]._run_for(thread_id):
            require(len(result.items) <= max(1, min(int(a["limit"] or 200), 200)), identity, "persisted page exceeded bound")
        require(result.session.id == a["session_id"] and all(item.at for item in result.items), identity, "read changed session or invented empty timestamp")
    elif identity == "providers.codex.media":
        require(isinstance(result[0], bytes) and result[1].startswith("image/") and bool(result[2]), identity, "media is not a named image")
    elif identity == "providers.codex.options":
        require(len({row["id"] for row in result["models"]}) == len(result["models"]), identity, "models duplicated")
        require([row["id"] for row in result["permissionModes"]] == ["ask", "auto", "full"] and set(result["auth"]) == {"kind", "label"}, identity, "permission/auth public projection changed")
        require(all(len(value) <= 500 for value in result.get("errors", {}).values()), identity, "failed section exposed unbounded diagnostic")
    elif identity == "providers.codex.login":
        require(result["state"] in {"signed-in", "code"} and not any(key in result for key in ("loginId", "token", "email")), identity, "login disclosed private response")
        if result["state"] == "code":
            require(result["verificationUrl"].startswith("https://") and bool(result["userCode"]) and result["method"] == "device-code", identity, "login code not user navigable")
    elif identity == "providers.codex.available":
        from .connected_sessions.codex_rpc import resolve_command
        require(result[0] is bool(resolve_command(a["self"]._command)) and (result[1] is None) is result[0], identity, "CLI availability disagrees with command resolution")
    elif identity == "providers.codex.thread":
        require(isinstance(result, dict) and str(result.get("id") or "") == a["thread_id"], identity, "thread lookup silently changed identity")
    elif identity == "providers.codex.writer":
        require(result is None or result["owner"] in {"app", "cli"}, identity, "foreign owner is not provider app/CLI")
    elif identity == "providers.codex.lock":
        require(result is None or result is True or result is False, identity, "OS ownership observation is neither locked, released nor unknown")
    elif identity == "providers.codex.summary":
        thread, adapter = a["thread"], a["self"]
        require(result.id == adapter._sid(str(thread["id"])) and result.app == "codex" and result.model == (thread.get("model") or None) and result.git_branch == ((thread.get("gitInfo") or {}).get("branch") or None) and result.host_device_id == adapter._device()["deviceId"] and result.archived is a["archived"], identity, "summary metadata differs from provider/device observation")
        if result.live_owner in {"app", "cli"}:
            require(not any((result.capabilities.continue_session, result.capabilities.compact, result.capabilities.goal, result.capabilities.steer, result.capabilities.stop)), identity, "foreign writer advertises competing controls")
    elif identity == "providers.codex.live":
        require(all(value[0] in {"working", "waiting_input", "waiting_approval"} and value[1] in {"neyvia", "app", "cli"} for value in result.values()), identity, "live projection invented owner/state")
    elif identity == "providers.codex.answer":
        run = a["self"]._runs.get(a["run_id"])
        require(run is None or a["request_id"] not in run.pending, identity, "answer did not consume pending request")
    elif identity == "providers.codex.goal":
        require(result is None or set(result) == {"text", "state", "tokenBudget", "tokensUsed", "timeUsedSeconds", "updatedAt"}, identity, "goal leaked private wire fields")
        require(a["action"] != "clear" or result is None, identity, "clear retained goal")
        if a["action"] == "set" and result:
            require(result["text"] == str(a["text"] or "").strip(), identity, "objective changed")
    elif identity == "providers.codex.plugin_login":
        require(isinstance(result.get("ok"), bool) and "token" not in result and "email" not in result, identity, "plugin login returned private fields")
        require(result.get("authUrl") is None or result["authUrl"].startswith("https://"), identity, "plugin login URL is not HTTPS")
    elif identity in {"providers.claude.lifecycle", "providers.codex.lifecycle"}:
        events = a["_events"]
        states = [event for event in events if event.get("type") == "run.state"]
        require(bool(states) and states[-1]["state"] in {"completed", "failed", "interrupted"}, identity, "turn returned without a terminal receipt")
        require(all(event["runId"] == a["run_id"] for event in states), identity, "event run ID differs from requested run")
        if identity == "providers.claude.lifecycle":
            require(all(event["sessionId"] == result for event in states), identity, "Claude resumed into a different identity")
        else:
            require(all(event["sessionId"] == result for event in states), identity, "Codex returned a different session from its events")
    elif identity == "providers.claude.page":
        page = result
        seqs = [item.seq for item in page.items]
        require(seqs == sorted(seqs) and len({item.id for item in page.items}) == len(page.items), identity, "page order or duplicate identity invalid")
        require(a["before_seq"] is None or all(seq < a["before_seq"] for seq in seqs), identity, "earlier page overlaps cutoff")
        require(all(item.kind != "tool" or item.data.get("category") is not None for item in page.items), identity, "tool has no family")
    elif identity == "providers.claude.summary":
        index = a["index"]
        require(result.title == index.title and result.cwd == index.cwd and result.model == index.model and result.git_branch == index.git_branch, identity, "summary invented transcript fields")
    elif identity == "providers.claude.context":
        require(result.used_tokens == a["index"].used and result.window_tokens == a["self"]._windows.get(a["index"].model or ""), identity, "context differs from actual usage/window observation")
        require(result.auto_compact_tokens == a["self"]._settings().get("autoCompactWindow"), identity, "auto compaction threshold not settings-derived")
    elif identity == "providers.claude.sequence":
        require(result == (a["offset"] * 64 | min(a["sub"], 63)), identity, "byte offset/block slot changed")
    elif identity == "providers.claude.store_page":
        items, earlier, cursor = result
        require(isinstance(cursor, str) and bool(cursor) and isinstance(earlier, bool), identity, "page cursor/frontier invalid")
        require(len(items) <= max(1, min(int(a["limit"] or 200), 200)), identity, "page exceeded item limit")
        seqs = [item.seq for item in items]
        require(seqs == sorted(seqs) and (a["before_seq"] is None or all(seq < a["before_seq"] for seq in seqs)), identity, "tail/earlier ordering invalid")
    elif identity == "providers.claude.media":
        if result is not None:
            require(isinstance(result[0], bytes) and result[1] in {"image/png", "image/jpeg", "image/webp", "image/gif"}, identity, "media result is not an allowed local image")
    elif identity == "providers.claude.read_bytes":
        require(isinstance(result, bytes) and len(result) <= max(0, a["end"] - a["start"]), identity, "reader exceeded requested byte range")
    elif identity == "providers.claude.title_priority":
        index = a["self"]
        expected = next((value for value in (index.custom_title, index.summary_title, index.ai_title, index.first_prompt) if value), "Untitled session")
        require(result == expected, identity, "title precedence changed")
    elif identity == "providers.claude.live":
        require(result is None or isinstance(result, list) and all(isinstance(row, dict) for row in result), identity, "CLI liveness is neither observed rows nor unknown")
        adapter = a["self"]
        stamp, cached = adapter._agents_cache
        previous_stamp, previous_rows = a["_previous_cache"]
        require(cached is result and stamp >= previous_stamp, identity, "liveness result not current cache projection")
        if a["force"]:
            require(stamp > previous_stamp, identity, "send-time owner check reused stale observation")
        elif stamp == previous_stamp:
            age = time.monotonic() - stamp
            require(age < adapter.agents_ttl + .1 or adapter._agents_signature is not None and age < 30.1, identity, "liveness reuse exceeded freshness limits")
    elif identity == "providers.terminal.images":
        import base64
        lines = [line.removeprefix("Attached image: ") for line in result.splitlines() if line.startswith("Attached image: ")]
        require(len(lines) == len(a["images"]), identity, "image paths missing")
        require(all(Path(path).read_bytes() == base64.b64decode(image["data"], validate=True) for path, image in zip(lines, a["images"])), identity, "saved image bytes differ")
    elif identity == "providers.terminal.compact":
        run, item = a["self"], a["item"]
        if run._stop_at is not None and a["_previous_stop"] is None:
            from .connected_sessions.claude_terminal import _since
            require(run._local_command and _since(item.at, run._began_at) and (item.kind == "compaction" and item.data.get("state") == "completed" or item.kind == "notice" and str(item.data.get("text") or "").strip() and not str(item.data.get("text")).startswith("/")), identity, "local command stopped on stale or echo item")
    elif identity == "providers.terminal.answer":
        run = a["self"]
        require(a["_pending_before"] is not None and a["request_id"] not in run._pending, identity, "pending terminal decision was not consumed exactly once")
        if a["_pending_before"].tool_name == "ClaudeFolderTrust":
            require(not run._screen and (a["response"].get("decision") == "approve" or run._interrupt_requested), identity, "trust screen was not consumed or decline did not interrupt")
    elif identity == "providers.claude.options":
        require(len({row["id"] for row in result["models"]}) == len(result["models"]), identity, "model IDs duplicated")
        require(set(result["auth"]) == {"kind", "label"} and all(row.get("scope") in {"user", "project"} for row in result["skills"]), identity, "private account fields or unknown skill scope exposed")
        require(all(row["state"] in {"connected", "needs_auth", "failed"} for row in result["mcpServers"]), identity, "unknown MCP status projected")
        require("env" not in result and "apiKeyHelper" not in result, identity, "private settings included in options")
    elif identity == "providers.claude.login":
        require(a["self"]._proc is None and str(a["code"] or "").strip() not in result and len(result) <= 160, identity, "sign-in process or pasted code retained in reply")


def check_goal_note(method, params, previous, expected, emit):
    identity = "providers.codex.goal_notes"
    clear = method == "thread/goal/cleared"
    if expected and clear != (expected == "clear"):
        desired = False
    elif clear:
        desired = previous is not None or expected == "clear"
    else:
        goal = params.get("goal") or {}
        changed = previous is not None and (previous.get("objective"), previous.get("status")) != (goal.get("objective"), goal.get("status"))
        desired = expected == "set" or changed
    require(emit is desired, identity, "counter/resume snapshot became a receipt or intended change was dropped")


def check_event(provider, event):
    identity = "providers." + provider + ".events"
    kind = event.get("type")
    if kind == "run.state":
        require(event["state"] in {"queued", "running", "waiting_input", "waiting_approval", "completed", "interrupted", "failed"} and bool(event.get("runId")), identity, "unknown run state")
        require(event["state"] in {"waiting_input", "waiting_approval"} or event.get("pendingRequest") is None, identity, "pending request outside waiting state")
    if kind in {"item.added", "item.updated"}:
        item = event["item"]
        require(bool(item["id"]) and isinstance(item["seq"], int) and item["seq"] >= 0 and isinstance(item["data"], dict), identity, "item identity/sequence/data invalid")
    if kind == "item.delta":
        require(bool(event.get("itemId")) and isinstance(event.get("textDelta"), str), identity, "delta has no target or text")


def check_process(options):
    identity = "providers.process.hidden"
    require(options.get("stdin") == subprocess.PIPE and options.get("stdout") == subprocess.PIPE and options.get("stderr") == subprocess.PIPE, identity, "provider stdio no longer piped")
    if os.name == "nt":
        require(options["creationflags"] & subprocess.CREATE_NO_WINDOW and options["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP and options["startupinfo"].wShowWindow == 0, identity, "provider process is visible or not isolated")


def self_check(root):
    import uuid
    started = time.perf_counter()
    scratch = Path(root).resolve() / "a-providers" / uuid.uuid4().hex
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    done = subprocess.run([sys.executable, "-m", __name__, "--scratch", str(scratch)], capture_output=True, text=True, encoding="utf-8", env=env, timeout=240, **hidden_windows_subprocess_kwargs())
    if done.returncode:
        raise RuntimeError("Provider scratch procedure failed: " + done.stderr[-5000:])
    receipt = json.loads(done.stdout)
    receipt["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
    return receipt


def _helpers(root):
    from .connected_sessions import claude_items as ci, claude_stream as cs, claude_terminal as terminal, claude_transcript as ct
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.model import TurnOptions
    from .external_chat_inventory import _row
    identities = set()
    checks = []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    host = {"deviceId": "proofprovider01", "deviceName": "Scratch PC", "kind": "local"}
    path = root / "identity.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    for sid in ("proof-chat", "odd chat/encoded"):
        gate("providers.claude.identity", ci.session_identity(sid, host) == _row("claude-code", sid, "Scratch", path, host)["id"], "inventory and adapter identity agree")
    for cwd, expected in ((r"C:\Projects\scratch\proof\one", True), (r"D:\evidence\run", True), (r"C:\tmp\other", True), (r"C:\Projects\scratch", False), (None, False), (r"C:\Projects\scratch\src", False), (r"C:\sandbox\.agent_control\owned", True), (r"C:\sandbox\.sandbox-scratch\run", True), (r"C:\sandbox\harness-comparison\run", True)):
        gate("providers.claude.origin", ci.is_harness_cwd(cwd, [r"C:\tmp"]) is expected, "path origin uses explicit scratch boundaries")
    tools = [("Bash", {"command": "\n git status\nls"}, "git status", "command"), ("Read", {"file_path": r"C:\a\notes.md"}, "notes.md", "read"), ("Edit", {"file_path": "/x/app.py"}, "app.py", "edit"), ("Grep", {"pattern": "foo.*bar"}, "foo.*bar", "search"), ("Glob", {"pattern": "**/*.py"}, "**/*.py", "search"), ("WebFetch", {"url": "https://docs.example.invalid/a"}, "docs.example.invalid", "web"), ("mcp__github__list_issues", {}, "github · list_issues", "mcp"), ("Agent", {"description": "Inspect owned folder"}, "Inspect owned folder", "agent"), ("Unknown", {}, "Unknown", "other")]
    for name, data, title, category in tools:
        gate("providers.claude.category", ci.tool_category(name) == category, "tool family mapped")
        gate("providers.claude.title", ci.tool_title(name, data) == title, "tool title uses command/file/pattern/host/description")
    markers = [("<system-reminder>internal</system-reminder>", ("hidden", "", "info")), ("<system-reminder>internal</system-reminder>\nfix this", ("prose", "fix this", "info")), ("<command-name>/model</command-name><command-args>opus</command-args>", ("notice", "/model opus", "info")), ("<local-command-stdout>Compacted </local-command-stdout>", ("hidden", "", "info")), ("<command-name>/compact</command-name><command-args></command-args>", ("hidden", "", "info")), ("<local-command-stdout>Not enough messages to compact.</local-command-stdout>", ("notice", "Not enough messages to compact.", "info")), ("<local-command-stdout></local-command-stdout>", ("hidden", "", "info")), ("<task-notification><status>failed</status><summary>Build failed</summary></task-notification>", ("notice", "Helper reported · Background task\nBuild failed", "error")), ("[Request interrupted by user]", ("notice", "Interrupted", "info"))]
    for raw, expected in markers:
        gate("providers.claude.classify", ci.classify_user_text(raw) == expected, "internal/command/task markers retain semantic kind")
    cap = ci.TOOL_OUTPUT_LIMIT
    for raw in ("short", "HEAD" + "middle" * cap + "TAIL", "🐱" * cap):
        shown, truncated, total = ci.bound_output(raw)
        gate("providers.claude.output", total == len(raw.encode()) and (truncated is (total > cap)) and (not truncated or "bytes omitted" in shown), "current 256KiB transparency head/tail bound")
    for option in (TurnOptions(), TurnOptions(model="sonnet", effort="high", permission_mode="acceptEdits"), TurnOptions(permission_mode="default"), TurnOptions(permission_mode="bypassPermissions")):
        for sid in (None, "existing-chat"):
            argv = cs.build_argv([sys.executable, "peer.py"], sid, option)
            gate("providers.claude.argv", ("--resume" in argv) is bool(sid), "new/resumed print argv checked")
        for resumed in (False, True):
            argv = terminal.terminal_argv([sys.executable, "peer.py"], "terminal-chat", resumed, option, root / "settings.json", "-rf literal message")
            gate("providers.terminal.argv", argv[-2:] == ["--", "-rf literal message"] and "-p" not in argv, "interactive message is last literal argument")
    branch = terminal.terminal_argv(["claude"], "new-chat", False, TurnOptions(fork_from="original-chat"), root / "settings.json", "continue")
    gate("providers.terminal.argv", branch[branch.index("--resume") + 1] == "original-chat" and branch[branch.index("--session-id") + 1] == "new-chat" and "--fork-session" in branch, "branch resumes original into explicitly new ID")
    for field in ("model", "effort", "permission_mode"):
        try:
            cs.build_argv(["claude"], None, TurnOptions(**{field: "--inject\ninvalid"}))
        except cs.ClaudeSessionError as error:
            gate("providers.claude.argv", error.code == "invalid_option", "invalid options refused before process launch")
        else:
            require(False, "providers.claude.argv", "invalid option accepted")
    gate("providers.terminal.screen", terminal.screen_text("\x1b[2JDo\x1b[1Cyou\x1b[1Ctrust\x1b[1Cthis\x1b[1Cfolder?\x1b[0m") == "Do you trust this folder?", "cursor movements preserved as spaces")
    saved = {key: os.environ.get(key) for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_TOKEN")}
    try:
        os.environ["CLAUDE_CODE_SESSION_ID"] = "outer-scratch-session"
        os.environ["CLAUDE_CODE_MESSAGING_TOKEN"] = "synthetic-scratch-marker"
        env = cs.child_env()
        gate("providers.claude.environment", not any(key in env for key in saved), "outer session markers removed from actual child environment")
        child = cs.start_process([sys.executable, "-c", "print('scratch process')"], str(root), env)
        stdout, stderr = child.communicate(timeout=10)
        gate("providers.process.hidden", child.returncode == 0 and stdout.strip() == b"scratch process" and stderr == b"", "real hidden piped child process completed")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    agg = ct.AgentAggregate()
    usage = {"input_tokens": 2, "cache_read_input_tokens": 600000, "cache_creation_input_tokens": 50, "output_tokens": 40}
    for block in ({"type": "thinking", "thinking": ""}, {"type": "text", "text": "ok"}, {"type": "tool_use", "id": "scratch_tool", "name": "Bash", "input": {}}):
        agg.feed({"type": "assistant", "timestamp": "2026-09-29T10:00:00Z", "message": {"id": "message-one", "model": "scratch-model", "content": [block], "usage": usage}})
    agg.feed({"type": "assistant", "timestamp": "2026-09-29T10:00:05Z", "message": {"id": "message-two", "content": [{"type": "text", "text": "done"}], "usage": {**usage, "output_tokens": 7}}})
    summary = agg.summarize({})
    gate("providers.claude.aggregate", summary["outputTokens"] == 47 and summary["inputTokens"] == 600052, "same message repeated blocks counted once and latest context retained")
    adapter = ClaudeAdapter(config_dir=root / "claude-config", cli_path=[sys.executable, "peer.py"], host=host)
    for installed in (False, True):
        for owner in (None, "app", "cli"):
            for status in ("idle", "working", "unknown"):
                caps = adapter._capabilities(owner, status, installed=installed)
                expected = installed and not (owner in {"app", "cli"} and (status != "idle" or owner == "cli"))
                gate("providers.claude.capabilities", caps.continue_session is expected and caps.compact is expected and caps.new_session is installed, "idle app sharing differs from competing/background writer")
    idle, busy, free = adapter._capabilities("app", "idle", installed=True), adapter._capabilities("app", "working", installed=True), adapter._capabilities(None, "idle", installed=True)
    fork = cs.build_argv(["claude"], None, TurnOptions(fork_from="original"))
    gate("providers.claude.capabilities", idle.fork and not idle.steer and idle.reason is None and busy.fork and "working on this chat" in busy.reason and free.steer and not free.fork and "--fork-session" in fork and fork[fork.index("--resume")+1] == "original" and "--fork-session" not in cs.build_argv(["claude"], "existing", TurnOptions(fork_from="ignored")), "app idle/busy fork capability and actual new/resumed branch argv preserve explicit identity")
    for kind in ("subscription", "gateway", "api-key", "signed-out", "unknown"):
        transports = adapter._transports({"kind": kind, "label": "synthetic setup"})
        gate("providers.claude.transports", [row["id"] for row in transports] == ["print", "terminal"] and bool(transports[1]["risk"]), "billing disclosure and opt-in terminal labels retained")
    outer_gateway = os.environ.pop("ANTHROPIC_BASE_URL", None)
    try:
        for n, (status, gateway, kind) in enumerate((({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}, None, "subscription"), ({"loggedIn": True, "authMethod": "none", "apiKeySource": "apiKeyHelper"}, proof_text("http://127.0.0.1:48463"), "gateway"), ({"loggedIn": True, "authMethod": "none", "apiKeySource": "ANTHROPIC_API_KEY"}, None, "api-key"), ({"loggedIn": False, "authMethod": "none"}, None, "signed-out"))):
            config = root / f"billing-{n}"
            config.mkdir()
            if gateway:
                (config / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": gateway}}), encoding="utf-8")
            public_status = json.dumps(status)
            billing_peer = config / "billing-peer.py"
            billing_peer.write_text("print("+repr(public_status)+")", encoding="utf-8")
            billing = ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(billing_peer)])
            auth = billing.auth(force=True)
            transports = billing._transports(auth)
            gate("providers.claude.auth", auth["kind"] == kind and (kind != "subscription" or auth["label"] == "your Claude Max plan") and (kind != "gateway" or proof_text("127.0.0.1:48463") in auth["label"]) and (transports[0]["note"] is None) is (kind == "subscription"), "actual CLI status and scoped gateway settings decide current public billing label/note")
    finally:
        if outer_gateway is not None:
            os.environ["ANTHROPIC_BASE_URL"] = outer_gateway
    return identities, checks


class _Events:
    """Observer retained by a single confined procedure; provider owns all events."""
    def __init__(self):
        self.rows = []
        self.condition = threading.Condition()

    def __call__(self, event):
        with self.condition:
            self.rows.append(event)
            self.condition.notify_all()

    def wait(self, predicate, seconds=12):
        end = time.monotonic() + seconds
        with self.condition:
            while True:
                found = next((row for row in self.rows if predicate(row)), None)
                if found is not None:
                    return found
                remaining = end - time.monotonic()
                if remaining <= 0 and hasattr(self, "cancel"):
                    self.cancel()
                require(remaining > 0, "providers.protocol.deadline", "finite peer did not reach expected state")
                self.condition.wait(remaining)

    def states(self):
        return [row["state"] for row in self.rows if row["type"] == "run.state"]

    def items(self):
        import copy
        latest = {}
        for row in self.rows:
            if row["type"] in {"item.added", "item.updated"}:
                latest[row["item"]["id"]] = copy.deepcopy(row["item"])
            elif row["type"] == "item.delta" and row["itemId"] in latest:
                item = latest[row["itemId"]]
                key = "summary" if item["kind"] == "reasoning" else "text"
                item["data"][key] = (item["data"].get(key) or "") + row["textDelta"]
        return list(latest.values())


def _start(adapter, session, text, *, options=None, cwd=None, name="scratch-run"):
    from .connected_sessions.model import TurnOptions
    events, outcome = _Events(), {}
    def run():
        try:
            outcome["session"] = adapter.start_turn(session, text, options or TurnOptions(), cwd=cwd, run_id=name, emit=events)
        except BaseException as error:
            outcome["error"] = error
    worker = threading.Thread(target=run, daemon=True)
    events.cancel = lambda: adapter.interrupt(name)
    worker.start()
    def finish():
        worker.join(18)
        missed = worker.is_alive()
        if missed:
            adapter.interrupt(name)
            worker.join(6)
        require(not missed, "providers.protocol.deadline", "finite peer turn did not return")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["session"]
    return events, outcome, finish


def _claude_protocol(root):
    import base64
    from .connected_sessions.claude import ClaudeAdapter, ClaudeSessionError
    from .connected_sessions import claude_stream
    from .connected_sessions.model import TurnOptions
    peer = Path(__file__).resolve().parents[2] / "tests/fixtures/fake_claude_cli.py"
    # The finite peer stays resident until stdin EOF; shorten its post-result
    # process grace in this isolated child only, without changing run watchdogs.
    claude_stream.ClaudeRun.__init__.__kwdefaults__["shutdown_grace"] = .05
    folder, config = root / "claude-work", root / "claude-config"
    folder.mkdir()
    project = config / "projects" / "scratch"
    project.mkdir(parents=True)
    live = root / "claude-live.json"
    live.write_text("[]", encoding="utf-8")
    log = root / "claude-protocol.jsonl"
    signed = root / "scratch-sign-in.marker"
    host = {"deviceId": "proofprovider01", "deviceName": "Scratch PC", "kind": "local"}
    def adapter(**extra):
        return ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(peer)], host=host, agents_ttl=0, context_probe=extra.pop("context_probe", False), extra_env={"FAKE_CLAUDE_LOG": str(log), "FAKE_CLAUDE_AGENTS": str(live), "FAKE_CLAUDE_SIGNED_IN": str(signed), "FAKE_CLAUDE_FORK_ID": "unexpected-copy", **extra.pop("peer_env", {})}, **extra)
    checks, identities = [], set()
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    def records():
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    def final(events, state):
        gate("providers.claude.lifecycle", events.states()[-1] == state, "real CLI protocol reached " + state)
        gate("providers.claude.events", all(row.get("sessionId") for row in events.rows if row["type"] in {"run.state", "item.added", "item.updated"}), "events carry actual session identity")
    first = adapter(context_probe=True)
    events, _, finish = _start(first, None, "hello", options=TurnOptions(model="haiku", effort="low", permission_mode="acceptEdits"), cwd=str(folder), name="claude-new")
    sid = finish()
    final(events, "completed")
    gate("providers.claude.argv", bool(sid) and any(item["kind"] == "assistant" and item["data"].get("text") == "Hello there" for item in events.items()), "new session ID learned from actual init and assistant stream assembled")
    context = [event["context"] for event in events.rows if event["type"] == "context.updated"][-1]
    gate("providers.claude.events", (context["used_tokens"], context["window_tokens"], context["auto_compact_tokens"]) == (1000, 200000, 167000), "actual CLI usage and context probe report context/window/threshold without guessing")
    # A persisted transcript makes resume and ownership checks use actual files.
    transcript = project / (sid + ".jsonl")
    transcript.write_text(json.dumps({"type": "user", "uuid": "persisted-user", "sessionId": sid, "cwd": str(folder), "timestamp": "2026-09-29T10:00:00Z", "message": {"role": "user", "content": "prior question"}}) + "\n", encoding="utf-8")
    events, _, finish = _start(first, sid, "continue", options=TurnOptions(model="sonnet", effort="high", permission_mode="acceptEdits"), cwd=None, name="claude-resume")
    gate("providers.claude.lifecycle", finish() == sid, "resumed session is the same ID")
    final(events, "completed")
    turn = [row for row in records() if row["kind"] == "start" and "-p" in row["argv"]][-1]
    gate("providers.claude.argv", turn["argv"][turn["argv"].index("--resume") + 1] == sid and turn["cwd"] == str(folder) and turn["argv"][turn["argv"].index("--model") + 1] == "sonnet", "selected resume/options/folder reached real child argv")
    for scenario in ("think", "compact", "image", "agent", "fail"):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nscratch-image").decode()
        events, _, finish = _start(first, sid, "SCN:" + scenario, options=TurnOptions(images=[{"mime": "image/png", "data": png}]) if scenario == "image" else None, cwd=str(folder), name="claude-" + scenario)
        finish()
        final(events, "failed" if scenario == "fail" else "completed")
        items = events.items()
        if scenario == "think":
            shown = [item["data"] for item in items if item["kind"] == "reasoning"]
            gate("providers.claude.events", any("Weighing options." in str(item) for item in shown), "actual thinking deltas reached visible reasoning")
        elif scenario == "compact":
            compact = [item["data"] for item in items if item["kind"] == "compaction"]
            gate("providers.claude.events", bool(compact) and compact[-1]["state"] == "completed" and compact[-1]["beforeTokens"] == 1725 and compact[-1]["afterTokens"] == 811, "compaction stream/boundary counts preserved")
        elif scenario == "image":
            user = next(item for item in items if item["kind"] == "user")
            image = user["data"]["attachments"][0]
            payload = first.read_media(sid, image["mediaRef"])
            gate("providers.claude.media", payload[0] == base64.b64decode(png) and payload[1] == "image/png", "base64 input became host-local media handle")
        elif scenario == "agent":
            agent = next(item["data"]["agent"] for item in items if item["kind"] == "tool" and item["data"].get("category") == "agent")
            gate("providers.claude.aggregate", agent["toolCount"] == 3 and agent["outputTokens"] == 77 and agent["inputTokens"] == 823 and agent["durationMs"] == 4200, "growing sub-agent stream preserves observed latest context and completion totals")
            counts = [event["item"]["data"]["agent"]["toolCount"] for event in events.rows if event["type"] == "item.updated" and event["item"]["id"] == "toolu_agent_1" and event["item"]["data"]["agent"]["toolCount"] is not None]
            # Each sub-agent tool use arrives ~1 s apart. A loaded host may deliver two at
            # once, so the exact intermediate values are timing, not behavior; what the
            # contract requires is a partial count shown live that then grows to the total.
            partial = [count for count in counts if 0 < count < 3]
            gate("providers.claude.aggregate", bool(counts) and counts == sorted(counts) and bool(partial) and counts[0] < counts[-1] == 3, "sub-agent tool count increases live before completion; observed counts=" + repr(counts))
        else:
            blob = json.dumps(events.rows)
            last = next(row for row in reversed(events.rows) if row["type"] == "run.state")
            gate("providers.claude.events", last["errorCode"] == "auth_failed" and "SECRET-STDERR" not in blob and "abc123" not in blob, "failure mapped to safe auth message without stderr")
    for decision in ("approve", "deny"):
        events, _, finish = _start(first, sid, "SCN:approve", cwd=str(folder), name="claude-decision-" + decision)
        waiting = events.wait(lambda row: row["type"] == "run.state" and row["state"] == "waiting_approval")
        request = waiting["pendingRequest"]
        gate("providers.claude.events", request["kind"] == "approval" and request["command"] == "echo proof > proof.txt", "approval exposes actual command before decision")
        if decision == "approve":
            try:
                first.answer("claude-decision-" + decision, request["requestId"], {"decision": "invented"})
            except ClaudeSessionError as error:
                gate("providers.claude.reply", error.code == "invalid_decision", "invalid decision retained pending request")
            try:
                first.answer("claude-decision-" + decision, "unknown-request", {"decision": "approve"})
            except ClaudeSessionError as error:
                gate("providers.claude.reply", error.code == "request_not_pending", "wrong request identity refused")
        first.answer("claude-decision-" + decision, request["requestId"], {"decision": decision})
        try:
            first.answer("claude-decision-" + decision, request["requestId"], {"decision": decision})
        except ClaudeSessionError as error:
            gate("providers.claude.reply", error.code in {"request_not_pending", "run_not_active"}, "request answered exactly once")
        else:
            require(False, "providers.claude.reply", "same request answered twice")
        finish()
        final(events, "completed")
        received = [row["msg"]["response"]["response"] for row in records() if row["kind"] == "stdin" and row["msg"].get("type") == "control_response" and row["msg"]["response"].get("request_id") == request["requestId"]][-1]
        gate("providers.claude.reply", received["behavior"] == ("allow" if decision == "approve" else "deny"), "actual stdio control reply follows person decision")
    events, _, finish = _start(first, sid, "SCN:ask", cwd=str(folder), name="claude-question")
    waiting = events.wait(lambda row: row["type"] == "run.state" and row["state"] == "waiting_input")
    request = waiting["pendingRequest"]
    first.answer("claude-question", request["requestId"], {"decision": "approve", "answers": {"q0": "Green"}})
    finish()
    final(events, "completed")
    gate("providers.claude.reply", next(item for item in events.items() if item["kind"] == "question")["data"]["answers"] == {"q0": "Green"}, "question input answer persisted in item")
    for scenario in ("long", "stuck", "silent"):
        runner = adapter(interrupt_grace=.2, idle_timeout=.5 if scenario == "silent" else 30, peer_env={"FAKE_CLAUDE_STUCK": "1"} if scenario == "stuck" else {})
        events, _, finish = _start(runner, sid, "SCN:" + scenario, cwd=str(folder), name="claude-stop-" + scenario)
        if scenario != "silent":
            events.wait(lambda row: row["type"] == "item.delta")
            if scenario == "long":
                runner.steer("claude-stop-long", "extra context")
                gate("providers.claude.events", any(item["data"].get("steer") for item in events.items()), "running turn accepts an actual user steer")
                try:
                    runner.start_turn(sid, "second competing send", TurnOptions(), cwd=str(folder), run_id="duplicate", emit=lambda row: None)
                except ClaudeSessionError as error:
                    gate("providers.claude.capabilities", error.code == "session_busy", "one own turn per persisted session")
            runner.interrupt("claude-stop-" + scenario)
        finish()
        final(events, "interrupted")
    for owner, expected in (({"sessionId": sid, "pid": 999999, "status": "busy", "kind": "foreground"}, "session_live_elsewhere"), ({"sessionId": sid, "pid": 999999, "status": "idle", "kind": "background"}, "session_live_elsewhere")):
        live.write_text(json.dumps([owner]), encoding="utf-8")
        try:
            first.preflight(sid)
        except ClaudeSessionError as error:
            gate("providers.claude.capabilities", error.code == expected and error.owner is not None, "foreign competing/background writer refused with owner details")
        else:
            require(False, "providers.claude.capabilities", "foreign writer accepted")
    live.write_text(json.dumps([{"sessionId": sid, "pid": 999999, "status": "idle", "kind": "foreground"}]), encoding="utf-8")
    first.preflight(sid)
    events, _, finish = _start(first, sid, "share idle desktop", cwd=str(folder), name="claude-idle-app")
    gate("providers.claude.lifecycle", finish() == sid, "idle desktop chat resumed in place")
    live.write_text("[]", encoding="utf-8")
    failing_live = adapter(peer_env={"FAKE_CLAUDE_AGENTS_FAIL": "1"})
    try:
        failing_live.preflight(sid)
    except ClaudeSessionError as error:
        gate("providers.claude.capabilities", error.code == "live_check_unavailable", "unknown writer liveness fails closed")
    for text in ("", "/clear", "/new", "/resume another", "x" * 100001):
        try:
            first.start_turn(sid, text, TurnOptions(), cwd=str(folder), run_id="refused-message", emit=lambda row: None)
        except ClaudeSessionError:
            gate("providers.claude.request", True, "session-leaving/empty/oversized message refused before stream launch")
        else:
            require(False, "providers.claude.argv", "invalid message accepted")
    auth = first.auth(force=True)
    gate("providers.claude.auth", auth["kind"] == "signed-out" and set(auth) == {"kind", "label"}, "real synthetic auth CLI response projects public billing only")
    login = first.sign_in()
    gate("providers.claude.auth", login["state"] == "paste" and login["verificationUrl"].startswith("https://claude.com/"), "finite CLI login yields public URL")
    for code, expected in (("not a code", "invalid_code"), ("wrong-code#state-123", "sign_in_failed"), ("good-code#state-123", "sign_in_expired")):
        try:
            first.finish_sign_in(code)
        except ClaudeSessionError as error:
            gate("providers.claude.login", error.code == expected and code not in str(error), "sign-in validation/failure/expiration never echoes pasted code")
        else:
            require(False, "providers.claude.login", "wrong/expired sign-in accepted")
    first.sign_in()
    done = first.finish_sign_in("good-code#state-123")
    gate("providers.claude.auth", done["state"] == "signed-in" and first.sign_in()["state"] == "signed-in", "synthetic code submitted once and signed-in login becomes no-op")
    gate("providers.claude.login", first._login._proc is None, "finished login closes one-time process")
    pending_runner = adapter(idle_timeout=1)
    events, _, finish = _start(pending_runner, sid, "SCN:approve", cwd=str(folder), name="claude-pending-watchdog")
    waiting = events.wait(lambda event: event["type"] == "run.state" and event["state"] == "waiting_approval")
    time.sleep(1.5)
    gate("providers.claude.lifecycle", events.states()[-1] == "waiting_approval", "person prompt outlives idle budget without being killed")
    pending_runner.answer("claude-pending-watchdog", waiting["pendingRequest"]["requestId"], {"decision": "approve"})
    finish()
    final(events, "completed")
    # Many small gaps (0.1 s, a fifteenth of the 1.5 s budget) that together run well past the
    # budget. Load can delay a tick by an order of magnitude and the run still must not be killed
    # for idleness; the assertion is relative to the budget rather than a fixed wall-clock figure.
    paced = adapter(idle_timeout=1.5, peer_env={"FAKE_CLAUDE_PACE": "0.1", "FAKE_CLAUDE_PACED_TICKS": "40"})
    started = time.monotonic()
    events, _, finish = _start(paced, sid, "SCN:paced", cwd=str(folder), name="claude-paced")
    finish()
    gate("providers.claude.lifecycle", events.states()[-1] == "completed" and time.monotonic() - started > 1.5 * 1.5, "healthy output repeatedly outlives idle budget without overall timeout")
    events, _, finish = _start(first, sid, "SCN:fork", cwd=str(folder), name="claude-refuse-copy")
    finish()
    final(events, "failed")
    last = [event for event in events.rows if event["type"] == "run.state"][-1]
    gate("providers.claude.lifecycle", last["errorCode"] == "session_forked", "unexpected provider fork stopped instead of silently continuing copy")
    return identities, checks


class _Transcript:
    """Produce append-only records in scratch; adapters perform all interpretation."""
    def __init__(self, path, sid, cwd):
        self.path, self.sid, self.cwd, self.ordinal, self.parent = path, sid, cwd, 0, None

    def record(self, kind, **fields):
        self.ordinal += 1
        uid = fields.pop("uuid", f"scratch-record-{self.ordinal}")
        result = {"type": kind, "uuid": uid, "parentUuid": self.parent, "sessionId": self.sid, "cwd": self.cwd, "gitBranch": "scratch-branch", "isSidechain": False, "timestamp": fields.pop("timestamp", f"2026-09-29T10:{self.ordinal // 60 % 60:02d}:{self.ordinal % 60:02d}Z"), **fields}
        self.parent = uid
        return result

    def user(self, text, **fields):
        return self.record("user", message={"role": "user", "content": text}, **fields)

    def assistant(self, blocks, mid="scratch-message", model="scratch-model", usage=None, **fields):
        return [self.record("assistant", apiBlockIndex=n, message={"id": mid, "role": "assistant", "model": model, "content": [block], "usage": usage or {"input_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5, "output_tokens": 3}}, **fields) for n, block in enumerate(blocks)]

    def result(self, tool, output, **fields):
        structured = fields.pop("structured", None)
        record = self.user([{"type": "tool_result", "tool_use_id": tool, "content": output, "is_error": fields.pop("is_error", False)}], **fields)
        if structured is not None:
            record["toolUseResult"] = structured
        return record

    def write(self, records, append=False):
        with self.path.open("a" if append else "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def _claude_transcripts(root):
    import base64
    from datetime import datetime, timedelta, timezone
    from .connected_sessions import claude_transcript as ct
    from .connected_sessions.claude import ClaudeAdapter
    peer = Path(__file__).resolve().parents[2] / "tests/fixtures/fake_claude_cli.py"
    config = root / "transcript-config"
    project = config / "projects" / "scratch"
    project.mkdir(parents=True)
    log, live = root / "transcript-cli.jsonl", root / "transcript-live.json"
    live.write_text("[]", encoding="utf-8")
    sid, host = "scratch-transcript", {"deviceId": "proofprovider01", "deviceName": "Scratch PC", "kind": "local"}
    transcript = _Transcript(project / (sid + ".jsonl"), sid, str(root))
    def adapter(**extra):
        return ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(peer)], host=host, agents_ttl=0, context_probe=False, extra_env={"FAKE_CLAUDE_LOG": str(log), "FAKE_CLAUDE_AGENTS": str(live)}, **extra)
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    image = b"\x89PNG\r\n\x1a\nscratch-image"
    image_block = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(image).decode()}}
    records = [transcript.user("<system-reminder>internal</system-reminder>", isMeta=True), transcript.user([{"type": "text", "text": "Repair scratch login"}, image_block]), transcript.user("<command-name>/model</command-name><command-args>opus</command-args>"), *transcript.assistant([{"type": "thinking", "thinking": ""}, {"type": "text", "text": "Looking."}, {"type": "text", "text": "At the file."}, {"type": "tool_use", "id": "scratch-read", "name": "Read", "input": {"file_path": str(root / "login.py")}}]), transcript.result("scratch-read", "1\tcode\n"), *transcript.assistant([{"type": "tool_use", "id": "scratch-command", "name": "Bash", "input": {"command": "echo scratch\necho done"}}], mid="command-message"), transcript.result("scratch-command", "Exit code 1\nFAILED scratch", is_error=True), *transcript.assistant([{"type": "tool_use", "id": "scratch-mcp", "name": "mcp__github__get_pr", "input": {"n": 1}}], mid="mcp-message"), transcript.result("scratch-mcp", [{"type": "text", "text": "PR body"}]), *transcript.assistant([{"type": "tool_use", "id": "scratch-question", "name": "AskUserQuestion", "input": {"questions": [{"question": "Which color?", "header": "Color", "multiSelect": False, "options": [{"label": "Blue", "description": "b"}, {"label": "Green", "description": "g"}]}]}}], mid="question-message"), transcript.result("scratch-question", "answered", structured={"questions": [], "answers": {"Which color?": "Green"}}), transcript.record("system", subtype="compact_boundary", compactMetadata={"trigger": "auto", "preTokens": 900000}), transcript.user("<task-notification><status>completed</status><summary>Background done</summary></task-notification>"), *transcript.assistant([{"type": "text", "text": "All done."}], mid="done-message", usage={"input_tokens": 5, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 1, "output_tokens": 9})]
    transcript.write(records)
    reader = adapter()
    page = reader.read(sid)
    gate("providers.claude.page", [item.kind for item in page.items] == ["user", "notice", "reasoning", "assistant", "tool", "tool", "tool", "question", "compaction", "notice", "assistant"], "real rich transcript maps every item family and hides meta records")
    user, notice, reasoning, text, read, command, mcp, question, compact, task, done = page.items
    gate("providers.claude.page", user.data["text"] == "Repair scratch login" and notice.data["text"] == "/model opus" and text.data["text"] == "Looking.\n\nAt the file." and done.data["text"] == "All done.", "user markers and adjacent same-message text preserve content")
    gate("providers.claude.page", read.data["title"] == "login.py" and read.data["files"] == [str(root / "login.py")] and read.data["status"] == "ok" and command.data["exitCode"] == 1 and command.data["status"] == "error" and mcp.data["output"] == "PR body", "tool source/result retains file command status MCP output and exit code")
    gate("providers.claude.page", question.data["answered"] is True and question.data["answers"] == {"q0": "Green"} and compact.data["beforeTokens"] == 900000 and task.data["text"] == "Helper reported · Background task" and task.data["helper"] == "Background task" and task.data["report"] == "Background done" and task.data["level"] == "info", "question answer and compaction/task state persisted")
    gate("providers.claude.context", page.context.used_tokens == 46 and page.context.window_tokens is None and page.context.auto_compact_tokens is None, "context reflects final actual usage without guessed window")
    gate("providers.claude.summary", page.session.title == "Repair scratch login" and page.session.cwd == str(root) and page.session.git_branch == "scratch-branch", "list/read summary reflects recorded folder branch first prompt")
    token = user.data["attachments"][0]["mediaRef"]
    gate("providers.claude.media", reader.read_media(sid, token)[:2] == (image, "image/png") and adapter().read_media(sid, token)[0] == image and reader.read_media(sid, "0" * 64) is None and reader.read_media(sid, "../outside") is None, "image handle resolves after adapter restart and invalid references remain absent")
    transcript.write([transcript.record("summary", summary="Summary title")], append=True)
    gate("providers.claude.title_priority", reader.list_sessions()[0].title == "Summary title", "summary overrides first prompt")
    transcript.write([transcript.record("custom-title", customTitle="Custom title")], append=True)
    gate("providers.claude.title_priority", reader.list_sessions()[0].title == "Custom title", "custom title overrides summary")
    live.write_text(json.dumps([{"sessionId": sid, "pid": 999999, "status": "busy", "kind": "foreground"}]), encoding="utf-8")
    row = reader.list_sessions()[0]
    gate("providers.claude.capabilities", row.status == "working" and row.live_owner == "app" and row.capabilities.continue_session is False and row.origin == "neyvia-harness", "real agents JSON status controls list ownership capabilities and scratch origin")
    live.write_text("[]", encoding="utf-8")
    # Append an incomplete JSON line, then its completion, through real file IO.
    initial = reader.read(sid)
    record = json.dumps(transcript.assistant([{"type": "text", "text": "Complete appended answer"}], mid="partial-message")[0], separators=(",", ":"))
    with transcript.path.open("ab") as handle:
        handle.write(record[:40].encode())
    gate("providers.claude.read_bytes", reader.read(sid, cursor=initial.cursor).items == [], "partial last record produces no premature item")
    with transcript.path.open("ab") as handle:
        handle.write((record[40:] + "\n").encode())
    gate("providers.claude.page", [item.data["text"] for item in reader.read(sid, cursor=initial.cursor).items] == ["Complete appended answer"], "completed bytes become one incremental item")
    # Current payload limit is deliberately larger than the former 8KiB limit.
    huge = "HEAD" + "L" * 400000 + "TAIL"
    transcript.write([transcript.user("run output"), *transcript.assistant([{"type": "tool_use", "id": "huge-tool", "name": "Bash", "input": {"command": "owned-output"}}], mid="huge-message"), transcript.result("huge-tool", huge)])
    fresh = adapter()
    tool = next(item for item in fresh.read(sid).items if item.kind == "tool")
    gate("providers.claude.output", tool.data["outputTruncated"] and tool.data["outputBytes"] == len(huge) and fresh.tool_output(sid, "huge-tool") == huge, "bounded page output retains full source on demand")
    # Capture reads as a receipt of real production IO; never substitute data.
    ranges, original = [], ct.read_bytes
    def observed_read(path, start, end):
        ranges.append(end - start)
        return original(path, start, end)
    ct.read_bytes = observed_read
    try:
        before = transcript.path.stat().st_size
        cursor = fresh.read(sid).cursor
        ranges.clear()
        transcript.write([transcript.result("huge-tool", "finished\n"), *transcript.assistant([{"type": "text", "text": "Incremental done"}], mid="incremental-message")], append=True)
        appended = transcript.path.stat().st_size - before
        delta = fresh.read(sid, cursor=cursor)
        gate("providers.claude.read_bytes", sum(ranges) <= 2 * (appended + 256) and [(item.id, item.kind) for item in delta.items] == [("huge-tool", "tool"), ("incremental-message:0", "assistant")], "appended result updates original item using only appended ranges/head checks")
        gate("providers.claude.page", delta.items[0].data["status"] == "ok" and delta.items[0].data["output"] == "finished\n" and fresh.read(sid, cursor=delta.cursor).items == [], "incremental cursor prevents repeat delivery")
    finally:
        ct.read_bytes = original
    # A >3MiB transcript forces real head/tail/middle-title and earlier paging.
    records = [transcript.user("First large prompt"), transcript.record("custom-title", customTitle="Middle custom title")]
    for n in range(1800):
        records += [transcript.user(f"question {n} " + "pad " * 300), *transcript.assistant([{"type": "text", "text": f"answer {n}"}], mid=f"large-message-{n}")]
    transcript.write(records)
    ct.read_bytes = observed_read
    try:
        ranges.clear()
        store = ct.ItemStore(transcript.path, sid)
        items, earlier, cursor = store.page(cursor=None, before_seq=None, limit=100)
        gate("providers.claude.read_bytes", transcript.path.stat().st_size > 3 * 1024 * 1024 and len(items) == 100 and earlier and sum(ranges) < transcript.path.stat().st_size * .9, "first large page reads bounded actual tail")
        ranges.clear()
        store.page(cursor=cursor, before_seq=None, limit=100)
        gate("providers.claude.read_bytes", sum(ranges) <= 256, "unchanged tail checks only bounded head fingerprint")
        index = ct.SummaryIndex(transcript.path, sid)
        index.refresh()
        gate("providers.claude.title_priority", index.title == "Middle custom title" and index.cwd == str(root) and index.model == "scratch-model" and index.used == 115, "middle title discovered outside initial head and tail")
        ranges.clear()
        transcript.write([transcript.record("custom-title", customTitle="Renamed appended"), *transcript.assistant([{"type": "text", "text": "later"}], mid="later-message", model="new-scratch-model")], append=True)
        index.refresh()
        gate("providers.claude.read_bytes", index.title == "Renamed appended" and index.model == "new-scratch-model" and sum(ranges) < 5000, "summary refresh reads appended bytes rather than whole transcript")
    finally:
        ct.read_bytes = original
    pager = adapter()
    last = pager.read(sid, limit=50)
    gate("providers.claude.store_page", last.has_earlier and len(last.items) == 50 and last.items[-1].data["text"] == "later", "tail-first latest bounded page")
    pages = [last]
    while pages[-1].has_earlier:
        pages.append(pager.read(sid, before_seq=pages[-1].items[0].seq, limit=200))
    chronological = [item for page in reversed(pages) for item in page.items]
    gate("providers.claude.sequence", len(chronological) == 3602 and len({item.id for item in chronological}) == len(chronological) and [item.seq for item in chronological] == sorted(item.seq for item in chronological), "deep earlier paging covers every source item once with stable byte-offset sequence")
    # Compaction resets usage until the next assistant and only settings supply threshold.
    transcript.write([transcript.user("go"), *transcript.assistant([{"type": "text", "text": "before"}]), transcript.record("system", subtype="compact_boundary", compactMetadata={"preTokens": 100})])
    gate("providers.claude.context", adapter().read(sid).context.used_tokens is None, "compaction boundary resets current usage")
    (config / "settings.json").write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")
    context = adapter().read(sid).context
    gate("providers.claude.context", context.auto_compact_tokens == 400000 and "settings" in context.source, "compaction threshold uses settings only")
    transcript.write([transcript.user("go"), *transcript.assistant([{"type": "text", "text": "No response requested."}], model="<synthetic>"), *transcript.assistant([{"type": "text", "text": "API failure"}], mid="api-error", isApiErrorMessage=True, error="authentication_failed")])
    gate("providers.claude.page", [(item.kind, item.data.get("level")) for item in adapter().read(sid).items[1:]] == [("notice", "info"), ("notice", "error")], "synthetic assistant and API errors become notices")
    transcript.write([transcript.user("start"), *transcript.assistant([{"type": "text", "text": "working"}]), transcript.record("attachment", attachment={"type": "queued_command", "prompt": [{"type": "text", "text": "queued image"}, image_block], "commandMode": "prompt"}), transcript.record("attachment", attachment={"type": "queued_command", "prompt": [image_block], "commandMode": "prompt"})])
    queued = [item for item in adapter().read(sid).items if item.data.get("queued")]
    gate("providers.claude.media", [item.data["text"] for item in queued] == ["queued image", ""] and all(item.data["attachments"][0]["mime"] == "image/png" and "base64" not in json.dumps(item.data) for item in queued), "queued images remain attachment handles, including image-only sends")
    return identities, checks


def _terminal_protocol(root):
    import base64
    from datetime import datetime, timedelta, timezone
    from .connected_sessions import claude_terminal as terminal
    from .connected_sessions.claude import ClaudeAdapter, ClaudeSessionError
    from .connected_sessions.model import TurnOptions, Item
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    peers = Path(__file__).resolve().parents[2] / "tests/fixtures"
    folder, config = root / "terminal-work", root / "terminal-config"
    folder.mkdir()
    project = config / "projects" / "scratch"
    project.mkdir(parents=True)
    live, log = root / "terminal-live.json", root / "terminal-protocol.jsonl"
    live.write_text("[]", encoding="utf-8")
    dispatcher = root / "terminal-peer.py"
    dispatcher.write_text("import sys,runpy,os\n" + "peers=" + repr(str(peers)) + "\n" + "if '--' in sys.argv:\n" + " if sys.argv[-1].startswith('trust-peer'):\n" + "  print('Quick safety check:\\nIs this a project you created or one you trust?\\n> Yes, I trust this folder\\nNo, exit\\nEnter to confirm\\nEsc to cancel',flush=True)\n" + "  keys=''\n" + "  while not keys.endswith('\\r'):\n" + "   raw=sys.stdin.buffer.read(1)\n" + "   if not raw: sys.exit(0)\n" + "   keys += raw.decode()\n" + "  if '\\x1b[B' in keys: sys.exit(0)\n" + " runpy.run_path(os.path.join(peers,'fake_claude_terminal.py'),run_name='__main__')\n" + "else: runpy.run_path(os.path.join(peers,'fake_claude_cli.py'),run_name='__main__')\n", encoding="utf-8")
    class PipeTerminal:
        """The documented terminal transport interface over a real confined pipe."""
        def __init__(self, argv, cwd, env):
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **hidden_windows_subprocess_kwargs(new_process_group=True))
            self.pid = self.process.pid
        def read(self, size):
            raw = os.read(self.process.stdout.fileno(), size)
            if not raw:
                raise EOFError
            return raw.decode("utf-8", errors="replace")
        def write(self, text):
            self.process.stdin.write(text.encode())
            self.process.stdin.flush()
        def isalive(self):
            return self.process.poll() is None
        def terminate(self, force=False):
            if self.process.poll() is None:
                self.process.kill()
    def adapter():
        made = ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(dispatcher)], agents_ttl=0, context_probe=False, extra_env={"FAKE_CLAUDE_PROJECTS": str(project), "FAKE_CLAUDE_LOG": str(log), "FAKE_CLAUDE_AGENTS": str(live)})
        made.terminal_spawn = PipeTerminal
        return made
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    # Standalone hook executes its actual file and emits its real spool event.
    spool = root / "hook-spool"
    (spool / "decisions").mkdir(parents=True)
    reply = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    (spool / "decisions/scratch-tool.json").write_text(json.dumps(reply), encoding="utf-8")
    done = subprocess.run([sys.executable, str(terminal.HOOK_SCRIPT), str(spool), "permission"], input=json.dumps({"tool_use_id": "scratch-tool"}), capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
    emitted = [json.loads(path.read_text(encoding="utf-8")) for path in (spool / "events").iterdir()]
    gate("providers.terminal.hook", done.returncode == 0 and json.loads(done.stdout) == reply and len(emitted) == 1 and emitted[0]["requestId"] == "scratch-tool", "actual standalone hook emitted event and printed exact allowed decision")
    (spool / "closed").write_text("closed", encoding="utf-8")
    started = time.monotonic()
    done = subprocess.run([sys.executable, str(terminal.HOOK_SCRIPT), str(spool), "permission"], input=json.dumps({"tool_use_id": "unanswered-tool"}), capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
    gate("providers.terminal.hook", done.stdout == "" and time.monotonic() - started < 10, "closed spool hook exits quietly without an invented answer")
    original_images = terminal.IMAGE_DIR
    terminal.IMAGE_DIR = root / "terminal-images"
    try:
        image = b"\x89PNG\r\n\x1a\nscratch-image"
        encoded = base64.b64encode(image).decode()
        for text in ("what is this?", ""):
            prompt = terminal.attach_images_as_files(text, [{"mime": "image/png", "data": encoded}])
            path = Path(next(line for line in prompt.splitlines() if line.startswith("Attached image: ")).removeprefix("Attached image: "))
            gate("providers.terminal.images", path.read_bytes() == image and prompt.startswith(text if text else "Look at the attached image."), "image bytes saved under scratch and named in literal prompt")
        try:
            terminal.attach_images_as_files("invalid", [{"mime": "application/pdf", "data": encoded}])
        except ClaudeSessionError as error:
            gate("providers.terminal.images", error.code == "invalid_image", "unsupported terminal attachment refused")
        made = adapter()
        options = TurnOptions(transport="terminal")
        events, _, finish = _start(made, None, "hello terminal", options=options, cwd=str(folder), name="terminal-new")
        sid = finish()
        gate("providers.claude.lifecycle", events.states()[-1] == "completed" and all(event["sessionId"] == sid for event in events.rows if event["type"] == "run.state"), "interactive CLI hooks/transcript reach completed session")
        gate("providers.claude.page", {item["data"].get("text") for item in events.items() if item["kind"] in {"user", "assistant"}} >= {"hello terminal", "echo: hello terminal"}, "new interactive transcript followed into both user and assistant items")
        events, _, finish = _start(made, sid, "next terminal", options=options, cwd=str(folder), name="terminal-resume")
        gate("providers.claude.lifecycle", finish() == sid and events.states()[-1] == "completed", "terminal resumes same persisted ID")
        texts = [item["data"].get("text") for item in events.items() if item["kind"] in {"user", "assistant"}]
        gate("providers.claude.page", "echo: next terminal" in texts and "echo: hello terminal" not in texts, "resume baseline displays only new transcript content")
        for decision in ("approve", "deny"):
            run_id = "terminal-" + decision
            events, _, finish = _start(made, sid, "approve-me", options=options, cwd=str(folder), name=run_id)
            waiting = events.wait(lambda event: event["type"] == "run.state" and event["state"] == "waiting_approval")
            request = waiting["pendingRequest"]
            gate("providers.claude.events", request["kind"] == "approval" and request["command"] == "echo hi", "actual PermissionRequest hook waits with real command")
            made.answer(run_id, request["requestId"], {"decision": decision})
            finish()
            gate("providers.terminal.answer", events.states()[-1] == "completed" and any(item["data"].get("text") == "permission: " + ("allow" if decision == "approve" else "deny") for item in events.items()), "hook decision consumed once and received by interactive process")
        events, _, finish = _start(made, sid, "ask-me", options=options, cwd=str(folder), name="terminal-question")
        waiting = events.wait(lambda event: event["type"] == "run.state" and event["state"] == "waiting_input")
        request = waiting["pendingRequest"]
        made.answer("terminal-question", request["requestId"], {"decision": "approve", "answers": {"q0": "Blue"}})
        finish()
        gate("providers.terminal.answer", any(item["data"].get("text") == "picked: Blue" for item in events.items()), "question answered through actual PreToolUse updatedInput")
        events, _, finish = _start(made, sid, "hang", options=options, cwd=str(folder), name="terminal-stop")
        events.wait(lambda event: event["type"] == "item.added" and event["item"]["kind"] == "user")
        made.interrupt("terminal-stop")
        finish()
        gate("providers.claude.lifecycle", events.states()[-1] == "interrupted", "Stop sends Escape then closes confined interactive process")
        for message, code in (("fail now", "rate_limited"), ("die please", "cli_exited")):
            events, _, finish = _start(made, sid, message, options=options, cwd=str(folder), name="terminal-" + code)
            finish()
            final = [event for event in events.rows if event["type"] == "run.state"][-1]
            gate("providers.claude.lifecycle", final["state"] == "failed" and final["errorCode"] == code, "CLI hook/exit failure reaches exact safe terminal reason")
        for decision in ("approve", "deny"):
            events, _, finish = _start(made, None, "trust-peer scratch folder", options=options, cwd=str(folder), name="terminal-trust-" + decision)
            waiting = events.wait(lambda event: event["type"] == "run.state" and event["state"] == "waiting_approval")
            request = waiting["pendingRequest"]
            gate("providers.terminal.answer", request.get("category") == "folder_trust" and request["kind"] == "approval", "unknown/untrusted folder becomes explicit recognized trust request")
            made.answer("terminal-trust-" + decision, request["requestId"], {"decision": decision})
            finish()
            gate("providers.terminal.answer", events.states()[-1] == ("completed" if decision == "approve" else "interrupted"), "only explicit person decision answers native trust menu")
        trust = config / ".claude.json"
        trust.write_text(json.dumps({"projects": {str(folder.parent): {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
        gate("providers.terminal.answer", made._folder_trusted(str(folder)) is True, "recorded parent folder trust recognized without changing saved config")
    finally:
        terminal.IMAGE_DIR = original_images
    # Local compaction stop is a current transcript boundary, never an old item/echo.
    run = terminal.ClaudeTerminalRun(cli=None, run_id="local-compact", session_id="scratch-compact", message="/compact", options=TurnOptions(transport="terminal"), cwd=str(root), emit=lambda event: None, projects=project, store_for=None)
    now = datetime.now(timezone.utc)
    for item in (Item("old", 1, "compaction", (now - timedelta(hours=1)).isoformat(), {"state": "completed"}), Item("echo", 2, "notice", now.isoformat(), {"text": "/compact"})):
        run._note_local_result(item)
        gate("providers.terminal.compact", run._stop_at is None, "stale boundary and command echo do not complete local compaction")
    run._note_local_result(Item("current", 3, "compaction", now.isoformat(), {"state": "completed", "beforeTokens": 9, "afterTokens": 1}))
    gate("providers.terminal.compact", run._stop_at is not None and run._prompted and terminal._is_local_command("  /Compact keep plan") and not terminal._is_local_command("please /compact"), "fresh boundary completes slash-local command")
    return identities, checks


def _claude_catalogue(root):
    from .connected_sessions.claude import ClaudeAdapter, ClaudeSessionError, AGENTS_MAX_AGE_SECONDS
    from .connected_sessions.model import TurnOptions
    peer = Path(__file__).resolve().parents[2] / "tests/fixtures/fake_claude_cli.py"
    config, work = root / "catalogue-config", root / "catalogue-work"
    work.mkdir()
    project = config / "projects/scratch"
    project.mkdir(parents=True)
    live, log = root / "catalogue-live.json", root / "catalogue-cli.jsonl"
    live.write_text("[]", encoding="utf-8")
    sid = "catalogue-chat"
    transcript = _Transcript(project / (sid + ".jsonl"), sid, str(work))
    transcript.write([transcript.user("catalogue"), *transcript.assistant([{"type": "text", "text": "response"}], model="scratch-custom-model")])
    def adapter(**overrides):
        return ClaudeAdapter(config_dir=config, cli_path=overrides.pop("cli_path", [sys.executable, str(peer)]), agents_ttl=overrides.pop("agents_ttl", 0), context_probe=False, extra_env={"FAKE_CLAUDE_LOG": str(log), "FAKE_CLAUDE_AGENTS": str(live), **overrides.pop("peer_env", {})}, **overrides)
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    for path, description in ((config / "skills/reviewer/SKILL.md", "Reviews scratch diffs"), (work / ".claude/skills/deploy/SKILL.md", "Deploy scratch")):
        path.parent.mkdir(parents=True)
        path.write_text("---\ndescription: " + description + "\n---\nbody", encoding="utf-8")
    (config / "settings.json").write_text(json.dumps({"model": "sonnet", "permissions": {"defaultMode": "acceptEdits"}, "effortLevel": "high", "env": {"SYNTHETIC_PRIVATE_MARKER": "scratch-private-setting"}, "apiKeyHelper": "scratch-unused-helper"}), encoding="utf-8")
    made = adapter()
    options = made.options(sid)
    models = {row["id"]: row for row in options["models"]}
    gate("providers.claude.options", {"default", "sonnet", "sonnet[1m]", "haiku", "opus", "scratch-custom-model"} <= set(models) and models["sonnet"]["efforts"] == ["low", "medium", "high", "xhigh"] and models["haiku"]["efforts"] == [] and models["sonnet"]["default"] is True and models["default"]["default"] is False, "actual CLI model list/defaults includes aliases and current session model")
    modes = {row["id"]: row for row in options["permissionModes"]}
    gate("providers.claude.options", list(modes) == ["acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"] and modes["acceptEdits"]["default"] is True and not modes["manual"]["default"] and bool(modes["plan"]["description"]), "real help choices and saved permission default projected")
    gate("providers.claude.options", options["efforts"] == ["low", "medium", "high", "xhigh", "max"] and options["defaultEffort"] == "high" and {(row["name"], row["scope"]) for row in options["skills"]} == {("reviewer", "user"), ("deploy", "project")}, "actual CLI efforts and scratch user/project skill directories projected")
    gate("providers.claude.options", {(row["name"], row["state"]) for row in options["mcpServers"]} == {("files", "connected"), ("browser", "needs_auth"), ("broken", "failed")} and {(row["id"], row["state"]) for row in options["plugins"]} == {("docs-plugin", "enabled"), ("old-plugin", "disabled")} and "scratch-private-setting" not in json.dumps(options) and "scratch-unused-helper" not in json.dumps(options), "observed MCP/plugin states retained without private settings")
    missing = adapter(cli_path=[sys.executable, str(root / "missing-peer.py")])
    fallback = missing.options()
    gate("providers.claude.options", missing.available()[0] is False and [row["id"] for row in fallback["models"]] == ["opus", "sonnet", "haiku"] and fallback["permissionModes"] == [] and fallback["efforts"] == [] and fallback["mcpServers"] == [], "unavailable CLI falls back only to advertised aliases")
    caps = missing.list_sessions()[0].capabilities
    gate("providers.claude.capabilities", not caps.continue_session and not caps.new_session and caps.billing is None and "not installed" in caps.reason, "missing CLI disables all continuation/new-session claims")
    try:
        missing.start_turn(sid, "hello", TurnOptions(), cwd=str(work), run_id="missing", emit=lambda event: None)
    except ClaudeSessionError as error:
        gate("providers.claude.capabilities", error.code == "cli_unavailable", "missing CLI refuses action before launch")
    failing = adapter(peer_env={"FAKE_CLAUDE_AGENTS_FAIL": "1"})
    gate("providers.claude.live", failing.list_sessions()[0].status == "unknown", "failed agents query is unknown rather than falsely idle")
    sessions = config / "sessions"
    sessions.mkdir()
    marker = sessions / "scratch-writer.json"
    marker.write_text('{"status":"idle"}', encoding="utf-8")
    cached = adapter(agents_ttl=2)
    def calls():
        return sum(1 for line in log.read_text(encoding="utf-8").splitlines() if json.loads(line).get("argv") == ["agents", "--json"])
    before = calls()
    cached._agents_entries()
    for _ in range(2):
        stamp, rows = cached._agents_cache
        cached._agents_cache = (stamp - 2.5, rows)
        cached._agents_entries()
    gate("providers.claude.live", calls() - before == 1, "unchanged writer-file signature avoids real process restarts beyond plain TTL")
    marker.write_text('{"status":"busy"}', encoding="utf-8")
    stamp, rows = cached._agents_cache
    cached._agents_cache = (stamp - 2.5, rows)
    cached._agents_entries()
    gate("providers.claude.live", calls() - before == 2, "changed writer file triggers actual CLI liveness query")
    stamp, rows = cached._agents_cache
    cached._agents_cache = (stamp - AGENTS_MAX_AGE_SECONDS, rows)
    cached._agents_entries()
    cached._agents_entries(force=True)
    gate("providers.claude.live", calls() - before == 4, "maximum age and send-time force query actual CLI")
    # No sessions folder: query repeats after plain TTL, without synthetic responses.
    plain = adapter(agents_ttl=2)
    plain._config_dir = root / "no-session-config"
    before = calls()
    for _ in range(3):
        plain._agents_entries()
        stamp, rows = plain._agents_cache
        plain._agents_cache = (stamp - 2.5, rows)
    gate("providers.claude.live", calls() - before == 3, "absent writer folder retains ordinary CLI polling TTL")
    return identities, checks


def _claude_agent_transcripts(root):
    from datetime import datetime, timedelta, timezone
    from .connected_sessions.claude import ClaudeAdapter
    config = root / "agents-config"
    project = config / "projects/scratch"
    project.mkdir(parents=True)
    sid = "scratch-agent-parent"
    transcript = _Transcript(project / (sid + ".jsonl"), sid, str(root))
    peer = Path(__file__).resolve().parents[2] / "tests/fixtures/fake_claude_cli.py"
    def adapter():
        return ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(peer)], agents_ttl=0, context_probe=False)
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    now = datetime.now(timezone.utc)
    def stamp(seconds):
        return (now + timedelta(seconds=seconds)).isoformat()
    inp = {"description": "Inspect scratch adapter", "prompt": "inspect owned files", "subagent_type": "general-purpose", "run_in_background": True}
    transcript.write([transcript.user("delegate", timestamp=stamp(-300)), *transcript.assistant([{"type": "tool_use", "id": "parent-agent", "name": "Agent", "input": inp}], timestamp=stamp(-290)), transcript.result("parent-agent", "Async launched", structured={"isAsync": True, "status": "async_launched", "agentId": "scratch-child", "description": "Inspect scratch adapter", "resolvedModel": "scratch-agent-model"}, timestamp=stamp(-289))])
    subfolder = project / sid / "subagents"
    subfolder.mkdir(parents=True)
    (subfolder / "agent-scratch-child.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "Inspect scratch adapter", "toolUseId": "parent-agent"}), encoding="utf-8")
    child = _Transcript(subfolder / "agent-scratch-child.jsonl", sid, str(root))
    def child_records(start, end):
        records = []
        for n in range(start, end):
            records += child.assistant([{"type": "tool_use", "id": f"child-tool-{n}", "name": "Bash", "input": {"command": "inspect scratch"}}], mid=f"child-message-{n}", model="scratch-agent-model", usage={"input_tokens": 3, "cache_read_input_tokens": 1000 * (n + 1), "cache_creation_input_tokens": 10, "output_tokens": 100 + n}, isSidechain=True, agentId="scratch-child", timestamp=stamp(-280 + n))
            records.append(child.result(f"child-tool-{n}", "ok", isSidechain=True, agentId="scratch-child", timestamp=stamp(-279.5 + n)))
        return records
    child.write(child_records(0, 1))
    made = adapter()
    first = made.read(sid)
    agent = next(item for item in first.items if item.kind == "tool").data["agent"]
    gate("providers.claude.aggregate", agent["toolCount"] == 1 and agent["status"] == "running", "actual sidechain file updates parent agent while running")
    child.write(child_records(1, 3), append=True)
    delta = made.read(sid, cursor=first.cursor)
    gate("providers.claude.page", [item.id for item in delta.items] == ["parent-agent"] and delta.items[0].data["agent"]["toolCount"] == 3 and made.read(sid, cursor=delta.cursor).items == [], "sidechain changes appear once through parent incremental cursor")
    agent = delta.items[0].data["agent"]
    gate("providers.claude.aggregate", agent["description"] == "Inspect scratch adapter" and agent["subagentType"] == "general-purpose" and agent["model"] == "scratch-agent-model" and agent["status"] == "running" and agent["outputTokens"] == 303 and agent["inputTokens"] == 3013 and agent["startedAt"] and agent["endedAt"] is None and agent["durationMs"] is None, "sidechain counts all messages, retains latest context and unknown finish fields")
    transcript.write([transcript.user("<task-notification><task-id>scratch-child</task-id><tool-use-id>parent-agent</tool-use-id><status>completed</status><summary>Agent finished</summary><usage><subagent_tokens>999</subagent_tokens><tool_uses>3</tool_uses><duration_ms>61234</duration_ms></usage></task-notification>", origin={"kind": "task-notification"}, timestamp=stamp(-100))], append=True)
    agent = next(item for item in made.read(sid).items if item.kind == "tool").data["agent"]
    gate("providers.claude.aggregate", agent["status"] == "ok" and agent["toolCount"] == 3 and agent["durationMs"] == 61234 and agent["endedAt"] > agent["startedAt"], "task notification supplies actual finish state/end/duration")
    transcript.write([transcript.user("<task-notification><tool-use-id>parent-agent</tool-use-id><status>killed</status><summary>Stopped</summary></task-notification>", origin={"kind": "task-notification"}, timestamp=stamp(-50))], append=True)
    gate("providers.claude.aggregate", next(item for item in made.read(sid).items if item.kind == "tool").data["agent"]["status"] == "error", "killed notification updates finished agent to error")
    # Missing sidechain/result data stays unknown; no fabricated metrics.
    missing_sid = "scratch-agent-missing"
    missing = _Transcript(project / (missing_sid + ".jsonl"), missing_sid, str(root))
    missing.write([missing.user("delegate", timestamp=stamp(-300)), *missing.assistant([{"type": "tool_use", "id": "missing-agent", "name": "Agent", "input": {**inp, "run_in_background": False}}], timestamp=stamp(-290))])
    fresh = adapter()
    agent = next(item for item in fresh.read(missing_sid).items if item.kind == "tool").data["agent"]
    gate("providers.claude.aggregate", agent["status"] == "running" and all(agent[key] is None for key in ("model", "endedAt", "durationMs", "toolCount", "inputTokens", "outputTokens")), "absent data preserves unknown fields")
    missing.write([missing.result("missing-agent", "done", structured={"status": "completed", "agentId": "other", "totalToolUseCount": 7, "totalDurationMs": 4200, "resolvedModel": "scratch-agent-model", "usage": {"input_tokens": 1, "output_tokens": 55, "cache_read_input_tokens": 90, "cache_creation_input_tokens": 9}}, timestamp=stamp(-10))], append=True)
    agent = next(item for item in fresh.read(missing_sid).items if item.kind == "tool").data["agent"]
    gate("providers.claude.aggregate", (agent["status"], agent["toolCount"], agent["durationMs"], agent["model"], agent["outputTokens"], agent["inputTokens"]) == ("ok", 7, 4200, "scratch-agent-model", 55, 100), "synchronous provider result supplies actual completion totals")
    # In-file sidechain records affect aggregate but never create top-level chat items.
    records = [missing.user("delegate again", timestamp=stamp(-300)), *missing.assistant([{"type": "tool_use", "id": "infile-agent", "name": "Agent", "input": inp}], timestamp=stamp(-290))]
    parent = missing.parent
    side = _Transcript(missing.path, missing_sid, str(root))
    side.parent = parent
    records += [side.user("inspect owned files", isSidechain=True, timestamp=stamp(-280)), *side.assistant([{"type": "tool_use", "id": "infile-child", "name": "Grep", "input": {"pattern": "scratch"}}], mid="infile-child-message", model="scratch-agent-model", isSidechain=True, timestamp=stamp(-279)), side.result("infile-child", "hit", isSidechain=True, timestamp=stamp(-278))]
    missing.write(records)
    items = adapter().read(missing_sid).items
    gate("providers.claude.page", [item.kind for item in items] == ["user", "tool"] and items[1].data["agent"]["toolCount"] == 1 and items[1].data["agent"]["model"] == "scratch-agent-model", "sidechain records aggregate under their parent and stay out of main chat")
    return identities, checks


class _CodexWorld:
    """Finite JSON-RPC peer world, kept under the procedure's selected root."""
    def __init__(self, root, world, **environment):
        self.root = root
        root.mkdir(parents=True)
        self.path, self.log = root / "world.json", root / "wire.jsonl"
        self.path.write_text(json.dumps(world), encoding="utf-8")
        self.environment = {"FAKE_CODEX_WORLD": str(self.path), "FAKE_CODEX_LOG": str(self.log), "FAKE_TURN_SECONDS": "2.7", "CODEX_HOME": str(root / "codex-home"), **environment}
        self.adapters = []

    def adapter(self, **options):
        from .connected_sessions.codex import CodexAdapter
        peer = Path(__file__).resolve().parents[2] / "tests/fixtures/fake_codex_app_server.py"
        made = CodexAdapter(command=[sys.executable, str(peer)], device={"deviceId": "proofcodex01", "deviceName": "Scratch PC"}, state_root=self.root, list_ttl=0, **options)
        made._conn._environment = dict(os.environ, **self.environment)
        self.adapters.append(made)
        return made

    def records(self, method=None):
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []
        return [row for row in rows if method is None or row["method"] == method]

    def close(self):
        for made in self.adapters:
            made.close()


def _codex_protocol(root):
    import base64
    from .connected_sessions import codex_items as ci
    from .connected_sessions.codex_rpc import AppServerConnection, CodexError
    from .connected_sessions.model import TurnOptions
    os.environ["CODEX_HOME"] = str(root / "codex-home")
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    def sid(tid):
        return ci.session_id_for(tid, "proofcodex01")
    def user(n, text):
        return {"type": "userMessage", "id": f"u-{n}", "content": [{"type": "text", "text": text, "text_elements": []}]}
    def turn(n, items, **fields):
        return {"id": f"legacy-turn-{n}", "items": items, "status": "completed", "startedAt": None, "completedAt": 1790000000+n, **fields}
    def thread(tid, **fields):
        return {"id": tid, "name": tid, "cwd": str(root), "updatedAt": int(time.time())-7200, "createdAt": 1790000000, "model": "scratch-model", "source": "vscode", **fields}
    picture = root / "codex-shot.png"
    picture.write_bytes(b"\x89PNG-scratch-bytes")
    ref = "data:image/png;base64," + base64.b64encode(b"inline-scratch").decode()
    rollout = root / "codex-usage.jsonl"
    def usage(tokens):
        rollout.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"total_tokens": tokens}, "model_context_window": 200000}}}) + "\n", encoding="utf-8")
        os.utime(rollout, (time.time()-3600,)*2)
    usage(4321)
    rich = [user(1, '<in-app-browser-context source="ambient">url: scratch</in-app-browser-context>\nPlease inspect the scratch file')]
    rich[0]["content"] += [{"type": "localImage", "path": str(picture)}, {"type": "image", "url": ref}]
    rich += [{"type": "reasoning", "id": "reason-hidden", "summary": [], "content": []}, {"type": "reasoning", "id": "reason-visible", "summary": ["Inspecting", "Then explaining"], "content": []}, {"type": "commandExecution", "id": "command", "command": "inspect scratch", "cwd": str(root), "status": "completed", "commandActions": [], "aggregatedOutput": "x"*300000 + "scratch-tail", "exitCode": 1, "durationMs": 17}, {"type": "fileChange", "id": "edit", "status": "completed", "changes": [{"path": str(root / "a.txt"), "kind": {"type": "update"}, "diff": "@@ -1 +1,2 @@\n-a\n+b\n+c\n"}]}, {"type": "mcpToolCall", "id": "mcp", "server": "scratch", "tool": "search", "status": "completed", "arguments": {"title": "Find scratch"}, "result": {"content": [{"type": "text", "text": "found"}]}, "error": None}, {"type": "webSearch", "id": "web", "query": "scratch", "action": {"type": "search", "query": "scratch"}}, {"type": "plan", "id": "plan", "text": "Inspect scratch"}, {"type": "contextCompaction", "id": "compact"}, {"type": "imageView", "id": "image", "path": str(picture)}, {"type": "agentMessage", "id": "answer", "text": "Inspected."}]
    turns = [turn(1, rich)] + [turn(n, [user(n, f"question {n}"), {"type": "agentMessage", "id": f"answer-{n}", "text": f"answer {n}"}]) for n in range(2, 13)]
    turns.append(turn(13, [user(13, "last")], status="failed", error={"message": "Scratch overloaded"}))
    giant = [user(900, "inspect many")] + [{"type": "commandExecution", "id": f"many-{n}", "command": f"inspect {n}", "cwd": str(root), "status": "completed", "commandActions": [], "aggregatedOutput": str(n), "exitCode": 0} for n in range(450)]
    long = [turn(n, [user(1000+n, f"q{n}"), {"type": "agentMessage", "id": f"long-{n}", "text": f"a{n}"}]) for n in range(1, 251)]
    world = {"threads": [thread("main", path=str(rollout), name="Scratch chat", gitInfo={"branch": "scratch/branch"}), thread("bare"), thread("giant"), thread("long"), thread("archived", archived=True)] + [thread(f"filler-{n}", updatedAt=int(time.time())-8000-n) for n in range(130)], "turns": {"main": turns, "giant": [turn(900, giant)], "long": long}, "config": {"model_auto_compact_token_limit": 180000}}
    world["threads"][0]["projectId"] = "explicit-project"
    world["projects"] = [{"id": "explicit-project", "name": "Scratch project", "roots": [{"path": str(root / "dedicated")}]}, {"id": "containing-root", "name": "Scratch root", "roots": [{"path": str(root)}]}]
    confined = _CodexWorld(root / "codex-read", world)
    try:
        made = confined.adapter()
        rows = made.list_sessions()
        main = next(row for row in rows if row.id == sid("main"))
        gate("providers.codex.list", len(rows) == 134 and len(confined.records("thread/list")) > 1 and (main.title, main.cwd, main.model, main.git_branch, main.origin, main.host_device_id) == ("Scratch chat", str(root), "scratch-model", "scratch/branch", "neyvia-harness", "proofcodex01"), "paged newest-first list projects identity/model/cwd/branch and scratch origin")
        gate("providers.codex.summary", main.project == "Scratch project" and next(row for row in rows if row.id == sid("filler-3")).project == "Scratch root" and all(getattr(main.capabilities, key) for key in ("continue_session", "new_session", "stop", "approvals", "questions", "images", "goal", "compact", "steer", "model_choice", "effort_choice", "permission_choice")), "actual project ID outranks containing root; idle installed summary advertises supported controls")
        old = next(row for row in made.list_sessions(include_archived=True) if row.id == sid("archived"))
        gate("providers.codex.list", old.archived and not old.capabilities.continue_session and "archived" in old.capabilities.reason, "archived list is explicit and cannot continue")
        full = made.read(sid("main"), limit=200)
        by_id = {item.id: item for item in full.items}
        gate("providers.codex.page", {item.kind for item in full.items} == {"user", "reasoning", "tool", "diff", "notice", "compaction", "assistant"} and by_id["reason-hidden"].data["hidden"] and by_id["reason-visible"].data["summary"] == "Inspecting\n\nThen explaining" and by_id["answer"].data["text"] == "Inspected." and any(item.data.get("text") == "Scratch overloaded" for item in full.items), "actual full-turn RPC maps every supported chat family and provider error")
        gate("providers.codex.page", by_id["u-1"].data["text"] == "Please inspect the scratch file" and all(a["url"] is None for a in by_id["u-1"].data["attachments"]) and by_id["command"].data["outputTruncated"] and by_id["command"].data["output"].endswith("scratch-tail") and by_id["command"].data["status"] == "error" and by_id["edit:diff"].data["files"][0]["additions"] == 2 and by_id["mcp"].data["output"] == "found", "injected context stripped; media opaque; command bounded; edit/mcp exact values")
        gate("providers.codex.page", (full.context.used_tokens, full.context.window_tokens, full.context.auto_compact_tokens) == (4321, 200000, 180000) and made.read(sid("bare")).context.used_tokens is None and made.read(sid("bare")).context.window_tokens is None, "persisted provider usage and threshold observed; missing usage stays unknown")
        first = made.read(sid("main"), limit=6)
        collected, page = list(first.items), first
        while page.has_earlier:
            page = made.read(sid("main"), before_seq=collected[0].seq, limit=6)
            collected = page.items + collected
        gate("providers.codex.page", [item.id for item in collected] == [item.id for item in full.items] and first.has_earlier and not page.has_earlier, "tail-first bounded pages cover rich/legacy turns exactly once")
        fresh = confined.adapter()
        older = fresh.read(sid("main"), before_seq=first.items[0].seq, limit=5)
        gate("providers.codex.page", bool(older.items) and max(item.seq for item in older.items) < first.items[0].seq, "new adapter resumes earlier paging without cursor cache")
        huge = made.read(sid("giant"), limit=200)
        prior = made.read(sid("giant"), before_seq=huge.items[0].seq, limit=200)
        gate("providers.codex.page", len(huge.items) == len(prior.items) == 200 and huge.has_earlier and prior.items[-1].seq < huge.items[0].seq and huge.items[-2].id == "many-449" and huge.items[-1].data["exposure"] == "not_reported", "giant450-tool turn clips pages and states unavailable reasoning")
        recent = made.read(sid("long"), limit=6)
        before = len(confined.records("thread/turns/list"))
        deep = made.read(sid("long"), before_seq=ci.make_seq(120, 0), limit=6)
        gate("providers.codex.page", [item.data.get("text") for item in recent.items if item.kind in {"user", "assistant"}] == ["q249", "a249", "q250", "a250"] and [item.data.get("text") for item in deep.items if item.kind in {"user", "assistant"}] == ["q119", "a119", "q120", "a120"] and len(confined.records("thread/turns/list"))-before < 60, "250legacy turns retain ordinal order; deep region uses bounded indexed requests")
        again = made.read(sid("main"), cursor=full.cursor)
        gate("providers.codex.page", len(again.items) <= 3 and again.items[-1].id == full.items[-1].id and not again.has_earlier, "incremental cursor rechecks only newest turn for changed state")
        attachments = by_id["u-1"].data["attachments"]
        gate("providers.codex.media", made.read_media(sid("main"), attachments[0]["mediaRef"]) == (picture.read_bytes(), "image/png", picture.name) and made.read_media(sid("main"), attachments[1]["mediaRef"])[:2] == (b"inline-scratch", "image/png"), "opaque tokens resolve actual local and inline scratch image bytes")
        for session, expected in ((sid("missing"), "session_not_found"), ("external:codex:other:main", "invalid_session"), ("external:claude-code:proofcodex01:main", "invalid_session")):
            try:
                made.read(session)
            except CodexError as error:
                gate("providers.codex.page", error.code == expected, "unknown/wrong-provider/wrong-device read rejects before identity substitution")
            else:
                require(False, "providers.codex.page", "unknown session accepted")
        gate("providers.codex.wire", confined.records("initialize")[0]["params"]["capabilities"]["experimentalApi"] is True and any(row["params"].get("itemsView") == "full" and row["params"].get("limit") == 1 for row in confined.records("thread/turns/list")), "actual initialized experimental transport and bounded full-item pages")
        gate("providers.process.hidden", made._conn.alive, "real app-server launched through mandatory hidden/piped process guard")
    finally:
        confined.close()
    # The same state machine is driven through actual notifications and requests.
    live = _CodexWorld(root / "codex-live", {"threads": [thread("chat", path=str(rollout))], "turns": {"chat": [turn(1, [user(1, "old"), {"type": "agentMessage", "id": "old-answer", "text": "older"}])]}, "config": {}})
    try:
        made = live.adapter()
        image = {"mime": "image/png", "data": base64.b64encode(b"scratch-image").decode()}
        events, outcome, finish = _start(made, sid("chat"), "say hello", options=TurnOptions(model="scratch-choice", effort="low", permission_mode="auto", images=[image]), name="codex-stream")
        returned = finish()
        added = [row["item"] for row in events.rows if row["type"] == "item.added"]
        gate("providers.codex.lifecycle", returned == sid("chat") and events.states() == ["running", "completed"] and [item["kind"] for item in added] == ["user", "assistant", "reasoning"] and "".join(row["textDelta"] for row in events.rows if row["type"] == "item.delta") == "Hello from the fake.", "resumed thread streams user/assistant/deltas and explicit unavailable reasoning to completion")
        gate("providers.codex.events", all(row.get("sessionId") in {None, sid("chat")} for row in events.rows if row["type"] != "session.updated") and not any(row.get("item", {}).get("kind") == "goal" for row in events.rows), "real event identities remain same session; resume goal-state sync is not a chat item")
        context = next(row["context"] for row in events.rows if row["type"] == "context.updated")
        gate("providers.codex.events", (context["used_tokens"], context["window_tokens"]) == (450, 128000) and events.rows[-1]["type"] == "session.updated" and events.rows[-1]["session"]["status"] == "idle", "actual streaming usage reaches clients and final summary returns idle")
        wire = live.records("turn/start")[-1]["params"]
        resume = live.records("thread/resume")[-1]["params"]
        gate("providers.codex.input", wire["threadId"] == "chat" and wire["input"][:2] == [{"type": "text", "text": "say hello", "text_elements": []}, {"type": "image", "url": "data:image/png;base64,"+image["data"]}] and (wire["model"], wire["effort"], wire["approvalPolicy"], wire["sandboxPolicy"]["type"]) == ("scratch-choice", "low", "on-request", "workspaceWrite"), "chosen model/effort/permission and image bytes preserved in actual turn RPC")
        gate("providers.codex.wire", resume["threadId"] == "chat" and resume["config"]["model_reasoning_summary"] == "detailed" and resume["config"]["show_raw_agent_reasoning"] and "developerInstructions" in resume and not live.records("thread/start") and len(live.records("initialize")) == 1 and live.records("thread/unsubscribe")[-1]["params"]["threadId"] == "chat", "resume same identity with reasoning/intent policy; reuse connection then release thread")
        persisted = {item.id: item.seq for item in made.read(sid("chat")).items}
        gate("providers.codex.page", all(persisted[row["item"]["id"]] == row["item"]["seq"] for row in events.rows if row["type"] in {"item.added", "item.updated"}), "live item sequences equal subsequent persisted page sequences")
        gate("providers.codex.page", made.read(sid("chat")).context.used_tokens == 4321, "after run persisted usage takes precedence over streaming450 context")
        usage(7777)
        gate("providers.codex.page", made.read(sid("chat")).context.used_tokens == 7777, "actual persisted usage updated by another writer supersedes ended run cache")
        usage(4321)
        events, _, finish = _start(made, None, "new scratch", cwd=str(root), name="codex-new")
        new = finish()
        gate("providers.codex.lifecycle", new != sid("chat") and events.states()[-1] == "completed" and live.records("thread/start")[-1]["params"]["cwd"] == str(root) and live.records("thread/start")[-1]["params"]["threadSource"] == "user", "new thread starts in selected existing folder and is user-visible")
        for text in ("THINK", "PLAN"):
            events, _, finish = _start(made, sid("chat"), text, name="codex-"+text)
            finish()
            items = events.items()
            gate("providers.codex.lifecycle", any(item["kind"] == ("reasoning" if text == "THINK" else "notice") and (item["data"].get("summary") if text == "THINK" else item["data"].get("subtype") == "plan") for item in items), "actual reasoning-summary/plan notifications reach chat")
            if text == "THINK":
                gate("providers.codex.events", any(item["kind"] == "reasoning" and item["data"] == {"summary": "Weighing options", "hidden": False, "provider": "codex", "source": "app-server", "exposure": "summary", "notice": None, "truncated": False} for item in items), "actual exposed reasoning preserves summary/source/exposure metadata")
            else:
                gate("providers.codex.events", any(item["kind"] == "notice" and "- [x] Read" in item["data"]["text"] and "- [~] Write" in item["data"]["text"] for item in items), "actual plan observer preserves completed and in-progress checkboxes")
        for text, decision in (("APPROVE", "approve"), ("APPROVE", "deny"), ("FILE", "approve"), ("ASK", "approve")):
            name = "codex-"+text+decision
            events, _, finish = _start(made, sid("chat"), text, name=name)
            pending = events.wait(lambda row: row["type"] == "run.state" and row["state"] in {"waiting_approval", "waiting_input"})["pendingRequest"]
            read = made.read(sid("chat"))
            gate("providers.codex.lifecycle", any(item.data.get("requestId") == pending["requestId"] for item in read.items) and read.session.status in {"waiting_approval", "waiting_input"}, "late client reads real pending request and partial transcript")
            response = {"decision": decision, **({"answers": {"color": "Green"}} if text == "ASK" else {})}
            if text == "ASK":
                question = pending["questions"][0]
                gate("providers.codex.events", (question["id"], question["header"], question["isSecret"], question["isOther"]) == ("color", "Color", False, True) and [row["label"] for row in question["options"]] == ["red", "blue"], "current question observer preserves flags, stable ID and offered choices")
                try:
                    made.answer(name, pending["requestId"], {"decision": "approve", "answers": {}})
                except CodexError as error:
                    gate("providers.codex.answer", error.code == "answers_required", "question cannot approve empty answer")
                else:
                    require(False, "providers.codex.answer", "empty answer accepted")
            made.answer(name, pending["requestId"], response)
            finish()
            gate("providers.codex.lifecycle", events.states()[-1] == "completed" and live.records("_response")[-1]["params"]["result"] == ({"answers": {"color": {"answers": ["Green"]}}} if text == "ASK" else {"decision": "accept" if decision == "approve" else "decline"}), "approval/file/question consumes request and sends exact wire decision")
            gate("providers.codex.answer", any(row["type"] == "run.state" and row["state"] == "running" and row.get("pendingRequest") is None for row in events.rows) and (text != "ASK" or any(item["kind"] == "question" and item["data"]["answers"] == {"color": "Green"} for item in events.items())), "person answer consumed pending state and actual question item records answer")
            if text == "APPROVE":
                items = events.items()
                gate("providers.codex.answer", pending["choices"] == ["approve", "deny", "cancel"] and pending["command"] == "pwsh -Command Get-Date" and "Needs a shell" in pending["detail"] and any(item["kind"] == "approval" and item["data"]["decision"] == decision for item in items) and any(item["kind"] == "tool" and item["data"]["status"] == ("ok" if decision == "approve" else "error") for item in items) and any(item["kind"] == "assistant" and item["data"]["text"] == ("It ran." if decision == "approve" else "You declined.") for item in items), "approved/denied command preserves actual detail, decision, tool status and final reply")
            try:
                made.answer(name, pending["requestId"], response)
            except CodexError as error:
                gate("providers.codex.answer", error.code in {"run_not_active", "request_not_pending"}, "finished request cannot be answered twice")
            else:
                require(False, "providers.codex.answer", "duplicate answer accepted")
            if text == "FILE":
                gate("providers.codex.lifecycle", any(item["kind"] == "diff" and "+" in item["data"]["patch"] for item in events.items()), "file approval exposes actual proposed diff")
        events, _, finish = _start(made, sid("chat"), "LONG", name="codex-long")
        events.wait(lambda row: row["type"] == "item.delta")
        before = len(live.records("turn/start"))
        try:
            made.start_turn(sid("chat"), "second", TurnOptions(), cwd=None, run_id="codex-second", emit=_Events())
        except CodexError as error:
            gate("providers.codex.lifecycle", error.code == "session_busy" and len(live.records("turn/start")) == before, "competing send rejected without a second turn RPC")
        else:
            require(False, "providers.codex.lifecycle", "competing send accepted")
        made.steer("codex-long", "finish scratch")
        finish()
        gate("providers.codex.wire", live.records("turn/steer")[-1]["params"]["expectedTurnId"] and events.states()[-1] == "completed", "steer binds active turn and completes through notifications")
        events, _, finish = _start(made, sid("chat"), "LONG", name="codex-stop")
        events.wait(lambda row: row["type"] == "item.delta")
        made.interrupt("codex-stop")
        finish()
        gate("providers.codex.lifecycle", events.states()[-1] == "interrupted" and bool(live.records("turn/interrupt")), "long running turn stops via actual interrupt RPC")
        events, _, finish = _start(made, sid("chat"), "SLOW", name="codex-slow")
        began = time.monotonic()
        finish()
        gate("providers.codex.lifecycle", events.states()[-1] == "completed" and time.monotonic()-began >= 2.5, "healthy slow finite turn has no hard short deadline")
        sink = _Events()
        made.set_event_sink(sink)
        goal = made.goal(sid("chat"), "set", "finite scratch objective")
        fetched = made.goal(sid("chat"), "get")
        made.goal(sid("chat"), "clear")
        gate("providers.codex.wire", goal["text"] == fetched["text"] and fetched["tokensUsed"] >= goal["tokensUsed"] and made.goal(sid("chat"), "get") is None and goal["text"] == "finite scratch objective", "real goal set/get/clear retains objective and clears state")
        for action, text, code in (("set", " ", "goal_required"), ("unsupported", None, "invalid_action")):
            try:
                made.goal(sid("chat"), action, text)
            except CodexError as error:
                gate("providers.codex.goal", error.code == code, "invalid goal action/empty objective refused before mutating remote goal")
            else:
                require(False, "providers.codex.goal", "invalid goal accepted")
        deadline = time.monotonic()+2
        while len([row for row in sink.rows if row.get("item", {}).get("kind") == "goal" and row["type"] == "item.added"]) < 2 and time.monotonic() < deadline:
            time.sleep(.02)
        gate("providers.codex.goal_notes", [row["item"]["data"]["state"] for row in sink.rows if row.get("item", {}).get("kind") == "goal" and row["type"] == "item.added"] == ["set", "cleared"], "goal set/clear notifications reach sink once each; token counters and delayed resume sync produce none")
        compact_events = _Events()
        compact = made.compact(sid("chat"), run_id="codex-compact", emit=compact_events)
        compactions = [(row["type"], row["item"]["data"]["state"]) for row in compact_events.rows if row.get("item", {}).get("kind") == "compaction"]
        gate("providers.codex.wire", compact["state"] == "completed" and compact["beforeTokens"] == 4321 and compact["afterTokens"] == 50 and compactions[:2] == [("item.added", "started"), ("item.updated", "completed")], "compaction emits real start/completion with observed token counts")
        made.rename(sid("chat"), "  Scratch   name ")
        made.archive(sid("chat"))
        gate("providers.codex.wire", live.records("thread/name/set")[-1]["params"]["name"] == "Scratch name" and live.records("thread/archive")[-1]["params"]["threadId"] == "chat", "rename normalizes whitespace; archive binds selected thread")
    finally:
        live.close()
    failed = _CodexWorld(root / "codex-failed-compact", {"threads": [thread("chat", path=str(rollout))]}, FAKE_COMPACT_FAIL="1")
    try:
        events = _Events()
        result = failed.adapter().compact(sid("chat"), run_id="codex-fail-compact", emit=events)
        gate("providers.codex.wire", result["state"] == "failed" and events.states()[-1] == "failed" and any(item["kind"] == "compaction" and item["data"]["state"] == "failed" and "compaction blew up" in item["data"]["error"] for item in events.items()), "compaction error produces failed item and terminal run receipt")
    finally:
        failed.close()
    return identities, checks


def _codex_adverse(root):
    from .connected_sessions.codex import CodexAdapter
    from .connected_sessions.codex_rpc import AppServerConnection, CodexError
    from .connected_sessions.model import TurnOptions
    os.environ["CODEX_HOME"] = str(root / "codex-home")
    identities, checks = set(), []
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    def sid(tid):
        return f"external:codex:proofcodex01:{tid}"
    def thread(tid, **fields):
        return {"id": tid, "name": tid, "cwd": str(root), "updatedAt": int(time.time())-7200, "createdAt": 1790000000, "model": "scratch-model", "source": "vscode", **fields}
    failing = AppServerConnection(lambda: [sys.executable, "-c", "raise SystemExit(3)"], on_notification=lambda *a: None, on_server_request=lambda *a: None, backoff=(.3, .6, 30), max_start_wait=.5, initialize_timeout=3)
    try:
        errors, durations = [], []
        for _ in range(3):
            started = time.monotonic()
            try:
                failing.request("ping", {})
            except CodexError as error:
                errors.append(error.code)
                durations.append(time.monotonic()-started)
        gate("providers.rpc.backoff", errors[:2] == ["app_server_stopped"]*2 and errors[-1] == "app_server_backoff" and durations[1] >= .25 and failing.generation == 2, "real repeatedly exiting processes wait before second start and refuse long retry delay")
    finally:
        failing.close()
    saved = {key: os.environ.get(key) for key in ("PATH", "NEYVIA_CODEX_APP_SERVER_COMMAND")}
    os.environ.update(PATH="", NEYVIA_CODEX_APP_SERVER_COMMAND="")
    missing = CodexAdapter(device={"deviceId": "proofcodex01", "deviceName": "Scratch PC"}, state_root=root)
    try:
        available = missing.available()
        try:
            missing.list_sessions()
        except CodexError as error:
            gate("providers.codex.available", available[0] is False and "not installed" in available[1] and error.code == "codex_unavailable", "confined empty PATH reports unavailable CLI without crash")
        else:
            require(False, "providers.codex.available", "missing CLI accepted")
    finally:
        missing.close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    peer = root / "rpc-request-peer.py"
    peer.write_text('''import json,sys
def send(value):
 sys.stdout.write(json.dumps(value)+"\\n");sys.stdout.flush()
for line in sys.stdin:
 m=json.loads(line)
 if m.get("method")=="initialize":
  send({"id":m["id"],"result":{}})
  send({"id":81,"method":"item/tool/call","params":{"threadId":"unknown"}})
  send({"id":82,"method":"currentTime/read","params":{}})
 elif m.get("method")=="ping":send({"id":m["id"],"result":{}})
 elif "method" not in m:send({"method":"scratch/echo","params":m})
''', encoding="utf-8")
    made = CodexAdapter(command=[sys.executable, str(peer)], device={"deviceId": "proofcodex01", "deviceName": "Scratch PC"}, state_root=root)
    echoes = []
    made._conn._on_notification = lambda generation, method, params: echoes.append(params)
    try:
        made._conn.request("ping", {})
        end = time.monotonic()+3
        while len(echoes) < 2 and time.monotonic() < end:
            time.sleep(.01)
        gate("providers.codex.wire", {row["id"] for row in echoes} == {81, 82} and next(row for row in echoes if row["id"] == 81)["error"]["code"] == -32601 and isinstance(next(row for row in echoes if row["id"] == 82)["result"]["currentTimeAt"], int), "unsupported real server request rejected; supported clock request answered")
        gate("providers.rpc.response", abs(next(row for row in echoes if row["id"] == 82)["result"]["currentTimeAt"]-time.time()) < 3, "actual clock answer is current epoch seconds through generation-checked writer")
    finally:
        made.close()
    error_peer = root / "rpc-missing-thread-peer.py"
    error_peer.write_text('''import json,os,sys
for line in sys.stdin:
 m=json.loads(line)
 if m.get("method")=="initialize":r={"id":m["id"],"result":{}}
 elif m.get("method")=="thread/read":r={"id":m["id"],"error":{"code":-32600,"message":os.environ["SCRATCH_MISSING_MESSAGE"]}}
 else:continue
 print(json.dumps(r),flush=True)
''', encoding="utf-8")
    for message in ("thread not loaded: scratch", "no rollout found for thread id scratch", "invalid thread id: invalid character"):
        made = CodexAdapter(command=[sys.executable, str(error_peer)], device={"deviceId": "proofcodex01", "deviceName": "Scratch PC"}, state_root=root)
        made._conn._environment = dict(os.environ, SCRATCH_MISSING_MESSAGE=message)
        try:
            try:
                made.read(sid("missing"))
            except CodexError as error:
                gate("providers.codex.thread", error.code == "session_not_found", "actual provider missing-thread wording translated to public session_not_found")
            else:
                require(False, "providers.codex.thread", "provider missing chat accepted")
        finally:
            made.close()
    # Persisted activity probes are finite local rollouts, never an existing provider home.
    threads = []
    for tid, kinds, age, source in (("app", ["task_started"], 3, "vscode"), ("cli", ["task_started"], 3, "cli"), ("done", ["task_started", "task_complete"], 3, "vscode"), ("stale", ["task_started"], 2700, "vscode"), ("quiet", [], 2, "vscode"), ("old", [], 600, "vscode")):
        path = root / ("writer-"+tid+".jsonl")
        path.write_text("\n".join(json.dumps({"type": "event_msg", "payload": {"type": kind, "turn_id": "scratch", "started_at": int(time.time())-30}}) for kind in kinds) + "\n", encoding="utf-8")
        os.utime(path, (time.time()-age,)*2)
        threads.append(thread(tid, path=str(path), updatedAt=int(time.time())-(2700 if tid == "stale" else 5), source=source))
    foreign = _CodexWorld(root / "codex-writer", {"threads": threads})
    try:
        made = foreign.adapter()
        status = made.live_status()
        gate("providers.codex.live", all(status[sid(tid)] == ("working", owner) for tid, owner in (("app", "app"), ("cli", "cli"), ("quiet", "app"))) and all(sid(tid) not in status for tid in ("done", "stale", "old")), "persisted fresh unfinished/quiet activity names app/CLI owners; completed/stale/old omitted")
        before = len(foreign.records("thread/list"))
        made.live_status()
        gate("providers.codex.live", len(foreign.records("thread/list")) == before and max(row["params"]["limit"] for row in foreign.records("thread/list")) <= 30, "foreign status cached for two seconds and probes only30recent threads")
        listed = {row.id: row for row in made.list_sessions()}
        page = made.read(sid("cli"))
        gate("providers.codex.live", (listed[sid("app")].status, listed[sid("app")].live_owner) == ("working", "app") and listed[sid("done")].status == "idle" and (page.session.status, page.session.live_owner) == ("working", "cli"), "list and read expose the same observed owner/status as liveness")
        for tid, owner in (("app", "app"), ("cli", "cli"), ("quiet", "app")):
            events = _Events()
            try:
                made.start_turn(sid(tid), "compete", TurnOptions(), cwd=None, run_id="compete-"+tid, emit=events)
            except CodexError as error:
                gate("providers.codex.writer", error.code == "session_live_elsewhere" and error.owner == owner and not events.rows, "foreign writer refuses before emitting a run")
            else:
                require(False, "providers.codex.writer", "foreign writer accepted")
        gate("providers.codex.writer", not any(foreign.records(method) for method in ("thread/resume", "thread/start", "turn/start", "thread/fork")), "foreign refusal made no resume/start/fork RPC")
        for tid in ("done", "stale", "old"):
            made.check_send(sid(tid))
        events, _, finish = _start(made, sid("done"), "continue", name="codex-finished-writer")
        gate("providers.codex.writer", finish() == sid("done") and events.states()[-1] == "completed", "finished/stale/idle activity allows same-thread continuation")
    finally:
        foreign.close()
    # Current provider ownership is an OS lock when a lock store exists, not a
    # rollout age guess. A separate hidden process holds only this scratch lock.
    from .connected_sessions.codex_writer import active_writer
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    home = root / "lock-home"
    locks = home / "thread-writer-locks"
    locks.mkdir(parents=True)
    lock = locks / "locked-chat.lock"
    lock.write_bytes(b"1")
    os.environ["CODEX_HOME"] = str(home)
    hold = root / "lock-peer.py"
    hold.write_text('''import os,sys
file=open(sys.argv[1],"r+b")
if os.name=="nt":
 import msvcrt
 msvcrt.locking(file.fileno(),msvcrt.LK_LOCK,1)
else:
 import fcntl
 fcntl.flock(file,fcntl.LOCK_EX)
print("locked",flush=True)
sys.stdin.readline()
file.close()
''', encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(hold), str(lock)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
    try:
        gate("providers.codex.lock", process.stdout.readline().strip() == "locked" and active_writer("locked-chat", None) is True and active_writer("absent-lock", None) is False and active_writer("../escape", None) is None, "actual separate OS writer lock blocks; absent/rejected IDs remain distinct")
        owner = _CodexWorld(root / "codex-locked-owner", {"threads": [thread("locked-chat", source="cli")]})
        try:
            made = owner.adapter()
            gate("providers.codex.writer", made.live_status()[sid("locked-chat")] == ("working", "cli"), "idle/stale transcript remains owned while actual OS lock is held")
        finally:
            owner.close()
    finally:
        process.communicate("release\n", timeout=5)
    gate("providers.codex.lock", active_writer("locked-chat", None) is False and lock.read_bytes() == b"1", "released OS lock permits ownership; probe never mutates lock bytes")
    os.environ["CODEX_HOME"] = str(root / "codex-home")
    live = _CodexWorld(root / "codex-adverse-live", {"threads": [thread("chat")]})
    try:
        made = live.adapter(idle_watchdog_seconds=.7)
        events, _, finish = _start(made, sid("chat"), "SLOW", name="codex-watchdog")
        finish()
        gate("providers.codex.lifecycle", events.states()[-1] == "interrupted" and "No output" in next(row for row in reversed(events.rows) if row["type"] == "run.state")["error"], "silent turn watchdog interrupts through normal transport")
        events, _, finish = _start(made, sid("chat"), "LONG", name="codex-watchdog-busy")
        events.wait(lambda row: row["type"] == "item.delta")
        time.sleep(1.2)
        gate("providers.codex.lifecycle", events.states() == ["running"], "ongoing output refreshes watchdog instead of hard timeout")
        made.interrupt("codex-watchdog-busy")
        finish()
        # Pending request dies with its connection generation and cannot be answered again.
        events, _, finish = _start(made, sid("chat"), "ASK", name="codex-pending-crash")
        pending = events.wait(lambda row: row["type"] == "run.state" and row["state"] == "waiting_input")["pendingRequest"]
        made._conn.kill()
        finish()
        try:
            made.answer("codex-pending-crash", pending["requestId"], {"decision": "approve", "answers": {"color": "Green"}})
        except CodexError as error:
            gate("providers.codex.answer", events.states()[-1] == "interrupted" and error.code in {"request_not_pending", "run_not_active", "request_expired"}, "connection loss expires pending request and old generation answer")
        else:
            require(False, "providers.codex.answer", "expired request accepted")
        crash = live.adapter()
        before = len(live.records("turn/start"))
        events, _, finish = _start(crash, sid("chat"), "CRASH", name="codex-crash")
        finish()
        gate("providers.codex.lifecycle", events.states()[-1] == "interrupted" and len(live.records("turn/start"))-before == 1 and "not resent" in next(row for row in reversed(events.rows) if row["type"] == "run.state")["error"].lower(), "actual process exit interrupts active turn and never resends")
        made = live.adapter()
        sink = _Events()
        made.set_event_sink(sink)
        made.goal(sid("chat"), "set", "LOOP finite scratch")
        running = sink.wait(lambda row: row["type"] == "run.state" and row["state"] == "running")
        sink.wait(lambda row: row["type"] == "item.delta")
        gate("providers.codex.goal", made.live_status()[sid("chat")] == ("working", "neyvia") and made.goal(sid("chat"), "clear") is None, "goal-started turn adopted into sink; goal clear permitted mid-turn")
        made.interrupt(running["runId"])
        sink.wait(lambda row: row["type"] == "run.state" and row["runId"] == running["runId"] and row["state"] == "interrupted")
        chain = _Events()
        made.set_event_sink(chain)
        made.goal(sid("chat"), "set", "CHAIN finite scratch")
        end = time.monotonic()+8
        while len({row["runId"] for row in chain.rows if row["type"] == "run.state" and row["state"] == "completed"}) < 2 and time.monotonic() < end:
            time.sleep(.03)
        gate("providers.codex.goal", len({row["runId"] for row in chain.rows if row["type"] == "run.state" and row["state"] == "completed"}) == 2 and [row["item"]["data"]["text"] for row in chain.rows if row["type"] == "item.updated" and row["item"]["kind"] == "assistant"] == ["Hello from the fake."]*2, "two goal-chained turns each streamed and completed once")
        made.goal(sid("chat"), "clear")
        rendezvous, results = threading.Barrier(2), []
        def send(n):
            rendezvous.wait()
            try:
                made.start_turn(sid("chat"), "LONG", TurnOptions(), cwd=None, run_id=f"codex-race-{n}", emit=_Events())
                results.append("ran")
            except CodexError as error:
                results.append(error.code)
        before = len(live.records("turn/start"))
        workers = [threading.Thread(target=send, args=(n,), daemon=True) for n in (1, 2)]
        for worker in workers:
            worker.start()
        end = time.monotonic()+3
        while not results and time.monotonic() < end:
            time.sleep(.01)
        # Wait for the accepted send to reach the peer before observing exact RPC count.
        end = time.monotonic()+3
        while len(live.records("turn/start")) == before and time.monotonic() < end:
            time.sleep(.01)
        for n in (1, 2):
            made.interrupt(f"codex-race-{n}")
        for worker in workers:
            worker.join(6)
        gate("providers.codex.lifecycle", sorted(results) == ["ran", "session_busy"] and len(live.records("turn/start"))-before == 1, "simultaneous sends atomically register exactly one actual turn")
    finally:
        live.close()
    return identities, checks


def _codex_catalogue(root):
    from .connected_sessions.codex import CodexAdapter
    from .connected_sessions.codex_rpc import CodexError
    identities, checks = set(), []
    os.environ["CODEX_HOME"] = str(root / "codex-home")
    def gate(identity, condition, evidence):
        require(condition, identity, evidence)
        identities.add(identity)
        checks.append({"contract": identity, "ok": True, "evidence": evidence})
    def model(name, **fields):
        return {"id": name, "model": name, "displayName": name.upper(), "hidden": False, "isDefault": False, "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}], "defaultReasoningEffort": "low", "inputModalities": ["text", "image"], **fields}
    def plugin(name, **fields):
        return {"id": name+"@scratch", "name": name, "installed": True, "enabled": True, "availability": "AVAILABLE", "authPolicy": "ON_INSTALL", "interface": {"displayName": name}, **fields}
    world = {"threads": [{"id": "chat", "name": "Scratch catalogue", "cwd": str(root), "model": "session-model", "reasoningEffort": "medium", "updatedAt": int(time.time())-7200}], "models": [model("m-a", isDefault=True), model("m-b"), model("m-hidden", hidden=True), model("m-c"), model("m-d")], "config": {"model": "m-b", "model_reasoning_effort": "high", "approval_policy": "on-request", "sandbox_mode": "workspace-write"}, "skills": [{"name": "zeta", "description": "last", "enabled": True, "scope": "user", "interface": {"displayName": "Zeta"}}, {"name": "alpha", "description": "first", "enabled": False, "scope": "repo"}], "plugins": [{"name": "scratch-market", "plugins": [plugin("Gmail"), plugin("GitHub", source={"type": "remote"}), plugin("Off", enabled=False), plugin("Admin", availability="DISABLED_BY_ADMIN"), plugin("Broken"), plugin("OAuth"), plugin("Docs", authPolicy="ON_USE"), plugin("notinstalled", installed=False)]}], "mcp": [{"name": "codex_apps", "authStatus": "bearerToken", "tools": {"gmail.search": {"_meta": {"connector_name": "Gmail", "connector_id": "scratch-gmail"}}}}, {"name": "broken", "pluginId": "Broken@scratch", "runtimeStatus": "failed", "authStatus": "oAuth"}, {"name": "oauth", "pluginId": "OAuth@scratch", "runtimeStatus": "authenticationRequired", "authStatus": "notLoggedIn"}, {"name": "standalone", "runtimeStatus": "connected", "authStatus": "bearerToken", "tools": {"scratch": {}}}], "apps_error": True}
    confined = _CodexWorld(root / "codex-catalogue", world)
    try:
        made = confined.adapter()
        options = made.options()
        gate("providers.codex.options", [row["id"] for row in options["models"]] == ["m-a", "m-b", "m-c", "m-d"] and (options["models"][0]["label"], options["models"][0]["efforts"], options["models"][0]["default"], options["models"][0]["defaultEffort"], options["models"][0]["images"]) == ("M-A", ["low", "high"], True, "low", True) and options["defaults"] == {"model": "m-b", "effort": "high", "permissionMode": "auto"}, "real paged model catalogue hides hidden models and preserves efforts/images/default configuration")
        gate("providers.codex.options", [row["name"] for row in options["skills"]] == ["alpha", "zeta"] and options["skills"][1]["label"] == "Zeta" and not options["skills"][0]["enabled"], "real skills sorted and labelled with disabled flag preserved")
        scoped = made.options("external:codex:proofcodex01:chat")
        gate("providers.codex.options", scoped["defaults"]["model"] == "session-model" and confined.records("skills/list")[-1]["params"] == {"cwds": [str(root)]}, "session options request actual session folder and prefer persisted model")
        states = {row["label"]: row["state"] for row in options["plugins"]}
        gate("providers.codex.integrations", all(states.get(name) == state for name, state in {"Gmail": "connected", "GitHub": "needs_sign_in", "Off": "disabled", "Admin": "disabled", "Broken": "error", "OAuth": "needs_sign_in", "Docs": "connected", "standalone": "connected"}.items()) and "notinstalled" not in states and {row["name"]: row["state"] for row in options["mcpServers"]}["oauth"] == "needs_sign_in", "actual installed plugins/MCP/tool evidence project connected/auth/disabled/error states")
        gate("providers.codex.options", "apps" in options["errors"] and len(options["errors"]["apps"]) < 400 and "<html>" not in json.dumps(options["errors"]) and bool(options["models"]), "failed apps section reported with bounded sanitized error while other sections survive")
        login = made.plugin_login("plugin:OAuth@scratch")
        fallback = made.plugin_login("plugin:GitHub@scratch")
        gate("providers.codex.plugin_login", login["ok"] and login["authUrl"].startswith("https://auth.example.test/login") and confined.records("mcpServer/oauth/login")[-1]["params"] == {"name": "oauth"} and "token" not in json.dumps(login).lower() and fallback["ok"] is False and fallback["authUrl"] is None, "plugin OAuth returns navigation URL, no token; missing login route honestly unavailable")
        gate("providers.codex.auth", made.auth(force=True) == {"kind": "subscription", "label": "your ChatGPT Plus plan"} and "someone@example.test" not in json.dumps(options), "actual account response projects public subscription plan without email")
        gate("providers.codex.login", made.sign_in()["state"] == "signed-in" and not confined.records("account/login/start"), "existing subscription does not restart sign-in")
    finally:
        confined.close()
    connector_world = {**world, "apps_error": False, "apps": [{"name": "GitHub", "isAccessible": False, "isEnabled": True, "installUrl": "https://chatgpt.example.test/connect/github"}]}
    confined = _CodexWorld(root / "codex-connector", connector_world)
    try:
        made = confined.adapter()
        options = made.options()
        login = made.plugin_login("plugin:GitHub@scratch")
        gate("providers.codex.plugin_login", next(row for row in options["plugins"] if row["label"] == "GitHub")["state"] == "needs_sign_in" and login["authUrl"] == "https://chatgpt.example.test/connect/github", "inaccessible connector app supplies actual install URL as login route")
    finally:
        confined.close()
    signed_out = _CodexWorld(root / "codex-sign-in", {"account": None})
    try:
        made = signed_out.adapter()
        started = made.sign_in()
        gate("providers.codex.login", made.auth(force=True)["kind"] == "signed-out" and (started["state"], started["userCode"]) == ("code", "ABCD-1234") and started["verificationUrl"].startswith("https://auth.openai.com/") and signed_out.records("account/login/start")[-1]["params"] == {"type": "chatgptDeviceCode"}, "synthetic signed-out account requests device code over real RPC and returns HTTPS navigation")
    finally:
        signed_out.close()
    # Every section can fail at the actual transport while the stable permissions remain useful.
    failed = CodexAdapter(command=[sys.executable, "-c", "raise SystemExit(3)"], device={"deviceId": "proofcodex01", "deviceName": "Scratch PC"}, state_root=root)
    try:
        failed._conn._max_start_wait = .01
        options = failed.options()
        gate("providers.codex.options", options["models"] == [] and [row["id"] for row in options["permissionModes"]] == ["ask", "auto", "full"] and "models" in options["errors"], "actual crashing transport returns section errors alongside usable static permission choices")
    finally:
        failed.close()
    return identities, checks


def _scratch(root):
    from .proof_credential_guard import install
    root = Path(root).resolve()
    workspace = next((parent.parent for parent in root.parents
                      if parent.name == ".agent_control" and root.is_relative_to(parent / "proofs")), None)
    if workspace is None:
        raise ValueError("Provider proof must belong to the disposable .agent_control/proofs subtree")
    install(workspace)
    identities, checks = _helpers(root)
    live_ids, live_checks = _claude_protocol(root)
    identities.update(live_ids)
    transcript_ids, transcript_checks = _claude_transcripts(root)
    identities.update(transcript_ids)
    terminal_ids, terminal_checks = _terminal_protocol(root)
    identities.update(terminal_ids)
    catalogue_ids, catalogue_checks = _claude_catalogue(root)
    identities.update(catalogue_ids)
    agent_ids, agent_checks = _claude_agent_transcripts(root)
    identities.update(agent_ids)
    codex_ids, codex_checks = _codex_protocol(root)
    identities.update(codex_ids)
    adverse_ids, adverse_checks = _codex_adverse(root)
    identities.update(adverse_ids)
    codex_catalogue_ids, codex_catalogue_checks = _codex_catalogue(root)
    identities.update(codex_catalogue_ids)
    return {"ok": True, "contracts": sorted(identities), "workflows": [{"procedure": "provider-helpers", "checks": checks}, {"procedure": "claude-protocol", "checks": live_checks}, {"procedure": "claude-transcripts", "checks": transcript_checks}, {"procedure": "terminal-protocol", "checks": terminal_checks}, {"procedure": "claude-catalogue", "checks": catalogue_checks}, {"procedure": "claude-agent-transcripts", "checks": agent_checks}, {"procedure": "codex-protocol", "checks": codex_checks}, {"procedure": "codex-adverse", "checks": adverse_checks}, {"procedure": "codex-catalogue", "checks": codex_catalogue_checks}], "boundary": "Confined protocol peers; no account, model, existing service or credential access; the terminal protocol peer uses pipes rather than proving ConPTY."}


if __name__ == "__main__":
    print(json.dumps(_scratch(Path(sys.argv[2]))))
