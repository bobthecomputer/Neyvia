from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class HttpServingDependencies:
    """Current facade policy and callbacks, supplied explicitly at each operation."""

    application_asset_content_types: dict[str, str]
    artifact_content_types: dict[str, str]
    desktop_shell_origins: frozenset[str]
    desktop_update_file: re.Pattern[str]
    product_name: str
    apply_security_headers: Callable[..., Any]
    json_response: Callable[..., Any]
    send_cors_headers: Callable[..., Any]
    write_response_body: Callable[..., Any]
    desktop_updates_dir: Callable[..., Any]
    load_delivery_receipts: Callable[..., Any]
    parse_qs: Callable[..., Any]
    quote: Callable[..., Any]
    unquote: Callable[..., Any]
    urlparse: Callable[..., Any]


class HttpServingMixin:
    """Owns serving behavior; the backend supplies state and external callbacks."""

    def serve_file(self, handler: BaseHTTPRequestHandler) -> bool:
        deps = self._serving_dependencies()
        parsed = deps.urlparse(handler.path)
        query = deps.parse_qs(parsed.query)
        raw_path = deps.unquote(parsed.path.lstrip("/"))
        candidate_paths = [raw_path or "index.html"]
        if raw_path == "control" or raw_path.startswith("control/"):
            control_relative = raw_path.removeprefix("control/").strip("/")
            candidate_paths.append(control_relative or "index.html")
        target = next(
            (
                self.static_root / candidate
                for candidate in candidate_paths
                if (self.static_root / candidate).exists()
            ),
            self.static_root / (candidate_paths[0] or "index.html"),
        )
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            if raw_path.startswith("assets/"):
                deps.json_response(handler, 404, {"error": "Build asset not found. Reload to use the current build."})
                return True
            target = self.static_root / "index.html"
        try:
            target.resolve().relative_to(self.static_root)
        except ValueError:
            deps.json_response(handler, 403, {"error": "Forbidden"})
            return True
        if not target.exists():
            deps.json_response(handler, 404, {"error": "Build web/dist first or run Vite dev."})
            return True
        content_type = "text/html; charset=utf-8"
        if target.suffix in {".js", ".mjs"}:
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        elif target.suffix == ".webmanifest":
            content_type = "application/manifest+json; charset=utf-8"
        elif target.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif target.suffix == ".png":
            content_type = "image/png"
        body = target.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        cache_control = "public, max-age=300"
        if target.name in {"index.html", "service-worker.js"} or target.suffix in {".html", ".js", ".mjs", ".css"}:
            cache_control = "no-store"
        if (
            target.parent == self.static_root / "assets"
            and re.search(r"-[A-Za-z0-9_-]{8,}\.(?:js|mjs|css)$", target.name)
        ):
            # Vite changes this URL when its content or imported build changes.
            # Keep the entry HTML fresh while reusing identical bundles across routes.
            cache_control = "public, max-age=31536000, immutable"
        frame_options = "DENY"
        if target.name == "index.html":
            embedded_target = (query.get("embedded") or [""])[0]
            if embedded_target in {"browser-proof", "fluxio-browser"}:
                frame_options = "SAMEORIGIN"
        request_headers = getattr(handler, "headers", None)
        origin = str(request_headers.get("Origin") or "") if request_headers is not None else ""
        cors = origin in deps.desktop_shell_origins and target.name != "index.html"
        from .proofs_e_wz import check_static_response
        check_static_response(self.static_root, target, body, origin, cors, deps.desktop_shell_origins,
                              cache_control, frame_options, query)
        if cors:
            # Interface files (never the page itself) for the desktop app's loader.
            handler.send_header("Access-Control-Allow-Origin", origin)
            handler.send_header("Vary", "Origin")
        deps.apply_security_headers(handler, cache_control=cache_control, frame_options=frame_options)
        handler.end_headers()
        deps.write_response_body(handler, body)
        return True

    def serve_desktop_update(self, handler: BaseHTTPRequestHandler, name: str) -> None:
        """Signed desktop builds and their ``latest.json`` feed, public like any release download.

        The desktop updater verifies every file against the public key built into the app,
        so serving them without a sign-in cannot install anything that was not signed.
        """
        deps = self._serving_dependencies()
        folder = deps.desktop_updates_dir(self.root)
        if not deps.desktop_update_file.fullmatch(name or "") or not (folder / name).is_file():
            deps.json_response(handler, 404, {"error": "No such desktop update file."})
            return
        target = folder / name
        try:
            target.resolve().relative_to(folder.resolve())
        except ValueError:
            deps.json_response(handler, 403, {"error": "Forbidden"})
            return
        content_type = {".json": "application/json; charset=utf-8", ".sig": "text/plain; charset=utf-8"}.get(
            target.suffix, "application/octet-stream")
        body = target.read_bytes()
        from .proofs_e_wz import check_update_response
        check_update_response(folder, target, body, deps.desktop_update_file)
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        deps.apply_security_headers(handler, cache_control="no-store" if target.suffix == ".json" else "public, max-age=3600")
        handler.end_headers()
        deps.write_response_body(handler, body)

    def _resolve_active_application_asset(
        self,
        application_id: str,
        requested_path: str,
    ) -> tuple[Path, str]:
        deps = self._serving_dependencies()
        application_id = str(application_id or "").strip()
        catalog = self.module_marketplace.installed_catalog()
        module = next(
            (
                item
                for item in catalog.get("modules") or []
                if item.get("moduleId") == application_id
                and item.get("state") == "active"
            ),
            None,
        )
        if not isinstance(module, dict):
            raise RuntimeError("Application is not active.")
        runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
        target_root = Path(str(module.get("targetPath") or "")).resolve()
        entrypoint = (target_root / str(runtime.get("entrypoint") or "")).resolve()
        try:
            entrypoint.relative_to(target_root)
        except ValueError as exc:
            raise RuntimeError("Application entry point escapes its verified package.") from exc
        if not entrypoint.is_file() or entrypoint.suffix.lower() not in {".html", ".htm"}:
            raise RuntimeError("Active application has no static HTML entry point.")

        asset_root = entrypoint.parent
        relative = deps.unquote(str(requested_path or "")).replace("\\", "/").lstrip("/")
        if not relative:
            candidate = entrypoint
        else:
            parts = Path(relative).parts
            if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
                raise RuntimeError("Application asset path is invalid.")
            candidate = (asset_root / Path(*parts)).resolve()
        try:
            candidate.relative_to(asset_root)
        except ValueError as exc:
            raise RuntimeError("Application asset escapes its verified package surface.") from exc
        content_type = deps.application_asset_content_types.get(candidate.suffix.lower())
        if (
            not content_type
            or not candidate.is_file()
            or candidate.is_symlink()
            or candidate.stat().st_size > 32 * 1024 * 1024
        ):
            raise RuntimeError("Application asset is unavailable or unsupported.")
        return candidate, content_type

    def serve_application(self, handler: BaseHTTPRequestHandler) -> bool:
        deps = self._serving_dependencies()
        if not self.is_authenticated(handler):
            deps.json_response(
                handler,
                401,
                {
                    "ok": False,
                    "error": f"{deps.product_name} login is required.",
                    "loginRequired": True,
                },
            )
            return True
        parsed = deps.urlparse(handler.path)
        prefix = "/api/application/"
        remainder = parsed.path[len(prefix) :] if parsed.path.startswith(prefix) else ""
        application_id, separator, asset_path = remainder.partition("/")
        if not application_id:
            deps.json_response(handler, 404, {"ok": False, "error": "Application id is required."})
            return True
        try:
            target, content_type = self._resolve_active_application_asset(
                deps.unquote(application_id),
                asset_path if separator else "",
            )
        except RuntimeError as exc:
            deps.json_response(handler, 404, {"ok": False, "error": str(exc)})
            return True
        body = target.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Neyvia-Application-Id", deps.unquote(application_id))
        deps.apply_security_headers(
            handler,
            cache_control="private, max-age=60",
            frame_options="SAMEORIGIN",
        )
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'self'",
        )
        handler.end_headers()
        deps.write_response_body(handler, body)
        return True

    def serve_app_factory(self, handler: BaseHTTPRequestHandler) -> bool:
        deps = self._serving_dependencies()
        if not self.is_authenticated(handler):
            deps.json_response(
                handler,
                401,
                {
                    "ok": False,
                    "error": f"{deps.product_name} login is required.",
                    "loginRequired": True,
                },
            )
            return True
        from .app_factory import AppFactory

        parsed = deps.urlparse(handler.path)
        prefix = "/api/app-factory/"
        remainder = parsed.path[len(prefix) :] if parsed.path.startswith(prefix) else ""
        job_id, separator, asset_path = remainder.partition("/")
        if not job_id:
            deps.json_response(
                handler,
                404,
                {"ok": False, "error": "App Factory job id is required."},
            )
            return True
        target: Path | None = None
        content_type = ""
        preview_error = "App Factory preview job was not found in an allowed workspace."
        seen_roots: set[str] = set()
        for raw_root in (self.root, *(Path(value) for value in self._workspace_roots())):
            root = raw_root.resolve()
            if str(root) in seen_roots:
                continue
            seen_roots.add(str(root))
            try:
                target, content_type = AppFactory(root).resolve_preview_asset(
                    deps.unquote(job_id),
                    deps.unquote(asset_path) if separator else "",
                )
                break
            except RuntimeError as exc:
                preview_error = str(exc)
        if target is None:
            deps.json_response(handler, 404, {"ok": False, "error": preview_error})
            return True
        body = target.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Neyvia-App-Factory-Job", deps.unquote(job_id))
        deps.apply_security_headers(
            handler,
            cache_control="private, no-store",
            frame_options="SAMEORIGIN",
        )
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "img-src 'self' data: blob:; "
            "style-src 'self'; "
            "script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'self'",
        )
        handler.end_headers()
        deps.write_response_body(handler, body)
        return True

    def serve_project_files(self, handler: BaseHTTPRequestHandler) -> bool:
        """Read the PC's registered project without relaying file bytes through chat."""
        deps = self._serving_dependencies()
        session = self.authenticated_session(handler)
        if not session:
            deps.json_response(handler, 401, {"ok": False, "loginRequired": True, "error": "Sign in to view and download project files."})
            return True
        if str(session.get("username") or "").casefold() != self.username.casefold():
            deps.json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required for project files."})
            return True
        # Downloads are same-origin authenticated reads. Do not reflect arbitrary
        # cross-origin credentials onto file content.
        origin = str(handler.headers.get("Origin") or "").strip()
        if origin and deps.urlparse(origin).netloc.casefold() != str(handler.headers.get("Host") or "").casefold():
            deps.json_response(handler, 403, {"ok": False, "error": "Open project files from this Neyvia controller."})
            return True

        from .project_files import (
            ProjectFilesError,
            create_project_archive,
            list_project_entries,
            open_project_download,
            preview_project_file,
        )

        parsed = deps.urlparse(handler.path)
        query = deps.parse_qs(parsed.query)
        workspace_id = (query.get("workspaceId") or [""])[0]
        relative_path = (query.get("path") or [""])[0]
        download = None
        archive = None
        stream = None
        headers_sent = False
        try:
            if parsed.path == "/api/project-files":
                result = list_project_entries(self.root, workspace_id, relative_path, offset=int((query.get("offset") or ["0"])[0]))
                deps.json_response(handler, 200, {"ok": True, "data": result})
                return True
            if parsed.path == "/api/project-files/preview":
                result = preview_project_file(self.root, workspace_id, relative_path)
                deps.json_response(handler, 200, {"ok": True, "data": result})
                return True
            if parsed.path == "/api/project-files/download":
                download = open_project_download(self.root, workspace_id, relative_path)
                stream, filename, size = download.file, download.filename, download.size
                content_type = "application/octet-stream"
            elif parsed.path == "/api/project-files/archive":
                archive = create_project_archive(self.root, workspace_id, relative_path)
                stream, filename, size = archive.path.open("rb"), archive.filename, archive.size
                content_type = "application/zip"
            else:
                deps.json_response(handler, 404, {"ok": False, "error": "Unknown project files route."})
                return True
            ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "download"
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(size))
            handler.send_header("Content-Disposition", f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{deps.quote(filename, safe='')}")
            deps.apply_security_headers(handler)
            handler.end_headers()
            headers_sent = True
            remaining = size
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    # A short response is a failed download, never a successful
                    # partial export. The browser enforces Content-Length.
                    handler.close_connection = True
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
            handler.wfile.flush()
        except ProjectFilesError as exc:
            if not headers_sent:
                deps.json_response(handler, getattr(exc, "status_code", 400), {"ok": False, "error": str(exc)})
        except ValueError:
            if not headers_sent:
                deps.json_response(handler, 400, {"ok": False, "error": "Invalid project files request."})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            handler.close_connection = True
        except OSError:
            if not headers_sent:
                deps.json_response(handler, 409, {"ok": False, "error": "The project changed or a file could not be read. Refresh and try again."})
        finally:
            if stream is not None:
                stream.close()
            if download is not None:
                download.close()
            if archive is not None:
                archive.cleanup()
        return True

    def serve_artifact(self, handler: BaseHTTPRequestHandler) -> bool:
        # Artifacts can contain sensitive build output; same-origin iframes
        # still send the session cookie, so the in-app preview keeps working.
        deps = self._serving_dependencies()
        if not self.is_authenticated(handler):
            deps.json_response(
                handler,
                401,
                {
                    "ok": False,
                    "error": f"{deps.product_name} login is required.",
                    "loginRequired": True,
                },
            )
            return True
        parsed = deps.urlparse(handler.path)
        query = deps.parse_qs(parsed.query)
        raw_id = (query.get("id") or [""])[0]
        raw_path = (query.get("path") or [""])[0]
        try:
            target = self._resolve_artifact_id(raw_id) if raw_id else self._resolve_artifact_path(raw_path)
        except RuntimeError as exc:
            deps.json_response(handler, 404, {"ok": False, "error": str(exc)})
            return True
        content_type = deps.artifact_content_types.get(target.suffix.lower())
        if not content_type:
            deps.json_response(handler, 415, {"ok": False, "error": "Unsupported artifact type"})
            return True
        from .proofs_e_wz import check_artifact_access
        check_artifact_access(self, handler)
        body = target.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Syntelos-Artifact-Id", self._artifact_id(target))
        if target.suffix.lower() == ".html":
            # Agent-authored HTML has an opaque origin even when opened in a
            # separate tab. Interactive inline scripts remain available, but
            # the artifact cannot call authenticated application APIs.
            handler.send_header(
                "Content-Security-Policy",
                "sandbox allow-scripts; default-src 'none'; "
                "script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; "
                "img-src data: blob: https:; font-src data: https:; "
                "connect-src 'none'; form-action 'none'; base-uri 'none'; "
                "frame-src 'none'",
            )
        # SAMEORIGIN so the in-app Preview window can iframe the artifact.
        deps.apply_security_headers(
            handler, cache_control="private, max-age=60", frame_options="SAMEORIGIN"
        )
        deps.send_cors_headers(handler)
        handler.end_headers()
        deps.write_response_body(handler, body)
        return True

    def serve_delivery_receipts(self, handler: BaseHTTPRequestHandler) -> bool:
        deps = self._serving_dependencies()
        parsed = deps.urlparse(handler.path)
        if not self.is_authenticated(handler):
            deps.json_response(
                handler,
                401,
                {
                    "ok": False,
                    "error": f"{deps.product_name} login is required.",
                    "loginRequired": True,
                },
            )
            return True
        query = deps.parse_qs(parsed.query)
        try:
            limit = int((query.get("limit") or ["50"])[0])
        except (TypeError, ValueError):
            limit = 50
        receipts = [asdict(item) for item in deps.load_delivery_receipts(self.root, limit=max(1, min(limit, 200)))]
        deps.json_response(handler, 200, {"ok": True, "data": {"receipts": receipts}})
        return True

    def serve_semantic_inspection(self, handler: BaseHTTPRequestHandler) -> bool:
        """Read-only, bounded semantic projection for an authenticated operator."""
        deps = self._serving_dependencies()
        if not self.is_authenticated(handler):
            deps.json_response(handler, 401, {"ok": False, "error": f"{deps.product_name} login is required.", "loginRequired": True})
            return True
        query = deps.parse_qs(deps.urlparse(handler.path).query)
        identity = str((query.get("conversationId") or query.get("sessionId") or [""])[0]).strip()
        if not identity:
            deps.json_response(handler, 400, {"ok": False, "error": "conversationId or sessionId is required."})
            return True
        try:
            limit = max(1, min(int((query.get("limit") or ["50"])[0]), 100))
        except (TypeError, ValueError):
            limit = 50
        store = self.neyvia_mcp.conversations
        try:
            conversation = store.get_conversation(identity, include_turns=False)
        except KeyError:
            deps.json_response(handler, 404, {"ok": False, "error": "Conversation/session was not found."})
            return True
        projection = conversation.get("semantic") if isinstance(conversation.get("semantic"), dict) else {}

        def safe(value: Any, key: str = "") -> Any:
            lowered = key.casefold()
            if any(term in lowered for term in ("password", "secret", "token", "credential", "authorization", "rawbody")):
                return "[redacted]"
            if isinstance(value, dict):
                return {str(k): safe(v, str(k)) for k, v in value.items() if str(k).casefold() not in {"raw", "body", "contentbody"}}
            if isinstance(value, list):
                return [safe(item, key) for item in value[:limit]]
            if isinstance(value, str):
                text = re.sub(r"(?i)(bearer\s+|api[_-]?key\s+)[^\s,;]+", r"\1[redacted]", value)
                return text[:400]
            return value

        objects = list(projection.get("objects") or [])[:limit]
        mission = safe(projection.get("mission"))
        event_rows: list[dict[str, Any]] = []
        try:
            with store._connection() as connection:
                rows = connection.execute("SELECT event_id, kind, payload_json, meaningful, created_at FROM conversation_events WHERE conversation_id = ? ORDER BY event_id DESC LIMIT ?", (identity, limit)).fetchall()
                for row in rows:
                    event_rows.append({"eventId": row["event_id"], "kind": row["kind"], "payload": safe(_decode(row["payload_json"], {})), "meaningful": bool(row["meaningful"]), "createdAt": row["created_at"]})
        except Exception:
            event_rows = []
        buckets = {"operations": [], "recovery": [], "proof": [], "memory": [], "application": []}
        for event in event_rows:
            kind = str(event.get("kind") or "").casefold()
            for bucket in buckets:
                if bucket in kind or (bucket == "operations" and "action" in kind):
                    buckets[bucket].append(event)
        data = {"schema": "neyvia.semantic-inspection.v1", "identity": {"conversationId": identity, "workspaceId": conversation.get("workspaceId"), "kind": conversation.get("kind")}, "mission": mission, "workspace": {"objects": [safe(item) for item in objects], "objectCount": len(objects), "truncated": len(projection.get("objects") or []) > len(objects)}, "summaries": buckets}
        try:
            scoped = self.semantic_snapshot({"conversationId": identity, "limit": limit})
            for key in ("operations", "recoveries", "proofs", "memory", "application"):
                data[key] = scoped.get(key)
        except Exception:
            data["operations"], data["recoveries"], data["proofs"] = [], [], []
        deps.json_response(handler, 200, {"ok": True, "data": data})
        return True

    def semantic_snapshot(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Command-dispatch equivalent of semantic inspection for the desktop UI."""
        request = payload if isinstance(payload, dict) else {}
        identity = str(request.get("conversationId") or request.get("sessionId") or "").strip()
        if not identity:
            raise ValueError("conversationId or sessionId is required")
        limit = max(1, min(int(request.get("limit") or 50), 100))
        conversation = self.neyvia_mcp.conversations.get_conversation(identity, include_turns=False)
        semantic = conversation.get("semantic") if isinstance(conversation.get("semantic"), dict) else {}
        mission = semantic.get("mission")
        objects = list(semantic.get("objects") or [])[:limit]
        # These stores are independently durable; scope them to the selected
        # identity so an operator never receives another mission's records.
        from .verified_operations import VerifiedOperationStore
        from .recovery_objects import RecoveryObjectStore
        from .proof_capsules import ProofCapsuleStore
        from .working_memory import WorkingMemoryStore
        operations = VerifiedOperationStore(self.root, identity).list(limit=limit).get("operations", [])
        recoveries = RecoveryObjectStore(self.root, identity).list(limit=limit)
        proof_store = ProofCapsuleStore(self.root, identity)
        proofs = []
        for path in sorted(proof_store.base.glob("*.json"))[:limit]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                proofs.append({key: raw.get(key) for key in ("capsuleId", "status", "claim", "createdAt", "updatedAt", "contentHash")})
            except (OSError, ValueError, TypeError):
                continue
        memory = WorkingMemoryStore(self.root, identity).snapshot()
        from .adaptive_work import AdaptiveWorkStore
        adaptive_work = AdaptiveWorkStore(self.root, identity).packet(token_budget=1800)
        memory["adaptiveWork"] = adaptive_work
        memory_summary = {"memoryId": memory.get("memoryId"), "revision": memory.get("revision"), "updatedAt": memory.get("updatedAt"), "counts": {key: len(memory.get(key) or []) for key in ("decisions", "observations", "evidence", "hypotheses", "failures")}, "integritySha256": memory.get("integritySha256")}
        return {"schema": "neyvia.semantic-inspection.v1", "conversationId": identity, "mission": mission, "objects": [{"id": item.get("objectId"), "kind": item.get("objectType"), "status": (item.get("content") or {}).get("state") or "recorded", "summary": ((item.get("content") or {}).get("statement") or "Semantic workspace object")[:280], "updatedAt": item.get("createdAt"), "detail": {key: item.get(key) for key in ("objectId", "objectType", "objectHash", "provenance", "createdAt")}} for item in objects], "operations": operations, "recoveries": recoveries, "proofs": proofs, "memory": memory_summary, "adaptiveWork": adaptive_work, "application": {"status": "unavailable", "reason": "No application instance is attached to this conversation."}, "limitations": ["Read-only projection; proof claims remain unverified until a referenced receipt or artifact is checked.", "Records are bounded to the selected conversation/session."]}
