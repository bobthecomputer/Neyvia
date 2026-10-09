"""Pure helpers that turn Claude Code data into connected-session items.

Shared by the transcript reader (``claude_transcript``) and the live stream
engine (``claude_stream``) so a tool, question or notice looks the same whether
it was read from disk or streamed while a turn ran.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import textwrap
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, unquote, urlparse

from ..connected_chat_media import MAX_MEDIA_BYTES, TYPES, media_refs  # noqa: F401  (MAX_MEDIA_BYTES re-exported)
from ..external_chat_inventory import _host
from .plan import note_task_created, plan_op
from .transparency import PAYLOAD_LIMIT, bounded_text
from ..proofs_a_providers import checked

TOOL_OUTPUT_LIMIT = PAYLOAD_LIMIT
TEXT_LIMIT = 200_000
TITLE_LIMIT = 120
COMMAND_LIMIT = PAYLOAD_LIMIT
ARGS_LIMIT = PAYLOAD_LIMIT

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


# --------------------------------------------------------------------------- identity


@checked("providers.claude.identity")
def session_identity(session_id: str, host: dict[str, str] | None = None) -> str:
    """``external:claude-code:<deviceId>:<quoted sessionId>``, as in ``external_chat_inventory._row``."""
    host = host or _host()
    return f"external:claude-code:{host['deviceId']}:{quote(str(session_id), safe='-_.~')}"


def parse_identity(identity: str, host: dict[str, str] | None = None) -> str:
    """Session id of a Claude Code identity on this device; ValueError for anything else."""
    parts = str(identity or "").split(":", 3)
    if len(parts) != 4 or parts[0] != "external" or parts[1] != "claude-code":
        raise ValueError("Not a Claude Code session id")
    host = host or _host()
    if parts[2] != host["deviceId"]:
        raise ValueError("This session belongs to another device")
    return valid_session_id(unquote(parts[3]))


def valid_session_id(session_id: str) -> str:
    """Session ids become file names, so refuse anything that is not a plain token."""
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Claude Code session id")
    return session_id


# --------------------------------------------------------------------------- origin

# Folders Neyvia's own automation creates. Kept in one place so the sidebar rule is testable.
_HARNESS_SEGMENTS = ("/.agent_control/", "/proof/")
_HARNESS_SUBSTRINGS = ("evidence", "harness-comparison", "neyvia-claude-resume-proof", ".sandbox-scratch")


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").casefold() + "/"


def _temp_roots() -> list[str]:
    roots = {tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", "")}
    return [_norm_path(root) for root in roots if root]


@checked("providers.claude.origin")
def is_harness_cwd(cwd: str | None, temp_roots: list[str] | None = None) -> bool:
    """True when ``cwd`` is inside a folder Neyvia's automation (proofs, harness runs) created."""
    if not cwd:
        return False
    path = _norm_path(str(cwd))
    if any(segment in path for segment in _HARNESS_SEGMENTS):
        return True
    if any(marker in path for marker in _HARNESS_SUBSTRINGS):
        return True
    roots = _temp_roots() if temp_roots is None else [_norm_path(root) for root in temp_roots]
    # People don't keep real projects in the temp folder; sessions there come
    # from test and proof runs, so they stay out of the sidebar by default.
    return any(path.startswith(root) for root in roots)


def session_origin(cwd: str | None) -> str:
    return "neyvia-harness" if is_harness_cwd(cwd) else "user"


def folder_name(cwd: str | None) -> str | None:
    """Last path component of a Windows or POSIX path."""
    if not cwd:
        return None
    parts = [part for part in re.split(r"[\\/]", str(cwd).rstrip("\\/")) if part]
    return parts[-1] if parts else None


# --------------------------------------------------------------------------- text helpers


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: Any) -> float | None:
    """Epoch seconds of an ISO timestamp (or epoch number), else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / 1000 if value > 10_000_000_000 else float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def collapse(text: Any, limit: int = TITLE_LIMIT) -> str:
    """Whitespace-collapsed single line, cut to ``limit`` characters with an ellipsis."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: max(1, limit - 1)].rstrip() + "…"


def bound_text(text: str, limit: int = TEXT_LIMIT) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit], True)


@checked("providers.claude.output")
def bound_output(text: str, limit: int = TOOL_OUTPUT_LIMIT) -> tuple[str, bool, int]:
    """(bounded text, truncated, full byte length). Keeps the head and the tail: errors usually end up last."""
    raw = text.encode("utf-8", "replace")
    if len(raw) <= limit:
        return text, False, len(raw)
    head_n, tail_n = int(limit * 0.7), int(limit * 0.25)
    head = raw[:head_n].decode("utf-8", "ignore")
    tail = raw[-tail_n:].decode("utf-8", "ignore")
    omitted = len(raw) - len(head.encode("utf-8")) - len(tail.encode("utf-8"))
    return f"{head}\n… {omitted} bytes omitted …\n{tail}", True, len(raw)


def int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def context_used(usage: Any) -> int | None:
    """Context in use after a model call: input plus cache reads plus cache creation."""
    if not isinstance(usage, dict) or int_or_none(usage.get("input_tokens")) is None:
        return None
    return sum(int_or_none(usage.get(key)) or 0 for key in
               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


# --------------------------------------------------------------------------- user text classification

_HIDDEN_BLOCKS = re.compile(
    r"<(system-reminder|local-command-caveat|user-prompt-submit-hook|ide_opened_file|ide_selection|ide_diagnostics)\b[^>]*>.*?</\1(?:\s+[^>]*)?>",
    re.DOTALL,
)
_TAG = re.compile(r"<{tag}>(.*?)</{tag}>", re.DOTALL)


def _tag(text: str, tag: str) -> str | None:
    match = re.search(r"<%s>(.*?)</%s>" % (tag, tag), text, re.DOTALL)
    return match.group(1).strip() if match else None


@checked("providers.claude.classify")
def classify_user_text(text: str) -> tuple[str, str, str]:
    """(kind, text, level) for one user text block: kind is ``prose``, ``notice`` or ``hidden``.

    Internal markers Claude Code writes into user records are not what the person typed:
    reminders are hidden, slash-command echoes and task notifications become notices.
    """
    reports = helper_reports(text)
    if reports:
        level = "error" if any(row["level"] == "error" for row in reports) else "info"
        return "notice", "\n\n".join("Helper reported · " + row["helper"] + "\n" + row["report"] for row in reports), level
    stripped = _HIDDEN_BLOCKS.sub("", text or "").strip()
    if not stripped:
        return "hidden", "", "info"
    if stripped.startswith("<command-name>"):
        name = _tag(stripped, "command-name") or ""
        args = _tag(stripped, "command-args") or ""
        if name.lstrip("/") == "compact":
            return "hidden", "", "info"  # the "Compacted · X → Y tokens" divider already says it
        return "notice", collapse(f"{name} {args}".strip(), 300), "info"
    if stripped.startswith("<local-command-stdout>") or stripped.startswith("<local-command-stderr>"):
        error = stripped.startswith("<local-command-stderr>")
        inner = _tag(stripped, "local-command-stderr" if error else "local-command-stdout") or ""
        if not error and inner.strip().lower() == "compacted":
            return "hidden", "", "info"
        return ("notice", inner, "warning" if error else "info") if inner else ("hidden", "", "info")
    if stripped.startswith("<task-notification>"):
        status = (_tag(stripped, "status") or "").lower()
        summary = _tag(stripped, "summary") or "Background task update"
        level = "error" if status in {"failed", "error", "killed"} else "info"
        return "notice", collapse(summary, 300), level
    if stripped.startswith("<bash-input>"):
        return "notice", "Ran: " + collapse(_tag(stripped, "bash-input") or "", 300), "info"
    if stripped.startswith("<bash-stdout>") or stripped.startswith("<bash-stderr>"):
        out, err = _tag(stripped, "bash-stdout") or "", _tag(stripped, "bash-stderr") or ""
        combined = "\n".join(part for part in (out, err) if part)
        return ("notice", bound_output(combined, 2000)[0], "warning" if err else "info") if combined else ("hidden", "", "info")
    if stripped.startswith("[Request interrupted by user"):
        return "notice", "Interrupted", "info"
    return "prose", stripped, "info"


def helper_reports(text: str) -> list[dict[str, str]]:
    """Display fields from Claude's machine envelopes, never their authority framing."""
    reports = []
    for match in re.finditer(r'<(agent-message|task-notification)\b([^>]*)>(.*?)</\1>', text or "", re.DOTALL):
        tag, attrs, body = match.groups()
        if tag == "agent-message":
            sender = re.search(r'\bfrom=[\"\']([^\"\']+)[\"\']', attrs)
            helper = sender.group(1) if sender else "Helper"
            report = body.strip()
            if report.startswith("[Subagent hand-back]"):
                # The harness puts its frame on the first line, then indents the report.
                _, separator, report = report.partition("The report follows:")
                if not separator:
                    report = "Report unavailable"
                report = textwrap.dedent(report.strip("\r\n"))
            reports.append({"helper": helper, "report": report.strip(), "level": "info"})
        else:
            status = (_tag(body, "status") or "").lower()
            reports.append({"helper": _tag(body, "task-id") or "Background task",
                            "report": _tag(body, "result") or _tag(body, "summary") or "Background task update",
                            "level": "error" if status in {"failed", "error", "killed"} else "info"})
    return reports


def task_notification(text: str) -> dict[str, str] | None:
    """Fields of a ``<task-notification>`` (task id, tool-use id, status, summary), else None."""
    if "<task-notification>" not in (text or ""):
        return None
    fields = {name: _tag(text, tag) for name, tag in (
        ("taskId", "task-id"), ("toolUseId", "tool-use-id"), ("status", "status"), ("summary", "summary"))}
    usage = _tag(text, "usage") or ""
    for name, tag in (("tokens", "subagent_tokens"), ("toolUses", "tool_uses"), ("durationMs", "duration_ms")):
        value = _tag(usage, tag)
        if value and value.isdigit():
            fields[name] = value
    return {key: value for key, value in fields.items() if value}


# --------------------------------------------------------------------------- tools

_COMMAND_TOOLS = {"Bash", "PowerShell", "BashOutput", "KillShell", "Monitor"}
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_READ_TOOLS = {"Read", "NotebookRead"}
_SEARCH_TOOLS = {"Grep", "Glob", "LS", "ToolSearch"}
_WEB_TOOLS = {"WebFetch", "WebSearch"}
_AGENT_TOOLS = {"Agent", "Task"}
QUESTION_TOOL = "AskUserQuestion"


@checked("providers.claude.category")
def tool_category(name: str) -> str:
    if name.startswith("mcp__"):
        return "mcp"
    for category, names in (("command", _COMMAND_TOOLS), ("edit", _EDIT_TOOLS), ("read", _READ_TOOLS),
                            ("search", _SEARCH_TOOLS), ("web", _WEB_TOOLS), ("agent", _AGENT_TOOLS)):
        if name in names:
            return category
    return "other"


def _basename(path: Any) -> str:
    parts = [part for part in re.split(r"[\\/]", str(path or "").rstrip("\\/")) if part]
    return parts[-1] if parts else ""


def mcp_parts(name: str) -> tuple[str, str]:
    """``mcp__server__tool`` -> (server, tool)."""
    body = name[len("mcp__"):]
    server, _, tool = body.partition("__")
    return server, tool or server


@checked("providers.claude.title")
def tool_title(name: str, tool_input: Any) -> str:
    """Human title: command first line, file name, pattern, host, ``server · tool`` or the agent description."""
    data = tool_input if isinstance(tool_input, dict) else {}
    category = tool_category(name)
    title = ""
    if category == "mcp":
        server, tool = mcp_parts(name)
        title = f"{server} · {tool}"
    elif category == "command":
        command = str(data.get("command") or "")
        title = next((line.strip() for line in command.splitlines() if line.strip()), "") or str(data.get("description") or name)
    elif category in ("edit", "read"):
        title = _basename(data.get("file_path") or data.get("notebook_path") or data.get("path"))
    elif name in ("Grep", "Glob"):
        title = str(data.get("pattern") or "")
    elif name == "WebFetch":
        title = urlparse(str(data.get("url") or "")).hostname or str(data.get("url") or "")
    elif name == "WebSearch":
        title = str(data.get("query") or "")
    elif category == "agent":
        title = str(data.get("description") or data.get("subagent_type") or "")
    elif name == "Skill":
        title = str(data.get("skill") or data.get("name") or "")
    elif name == "ToolSearch":
        title = str(data.get("query") or "")
    elif name == "TodoWrite":
        todos = data.get("todos")
        title = f"Update todos ({len(todos)})" if isinstance(todos, list) else "Update todos"
    elif name == "ExitPlanMode":
        title = "Plan ready for review"
    return collapse(title or name, TITLE_LIMIT)


def tool_files(name: str, tool_input: Any) -> list[str]:
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool_category(name) in ("edit", "read"):
        path = data.get("file_path") or data.get("notebook_path")
        return [str(path)] if path else []
    return []


def _one_line_input(name: str, data: dict) -> str:
    category = tool_category(name)
    if category == "command":
        command = str(data.get("command") or "")
        return collapse(next((line for line in command.splitlines() if line.strip()), ""), 500)
    if category in ("edit", "read"):
        return str(data.get("file_path") or data.get("notebook_path") or "")
    if name in ("Grep", "Glob"):
        where = data.get("path")
        return f"{data.get('pattern') or ''}" + (f"  in {where}" if where else "")
    if name == "WebFetch":
        return str(data.get("url") or "")
    if name == "WebSearch":
        return str(data.get("query") or "")
    if category == "agent":
        return collapse(data.get("prompt") or data.get("description") or "", 500)
    return collapse(json.dumps(data, ensure_ascii=False, default=str), 500) if data else ""


def tool_data(name: str, tool_input: Any) -> dict[str, Any]:
    """Initial ``tool`` item data (status running) for a tool call."""
    data = tool_input if isinstance(tool_input, dict) else {}
    category = tool_category(name)
    out: dict[str, Any] = {
        "name": name, "category": category, "title": tool_title(name, data),
        "input": _one_line_input(name, data), "status": "running", "output": "",
        "exitCode": None, "files": tool_files(name, data), "durationMs": None,
    }
    if category == "command":
        command, truncated = bound_text(str(data.get("command") or ""), COMMAND_LIMIT)
        out.update(command=command, input=command, inputTruncated=truncated)
        if data.get("description"):
            out["description"] = collapse(data["description"], 300)
    if category == "mcp":
        out["server"], out["tool"] = mcp_parts(name)
    if category == "agent":
        out["agent"] = agent_shell(data)
    plan = plan_op(name, data)
    if plan is not None:
        out["plan"] = plan
    if data:
        out["args"], out["argsTruncated"] = bounded_text(data)
        if category != "command":
            out["input"], out["inputTruncated"] = out["args"], out["argsTruncated"]
    if category == "edit":
        out["diff"] = edit_diff(name, data)
    return out


def edit_diff(name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Expose the exact edit supplied to Claude; a Write is full new content, not an invented before state."""
    import difflib
    path = str(data.get("file_path") or "")
    if not path or name not in {"Edit", "MultiEdit", "Write"}:
        return None
    edits = data.get("edits") if name == "MultiEdit" else [data]
    chunks = []
    for edit in edits or []:
        old = str(edit.get("old_string") or "")
        new = str(edit.get("content") if name == "Write" else edit.get("new_string") or "")
        chunks.append("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                               fromfile=f"a/{path}", tofile=f"b/{path}")))
    patch, truncated = bounded_text("\n".join(chunks))
    return {"files": [{"path": path}], "patch": patch or None, "truncated": truncated,
            "source": "tool-input", "scope": "new-content" if name == "Write" else "replacement", "provider": "claude-code"}


def agent_shell(tool_input: dict) -> dict[str, Any]:
    """``data.agent`` before any sub-agent record is known: only what the tool call itself says."""
    return {
        "description": collapse(tool_input.get("description"), 200) or None,
        "subagentType": tool_input.get("subagent_type") or None,
        "model": tool_input.get("model") or None,
        "status": None, "startedAt": None, "endedAt": None, "durationMs": None,
        "toolCount": None, "inputTokens": None, "outputTokens": None,
    }


def question_data(tool_input: Any, request_id: str | None) -> dict[str, Any]:
    """``question`` item data from an AskUserQuestion input."""
    questions = []
    raw = tool_input.get("questions") if isinstance(tool_input, dict) else None
    for index, question in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(question, dict):
            continue
        options = [
            {"label": str(option.get("label") or ""), "description": str(option.get("description") or "")}
            for option in (question.get("options") or []) if isinstance(option, dict)
        ]
        questions.append({
            "id": f"q{index}", "header": str(question.get("header") or ""),
            "question": str(question.get("question") or ""), "options": options,
            "multiSelect": bool(question.get("multiSelect")), "isSecret": False,
        })
    return {"requestId": request_id, "questions": questions, "answers": {}, "answered": False}


def answers_by_id(question_items: list[dict], answers: Any) -> dict[str, str]:
    """Map a ``{question text: answer}`` result onto question ids."""
    if not isinstance(answers, dict):
        return {}
    out: dict[str, str] = {}
    for question in question_items:
        value = answers.get(question.get("question"))
        if isinstance(value, list):
            value = ", ".join(str(part) for part in value)
        if isinstance(value, str):
            out[question["id"]] = value
    return out


def flatten_result_content(content: Any) -> tuple[str, list[dict]]:
    """(text, image blocks) of a ``tool_result`` content value."""
    if isinstance(content, str):
        return content, []
    text: list[str] = []
    images: list[dict] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text.append(str(block.get("text") or ""))
        elif block.get("type") == "image":
            images.append(block)
    return "\n".join(text), images


_EXIT_CODE = re.compile(r"^Exit code (-?\d+)")
_DECLINED = ("The user doesn't want to proceed", "The user doesn't want to take this action", "Permission to use", "User rejected tool use")


def apply_tool_result(data: dict[str, Any], *, text: str, is_error: bool, timestamp: str | None = None,
                      started_at: str | None = None, structured: Any = None) -> None:
    """Fill a ``tool`` item's result fields (status, bounded output, exit code, duration, declined)."""
    output, truncated, total = bound_output(text)
    data["output"] = output
    data["status"] = "error" if is_error else "ok"
    if truncated:
        data["outputTruncated"] = True
        data["outputBytes"] = total
    match = _EXIT_CODE.match(text or "")
    if match and data.get("category") == "command":
        data["exitCode"] = int(match.group(1))
    elif data.get("category") == "command" and not is_error:
        data["exitCode"] = 0
        data["exitCodeSource"] = "successful-tool-result"
    if isinstance(structured, dict):
        data["result"], data["resultTruncated"] = bounded_text(structured)
        code = structured.get("exitCode", structured.get("exit_code"))
        if isinstance(code, int) and not isinstance(code, bool):
            data.update(exitCode=code, exitCodeSource="tool-result")
        duration = structured.get("durationMs", structured.get("duration_ms"))
        if isinstance(duration, (int, float)):
            data.update(durationMs=duration, durationSource="tool-result")
    if is_error and (text.startswith(_DECLINED) or structured == "User rejected tool use"):
        data["declined"] = True
    start, end = parse_time(started_at), parse_time(timestamp)
    if data.get("durationMs") is None and start is not None and end is not None and end >= start:
        data["durationMs"] = int((end - start) * 1000)
        data["durationSource"] = "transcript-timestamps"
    if data.get("plan") and is_error:
        data.pop("plan")  # a refused or failed call did not change the plan
    elif data.get("plan"):
        note_task_created(data["plan"], structured)
    if isinstance(structured, dict) and data.get("category") == "edit":
        patch = structured.get("structuredPatch")
        if isinstance(patch, list):
            adds = dels = 0
            for hunk in patch:
                for line in (hunk.get("lines") or []) if isinstance(hunk, dict) else []:
                    adds += str(line).startswith("+")
                    dels += str(line).startswith("-")
            data["additions"], data["deletions"] = adds, dels
            path = (data.get("files") or [""])[0]
            chunks = [f"--- a/{path}\n+++ b/{path}\n"]
            for hunk in patch:
                if isinstance(hunk, dict):
                    chunks.append(f"@@ -{hunk.get('oldStart', 0)},{hunk.get('oldLines', 0)} +{hunk.get('newStart', 0)},{hunk.get('newLines', 0)} @@\n")
                    chunks.extend(str(line) + "\n" for line in hunk.get("lines") or [])
            text_patch, truncated = bounded_text("".join(chunks))
            data["diff"] = {"files": [{"path": path, "additions": adds, "deletions": dels}], "patch": text_patch,
                            "truncated": truncated, "source": "tool-result", "scope": "file", "provider": "claude-code"}


# --------------------------------------------------------------------------- media


def image_token(media_type: str, base64_data: str) -> str:
    """Same 64-hex token ``connected_chat_media`` derives for an inline image (sha256 of its data URL)."""
    digest = hashlib.sha256()
    digest.update(f"data:{media_type};base64,".encode())
    digest.update(base64_data.encode())
    return digest.hexdigest()


def ref_token(ref: str) -> str:
    return hashlib.sha256(ref.encode()).hexdigest()


def attachment_dict(token: str, *, kind: str, label: str | None, mime: str | None) -> dict[str, Any]:
    """An attachment the broker serves through its media route: ``url`` stays None, ``mediaRef`` names the media."""
    return {"id": token, "kind": kind, "label": label, "url": None, "mime": mime, "mediaRef": token}


def text_media_refs(text: str) -> list[tuple[str, dict[str, Any]]]:
    """(ref, attachment) for local files a text points at, via ``connected_chat_media.media_refs``."""
    out = []
    for ref in media_refs(None, text):
        if ref.startswith("data:"):
            continue
        suffix = os.path.splitext(ref)[1].lower()
        mime = TYPES.get(suffix)
        if not mime:
            continue
        out.append((ref, attachment_dict(ref_token(ref), kind="image" if mime.startswith("image/") else "file",
                                         label=_basename(ref) or None, mime=mime)))
    return out
