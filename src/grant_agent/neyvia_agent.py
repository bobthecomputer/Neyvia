"""Neyvia's native model loop with progressive tools and durable sessions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from .capability_contracts import canonical_hash
from .durability import atomic_write_json
from .external_cli_bridge import _assistant_text, _popen_args, _session_id, _tool_labels
from .neyvia_version import NEYVIA_AGENT_VERSION
from .reasoning_capabilities import normalize_reasoning_effort, resolve_reasoning_effort
from .subprocess_utils import hidden_windows_subprocess_kwargs, capture_bounded_process, install_hidden_subprocess_default
from .agent_prompt_library import compiled_role_prompt, ROLES
from .agent_questions import request_question, list_questions
from .chat_stream import safe_tool_display
from .native_access import access_context as build_access_context, mutation_tools_for_mode, PERMISSION_MODES


NEYVIA_AGENT_RECEIPT_SCHEMA = "neyvia.agent-run-receipt/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
AskQuestionText = Annotated[str, Field(max_length=1000)]
AskQuestionOption = Annotated[str, Field(max_length=200)]
AskQuestionOptions = Annotated[list[AskQuestionOption], Field(max_length=3)] | None
AskQuestionContext = Annotated[str, Field(max_length=2000)]


from .neyvia_gateway import NeyviaToolGateway, _LazyUiBrowserRuntime


def _public_thinking_event(raw, config, response_id=""):
    """Expose the documented DeepSeek API output channel, not internal traces."""
    if (config.transport != "chat-completions" or config.provider_id != "opencode-go"
            or config.model != "deepseek-v4.1-flash"
            or getattr(raw, "type", "") != "response.reasoning_text.delta"):
        return None
    delta = getattr(raw, "delta", "")
    if not isinstance(delta, str) or not delta:
        return None
    return {"kind": "runtime.thinking_delta", "message": delta, "data": {
        "source": "provider.reasoning_content", "eventType": raw.type,
        "responseId": response_id, "itemId": getattr(raw, "item_id", ""),
        "outputIndex": getattr(raw, "output_index", None),
    }}


def _tool_output_error(value: Any) -> Any:
    """Recognize explicit failed tool results and the SDK's error-as-text outputs."""
    if isinstance(value, dict):
        error = value.get("error") or value.get("message")
        failed = bool(value.get("is_error") or value.get("isError") or value.get("ok") is False
                      or str(value.get("status") or "").lower() in {"failed", "error"}
                      or value.get("error"))
        return error or value if failed else None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                decoded = json.loads(text)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, dict):
                return _tool_output_error(decoded)
        if re.match(r"(?i)^An error occurred while (?:running|parsing) tool\b", text):
            return text
        if re.match(r"(?i)^Tool\s+['\"].+['\"] timed out after\s+", text):
            return text
    return None


def _ask_user_tool_behavior(context_wrapper: Any, tool_results: list[Any]) -> Any:
    """Pause only when ask_user produced a durable pending question.

    The SDK converts function exceptions into error text. An unconditional
    stop-at-tool-name rule treated that error as the final assistant reply,
    preventing the model from correcting the call and completing its answer.
    """
    from agents import ToolsToFinalOutputResult

    for result in tool_results:
        if getattr(getattr(result, "tool", None), "name", "") != "neyvia_ask_user":
            continue
        output = getattr(result, "output", None)
        if _tool_output_error(output):
            continue
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (ValueError, TypeError):
                continue
        if isinstance(output, dict) and output.get("status") == "pending" and output.get("questionId"):
            return ToolsToFinalOutputResult(is_final_output=True, final_output=result.output)
    return ToolsToFinalOutputResult(is_final_output=False, final_output=None)


def _safe_exception_origin(exc: BaseException) -> dict[str, Any]:
    """Return stack identity without exception text, locals, paths, or arguments."""
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    cause = exc.__cause__ or exc.__context__
    chain = []
    seen: set[int] = set()
    while cause is not None and len(chain) < 3 and id(cause) not in seen:
        seen.add(id(cause))
        chain.append({
            "type": type(cause).__name__,
            "module": type(cause).__module__,
        })
        cause = cause.__cause__ or cause.__context__
    return {
        "frames": [
            {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in frames[-12:]
        ],
        "causeChain": chain,
    }


def _failure_for_agent_exception(exc: BaseException, *, max_turns: int, session_id: str, session_database: Path) -> dict[str, Any]:
    """Classify the SDK's turn ceiling separately from provider/runtime failures."""

    from .prompt_contract import PromptContractError
    from .session_compaction import CompactionError
    if isinstance(exc, CompactionError):
        return {"code": "context_compaction_failed", "message": str(exc),
                "exceptionType": type(exc).__name__, "sessionId": session_id,
                "sideEffects": "inspect_prior_tool_receipts", "retrySafety": "reconcile_before_retry",
                "nextAction": "Retry to resume automatic compaction from the last saved checkpoint."}
    if isinstance(exc, PromptContractError):
        return {
            "code": "prompt_contract_violation", "message": str(exc),
            "exceptionType": type(exc).__name__, "sessionId": session_id,
            "sideEffects": "inspect_prior_tool_receipts", "retrySafety": "reconcile_before_retry",
            "nextAction": "Start a clean chat or repair the competing session instructions before retrying. The blocked model call was not sent.",
        }
    exception_type = type(exc).__name__
    if exception_type == "ModelBehaviorError":
        detail = str(exc).lower()
        if "buffered chat completions tool call stream ended without a tool call id" in detail:
            category = "missing_tool_call_id"
        elif "buffered chat completions tool call stream ended without a function name" in detail:
            category = "missing_tool_name"
        elif "finish_reason='tool_calls'" in detail and "without any streamed tool call deltas" in detail:
            category = "missing_tool_call_deltas"
        elif "invalid json input for tool" in detail or "invalid json input for" in detail:
            category = "invalid_tool_arguments"
        elif "tool " in detail and " not found" in detail:
            category = "unknown_tool"
        elif "final response" in detail:
            category = "incomplete_model_response"
        else:
            category = "invalid_model_protocol"
        return {"code": category, "exceptionType": exception_type,
                "message": "The model returned an invalid tool call or response. Your chat and Goal mode are retained.",
                "sessionId": session_id, "sideEffects": "inspect_prior_tool_receipts",
                "retrySafety": "reconcile_before_retry",
                "nextAction": "Continue this same chat after checking the last tool receipts; do not repeat actions whose outcome is uncertain.",
                "diagnostic": category, "origin": _safe_exception_origin(exc)}
    body = getattr(exc, "body", None)
    provider_error = body.get("error", body) if isinstance(body, dict) else {}
    provider_message = str(provider_error.get("message", "")) if isinstance(provider_error, dict) else ""
    if any(term in provider_message.lower() for term in ("prompt is too long", "maximum context length", "context_length_exceeded")):
        return {
            "code": "context_window_exceeded", "exceptionType": exception_type,
            "message": "This conversation exceeded the model's context window. This is a request-size limit, not a plan usage limit.",
            "sessionId": session_id, "sessionDatabase": str(session_database),
            "sideEffects": "inspect_prior_tool_receipts", "retrySafety": "reconcile_before_retry",
            "nextAction": "Resume with bounded recent history; full saved history and action receipts remain available.",
        }
    limit_reached = "maxturnsexceeded" in exception_type.replace("_", "").lower()
    failure = {
        "code": "run_limit_reached" if limit_reached else "executor_timeout" if isinstance(exc, TimeoutError) else "executor_exception",
        "exceptionType": exception_type,
        "sideEffects": "uncertain",
        "retrySafety": "reconcile_before_retry",
        "sessionId": session_id,
        "sessionDatabase": str(session_database),
    }
    if limit_reached:
        failure.update(
            maxTurns=max_turns,
            message=f"The Native run reached its {max_turns}-turn limit before completing.",
            nextAction="Resume this session and continue unfinished work; inspect saved action receipts before repeating side effects.",
        )
    else:
        failure["nextAction"] = "Read saved session and action receipts, reconcile completed or uncertain effects, then resume only unfinished work."
    return failure


@dataclass(frozen=True)
class NeyviaAgentConfig:
    root: Path
    session_id: str
    control_root: Path | None = None
    model: str = "gpt-5.6-sol"
    provider_id: str = ""
    base_url: str = ""
    api_key_env: str = ""
    transport: str = "auto"
    max_turns: int = 12
    timeout_seconds: int | None = None
    allow_mutations: bool = False
    enable_specialists: bool = True
    reasoning_effort: str = "high"
    agent_role: str = "chat"
    instructions_file: Path | None = None
    max_output_tokens: int | None = None
    native_mutation_tools: tuple[str, ...] | None = None
    permission_mode: str = ""
    situation_interface: bool = True
    goal_mode: bool = False
    _validated: bool = field(default=False, init=False, repr=False, compare=False)

    def validated(self) -> "NeyviaAgentConfig":
        from .proofs_d_neyvia import agent_config
        agent_config(self)
        if self._validated:
            return self
        root = self.root.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Neyvia workspace is not a directory: {root}")
        control_root = (
            self.control_root.expanduser().resolve()
            if self.control_root is not None
            else root
        )
        if not control_root.is_dir():
            raise ValueError(
                f"Neyvia control workspace is not a directory: {control_root}"
            )
        if not _SAFE_ID.fullmatch(self.session_id):
            raise ValueError("session_id must be a safe 1-128 character identifier.")
        if not self.model.strip():
            raise ValueError("A concrete model identifier is required.")
        if self.agent_role not in ROLES:
            raise ValueError("Unknown agent role.")
        if self.max_output_tokens is not None and not 256 <= self.max_output_tokens <= 16000:
            raise ValueError("max_output_tokens must be between 256 and 16000.")
        effort = normalize_reasoning_effort(self.reasoning_effort, fallback="invalid")
        if effort == "invalid":
            raise ValueError("Unknown reasoning effort.")
        if self.max_turns < 1 or self.max_turns > 64:
            raise ValueError("max_turns must be between 1 and 64.")
        if self.timeout_seconds is not None and (type(self.timeout_seconds) is not int or self.timeout_seconds < 1):
            raise ValueError("timeout_seconds must be a positive integer when supplied.")
        transport = self.transport.strip().lower() or "auto"
        if transport not in {"auto", "responses", "chat-completions", "codex-cli"}:
            raise ValueError(
                "transport must be auto, responses, chat-completions, or codex-cli."
            )
        if self.native_mutation_tools is not None and (
            not isinstance(self.native_mutation_tools, (tuple, list)) or len(self.native_mutation_tools)>100
            or any(not isinstance(tool, str) or not re.fullmatch(r"[a-z][a-z0-9_.]{0,119}", tool) for tool in self.native_mutation_tools)
        ):
            raise ValueError("Native mutation grants must be bounded exact tool identifiers")
        if type(self.situation_interface) is not bool:
            raise ValueError("situation_interface must be boolean")
        permission_mode = self.permission_mode
        if permission_mode and permission_mode not in PERMISSION_MODES:
            raise ValueError("permission_mode must be read-only, workspace, or full-access.")
        if not permission_mode:
            permission_mode = (
                "full-access" if self.allow_mutations and self.native_mutation_tools and "terminal.exec" in self.native_mutation_tools
                else "workspace" if self.allow_mutations else "read-only"
            )
        allow_mutations = permission_mode != "read-only" if self.permission_mode else self.allow_mutations
        native_mutation_tools = self.native_mutation_tools
        if self.permission_mode:
            mode_grants = set(mutation_tools_for_mode(permission_mode))
            native_mutation_tools = (
                tuple(sorted(mode_grants)) if native_mutation_tools is None
                else tuple(tool for tool in native_mutation_tools if tool in mode_grants)
            )
        elif not allow_mutations:
            native_mutation_tools = ()
        if self.agent_role in {"reader", "planner", "verifier"}:
            permission_mode = "read-only"
            allow_mutations = False
            native_mutation_tools = ()
        result = NeyviaAgentConfig(
            root=root,
            session_id=self.session_id,
            control_root=control_root,
            model=self.model.strip(),
            provider_id=self.provider_id.strip(),
            base_url=self.base_url.strip(),
            api_key_env=self.api_key_env.strip(),
            transport=transport,
            max_turns=self.max_turns,
            timeout_seconds=self.timeout_seconds,
            allow_mutations=allow_mutations and self.agent_role not in {"reader", "planner", "verifier"},
            enable_specialists=self.enable_specialists,
            reasoning_effort=effort,
            agent_role=self.agent_role,
            instructions_file=self.instructions_file,
            max_output_tokens=self.max_output_tokens,
            native_mutation_tools=tuple(native_mutation_tools) if native_mutation_tools is not None else None,
            permission_mode=permission_mode,
            situation_interface=self.situation_interface,
            goal_mode=self.goal_mode is True,
        )
        # Revalidation must not reinterpret an inferred mode as a new explicit
        # cap and silently discard caller grants. Frozen instances are safe to
        # reuse; dataclasses.replace resets this init=False marker for edits.
        object.__setattr__(result, "_validated", True)
        return result


def _role_instructions(config: NeyviaAgentConfig) -> str:
    if config.instructions_file:
        with config.instructions_file.open("r", encoding="utf-8", newline="") as stream:
            text = stream.read()
        if not text.strip() or len(text) > 250000:
            raise ValueError("Agent instructions must contain 1â€“250000 characters.")
    else:
        text = compiled_role_prompt(config.control_root or config.root, config.agent_role,
                                    runtime="neyvia-agent", provider=config.provider_id, model=config.model)
    # Retain authored instructions and append the shared checklist protocol.
    # Tool descriptions and the gateway retain capability/approval boundaries.
    from .neyvia_intent_plan import intent_instructions
    return intent_instructions(text.replace("\n", "\n").replace("\r", "\n"))


def _agent_reasoning_resolution(config: NeyviaAgentConfig) -> dict[str, Any]:
    # Compatibility routes do not automatically inherit OpenAI parameters.
    provider = "openai" if config.transport != "chat-completions" else "compatibility"
    if config.transport == "chat-completions" and str(config.base_url or "").rstrip("/") == "https://opencode.ai/zen/go/v1":
        provider = "opencode-go"
    return resolve_reasoning_effort(
        provider=provider, model=config.model, requested_effort=config.reasoning_effort,
    )



def _json_tool_result(value: Any) -> str:
    # The model gets the facts; the audit envelope stays in the receipt file (EFF, see model_view.py).
    from .model_view import model_view
    return json.dumps(model_view(value), ensure_ascii=False, separators=(",", ":"))


def _command_capability_summary(config: NeyviaAgentConfig, gateway: NeyviaToolGateway) -> str:
    """Describe the selected run's command route before the first model request."""
    try:
        environment = gateway.call_native("runtime.environment", {})
        while isinstance(environment, dict) and isinstance(environment.get("result"), dict):
            environment = environment["result"]
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        environment = {}
    executables = environment.get("executables") if isinstance(environment, dict) else {}
    executables = executables if isinstance(executables, dict) else {}
    shells = executables.get("shells") if isinstance(executables.get("shells"), dict) else {}
    available = sorted(name for name, executable in shells.items() if executable)
    if executables.get("python") or (environment.get("python") if isinstance(environment, dict) else None):
        available.append("python")
    available_labels = [{"powershell": "PowerShell", "python": "Python", "bash": "Bash", "cmd": "Command Prompt"}.get(name, name) for name in available]
    workspace = str(environment.get("workspaceRoot") or config.root)
    permitted = config.allow_mutations and (
        config.native_mutation_tools is None or "terminal.exec" in config.native_mutation_tools
    )
    return (
        f"Current Native mode: {config.permission_mode}. Selected workspace: {workspace}. "
        f"Detected command routes: {', '.join(available_labels) if available_labels else 'none detected (runtime.environment inspection failed or found none)'}. "
        f"Local command execution: {'permitted' if permitted else 'not permitted in this run'}; "
        "diagnostic availability does not grant execution permission. Inspect runtime.environment for command routes and the relevant tool/device inventory before claiming a command or device is absent; runtime.environment does not enumerate USB devices."
    )


def build_neyvia_agent(
    config: NeyviaAgentConfig,
    *,
    provider: OpenAIProvider,
    instructions: str | None = None,
) -> tuple[Agent[Any], RunConfig, NeyviaToolGateway]:
    from agents import Agent, ModelSettings, RunConfig, ToolOutputImage, function_tool
    from .agent_vision import chat_completions_vision_input
    from .prompt_contract import PromptContract

    selected = config.validated()
    gateway = NeyviaToolGateway(
        selected.root,
        allow_mutations=selected.allow_mutations,
        action_scope=os.environ.get("NEYVIA_PROOF_CONVERSATION_ID") or selected.session_id,
        action_root=Path(os.environ["NEYVIA_PROOF_ROOT"]) if os.environ.get("NEYVIA_PROOF_CONVERSATION_ID") and os.environ.get("NEYVIA_PROOF_ROOT") else None,
        allowed_mutation_tools=set(selected.native_mutation_tools) if selected.native_mutation_tools is not None else None,
        permission_mode=selected.permission_mode,
    )
    command_capability_summary = _command_capability_summary(selected, gateway)
    from .neyvia_memory_tools import launcher_context
    gateway.memory_context = launcher_context(selected.control_root or selected.root, project=selected.root)
    from .goal_loop import GoalLoop, GOAL_TOOL_DESCRIPTION
    gateway.goal_loop = GoalLoop(selected.control_root or selected.root, selected.session_id)

    goal_tool_description = GOAL_TOOL_DESCRIPTION if selected.goal_mode else (
        "Compatibility tool retained for earlier messages in this chat. Goal mode is currently off. "
        "You may use action=inspect to view the prior checkpoint. Do not start or update a goal while "
        "Goal mode is off; those actions return goal_mode_disabled. Continue the current chat normally."
    )

    @function_tool(name_override="neyvia_goal", description_override=goal_tool_description)
    def goal_checkpoint(action: str, goal: str = "", acceptance: str = "", evidence: str = "",
                        next_action: str = "", blocker: str = "") -> str:
        if list_questions(selected.control_root or selected.root, selected.session_id):
            return _json_tool_result({"ok": False, "status": "user_input_pending"})
        if not selected.goal_mode and action != "inspect":
            return _json_tool_result({
                "ok": False,
                "status": "goal_mode_disabled",
                "message": "Goal mode is off for this turn. No checkpoint was changed; continue the current chat normally.",
            })
        return _json_tool_result(gateway.goal_loop.update(action, goal, acceptance, evidence, next_action, blocker))

    from .neyvia_manuals import discovery_description
    @function_tool(name_override="neyvia_tools_search", description_override=discovery_description(command_capability_summary))
    def tools_search(query: str, limit: int = 10) -> str:
        result = gateway.search(query, limit)
        # SDK-only tools retain vision/managed semantics and are bound on request.
        result["deferredBindings"] = [{"name":tool.name,"description":tool.description,"next":"neyvia_tools_describe"}
                                      for tool in deferred_tools.values()
                                      if query.casefold() in (tool.name + " " + tool.description).casefold()]
        return _json_tool_result(result)

    @function_tool(name_override="neyvia_manual_index", description_override="List manual IDs and chapter names.")
    def manual_index() -> str:
        return _json_tool_result(gateway.call_native("neyvia.manual.index", {}))

    @function_tool(name_override="neyvia_manual_load", description_override="Read one manual chapter before discovering tools.")
    def manual_load(id: str, chapter: str = "overview", offset: int = 0, max_chars: int = 8000) -> str:
        return _json_tool_result(gateway.call_native("neyvia.manual.load", {"id":id,"chapter":chapter,"offset":offset,"maxChars":max_chars}))

    @function_tool(name_override="neyvia_manual_observe", description_override="Read a grounded observer and verify its result shape.")
    def manual_observe(id: str, state: str, chapter: str = "", inputs_json: str = "{}") -> str:
        return _json_tool_result(gateway.call_native("neyvia.manual.observe", {"id": id, "state": state, "chapter": chapter, "inputs": json.loads(inputs_json)}))

    @function_tool(name_override="neyvia_manual_run", description_override="Execute typed steps and checks; stop at JUDGE. Resume run_id with offered decisions; original nested permissions apply.")
    def manual_run(id: str, procedure: str, chapter: str = "", inputs_json: str = "{}", run_id: str = "", decisions_json: str = "{}") -> str:
        args = {"id": id, "procedure": procedure, "chapter": chapter}
        if run_id:
            args.update(runId=run_id, decisions=json.loads(decisions_json))
        else:
            args["inputs"] = json.loads(inputs_json)
        return _json_tool_result(gateway.call_native("neyvia.manual.run", args))

    @function_tool(name_override="neyvia_manual_frontier", description_override="Quarantine observed unmapped behavior; never edit the live manual.")
    def manual_frontier(id: str, note: str, observed_json: str) -> str:
        return _json_tool_result(gateway.call_native("neyvia.manual.frontier", {"id": id, "note": note, "observed": json.loads(observed_json)}))

    @function_tool(
        name_override="neyvia_workspace_read",
        description_override=(
            "Read one named UTF-8 text file inside the active workspace. Use this direct, "
            "receipt-bound tool whenever the operator supplies an exact file path. "
            "If truncated, pass nextOffset as offset for the next chunk; do not reread the same prefix."
        ),
    )
    def workspace_read(path: str, max_chars: int = 20000, offset: int = 0) -> str:
        return _json_tool_result(
            gateway.call_native(
                "workspace.read",
                {"path": path, "maxChars": max_chars, "offset": offset},
            )
        )

    @function_tool(
        name_override="neyvia_access_context",
        description_override=(
            "Read the effective Native permission mode and live local runtime capabilities, including PowerShell/Python command availability, "
            "Preview and browser access, and the exact bounded Laya workflow. This reports diagnostic availability separately from execution permission; it performs no command or UI action. "
            + command_capability_summary
        ),
    )
    def access_context_tool() -> str:
        environment = gateway.call_native("runtime.environment", {})
        laya = gateway.call_native("laya.native.capabilities", {})
        preview = {}
        for name, key in (("preview.inspect", "inspectAvailable"), ("preview.screenshot", "captureAvailable")):
            try:
                preview[key] = bool(gateway.native.describe(name).get("available"))
            except KeyError:
                preview[key] = False
        return _json_tool_result({
            **build_access_context(selected.permission_mode, environment=environment, laya=laya, preview=preview,
                                   granted_tools=selected.native_mutation_tools, mutations_allowed=selected.allow_mutations,
                                   situation_interface=selected.situation_interface),
            "runtimeEnvironment": environment,
            "layaCapabilities": laya,
        })

    @function_tool(
        name_override="neyvia_tools_describe",
        description_override="Load exactly one Neyvia tool or managed package schema.",
    )
    def tools_describe(tool_id: str) -> str:
        if tool_id in deferred_tools:
            tool = deferred_tools[tool_id]
            if tool not in agent.tools:
                agent.tools.append(tool)
            return _json_tool_result({"name":tool.name,"description":tool.description,
                                      "inputSchema":tool.params_json_schema,"loaded":True,"callTarget":tool.name})
        description = gateway.describe(tool_id)
        if description.get("kind") == "managed":
            for name in ("neyvia_managed_call","neyvia_compiled_call"):
                tool = deferred_tools[name]
                if tool not in agent.tools:
                    agent.tools.append(tool)
        return _json_tool_result(description)

    @function_tool(
        name_override="neyvia_compiled_call",
        description_override=(
            "Execute one exact namespace.name provider call returned by "
            "neyvia_tools_search. Neyvia resolves the immutable call map, "
            "enforces approval and hard limits, and writes a loop receipt. Mutations require a stable action_id reused after interruption."
        ),
    )
    def compiled_call(provider_call: str, arguments_json: str = "{}", action_id: str = "") -> str:
        arguments = json.loads(arguments_json or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments_json must decode to an object.")
        return _json_tool_result(gateway.call_compiled(provider_call, arguments, action_id=action_id))

    @function_tool(
        name_override="neyvia_native_call",
        description_override=(
            "Call one native tool by exact ID. arguments_json must be a JSON "
            "object. Mutations require a stable action_id reused for the same intent after interruption or compaction. Neyvia enforces schemas, mutation policy, and saved receipts. "
            "terminal.exec is available only in Full access; permission modes never grant managed connector mutations. "
            + command_capability_summary
        ),
    )
    def native_call(tool_id: str, arguments_json: str = "{}", action_id: str = "") -> str:
        arguments = json.loads(arguments_json or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments_json must decode to an object.")
        return _json_tool_result(gateway.call_native(tool_id, arguments, action_id=action_id))

    @function_tool(
        name_override="neyvia_terminal_exec",
        description_override=(
            "Run one bounded local command through Native's terminal.exec gateway. "
            "This can change files or machine state and may access the network. "
            # Recorded sessions showed most commands were file reads and writes,
            # each paying ~2.4 s of shell start-up that the direct tools avoid.
            "For file work prefer the direct tools: neyvia_workspace_read to read a file, and "
            "neyvia_native_call with workspace.search or workspace.write to search or write. They "
            "answer in milliseconds, while every command starts a new shell (usually 1-3 s). "
            "Provide a stable action_id and reuse it for the same intent after interruption. "
            + command_capability_summary
        ),
    )
    def terminal_exec(
        command: str,
        shell: str = "auto",
        cwd: str = "",
        timeoutMs: int = 30000,
        maxOutputChars: int = 12000,
        action_id: str = "",
    ) -> str:
        return _json_tool_result(gateway.call_native(
            "terminal.exec",
            {"command": command, "shell": shell, "cwd": cwd, "timeoutMs": timeoutMs, "maxOutputChars": maxOutputChars},
            action_id=action_id,
        ))

    @function_tool(name_override="neyvia_actions_inspect", description_override="Inspect a durable native action by its stable ID before recovery. This never repeats the action.")
    def actions_inspect(action_id: str = "", after: str = "") -> str:
        return _json_tool_result(gateway.actions.inspect(action_id) if action_id else gateway.actions.list(after=after))

    @function_tool(
        name_override="neyvia_managed_call",
        description_override=(
            "Call a verified operation from one managed tool package. Unverified "
            "or non-executable tools and unapproved mutations remain blocked. Mutations require a stable action_id; saved results are not a fresh postcondition check."
        ),
    )
    def managed_call(
        tool_id: str,
        operation_id: str,
        arguments_json: str = "{}",
        action_id: str = "",
    ) -> str:
        arguments = json.loads(arguments_json or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments_json must decode to an object.")
        return _json_tool_result(
            gateway.call_managed(tool_id, operation_id, arguments, action_id=action_id)
        )

    @function_tool(name_override="neyvia_view_image", description_override=(
        "Inspect an actual workspace image or managed screenshot. Returns image pixels to the model, "
        "not just a filename. Capture the relevant page first, then inspect it before claiming visual verification."
    ))
    def view_image(path: str) -> Any:
        candidate = Path(path).expanduser()
        candidate = (selected.root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        proof_root = (selected.control_root or selected.root) / ".agent_control" / "mission_artifacts"
        if not (candidate.is_relative_to(selected.root) or candidate.is_relative_to(proof_root.resolve())):
            raise ValueError("Image must be inside the workspace or managed proof artifacts.")
        if candidate.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB; capture a smaller viewport or region.")
        from PIL import Image
        with Image.open(candidate) as picture:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(picture.format)
            if not mime:
                raise ValueError("Use a PNG, JPEG, or WebP image.")
            picture.verify()
        # History replays this image every later turn: 1024 px long edge, JPEG (EFF; see image_budget.py).
        from .image_budget import shrunk_image
        shrunk_mime, shrunk_bytes = shrunk_image(candidate.read_bytes())
        output = ToolOutputImage(image_url=f"data:{shrunk_mime};base64," + base64.b64encode(shrunk_bytes).decode(), detail="high")
        from .proofs_a_control import check_image_output
        check_image_output(candidate, output)
        return output

    @function_tool(name_override="neyvia_ask_user", description_override=(
        "Ask one concise question when missing intent, scope, or approval blocks progress. "
        "Provide up to three useful options. The run pauses for a real user reply; never invent an answer. "
        "Do not ask for routine reversible implementation choices."
    ))
    def ask_user(
        question: AskQuestionText,
        options: AskQuestionOptions = None,
        context: AskQuestionContext = "",
    ) -> str:
        return _json_tool_result(request_question(selected.control_root or selected.root,
            selected.session_id, question, options, context,
            conversation_id=os.environ.get("NEYVIA_PROOF_CONVERSATION_ID", "")))

    resolution = _agent_reasoning_resolution(selected)
    model_settings = ModelSettings(
        reasoning={"effort": resolution["wireEffort"]} if resolution["wireEffort"] and selected.transport != "chat-completions" else None,
        extra_body={"reasoning_effort": resolution["wireEffort"]} if resolution["wireEffort"] and selected.transport == "chat-completions" else None,
        max_tokens=selected.max_output_tokens,
    )
    prompt_contract = PromptContract(chat_completions_vision_input if selected.transport == "chat-completions" else None)
    run_config = RunConfig(
        model_provider=provider,
        tracing_disabled=True,
        workflow_name="Neyvia native agent",
        call_model_input_filter=prompt_contract,
        trace_include_sensitive_data=False,
    )
    from .cl.protocol import Protocol
    gateway.task_goal_root = selected.control_root or selected.root
    cl_protocol = Protocol(gateway)
    gateway._cl_protocol = cl_protocol
    def current_memory():
        from .cue_memory import CueMemoryStore
        from .prompt_contract import PromptContractError
        store = CueMemoryStore(gateway.memory_context)
        if not store.session_valid(selected.session_id):
            raise PromptContractError('This Native chat has revoked memory context; start a fresh chat')
        cl_protocol.host.task_text = getattr(gateway, 'cl_task_text', '')
        packet = cl_protocol.host.refresh_memory()
        if packet.get('selected'):
            store.mark_session(selected.session_id, packet['generation'])
        return packet
    prompt_contract.memory_provider = current_memory if gateway.memory_context else None

    @function_tool(name_override="cl", description_override="CL 1.1 Python-style calls; prefer run procedures. Refs are bare e1/h1/w1. Host fills stamps; done requires observer G. Existing permissions apply.")
    def cl_tool(lines: str, action_id: str = "") -> str:
        if list_questions(selected.control_root or selected.root, selected.session_id):
            return 'R batch ask 0ms\nX batch -> "User input pending; wait for the real reply"\n'
        return cl_protocol.run(lines, action_id=action_id)["text"]

    legacy_tools = [
        manual_index,
        manual_load,
        manual_observe,
        manual_run,
        manual_frontier,
        workspace_read,
        access_context_tool,
        tools_search,
        tools_describe,
        native_call,
        actions_inspect,
        ask_user,
    ]
    # Full archival manual entry points stay deferred and callable on discovery.
    tools = [cl_tool, workspace_read, access_context_tool, tools_search,
             tools_describe, native_call, actions_inspect, ask_user]
    deferred_tools = {tool.name:tool for tool in [*legacy_tools,view_image,compiled_call,terminal_exec,managed_call]}
    # Capability inventories belong in access.context, rather than repeated startup schemas.
    tools_search.description = "Find native or managed tools by name or purpose. Read the relevant manual first."
    access_context_tool.description = "Observe this run's permissions, command routes and local capabilities."
    native_call.description = "Call one exact native tool; arguments_json is a JSON object. Reuse action_id for mutations. Existing authority checks apply."
    # A saved session can contain calls to neyvia_goal from an earlier Goal
    # turn. Keep the same tool schema available in ordinary chat turns so a
    # stale/model-selected call returns a tool result instead of failing the
    # whole Native run with SDK ModelBehaviorError("tool not found").
    if selected.agent_role == "chat":
        tools.insert(0, goal_checkpoint)
    if selected.situation_interface:
        from .situation_service import SituationService
        from .situation_interface import situation_tool_spec
        situation_service = SituationService(selected.control_root or selected.root)

        @function_tool(name_override="neyvia_situation", description_override=situation_tool_spec()["description"] +
                       ' SDK binding: supply verb separately and put all its fields in arguments_json, a JSON object string. Example: verb="observe", arguments_json="{\\"url\\":\\"http://127.0.0.1:47908/control\\"}".')
        def situation_call(verb: str, arguments_json: str) -> str:
            """Pass the verb arguments as a JSON object string."""
            if list_questions(selected.control_root or selected.root, selected.session_id):
                return _json_tool_result({"ok":False,"status":"user_input_pending"})
            try:
                result = situation_service.call(verb, gateway.work_scope, json.loads(arguments_json),
                    may_change=selected.allow_mutations and (selected.native_mutation_tools is None or "workspace.browser" in selected.native_mutation_tools))
                return _json_tool_result(result)
            except (ValueError, KeyError, OSError, RuntimeError, TypeError) as exc:
                return _json_tool_result({"ok":False,"error":str(exc)})
        gateway.situation_service = situation_service
        # Keep existing capability gateways and recovery tools available.
        deferred_tools[situation_call.name] = situation_call
    if selected.agent_role == "planner":
        tools = [ask_user]
    from .neyvia_intent_plan import native_plan_tool, intent_instructions
    tools.append(native_plan_tool(selected.control_root or selected.root, selected.session_id, function_tool))
    if selected.enable_specialists and selected.agent_role == "chat":
        planner = Agent(
            name="Neyvia Planner",
            instructions=compiled_role_prompt(selected.control_root or selected.root, "planner", runtime="neyvia-agent", provider=selected.provider_id, model=selected.model),
            model=selected.model,
            model_settings=model_settings,
        )
        verifier = Agent(
            name="Neyvia Verifier",
            instructions=compiled_role_prompt(selected.control_root or selected.root, "verifier", runtime="neyvia-agent", provider=selected.provider_id, model=selected.model),
            model=selected.model,
            model_settings=model_settings,
        )
        prompt_contract.register(planner)
        prompt_contract.register(verifier)
        specialist_tools = [
                planner.as_tool(
                    "delegate_to_neyvia_planner",
                    "Ask the Neyvia planning specialist for a bounded plan.",
                    run_config=run_config,
                    max_turns=4,
                ),
                verifier.as_tool(
                    "delegate_to_neyvia_verifier",
                    "Ask the Neyvia verification specialist to audit evidence.",
                    run_config=run_config,
                    max_turns=4,
                ),
            ]
        deferred_tools.update({tool.name:tool for tool in specialist_tools})
    from .manual_first import INSTRUCTIONS
    agent_instructions = intent_instructions(instructions if instructions is not None else _role_instructions(selected)) + "\n" + INSTRUCTIONS.replace("neyvia.manual.load", "neyvia_manual_load")
    agent = Agent(
        name="Neyvia",
        instructions=agent_instructions,
        model=selected.model,
        model_settings=model_settings,
        tools=tools,
        tool_use_behavior=_ask_user_tool_behavior,
    )
    prompt_contract.register(agent)
    if provider is not None:
        from .session_compaction import SessionCompactor
        from .compaction_policy import resolve_policy, ContextMeter
        from agents import AgentHooks

        context_policy = resolve_policy(selected.control_root or selected.root,
                                        selected.provider_id, selected.model, selected.max_output_tokens)
        if model_settings.max_tokens is None:
            model_settings.max_tokens = context_policy.output_reserve
        context_meter = ContextMeter(agent_instructions, [
            {"name": getattr(tool, "name", ""), "description": getattr(tool, "description", ""),
             "parameters": getattr(tool, "params_json_schema", {})} for tool in tools
        ])

        class ContextUsageHooks(AgentHooks):
            async def on_llm_end(self, context, agent, response):
                from .model_usage import stream_sdk_usage
                compaction_event({"kind": "runtime.progress", "message": "", "data": {
                    "eventType": "model.usage", "usage": stream_sdk_usage(prompt_contract, context.usage)}})
                input_tokens = getattr(response.usage, "input_tokens", None)
                context_meter.observe(input_tokens)
                # The provider's own prompt size for this call is the context in
                # use; clients show it against the policy's window and trigger.
                if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) and input_tokens > 0:
                    compaction_event({"kind": "runtime.progress", "message": "", "data": {
                        "eventType": "context.usage", "inputTokens": input_tokens,
                        "contextTokens": context_policy.context_tokens, "triggerTokens": context_policy.trigger,
                    }})

        agent.hooks = ContextUsageHooks()

        async def summarize_history(previous, records):
            from .compaction_model import summarize
            return await summarize(provider, selected, prompt_contract.compactor, previous, records)

        def compaction_event(event):
            if os.environ.get("NEYVIA_STREAM_EVENTS") == "1":
                print("FLUXIO_EVENT:" + json.dumps(event, ensure_ascii=True), flush=True)

        cache_key = hashlib.sha256(f"{selected.session_id}:{selected.provider_id}:{selected.model}".encode()).hexdigest()
        prompt_contract.compactor = SessionCompactor(
            (selected.control_root or selected.root) / ".agent_control" / "neyvia_agent" / "compaction" / f"{cache_key}.json",
            summarize_history, emit=compaction_event,
            policy=context_policy, meter=context_meter,
        )
        prompt_contract.compaction_agent = id(agent)
    return agent, run_config, gateway


def _provider_from_config(config: NeyviaAgentConfig) -> tuple[OpenAIProvider, str]:
    from agents import OpenAIProvider
    from openai import AsyncOpenAI

    env_name = config.api_key_env or (
        "CLIPROXY_API_KEY" if config.base_url else "OPENAI_API_KEY"
    )
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(f"Provider credential is missing from {env_name}.")
    base_url = config.base_url or os.environ.get("OPENAI_BASE_URL", "").strip() or None
    headers = None
    if base_url and base_url.rstrip("/") == "https://opencode.ai/zen/go/v1":
        headers = {"User-Agent": f"Neyvia/{NEYVIA_AGENT_VERSION}", "x-opencode-session": config.session_id}
    client = AsyncOpenAI(api_key=key, base_url=base_url, default_headers=headers)
    return OpenAIProvider(
        openai_client=client,
        use_responses=config.transport != "chat-completions",
    ), env_name


def _codex_cli_command() -> str | None:
    explicit = os.environ.get("NEYVIA_CODEX_CLI", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            codex_bin_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            try:
                installed = sorted(
                    (
                        child / "codex.exe"
                        for child in codex_bin_root.iterdir()
                        if child.is_dir() and (child / "codex.exe").is_file()
                    ),
                    key=lambda candidate: candidate.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                installed = []
            if installed:
                return str(installed[0])
    return shutil.which("codex")


def _selected_transport(
    config: NeyviaAgentConfig,
    *,
    provider_supplied: bool,
) -> str:
    if provider_supplied:
        return config.transport if config.transport != "auto" else "responses"
    if config.transport != "auto":
        return config.transport
    env_name = config.api_key_env or (
        "CLIPROXY_API_KEY" if config.base_url else "OPENAI_API_KEY"
    )
    if os.environ.get(env_name, "").strip():
        return "responses"
    if _codex_cli_command():
        return "codex-cli"
    return "responses"


def _codex_neyvia_mcp_args(root: Path, *, read_only: bool = False, session_id: str = "",
                          proof_root: Path | None = None, proof_conversation_id: str | None = None,
                          situation_interface: bool = False,
                          permission_mode: str = "",
                          cl_task_id: str = "", task_goal_root: Path | None = None, task_text: str | None = None,
                          native_mutation_tools: tuple[str, ...] = ("orchestration.compile", "context.compact", "workspace.browser", "workspace.write",
                              "work.focus", "work.problem", "work.constraint", "work.update_problem",
                              "experience.compare", "experience.trace", "experience.investigate", "experience.note",
                              "intelligence.rationale", "intelligence.obligate", "intelligence.handoff", "intelligence.brief",
                              "quality.instrument", "quality.measure", "quality.compare", "quality.holdout", "quality.examine", "quality.challenge",
                              "taste.correction", "attention.create", "attention.observe")) -> list[str]:
    source_path = str(Path(__file__).resolve().parents[1])
    args = [
        "--config",
        f"mcp_servers.neyvia.command={json.dumps(sys.executable)}",
        "--config",
        "mcp_servers.neyvia.args="
        + json.dumps(
            [
                "-B",
                str(Path(__file__).with_name("neyvia_mcp_bootstrap.py")),
                "--root",
                str(root),
                *(["--permission-mode", permission_mode] if permission_mode else []),
                *(["--read-only"] if read_only else []),
                *(["--session-id", session_id] if session_id else []),
                *(["--situation-interface"] if situation_interface else []),
                *[part for tool in (() if read_only else native_mutation_tools) for part in ("--native-mutation-tool", tool)],
            ]
        ),
        "--config",
        f"mcp_servers.neyvia.env.PYTHONPATH={json.dumps(source_path)}",
        "--config",
        "mcp_servers.neyvia.enabled=true",
        "--config",
        "mcp_servers.neyvia.startup_timeout_sec=60",
        "--config",
        "mcp_servers.neyvia.tool_timeout_sec=600",
        "--config",
        "mcp_servers.node_repl.enabled=false",
    ]
    from .cua_launch import codex_config
    for key, spec in codex_config(session_id or proof_conversation_id or "neyvia-native", app="neyvia").items():
        for field, value in spec.items():
            if field == "env":
                for name, text in value.items():
                    args.extend(["--config", f"{key}.env.{name}=" + json.dumps(text)])
            else:
                args.extend(["--config", f"{key}.{field}=" + ("true" if value is True else json.dumps(value))])
    disabled_features = (
        "plugins",
        "apps",
        "browser_use",
        "browser_use_external",
        "in_app_browser",
        "computer_use",
        "image_generation",
        "memories",
        "multi_agent",
        "goals",
        "workspace_dependencies",
        "skill_search",
        "hooks",
        "personality",
        "auth_elicitation",
        "guardian_approval",
        "plugin_sharing",
        "remote_plugin",
        "tool_suggest",
    )
    for feature in disabled_features:
        args.extend(["--config", f"features.{feature}=false"])
    # MCP calls are dispatched through code mode by current Codex clients.
    # Disabling its host leaves tools visible but every invocation fails.
    args.extend(["--config", "features.code_mode_host=true"])
    args.extend(["--config", "features.shell_tool=true"])
    bindings = {"NEYVIA_PROOF_ROOT": str(proof_root) if proof_root is not None else os.environ.get("NEYVIA_PROOF_ROOT", ""),
                "NEYVIA_PROOF_CONVERSATION_ID": proof_conversation_id if proof_conversation_id is not None else os.environ.get("NEYVIA_PROOF_CONVERSATION_ID", ""),
                "NEYVIA_UI_STATE_ROOT": os.environ.get("NEYVIA_UI_STATE_ROOT", ""),
                "NEYVIA_UI_BACKEND_URL": os.environ.get("NEYVIA_UI_BACKEND_URL", ""),
                "NEYVIA_CL_TASK_ID": cl_task_id,
                "NEYVIA_TASK_TEXT": task_text or "",
                "NEYVIA_CL_GOAL_ROOT": str(task_goal_root or root)}
    bindings['NEYVIA_MEMORY_SCOPE'] = os.environ.get('NEYVIA_MEMORY_SCOPE', '')
    bindings['NEYVIA_MEMORY_HOST_ROOT'] = os.environ.get('NEYVIA_MEMORY_HOST_ROOT', '')
    for name, value in bindings.items():
        args.extend(["--config", f"mcp_servers.neyvia.env.{name}={json.dumps(value)}"])
    approvals = []
    if situation_interface:
        # This gateway enforces the run's read-only policy and exact browser grant.
        approvals.append('"neyvia.situation"={approval_mode="approve"}')
        approvals.append('"neyvia.tools.invoke"={approval_mode="approve"}')
    if session_id or (not read_only and native_mutation_tools):
        # Carry the existing scoped grant into Codex's MCP policy. The gateway
        # independently enforces the tool allowlist and stable action identity.
        # CLI override paths split on every dot, including quoted segments.
        # Keep the dotted MCP tool name inside the TOML value instead.
        approvals.append('"neyvia.native.call"={approval_mode="approve"}')
        # CL is the progressive gateway; the host checks every nested action
        # against this run's exact native grants, including read-only runs.
        approvals.append('"neyvia.cl"={approval_mode="approve"}')
    if approvals:
        args.extend(["--config", "mcp_servers.neyvia.tools={" + ",".join(approvals) + "}"])
    return args


def _run_codex_supervised(
    config: NeyviaAgentConfig,
    prompt: str,
    gateway: NeyviaToolGateway | None,
    instructions: str | None = None,
    *, cl_task_id: str = "",
) -> dict[str, Any]:
    command = _codex_cli_command()
    if not command:
        raise RuntimeError("Codex CLI is unavailable for OWN's supervised subscription transport.")
    # Codex receives the saved text through baseInstructions and the
    # operator's task as user content. Runtime access limits live in sandbox and
    # MCP configuration, so they do not need a competing user-message preamble.
    supervisor_prompt = prompt
    reasoning = _agent_reasoning_resolution(config)
    reasoning_args = (
        ["--config", f'model_reasoning_effort="{reasoning["wireEffort"]}"']
        if reasoning["wireEffort"] else []
    )
    if os.environ.get("NEYVIA_STREAM_EVENTS") == "1":
        from .codex_app_server_stream import run_codex_streamed

        def forward_event(event: dict[str, Any]) -> None:
            print("FLUXIO_EVENT:" + json.dumps(event, ensure_ascii=True), flush=True)

        streamed = run_codex_streamed(
            command=command,
            config_args=_codex_neyvia_mcp_args(
                config.root,
                read_only=not config.allow_mutations,
                session_id=config.session_id,
                situation_interface=config.situation_interface,
                permission_mode=config.permission_mode,
                cl_task_id=cl_task_id, task_goal_root=config.control_root or config.root, task_text=prompt,
                **({"native_mutation_tools": config.native_mutation_tools}
                   if config.native_mutation_tools is not None else {}),
            ),
            cwd=config.root, model=config.model,
            effort=reasoning["wireEffort"],
            base_instructions=instructions if instructions is not None else _role_instructions(config),
            prompt=supervisor_prompt, allow_mutations=config.allow_mutations,
            permission_mode=config.permission_mode,
            timeout=config.timeout_seconds,
            on_event=forward_event,
        )
        return {**streamed, "toolGateway": gateway.search("", 20) if gateway else {
            "schema": "neyvia.agent-tool-search/v1", "status": "deferred_to_mcp",
            "flow": ["search", "describe", "call", "receipt"],
        },
                "transport": "codex-app-server"}
    args = [
        command,
        "exec",
        "--json",
        "--sandbox",
        ("danger-full-access" if config.permission_mode == "full-access" else "workspace-write") if config.allow_mutations else "read-only",
        "--skip-git-repo-check",
        "--model",
        config.model,
        *reasoning_args,
        "--config", "base_instructions=" + json.dumps(instructions if instructions is not None else _role_instructions(config)),
        "--config", 'developer_instructions=""',
        *_codex_neyvia_mcp_args(config.root, read_only=not config.allow_mutations, session_id=config.session_id,
                              situation_interface=config.situation_interface,
                              permission_mode=config.permission_mode,
                              cl_task_id=cl_task_id, task_goal_root=config.control_root or config.root, task_text=prompt,
                              **({"native_mutation_tools": config.native_mutation_tools} if config.native_mutation_tools is not None else {})),
        "--cd",
        str(config.root),
        "-",
    ]
    completed = capture_bounded_process(
        _popen_args(args),
        cwd=str(config.root),
        env=dict(os.environ),
        input_text=supervisor_prompt,
        timeout=config.timeout_seconds,
    )
    assistant_parts: list[str] = []
    final_text = ""
    external_session_id = ""
    tool_events: list[str] = []
    reported_usage = None
    for raw_line in (completed["stdout"] or "").splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "turn.completed" and isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
            if isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
                reported_usage = {
                    "requests": 1,
                    "inputTokens": usage["input_tokens"],
                    "outputTokens": usage["output_tokens"],
                    "cachedInputTokens": usage.get("cached_input_tokens", 0),
                    "totalTokens": usage["input_tokens"] + usage["output_tokens"],
                    "reportedByTransport": True,
                }
        external_session_id = _session_id(payload) or external_session_id
        text, terminal = _assistant_text(payload)
        if text:
            if terminal:
                final_text = text
            elif not assistant_parts or assistant_parts[-1] != text:
                assistant_parts.append(text)
        for label in _tool_labels(payload):
            if label not in tool_events:
                tool_events.append(label)
    output = (final_text or "".join(assistant_parts)).strip()
    failure = None
    if completed["timedOut"] or completed["returncode"] != 0 or not output:
        failure = {
            "code": "executor_timeout" if completed["timedOut"] else "executor_failed" if completed["returncode"] != 0 else "empty_output",
            "exitCode": completed["returncode"],
            "processTreeStopped": completed["processTreeStopped"],
            "partialOutput": output,
            "observedToolLabels": tool_events,
            "sideEffects": "uncertain" if config.allow_mutations else "source_read_only_task_records_possible",
            "retrySafety": "reconcile_before_retry",
            "nextAction": "Inspect this receipt and saved action receipts, reconcile current target state, then resume unfinished work. Do not repeat uncertain actions.",
        }
        output = ("The executor exceeded its time limit." if completed["timedOut"] else "The executor did not complete successfully.") + " Partial progress was preserved in the run receipt; reconcile it before continuing."
    return {
        "output": output,
        "failure": failure,
        "externalSessionId": external_session_id,
        "toolEvents": tool_events,
        "toolGateway": gateway.search("", 20) if gateway else {
            "schema": "neyvia.agent-tool-search/v1", "status": "deferred_to_mcp",
            "flow": ["search", "describe", "call", "receipt"],
        },
        "usage": reported_usage,
    }


async def run_neyvia_agent(
    config: NeyviaAgentConfig,
    prompt: str,
    *,
    provider: OpenAIProvider | None = None,
) -> dict[str, Any]:
    from .execution_ownership import run_owned
    selected = config.validated()
    return await run_owned(selected.control_root or selected.root, selected.session_id,
                           lambda: _run_neyvia_agent_owned(selected, prompt, provider=provider))


def _product_cl_completion(config, gateway, task_id):
    """Separate reply transport completion from a verified CL task outcome."""
    from .cl.protocol import Protocol
    from .ui_command_bus import bus_for
    root = config.control_root or config.root
    scope = os.environ.get("NEYVIA_PROOF_CONVERSATION_ID") or config.session_id
    try:
        if gateway is not None and hasattr(gateway, "_cl_protocol"):
            result = gateway._cl_protocol.completion()
        else:
            bus = bus_for(root)
            saved = bus.get(Protocol.completion_key(scope, task_id))
            authored = bus.get("cl:task-goals:" + scope, [])
            if saved is None:
                result = ({"active": True, "status": "incomplete", "doneStatus": "unverified",
                           "reason": "Authored task G requires explicit successful done in this run"} if authored
                          else {"active": False, "status": "not_applicable"})
            elif not saved.get("active") and not authored:
                result = {"active": False, "status": "not_applicable"}
            elif saved.get("doneStatus") != "ok":
                result = {"active": True, "status": "incomplete", "doneStatus": saved.get("doneStatus") or "unverified",
                          "reason": "Explicit successful done required in this run"}
            else:
                current = NeyviaToolGateway(config.root, allow_mutations=config.allow_mutations,
                    action_scope=scope, allowed_mutation_tools=set(config.native_mutation_tools) if config.native_mutation_tools is not None else None,
                    permission_mode=config.permission_mode)
                current.task_goal_root = root
                try:
                    result = Protocol(current).completion(saved=saved)
                finally:
                    if hasattr(current.native, "_codex_plugins"):
                        current.native._codex_plugins.close()
        return {**result, "taskId": task_id, "boundary": "observer-verified CL task" if result["active"] else "reply transport only"}
    except Exception as exc:
        return {"active": True, "status": "incomplete", "taskId": task_id,
                "reason": "CL completion observer failed: " + str(exc), "boundary": "unverified CL task"}


async def _run_neyvia_agent_owned(
    config: NeyviaAgentConfig,
    prompt: str,
    *,
    provider: OpenAIProvider | None = None,
) -> dict[str, Any]:
    selected = config.validated()
    if not prompt.strip():
        raise ValueError("Neyvia Agent prompt cannot be empty.")
    transport = _selected_transport(selected, provider_supplied=provider is not None)
    if selected.goal_mode and transport == "codex-cli":
        raise ValueError("Goal mode needs a direct Neyvia Native model connection. This connection uses the Codex CLI, which owns its execution loop.")
    credential_env = selected.api_key_env or "provider-object"
    control_root = selected.control_root or selected.root
    from .neyvia_memory_tools import launcher_context, ingest_teaching
    memory_context = launcher_context(control_root, project=selected.root)
    memory_write = None
    if memory_context:
        from .cue_memory import CueMemoryStore
        from .memory_recall import TRUST, END, recall
        from .prompt_contract import PromptContractError
        memory_store = CueMemoryStore(memory_context)
        if not memory_store.session_valid(selected.session_id):
            raise PromptContractError('Memory changed since this Native chat received it; start a fresh chat')
        prepared = prompt.startswith(TRUST) and END in prompt
        if prepared:
            prompt = prompt.split(END, 1)[1].lstrip()
        else:
            memory_write = ingest_teaching(memory_context, prompt)
        if not memory_store.session_valid(selected.session_id):
            raise PromptContractError('The memory request was applied; start a fresh chat for its new context')
        if transport == 'codex-cli':
            packet = recall(memory_context, {'intent': prompt}, destination='provider', write_receipt=memory_write)
            if packet['selected'] or memory_write or prepared:
                memory_store.mark_session(selected.session_id, packet['generation'])
            prompt = packet['section'] + '\n' + prompt if packet['section'] else prompt
    if selected.situation_interface:
        from .situation_interface import SituationStore
        work_id = os.environ.get("NEYVIA_PROOF_CONVERSATION_ID") or selected.session_id
        situation = SituationStore(control_root, work_id)
        if situation._read()["contract"] is None:
            situation.define(prompt, source="runtime_request")
    state_root = control_root / ".agent_control" / "neyvia_agent"
    state_root.mkdir(parents=True, exist_ok=True)
    # Freeze this run's instructions once. A user edit during execution belongs
    # to the next reply, and the receipt must hash what this model actually saw.
    timing_origin = time.perf_counter()
    timing_phases: dict[str, int] = {}
    run_instructions = _role_instructions(selected)
    timing_phases["instructionsReady"] = int((time.perf_counter() - timing_origin) * 1000)
    started = datetime.now(timezone.utc)
    failure = None
    cl_task_id = "cl-task-" + uuid.uuid4().hex
    if transport == "codex-cli":
        # The Codex MCP server owns discovery and compiles on the first tool
        # search. Loading a second catalog here delays every ordinary reply.
        gateway = None
        timing_phases["toolsDeferred"] = int((time.perf_counter() - timing_origin) * 1000)
        supervised = await asyncio.to_thread(
            _run_codex_supervised,
            selected,
            prompt,
            gateway,
            run_instructions,
            cl_task_id=cl_task_id,
        )
        timing_phases["supervisorReturned"] = int((time.perf_counter() - timing_origin) * 1000)
        output = supervised["output"]
        failure = supervised.get("failure")
        usage_payload = supervised.get("usage") or {
            "requests": 1,
            "inputTokens": None,
            "outputTokens": None,
            "totalTokens": None,
            "reportedByTransport": False,
        }
        run_items = [f"CodexTool:{label}" for label in supervised["toolEvents"]]
        external_session_id = supervised["externalSessionId"]
        tool_gateway = supervised["toolGateway"]
        credential_env = "CODEX_HOME"
    else:
        from agents import Runner, SQLiteSession
        from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent

        if provider is None:
            provider, credential_env = _provider_from_config(selected)
        agent, run_config, gateway = build_neyvia_agent(selected, provider=provider, instructions=run_instructions)
        gateway.cl_task_id = cl_task_id
        gateway.cl_task_text = prompt
        if selected.goal_mode and selected.agent_role == "chat":
            from .session_compaction import _authored_request
            gateway.goal_loop.activate(_authored_request(prompt)[0] or prompt)
        gateway.compile(prompt, min(selected.max_turns, 20))
        session = SQLiteSession(selected.session_id, state_root / "sessions.sqlite3")
        stream_enabled = os.environ.get("NEYVIA_STREAM_EVENTS") == "1"
        streamed_result = None
        streamed_tool_names: dict[str, str] = {}
        started_answer_items: set[tuple[str, str, str]] = set()
        current_response_id = ""

        def emit_sdk_stream_event(event: dict[str, Any]) -> None:
            print("FLUXIO_EVENT:" + json.dumps(event, ensure_ascii=True), flush=True)

        def forward_sdk_stream_event(event: Any) -> None:
            """Translate SDK events to the stable chat stream envelope.

            Both Agents SDK transports (Responses and Chat Completions) normalize
            provider chunks to Responses stream events, so this path consumes the
            provider's actual deltas without guessing text from the final reply.
            """
            nonlocal current_response_id
            if not stream_enabled:
                return
            if isinstance(event, RawResponsesStreamEvent):
                raw = event.data
                event_type = str(getattr(raw, "type", ""))
                if event_type == "response.created":
                    response = getattr(raw, "response", None)
                    current_response_id = str(getattr(response, "id", "") or "")
                    return
                if event_type == "response.output_item.added":
                    item = getattr(raw, "item", None)
                    item_type = str(getattr(item, "type", "") or "")
                    if item_type == "message":
                        provider_data = getattr(item, "provider_data", None)
                        provider_data = provider_data if isinstance(provider_data, dict) else {}
                        response_id = str(provider_data.get("response_id") or current_response_id)
                        if provider_data.get("response_id"):
                            current_response_id = response_id
                        item_id = str(getattr(item, "id", "") or "")
                        output_index_value = getattr(raw, "output_index", None)
                        output_index = str(output_index_value if output_index_value is not None else "")
                        answer_key = (response_id, item_id, output_index)
                        if answer_key not in started_answer_items:
                            started_answer_items.add(answer_key)
                            emit_sdk_stream_event({
                                "kind": "runtime.answer_start",
                                "message": "",
                                "data": {
                                    "responseId": response_id,
                                    "itemId": item_id,
                                    "outputIndex": output_index_value,
                                    "eventType": event_type,
                                },
                            })
                    return
                if event_type == "response.output_text.delta":
                    delta = getattr(raw, "delta", "")
                    if isinstance(delta, str) and delta:
                        response_id = str(getattr(raw, "response_id", "") or current_response_id)
                        item_id = str(getattr(raw, "item_id", "") or "")
                        output_index_value = getattr(raw, "output_index", None)
                        output_index = str(output_index_value if output_index_value is not None else "")
                        answer_key = (response_id, item_id, output_index)
                        if answer_key not in started_answer_items:
                            started_answer_items.add(answer_key)
                            emit_sdk_stream_event({
                                "kind": "runtime.answer_start",
                                "message": "",
                                "data": {
                                    "responseId": response_id,
                                    "itemId": item_id,
                                    "outputIndex": output_index_value,
                                    "eventType": event_type,
                                },
                            })
                        emit_sdk_stream_event({
                            "kind": "runtime.answer_delta",
                            "message": delta,
                            "data": {
                                "eventType": event_type,
                                "responseId": response_id,
                                "itemId": item_id,
                                "outputIndex": output_index_value,
                            },
                        })
                elif event_type == "response.reasoning_text.delta":
                    public_event = _public_thinking_event(raw, selected, current_response_id)
                    if public_event:
                        emit_sdk_stream_event(public_event)
                elif event_type == "response.reasoning_summary_text.delta":
                    # Deliberately forward provider-authored summaries only. Raw
                    # hidden reasoning tokens are not exposed to the chat UI.
                    delta = getattr(raw, "delta", "")
                    if isinstance(delta, str) and delta:
                        emit_sdk_stream_event({
                            "kind": "runtime.reasoning_summary_delta",
                            "message": delta,
                            "data": {"eventType": event_type},
                        })
                return
            if isinstance(event, RunItemStreamEvent):
                event_name = str(getattr(event, "name", ""))
                if event_name not in {"tool_called", "tool_output"}:
                    return
                item = event.item
                raw_item = getattr(item, "raw_item", None)

                def item_value(source: Any, *names: str) -> Any:
                    for name in names:
                        value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
                        if value is not None:
                            return value
                    return None

                raw_id = item_value(raw_item, "id", "call_id")
                raw_call_id = item_value(item, "call_id") or item_value(raw_item, "call_id", "id")
                call_id = str(raw_call_id or raw_id or "")
                tool_name = str(
                    getattr(item, "tool_name", None)
                    or getattr(item, "title", None)
                    or item_value(raw_item, "name", "tool_name")
                    or streamed_tool_names.get(call_id)
                    or "tool"
                )[:160]
                tool_input = item_value(raw_item, "arguments", "input", "query", "command", "changes")
                gateway_tool = tool_name
                if event_name == "tool_called" and tool_name == "neyvia_native_call":
                    try:
                        invocation = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
                        if isinstance(invocation, dict) and invocation.get("tool_id"):
                            tool_name = str(invocation["tool_id"])
                            arguments = invocation.get("arguments_json") or "{}"
                            tool_input = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except (ValueError, TypeError):
                        pass
                elif event_name == "tool_called" and tool_name == "neyvia_terminal_exec":
                    tool_name = "terminal.exec"
                elif event_name == "tool_output" and call_id in streamed_tool_names:
                    tool_name = streamed_tool_names[call_id]
                if event_name == "tool_called" and call_id:
                    streamed_tool_names[call_id] = tool_name
                tool_output = getattr(item, "output", None) if event_name == "tool_output" else None
                if tool_output is None and event_name == "tool_output":
                    tool_output = item_value(raw_item, "output", "result", "content")
                tool_error = item_value(item, "error", "exception") or item_value(raw_item, "error")
                if not tool_error and event_name == "tool_output":
                    tool_error = _tool_output_error(tool_output)
                status = "started" if event_name == "tool_called" else ("failed" if tool_error else "completed")
                emit_sdk_stream_event({
                    "kind": "runtime.tool",
                    "message": tool_name,
                    "data": {
                        "eventType": event_name,
                        "tool": tool_name,
                        "gatewayTool": gateway_tool,
                        "toolStatus": status,
                        "status": status,
                        "itemId": str(raw_id or ""),
                        "callId": call_id,
                        "input": safe_tool_display(tool_input),
                        "output": safe_tool_display(tool_output) if event_name == "tool_output" and not tool_error else "",
                        "error": safe_tool_display(tool_error) if tool_error else "",
                    },
                })

        accumulated_usage = {"requests": 0, "inputTokens": 0, "outputTokens": 0, "totalTokens": 0,
                             "reportedByTransport": True, "cachedInputTokens": 0}
        accumulated_items = []

        async def cancel_and_drain_provider_stream() -> None:
            if streamed_result is None:
                return
            streamed_result.cancel(mode="immediate")
            try:
                async for _stream_event in streamed_result.stream_events():
                    pass
            except BaseException:
                pass
            run_task = streamed_result.run_loop_task
            if run_task is not None:
                await asyncio.gather(run_task, return_exceptions=True)

        async def execute_goal_rounds():
            nonlocal streamed_result
            next_input = prompt
            while True:
                from agents.exceptions import MaxTurnsExceeded
                batch_limit = False
                cl_active = gateway._cl_protocol.host.task_active or gateway._cl_protocol.host.task_goals
                round_limit = max(1, selected.max_turns - accumulated_usage["requests"]) if cl_active else selected.max_turns
                try:
                    if stream_enabled:
                        streamed_result = Runner.run_streamed(
                            agent, next_input, max_turns=round_limit,
                            run_config=run_config, session=session,
                        )
                        async for stream_event in streamed_result.stream_events():
                            forward_sdk_stream_event(stream_event)
                        if streamed_result.run_loop_exception is not None:
                            raise streamed_result.run_loop_exception
                        round_result = streamed_result
                    else:
                        round_result = await Runner.run(
                            agent, next_input, max_turns=round_limit,
                            run_config=run_config, session=session,
                        )
                except MaxTurnsExceeded as exc:
                    if gateway.goal_loop.state is None:
                        raise
                    # SDK batches are checkpoints, not goal termination. The SDK
                    # has saved completed tool pairs to the same durable session.
                    round_result = streamed_result if stream_enabled else exc.run_data
                    if round_result is None:
                        raise
                    batch_limit = True
                usage = round_result.context_wrapper.usage
                from .model_usage import accumulate_sdk_usage
                # Some compatible streams omit usage entirely. Completed response
                # records still contribute to the cumulative usage receipt.
                round_requests = max(usage.requests, len(round_result.raw_responses), 1)
                accumulate_sdk_usage(accumulated_usage, usage, round_requests)
                run_config.call_model_input_filter.completed_usage = dict(accumulated_usage)
                accumulated_items.extend(type(item).__name__ for item in round_result.new_items)
                gateway.goal_loop.observe(round_result.new_items)
                next_input = gateway.goal_loop.after_round(
                    requests=round_requests,
                    pending_question=bool(list_questions(control_root, selected.session_id)),
                    batch_limit=batch_limit,
                    final_output=str(getattr(round_result, "final_output", "") or ""),
                )
                cl_completion = _product_cl_completion(selected, gateway, cl_task_id)
                if (cl_completion["active"] and cl_completion["status"] != "completed"
                        and not list_questions(control_root, selected.session_id)
                        and gateway.goal_loop.stop_reason not in {"paused", "blocked", "input_required"}):
                    # CL cannot turn a final model message into task completion.
                    # Continuation shares the caller's request and time budgets.
                    if accumulated_usage["requests"] >= selected.max_turns:
                        return round_result
                    next_input = ("[Neyvia CL task remains unfinished] " + cl_completion.get("reason", "")
                                  + ". Continue the current authorized task. Author observer G if absent; "
                                  "fix failing G, then explicitly call done(\"summary\"). A final reply alone does not finish it.")
                if not next_input:
                    return round_result
                if stream_enabled:
                    emit_sdk_stream_event({"kind": "runtime.progress",
                        "message": "Continuing the active task: " + (gateway.goal_loop.state or {}).get("nextAction", "Verify CL G and call done"),
                        "data": {"goalLoop": gateway.goal_loop.receipt()}})

        try:
            # One deadline spans all rounds. Continuation never resets caller budgets.
            execution = execute_goal_rounds()
            result = await execution if selected.timeout_seconds is None else await asyncio.wait_for(
                execution, timeout=selected.timeout_seconds,
            )
        except asyncio.CancelledError:
            gateway.goal_loop.stop_reason = "cancelled"
            gateway.goal_loop.save()
            if streamed_result is not None:
                await cancel_and_drain_provider_stream()
            raise
        except Exception as exc:
            gateway.goal_loop.stop_reason = "failed"
            gateway.goal_loop.save()
            if streamed_result is not None and not streamed_result.is_complete:
                await cancel_and_drain_provider_stream()
            result = None
            failure = _failure_for_agent_exception(
                exc, max_turns=selected.max_turns, session_id=selected.session_id,
                session_database=state_root / "sessions.sqlite3",
            )
            if stream_enabled:
                emit_sdk_stream_event({
                    "kind": "runtime.stream_error",
                    "message": failure.get("message") or "The Native run failed before completing.",
                    "status": "failed",
                    "data": {"code": failure["code"], "exceptionType": type(exc).__name__,
                             **({"diagnostic": failure.get("diagnostic"),
                                 "origin": failure.get("origin")} if failure.get("origin") else {}),
                             **({"maxTurns": selected.max_turns} if failure["code"] == "run_limit_reached" else {})},
                })
        finally:
            if getattr(gateway, "situation_service", None) is not None:
                gateway.situation_service.close()
            if hasattr(gateway.native, "_codex_plugins"):
                gateway.native._codex_plugins.close()
        if result is not None:
            output = str(getattr(result, "final_output", "") or "")
            usage_payload = accumulated_usage
            run_items = accumulated_items
            goal_stop = gateway.goal_loop.stop_reason
            if gateway.goal_loop.state and goal_stop not in {"completed", "input_required"}:
                output += "\n\nGoal remains unfinished (" + (goal_stop or "interrupted") + "). " + (
                    gateway.goal_loop.state.get("blocker") or gateway.goal_loop.state.get("nextAction", "")
                )
        else:
            output = (
                failure["message"] + " Saved session and action receipts are available; resume the unfinished work."
                if failure and failure.get("message")
                else "The executor failed before completing the reply. Saved session and action evidence remain available for recovery."
            )
            usage_payload = {**getattr(run_config.call_model_input_filter, "live_usage", accumulated_usage),
                             "coverage": "partial", "reportedByTransport": False}
            run_items = accumulated_items
        external_session_id = ""
        tool_gateway = gateway.search("", 20)
        from .model_usage import include_compaction
        usage_payload = include_compaction(usage_payload, run_config.call_model_input_filter.compactor)
    finished = datetime.now(timezone.utc)
    timing_phases["executionFinished"] = int((time.perf_counter() - timing_origin) * 1000)
    pending_questions = list_questions(control_root, selected.session_id)
    cl_completion = _product_cl_completion(selected, gateway, cl_task_id)
    from .manual_first import core_tools
    native_mcp_tool_count = len(core_tools(ask_user=bool(selected.session_id)))
    cl_incomplete = cl_completion["active"] and cl_completion["status"] != "completed"
    if cl_incomplete and not failure and not pending_questions:
        output += "\n\nCL task remains unfinished: " + cl_completion.get("reason", "Current observer G and explicit done are required")
    if pending_questions and not failure:
        pending = pending_questions[-1]
        output = (pending.get("context", "") + "\n\n" if pending.get("context") else "") + pending["question"] + ("\n" + "\n".join(f"â€¢ {option}" for option in pending["options"]) if pending["options"] else "")
    from .workspace_intelligence import COLLABORATION_NOTE_TOOLS
    receipt = {
        "schema": NEYVIA_AGENT_RECEIPT_SCHEMA,
        "runId": f"neyvia_{uuid.uuid4().hex}",
        "sessionId": selected.session_id,
        "status": "failed" if failure else "input_required" if pending_questions else (
            "incomplete" if cl_incomplete else "incomplete" if gateway and hasattr(gateway, "goal_loop") and gateway.goal_loop.state
            and gateway.goal_loop.state["status"] != "completed" else "completed" if output.strip() else "failed"),
        "recovery": failure,
        "pendingQuestions": pending_questions,
        "agentRole": selected.agent_role,
        "promptHash": canonical_hash(run_instructions),
        "promptContract": run_config.call_model_input_filter.receipt() if transport != "codex-cli" else {
            "mode": "base_instructions_replacement", "boundary": "codex_configuration",
            "remoteProviderInstructionsObservable": False,
        },
        "workspaceRoot": str(selected.root),
        "controlRoot": str(control_root),
        "model": selected.model,
        "reasoningResolution": _agent_reasoning_resolution(selected),
        "provider": {
            "kind": (
                "codex-app-server-supervised-subscription"
                if transport == "codex-cli" and supervised.get("transport") == "codex-app-server"
                else "codex-cli-supervised-subscription"
                if transport == "codex-cli"
                else "openai-chat-completions-compatible"
                if transport == "chat-completions"
                else "openai-responses-compatible"
            ),
            "transport": supervised.get("transport", transport) if transport == "codex-cli" else transport,
            "baseUrlConfigured": bool(
                selected.base_url or os.environ.get("OPENAI_BASE_URL")
            ),
            "credentialEnv": credential_env,
            "credentialValueStored": False,
        },
        "policy": {
            "planFirst": True,
            "allowMutations": selected.allow_mutations,
            "permissionMode": selected.permission_mode,
            "allowedNativeMutationTools": list(selected.native_mutation_tools or ()),
            "scopedTaskRecordTools": sorted(COLLABORATION_NOTE_TOOLS) if selected.session_id else [],
            "maxTurns": selected.max_turns,
            "goalMode": selected.goal_mode and transport != "codex-cli",
            "executorTimeoutSeconds": selected.timeout_seconds,
            "progressiveTools": True,
            "situationInterface": selected.situation_interface,
            "specialistsEnabled": selected.enable_specialists and selected.agent_role == "chat" and transport != "codex-cli",
            "turnLimitEnforcement": "sdk-batch-with-goal-continuation" if transport != "codex-cli" else "prompt-and-process-timeout",
            "maxOutputTokens": selected.max_output_tokens if transport != "codex-cli" else None,
            "nativeToolLoopActive": transport in {
                "responses",
                "chat-completions",
                "codex-cli",
            },
            "modelToolTransport": (
                "compact-neyvia-mcp"
                if transport == "codex-cli"
                else "chat-completions-function-tools"
                if transport == "chat-completions"
                else "responses-function-tools"
            ),
            "modelVisibleToolCount": (
                native_mcp_tool_count
                if transport == "codex-cli"
                else len(agent.tools)
            ),
            "toolCountScope": "configured Neyvia gateways; CLI may own additional tools" if transport == "codex-cli" else "SDK agent tools",
            "fullCatalogDeferred": True,
        },
        "goalLoop": gateway.goal_loop.receipt() if gateway and hasattr(gateway, "goal_loop") else None,
        "clCompletion": cl_completion,
        "toolGateway": tool_gateway,
        "toolCompiler": gateway.compiler_snapshot() if gateway else {"status": "deferred_to_mcp", "providerCalls": 0},
        "toolLoopReceipts": gateway.tool_loop_receipts if gateway else [],
        "output": output,
        "usage": usage_payload,
        "transportTiming": ({
            "phaseTimingsMs": supervised.get("phaseTimingsMs") or {},
            "localSetupMs": supervised.get("localSetupMs"),
            "providerToFirstOutputMs": supervised.get("providerToFirstOutputMs"),
            "agentPhasesMs": timing_phases,
        } if transport == "codex-cli" and supervised.get("transport") == "codex-app-server" else None),
        "runItems": run_items,
        "externalRuntimeSessionId": external_session_id,
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "finishedAt": finished.isoformat().replace("+00:00", "Z"),
        "durationMs": max(1, int((finished - started).total_seconds() * 1000)),
    }
    receipt_path = state_root / "receipts" / f"{receipt['runId']}.json"
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receiptPath": str(receipt_path)}


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(
        description="Run Neyvia's native provider-neutral agent."
    )
    from .proofs_d_neyvia import agent_version
    parser.add_argument("--version", action="version", version=agent_version())
    parser.add_argument("prompt")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--control-root",
        type=Path,
        default=None,
        help=(
            "Canonical Neyvia state/tool root. Keep --root as the isolated "
            "execution workspace when read-only isolation is active."
        ),
    )
    parser.add_argument("--session-id", default=f"session-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--provider-id", default="", help="Provider identity used for saved prompt scope selection.")
    parser.add_argument("--reasoning-effort", default="high",
                        choices=["default", "none", "low", "medium", "high", "xhigh", "max", "ultra"])
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument(
        "--transport",
        choices=["auto", "responses", "chat-completions", "codex-cli"],
        default="auto",
    )
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--goal-mode", action="store_true", help="Continue the current goal across SDK batches until completion, input or a demonstrated blocker.")
    parser.add_argument("--timeout-seconds", type=int, help="Executor deadline, leaving the caller time to preserve the run receipt.")
    parser.add_argument("--agent-role", choices=ROLES, default="chat")
    parser.add_argument("--instructions-file", type=Path)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--allow-mutations", action="store_true")
    parser.add_argument("--permission-mode", choices=["read-only", "workspace", "full-access"], default="")
    parser.add_argument("--native-mutation-tool", action="append", default=None,
                        help="Restrict mutation authority to these named Native tools (repeatable).")
    parser.add_argument("--no-specialists", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    receipt = asyncio.run(
        run_neyvia_agent(
            NeyviaAgentConfig(
                root=args.root,
                session_id=args.session_id,
                control_root=args.control_root,
                model=args.model,
                provider_id=args.provider_id,
                reasoning_effort=args.reasoning_effort,
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                transport=args.transport,
                max_turns=args.max_turns,
                goal_mode=args.goal_mode,
                timeout_seconds=args.timeout_seconds,
                allow_mutations=args.allow_mutations,
                native_mutation_tools=tuple(args.native_mutation_tool) if args.native_mutation_tool is not None else None,
                permission_mode=args.permission_mode,
                enable_specialists=not args.no_specialists,
                agent_role=args.agent_role,
                instructions_file=args.instructions_file,
                max_output_tokens=args.max_output_tokens,
            ),
            args.prompt,
        )
    )
    if os.environ.get("FLUXIO_SESSION_FILE"):
        # The worker consumes line events. Keep the full receipt on disk instead
        # of turning its capability catalog into hundreds of activity messages.
        print("FLUXIO_EVENT:" + json.dumps({
            "kind": "runtime.model_message",
            "message": receipt["output"],
            "status": receipt["status"],
            "data": {"receiptPath": receipt["receiptPath"]},
        }, ensure_ascii=True))
    elif args.json:
        # ASCII JSON survives Windows pipe code pages; json.loads restores the
        # original Unicode without losing accents, arrows, or non-Latin text.
        print(json.dumps(receipt, ensure_ascii=True,
                         indent=None if os.environ.get("NEYVIA_STREAM_EVENTS") == "1" else 2))
    else:
        print(receipt["output"])
        print(f"\nReceipt: {receipt['receiptPath']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
