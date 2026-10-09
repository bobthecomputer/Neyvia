"""Workspace-scoped tool entry points for adaptive work and creative evidence."""
from pathlib import Path
import re

from .adaptive_work import AdaptiveWorkStore
from .experiment_studio import ExperimentStudio
from .visual_specifications import inspect_image
from .experience_learning import ExperienceStore
from .shared_environments import SharedEnvironmentStore
from .behavioral_experiments import BehavioralExperimentLedger
import sys


_EXPERIENCE_AUTHORITY_ALIASES = (
    ("workId", "work_id"),
    ("permissionMode", "permission_mode"),
    ("approvedPermissions", "approved_permissions"),
    ("capabilityId", "capability_id"),
    ("capabilityPolicy", "capability_policy"),
    ("capability", "capabilities"),
    ("approvalId", "approval_id"),
    ("autonomyLeaseId", "autonomy_lease_id"),
)


def _experience_arguments(args):
    """Flatten an experience body while leaving scope and authority with caller."""
    nested = args.get("arguments")
    if not isinstance(nested, dict):
        raise ValueError("Experience tool arguments must be an object")
    outer = {key: value for key, value in args.items() if key != "arguments"}
    merged = {**outer, **nested}
    # Policy fields have camelCase and snake_case spellings in adjacent APIs.
    # Remove every nested alias in a family, then restore the caller's values.
    # This prevents a differently-spelled inner key from shadowing an outer
    # policy while retaining legacy flat values unchanged.
    for aliases in _EXPERIENCE_AUTHORITY_ALIASES:
        for key in aliases:
            merged.pop(key, None)
        for key in aliases:
            if key in outer:
                merged[key] = outer[key]
    return merged


def creative_tool_definitions():
    from .innovation_tools import innovation_tool_definitions
    from .installed_programs import installed_program_tool_definitions
    from .improvement_tools import improvement_tool_definitions
    from .situation_tools import situation_tool_definitions
    scope = {"workId": {"type": "string"}}
    definitions = innovation_tool_definitions() + installed_program_tool_definitions() + improvement_tool_definitions() + situation_tool_definitions() + [
        ("behavior.create", "Freeze a matched API behavioral experiment, observable criterion, route and call budget; does not run a model.", "artifact_write", {"experimentId":{"type":"string"},"baselineInput":{"type":"string"},"variantInput":{"type":"string"},"acceptance":{"type":"object"},"requestedRoute":{"type":"object"},"budget":{"type":"object"}}, ["experimentId","baselineInput","variantInput","acceptance","requestedRoute","budget"]),
        ("behavior.observe", "Record explicitly unverified, caller-reported API observations. Does not establish internal model state or improvement.", "artifact_write", {"experimentId":{"type":"string"},"variant":{"type":"string","enum":["baseline","variant"]},"response":{"type":"string"},"actualRoute":{"type":"object"},"latencyMs":{"type":"number"},"cost":{"type":"number"}}, ["experimentId","variant","response","actualRoute"]),
        ("behavior.compare", "Compare all recorded matched pairs against the frozen observable criterion, retaining negatives and route mismatches.", "read", {"experimentId":{"type":"string"}}, ["experimentId"]),
        ("work.state", "Read saved focus, open problems and the next evidence-driven action; initialize its durable record when absent.", "artifact_write", scope, ["workId"]),
        ("work.focus", "Save the current focus without discarding other open problems.", "artifact_write", {**scope, "text": {"type": "string"}}, ["workId", "text"]),
        ("work.problem", "Record an unresolved problem for future turns and context recovery.", "artifact_write", {**scope, "text": {"type": "string"}, "blocker": {"type": "string"}}, ["workId", "text"]),
        ("work.update_problem", "Update a saved problem and propose its next useful action; no fixed stage sequence.", "artifact_write", {**scope, "problemId": {"type":"string"}, "status": {"type":"string", "enum":["open","blocked","resolved"]}, "need": {"type":"string", "enum":["inspect","generate","implement","compare","test","retrieve","reflect"]}}, ["workId","problemId","status","need"]),
        ("work.constraint", "Preserve an explicit work constraint across focus changes.", "artifact_write", {**scope, "text": {"type": "string"}}, ["workId", "text"]),
        ("experiment.create", "Preserve an isolated experiment snapshot and declared recipes; does not execute recipes.", "artifact_write", {"experimentId": {"type": "string"}, "source": {"type": "string"}, "launchRecipe": {"type": "object"}, "resetRecipe": {"type": "object"}}, ["experimentId", "source"]),
        ("experiment.inspect", "Inspect a saved experiment and independently check its snapshot hashes.", "read", {"experimentId": {"type": "string"}}, ["experimentId"]),
        ("experiment.restore", "Restore an intact experiment into a new isolated directory, refusing overwrite.", "artifact_write", {"experimentId": {"type": "string"}, "restoreId": {"type": "string"}}, ["experimentId", "restoreId"]),
        ("image.inspect_asset", "Inspect actual image dimensions, alpha, format and SHA-256 inside this workspace.", "read", {"path": {"type": "string"}}, ["path"]),
        ("experience.read", "Read persisted comparisons, temporal observations and investigations for this work.", "read", scope, ["workId"]),
        ("experience.relevant", "Retrieve a bounded set of scoped experience notes with freshness checks and full-note retrieval paths.", "read", {**scope, "query": {"type":"string"}, "maxCharacters": {"type":"integer","minimum":600,"maximum":12000}}, ["workId"]),
        ("experience.note", "After work, preserve a small proposed lesson, applicability conditions, invalidation rules and existing evidence paths. Requires learning enabled; does not establish truth or authority.", "artifact_write", {**scope,"lesson":{"type":"string"},"conditions":{"type":"string"},"invalidation":{"type":"string"},"evidence":{"type":"array","items":{"type":"string"}}}, ["workId","lesson","conditions","invalidation","evidence"]),
        ("experience.compare", "Record a provisional critic comparison tied to two actual image artifacts; does not claim user preference.", "artifact_write", {**scope, "baseline": {"type":"string"}, "candidate": {"type":"string"}, "preference": {"type":"string","enum":["user","provisional","undecided"]}, "observations": {"type":"object"}}, ["workId","baseline","candidate","preference"]),
        ("experience.trace", "Append a timestamped reported interaction observation with references; not an independently verified journey.", "artifact_write", {**scope, "traceId": {"type":"string"}, "eventKind": {"type":"string","enum":["input","frame","state","error","timing"]}, "payload": {"type":"object"}, "references": {"type":"array"}}, ["workId","traceId","eventKind","payload"]),
        ("experience.investigate", "Preserve an explicit hypothesis and proposed experiment without claiming the experiment ran.", "artifact_write", {**scope, "hypothesis": {"type":"string"}, "experiment": {"type":"object"}, "references": {"type":"array"}}, ["workId","hypothesis","experiment"]),
        ("environment.create", "Create or reuse hash-pinned Python dependencies with a shared uv cache. Dependency installation requires a mutation grant.", "process_execute", {"environmentId":{"type":"string"},"lockPath":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":300}}, ["environmentId","lockPath"]),
        ("environment.run", "Run Python in a saved dependency environment and preserve the argv-bound process receipt. CL additionally requires a scoped script and declared fresh output hashes; dependency isolation is not an OS sandbox.", "process_execute", {"manifestPath":{"type":"string"},"args":{"type":"array","maxItems":32,"items":{"type":"string","maxLength":4096}},"timeout":{"type":"integer","minimum":1,"maximum":300},"outputs":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"object","additionalProperties":False,"properties":{"path":{"type":"string","minLength":1,"maxLength":4096},"sha256":{"type":"string","pattern":"^[a-fA-F0-9]{64}$"}},"required":["path","sha256"]}}}, ["manifestPath","args"]),
    ]


    # Experience tools are called by both older flat native-tool clients and
    # wrappers that send their operation fields below an `arguments` object.
    # Keep the scoped work identity outside that body, and describe both forms
    # in the registered schema so the handler can normalize them consistently.
    experience = []
    for name, description, mutation, properties, required in definitions:
        if name.startswith("experience."):
            body = {key: value for key, value in properties.items() if key != "workId"}
            properties = {**properties, "arguments": {"type": "object", "properties": body}}
            required = ["workId"]
        experience.append((name, description, mutation, properties, required))
    definitions = experience

    from .workspace_intelligence import COLLABORATION_FEATURE_TOOLS
    return [(name, description, mutation, {**fields, "workId": {"type": "string"}}, list(dict.fromkeys([*required, "workId"])))
            if name in COLLABORATION_FEATURE_TOOLS else (name, description, mutation, fields, required)
            for name, description, mutation, fields, required in definitions]


class CreativeToolRuntime:
    def __init__(self, root, *, collaboration_root=None, work_scope=None):
        self.root = Path(root).resolve()
        self.collaboration_root = Path(collaboration_root or root).resolve()
        self.work_scope = work_scope

    @staticmethod
    def identity(value):
        value = str(value or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
            raise ValueError("A safe, nonempty object identifier is required")
        return value

    def inside(self, value):
        path = Path(str(value))
        path = (path if path.is_absolute() else self.root / path).resolve()
        path.relative_to(self.root)
        return path

    def call(self, name, args):
        if not isinstance(args, dict):
            raise ValueError("Creative tool arguments must be an object")
        if name.startswith("experience.") and "arguments" in args:
            args = _experience_arguments(args)
        required = {
            "experience.investigate": ("hypothesis", "experiment"),
            "experience.note": ("lesson", "conditions", "invalidation", "evidence"),
            "experience.compare": ("baseline", "candidate", "preference"),
            "experience.trace": ("traceId", "eventKind", "payload"),
        }.get(name, ())
        missing = [key for key in required if key not in args]
        if missing:
            raise ValueError("Missing required experience argument(s): " + ", ".join(missing))
        from .workspace_intelligence import require_collaboration_feature
        if self.work_scope and args.get("workId") and self.work_scope != args["workId"]:
            raise PermissionError("Use the durable work identity bound to this run")
        require_collaboration_feature(self.collaboration_root, self.work_scope or args.get("workId"), name)
        if name.startswith("situation."):
            from .situation_tools import call_situation
            return call_situation(self.root,name,args)
        if name.startswith("lab."):
            from .improvement_tools import call_improvement
            return call_improvement(self.root, name, {key: value for key, value in args.items() if key != "workId"})
        if name.startswith("host."):
            from .installed_programs import InstalledPrograms
            method = {"host.programs": "discover", "host.sessions": "list_sessions", "host.launch": "launch", "host.status": "status", "host.stop": "stop", "host.inspect_preview": "inspect_preview", "host.prepare_file": "prepare_file", "host.launch_file": "launch_file"}.get(name)
            if not method:
                raise ValueError("Unknown host program tool")
            result = getattr(InstalledPrograms(self.root), method)(**args)
            return {"session": result} if name in {"host.launch", "host.launch_file", "host.status", "host.stop"} else result
        if name.startswith(('intelligence.','quality.','taste.','attention.','execution.')):
            from .innovation_tools import InnovationToolRuntime
            return InnovationToolRuntime(self.root).call(name,args)
        if name.startswith("behavior."):
            path = self.root / ".agent_control" / "behavioral_experiments.json"
            ledger = BehavioralExperimentLedger(path)
            identity = self.identity(args["experimentId"])
            if len(str(args).encode("utf-8")) > 256000:
                raise ValueError("Behavioral experiment payload exceeds 256 KB")
            if name == "behavior.create":
                result = ledger.create(identity, baseline_input=args["baselineInput"], variant_input=args["variantInput"], acceptance=args["acceptance"], requested_route=args["requestedRoute"], budget=args["budget"])
            elif name == "behavior.observe":
                result = ledger.record(identity, variant=args["variant"], response=args["response"], actual_route=args["actualRoute"], latency_ms=args.get("latencyMs"), cost=args.get("cost"))
            elif name == "behavior.compare": result = ledger.compare(identity)
            else: raise ValueError("Unknown behavioral experiment action")
            return {"experiment":result,"artifacts":[str(path)]}
        if name.startswith("work."):
            store = AdaptiveWorkStore(self.root, self.identity(args["workId"]))
            if name == "work.update_problem":
                store.update_problem(str(args["problemId"]),status=str(args["status"]),need=str(args["need"]))
            elif name != "work.state":
                text = str(args["text"]).strip()
                if not text or len(text) > 12000:
                    raise ValueError("Work text must contain 1 to 12000 characters")
                if name == "work.focus":
                    store.change_focus(text, source="agent_report")
                elif name == "work.problem":
                    store.record_problem(text, blocker=str(args.get("blocker") or ""), source="agent_report")
                elif name == "work.constraint":
                    store.record_constraint(text, source="agent_report")
                else:
                    raise ValueError("Unknown work action")
            return {"state": store.snapshot(), "nextAction": store.next_action(), "artifacts": [str(store.path)]}
        if name.startswith("experiment."):
            studio = ExperimentStudio(self.root)
            identity = self.identity(args["experimentId"])
            if name == "experiment.create":
                return studio.create(identity, source=self.inside(args["source"]), launch_recipe=args.get("launchRecipe"), reset_recipe=args.get("resetRecipe"))
            if name == "experiment.inspect":
                return {"experiment": studio.inspect(identity), "integrity": studio.compare(identity)}
            if name == "experiment.restore":
                return studio.restore(identity, self.root / ".agent_control" / "experiment_restores" / self.identity(args["restoreId"]))
        if name == "image.inspect_asset":
            return {"image": inspect_image(self.inside(args["path"]))}
        if name.startswith("experience."):
            identity = self.identity(args["workId"])
            store = ExperienceStore(self.root, identity)
            if name == "experience.read": return store.snapshot()
            if name == "experience.relevant": return store.relevant(args.get("query", ""), max_characters=args.get("maxCharacters", 3000))
            if name == "experience.note": return {"record": store.note(**{key: args[key] for key in ("lesson", "conditions", "invalidation", "evidence")})}
            if name == "experience.compare":
                baseline = inspect_image(self.inside(args["baseline"]))
                candidate = inspect_image(self.inside(args["candidate"]))
                record = store.compare(experience_id=identity, user_version=baseline["sha256"], provisional_version=candidate["sha256"],
                    preference=str(args["preference"]), observations=args.get("observations"),
                    provenance={"source":"agent_critic", "userPreferenceConfirmed":False,"baseline":baseline,"candidate":candidate})
            elif name == "experience.trace":
                record = store.trace(trace_id=self.identity(args["traceId"]),event_kind=str(args["eventKind"]),payload=dict(args["payload"]),references=args.get("references"),provenance={"source":"agent_report","verified":False})
            elif name == "experience.investigate":
                record = store.investigate(hypothesis=str(args["hypothesis"]),experiment=dict(args["experiment"]),references=args.get("references"))
            else: raise ValueError("Unknown experience action")
            return {"record":record,"artifacts":[str(store.base / f"{record['recordId']}.json")]}
        if name.startswith("environment."):
            store = SharedEnvironmentStore(self.root)
            if name == "environment.create":
                value = store.create(self.identity(args["environmentId"]),lock_path=self.inside(args["lockPath"]),interpreter=sys.executable,timeout=args.get("timeout",120))
                return {"environment":value,"artifacts":[value["manifestPath"]]}
            if name == "environment.run":
                manifest = store._load(self.inside(args["manifestPath"]))
                result = store.run(manifest,list(args["args"]),timeout=args.get("timeout",30),outputs=args.get('outputs'))
                return {**result,"ok":result["exitCode"]==0,"artifacts":[result["receiptPath"]]}
        raise ValueError("Unknown creative tool")
