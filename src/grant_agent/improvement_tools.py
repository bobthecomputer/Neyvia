"""Native entry points for the improvement lab; execution still needs tool grants."""
from .improvement_lab import ImprovementLab

S = {"type": "string"}
O = {"type": "object"}
A = {"type": "array"}
IDS = {"type": "array", "minItems": 1, "maxItems": 12, "uniqueItems": True,
       "items": {"type": "string", "minLength": 1, "maxLength": 120}}
INSTRUMENT = {"type": "object", "additionalProperties": False,
    "properties": {"kind": {"type": "string", "enum": ["json_numeric", "image", "trace_timing"]},
                   "key": {"type": "string", "minLength": 1}, "max": {"type": "number"},
                   "maxMeanMs": {"type": "number", "minimum": 0}, "minWidth": {"type": "integer", "minimum": 0},
                   "minHeight": {"type": "integer", "minimum": 0}, "maxBytes": {"type": "integer", "minimum": 0}},
    "required": ["kind"]}
OPERATIONS = {
 "lab.instrument": ("Freeze an existing quality instrument for matched artifact evaluation", "artifact_write", {"identity":S,"spec":INSTRUMENT}),
 "lab.competition": ("Create isolated candidate source snapshots under one frozen measurement contract", "artifact_write", {"identity":S,"source":S,"candidates":{**IDS,"minItems":2,"maxItems":8},"instruments":IDS}),
 "lab.compare": ("Measure every competition candidate with the same frozen instruments; never automatically promote", "artifact_write", {"identity":S,"targets":{"type":"object","minProperties":2,"maxProperties":8,"additionalProperties":{"type":"string","minLength":1,"maxLength":4096}}}),
 "lab.rehearse": ("Run an existing snapshot script with installed software in a managed session; host access remains", "process_execute", {"experiment_id":S,"script":S}),
 "lab.uncertainty": ("Rank explicit assumptions by estimated impact and uncertainty per experiment cost", "artifact_write", {"identity":S,"assumptions":A}),
 "lab.causal": ("Compare reported trials only when one declared factor changes; expose confounded comparisons", "artifact_write", {"baseline":S,"variant":S,"factor":S}),
 "lab.resolve_uncertainty": ("Attach a real frozen-instrument measurement to an assumption without promoting its semantic claim", "artifact_write", {"identity":S,"assumption":{"type":"integer"},"instrument":S,"target":S}),
 "lab.next_experiment": ("Prioritize unmeasured or stale assumptions and preserve failed observations", "read", {"identity":S}),
 "lab.taste_packet": ("Retrieve context-specific operator-approved comparisons whose artifacts still match", "read", {"work_id":S,"context":S}),
 "lab.visual_guard": ("Compare actual protected image pixels, including alpha, without changing either image", "artifact_write", {"baseline":S,"candidate":S,"regions":A}),
 "lab.journey": ("Analyze a timestamped interaction trace for delay, unanswered actions, errors and continuity events", "artifact_write", {"path":S}),
 "lab.curriculum": ("Freeze training and holdout evidence; reject duplicate content and task-family leakage", "artifact_write", {"identity":S,"examples":A}),
 "lab.lesson_packet": ("Retrieve hash-checked training examples without including held-out content", "read", {"identity":S}),
 "lab.complexity": ("Inspect duplicate contracts and absent observations; never remove tools from absence alone", "read", {}),
 "lab.status": ("Read recent persisted improvement definitions and measurements", "read", {}),
}


def improvement_tool_definitions():
    from .workspace_intelligence import COLLABORATION_FEATURE_TOOLS
    return [(name, description, mutation,
             {**fields, "workId": S} if name in COLLABORATION_FEATURE_TOOLS else fields,
             [*fields, "workId"] if name in COLLABORATION_FEATURE_TOOLS else list(fields))
            for name,(description,mutation,fields) in OPERATIONS.items()]


def call_improvement(root, name, args):
    if name not in OPERATIONS:
        raise ValueError("Unknown improvement tool")
    payload = dict(args)
    allowed = set(OPERATIONS[name][2])
    if name == "lab.rehearse":
        allowed.update({"arguments", "_actor"})
    if set(payload)-allowed:
        raise ValueError("Unexpected improvement arguments")
    lab = ImprovementLab(root)
    if name == "lab.instrument":
        return {"path": lab.quality.define_instrument(payload["identity"], payload["spec"])}
    return getattr(lab, name.split(".",1)[1])(**payload)
