"""Adversarial model-route and callable-compiler feature journeys.

Explicit cache paths and workspace stores keep these proofs independent from
installed accounts.  Every binding is an exercised production owner, rather
than a repeated baseline self-check or schema admission witness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

TEXT = {"empty": "", "huge": "neutral " * 18000, "unicode": "雪🙂e\u0301\u202e العربية"}
P = "proofs-c.models."


def _require(value, message):
    if not value:
        raise AssertionError(message)


@contextmanager
def _deny_read(path):
    """Actual Windows share denial, no ACL or machine configuration changes."""
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "fixture sharing handle unavailable")
    try:
        try:
            path.read_bytes()
        except PermissionError:
            pass
        else:
            raise AssertionError("fixture file was not actually denied")
        yield
    finally:
        kernel.CloseHandle(handle)


def _catalog(root, category):
    from .model_catalog import build_model_catalog
    text = TEXT.get(category, "fixture")
    path = root / "observed.json"
    bootstrap = build_model_catalog(root, cache_paths=[])
    baseline = {row["id"]: row for row in bootstrap["models"]}
    models = [] if category == "empty" else [
        {"slug": "fixture.model", "display_name": text, "description": text,
         "supported_reasoning_levels": [{"effort": "high"}, {"effort": "high"}, {"effort": "max"}]},
        {"slug": "gpt-6-astra", "supported_in_api": False, "supported_reasoning_levels": []},
        {"slug": "gpt-5.3-obsolete", "status": "deprecated"}, None, {}]
    payload = {"fetched_at": "2020-01-01T00:00:00Z", "client_version": text, "models": models}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if category == "permissions":
        with _deny_read(path):
            result = build_model_catalog(root, cache_paths=[path])
        _require(result["models"] == bootstrap["models"] and result["sourceStatus"] == "bootstrap", "denied cache invents observed models")
    elif category == "interrupted":
        script = "import sys,time;from pathlib import Path;p=Path(sys.argv[1]);f=p.open('w',encoding='utf-8');f.write('{\\\"models\\\":[');f.flush();Path(sys.argv[2]).write_text('ready');time.sleep(30)"
        marker = root / "partial.ready"
        child = subprocess.Popen([sys.executable, "-c", script, str(path), str(marker)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            _require(marker.exists(), "partial writer did not establish real interrupted state")
            child.kill(); child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
        result = build_model_catalog(root, cache_paths=[path])
        _require(result["models"] == bootstrap["models"] and child.returncode != 0, "killed invalid writer invented catalog detection")
    elif category == "concurrency":
        # Multiple live readers of an immutable cache may not alter caller bytes.
        before = path.read_bytes()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: build_model_catalog(root, cache_paths=[path]), range(24)))
        _require(path.read_bytes() == before, "parallel observations changed source cache")
        projections = [r["models"] for r in results]
        _require(all(r == projections[0] for r in projections), "parallel catalog observations diverged")
        result = results[0]
    elif category == "stale":
        newer = root / "newer.json"
        newer.write_text(json.dumps({"fetched_at": "2099-01-01T00:00:00Z", "client_version": "new-version", "models": [{"slug": "gpt-6-astra", "supported_in_api": True, "reasoningEfforts": ["high"]}]}), encoding="utf-8")
        result = build_model_catalog(root, cache_paths=[newer, path])
        astra = next(r for r in result["models"] if r["id"] == "gpt-6-astra")
        _require(astra["selectable"] and astra["reasoningEfforts"] == ["high"] and astra["source"] == str(newer), "stale cache overrode newer observed restriction")
        _require(result["sourceAgeSeconds"] == 0 and not result["sourceStale"], "future cache age became negative")
    else:
        result = build_model_catalog(root, cache_paths=[path])
    actual = {row["id"]: row for row in result["models"]}
    _require(set(baseline) <= set(actual), "cache removed bootstrap family identities")
    _require(result["selectableModels"] == [r for r in result["models"] if r["selectable"]], "selectable projection changed")
    if category not in {"empty", "permissions", "interrupted", "stale"}:
        _require(actual["fixture.model"]["reasoningEfforts"] == ["high", "max"] and actual["fixture.model"]["description"] == text.strip(), "observed model metadata lost")
        _require(not actual["gpt-6-astra"]["selectable"] and actual["gpt-6-astra"]["reasoningEfforts"] == [], "explicit model restriction was ignored")
    return {"models": len(actual), "sourceStatus": result["sourceStatus"], "sourceBytes": path.stat().st_size,
            "observed": "Explicit local caches, actual parser, bootstrap identity, restrictions, chronology and projection"}


def _routing(root, category):
    from .model_portfolio import build_model_portfolio, classify_task_lane, recommended_route
    from .model_routing import parse_route_dictation
    from .launch_recommendation import build_launch_runtime_recommendation
    text = TEXT[category]
    if category == "empty":
        blank = parse_route_dictation("", default_runtime="hermes")
        _require(blank["status"] == "empty" and blank["routeOverrides"] == [] and blank["sourceText"] == "", "empty dictation invented route assignments")
    _require(classify_task_lane(text, fallback="caller-lane") == "caller-lane", "neutral input discarded fallback")
    for task, expected in (("verify architecture small " + text, "verification"), ("architecture small " + text, "deep"), ("small " + text, "routine")):
        _require(classify_task_lane(task) == expected, "task-first lane precedence changed")
    for provider, runner, profile in ((False, False, False), (False, True, True), (True, True, False), (True, True, True)):
        portfolio = build_model_portfolio(provider_presence={"kimi-code": provider, "openai-codex": True}, runtime_presence={"kimi-code": runner, "kimi-code-profile": profile, "codex": True, text: True})
        expected = "kimi-code" if provider and runner and profile else "openai-codex"
        _require(recommended_route(portfolio, "routine")["provider"] == expected, "unproved Kimi readiness outranked observed route")
        _require(recommended_route(portfolio, "deep")["provider"] == expected and not portfolio["autoFallback"], "route silently substituted provider")
    dictated = text + ", GPT-5.6 Sol low for planner, GPT-5.6 Luna high for verifier, GPT-5.6 Sol high for planner, no, x high"
    receipt = parse_route_dictation(dictated, default_runtime="hermes")
    routes = {row["role"]: row for row in receipt["routeOverrides"]}
    _require(routes["planner"]["model"] == "gpt-5.6-sol" and routes["planner"]["effort"] == "xhigh" and routes["verifier"]["model"] == "gpt-5.6-luna", "last role/correction lost")
    # Invoke the actual CLI owner in an isolated interpreter, not its parser only.
    cli_script = "import argparse,sys;sys.stdout.reconfigure(encoding='utf-8');from grant_agent.cli import cmd_route_dictation;raise SystemExit(cmd_route_dictation(argparse.Namespace(text=sys.stdin.buffer.read().decode('utf-8'),default_runtime='hermes',preserve_models=False)))"
    child = subprocess.run([sys.executable, "-c", cli_script], input=dictated, capture_output=True, text=True, encoding="utf-8", timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _require(child.returncode == 0 and json.loads(child.stdout) == receipt, "actual route CLI differs from returned parser receipt")
    launch = build_launch_runtime_recommendation(objective=text + " Use Cursor with Grok 4.5", workspace_default_runtime="hermes")
    _require((launch["runtime"], launch["modelProvider"], launch["model"]) == ("cursor", "cursor", "grok-4-5"), "explicit launch request substituted")
    decisions = {row["role"]: row for row in launch["routeDecisionRows"]}
    _require(decisions["context-reader"]["model"] == "receipt-bound-cache" and all(decisions[r]["model"] == "gpt-5.6-sol" for r in ("planner", "verifier")), "independent/context routes lost")
    return {"dictationCharacters": len(dictated), "cliExit": child.returncode, "lanes": [r["laneId"] for r in portfolio["lanes"]], "launchModel": launch["model"]}


def _mode(root, category):
    from .modes import ModeRegistry
    text = TEXT.get(category, "changed")
    path = root / "modes.json"
    fields = {"persona": text, "max_tokens": 1301, "max_handoffs": 7, "max_runtime_seconds": 313, "parallel_agents": 3, "merge_policy": "consensus", "description": text}
    path.write_text(json.dumps({"balanced": fields, "named": {**fields, "max_tokens": 9183}}, ensure_ascii=False), encoding="utf-8")
    registry = ModeRegistry(path)
    _require(registry.get("named").max_tokens == 9183 and vars(registry.get(text)) == {"name": "balanced", **fields}, "mode config or caller fallback changed")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            observed = list(pool.map(lambda _: vars(registry.get("named")), range(24)))
        _require(all(row == {"name": "named", **fields, "max_tokens": 9183} for row in observed), "Concurrent mode observations mixed selected-root fields")
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        intact = path.read_bytes()
        process = subprocess.run([sys.executable, "-c", "from pathlib import Path; import os,sys; p=Path(sys.argv[1]); f=p.open('wb'); f.write(b'{\\\"balanced\\\":'); f.flush(); os.fsync(f.fileno()); os._exit(23)", str(path)], capture_output=True, timeout=20, **hidden_windows_subprocess_kwargs())
        _require(process.returncode == 23, "Owned interrupted mode publisher did not reach partial config flush")
        try:
            registry.get("named")
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("Incomplete selected-root mode config silently fell back to stale fields")
        path.write_bytes(intact)
        _require(vars(registry.get("named")) == {"name": "named", **fields, "max_tokens": 9183}, "Mode failed to recover exact selected-root config after interrupted publisher")
    if category == "permissions":
        before = path.read_bytes()
        with _deny_read(path):
            try:
                registry.get("balanced")
            except PermissionError:
                pass
            else:
                raise AssertionError("current configuration read succeeded through actual OS denial")
        _require(path.read_bytes() == before and vars(registry.get("balanced")) == {"name": "balanced", **fields}, "denied mode observation changed stored config or resumed fields")
    if category == "stale":
        fields["max_tokens"] = 9901
        path.write_text(json.dumps({"balanced": fields}), encoding="utf-8")
        # The public getter contract checks exact selected-root configuration.
        result = registry.get("balanced")
        _require(result.max_tokens == 9901, "live mode registry returned stale replaced configuration")
    missing = ModeRegistry(root / "missing.json").get(text)
    _require(missing.name == "fallback" and missing.max_tokens == 2400 and missing.parallel_agents == 1, "missing config invented resources")
    return {"configuredBudget": registry.get("balanced").max_tokens, "characters": len(text)}


def _advisor(root, category):
    from .improvement_advisor import recommend_improvements
    text = TEXT[category]
    size = 20000 if category == "huge" else 2
    recs = recommend_improvements({"total_sessions": size, "sessions_with_handoff": size, "verification_failures": 1, "runs_with_memory_writes": 0, "runs_with_doc_evidence": 0}, [{"resistance_score": 74, "unrelated": text}] * size, top_k=7)
    expected = ["Context Compaction Tuning", "Verification Matrix", "Adversarial Strategy Expansion", "Memory Coverage Boost", "Docs Reliability Monitor", "Approval Gates", "Dashboard Drill-Down"]
    _require([r["feature"] for r in recs] == expected, "metric-triggered ordering changed")
    _require(recommend_improvements({}, [], top_k=0) == [] and all(r["why"] and r["next_step"] for r in recs), "result limit or actionable explanation lost")
    return {"bundles": size, "features": expected}


def _compiler(root, category):
    from .model_tool_intelligence import ModelToolIntelligence, strict_schema
    from .progressive_tools import ProgressiveToolSurface, ProgressiveToolSpec
    from .openai_adapter import resolve_compiled_tool_call, build_responses_request_from_tool_compiler
    text = TEXT.get(category, "permissions")
    property_name = "query" + text
    source = {"type": "object", "properties": {property_name: {"type": "string"}, "limit": {"type": "integer"}}, "required": [property_name]}
    before = copy.deepcopy(source)
    strict, eligible, warnings = strict_schema(source)
    _require(eligible and not warnings and source == before and strict["required"] == list(source["properties"]) and strict["additionalProperties"] is False and strict["properties"]["limit"]["type"] == ["integer", "null"], "strict compiler mutates source or weakens optional admission")
    unsupported = {"type": "object", "patternProperties": {".*": {"type": "string"}}}
    unresolved, eligible, warnings = strict_schema(unsupported)
    _require(not eligible and warnings and unresolved["patternProperties"] == unsupported["patternProperties"] and "additionalProperties" not in unresolved and unsupported == {"type": "object", "patternProperties": {".*": {"type": "string"}}}, "unsupported construct silently weakened")
    surface = ProgressiveToolSurface()
    for index in range(50 if category == "huge" else 4):
        surface.register(ProgressiveToolSpec(name=f"fixture.operation-{index}", title="Citation OCR" if index == 1 else "Other", description="Citation OCR " + text if index == 1 else "Other", input_schema=source, output_schema={"type": "object"}, annotations={"readOnlyHint": False, "requiresApproval": True}, permissions=("workspace.write",), provenance={"sourceKind": "native", "provider": "fixture", "originalName": f"fixture.operation-{index}"}))
    from .tool_factory import AuthoredToolStore
    authored = AuthoredToolStore(root)
    manifest = {"schema": "neyvia.authored_tool.v1", "toolId": "fixture.citation", "name": "Fixture citation", "description": "Citation OCR", "kind": "composite", "permissions": [], "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}, "outputSchema": {"type": "object"}, "steps": [{"stepId": "read", "operation": "workspace.read", "arguments": {"path": "source.txt"}}], "provenance": {"sourceKind": "workspace", "originalName": "fixture.citation"}}
    saved = authored.save(manifest, approved=True)
    _require(saved["ok"], "real authored compiler source not saved")
    intelligence = ModelToolIntelligence(root, progressive=surface, authored_store=authored)
    if category == "empty":
        try:
            intelligence.compile_belt({"task": ""})
        except ValueError:
            pass
        else:
            raise AssertionError("empty task admitted")
    compiler = intelligence.compile_openai({"task": "Citation OCR " + text, "limit": 2, "deferLoading": True})
    belt = compiler["belt"]
    _require(any(r["callTarget"] == "fixture.operation-1" for r in belt["tools"]) and len(belt["tools"]) == 2 and belt["policy"]["permissionAuthority"] == "existing execution surface", "belt relevance/bound or authority changed")
    callmap = compiler["callMap"]
    _require(len(callmap) == 2 and len(set(callmap)) == 2 and compiler["tools"][-1] == {"type": "tool_search"}, "provider callable collisions or deferred search lost")
    for key, mapping in callmap.items():
        ns, function = key.split(".", 1)
        arguments = {property_name: text, "limit": None}
        resolved = resolve_compiled_tool_call(compiler, {"namespace": ns, "name": function, "arguments": json.dumps(arguments)})
        expected = {**mapping["boundArguments"], "arguments": arguments} if mapping.get("argumentMode") == "nest_arguments" else {**mapping["boundArguments"], **arguments}
        _require(resolved["callTarget"] == mapping["callTarget"] and resolved["arguments"] == expected and resolved["provenance"] == mapping["provenance"], "provider resolution changed saved target/payload/provenance")
    # Independently exercise saved authored target nesting even if native rank wins.
    authored_compiler = intelligence.compile_openai({"task": "fixture citation", "limit": 20})
    nested = [(key, value) for key, value in authored_compiler["callMap"].items() if value.get("argumentMode") == "nest_arguments"]
    _require(nested, "authored callable not compiled")
    key, mapping = nested[0]
    ns, function = key.split(".", 1)
    injected = {"toolId": "attacker.other", "query": text}
    resolved = resolve_compiled_tool_call(authored_compiler, {"namespace": ns, "name": function, "arguments": injected})
    _require(resolved["arguments"]["toolId"] == "fixture.citation" and resolved["arguments"]["arguments"] == injected, "provider retargeted immutable authored toolId")
    try:
        resolve_compiled_tool_call(compiler, {"name": "missing", "arguments": {}})
    except KeyError:
        pass
    else:
        raise AssertionError("unknown callable admitted")
    wire = build_responses_request_from_tool_compiler(text, "fixture-model", compiler).as_dict()
    _require(wire["tools"] == compiler["tools"] and "callMap" not in wire, "internal target map leaked on provider wire")
    return {"callTargets": [r["callTarget"] for r in callmap.values()], "sourceUnchanged": source == before, "schemaCharacters": len(json.dumps(source)), "wireKeys": list(wire)}


def _authored(root, category):
    from .tool_factory import AuthoredToolStore
    from .capability_contracts import canonical_hash
    text = TEXT.get(category, "fixture")
    store = AuthoredToolStore(root)
    source = {"name": "remote.fixture", "description": text, "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}}
    payload = {"sourceType": "mcp", "source": source, "toolId": "fixture.imported", "adapterId": "fixture.adapter", "server": "fixture.server", "permissions": ["workspace.write"] if category == "permissions" else [], "sourceMetadata": {"provider": "fixture-provider", "version": text, "license": "MIT", "sourceUrl": "https://example.invalid/fixture"}}
    draft = store.adapt(payload)
    manifest = draft["manifest"]
    provenance = manifest["provenance"]
    _require(provenance["sourceHash"] == canonical_hash(source) and provenance["originalName"] == manifest["delegated"]["remoteToolName"] == source["name"] and provenance["sourceVersion"] == text and provenance["license"] == "MIT" and provenance["server"] == "fixture.server", "adapter erased source/license/hash identity")
    refused = store.save(manifest, approved=False)
    _require(not refused["ok"] and refused["status"] == "approval_required" and not list(store.directory.glob("*.json")), "unapproved manifest changed durable storage")
    if category == "concurrency":
        def save(index):
            consumer = AuthoredToolStore(root)
            candidate = consumer.adapt({**payload, "toolId": f"fixture.import-{index}"})["manifest"]
            _require(candidate["provenance"]["sourceHash"] == canonical_hash(source), "concurrent adaptation changed independent source hash")
            return consumer.save(candidate, approved=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            saved_rows = list(pool.map(save, range(12)))
    else:
        saved_rows = [store.save(manifest, approved=True)]
    for saved in saved_rows:
        loaded = AuthoredToolStore(root).describe(saved["tool"]["toolId"])
        _require(saved["ok"] and json.loads(Path(saved["path"]).read_text(encoding="utf-8")) == saved["tool"] and {k: v for k, v in loaded.items() if k not in {"path", "manifestHash"}} == saved["tool"], "approved manifest not exact fresh-store durable")
    if category == "interrupted":
        from . import tool_factory as owner
        from .edge_fixture_local import replacement_fault
        target = Path(saved_rows[0]["path"])
        original = target.read_bytes()
        with replacement_fault(owner, target, KeyboardInterrupt) as commits:
            try:
                store.save({**manifest, "description": "interrupted replacement"}, approved=True)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("Authored publisher missed actual replacement interruption")
        _require(commits and target.read_bytes() == original and AuthoredToolStore(root).describe(manifest["toolId"])["description"] == manifest["description"], "Interrupted approved authored save corrupted prior durable manifest/provenance")
    if category == "stale":
        replaced_source = {**source, "description": "replacement description"}
        newer = AuthoredToolStore(root).adapt({**payload, "source": replaced_source})["manifest"]
        _require(newer["provenance"]["sourceHash"] == canonical_hash(replaced_source) and newer["provenance"]["sourceHash"] != provenance["sourceHash"], "replacement adaptation reused stale source hash")
        updated = AuthoredToolStore(root).save(newer, approved=True)
        loaded = AuthoredToolStore(root).describe(manifest["toolId"])
        _require({k: v for k, v in loaded.items() if k not in {"path", "manifestHash"}} == updated["tool"], "fresh authored store loaded stale replaced manifest")
    return {"sourceHash": provenance["sourceHash"], "approvedWrites": len(saved_rows), "unapprovedWriteRefused": True}


def _node(root, category):
    from .managed_node_runtime import node_supports_current_openclaw
    versions = [None] if category == "empty" else [(22, 22, 2), (22, 22, 3), (23, 99, 0), (24, 14, 999), (24, 15, 0), (25, 8, 999), (25, 9, 0)] + [(major, 999999, 999999) for major in range(26, 2026)]
    expected = [False] if category == "empty" else [False, True, False, False, True, False, True] + [True] * 2000
    _require([node_supports_current_openclaw(v) for v in versions] == expected, "Node release boundary changed")
    return {"versions": versions, "admitted": expected}


def _node_env(root, category):
    from .managed_node_runtime import prepend_openclaw_node_to_env
    text = TEXT[category]
    original = {"PATH": "existing;" + text, "CALLER_VALUE": text, "NEYVIA_MANAGED_NODE_BIN": "stale"}
    before = copy.deepcopy(original)
    result = prepend_openclaw_node_to_env(original, resolved_bin=root / "explicit-node")
    _require(original == before and result["PATH"] == str(root / "explicit-node") + os.pathsep + before["PATH"] and result["CALLER_VALUE"] == text and result["NEYVIA_MANAGED_NODE_BIN"] == str(root / "explicit-node"), "explicit runtime environment lost PATH suffix/caller values or mutated input")
    return {"pathCharacters": len(result["PATH"]), "sourceUnchanged": original == before}


def _loop(root, category):
    from .model_tool_intelligence import ModelToolIntelligence, ToolFeedbackStore
    from .durability import append_jsonl_durable
    text = TEXT.get(category, "durable")
    intelligence = ModelToolIntelligence(root)
    effect = root / "effects.jsonl"
    denied_network = {"attempts": 0}
    if category == "offline":
        import socket
        original_socket = socket.socket
        def deny_socket(*args, **kwargs):
            denied_network["attempts"] += 1
            raise OSError("offline model-loop fixture denies sockets")
        socket.socket = deny_socket
    if category == "empty":
        try:
            intelligence.run_bounded({"calls": []}, executor=lambda *_: effect.write_text("bad"))
        except ValueError:
            pass
        else:
            raise AssertionError("empty loop admitted")
        _require(not effect.exists(), "empty loop dispatched side effect")
    def execute(target, arguments, context):
        if category == "offline":
            import socket
            try:
                with socket.socket() as client:
                    client.settimeout(.05)
                    client.connect(("127.0.0.1", int(os.environ['NEYVIA_C7_PORT'])))
            except OSError:
                pass
            return {"ok": False, "error": "offline", "status": "offline"}
        append_jsonl_durable(effect, {"target": target, "arguments": arguments, "approved": context["approved"]})
        if category == "permissions":
            return {"ok": False, "status": "approval_required"}
        return {"ok": True, "evidence": [str(effect)]}
    calls = [{"callTarget": f"fixture.operation-{i}", "arguments": {"text": text, "index": i}} for i in range(80 if category == "huge" else 4)]
    def single(index):
        consumer = ModelToolIntelligence(root)
        return consumer.run_bounded({"goal": text, "calls": [{**r, "callTarget": r["callTarget"] + f"-{index}"} for r in calls], "maxCalls": 2, "maxRetries": 0}, executor=execute)
    try:
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                receipts = list(pool.map(single, range(8)))
        else:
            receipts = [single(0)]
    finally:
        if category == "offline":
            import socket
            socket.socket = original_socket
    if category == "offline":
        _require(denied_network["attempts"] == 1 and receipts[0]["status"] == "failed"
                 and receipts[0]["attempts"] == 1 and not effect.exists(),
                 "offline loop did not fail closed at the actual executor boundary")
    actual_effects = [json.loads(line) for line in effect.read_text(encoding="utf-8").splitlines()] if effect.exists() else []
    if category != "offline":
        _require(len(actual_effects) == sum(r["attempts"] for r in receipts), "loop count differed from actual persisted executions")
    for receipt in receipts:
        _require(json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8")) == {k: v for k, v in receipt.items() if k != "receiptPath"}, "returned loop receipt differs from actual durable bytes")
        _require(receipt["attempts"] <= 2, "loop call budget exceeded")
        if category == "permissions":
            _require(receipt["attempts"] == 1 and receipt["status"] == "approval_required" and receipt["state"]["next_action"] == "operator_action", "approval refusal did not stop actual subsequent call")
    feedback = ToolFeedbackStore(root)
    events = feedback.recent(limit=1000)
    expected_events = sum(r["attempts"] for r in receipts) if category == "offline" else len(actual_effects)
    _require(len(events) == expected_events and sum(r["calls"] for r in feedback.aggregate().values()) == len(events), "fresh feedback index disagrees with durable effects")
    if category == "stale":
        # Append a complete real production event through a second owner. A
        # previously initialized index must import the newly observed tail.
        fresh = ToolFeedbackStore(root).record({"callTarget": "fixture.new-tail", "ok": True, "durationMs": 9})
        _require(feedback.recent(limit=1000)[-1] == fresh and feedback.aggregate()["fixture.new-tail"]["calls"] == 1, "existing feedback index missed new durable tail")
    return {"receipts": [r["receiptPath"] for r in receipts], "executedEffects": len(actual_effects), "indexedEvents": len(events), "reopened": True,
            "offlineSocketDenials": denied_network["attempts"] if category == "offline" else None}


def _loop_interrupted(root, category):
    from .model_tool_intelligence import ModelToolIntelligence, ToolFeedbackStore
    marker = root / "second-call-started"
    worker = """import sys,time
from pathlib import Path
from grant_agent.model_tool_intelligence import ModelToolIntelligence
root=Path(sys.argv[1])
def execute(target,arguments,context):
    if target=='fixture.pending':
        (root/'second-call-started').write_text('entered',encoding='utf-8')
        time.sleep(30)
    (root/(target+'.effect')).write_text('completed',encoding='utf-8')
    return {'ok':True}
ModelToolIntelligence(root).run_bounded({'calls':[{'callTarget':'fixture.completed'},{'callTarget':'fixture.pending'}],'maxCalls':2},executor=execute)
"""
    child = subprocess.Popen([sys.executable, "-c", worker, str(root)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        _require(marker.exists(), "worker did not establish actual in-flight second action")
        child.kill(); child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
    events = ToolFeedbackStore(root).recent()
    _require(child.returncode != 0 and len(events) == 1 and events[0]["callTarget"] == "fixture.completed" and events[0]["ok"] and (root / "fixture.completed.effect").read_text(encoding="utf-8") == "completed" and not (root / "fixture.pending.effect").exists(), "crash lost completed feedback or invented pending completion")
    intelligence = ModelToolIntelligence(root)
    def execute(target, args, context):
        path = root / "post-crash.effect"; path.write_text("reopened", encoding="utf-8")
        return {"ok": True, "evidence": [str(path)]}
    receipt = intelligence.run_bounded({"calls": [{"callTarget": "fixture.reopened"}], "maxCalls": 1}, executor=execute)
    _require(receipt["status"] == "completed" and len(ToolFeedbackStore(root).recent()) == 2, "crashed consumer prevented fresh durable execution")
    return {"killedExitCode": child.returncode, "completedBeforeCrash": events[0]["eventId"], "pendingCompletionAbsent": True, "freshReceipt": receipt["receiptPath"], "automaticResumeClaimed": False}


FAMILIES = {
    "catalog": (_catalog, {P + "catalog"}, set(TEXT) | {"stale", "concurrency", "permissions", "interrupted"}),
    "routing": (_routing, {P + name for name in ("portfolio", "classification", "dictation", "launch")}, set(TEXT)),
    "mode": (_mode, {P + "mode"}, set(TEXT) | {"stale", "permissions", "concurrency", "interrupted"}),
    "advisor": (_advisor, {P + "advisor"}, set(TEXT)),
    "compiler": (_compiler, {P + name for name in ("strict-schema", "belt", "compiler", "resolved", "provider-request")}, set(TEXT)),
    "authored": (_authored, {P + "adapt", P + "authored-save"}, set(TEXT) | {"permissions", "stale", "concurrency", "interrupted"}),
    "node": (_node, {"runtime.node.versions"}, {"empty", "huge"}),
    "node-env": (_node_env, {"runtime.node.environment"}, set(TEXT)),
    "loop": (_loop, {P + "loop"}, set(TEXT) | {"permissions", "concurrency", "stale", "offline"}),
    "loop-interrupted": (_loop_interrupted, {P + "loop"}, {"interrupted"}),
}


def run(root, contracts, categories):
    rows = []
    base = Path(root).resolve()
    for name, (builder, identities, supported) in FAMILIES.items():
        bindings = sorted(identities & set(contracts))
        if not bindings:
            continue
        for category in categories:
            if category not in supported:
                continue
            scratch = base / f"models-{name}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            row = {"id": f"models.{name}.{category}", "category": category, "contracts": bindings,
                   "boundary": "Actual local production owner and independently inspected route/cache/callable/durable effects"}
            if name == "authored" and category == "interrupted":
                row["contracts"] = [identity for identity in bindings if identity == P + "authored-save"]
            try:
                row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "scratch": str(scratch), "traceback": traceback.format_exc()[-4000:]})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity == P + "adapt" and category == "interrupted":
        return {"kind": "not_applicable", "reason": "Audited AuthoredToolStore.adapt normalizes supplied source metadata/schema into a returned draft and source hash. It owns no durable publisher or asynchronous worker. Interrupted approved publication is separately exercised against authored-save's actual os.replace boundary, preserving its prior exact manifest/provenance."}
    for name, (_, identities, supported) in FAMILIES.items():
        if identity not in identities or category in supported:
            continue
        if name in {"routing", "advisor", "node", "node-env"} or (name == "compiler" and identity in {P + "strict-schema", P + "resolved", P + "provider-request"}):
            return {"kind": "not_applicable", "reason": f"Audited {identity} owner at {contract.get('checkedAt', [])} is an in-memory transform over explicit caller observations; it owns no file writer, permission decision, transport, revision or resumable process for {category}."}
        if category == "offline" and name not in {"compiler", "loop", "loop-interrupted"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} reads explicit local caches/manifests or compiles local descriptors; the owner does not contact a provider or infer live authentication. There is no connectivity state in this contract."}
        return {"kind": "fixture_gap", "reason": f"The exact {identity} {category} boundary remains without an implemented adversarial owner fixture; successful local computations are not evidence for this pair."}
    return None
