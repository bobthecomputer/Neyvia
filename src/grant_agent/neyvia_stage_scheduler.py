"""Execute compiled NEYVIA/1 stages with best-checkpoint rollback receipts.

Matrix gap #4: plan once via orchestration_language.compile(), run stages until
interrupt. Does not invent a new DSL — only dispatches compiled steps.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .orchestration_language import NEYVIA_PLAN_SCHEMA, compile_neyvia_program


STAGE_EXEC_SCHEMA = "neyvia.stage_execution.v1"
ROLLBACK_RECEIPT_SCHEMA = "neyvia.checkpoint_rollback.v1"
CHECKPOINT_SCHEMA = "neyvia.stage_checkpoint.v1"

StepHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

# Actions that must stay sequential even inside a parallelSafe stage.
_SERIAL_ACTIONS = frozenset({"checkpoint", "verify", "repair"})
_BUILTIN_ACTIONS = frozenset({"checkpoint", "verify", "repair", "tool"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class StepOutcome:
    step_id: str
    action: str
    ok: bool
    verification_score: float | None = None
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    rolled_back: bool = False
    rollback_receipt_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_compiled_plan(plan_or_source: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(plan_or_source, str):
        return compile_neyvia_program(plan_or_source)
    if not isinstance(plan_or_source, dict):
        raise TypeError("plan must be a compiled dict or NEYVIA/1 source string")
    if str(plan_or_source.get("schema") or "") != NEYVIA_PLAN_SCHEMA:
        raise ValueError(f"Expected {NEYVIA_PLAN_SCHEMA}, got {plan_or_source.get('schema')!r}")
    if not plan_or_source.get("executionStages") or not plan_or_source.get("steps"):
        raise ValueError("Compiled plan is missing executionStages or steps")
    if not plan_or_source.get("planHash"):
        raise ValueError("Compiled plan is missing planHash")
    return plan_or_source


def _tool_is_mutating(step: dict[str, Any], tool_name: str, surface: Any | None) -> bool:
    risk = str(step.get("risk") or "").strip().lower()
    if risk in {"workspace_write", "artifact_write", "external_write", "destructive", "write"}:
        return True
    envelope = step.get("permissionEnvelope") if isinstance(step.get("permissionEnvelope"), dict) else {}
    if bool(envelope.get("approvalRequired")):
        return True
    mutability = str(envelope.get("mutability") or "").strip().lower()
    if mutability in {"workspace_write", "artifact_write", "external_write", "destructive", "write"}:
        return True
    if surface is not None and hasattr(surface, "describe"):
        try:
            described = surface.describe(tool_name)
            annotations = described.get("annotations") if isinstance(described, dict) else {}
            if isinstance(annotations, dict):
                if "requiresApproval" in annotations:
                    return bool(annotations.get("requiresApproval"))
                if bool(annotations.get("destructiveHint")):
                    return True
                if "readOnlyHint" in annotations:
                    return not bool(annotations.get("readOnlyHint"))
        except Exception:
            pass
    if tool_name.startswith("ui.") and tool_name in {"ui.do", "ui.observe"}:
        return True
    if tool_name == "mcp.call":
        return True
    return False


def build_progressive_step_handler(
    root: str | Path,
    *,
    progressive: Any | None = None,
    ui: Any | None = None,
    broker: Any | None = None,
    approved_mutations: bool = False,
    approval_id: str = "",
    autonomy_policy_path: str | Path | None = None,
) -> StepHandler:
    """Route tool steps through ProgressiveToolSurface / ui.* / mcp_broker when available.

    Read-only tools auto-run. Mutating tools stay approval-gated unless approved_mutations=True
    (or the step/context already carries approved=True).
    """
    root_path = Path(root)
    surface = progressive
    ui_surface = ui
    mcp_broker = broker

    def _ensure_surface() -> Any:
        nonlocal surface, ui_surface, mcp_broker
        if surface is not None:
            return surface
        from .progressive_tools import ProgressiveToolSurface

        surface = ProgressiveToolSurface()
        try:
            from .ui_tools import default_ui_surface, register_with_progressive_surface as register_ui

            ui_surface = ui_surface or default_ui_surface()
            register_ui(surface, ui_surface)
        except Exception:
            pass
        try:
            from .mcp_broker import McpOutboundBroker, register_with_progressive_surface as register_mcp

            mcp_broker = mcp_broker or McpOutboundBroker(
                root_path,
                include_default_demo=False,
            )
            register_mcp(surface, mcp_broker)
        except Exception:
            pass
        try:
            from .capability_service import (
                CapabilityService,
                register_with_progressive_surface as register_capabilities,
            )

            register_capabilities(
                surface,
                CapabilityService(root_path, include_default_mcp_demo=False),
            )
        except Exception:
            pass
        return surface

    def handler(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(step.get("action") or "")
        if action != "tool":
            return default_step_handler(step, context)

        tool_name = str(step.get("tool") or "").strip()
        args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        args = dict(args)
        if not tool_name:
            return {
                "ok": False,
                "summary": f"Tool step {step.get('step_id')} missing tool name",
                "metadata": {"deferred": False, "error": "missing_tool"},
            }

        approved = bool(
            approved_mutations
            or context.get("approved")
            or context.get("approved_mutations")
            or args.pop("approved", False)
        )
        approval = str(
            approval_id
            or context.get("approval_id")
            or context.get("approvalId")
            or args.pop("approvalId", "")
            or args.pop("approval_id", "")
            or ""
        )

        # Direct ui.* path (keeps attached page / graph identity).
        if tool_name.startswith("ui."):
            try:
                from .ui_tools import default_ui_surface

                local_ui = ui_surface or default_ui_surface()
            except Exception as exc:
                return {
                    "ok": False,
                    "summary": f"ui tools unavailable: {exc}",
                    "metadata": {"tool": tool_name, "error": str(exc)},
                }
            if _tool_is_mutating(step, tool_name, None) and not approved:
                return {
                    "ok": False,
                    "summary": f"Approval required for mutating tool {tool_name}",
                    "metadata": {
                        "approval_required": True,
                        "tool": tool_name,
                        "args": args,
                    },
                }
            result = local_ui.call(tool_name, args)
            ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
            return {
                "ok": ok,
                "summary": str((result or {}).get("text") or (result or {}).get("status") or tool_name)[:400],
                "artifacts": [
                    str(p)
                    for p in [((result or {}).get("detail") or {}).get("path")]
                    if p
                ],
                "metadata": {"tool": tool_name, "result": result, "routed": "ui"},
            }

        # Direct mcp.<server>.<tool> or mcp.call progressive entry.
        if tool_name.startswith("mcp.") and tool_name not in {
            "mcp.servers",
            "mcp.search",
            "mcp.describe",
            "mcp.call",
        }:
            try:
                from .mcp_broker import McpOutboundBroker

                local_broker = mcp_broker or McpOutboundBroker(root_path)
            except Exception as exc:
                return {
                    "ok": False,
                    "summary": f"mcp broker unavailable: {exc}",
                    "metadata": {"tool": tool_name, "error": str(exc)},
                }
            receipt = local_broker.call(
                tool_name,
                arguments=args,
                name=tool_name,
                approved=approved,
                approval_id=approval,
                mission_id=str(context.get("mission_id") or context.get("missionId") or ""),
            )
            return {
                "ok": bool(receipt.get("ok")),
                "summary": f"{tool_name} status={receipt.get('status')}",
                "artifacts": [str(receipt.get("receipt_path") or "")] if receipt.get("receipt_path") else [],
                "metadata": {"tool": tool_name, "result": receipt, "routed": "mcp_broker"},
            }

        prog = _ensure_surface()
        mutating = _tool_is_mutating(step, tool_name, prog)
        if mutating and not approved:
            return {
                "ok": False,
                "summary": f"Approval required for mutating tool {tool_name}",
                "metadata": {
                    "approval_required": True,
                    "tool": tool_name,
                    "args": args,
                },
            }

        call_args = dict(args)
        if tool_name == "mcp.call":
            call_args.setdefault("approved", approved)
            if approval:
                call_args.setdefault("approvalId", approval)
            call_args.setdefault(
                "missionId",
                str(context.get("mission_id") or context.get("missionId") or ""),
            )

        try:
            result = prog.call(tool_name, call_args)
        except KeyError:
            return {
                "ok": False,
                "summary": f"Unknown tool {tool_name} (not deferred)",
                "metadata": {"tool": tool_name, "args": args, "error": "unknown_tool"},
            }
        except Exception as exc:
            return {
                "ok": False,
                "summary": f"Tool {tool_name} failed: {exc}",
                "metadata": {"tool": tool_name, "args": args, "error": str(exc)},
            }

        ok = True
        if isinstance(result, dict):
            if "ok" in result:
                ok = bool(result.get("ok"))
            status = str(result.get("status") or "")
            if status in {"approval_required", "auth_required", "failed", "stale_state"}:
                ok = False
        return {
            "ok": ok,
            "summary": f"Tool {tool_name} ok={ok}",
            "metadata": {"tool": tool_name, "result": result, "routed": "progressive"},
        }

    def durable_handler(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if str(step.get("action") or "") != "tool":
            return handler(step, context)
        from .semantic_dispatch import dispatch_operation
        return dispatch_operation(root_path, step, context, handler,
                                  autonomy_policy_path=Path(autonomy_policy_path) if autonomy_policy_path else None)

    return durable_handler


def default_step_handler(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Builtin handler for checkpoint/verify/repair and non-tool actions.

    Tool steps should go through build_progressive_step_handler (scheduler default).
    """
    action = str(step.get("action") or "")
    args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
    score = args.get("verificationScore", args.get("verification_score"))
    if action == "checkpoint":
        return {
            "ok": True,
            "summary": f"Checkpoint recorded for {step.get('step_id')}",
            "verification_score": context.get("verification_score"),
            "metadata": {"kind": "checkpoint"},
        }
    if action == "verify":
        normalized = 1.0 if score is None else max(0.0, min(1.0, float(score)))
        return {
            "ok": normalized >= 0.5,
            "summary": f"Verify {step.get('step_id')} score={normalized:.3f}",
            "verification_score": normalized,
            "metadata": {"command": step.get("command") or "", "acceptance": step.get("acceptance") or ""},
        }
    if action == "repair":
        if score is None:
            prior = float(context.get("verification_score") or 0.0)
            normalized = max(0.0, prior - 0.1)
        else:
            normalized = max(0.0, min(1.0, float(score)))
        return {
            "ok": True,
            "summary": f"Repair {step.get('step_id')} score={normalized:.3f}",
            "verification_score": normalized,
            "metadata": {"kind": "repair"},
        }
    if action == "tool":
        # Explicit fallback only when callers force default_step_handler for tools.
        return {
            "ok": False,
            "summary": f"No progressive handler for tool step {step.get('tool') or step.get('step_id')}",
            "metadata": {"deferred": False, "tool": step.get("tool") or "", "args": args, "error": "no_handler"},
        }
    return {
        "ok": False,
        "summary": (
            f"No handler registered for executable action {action!r} on step "
            f"{step.get('step_id')}"
        ),
        "metadata": {
            "action": action,
            "args": args,
            "deferred": False,
            "error": "no_handler",
            "registeredActions": sorted(_BUILTIN_ACTIONS),
        },
    }


class NeyviaStageScheduler:
    """Run compiled executionStages in order with checkpoint rollback receipts."""

    def __init__(
        self,
        root: str | Path,
        *,
        step_handler: StepHandler | None = None,
        mission_id: str = "",
        max_workers: int = 8,
    ) -> None:
        self.root = Path(root)
        self.step_handler = step_handler or build_progressive_step_handler(self.root)
        self.mission_id = mission_id or "mission"
        self.max_workers = max(1, int(max_workers))
        self.receipt_dir = (
            self.root / ".agent_control" / "mission_artifacts" / "context_microkernel" / "stage_exec"
        )

    def execute(
        self,
        plan_or_source: dict[str, Any] | str,
        *,
        initial_context: dict[str, Any] | None = None,
        stop_on_failure: bool = True,
    ) -> dict[str, Any]:
        plan = normalize_compiled_plan(plan_or_source)
        step_map = {str(step["step_id"]): step for step in plan.get("steps") or []}
        context: dict[str, Any] = {
            "planHash": plan["planHash"],
            "objective": plan.get("objective") or "",
            "verification_score": 0.0,
            "best_verification_score": 0.0,
            "completed_step_ids": [],
            "workspace": {},
            "mission_id": self.mission_id,
            **dict(initial_context or {}),
        }
        checkpoints: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        rollbacks: list[dict[str, Any]] = []
        interrupted = False
        interrupt_reason = ""
        repairs_used = 0
        max_repairs = int((plan.get("budget") or {}).get("maxRepairs") or 0)
        parallel_stages_run = 0

        for stage in plan.get("executionStages") or []:
            stage_index = int(stage.get("index") or 0)
            step_ids = [str(item) for item in (stage.get("stepIds") or [])]
            steps = []
            for step_id in step_ids:
                step = step_map.get(step_id)
                if step is None:
                    interrupted = True
                    interrupt_reason = f"unknown_step:{step_id}"
                    break
                steps.append(step)
            if interrupted:
                break

            use_parallel = bool(stage.get("parallelSafe")) and len(steps) > 1
            if use_parallel and any(str(s.get("action") or "") in _SERIAL_ACTIONS for s in steps):
                use_parallel = False

            if use_parallel:
                parallel_stages_run += 1
                stage_results = self._run_parallel_steps(steps, context)
                # Deterministic merge in compiled stepIds order.
                for step in steps:
                    step_id = str(step["step_id"])
                    raw = stage_results.get(step_id) or {
                        "ok": False,
                        "summary": f"missing parallel result for {step_id}",
                        "metadata": {"error": "missing_parallel_result"},
                    }
                    action = str(step.get("action") or "")
                    pre_score = float(context.get("verification_score") or 0.0)
                    outcome, context, rollback, interrupted_now, reason, repairs_used = self._apply_outcome(
                        plan=plan,
                        step=step,
                        raw=raw,
                        context=context,
                        checkpoints=checkpoints,
                        stage_index=stage_index,
                        pre_score=pre_score,
                        repairs_used=repairs_used,
                        max_repairs=max_repairs,
                        stop_on_failure=stop_on_failure,
                    )
                    outcomes.append(outcome.as_dict())
                    if rollback:
                        rollbacks.append(rollback)
                    if interrupted_now:
                        interrupted = True
                        interrupt_reason = reason
                        break
            else:
                for step in steps:
                    step_id = str(step["step_id"])
                    action = str(step.get("action") or "")
                    if action == "repair" and max_repairs and repairs_used >= max_repairs:
                        interrupted = True
                        interrupt_reason = "max_repairs_exhausted"
                        break
                    pre_score = float(context.get("verification_score") or 0.0)
                    raw = self.step_handler(step, dict(context))
                    outcome, context, rollback, interrupted_now, reason, repairs_used = self._apply_outcome(
                        plan=plan,
                        step=step,
                        raw=raw,
                        context=context,
                        checkpoints=checkpoints,
                        stage_index=stage_index,
                        pre_score=pre_score,
                        repairs_used=repairs_used,
                        max_repairs=max_repairs,
                        stop_on_failure=stop_on_failure,
                    )
                    outcomes.append(outcome.as_dict())
                    if rollback:
                        rollbacks.append(rollback)
                    if interrupted_now:
                        interrupted = True
                        interrupt_reason = reason
                        break
            if interrupted:
                break

        receipt = {
            "schema": STAGE_EXEC_SCHEMA,
            "generatedAt": _utc_now(),
            "missionId": self.mission_id,
            "planHash": plan["planHash"],
            "objective": plan.get("objective") or "",
            "language": plan.get("language") or "NEYVIA/1",
            "ok": not interrupted,
            "interrupted": interrupted,
            "interruptReason": interrupt_reason,
            "verificationScore": context.get("verification_score"),
            "bestVerificationScore": context.get("best_verification_score"),
            "repairsUsed": repairs_used,
            "maxRepairs": max_repairs,
            "completedStepIds": list(context.get("completed_step_ids") or []),
            "parallelStagesRun": parallel_stages_run,
            "outcomes": outcomes,
            "checkpoints": [
                {
                    "checkpointId": item.get("checkpointId"),
                    "path": item.get("path"),
                    "verificationScore": item.get("verificationScore"),
                }
                for item in checkpoints
            ],
            "rollbacks": rollbacks,
            "ultraCompetingCandidates": {"enabled": False},
        }

        path = self._write_execution_receipt(receipt)
        receipt["receiptPath"] = str(path)
        _atomic_json(path, receipt)
        from .proofs_d_host import check_stage_receipt
        check_stage_receipt(plan, receipt)
        return receipt

    def _run_parallel_steps(
        self,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Execute independent steps concurrently; return raw results keyed by step_id."""
        results: dict[str, dict[str, Any]] = {}
        workers = min(self.max_workers, len(steps))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.step_handler, step, copy.deepcopy(context)): str(step["step_id"])
                for step in steps
            }
            for future in as_completed(futures):
                step_id = futures[future]
                try:
                    raw = future.result()
                    results[step_id] = raw if isinstance(raw, dict) else {"ok": True, "summary": str(raw)}
                except Exception as exc:
                    results[step_id] = {
                        "ok": False,
                        "summary": f"Parallel step {step_id} raised: {exc}",
                        "metadata": {"error": str(exc), "parallel": True},
                    }
        return results

    def _apply_outcome(
        self,
        *,
        plan: dict[str, Any],
        step: dict[str, Any],
        raw: dict[str, Any] | None,
        context: dict[str, Any],
        checkpoints: list[dict[str, Any]],
        stage_index: int,
        pre_score: float,
        repairs_used: int,
        max_repairs: int,
        stop_on_failure: bool,
    ) -> tuple[StepOutcome, dict[str, Any], dict[str, Any] | None, bool, str, int]:
        step_id = str(step.get("step_id") or "")
        action = str(step.get("action") or "")
        outcome = self._normalize_outcome(step, raw)
        rollback: dict[str, Any] | None = None
        interrupted = False
        interrupt_reason = ""

        if action == "repair":
            repairs_used += 1
            if max_repairs and repairs_used > max_repairs:
                interrupted = True
                interrupt_reason = "max_repairs_exhausted"

        if action in {"verify", "repair"} and outcome.verification_score is not None:
            new_score = float(outcome.verification_score)
            context["verification_score"] = new_score
            if action == "repair" and new_score < float(context.get("best_verification_score") or 0.0):
                rollback = self._rollback_to_best_checkpoint(
                    plan=plan,
                    context=context,
                    checkpoints=checkpoints,
                    step=step,
                    previous_score=pre_score,
                    new_score=new_score,
                )
                outcome.rolled_back = True
                outcome.rollback_receipt_path = str(rollback.get("receiptPath") or "")
                outcome.ok = False
                outcome.summary = (
                    f"{outcome.summary}; rolled back to best checkpoint "
                    f"(score {new_score:.3f} < best {context.get('best_verification_score')})"
                )
                context["verification_score"] = float(context.get("best_verification_score") or 0.0)
            elif new_score >= float(context.get("best_verification_score") or 0.0):
                context["best_verification_score"] = new_score

        if action == "checkpoint" or (action == "verify" and outcome.ok and not outcome.rolled_back):
            checkpoints.append(self._save_checkpoint(plan, context, stage_index, step_id))

        if outcome.ok and not outcome.rolled_back:
            completed = list(context.get("completed_step_ids") or [])
            if step_id not in completed:
                completed.append(step_id)
            context["completed_step_ids"] = completed

        hard_failure = (not outcome.ok) and action != "repair" and not outcome.rolled_back
        if hard_failure and stop_on_failure and not interrupted:
            interrupted = True
            interrupt_reason = f"step_failed:{step_id}"

        return outcome, context, rollback, interrupted, interrupt_reason, repairs_used

    def _normalize_outcome(self, step: dict[str, Any], raw: dict[str, Any] | None) -> StepOutcome:
        payload = raw if isinstance(raw, dict) else {}
        score = payload.get("verification_score", payload.get("verificationScore"))
        return StepOutcome(
            step_id=str(step.get("step_id") or ""),
            action=str(step.get("action") or ""),
            ok=bool(payload.get("ok", True)),
            verification_score=None if score is None else float(score),
            summary=str(payload.get("summary") or ""),
            artifacts=[str(item) for item in (payload.get("artifacts") or []) if str(item).strip()],
            metadata=dict(payload.get("metadata") or {}),
        )

    def _save_checkpoint(
        self,
        plan: dict[str, Any],
        context: dict[str, Any],
        stage_index: int,
        step_id: str,
    ) -> dict[str, Any]:
        checkpoint_id = f"stageckpt_{stage_index:03d}_{step_id}_{uuid.uuid4().hex[:8]}"
        payload = {
            "schema": CHECKPOINT_SCHEMA,
            "checkpointId": checkpoint_id,
            "createdAt": _utc_now(),
            "planHash": plan["planHash"],
            "missionId": self.mission_id,
            "stageIndex": stage_index,
            "stepId": step_id,
            "verificationScore": float(context.get("verification_score") or 0.0),
            "bestVerificationScore": float(context.get("best_verification_score") or 0.0),
            "completedStepIds": list(context.get("completed_step_ids") or []),
            "workspace": copy.deepcopy(context.get("workspace") or {}),
            "context": {
                "verification_score": context.get("verification_score"),
                "best_verification_score": context.get("best_verification_score"),
                "completed_step_ids": list(context.get("completed_step_ids") or []),
                "workspace": copy.deepcopy(context.get("workspace") or {}),
            },
        }
        path = self.receipt_dir / "checkpoints" / f"{checkpoint_id}.json"
        _atomic_json(path, payload)
        payload["path"] = str(path)
        return payload

    def _rollback_to_best_checkpoint(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
        checkpoints: list[dict[str, Any]],
        step: dict[str, Any],
        previous_score: float,
        new_score: float,
    ) -> dict[str, Any]:
        best = None
        best_score = -1.0
        for item in checkpoints:
            score = float(item.get("verificationScore") or item.get("bestVerificationScore") or 0.0)
            if score >= best_score:
                best_score = score
                best = item
        restored = {}
        if best and isinstance(best.get("context"), dict):
            restored = copy.deepcopy(best["context"])
            context["verification_score"] = float(restored.get("verification_score") or best_score)
            context["best_verification_score"] = float(
                restored.get("best_verification_score") or best_score
            )
            context["completed_step_ids"] = list(restored.get("completed_step_ids") or [])
            context["workspace"] = copy.deepcopy(restored.get("workspace") or {})
        elif best:
            context["verification_score"] = float(best.get("verificationScore") or 0.0)
            context["best_verification_score"] = float(
                best.get("bestVerificationScore") or context["verification_score"]
            )

        receipt = {
            "schema": ROLLBACK_RECEIPT_SCHEMA,
            "generatedAt": _utc_now(),
            "missionId": self.mission_id,
            "planHash": plan["planHash"],
            "triggerStepId": step.get("step_id"),
            "triggerAction": step.get("action"),
            "reason": "repair_decreased_verification_score",
            "previousScore": previous_score,
            "decreasedTo": new_score,
            "restoredScore": context.get("verification_score"),
            "bestCheckpointId": (best or {}).get("checkpointId") or "",
            "bestCheckpointPath": (best or {}).get("path") or "",
            "restoredContext": restored,
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.receipt_dir / f"{stamp}_{plan['planHash'][:12]}_rollback.json"
        receipt["receiptPath"] = str(path)
        _atomic_json(path, receipt)
        return receipt

    def _write_execution_receipt(self, receipt: dict[str, Any]) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plan_hash = str(receipt.get("planHash") or "plan")[:12]
        attempt_id = uuid.uuid4().hex[:12]
        return self.receipt_dir / f"{stamp}_{plan_hash}_{attempt_id}_stage_exec.json"


def execute_neyvia_stages(
    root: str | Path,
    plan_or_source: dict[str, Any] | str,
    *,
    step_handler: StepHandler | None = None,
    mission_id: str = "",
    initial_context: dict[str, Any] | None = None,
    stop_on_failure: bool = True,
    max_workers: int = 8,
) -> dict[str, Any]:
    scheduler = NeyviaStageScheduler(
        root,
        step_handler=step_handler,
        mission_id=mission_id,
        max_workers=max_workers,
    )
    return scheduler.execute(
        plan_or_source,
        initial_context=initial_context,
        stop_on_failure=stop_on_failure,
    )
