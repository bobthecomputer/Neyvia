"""Native inventory plus supervised OpenCode ACP turns; no extra server port."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from .broker import ConnectedError
from .model import Capabilities, ContextUsage, Item, ItemsPage, SessionSummary, TurnOptions

from .. import proofs_a_sessions as _proofs

REASON = "Install the native OpenCode CLI to continue or control sessions."
_MAX_SESSIONS = 2000


class OpenCodeAdapter:
    app = "opencode"

    def __init__(self, root: Path | None = None):
        self._root = root
        self._runs = {}
        self._lock = threading.RLock()
        self._options_cache = None

    @staticmethod
    def _database() -> Path:
        from ..external_chat_inventory import _paths

        return _paths(None)["opencode"]

    def available(self) -> tuple[bool, str | None]:
        from .opencode_acp import command
        if self._database().is_file() or command():
            return True, None
        return False, "OpenCode has no local sessions on this PC."

    def _summary(self, row: dict[str, Any], capabilities=None) -> SessionSummary:
        directory = str(row.get("project") or "")
        cwd = directory if os.path.isabs(directory) else None
        return SessionSummary(
            id=row["id"], app="opencode", title=row.get("title") or "Untitled conversation",
            updated_at=row.get("updatedAt") or None, cwd=cwd,
            project=Path(directory).name if cwd else (directory or None),
            model=row.get("model"),
            host_device_id=row.get("deviceId"), host_device_name=row.get("deviceName"),
            capabilities=capabilities or self.capabilities(),
        )

    def list_sessions(self, *, include_archived: bool = False) -> list[SessionSummary]:
        from ..external_chat_inventory import list_external_chats

        rows: list[dict[str, Any]] = []
        offset: int | None = 0
        while offset is not None and len(rows) < _MAX_SESSIONS:
            page = list_external_chats(app="opencode", limit=500, offset=offset)
            rows.extend(page["chats"])
            offset = page.get("nextOffset")
        capabilities = self.capabilities()  # one PATH lookup per listing, not one per chat
        return [self._summary(row, capabilities) for row in rows]

    def live_status(self) -> dict[str, Any]:
        from .broker import make_session_id
        from ..external_chat_inventory import _host
        with self._lock:
            return {make_session_id(self.app, _host()["deviceId"], run.sid):
                    ("waiting_approval" if run.pending else "working", "neyvia") for run in self._runs.values() if run.sid}

    def capabilities(self):
        from .opencode_acp import command
        ready = bool(command())
        result = Capabilities(continue_session=ready, new_session=ready, stop=ready, approvals=ready,
                            images=ready, model_choice=ready, permission_choice=ready,
                            billing="OpenCode configured provider", reason=None if ready else REASON)
        _proofs.check_opencode_capabilities(ready, result)
        return result

    def read(self, session_id: str, *, cursor: str | None = None, before_seq: int | None = None,
             limit: int = 200) -> ItemsPage:
        from ..external_chat_inventory import _opencode_messages, resolve_external_chat

        try:
            row = resolve_external_chat(session_id)
        except (ValueError, FileNotFoundError) as exc:
            raise FileNotFoundError(str(exc)) from exc
        from .opencode_history import read_items
        items = read_items(self._database(), row["_sessionId"], session_id)
        if items is None:
            messages = _opencode_messages(self._database(), row["_sessionId"])
            items = [Item(id=f"{session_id}#{number}", seq=number, kind=message["role"], at=message.get("timestamp") or None,
                          data={"text": message["text"], "attachments": []})
                     for number, message in enumerate(messages, 1) if message.get("role") in ("user", "assistant")]
        observed = list(items)
        newest = items[-1].seq if items else 0
        has_earlier = False
        if cursor not in (None, ""):
            try:
                after = int(cursor)
            except ValueError:
                after = 0
            items = [item for item in items if item.seq > after]
        else:
            if before_seq is not None:
                items = [item for item in items if item.seq < before_seq]
            has_earlier = len(items) > limit
            items = items[-limit:]
        from .opencode_history import latest_model
        result = ItemsPage(session=self._summary({**row, "id": session_id, "model": latest_model(self._database(), row["_sessionId"])}), items=items, context=ContextUsage(),
                         cursor=str(newest), has_earlier=has_earlier)
        _proofs.check_opencode_page(observed, result, cursor, before_seq, limit, newest)
        return result

    def options(self, session_id: str | None = None) -> dict[str, Any]:
        from .opencode_acp import AcpTurn, command, MODES
        with self._lock:
            if self._options_cache and time.monotonic() - self._options_cache[0] < 300:
                return self._options_cache[1]
            cli = command()
            if not cli:
                return {"models": [], "permissionModes": [], "reason": REASON}
            folder = Path(self._root or Path.cwd()) / ".agent_control" / "opencode-probe"
            folder.mkdir(parents=True, exist_ok=True)
            run = AcpTurn(cli, str(folder.resolve()), TurnOptions(permission_mode="read-only"), "options", lambda event: None)
            try:
                marker = folder / "session-id.txt"
                if marker.is_file():
                    setup = run.rpc.request("session/resume", {"sessionId": marker.read_text(encoding="utf-8").strip(), "cwd": str(folder.resolve()), "mcpServers": []})
                else:
                    setup = run.rpc.request("session/new", {"cwd": str(folder.resolve()), "mcpServers": []})
                    marker.write_text(setup["sessionId"], encoding="utf-8")
                model = next((row for row in setup.get("configOptions") or [] if row.get("id") == "model"), {})
                result = {"models": [{"id": row["value"], "label": row.get("name") or row["value"], "default": row["value"] == model.get("currentValue"), "efforts": []} for row in model.get("options") or []],
                          "permissionModes": [{"id": mode, "label": mode} for mode in MODES], "skills": [], "plugins": [], "mcpServers": [],
                          "transport": "acp-stdio", "version": (run.rpc.server_info.get("agentInfo") or {}).get("version"),
                          "billing": "OpenCode configured provider", "usage": "context only; execution tokens unknown"}
                self._options_cache = (time.monotonic(), result)
                return result
            finally:
                run.rpc.close()

    def tool_output(self, session_id: str, item_id: str) -> str | None:
        from urllib.parse import unquote
        from .opencode_history import tool_output
        native_id = unquote(session_id.split(":", 3)[-1])
        saved = tool_output(self._database(), native_id, item_id)
        if saved is not None:
            return saved
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            if run.sid == native_id:
                item = run.items.get(item_id)
                if item and item.get("kind") == "tool":
                    return str(item["data"].get("output") or "")
        return None

    def can_start_new(self) -> tuple[bool, str | None]:
        from .opencode_acp import command
        return (True, None) if command() else (False, REASON)

    def start_turn(self, session_id: str | None, message: str, options: TurnOptions, *,
                   cwd: str | None, run_id: str, emit: Any) -> str:
        from .opencode_acp import AcpTurn, command, MODES
        from ..neyvia_workspace_tools import WorkspaceTools
        if options.effort or options.transport not in {None, "print"}:
            raise ConnectedError("invalid_option", "OpenCode ACP exposes no effort or terminal transport option", 400)
        if options.permission_mode not in {None, *MODES}:
            raise ConnectedError("invalid_option", "Unsupported OpenCode permission mode", 400)
        if not cwd and session_id:
            from ..external_chat_inventory import resolve_external_chat
            cwd = resolve_external_chat(session_id).get("project")
        folder = WorkspaceTools.safe_path(cwd or self._root or Path.cwd())
        if not folder.is_dir() or not command():
            raise ConnectedError("unavailable", "OpenCode needs an installed CLI and existing working folder", 409)
        run = AcpTurn(command(), str(folder), options, run_id, emit)
        with self._lock:
            self._runs[run_id] = run
        try:
            return run.run(session_id, message)
        finally:
            run.rpc.close()
            with self._lock:
                self._runs.pop(run_id, None)

    def interrupt(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run:
            run.interrupt()

    def answer(self, run_id: str, request_id: str, response: dict[str, Any]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if not run:
            raise ConnectedError("stale_request", "OpenCode turn has ended", 409)
        run.answer(request_id, response)

    def close(self):
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.interrupt()


def create_adapter(root: Path | None = None) -> OpenCodeAdapter:
    return OpenCodeAdapter(root)
