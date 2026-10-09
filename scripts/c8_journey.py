"""Disposable UI journey worker using a pinned Neyvia's headless T18 code.

The controller supplies an exact scratch source path and candidate origin. No
operator browser/profile, provider, credential file or live service is used.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
import sys
import time
import uuid
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.parse import urlsplit
from c8_scope import assigned_ports, run_root


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class Candidate:
    def __init__(self, url, session_cookies=None):
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            raise ValueError("Credential-bearing URLs are refused")
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port not in assigned_ports():
            raise ValueError("C8 requires an explicitly declared owned loopback port")
        self.url = url.rstrip("/")
        self.client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.session_cookies = session_cookies
        if session_cookies is None:
            self.post("/api/auth/local-session", {})
        else:
            self.client.addheaders = [("Cookie", "; ".join(c["name"] + "=" + c["value"] for c in session_cookies))]

    def post(self, path, value):
        with self.client.open(Request(self.url + path, data=json.dumps(value).encode(),
                                      headers={"Content-Type": "application/json", "Origin": self.url}), timeout=60) as response:
            return json.load(response)

    def tool(self, name, value=None):
        row = self.post("/api/ui/tools/call", {"tool": "neyvia." + name, "arguments": value or {}})
        data = row.get("data", {})
        if not row.get("ok") or not data.get("ok"):
            raise RuntimeError(str(row))
        return data["result"]

    def cookies(self):
        if self.session_cookies is not None:
            return self.session_cookies
        jar = next(handler.cookiejar for handler in self.client.handlers if isinstance(handler, HTTPCookieProcessor))
        return [{"name": c.name, "value": c.value, "url": self.url} for c in jar]


class UnsupportedRoute(RuntimeError):
    """A valid CL contract that this isolated C8 route cannot safely execute."""


def _deferred_map(binding, field, allowed_names):
    rows = binding.get(field, {})
    if not isinstance(rows, dict):
        raise UnsupportedRoute(f"{field} must be a name-to-receipt map")
    for name, detail in rows.items():
        if name not in allowed_names or not isinstance(detail, dict) or set(detail) != {"reason", "owner", "requiredReceipt"}:
            raise UnsupportedRoute(f"{field} contains an undeclared slot or malformed authority record")
        if any(not isinstance(detail[key], str) or not detail[key].strip() for key in ("reason", "owner", "requiredReceipt")):
            raise UnsupportedRoute(f"{field} requires a concrete reason, owner, and receipt type")
    return rows


def _check_supplied_inputs(schema, inputs, deferred, dynamic_fields=()):
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    if not isinstance(inputs, dict):
        raise UnsupportedRoute("Authored inputs must be a typed object")
    adjusted = deepcopy(schema)
    required = adjusted.get("required", [])
    supplied_later = set(deferred) | set(dynamic_fields)
    if set(deferred) & set(inputs):
        raise UnsupportedRoute("A deferred input cannot also be supplied")
    if any(name not in required for name in supplied_later):
        raise UnsupportedRoute("Deferred or dynamic input must be a required authored field")
    adjusted["required"] = [name for name in required if name not in supplied_later]
    errors = list(Draft202012Validator(adjusted).iter_errors(inputs))
    if errors:
        detail = "; ".join(error.message for error in errors[:4])
        raise UnsupportedRoute("Supplied manual inputs fail the authored schema: " + detail)


def _readonly_tool(name, arguments):
    """Use CL's owner classifier first, then conservative read-only verbs."""
    from grant_agent.cl.frontier_effects import readonly
    classified = readonly(name, arguments)
    if classified is not None:
        return classified is True
    return name.endswith((".read", ".get", ".list", ".stat", ".state", ".describe",
                          ".search", ".inspect", ".index", ".load", ".now", ".limits",
                          ".history", ".versions", ".compiled", ".validate"))


def _driver_closure(output):
    """Copy and hash the exact local executor closure used by this run."""
    scripts = Path(__file__).resolve().parent
    pinned = Path(output).resolve() / "driver-closure"
    pinned.mkdir(parents=True, exist_ok=True)
    closure = {}
    names = ("c8_journey.py", "c8d_worker.py", "run_c8d.py", "run_c8_inception.py",
             "c8_scope.py", "c8_desktop_guard.py", "c8_headless.py")
    for name in names:
        path = scripts / name
        if not path.is_file() or path.is_symlink():
            raise UnsupportedRoute("C8 manual driver source is missing or redirected: " + name)
        payload = path.read_bytes()
        target = pinned / name
        shutil.copyfile(path, target)
        copied = target.read_bytes()
        if copied != payload:
            raise UnsupportedRoute("C8 driver changed while its run-local copy was pinned: " + name)
        closure[name] = {"sha256": hashlib.sha256(copied).hexdigest(), "path": str(target)}
    # Import the reusable execution modules only from their retained copies.
    sys.path.insert(0, str(pinned))
    sys.modules["c8_journey"] = sys.modules[__name__]
    import importlib
    for module_name in ("c8d_worker", "run_c8d", "c8_headless"):
        module = importlib.import_module(module_name)
        if Path(module.__file__).resolve() != (pinned / (module_name + ".py")).resolve():
            raise UnsupportedRoute("C8 runner imported outside its retained driver closure: " + module_name)
    return closure


def preflight_contract(output_root):
    """Execute fresh source-bound C8 adapter admission/refusal checks without a product session."""
    repository = Path(__file__).resolve().parents[1]
    allowed_output = Path("D:/NeyviaRuns").resolve()
    base = Path(output_root).resolve()
    try:
        base.relative_to(allowed_output)
    except ValueError as error:
        raise ValueError("C8 preflight output must remain under D:/NeyviaRuns") from error
    sys.path.insert(0, str(repository / "src"))
    run_dir = base / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    closure = _driver_closure(run_dir)
    from grant_agent.neyvia_inception import inventory, validate_bindings
    from grant_agent.neyvia_manuals import get_manual
    catalog = inventory()
    rows = {row["id"]: row for row in catalog["rows"]}

    def binding_for(identity, inputs):
        row = rows[identity]
        _, _, document = get_manual(row["manual"])
        procedure = document["chapters"][row["chapter"]]["procedures"][row["procedure"]]
        return {"id": identity, "sourceHash": row["sourceHash"], "journey": "manual", "inputs": inputs,
                "actions": [step["action"] for step in procedure["steps"] if "action" in step],
                "goals": [procedure["goal"]], "contracts": row["checkContracts"]}

    checks = {}
    bindings = json.loads((repository / "config/inception_journeys.json").read_text(encoding="utf-8"))
    catalog_check = validate_bindings(catalog, bindings)
    checks["complete-current-source-bindings"] = {"passed": catalog_check["valid"] and not catalog_check["unbound"],
                                                 "bindings": len(bindings), "rows": len(rows),
                                                 "invalid": len(catalog_check["errors"]), "unbound": len(catalog_check["unbound"])}
    ready = binding_for("workspace/files/create-and-confirm", {"path": "c8/proof.txt", "content": "C8 adapter preflight"})
    row, _ = prepare_manual_binding(ready, repository, rows.values())
    checks["ready-binding"] = {"passed": row["id"] == ready["id"], "sourceHash": row["sourceHash"]}

    focus = binding_for("adaptive-work/work/record-focus", {"workId": "c8-preflight", "text": "Scoped focus"})
    focus_row, _ = prepare_manual_binding(focus, repository, rows.values())
    checks["symbolic-effect-admission"] = {"passed": focus_row["id"] == focus["id"],
                                           "sourceHash": focus_row["sourceHash"]}
    schema = rows["adaptive-work/work/record-update-problem"]["inputs"]
    _check_supplied_inputs(schema, {"workId": "c8-preflight", "status": "open", "need": "inspect"}, {}, ["problemId"])
    checks["dynamic-required-slot-admission"] = {"passed": True}
    try:
        _check_supplied_inputs(schema, {"workId": "c8-preflight", "status": "open", "need": "inspect"}, {}, ["invented"])
    except UnsupportedRoute as error:
        checks["undeclared-dynamic-slot-refusal"] = {"passed": "required authored field" in str(error), "reason": str(error)}
    else:
        checks["undeclared-dynamic-slot-refusal"] = {"passed": False}
    try:
        _check_supplied_inputs(schema, {"workId": "c8-preflight", "problemId": "conflict", "status": "open", "need": "inspect"}, {"problemId": {}})
    except UnsupportedRoute as error:
        checks["supplied-deferred-overlap-refusal"] = {"passed": "cannot also be supplied" in str(error), "reason": str(error)}
    else:
        checks["supplied-deferred-overlap-refusal"] = {"passed": False}
    unresolved = binding_for("workspace/files/create-and-confirm", {"path": "c8/proof.txt"})
    unresolved["dynamicInputs"] = {"content": {"$result": "missing.content"}}
    try:
        prepare_manual_binding(unresolved, repository, rows.values())
    except UnsupportedRoute as error:
        checks["missing-setup-result-refusal"] = {"passed": "no declared setup result" in str(error), "reason": str(error)}
    else:
        checks["missing-setup-result-refusal"] = {"passed": False}

    try:
        prepare_manual_binding({**ready, "sourceHash": "0" * 64}, repository, rows.values())
    except UnsupportedRoute as error:
        checks["bad-hash-refusal"] = {"passed": "source hash is stale" in str(error), "reason": str(error)}
    else:
        checks["bad-hash-refusal"] = {"passed": False, "reason": "stale source hash was admitted"}

    deferred = {**binding_for("workspace/files/create-and-confirm", {"path": "c8/proof.txt"}),
                "deferredInputs": {"content": {"reason": "Requires owner-supplied content", "owner": "Paul",
                                                  "requiredReceipt": "owner content receipt"}}}
    try:
        prepare_manual_binding(deferred, repository, rows.values())
    except UnsupportedRoute as error:
        checks["deferred-input-refusal"] = {"passed": "Deferred authored inputs remain uncovered" in str(error), "reason": str(error)}
    else:
        checks["deferred-input-refusal"] = {"passed": False, "reason": "deferred input was admitted"}

    deferred_judges = binding_for("workspace/files/replace-and-read", {"path": "c8/proof.txt", "content": "replacement"})
    deferred_judges["deferredJudges"] = {"replace": {"reason": "Requires owner decision", "owner": "Paul",
                                                       "requiredReceipt": "owner decision receipt"}}
    try:
        prepare_manual_binding(deferred_judges, repository, rows.values())
    except UnsupportedRoute as error:
        checks["deferred-judge-refusal"] = {"passed": "Deferred authored judgements remain uncovered" in str(error), "reason": str(error)}
    else:
        checks["deferred-judge-refusal"] = {"passed": False, "reason": "deferred judge was admitted"}

    with tempfile.TemporaryDirectory(prefix="fixture-", dir=run_dir) as scratch:
        root = Path(scratch) / "candidate"
        validate_manual_fixtures({"files": [{"path": "c8/input.txt", "content": "seed"}]}, root,
                                 "http://127.0.0.1:48871")
        checks["scoped-fixture"] = {"passed": root.is_dir() and not (root / "c8/input.txt").exists()}
        try:
            validate_manual_fixtures({"files": [{"path": "../escape.txt", "content": "no"}]}, root,
                                     "http://127.0.0.1:48871")
        except UnsupportedRoute as error:
            checks["path-escape-refusal"] = {"passed": "escapes candidate state" in str(error), "reason": str(error)}
        else:
            checks["path-escape-refusal"] = {"passed": False, "reason": "escaping fixture was admitted"}
        try:
            validate_manual_fixtures({"files": [{"path": "large.png", "kind": "png", "width": 2049, "height": 32}]}, root,
                                     "http://127.0.0.1:48871")
        except UnsupportedRoute as error:
            checks["bounded-fixture-refusal"] = {"passed": "dimensions are outside" in str(error), "reason": str(error)}
        else:
            checks["bounded-fixture-refusal"] = {"passed": False, "reason": "oversized fixture was admitted"}

    passed = all(check["passed"] for check in checks.values())
    result = {"schema": "neyvia.c8.adapter-preflight.v1", "runId": run_dir.name,
              "preflightStatus": "C8-ADAPTER-PREFLIGHT-PASSED" if passed else "C8-ADAPTER-PREFLIGHT-FAILED",
              "passed": passed, "executionBoundary": "No browser, candidate product tool, network or external process",
              "checks": checks, "driverClosure": closure}
    receipt = write(run_dir / "result.json", result)
    return {**result, "receipt": str(receipt), "receiptSha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}


def prove_preflight_contract(output_root):
    """Run the authored contract twice, compile it and replay its real script."""
    repository = Path(__file__).resolve().parents[1]
    output = Path(output_root).resolve()
    if not output.is_relative_to(Path("D:/NeyviaRuns").resolve()):
        raise ValueError("C8 contract proof output must remain under D:/NeyviaRuns")
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(repository / "src"))
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.neyvia_manuals import unwrap
    state = repository / ".agent_control/INTN/c8-preflight" / uuid.uuid4().hex
    state.mkdir(parents=True, exist_ok=False)
    grants = ["terminal.exec", "neyvia.manual.run", "neyvia.manual.compile", "neyvia.manual.script.run"]
    gateway = NeyviaToolGateway(state, allow_mutations=True, permission_mode="full-access",
                                managed_capabilities=False, allowed_mutation_tools=grants)
    manual = gateway.call_native("neyvia.cl", {"lines": 'help("inception")'})
    if manual.get("ok") is not True:
        raise RuntimeError("The executable inception manual did not load")
    request = {"id": "inception", "chapter": "release", "procedure": "run-adapter-preflight",
               "inputs": {"stateRoot": "."}}
    rows = []
    for tool, arguments in [("neyvia.manual.run", request), ("neyvia.manual.run", request),
                            ("neyvia.manual.compile", {**request, "minRuns": 2}),
                            ("neyvia.manual.script.run", None)]:
        if arguments is None:
            arguments = {"scriptId": unwrap(rows[-1]["result"])["scriptId"], "inputs": request["inputs"]}
        result = gateway.call_native(tool, arguments, action_id="c8-preflight-" + uuid.uuid4().hex)
        rows.append({"tool": tool, "result": result})
        write(output / "receipt.json", {"rows": rows, "stateRoot": str(state),
                                       "boundary": "Actual authored CL procedure and compiled replay; no browser or product journey"})
        print(json.dumps({"tool": tool, "ok": result.get("ok"), "status": result.get("status")}), flush=True)
        if result.get("ok") is not True:
            raise RuntimeError("C8 authored preflight failed; inspect " + str(output / "receipt.json"))
    return {"passed": True, "verifiedRuns": 2, "compiledReplays": 1,
            "receipt": str(output / "receipt.json")}


def prepare_manual_binding(binding, stable_source, inventory_rows=None):
    """Resolve one binding against the pinned CL registry and reject unsafe routes."""
    from grant_agent.neyvia_inception import inventory
    from grant_agent.neyvia_manuals import get_manual

    pinned_src = (Path(stable_source).resolve() / "src").resolve()
    for function in (inventory, get_manual):
        try:
            Path(function.__code__.co_filename).resolve().relative_to(pinned_src)
        except (AttributeError, ValueError) as error:
            raise UnsupportedRoute("CL inventory/manual APIs were not loaded from the pinned stable source") from error

    rows = inventory_rows if inventory_rows is not None else inventory()["rows"]
    row = next((item for item in rows if item["id"] == binding.get("id")), None)
    if not row:
        raise UnsupportedRoute("Binding is absent from the pinned CL registry")
    if row.get("sourceHash") != binding.get("sourceHash"):
        raise UnsupportedRoute("Binding source hash is stale against the pinned CL registry")
    if row.get("kind") != "procedure":
        raise UnsupportedRoute("C8 manual adapter requires an authored procedure")
    deferred_inputs = _deferred_map(binding, "deferredInputs", row.get("inputs", {}).get("properties", {}))
    deferred_judges = _deferred_map(binding, "deferredJudges", row.get("judges", {}))
    if binding.get("contracts") != row.get("checkContracts"):
        raise UnsupportedRoute("Binding checks differ from the pinned CL registry")
    has_authored_checks = bool(row.get("checks") and row.get("checkContracts"))
    if binding.get("decisions"):
        raise UnsupportedRoute("A human/model judgement needs its actual decision authority")
    if row.get("judges") and set(row["judges"]) != set(deferred_judges):
        raise UnsupportedRoute("Every authored judgement must have an explicit deferred authority record")
    if binding.get("prerequisites"):
        raise UnsupportedRoute("Authored prerequisite is not proven by this isolated C8 run")

    allowed_fields = {"id", "sourceHash", "journey", "inputs", "decisions", "actions", "goals",
                      "toolAvailability", "scope", "files", "contracts", "prerequisites",
                      "deferredInputs", "deferredJudges", "setup", "dynamicInputs", "sourceCopies",
                      "deadlineSeconds",
                      "nativeOnly", "gitProjects", "priorReport"}
    unknown = sorted(set(binding) - allowed_fields)
    if unknown:
        raise UnsupportedRoute("C8 adapter does not admit additional host authority or fixture modes: " + ", ".join(unknown))

    digest, manual = get_manual(row["manual"])[1:]
    if digest != row["sourceHash"]:
        raise UnsupportedRoute("Pinned manual bytes differ from the inventory source hash")
    chapter = manual["chapters"].get(row["chapter"])
    if not chapter or row["procedure"] not in chapter["procedures"]:
        raise UnsupportedRoute("Pinned CL procedure is missing from its chapter")
    procedure = chapter["procedures"][row["procedure"]]
    if procedure.get("steps") != row.get("steps") or procedure.get("inputs") != row.get("inputs"):
        raise UnsupportedRoute("Pinned CL procedure differs from the inventory row")
    action_names = [step["action"] for step in procedure["steps"] if "action" in step]
    if binding.get("actions") != action_names or binding.get("goals") != [procedure["goal"]]:
        raise UnsupportedRoute("Binding action/goal metadata must exactly match the authored procedure")
    dynamic = binding.get("dynamicInputs", {})
    if not isinstance(dynamic, dict):
        raise UnsupportedRoute("dynamicInputs must map typed input fields to saved setup results")
    props = row.get("inputs", {}).get("properties", {})
    required = set(row.get("inputs", {}).get("required", []))
    for field, reference in dynamic.items():
        if field not in required or field in binding.get("inputs", {}) or field not in props:
            raise UnsupportedRoute("Dynamic value must fill one absent required authored input")
        if not isinstance(reference, dict) or set(reference) != {"$result"} or not isinstance(reference["$result"], str):
            raise UnsupportedRoute("Dynamic input must reference an actual saved setup result path")
        source = reference["$result"].split(".", 1)[0]
        if source not in {entry.get("save") for entry in binding.get("setup", [])}:
            raise UnsupportedRoute("Dynamic input references no declared setup result")
    _check_supplied_inputs(row["inputs"], binding.get("inputs", {}), deferred_inputs, dynamic)
    if deferred_inputs:
        details = "; ".join(f"{name}: {meta['reason']} (owner={meta['owner']}; receipt={meta['requiredReceipt']})"
                             for name, meta in deferred_inputs.items())
        raise UnsupportedRoute("Deferred authored inputs remain uncovered: " + details)
    if deferred_judges:
        details = "; ".join(f"{name}: {meta['reason']} (owner={meta['owner']}; receipt={meta['requiredReceipt']})"
                             for name, meta in deferred_judges.items())
        raise UnsupportedRoute("Deferred authored judgements remain uncovered: " + details)

    # These routes need an admitted desktop, external account, provider, network,
    # or child-process boundary that the C8 headless candidate intentionally lacks.
    forbidden = (".terminal.", ".cua.", ".remote.", ".browser.", ".nas.", ".gamedev.",
                 ".game_dev.", ".native.", ".web.", ".research.", ".image.generate",
                 ".mobile.build", ".mobile.install", ".app_sdk.build", ".app_sdk.install",
                 ".provider.auth", ".settings.propose", ".files.trash")
    from grant_agent.cl import effects
    has_effect_observer = False
    for step in procedure["steps"]:
        if "judge" in step or step.get("when"):
            raise UnsupportedRoute("Conditional or judgement steps require another admitted runner")
        if "action" not in step:
            raise UnsupportedRoute("Unsupported CL procedure step")
        action = chapter["actions"].get(step["action"])
        if not action:
            raise UnsupportedRoute("Procedure references a missing CL action")
        check = chapter["checks"].get(step["check"]) if step.get("check") else None
        if step.get("check") and not check:
            raise UnsupportedRoute("Procedure references a missing CL check")
        tool_names = [action.get("tool", "")]
        if check:
            tool_names.append(check.get("tool", ""))
        action_name = action.get("tool", "")
        readonly = _readonly_tool(action_name, step.get("args", {}))
        if not readonly:
            # References are still symbolic at admission. The real CL host
            # constructs and verifies owning effects after resolving inputs.
            if not effects.supported(action_name, step.get("args", {})):
                raise UnsupportedRoute("Mutating action has no registered CL owner effect observer: " + action_name)
            has_effect_observer = True
        for tool_name in tool_names:
            if not isinstance(tool_name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_-]*)+", tool_name):
                raise UnsupportedRoute("Only typed Neyvia tools are admitted")
            if any(part in ("." + tool_name) for part in forbidden):
                raise UnsupportedRoute("Tool requires an external, process or owner-authority route: " + tool_name)

    if not has_authored_checks and not has_effect_observer:
        raise UnsupportedRoute("Procedure has neither authored checks nor a CL owning effect observer")

    # Only bounded data setup is accepted. Its actions still pass the same
    # source/action schema checks at execution; authority-bearing recipes stay blocked.
    if "deadlineSeconds" in binding and (type(binding["deadlineSeconds"]) is not int or not 1 <= binding["deadlineSeconds"] <= 600):
        raise UnsupportedRoute("deadlineSeconds must be an integer from 1 through 600")
    if binding.get("nativeOnly") or binding.get("gitProjects") or binding.get("priorReport"):
        raise UnsupportedRoute("Binding requires an unavailable native, Git, or historical-report authority")
    if set(binding) & {"c8e", "c8eEffect", "effectModule", "speechFixture", "videoFixture",
                       "ownerApproval", "ownerApprove", "adapter", "readiness"}:
        raise UnsupportedRoute("Binding requests an auxiliary adapter outside the pinned C8 execution closure")
    if binding.get("setup") and (not isinstance(binding["setup"], list) or len(binding["setup"]) > 8):
        raise UnsupportedRoute("Setup must be a typed list of at most eight authored actions")
    if binding.get("dynamicInputs") and not isinstance(binding["dynamicInputs"], dict):
        raise UnsupportedRoute("dynamicInputs must map typed input fields to saved setup results")
    if binding.get("sourceCopies"):
        raise UnsupportedRoute("sourceCopies require the bounded source-copy authoring contract, which is not yet admitted")
    for entry in binding.get("setup", []):
        if not isinstance(entry, dict) or set(entry) - {"tool", "args", "save"}:
            raise UnsupportedRoute("Setup entries may contain only an authored tool, arguments and save name")
        action = next((item for item in chapter["actions"].values() if item.get("tool") == entry.get("tool")), None)
        if not action:
            raise UnsupportedRoute("Setup tool is not an action in the pinned CL chapter")
        tool_name = action["tool"]
        if any(part in ("." + tool_name) for part in forbidden):
            raise UnsupportedRoute("Setup tool requires an external, process or owner-authority route: " + tool_name)
        if not (_readonly_tool(tool_name, entry.get("args", {})) or effects.supported(tool_name, entry.get("args", {}))):
            raise UnsupportedRoute("Setup tool has no read-only classification or CL owner effect observer: " + tool_name)
    setup_saves = [entry.get("save") for entry in binding.get("setup", [])]
    if any(not isinstance(name, str) or not name for name in setup_saves) or len(set(setup_saves)) != len(setup_saves):
        raise UnsupportedRoute("Every setup action needs a unique named result")
    if any(reference["$result"].split(".", 1)[0] not in setup_saves for reference in dynamic.values()):
        raise UnsupportedRoute("Dynamic input references no declared setup result")

    return row, manual


def validate_manual_fixtures(binding, root, candidate_url):
    """Admit only fresh, small fixture inputs below this candidate's state root."""
    from c8d_worker import expand

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    entries = binding.get("files", [])
    if not isinstance(entries, list) or len(entries) > 16:
        raise UnsupportedRoute("Manual file fixtures must be a bounded list")
    allowed = {"path", "content", "kind", "width", "height", "text", "seconds"}
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - allowed or not isinstance(entry.get("path"), str):
            raise UnsupportedRoute("Manual file fixture has unsupported fields")
        raw = Path(expand(entry["path"], argparse.Namespace(state_root=str(root), candidate_url=candidate_url, binding=binding)))
        raw = raw if raw.is_absolute() else root / raw
        lexical = Path(os.path.abspath(raw))
        try:
            lexical.relative_to(root)
        except ValueError as error:
            raise UnsupportedRoute("Manual fixture path escapes candidate state") from error
        cursor = root
        for part in lexical.relative_to(root).parts[:-1]:
            cursor = cursor / part
            if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
                raise UnsupportedRoute("Manual fixture path traverses a link or junction")
        target = lexical.resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise UnsupportedRoute("Manual fixture path escapes candidate state") from error
        # Existing paths and links could redirect the fixture writer into
        # pre-existing state, so only new leaves under real directories pass.
        if target.exists() or target.is_symlink():
            raise UnsupportedRoute("Manual fixture refuses to overwrite existing candidate state")
        kind = entry.get("kind")
        if kind not in (None, "png", "wav", "pdf"):
            raise UnsupportedRoute("Unsupported authored fixture kind")
        if kind == "png" and (type(entry.get("width", 64)) is not int or type(entry.get("height", 48)) is not int
                               or not 1 <= entry.get("width", 64) <= 2048 or not 1 <= entry.get("height", 48) <= 2048):
            raise UnsupportedRoute("PNG fixture dimensions are outside the bounded 1..2048 range")
        if kind == "wav" and (type(entry.get("seconds", 0.1)) not in (int, float) or not 0 < entry.get("seconds", 0.1) <= 10):
            raise UnsupportedRoute("WAV fixture duration exceeds the bounded 10-second limit")
        if kind == "pdf" and (not isinstance(entry.get("text", ""), str) or len(entry.get("text", "").encode("ascii", errors="ignore")) > 4096):
            raise UnsupportedRoute("PDF fixture text exceeds the bounded size")
        content = entry.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
            raise UnsupportedRoute("Manual text fixture exceeds the bounded input size")
        total += len(content.encode("utf-8"))
    if total > 262144:
        raise UnsupportedRoute("Manual fixtures exceed the bounded input size")


class Journey:
    def __init__(self, args):
        self._closed = False
        print("C8 stage: pinned worker starting", flush=True)
        self.args, self.directory = args, Path(args.output).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        stable = Path(args.stable_source).resolve()
        workspace = Path(__file__).resolve().parents[1]
        if not (stable.is_relative_to(workspace / ".agent_control") or stable.is_relative_to(run_root(workspace))) or stable == workspace:
            raise ValueError("Stable source must be a separate task-local scratch copy")
        sys.path.insert(0, str(stable / "src"))
        # Imports are deliberately from the pinned copy, never candidate source.
        from grant_agent.perception_browser import BrowserSessions, DOM, origin
        from grant_agent.proof_credential_guard import install
        install(self.directory)
        self.stable = stable
        self.dom_code, self.origin = DOM, origin
        self.candidate = Candidate(args.candidate_url, args.session_cookies)
        print("C8 stage: scratch local session ready", flush=True)
        self.events, self.t16, self.t18 = [], [], []
        self.receipt_seq = 0
        self.projection = BrowserSessions()
        # BrowserSessions' DOM and fresh-revision guard remain the production
        # implementation. Opening creates a fresh, exclusively headless browser.
        self.projection.run("shutdown")
        print("C8 stage: T18 session ready", flush=True)
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        print("C8 stage: Playwright transport ready", flush=True)
        if os.environ.get("NEYVIA_C8_ENGINE") == "obscura":
            import secrets
            import socket
            import subprocess
            from urllib.request import urlopen
            executable = Path(os.environ["NEYVIA_OBSCURA_EXE"]).resolve()
            engine_port = int(os.environ["NEYVIA_C8_ENGINE_PORT"])
            if engine_port not in assigned_ports():
                raise ValueError("Obscura requires an explicitly assigned C8 port")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", engine_port))
            token = secrets.token_urlsafe(36)
            self.engine_log = (self.directory / "obscura.log").open("wb")
            engine_env = {key: value for key, value in os.environ.items() if not any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "AUTH_FILE"))}
            profile = self.directory / "engine-home"
            profile.mkdir(exist_ok=True)
            engine_env.update({key: str(profile / key.lower()) for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")})
            for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
                Path(engine_env[key]).mkdir(exist_ok=True)
            engine_env["OBSCURA_CDP_TOKEN"] = token
            self.engine = subprocess.Popen([str(executable), "serve", "--host", "127.0.0.1", "--port", str(engine_port), "--user-agent", "NeyviaAgent/1.0 (Automation; Obscura)", "--max-connections", "8", "--allow-private-network"], env=engine_env, stdout=self.engine_log, stderr=self.engine_log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            endpoint = f"http://127.0.0.1:{engine_port}"
            for attempt in range(120):
                if self.engine.poll() is not None:
                    raise RuntimeError("Owned Obscura process exited")
                try:
                    with urlopen(Request(endpoint + "/json/version", headers={"Authorization": "Bearer " + token}), timeout=.5):
                        break
                except OSError:
                    time.sleep(.25)
            else:
                raise TimeoutError("Owned Obscura did not become ready")
            self.browser = self.playwright.chromium.connect_over_cdp(endpoint, headers={"Authorization": "Bearer " + token})
            write(self.directory / "engine.json", {"engine": "obscura", "executable": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "port": engine_port})
        else:
            raise UnsupportedRoute("C8 requires an explicitly configured Obscura engine; Chromium fallback is disabled")
        print("C8 stage: owned browser transport ready", flush=True)
        self.context = self.browser.new_context(accept_downloads=False, service_workers="allow", viewport={"width": 1280, "height": 900})
        from c8_headless import block_service_workers
        block_service_workers(self.context)
        granted = origin(args.candidate_url)
        def route(request):
            try:
                permitted = origin(request.request.url) == granted
            except ValueError:
                permitted = False
            request.continue_() if permitted else request.abort()
        self.context.route("**/*", route)
        self.context.add_cookies(self.candidate.cookies())
        self.page = self.context.new_page()
        self.page.emulate_media(reduced_motion="reduce")
        self.page_errors = []
        self.page_error_details = []
        def page_error(error):
            self.page_errors.append(str(error))
            self.page_error_details.append({"message": str(error), "stack": str(error.stack), "url": self.page.url})
            write(self.directory / "page-errors.json", self.page_error_details)
        self.page.on("pageerror", page_error)
        self.sid = "c8-" + args.journey
        self.projection.sessions[self.sid] = {"page": self.page, "context": self.context, "origin": granted, "revision": None}
        try:
            self.page.goto(args.candidate_url + "/control?ui=next", wait_until="domcontentloaded", timeout=90000)
            try:
                self.page.locator(".nx-root").wait_for(timeout=45000)
            except Exception:
                if not self.page.get_by_role("button", name="Try again", exact=True).is_visible():
                    raise
                self.proof("t18", {"source": "T18.boot-recovery", "observation": self.projection._observe(self.sid)})
                self.action("Try again")
                self.page.locator(".nx-root").wait_for(timeout=45000)
        except Exception:
            write(self.directory / "boot-failure.json", {"url": self.page.url, "text": self.page.locator("body").inner_text(), "pageErrors": self.page_errors})
            self.screenshot("boot-failure")
            self.close()
            raise
        # Binding a production BrowserSessions session gives T18's exact DOM
        # observer/revision verifier access to the same headless page. No native driver is instantiated.
        print("C8 stage: candidate application rendered", flush=True)
        self.page.locator(".nx-boot").wait_for(state="hidden", timeout=20000) if self.page.locator(".nx-boot").count() else None
        try:
            self.page.get_by_role("button", name="Skip setup", exact=True).wait_for(timeout=6000)
            self.action("Skip setup")
        except Exception as error:
            if "Timeout" not in str(error):
                raise

    def proof(self, kind, value, success=True):
        self.receipt_seq += 1
        value = {**value, "schema": "neyvia.inception.proof.v1", "runId": self.args.run_id,
                 "journey": self.args.journey, "target": self.args.candidate_url, "kind": kind}
        path = write(self.directory / f"{self.receipt_seq:03d}-{kind}.json", value)
        row = {"fresh": True, "success": success, "target": self.args.candidate_url,
               "proof": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        getattr(self, kind).append(row)
        return value

    @staticmethod
    def structured(value):
        if value.get("isError"):
            raise RuntimeError(json.dumps(value))
        return value.get("structuredContent") or json.loads(next(item["text"] for item in value["content"] if item["type"] == "text"))

    def observe(self):
        # BrowserSessions methods are invoked on the page-owning thread; a
        # cross-thread Playwright object must never enter its normal executor.
        data = self.projection._observe(self.sid)
        self.proof("t18", {"source": "T18.DOM", "stableSource": str(self.stable), "observation": data})
        return data

    def element(self, name, role=None):
        data = self.observe()
        choices = [row for row in data["elements"] if row["name"] == name and (role is None or row["role"] == role)]
        if len(choices) != 1:
            raise RuntimeError(f"Expected one visible {name!r}; found {len(choices)}")
        return data, choices[0]

    def action(self, name, action="click", value="", role=None):
        if name != "Skip setup" and self.page.locator(".nx-onb-scrim").is_visible():
            self.action("Skip setup")
            self.page.locator(".nx-onb-scrim").wait_for(state="hidden", timeout=15000)
        for attempt in range(8):
            if attempt:
                self.page.wait_for_timeout(150)
            data = self.projection._observe(self.sid)
            choices = [e for e in data["elements"] if e["name"] == name and (role is None or e["role"] == role)]
            if len(choices) != 1:
                raise RuntimeError(f"Expected one visible {name!r}; found {len(choices)}")
            element = choices[0]
            result = self.projection._action(self.sid, data["revision"], element["id"], action, value)
            if result.get("ok"):
                break
            if result.get("status") != "stale_projection":
                raise RuntimeError(str(result))
            write(self.directory / f"stale-refusal-{self.receipt_seq}-{attempt}.json",
                  {"effect": "refused-before-dispatch", "result": result, "name": name})
        else:
            raise RuntimeError("Page stayed unstable after eight fresh observations")
        self.proof("t18", {"source": "T18.action", "name": name, "action": action, "result": result})

    def screenshot(self, name="final"):
        path = self.directory / (name + ".jpg")
        self.page.screenshot(path=str(path), type="jpeg", quality=65, full_page=True)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def manual_checks(self, inputs):
        from grant_agent.neyvia_manuals import resolve, expect
        checks = []
        for identity, contract in self.args.binding["contracts"].items():
            tool = contract["tool"].removeprefix("neyvia.")
            if tool not in {"notes.read", "settings.get"}:
                raise ValueError("No authored read-only check route for " + tool)
            arguments = resolve(contract["args"], inputs, {}, self.directory)
            observed = self.candidate.tool(tool, arguments)
            checks.append({"id": identity, "passed": expect(observed, contract["expect"], inputs, {}, self.directory),
                           "contract": contract, "observed": observed})
        return checks

    def reload(self):
        self.page.reload(wait_until="domcontentloaded")
        self.page.locator(".nx-root").wait_for(timeout=45000)
        # Skip setup dismisses this visit. An unfinished setup can reopen on
        # reload, so exercise its real dismissal before waiting on the app.
        try:
            self.page.get_by_role("button", name="Skip setup", exact=True).wait_for(timeout=6000)
        except Exception as error:
            if "Timeout" not in str(error):
                raise
        else:
            self.action("Skip setup")
            self.page.locator(".nx-onb-scrim").wait_for(state="hidden", timeout=15000)

    def run(self):
        print("C8 stage: journey navigation", flush=True)
        if self.args.journey == "probe":
            self.action("Apps")
            return {"observation": self.observe(), "screenshot": self.screenshot()}
        if self.args.journey == "manual":
            raise UnsupportedRoute("Manual contracts use the existing source-bound C8d worker")
        if self.args.journey == "notes":
            self.open_notes()
        else:
            # The existing two-sided pane command is the supported entry to
            # canonical Settings. The sidebar menu intentionally opens classic.
            self.candidate.tool("pane.show", {"kind": "settings", "target": "look"})
        if self.args.journey == "notes":
            folder = Path(getattr(self.args, 'state_root', str(self.directory))) / "notes"
            self.candidate.tool("notes.folder", {"folder": str(folder)})
            note = self.candidate.tool("notes.write", {"path": self.args.binding["inputs"]["path"], "body": "# C8 before\nDisposable existing note.\n"})
            self.reload()
            self.open_notes()
            self.page.get_by_role("button", name="C8 before", exact=False).wait_for(timeout=20000)
            data = self.observe()
            choices = [e for e in data["elements"] if e["role"] == "button" and "C8 before" in e["name"]]
            if len(choices) != 1:
                raise RuntimeError("Existing scratch note not uniquely visible")
            self.action(choices[0]["name"])
            self.page.get_by_role("textbox", name="Note text", exact=True).wait_for()
            body = self.args.binding["inputs"]["body"]
            inputs = {"path": note["path"], "body": body, "expectedModified": note["modified"]}
            self.action("Note text", "fill", body, "textbox")
            self.page.get_by_role("status").filter(has_text="Saved").wait_for(timeout=15000)
            self.action("Pin")
            self.page.get_by_role("button", name="Unpin", exact=True).wait_for(timeout=10000)
            self.reload()
            self.open_notes()
            self.page.get_by_role("button", name="C8 saved", exact=False).wait_for(timeout=15000)
            # Explicit postconditions observe candidate state, never stable state.
            observed = self.candidate.tool("notes.read", {"path": note["path"]})
            checks = self.manual_checks(inputs)
            goal = {"passed": all(c["passed"] for c in checks) and "C8 saved" in self.observe()["text"], "observed": {"persistedAfterReload": observed, "visible": "C8 saved"}}
            return {"inputs": inputs, "decisions": {"replace-note": "replace"}, "checks": checks, "goals": [goal], "artifacts": [self.screenshot()]}
        self.page.get_by_role("heading", name="Look", exact=True).wait_for(timeout=20000)
        # Change only the disposable candidate's theme through the rendered headless UI.
        self.action("Night Green")
        deadline = time.monotonic() + 10
        while True:
            observed = self.candidate.tool("settings.get")
            if observed["settings"]["theme"] == "night-green" or time.monotonic() >= deadline:
                break
            self.page.wait_for_timeout(100)
        self.observe()
        passed = observed.get("network", {}).get("enforced") is True
        theme = observed["settings"]["theme"]
        self.reload()
        self.page.locator('.nx-root[data-nx-theme="night"]').wait_for(timeout=20000)
        self.candidate.tool("pane.show", {"kind": "settings", "target": "look"})
        self.page.get_by_role("heading", name="Look", exact=True).wait_for(timeout=20000)
        passed = passed and theme == "night-green"
        return {"inputs": {}, "checks": self.manual_checks({}),
                "goals": [{"passed": passed and "Look" in self.observe()["text"], "observed": {"visible": "Look", "settings": observed}}], "artifacts": [self.screenshot()]}

    def open_notes(self):
        self.action("Apps")
        choices = [e for e in self.observe()["elements"] if e["role"] == "button" and e["name"].startswith("Documents\n")]
        if len(choices) != 1:
            raise RuntimeError("Documents suite not uniquely visible")
        self.action(choices[0]["name"])
        self.page.get_by_role("button", name="Notes", exact=False).wait_for(timeout=15000)
        choices = [e for e in self.observe()["elements"] if e["role"] == "button" and (e["name"] == "Notes" or e["name"].startswith("Notes\n"))]
        if len(choices) != 1:
            raise RuntimeError("Notes app not uniquely visible in Documents suite")
        self.action(choices[0]["name"])

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        if hasattr(self, "browser"):
            self.browser.close()
        if hasattr(self, "playwright"):
            self.playwright.stop()
        if hasattr(self, "projection"):
            self.projection.sessions.clear()
            self.projection.close()
        if hasattr(self, "engine") and self.engine.poll() is None:
            self.engine.terminate()
            try:
                self.engine.wait(timeout=10)
            except Exception:
                self.engine.kill()
        if hasattr(self, "engine_log"):
            self.engine_log.close()



def main():
    if "--prove-preflight" in sys.argv:
        parser = argparse.ArgumentParser(description="Execute the authored C8 contract and its compiled replay")
        parser.add_argument("--prove-preflight", action="store_true")
        parser.add_argument("--output", required=True)
        args = parser.parse_args()
        print(json.dumps(prove_preflight_contract(args.output)))
        return 0
    if "--preflight" in sys.argv:
        preflight = argparse.ArgumentParser(description="Run source-bound C8 adapter preflight without launching a product session")
        preflight.add_argument("--preflight", action="store_true")
        preflight.add_argument("--output", required=True)
        args = preflight.parse_args()
        try:
            result = preflight_contract(args.output)
        except Exception as error:
            result = {"schema": "neyvia.c8.adapter-preflight.v1", "preflightStatus": "C8-ADAPTER-PREFLIGHT-FAILED",
                      "passed": False, "error": str(error)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("passed") is True else 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-source", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--journey", choices=["notes", "settings", "probe", "manual"], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate-state", required=True, help="Fresh state root selected by the controller for this binding")
    parser.add_argument("--session-input", action="store_true", help="Receive the scratch session in memory over stdin")
    args = parser.parse_args()
    envelope = json.load(sys.stdin) if args.session_input else {}
    args.session_cookies = envelope.get("cookies")
    args.binding = envelope.get("binding", {})
    selected_state = Path(args.candidate_state).resolve()
    if not selected_state.is_relative_to(run_root(Path(__file__).resolve().parents[1]) / args.run_id):
        raise ValueError("Candidate state must belong to this exact disposable C8 run")
    args.state_root = str(selected_state)
    if args.journey != "probe" and not args.binding:
        raise ValueError("Authored source-bound journey binding is required")
    if args.journey == "manual":
        stable_source = Path(args.stable_source).resolve()
        if not stable_source.is_dir():
            raise ValueError("Manual route requires the pinned stable source tree")
        sys.path.insert(0, str(stable_source / "src"))
        try:
            args.binding["row"], args.binding["manual"] = prepare_manual_binding(args.binding, stable_source)
        except UnsupportedRoute as error:
            # A policy refusal is an uncovered route, not a product failure.
            Path(args.output).mkdir(parents=True, exist_ok=True)
            write(Path(args.output) / "result.json", {
                "id": args.binding.get("id"), "sourceHash": args.binding.get("sourceHash"),
                "journey": args.journey, "executionMode": "headless", "status": "blocked",
                "coverageGap": "unsupported-or-unauthorized-route", "error": str(error),
                "startedAt": time.time(), "finishedAt": time.time(),
            })
            print(json.dumps({"journey": args.journey, "status": "blocked", "error": str(error)}))
            return 0
    if os.environ.get("NEYVIA_C8_ENGINE") != "obscura":
        Path(args.output).mkdir(parents=True, exist_ok=True)
        write(Path(args.output) / "result.json", {
            "id": args.binding.get("id"), "sourceHash": args.binding.get("sourceHash"),
            "journey": args.journey, "executionMode": "headless", "status": "blocked",
            "coverageGap": "obscura-engine-not-configured",
            "error": "C8 requires the explicit Obscura engine; Chromium fallback is disabled",
            "startedAt": time.time(), "finishedAt": time.time(),
        })
        print(json.dumps({"journey": args.journey, "status": "blocked", "error": "Obscura engine unavailable"}))
        return 0
    driver_closure = None
    if args.journey == "manual":
        try:
            driver_closure = _driver_closure(args.output)
        except (OSError, ImportError, UnsupportedRoute) as error:
            Path(args.output).mkdir(parents=True, exist_ok=True)
            write(Path(args.output) / "result.json", {
                "id": args.binding.get("id"), "sourceHash": args.binding.get("sourceHash"),
                "journey": args.journey, "executionMode": "headless", "status": "blocked",
                "coverageGap": "unpinned-driver-source", "error": str(error),
                "startedAt": time.time(), "finishedAt": time.time(),
            })
            return 0
        try:
            validate_manual_fixtures(args.binding, Path(args.state_root), args.candidate_url)
        except UnsupportedRoute as error:
            write(Path(args.output) / "result.json", {
                "id": args.binding.get("id"), "sourceHash": args.binding.get("sourceHash"),
                "journey": args.journey, "executionMode": "headless", "status": "blocked",
                "coverageGap": "unsafe-fixture", "error": str(error),
                "startedAt": time.time(), "finishedAt": time.time(),
            })
            return 0
    import faulthandler
    faulthandler.dump_traceback_later(60, repeat=True)
    from c8_scope import install as install_socket_scope
    install_socket_scope()
    started = time.time()
    worker = None
    result = {"executionMode": "headless", "nativeDriver": "blocked pending isolated C11 desktop", "status": "failed", "startedAt": started, "journey": args.journey}
    try:
        if args.journey == "manual":
            from run_c8d import fixture_files
            fixture_files(args.binding, Path(args.state_root), args.candidate_url)
            from c8d_worker import ManualJourney
            worker = ManualJourney.__new__(ManualJourney)
        else:
            worker = Journey.__new__(Journey)
        worker.__init__(args)
        journey_result = worker.execute() if args.journey == "manual" else worker.run()
        result.update(journey_result, status="passed")
        if args.journey == "manual":
            result["driverClosure"] = driver_closure
        if args.journey != "probe" and any(check.get("passed") is not True for check in result.get("checks", []) + result.get("goals", [])):
            if result.get("status") != "blocked":
                result.update(status="failed", error="Authored manual check or observed goal failed")
        result.update(t16=worker.t16, t18=worker.t18, pageErrors=worker.page_errors)
        if worker.page_errors:
            result.update(status="failed", error="Candidate page raised an unhandled error")
    except Exception as error:
        import traceback
        result.update(error=str(error), traceback=traceback.format_exc())
        if worker:
            result.update(t16=getattr(worker, "t16", []), t18=getattr(worker, "t18", []))
            if hasattr(worker, "page") and not worker.page.is_closed():
                try:
                    result["artifacts"] = [worker.screenshot("failure")]
                except Exception as capture_error:
                    result["captureError"] = str(capture_error)
    finally:
        if worker:
            try:
                worker.close()
            except Exception as cleanup_error:
                result.update(status="failed", cleanupError=str(cleanup_error))
        result.update(finishedAt=time.time(), durationMs=round((time.time() - started) * 1000))
        write(Path(args.output) / "result.json", result)
        faulthandler.cancel_dump_traceback_later()
    print(json.dumps({key: result.get(key) for key in ("journey", "status", "error", "durationMs")}))
    return 0 if result["status"] in {"passed", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
