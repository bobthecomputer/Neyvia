"""Owner-authenticated client of existing Neyvia HTTP commands and CL tools."""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class NeyviaError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


class NeyviaClient:
    """A local Neyvia service client; the host owns provider and memory state.

    Pass the explicit URL of a running Neyvia backend. ``sign_in`` obtains only
    this PC's local owner session cookie; provider sign-in remains a separate
    Neyvia-owned operation and may require the owner's interactive action.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.port:
            raise ValueError("base_url must be an explicit localhost HTTP URL with a port")
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must contain only scheme, localhost host and port")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                answer = json.load(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                answer = json.load(exc)
            except (ValueError, OSError):
                answer = {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NeyviaError("Neyvia's local service is unavailable", code="network") from exc
        if not isinstance(answer, dict) or not answer.get("ok") or status >= 400:
            data = answer if isinstance(answer, dict) else {}
            raise NeyviaError(str(data.get("error") or "Neyvia request failed"),
                              code=str(data.get("code") or ("login_required" if status == 401 else "")), status=status)
        return answer.get("data")

    def sign_in(self) -> dict[str, Any]:
        return self._post("/api/auth/local-session", {})

    def command(self, name: str, payload: dict[str, Any] | None = None) -> Any:
        return self._post("/api/backend", {"command": name, "payload": payload or {}})

    def tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self._post("/api/ui/tools/call", {"tool": name, "arguments": arguments or {}})

    def providers(self, app: str = "codex") -> Any:
        return self.command("connected_provider_options_command", {"app": app})

    def provider_status(self, app: str = "codex") -> Any:
        return self.command("connected_app_auth_command", {"app": app})

    def sign_in_provider(self, app: str = "codex") -> Any:
        return self.command("connected_app_sign_in_command", {"app": app})

    def recall(self, situation: dict[str, Any], *, session_id: str = "", budget: int = 256) -> Any:
        payload: dict[str, Any] = {"situation": situation, "budget": budget}
        if session_id:
            payload["sessionId"] = session_id
        return self.command("memory_recall_command", payload)

    def remember(self, *, key: str, content: str, request_id: str,
                 kind: str = "fact", cues: dict[str, Any] | None = None,
                 session_id: str = "") -> Any:
        payload: dict[str, Any] = {"key": key, "content": content, "requestId": request_id,
                                   "kind": kind, "cues": cues or {}, "exportPolicy": "local"}
        if session_id:
            payload["sessionId"] = session_id
        return self.command("memory_remember_command", payload)

    def model_call(self, *, app: str, cwd: str, message: str, request_id: str,
                   model: str = "", permission_mode: str = "read-only") -> Any:
        options = {"permissionMode": permission_mode}
        if model:
            options["model"] = model
        return self.command("connected_session_new_command", {
            "app": app, "cwd": cwd, "message": message, "requestId": request_id, "options": options})

    def model_result(self, session_id: str, *, limit: int = 200) -> Any:
        return self.command("connected_session_read_command", {"id": session_id, "limit": limit})

    def verify(self, *, question: str, candidate: Any, evidence: dict[str, Any]) -> Any:
        return self.tool("neyvia.efficiency.laya_verify", {
            "question": question, "candidate": candidate, "evidence": evidence})

    def judge_scene(self, scene: dict[str, Any], *, predicates: list[dict[str, Any]] | None = None,
                    domain: str = "", user: str = "", record: bool = True) -> Any:
        """LAYA's shared judge on a Scene; ``predicates`` is the caller's own vocabulary
        (data only, same shape as a registered domain's, never executed as code)."""
        args: dict[str, Any] = {"scene": scene, "user": user, "record": record}
        if predicates is not None:
            args["predicates"] = predicates
        if domain:
            args["domain"] = domain
        return self.tool("neyvia.laya.judge", args)

    def manual(self, *, layer: str, chapter: str = "", level: int = 1) -> Any:
        args: dict[str, Any] = {"layer": layer, "level": level}
        if chapter:
            args["chapter"] = chapter
        return self.tool("neyvia.cl.describe", args)

    def cl(self, lines: str) -> Any:
        return self.tool("neyvia.cl", {"lines": lines})

    def register_app(self, *, application_id: str, name: str, services: list[str],
                     summary: str = "", version: str = "", permissions: list[str] | None = None) -> Any:
        return self.command("register_sdk_application_command", {
            "applicationId": application_id, "name": name, "summary": summary,
            "version": version, "services": services, "permissions": permissions or []})
