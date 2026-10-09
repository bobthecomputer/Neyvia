"""Grounded data manuals: compact views, typed execution and quarantined discoveries."""
from __future__ import annotations
import hashlib
import json
import re
import threading
import uuid
import os
from copy import deepcopy
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from jsonschema import Draft202012Validator
from .proof_ports import C7_PORT_SCHEMA

REPO = Path(__file__).resolve().parents[2]
_COMPILED_MANIFEST = REPO / "config/fixcl_manual_cache.json"
_COMPILER_FILES = (
    "scripts/build_fixcl_manual_cache.py",
    "src/grant_agent/neyvia_manuals.py",
    "src/grant_agent/cl/manuals.py",
    "src/grant_agent/cl/parser.py",
    "src/grant_agent/cl/schema.py",
    "src/grant_agent/cl/integration.py",
    "src/grant_agent/cl/tokens.py",
    "src/grant_agent/manual_contracts.py",
)


def catalog_stamp(*, include_manifest=False):
    """Observe the same catalog files without repeated glob/stat path walks."""
    rows = []
    for directory, suffix in ((REPO / 'manuals', '.manual.json'),
                              (REPO / 'manuals/cl', '.cl')):
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.endswith(suffix):
                    state = entry.stat()
                    rows.append((entry.path, state.st_mtime_ns, state.st_size))
    paths = [REPO / 'config/neyvia_manuals.json',
             *(REPO / name for name in _COMPILER_FILES)]
    if include_manifest:
        paths.append(REPO / 'config/fixcl_manual_cache.json')
    for path in paths:
        try:
            state = path.stat()
            rows.append((str(path), state.st_mtime_ns, state.st_size))
        except FileNotFoundError:
            rows.append((str(path), None, None))
    return tuple(sorted(rows))


def _compiled_manifest():
    bypass = os.environ.get('NEYVIA_MANUAL_CACHE_BYPASS')
    if bypass == "1":
        return {}
    return _compiled_manifest_at(catalog_stamp(include_manifest=True), bypass)


@lru_cache(maxsize=2)
def _compiled_manifest_at(stamp, bypass):
    """Admit only artifacts compiled from these exact sources and compiler."""
    if bypass == "1" or not _COMPILED_MANIFEST.is_file():
        return {}
    try:
        manifest = json.loads(_COMPILED_MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("schema") != "neyvia.compiled-manual-cache.v1":
            return {}
        if manifest.get("compiler") != {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                                        for name in _COMPILER_FILES}:
            return {}
        return manifest
    except (OSError, ValueError, TypeError):
        return {}


def compiled_index_lines():
    """Return build-checked token-bounded index lines for this exact catalog."""
    manifest = _compiled_manifest()
    if (manifest.get("indexSourceSha256") == hashlib.sha256(
            (REPO / "config/neyvia_manuals.json").read_bytes()).hexdigest()
            and isinstance(manifest.get("indexLines"), list)):
        return list(manifest["indexLines"])
    return None


def compiled_manual_owners():
    """Exact catalog owner hints; a missing/stale hint requires full loading."""
    stamp = catalog_stamp(include_manifest=True)
    result = _compiled_manual_owners_at(stamp, os.environ.get('NEYVIA_MANUAL_CACHE_BYPASS'))
    # A catalog edited during admission may not reuse the preceding verdict.
    return result if stamp == catalog_stamp(include_manifest=True) else None


@lru_cache(maxsize=2)
def _compiled_manual_owners_at(stamp, bypass):
    manifest = _compiled_manifest_at(stamp, bypass)
    if (manifest.get("indexSourceSha256") == hashlib.sha256(
            (REPO / "config/neyvia_manuals.json").read_bytes()).hexdigest()
            and isinstance(manifest.get("toolOwners"), dict)
            and isinstance(manifest.get("procedureOwners"), dict)):
        try:
            if all(hashlib.sha256((REPO / row["source"]).read_bytes()).hexdigest() == row["sourceSha256"]
                   and hashlib.sha256((REPO / row["artifact"]).read_bytes()).hexdigest() == row["artifactSha256"]
                   for row in manifest.get("manuals", {}).values()):
                return manifest["toolOwners"], manifest["procedureOwners"]
        except (OSError, KeyError, TypeError):
            pass
    return None


@lru_cache(maxsize=64)
def _cached_artifact(raw):
    return json.loads(raw)


TEXT = {"type": "string"}
SCOPE = {"type": "array", "items": TEXT, "description": "Optional restriction on nested tools; never grants authority"}
DEFINITIONS = [
    ("verify.edges", "Generate adversarial native inputs and execute reviewed generative feature-family fixtures in a fresh worker. Unmapped semantic pairs retain exact requirements; admission never earns semantic coverage or release readiness.",
     {"port": C7_PORT_SCHEMA, "schemaOnly": {"type": "boolean"}, "semanticFixtures": {"type": "boolean"}, "families": {"type": "array", "items": TEXT, "minItems": 1, "uniqueItems": True}}, ["port"]),
    ("verify.edges.status", "Read the last adversarial campaign summary and its source freshness; optionally require every case in one selected family to pass. Never reruns effects.", {"family": TEXT}, []),
    ("verify.status", "Read the latest executable-contract/startup receipt without replaying actions.", {}, []),
    ('verify', 'Run executable manual contracts and startup self-checks in isolated scratch state; report uncovered tests and blocked external procedures.', {'areas': {'type': 'array', 'items': {'type': 'string', 'enum': ['a-capabilities', 'a-cli', 'a-control', 'a-livecontrol', 'a-native-sessions', 'a-providers', 'a-sessions', 'awareness', 'd-host', 'd-native', 'd-nearby', 'd-neyvia', 'd-onboarding', 'd-runtime', 'd-ui-planning', 'dictation', 'frontend', 'frontend-models', 'notes-files', 'proofs-b-adapters', 'proofs-b-browser', 'proofs-b-desktop', 'proofs-b-engine', 'proofs-b-harness', 'proofs-c-control', 'proofs-c-frontend', 'proofs-c-intent', 'proofs-c-missions', 'proofs-c-mobile', 'proofs-c-models', 'proofs-c-runtime', 'proofs-e-chat', 'proofs-e-frontend', 'proofs-e-host', 'proofs-e-models', 'proofs-e-release', 'proofs-e-shell', 'proofs-e-sv', 'proofs-e-wz', 'settings']}, 'minItems': 1, 'uniqueItems': True}, 'includeManuals': {'type': 'boolean', 'default': True, 'description': 'False runs selected areas only and can never establish startup completeness.'}, 'adapterChapters': {'type':'array', 'items':{'type':'string','enum':['git','handoff','html','ocr','publication','sync','release']}, 'minItems':1,'uniqueItems':True,'description':'Selected B adapter chapters only; areas must be proofs-b-adapters and completeness remains false.'}}, []),
    ("manual.index", "List grounded manuals and chapters.", {}, []),
    ("manual.load", "Render one validated chapter.", {"id": TEXT, "chapter": TEXT, "offset": {"type": "integer", "minimum": 0}, "maxChars": {"type": "integer", "minimum": 512, "maximum": 20000}}, ["id"]),
    ("manual.validate", "Validate tools, live schemas, observers, checks and typed steps.", {"id": TEXT}, []),
    ("manual.observe", "Read a named observer and verify its result shape.", {"id": TEXT, "state": TEXT, "inputs": {"type": "object"}, "chapter": TEXT, "scopeTools": SCOPE}, ["id", "state"]),
    ("manual.run", "Execute typed steps and checks; stop at JUDGE. Resume runId with explicit decisions. Nested calls retain authority.", {"id": TEXT, "procedure": TEXT, "inputs": {"type": "object"}, "chapter": TEXT, "runId": TEXT, "decisions": {"type": "object", "additionalProperties": TEXT}, "evidence": TEXT, "scopeTools": SCOPE}, ["id", "procedure"]),
    ("manual.frontier", "Save a quarantined patch; never change live manuals.", {"id": TEXT, "note": {"type": "string", "minLength": 1, "maxLength": 4000}, "observed": {"type": "object"}}, ["id", "note", "observed"]),
    ("manual.patches", "List quarantined patches; promotion requires explicit source review.", {"id": TEXT}, []),
    ("manual.project", "Project a durable state handle by JSON Pointer, offset and limit.", {"handle": TEXT, "path": TEXT, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["handle"]),
    ("manual.versions", "Read workspace manual version lineage and demoted procedures.", {"id": TEXT}, ["id"]),
    ("manual.patch.apply", "Explicitly approve a grounded quarantined patch in this workspace; CAS hash required.", {"id": TEXT, "patchId": TEXT, "expectedSha256": TEXT, "approved": {"const": True}, "reviewer": TEXT, "evidence": {"type": "array", "items": TEXT, "minItems": 1}}, ["id", "patchId", "expectedSha256", "approved", "reviewer", "evidence"]),
    ("manual.demote", "Quarantine removal of an obsolete procedure; explicit patch.apply promotes it.", {"id": TEXT, "chapter": TEXT, "procedure": TEXT, "reason": TEXT}, ["id", "chapter", "procedure", "reason"]),
    ("manual.recovery.bind", "Bind a typed recovery procedure to an observed failed run; never replay failed effects.", {"runId": TEXT, "chapter": TEXT, "procedure": TEXT, "inputs": {"type": "object"}}, ["runId", "chapter", "procedure", "inputs"]),
    ("manual.recover", "Run a recovery bound to this exact failure through original permissions/checks.", {"runId": TEXT, "recipeId": TEXT, "scopeTools": SCOPE}, ["runId", "recipeId"]),
    ("manual.compile", "Compile N verified identical runs to a hash-bound, input-bound executable script.", {"id": TEXT, "chapter": TEXT, "procedure": TEXT, "inputs": {"type": "object"}, "minRuns": {"type": "integer", "minimum": 2, "maximum": 100}}, ["id", "procedure"]),
    ("manual.compiled", "List durable compiled scripts and stale manual versions.", {"id": TEXT}, []),
    ("manual.script.run", "Execute a compiled script without model calls; varied or changed judgements stop at JUDGE.", {"scriptId": TEXT, "inputs": {"type": "object"}, "runId": TEXT, "decisions": {"type": "object", "additionalProperties": TEXT}, "evidence": TEXT, "scopeTools": SCOPE}, ["scriptId"]),
    ("state", "Observe projects, panes, settings, apps and active provider runs.", {}, []),
]
_LOCK = threading.RLock()

for _name, _, _props, _required in DEFINITIONS:
    if _name == "manual.observe":
        _props.update(stream=TEXT, previousHandle=TEXT, reset={"type": "boolean"})
    if _name == "manual.frontier":
        _props["operations"] = {"type": "array", "items": {"type": "object"}, "maxItems": 100}

@contextmanager
def execution_lock(root):
    """Serialize all effects and log writes across MCP/backend processes."""
    with (root / "manual-execution.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            lock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            lock()
        except OSError as exc:
            raise RuntimeError("Another manual run is executing in this workspace; retry after it returns") from exc
        try:
            yield
        finally:
            handle.seek(0)
            unlock()

def records():
    return json.loads((REPO / "config/neyvia_manuals.json").read_text(encoding="utf-8"))["manuals"]

@lru_cache(maxsize=64)
def _compiled_manual_source(source):
    """Cache by exact source content; callers receive a private mutable copy."""
    from .cl.manuals import cl_to_manual
    return cl_to_manual(source)


@lru_cache(maxsize=64)
def _validate_structure_bytes(encoded):
    from .manual_contracts import validate_structure
    validate_structure(json.loads(encoded))


@lru_cache(maxsize=64)
def _validate_grounding_bytes(encoded, catalog):
    from .manual_contracts import validate_grounding
    descriptions = json.loads(catalog)
    class BoundCatalog:
        _handlers = {name: True for name in descriptions}
        def describe(self, name):
            return descriptions[name]
    validate_grounding(json.loads(encoded), BoundCatalog())

def document(record):
    path = (REPO / record.get("clSource", record["path"])).resolve()
    path.relative_to((REPO / "manuals").resolve())
    if path.stat().st_size > 1000000:
        raise ValueError("Manual exceeds 1MB; split it")
    raw = path.read_bytes()
    trusted = False
    if record.get("clSource"):
        artifact_path = (REPO / record["path"]).resolve()
        artifact_path.relative_to((REPO / "manuals").resolve())
        artifact_raw = artifact_path.read_bytes()
        admission = _compiled_manifest().get("manuals", {}).get(record["id"], {})
        trusted = (admission.get("source") == record["clSource"] and admission.get("artifact") == record["path"]
                   and admission.get("sourceSha256") == hashlib.sha256(raw).hexdigest()
                   and admission.get("artifactSha256") == hashlib.sha256(artifact_raw).hexdigest())
        if trusted:
            # The checked-in manifest is emitted only after full CL projection,
            # artifact equality, and schema validation. Private copies prevent
            # callers from mutating another call's manual.
            data = deepcopy(_cached_artifact(artifact_raw))
        else:
            data = deepcopy(_compiled_manual_source(raw.decode("utf-8")))
            artifact = json.loads(artifact_raw)
            if artifact != data:
                raise ValueError("Compiled manual artifact is stale; run scripts/cl_compile_manuals.py")
    else:
        data = json.loads(raw)
    if not trusted:
        from .manual_contracts import validate_structure
        validate_structure(data)
    if data["id"] != record["id"]:
        raise ValueError("Manual ID differs from its index")
    return raw, data

def get_manual(identity, root=None, *, lesson_root=None):
    record = next((row for row in records() if row["id"] == identity), None)
    if not record:
        raise ValueError("Unknown manual ID; use manual.index")
    raw, data = document(record)
    digest = hashlib.sha256(raw).hexdigest()
    if root is not None:
        from .manual_versions import revision
        digest, data = revision(root, identity, digest, data)
        # Measured lesson versions overlay this selected workspace only. Base
        # manuals and explicitly promoted JSON revisions remain recoverable.
        from .lesson_evolver import service_for
        lessons = service_for(lesson_root if lesson_root is not None else Path(root).parent).active_lines(manual=identity)
        if lessons:
            data = deepcopy(data)
            chapter = next(iter(data["chapters"].values()))
            from .cl_skill import JUDGE_HEAD, _split_gloss
            for lesson in lessons:
                line = lesson["line"]
                if lesson["kind"] == "guidance":
                    quoted = re.search(r'"(?:[^"\\]|\\.)*"', line)
                    if quoted:
                        chapter["guidance"].append(json.loads(quoted.group()))
                elif lesson["kind"] == "judge":
                    head, gloss = _split_gloss(line[2:])
                    match = JUDGE_HEAD.match(head)
                    chapter["judge"]["lesson_" + lesson["id"]] = {"question": json.loads(match["question"]), "options": match["options"].split("|"), "constraints": gloss}
                elif lesson["kind"] == "pitfall":
                    failure, _, recovery = line[2:].partition(" -> ")
                    chapter["pitfalls"].append({"failure": failure, "recovery": recovery})
            digest = hashlib.sha256(json.dumps([digest, lessons], sort_keys=True).encode()).hexdigest()
    return record, digest, data

def index(root=None):
    return {"schema": "neyvia.manual-index.v2", "manuals": [{"id": row["id"], "description": row["description"], "chapters": list(get_manual(row["id"], root)[2]["chapters"])} for row in records()], "load": "neyvia.manual.load(id, chapter)"}

def prompt_index():
    return ("NEYVIA MANUAL · " + " · ".join(row["id"] for row in records()) + "\nRead manual.load(id='neyvia',chapter='overview'), then relevant chapters. "
            "STATE/ACTIONS/CHECKS are grounded; run stops at JUDGE. Search/describe/call retains tools and approvals. Frontier patches stay quarantined.")

def discovery_description(command_summary):
    return "Search and describe exact tools; schemas are deferred. " + command_summary + " " + prompt_index()

def render_legacy(chapter, schemas, proofs=None):
    lines = ["INDEX " + chapter["title"]]
    compact = lambda item: json.dumps(item, separators=(',', ':'))
    for name, row in chapter["state"].items():
        lines.append(f"STATE {name}: {row['tool']}({compact(row['args'])}) → {compact(row['shape'])}")
    for name, row in chapter["actions"].items():
        schema = schemas[row["schema"]]
        signature = ",".join(key + ("" if key in schema.get("required", []) else "?") for key in schema.get("properties", {}))
        lines.append(f"ACTIONS {name}={row['tool']}({signature}); pre={row['pre']}; effect={row['effect']}; {'reversible' if row['reversible'] else '⚠ review authority'}")
    for name, row in chapter["checks"].items():
        lines.append(f"CHECKS {name}: {row['tool']}({compact(row['args'])}) {compact(row['expect'])}")
    for name, row in chapter["procedures"].items():
        chain = " → ".join("JUDGE:" + step["judge"] if "judge" in step else step["action"] + (" [" + step["check"] + "]" if step.get("check") else "") for step in row["steps"])
        lines.append(f"PROCEDURE {name}({','.join(row['inputs'].get('properties', {}))}): {row['goal']} → {chain}")
        lines.append(f"STEPS {name}: {compact(row['steps'])}")
    for name, row in chapter["judge"].items():
        lines.append(f"JUDGE {name}: {row['question']} options={','.join(row['options'])}; {row['constraints']}")
    lines += [f"PITFALL {row['failure']} → {row['recovery']}" for row in chapter["pitfalls"]]
    lines += ["FRONTIER " + row for row in chapter["frontier"]]
    lines += ["GUIDANCE " + row for row in chapter["guidance"]]
    for contract in (proofs or {}).get("contracts", []):
        lines.append("CONTRACT " + contract["id"] + " " + contract["phase"] + ": " + contract["claim"])
        lines.append("CHECKED " + "; ".join(contract["checkedAt"]) + " I " + "; ".join(contract["impact"]))
    return "\n".join(lines) + "\n"

def render(chapter, schemas, proofs=None, *, layer="manual", source_version="1.0"):
    from .cl.manuals import render_chapter
    text = render_chapter(chapter, schemas, layer=layer, source_version=source_version)
    # Proofs are trusted host declarations, never model-authored code or
    # CL 1.1 awareness tags. Preserve their exact executable metadata.
    return text + "".join("-- @proof " + json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                          for contract in (proofs or {}).get("contracts", []))

def unwrap(value):
    while isinstance(value, dict) and (isinstance(value.get('toolResult'), dict) or
                                     "tool" in value and isinstance(value.get("result"), dict)):
        if value.get("ok") is False:
            raise RuntimeError(value.get("error") or value.get("status") or "Tool failed")
        value = value['toolResult'] if isinstance(value.get('toolResult'), dict) else value["result"]
    if isinstance(value, dict) and value.get("ok") is False:
        raise RuntimeError(value.get("error") or value.get("message") or value.get("status") or "Tool failed")
    return value


def checked_action_output(registry, name, output):
    """Resolve only this registry's exact saved native result after dispatch."""
    if not isinstance(output, dict) or output.get("ok") is not True or "result" in output:
        return output
    raw = output.get("receipt_path")
    if not raw:
        return output
    original = Path(raw)
    path = original.resolve()
    base = registry.receipt_root.resolve()
    if (original.is_symlink() or path.parent != base or path.is_symlink()
            or path.stat().st_size > 4 * 1024 * 1024):
        raise ValueError("Native result receipt is outside its owning store or bound")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("tool") != name or saved.get("receipt_id") != output.get("receipt_id")
            or saved.get("ok") is not True):
        raise ValueError("Native result receipt does not match this action")
    from .action_receipts import _safe_tool_result
    return {**output, "tool": name, "result": _safe_tool_result(saved["result"])}

def select(value, path):
    for key in (path if isinstance(path, list) else path.split(".")) if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value

def resolve(value, inputs, results, root=None):
    if isinstance(value, dict) and set(value) == {"$input"}:
        return inputs[value["$input"]]
    if isinstance(value, dict) and set(value) == {"$path"}:
        path = Path(inputs[value["$path"]]).expanduser()
        return str((path if path.is_absolute() else root / path).resolve())
    if isinstance(value, dict) and set(value) == {"$result"}:
        name, _, path = value["$result"].partition(".")
        return select(results[name], path)
    if isinstance(value, dict):
        return {key: resolve(item, inputs, results, root) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, inputs, results, root) for item in value]
    return value

def expect(value, rule, inputs, results, root):
    try:
        selected = select(value, resolve(rule["path"], inputs, results, root))
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    if rule["op"] == "exists":
        return True
    if rule["op"] == "schema":
        return Draft202012Validator(resolve(rule["schema"], inputs, results, root)).is_valid(selected)
    wanted = resolve(rule.get("value"), inputs, results, root)
    return selected == wanted if rule["op"] == "eq" else wanted in selected

def validate(data, registry):
    from .manual_contracts import validate_grounding
    canonical_controls = get_manual('manuals-next')[2] if data['id'] == 'manuals-next' else None
    validate_grounding(data, registry, canonical_controls=canonical_controls)
    procedures = [{"chapter": name, "procedure": key, "tools": sorted({chapter["actions"][step["action"]]["tool"] for step in row["steps"] if "action" in step} |
        {chapter["checks"][step["check"]]["tool"] for step in row["steps"] if step.get("check")})}
        for name, chapter in data["chapters"].items() for key, row in chapter["procedures"].items()]
    observers = [{"chapter": name, "state": key, "tools": [row["tool"]]} for name, chapter in data["chapters"].items() for key, row in chapter["state"].items()]
    return {"id": data["id"], "chapters": len(data["chapters"]), "grounded": True, "procedures": procedures, "observers": observers}

def context(service, dispatcher=None, registry=None):
    if registry is None:
        from .native_tools import NativeToolRegistry
        registry = NativeToolRegistry(service.bus.root)
    if dispatcher is None:
        dispatcher = lambda tool, arguments, action_id="": registry.call(tool, arguments)
    return registry, dispatcher

def chapter_entry(data, chapter, section, name):
    found = [(key, item, item[section][name]) for key, item in data["chapters"].items() if (not chapter or key == chapter) and name in item[section]]
    if len(found) != 1:
        raise ValueError("Unknown or ambiguous " + section + " entry; specify chapter")
    return found[0]

def run(service, args, registry, dispatch, *, compiled=None):
    _, digest, data = get_manual(args["id"], service.bus.root / ".neyvia")
    validate(data, registry)
    live = data["id"] == "remote"
    if live and (compiled or args.get("runId")):
        raise ValueError("Remote observations are volatile; run a fresh procedure")
    try:
        chapter, chapter_data, procedure = chapter_entry(data, args.get("chapter"), "procedures", args["procedure"])
    except ValueError as exc:
        return detected_frontier(service, data["id"], digest, "unmapped-procedure", {"chapter": args.get("chapter"), "procedure": args["procedure"], "error": str(exc)})
    # Canonical controls are CL entrypoints, not permission to recurse through
    # the native manual runner. Keep nested execution barred before any write.
    safe_controls = {'index', 'patches', 'project', 'versions', 'compiled', 'frontier', 'demote', 'patch.apply'}
    if any('action' in step and chapter_data['actions'][step['action']]['tool'].startswith('neyvia.manual.')
           and chapter_data['actions'][step['action']]['tool'].removeprefix('neyvia.manual.') not in safe_controls
           for step in procedure['steps']):
        raise ValueError('Recursive manual execution is forbidden')
    def with_defaults(inputs):
        return {**{key: deepcopy(field['default']) for key, field in procedure['inputs'].get('properties', {}).items()
                   if 'default' in field}, **(inputs or {})}
    root = service.bus.root / ".neyvia"
    root.mkdir(parents=True, exist_ok=True)
    decisions = args.get("decisions") or {}
    with _LOCK, execution_lock(root):
        if get_manual(args["id"], root)[1] != digest or (compiled and compiled["sha256"] != digest):
            raise ValueError("Manual changed before execution; reload or recompile")
        identity = args.get("runId") or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("runId must be a returned run identity")
        state_path = root / "manual-runs" / (identity + ".json")
        if args.get("runId"):
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            for key, value in {"id": data["id"], "chapter": chapter, "procedure": args["procedure"], "sha256": digest}.items():
                if saved[key] != value:
                    raise ValueError("Resume must use original manual, procedure and hash")
            if "inputs" in args and with_defaults(args["inputs"]) != saved["inputs"]:
                raise ValueError("Resume cannot replace original inputs")
            if "scopeTools" in args and args["scopeTools"] != saved.get("scopeTools"):
                raise ValueError("Resume cannot replace the original nested-tool restriction")
            if saved.get("compiledArtifactId") != (compiled or {}).get("scriptId"):
                raise ValueError("Resume must use the original compiled artifact or ordinary runner")
            if saved["status"] == "completed":
                return {"ok": True, **saved, "replayed": True}
            if saved["status"] != "judge":
                return {"ok": False, "status": "blocked", "runId": identity, "error": "Interrupted or failed run needs reconciliation; effects will not be replayed"}
        else:
            if decisions:
                raise ValueError("Decisions require a returned judge runId")
            saved = {"runId": identity, "id": data["id"], "chapter": chapter, "procedure": args["procedure"], "sha256": digest, "inputs": with_defaults(args.get("inputs")), "nextStep": 0, "results": {}, "decisions": {}, "checks": [], "status": "running"}
            if compiled:
                saved.update(compiledArtifactId=compiled["scriptId"], decisions=dict(compiled["fixedDecisions"]))
            if "scopeTools" in args:
                saved["scopeTools"] = args["scopeTools"]
        if "scopeTools" in saved:
            Draft202012Validator(SCOPE).validate(saved["scopeTools"])
            nested = next(row["tools"] for row in validate(data, registry)["procedures"] if row["chapter"] == chapter and row["procedure"] == args["procedure"])
            if any(tool not in saved["scopeTools"] for tool in nested):
                raise PermissionError("Procedure contains a tool outside the caller's nested-tool restriction")
        Draft202012Validator(procedure["inputs"]).validate(saved["inputs"])
        def persist():
            if live: return
            from .durability import atomic_write_json
            atomic_write_json(state_path, saved)
        def event(kind, **details):
            if live: return
            from .ui_command_bus import now
            from .durability import append_jsonl_durable
            append_jsonl_durable(root / "manual-runs.jsonl", {"at": now(), "runId": identity, "id": data["id"], "chapter": chapter, "sha256": digest, "procedure": args["procedure"], "compiledArtifactId": saved.get("compiledArtifactId"), "event": kind, **details})
        pending = saved.get("judge")
        if decisions:
            if not pending or set(decisions) != {pending["id"]} or decisions[pending["id"]] not in pending["options"]:
                raise ValueError("Choose exactly one offered option for the pending judge")
            if pending.get("kind", "human") == "model":
                from .judgment_evidence import verify
                ok, why = verify(args.get("evidence"), pending.get("evidence"), [service.bus.root, root], [])
                if not ok:  # a recorded option alone never stands in for the screenshot/artifact it judges
                    raise ValueError("Model judgment is not bound to current evidence: " + why + " (pass evidence as path#sha256)")
                saved.setdefault("judgmentEvidence", {})[pending["id"]] = args["evidence"]
            saved["decisions"].update(decisions)
            saved.setdefault("explicitDecisions", []).extend(decisions)
            event("decision", decisions=decisions)
            saved.pop("judge", None)
        saved["status"] = "running"
        persist()
        event("resume" if args.get("runId") else "start", inputs=saved["inputs"])
        try:
            for position in range(saved["nextStep"], len(procedure["steps"])):
                step = procedure["steps"][position]
                if "judge" in step:
                    name = step["judge"]
                    if compiled and name in compiled["fixedDecisions"] and name not in saved.get("explicitDecisions", []):
                        from .manual_compiler import digest as context_digest
                        if context_digest(saved["results"]) != compiled["fixedDecisionGuards"][name]:
                            saved["decisions"].pop(name, None)
                            saved.setdefault("compiledGuardEscalations", []).append(name)
                    if name not in saved["decisions"]:
                        saved.update(status="judge", judge={"id": name, **chapter_data["judge"][name]}, nextStep=position)
                        persist()
                        event("judge", judge=saved["judge"])
                        return {"ok": True, **saved}
                elif not step.get("when") or saved["decisions"].get(step["when"]["judge"]) == step["when"]["option"]:
                    action = chapter_data["actions"][step["action"]]
                    arguments = resolve(step["args"], saved["inputs"], saved["results"], service.bus.root)
                    Draft202012Validator(data["schemas"][action["schema"]]).validate(arguments)
                    saved["status"] = "executing"
                    persist()  # crash means reconciliation, never automatic mutation replay
                    output = unwrap(checked_action_output(registry, action["tool"],
                        dispatch(action["tool"], arguments, action_id=f"manual:{identity}:{position}")))
                    Draft202012Validator(action["returns"]).validate(output)
                    saved["results"][step["save"]] = output
                    event("action", step=position, action=step["action"], tool=action["tool"], result=output)
                    if step.get("check"):
                        check = chapter_data["checks"][step["check"]]
                        observed = unwrap(checked_action_output(registry, check["tool"],
                            dispatch(check["tool"], resolve(check["args"], saved["inputs"], saved["results"], service.bus.root), action_id=f"manual:{identity}:check:{position}")))
                        passed = expect(observed, check["expect"], saved["inputs"], saved["results"], service.bus.root)
                        receipt = {"step": position, "check": step["check"], "passed": passed, "observed": observed}
                        saved["checks"].append(receipt)
                        event("check", **receipt)
                        if not passed:
                            raise RuntimeError("Verifier failed: " + step["check"])
                saved.update(nextStep=position + 1, status="running")
                persist()
            saved["status"] = "completed"
            event("completed", decisions=saved["decisions"], checks=len(saved["checks"]))
        except Exception as exc:
            saved.update(status="failed", error=str(exc))
            event("failed", step=saved["nextStep"], error=str(exc))
            from .manual_recovery import recipes_for
            saved["recoveryRecipes"] = recipes_for(root, saved)
            if not saved["recoveryRecipes"]:
                saved["frontier"] = detected_frontier(service, data["id"], digest, "execution-failure", {"runId": identity, "chapter": chapter, "procedure": args["procedure"], "step": saved["nextStep"], "error": str(exc)})
        persist()
        return {"ok": saved["status"] == "completed", **saved, **({"recording": False} if live else {})}


def detected_frontier(service, identity, digest, reason, observed):
    from .manual_versions import quarantine
    patch = quarantine(service.bus.root / ".neyvia", identity, digest, reason, observed)
    return {"ok": False, "status": "frontier", "reason": reason, "patchId": patch["patchId"], "quarantined": True,
            "escalation": "Explorer or explicit reviewer needed; no hidden model call", "observed": observed}

def call(service, name, args, *, dispatcher=None, registry=None):
    root = service.bus.root / ".neyvia"
    root.mkdir(parents=True, exist_ok=True)
    if name in {"manual.compile", "manual.compiled", "manual.script.run"}:
        from .manual_compiler import compile_procedure, compiled_index, run_compiled
        if name == "manual.compiled":
            return compiled_index(service, args)
        registry, dispatch = context(service, dispatcher, registry)
        return compile_procedure(service, args, registry) if name == "manual.compile" else run_compiled(service, args, registry, dispatch)
    if name == "manual.project":
        from .manual_state import project
        return project(root, args)
    if name in {"manual.recovery.bind", "manual.recover"}:
        from .manual_recovery import call as recovery_call
        registry, dispatch = context(service, dispatcher, registry)
        return recovery_call(service, name, args, registry, dispatch)
    if name == "state":
        snapshot = service.bus.snapshot()
        page = service.broker().list_sessions(limit=2000, include_archived=False) if service.backend is not None else {"sessions": []}
        return {"ok": True, "project": snapshot.get("activeProject"), "pane": snapshot.get("pane"), "density": snapshot.get("density"), "transparency": snapshot.get("transparency", "everything"), "projects": snapshot.get("projects", {}), "sessions": snapshot.get("sessions", {}),
                "running": [row for row in page["sessions"] if row.get("status") in {"working", "waiting_approval", "waiting_input"}], "apps": {key[4:]: value for key, value in snapshot.items() if key.startswith("app:")}, "nextOffset": page.get("nextOffset"), "providerSessionsObserved": service.backend is not None}
    if name == "manual.index":
        return {"ok": True, **index(root)}
    if name == "manual.patches":
        patches = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((service.bus.root / ".neyvia/manual-patches").glob("*.json"))]
        return {"ok": True, "patches": [row for row in patches if not args.get("id") or row["id"] == args["id"]]}
    if name == "manual.validate":
        registry, _ = context(service, dispatcher, registry)
        checked = [validate(get_manual(row["id"], root)[2], registry) for row in records() if not args.get("id") or row["id"] == args["id"]]
        if not checked:
            raise ValueError("Unknown manual ID")
        return {"ok": True, "manuals": checked}
    record, digest, data = get_manual(args["id"], root)
    if name == "manual.versions":
        path = root / "manual-versions" / (data["id"] + ".json")
        return {"ok": True, "sha256": digest, **(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"id": data["id"], "lineage": []})}
    if name == "manual.patch.apply":
        from .manual_versions import promote
        registry, _ = context(service, dispatcher, registry)
        with _LOCK, execution_lock(root):
            _, digest, data = get_manual(args["id"], root)
            return promote(root, args, digest, data, registry)
    if name == "manual.demote":
        from .manual_versions import quarantine
        chapter, _, _ = chapter_entry(data, args["chapter"], "procedures", args["procedure"])
        from .manual_state import escape
        operations = [{"op": "remove", "path": "/chapters/" + escape(chapter) + "/procedures/" + escape(args["procedure"])}]
        return {"ok": True, **quarantine(root, data["id"], digest, args["reason"], {"obsoleteProcedure": args["procedure"]}, operations)}
    if name == "manual.frontier":
        from .manual_versions import quarantine
        patch = quarantine(root, data["id"], digest, args["note"], args["observed"], args.get("operations"))
        return {"ok": True, **patch}
    if name in {"manual.run", "manual.observe"}:
        registry, dispatch = context(service, dispatcher, registry)
        if name == "manual.run":
            return run(service, args, registry, dispatch)
        validate(data, registry)
        try:
            chapter, _, observer = chapter_entry(data, args.get("chapter"), "state", args["state"])
        except ValueError as exc:
            return detected_frontier(service, data["id"], digest, "unmapped-state", {"state": args["state"], "error": str(exc)})
        if "scopeTools" in args:
            Draft202012Validator(SCOPE).validate(args["scopeTools"])
            if observer["tool"] not in args["scopeTools"]:
                raise PermissionError("Observer is outside the caller's nested-tool restriction")
        Draft202012Validator(observer["inputs"]).validate(args.get("inputs") or {})
        output = unwrap(checked_action_output(registry, observer["tool"],
            dispatch(observer["tool"], resolve(observer["args"], args.get("inputs") or {}, {}, service.bus.root))))
        try:
            Draft202012Validator(observer["shape"]).validate(output)
        except Exception as exc:
            return detected_frontier(service, data["id"], digest, "observer-shape-drift", {"state": args["state"], "error": str(exc)[:1000]})
        from .manual_state import observe
        if data["id"] == "remote":
            return {"ok": True, "id": "remote", "chapter": chapter, "state": args["state"], "mode": "snapshot", "observed": output, "recording": False}
        with _LOCK, execution_lock(root):
            return observe(root, {"id": data["id"], "chapter": chapter, "state": args["state"], "sha256": digest}, output, args)
    if name != "manual.load":
        raise ValueError("Unknown manual operation")
    chapter = args.get("chapter") or "overview"
    if chapter not in data["chapters"]:
        raise ValueError("Unknown chapter; use manual.index")
    registry, _ = context(service, dispatcher, registry)
    validate(data, registry)
    text = render(data["chapters"][chapter], data["schemas"], data.get("proofs"), layer=data["id"],
                  source_version="1.1" if record.get("clSource") else "1.0")
    offset, limit = args.get("offset", 0), args.get("maxChars", 8000)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 512 <= limit <= 20000:
        raise ValueError("offset must be nonnegative; maxChars must be 512–20000")
    end = min(len(text), offset + limit)
    return {"ok": True, "id": data["id"], "chapter": chapter, "path": record["path"], "sha256": digest, "text": text[offset:end], "offset": offset, "truncated": end < len(text), "nextOffset": end if end < len(text) else None}
