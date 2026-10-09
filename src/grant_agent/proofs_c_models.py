"""Model contracts at production entry points and isolated action self-checks.

The validators operate on the actual inputs, output, and durable receipts. They
do not import tests and never grant provider or network authority.
"""
from __future__ import annotations

import inspect
import json
import time
from contextlib import nullcontext
from functools import wraps
from pathlib import Path


def require(condition, identity, detail):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{identity}: {detail}")


def check_feedback(connection, event):
    stored = connection.execute("SELECT payload FROM feedback_events ORDER BY sequence DESC LIMIT 1").fetchone()
    require(stored is not None and json.loads(stored[0]) == event,
            "proofs-c.models.loop", "returned feedback differs from the indexed durable event")


def checked(kind):
    """Keep the public signature while checking every successful real action."""
    def decorate(action):
        signature = inspect.signature(action)

        @wraps(action)
        def invoke(*args, **kwargs):
            inputs = signature.bind(*args, **kwargs)
            inputs.apply_defaults()
            guard = nullcontext()
            if kind == "authored-save":
                from .harness_jobs import _exclusive_job_lock
                store = inputs.arguments["self"]
                directory = store.directory
                # Keep the refusal census and its action in the same mutation
                # boundary across store instances; concurrent accepted saves
                # must not appear as side effects of a refused operation.
                store.root.mkdir(parents=True, exist_ok=True)
                guard = _exclusive_job_lock(store.root / ".authored-tools-save", timeout_seconds=30)
            with guard:
                before = None
                if kind == "authored-save":
                    before = {path.name: path.read_bytes() for path in directory.glob("*.json")} if directory.exists() else {}
                output = action(*args, **kwargs)
                check(kind, inputs.arguments, output)
                if before is not None and not output.get("ok"):
                    after = {path.name: path.read_bytes() for path in directory.glob("*.json")} if directory.exists() else {}
                    require(after == before, "proofs-c.models.authored-save", "rejected manifest changed authored storage")
                return output
        return invoke
    return decorate


def _catalog_efforts(source, prior):
    key = next((name for name in ("supported_reasoning_levels", "supportedReasoningLevels", "reasoningEfforts") if name in source), None)
    defaults = ["low", "medium", "high", "xhigh"]
    if key is None:
        return prior.get("reasoningEfforts", defaults)
    raw = source[key]
    if raw is None:
        return defaults
    values = []
    for item in raw if isinstance(raw, list) else []:
        value = str(item.get("effort") if isinstance(item, dict) else item or "").strip().lower()
        if value and value not in values:
            values.append(value)
    return values


def check_catalog(output, cache_payloads):
    identity = "proofs-c.models.catalog"
    models = {row["id"]: row for row in output["models"]}
    require(len(models) == len(output["models"]), identity, "duplicate model identity")
    require(output["selectableModels"] == [row for row in output["models"] if row["selectable"]], identity, "selectable projection differs")
    require(output["deprecatedModels"] == [row for row in output["models"] if row["deprecated"]], identity, "deprecated projection differs")
    for row in models.values():
        require(row["selectable"] == (row["supportedInApi"] and not row["deprecated"] and row["visibility"] == "list"), identity, "restricted model selectable")
        require(not row["id"].startswith("gpt-5.3") or row["deprecated"], identity, "deprecated family promoted")
    from .model_catalog import BOOTSTRAP_CODEX_MODELS
    seen = {row["id"]: dict(row) for row in BOOTSTRAP_CODEX_MODELS}
    for _, path, payload in sorted(cache_payloads, key=lambda row: row[0]):
        for source in payload.get("models", []) if isinstance(payload.get("models"), list) else []:
            if not isinstance(source, dict):
                continue
            model_id = str(source.get("slug") or source.get("id") or source.get("model") or "").strip()
            if not model_id:
                continue
            prior = seen.get(model_id, {})
            expected_efforts = _catalog_efforts(source, prior)
            label = str(source.get("display_name") or source.get("displayName") or source.get("label") or model_id).strip()
            seen[model_id] = {"reasoningEfforts": expected_efforts, "source": str(path), "detected": True, "label": prior.get("label", model_id) if not label or label == model_id else label,
                              "supportedInApi": bool(source.get("supported_in_api", source.get("supportedInApi", True))), "visibility": str(source.get("visibility") or "list").strip().lower()}
    require(set(models) == set(seen), identity, "bootstrap or detected identity lost")
    for model_id, expected in seen.items():
        require(models[model_id]["reasoningEfforts"] == expected["reasoningEfforts"], identity, "model-specific efforts lost")
        require(models[model_id]["detected"] == expected.get("detected", False), identity, "bootstrap misreported as detected")
        require(models[model_id]["label"] == expected["label"], identity, "bootstrap/display label lost")
        require(models[model_id]["supportedInApi"] == expected.get("supportedInApi", True) and models[model_id]["visibility"] == expected.get("visibility", "list"), identity, "cache restriction lost")
        if expected.get("source"):
            require(models[model_id]["source"] == expected["source"], identity, "newest observed source lost")
    require(output["sourceAgeSeconds"] is None or type(output["sourceAgeSeconds"]) is int and output["sourceAgeSeconds"] >= 0, identity, "invalid source age")


def check(kind, inputs, output):
    identity = "proofs-c.models." + kind
    if kind == "portfolio":
        providers, runtimes = inputs["provider_presence"] or {}, inputs["runtime_presence"] or {}
        require(output["autoFallback"] is False and output["modelIdentifierContract"]["aliasesInterchangeable"] is False, identity, "provider substitution allowed")
        require(output["modelIdentifierContract"]["openCodeGoId"] == "kimi-k3", identity, "OpenCode model identifier contract changed")
        for lane in output["lanes"]:
            ready = [row for row in lane["routes"] if row["availability"]["ready"]]
            require(lane["recommendedRouteId"] == (ready or lane["routes"])[0]["routeId"], identity, "unready route outranks observed ready route")
            for row in lane["routes"]:
                state = row["availability"]
                expected = bool(providers.get(row["provider"])) and bool(runtimes.get(row["runtime"])) and (row["provider"] != "kimi-code" or bool(runtimes.get("kimi-code-profile")))
                require(state["ready"] == expected and row["fallbackAllowed"] is False, identity, "unproved auth/profile marked ready")
                expected_state = "ready" if expected else "runner_required" if not runtimes.get(row["runtime"]) else "provider_profile_required" if providers.get(row["provider"]) and row["provider"] == "kimi-code" else "runner_ready_auth_unchecked" if row["provider"] == "kimi-code" else "authentication_required"
                require(state["state"] == expected_state and state["runnerAvailable"] == bool(runtimes.get(row["runtime"])) and state["authObserved"] == bool(providers.get(row["provider"])), identity, "availability does not reflect observed runner/auth/profile")
                if row["provider"] == "kimi-code":
                    require(row["model"] == ("k3-256k" if lane["laneId"] == "routine" else "k3") and row["effort"] == ("low" if lane["laneId"] == "routine" else "high"), identity, "Kimi task-specific identity changed")
                if row["provider"] == "opencode-go":
                    require(row["model"] == "kimi-k3", identity, "provider-specific alias lost")
    elif kind == "classification":
        import re
        text = str(inputs["value"] or "").casefold()
        expected = inputs["fallback"]
        for pattern, lane in ((r"\b(?:verify|verification|review|audit|prove|proof|acceptance)\b", "verification"), (r"\b(?:architecture|deep|large codebase|long context|multi[- ]file|migration|redesign|system[- ]wide|whole repo|entire repo)\b", "deep"), (r"\b(?:small|little|quick|routine|single[- ]file|bounded|typo|rename|format|summari[sz]e)\b", "routine")):
            if re.search(pattern, text):
                expected = lane
                break
        require(output == expected, identity, "task-first lane changed")
    elif kind == "dictation":
        import re
        winners = {}
        for row in output["parsedSegments"]:
            role = row["role"]
            if row.get("action") == "corrected_effort":
                require(role in winners, identity, "correction without previous role")
                winners[role]["effort"] = row["effort"]
            else:
                winners[role] = {key: row[key] for key in ("role", "provider", "model", "effort")}
                segment = row["segment"].casefold().replace("_", " ")
                gpt = re.search(r"\bgpt[\s-]*(\d+(?:\.\d+)?)[\s-]*(sol|terra|luna)\b", segment)
                if gpt:
                    require(row["model"] == f"gpt-{gpt[1]}-{gpt[2]}", identity, "spoken GPT family variant changed")
                if re.search(r"\b(?:composer|composite)\s*2[.\s-]*5", segment):
                    require(row["model"] == "composer-2.5" and row["provider"] == "cursor", identity, "spoken Composer identity changed")
                if re.search(r"\bgrok\s*4[.\s-]*5", segment):
                    require(row["model"] == "grok-4-5" and row["provider"] == "cursor", identity, "spoken Grok identity changed")
                glm = re.search(r"\bglm\s*(\d+(?:\.\d+)?)", segment)
                if glm and inputs["canonicalize_models"] and row["provider"] == "openrouter":
                    require(row["model"] == "z-ai/glm-" + glm[1], identity, "spoken GLM identity changed")
        actual = {row["role"]: row for row in output["routeOverrides"]}
        require(len(actual) == len(output["routeOverrides"]) and set(actual) == set(winners), identity, "last-role winner lost or duplicated")
        from .model_routing import ROUTE_ROLE_ORDER
        require([row["role"] for row in output["routeOverrides"]] == [role for role in ROUTE_ROLE_ORDER if role in winners], identity, "canonical role order changed")
        require(output["sourceText"] == str(inputs["text"] or "").strip() and output["status"] == ("parsed" if actual else "empty"), identity, "parse receipt text/status changed")
        for role, row in winners.items():
            require(all(actual[role][key] == value for key, value in row.items()), identity, "dictation correction or identity lost")
            expected_runtime = {"cursor": "cursor", "openrouter": "opencode"}.get(row["provider"])
            explicit_harness = any(word in str(next((item.get("segment", "") for item in reversed(output["parsedSegments"]) if item.get("role") == role and item.get("model")), "")).casefold() for word in ("hermes", "openclaw"))
            if expected_runtime and not explicit_harness:
                require(actual[role].get("runtimeId") == expected_runtime, identity, "provider/runtime mismatch")
    elif kind == "launch":
        rows = {row["role"]: row for row in output["routeDecisionRows"]}
        require(rows["context-reader"] == output["readerLane"] and rows["context-reader"]["provider"] == "neyvia-context" and rows["context-reader"]["model"] == "receipt-bound-cache", identity, "context reader changed")
        for role in ("planner", "verifier"):
            require(tuple(rows[role][key] for key in ("provider", "model", "effort")) == ("openai-codex", "gpt-5.6-sol", "high"), identity, "canonical independent route changed")
        require(rows["executor"]["model"] == output["model"] and rows["executor"]["provider"] == output["modelProvider"], identity, "launch and executor disagree")
        if "cursor" in str(inputs["objective"]).casefold():
            require(output["runtime"] == output["modelProvider"] == "cursor", identity, "explicit Cursor request ignored")
            import re
            match = re.search(r"\bgrok[\s_-]*(\d+)(?:[.\s_-]+(\d+))?\b", str(inputs["objective"]).casefold())
            requested = f"grok-{match[1]}-{match[2]}" if match and match[2] else f"grok-{match[1]}" if match else "auto"
            require(output["model"] == requested, identity, "requested Cursor model lost")
    elif kind == "mode":
        registry = inputs["self"]
        raw = json.loads(registry.path.read_text(encoding="utf-8")) if registry.path.exists() else {}
        requested = inputs["name"]
        source = raw.get(requested, raw.get("balanced"))
        if source:
            for key in ("persona", "max_tokens", "max_handoffs", "max_runtime_seconds", "parallel_agents", "merge_policy", "description"):
                expected = source.get(key, {"parallel_agents": 1, "merge_policy": "best_score", "description": ""}.get(key))
                if key in {"max_tokens", "max_handoffs", "max_runtime_seconds", "parallel_agents"}:
                    expected = int(expected)
                require(getattr(output, key) == expected, identity, "configured mode field changed: " + key)
        require(output.max_tokens > 0 and output.parallel_agents >= 1, identity, "invalid mode resource budget")
    elif kind == "advisor":
        metrics, bundles = inputs["metrics"], inputs["bundles"]
        total = max(1, int(metrics.get("total_sessions", 0)))
        scores = [int(row.get("resistance_score", 0)) for row in bundles]
        expected = []
        rules = [(float(metrics.get("sessions_with_handoff", 0))/total > .45, "Context Compaction Tuning"), (int(metrics.get("verification_failures", 0)) > 0, "Verification Matrix"), ((round(sum(scores)/len(scores), 2) if scores else 0) < 75, "Adversarial Strategy Expansion"), (int(metrics.get("runs_with_memory_writes", 0)) < max(2, total//3), "Memory Coverage Boost"), (int(metrics.get("runs_with_doc_evidence", 0)) < total, "Docs Reliability Monitor"), (int(metrics.get("blocked_commands", 0)) >= 0, "Approval Gates"), (True, "Dashboard Drill-Down")]
        expected = [name for enabled, name in rules if enabled][:inputs["top_k"]]
        require([row["feature"] for row in output] == expected and all(row["why"] and row["next_step"] for row in output), identity, "metric-triggered recommendations changed")
        priorities = {name: "high" if index < 3 else "medium" if index < 6 else "low" for index, (_, name) in enumerate(rules)}
        require(all(row["priority"] == priorities[row["feature"]] for row in output), identity, "metric priority changed")
    elif kind == "strict-schema":
        schema, eligible, warnings = output
        if not eligible:
            require(bool(warnings), identity, "unsupported schema silently weakened")
            return
        original = inputs["schema"] if isinstance(inputs["schema"], dict) else {}
        def walk(source, result):
            if not isinstance(source, dict) or not isinstance(result, dict):
                return
            if isinstance(source.get("properties"), dict):
                require(result.get("required", []) == list(source["properties"]) and result.get("additionalProperties") is False, identity, "strict object not closed/required")
                for key, value in source["properties"].items():
                    child = result["properties"][key]
                    if key not in source.get("required", []) and isinstance(value, dict) and isinstance(value.get("type"), str):
                        require(child.get("type") == [value["type"], "null"], identity, "optional type lost nullability")
                    walk(value, child)
            if isinstance(source.get("items"), dict):
                walk(source["items"], result.get("items"))
        walk(original, schema)
    elif kind == "belt":
        payload = inputs["payload"]
        cards = output["tools"]
        limit = max(1, min(int(payload.get("limit") or 8), 20))
        require(output["schema"] == "neyvia.model_tool_belt.v1" and len(cards) <= limit and output["summary"]["selectedTools"] == len(cards), identity, "tool context schema or limit changed")
        require(all(cards[index]["score"] >= cards[index+1]["score"] for index in range(len(cards)-1)), identity, "tool ranking unordered")
        require(all(card["callTarget"] and card.get("provenance") and card.get("inputSchema") for card in cards), identity, "execution identity/provenance missing")
        require(output["policy"]["permissionAuthority"] == "existing execution surface", identity, "compiler granted execution authority")
    elif kind == "compiler":
        cards = output["belt"]["tools"]
        functions = [(namespace["name"], function) for namespace in output["tools"] if namespace["type"] == "namespace" for function in namespace["tools"]]
        require(len(functions) == len(output["callMap"]) and len({ns + "." + row["name"] for ns, row in functions}) == len(functions), identity, "provider function identity collision")
        for ns, function in functions:
            mapping = output["callMap"][ns + "." + function["name"]]
            require(any(mapping["callTarget"] == card["callTarget"] and mapping["boundArguments"] == card.get("boundArguments", {}) and mapping["provenance"] == card.get("provenance", {}) for card in cards), identity, "compiled callable lost target or provenance")
        deferred = bool(inputs["payload"].get("deferLoading", True))
        require(any(row["type"] == "tool_search" for row in output["tools"]) == (deferred and bool(functions)), identity, "deferred tool search missing or unexpected")
    elif kind == "resolved":
        mapping = inputs["compiler"]["callMap"][output["providerCall"]]
        arguments = dict(inputs["arguments"] or {})
        expected = {**mapping.get("boundArguments", {}), "arguments": arguments} if mapping.get("argumentMode") == "nest_arguments" else {**mapping.get("boundArguments", {}), **arguments}
        require(output["callTarget"] == mapping["callTarget"] and output["arguments"] == expected and output["provenance"] == mapping["provenance"], identity, "provider arguments flattened or retargeted")
    elif kind == "provider-request":
        request = output.as_dict()
        require("callMap" not in request and request["tools"] == inputs["compiler"]["tools"], identity, "internal call map leaked or compiled tools changed on provider wire")
    elif kind == "mcp-compiler":
        request = inputs["request"]
        if not isinstance(output, dict) or "error" in output:
            return
        params = request.get("params") or {}
        if request.get("method") == "tools/list" and params.get("includeSchemas") is False:
            tools = output["result"]["tools"]
            require(all("inputSchema" not in row for row in tools) and any(row["name"] == "model.tools.compile" for row in tools), identity, "progressive model tool catalog missing or leaked schemas")
        if request.get("method") == "tools/call" and params.get("name") == "model.tools.compile" and not output["result"].get("isError"):
            require(output["result"]["structuredContent"]["schema"] == "neyvia.model_tool_belt.v1", identity, "MCP compiler dispatched wrong output")
    elif kind in {"loop", "benchmark"}:
        path = Path(output["receiptPath"])
        path.resolve().relative_to(inputs["self"].root.resolve())
        require(json.loads(path.read_text(encoding="utf-8")) == {key: value for key, value in output.items() if key != "receiptPath"}, identity, "returned result differs from durable receipt")
        if kind == "loop":
            require(output["attempts"] <= output["limits"]["maxCalls"], identity, "execution call bound exceeded")
            if output["status"] in {"approval_required", "auth_required"}:
                require(output["state"]["next_action"] == "operator_action" and not output["calls"][-1]["ok"], identity, "approval/auth stop misreported")
        else:
            rows = output["cases"]
            require(output["summary"]["cases"] == len(rows), identity, "benchmark denominator changed")
            for field, bound in (("top1", 1), ("top3", 3), ("topK", None)):
                require(all(row[field] == (row["expected"] in row["selected"][:bound]) for row in rows), identity, "ranking evidence misreported")
                require(output["summary"][field+"Accuracy"] == round(sum(row[field] for row in rows)/max(1,len(rows)),4), identity, "accuracy not derived from evidence")
    elif kind == "adapt":
        payload = inputs["payload"]
        if str(payload.get("sourceType") or "").lower() not in {"mcp", "openai_function"}:
            return
        from .model_tool_intelligence import canonical_hash
        manifest, source = output["manifest"], payload["source"]
        function = source.get("function") or source
        provenance = manifest["provenance"]
        require(provenance["originalName"] == manifest["delegated"]["remoteToolName"] == function["name"] and provenance["sourceHash"] == canonical_hash(source), identity, "source identity/hash lost")
        for source_key, target_key in (("provider", "provider"), ("version", "sourceVersion"), ("license", "license"), ("sourceUrl", "sourceUrl")):
            if payload.get("sourceMetadata", {}).get(source_key):
                require(provenance[target_key] == str(payload["sourceMetadata"][source_key]), identity, "source provenance dropped: " + source_key)
        require(provenance["server"] == str(payload.get("server") or "") and provenance["adapterId"] == str(payload.get("adapterId") or ""), identity, "adapter/server provenance changed")
    elif kind == "authored-save":
        if output.get("ok"):
            require(inputs["approved"] is True and json.loads(Path(output["path"]).read_text(encoding="utf-8")) == output["tool"], identity, "unapproved or non-durable authored tool save")
    elif kind == "authored-execute":
        if output.get("ok") and "authoredOutputValidation" in output:
            require(output["authoredOutputValidation"]["valid"] is True and output["status"] == "completed", identity, "invalid delegated output called completed")
            tool = inputs["self"].authored_tools.describe(output["toolId"])
            require(output["provenance"] == tool["provenance"], identity, "execution source provenance differs from saved tool")
            from jsonschema import Draft202012Validator
            Draft202012Validator(tool["outputSchema"]).validate(output["result"]["structuredContent"])


def self_check(root):
    """Exercise production actions with bounded caches, stores and stdio only."""
    import argparse
    import io
    import sys
    from contextlib import redirect_stdout
    from .model_catalog import build_model_catalog
    from .model_portfolio import build_model_portfolio, classify_task_lane, recommended_route
    from .model_routing import parse_route_dictation
    from .launch_recommendation import build_launch_runtime_recommendation
    from .modes import ModeRegistry
    from .improvement_advisor import recommend_improvements
    from .model_tool_intelligence import ModelToolIntelligence, strict_schema
    from .progressive_tools import ProgressiveToolSurface, ProgressiveToolSpec
    from .capability_service import CapabilityService
    from .tool_factory import AuthoredToolStore
    from .openai_adapter import resolve_compiled_tool_call, build_responses_request_from_tool_compiler
    from .neyvia_mcp import NeyviaMCPServer
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows = []

    def run(name, action):
        try:
            detail = action() or {}
            rows.append({"id": name, "ok": True, **detail})
        except Exception as error:
            rows.append({"id": name, "ok": False, "error": str(error)})

    def catalog_bootstrap():
        receipt = build_model_catalog(root, cache_paths=[])
        ids = {row["id"]: row for row in receipt["selectableModels"]}
        require(receipt["schema"] == "fluxio.model_catalog.v1" and receipt["sourceStatus"] == "bootstrap", "catalog-bootstrap", "bootstrap status changed")
        require(ids["gpt-6-astra"]["reasoningEfforts"] == ["low", "medium", "high", "xhigh", "max"] and not ids["gpt-6-astra"]["detected"], "catalog-bootstrap", "Astra effort contract changed")
        require(all(model in ids for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")) and "ultra" in ids["gpt-5.6-sol"]["reasoningEfforts"] and "ultra" not in ids["gpt-5.6-luna"]["reasoningEfforts"], "catalog-bootstrap", "model family/effort changed")

    def catalog_cache():
        path = root / "models-cache.json"
        path.write_text(json.dumps({"fetched_at": "2026-09-01T10:00:00Z", "client_version": "self-check", "models": [{"slug": "gpt-future-scratch", "supported_reasoning_levels": [{"effort": "high"}]}, {"slug": "gpt-5.3-codex-spark"}, {"slug": "gpt-disabled-scratch", "supported_in_api": False}, {"slug": "gpt-5.6-sol"}]}), encoding="utf-8")
        receipt = build_model_catalog(root, cache_paths=[path])
        ids = {row["id"]: row for row in receipt["models"]}
        require(ids["gpt-future-scratch"]["selectable"] and not ids["gpt-disabled-scratch"]["selectable"] and ids["gpt-5.3-codex-spark"]["deprecated"], "catalog-cache", "detected/restricted model visibility wrong")
        require(ids["gpt-5.6-sol"]["label"] == "GPT-5.6 Sol" and all(effort in ids["gpt-5.6-sol"]["reasoningEfforts"] for effort in ("max", "ultra")) and receipt["sources"][0]["clientVersion"] == "self-check", "catalog-cache", "bootstrap metadata/source version lost")

    def catalog_explicit():
        path = root / "explicit-cache.json"
        path.write_text(json.dumps({"fetched_at": "2026-09-01T10:00:00", "models": [{"slug": "gpt-6-astra", "supported_in_api": False, "supported_reasoning_levels": []}]}), encoding="utf-8")
        receipt = build_model_catalog(root, cache_paths=[path])
        astra = next(row for row in receipt["models"] if row["id"] == "gpt-6-astra")
        require(astra["reasoningEfforts"] == [] and not astra["selectable"] and type(receipt["sourceAgeSeconds"]) is int, "catalog-explicit", "explicit restrictions or timezone-free source age lost")

    def portfolio():
        profiles = build_model_portfolio(provider_presence={"kimi-code": True, "opencode-go": True}, runtime_presence={"kimi-code": True, "kimi-code-profile": True, "opencode": True})
        require(recommended_route(profiles, "routine")["model"] == "k3-256k" and recommended_route(profiles, "deep")["model"] == "k3", "portfolio", "task model lane lost")
        available = build_model_portfolio(provider_presence={"openai-codex": True}, runtime_presence={"codex": True, "kimi-code": True})
        require(recommended_route(available, "routine")["provider"] == "openai-codex" and available["lanes"][0]["routes"][0]["availability"]["state"] == "runner_ready_auth_unchecked", "portfolio", "unobserved auth outranked ready model")
        missing = build_model_portfolio(provider_presence={"kimi-code": True}, runtime_presence={"kimi-code": True, "kimi-code-profile": False})
        require(missing["lanes"][0]["routes"][0]["availability"]["state"] == "provider_profile_required", "portfolio", "missing profile called ready")
        for prompt, lane in (("Correct one small typo", "routine"), ("Redesign the architecture across the whole repo", "deep"), ("Independently verify the release proof", "verification")):
            require(classify_task_lane(prompt) == lane, "classification", "task classification differs")

    def routes():
        receipt = parse_route_dictation("GPT-5.6 Sol high for planner, no, x high, GLM 5.2 for frontend executor, GPT-5.6 Sol high for backend executor, deepseek v4Flash for verifier, GLM for, not front-end", default_runtime="hermes")
        routes = {row["role"]: row for row in receipt["routeOverrides"]}
        expected = {"planner": ("openai-codex", "gpt-5.6-sol", "xhigh"), "frontend_executor": ("openrouter", "z-ai/glm-5.2", "medium"), "backend_executor": ("openai-codex", "gpt-5.6-sol", "high"), "verifier": ("openrouter", "deepseek/deepseek-v4-flash", "high")}
        require(all(tuple(routes[role][key] for key in ("provider", "model", "effort")) == wanted for role, wanted in expected.items()) and receipt["warnings"], "dictation", "specialized route/correction warnings changed")
        receipt = parse_route_dictation("Composer 2.5 fast for frontend executor, GPT-5.6 Sol high for backend executor, Grok 4.5 high for verifier", default_runtime="hermes")
        routes = {row["role"]: row for row in receipt["routeOverrides"]}
        require(routes["frontend_executor"]["model"] == "composer-2.5" and routes["frontend_executor"]["runtimeId"] == "cursor" and routes["verifier"]["model"] == "grok-4-5" and routes["verifier"]["provider"] == "cursor", "dictation", "Cursor identity changed")
        receipt = parse_route_dictation("GPT-5.6 Sol low for planner, GPT-5.6 Luna max for verifier", default_runtime="hermes")
        routes = {row["role"]: row for row in receipt["routeOverrides"]}
        require(routes["planner"]["effort"] == "low" and routes["verifier"]["model"] == "gpt-5.6-luna" and routes["verifier"]["effort"] == "max", "dictation", "variant/effort changed")
        from .cli import cmd_route_dictation
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cmd_route_dictation(argparse.Namespace(text="GPT-5.6 Sol xhigh for planner, GLM 5.2 for frontend executor", default_runtime="hermes", preserve_models=False))
        wire = json.loads(stream.getvalue())
        require(code == 0 and wire["schema"] == "fluxio.route_dictation.v1" and [row["role"] for row in wire["routeOverrides"]] == ["planner", "frontend_executor"], "dictation-cli", "CLI receipt changed")

    def recommendations():
        standard = build_launch_runtime_recommendation(objective="Inspect this codebase and implement a feature with proof.", workspace_default_runtime="hermes")
        executor = next(row for row in standard["routeDecisionRows"] if row["role"] == "executor")
        require((executor["provider"], executor["model"], executor["effort"]) == ("opencode-go", "opencode-go/deepseek-v4-pro", "high"), "launch", "default executor route changed")
        cursor = build_launch_runtime_recommendation(objective="Use Cursor Agent with Grok 4.5 for route review", workspace_default_runtime="hermes")
        require(cursor["runtime"] == cursor["modelProvider"] == "cursor" and cursor["model"] == "grok-4-5", "launch", "explicit Cursor model changed")
        from .proof_contracts import REPO
        registry = ModeRegistry(REPO / "config/modes.json")
        balanced, swarms = registry.get("balanced"), registry.get("swarms")
        require(balanced.persona == "balanced_builder" and balanced.max_tokens > 1000 and balanced.merge_policy == "best_score", "mode", "balanced preset changed")
        require(swarms.parallel_agents == 3 and swarms.merge_policy == "consensus" and "parallel" in swarms.description.lower(), "mode", "swarms preset changed")
        require(registry.get("unknown") == balanced and ModeRegistry(root / "missing-modes.json").get("unknown").name == "fallback", "mode", "fallback mode changed")
        recs = recommend_improvements({"total_sessions": 12, "sessions_with_handoff": 8, "verification_failures": 3, "blocked_commands": 1, "runs_with_memory_writes": 1, "runs_with_doc_evidence": 10}, [{"resistance_score": 60}, {"resistance_score": 70}], top_k=5)
        require(len(recs) >= 3 and "high" in [row["priority"] for row in recs], "advisor", "missing high-priority recommendations")

    def compile_context():
        source = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}
        strict, eligible, warnings = strict_schema(source)
        require(eligible and not warnings and strict["required"] == ["query", "limit"] and strict["properties"]["limit"]["type"] == ["integer", "null"] and source["properties"]["limit"]["type"] == "integer", "strict-schema", "optional/nullability or source immutability changed")
        surface = ProgressiveToolSurface()
        for index in range(24):
            surface.register(ProgressiveToolSpec(name=f"proof.operation-{index}", title=f"Operation {index}", description="Rank and validate OCR PDF pages with citations" if index == 9 else f"Unrelated operation {index}", category="documents" if index == 9 else "misc", input_schema=source, output_schema={"type": "object"}, annotations={"readOnlyHint": True, "idempotentHint": True}, provenance={"sourceKind": "native", "provider": "neyvia", "originalName": f"proof.operation-{index}", "trustLevel": "builtin"}), handler=lambda args: {"ok": True, "arguments": args})
        intelligence = ModelToolIntelligence(_fixture_root(root / "compiler"), progressive=surface)
        compiler = intelligence.compile_openai({"task": "Rank OCR PDF pages and validate citations", "limit": 2, "deferLoading": True})
        belt = compiler["belt"]
        require(belt["tools"][0]["name"] == "proof.operation-9" and belt["tools"][0]["route"] == "programmatic" and belt["summary"]["selectedTools"] == 2 and belt["summary"]["contextReductionRatio"] > 2 and compiler["tools"][-1] == {"type": "tool_search"}, "compiler", "bounded relevant context not selected")
        namespace = next(row for row in compiler["tools"] if row["type"] == "namespace")
        resolved = resolve_compiled_tool_call(compiler, {"namespace": namespace["name"], "name": namespace["tools"][0]["name"], "arguments": json.dumps({"query": "source page", "limit": None})})
        require(resolved["callTarget"] == "proof.operation-9" and resolved["arguments"]["query"] == "source page", "resolved", "compiled function failed to resolve")
        build_responses_request_from_tool_compiler("Review citations", "gpt-5.6", compiler)
        try:
            resolve_compiled_tool_call(compiler, {"name": "missing-function", "arguments": {}})
        except KeyError:
            pass
        else:
            raise ValueError("Unknown provider function was resolved")

    def loop_approval():
        intelligence = ModelToolIntelligence(_fixture_root(root / "bounded"))
        seen = []
        def execution_boundary(target, arguments, context):
            seen.append({"target": target, "arguments": arguments, "approved": context["approved"]})
            return {"ok": False, "status": "approval_required"}
        receipt = intelligence.run_bounded({"goal": "Save an externally visible receipt", "acceptance": ["receipt exists"], "calls": [{"callTarget": "external.proof", "arguments": {"message": "proof"}}, {"callTarget": "must.not.run", "arguments": {}}], "maxCalls": 3, "maxRetries": 0}, executor=execution_boundary)
        require(receipt["status"] == "approval_required" and receipt["attempts"] == 1 and seen == [{"target": "external.proof", "arguments": {"message": "proof"}, "approved": False}] and intelligence.feedback.aggregate()["external.proof"]["calls"] == 1, "loop", "approval stop or durable feedback wrong")
        return {"receiptPath": receipt["receiptPath"]}

    def service_routing():
        service = CapabilityService(_fixture_root(root / "service"))
        try:
            belt = service.compile_model_tool_belt({"task": "OCR a scanned PDF quickly and retain page citations", "artifactTypes": ["application/pdf"], "limit": 5})
            ocr = next(row for row in belt["tools"] if row["name"] == "document.fast-ocr")
            require("document.fast-ocr" in [row["name"] for row in belt["tools"][:3]] and ocr["callTarget"] == "capability.execute" and ocr["boundArguments"]["capabilityId"] == "document.fast-ocr" and ocr["provenance"]["sourceKind"] == "capability-pack", "belt", "live capability routing lost")
            result = service.benchmark_model_tool_routing({"cases": [{"task": "Test the native Android app in an emulator", "expected": "device.android-test"}, {"task": "Run an authorized AI model red-team assessment", "expected": "security.ai-red-team"}, {"task": "Make source-grounded flashcards for a student", "expected": "learning.flashcards"}]})
            require(result["summary"]["top3Accuracy"] == 1, "benchmark", "representative task routing regressed")
            return {"receiptPath": result["receiptPath"]}
        finally:
            if service._model_tool_broker:
                service._model_tool_broker.close()

    def mcp_compiler():
        server = NeyviaMCPServer(_fixture_root(root / "mcp"))
        try:
            listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"includeSchemas": False}})
            compiler = next(row for row in listed["result"]["tools"] if row["name"] == "model.tools.compile")
            require("inputSchema" not in compiler, "mcp-compiler", "progressive list exposed full schemas")
            called = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "model.tools.compile", "arguments": {"task": "Analyze this Excel workbook", "limit": 4}}})
            require("error" not in called and called["result"]["isError"] is False and called["result"]["structuredContent"]["tools"][0]["name"] == "office.spreadsheet-analysis", "mcp-compiler", "MCP compiler dispatch failed")
        finally:
            server.mcp_broker.close()
            if server.capability_os._model_tool_broker:
                server.capability_os._model_tool_broker.close()

    def adapted_execution():
        workspace = root / "adapted"
        workspace.mkdir()
        definition = {"name": "echo", "title": "Workspace echo", "description": "Echo bounded text through a local MCP stdio server", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "outputSchema": {"type": "object", "properties": {"ok": {"type": "boolean"}, "text": {"type": "string"}, "tool": {"type": "string"}}, "required": ["ok", "text", "tool"]}}
        fixture = workspace / "echo_server.py"
        fixture.write_text('import json,sys\nfor line in sys.stdin:\n request=json.loads(line)\n method=request.get("method")\n if "id" not in request: continue\n if method=="initialize": result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"proofs-c-echo","version":"1"}}\n elif method=="tools/list": result={"tools":['+repr(definition)+']}\n elif method=="tools/call":\n  args=request["params"]["arguments"]\n  value={"ok":True,"text":args["text"],"tool":request["params"]["name"]}\n  result={"content":[{"type":"text","text":json.dumps(value)}],"structuredContent":value,"isError":False}\n else: result={}\n print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}),flush=True)\n', encoding="utf-8")
        # A real reviewed local server is explicit. Production defaults stay empty.
        config = workspace / ".agent_control/mcp_broker.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"schema": "neyvia.mcp_broker_config.v1", "servers": {"proofs-echo": {"transport": "stdio", "command": sys.executable, "args": ["-I", str(fixture)], "framing": "newline", "authState": "authenticated", "tools": [definition]}}}), encoding="utf-8")
        service = CapabilityService(_fixture_root(workspace))
        try:
            draft = service.adapt_authored_tool({"sourceType": "mcp", "toolId": "proofs.workspace-echo", "adapterId": "mcp.proofs-echo", "server": "proofs-echo", "sourceMetadata": {"provider": "local-reviewed", "version": "1", "sourceUrl": "https://example.test/local", "license": "Apache-2.0"}, "source": definition})
            require(draft["validation"]["valid"] and draft["manifest"]["toolId"] == "proofs.workspace-echo", "adapt", "adapted manifest invalid")
            held = service.save_authored_tool({"tool": draft["manifest"], "approved": False})
            require(held["status"] == "approval_required" and not service.authored_tools.list_tools()["tools"], "authored-save", "unapproved draft persisted")
            saved = service.save_authored_tool({"tool": draft["manifest"], "approved": True})
            require(saved["ok"] and AuthoredToolStore(workspace).describe("proofs.workspace-echo")["provenance"] == saved["tool"]["provenance"], "authored-save", "fresh store lost saved provenance")
            executed = service.execute_authored_tool({"toolId": "proofs.workspace-echo", "arguments": {"text": "real-stdio-proof"}})
            require(executed["ok"] and executed["result"]["structuredContent"]["text"] == "real-stdio-proof" and executed["authoredOutputValidation"]["valid"], "authored-execute", "real adapted server execution failed")
            compiler = service.compile_openai_tool_belt({"task": "Use the workspace echo tool with bounded text", "limit": 8})
            key = next(key for key, row in compiler["callMap"].items() if row["callTarget"] == "tool.author.execute" and row["boundArguments"].get("toolId") == "proofs.workspace-echo")
            namespace, name = key.split(".", 1)
            resolved = resolve_compiled_tool_call(compiler, {"namespace": namespace, "name": name, "arguments": {"text": "from-provider"}})
            require(resolved["arguments"] == {"toolId": "proofs.workspace-echo", "arguments": {"text": "from-provider"}}, "resolved", "authored provider arguments not nested")
            return {"receiptPath": executed.get("receipt_path", ""), "transport": "real-stdio-jsonrpc"}
        finally:
            if service._model_tool_broker:
                service._model_tool_broker.close()

    for name, action in (("catalog-bootstrap", catalog_bootstrap), ("catalog-detected", catalog_cache), ("catalog-explicit-restrictions", catalog_explicit), ("portfolio-task-and-auth", portfolio), ("dictation-and-cli", routes), ("recommendations-and-modes", recommendations), ("strict-compiler-provider", compile_context), ("bounded-approval-receipt", loop_approval), ("live-capability-routing", service_routing), ("mcp-progressive-compiler", mcp_compiler), ("adapted-real-stdio", adapted_execution)):
        run(name, action)
    from .proof_contracts import REPO
    manifest = json.loads((REPO / "config/proofs/proofs-c-models.json").read_text(encoding="utf-8"))
    observed = {row["id"]: row["ok"] for row in rows}
    passed = []
    for contract in manifest["contracts"]:
        scenarios = [name for site in contract["checkedAt"] if site.startswith("proofs_c_models.self_check:") for name in site.split(":", 1)[1].split(";")]
        if scenarios and all(observed.get(name) is True for name in scenarios):
            passed.append(contract["id"])
    return {"ok": all(row["ok"] for row in rows), "contracts": passed, "cases": rows, "failures": [row for row in rows if not row["ok"]], "durationMs": round((time.perf_counter()-started)*1000, 3), "scratchRoot": str(root), "frontier": "Provider inference is checked against explicit observations; no live provider authentication or external actions are exercised."}


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
