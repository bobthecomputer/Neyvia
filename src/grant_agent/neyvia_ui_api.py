"""HTTP boundary for the UI bus, workspace tools, app registry and Night Shift."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs

from .ui_command_bus import bus_for
from .neyvia_workspace_tools import workspace_for


def bind_backend(backend):
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(backend.root)
    service = workspace_for(backend.root, backend)
    service.bus.receivers_enabled = True
    if service._usage_broker is None:
        service.broker()
    service.start_timers()
    try:
        from .claude_code_host import warm
        warm(backend.root)  # the Claude Code mod's caches are ready before its first request
    except Exception:  # noqa: BLE001
        pass


def serve(backend, handler, parsed, method="GET") -> bool:
    path = parsed.path
    if not (path.startswith(("/api/ui/", "/api/nightshift/", "/api/apps/pdf/")) or path == "/api/apps"):
        return False
    from .web_backend import _json_response, _read_json_body
    if path.startswith("/api/ui/scroll/download/") and method == "GET":
        from .neyvia_scroll import download
        download(backend.root, handler, parsed)
        return True
    if path == "/api/ui/remote" or path.startswith("/api/ui/remote/"):
        from .neyvia_remote import serve_http
        serve_http(backend, handler, parsed, method)
        return True
    if path.startswith("/api/ui/devices"):
        from .neyvia_devices import bind_peer_backend
        bind_peer_backend(backend, handler)
    if path.startswith("/api/ui/mobile-preview/"):
        # A phone preview page: its own token is the capability, the page runs sandboxed.
        from .neyvia_mobile_studio import serve_preview
        serve_preview(backend.root, handler, parsed, method)
        return True
    if path.startswith("/api/ui/artifact/") and method == "GET":
        # An HTML artifact in the artifact pane: its own token is the capability, the page runs sandboxed.
        from .neyvia_panes import serve_artifact
        serve_artifact(backend.root, handler, parsed)
        return True
    if path in {"/api/ui/browser", "/api/ui/browser/runtime"}:
        from .neyvia_browser import serve_http
        serve_http(backend, handler, parsed, method)
        return True
    if path.startswith("/api/ui/claude-code/mod/"):
        from .claude_code_host import serve_http  # the Claude Code mod: its own fast path (cached session, no per-request setup)
        serve_http(backend, handler, parsed, method)
        return True
    session = backend.authenticated_session(handler)
    if not session:
        _json_response(handler, 401, {"ok": False, "loginRequired": True})
        return True
    from .source_marketplace import authorize_app
    try:
        authorize_app(backend, handler)
    except ValueError as exc:
        _json_response(handler, 403, {"ok": False, "error": str(exc)})
        return True
    if (method == "POST" or path in {"/api/ui/approvals", "/api/ui/attention", "/api/ui/sidebar"}) and str(session.get("username") or "").casefold() != backend.username.casefold():
        _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required"})
        return True
    if path == "/api/ui/agentview" or path.startswith("/api/ui/agentview/"):
        from .neyvia_agentview import serve_http
        serve_http(backend, handler, parsed, method)
        return True
    if path == "/api/ui/cua" or path.startswith("/api/ui/cua/"):
        from .neyvia_cua import serve_http
        serve_http(backend, handler, parsed, method)
        return True
    if path.startswith("/api/ui/dictation/"):
        # Raw audio bodies (16 kHz mono 16-bit PCM), proxied to the local speech engine.
        from .neyvia_dictation import serve_http
        serve_http(backend, handler, parsed, method)
        return True
    if path == '/api/apps/pdf/raster' and method == 'POST':
        # Raw PDF bytes use the same authenticated owner boundary as tools.
        # Handle before the JSON-body parser; no network or path lookup here.
        try:
            from .neyvia_pdf_api import serve_raster
            serve_raster(handler, parsed)
        except (ValueError, RuntimeError, ImportError) as exc:
            _json_response(handler, 400, {'ok': False, 'error': str(exc)})
        return True
    bind_backend(backend)
    bus = bus_for(backend.root)
    try:
        body = _read_json_body(handler) if method == "POST" else {}
        if path in {"/api/ui/settings", "/api/ui/settings/setup"}:
            from .neyvia_settings import handle_command
            command = {
                ("/api/ui/settings", "GET"): "settings_get_command",
                ("/api/ui/settings", "POST"): "settings_update_command",
                ("/api/ui/settings/setup", "POST"): "settings_setup_command",
            }.get((path, method))
            if command is None:
                raise ValueError("Unsupported Settings request")
            result = handle_command(backend, command, body)
            _json_response(handler, 200, {"ok": True, "data": result})
            return True
        elif path == "/api/ui/devices/raw" and method == "GET":
            from .neyvia_devices import serve_raw
            serve_raw(backend.root, handler, parsed)
            return True
        if path == "/api/apps/pdf/file" and method == "GET":
            from .neyvia_pdf_api import serve_file
            serve_file(backend.root, handler, parsed)
            return True
        if path == "/api/ui/files/raw" and method == "GET":
            from .neyvia_files_tools import serve_raw
            serve_raw(backend.root, handler, parsed)
            return True
        if path == "/api/ui/image-file" and method == "GET":
            from .neyvia_image_tools import serve_file
            serve_file(workspace_for(backend.root), handler, parsed)
            return True
        if path == "/api/ui/panes/terminal" and method == "GET":
            from .neyvia_panes import stream_terminal
            stream_terminal(handler, parsed)
            return True
        if path == "/api/ui/events" and method == "GET":
            if (parse_qs(parsed.query).get("poll") or [""])[0] == "1":
                cursor = int((parse_qs(parsed.query).get("cursor") or ["0"])[0])
                if cursor < 0:
                    raise ValueError("cursor must be nonnegative")
                rows = bus.since(cursor)
                _json_response(handler, 200, {"ok": True, "data": {"events": rows}})
                return True
            stream(bus, handler, parsed)
            return True
        if path == "/api/ui/autopilot":
            from .neyvia_autopilot import request
            if str(session.get("username") or "").casefold() != backend.username.casefold():
                _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required"})
                return True
            if body.get("_expectedStateRoot") and Path(body["_expectedStateRoot"]).resolve() != backend.root.resolve():
                _json_response(handler, 409, {"ok": False, "error": "Autopilot belongs to another workspace"})
                return True
            query = parse_qs(parsed.query)
            operation = body.get("operation", "start") if method == "POST" else "get" if query.get("runId") else "list"
            arguments = {k: v for k, v in body.items() if k not in {"operation", "_expectedStateRoot"}}
            if method == "GET" and query.get("runId"):
                arguments["runId"] = query["runId"][0]
            if method == "POST":
                arguments["background"] = True
            result = request(backend, operation, arguments)
        elif path in {"/api/ui/outputs", "/api/ui/navigation"}:
            from .neyvia_outputs import COMMANDS, call, failure
            expected = body.get("_expectedStateRoot")
            if expected and Path(expected).resolve() != backend.root.resolve():
                result = failure("conflict", "The output service belongs to a different workspace")
            elif path == "/api/ui/navigation" and method == "POST":
                result = call(workspace_for(backend.root, backend), "app.open", body)
            elif path == "/api/ui/outputs":
                query = parse_qs(parsed.query)
                args = {key: value[0] for key, value in query.items()} if method == "GET" else body.get("args", {})
                if method == "GET":
                    for key in ("limit", "offset"):
                        if key in args:
                            args[key] = int(args[key])
                op = "list" if method == "GET" else body.get("op")
                if "artifact_" + str(op) + "_command" not in COMMANDS:
                    raise ValueError("Choose publish, list, get or open")
                result = call(workspace_for(backend.root, backend), "artifact." + op, args)
            else:
                raise ValueError("Use POST to open an app")
            if result.get("ok") is False:
                _json_response(handler, 409 if result.get("status") == "conflict" else 404 if result.get("status") == "missing" else 400,
                               {"ok": False, "error": result.get("error"), "data": result})
                return True
        elif path == "/api/ui/sidebar":
            from .neyvia_sidebar import handle_command
            if method == "GET":
                query = parse_qs(parsed.query)
                body = {key: int(query[key][0]) for key in ("limit", "offset") if key in query}
                if "query" in query: body["query"] = query["query"][0]
                command = "sidebar_state_command"
            else:
                command = body.get("command", "sidebar_state_command")
            result = handle_command(backend, command, body)
        elif path == "/api/ui/voice/commands" and method == "GET":
            from .neyvia_voice import catalog
            result = catalog()
        elif path == "/api/ui/voice" and method == "POST":
            from .neyvia_voice import COMMANDS, handle_command
            expected = body.get("_expectedStateRoot")
            if expected and Path(expected).resolve() != backend.root.resolve():
                _json_response(handler, 409, {"ok": False, "error": "Voice service belongs to a different workspace"})
                return True
            command = body.get("command", "voice_command_command")
            if command not in COMMANDS:
                raise ValueError("Unknown voice command")
            result = handle_command(backend, command, body, owner=True)
        elif path == "/api/ui/ack" and method == "POST":
            result = bus.ack(body, str(session.get("username")) + ":" + str(body.get("clientId") or "default"))
        elif path == "/api/ui/state" and method == "GET":
            result = bus.snapshot()
        elif path == "/api/ui/approvals" and method == "GET":
            with bus.connect() as db:
                approvals = [(row["key"][9:], json.loads(row["value"])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
            history = (parse_qs(parsed.query).get("includeResolved") or [""])[0] == "1"
            result = {"requests": [{"id": identity, "status": "approved" if bus.get("grant:" + row["key"], False) else
                                   "denied" if bus.get("denied:" + row["key"], False) else "pending",
                                   **{key: row.get(key) for key in ("description", "details")}}
                                   for identity, row in approvals if history or not (bus.get("grant:" + row["key"], False) or bus.get("denied:" + row["key"], False))]}
        elif path == "/api/ui/analytics" and method == "GET":
            from .neyvia_analytics import report
            result = report(workspace_for(backend.root).broker())
        elif path == "/api/ui/usage" and method == "GET":
            from .usage_report import report as usage_report
            result = usage_report(backend.root, (parse_qs(parsed.query).get("range") or ["week"])[0])
        elif path == "/api/ui/agents/overview" and method == "GET":
            from .agents_overview import overview
            result = overview(workspace_for(backend.root, backend))
        elif path == "/api/ui/attention" and method == "GET":
            from .neyvia_attention import call
            query = parse_qs(parsed.query)
            args = {key: int(query[key][0]) for key in ("limit", "offset") if key in query}
            if "recentHours" in query:
                args["recentHours"] = float(query["recentHours"][0])
            result = call(workspace_for(backend.root), args)
        elif path == "/api/ui/laya" and method == "GET":
            from .laya_ledger import report as laya_report
            result = laya_report(backend.root)
        elif path == "/api/ui/laya" and method == "POST":
            # Start or restart the backend-owned LAYA service (the pane's Start / Try again button).
            if body.get("operation") != "restart":
                raise ValueError("Use operation restart")
            from .laya_host import restart as restart_laya
            from .laya_ledger import report as laya_report
            restart_laya(backend.root)
            result = laya_report(backend.root)
        elif path == "/api/ui/connections":
            from .neyvia_connections import request as connections_request
            if method == "POST" and str(session.get("username") or "").casefold() != backend.username.casefold():
                _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required"})
                return True
            result = connections_request(backend, workspace_for(backend.root), body, method)
        elif path == "/api/ui/runtime":
            from .neyvia_runtime import request
            result = request(workspace_for(backend.root), body, method)
        elif path == "/api/ui/parallel" and method in {"GET", "POST"}:
            from .neyvia_parallel import call
            query = parse_qs(parsed.query)
            operation = body.get("operation", "state") if method == "POST" else "state"
            args = {k: v for k, v in body.items() if k not in {"operation", "approved"}} if method == "POST" else ({"run": query["run"][0]} if query.get("run") else {})
            result = call(workspace_for(backend.root, backend), "parallel." + operation, args,
                          owner_approved=method == "POST" and operation == "finish" and body.get("approved") is True,
                          pane=method == "GET")
        elif path == "/api/ui/comments" and method in {"GET", "POST"}:
            from .neyvia_comments import call
            query = parse_qs(parsed.query)
            args = {key: values[0] for key, values in query.items()} if method == "GET" else {key: value for key, value in body.items() if key != "op"}
            if method == "GET":
                for key in ("limit", "offset"):
                    if key in args:
                        args[key] = int(args[key])
                if "includeDeleted" in args:
                    if args["includeDeleted"] not in {"0", "1"}:
                        raise ValueError("includeDeleted must be 0 or 1")
                    args["includeDeleted"] = args["includeDeleted"] == "1"
            result = call(workspace_for(backend.root, backend), "comments." + (body.get("op", "") if method == "POST" else "list"), args, source="ui")
        elif path == "/api/ui/conductor":
            from .neyvia_conductor import request
            query = parse_qs(parsed.query)
            operation = body.get("operation", "list") if method == "POST" else "get" if query.get("id") else "list"
            if method == "GET":
                body = {"id": query["id"][0]} if query.get("id") else {key: int(query[key][0]) for key in ("offset", "limit") if query.get(key)}
            result = request(backend.root, operation, body)
        elif path == "/api/ui/missions":
            from .neyvia_missions import call
            from .nightshift import nightshift_for
            operation = body.get("operation") if method == "POST" else "list"
            if operation not in {"list", "create", "control"}:
                raise ValueError("Use a mission create or control operation")
            result = call(nightshift_for(backend.root, backend), "mission." + operation, body)
        elif path == "/api/ui/manuals" and method == "GET":
            from .neyvia_manuals import index
            result = index(backend.root / ".neyvia")
        elif path == "/api/ui/lab" and method == "GET":
            from .neyvia_lab_board import state
            result = state(backend.root)
        elif path in {"/api/ui/scroll", "/api/ui/scroll/state"} and method in {"GET", "POST"}:
            from .neyvia_scroll import call
            query = parse_qs(parsed.query)
            if body.get("_expectedStateRoot") and Path(body["_expectedStateRoot"]).resolve() != backend.root.resolve():
                _json_response(handler, 409, {"ok": False, "error": "Scroll Study belongs to another workspace"})
                return True
            operation = body.get("operation", "state") if method == "POST" else "state"
            args = {k: v for k, v in body.items() if k not in {"operation", "_expectedStateRoot"}} if method == "POST" else ({"pack": query["pack"][0]} if query.get("pack") else {})
            result = call(workspace_for(backend.root, backend), "scroll." + operation, args)
        elif path == "/api/ui/evolver" and method in {"GET", "POST"}:
            from .neyvia_evolver import call
            query = parse_qs(parsed.query)
            if body.get("_expectedStateRoot") and Path(body["_expectedStateRoot"]).resolve() != backend.root.resolve():
                _json_response(handler, 409, {"ok": False, "error": "Evolver belongs to another workspace"})
                return True
            operation = body.get("operation", "state") if method == "POST" else "state"
            args = {key: value for key, value in body.items() if key not in {"operation", "_expectedStateRoot"}} if method == "POST" else ({"domain": query["domain"][0]} if query.get("domain") else {})
            result = call(backend.root, "evolver." + operation, args)
        elif path == "/api/ui/app-state" and method == "POST":
            from .neyvia_pdf_tools import report_pdf_state
            if body.get("app") in {"game-dev", "godot", "unity", "roblox", "asset-checks", "playtest"}:
                from .neyvia_gamedev import report_state
                result = report_state(backend.root, body.get("state"), str(body.get("clientId") or "default"))
            elif body.get("app") == "image-studio":
                from .neyvia_image_tools import report_state
                result = report_state(workspace_for(backend.root), body.get("state"), str(body.get("clientId") or "default"))
            elif body.get("app") == "mobile-studio":
                from .neyvia_mobile_studio import report_state
                result = report_state(workspace_for(backend.root), body.get("state"), str(body.get("clientId") or "default"))
            elif body.get("app") == "pdf":
                result = report_pdf_state(backend.root, body.get("state"), str(body.get("clientId") or "default"))
            elif body.get('app') == 'shell':
                from .cl.fixcl4_render_effects import report_state
                result = report_state(backend.root, body.get('state'), str(body.get('clientId') or 'default'))
            elif body.get("app") == "browser":
                from .neyvia_browser import report_state
                result = report_state(backend.root, body.get("state"), str(body.get("clientId") or "default"))
            else:
                raise ValueError("Unknown app state")
        elif path == "/api/ui/devices" and method == "POST":
            from .neyvia_devices import call_devices
            result = call_devices(backend.root, str(body.get("op") or ""), body.get("args") or {}, source="ui")
        elif path in {"/api/ui/notes", "/api/ui/files"} and method == "POST":
            # The Notes and Files apps' user side: the same functions as neyvia.notes.* / neyvia.files.*.
            from .neyvia_files_tools import call_files
            from .neyvia_notes_tools import call_notes
            call = call_notes if path == "/api/ui/notes" else call_files
            result = call(backend.root, str(body.get("op") or ""), body.get("args") or {}, source="ui")
            if result.get("ok") is False:
                _json_response(handler, 409 if result.get("status") == "conflict" else 400,
                               {"ok": False, "error": result.get("error") or result.get("status"), "data": result})
                return True
        elif path == "/api/ui/panes" and method == "POST":
            # The file, artifact and terminal panes (pane.show): editor, sandboxed artifacts, live terminals.
            from .neyvia_panes import call_panes
            result = call_panes(backend.root, str(body.get("op") or ""), body.get("args") or {})
            if result.get("ok") is False:
                _json_response(handler, 409 if result.get("status") == "conflict" else 404 if result.get("status") == "missing" else 400,
                               {"ok": False, "error": result.get("error") or result.get("status"), "data": result})
                return True
        elif path == "/api/ui/approve" and method == "POST":
            result = workspace_for(backend.root).approve(str(body.get("id") or ""))
        elif path == "/api/ui/decline" and method == "POST":
            result = workspace_for(backend.root).decline(str(body.get("id") or ""))
        elif path == "/api/ui/tools/call" and method == "POST":
            if body.get("_expectedStateRoot") and Path(body["_expectedStateRoot"]).resolve() != backend.root.resolve():
                _json_response(handler, 409, {"ok": False, "error": "Tool service belongs to another workspace"})
                return True
            name = str(body.get("tool") or "")
            if name == "neyvia.cl" or name.startswith("neyvia.browser.") or name == "neyvia.perception.observe" and (body.get("arguments") or {}).get("source", {}).get("tabId"):
                from .neyvia_browser import trusted_origin
                if not trusted_origin(handler):
                    _json_response(handler, 403, {"ok": False, "error": "CL and browser tools require the configured owner shell"})
                    return True
            if not name.startswith("neyvia."):
                raise ValueError("Choose a neyvia.* tool")
            from .neyvia_cl import call_owner
            result = call_owner(workspace_for(backend.root, backend), name,
                body.get("arguments") or {}, session=session, owner=backend.username)
        elif path == "/api/ui/tools" and method == "GET":
            # The neyvia.* catalog with schemas, for the Claude Code plugin's MCP server (plugins/neyvia).
            from .native_tools import NativeToolRegistry
            result = {"tools": [{"name": row["name"], "description": row["description"], "inputSchema": row["inputSchema"],
                                 "mutability": row.get("mutability_class"), "available": row["available"]}
                                for row in NativeToolRegistry(backend.root).list_tools(include_schemas=True, prefix="neyvia.")]}
        elif path == "/api/ui/claude-code/report" and method == "POST":
            from .claude_code_mods import record_report
            result = record_report(bus, body)
        elif path == "/api/ui/tools/preflight" and method == "POST":
            from .neyvia_image_approval import preflight
            name = str(body.get("tool") or "").removeprefix("neyvia.")
            result = preflight(workspace_for(backend.root), name, body.get("arguments") or {}) or {"ok": True, "ready": True}
        elif path == "/api/apps" and method == "GET":
            registry = Path(__file__).resolve().parents[2] / "config" / "neyvia_apps.json"
            result = json.loads(registry.read_text(encoding="utf-8"))
        elif path.startswith("/api/nightshift/"):
            from .nightshift import nightshift_for
            result = nightshift_for(backend.root, backend).request(path.rsplit("/", 1)[1], body, method)
        else:
            _json_response(handler, 404, {"ok": False, "error": "Unknown UI API route"})
            return True
        ok = result.get("ok", True) if path in {"/api/ui/tools/call", "/api/ui/sidebar"} else True
        _json_response(handler, 200, {"ok": ok, "data": result,
                                     **({"error": result.get("error") or result.get("status")} if not ok else {})})
    except (ValueError, KeyError, TypeError) as exc:
        output_error = path in {"/api/ui/outputs", "/api/ui/navigation"}
        _json_response(handler, 400 if output_error else getattr(exc, "status", 400),
                       {"ok": False, "error": str(exc), **({"data": {"ok": False, "status": getattr(exc, "status", "invalid"), "error": str(exc)}} if output_error else {})})
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass
    except Exception as exc:
        from .connected_sessions.broker import ConnectedError
        _json_response(handler, exc.status if isinstance(exc, ConnectedError) else 500,
                       {"ok": False, "error": str(exc)[:500], **({"code": exc.code} if isinstance(exc, ConnectedError) else {})})
    return True


def stream(bus, handler, parsed):
    from .connected_sessions.api import _client_gone
    from .web_backend import _apply_security_headers, _send_cors_headers
    query = parse_qs(parsed.query)
    cursor = int(handler.headers.get("Last-Event-ID") or (query.get("cursor") or ["0"])[0])
    if cursor < 0:
        raise ValueError("cursor must be nonnegative")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    _send_cors_headers(handler)
    _apply_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(b": connected\n\n")
    handler.wfile.flush()
    heartbeat = time.monotonic()
    with bus.receiver(lambda: not _client_gone(handler)):
        while not _client_gone(handler):
            # Query and sleep under the notification lock: an in-process emit
            # cannot notify between an empty read and starting the wait.
            with bus.changed:
                rows = bus.since(cursor)
                if not rows:
                    bus.changed.wait(1)  # also catches separate-process emits
                    rows = bus.since(cursor)
            for row in rows:
                handler.wfile.write(("id: " + row["id"] + "\ndata: " + json.dumps(row) + "\n\n").encode())
                cursor = int(row["id"])
            if not rows and time.monotonic() - heartbeat >= 15:
                handler.wfile.write(b": heartbeat\n\n")
                heartbeat = time.monotonic()
            handler.wfile.flush()
