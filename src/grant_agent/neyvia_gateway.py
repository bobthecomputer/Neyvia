"""Compact native gateway shared by agent and CL transports."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def canonical_hash(value):
    from .capability_contracts import canonical_hash as implementation
    return implementation(value)


def safe_tool_display(value):
    from .chat_stream import safe_tool_display as implementation
    return implementation(value)


class _LazyUiBrowserRuntime:
    """Resolve the shared UI browser only when a browser action uses it."""

    def __init__(self, root: Path):
        self.root = root

    def __getattr__(self, name):
        from .ui_tools import default_ui_surface
        return getattr(default_ui_surface(self.root).observer.browser_runtime, name)


class NeyviaToolGateway:
    """Compact bridge over native and verified managed tool surfaces."""

    def __init__(self, root: Path, *, allow_mutations: bool = False, action_scope: str = "", action_root: Path | None = None,
                 allowed_mutation_tools: set[str] | None = None, permission_mode: str = "",
                 managed_capabilities: bool = True) -> None:
        from .native_tools import NativeToolRegistry

        self.root = root.resolve()
        self.native = NativeToolRegistry(
            self.root,
            browser_runtime=_LazyUiBrowserRuntime(self.root),
        )
        self._capabilities_loaded = not managed_capabilities
        self._capabilities = None
        self.allow_mutations = allow_mutations
        self.permission_mode = (permission_mode if allow_mutations else "read-only") or (
            "full-access" if allow_mutations and allowed_mutation_tools and "terminal.exec" in allowed_mutation_tools
            else "workspace" if allow_mutations else "read-only"
        )
        self.work_scope = action_scope
        self.work_root = Path(action_root or self.root).resolve()
        if action_root is not None:
            from .creative_tools import CreativeToolRuntime, creative_tool_definitions
            saved_work = CreativeToolRuntime(action_root)
            for name, *_ in creative_tool_definitions():
                if name.startswith(("work.","intelligence.","quality.","taste.","attention.","execution.","situation.","experience.")):
                    self.native._handlers[name] = lambda args, tool=name: saved_work.call(tool, args)
            scoped_experiments = CreativeToolRuntime(self.root, collaboration_root=action_root, work_scope=action_scope)
            for name, *_ in creative_tool_definitions():
                if name.startswith(("lab.", "behavior.")):
                    self.native._handlers[name] = lambda args, tool=name: scoped_experiments.call(tool, args)
        self.allowed_mutation_tools = allowed_mutation_tools
        from .action_receipts import NativeActionStore
        self.actions = NativeActionStore(action_root or self.root, action_scope or str(self.root))
        self._operations = None
        self._recoveries = None
        self._compiled_tool_belt: dict[str, Any] | None = None
        self._compiled_tool_maps = None
        self._tool_loop_receipts: list[str] = []

    @property
    def capabilities(self):
        if not self._capabilities_loaded:
            from .capability_service import CapabilityService
            try:
                self._capabilities = CapabilityService(self.root)
            except FileNotFoundError:
                self._capabilities = None
            self._capabilities_loaded = True
        return self._capabilities

    @property
    def operations(self):
        if self._operations is None:
            from .verified_operations import VerifiedOperationStore
            self._operations = VerifiedOperationStore(self.work_root, self.work_scope or str(self.root))
        return self._operations

    @property
    def recoveries(self):
        if self._recoveries is None:
            from .recovery_objects import RecoveryObjectStore
            self._recoveries = RecoveryObjectStore(self.work_root, self.work_scope or str(self.root))
        return self._recoveries

    @property
    def compiled_tool_maps(self):
        if self._compiled_tool_maps is None:
            from .compiled_tool_maps import CompiledToolMapStore
            self._compiled_tool_maps = CompiledToolMapStore()
        return self._compiled_tool_maps

    def compile(self, task: str, limit: int = 12) -> dict[str, Any]:
        """Compile one task-scoped provider belt and retain its immutable call map."""

        if self.capabilities is None:
            return {
                "schema": "neyvia.production-tool-compiler.v1",
                "status": "not_configured",
                "providerCalls": [],
            }
        compiled = self.capabilities.compile_openai_tool_belt(
            {
                "task": str(task or "").strip(),
                "limit": max(1, min(int(limit), 20)),
                "deferLoading": True,
            }
        )
        self._compiled_tool_belt = compiled
        version = self.compiled_tool_maps.retain(compiled)
        provider_calls = []
        for namespace_row in compiled.get("tools") or []:
            if not isinstance(namespace_row, dict) or namespace_row.get("type") != "namespace":
                continue
            namespace = str(namespace_row.get("name") or "")
            for tool in namespace_row.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                provider_calls.append(
                    {
                        "providerCall": f"{namespace}.{tool.get('name')}@{version}",
                        "description": str(tool.get("description") or ""),
                        "deferred": bool(tool.get("defer_loading")),
                    }
                )
        return {
            "schema": "neyvia.production-tool-compiler.v1",
            "status": "ready",
            "catalogHash": str((compiled.get("belt") or {}).get("catalogHash") or ""),
            "callMapHash": version,
            "providerCalls": provider_calls,
            "warnings": list(compiled.get("warnings") or []),
            "policy": dict((compiled.get("belt") or {}).get("policy") or {}),
        }

    def call_compiled(
        self,
        provider_call: str,
        arguments: dict[str, Any] | None = None,
        *, action_id: str = "",
    ) -> dict[str, Any]:
        """Resolve one provider call through the retained map and run one bounded step."""

        if self.capabilities is None or self._compiled_tool_belt is None:
            return {
                "ok": False,
                "status": "compiler_not_ready",
                "message": "Search tools for the current task before calling a compiled tool.",
            }
        normalized = str(provider_call or "").strip()
        resolved = self.compiled_tool_maps.resolve(normalized, arguments or {})
        if resolved.get("requiresApproval") and not self.allow_mutations:
            return {
                "ok": False,
                "status": "approval_required",
                "providerCall": normalized,
                "callTarget": resolved["callTarget"],
                "message": (
                    "This compiled call changes browser, workspace, artifact, or external state. "
                    "Resume with an operator-approved mutation grant."
                ),
            }
        if resolved.get("requiresApproval") and self.allowed_mutation_tools is not None:
            return {"ok": False, "status": "mutation_outside_contract",
                    "message": "This run grants named native tools only. Use neyvia_native_call for a granted tool.",
                    "allowedNativeMutationTools": sorted(self.allowed_mutation_tools)}
        plan = {
                "goal": f"Execute compiled provider call {normalized}",
                "calls": [
                    {
                        "callTarget": resolved["callTarget"],
                        "arguments": resolved["arguments"],
                        "route": resolved.get("route") or "direct",
                        "approved": self.allow_mutations,
                        "idempotent": bool(
                            (resolved.get("provenance") or {}).get("readOnlyHint")
                        ),
                    }
                ],
                "maxCalls": 1,
                "maxRetries": 0,
                "maxWallTimeMs": 120000,
                "maxContextBytes": 131072,
                "minimumEvidence": 0,
                "approved": self.allow_mutations,
        }
        def invoke():
            loop = self.capabilities.run_model_tool_plan(plan)
            receipt_path = str(loop.get("receiptPath") or "")
            if receipt_path and receipt_path not in self._tool_loop_receipts:
                self._tool_loop_receipts.append(receipt_path)
            return {"ok": loop.get("status") == "completed", "status": loop.get("status"),
                    "providerCall": normalized, "callMapHash": resolved["callMapHash"],
                    "callTarget": resolved["callTarget"], "run": loop}
        if resolved.get("requiresApproval"):
            return self._record_managed_action(action_id, f"compiled:{normalized}",
                {"callTarget": resolved["callTarget"], "arguments": resolved["arguments"]}, invoke)
        return invoke()

    def compiler_snapshot(self) -> dict[str, Any]:
        if self._compiled_tool_belt is None:
            return {"status": "not_compiled", "providerCalls": 0, "callMapHash": ""}
        call_map = self._compiled_tool_belt.get("callMap") or {}
        return {
            "status": "ready",
            "providerCalls": len(call_map),
            "callMapHash": canonical_hash(call_map),
            "retainedVersions": self.compiled_tool_maps.version_count,
            "catalogHash": str(
                (self._compiled_tool_belt.get("belt") or {}).get("catalogHash") or ""
            ),
        }

    @property
    def tool_loop_receipts(self) -> list[str]:
        return list(self._tool_loop_receipts)

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 20))
        compiler = (
            self.compile(query, bounded)
            if str(query or "").strip() and self.capabilities is not None
            else {
                "schema": "neyvia.production-tool-compiler.v1",
                "status": "query_required",
                "providerCalls": [],
            }
        )
        managed = (
            self.capabilities.search_tool_suite(
                {
                    "query": query,
                    "limit": bounded,
                    "agentReadyOnly": True,
                    "executionReadyOnly": True,
                }
            )
            if self.capabilities is not None
            else {
                "schema": "neyvia.tool_suite_lock.v1",
                "query": query,
                "results": [],
                "summary": {
                    "matches": 0,
                    "returned": 0,
                    "agentReadyOnly": True,
                    "executionReadyOnly": True,
                    "operationsDeferred": True,
                    "status": "not_configured",
                },
            }
        )
        return {
            "schema": "neyvia.agent-tool-search/v1",
            "query": query,
            "native": [self._native_discovery(tool) for tool in self.native.search(query, limit=bounded)],
            "managed": managed,
            "compiler": compiler,
            "flow": ["search", "describe", "call", "receipt"],
            "compilerFlow": ["compile", "resolve", "bounded-call", "receipt"],
        }

    def _native_discovery(self, tool: dict[str, Any]) -> dict[str, Any]:
        from .workspace_intelligence import COLLABORATION_NOTE_TOOLS
        name = str(tool.get("name") or "")
        mutation = tool.get("mutability_class") not in {"read", "none"}
        scoped_note = name in COLLABORATION_NOTE_TOOLS and bool(self.work_scope)
        observation = name in {"preview.screenshot", "preview.taste"}
        allowed = (not mutation or scoped_note or observation or
                   (self.allow_mutations and (self.allowed_mutation_tools is None or name in self.allowed_mutation_tools)))
        if name == "terminal.exec" and self.permission_mode != "full-access":
            allowed = False
        call_instructions = "Pass this exact name as tool_id and its schema fields as arguments_json. Use a stable action_id for mutations."
        if name == "terminal.exec" and not allowed:
            call_instructions += " Local commands require Full access in the composer to bypass local approvals."
        return {**{key:value for key,value in tool.items() if key != "core"},
                "catalogCore": bool(tool.get("core")), "allowedInRun": allowed,
                "callTarget": "neyvia_native_call", "actionIdRequired": mutation and not observation,
                "callInstructions": call_instructions,
                **({"capturePolicy": "Read-only capture is allowed; a journey requires a preview.taste mutation grant."} if name == "preview.taste" else {})}

    def describe(self, tool_id: str) -> dict[str, Any]:
        try:
            return {"kind": "native", "tool": self._native_discovery(self.native.describe(tool_id))}
        except KeyError:
            if self.capabilities is None:
                raise KeyError(
                    "Managed tool catalog is not configured for this workspace."
                )
            return {
                "kind": "managed",
                "tool": self.capabilities.describe_tool_suite({"toolId": tool_id}),
            }

    def _call_bound_native(self, tool_id, arguments):
        if tool_id.startswith('neyvia.memory.'):
            from .cue_memory import BOUND_MEMORY, require_context
            token = BOUND_MEMORY.set(require_context(getattr(self, 'memory_context', None)))
            try:
                return self.native.call(tool_id, arguments)
            finally:
                BOUND_MEMORY.reset(token)
        if not tool_id.startswith("neyvia.cua."):
            return self.native.call(tool_id, arguments)
        from .neyvia_cua import NATIVE_CLIENT
        token = NATIVE_CLIENT.set({"chatId": self.work_scope or "native", "app": "neyvia"})
        try:
            return self.native.call(tool_id, arguments)
        finally:
            NATIVE_CLIENT.reset(token)

    def call_native(
        self,
        tool_id: str,
        arguments: dict[str, Any] | None = None,
        *, action_id: str = "",
    ) -> dict[str, Any]:
        description = self.native.describe(tool_id)
        from .native_arguments import normalize
        arguments = normalize(description["inputSchema"], dict(arguments or {}))
        if tool_id in {"neyvia.cl", "neyvia.cl.describe"}:
            arguments = self.native.prepare_arguments(tool_id, arguments)
            from .cl.protocol import Protocol
            if not hasattr(self, "_cl_protocol"):
                self._cl_protocol = Protocol(self, lazy_manuals=True)
            if tool_id == "neyvia.cl.describe":
                return {"ok": True, "text": self._cl_protocol.describe(**arguments)}
            return self._cl_protocol.run(arguments["lines"], action_id=arguments.get("actionId", action_id),
                                         scope_tools=arguments.get("scopeTools"))
        protocol = getattr(self, "_cl_protocol", None)
        if protocol is not None and protocol.host.task_active and protocol._mutating(tool_id, arguments):
            protocol.host.invalidate_done()
            protocol._save_completion()
        if tool_id.startswith("neyvia.efficiency."):
            from .neyvia_efficiency import call
            from .neyvia_workspace_tools import workspace_for
            arguments = self.native.prepare_arguments(tool_id, arguments)
            return call(workspace_for(self.root), tool_id.removeprefix("neyvia."), arguments,
                        dispatcher=self.call_native)
        if tool_id.startswith("neyvia.autopilot."):
            from .neyvia_autopilot import call
            from .neyvia_workspace_tools import workspace_for
            arguments = self.native.prepare_arguments(tool_id, arguments)
            scope = arguments.get("scopeTools", [])
            if tool_id.endswith(".resume"):
                from .neyvia_autopilot import load
                scope = load(workspace_for(self.root), arguments["runId"])["scopeTools"]
            for nested in scope:
                mutating = self.native.describe(nested).get("mutability_class") not in {"read", "none"}
                if mutating and (not self.allow_mutations or self.allowed_mutation_tools is not None and nested not in self.allowed_mutation_tools):
                    raise PermissionError("Autopilot scope exceeds this caller's mutation authority: " + nested)
            if arguments.get("background"):
                raise ValueError("Background autopilot belongs to the persistent owner HTTP service; native calls run synchronously")
            return call(workspace_for(self.root), tool_id.removeprefix("neyvia."), arguments,
                        registry=self.native, dispatcher=self.call_native)
        if tool_id in {"neyvia.manual.run", "neyvia.manual.observe", "neyvia.manual.script.run", "neyvia.manual.recover"}:
            arguments = self.native.prepare_arguments(tool_id, arguments)
            if tool_id == "neyvia.manual.observe" and self.work_scope:
                arguments.setdefault("stream", self.work_scope)
            from .neyvia_manuals import call
            from .neyvia_workspace_tools import workspace_for
            return call(workspace_for(self.root), tool_id.removeprefix("neyvia."), arguments,
                        dispatcher=self.call_native, registry=self.native)
        if tool_id in {"host.launch", "host.launch_file", "host.stop", "lab.rehearse"}:
            arguments = {**(arguments or {}), "_actor": "agent"}
        from .workspace_intelligence import COLLABORATION_FEATURE_TOOLS, COLLABORATION_NOTE_TOOLS
        managed_note = tool_id in COLLABORATION_NOTE_TOOLS and bool(self.work_scope)
        if (tool_id.startswith(("work.","intelligence.","quality.","taste.","attention.","execution.","situation.","experience.")) or tool_id in COLLABORATION_FEATURE_TOOLS) and self.work_scope:
            arguments = dict(arguments or {})
            if arguments.get("workId") and arguments["workId"] != self.work_scope:
                return {"ok":False,"status":"work_scope_mismatch","workId":self.work_scope,
                        "message":"Use the durable work identity bound to this run."}
            arguments["workId"] = self.work_scope
        mutability = str(description.get("mutability_class") or "read")
        if tool_id == "terminal.exec" and self.permission_mode != "full-access":
            return {"ok": False, "status": "approval_required", "toolId": tool_id,
                    "message": "Local commands require Full access in the composer to bypass local approvals."}
        if tool_id == "preview.screenshot" and not self.allow_mutations:
            # Observational capture may write only its managed proof artifact.
            arguments = {**(arguments or {}), "outputPath": ""}
            return self._call_bound_native(tool_id, arguments)
        if tool_id == "preview.taste" and not self.allow_mutations:
            # Looking is observational; a Laya journey operates the page.
            if (arguments or {}).get("journey"):
                return {"ok": False, "status": "approval_required", "toolId": tool_id,
                        "message": "A Laya journey clicks and types in the page. Review without a journey stays read-only; "
                                   "exercising controls needs an operator-approved mutation grant."}
            arguments = {**(arguments or {}), "outputDir": ""}
            return self._call_bound_native(tool_id, arguments)
        if not self.allow_mutations and not managed_note and mutability not in {"read", "none"}:
            if tool_id == "terminal.exec":
                return {"ok": False, "status": "approval_required", "toolId": tool_id,
                        "message": "Local commands require Full access in the composer to bypass local approvals."}
            return {
                "ok": False,
                "status": "approval_required",
                "toolId": tool_id,
                "mutability": mutability,
                "message": (
                    "This Neyvia Agent run is read-only. Resume with an "
                    "operator-approved mutation grant to execute this tool."
                ),
            }
        if mutability not in {"read", "none"}:
            if not managed_note and self.allowed_mutation_tools is not None and tool_id not in self.allowed_mutation_tools:
                return {"ok": False, "status": "mutation_outside_contract", "toolId": tool_id,
                        "message": ("Local commands require Full access in the composer to bypass local approvals."
                                    if tool_id == "terminal.exec" else "This native mutation is outside the run's tool grants."),
                        "allowedNativeMutationTools": sorted(self.allowed_mutation_tools)}
            if not action_id:
                return {"ok": False, "status": "action_id_required", "toolId": tool_id,
                        "message": "Provide a stable actionId for this intended mutation and reuse it after interruption or compaction. Inspect saved actions before repeating work."}
            # Invalid declared inputs have no effects and must not poison an action ID.
            arguments = self.native.prepare_arguments(tool_id, arguments)
            if tool_id in {'neyvia.memory.remember', 'neyvia.memory.correct', 'neyvia.memory.forget'}:
                # The private store commits request identity and effect atomically.
                # Generic journals would retain forgotten bodies; CL observes the
                # current private store instead of a plaintext action archive.
                return self._call_bound_native(tool_id, arguments)
            if tool_id in {"neyvia.image.export", "neyvia.image.generate"} and self.actions.inspect(action_id).get("status") == "not_started":
                from .neyvia_image_approval import for_gateway
                approval = for_gateway(self.root, tool_id, arguments or {})
                if approval:
                    return approval
            from .workspace_intelligence import require_collaboration_feature
            try:
                require_collaboration_feature(self.work_root, self.work_scope or (arguments or {}).get("workId"), tool_id)
            except PermissionError as exc:
                return {"ok": False, "status": "experience_disabled", "toolId": tool_id,
                        "message": str(exc)}
            binding = {"workspace": str(self.root), "arguments": arguments or {}}
            authority = {"granted": True, "grant": "scoped_collaboration_record" if managed_note else "native_mutation", "toolId": tool_id}
            def invoke() -> dict[str, Any]:
                operation_id = f"{action_id}:{tool_id}"
                recovery_id = "recovery_" + hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:32]
                from .operation_adapters import adapter_for
                adapter = adapter_for(self.operations.root if tool_id.startswith("work.") else self.root, tool_id, arguments or {})
                operation = self.operations.execute(
                    operation_id, tool_id, authority=authority,
                    request=binding,
                    before=adapter.before if adapter else None,
                    effect=lambda: self._call_bound_native(tool_id, arguments or {}),
                    after=adapter.after if adapter else None,
                    verify=adapter.verify if adapter else None,
                    recovery_ref=recovery_id,
                )
                native = dict(operation.get("result", {}).get("effect") or {}) if isinstance(operation.get("result"), dict) else {}
                native.setdefault("ok", bool(native.get("ok", False)))
                if tool_id in {"workspace.write", "workspace.patch", "terminal.exec"} or tool_id.startswith(("neyvia.scene.","neyvia.laya.","neyvia.image.","preview.","laya.native.","intelligence.","quality.","taste.","attention.","host.","lab.","situation.")):
                    native["toolResult"] = native.get("result", {})
                if tool_id in {"workspace.write", "workspace.patch"}:
                    native["filesChanged"] = list((native.get("result") or {}).get("filesChanged") or [])
                if operation.get("status") == "unknown_side_effects":
                    native["ok"] = False
                    native["status"] = "action_uncertain"
                native["operationStatus"] = operation.get("status")
                if tool_id.startswith("neyvia.image."):
                    native["verification"] = (operation.get("result") or {}).get("verification")
                native["operationReceiptPath"] = operation.get("operationReceiptPath")
                if operation.get("status") in {"unknown_side_effects", "failed"}:
                    native["failure"] = {
                        "kind": str(operation.get("status")),
                        "message": safe_tool_display(
                            operation.get("error") or native.get("error")
                            or (native.get("failure") or {}).get("message")
                            or operation.get("message") or "Tool verification failed."
                        ),
                        "recovery": "Inspect the saved operation and target before any retry.",
                    }
                    recovery = self.recoveries.create(
                        {"operationId": operation_id, "toolId": tool_id, "arguments": binding},
                        recovery_id=recovery_id,
                        uncertain_effects=[{"operationStatus": operation.get("status"), "message": operation.get("message", "") }],
                        retry_safety="requires_reconciliation",
                        required_authority=["native_mutation"],
                        available_recovery_paths=[{"kind": "inspect_operation", "operationId": operation_id}],
                        operation_id=operation_id,
                    )
                    native["recoveryRef"] = recovery.recovery_id
                return native
            return self.actions.execute(action_id, tool_id, binding, invoke)
        return self._call_bound_native(tool_id, arguments or {})

    def call_managed(
        self,
        tool_id: str,
        operation_id: str,
        arguments: dict[str, Any] | None = None,
        *, action_id: str = "",
    ) -> dict[str, Any]:
        if self.capabilities is None:
            return {
                "ok": False,
                "status": "managed_catalog_not_configured",
                "toolId": tool_id,
                "operationId": operation_id,
            }
        description = self.capabilities.describe_tool_suite({"toolId": tool_id})
        if not description.get("executionReady"):
            return {
                "ok": False,
                "status": "tool_execution_not_ready",
                "toolId": tool_id,
                "operationId": operation_id,
                "blockedPrerequisites": description.get("blockedPrerequisites") or [],
                "message": (
                    "This package is catalogued but has no verified executable "
                    "adapter on the current host."
                ),
            }
        operations = description.get("operations") or []
        selected = next(
            (
                row
                for row in operations
                if isinstance(row, dict)
                and str(row.get("operationId") or "") == operation_id
            ),
            None,
        )
        if selected is None:
            raise KeyError(f"{tool_id} does not expose {operation_id}.")
        permissions = [str(item) for item in selected.get("permissions") or ()]
        mutating = any(
            token in permission
            for permission in permissions
            for token in ("write", "delete", "execute", "network")
        )
        if mutating and not self.allow_mutations:
            return {
                "ok": False,
                "status": "approval_required",
                "toolId": tool_id,
                "operationId": operation_id,
                "permissions": permissions,
            }
        if mutating and self.allowed_mutation_tools is not None:
            return {"ok": False, "status": "mutation_outside_contract",
                    "toolId": tool_id, "operationId": operation_id,
                    "message": "This run grants named native tools only; managed package mutations are not granted."}
        request = {
            "toolId": tool_id,
            "operationId": operation_id,
            "arguments": arguments or {},
            "permissionMode": "operator_approved" if self.allow_mutations else "workspace_safe",
            "approvedPermissions": permissions if self.allow_mutations else [],
        }
        if not mutating:
            return self.capabilities.execute_tool_operation(request)
        return self._record_managed_action(
            action_id, f"managed:{tool_id}:{operation_id}", request,
            lambda: self.capabilities.execute_tool_operation(request),
        )

    def _record_managed_action(self, action_id, tool_id, request, effect):
        """Use the same durable attempt boundary without inventing a verifier."""
        if not action_id:
            return {"ok": False, "status": "action_id_required", "toolId": tool_id,
                    "message": "Use one stable action_id for this intent. Inspect it before recovery; do not rename a retry."}
        binding = {"workspace": str(self.root), "request": request}
        def invoke():
            operation_id = f"{action_id}:{tool_id}"
            recovery_id = "recovery_" + hashlib.sha256(operation_id.encode()).hexdigest()[:32]
            operation = self.operations.execute(operation_id, tool_id,
                authority={"granted": self.allow_mutations, "grant": "managed_mutation", "toolId": tool_id},
                request=binding, effect=effect, recovery_ref=recovery_id)
            result = dict((operation.get("result") or {}).get("effect") or {})
            output = {"ok": result.get("ok") is True, "status": result.get("status") or "failed",
                      "toolResult": result, "operationStatus": operation.get("status"),
                      "operationReceiptPath": operation.get("operationReceiptPath")}
            if operation.get("status") in {"unknown_side_effects", "failed"}:
                output.update(ok=False, status="action_uncertain" if operation["status"] == "unknown_side_effects" else "failed")
                self.recoveries.create({"operationId": operation_id, "toolId": tool_id},
                    recovery_id=recovery_id, operation_id=operation_id,
                    uncertain_effects=[{"operationStatus": operation["status"]}],
                    retry_safety="requires_reconciliation", required_authority=["managed_mutation"],
                    available_recovery_paths=[{"kind": "inspect_operation", "operationId": operation_id}])
                output["recoveryRef"] = recovery_id
            return output
        return self.actions.execute(action_id, tool_id, binding, invoke)
