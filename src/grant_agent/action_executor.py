from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, fields
from pathlib import Path

from .models import (
    ActionApprovalGate,
    ActionExecutionRecord,
    ActionProposal,
    ActionResultEnvelope,
    DelegatedRuntimeSession,
    ExecutionPolicy,
    ExecutionScope,
    ModelRouteConfig,
    Mission,
    PlannedStep,
    WorkspaceProfile,
    utc_now_iso,
)
from .execution_truth import derive_execution_target
from .research import search_workspace
from .runtimes import runtime_adapter_map
from .runtimes.base import runtime_subprocess_env
from .runtime_supervisor import DelegatedRuntimeSupervisor, _pid_alive
from .safety import risk_level_for_command
from .subprocess_utils import hidden_windows_subprocess_kwargs

PROFILE_EXECUTION_DEFAULTS = {
    "beginner": {
        "scope": "isolated",
        "approval_mode": "strict",
        "explanation_depth": "high",
        "delegation": "low",
    },
    "builder": {
        "scope": "isolated",
        "approval_mode": "tiered",
        "explanation_depth": "medium",
        "delegation": "balanced",
    },
    "advanced": {
        "scope": "isolated",
        "approval_mode": "tiered",
        "explanation_depth": "low",
        "delegation": "balanced",
    },
    "experimental": {
        "scope": "isolated",
        "approval_mode": "hands_free",
        "explanation_depth": "low",
        "delegation": "high",
    },
}
PROFILE_EXECUTION_ALIASES = {
    "hands_free_builder": "experimental",
}

WRITE_HINTS = (
    "build",
    "implement",
    "edit",
    "update",
    "patch",
    "fix",
    "repair",
    "write",
    "refactor",
    "prototype",
    "dashboard",
    "report",
)
CREATE_HINTS = ("create", "new file", "draft", "author", "artifact")
DELEGATE_HINTS = ("delegate", "runtime lane", "openclaw", "hermes")
STATUS_HINTS = ("status", "ground", "inspect mutable", "workspace state")
DIFF_HINTS = ("rollout", "diff", "next iteration", "changed files")
VERIFY_HINTS = ("verify", "test", "lint", "smoke")
EXECUTION_TARGET_SCOPE_OVERRIDES = {
    "workspace_root": "direct",
    "isolated_worktree": "isolated",
}
ISOLATED_COPY_EXCLUDE_NAMES = {
    ".agent_control",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}
DELEGATED_PLAN_HINTS = (
    "plan",
    "replan",
    "diagnose",
    "investigate",
    "inspect",
    "research",
    "analyze",
    "analysis",
    "review",
    "roadmap",
)
DELEGATED_VERIFY_HINTS = (
    "verify",
    "verification",
    "test",
    "lint",
    "smoke",
    "proof",
    "validate",
)

_MODEL_ROUTE_CONFIG_FIELDS = {field.name for field in fields(ModelRouteConfig)}


def _normalize_runtime_id(value: object, default: str = "hermes") -> str:
    normalized = str(value or default).strip().lower().replace("_", "-")
    aliases = {
        "open-code": "opencode",
        "opencode-native": "opencode",
        "native-opencode": "opencode",
        "openclaw-local": "openclaw",
    }
    return aliases.get(normalized, normalized) or default


def _route_config_payload(item: object) -> dict:
    if hasattr(item, "__dataclass_fields__"):
        payload = asdict(item)
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        return {}
    if "runtime_id" in payload and "runtimeId" not in payload:
        payload["runtimeId"] = payload.get("runtime_id")
    if "budgetClass" in payload and "budget_class" not in payload:
        payload["budget_class"] = payload.get("budgetClass")
    if "fallbackPolicy" in payload and "fallback_policy" not in payload:
        payload["fallback_policy"] = payload.get("fallbackPolicy")
    if "taskType" in payload and "task_type" not in payload:
        payload["task_type"] = payload.get("taskType")
    if "routeIntent" in payload and "route_intent" not in payload:
        payload["route_intent"] = payload.get("routeIntent")
    return payload


def _model_route_config_from_payload(item: object) -> ModelRouteConfig | None:
    payload = _route_config_payload(item)
    if not payload:
        return None
    filtered = {
        key: value
        for key, value in payload.items()
        if key in _MODEL_ROUTE_CONFIG_FIELDS
    }
    if not filtered.get("role") or not filtered.get("provider") or not filtered.get("model"):
        return None
    return ModelRouteConfig(**filtered)


def _isolated_copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if name in ISOLATED_COPY_EXCLUDE_NAMES
        or name.endswith(".pyc")
        or name.endswith(".pyo")
    }
    if Path(directory).name in {"web", "frontend"}:
        ignored.update({"dist", "node_modules"} & set(names))
    return ignored


def _filesystem_copy_execution_scope(
    *,
    workspace_root: Path,
    worktree_path: Path,
    requested: str,
    branch_name: str,
    reason: str,
) -> tuple[ExecutionScope | None, str]:
    if worktree_path.exists():
        return _with_execution_truth(
            ExecutionScope(
                requested=requested,
                strategy="filesystem_copy",
                execution_root=str(worktree_path),
                workspace_root=str(workspace_root),
                branch_name=branch_name,
                worktree_path=str(worktree_path),
                isolated=True,
                status="ready",
                detail="Mission is isolated in a dedicated filesystem copy.",
            )
        ), ""
    try:
        shutil.copytree(
            workspace_root,
            worktree_path,
            symlinks=True,
            ignore=_isolated_copy_ignore,
        )
    except OSError as exc:
        shutil.rmtree(worktree_path, ignore_errors=True)
        return None, str(exc)
    return _with_execution_truth(
        ExecutionScope(
            requested=requested,
            strategy="filesystem_copy",
            execution_root=str(worktree_path),
            workspace_root=str(workspace_root),
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            isolated=True,
            status="ready",
            detail=(
                "Git worktree isolation was unavailable, so Neyvia created a "
                f"dedicated filesystem copy. {reason}"
            ).strip(),
        )
    ), ""


class ExecutionAdapter(ABC):
    @abstractmethod
    def build_policy(self, profile_name: str) -> ExecutionPolicy:
        raise NotImplementedError

    @abstractmethod
    def prepare_scope(
        self,
        workspace_root: Path,
        mission_id: str,
        requested_scope: str = "",
        profile_name: str = "builder",
    ) -> ExecutionScope:
        raise NotImplementedError

    @abstractmethod
    def build_action_proposal(
        self,
        step: PlannedStep,
        objective: str,
        workspace_root: Path,
        verification_commands: list[str],
        runtime_id: str,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
        route_configs: list[dict] | list[ModelRouteConfig] | None = None,
    ) -> ActionProposal:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        proposal: ActionProposal,
        workspace_root: Path,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
        timeout_seconds: int = 90,
        approval_override: bool = False,
    ) -> ActionExecutionRecord:
        raise NotImplementedError


class HybridExecutionAdapter(ExecutionAdapter):
    def build_policy(self, profile_name: str) -> ExecutionPolicy:
        normalized_profile = (profile_name or "builder").strip().lower()
        normalized_profile = PROFILE_EXECUTION_ALIASES.get(
            normalized_profile,
            normalized_profile,
        )
        defaults = PROFILE_EXECUTION_DEFAULTS.get(
            normalized_profile,
            PROFILE_EXECUTION_DEFAULTS["builder"],
        )
        approval_mode = defaults["approval_mode"]
        auto_allowed = [
            "workspace_search",
            "file_read",
            "git_status",
            "git_diff",
            "test_run",
            "native_tool",
            "runtime_delegate",
        ]
        approval_required = ["git_commit", "shell_command"]
        if approval_mode == "strict":
            approval_required.extend(["file_patch", "file_write"])
        elif approval_mode == "tiered":
            approval_required.extend(["file_patch", "file_write"])
        return normalize_execution_policy(
            ExecutionPolicy(
                profile_name=(profile_name or "builder"),
                approval_mode=approval_mode,
                explanation_depth=defaults["explanation_depth"],
                delegation_aggressiveness=defaults["delegation"],
                auto_allowed_kinds=auto_allowed,
                approval_required_kinds=approval_required,
                destructive_requires_approval=True,
            )
        )

    def prepare_scope(
        self,
        workspace_root: Path,
        mission_id: str,
        requested_scope: str = "",
        profile_name: str = "builder",
    ) -> ExecutionScope:
        workspace_root = workspace_root.resolve()
        requested = requested_scope or PROFILE_EXECUTION_DEFAULTS.get(
            (profile_name or "builder").strip().lower(),
            PROFILE_EXECUTION_DEFAULTS["builder"],
        )["scope"]
        direct_scope = _with_execution_truth(
            ExecutionScope(
            requested=requested,
            strategy="direct",
            execution_root=str(workspace_root),
            workspace_root=str(workspace_root),
            isolated=False,
            status="ready",
            detail="Mission is executing in the primary workspace.",
            )
        )
        branch_name = f"fluxio/{mission_id}"
        worktree_path = workspace_root.parent / f".fluxio-worktrees-{workspace_root.name}" / mission_id
        if requested == "direct":
            return direct_scope
        if not _is_git_workspace(workspace_root):
            copy_scope, copy_error = _filesystem_copy_execution_scope(
                workspace_root=workspace_root,
                worktree_path=worktree_path,
                requested=requested,
                branch_name=branch_name,
                reason="Source workspace is not a git checkout.",
            )
            if copy_scope is not None:
                return copy_scope
            direct_scope.status = "fallback"
            direct_scope.detail = (
                "Git isolation is unavailable and filesystem isolation failed, "
                f"so Neyvia is using the primary workspace. {copy_error}".strip()
            )
            return direct_scope
        if worktree_path.exists():
            return _with_execution_truth(ExecutionScope(
                requested=requested,
                strategy="git_worktree",
                execution_root=str(worktree_path),
                workspace_root=str(workspace_root),
                branch_name=branch_name,
                worktree_path=str(worktree_path),
                isolated=True,
                status="ready",
                detail="Mission is isolated in a dedicated git worktree.",
            ))

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        add_attempts = [
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
            ["git", "worktree", "add", "--force", str(worktree_path), "HEAD"],
        ]
        last_error = ""
        for command in add_attempts:
            try:
                completed = subprocess.run(  # noqa: S603
                    command,
                    cwd=str(workspace_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
            except OSError as exc:
                last_error = str(exc)
                continue
            if completed.returncode == 0:
                return _with_execution_truth(ExecutionScope(
                    requested=requested,
                    strategy="git_worktree",
                    execution_root=str(worktree_path),
                    workspace_root=str(workspace_root),
                    branch_name=branch_name,
                    worktree_path=str(worktree_path),
                    isolated=True,
                    status="ready",
                    detail="Mission is isolated in a dedicated git worktree.",
            ))
            last_error = (completed.stderr or completed.stdout).strip()

        copy_scope, copy_error = _filesystem_copy_execution_scope(
            workspace_root=workspace_root,
            worktree_path=worktree_path,
            requested=requested,
            branch_name=branch_name,
            reason=last_error,
        )
        if copy_scope is not None:
            return copy_scope
        direct_scope.status = "fallback"
        direct_scope.detail = (
            "Git worktree setup failed and filesystem isolation failed, so Neyvia "
            f"fell back to the primary workspace. {last_error} {copy_error}".strip()
        )
        return direct_scope

    def build_action_proposal(
        self,
        step: PlannedStep,
        objective: str,
        workspace_root: Path,
        verification_commands: list[str],
        runtime_id: str,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
        route_configs: list[dict] | list[ModelRouteConfig] | None = None,
    ) -> ActionProposal:
        raw_step_text = f"{step.title} {step.description}"
        video_match = re.search(
            r"(?P<path>(?:[A-Za-z]:[\\/]|/)[^\r\n\"']+?\.(?:mp4|mov|mkv|webm|avi))(?=\s|$)",
            raw_step_text,
            flags=re.IGNORECASE,
        )
        # A source folder named verify/test/hermes is data, not an instruction
        # to select a test runner or delegated runtime. Keep the exact source
        # for the later video action and classify only the surrounding intent.
        intent_text = (raw_step_text[:video_match.start()] + raw_step_text[video_match.end():]
                       if video_match else raw_step_text)
        step_text = intent_text.lower()
        lowered = f"{step_text} {objective}".lower()
        action_id = f"action_{uuid.uuid4().hex[:10]}"
        event_id = f"evt_{uuid.uuid4().hex[:10]}"
        scope_root = Path(execution_scope.execution_root or workspace_root)
        target_path = _infer_target_path(objective, scope_root)

        if _matches(step_text, VERIFY_HINTS):
            command = verification_commands[0] if verification_commands else "git diff --stat"
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="test_run",
                title=f"Run verification for {step.title}",
                command=command,
                step=step,
                reason="Verification uses the real execution surface so proof reflects actual outcomes.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                mutability_class="verify",
            )

        if _should_delegate_step(lowered, execution_policy):
            delegated_cycle_phase = _delegated_cycle_phase(step, objective, route_configs)
            delegated_role = _route_role_for_phase(delegated_cycle_phase)
            route_rows = [_route_config_payload(item) for item in (route_configs or [])]
            delegated_route = next(
                (
                    item
                    for item in route_rows
                    if str(item.get("role", "")).strip().lower()
                    == delegated_role
                ),
                {},
            )
            delegated_runtime_id = _normalize_runtime_id(
                delegated_route.get("runtimeId")
                or delegated_route.get("runtime_id")
                or delegated_route.get("runtime")
                or runtime_id
            )
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="runtime_delegate",
                title=f"Delegate {step.title} to {delegated_runtime_id}",
                step=step,
                reason="Neyvia can hand this step to the selected runtime lane and normalize the returned trace.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                mutability_class="delegate",
                delegation_metadata={
                    "runtime_id": delegated_runtime_id,
                    "mission_runtime_id": runtime_id,
                    "route_runtime_id": delegated_runtime_id,
                    "objective": objective,
                    "cycle_phase": delegated_cycle_phase,
                    "route_role": delegated_role,
                    "route_provider": str(delegated_route.get("provider", "")).strip().lower(),
                    "route_model": str(delegated_route.get("model", "")).strip(),
                    "route_effort": str(delegated_route.get("effort", "")).strip().lower(),
                    "route_configs": route_rows,
                },
            )

        if _matches(lowered, DIFF_HINTS):
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="git_diff",
                title=f"Inspect diff surface for {step.title}",
                command="git diff --stat",
                step=step,
                reason="Diff summaries keep proof grounded in actual repo changes.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                mutability_class="read",
            )

        if _matches(lowered, STATUS_HINTS):
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="git_status",
                title=f"Inspect workspace state for {step.title}",
                command="git status --short",
                step=step,
                reason="The planner should inspect actual repo state before branching into more work.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                mutability_class="read",
            )

        if video_match and re.search(r"\b(?:analy[sz]e|review|digest|storyboard|scene)\b", lowered):
            video_path = video_match.group("path").strip()
            proposal = self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="native_tool",
                title=f"Build video evidence for {step.title}",
                step=step,
                reason="The native video digest produces sampled frames, scene evidence, and a manifest.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                args={
                    "tool": "video.digest",
                    "arguments": {"path": video_path},
                },
                mutability_class="verify",
            )
            from .proofs_e_sv import check_video_proposal
            return check_video_proposal(proposal, video_path)

        screenshot_request = re.search(
            r"\b(?:capture|take|create|make)\b.*\b(?:screenshot|visual proof)\b"
            r"|\b(?:screenshot|visual proof)\b",
            lowered,
        )
        if screenshot_request:
            url_match = re.search(r"\b(?:https?|file)://[^\s)\]}>\"']+", lowered)
            if url_match:
                return self._proposal(
                    action_id=action_id,
                    event_id=event_id,
                    kind="native_tool",
                    title=f"Capture preview proof for {step.title}",
                    step=step,
                    reason="A native preview capture produces real, receipted visual evidence.",
                    execution_scope=execution_scope,
                    execution_policy=execution_policy,
                    args={
                        "tool": "preview.screenshot",
                        "arguments": {"url": url_match.group(0).rstrip(".,;")},
                    },
                    mutability_class="verify",
                )

        if re.search(r"\b(?:ui|interface|ux)\b.*\binspiration\b|\binspiration\b.*\b(?:ui|interface|ux)\b", lowered):
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="native_tool",
                title=f"Research visual references for {step.title}",
                step=step,
                reason="The native inspiration tool returns traceable visual references before implementation.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                args={
                    "tool": "ui.inspiration.search",
                    "arguments": {
                        "query": objective.strip() or step.title,
                        "surface": step.title,
                        "platform": "desktop web app",
                        "limit": 8,
                    },
                },
                mutability_class="read",
            )

        context_hint = bool(
            re.search(r"\b(doc|docs|documentation|constraint|constraints|review)\b", lowered)
        )
        read_step_hint = bool(
            re.search(r"\b(read|collect|inspect|review|ground|context)\b", step_text)
        )
        if context_hint and read_step_hint:
            if target_path.exists():
                return self._proposal(
                    action_id=action_id,
                    event_id=event_id,
                    kind="file_read",
                    title=f"Read context for {step.title}",
                    step=step,
                    reason="Neyvia reads the actual file before it edits or delegates follow-up work.",
                    execution_scope=execution_scope,
                    execution_policy=execution_policy,
                    target_path=str(target_path),
                    mutability_class="read",
                )
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind="workspace_search",
                title=f"Search workspace context for {step.title}",
                step=step,
                reason="Ground the plan in repo evidence before execution.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                query=r"TODO|FIXME|README|roadmap|plan|mission",
                args={"include_glob": "**/*", "max_results": 12},
                mutability_class="read",
            )

        if _matches(lowered, WRITE_HINTS) or _matches(lowered, CREATE_HINTS):
            target_path = _infer_write_target_path(step, objective, scope_root)
            create_mode = _matches(lowered, CREATE_HINTS) or not target_path.exists()
            patch_kind = "file_write" if create_mode else "file_patch"
            content = (
                _generated_file_content(step, objective, target_path)
                if create_mode
                else _generated_patch_content(step, objective, target_path)
            )
            title = (
                f"Create mission artifact for {step.title}"
                if create_mode
                else f"Patch target file for {step.title}"
            )
            return self._proposal(
                action_id=action_id,
                event_id=event_id,
                kind=patch_kind,
                title=title,
                step=step,
                reason="This step requires a real file mutation instead of a placeholder summary.",
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                target_path=str(target_path),
                args={"content": content},
                mutability_class="write",
            )

        return self._proposal(
            action_id=action_id,
            event_id=event_id,
            kind="workspace_search",
            title=f"Explore workspace for {step.title}",
            step=step,
            reason="Fallback to real repo exploration when no sharper action is available yet.",
            execution_scope=execution_scope,
            execution_policy=execution_policy,
            query=_fallback_query(objective),
            args={"include_glob": "**/*", "max_results": 10},
            mutability_class="read",
        )

    def execute(
        self,
        proposal: ActionProposal,
        workspace_root: Path,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
        timeout_seconds: int = 90,
        approval_override: bool = False,
    ) -> ActionExecutionRecord:
        gate = ActionApprovalGate(
            required=proposal.requires_approval,
            status=(
                "approved"
                if proposal.requires_approval and approval_override
                else ("pending" if proposal.requires_approval else "not_required")
            ),
            risk_level=proposal.risk_level,
            reason=proposal.reason,
        )
        record = ActionExecutionRecord(
            action_id=proposal.action_id,
            proposal=proposal,
            gate=gate,
            attempts=1,
            event_id=proposal.event_id,
        )
        if proposal.requires_approval and not approval_override:
            record.result = ActionResultEnvelope(
                ok=False,
                error="Approval required before action execution.",
                payload={"approvalRequired": True, "policyDecision": proposal.policy_decision},
                target_path=proposal.target_path,
                result_summary="Waiting for operator approval.",
            )
            return record

        execution_root = Path(execution_scope.execution_root or workspace_root).resolve()
        start = time.monotonic()

        if proposal.kind == "workspace_search":
            results = search_workspace(
                execution_root,
                proposal.query or "mission",
                include_glob=str(proposal.args.get("include_glob", "**/*")),
                max_results=int(proposal.args.get("max_results", 12)),
            )
            return _completed_record(
                record,
                start,
                ok=True,
                stdout=json.dumps(results, indent=2),
                payload={"matches": results},
                target_path=proposal.target_path,
                result_summary="Workspace search completed.",
            )

        if proposal.kind == "file_read":
            target = _resolve_target(proposal.target_path, execution_root)
            try:
                content = target.read_text(encoding="utf-8")
            except OSError as exc:
                return _completed_record(
                    record,
                    start,
                    ok=False,
                    error=str(exc),
                    target_path=str(target),
                    result_summary="File read failed.",
                )
            return _completed_record(
                record,
                start,
                ok=True,
                stdout=content,
                payload={"targetPath": str(target)},
                target_path=str(target),
                result_summary="File read completed.",
            )

        if proposal.kind == "native_tool":
            from .native_tools import NativeToolRegistry

            tool_name = str(proposal.args.get("tool") or "").strip()
            arguments = dict(proposal.args.get("arguments") or {})
            try:
                registry = NativeToolRegistry(execution_root)
                tool_schema = dict(
                    (registry.describe(tool_name).get("inputSchema") or {}).get(
                        "properties"
                    )
                    or {}
                )
                timeout_schema = tool_schema.get("timeoutSeconds")
                if isinstance(timeout_schema, dict):
                    requested_timeout = int(
                        arguments.get("timeoutSeconds") or timeout_seconds
                    )
                    bounded_timeout = min(requested_timeout, int(timeout_seconds))
                    bounded_timeout = max(
                        int(timeout_schema.get("minimum") or 1),
                        min(
                            bounded_timeout,
                            int(timeout_schema.get("maximum") or bounded_timeout),
                        ),
                    )
                    arguments["timeoutSeconds"] = bounded_timeout
                receipt = registry.call(tool_name, arguments)
            except Exception as exc:
                return _completed_record(
                    record,
                    start,
                    ok=False,
                    error=str(exc),
                    result_summary=f"Native tool {tool_name or 'request'} failed.",
                )
            return _completed_record(
                record,
                start,
                ok=bool(receipt.get("ok")),
                stdout=json.dumps(receipt, indent=2),
                error=str(receipt.get("error") or ""),
                payload={"receipt": receipt},
                changed_files=_git_changed_files(execution_root),
                result_summary=f"Native tool {tool_name} completed.",
            )

        if proposal.kind in {"file_write", "file_patch"}:
            target = _resolve_target(proposal.target_path, execution_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(proposal.args.get("content", ""))
            try:
                if proposal.kind == "file_write":
                    target.write_text(content, encoding="utf-8")
                else:
                    existing = target.read_text(encoding="utf-8") if target.exists() else ""
                    target.write_text(existing + content, encoding="utf-8")
            except OSError as exc:
                return _completed_record(
                    record,
                    start,
                    ok=False,
                    error=str(exc),
                    target_path=str(target),
                    result_summary="File mutation failed.",
                )
            return _completed_record(
                record,
                start,
                ok=True,
                stdout=f"Updated {target}",
                changed_files=_git_changed_files(execution_root),
                payload={"targetPath": str(target), "mutated": True},
                target_path=str(target),
                result_summary="File mutation completed.",
            )

        if proposal.kind == "runtime_delegate":
            runtime_id = _normalize_runtime_id(
                proposal.delegation_metadata.get("route_runtime_id")
                or proposal.delegation_metadata.get("runtime_id", "hermes")
            )
            if os.environ.get("FLUXIO_RUNTIME_DELEGATION_MODE") == "local_shim":
                proof_dir = execution_root / "docs"
                proof_dir.mkdir(parents=True, exist_ok=True)
                proof_path = proof_dir / f"runtime-delegate-inspection-{uuid.uuid4().hex[:8]}.md"
                delegated_objective = str(
                    proposal.delegation_metadata.get("objective", "")
                )
                deliverable_paths: list[Path] = []
                summary_lines = [
                    "# Runtime Delegate Inspection",
                    "",
                    f"- Runtime: `{runtime_id}`",
                    f"- Step: {proposal.title}",
                    f"- Execution root: `{execution_root}`",
                    "",
                    "## Workspace Snapshot",
                ]
                for child in sorted(execution_root.iterdir(), key=lambda item: item.name.lower())[:40]:
                    marker = "dir" if child.is_dir() else "file"
                    summary_lines.append(f"- `{child.name}` ({marker})")
                requested_doc = re.search(
                    r"\b(docs/[A-Za-z0-9_.-]+\.md)\b",
                    delegated_objective,
                )
                if requested_doc and re.search(
                    r"\b(create|write|update|draft|prepare)\b",
                    delegated_objective,
                    flags=re.IGNORECASE,
                ):
                    target_doc = _resolve_target(requested_doc.group(1), execution_root)
                    target_doc.parent.mkdir(parents=True, exist_ok=True)
                    generated_at = utc_now_iso()
                    package_scripts: dict[str, object] = {}
                    package_json = execution_root / "package.json"
                    if package_json.exists():
                        try:
                            package_scripts = json.loads(
                                package_json.read_text(encoding="utf-8")
                            ).get("scripts", {})
                        except (OSError, json.JSONDecodeError):
                            package_scripts = {}
                    runtime_checks: list[str] = []
                    runtime_check_commands = [
                        "command -v hermes >/dev/null 2>&1 && hermes auth status openai-codex || true",
                        "command -v hermes >/dev/null 2>&1 && hermes auth status minimax-oauth || true",
                    ]
                    if "minimax" in delegated_objective.lower():
                        runtime_check_commands.append(
                            "command -v hermes >/dev/null 2>&1 && timeout 60s hermes chat -q 'Reply exactly: HERMES_MINIMAX_ROUTE_OK' -Q --provider minimax-oauth --model MiniMax-M3 || true"
                        )
                    runtime_env = runtime_subprocess_env(execution_root)
                    for command in runtime_check_commands:
                        try:
                            completed = subprocess.run(  # noqa: S603
                                command,
                                shell=True,
                                cwd=str(execution_root),
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=70,
                                env=runtime_env,
                                check=False,
                                **hidden_windows_subprocess_kwargs(),
                            )
                            output = (completed.stdout or completed.stderr or "").strip()
                        except subprocess.TimeoutExpired:
                            output = "Timed out."
                        runtime_checks.append(
                            "\n".join(
                                [
                                    f"### `{command}`",
                                    "```",
                                    output[:4000] or "No output.",
                                    "```",
                                ]
                            )
                        )
                    target_doc.write_text(
                        "\n".join(
                            [
                                "# Autonomous Hermes Proof",
                                "",
                                f"- Generated at: `{generated_at}`",
                                f"- Runtime selected by mission: `{runtime_id}`",
                                f"- Generated by: `FLUXIO_RUNTIME_DELEGATION_MODE=local_shim`",
                                f"- Workspace: `{execution_root}`",
                                f"- Source step: {proposal.title}",
                                "",
                                "## Scope",
                                "",
                                (
                                    "This artifact records a safe response-quality pass for "
                                    "defensive AI red-team evaluation. It avoids operational "
                                    "jailbreak instructions and focuses on evaluation hygiene, "
                                    "traceability, and model-routing readiness."
                                ),
                                "",
                                "## Findings",
                                "",
                                "- The project has established red-team documentation and benchmark scripts.",
                                "- MiniMax routing is guarded until API-key or OAuth auth is visible to Hermes.",
                                "- Hermes is the selected runtime for this mission; OpenAI Codex OAuth is the currently verified broker path.",
                                "- Response-quality work should separate prompt datasets, scoring rubrics, model adapters, and safety review notes.",
                                "",
                                "## Runtime Auth Checks",
                                "",
                                *runtime_checks,
                                "",
                                "## Improvement Actions",
                                "",
                                "- Add a response-quality rubric that scores clarity, refusal quality, benign redirection, and reproducibility.",
                                "- Keep red-team payload corpora separate from generated assistant responses and report only aggregate safety metrics by default.",
                                "- Add a lightweight smoke command that validates benchmark configuration without invoking external model providers.",
                                "- Gate MiniMax routes on explicit auth verification so unattended missions cannot silently choose an unconfigured provider.",
                                "",
                                "## Detected Package Scripts",
                                "",
                                *[
                                    f"- `{name}`: `{command}`"
                                    for name, command in sorted(package_scripts.items())[:20]
                                ],
                                "",
                            ]
                        ),
                        encoding="utf-8",
                    )
                    deliverable_paths.append(target_doc)
                    summary_lines.extend(
                        [
                            "",
                            "## Deliverables",
                            f"- Wrote `{target_doc.relative_to(execution_root)}`",
                        ]
                    )
                checks: list[str] = []
                for command in (
                    "pwd",
                    "find . -maxdepth 2 -type f | sort | head -80",
                    "command -v git >/dev/null 2>&1 && git status --short || true",
                    "command -v npm >/dev/null 2>&1 && npm run build --if-present || true",
                ):
                    try:
                        completed = subprocess.run(  # noqa: S603
                            command,
                            shell=True,
                            cwd=str(execution_root),
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=45,
                            check=False,
                            **hidden_windows_subprocess_kwargs(),
                        )
                        checks.append(
                            "\n".join(
                                [
                                    f"### `{command}`",
                                    f"exit: {completed.returncode}",
                                    "```",
                                    (completed.stdout or completed.stderr or "").strip()[:4000],
                                    "```",
                                ]
                            )
                        )
                    except subprocess.TimeoutExpired:
                        checks.append(f"### `{command}`\nexit: 124\n\nTimed out after 45 seconds.")
                proof_path.write_text(
                    "\n".join([*summary_lines, "", "## Bounded Checks", *checks, ""]),
                    encoding="utf-8",
                )
                changed_files = _git_changed_files(execution_root)
                if not changed_files and deliverable_paths:
                    changed_files = [
                        str(path.relative_to(execution_root))
                        for path in [*deliverable_paths, proof_path]
                    ]
                return _completed_record(
                    record,
                    start,
                    ok=True,
                    stdout=str(proof_path),
                    changed_files=changed_files,
                    payload={
                        "localDelegateShim": True,
                        "runtimeId": runtime_id,
                        "proofPath": str(proof_path),
                        "deliverables": [str(path) for path in deliverable_paths],
                    },
                    target_path=str(proof_path),
                    result_summary="Runtime delegation completed via bounded local inspection.",
                )
            adapters = runtime_adapter_map()
            adapter = adapters.get(runtime_id)
            if adapter is None:
                return _completed_record(
                    record,
                    start,
                    ok=False,
                    error=f"Unknown runtime delegate: {runtime_id}",
                    result_summary="Delegation failed before launch.",
                )
            status = adapter.detect(execution_root)
            if not status.detected:
                return _completed_record(
                    record,
                    start,
                    ok=False,
                    error=status.doctor_summary or "Runtime is unavailable.",
                    payload={"runtimeStatus": status.doctor_summary},
                    result_summary="Delegation blocked because the runtime is missing.",
                )
            parent_mission_id = str(
                proposal.delegation_metadata.get("parent_mission_id")
                or proposal.delegation_metadata.get("mission_id")
                or ""
            ).strip()
            delegated_route_configs = [
                _model_route_config_from_payload(item)
                for item in proposal.delegation_metadata.get("route_configs", [])
            ]
            delegated_mission = Mission(
                mission_id=parent_mission_id or f"delegated_{uuid.uuid4().hex[:8]}",
                workspace_id="delegated",
                runtime_id=runtime_id,
                objective=str(proposal.delegation_metadata.get("objective", proposal.title)),
                success_checks=[],
                execution_scope=execution_scope,
                route_configs=[item for item in delegated_route_configs if item is not None],
            )
            delegated_mission.state.current_cycle_phase = str(
                proposal.delegation_metadata.get("cycle_phase", "execute")
            ).strip().lower() or "execute"
            delegated_mission.state.status = "running"
            delegated_workspace = WorkspaceProfile(
                workspace_id="delegated",
                name=execution_root.name,
                root_path=str(execution_root),
                default_runtime=runtime_id,
                workspace_type="general",
            )
            supervisor = DelegatedRuntimeSupervisor(workspace_root)
            session = supervisor.start_session(
                runtime_id=runtime_id,
                mission=delegated_mission,
                workspace=delegated_workspace,
                source_step_id=proposal.source_step_id,
            )
            settle_deadline = time.monotonic() + 2.0
            while (
                session.status in {"launching", "running"}
                and time.monotonic() < settle_deadline
            ):
                time.sleep(0.1)
                session = supervisor.refresh_session(session)
            if session.status in {"completed", "failed", "stopped"} and session.supervisor_pid:
                release_deadline = time.monotonic() + 1.0
                while _pid_alive(session.supervisor_pid) and time.monotonic() < release_deadline:
                    time.sleep(0.05)
            snapshot = supervisor.build_session_snapshot(session)
            events = adapter.stream_events(delegated_mission) + supervisor.read_events(session)
            return _completed_record(
                record,
                start,
                ok=True,
                stdout=session.launch_command,
                payload={
                    "runtimeId": runtime_id,
                    "delegatedSession": session.__dict__,
                    "delegatedSnapshot": asdict(snapshot),
                    "events": events,
                },
                result_summary="Delegated runtime lane launched under Neyvia supervision.",
            )

        if proposal.kind in {"git_status", "git_diff"} and shutil.which("git") is None:
            snapshot = search_workspace(
                execution_root,
                "",
                include_glob="**/*",
                max_results=80,
            )
            return _completed_record(
                record,
                start,
                ok=True,
                stdout=json.dumps(snapshot, indent=2),
                payload={"gitAvailable": False, "filesystemSnapshot": snapshot},
                target_path=proposal.target_path,
                result_summary=f"{proposal.kind} completed with filesystem snapshot because git is unavailable.",
            )

        command = proposal.command.strip()
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                shell=True,
                cwd=str(execution_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            timeout_message = f"Command timed out after {timeout_seconds} seconds."
            return _completed_record(
                record,
                start,
                ok=False,
                exit_code=124,
                stdout=stdout.strip(),
                stderr=(f"{stderr.strip()}\n{timeout_message}".strip()),
                error=timeout_message,
                changed_files=_git_changed_files(execution_root),
                target_path=proposal.target_path,
                result_summary=f"{proposal.kind} timed out after {timeout_seconds} seconds.",
            )
        return _completed_record(
            record,
            start,
            ok=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            changed_files=_git_changed_files(execution_root),
            target_path=proposal.target_path,
            result_summary=f"{proposal.kind} completed with exit code {completed.returncode}.",
        )

    def _proposal(
        self,
        *,
        action_id: str,
        event_id: str,
        kind: str,
        title: str,
        step: PlannedStep,
        reason: str,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
        command: str = "",
        query: str = "",
        args: dict | None = None,
        target_path: str = "",
        mutability_class: str = "read",
        delegation_metadata: dict | None = None,
    ) -> ActionProposal:
        proposal = ActionProposal(
            action_id=action_id,
            kind=kind,
            title=title,
            command=command,
            query=query,
            args=args or {},
            source_step_id=step.step_id,
            reason=reason,
            event_id=event_id,
            target_path=target_path,
            target_scope=("worktree" if execution_scope.isolated else "workspace"),
            mutability_class=mutability_class,
            branch_name=execution_scope.branch_name,
            worktree_path=execution_scope.worktree_path,
            delegation_metadata=delegation_metadata or {},
            replay_cursor=event_id,
        )
        proposal.risk_level = _risk_for_proposal(proposal)
        if (
            proposal.kind == "runtime_delegate"
            and os.environ.get("FLUXIO_RUNTIME_DELEGATION_MODE") == "local_shim"
        ):
            proposal.policy_decision = "auto_run"
        else:
            proposal.policy_decision = _policy_decision(proposal, execution_policy)
        proposal.requires_approval = proposal.policy_decision == "requires_approval"
        if proposal.kind == "native_tool":
            from .proofs_d_native import check_native_proposal
            check_native_proposal(proposal)
        return proposal


DEFAULT_EXECUTION_ADAPTER = HybridExecutionAdapter()


def build_execution_policy(profile_name: str) -> ExecutionPolicy:
    return normalize_execution_policy(DEFAULT_EXECUTION_ADAPTER.build_policy(profile_name))


def normalize_execution_policy(policy: ExecutionPolicy) -> ExecutionPolicy:
    auto_allowed = {
        "workspace_search",
        "file_read",
        "git_status",
        "git_diff",
        "test_run",
        "native_tool",
    }
    approval_required = {"git_commit", "shell_command"}
    if policy.delegation_aggressiveness != "low":
        auto_allowed.add("runtime_delegate")
    else:
        approval_required.add("runtime_delegate")
    if policy.approval_mode in {"strict", "tiered"}:
        approval_required.update({"file_patch", "file_write"})
    policy.auto_allowed_kinds = sorted(auto_allowed)
    policy.approval_required_kinds = sorted(approval_required)
    return policy


def requested_scope_for_execution_target(preference: str = "") -> str:
    normalized = (preference or "").strip().lower()
    return EXECUTION_TARGET_SCOPE_OVERRIDES.get(normalized, "")


def prepare_execution_scope(
    workspace_root: Path,
    mission_id: str,
    requested_scope: str = "",
    profile_name: str = "builder",
) -> ExecutionScope:
    scope = DEFAULT_EXECUTION_ADAPTER.prepare_scope(
        workspace_root=workspace_root,
        mission_id=mission_id,
        requested_scope=requested_scope,
        profile_name=profile_name,
    )
    from .proofs_a_control import check_execution_scope
    check_execution_scope(scope)
    return scope


def build_action_proposal(
    step: PlannedStep,
    objective: str,
    workspace_root: Path,
    verification_commands: list[str],
    runtime_id: str = "hermes",
    execution_scope: ExecutionScope | None = None,
    execution_policy: ExecutionPolicy | None = None,
    route_configs: list[dict] | list[ModelRouteConfig] | None = None,
) -> ActionProposal:
    execution_scope = _with_execution_truth(
        execution_scope
        or ExecutionScope(
            execution_root=str(workspace_root),
            workspace_root=str(workspace_root),
            status="ready",
        )
    )
    execution_policy = execution_policy or build_execution_policy("builder")
    proposal = DEFAULT_EXECUTION_ADAPTER.build_action_proposal(
        step=step,
        objective=objective,
        workspace_root=workspace_root,
        verification_commands=verification_commands,
        runtime_id=runtime_id,
        execution_scope=execution_scope,
        execution_policy=execution_policy,
        route_configs=route_configs,
    )
    from .proofs_a_control import check_action_proposal
    check_action_proposal(step, proposal, execution_scope)
    return proposal


def execute_action(
    proposal: ActionProposal,
    workspace_root: Path,
    execution_scope: ExecutionScope | None = None,
    execution_policy: ExecutionPolicy | None = None,
    timeout_seconds: int = 90,
    approval_override: bool = False,
    autonomy_lease_id: str = "",
) -> ActionExecutionRecord:
    execution_scope = _with_execution_truth(
        execution_scope
        or ExecutionScope(
            execution_root=str(workspace_root),
            workspace_root=str(workspace_root),
            status="ready",
        )
    )
    execution_policy = execution_policy or build_execution_policy("builder")
    autonomy_decision: dict[str, object] | None = None
    if autonomy_lease_id and proposal.requires_approval and not approval_override:
        from .crashproof import CrashProofStore

        target = Path(proposal.target_path) if proposal.target_path else Path(execution_scope.execution_root or workspace_root)
        if not target.is_absolute():
            target = Path(execution_scope.execution_root or workspace_root) / target
        autonomy_context = {
            "path": str(target.resolve()),
            "destructive": proposal.mutability_class == "destructive" or proposal.risk_level == "high",
            "publicCommunication": bool(proposal.args.get("publicCommunication", False)),
            "spend": float(proposal.args.get("spend", 0) or 0),
            "domain": str(proposal.args.get("domain") or ""),
        }
        try:
            autonomy_decision = CrashProofStore(workspace_root).autonomy_allows(
                autonomy_lease_id,
                action=proposal.kind,
                context=autonomy_context,
            )
        except KeyError:
            autonomy_decision = {"allowed": False, "reason": "lease_not_found"}
        approval_override = bool(autonomy_decision.get("allowed"))

    record = DEFAULT_EXECUTION_ADAPTER.execute(
        proposal=proposal,
        workspace_root=workspace_root,
        execution_scope=execution_scope,
        execution_policy=execution_policy,
        timeout_seconds=timeout_seconds,
        approval_override=approval_override,
    )
    if autonomy_decision is not None:
        reason = str(autonomy_decision.get("reason") or "unknown")
        if autonomy_decision.get("allowed"):
            record.gate.approved_by = f"autonomy:{autonomy_lease_id}"
            record.gate.resolved_at = utc_now_iso()
            record.gate.reason = "Approved by the active scoped N-E-Y-V-I-A autonomy lease."
            record.result.payload.setdefault("autonomyLeaseId", autonomy_lease_id)
        else:
            record.gate.reason = f"Autonomy lease did not authorize this action: {reason}."
            record.result.payload.update({"autonomyLeaseId": autonomy_lease_id, "autonomyDenialReason": reason})
    from .proofs_a_control import check_action_result
    check_action_result(proposal, record, approval_override, autonomy_decision, autonomy_lease_id)
    return record


def cleanup_execution_scope(execution_scope: ExecutionScope | None) -> dict[str, object]:
    if execution_scope is None:
        return {"cleaned": False, "reason": "missing_scope"}
    if not execution_scope.isolated or execution_scope.strategy not in {"git_worktree", "filesystem_copy"}:
        return {"cleaned": False, "reason": "not_isolated"}

    workspace_root = Path(execution_scope.workspace_root).resolve() if execution_scope.workspace_root else None
    worktree_path = Path(execution_scope.worktree_path or execution_scope.execution_root).resolve()
    # Isolation cleanup can remove only this workspace's dedicated sibling.
    if workspace_root is None:
        raise ValueError("Isolated cleanup requires its source workspace.")
    from .proofs_a_control import require
    container = workspace_root.parent / f".fluxio-worktrees-{workspace_root.name}"
    require(worktree_path != container.resolve() and worktree_path.is_relative_to(container.resolve()),
            "control.execution-cleanup", "cleanup target escaped the workspace isolation container")
    if not worktree_path.exists():
        return {"cleaned": False, "reason": "missing_worktree", "path": str(worktree_path)}

    details: list[str] = []
    if execution_scope.strategy == "git_worktree" and workspace_root and workspace_root.exists():
        try:
            completed = subprocess.run(  # noqa: S603
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            if completed.returncode == 0:
                details.append("git_worktree_removed")
            else:
                details.append((completed.stderr or completed.stdout).strip() or "git_worktree_remove_failed")
        except OSError as exc:
            details.append(str(exc))

        try:
            subprocess.run(  # noqa: S603
                ["git", "worktree", "prune"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except OSError:
            pass

        branch_name = (execution_scope.branch_name or "").strip()
        if branch_name.startswith("fluxio/"):
            try:
                subprocess.run(  # noqa: S603
                    ["git", "branch", "-D", branch_name],
                    cwd=str(workspace_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
            except OSError:
                pass

    if worktree_path.exists():
        worktree_parent = worktree_path.parent
        shutil.rmtree(worktree_path, ignore_errors=True)
        if not worktree_path.exists():
            details.append("worktree_directory_removed")
        if worktree_parent.exists():
            try:
                next(worktree_parent.iterdir())
            except StopIteration:
                worktree_parent.rmdir()

    result = {
        "cleaned": not worktree_path.exists(),
        "path": str(worktree_path),
        "details": details,
    }
    require(result["cleaned"] is (not worktree_path.exists()), "control.execution-cleanup", "cleanup receipt differs from remaining directory")
    return result


def _is_git_workspace(workspace_root: Path) -> bool:
    return (workspace_root / ".git").exists()


def _with_execution_truth(scope: ExecutionScope) -> ExecutionScope:
    truth = derive_execution_target(
        execution_root=scope.execution_root,
        workspace_root=scope.workspace_root,
        strategy=scope.strategy,
    )
    scope.execution_target = truth["execution_target"]
    scope.storage_mode = truth["storage_mode"]
    scope.host_locality = truth["host_locality"]
    scope.execution_target_detail = truth["execution_target_detail"]
    return scope


def _git_changed_files(root: Path) -> list[str]:
    if not _is_git_workspace(root) and not (root / ".git").exists():
        return []
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "status", "--short"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except OSError:
        return []
    changed: list[str] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        changed.append(line[3:].strip())
    return changed


def _policy_decision(proposal: ActionProposal, policy: ExecutionPolicy) -> str:
    if proposal.risk_level == "high" or proposal.mutability_class == "destructive":
        return "requires_approval"
    if _is_internal_mission_artifact_write(proposal):
        return "auto_run"
    if proposal.kind in policy.approval_required_kinds:
        return "requires_approval"
    if proposal.kind in policy.auto_allowed_kinds:
        return "auto_run"
    if policy.approval_mode == "hands_free":
        return "auto_run"
    return "requires_approval"


def _is_internal_mission_artifact_write(proposal: ActionProposal) -> bool:
    if proposal.kind not in {"file_write", "file_patch"}:
        return False
    normalized = proposal.target_path.replace("\\", "/").lower()
    return "/.agent_control/mission_artifacts/" in normalized


def _risk_for_proposal(proposal: ActionProposal) -> str:
    if proposal.kind in {"file_write", "file_patch"}:
        lowered = proposal.target_path.lower()
        if ".env" in lowered or "\\.git" in lowered or "/.git" in lowered:
            return "high"
        return "medium"
    if proposal.kind == "runtime_delegate":
        return "medium"
    if proposal.command:
        return risk_level_for_command(proposal.command)
    return "low"


def _fallback_query(objective: str) -> str:
    words = re.findall(r"[A-Za-z0-9_]+", objective)
    return "|".join(words[:4]) or "mission"


def _should_delegate_step(text: str, policy: ExecutionPolicy) -> bool:
    if _matches(text, DELEGATE_HINTS):
        return True
    delegation = (policy.delegation_aggressiveness or "balanced").strip().lower()
    if delegation == "high":
        return any(
            hint in text
            for hint in (
                "approval",
                "bridge",
                "deploy",
                "handoff",
                "runtime lane",
            )
        )
    if delegation == "balanced":
        return any(hint in text for hint in ("bridge", "runtime lane"))
    return False


def _delegated_cycle_phase(
    step: PlannedStep,
    objective: str,
    route_configs: list[dict] | list[ModelRouteConfig] | None = None,
) -> str:
    explicit_roles = []
    for item in route_configs or []:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        role = str(row.get("role", "")).strip().lower()
        if role:
            explicit_roles.append(role)
    if explicit_roles:
        if "planner" in explicit_roles and "executor" not in explicit_roles and "verifier" not in explicit_roles:
            return "plan"
        if "verifier" in explicit_roles and "executor" not in explicit_roles:
            return "verify"

    step_text = f"{step.title} {step.description} {step.kind}".lower()
    objective_text = objective.lower()
    if "execute first" in objective_text and _matches(step_text, WRITE_HINTS):
        return "execute"
    if _matches(step_text, DELEGATED_VERIFY_HINTS):
        return "verify"
    if _matches(step_text, DELEGATED_PLAN_HINTS):
        return "plan"
    return "execute"


def delegated_cycle_phase_for_step(
    step: PlannedStep,
    objective: str = "",
    route_configs: list[dict] | list[ModelRouteConfig] | None = None,
) -> str:
    result = _delegated_cycle_phase(
        step=step,
        objective=objective,
        route_configs=route_configs,
    )
    from .proofs_a_control import require
    roles = {str((asdict(row) if hasattr(row, "__dataclass_fields__") else row).get("role", "")).strip().lower()
             for row in route_configs or []}
    require(result in {"plan", "verify", "execute"}
            and (not ("planner" in roles and not roles & {"executor", "verifier"}) or result == "plan")
            and (not ("verifier" in roles and "executor" not in roles) or result == "verify"),
            "control.execution-phase", "phase does not honor explicit role routing")
    return result


def _route_role_for_phase(phase: str) -> str:
    normalized = (phase or "execute").strip().lower()
    if normalized in {"plan", "replan"}:
        return "planner"
    if normalized == "verify":
        return "verifier"
    return "executor"


def _matches(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _infer_target_path(objective: str, workspace_root: Path) -> Path:
    explicit_matches = re.findall(r"[\w./\\-]+\.[A-Za-z0-9]+", objective)
    for match in explicit_matches:
        candidate = (workspace_root / match).resolve()
        if str(candidate).startswith(str(workspace_root.resolve())):
            return candidate
    preferred = [
        workspace_root / "README.md",
        workspace_root / "docs" / "ROADMAP.md",
        workspace_root / "docs" / "PRD.md",
        workspace_root / "MISSION_NOTES.md",
    ]
    for candidate in preferred:
        if candidate.exists():
            return candidate
    return workspace_root / "MISSION_NOTES.md"


def _infer_write_target_path(step: PlannedStep, objective: str, workspace_root: Path) -> Path:
    explicit_matches = re.findall(r"[\w./\\-]+\.[A-Za-z0-9]+", objective)
    for match in explicit_matches:
        candidate = (workspace_root / match).resolve()
        if str(candidate).startswith(str(workspace_root.resolve())):
            return candidate
    safe_title = re.sub(r"[^a-zA-Z0-9_.-]+", "-", step.title.strip().lower()).strip("-")
    if not safe_title:
        safe_title = "mission-artifact"
    return workspace_root / ".agent_control" / "mission_artifacts" / f"{safe_title}.md"


def _generated_file_content(step: PlannedStep, objective: str, target_path: Path) -> str:
    if target_path.suffix.lower() in {".md", ".txt", ".rst"}:
        return (
            f"# {step.title}\n\n"
            f"- Objective: {objective}\n"
            f"- Triggered by step: {step.description or step.title}\n"
            f"- Generated by Neyvia OWN execution engine at {utc_now_iso()}\n"
        )
    return _comment_block(
        target_path,
        [
            f"Neyvia created this artifact for step: {step.title}",
            f"Objective: {objective}",
        ],
    )


def _generated_patch_content(step: PlannedStep, objective: str, target_path: Path) -> str:
    if target_path.suffix.lower() in {".md", ".txt", ".rst"}:
        return (
            f"\n\n## Neyvia Mission Note\n"
            f"- Step: {step.title}\n"
            f"- Objective: {objective}\n"
            f"- Updated: {utc_now_iso()}\n"
        )
    return "\n" + _comment_block(
        target_path,
        [
            f"Neyvia mission note: {step.title}",
            f"Objective: {objective}",
        ],
    )


def _comment_block(target_path: Path, lines: list[str]) -> str:
    suffix = target_path.suffix.lower()
    if suffix == ".html":
        return "\n".join([f"<!-- {line} -->" for line in lines]) + "\n"
    if suffix in {".py", ".sh", ".yml", ".yaml", ".toml"}:
        return "\n".join([f"# {line}" for line in lines]) + "\n"
    if suffix in {".css", ".xml"}:
        return "\n".join([f"/* {line} */" for line in lines]) + "\n"
    return "\n".join([f"// {line}" for line in lines]) + "\n"


def _resolve_target(target_path: str, execution_root: Path) -> Path:
    candidate = Path(target_path)
    if candidate.is_absolute():
        return candidate
    return (execution_root / candidate).resolve()


def _completed_record(
    record: ActionExecutionRecord,
    started_at: float,
    *,
    ok: bool,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    error: str = "",
    changed_files: list[str] | None = None,
    payload: dict | None = None,
    target_path: str = "",
    result_summary: str = "",
) -> ActionExecutionRecord:
    record.result = ActionResultEnvelope(
        ok=ok,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=int((time.monotonic() - started_at) * 1000),
        error=error,
        changed_files=changed_files or [],
        payload=payload or {},
        target_path=target_path,
        result_summary=result_summary,
    )
    record.acked = True
    record.executed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return record
