"""Runtime semantic contracts for Neyvia prompt preparation and applications.

These checks run inside the shared feature functions, including direct callers.
The startup journey uses local files only and never launches a provider or editor.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import time
from pathlib import Path


def require(condition, identity, detail):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{identity}: {detail}")


def check_profile(subject, requested, result):
    from .neyvia_ecosystem import TASK_PROMPT_PROFILES, TASK_PROMPT_PRIORITY
    requested = str(requested or "").strip().lower().replace("-", "_")
    identity = "neyvia-core.prompt-selection"
    if requested in TASK_PROMPT_PROFILES:
        require(result["profileId"] == requested and result["selection"] == "explicit", identity, "explicit profile lost precedence")
    else:
        text = f" {str(subject or '').lower()} "
        scores = [(sum(word in text for word in TASK_PROMPT_PROFILES[key]["keywords"]), -i, key)
                  for i, key in enumerate(TASK_PROMPT_PRIORITY)]
        winner = max(scores) if scores else (0, 0, "general")
        expected = winner[2] if winner[0] else "general"
        require(result["profileId"] == expected, identity, "profile is not the strongest deterministic keyword match")
        require(result["selection"] == ("inferred" if winner[0] else "default"), identity, "selection provenance disagrees")
    policy = TASK_PROMPT_PROFILES[result["profileId"]]
    require(all(result[key] == policy[key] for key in ("contextDepth", "focus", "deliverable", "stopCondition", "proofBudget")),
            identity, "selected policy metadata differs from declared profile")
    fixed = {"study": ("source-led", 4), "ecosystem_architecture": ("rich", 5), "optimization": ("measured", 4)}
    if result["profileId"] in fixed:
        depth, maximum = fixed[result["profileId"]]
        require(result["contextDepth"] == depth and result["proofBudget"]["maximumChecks"] == maximum,
                "neyvia-core.domain-policy", "domain context or proof limit changed")


def check_prompt(original, context, result):
    from .neyvia_ecosystem import _context_lines
    text = result["prompt"]
    require(result["originalPrompt"] == original and original.strip() in text and "Original user request" in text,
            "neyvia-core.prompt-preservation", "authoritative request was lost")
    require(all(line in text for line in _context_lines(context)) and
            "orchestration owns task division and sequence" in text,
            "neyvia-core.prompt-preservation", "scope, ownership or layer boundary was lost")
    if result["profile"]["profileId"] == "communication":
        require("sending, deleting, and unsubscribing remain per-action approvals" in text,
                "neyvia-core.domain-policy", "communication preparation omitted approval boundary")
    if result["profile"]["profileId"] == "experimentation":
        require("Observe, Simulate, or Act" in text and "retain failures" in text.lower(),
                "neyvia-core.domain-policy", "experimental modes or failure evidence lost")


def check_image(fields, result):
    require(result["profile"]["profileId"] == "image_generation" and "Proof budget" not in result["prompt"],
            "neyvia-core.image-spec", "visual preparation used execution contract")
    for label, value in fields:
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(item).strip() for item in value if str(item).strip())
        value = str(value or "").strip()
        require(not value or f"{label}: {value}" in result["prompt"], "neyvia-core.image-spec", "visual field omitted")


def check_rewrite(original, enabled, result):
    require((enabled and result["rewritten"] and result["status"] == "ecosystem_coaching_applied" and
             result["autoPrompt"]["prompt"] in result["prompt"]) or
            (not enabled and not result["rewritten"] and result["prompt"] == original),
            "neyvia-core.prompt-preservation", "rewrite state disagrees with retained request")


def check_projection(module, surfaces, presentations, provides, entrypoint, result):
    from urllib.parse import urlparse
    candidate = str(entrypoint or "").strip()
    parsed = urlparse(candidate)
    safe = ((candidate.startswith("/") and not candidate.startswith("//")) or
            (parsed.scheme == "https" and bool(parsed.netloc)) or
            (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and bool(parsed.netloc)))
    expected = candidate if safe and str(module.get("state", "")).lower() == "active" else None
    require(result["entryPointUrl"] == expected,
            "neyvia-core.hosted-entrypoint", "inactive or unsafe module exposes a hosted entrypoint")
    if not result["valid"]:
        return  # Refused manifests promise no successful surface projection.
    expected_ids = [str(row.get("capabilityId") or "").strip() if isinstance(row, dict) else str(row).strip() for row in provides]
    require(result["surfaces"] == list(dict.fromkeys(str(value).strip() for value in surfaces if str(value).strip())) and
            result["presentations"] == list(dict.fromkeys(str(value).strip() for value in presentations if str(value).strip())) and
            [row["capabilityId"] for row in result["provides"]] == [identity for identity in expected_ids if identity],
            "neyvia-core.application-projection", "native module surface or capability projection lost")


def check_sdk(root, old, result):
    from .neyvia_application_contract import load_sdk_applications
    saved = [row for row in load_sdk_applications(root) if row["applicationId"] == result["applicationId"]]
    require(len(saved) == 1 and saved[0] == result["manifest"], "neyvia-core.sdk-durable", "registration differs from saved metadata")
    previous = next((row for row in old if row["applicationId"] == result["applicationId"]), None)
    require(previous is None or set(previous["services"]) <= set(saved[0]["services"]),
            "neyvia-core.sdk-durable", "reregistration dropped adopted services")


def check_bundled(sources, installations, catalog):
    require(len(catalog) == len(sources) and len({row["applicationId"] for row in catalog}) == len(sources),
            "neyvia-core.bundled-catalog", "bundled application identities lost or duplicated")
    for source, row in zip(sources, catalog):
        require(all(row[key] == source[key] for key in ("applicationId", "name", "launch")) and
                row["logoUrl"] == (source.get("logoUrl") or None) and row["marketplaceEligible"] and
                row["provides"] == source["provides"] and row["permissions"] == source["permissions"],
                "neyvia-core.bundled-catalog", "bundled metadata or capability/trust declaration lost")
        installed = source["applicationId"] in installations
        require(row["installed"] == installed and row["state"] == ("active" if installed else "available"),
                "neyvia-core.bundled-durable", "catalog installation state disagrees with saved record")


def check_install(root, result):
    from .neyvia_application_contract import _load_bundled_installations, bundled_application_catalog
    stored = _load_bundled_installations(root)
    row = next(item for item in bundled_application_catalog(root) if item["applicationId"] == result["applicationId"])
    require(result["applicationId"] in stored and row["installed"] and row["state"] == "active" and
            row["launch"] == result["launch"], "neyvia-core.bundled-durable", "installation success returned before durable activation")


def browser_owner(op, owner):
    from .neyvia_browser import fail
    if op in {"runtime.connect", "runtime.disconnect", "headless.start", "headless.stop", "profile.create", "space.create", "tab.grant", "layout", "split", "peek"} and not owner:
        fail("owner_required", "Only the PC owner may perform this browser operation")


def browser_runtime(token, supplied):
    import secrets
    from .neyvia_browser import fail
    if not token or not secrets.compare_digest(supplied, token):
        fail("invalid_runtime", "Native runtime capability is absent or expired")


def browser_url(value, parsed):
    from .neyvia_browser import fail
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        fail("invalid_url", "Use an HTTP(S) URL without embedded credentials")
    if len(value) > 8192:
        fail("invalid_url", "URL exceeds 8192 characters")


def browser_ports(ports, allowed):
    if not ports or not ports <= allowed:
        raise ValueError("Browser proof ports must belong to an assigned local range")


def browser_queue(service, action_id):
    row = service.actions[action_id]
    require(row["status"] == "queued" and "result" not in row,
            "neyvia-core.browser-pending", "queue operation claims unobserved native effect")


def browser_restored(service):
    require(all(not row["live"] and not row["agentGranted"] and row["status"] == "runtime_needed" for row in service.state["tabs"]),
            "neyvia-core.browser-pending", "restored browser retains live status or grants")


def account_device(agent, result):
    from .desktop_bridge import ALLOWED_DESKTOP_COMMANDS
    from .neyvia_accounts import ACCOUNT_COMMANDS
    require(ACCOUNT_COMMANDS <= ALLOWED_DESKTOP_COMMANDS, "neyvia-core.account-devices", "account commands unavailable through desktop boundary")
    require(isinstance(result, str) and 0 < len(result) <= 40 and not any(char in result for char in "\r\n\x00"),
            "neyvia-core.account-devices", "device label contains untrusted raw agent text")


def account_session(db, token_hash, expected, username, result):
    from .web_auth_sessions import session_id
    row = db.execute("SELECT identity_hash,username FROM web_auth_sessions WHERE token_hash=?", (token_hash,)).fetchone()
    require(row is not None and row[0] == expected and row[1] == username and
            result["username"] == username and result["sessionId"] == session_id(token_hash),
            "neyvia-core.account-session-binding", "session principal or legacy identity upgrade differs from database")


def rpc_methods(methods):
    require(not {"native.device.approvals.decide", "native.device.commands.cancel"} & set(methods),
            "neyvia-core.rpc-authority", "agent RPC exposes operator approval/cancel authority")


def rpc_capabilities(server, result):
    rpc_methods(server._methods)
    authority = result["authority"]
    actual = server.device_commands.operator_authority_status()
    require(result["methods"] == sorted(server._methods) and authority["default"] == "read-only" and
            authority["deviceCommandAutomaticRetry"] is False and authority["deviceCommandHumanIdentityCryptographicallyVerified"] is False and
            authority["deviceCommandDecisionRpcExposed"] is False and authority["deviceCommandSignedOperatorAuthorizationRequired"] is True and
            authority["deviceCommandOperatorVerifierReady"] == actual["ready"] and authority["deviceCommandOperatorKeyId"] == actual["keyId"],
            "neyvia-core.rpc-authority", "capability document overstates authority or differs from real verifier")


def rpc_reply(request, result, response):
    require(("id" not in request and response is None) or
            ("id" in request and response == {"jsonrpc": "2.0", "id": request["id"], "result": result}),
            "neyvia-core.rpc-protocol", "notification generated output or response lost identity/result")


def rpc_error(request_id, error, response):
    require(response["jsonrpc"] == "2.0" and response["id"] == request_id and response["error"]["code"] == error.code and
            response["error"]["message"] == error.message, "neyvia-core.rpc-protocol", "JSONL failure envelope changed")


def rpc_device_response(server, method, params, result):
    if method == "native.device.commands.enqueue":
        require(result["approvalId"] == params["approvalId"] and all(result[key] == params[key] for key in ("deviceId", "actorId", "sessionId", "runId")),
                "neyvia-core.rpc-device-binding", "RPC queue lost signed approval/device/actor/session/run binding")
    if method == "native.device.commands.complete":
        saved = server.device_commands.get(result["commandId"])
        require(result == saved and result["commandId"] == params["commandId"] and result["status"] == params["status"] and
                (params["status"] != "succeeded" or result["executionProven"] is True),
                "neyvia-core.rpc-device-binding", "terminal RPC receipt differs from authenticated stored command")


def mcp_catalog(tools):
    names = [row["name"] for row in tools]
    require(names == sorted(names) and "neyvia.time.budget" in names and
            any(row.get("execution", {}).get("taskSupport") == "required" for row in tools),
            "neyvia-core.mcp-protocol", "MCP catalog is unordered or missing durable/synchronous execution surfaces")


def mcp_initialize(requested, result):
    require(result["protocolVersion"] == requested and result["serverInfo"]["title"].startswith("N-E-Y-V-I-A") and
            result["capabilities"]["tasks"]["requests"]["tools"]["call"] == {},
            "neyvia-core.mcp-protocol", "MCP initialization lost negotiated protocol/task augmentation")


def mcp_call_pre(server, params):
    name = str(params.get("name") or "")
    definition = next((row for row in server.tools if row["name"] == name), {})
    if definition.get("execution", {}).get("taskSupport") == "required" and not params.get("task"):
        raise RuntimeError(f"{name} requires task-augmented execution")


def mcp_call_post(server, params, result):
    name = str(params.get("name") or "")
    args = params.get("arguments") or {}
    if "task" in result:
        task = server.store.get_task(result["task"]["taskId"])
        require(task["missionId"] == args["missionId"] and "model-immediate-response" in next(iter(result["_meta"])) and
                result["task"]["status"] == ("working" if task["status"] in {"queued", "waiting", "working"} else task["status"]),
                "neyvia-core.mcp-task-durable", "MCP task handle differs from saved task")
        if name == "neyvia.training.batch.start":
            children = [row for row in server.store.list_tasks(mission_id=args["missionId"], limit=1000) if row["parentTaskId"] == task["taskId"]]
            require(len(children) == max(1, min(int(args.get("modelCount", 1)), 128)) and
                    all(row["payload"]["wakePolicy"] == "terminal_or_input_only" for row in children),
                    "neyvia-core.mcp-task-durable", "durable training batch children or wake policy mismatch")
    value = result.get("structuredContent", {})
    if name == "neyvia.time.budget":
        require("task" not in result and type(value.get("shouldContinue")) is bool, "neyvia-core.mcp-sync-budget", "time budget response is not synchronous decision")
    if name == "neyvia.autonomy.check":
        expected = server.store.autonomy_allows(args["leaseId"], action=args["action"], context=dict(args.get("context") or {}))
        require(value == expected, "neyvia-core.mcp-autonomy", "MCP response differs from durable scoped policy decision")
    if name == "neyvia.autonomy.revoke":
        require(value["active"] is False, "neyvia-core.mcp-autonomy", "revoked lease still active")
    if name == "neyvia.question.branch":
        stored = server.conversations.get_conversation(value["conversationId"])
        require(stored["capabilityPolicy"]["readOnly"] and value["capabilityPolicy"]["readOnly"],
                "neyvia-core.mcp-conversation", "question branch lacks durable read-only policy")
    if name == "neyvia.question.action.check":
        stored = server.conversations.get_conversation(args["conversationId"])
        if stored["capabilityPolicy"]["readOnly"] and args["action"] == "file.write":
            require(value["allowed"] is False, "neyvia-core.mcp-conversation", "question branch allowed mutation")
    if name == "neyvia.conversation.search":
        for hit in value["results"]:
            require(hit["conversationId"] == server.conversations.get_conversation(hit["conversationId"])["conversationId"],
                    "neyvia-core.mcp-conversation", "search hit has no durable conversation provenance")
    if name == "neyvia.context.retrieve":
        with server.conversations._connection() as db:
            for item in value["items"]:
                if item.get("evidenceTurnId"):
                    row = db.execute("SELECT conversation_id FROM conversation_turns WHERE turn_id=?", (item["evidenceTurnId"],)).fetchone()
                    require(row is not None and row[0] == item["conversationId"], "neyvia-core.mcp-conversation", "context evidence points outside its durable conversation")
    if name == "neyvia.orchestration.plan":
        nodes = {row["nodeId"]: row for row in value["nodes"]}
        for edge in value["edges"]:
            require(nodes[edge["to"]]["wave"] > nodes[edge["from"]]["wave"], "neyvia-core.mcp-conversation", "dependency can run before prerequisite wave")
        plan = args.get("typedPlan") or args.get("leadPlan") or args.get("plan")
        if plan is not None:
            require(len(value["childConversations"]) == len(plan["children"]) and value["approvedPlanHash"] == args["approvedPlanHash"] and
                    value["parentTaskId"] == args.get("parentTaskId") and value["governor"]["maxParallel"] == plan["governor"]["maxParallel"],
                    "neyvia-core.mcp-conversation", "typed approved plan returned different child/approval/governor binding")
            for child in value["childConversations"]:
                stored = server.conversations.get_conversation(child["conversationId"])
                require(stored["metadata"] == child["metadata"] and stored["metadata"]["childTaskId"].startswith("task:"),
                        "neyvia-core.mcp-conversation", "named child contract not persisted")


def mcp_task_result(task, result):
    expected = task["result"] if task["status"] == "completed" else task["error"] or task["checkpoint"] or task
    require(result["structuredContent"] == expected and result["_meta"]["io.modelcontextprotocol/related-task"]["taskId"] == task["taskId"],
            "neyvia-core.mcp-task-durable", "terminal result lost persisted payload or related-task provenance")


def conversation_revision(actual, expected):
    if expected is not None and int(actual) != int(expected):
        raise RuntimeError(f"conversation revision conflict: expected {expected}, found {actual}")


def conversation_replay(turn_id, expected, actual):
    if actual != expected:
        raise RuntimeError(f"conversation turn id conflict: {turn_id}")


def conversation_append(db, before, turn_id, role, text, timestamp, meaningful, next_title, next_generated):
    row = db.execute("SELECT * FROM conversations WHERE conversation_id=?", (before["conversation_id"],)).fetchone()
    turn = db.execute("SELECT * FROM conversation_turns WHERE turn_id=?", (turn_id,)).fetchone()
    require(row["revision"] == before["revision"] + 1 and turn["conversation_id"] == before["conversation_id"] and
            turn["content"] == text and turn["role"] == role,
            "neyvia-core.conversation-turns", "atomic append lost identity/content or incremented revision incorrectly")
    require(row["last_meaningful_activity_at"] == (timestamp if meaningful else before["last_meaningful_activity_at"]) and
            row["updated_at"] == (timestamp if meaningful else before["updated_at"]) and row["title"] == next_title and row["generated_title"] == next_generated,
            "neyvia-core.conversation-activity", "heartbeat advanced meaningful activity or title policy differs from stored result")


def conversation_page(result, limit, before):
    turns, page = result["turns"], result["turnPage"]
    ordering = [(row["createdAt"], row["turnId"]) for row in turns]
    require(len(turns) <= limit and ordering == sorted(ordering) and len({row["turnId"] for row in turns}) == len(turns) and
            page["returnedTurns"] == len(turns) and page["turnLimit"] == limit and
            page["beforeTurnId"] == (turns[0]["turnId"] if turns and page["hasEarlierTurns"] else ""),
            "neyvia-core.conversation-pages", "page bound/order/cursor metadata differs from returned turns")
    if before:
        require(all((row["createdAt"], row["turnId"]) < before for row in turns), "neyvia-core.conversation-pages", "page overlaps its exclusive cursor")


def conversation_question(parent, branch):
    require(branch["parentConversationId"] == parent["conversationId"] and branch["branchKind"] == "question" and
            branch["capabilityPolicy"]["readOnly"] and not branch["capabilityPolicy"]["mutationAllowed"] and
            branch["turns"][0]["role"] == "user", "neyvia-core.conversation-question", "question branch lost parent/user-turn/read-only contract")


def conversation_action(conversation, normalized, result):
    if conversation["capabilityPolicy"].get("readOnly"):
        from .neyvia_conversations import QUESTION_BRANCH_ALLOWED_PREFIXES
        prefixes = conversation["capabilityPolicy"].get("allowedActionPrefixes") or QUESTION_BRANCH_ALLOWED_PREFIXES
        expected = bool(normalized) and any(normalized.startswith(str(value).lower()) for value in prefixes)
        require(result["allowed"] == expected and result["policy"] == "ask" and result["conversationId"] == conversation["conversationId"],
                "neyvia-core.conversation-question", "question action response differs from host policy")


def conversation_delete(db, conversation_id, timestamp, fts):
    row = db.execute("SELECT status,deleted_at FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
    require(row["status"] == "deleted" and row["deleted_at"] == timestamp and
            db.execute("SELECT COUNT(*) FROM context_atoms WHERE conversation_id=? AND deleted_at IS NULL", (conversation_id,)).fetchone()[0] == 0 and
            (not fts or db.execute("SELECT COUNT(*) FROM conversation_search_fts WHERE conversation_id=?", (conversation_id,)).fetchone()[0] == 0),
            "neyvia-core.conversation-deletion", "deletion lost tombstone or left searchable context")


def conversation_receipts(store, conversation_id, results):
    for row in results:
        turn = store.get_turn(row["turnId"], hydrate=False)
        require("content" not in row and set(row) == {"turnId", "conversationId", "createdAt", "receipt"} and
                row["conversationId"] == conversation_id == turn["conversationId"] and row["receipt"] == store._turn_receipt_from_metadata(turn["metadata"]),
                "neyvia-core.conversation-receipts", "receipt index leaks turn content or loses nested provenance")


def conversation_import(store, result, before):
    with store._connection() as db:
        after = (db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], db.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0])
    require(after[0] >= before[0] + result["importedConversations"] and after[1] >= before[1] + result["importedTurns"],
            "neyvia-core.conversation-import", "legacy import receipt differs from durable identity counts")


def agent_version():
    from .neyvia_version import NEYVIA_AGENT_VERSION
    value = f"Neyvia Agent {NEYVIA_AGENT_VERSION}"
    require(value.startswith("Neyvia Agent ") and "\n" not in value, "neyvia-core.agent-version", "version must be one readable product/version line")
    return value


def agent_config(config):
    from .neyvia_agent import _SAFE_ID
    if not _SAFE_ID.fullmatch(config.session_id):
        raise ValueError("session_id must be a safe 1-128 character identifier.")
    if not 1 <= config.max_turns <= 64:
        raise ValueError("max_turns must be between 1 and 64.")
    if (config.transport.strip().lower() or "auto") not in {"auto", "responses", "chat-completions", "codex-cli"}:
        raise ValueError("transport must be auto, responses, chat-completions, or codex-cli.")


def mobile_project(root, candidates, kind, name, ios_id, android_id, result):
    expected_root = next((root / value for value in candidates if value and (root / value / "index.html").is_file()), None)
    require(result["kind"] == kind and result["name"] == name and result["iosBundleId"] == ios_id and result["androidPackage"] == android_id and
            result["webRoot"] == (str(expected_root) if expected_root else ""),
            "neyvia-core.mobile-project", "mobile project kind/metadata/first existing web export differs from source config")


def mobile_scheme(source, dark, result):
    import re
    from .neyvia_mobile_studio import _TRUE_MEDIA, _FALSE_MEDIA
    require(not re.search(r"\(\s*prefers-color-scheme\s*:\s*(dark|light)\s*\)", result) and "env(safe-area-inset-" not in result,
            "neyvia-core.mobile-injection", "preview left unresolved frame color/safe-area queries")
    for scheme, expected in [("dark", _TRUE_MEDIA if dark else _FALSE_MEDIA), ("light", _FALSE_MEDIA if dark else _TRUE_MEDIA)]:
        if re.search(r"\(\s*prefers-color-scheme\s*:\s*" + scheme + r"\s*\)", source):
            require(expected in result, "neyvia-core.mobile-injection", "frame color query answers lost")


def mobile_inject(config, result):
    import json, html
    prefix = "window.__NX_MOBILE__="
    begin = result.index(prefix) + len(prefix)
    end = result.index(";</script>", begin)
    require(json.loads(result[begin:end]) == config and "</script" not in result[begin:end].lower() and
            f'<base href="{html.escape(config["base"], quote=True)}">' in result and
            all(f"--nx-safe-area-inset-{side}:{value}px;" in result for side, value in config["safe"].items()),
            "neyvia-core.mobile-injection", "preview config/script boundary/base/safe-area metadata lost")


def mobile_target(web_root, target):
    target.resolve().relative_to(web_root.resolve())


def mobile_storage_body(body):
    return isinstance(body, dict) and all(isinstance(key, str) and isinstance(value, str) for key, value in body.items())


def mobile_storage_saved(path, body):
    import json
    require(json.loads(path.read_text(encoding="utf-8")) == body, "neyvia-core.mobile-storage", "preview string map changed before durable response")


def mobile_sandbox(csp):
    require("sandbox" in csp.split() and "allow-same-origin" not in csp.split(), "neyvia-core.mobile-confinement", "preview response grants Neyvia origin authority")


def self_check(root):
    from . import neyvia_ecosystem as prompts
    from . import neyvia_application_contract as apps
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    def run(identity, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            action()
            cases.append({"id": identity, "contracts": contracts, "ok": True})
        except Exception as exc:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "error": str(exc)})

    def preparation():
        for subject, expected in [("Design the SDK, marketplace, runtime and orchestration ecosystem architecture.", "ecosystem_architecture"),
                                  ("Find the latency bottleneck and optimize memory usage.", "optimization"), ("Hello", "general")]:
            value = prompts.infer_task_prompt_profile(subject)
            require(value["profileId"] == expected, "neyvia-core.prompt-selection", "startup classification drift")
        require(prompts.infer_task_prompt_profile("Debug the broken UI image preview.", requested_profile="research")["selection"] == "explicit",
                "neyvia-core.prompt-selection", "startup explicit profile lost")
        for requested in ("ecosystem_architecture", "study", "communication", "experimentation"):
            original = "Preserve my full request, including all runtime relationships."
            context = {"scope": "Owned hardware only", "ownership": "Architecture owner", "doNotTouch": "Serving", "constraints": "Per-action approval"}
            result = prompts.apply_silent_ecosystem_rewrite(original, requested_profile=requested, task_context=context)
            require(original in result["prompt"], "neyvia-core.prompt-preservation", "startup rewrite dropped request")
        prompts.apply_silent_ecosystem_rewrite("  preserve whitespace  ", enabled=False)
        value = prompts.build_image_generation_prompt({"operation": "edit", "prompt": {"text": "Botanical observatory", "exactText": "NEYVIA", "negative": "no lettering"}, "compositionIntent": "left third", "canvas": {"width": 1536, "height": 1024}})
        require("Exact visible text: NEYVIA" in value["prompt"] and "Composition: left third" in value["prompt"], "neyvia-core.image-spec", "startup visual fields lost")

    def application_lifecycle():
        module = {"moduleId": "proofs.weather", "name": "Weather", "version": "1.0.0", "state": "active", "publisher": {"id": "proofs"},
                  "runtime": {"entrypoint": "web/index.html"}, "permissions": [],
                  "applicationProjection": {"compatibility": {"neyvia": ">=1"}, "capabilities": [{"operationId": "weather.read", "name": "Read"}],
                                            "surfaces": [{"surfaceId": "weather.panel", "kind": "embedded", "title": "Weather", "route": "app://weather"}]}}
        value = apps._module_to_manifest(module)
        require(value["valid"] and value["surfaces"] == ["marketplace"] and value["presentations"] == ["inline-card"] and
                value["provides"][0]["capabilityId"] == "weather.read" and value["entryPointUrl"] == "/api/application/proofs.weather/",
                "neyvia-core.application-projection", "startup active projection failed")
        require(apps._module_to_manifest({**module, "state": "installed"})["entryPointUrl"] is None,
                "neyvia-core.application-projection", "startup inactive projection exposed entrypoint")
        for state, url, expected in [("active", "https://apps.example/reader", "https://apps.example/reader"),
                                     ("installed", "https://apps.example/reader", None),
                                     ("active", "file:///tmp/reader.html", None)]:
            projected = apps._module_to_manifest({**module, "state": state, "runtime": {"servedUrl": url}})
            require(projected["entryPointUrl"] == expected, "neyvia-core.hosted-entrypoint", "hosted projection did not enforce lifecycle and URL safety")
        apps.register_sdk_application(root, {"applicationId": "proofs.notes", "name": "First", "services": ["agents"]})
        apps.register_sdk_application(root, {"applicationId": "proofs.notes", "name": "Second", "summary": "Updated", "services": ["memory"]})
        row = apps.load_sdk_applications(root)[0]
        require(row["name"] == "Second" and row["summary"] == "Updated" and row["services"] == ["agents", "memory"],
                "neyvia-core.sdk-durable", "startup SDK adoption failed")

    def bundled_lifecycle():
        catalog = {row["applicationId"]: row for row in apps.bundled_application_catalog(root)}
        require(len(apps.BUNDLED_APPLICATIONS) == 32, "neyvia-core.bundled-catalog", "startup bundled catalog count changed; review baseline coverage")
        for name, target in [("LumaForge", "lumaforge"), ("Frameweave", "frameweave"), ("Citecraft", "citecraft"), ("Aegis Range", "aegis-range"), ("CueLedger", "cueledger")]:
            row = catalog["neyvia.app." + target]
            require(row["name"] == name and row["launch"] == {"kind": "surface", "target": target} and
                    row["logoUrl"] == f"/neyvia-apps/{target}.png?v=20260728" and not row["installed"],
                    "neyvia-core.bundled-catalog", "startup studio metadata drift")
        first = apps.install_bundled_application(root, "neyvia.app.citecraft", requested_by="proofs-d")
        second = apps.install_bundled_application(root, "neyvia.app.citecraft", requested_by="proofs-d")
        require(first["installed"] and second["alreadyInstalled"], "neyvia-core.bundled-durable", "startup durable idempotent activation failed")
        try:
            apps.install_bundled_application(root, "unknown.proof")
        except ValueError:
            pass
        else:
            raise ValueError("Unknown bundled application was accepted")

    def browser_journey():
        from .neyvia_browser import BrowserService, BrowserError, web_url
        from .browser_obscura import proof_ports
        import subprocess, os, sys
        service = BrowserService(root / "browser")
        # An agent's default engine is headless Obscura, which the owner must
        # start explicitly; without it the open is refused and no tab exists.
        try:
            service.request("tab.open", {"url": proof_text("http://127.0.0.1:48491/")})
        except BrowserError as exc:
            require(exc.code == "engine_missing" and not service.view()["tabs"], "neyvia-core.browser-pending", "unstarted Obscura open left a tab")
        else:
            raise ValueError("Obscura open succeeded without an explicitly started engine")
        # The visible WebView2 route queues until the owner's runtime connects.
        opened = service.request("tab.open", {"url": proof_text("http://127.0.0.1:48491/"), "engine": "webview2"})
        require(opened["status"] == "queued" and service.request("action.get", {"actionId": opened["actionId"]})["status"] == "queued" and
                not service.view()["runtime"]["connected"] and not service.view()["tabs"][0]["live"] and not service.view()["tabs"][0]["agentGranted"],
                "neyvia-core.browser-pending", "queued open pretended to navigate")
        restored = BrowserService(root / "browser").view()["tabs"][0]
        require(restored["status"] == "runtime_needed" and not restored["agentGranted"], "neyvia-core.browser-pending", "restored tab grant survived")
        for action, code in [(lambda: service.request("tab.grant", {"tabId": opened["tabId"], "enabled": True}), "owner_required"),
                             (lambda: service.runtime({"op": "report", "token": "forged"}), "invalid_runtime")]:
            try:
                action()
            except BrowserError as exc:
                require(exc.code == code and exc.status == 403 and not service.view()["tabs"][0]["agentGranted"],
                        "neyvia-core.browser-authority", "denial differs from authority or changed grant")
            else:
                raise ValueError("Browser authority boundary accepted forged request")
        for url in ("file:///private", "javascript:alert(1)", "https://user:fixture@example.com"):
            try:
                web_url(url)
            except BrowserError as exc:
                require(exc.code == "invalid_url" and exc.status == 400, "neyvia-core.browser-url", "unsafe URL denial changed")
            else:
                raise ValueError("Unsafe URL accepted")
        # Isolated interpreters exercise the real environment entrypoint without
        # mutating the caller's global environment or contacting any service.
        command = [sys.executable, "-c", "import json; from grant_agent.browser_obscura import proof_ports; print(json.dumps(sorted(proof_ports())))"]
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        import json
        env = dict(os.environ, NEYVIA_BROWSER_PROOF_PORTS=proof_text("48491,48499"))
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH", ""))))
        done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
        require(done.returncode == 0 and json.loads(done.stdout) == sorted([proof_port(48491), proof_port(48499)]), "neyvia-core.browser-ports", "assigned proof port set changed")
        env["NEYVIA_BROWSER_PROOF_PORTS"] = "47881"
        denied = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
        require(denied.returncode != 0 and "cannot include the live Neyvia ports" in denied.stderr, "neyvia-core.browser-ports", "protected service accepted as proof port")

    def account_journey():
        from .neyvia_accounts import describe_device
        from .web_auth_sessions import WebAuthSessions
        for agent, label in [("Mozilla Windows Chrome/141.0 Safari/537.36", "Chrome on Windows"),
                             ("Mozilla iPhone Version/19.0 Safari/604.1", "Safari on iPhone"),
                             ("Mozilla Macintosh Firefox/140.0", "Firefox on Mac"),
                             ("Mozilla Android Chrome/141 EdgA/141", "Edge on Android"), ("Python-urllib/3.13", "Neyvia desktop app"), ("", "Unknown device")]:
            require(describe_device(agent) == label, "neyvia-core.account-devices", "startup plain device name drift")
        store_root = root / "sessions"
        token = WebAuthSessions(store_root, auth_identity="scratch-shared").issue({"username": "paul", "role": "account"})
        identities = {"paul": "paul-v1", "maya": "maya-v1"}
        store = WebAuthSessions(store_root, auth_identity="scratch-shared", user_identity=identities.get)
        require(store.lookup(token)["username"] == "paul", "neyvia-core.account-session-binding", "legacy session not upgraded")
        moved = WebAuthSessions(store_root, auth_identity="scratch-changed", user_identity=identities.get)
        require(moved.lookup(token) is not None, "neyvia-core.account-session-binding", "upgraded session still uses shared identity")
        member = moved.issue({"username": "maya", "role": "account"})
        identities["paul"] = "paul-v2"
        require(moved.lookup(token) is None and moved.lookup(member)["username"] == "maya", "neyvia-core.account-session-binding", "account change revoked unrelated session")
        identities.pop("maya")
        require(moved.lookup(member) is None, "neyvia-core.account-session-binding", "removed principal retained session")

    def rpc_journey():
        from .neyvia_native_rpc import NativeRpcServer, RpcError, serve
        import io, json
        service = NativeRpcServer(root / "rpc")
        capabilities = service.dispatch({"jsonrpc": "2.0", "id": 1, "method": "native.capabilities", "params": {}})["result"]
        required = {"native.checkpoints.restore", "native.device.approvals.request", "native.device.approvals.get", "native.device.commands.enqueue"}
        require(required <= set(capabilities["methods"]) and not capabilities["authority"]["deviceCommandOperatorVerifierReady"] and
                capabilities["authority"]["deviceCommandOperatorKeyId"] is None, "neyvia-core.rpc-authority", "default capability document differs from actual unavailable operator")
        plan = service.dispatch({"jsonrpc": "2.0", "id": 2, "method": "native.plan.compile", "params": {"task": "Diagnose and repair reconnect failure", "resourceMode": "eco"}})["result"]
        require(plan["capsule"]["id"] == "diagnosis-repair" and plan["resourceProfile"]["mode"] == "eco", "neyvia-core.rpc-plan", "RPC plan lost selected behavior/resource")
        try:
            service.dispatch({"jsonrpc": "2.0", "id": 3, "method": "native.device.commands.cancel", "params": {"commandId": "command_fake", "cancelledBy": "human:operator", "humanConfirmed": True}})
        except RpcError as exc:
            require(exc.code == -32601, "neyvia-core.rpc-authority", "forged cancel denial changed")
        else:
            raise ValueError("Agent RPC can forge human cancellation")
        source = io.StringIO('not-json\n' + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "native.plan.compile", "params": {}}) + '\n' + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "native.alive", "params": {}}) + '\n')
        output = io.StringIO()
        require(serve(root / "rpc-jsonl", input_stream=source, output_stream=output) == 0, "neyvia-core.rpc-protocol", "JSONL worker failed")
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        require(rows[0]["error"]["code"] == -32700 and rows[1]["error"]["code"] == -32602 and rows[2]["result"]["alive"],
                "neyvia-core.rpc-protocol", "malformed line or parameter error stopped subsequent action")
        quiet = io.StringIO()
        serve(root / "rpc-notifications", input_stream=io.StringIO(json.dumps({"jsonrpc": "2.0", "method": "native.alive", "params": {}}) + '\n'), output_stream=quiet)
        require(quiet.getvalue() == "", "neyvia-core.rpc-protocol", "notification emitted response")

    def rpc_signed_journey():
        from .neyvia_native_rpc import NativeRpcServer, RpcError
        from .native_device_operator_signing_wire import prepare_signing_request, inspect_signing_request, submit_operator_signature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import hashlib, base64
        base = root / "rpc-signed"
        base.mkdir()
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        public_path = base / "scratch-public.pem"
        public_path.write_bytes(public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        key_id = "sha256:" + hashlib.sha256(public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()
        service = NativeRpcServer(base / "workspace", device_operator_public_key_path=public_path, device_operator_key_id=key_id)
        serial = 0
        def call(method, params):
            nonlocal serial
            serial += 1
            return service.dispatch({"jsonrpc": "2.0", "id": serial, "method": method, "params": params})["result"]
        authority = call("native.capabilities", {})["authority"]
        require(authority["deviceCommandOperatorVerifierReady"] and authority["deviceCommandOperatorKeyId"] == key_id,
                "neyvia-core.rpc-device-binding", "ephemeral pinned verifier unavailable")
        pairing = call("native.pairing.create", {"target": "phone", "scopes": ["device.commands", "mission.read", "proof.read"]})
        device = call("native.pairing.redeem", {"pairingId": pairing["pairingId"], "pairingToken": pairing["pairingToken"], "displayName": "Scratch paired device"})
        credential = {"deviceId": device["deviceId"], "deviceSecret": device["deviceSecret"]}
        call("native.device.capabilities.publish", {**credential, "capabilities": ["app.open"]})
        context = {"actorId": "agent:rpc", "sessionId": "session:rpc", "runId": "run:rpc"}
        approval = call("native.device.approvals.request", {"deviceId": device["deviceId"], "action": "app.open", "arguments": {"route": "agent"}, **context})
        try:
            call("native.device.approvals.decide", {"approvalId": approval["approvalId"], "decision": "approved", "humanConfirmed": True})
        except RpcError as exc:
            require(exc.code == -32601, "neyvia-core.rpc-authority", "agent RPC can approve own device action")
        else:
            raise ValueError("RPC operator decision authority exposed")
        request = prepare_signing_request(service.device_commands, approval["approvalId"], decided_by="human:local")
        inspected = inspect_signing_request(request)
        approved = submit_operator_signature(service.device_commands, request, signature_base64=base64.b64encode(private.sign(inspected["signingBytes"])).decode("ascii"))
        require(approved["status"] == "approved" and approved["operatorDecisionSignatureVerified"] and not approved["humanIdentityCryptographicallyVerified"],
                "neyvia-core.rpc-device-binding", "host approval lost signature/personhood distinction")
        queued = call("native.device.commands.enqueue", {"deviceId": device["deviceId"], "action": "app.open", "arguments": {"route": "agent"}, "idempotencyKey": "proofs-rpc-open-agent-0001", "approvalId": approval["approvalId"], **context})
        claimed = call("native.device.commands.claim", credential)["command"]
        require(queued["status"] == "queued" and claimed["arguments"] == {"route": "agent"}, "neyvia-core.rpc-device-binding", "exact signed queued action not claimable")
        settled = call("native.device.commands.complete", {**credential, "commandId": claimed["commandId"], "claimId": claimed["claimId"], "status": "succeeded", "result": {"handled": True}})
        require(settled["status"] == "succeeded" and settled["executionProven"], "neyvia-core.rpc-device-binding", "authenticated terminal receipt not persisted")

    def mcp_journey():
        from .neyvia_mcp import NeyviaMCPServer, MCP_PROTOCOL_VERSION
        from .neyvia_conversations import FROZEN_SOL_PLANNER_ROUTE, typed_plan_hash
        from .proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(root / 'mcp')
        service = NeyviaMCPServer(root / "mcp")
        serial = 0
        def request(method, params=None):
            nonlocal serial
            serial += 1
            return service.handle({"jsonrpc": "2.0", "id": serial, "method": method, "params": params or {}})
        def call(name, arguments, task=None):
            value = {"name": name, "arguments": arguments}
            if task is not None:
                value["task"] = task
            response = request("tools/call", value)
            require("error" not in response, "neyvia-core.mcp-protocol", f"scratch tool call failed: {response.get('error')}")
            return response["result"]
        initialized = request("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}})
        require(initialized["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION, "neyvia-core.mcp-protocol", "protocol mismatch")
        first = request("tools/list")["result"]["tools"]
        require(first == request("tools/list")["result"]["tools"], "neyvia-core.mcp-protocol", "catalog nondeterministic")
        args = {"missionId": "proofs-research", "idempotencyKey": "research:first", "query": "durable systems"}
        denied = request("tools/call", {"name": "neyvia.research.start", "arguments": args})
        require(denied["error"]["code"] == -32002, "neyvia-core.mcp-task-durable", "task augmentation not required")
        handle = call("neyvia.research.start", args, {"ttl": 60000})["task"]
        require(request("tasks/get", {"taskId": handle["taskId"]})["result"]["task"]["taskId"] == handle["taskId"],
                "neyvia-core.mcp-task-durable", "task handle not openable")
        batch = call("neyvia.training.batch.start", {"missionId": "proofs-training", "idempotencyKey": "training:28", "modelCount": 28, "training": {"dataset": "local-fixture-only"}}, {"ttl": 86400000})["task"]
        require(len(service.store.list_tasks(mission_id="proofs-training")) == 29, "neyvia-core.mcp-task-durable", "batch did not persist 28 children")
        task = service.store.submit_task(mission_id="proofs-result", kind="extension.research", idempotency_key="result:first")
        service.store.transition_task(task["taskId"], "working")
        service.store.transition_task(task["taskId"], "completed", result={"answer": 42})
        terminal = request("tasks/result", {"taskId": task["taskId"]})["result"]
        require(terminal["structuredContent"] == {"answer": 42}, "neyvia-core.mcp-task-durable", "result payload changed")
        budget = call("neyvia.time.budget", {"deadlineAt": "2999-01-01T00:00:00Z", "estimatedNextSeconds": 20, "verificationReserveSeconds": 10, "optional": True})
        require(budget["structuredContent"]["shouldContinue"] and "task" not in budget, "neyvia-core.mcp-sync-budget", "available time rejected")
        lease = call("neyvia.autonomy.grant", {"missionId": "proofs-autonomy", "durationSeconds": 900, "allowedActions": ["file_write"], "allowedRoots": [str(root)], "destructiveAllowed": False})["structuredContent"]
        allowed = call("neyvia.autonomy.check", {"leaseId": lease["leaseId"], "action": "file_write", "context": {"path": str(root / "proof.txt")}})["structuredContent"]
        denied = call("neyvia.autonomy.check", {"leaseId": lease["leaseId"], "action": "shell_command"})["structuredContent"]
        require(allowed["allowed"] and not denied["allowed"] and denied["reason"] == "action_out_of_scope", "neyvia-core.mcp-autonomy", "scoped policy decision failed")
        call("neyvia.autonomy.revoke", {"leaseId": lease["leaseId"]})
        chat = service.conversations.create_conversation(kind="chat", title="Durable provenance")
        turn = service.conversations.append_turn(chat["conversationId"], role="assistant", content="Use durable provenance for every retained decision.")
        service.conversations.put_context_atom(chat["conversationId"], kind="decision", content="Question Branches are read-only.", evidence_turn_id=turn["turnId"])
        search = call("neyvia.conversation.search", {"query": "durable provenance"})["structuredContent"]
        branch = call("neyvia.question.branch", {"parentConversationId": chat["conversationId"], "question": "What may change?"})["structuredContent"]
        refused = call("neyvia.question.action.check", {"conversationId": branch["conversationId"], "action": "file.write"})["structuredContent"]
        context = call("neyvia.context.retrieve", {"query": "read-only"})["structuredContent"]
        parent = service.conversations.create_conversation(kind="orchestration", title="MCP plan")
        graph = call("neyvia.orchestration.plan", {"conversationId": parent["conversationId"], "tasks": [{"id": "inspect", "title": "Inspect", "assignedScope": ["src"]}, {"id": "verify", "title": "Verify", "dependencies": ["inspect"], "assignedScope": ["proofs"]}]})["structuredContent"]
        require(search["results"][0]["conversationId"] == chat["conversationId"] and not refused["allowed"] and context["items"][0]["evidenceTurnId"] == turn["turnId"] and graph["nodes"][1]["wave"] == 1,
                "neyvia-core.mcp-conversation", "conversation/search/context/dependency provenance differs")
        parent = service.conversations.create_conversation(kind="orchestration", title="MCP typed lead")
        children = [{"id": f"child_{i+1}", "name": f"MCP child {i+1}", "objective": "Return evidenced handback", "route": {"runtimeId": "codex", "provider": "openai-codex", "model": "gpt-5.6-luna", "effort": "high"}, "budget": {"maxSeconds": 90}, "authority": {"allowed": ["read_assigned_scope"]}, "tools": ["reasoning"], "handback": {"schema": "neyvia.agent_delta.v1"}} for i in range(6)]
        plan = {"schema": "neyvia.orchestration.typed-lead-plan.v1", "planId": "proofs-mcp-plan", "approved": True, "governor": {"maxParallel": 2}, "preset": {"id": "proofs-mcp"}, "children": children}
        plan["approvedPlanHash"] = typed_plan_hash(plan)
        run = service.conversations.create_dynamic_plan_run(parent["conversationId"], planner_route=FROZEN_SOL_PLANNER_ROUTE)
        service.conversations.update_dynamic_plan_run(run["runId"], status="awaiting_approval", typed_plan=plan, plan_hash=typed_plan_hash(plan))
        approval = service.conversations.approve_dynamic_plan_run(run["runId"], approval_receipt={"schema": "neyvia.approval.receipt.v1", "issuer": "neyvia", "approved": True, "runId": run["runId"], "planHash": typed_plan_hash(plan)})
        call("neyvia.orchestration.plan", {"conversationId": parent["conversationId"], "typedPlan": plan, "approvedPlanHash": plan["approvedPlanHash"], "runId": run["runId"], "approvalReceipt": approval["approvalReceipt"], "parentTaskId": "task:proofs-mcp-parent"})

    def conversation_journey():
        from .neyvia_conversations import NeyviaConversationStore
        store = NeyviaConversationStore(root / "conversations")
        chat = store.create_conversation(kind="chat", now="2026-07-21T10:00:00Z")
        orchestration = store.create_conversation(kind="orchestration", title_mode="suggest", now="2026-07-21T10:01:00Z")
        store.append_turn(chat["conversationId"], role="user", content="Please design the durable conversation search and memory system.", now="2026-07-21T10:02:00Z")
        store.append_turn(orchestration["conversationId"], role="assistant", content="Background runtime heartbeat", meaningful=False, turn_kind="heartbeat", now="2026-07-21T10:03:00Z")
        history = store.list_conversations()
        require([row["conversationId"] for row in history] == [chat["conversationId"], orchestration["conversationId"]] and
                history[0]["title"] == "Design the durable conversation search and memory system" and history[1]["title"] == "New conversation" and
                history[1]["generatedTitle"] == "Background runtime heartbeat" and history[1]["lastMeaningfulActivityAt"] == "2026-07-21T10:01:00Z",
                "neyvia-core.conversation-activity", "meaningful ordering or automatic/suggest title policy drift")
        branch = store.create_question_branch(orchestration["conversationId"], question="Which files own durable conversation state?")
        require(store.action_allowed(branch["conversationId"], "file.read")["allowed"] and not store.action_allowed(branch["conversationId"], "file.write")["allowed"] and
                not store.action_allowed(branch["conversationId"], "email.send")["allowed"], "neyvia-core.conversation-question", "read-only branch can write/send")
        durable = store.create_conversation(kind="chat")
        turn = store.append_turn(durable["conversationId"], role="user", content="Retain this live turn once", source="operator", expected_revision=durable["revision"], turn_id="proofs-live-turn", idempotent=True)
        replayed = store.append_turn(durable["conversationId"], role="user", content="Retain this live turn once", source="operator", expected_revision=durable["revision"], turn_id="proofs-live-turn", idempotent=True)
        require(turn == replayed and store.get_conversation(durable["conversationId"], include_turns=True)["revision"] == durable["revision"] + 1,
                "neyvia-core.conversation-turns", "idempotent replay changed revision/result")
        for kwargs in [{"content": "Stale append", "expected_revision": durable["revision"]}, {"content": "Different payload", "source": "operator", "turn_id": "proofs-live-turn", "idempotent": True}]:
            try:
                store.append_turn(durable["conversationId"], role="user", **kwargs)
            except RuntimeError:
                pass
            else:
                raise ValueError("Conflicting append accepted")
        require(len(store.get_conversation(durable["conversationId"], include_turns=True)["turns"]) == 1, "neyvia-core.conversation-turns", "rejection appended conflicting turn")
        paged = store.create_conversation(kind="chat", title="Paged")
        for index in range(10):
            store.append_turn(paged["conversationId"], role="user", content=f"Turn {index}", turn_id=f"page-{index:02d}", now=f"2026-07-24T05:00:{index:02d}Z")
        cursor, seen = "", []
        for _ in range(3):
            page = store.get_conversation_page(paged["conversationId"], turn_limit=4, before_turn_id=cursor)
            seen += [row["turnId"] for row in page["turns"]]
            cursor = page["turnPage"]["beforeTurnId"]
        require(len(seen) == 10 and len(set(seen)) == 10 and not cursor, "neyvia-core.conversation-pages", "page traversal lost/duplicated turns")
        receipt = {"schema": "fluxio.turn_receipt.v1", "status": "completed", "proofArtifacts": [{"path": "proof/result.json"}]}
        delivered = store.append_turn(durable["conversationId"], role="assistant", content="Private result text", metadata={"runtimeResult": {"compartment": {"turnReceipt": receipt}}})
        index = store.list_turn_receipts(durable["conversationId"])
        require(index[0]["receipt"] == receipt and store.get_turn_receipt(durable["conversationId"], delivered["turnId"])["receipt"] == receipt,
                "neyvia-core.conversation-receipts", "nested receipt could not reopen")
        try:
            store.get_turn_receipt(paged["conversationId"], delivered["turnId"])
        except ValueError:
            pass
        else:
            raise ValueError("Receipt opened through wrong conversation")
        deleted = store.create_conversation(kind="chat", title="Delete indexed thread")
        store.put_context_atom(deleted["conversationId"], kind="decision", content="Indexed secret decision")
        require(store.search("indexed secret")["results"], "neyvia-core.conversation-deletion", "deletion fixture not indexed")
        store.delete_conversation(deleted["conversationId"], now="2026-07-21T14:00:00Z")
        require(not store.search("indexed secret")["results"] and not store.retrieve_context("indexed secret")["items"] and
                store.get_conversation(deleted["conversationId"])["deletedAt"] == "2026-07-21T14:00:00Z", "neyvia-core.conversation-deletion", "deleted evidence still searchable or tombstone missing")
        legacy = {"chatSessions": [{"id": "proofs-legacy", "title": "Recovered notes"}], "chatSessionTranscripts": {"proofs-legacy": [{"id": "legacy-turn", "role": "user", "title": "Preserve the fine-tuning recipe across crashes."}]}}
        first, second = store.import_legacy_state(legacy), store.import_legacy_state(legacy)
        require(first["importedConversations"] == first["importedTurns"] == 1 and second["importedConversations"] == second["importedTurns"] == 0 and
                second["skippedConversations"] == second["skippedTurns"] == 1 and store.search("fine-tuning recipe")["results"][0]["conversationId"] == "proofs-legacy",
                "neyvia-core.conversation-import", "legacy import not idempotent/searchable")

    def agent_entry_journey():
        from .neyvia_agent import NeyviaAgentConfig, main
        import contextlib, io, subprocess, sys, os
        for kwargs in [{"session_id": "../escape"}, {"session_id": "valid-session", "max_turns": 65}, {"session_id": "valid-session", "transport": "pretend"}]:
            try:
                NeyviaAgentConfig(root=root, **kwargs).validated()
            except ValueError:
                pass
            else:
                raise ValueError("Invalid native agent configuration accepted")
        value = NeyviaAgentConfig(root=root, session_id="valid-session", max_turns=1).validated()
        require(value.session_id == "valid-session" and value.max_turns == 1 and value.permission_mode == "read-only", "neyvia-core.agent-config", "valid bounded agent configuration drift")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                main(["--version"])
            except SystemExit as exc:
                require(exc.code == 0, "neyvia-core.agent-version", "version required prompt/runtime execution")
        require(output.getvalue().strip() == agent_version(), "neyvia-core.agent-version", "full CLI version output drift")
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        command = [sys.executable, "-c", "import sys; from grant_agent.neyvia_agent_cli import main; code=main(['--version']); assert 'grant_agent.neyvia_agent' not in sys.modules; raise SystemExit(code)"]
        child_env = dict(os.environ)
        child_env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(Path(__file__).resolve().parents[1]), child_env.get("PYTHONPATH", ""))))
        done = subprocess.run(command, env=child_env, capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
        require(done.returncode == 0 and done.stdout.strip() == agent_version(), "neyvia-core.agent-version", "lightweight readiness probe imported runtime or printed wrong version")

    def mobile_journey():
        from . import neyvia_mobile_studio as mobile
        from .neyvia_workspace_tools import WorkspaceTools
        import json, http.client, threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse
        base = root / "mobile"
        base.mkdir()
        def write(path, text):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for format in ("json", "ts"):
            project = base / format
            for folder in ("www", "dist", "screens"):
                write(project / folder / "index.html", folder)
            config = {"appId": "com.example.phone", "appName": "Phone", "webDir": "screens"}
            write(project / f"capacitor.config.{format}", json.dumps(config) if format == "json" else "export default {appId:'com.example.phone',appName:'Phone',webDir:'screens'};")
            info = mobile.project_info(project)
            require(info["kind"] == "capacitor" and info["name"] == "Phone" and info["androidPackage"] == info["iosBundleId"] == "com.example.phone" and Path(info["webRoot"]) == project / "screens",
                    "neyvia-core.mobile-project", "Capacitor config failed to select explicit screens/IDs")
        project = base / "priority"
        write(project / "dist/index.html", "dist")
        require(Path(mobile.project_info(project)["webRoot"]) == project / "dist", "neyvia-core.mobile-project", "dist export not discovered")
        write(project / "www/index.html", "www")
        write(project / "package.json", '{"dependencies":{"expo":"~53"}}')
        write(project / "app.json", '{"expo":{"name":"Expo Phone","ios":{"bundleIdentifier":"com.example.ios"},"android":{"package":"com.example.android"}}}')
        info = mobile.project_info(project)
        require(Path(info["webRoot"]) == project / "www" and info["kind"] == "expo" and info["name"] == "Expo Phone" and info["iosBundleId"] == "com.example.ios" and info["androidPackage"] == "com.example.android",
                "neyvia-core.mobile-project", "Expo metadata or www priority lost")
        source = '@media screen and (prefers-color-scheme: dark){padding:env(safe-area-inset-top, 4px)}<meta media="(prefers-color-scheme: light)">'
        for dark in (True, False):
            value = mobile._scheme(source, dark)
            require(f'screen and {mobile._TRUE_MEDIA if dark else mobile._FALSE_MEDIA}' in value and f'media="{mobile._FALSE_MEDIA if dark else mobile._TRUE_MEDIA}"' in value and 'var(--nx-safe-area-inset-top, 4px)' in value,
                    "neyvia-core.mobile-injection", "compound media or safe-area fallback lost")
        for source in ("<HTML><HEAD></HEAD><body>app</body></HTML>", "<html><body>app</body></html>", "<main>app</main>"):
            value = mobile._inject(source, {"safe": {"top": 62}, "dark": True, "base": "/preview/", "storage": {"saved": "</script><script>evil</script>"}})
            require(value.index("window.__NX_MOBILE__") < value.index("app") and "</script><script>evil" not in value and "\\u003c/script>" in value,
                    "neyvia-core.mobile-injection", "preview injection moved after app or escaped script")
        value = mobile._inject('<html><head><script src="/assets/app.js"></script><link href="//cdn.example/style.css"></head></html>', {"safe": {}, "dark": False, "base": "/api/ui/mobile-preview/token/"})
        require('src="/api/ui/mobile-preview/token/assets/app.js"' in value and 'href="//cdn.example/style.css"' in value,
                "neyvia-core.mobile-injection", "root export URL escaped capability or protocol-relative URL changed")
        service = WorkspaceTools(base)
        project = base / "preview-app"
        write(project / "www/index.html", "<html><head></head><body>Local mobile app</body></html>")
        write(project / "secret.txt", "scratch private outside web export")
        token = mobile.preview_token(service, project)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): mobile.serve_preview(base, self, urlparse(self.path), "GET")
            def do_POST(self): mobile.serve_preview(base, self, urlparse(self.path), "POST")
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", proof_port(48498)), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(relative, body=None, length=None):
            connection = http.client.HTTPConnection("127.0.0.1", proof_port(48498), timeout=5)
            headers = {"Content-Length": str(len(body or b"")) if length is None else length}
            connection.request("POST" if body is not None else "GET", mobile.PREVIEW_PREFIX + token + "/" + relative, body=body, headers=headers)
            response = connection.getresponse()
            value = response.status, dict(response.getheaders()), response.read()
            connection.close()
            return value
        try:
            for path in ("../secret.txt", "%2e%2e/secret.txt", "%2e%2e%5csecret.txt", "../../bad"):
                require(request(path)[0] == 403, "neyvia-core.mobile-confinement", "HTTP preview traversal accepted")
            code, headers, page = request("settings/profile")
            require(code == 200 and b"window.__NX_MOBILE__" in page and "sandbox" in headers["Content-Security-Policy"] and "allow-same-origin" not in headers["Content-Security-Policy"] and request("missing.js")[0] == 404,
                    "neyvia-core.mobile-confinement", "SPA fallback, missing asset or sandbox policy changed")
            for body, length, status in [(b"{", None, 400), (b"[]", None, 400), (b'{"a":1}', None, 400), (b"", "-1", 400), (b"", "bad", 400), (b"", "2000001", 413)]:
                require(request("__nx/storage", body, length)[0] == status and not (project / mobile.STORAGE).exists(),
                        "neyvia-core.mobile-storage", "invalid storage request wrote data or changed rejection")
            require(request("__nx/storage", b'{"saved":"hello"}')[0] == 200 and json.loads(request("__nx/storage")[2]) == {"saved": "hello"},
                    "neyvia-core.mobile-storage", "actual HTTP storage string map not durable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            service.close()

    run("prompt-preparation", ["neyvia-core.prompt-selection", "neyvia-core.prompt-preservation", "neyvia-core.domain-policy", "neyvia-core.image-spec"], preparation)
    run("application-lifecycle", ["neyvia-core.application-projection", "neyvia-core.hosted-entrypoint", "neyvia-core.sdk-durable"], application_lifecycle)
    run("bundled-lifecycle", ["neyvia-core.bundled-catalog", "neyvia-core.bundled-durable"], bundled_lifecycle)
    run("browser-authority", ["neyvia-core.browser-pending", "neyvia-core.browser-authority", "neyvia-core.browser-url", "neyvia-core.browser-ports"], browser_journey)
    run("account-devices-sessions", ["neyvia-core.account-devices", "neyvia-core.account-session-binding"], account_journey)
    run("rpc-protocol-authority", ["neyvia-core.rpc-authority", "neyvia-core.rpc-protocol", "neyvia-core.rpc-plan"], rpc_journey)
    run("rpc-signed-device-receipt", ["neyvia-core.rpc-authority", "neyvia-core.rpc-device-binding"], rpc_signed_journey)
    run("mcp-durable-journey", ["neyvia-core.mcp-protocol", "neyvia-core.mcp-task-durable", "neyvia-core.mcp-sync-budget", "neyvia-core.mcp-autonomy", "neyvia-core.mcp-conversation"], mcp_journey)
    run("conversation-lifecycle", ["neyvia-core.conversation-turns", "neyvia-core.conversation-activity", "neyvia-core.conversation-pages", "neyvia-core.conversation-question", "neyvia-core.conversation-deletion", "neyvia-core.conversation-receipts", "neyvia-core.conversation-import"], conversation_journey)
    run("agent-entry", ["neyvia-core.agent-config", "neyvia-core.agent-version"], agent_entry_journey)
    run("mobile-http-preview", ["neyvia-core.mobile-project", "neyvia-core.mobile-injection", "neyvia-core.mobile-confinement", "neyvia-core.mobile-storage"], mobile_journey)
    return {"ok": all(row["ok"] for row in cases), "cases": cases,
            "contracts": sorted({identity for row in cases if row["ok"] for identity in row["contracts"]}),
            "durationMs": round((time.perf_counter() - started) * 1000, 3), "scratchRoot": str(root)}
