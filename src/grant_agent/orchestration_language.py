from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import asdict, dataclass, field
from typing import Any


NEYVIA_LANGUAGE_VERSION = "1"
NEYVIA_PLAN_SCHEMA = "neyvia.orchestration_plan.v1"
VALID_RISKS = {"read", "artifact_write", "workspace_write", "external_write", "destructive"}
VALID_ACTIONS = {"tool", "runtime", "verify", "review", "repair", "checkpoint"}


class NeyviaLanguageError(ValueError):
    pass


def _safe_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,95}", normalized):
        raise NeyviaLanguageError(f"Invalid {label} identifier: {value!r}")
    return normalized


def _parse_value(value: str) -> Any:
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null"}:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if text.startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise NeyviaLanguageError(f"Invalid JSON value: {text}") from exc
    return text


def _fields(tokens: list[str], *, line_number: int) -> tuple[list[str], dict[str, Any]]:
    positional: list[str] = []
    fields: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            positional.append(token)
            continue
        key, value = token.split("=", 1)
        key = str(key).strip()
        if not key:
            raise NeyviaLanguageError(f"Line {line_number}: empty field name")
        if key in fields:
            raise NeyviaLanguageError(f"Line {line_number}: duplicate field {key!r}")
        fields[key] = _parse_value(value)
    return positional, fields


def _list_value(value: Any) -> list[str]:
    if value is None or value == "" or value == "-":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip() and item.strip() != "-"]


@dataclass(frozen=True)
class OrchestrationLane:
    lane_id: str
    runtime: str
    model: str
    effort: str
    permissions: list[str] = field(default_factory=list)
    max_parallel: int = 1


@dataclass(frozen=True)
class OrchestrationStep:
    step_id: str
    lane_id: str
    action: str
    after: list[str] = field(default_factory=list)
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    risk: str = "read"
    output: str = ""
    acceptance: str = ""


@dataclass
class NeyviaProgram:
    objective: str = ""
    lanes: list[OrchestrationLane] = field(default_factory=list)
    steps: list[OrchestrationStep] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    stop_conditions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.objective.strip():
            raise NeyviaLanguageError("A GOAL text=... directive is required.")
        if not self.lanes:
            raise NeyviaLanguageError("At least one LANE is required.")
        if not self.steps:
            raise NeyviaLanguageError("At least one STEP or VERIFY is required.")
        lane_ids = [item.lane_id for item in self.lanes]
        if len(lane_ids) != len(set(lane_ids)):
            raise NeyviaLanguageError("Lane identifiers must be unique.")
        step_ids = [item.step_id for item in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise NeyviaLanguageError("Step identifiers must be unique.")
        lane_set = set(lane_ids)
        step_set = set(step_ids)
        for step in self.steps:
            if step.lane_id not in lane_set:
                raise NeyviaLanguageError(
                    f"Step {step.step_id!r} references unknown lane {step.lane_id!r}."
                )
            if step.action not in VALID_ACTIONS:
                raise NeyviaLanguageError(
                    f"Step {step.step_id!r} has unsupported action {step.action!r}."
                )
            if step.risk not in VALID_RISKS:
                raise NeyviaLanguageError(
                    f"Step {step.step_id!r} has unsupported risk {step.risk!r}."
                )
            if step.action == "tool" and not step.tool:
                raise NeyviaLanguageError(f"Tool step {step.step_id!r} requires tool=...")
            for dependency in step.after:
                if dependency not in step_set:
                    raise NeyviaLanguageError(
                        f"Step {step.step_id!r} references unknown dependency {dependency!r}."
                    )
                if dependency == step.step_id:
                    raise NeyviaLanguageError(f"Step {step.step_id!r} cannot depend on itself.")
        self.topological_stages()

    def topological_stages(self) -> list[list[str]]:
        dependencies = {item.step_id: set(item.after) for item in self.steps}
        remaining = set(dependencies)
        completed: set[str] = set()
        stages: list[list[str]] = []
        while remaining:
            ready = sorted(
                step_id for step_id in remaining if dependencies[step_id].issubset(completed)
            )
            if not ready:
                cycle_members = ", ".join(sorted(remaining))
                raise NeyviaLanguageError(f"Dependency cycle detected among: {cycle_members}")
            stages.append(ready)
            completed.update(ready)
            remaining.difference_update(ready)
        return stages

    def compile(self) -> dict[str, Any]:
        self.validate()
        stages = self.topological_stages()
        lane_map = {item.lane_id: asdict(item) for item in self.lanes}
        compiled_steps: list[dict[str, Any]] = []
        for step in self.steps:
            lane = lane_map[step.lane_id]
            approval_required = step.risk in {"external_write", "destructive"}
            compiled_steps.append(
                {
                    **asdict(step),
                    "runtime": lane["runtime"],
                    "model": lane["model"],
                    "effort": lane["effort"],
                    "permissionEnvelope": {
                        "allowed": lane["permissions"],
                        "mutability": step.risk,
                        "approvalRequired": approval_required,
                    },
                    "proofRequired": bool(step.output or step.acceptance or step.action == "verify"),
                }
            )
        payload: dict[str, Any] = {
            "schema": NEYVIA_PLAN_SCHEMA,
            "language": f"NEYVIA/{NEYVIA_LANGUAGE_VERSION}",
            "objective": self.objective,
            "budget": {
                "contextTokens": int(self.budget.get("context", 0) or 0),
                "reserveTokens": int(self.budget.get("reserve", 0) or 0),
                "wallSeconds": int(self.budget.get("wall", 0) or 0),
                "maxRepairs": int(self.budget.get("repairs", 0) or 0),
            },
            "lanes": list(lane_map.values()),
            "steps": compiled_steps,
            "executionStages": [
                {
                    "index": index,
                    "stepIds": stage,
                    "parallelSafe": len(stage) > 1,
                }
                for index, stage in enumerate(stages)
            ],
            "stopConditions": self.stop_conditions,
            "metadata": self.metadata,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["planHash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        payload["estimatedPlanTokens"] = max(1, (len(canonical) + 3) // 4)
        from .proofs_d_ui_planning import check_compiled
        check_compiled(self, payload, canonical)
        return payload


def parse_neyvia_program(source: str) -> NeyviaProgram:
    program = NeyviaProgram()
    saw_header = False
    for line_number, raw_line in enumerate(str(source).splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise NeyviaLanguageError(f"Line {line_number}: {exc}") from exc
        if not tokens:
            continue
        directive = tokens.pop(0).upper()
        if directive == f"NEYVIA/{NEYVIA_LANGUAGE_VERSION}":
            if saw_header:
                raise NeyviaLanguageError(f"Line {line_number}: duplicate language header")
            saw_header = True
            continue
        if not saw_header:
            raise NeyviaLanguageError(
                f"Line {line_number}: program must begin with NEYVIA/{NEYVIA_LANGUAGE_VERSION}"
            )
        positional, fields = _fields(tokens, line_number=line_number)
        if directive == "GOAL":
            text = fields.get("text")
            if text is None and positional:
                text = " ".join(positional)
            program.objective = str(text or "").strip()
        elif directive == "BUDGET":
            program.budget.update(fields)
        elif directive == "META":
            program.metadata.update(fields)
        elif directive == "STOP":
            condition = fields.get("when") or (" ".join(positional) if positional else "")
            if condition:
                program.stop_conditions.append(str(condition))
        elif directive == "LANE":
            if not positional:
                raise NeyviaLanguageError(f"Line {line_number}: LANE requires an identifier")
            lane_id = _safe_identifier(positional[0], "lane")
            program.lanes.append(
                OrchestrationLane(
                    lane_id=lane_id,
                    runtime=str(fields.get("runtime") or "neyvia-native"),
                    model=str(fields.get("model") or "runtime-default"),
                    effort=str(fields.get("effort") or "provider-default"),
                    permissions=_list_value(fields.get("permissions")),
                    max_parallel=max(1, int(fields.get("parallel") or 1)),
                )
            )
        elif directive in {"STEP", "VERIFY"}:
            if not positional:
                raise NeyviaLanguageError(f"Line {line_number}: {directive} requires an identifier")
            step_id = _safe_identifier(positional[0], "step")
            default_lane = "verifier" if any(item.lane_id == "verifier" for item in program.lanes) else (
                program.lanes[0].lane_id if program.lanes else ""
            )
            action = "verify" if directive == "VERIFY" else str(fields.get("action") or "runtime")
            arguments = fields.get("args") or {}
            if not isinstance(arguments, dict):
                raise NeyviaLanguageError(f"Line {line_number}: args must be a JSON object")
            program.steps.append(
                OrchestrationStep(
                    step_id=step_id,
                    lane_id=str(fields.get("lane") or default_lane),
                    action=action,
                    after=_list_value(fields.get("after")),
                    tool=str(fields.get("tool") or ""),
                    arguments=arguments,
                    command=str(fields.get("command") or ""),
                    risk=str(fields.get("risk") or ("read" if directive == "VERIFY" else "workspace_write")),
                    output=str(fields.get("output") or ""),
                    acceptance=str(fields.get("accept") or fields.get("acceptance") or ""),
                )
            )
        else:
            raise NeyviaLanguageError(f"Line {line_number}: unknown directive {directive!r}")
    if not saw_header:
        raise NeyviaLanguageError(f"Program must begin with NEYVIA/{NEYVIA_LANGUAGE_VERSION}")
    program.validate()
    return program


def compile_neyvia_program(source: str) -> dict[str, Any]:
    return parse_neyvia_program(source).compile()
