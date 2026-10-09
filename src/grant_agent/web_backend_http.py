"""Authenticated HTTP transport for the public backend facade.

The facade is an explicit dependency so request handlers retain late-bound
response, authentication and policy collaborators while owning their transport.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .web_backend import FluxioWebBackend


def make_handler(backend: FluxioWebBackend, *, _facade) -> type[BaseHTTPRequestHandler]:
    class Handler(_facade.BaseHTTPRequestHandler):
        def do_PUT(self) -> None:  # noqa: N802
            parsed = _facade.urlparse(self.path)
            if parsed.path.startswith("/api/peer/v1/"):
                from .neyvia_devices import serve_peer
                serve_peer(backend, self, parsed, "PUT")
            else:
                _facade._json_response(self, 404, {"ok": False, "error": "Unknown API route"})

        protocol_version = "HTTP/1.1"

        def do_OPTIONS(self) -> None:  # noqa: N802
            parsed = _facade.urlparse(self.path)
            if parsed.path.startswith("/api/ui/mobile-preview/"):
                from .neyvia_mobile_studio import serve_preview
                serve_preview(backend.root, self, parsed, "OPTIONS")
                return
            _facade._json_response(self, 204, {})

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = _facade.urlparse(self.path)
            if parsed.path.startswith("/api/delivery-receipts"):
                if not backend.is_authenticated(self):
                    _facade._json_response(
                        self,
                        401,
                        {
                            "ok": False,
                            "error": f"{_facade.PRODUCT_NAME} login is required.",
                            "loginRequired": True,
                        },
                    )
                    return
                query = _facade.parse_qs(parsed.query)
                payload = _facade._read_json_body(self)
                parts = [_facade.unquote(part) for part in parsed.path.split("/") if part]
                receipt_id = ""
                if len(parts) >= 3 and parts[2] not in {"ack", "acknowledge"}:
                    receipt_id = parts[2]
                receipt_id = str(
                    payload.get("receiptId")
                    or payload.get("receipt_id")
                    or (query.get("receiptId") or query.get("receipt_id") or query.get("id") or [""])[0]
                    or receipt_id
                ).strip()
                if not receipt_id:
                    _facade._json_response(self, 400, {"ok": False, "error": "receiptId is required."})
                    return
                if not _facade.acknowledge_delivery_receipt(backend.root, receipt_id):
                    _facade._json_response(
                        self,
                        404,
                        {"ok": False, "error": "Delivery receipt was not acknowledged."},
                    )
                    return
                _facade._json_response(
                    self,
                    200,
                    {"ok": True, "data": {"receiptId": receipt_id, "status": "acknowledged"}},
                )
                return
            _facade._json_response(self, 404, {"ok": False, "error": "Unknown API route"})

        def do_GET(self) -> None:  # noqa: N802
            _facade._extend_io_timeout(self)
            parsed = _facade.urlparse(self.path)
            if parsed.path.startswith("/api/peer/v1/"):
                from .neyvia_devices import serve_peer
                serve_peer(backend, self, parsed, "GET")
                return
            openrouter_callback_prefix = "/api/openrouter/oauth/callback/"
            if parsed.path.startswith(openrouter_callback_prefix):
                session_id = _facade.unquote(parsed.path[len(openrouter_callback_prefix) :])
                query = _facade.parse_qs(parsed.query)
                try:
                    result = backend.complete_openrouter_oauth_callback(
                        session_id=session_id,
                        code=(query.get("code") or [""])[0],
                    )
                    _facade._html_response(
                        self,
                        200,
                        (
                            "<!doctype html><meta charset='utf-8'>"
                            "<title>OpenRouter connected</title>"
                            "<main style='font:16px system-ui;max-width:38rem;margin:12vh auto;padding:2rem'>"
                            "<h1>OpenRouter connected</h1>"
                            f"<p>{_facade.html.escape(str(result['message']))}</p>"
                            "</main>"
                        ),
                    )
                except PermissionError as exc:
                    _facade._html_response(
                        self,
                        403,
                        (
                            "<!doctype html><meta charset='utf-8'><title>OpenRouter connection rejected</title>"
                            "<h1>OpenRouter connection rejected</h1>"
                            f"<p>{_facade.html.escape(str(exc))}</p>"
                        ),
                    )
                except Exception as exc:
                    _facade._html_response(
                        self,
                        400,
                        (
                            "<!doctype html><meta charset='utf-8'><title>OpenRouter connection failed</title>"
                            "<h1>OpenRouter connection failed</h1>"
                            f"<p>{_facade.html.escape(str(exc))}</p>"
                        ),
                    )
                return
            if parsed.path.startswith("/updates/desktop/"):
                backend.serve_desktop_update(self, _facade.unquote(parsed.path[len("/updates/desktop/"):]))
                return
            if parsed.path in {"/health", "/api/health"}:
                _facade._json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "backend": "fluxio-web",
                        "loginRequired": True,
                        "selfCheck": __import__("grant_agent.proof_readiness", fromlist=["status"]).status(backend.root).get("state"),
                    },
                )
                return
            if parsed.path == "/auth/minimax-openclaw":
                try:
                    query = _facade.parse_qs(parsed.query)
                    region = (query.get("region") or ["global"])[0]
                    _facade._html_response(self, 200, _facade._minimax_openclaw_connect_page(region))
                except Exception as exc:
                    _facade._html_response(
                        self,
                        500,
                        (
                            "<!doctype html><title>MiniMax Connect Error</title>"
                            "<h1>MiniMax Connect Error</h1>"
                            f"<pre>{_facade.html.escape(str(exc))}</pre>"
                        ),
                    )
                return
            if parsed.path == "/api/auth/status":
                _facade._json_response(self, 200, {"ok": True, "data": backend.session_status(self)})
                return
            if parsed.path == "/api/desktop-controller/status":
                session = backend.authenticated_session(self)
                if not session:
                    _facade._json_response(self, 401, {"ok": False, "loginRequired": True, "error": "Sign in to connect to the PC app."})
                    return
                if str(session.get("username") or "").casefold() != backend.username.casefold():
                    _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required for desktop control."})
                    return
                from .desktop_controller import controller_status

                _facade._json_response(self, 200, {"ok": True, "data": controller_status(backend.root)})
                return
            if parsed.path == "/api/browser-click-probe":
                _facade._html_response(self, 200, _facade._browser_click_probe_page(), frame_options="SAMEORIGIN")
                return
            if parsed.path == "/api/artifact":
                backend.serve_artifact(self)
                return
            if parsed.path.startswith("/api/connected/"):
                from .connected_sessions.api import serve_connected_get
                serve_connected_get(backend, self, parsed)
                return
            if parsed.path.startswith("/api/gamedev/"):
                from .neyvia_gamedev import serve_http
                serve_http(backend, self, parsed, "GET")
                return
            if parsed.path.startswith(("/api/ui/", "/api/nightshift/", "/api/apps/pdf/")) or parsed.path == "/api/apps":
                from .neyvia_ui_api import serve
                serve(backend, self, parsed)
                return
            if parsed.path == "/api/connected-chat-media":
                if not backend.is_authenticated(self):
                    _facade._json_response(self, 401, {"ok": False, "loginRequired": True})
                    return
                from .connected_chat_media import read_media
                query = _facade.parse_qs(parsed.query)
                try:
                    body, mime, name = read_media((query.get("chat") or [""])[0], (query.get("media") or [""])[0])
                except (ValueError, OSError):
                    _facade._json_response(self, 404, {"ok": False, "error": "Referenced chat media is unavailable"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "private, no-store")
                if not mime.startswith("image/"):
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + _facade.quote(name, safe=""))
                self.end_headers()
                _facade._write_response_body(self, body)
                return
            if parsed.path == "/api/project-files" or parsed.path.startswith("/api/project-files/"):
                backend.serve_project_files(self)
                return
            if parsed.path.startswith("/api/app-factory/"):
                backend.serve_app_factory(self)
                return
            if parsed.path.startswith("/api/application/"):
                backend.serve_application(self)
                return
            if parsed.path == "/api/sdk/neyvia-sdk.js":
                from .source_marketplace import serve_sdk
                serve_sdk(backend, self)
                return
            if parsed.path == "/api/delivery-receipts":
                backend.serve_delivery_receipts(self)
                return
            if parsed.path == "/api/cluster/hosts":
                if not backend.is_authenticated(self):
                    _facade._json_response(
                        self,
                        401,
                        {
                            "ok": False,
                            "error": f"{_facade.PRODUCT_NAME} login is required.",
                            "loginRequired": True,
                        },
                    )
                    return
                registry = _facade.ClusterRegistry(backend.root)
                _facade._json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "data": {
                            "hosts": registry.list_hosts(),
                            "summary": registry.snapshot(job_limit=20).get("summary", {}),
                        },
                    },
                )
                return
            if parsed.path == "/api/neyvia/runtime":
                if not backend.is_authenticated(self):
                    _facade._json_response(self, 401, {"ok": False, "error": "N-E-Y-V-I-A login is required."})
                    return
                _facade._json_response(
                    self,
                    200,
                    {"ok": True, "data": backend.neyvia_mcp.store.operator_snapshot()},
                )
                return
            if parsed.path == "/api/neyvia/semantic":
                backend.serve_semantic_inspection(self)
                return
            backend.serve_file(self)

        def do_POST(self) -> None:  # noqa: N802
            _facade._extend_io_timeout(self)
            path = _facade.urlparse(self.path).path
            if path.startswith("/api/gamedev/"):
                from .neyvia_gamedev import serve_http
                serve_http(backend, self, _facade.urlparse(self.path), "POST")
                return
            if path.startswith("/api/peer/v1/"):
                from .neyvia_devices import serve_peer
                serve_peer(backend, self, _facade.urlparse(self.path), "POST")
                return
            if path.startswith(("/api/ui/", "/api/nightshift/", "/api/apps/pdf/")):
                from .neyvia_ui_api import serve
                serve(backend, self, _facade.urlparse(self.path), "POST")
                return
            if path == "/mcp":
                if not backend.is_authenticated(self):
                    _facade._json_response(self, 401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "N-E-Y-V-I-A authentication is required."}})
                    return
                try:
                    request = _facade._read_json_body(self)
                    response = backend.neyvia_mcp.handle(request)
                    if response is None:
                        _facade._json_response(self, 202, {})
                    else:
                        _facade._json_response(self, 200, response)
                except Exception as exc:
                    _facade._json_response(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}})
                return
            relay_prefix = "/api/codex/login/browser-relay/complete/"
            if path.startswith(relay_prefix):
                session_id = _facade.unquote(path[len(relay_prefix) :])
                try:
                    payload = _facade._read_json_body(self)
                    result = backend.complete_openai_codex_oauth_relay(
                        session_id=session_id,
                        payload=payload,
                        authorization=self.headers.get("Authorization") or "",
                    )
                    _facade._json_response(self, 200, {"ok": True, "data": result})
                except PermissionError as exc:
                    _facade._json_response(self, 401, {"ok": False, "error": str(exc)})
                except ValueError as exc:
                    _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                except RuntimeError as exc:
                    _facade._json_response(self, 410, {"ok": False, "error": str(exc)})
                except Exception as exc:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                return
            if path == "/api/auth/local-session":
                try:
                    token = backend.create_local_session(self)
                    if not token:
                        _facade._json_response(
                            self,
                            403,
                            {
                                "ok": False,
                                "error": "Local session bootstrap is only available from this computer.",
                                "loginRequired": True,
                            },
                        )
                        return
                    session = backend.web_auth_sessions.lookup(token) or {}
                    self.send_response(200)
                    backend._set_session_cookie(self, token)
                    response_payload = {
                        "ok": True,
                        "data": {
                            "authenticated": True,
                            "localSession": True,
                            "user": {
                                "username": session.get("username") or backend.username,
                                "displayName": session.get("displayName") or backend.admin_config.get("displayName") or "Account",
                                "role": session.get("role") or backend.role,
                            },
                            "loginRequired": True,
                            "productName": _facade.PRODUCT_NAME,
                        },
                    }
                    body = _facade.json.dumps(response_payload, indent=2).encode("utf-8")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    _facade._apply_security_headers(self)
                    _facade._send_cors_headers(self)
                    self.end_headers()
                    _facade._write_response_body(self, body)
                except Exception as exc:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                return
            if path == "/api/auth/login":
                try:
                    payload = _facade._read_json_body(self)
                    token = backend.login(payload, self)
                    if not token:
                        _facade._json_response(
                            self,
                            401,
                            {
                                "ok": False,
                                "error": f"Invalid {_facade.PRODUCT_NAME} account username or password.",
                            },
                        )
                        return
                    session = backend.web_auth_sessions.lookup(token) or {}
                    self.send_response(200)
                    backend._set_session_cookie(self, token)
                    response_payload = {
                        "ok": True,
                        "data": {
                            "authenticated": True,
                            "user": {
                                "username": session.get("username") or backend.username,
                                "displayName": session.get("displayName") or backend.admin_config.get("displayName") or "Account",
                                "role": session.get("role") or backend.role,
                            },
                            "loginRequired": True,
                            "productName": _facade.PRODUCT_NAME,
                        },
                    }
                    body = _facade.json.dumps(response_payload, indent=2).encode("utf-8")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    _facade._apply_security_headers(self)
                    _facade._send_cors_headers(self)
                    self.end_headers()
                    _facade._write_response_body(self, body)
                except Exception as exc:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                return
            if path == "/api/minimax/openclaw/complete":
                try:
                    payload = _facade._read_json_body(self)
                    result = _facade._minimax_openclaw_auth_complete(payload)
                    _facade._json_response(self, 200, {"ok": True, "data": result})
                except Exception as exc:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                return
            if path == "/api/auth/logout":
                self.send_response(200)
                backend.logout(self)
                body = _facade.json.dumps({"ok": True, "data": {"authenticated": False}}).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                _facade._apply_security_headers(self)
                _facade._send_cors_headers(self)
                self.end_headers()
                _facade._write_response_body(self, body)
                return
            if path.startswith("/api/cluster/worker/"):
                registry = _facade.ClusterRegistry(backend.root)
                if not registry.verify_worker_token(self.headers.get("Authorization") or ""):
                    _facade._json_response(self, 401, {"ok": False, "error": "Invalid worker token."})
                    return
                try:
                    payload = _facade._read_json_body(self)
                    if path == "/api/cluster/worker/heartbeat":
                        result = registry.heartbeat_host(payload)
                        lease_id = str(payload.get("leaseId") or payload.get("lease_id") or "")
                        host_id = str(payload.get("hostId") or payload.get("host_id") or "")
                        if lease_id and host_id:
                            lease_result = registry.heartbeat_lease(
                                lease_id=lease_id,
                                host_id=host_id,
                                process_id=int(payload.get("processId") or payload.get("process_id") or 0),
                            )
                            result["lease"] = lease_result.get("lease", {})
                            result["job"] = lease_result.get("job", {})
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                        return
                    if path == "/api/cluster/worker/claim":
                        result = registry.claim_next_job(payload)
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                        return
                    if path == "/api/cluster/worker/events":
                        result = registry.record_event(
                            job_id=str(payload.get("jobId") or payload.get("job_id") or ""),
                            lease_id=str(payload.get("leaseId") or payload.get("lease_id") or ""),
                            host_id=str(payload.get("hostId") or payload.get("host_id") or ""),
                            kind=str(payload.get("kind") or "worker.event"),
                            message=str(payload.get("message") or ""),
                            payload=dict(payload.get("payload") or {}),
                        )
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                        return
                    if path == "/api/cluster/worker/provider-result":
                        job_id = str(payload.get("jobId") or payload.get("job_id") or "")
                        lease_id = str(payload.get("leaseId") or payload.get("lease_id") or "")
                        host_id = str(payload.get("hostId") or payload.get("host_id") or "")
                        if not job_id or not lease_id or not host_id:
                            _facade._json_response(
                                self,
                                400,
                                {"ok": False, "error": "Provider result requires jobId, leaseId, and hostId."},
                            )
                            return
                        job = registry.get_job(job_id)
                        if not job:
                            _facade._json_response(self, 400, {"ok": False, "error": "Unknown cluster job."})
                            return
                        result = registry.record_provider_result(
                            job=job,
                            lease_id=lease_id,
                            host_id=host_id,
                            result=dict(payload.get("result") or {}),
                        )
                        if not result.get("ok"):
                            _facade._json_response(self, 409, {"ok": False, "error": result.get("error", "Provider result rejected."), "data": result})
                            return
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                        return
                    if path == "/api/cluster/worker/complete":
                        result = registry.complete_job(
                            job_id=str(payload.get("jobId") or payload.get("job_id") or ""),
                            lease_id=str(payload.get("leaseId") or payload.get("lease_id") or ""),
                            host_id=str(payload.get("hostId") or payload.get("host_id") or ""),
                            status=str(payload.get("status") or "failed"),
                            detail=str(payload.get("detail") or ""),
                            artifacts=list(payload.get("artifacts") or []),
                            changed_files=list(payload.get("changedFiles") or payload.get("changed_files") or []),
                            result=dict(payload.get("result") or {}),
                        )
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                        return
                    _facade._json_response(self, 404, {"ok": False, "error": "Unknown worker route."})
                except Exception as exc:
                    _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                return
            if path == "/api/context-import/stage":
                if not backend.is_authenticated(self):
                    _facade._json_response(
                        self,
                        401,
                        {"ok": False, "error": f"{_facade.PRODUCT_NAME} login is required.", "loginRequired": True},
                    )
                    return
                try:
                    from . import context_import

                    filename = self.headers.get("X-Neyvia-File-Name") or self.headers.get("X-File-Name") or ""
                    content_type = (self.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                    if content_type and content_type not in {"application/octet-stream", "application/json", "text/plain", "text/markdown"}:
                        raise ValueError("Use a raw file upload with content-type application/octet-stream.")
                    receipt = context_import.stage_upload(
                        backend.root,
                        filename=filename,
                        chunks=_facade._stream_request_body(self, limit=context_import.MAX_EXPORT_BYTES),
                    )
                    _facade._json_response(self, 201, {"ok": True, "data": receipt})
                except ValueError as exc:
                    _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                except Exception as exc:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                return
            if path != "/api/backend":
                _facade._json_response(self, 404, {"ok": False, "error": "Unknown API route"})
                return
            try:
                payload = _facade._read_json_body(self)
            except Exception as exc:  # pragma: no cover - exercised by browser/manual flows
                try:
                    _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
                return
            if not backend.is_authenticated(self):
                _facade._json_response(
                    self,
                    401,
                    {
                        "ok": False,
                        "error": f"{_facade.PRODUCT_NAME} login is required.",
                        "loginRequired": True,
                    },
                )
                return
            try:
                command = str(payload.get("command") or "").strip()
                command_payload = payload.get("payload")
                from .source_marketplace import COMMANDS as SOURCE_COMMANDS, authorize_app
                try:
                    authorize_app(backend, self)
                except ValueError as exc:
                    _facade._json_response(self, 403, {"ok": False, "code": "app_disabled", "error": str(exc)})
                    return
                if command in SOURCE_COMMANDS and str(backend.authenticated_session(self).get('username') or '').casefold() != backend.username.casefold():
                    _facade._json_response(self, 403, {'ok': False, 'error': 'Source lifecycle requires the PC owner'})
                    return
                from .components import COMMANDS as COMPONENT_COMMANDS
                if command in COMPONENT_COMMANDS and command != "components_status_command" and str(backend.authenticated_session(self).get('username') or '').casefold() != backend.username.casefold():
                    _facade._json_response(self, 403, {'ok': False, 'error': 'Installing components requires the PC owner'})
                    return
                from .neyvia_memory_tools import COMMANDS as MEMORY_COMMANDS, handle_command as memory_command
                if command in MEMORY_COMMANDS:
                    from .cue_memory import MemoryRefusal
                    import sqlite3
                    try:
                        result = memory_command(backend, command, _facade._as_payload(command_payload),
                            user=str(backend.authenticated_session(self).get('username') or ''))
                    except MemoryRefusal as exc:
                        _facade._json_response(self, exc.status, {'ok': False, 'code': exc.code, 'error': str(exc)})
                    except sqlite3.Error:
                        _facade._json_response(self, 503, {'ok': False, 'code': 'memory_unavailable',
                            'error': 'Private memory is unavailable. Retry after the store is accessible.'})
                    except (ValueError, KeyError, TypeError, OSError) as exc:
                        _facade._json_response(self, 400, {'ok': False, 'code': 'memory_unavailable', 'error': str(exc)[:180]})
                    else:
                        _facade._json_response(self, 200, {'ok': True, 'data': result})
                    return
                from .neyvia_scroll import COMMANDS as SCROLL_COMMANDS
                if command in SCROLL_COMMANDS:
                    if str(backend.authenticated_session(self).get("username") or "").casefold() != backend.username.casefold():
                        _facade._json_response(self, 403, {"ok": False, "error": "Only the PC owner may use the study generator"})
                        return
                    try:
                        result = backend.dispatch(command, _facade._as_payload(command_payload))
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    except (ValueError, KeyError, TypeError) as exc:
                        _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                    return
                from .neyvia_evolver import COMMANDS as EVOLVER_COMMANDS
                if command in EVOLVER_COMMANDS:
                    if not isinstance(command_payload, dict):
                        _facade._json_response(self, 400, {"ok": False, "error": "Evolver payload must be an object"})
                        return
                    if command_payload.get("_expectedStateRoot") and _facade.Path(command_payload["_expectedStateRoot"]).resolve() != backend.root.resolve():
                        _facade._json_response(self, 409, {"ok": False, "error": "Evolver belongs to another workspace"})
                        return
                    if command == "evolver_run_command" and str(backend.authenticated_session(self).get("username") or "").casefold() != backend.username.casefold():
                        _facade._json_response(self, 403, {"ok": False, "error": "Only the PC owner may start model evolution"})
                        return
                    try:
                        result = backend.dispatch(command, command_payload)
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    except ValueError as exc:
                        _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                    return
                from .neyvia_browser import COMMANDS as BROWSER_COMMANDS
                if command in BROWSER_COMMANDS:
                    from .neyvia_browser import trusted_origin
                    if str(backend.authenticated_session(self).get("username") or "").casefold() != backend.username.casefold() or not trusted_origin(self):
                        _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required for browser state."})
                        return
                    from .neyvia_browser import handle_command
                    value = _facade._as_payload(command_payload)
                    if value.get("_expectedStateRoot") and _facade.Path(str(value["_expectedStateRoot"])).resolve() != backend.root.resolve():
                        _facade._json_response(self, 409, {"ok": False, "error": "Browser workspace differs from desktop request"})
                        return
                    try:
                        result = handle_command(backend.root, command, value, owner=True)
                    except (ValueError, KeyError, TypeError, OSError) as exc:
                        _facade._json_response(self, getattr(exc, "status", 400), {"ok": False,
                            "error": {"code": getattr(exc, "code", "invalid_request"), "message": str(exc)}})
                    else:
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    return
                from .neyvia_dictation import COMMANDS as DICTATION_COMMANDS
                if command in DICTATION_COMMANDS:
                    from .neyvia_dictation import respond_command
                    respond_command(self, backend.root, command, _facade._as_payload(command_payload))
                    return
                from .neyvia_outputs import COMMANDS as OUTPUT_COMMANDS
                if command in OUTPUT_COMMANDS and str(backend.authenticated_session(self).get("username") or "").casefold() != backend.username.casefold():
                    _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required for outputs and navigation."})
                    return
                from .neyvia_sidebar import COMMANDS as SIDEBAR_COMMANDS
                if command in SIDEBAR_COMMANDS:
                    from .neyvia_sidebar import respond_command
                    respond_command(self, backend, command, command_payload)
                    return
                from .neyvia_settings import COMMANDS as SETTINGS_COMMANDS
                if command in SETTINGS_COMMANDS and command != "settings_get_command":
                    session = backend.authenticated_session(self)
                    if str(session.get("username") or "").casefold() != backend.username.casefold():
                        _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required"})
                        return
                if command in SETTINGS_COMMANDS:
                    try:
                        result = backend.dispatch(command, command_payload)
                    except ValueError as exc:
                        _facade._json_response(self, getattr(exc, "status", 400), {"ok": False, "error": str(exc)})
                    else:
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    return
                from .connected_sessions.api import CONNECTED_COMMANDS, respond_connected_command
                from .neyvia_accounts import ACCOUNT_COMMANDS, respond_account_command
                from .neyvia_nightshift import COMMANDS as NIGHTSHIFT_COMMANDS, respond as respond_nightshift
                if command in NIGHTSHIFT_COMMANDS:
                    respond_nightshift(self, backend, command, command_payload)
                    return
                if command in ACCOUNT_COMMANDS:
                    respond_account_command(self, backend, command, command_payload)
                    return
                if command in CONNECTED_COMMANDS:
                    # The broker lives in this service, so it never goes through the desktop controller.
                    respond_connected_command(self, backend, command, command_payload)
                    return
                if command.startswith("gamedev_"):
                    from .neyvia_gamedev import trusted_origin
                    session = backend.authenticated_session(self)
                    if str(session.get("username") or "").casefold() != backend.username.casefold() or not trusted_origin(self):
                        _facade._json_response(self, 403, {"ok": False, "error": "Game Dev requires the owner's local app or IPC session."})
                        return
                    try:
                        result = backend.dispatch(command, command_payload)
                    except (ValueError, OSError, RuntimeError, _facade.subprocess.TimeoutExpired) as exc:
                        _facade._json_response(self, 400, {"ok": False, "error": str(exc)[:500]})
                    else:
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    return
                if command in {"list_connected_app_windows_command", "get_connected_app_window_command", "act_connected_app_window_command"}:
                    session = backend.authenticated_session(self)
                    origin = _facade.urlparse(str(self.headers.get("Origin") or ""))
                    request_host = str(self.headers.get("Host") or "").strip().lower()
                    if str(session.get("username") or "").casefold() != backend.username.casefold():
                        _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required for app control."})
                        return
                    # Browser requests must originate at this Neyvia page. A
                    # local desktop IPC proxy has no Origin and is loopback.
                    if origin.netloc.lower() != request_host or origin.scheme not in {"http", "https"}:
                        if str(self.client_address[0]) not in {"127.0.0.1", "::1"} or self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"):
                            _facade._json_response(self, 403, {"ok": False, "error": "App control requires a request from this Neyvia page."})
                            return
                # Host polling/completion is a local Tauri IPC boundary, never a
                # web command, even for an authenticated controller.
                if command in {"desktop_controller_poll_command", "desktop_controller_complete_command", "set_opencode_provider_api_key_command"}:
                    _facade._json_response(self, 403, {"ok": False, "error": "This command is reserved for the installed PC app."})
                    return
                referrer = _facade.urlparse(str(self.headers.get("Referer") or ""))
                controller_requested = (
                    str(self.headers.get("X-Neyvia-Controller") or "").strip().lower() == "desktop"
                    or (_facade.parse_qs(referrer.query).get("controller") or [""])[0] == "desktop"
                    # The page's Referrer-Policy hides the query string, so the
                    # checks above only see requests that send the header.
                    # Where a PC app is paired, computer use never skips the
                    # PC owner rules or its offline state.
                    or (
                        bool(self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"))
                        and _facade._is_pc_host_command(command, command_payload)
                        and _facade._pc_app_is_paired(backend.root)
                    )
                )
                if controller_requested:
                    session = backend.authenticated_session(self)
                    origin = _facade.urlparse(str(self.headers.get("Origin") or ""))
                    request_host = str(self.headers.get("Host") or "").strip().lower()
                    if str(session.get("username") or "").casefold() != backend.username.casefold():
                        _facade._json_response(self, 403, {"ok": False, "error": "The PC owner's account is required for desktop control."})
                        return
                    if origin.scheme not in {"http", "https"} or origin.netloc.lower() != request_host:
                        _facade._json_response(self, 403, {"ok": False, "error": "Desktop control requires a request from this Neyvia page."})
                        return
                    from .desktop_controller import controller_status, submit_controller_request

                    try:
                        if command in {
                            "get_agent_chat_stream_command",
                            "get_agent_chat_run_status_command",
                            "get_conversation_state_command",
                            "get_conversation_session_state_command",
                            # Both ends share one state root and its cross-process
                            # lock. The phone's whole transcript would not fit
                            # the relay's request limit.
                            "save_conversation_state_command",
                            "get_control_room_summary_command",
                            "get_real_agent_runtime_proof_status_command",
                            "get_openai_codex_oauth_session_command",
                            "get_external_chats_command",
                            "get_external_chat_command",
                            "send_connected_app_chat_command",
                            "get_connected_app_chat_run_command",
                            "answer_connected_app_chat_command",
                            "cancel_connected_app_chat_command",
                            "list_connected_app_windows_command",
                            "get_connected_app_window_command",
                            "act_connected_app_window_command",
                        }:
                            if not controller_status(backend.root).get("online"):
                                raise RuntimeError("The PC app is disconnected. Open Neyvia on the PC to reconnect.")
                            # Both ends use the same authoritative state root.
                            # Read-only state and host-status refreshes use the
                            # persistent local service rather than spawning a
                            # desktop Python worker per browser refresh. They
                            # must not occupy slots for execution or prompts.
                            result = backend.dispatch(command, command_payload)
                        else:
                            result = submit_controller_request(
                                backend.root, command, command_payload or {},
                                str(payload.get("controllerRequestId") or payload.get("requestId") or _facade.uuid.uuid4().hex),
                            )
                    except ValueError as exc:
                        _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                        return
                    except TimeoutError as exc:
                        _facade._json_response(self, 504, {"ok": False, "error": str(exc), "outcomeUnknown": True})
                        return
                    except RuntimeError as exc:
                        _facade._json_response(self, 503, {
                            "ok": False, "error": str(exc), "desktopController": True,
                            "pcOffline": _facade._is_pc_offline_error(exc),
                        })
                        return
                    try:
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError):
                        # The browser gave up on a large answer; nothing to report.
                        return
                    return
                if command in {"review_contextual_correction_command", "review_quality_challenge_command", "set_host_session_control_command", "call_situation_command", "save_agent_collaboration_command", "review_agent_brief_command", "save_operator_preferences_command", "test_app_factory_job_command", "install_app_factory_job_command", "rollback_app_factory_install_command"}:
                    command_payload = dict(command_payload or {})
                    command_payload["_operatorIdentity"] = backend.authenticated_session(self)["username"]
                    if command == "test_app_factory_job_command":
                        command_payload["_backendPort"] = self.server.server_port
                if command in {"get_task_continuity_command", "save_task_continuity_command"}:
                    command_payload = dict(command_payload or {})
                    command_payload["_continuityOwner"] = backend.authenticated_session(self)["username"]
                if command == "get_control_room_workspace_action_receipt_command":
                    try:
                        result = backend.dispatch(command, command_payload)
                    except (ValueError, OSError) as exc:
                        _facade._json_response(self, 400, {"ok": False, "error": str(exc)[:500]})
                    else:
                        _facade._json_response(self, 200, {"ok": True, "data": result})
                    return
                result = backend.dispatch(command, command_payload)
                try:
                    _facade._json_response(self, 200, {"ok": True, "data": result})
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError):
                    return
            except _facade.ChatAttachmentValidationError as exc:
                _facade._json_response(self, 400, {"ok": False, "error": str(exc)})
                return
            except (_facade.SettingsConflict, _facade.LocalOnlyError) as exc:
                _facade._json_response(self, exc.status, {"ok": False, "error": str(exc), "code": getattr(exc, "code", "settings_conflict")})
                return
            except Exception as exc:  # pragma: no cover - exercised by browser/manual flows
                _facade.traceback.print_exc()
                try:
                    _facade._json_response(self, 500, {"ok": False, "error": str(exc)})
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler
