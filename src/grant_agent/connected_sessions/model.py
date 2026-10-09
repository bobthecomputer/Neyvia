"""Shared shapes for connected app sessions (Claude Code, Codex, OpenCode).

Adapters translate each app's own session store and live protocol into these
shapes; the broker stamps events with a cursor and serves them to every Neyvia
client (browser, phone, desktop) the same way. Anything an app does not report
stays ``None`` -- the UI never invents a status, threshold, or percentage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal, Protocol

App = Literal["claude-code", "codex", "opencode", "neyvia"]

# Sidebar category: the app's own session ("connected"), Neyvia's own agent
# loop ("native"), or Neyvia orchestrating external runtimes ("hybrid").
Category = Literal["connected", "native", "hybrid"]

# Session lifecycle as the UI shows it. "unknown" means the app gave no signal.
SessionStatus = Literal[
    "idle", "working", "waiting_approval", "waiting_input",
    "failed", "interrupted", "unknown",
]

# Who is running the session right now: Neyvia's broker, the app's own UI or
# CLI on the host, or nobody.
LiveOwner = Literal["neyvia", "app", "cli"]

# "neyvia-harness" marks sessions Neyvia's own automated runs created (proof
# runs, harness comparisons); the sidebar hides them unless asked.
Origin = Literal["user", "neyvia-harness"]

ItemKind = Literal[
    "user", "assistant", "reasoning", "tool", "approval", "question",
    "compaction", "goal", "notice", "diff",
]

ToolCategory = Literal["command", "edit", "read", "search", "web", "mcp", "agent", "other"]

RunState = Literal[
    "queued", "running", "waiting_approval", "waiting_input",
    "completed", "failed", "interrupted", "cancelled",
]

Emit = Callable[[dict[str, Any]], None]


@dataclass
class Capabilities:
    """What this session can do through Neyvia on this host, never guessed."""

    continue_session: bool = False
    new_session: bool = False
    stop: bool = False
    approvals: bool = False
    questions: bool = False
    images: bool = False
    goal: bool = False
    compact: bool = False
    steer: bool = False
    model_choice: bool = False
    effort_choice: bool = False
    permission_choice: bool = False
    # A new session can branch from this one (Claude Code or Codex).
    fork: bool = False
    # Billing route shown on the composer, e.g. "agent-sdk-credits" for
    # Claude Code print-mode turns (Anthropic, since 2026-06-15).
    billing: str | None = None
    # Human-readable reason when continue/new is unavailable.
    reason: str | None = None


@dataclass
class SessionSummary:
    id: str  # "external:<app>:<deviceId>:<quoted sessionId>" as in external_chat_inventory
    app: App
    title: str
    updated_at: str | None = None
    created_at: str | None = None
    cwd: str | None = None
    project: str | None = None  # folder name of cwd, or the app's own project/section name
    git_branch: str | None = None
    model: str | None = None
    status: SessionStatus = "unknown"
    status_since: str | None = None
    live_owner: LiveOwner | None = None
    origin: Origin = "user"
    # A CLI chat: started from a terminal or script (`codex exec`, Claude Code CLI, `claude -p`) rather than a chat window.
    background: bool = False
    host_device_id: str | None = None
    host_device_name: str | None = None
    archived: bool = False
    capabilities: Capabilities = field(default_factory=Capabilities)
    category: Category = "connected"
    # For native/hybrid rows: the runtime Neyvia used (e.g. "neyvia-agent", "codex").
    runtime: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attachment:
    id: str
    kind: Literal["image", "file"]
    label: str | None = None
    url: str | None = None  # served by the broker's media route, never a host path
    mime: str | None = None


@dataclass
class Item:
    """One chronological transcript entry. ``seq`` orders items inside a session.

    ``data`` holds kind-specific fields:
      user/assistant: {"text": markdown, "attachments": [Attachment]}
      reasoning:      {"summary": str | None, "hidden": bool, "provider", "source",
                       "exposure": "summary"|"thinking"|"withheld"|"not_reported"|"pending", "notice", "truncated"}
      tool:           {"name", "category": ToolCategory, "title", "input": str (bounded, one line
                       for commands), "command": full multiline text, "args": JSON text,
                       "status": "running"|"ok"|"error", "output": str (bounded with outputTruncated),
                       "exitCode": int | None, "files": [path], "durationMs": int | None,
                       "durationSource": provider result or observed transport/transcript timestamps}
      approval:       {"requestId", "title", "detail", "command", "cwd", "choices", "decision"}
      question:       {"requestId", "questions": [{"id","header","question","options","isSecret"}],
                       "answers": {}}
      compaction:     {"state": "started"|"completed"|"failed", "beforeTokens", "afterTokens"}
      goal:           {"state": "set"|"updated"|"cleared"|"achieved", "text"}
      notice:         {"text", "level": "info"|"warning"|"error"}
      diff:           {"files": [{"path","additions","deletions"}], "patch": str | None}
    """

    id: str
    seq: int
    kind: ItemKind
    at: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextUsage:
    used_tokens: int | None = None
    window_tokens: int | None = None  # only when the app reported it
    auto_compact_tokens: int | None = None  # only when configured/reported
    source: str | None = None
    updated_at: str | None = None


@dataclass
class ItemsPage:
    session: SessionSummary
    items: list[Item]
    context: ContextUsage
    # Opaque adapter cursor for incremental reads (e.g. byte offset + seq).
    cursor: str | None = None
    # True when older items exist before items[0].
    has_earlier: bool = False
    # The agent's own checklist (connected_sessions.plan.latest_plan), when the adapter folded it
    # over more than this page; the broker folds the page's items otherwise.
    plan: dict[str, Any] | None = None


# Live events an adapter emits while it owns a turn. The broker adds
# {"cursor": int, "hostDeviceId": str} and fans them out.
#   {"type": "session.updated", "session": SessionSummary.public()}
#   {"type": "item.added",   "sessionId", "item": Item.public()}
#   {"type": "item.delta",   "sessionId", "itemId", "textDelta": str}
#   {"type": "item.updated", "sessionId", "item": Item.public()}
#   {"type": "run.state",    "sessionId", "runId", "state": RunState,
#                            "pendingRequest": dict | None, "error": str | None}
#   {"type": "context.updated", "sessionId", "context": ContextUsage}


@dataclass
class TurnOptions:
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None  # app-native value, listed by options()
    images: list[dict[str, Any]] = field(default_factory=list)  # {"mime","data"(base64),"name"}
    # How the app runs the turn when it offers more than one way (options()["transports"]):
    # Claude Code "print" (claude -p, Agent SDK credit) or "terminal" (interactive, plan limits).
    transport: str | None = None
    # Start a new session as a branch of this one (full history, the original untouched).
    # Claude Code: --resume <id> --fork-session. Codex: thread/fork.
    fork_from: str | None = None


class Adapter(Protocol):
    app: App

    def available(self) -> tuple[bool, str | None]:
        """(usable on this host, reason when not)."""

    def list_sessions(self, *, include_archived: bool = False) -> list[SessionSummary]:
        ...

    def live_status(self) -> dict[str, tuple[SessionStatus, LiveOwner | None]]:
        """Status keyed by SessionSummary.id for sessions that are live right now."""

    def read(self, session_id: str, *, cursor: str | None = None,
             before_seq: int | None = None, limit: int = 200) -> ItemsPage:
        ...

    def options(self, session_id: str | None = None) -> dict[str, Any]:
        """{"models": [{"id","label","efforts":[...],"default":bool}],
            "permissionModes": [{"id","label","description"}],
            "skills": [...], "plugins": [{"id","label","state","authUrl"?}],
            "mcpServers": [{"name","state","error"?}]} -- only what the app reports."""

    def start_turn(self, session_id: str | None, message: str, options: TurnOptions, *,
                   cwd: str | None, run_id: str, emit: Emit) -> str:
        """Run one turn to completion on the calling thread; returns the session id
        (new for a new session). Emits live events. Must not time out a healthy turn."""

    def interrupt(self, run_id: str) -> None:
        ...

    def answer(self, run_id: str, request_id: str, response: dict[str, Any]) -> None:
        """response: {"decision": "approve"|"deny"|"cancel", "answers": {id: str}}"""
