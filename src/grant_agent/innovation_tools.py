"""Model-facing entry points; operator preference/promotion is intentionally separate."""

from pathlib import Path
import json
from .workspace_intelligence import WorkspaceIntelligence
from .experimental_quality import ExperimentalQuality
from .contextual_learning import ContextualLearningStore
from .execution_ownership import ExecutionOwnership


_OPERATIONS = {
    "intelligence.ask_self": (
        "Record a concrete unresolved question and the decision it changes. This does not call another model or request user input.",
        "ask_self", ["question", "decision"],
    ),
    "intelligence.answer_self": (
        "Record your answer against existing artifact obligation IDs, checking their current evidence. Failed or stale checks keep the question unresolved. Use its exact expected_revision.",
        "answer_self", ["question_id", "answer", "checks", "expected_revision"],
    ),
    "intelligence.self_questions": (
        "Retrieve bounded self-questions, reported answers and stale evidence; no claim about hidden model thinking.",
        "self_questions", [],
    ),
    "intelligence.collaboration": (
        "Read this task's collaboration preferences and evolving brief. Model proposals confer no authority.",
        "collaboration", [],
    ),
    "intelligence.brief": (
        "Save or revise the task brief. Use expected_revision from intelligence.collaboration.brief.revision (0 when no brief), not the preferences revision. Omitted lists retain their saved values; user corrections and the selected direction are protected.",
        "propose_brief", ["understanding"],
    ),
    "intelligence.rationale": (
        "Save a versioned purpose and protected decisions for an element.",
        "rationale",
        ["element_id", "purpose"],
    ),
    "intelligence.read": ("Read durable rationale and obligations.", "snapshot", []),
    "intelligence.obligate": (
        "Attach a runnable file_contains or json_path criterion to a real artifact hash.",
        "attach_obligation",
        ["artifact", "sha256", "criterion"],
    ),
    "intelligence.check": (
        "Recheck saved artifact obligations and report failures.",
        "evaluate_obligations",
        [],
    ),
    "intelligence.handoff": (
        "Persist an immutable handoff with objective, protected decision IDs, answer key and artifact identities.",
        "export_handoff",
        ["objective", "protected_decisions", "answers"],
    ),
    "intelligence.resume": (
        "Reconstruct a saved handoff by ID and verify objective, answers and current artifacts.",
        "resume_handoff",
        ["handoff", "objective", "answers"],
    ),
    "quality.instrument": (
        "Seal a json_numeric, image or trace_timing instrument specification.",
        "define_instrument",
        ["i", "spec"],
    ),
    "quality.measure": (
        "Measure an actual scoped artifact and preserve a receipt.",
        "measure",
        ["instrument", "target"],
    ),
    "quality.compare": (
        "Apply the same frozen instrument to real baseline and candidate artifacts.",
        "compare",
        ["instrument", "baseline", "candidate"],
    ),
    "quality.holdout": (
        "Seal an immutable examination with an instruments list.",
        "define_holdout",
        ["i", "spec"],
    ),
    "quality.examine": (
        "Run all frozen examination instruments on supplied artifact targets.",
        "examine",
        ["holdout", "targets"],
    ),
    "quality.challenge": (
        "Persist a proposed examination challenge pending operator review.",
        "challenge",
        ["holdout", "proposal"],
    ),
    "taste.correction": (
        "Record a provisional contextual correction from real before/after artifacts.",
        "record_correction",
        ["context", "before_path", "after_path", "correction"],
    ),
    "taste.history": (
        "Read contextual preferences with sample counts and explicit uncertainty.",
        "history",
        ["context"],
    ),
    "attention.create": (
        "Freeze a matched representation experiment with route, criterion and budget.",
        "create_attention_experiment",
        [
            "experiment_id",
            "baseline_input",
            "variant_input",
            "acceptance",
            "requested_route",
            "budget",
        ],
    ),
    "attention.observe": (
        "Record explicitly unverified API behavioral observations.",
        "record_attention_observation",
        ["experiment_id", "variant", "response", "actual_route"],
    ),
    "attention.select": (
        "Compare representation outcomes without dropping protected constraints or promoting unverified claims.",
        "select_representation",
        ["experiment_id", "protected_constraints"],
    ),
    "execution.status": (
        "Inspect server execution ownership independently of the viewer connection.",
        "snapshot",
        [],
    ),
}

_BRIEF_DIRECTION = {"type": "object", "additionalProperties": False,
    "properties": {key: {"type": "string", "minLength": 1, "maxLength": 1500 if key in {"approach", "tradeoff"} else 120}
                   for key in ("id", "title", "approach", "tradeoff")},
    "required": ["id", "title", "approach", "tradeoff"]}
_ARGUMENT_SCHEMAS = {
    "intelligence.collaboration": {"type": "object", "properties": {}, "additionalProperties": False},
    "intelligence.brief": {"type": "object", "additionalProperties": False,
        "properties": {
            "understanding": {"type": "string", "minLength": 1, "maxLength": 6000},
            "expected_revision": {"type": "integer", "minimum": 0,
                "description": "Current brief.revision, or 0 before first save. The top-level revision belongs to preferences."},
            "assumptions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 1000}},
            "directions": {"type": "array", "maxItems": 4, "items": _BRIEF_DIRECTION,
                "description": "Omit to preserve the saved choices. Selected direction content must remain unchanged."},
            "open_questions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 1000}},
        }, "required": ["understanding", "expected_revision"]},
    "intelligence.ask_self": {"type": "object", "additionalProperties": False,
        "properties": {key: {"type": "string", "minLength": 1, "maxLength": 1200} for key in ("question", "decision")},
        "required": ["question", "decision"]},
    "intelligence.answer_self": {"type": "object", "additionalProperties": False,
        "properties": {"question_id": {"type": "string"}, "answer": {"type": "string", "maxLength": 4000},
            "checks": {"type": "array", "minItems": 1, "maxItems": 12, "uniqueItems": True, "items": {"type": "string"},
                "description": "IDs of already saved artifact obligations; do not invent check results."},
            "expected_revision": {"type": "integer", "minimum": 0}},
        "required": ["question_id", "answer", "checks", "expected_revision"]},
}


_LOCAL_ID = {"type": "string", "minLength": 1, "maxLength": 120,
             "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]*$"}
_LOCAL_PATH = {"type": "string", "minLength": 1, "maxLength": 4096}
_INSTRUMENT_SPEC = {"type": "object", "additionalProperties": False,
    "properties": {"kind": {"type": "string", "enum": ["json_numeric", "image", "trace_timing"]},
                   "key": {"type": "string", "minLength": 1, "maxLength": 256},
                   "max": {"type": "number"}, "maxMeanMs": {"type": "number", "minimum": 0},
                   "minWidth": {"type": "integer", "minimum": 0},
                   "minHeight": {"type": "integer", "minimum": 0},
                   "maxBytes": {"type": "integer", "minimum": 0}}, "required": ["kind"]}
_HOLDOUT_SPEC = {"type": "object", "properties": {"instruments": {"type": "array",
    "minItems": 1, "maxItems": 20, "uniqueItems": True, "items": _LOCAL_ID}}, "required": ["instruments"]}


def _local_arguments(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


_ARGUMENT_SCHEMAS.update({
    "quality.instrument": _local_arguments({"i": _LOCAL_ID, "spec": _INSTRUMENT_SPEC}),
    "quality.holdout": _local_arguments({"i": _LOCAL_ID, "spec": _HOLDOUT_SPEC}),
    "quality.measure": _local_arguments({"instrument": _LOCAL_ID, "target": _LOCAL_PATH}),
    "quality.compare": _local_arguments({"instrument": _LOCAL_ID, "baseline": _LOCAL_PATH, "candidate": _LOCAL_PATH}),
    "quality.examine": _local_arguments({"holdout": _LOCAL_ID, "targets": {"type": "array", "minItems": 1,
        "maxItems": 20, "items": _LOCAL_PATH}}),
    "quality.challenge": _local_arguments({"holdout": _LOCAL_ID, "proposal": {"type": "object"}}),
    "taste.correction": _local_arguments({"context": {"type": "string", "enum": ["landing-page", "product-ui", "research", "game"]},
        "before_path": _LOCAL_PATH, "after_path": _LOCAL_PATH, "correction": {"type": "string", "minLength": 1, "maxLength": 12000},
        "agent_id": {"type": "string", "maxLength": 120}}, ["context", "before_path", "after_path", "correction"]),
})


def innovation_tool_definitions():
    reads = {
        "intelligence.self_questions",
        "intelligence.collaboration",
        "intelligence.read",
        "intelligence.check",
        "intelligence.resume",
        "taste.history",
        "attention.select",
        "execution.status",
    }
    return [
        (
            name,
            description + " Arguments: " + ", ".join(required) + ".",
            "read" if name in reads else "artifact_write",
            {"workId": {"type": "string"}, "arguments": _ARGUMENT_SCHEMAS.get(name, {"type": "object"})},
            ["workId", "arguments"],
        )
        for name, (description, method, required) in _OPERATIONS.items()
    ]


class InnovationToolRuntime:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def call(self, name, args):
        if name not in _OPERATIONS:
            raise ValueError("Unknown innovation tool")
        from .creative_tools import CreativeToolRuntime

        work_id = CreativeToolRuntime.identity(args["workId"])
        from .workspace_intelligence import require_collaboration_feature
        require_collaboration_feature(self.root, work_id, name)
        payload = dict(args.get("arguments") or {})
        if len(json.dumps(payload, allow_nan=False)) > 128000:
            raise ValueError("Tool payload too large")
        if any(
            key in payload
            for key in (
                "source",
                "operator_identity",
                "trusted_operator",
                "trustedOperator",
            )
        ):
            raise PermissionError(
                "Operator authority is not a model-controlled argument"
            )
        description, method, required = _OPERATIONS[name]
        if any(key not in payload for key in required):
            raise ValueError("Required arguments: " + ", ".join(required))
        if name.startswith("intelligence."):
            store = WorkspaceIntelligence(self.root, work_id)
        elif name.startswith("quality."):
            store = ExperimentalQuality(self.root, work_id)
        elif name.startswith(("taste.", "attention.")):
            store = ContextualLearningStore(
                self.root
                / ".agent_control"
                / "contextual_learning"
                / f"{work_id}.json",
                scope_root=self.root,
            )
        else:
            store = ExecutionOwnership(self.root, work_id)
        result = getattr(store, method)(**payload)
        return {
            "result": result,
            "workId": work_id,
            "evidenceBoundary": "saved rationale and observed artifact criteria; no general quality guarantee",
        }
