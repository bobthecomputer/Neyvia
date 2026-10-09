"""Compact stdio MCP transport for model-facing N-E-Y-V-I-A tools."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, TextIO

from .subprocess_utils import install_hidden_subprocess_default


COMPACT_TOOL_NAMES = frozenset(
    {
        "neyvia.access.context",
        "neyvia.tools.search",
        "neyvia.tools.describe",
        "neyvia.workspace.browser",
        "neyvia.workspace.intent",
        "neyvia.workspace.prove",
        "neyvia.situation",
        "model.tools.compile",
        "model.tools.run",
    }
)


class CompactNeyviaMCPServer:
    """Keep the subscription-agent hot path limited to progressive gateways."""

    def __init__(self, root: str | Path, *, read_only: bool = False, session_id: str = "", native_mutation_tools: list[str] | None = None, situation_interface: bool = False, permission_mode: str = "") -> None:
        from .native_access import mutation_tools_for_mode
        self.root = Path(root)
        self.session_id = session_id
        self.read_only = bool(read_only)
        self.situation_interface = situation_interface
        self.explicit_permission_mode = bool(permission_mode)
        self.permission_mode = "read-only" if read_only else permission_mode or (
            "read-only" if read_only
            else "full-access" if native_mutation_tools and "terminal.exec" in native_mutation_tools
            else "workspace"
        )
        mode_grants = set(mutation_tools_for_mode(self.permission_mode))
        if self.permission_mode == "read-only":
            self.native_mutation_tools = set()
        elif native_mutation_tools is not None:
            # An explicit per-run grant is the same allowlist used by the SDK.
            # The gateway still enforces mode-specific rules such as Full access
            # for terminal commands; Read-only above always overrides the list.
            self.native_mutation_tools = set(native_mutation_tools)
        elif self.explicit_permission_mode:
            self.native_mutation_tools = mode_grants
        else:
            self.native_mutation_tools = set()
        self.read_only = self.permission_mode == "read-only"
        # CL calls use the native gateway directly. Build the broad MCP
        # catalog only when a catalog/legacy tool actually needs it.
        self._server = None
        self.proof_conversation_id = os.environ.get("NEYVIA_PROOF_CONVERSATION_ID", "")
        proof_root = os.environ.get("NEYVIA_PROOF_ROOT", "")
        if self.proof_conversation_id and proof_root:
            from .neyvia_conversations import NeyviaConversationStore
            from .crashproof import CrashProofStore
            self.server.conversations = NeyviaConversationStore(proof_root, database_path=CrashProofStore(proof_root).database_path)
            self.server.conversations.get_conversation(self.proof_conversation_id)
        self._native = None

    @property
    def server(self):
        if self._server is None:
            from .neyvia_mcp import NeyviaMCPServer
            self._server = NeyviaMCPServer(self.root)
        return self._server

    @server.setter
    def server(self, value):
        self._server = value

    def _gateway(self):
        if self._native is None:
            from .neyvia_gateway import NeyviaToolGateway
            self._native = NeyviaToolGateway(self.root, allow_mutations=not self.read_only,
                action_scope=self.proof_conversation_id or self.session_id,
                action_root=Path(os.environ["NEYVIA_PROOF_ROOT"]) if self.proof_conversation_id and os.environ.get("NEYVIA_PROOF_ROOT") else self.root,
                allowed_mutation_tools=self.native_mutation_tools,
                permission_mode=self.permission_mode)
            self._native.cl_task_id = os.environ.get("NEYVIA_CL_TASK_ID", "")
            from .neyvia_memory_tools import launcher_context
            self._native.memory_context = launcher_context(Path(os.environ.get('NEYVIA_PROOF_ROOT') or self.root), project=self.root)
            self._native.cl_task_text = os.environ.get("NEYVIA_TASK_TEXT")
            self._native.task_goal_root = Path(os.environ.get("NEYVIA_CL_GOAL_ROOT") or self.root)
        return self._native

    def _command_capability_summary(self) -> str:
        try:
            environment = self._gateway().call_native("runtime.environment", {})
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
        workspace = str(environment.get("workspaceRoot") or self.root)
        permitted = "terminal.exec" in self.native_mutation_tools and not self.read_only
        return (
            f"Current Native mode: {self.permission_mode}. Selected workspace: {workspace}. "
            f"Detected command routes: {', '.join(available_labels) if available_labels else 'none detected (runtime.environment inspection failed or found none)'}. "
            f"Local command execution: {'permitted' if permitted else 'not permitted in this run'}; "
            "diagnostic availability does not grant execution permission. Inspect runtime.environment for command routes and the relevant tool/device inventory before claiming a command or device is absent; runtime.environment does not enumerate USB devices."
        )

    def _native_discovery(self, tool: dict[str, Any]) -> dict[str, Any]:
        from .workspace_intelligence import COLLABORATION_NOTE_TOOLS
        managed_note = tool["name"] in COLLABORATION_NOTE_TOOLS and bool(self.session_id or self.proof_conversation_id)
        mutation = tool.get("mutability_class") not in {"read", "none"}
        observational_capture = self.read_only and tool["name"] == "preview.screenshot"
        return {**{key:value for key,value in tool.items() if key != "core"},
                "catalogCore": bool(tool.get("core")), "startupCore": False,
                "kind": "native", "callTarget": "neyvia.native.call",
                "callArguments": {"toolId": tool["name"]},
                "callInstructions": ("Pass the inputSchema fields in arguments; include a stable actionId for mutations. "
                    + ("terminal.exec requires Full access in the composer to bypass local approvals." if tool.get("name") == "terminal.exec" and self.permission_mode != "full-access" else "")),
                "actionIdRequired": mutation and not observational_capture,
                "allowedInRun": managed_note or observational_capture or not mutation or (not self.read_only and tool["name"] in self.native_mutation_tools),
                **({"capturePolicy": "Observational capture to a managed proof artifact; requested outputPath is ignored."} if observational_capture else {})}

    def _allowed(self, name: str, arguments: dict[str, Any]) -> bool:
        if not self.read_only:
            return True
        if name in {"neyvia.tools.search", "neyvia.tools.describe", "model.tools.compile"}:
            return True
        if name == "neyvia.situation":
            return arguments.get("verb") != "change"
        if name == "neyvia.workspace.prove":
            nested = arguments.get("arguments") or {}
            return (str(arguments.get("operation") or "").lower() in {"inspect", "find", "frame", "inspect_frame", "screenshot", "annotate"}
                    and isinstance(nested, dict) and not nested.get("outputPath") and not nested.get("outputDir"))
        if name == "model.tools.run":
            calls = arguments.get("calls")
            return bool(isinstance(calls, list) and 0 < len(calls) <= 12 and all(
                isinstance(call, dict)
                and str(call.get("callTarget") or call.get("tool") or "") != "model.tools.run"
                and self._allowed(str(call.get("callTarget") or call.get("tool") or ""), call.get("arguments") or {})
                for call in calls
            ))
        tool = next((item for item in self.server.tools if item.get("name") == name), None)
        return bool(tool and (tool.get("annotations") or {}).get("readOnlyHint"))

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("method") == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name in {"neyvia.cl", "neyvia.cl.describe"}:
                try:
                    from jsonschema import ValidationError
                    if self.session_id:
                        from .agent_questions import list_questions
                        if list_questions(self.root, self.session_id):
                            raise ValueError("User input required. End this turn and wait for an answer.")
                    arguments = self._gateway().native.prepare_arguments(name, arguments)
                    from .cl.protocol import Protocol
                    if not hasattr(self, "_cl_protocol"):
                        self._cl_protocol = getattr(self._gateway(), "_cl_protocol", None) or Protocol(self._gateway(), lazy_manuals=True)
                        self._native._cl_protocol = self._cl_protocol
                    value = (self._cl_protocol.run(arguments["lines"], action_id=arguments.get("actionId", ""), scope_tools=arguments.get("scopeTools"))
                             if name == "neyvia.cl" else {"ok":True,"text":self._cl_protocol.describe(**arguments)})
                    return {"jsonrpc":"2.0","id":request.get("id"),"result":{
                        "content":[{"type":"text","text":value["text"]}],"structuredContent":value,"isError":not value["ok"]}}
                except (ValueError, KeyError, OSError, RuntimeError, TypeError, ValidationError) as exc:
                    return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32003,"message":str(exc)}}
            if name.startswith(("neyvia.manual.", "neyvia.autopilot.", "neyvia.efficiency.")) or name in {"neyvia.verify.edges", "neyvia.verify.edges.status"}:
                try:
                    value = self._gateway().call_native(name, arguments)
                    return {"jsonrpc":"2.0","id":request.get("id"),"result":self.server._tool_result(value)}
                except Exception as exc:  # isolate malformed manual/schema input at the MCP boundary
                    return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32003,"message":str(exc)}}
            if name == "neyvia.tools.invoke":
                target = arguments.get("tool")
                nested = arguments.get("arguments")
                deferred = {row["name"] for row in self.server.tools} | COMPACT_TOOL_NAMES | {"neyvia.actions.inspect", "neyvia.operations.inspect", "neyvia.terminal.exec", "neyvia.ask_user"}
                if target not in deferred or not isinstance(nested,dict):
                    return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32003,"message":"Invoke needs a discovered gateway tool and an arguments object"}}
                # Preserve the selected gateway's grant and identity checks.
                return self.handle({**request,"params":{"name":target,"arguments":nested}})
            if name == "neyvia.access.context":
                from .native_access import access_context
                try:
                    environment = self._gateway().call_native("runtime.environment", {})
                    laya = self._gateway().call_native("laya.native.capabilities", {})
                    preview = {}
                    for tool_id, key in (("preview.inspect", "inspectAvailable"), ("preview.screenshot", "captureAvailable")):
                        try:
                            preview[key] = bool(self._gateway().native.describe(tool_id).get("available"))
                        except KeyError:
                            preview[key] = False
                    context = {**access_context(self.permission_mode, environment=environment, laya=laya, preview=preview,
                                                granted_tools=self.native_mutation_tools, mutations_allowed=not self.read_only,
                                                situation_interface=self.situation_interface),
                               "runtimeEnvironment": environment, "layaCapabilities": laya}
                    return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(context)}
                except (ValueError, KeyError, OSError, RuntimeError, TypeError) as exc:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": str(exc)}}
            if name == "neyvia.terminal.exec":
                try:
                    self._gateway()
                    result = self._native.call_native(
                        "terminal.exec",
                        {"command": arguments.get("command"), "shell": arguments.get("shell", "auto"),
                         "cwd": arguments.get("cwd", ""), "timeoutMs": arguments.get("timeoutMs", 30000),
                         "maxOutputChars": arguments.get("maxOutputChars", 12000)},
                        action_id=str(arguments.get("actionId") or ""),
                    )
                    return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(result)}
                except (ValueError, KeyError, OSError, RuntimeError, TypeError) as exc:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": str(exc)}}
            if name == "neyvia.situation":
                try:
                    from .agent_questions import list_questions
                    if self.session_id and list_questions(self.root,self.session_id):
                        raise PermissionError("User input is pending")
                    work_id = self.proof_conversation_id or self.session_id
                    if not work_id or arguments.get("workId",work_id)!=work_id:
                        raise PermissionError("Situation must use the run's durable work identity")
                    from .situation_interface import situation_arguments
                    args = situation_arguments(arguments)
                    result = self.server.situations.call(arguments["verb"],work_id,args,
                        may_change=not self.read_only and "workspace.browser" in self.native_mutation_tools)
                    return {"jsonrpc":"2.0","id":request.get("id"),"result":self.server.situations.tool_result(result)}
                except (ValueError,KeyError,OSError,RuntimeError,TypeError) as exc:
                    return {"jsonrpc":"2.0","id":request.get("id"),"error":{"code":-32003,"message":str(exc)}}
            if name == "neyvia.workspace.prove" and self.proof_conversation_id:
                arguments = {**arguments, "conversationId": self.proof_conversation_id}
                request = {**request, "params": {**params, "arguments": arguments}}
            if name in {"neyvia.workspace.browser", "neyvia.workspace.intent"}:
                if self.read_only:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": "Read-only MCP denied tool: neyvia.workspace.browser"}}
                if "workspace.browser" not in self.native_mutation_tools:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": "Browser interaction authority is not granted for this run; require scoped native mutation tool workspace.browser."}}
                operation = str(arguments.get("operation") or "").lower()
                if (name == "neyvia.workspace.intent" or operation in {"click", "fill", "press", "select", "toggle", "upload", "reload"}) and not str(arguments.get("actionId") or "").strip():
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": "Authorized browser mutations require a stable actionId."}}
            if self.session_id and name != "neyvia.ask_user":
                from .agent_questions import list_questions
                if list_questions(self.root, self.session_id):
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": "User input required. End this turn and wait for an answer."}}
            if name in {"neyvia.tools.search", "neyvia.tools.describe"}:
                try:
                    native = self._gateway().native
                    query = str(arguments.get("query" if name.endswith("search") else "name") or "").strip()
                    try:
                        exact = self._native_discovery(native.describe(query))
                    except KeyError:
                        exact = None
                    if exact:
                        result = {"tools": [exact], "flow": ["call"], "schema": "neyvia.progressive_tools.search.v1", "exactMatch": True} if name.endswith("search") else exact
                        return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(result)}
                    from .manual_first import core_tools, deferred_tools
                    deferred = next((row for row in [*self.server.tools,*deferred_tools(),*core_tools(ask_user=bool(self.session_id))] if row["name"] == query), None)
                    if name.endswith("describe") and deferred and query not in {"neyvia.manual.index", "neyvia.manual.load"}:
                        result = {**deferred, "callTarget":"neyvia.tools.invoke", "callArguments":{"tool":query}}
                        return {"jsonrpc":"2.0","id":request.get("id"),"result":self.server._tool_result(result)}
                    if name.endswith("search"):
                        limit = max(1, min(int(arguments.get("limit") or 8), 20))
                        native_rows = [self._native_discovery(row) for row in native.search(query, limit=max(1, limit // 2))]
                        managed = self.server._progressive.search(query, limit=max(1, limit - len(native_rows)))
                        if re.fullmatch(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+", query):
                            tools = native_rows + managed
                            matches = [row for row in tools if row.get("name") == query]
                            result = {"schema": "neyvia.progressive_tools.search.v1", "flow": ["describe", "call"] if matches else [],
                                      "tools": matches, "exactMatch": bool(matches), "alternatives": [] if matches else tools[:limit],
                                      "catalogSource": str(Path(__file__).resolve().parent),
                                      "hint": "An unavailable exact name must not be substituted with an alternative's schema."}
                            return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(result)}
                        result = {"schema": "neyvia.progressive_tools.search.v1", "flow": ["search", "describe", "call"],
                                  "tools": (native_rows + managed)[:limit]}
                        return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(result)}
                except (ValueError, OSError) as exc:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": str(exc)}}
            if name in {"neyvia.native.call", "neyvia.actions.inspect", "neyvia.operations.inspect", "neyvia.ask_user"}:
                try:
                    if name == "neyvia.ask_user":
                        from .agent_questions import request_question
                        if not self.session_id:
                            raise ValueError("Question tool requires an active session.")
                        result = request_question(self.root, self.session_id, arguments.get("question", ""),
                                                  arguments.get("options"), arguments.get("context", ""),
                                                  conversation_id=self.proof_conversation_id)
                    else:
                        self._gateway()
                        if name == "neyvia.operations.inspect":
                            operation_id = str(arguments.get("operationId") or "")
                            result = self._native.operations.inspect(operation_id) if operation_id else self._native.operations.list(limit=int(arguments.get("limit") or 50))
                        elif name == "neyvia.actions.inspect":
                            action_id = str(arguments.get("actionId") or "")
                            result = self._native.actions.inspect(action_id) if action_id else self._native.actions.list(after=str(arguments.get("after") or ""))
                        else:
                            result = self._native.call_native(str(arguments.get("toolId") or ""), arguments.get("arguments") or {}, action_id=str(arguments.get("actionId") or ""))
                    return {"jsonrpc": "2.0", "id": request.get("id"), "result": self.server._tool_result(result)}
                except (ValueError, KeyError, OSError) as exc:
                    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": str(exc)}}
        if self.read_only and request.get("method") == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if not self._allowed(name, arguments):
                return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32003, "message": f"Read-only MCP denied tool: {name or 'unknown'}"}}
        response = self.server.handle(request)
        if (
            response
            and request.get("method") == "tools/list"
            and isinstance(response.get("result"), dict)
        ):
            from .manual_first import core_tools
            result = response["result"]
            result["tools"] = core_tools(ask_user=bool(self.session_id))
            result["catalogPolicy"] = {"mode":"manual-first", "toolCount":len(result["tools"]), "fullCatalogDeferred":True}
        if response and request.get("method") == "initialize" and isinstance(response.get("result"),dict):
            from .manual_first import INSTRUCTIONS
            response["result"]["instructions"] = INSTRUCTIONS
        return response


def serve(
    root: str | Path,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    read_only: bool = False,
    session_id: str = "",
    native_mutation_tools: list[str] | None = None,
    situation_interface: bool = False,
    permission_mode: str = "",
) -> int:
    server = CompactNeyviaMCPServer(root, read_only=read_only, session_id=session_id, native_mutation_tools=native_mutation_tools, situation_interface=situation_interface, permission_mode=permission_mode)
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("MCP request must be an object.")
            response = server.handle(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            output_stream.write(
                json.dumps(response, ensure_ascii=True, separators=(",", ":"))
                + "\n"
            )
            output_stream.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    from .local_provisioning import ensure_bytecode
    ensure_bytecode()
    install_hidden_subprocess_default()
    # MCP JSON is UTF-8. Windows redirected stdin otherwise inherits the local
    # code page and silently corrupts non-ASCII file contents and arguments.
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Serve N-E-Y-V-I-A's compact model tool gateway over stdio MCP."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--native-mutation-tool", action="append", default=[])
    parser.add_argument("--permission-mode", choices=["read-only", "workspace", "full-access"], default="")
    parser.add_argument("--situation-interface", action="store_true")
    args = parser.parse_args(argv)
    return serve(args.root, read_only=args.read_only, session_id=args.session_id, native_mutation_tools=args.native_mutation_tool or None, situation_interface=args.situation_interface, permission_mode=args.permission_mode)


if __name__ == "__main__":
    raise SystemExit(main())
