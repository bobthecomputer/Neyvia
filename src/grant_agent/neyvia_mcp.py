from __future__ import annotations

from .proofs_c_models import checked

import hashlib
import json
import re
import urllib.parse
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capability_service import (
    CapabilityService,
    register_with_progressive_surface as register_capability_tools,
)
from .crashproof import CrashProofStore
from .durability import atomic_write_json
from .action_receipts import NativeActionStore
from .mcp_broker import (
    PROGRESSIVE_MCP_TOOLS,
    McpOutboundBroker,
    mcp_tool_specs,
    register_with_progressive_surface as register_mcp_broker_with_progressive_surface,
)
from .neyvia_conversations import NeyviaConversationStore
from .progressive_tools import ProgressiveToolSurface, ProgressiveToolSpec, catalog_rows_without_schemas
from .ui_tools import (
    TOOL_NAMES,
    default_ui_surface,
    register_with_progressive_surface,
    ui_tool_specs,
)
from .intent_actions import IntentAction


MCP_PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "neyvia-crash-proof"
SERVER_VERSION = "0.1.0"


def _app_definitions() -> list:
    """neyvia.notes.* and neyvia.files.* rows (name without the neyvia. prefix)."""
    from .neyvia_files_tools import DEFINITIONS as FILES
    from .neyvia_notes_tools import DEFINITIONS as NOTES
    from .neyvia_devices import DEFINITIONS as DEVICES
    from .cua_native_procedures import SCHEMAS as NATIVE_APP_SCHEMAS
    return [*[("notes." + row[0], *row[1:]) for row in NOTES], *[("files." + row[0], *row[1:]) for row in FILES],
            *[("devices." + row[0], *row[1:]) for row in DEVICES],
            *[("nativeapp." + name, "Owned hidden native application: " + name,
               schema['properties'], schema['required']) for name, schema in NATIVE_APP_SCHEMAS.items()]]


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


class NeyviaMCPServer:
    """Sessionless MCP JSON-RPC host backed by the durable N-E-Y-V-I-A store."""

    def __init__(self, root: str | Path, *, include_default_mcp_demo: bool = False,
                 conversations: NeyviaConversationStore | None = None) -> None:
        self.root = Path(root).resolve()
        self.store = CrashProofStore(self.root)
        self.conversations = conversations if conversations is not None else NeyviaConversationStore(
            self.root,
            database_path=self.store.database_path,
        )
        self.ui_tools = default_ui_surface(self.root)
        from .situation_browser import SituationBrowser
        self.situations = SituationBrowser(self)
        self.mcp_broker = McpOutboundBroker(
            self.root,
            include_default_demo=include_default_mcp_demo,
        )
        self.capability_os = CapabilityService(
            self.root,
            include_default_mcp_demo=include_default_mcp_demo,
        )
        self.tools = self._tool_catalog()
        from .situation_interface import situation_tool_spec
        self.tools.append(situation_tool_spec())
        self._progressive = self._build_progressive_surface()
        known_tool_names = {str(item.get("name") or "") for item in self.tools}
        for item in self._progressive.list_tools(include_schemas=True):
            if (
                item.get("category")
                not in {"capability-os", "model-tool-intelligence", "tool-authoring", "computer-use"}
                or item["name"] in known_tool_names
            ):
                continue
            self.tools.append(
                {
                    "name": item["name"],
                    "title": item["name"],
                    "description": item.get("description") or "",
                    "inputSchema": item.get("inputSchema") or {"type": "object"},
                    "annotations": item.get("annotations") or {},
                }
            )
        self.tools.sort(key=lambda item: str(item.get("name") or ""))
        # Prefer live ProgressiveToolSurface discovery; also try NAS NativeToolRegistry if present.
        self._native_ui_registered: list[str] = []
        try:
            from .native_tools import NativeToolRegistry  # type: ignore

            from .ui_tools import register_with_native_registry

            self.native_tools = NativeToolRegistry(
                self.root,
                browser_runtime=self.ui_tools.observer.browser_runtime,
            )
            self._native_ui_registered = register_with_native_registry(
                self.native_tools,
                self.ui_tools,
            )
            from .neyvia_workspace_tools import DEFINITIONS
            from .neyvia_pdf_tools import DEFINITIONS as PDF_DEFINITIONS
            from .neyvia_onboarding import DEFINITIONS as ONBOARDING_DEFINITIONS
            known_tool_names = {item["name"] for item in self.tools}
            self.tools.extend({"name": "neyvia." + name, "description": description,
                               "inputSchema": {"type": "object", "properties": props, "required": required}}
                              for name, description, props, required in [*DEFINITIONS, *[("pdf." + name, desc, props, required) for name, desc, props, required in PDF_DEFINITIONS], *_app_definitions(), *ONBOARDING_DEFINITIONS]
                              if "neyvia." + name not in known_tool_names)
        except Exception:
            self.native_tools = None
        self.tools.sort(key=lambda item: str(item.get("name") or ""))

    @checked("mcp-compiler")
    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return self._error(request_id, -32600, "Invalid Request")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "notifications/initialized":
            return None
        try:
            if method == "initialize":
                return self._response(request_id, self._initialize(params))
            if method == "ping":
                return self._response(request_id, {})
            if method == "tools/list":
                include_schemas = bool(params.get("includeSchemas", True))
                # Progressive hot path: prefer search→describe→call. When callers
                # explicitly set includeSchemas=false, omit full input schemas.
                tools = catalog_rows_without_schemas(
                    self.tools,
                    include_schemas=include_schemas,
                )
                tools.sort(key=lambda tool: tool["name"])
                from .proofs_d_neyvia import mcp_catalog
                mcp_catalog(tools)
                return self._response(
                    request_id,
                    {
                        "tools": tools,
                        "discovery": self._progressive.discovery_contract(),
                    },
                )
            if method == "tools/call":
                return self._response(request_id, self._call_tool(params))
            if method == "tasks/get":
                return self._response(request_id, {"task": self._task(params.get("taskId"))})
            if method == "tasks/list":
                tasks = [self._task(row["taskId"]) for row in self.store.list_tasks(limit=200)]
                return self._response(request_id, {"tasks": tasks})
            if method == "tasks/cancel":
                return self._response(request_id, {"task": self._cancel_task(params.get("taskId"))})
            if method == "tasks/result":
                return self._response(request_id, self._task_result(params.get("taskId")))
            return self._error(request_id, -32601, f"Method not found: {method}")
        except (KeyError, ValueError) as exc:
            return self._error(request_id, -32602, str(exc))
        except RuntimeError as exc:
            return self._error(request_id, -32002, str(exc))
        except Exception as exc:  # protocol boundary
            return self._error(request_id, -32603, str(exc))

    def _build_progressive_surface(self) -> ProgressiveToolSurface:
        surface = ProgressiveToolSurface()
        for tool in self.tools:
            # ui.* / mcp.* tools are registered with callable handlers below; skip catalog stubs here.
            name = str(tool["name"])
            if name in TOOL_NAMES or name in PROGRESSIVE_MCP_TOOLS:
                continue
            surface.register(
                ProgressiveToolSpec(
                    name=name,
                    description=str(tool.get("description") or ""),
                    category="mcp",
                    input_schema=dict(tool.get("inputSchema") or {}),
                    annotations=dict(tool.get("annotations") or {}),
                )
            )
        register_with_progressive_surface(surface, self.ui_tools)
        register_mcp_broker_with_progressive_surface(surface, self.mcp_broker)
        register_capability_tools(surface, self.capability_os)
        return surface

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = str(params.get("protocolVersion") or MCP_PROTOCOL_VERSION)
        result = {
            "protocolVersion": requested,
            "capabilities": {
                "tools": {"listChanged": False},
                "tasks": {
                    "list": {},
                    "cancel": {},
                    "requests": {"tools": {"call": {}}},
                },
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "N-E-Y-V-I-A Crash-Proof Runtime",
                "version": SERVER_VERSION,
                "description": "Durable sparse tasks, time budgets, results, and scoped autonomy.",
            },
        }
        from .proofs_d_neyvia import mcp_initialize
        mcp_initialize(requested, result)
        return result

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        from .proofs_d_neyvia import mcp_call_pre, mcp_call_post
        mcp_call_pre(self, params)
        result = self._call_tool_action(params)
        mcp_call_post(self, params, result)
        return result

    def _call_tool_action(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        from .neyvia_workspace_tools import DEFINITIONS
        from .neyvia_pdf_tools import DEFINITIONS as PDF_DEFINITIONS
        from .neyvia_onboarding import DEFINITIONS as ONBOARDING_DEFINITIONS
        if name.startswith("neyvia.mod.") or name in {"neyvia." + row[0] for row in [*DEFINITIONS, *ONBOARDING_DEFINITIONS]} | {"neyvia.pdf." + row[0] for row in PDF_DEFINITIONS} | {"neyvia." + row[0] for row in _app_definitions()}:
            result = self.native_tools.call(name, arguments)
            return self._tool_result(result.get("result") or result, is_error=not result.get("ok"))
        definitions = {tool["name"]: tool for tool in self.tools}
        if name not in definitions:
            raise KeyError(f"Unknown tool: {name}")

        if name == "neyvia.time.now":
            from .neyvia_workspace_tools import workspace_for
            return self._tool_result(workspace_for(self.root).call("time.now", arguments))
        if name == "neyvia.tools.search":
            return self._tool_result(
                {
                    "schema": "neyvia.progressive_tools.search.v1",
                    "flow": ["search", "describe", "call"],
                    "tools": self._progressive.search(
                        str(arguments.get("query") or ""),
                        limit=int(arguments.get("limit") or 8),
                    ),
                }
            )
        if name == "neyvia.tools.describe":
            return self._tool_result(self._progressive.describe(str(arguments.get("name") or "")))
        if name in {"neyvia.workspace.browser", "neyvia.workspace.prove"}:
            if name == "neyvia.workspace.prove":
                operation = str(arguments.get("operation") or "").strip().lower()
                if operation not in {"inspect", "find", "frame", "inspect_frame", "screenshot", "annotate"}:
                    raise ValueError(
                        "neyvia.workspace.prove only supports inspect, find, "
                        "screenshot, or annotate."
                    )
            return self._tool_result(
                self._run_workspace_browser(
                    arguments if isinstance(arguments, dict) else {}
                )
            )
        if name == "neyvia.workspace.intent":
            result = self._run_browser_intent(arguments if isinstance(arguments, dict) else {})
            return self._tool_result(result, is_error=not bool(result.get("ok")))
        if name == "neyvia.situation":
            # Mutations are deliberately unavailable through the unscoped public
            # server. Its authenticated/stdio adapters must supply their grant.
            from .situation_interface import situation_arguments
            result = self.situations.call(arguments["verb"],arguments["workId"],situation_arguments(arguments),may_change=False)
            return self.situations.tool_result(result)
        if (
            name.startswith("capability.")
            or name.startswith("artifact.")
            or name.startswith("model.tools.")
            or name.startswith("tool.author.")
            or name.startswith("computer_use.")
        ):
            result = self._progressive.call(
                name,
                arguments if isinstance(arguments, dict) else {},
            )
            status = str(result.get("status") or "") if isinstance(result, dict) else ""
            return self._tool_result(
                result,
                is_error=status
                in {
                    "approval_required",
                    "permission_denied",
                    "adapter_required",
                    "failed",
                },
            )
        if name in TOOL_NAMES:
            result = self.ui_tools.call(name, arguments if isinstance(arguments, dict) else {})
            return self._tool_result(result, is_error=not bool(result.get("ok", True)))
        if name in PROGRESSIVE_MCP_TOOLS:
            result = self._progressive.call(name, arguments if isinstance(arguments, dict) else {})
            if name == "mcp.call" and isinstance(result, dict):
                is_error = not bool(result.get("ok", False)) or str(result.get("status") or "") in {
                    "approval_required",
                    "auth_required",
                    "failed",
                }
                return self._tool_result(result, is_error=is_error)
            return self._tool_result(result)
        if name == "neyvia.time.budget":
            from .native_tools import NativeToolRegistry
            receipt = NativeToolRegistry(self.root).call(name, arguments)
            return self._tool_result(receipt.get("result") or receipt, is_error=not receipt["ok"])
        if name == "neyvia.task.status":
            task = self.store.get_task(str(arguments.get("taskId") or ""))
            return self._tool_result(task)
        if name == "neyvia.result.summary":
            summary = self.store.summarize_result_set(
                str(arguments.get("resultSetId") or ""),
                sample_limit=int(arguments.get("sampleLimit", 5)),
            )
            return self._tool_result(summary)
        if name == "neyvia.autonomy.check":
            result = self.store.autonomy_allows(
                str(arguments.get("leaseId") or ""),
                action=str(arguments.get("action") or ""),
                context=dict(arguments.get("context") or {}),
            )
            return self._tool_result(result, is_error=not result["allowed"])
        if name == "neyvia.autonomy.grant":
            policy = {
                "allowedActions": list(arguments.get("allowedActions") or []),
                "allowedRoots": list(arguments.get("allowedRoots") or []),
                "allowedDomains": list(arguments.get("allowedDomains") or []),
                "destructiveAllowed": bool(arguments.get("destructiveAllowed", False)),
                "publicCommunicationAllowed": bool(arguments.get("publicCommunicationAllowed", False)),
                "maxSpend": max(0, float(arguments.get("maxSpend", 0) or 0)),
            }
            if not policy["allowedActions"]:
                raise ValueError("allowedActions must contain at least one bounded action or '*'")
            lease = self.store.create_autonomy_lease(
                mission_id=str(arguments.get("missionId") or "").strip(),
                session_id=str(arguments.get("sessionId") or "").strip(),
                parent_lease_id=str(arguments.get("parentLeaseId") or "").strip() or None,
                duration_seconds=min(max(1, int(arguments.get("durationSeconds", 3600))), 86400),
                policy=policy,
            )
            return self._tool_result(lease)
        if name == "neyvia.autonomy.revoke":
            return self._tool_result(
                self.store.revoke_autonomy_lease(str(arguments.get("leaseId") or ""))
            )
        if name == "neyvia.conversation.search":
            return self._tool_result(
                self.conversations.search(
                    str(arguments.get("query") or ""),
                    workspace_id=str(arguments.get("workspaceId") or "").strip() or None,
                    kind=str(arguments.get("kind") or "").strip() or None,
                    limit=int(arguments.get("limit") or 30),
                )
            )
        if name == "neyvia.conversation.list":
            return self._tool_result(
                {
                    "schema": "neyvia.conversation-list.v1",
                    "conversations": self.conversations.list_conversations(
                        workspace_id=str(arguments.get("workspaceId") or "").strip() or None,
                        kind=str(arguments.get("kind") or "").strip() or None,
                        limit=int(arguments.get("limit") or 80),
                    ),
                }
            )
        if name == "neyvia.question.branch":
            return self._tool_result(
                self.conversations.create_question_branch(
                    str(arguments.get("parentConversationId") or ""),
                    question=str(arguments.get("question") or ""),
                    title_mode=str(arguments.get("titleMode") or "automatic"),
                )
            )
        if name == "neyvia.question.action.check":
            result = self.conversations.action_allowed(
                str(arguments.get("conversationId") or ""),
                str(arguments.get("action") or ""),
            )
            return self._tool_result(result, is_error=not result["allowed"])
        if name == "neyvia.context.retrieve":
            return self._tool_result(
                self.conversations.retrieve_context(
                    str(arguments.get("query") or ""),
                    workspace_id=str(arguments.get("workspaceId") or "").strip() or None,
                    exclude_conversation_id=str(arguments.get("excludeConversationId") or "").strip() or None,
                    limit=int(arguments.get("limit") or 8),
                )
            )
        if name == "neyvia.orchestration.plan":
            typed_plan = arguments.get("typedPlan") or arguments.get("leadPlan") or arguments.get("plan")
            if typed_plan is not None:
                return self._tool_result(
                    self.conversations.create_dynamic_child_plan(
                        str(arguments.get("conversationId") or ""),
                        plan=dict(typed_plan),
                        run_id=str(arguments.get("runId") or "").strip(),
                        approval_receipt=dict(arguments.get("approvalReceipt") or {}),
                        approved_plan_hash=str(arguments.get("approvedPlanHash") or "").strip() or None,
                        parent_task_id=str(arguments.get("parentTaskId") or "").strip() or None,
                        approved=arguments.get("approved") if "approved" in arguments else None,
                    )
                )
            preset = str(arguments.get("preset") or "").strip().lower()
            if preset == "lead-workers":
                return self._tool_result(
                    self.conversations.create_lead_workers_plan(
                        str(arguments.get("conversationId") or ""),
                        objective=str(arguments.get("objective") or "Complete the bounded orchestration objective."),
                        worker_count=int(arguments.get("workerCount") or 2),
                        sequential_integration=bool(arguments.get("sequentialIntegration")),
                    )
                )
            return self._tool_result(
                self.conversations.create_concurrency_plan(
                    str(arguments.get("conversationId") or ""),
                    tasks=list(arguments.get("tasks") or []),
                    max_parallel=int(arguments.get("maxParallel") or 4),
                )
            )
        if name == "neyvia.orchestration.graph":
            return self._tool_result(
                self.conversations.agent_graph(str(arguments.get("conversationId") or ""))
            )

        if definitions[name].get("execution", {}).get("taskSupport") == "required" and not params.get("task"):
            raise RuntimeError(f"{name} requires task-augmented execution")
        task = self._submit_extension_task(name, arguments)
        return {
            "task": self._task(task["taskId"]),
            "_meta": {
                "io.modelcontextprotocol/model-immediate-response": (
                    f"N-E-Y-V-I-A accepted durable task {task['taskId']}. "
                    "Continue other work; inspect it only at a milestone or terminal state."
                )
            },
        }

    def _approved_browser_url(self, value: str) -> str:
        from .local_browser_authority import approved_browser_url
        return approved_browser_url(self.root, value, legacy_ports={4173,47880,47908}, app_factory=True)

    def _sanitize_browser_value(self, value: Any, *, key: str = "") -> Any:
        """Persist only receipt-safe metadata; never raw tool bodies or inputs."""
        if key.lower() in {"value", "fill", "text", "body", "html", "content", "error", "message", "detail"}:
            return "[redacted]"
        if isinstance(value, dict):
            safe: dict[str, Any] = {}
            for name, item in value.items():
                lname = str(name).lower()
                if lname in {"value", "fill", "text", "body", "html", "content", "error", "message", "detail", "arguments", "result"}:
                    continue
                if lname in {"url", "finalurl", "pageurl", "origin"}:
                    safe[name] = self._approved_browser_url(str(item))
                elif lname in {"hash", "sha256", "semantichash", "revision", "status", "ok", "actionid", "duplicatesuppressed"}:
                    safe[name] = self._sanitize_browser_value(item, key=lname)
            return safe
        if isinstance(value, list):
            return [self._sanitize_browser_value(item) for item in value[:50]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value if key.lower() not in {"value", "fill", "text"} else "[redacted]"
        return str(value)[:120]

    def _validate_browser_origins(self, value: Any) -> None:
        if isinstance(value, dict):
            for name, item in value.items():
                if str(name).lower() in {"url", "finalurl", "pageurl", "origin"} and item:
                    self._approved_browser_url(str(item))
                self._validate_browser_origins(item)
        elif isinstance(value, list):
            for item in value[:50]:
                self._validate_browser_origins(item)

    def _run_workspace_browser(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "").strip().lower()
        mutations = {"click", "fill", "press", "select", "toggle", "upload", "reload"}
        if operation in mutations:
            action_id = str(payload.get("actionId") or "").strip()
            if not action_id:
                raise ValueError("Authorized browser mutations require a stable actionId.")
            scope = str(payload.get("missionId") or payload.get("conversationId") or "").strip()
            if not scope:
                raise ValueError("Authorized browser mutations require a durable missionId or conversationId scope.")
            self._preflight_browser_mutation(payload)
            store = NativeActionStore(self.root, f"workspace.browser:{scope}")
            binding = dict(payload)
            # Values participate in conflict detection but are never persisted by receipts.
            binding["arguments"] = dict(binding.get("arguments") or {})
            binding["arguments"]["valueFingerprint"] = hashlib.sha256(str(binding["arguments"].get("value", "")).encode()).hexdigest()
            def observed_mutation() -> dict[str, Any]:
                result = self._run_workspace_browser_once(payload)
                page = getattr(getattr(self, "ui_tools", None), "attached_page", None)
                self._approved_browser_url(str(getattr(page, "url", "") or ""))
                self._validate_browser_origins(result)
                return self._sanitize_browser_value(result)
            return store.execute(
                action_id,
                "workspace.browser",
                binding,
                observed_mutation,
            )
        return self._run_workspace_browser_once(payload)

    def _run_browser_intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
        if not intent:
            return {"ok": False, "status": "invalid_intent"}
        if str(intent.get("action") or "click") not in {"click", "toggle"}:
            return {"ok": False, "status": "unsupported_intent_action"}
        action_id = str(payload.get("actionId") or "").strip()
        if not action_id:
            return {"ok": False, "status": "action_id_required"}
        def observe():
            self._preflight_browser_mutation(payload)
            # Refresh the attached document without navigating/reloading it.
            self.ui_tools.observe_page(self.ui_tools.attached_page)
            stamp = datetime.now(timezone.utc).isoformat()
            return [{"id": node.id, "semanticTarget": node.name, "name": node.name,
                     "role": node.role, "states": list(node.states), "value": node.value,
                     "checked": "checked" in node.states, "disabled": "disabled" in node.states,
                     "observedAt": stamp}
                    for node in self.ui_tools.graph.snapshot_nodes().values()]
        def gateway(request):
            return self._run_workspace_browser({"operation": str(request.get("action") or "click"), "arguments": {"id": request.get("targetId")}, "actionId": payload.get("actionId"), "missionId": payload.get("missionId"), "conversationId": payload.get("conversationId"), "url": payload.get("url")})
        from .verified_operations import VerifiedOperationStore
        scope = str(payload.get("conversationId") or payload.get("missionId") or "browser-intents")
        return IntentAction(observe=observe, gateway=gateway,
                            verified_store=VerifiedOperationStore(self.root, scope)).execute(
                                intent, operation_id=action_id, authority=payload.get("authority"))

    def _preflight_browser_mutation(self, payload: dict[str, Any]) -> None:
        """Prove the attached page is allowed before any mutating handler runs."""
        page = getattr(getattr(self, "ui_tools", None), "attached_page", None)
        actual = str(getattr(page, "url", "") or "").strip()
        if not actual:
            raise ValueError("Browser mutation requires trustworthy attached-page origin evidence.")
        self._approved_browser_url(actual)
        requested = str(payload.get("url") or "").strip()
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        nested = str(arguments.get("url") or "").strip()
        if requested:
            self._approved_browser_url(requested)
        if nested:
            self._approved_browser_url(nested)
        if requested and nested and requested != nested:
            raise ValueError("Browser mutation has contradictory URL targets.")
        target = requested or nested
        if target and target != actual:
            raise ValueError("Browser mutation target must match the currently attached approved page.")

    def _run_workspace_browser_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        observed_start = time.monotonic()
        operation = str(payload.get("operation") or "").strip().lower()
        allowed = {
            "inspect",
            "frame",
            "inspect_frame",
            "find",
            "click",
            "fill",
            "press",
            "select",
            "toggle",
            "upload",
            "screenshot",
            "annotate",
            "reload",
        }
        if operation not in allowed:
            raise ValueError(f"Unsupported Browser/Preview operation: {operation}")
        if operation in {"click", "fill", "press", "select", "toggle", "upload", "reload"}:
            self._preflight_browser_mutation(payload)
        url = str(payload.get("url") or "").strip()
        arguments = (
            dict(payload.get("arguments"))
            if isinstance(payload.get("arguments"), dict)
            else {}
        )
        if url:
            if arguments.get("url") and str(arguments["url"]).strip() != url:
                raise ValueError("Browser arguments contradict the requested target URL")
            arguments.setdefault("url", url)
        if url:
            self._approved_browser_url(url)
        if operation not in {"screenshot", "annotate"}:
            page = self.ui_tools.attached_page
            if url and (page is None or (callable(getattr(page,"is_closed",None)) and page.is_closed())):
                page = self.ui_tools.observer.browser_runtime.persistent_page(
                    width=int(arguments.get("width") or payload.get("viewportWidth") or 1440),
                    height=int(arguments.get("height") or payload.get("viewportHeight") or 1000),
                )
            if page is not None:
                from .local_browser_authority import guard_browser_page
                origin = url or str(getattr(page, "url", "") or "")
                self._approved_browser_url(origin)
                guard_browser_page(self.root,page,origin,legacy_ports={4173,47880,47908},app_factory=True)
                self.ui_tools.attached_page = page
        if operation == "screenshot" and url:
            parsed_url = urllib.parse.urlparse(url)
            if (
                parsed_url.hostname in {"127.0.0.1", "localhost"}
                and (parsed_url.path == "/control" or parsed_url.path.startswith("/control/"))
            ):
                arguments.setdefault("waitFor", ".fluxos-shell")
                arguments.setdefault("delayMs", 750)

        tool_name = ""
        if operation in {"screenshot", "annotate"}:
            if self.native_tools is None:
                raise RuntimeError("Native Preview tools are unavailable.")
            tool_name = f"preview.{operation}"
            if operation == "screenshot":
                from .local_browser_authority import capture_authority
                with capture_authority(self.root,url,legacy_ports={4173,47880,47908},app_factory=True):
                    result = self.native_tools.call(tool_name, arguments)
            else:
                result = self.native_tools.call(tool_name, arguments)
        else:
            result: dict[str, Any] = {}
            if operation == "reload":
                self._preflight_browser_mutation(payload)
                page = self.ui_tools.attached_page
                if page is None:
                    raise RuntimeError("Browser reload requires an attached persistent page; inspect first.")
                page.reload(wait_until="domcontentloaded", timeout=30000)
                self.ui_tools.observer.observe_playwright_page(page)
                self.ui_tools.last_observe_url = str(page.url or self.ui_tools.last_observe_url)
                result = {"ok": True, "status": "reloaded", "url": self.ui_tools.last_observe_url,
                          "revision": self.ui_tools.graph.revision, "semanticHash": self.ui_tools.graph.semantic_hash}
            if operation in {"frame", "inspect_frame"} and url and self.ui_tools.last_observe_url != url:
                raise ValueError("Perception frame belongs to another page; inspect the requested page first")
            if url and operation not in {"inspect", "frame", "inspect_frame"} and self.ui_tools.last_observe_url != url:
                observed = self.ui_tools.call(
                    "ui.observe",
                    {
                        "url": url,
                        "width": int(payload.get("viewportWidth") or 1440),
                        "height": int(payload.get("viewportHeight") or 1000),
                    },
                )
                if not bool(observed.get("ok", True)):
                    result = observed
                if operation in {"click", "fill", "press", "select", "toggle", "upload"}:
                    self._approved_browser_url(str(getattr(self.ui_tools.attached_page, "url", "") or ""))
            if not result:
                if operation == "inspect":
                    tool_name = "ui.observe"
                    result = self.ui_tools.call(tool_name, arguments)
                elif operation in {"frame", "inspect_frame"}:
                    tool_name = "ui." + operation
                    result = self.ui_tools.call(tool_name, arguments)
                elif operation == "find":
                    tool_name = "ui.find"
                    result = self.ui_tools.call(tool_name, arguments)
                elif operation == "upload":
                    self._preflight_browser_mutation(payload)
                    tool_name = "ui.upload"
                    result = self.ui_tools.call(tool_name, arguments)
                else:
                    self._preflight_browser_mutation(payload)
                    tool_name = "ui.do"
                    result = self.ui_tools.call(
                        tool_name,
                        {**arguments, "action": operation},
                    )

        current_url = str(getattr(self.ui_tools.attached_page, "url", "") or self.ui_tools.last_observe_url or url)
        if not current_url:
            raise ValueError("Browser interaction requires trustworthy current-origin evidence.")
        self._approved_browser_url(current_url)
        self._validate_browser_origins(result)
        ok = bool(result.get("ok", True))
        if str(result.get("status") or "") in {
            "failed",
            "approval_required",
            "auth_required",
        }:
            ok = False
        checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        receipt_id = f"workspace_proof_{uuid.uuid4().hex}"
        conversation_id = str(
            payload.get("conversationId") or payload.get("conversation_id") or ""
        ).strip()
        mission_id = str(
            payload.get("missionId")
            or payload.get("mission_id")
            or conversation_id
            or "unbound"
        ).strip()
        safe_mission_id = "".join(
            character
            for character in mission_id
            if character.isalnum() or character in "._-"
        )[:128] or "unbound"
        receipt_dir = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / safe_mission_id
            / "workspace_proof"
        )
        receipt_path = receipt_dir / f"{receipt_id}.json"
        native_result = (
            result.get("result") if isinstance(result.get("result"), dict) else {}
        )
        artifacts = []
        safe_result = self._sanitize_browser_value(result)
        result_hash = hashlib.sha256(
            json.dumps(
                safe_result,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        receipt = {
            "schema": "neyvia.workspace-proof-receipt.v1",
            "receiptId": receipt_id,
            "checkedAt": checked_at,
            "status": "completed" if ok else "failed",
            "workspace": str(payload.get("workspaceKind") or "browser"),
            "operation": operation,
            "tool": tool_name,
            "target": {
                "url": self._approved_browser_url(url) if url else current_url,
            },
            "missionId": str(payload.get("missionId") or ""),
            "conversationId": conversation_id,
            "resultHash": result_hash,
            "artifacts": artifacts,
            "result": safe_result,
        }
        atomic_write_json(receipt_path, receipt)
        from .experience_learning import ExperienceStore
        experience = ExperienceStore(self.root, conversation_id or mission_id)
        experience.trace(trace_id=receipt_id,event_kind="state" if ok else "error",
            payload={"operation":operation,"status":receipt["status"],"resultHash":result_hash,
                     "receiptPath":str(receipt_path),"durationMs":round((time.monotonic()-observed_start)*1000)},
            references=[receipt_id],provenance={"source":"browser_operation_gateway","observedAt":checked_at})
        compact_receipt = {
            "schema": receipt["schema"],
            "receiptId": receipt_id,
            "status": receipt["status"],
            "workspace": receipt["workspace"],
            "operation": operation,
            "tool": tool_name,
            "receiptPath": str(receipt_path),
            "resultHash": result_hash,
            "artifacts": artifacts,
        }
        attachment: dict[str, Any] = {
            "status": "unbound",
            "conversationId": conversation_id,
        }
        if conversation_id:
            try:
                turn = self.conversations.append_turn(
                    conversation_id,
                    role="assistant",
                    content=(
                        f"{receipt['workspace'].title()} proof: {operation} "
                        f"{'completed' if ok else 'failed'}."
                    ),
                    detail=url,
                    source="workspace-proof",
                    turn_kind="proof",
                    metadata={"turnReceipt": compact_receipt},
                    meaningful=False,
                    turn_id=f"turn_{receipt_id}",
                    idempotent=True,
                    now=checked_at,
                )
                attachment = {
                    "status": "attached",
                    "conversationId": conversation_id,
                    "turnId": str(turn.get("turnId") or ""),
                    "storage": "sqlite",
                }
            except KeyError:
                attachment["status"] = "conversation_not_found"
        return {
            "schema": "neyvia.workspace-operation-result.v1",
            "ok": ok,
            "status": receipt["status"],
            "operation": operation,
            "tool": tool_name,
            "receipt": compact_receipt,
            "attachment": attachment,
            "resultSummary": str(
                safe_result.get("summary")
                or safe_result.get("status")
                or ""
            )[:1200],
        }

    def _submit_extension_task(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mission_id = str(arguments.get("missionId") or "").strip()
        idempotency_key = str(arguments.get("idempotencyKey") or "").strip()
        if not mission_id or not idempotency_key:
            raise ValueError("missionId and idempotencyKey are required")
        kinds = {
            "neyvia.research.start": "extension.research",
            "neyvia.browser.start": "extension.browser",
            "neyvia.computer.start": "extension.computer-use",
            "neyvia.training.batch.start": "extension.model-training-batch",
        }
        payload = dict(arguments)
        task = self.store.submit_task(
            mission_id=mission_id,
            kind=kinds[name],
            idempotency_key=idempotency_key,
            payload=payload,
            deadline_at=arguments.get("deadlineAt"),
            permission_lease_id=arguments.get("autonomyLeaseId"),
        )
        if name == "neyvia.training.batch.start" and not task["deduplicated"]:
            model_count = max(1, min(int(arguments.get("modelCount", 1)), 128))
            for index in range(model_count):
                self.store.submit_task(
                    mission_id=mission_id,
                    kind="model.train",
                    idempotency_key=f"{idempotency_key}:model:{index:03d}",
                    parent_task_id=task["taskId"],
                    payload={
                        "batchTaskId": task["taskId"],
                        "modelIndex": index,
                        "training": arguments.get("training") or {},
                        "wakePolicy": "terminal_or_input_only",
                    },
                    deadline_at=arguments.get("deadlineAt"),
                    permission_lease_id=arguments.get("autonomyLeaseId"),
                )
        return task

    def _cancel_task(self, task_id: Any) -> dict[str, Any]:
        task = self.store.get_task(str(task_id or ""))
        if task["status"] not in {"completed", "failed", "cancelled"}:
            task = self.store.transition_task(task["taskId"], "cancelled")
        return self._task(task["taskId"])

    def _task_result(self, task_id: Any) -> dict[str, Any]:
        task = self.store.get_task(str(task_id or ""))
        if task["status"] not in {"completed", "failed", "cancelled", "input_required"}:
            raise RuntimeError("task result is not available yet")
        payload = task["result"] if task["status"] == "completed" else task["error"] or task["checkpoint"] or task
        result = {
            **self._tool_result(payload, is_error=task["status"] in {"failed", "cancelled"}),
            "_meta": {"io.modelcontextprotocol/related-task": {"taskId": task["taskId"]}},
        }
        from .proofs_d_neyvia import mcp_task_result
        mcp_task_result(task, result)
        return result

    def _task(self, task_id: Any) -> dict[str, Any]:
        task = self.store.get_task(str(task_id or ""))
        status = {
            "queued": "working",
            "waiting": "working",
            "working": "working",
            "input_required": "input_required",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }[task["status"]]
        return {
            "taskId": task["taskId"],
            "status": status,
            "statusMessage": self._status_message(task),
            "createdAt": task["createdAt"],
            "lastUpdatedAt": task["updatedAt"],
            "pollInterval": 5000,
        }

    @staticmethod
    def _status_message(task: dict[str, Any]) -> str:
        if task["status"] == "queued":
            return "Persisted and waiting for an eligible background worker."
        if task["status"] == "waiting":
            return "Background work is waiting for its deterministic wake time."
        if task["status"] == "input_required":
            return "N-E-Y-V-I-A needs user input before continuing."
        return f"Task is {task['status'].replace('_', ' ')}."

    @staticmethod
    def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
        structured = payload if isinstance(payload, dict) else {"value": payload}
        return {
            "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "structuredContent": structured,
            "isError": is_error,
        }

    @staticmethod
    def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _tool_catalog() -> list[dict[str, Any]]:
        mission_task_properties = {
            "missionId": {"type": "string", "minLength": 1},
            "idempotencyKey": {"type": "string", "minLength": 1},
            "deadlineAt": {"type": "string", "format": "date-time"},
            "autonomyLeaseId": {"type": "string"},
        }
        task_tools = [
            (
                "neyvia.research.start",
                "Start Resumable Research",
                "Persist a research request and return immediately with a durable task handle.",
                {**mission_task_properties, "query": {"type": "string", "minLength": 1}},
                ["missionId", "idempotencyKey", "query"],
            ),
            (
                "neyvia.browser.start",
                "Start Resumable Browser Work",
                "Persist a browser objective with checkpoint and recovery semantics.",
                {**mission_task_properties, "objective": {"type": "string"}, "startUrl": {"type": "string"}},
                ["missionId", "idempotencyKey", "objective"],
            ),
            (
                "neyvia.computer.start",
                "Start Resumable Computer Use",
                "Persist a bounded desktop objective that background workers can checkpoint and resume.",
                {**mission_task_properties, "objective": {"type": "string"}, "application": {"type": "string"}},
                ["missionId", "idempotencyKey", "objective"],
            ),
            (
                "neyvia.training.batch.start",
                "Start Sparse Model Training Batch",
                "Persist one to 128 model-training jobs without holding a model turn while they run.",
                {
                    **mission_task_properties,
                    "modelCount": {"type": "integer", "minimum": 1, "maximum": 128},
                    "training": {"type": "object"},
                },
                ["missionId", "idempotencyKey", "modelCount"],
            ),
        ]
        catalog = [
            {
                "name": name,
                "title": title,
                "description": description,
                "inputSchema": _object_schema(properties, required),
                "execution": {"taskSupport": "required"},
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
            }
            for name, title, description, properties, required in task_tools
        ]
        catalog.extend(
            [
                {
                    "name": "neyvia.time.now",
                    "title": "Current Time",
                    "description": "Return a precise UTC timestamp without using a model turn to infer time.",
                    "inputSchema": _object_schema({}),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.tools.search",
                    "title": "Search Tools (Progressive)",
                    "description": "Search callable tools without dumping full schemas. Prefer search → describe → call.",
                    "inputSchema": _object_schema(
                        {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        }
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.tools.describe",
                    "title": "Describe Tool (Progressive)",
                    "description": "Return one tool schema after search. Do not list all schemas by default.",
                    "inputSchema": _object_schema(
                        {"name": {"type": "string", "minLength": 1}},
                        ["name"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.workspace.prove",
                    "title": "Inspect Browser or Capture Proof",
                    "description": (
                        "Inspect, find, screenshot, or annotate through "
                        "N-E-Y-V-I-A's model-usable Browser/Preview runtime. "
                        "The operation is observational; it writes a durable "
                        "receipt and can attach it to the active conversation."
                    ),
                    "inputSchema": _object_schema(
                        {
                            "operation": {
                                "type": "string",
                                "enum": [
                                    "inspect",
                                    "frame",
                                    "inspect_frame",
                                    "find",
                                    "screenshot",
                                    "annotate",
                                ],
                            },
                            "url": {"type": "string"},
                            "arguments": {"type": "object"},
                            "conversationId": {"type": "string"},
                            "missionId": {"type": "string"},
                            "actionId": {"type": "string", "maxLength": 160},
                            "workspaceKind": {
                                "type": "string",
                                "enum": ["browser", "preview"],
                            },
                            "viewportWidth": {
                                "type": "integer",
                                "minimum": 320,
                                "maximum": 4096,
                            },
                            "viewportHeight": {
                                "type": "integer",
                                "minimum": 320,
                                "maximum": 4096,
                            },
                        },
                        ["operation"],
                    ),
                    "annotations": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": False,
                    },
                },
                {
                    "name": "neyvia.workspace.browser",
                    "title": "Operate Browser or Preview",
                    "description": (
                        "Inspect, find, click, fill, upload, or capture a screenshot "
                        "through N-E-Y-V-I-A's model-usable Browser/Preview runtime. "
                        "Every call writes a durable receipt and can attach it to "
                        "the active conversation."
                    ),
                    "inputSchema": _object_schema(
                        {
                            "operation": {
                                "type": "string",
                                "enum": [
                                    "inspect",
                                    "find",
                                    "click",
                                    "fill",
                                    "press",
                                    "select",
                                    "toggle",
                                    "upload",
                                    "screenshot",
                                    "annotate",
                                    "reload",
                                ],
                            },
                            "url": {"type": "string"},
                            "arguments": {"type": "object"},
                            "conversationId": {"type": "string"},
                            "missionId": {"type": "string"},
                            "workspaceKind": {
                                "type": "string",
                                "enum": ["browser", "preview"],
                            },
                            "viewportWidth": {
                                "type": "integer",
                                "minimum": 320,
                                "maximum": 4096,
                            },
                            "viewportHeight": {
                                "type": "integer",
                                "minimum": 320,
                                "maximum": 4096,
                            },
                        },
                        ["operation"],
                    ),
                    "annotations": {
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": False,
                    },
                },
                {
                    "name": "neyvia.workspace.intent",
                    "title": "Browser intent action",
                    "description": "Resolve one fresh semantic browser target, perform its bounded action, and verify the postcondition.",
                    "inputSchema": _object_schema({"intent": {"type": "object"}, "authority": {"type": "object"}, "actionId": {"type": "string"}, "missionId": {"type": "string"}, "url": {"type": "string"}}, ["intent", "authority"]),
                },
                {
                    "name": "neyvia.time.budget",
                    "title": "Deadline Budget",
                    "description": "Decide deterministically whether optional work fits before a deadline and verification reserve.",
                    "inputSchema": _object_schema(
                        {
                            "deadlineAt": {"type": "string", "format": "date-time"},
                            "estimatedNextSeconds": {"type": "number", "minimum": 0},
                            "verificationReserveSeconds": {"type": "number", "minimum": 0},
                            "optional": {"type": "boolean"},
                        }
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.task.status",
                    "title": "Durable Task Status",
                    "description": "Read a persisted task status and checkpoint.",
                    "inputSchema": _object_schema({"taskId": {"type": "string"}}, ["taskId"]),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.result.summary",
                    "title": "Result Set Summary",
                    "description": "Return a compact deduplicated summary instead of injecting every intermediate result.",
                    "inputSchema": _object_schema(
                        {"resultSetId": {"type": "string"}, "sampleLimit": {"type": "integer", "minimum": 0, "maximum": 20}},
                        ["resultSetId"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.autonomy.grant",
                    "title": "Grant Scoped Autonomy",
                    "description": "Create an expiring mission or session permission lease so repeated in-scope approvals are unnecessary.",
                    "inputSchema": _object_schema(
                        {
                            "missionId": {"type": "string", "minLength": 1},
                            "sessionId": {"type": "string"},
                            "parentLeaseId": {"type": "string"},
                            "durationSeconds": {"type": "integer", "minimum": 1, "maximum": 86400},
                            "allowedActions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            "allowedRoots": {"type": "array", "items": {"type": "string"}},
                            "allowedDomains": {"type": "array", "items": {"type": "string"}},
                            "destructiveAllowed": {"type": "boolean"},
                            "publicCommunicationAllowed": {"type": "boolean"},
                            "maxSpend": {"type": "number", "minimum": 0},
                        },
                        ["missionId", "durationSeconds", "allowedActions"],
                    ),
                    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
                },
                {
                    "name": "neyvia.autonomy.check",
                    "title": "Autonomy Lease Check",
                    "description": "Check an action against a scoped, expiring permission lease and return a concrete reason.",
                    "inputSchema": _object_schema(
                        {
                            "leaseId": {"type": "string"},
                            "action": {"type": "string"},
                            "context": {"type": "object"},
                        },
                        ["leaseId", "action"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.autonomy.revoke",
                    "title": "Revoke Scoped Autonomy",
                    "description": "Immediately revoke a permission lease and all child use that depends on it.",
                    "inputSchema": _object_schema({"leaseId": {"type": "string"}}, ["leaseId"]),
                    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
                },
                {
                    "name": "neyvia.conversation.list",
                    "title": "List Unified Conversations",
                    "description": "List Chat and Orchestration conversations together in meaningful-activity recency order.",
                    "inputSchema": _object_schema(
                        {
                            "workspaceId": {"type": "string"},
                            "kind": {"type": "string", "enum": ["chat", "orchestration"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                        }
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.conversation.search",
                    "title": "Search Conversation Fabric",
                    "description": "Search titles, dialogue, context atoms, artifacts, and orchestration evidence with provenance.",
                    "inputSchema": _object_schema(
                        {
                            "query": {"type": "string", "minLength": 1},
                            "workspaceId": {"type": "string"},
                            "kind": {"type": "string", "enum": ["chat", "orchestration"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        },
                        ["query"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.question.branch",
                    "title": "Create Read-Only Question Branch",
                    "description": "Create a durable Ask branch that inherits parent context but cannot mutate files, systems, or external services.",
                    "inputSchema": _object_schema(
                        {
                            "parentConversationId": {"type": "string", "minLength": 1},
                            "question": {"type": "string", "minLength": 1},
                            "titleMode": {"type": "string", "enum": ["off", "suggest", "automatic"]},
                        },
                        ["parentConversationId", "question"],
                    ),
                    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
                },
                {
                    "name": "neyvia.question.action.check",
                    "title": "Check Question Branch Action",
                    "description": "Enforce the host-level read-only policy for an Ask branch before a tool can run.",
                    "inputSchema": _object_schema(
                        {"conversationId": {"type": "string"}, "action": {"type": "string"}},
                        ["conversationId", "action"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.context.retrieve",
                    "title": "Retrieve Cited Context",
                    "description": "Return a bounded, expiring Context Atlas packet from authorized prior conversations.",
                    "inputSchema": _object_schema(
                        {
                            "query": {"type": "string", "minLength": 1},
                            "workspaceId": {"type": "string"},
                            "excludeConversationId": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        },
                        ["query"],
                    ),
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "neyvia.orchestration.plan",
                    "title": "Build Dependency-Aware Constellation",
                    "description": "Create a bounded parallel execution graph that preserves dependencies and separates overlapping write scopes.",
                    "inputSchema": _object_schema(
                        {
                            "conversationId": {"type": "string", "minLength": 1},
                            "tasks": {"type": "array", "minItems": 1, "items": {"type": "object"}},
                            "maxParallel": {"type": "integer", "minimum": 1, "maximum": 16},
                            "preset": {"type": "string", "enum": ["lead-workers"]},
                            "objective": {"type": "string"},
                            "workerCount": {"type": "integer", "minimum": 2, "maximum": 4},
                            "sequentialIntegration": {"type": "boolean"},
                            "typedPlan": {"type": "object"},
                            "leadPlan": {"type": "object"},
                            "plan": {"type": "object"},
                            "approvedPlanHash": {"type": "string", "minLength": 64, "maxLength": 64},
                            "runId": {"type": "string", "minLength": 1},
                            "approvalReceipt": {"type": "object"},
                            "approved": {"type": "boolean"},
                            "parentTaskId": {"type": "string"},
                        },
                        ["conversationId"],
                    ),
                    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
                },
                {
                    "name": "neyvia.orchestration.graph",
                    "title": "Read Constellation Graph",
                    "description": "Read agent nodes, lifecycle stages, dependencies, and the latest synthesis result.",
                    "inputSchema": _object_schema({"conversationId": {"type": "string"}}, ["conversationId"]),
                    "annotations": {"readOnlyHint": True},
                },
            ]
        )
        for spec in ui_tool_specs():
            catalog.append(
                {
                    "name": str(spec["name"]),
                    "title": str(spec["name"]),
                    "description": str(spec["description"]),
                    "inputSchema": dict(spec.get("input_schema") or {}),
                    "annotations": {
                        "readOnlyHint": str(spec.get("mutability_class") or "read") == "read",
                        "compactOnly": True,
                        "treeOmitted": True,
                    },
                }
            )
        for spec in mcp_tool_specs():
            catalog.append(
                {
                    "name": str(spec["name"]),
                    "title": str(spec["name"]),
                    "description": str(spec["description"]),
                    "inputSchema": dict(spec.get("input_schema") or {}),
                    "annotations": {
                        "readOnlyHint": str(spec.get("mutability_class") or "read") == "read",
                        "brokered": True,
                        "schemasDeferred": True,
                    },
                }
            )
        return sorted(catalog, key=lambda tool: tool["name"])
