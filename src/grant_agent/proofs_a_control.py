"""Executable operator-control contracts, shared by real actions and startup.

These observers validate decisions and durable transactions at their owning
boundaries. The startup procedures operate only on the supplied scratch root.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import json
from pathlib import Path

CONTRACTS = (
    'control.approval-policy',
    'control.approval-description',
    'control.questions-durable',
    'control.questions-session',
    'control.questions-immutable',
    'control.prompts-composition',
    'control.prompts-durable',
    'control.context-budget',
    'control.context-compaction',
    'control.image-magic',
    'control.attachments-content',
    'control.attachments-message',
    'control.import-upload',
    'control.import-preview',
    'control.import-selection',
    'control.import-read',
    'control.import-packet',
    'control.context-bundle',
    'control.context-cache',
    'control.context-cache-wire',
    'control.context-metrics',
    'control.tools-deferred-schema',
    'control.vision-wire',
    'control.vision-pixels',
    'control.submission-verdict',
    'control.submission-source-phase',
    'control.submission-lineage',
    'control.submission-counts',
    'control.submission-git-delta',
    'control.submission-secrets',
    'control.stream-order',
    'control.stream-frame',
    'control.stream-tail',
    'control.stream-relay',
    'control.result-retention',
    'control.result-compaction',
    'control.bridge-authority',
    'control.bridge-receipt',
    'control.bridge-grants',
    'control.bridge-snapshot',
    'control.bridge-feedback',
    'control.execution-scope',
    'control.execution-proposal',
    'control.execution-result',
    'control.execution-cleanup',
    'control.execution-phase',
    'control.chrome-policy',
    'control.chrome-grant',
    'control.console-observation',
    'control.console-memory',
    'control.chrome-live-action',
    'control.neyvia-live-action',
    'control.browser-preflight',
    'control.browser-repair',
    'control.plan-transitions',
    'control.plan-limits',
    'control.plan-dashboard',
    'control.plan-history',
    'control.agents-manual',
    'control.cu-receipt',
    'control.cu-verdict',
    'control.cu-aliases',
    'control.cu-recovery',
)


def require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_stream_emission(sources, event):
    first = sources.popleft()
    require(event.get("kind") == first.get("kind") and event.get("data") == first.get("data"),
            "control.stream-order", "delivery changed event kind or item metadata")
    expected = first.get("message")
    if isinstance(expected, str):
        while expected != event.get("message") and sources:
            following = sources[0]
            require(following.get("kind") == first.get("kind") and following.get("data") == first.get("data")
                    and isinstance(following.get("message"), str), "control.stream-order", "delivery merged distinct events")
            expected += sources.popleft()["message"]
        require(expected == event.get("message"), "control.stream-order", "delivery lost or reordered text")
    else:
        require(event == first, "control.stream-order", "delivery changed a non-text event")
    if "at" in first:
        require(event.get("at") == first["at"], "control.stream-order", "delivery changed first arrival time")


def check_stream_frames(source, rows):
    require("".join(row["message"] for row in rows) == str(source.get("message") or "")
            and all(len(row["message"]) <= 4000 and isinstance(row["at"], (float, int)) for row in rows),
            "control.stream-frame", "bounded framing changed content or timestamp")
    stamp = source.get("at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        require(all(row["at"] == round(stamp, 3) for row in rows), "control.stream-frame", "supplied arrival time changed")


def check_recorded_result(source, saved):
    require(isinstance(saved, dict) and saved.get("reply") == source.get("reply")
            and saved.get("status") == source.get("status"), "control.result-retention", "durable result changed reply or status")
    compartment = saved.get("compartment")
    if isinstance(compartment, dict):
        require(not {"messages", "turnReceipts"} & compartment.keys(), "control.result-retention", "result retained duplicate session window")
        original = source.get("compartment") or {}
        persistence = source.get("conversationPersistence") or {}
        if {"messages", "turnReceipts"} & original.keys() and persistence.get("turnId"):
            require(compartment.get("windowRef") == {key: persistence.get(key) for key in ("conversationId", "turnId")},
                    "control.result-retention", "removed session window lost durable reference")
    usage = (source.get("turnReceipt") or {}).get("usage")
    if isinstance(usage, dict):
        require(saved.get("usage", (saved.get("turnReceipt") or {}).get("usage")) == usage,
                "control.result-retention", "bounded recording lost provider usage")


def check_bridge_decision(hosts, request, decision):
    require(all(getattr(decision, key) == getattr(request, key) for key in
                ("action_id", "action_type", "direction", "source_host", "target_host"))
            and decision.status in {"approved", "denied", "pending_approval"} and bool(decision.reason)
            and decision.approval_required is (decision.status == "pending_approval"),
            "control.bridge-authority", "decision changed identity or approval state")
    if decision.status != "approved":
        return
    lookup = {host.host_id: host for host in hosts}
    require(request.source_host in lookup and request.target_host in lookup
            and (request.direction != "nas_to_local" or (request.source_host, request.target_host) == ("nas", "local"))
            and (request.direction != "local_to_nas" or (request.source_host, request.target_host) == ("local", "nas")),
            "control.bridge-authority", "approved disconnected or reversed lane")
    host = lookup[request.target_host]
    if request.action_type in {"read_file", "write_file", "sync_file", "record_artifact", "record_receipt"}:
        path = Path(request.path or request.destination_path or request.artifact_path).expanduser().resolve()
        matches = []
        for scope in host.file_roots:
            try:
                path.relative_to(Path(scope.path).expanduser().resolve())
            except ValueError:
                continue
            if request.action_type == "read_file" or scope.access in {"write", "read_write", "sync"}:
                matches.append(scope)
        require(any(scope.permission_state.strip().lower() == "approved" for scope in matches),
                "control.bridge-authority", "approved file outside granted readable/writable roots")
    elif request.action_type in {"run_command", "use_github_auth"} and request.command:
        command = request.command.strip().split()[0]
        capability = next((cap for cap in host.command_capabilities if cap.command == command), None)
        require(capability is not None and capability.available
                and not any(token in request.command for token in (";", "&&", "||", "|", "`", "$(", ")", "\n", "\r", ">", "<"))
                and (not capability.allowed_prefixes or any(request.command.startswith(p) for p in capability.allowed_prefixes)),
                "control.bridge-authority", "approved unavailable command or shell operator/prefix escape")
    elif request.action_type in {"inspect_browser", "inspect_app_window", "inspect_window"}:
        surface = next((s for s in host.app_surfaces if s.surface_id == request.surface_id), None)
        require(surface is not None and surface.available and surface.permission_state.strip().lower() == "approved"
                and any(g.capability == "surface.inspect" and g.state.strip().lower() == "approved" for g in host.permissions),
                "control.bridge-authority", "approved surface missing explicit inspection authority")


def check_bridge_receipt(decisions, receipt, execute):
    statuses = [d.status for d in decisions]
    expected = "denied" if "denied" in statuses else "pending_approval" if "pending_approval" in statuses else "approved" if statuses else "empty"
    require(receipt["status"] == expected and len(receipt["steps"]) == len(decisions)
            and [r["actionId"] for r in receipt["pendingApprovals"]] == [d.action_id for d in decisions if d.status == "pending_approval"]
            and [r["actionId"] for r in receipt["denials"]] == [d.action_id for d in decisions if d.status == "denied"],
            "control.bridge-receipt", "operation hid a denied/pending step or changed aggregate verdict")
    for d, step in zip(decisions, receipt["steps"]):
        require(step["performedByHost"] == d.performed_by_host and step["syncStatus"] == d.sync_status
                and step["auditEventId"] == d.audit_event_id and (execute or step["resultStatus"] == "not_executed"),
                "control.bridge-receipt", "plan changed host/audit/sync identity or claimed execution")
    for host, status in receipt["hostStatus"].items():
        current = [d.status for d in decisions if d.performed_by_host == host]
        require(status == ("denied" if "denied" in current else "pending_approval" if "pending_approval" in current else "approved"),
                "control.bridge-receipt", "host verdict hid its worst decision")


def check_bridge_feedback(receipt, event, handoff, route, task, feedback, idea):
    require(receipt["eventId"] == event and receipt["plannerExecutorHandoffId"] == handoff
            and receipt["eventName"] == "agent:structured-feedback" and receipt["status"] == "received" and receipt["timestamp"]
            and receipt["nextIdea"] == str(idea or "").strip(), "control.bridge-feedback", "feedback lost identity, handoff or followup")
    for key, value in (("routeContext", route), ("taskContext", task), ("verifierFeedback", feedback)):
        if isinstance(value, dict):
            require(receipt[key] == value, "control.bridge-feedback", "feedback changed supplied context")


def check_execution_scope(scope):
    from .action_executor import derive_execution_target
    expected = derive_execution_target(execution_root=scope.execution_root, workspace_root=scope.workspace_root, strategy=scope.strategy)
    require(all(getattr(scope, key) == expected[key] for key in ("execution_target", "storage_mode", "host_locality")),
            "control.execution-scope", "execution scope misstated its target/storage/host")
    if scope.strategy in {"git_worktree", "filesystem_copy"}:
        require(scope.isolated and Path(scope.execution_root).exists()
                and Path(scope.execution_root).resolve() != Path(scope.workspace_root).resolve(),
                "control.execution-scope", "isolated scope reuses primary workspace or missing directory")
    elif scope.strategy == "direct":
        require(not scope.isolated and Path(scope.execution_root).resolve() == Path(scope.workspace_root).resolve(),
                "control.execution-scope", "direct scope falsely claims isolation")


def check_action_proposal(step, proposal, scope):
    from .action_executor import VERIFY_HINTS
    if any(word in (step.title + " " + step.description).lower() for word in VERIFY_HINTS):
        require(proposal.kind == "test_run", "control.execution-proposal", "verification step bypassed real verification surface")
    require(proposal.target_scope == ("worktree" if scope.isolated else "workspace")
            and proposal.worktree_path == scope.worktree_path and proposal.branch_name == scope.branch_name,
            "control.execution-proposal", "proposal changed isolation scope or branch identity")


def check_action_result(proposal, record, override, autonomy, lease):
    require(not (proposal.requires_approval and not override and record.result.ok),
            "control.execution-result", "action completed without required authority")
    if autonomy is not None and autonomy.get("allowed"):
        require(record.gate.approved_by == "autonomy:" + lease and record.result.payload.get("autonomyLeaseId") == lease,
                "control.execution-result", "lease-authorized result lost exact lease attribution")
    if record.result.exit_code == 124 and record.result.error:
        require(not record.result.ok and "timed out" in record.result.error.lower() and "timed out" in record.result.stderr.lower(),
                "control.execution-result", "timeout lost failed record or explanatory stderr")


def check_chrome_assessment(action, label, url, text, result):
    import re
    from . import connected_chrome_policy as p
    haystack = label.lower() or (text.lower()[:2000] if action.get("kind") in {"type", "key"} else "")
    routine = action.get("kind") == "navigate" or action.get("kind") == "key" and str(action.get("key") or "").lower() != "enter"
    destructive = not routine and any(re.search(pattern, haystack) for pattern, _ in p._DESTRUCTIVE_PATTERNS)
    consequential = not routine and (any(re.search(pattern, haystack) for pattern, _ in p._CONSEQUENTIAL_PATTERNS)
                                    or action.get("kind") == "click" and not label.strip())
    expected = p.RISK_DESTRUCTIVE if destructive else p.RISK_CONSEQUENTIAL if consequential else p.RISK_ROUTINE
    require(result.risk == expected and result.requires_approval is (expected != p.RISK_ROUTINE)
            and result.fingerprint == p.action_fingerprint(action, label=label, url=url),
            "control.chrome-policy", "page-evidence risk or exact action fingerprint changed")


def check_console_authentication(text, result):
    from . import thunder_compute as t
    value = text.lower()
    signed_out = sum(marker in value for marker in t._SIGNED_OUT_MARKERS)
    signed_in = sum(marker in value for marker in t._SIGNED_IN_MARKERS)
    expected = (True if signed_in > signed_out else None, "low") if signed_in and signed_out else (True, "high") if signed_in else (False, "high") if signed_out else (None, "none")
    require(result[:2] == expected and bool(result[2]), "control.console-observation", "read console guessed unsupported authentication state")


def check_plan_transition(before, op, after, at, seq):
    if not isinstance(op, dict):
        require(before == after, "control.plan-transitions", "non-operation changed checklist")
        return
    kind = op.get("op")
    old = (before or {}).get("items", [])
    if kind == "replace":
        expected = [dict(row) for row in op.get("items") or [] if isinstance(row, dict)]
    elif kind == "add":
        basis = old if (before or {}).get("source") == op.get("source") else []
        added = dict(op.get("item") or {})
        added["id"] = added.get("id") or str(max([int(row["id"]) for row in basis if str(row.get("id") or "").isdigit()] or [0]) + 1)
        expected = [row for row in basis if row.get("id") != added["id"]] + [added]
    elif kind == "update":
        if not any(row.get("id") == op.get("id") for row in old):
            require(before == after, "control.plan-transitions", "unknown task update changed existing checklist")
            return
        expected = []
        for row in old:
            if row.get("id") != op.get("id"):
                expected.append(row)
            elif op.get("status") != "deleted":
                expected.append({**row, **{key: op[key] for key in ("status", "text", "active") if op.get(key)}})
    else:
        require(before == after, "control.plan-transitions", "unrecognized operation changed checklist")
        return
    require((after is None and not expected) or after is not None and after["items"] == expected[:100],
            "control.plan-transitions", "checklist operation changed task IDs/order/text/status or failed to clear")
    if after is not None:
        require(after["updatedAt"] == (at or (before or {}).get("updatedAt"))
                and after["throughSeq"] == (seq if seq is not None else (before or {}).get("throughSeq")),
                "control.plan-transitions", "checklist lost operation timestamp/sequence")


def check_itemstore_plan(store, historical, result):
    from .connected_sessions.plan import latest_plan
    require(store._plan_history[0] == store.tail_start and not any(item.id in store.by_id for item in historical)
            and len({item.id for item in historical}) == len(historical),
            "control.plan-history", "history cache belongs to another tail or replays materialized task calls")
    require(result == latest_plan(historical + store.items), "control.plan-history", "checklist changed accepted transcript operation fold")


def check_approval(action, session, approval, decision):
    from . import approval_modes as a
    declared = str(action.get("category") or "").strip().lower()
    category = declared if declared in a.ROUTINE or declared in a.ALWAYS_ASK else "unknown"
    server = str(action.get("mcpServer") or "").strip().lower()
    if server and server not in session.trusted_servers:
        category = "new_mcp_server"
    fingerprint = a.action_fingerprint(action)
    grant = (approval is not None and approval.get("fingerprint") == fingerprint) or fingerprint in session.granted
    consequential = category in a.ALWAYS_ASK
    allowed = bool(grant or not consequential and (session.mode == a.MODE_ALL or session.mode == a.MODE_SAFE and category in a.ROUTINE))
    require(decision.allowed is allowed and decision.category == category and decision.always_ask is consequential
            and decision.mode == session.mode and decision.fingerprint == fingerprint and bool(decision.reason),
            "control.approval-policy", "decision does not match session authority, classification and bound grant")


def check_modes(result):
    from . import approval_modes as a
    require({r["category"] for r in result["alwaysAsk"]} == set(a.ALWAYS_ASK)
            and {r["id"] for r in result["modes"]} == set(a.MODES)
            and all(r["sessionOnly"] is (r["id"] == a.MODE_ALL) for r in result["modes"]),
            "control.approval-description", "settings omitted protected categories or session-only scope")


def check_questions(path, before, after, result, operation):
    require(json.loads(Path(path).read_text(encoding="utf-8")) == after,
            "control.questions-durable", "returned transaction is not durable")
    require(result in after, "control.questions-durable", "returned question is absent")
    pending = [r["sessionId"] for r in after if r.get("status") == "pending"]
    require(len(pending) == len(set(pending)), "control.questions-session", "multiple pending questions in one session")
    prior = next((r for r in before if r["questionId"] == result["questionId"]), None)
    if operation == "request":
        require(prior is None and after == before + [result] and result["status"] == "pending",
                "control.questions-session", "request changed another session or reused identity")
    else:
        require(prior is not None and after == [result if r["questionId"] == result["questionId"] else r for r in before]
                and result["status"] == "answered" and bool(result["answer"])
                and all(result.get(k) == v for k, v in prior.items() if k not in {"status", "answer", "answeredAt"}),
                "control.questions-immutable", "answer changed question identity or unrelated entries")


def check_question_list(rows, session, pending_only, result):
    expected = [r for r in rows if (session is None or r.get("sessionId") == session)
                and (not pending_only or r.get("status") == "pending")]
    require(result == expected, "control.questions-session", "observer crossed session or pending filter")


def check_prompt_library(raw, result):
    from . import agent_prompt_library as p
    require(set(result["roles"]) == set(p.ROLES) == set(result["hashes"]),
            "control.prompts-composition", "role or hash catalog incomplete")
    common = raw.get("common", {}).get("instructions", p.DEFAULT_COMMON)
    for role in p.ROLES:
        text = raw.get("roles", {}).get(role, {}).get("instructions", p.DEFAULT_ROLES[role])
        c, r = common != p.DEFAULT_COMMON, text != p.DEFAULT_ROLES[role]
        expected = common + "\n\n" + text if c and r or not c and not r else text if r else common
        require(result["roles"][role]["instructions"] == text
                and result["hashes"][role] == hashlib.sha256(expected.encode()).hexdigest(),
                "control.prompts-composition", "authored text or composed hash changed")


def check_prompt_write(path, payload, result):
    require(json.loads(Path(path).read_text(encoding="utf-8")) == payload
            and result["revision"] == payload["revision"],
            "control.prompts-durable", "saved payload/revision differs from returned library")


def check_compiled_prompt(raw, role, scope_id, result):
    from . import agent_prompt_library as p
    if scope_id != "global":
        expected = raw["scopes"][scope_id]["roles"][role]["instructions"]
    else:
        common = raw.get("common", {}).get("instructions", p.DEFAULT_COMMON)
        authored = raw.get("roles", {}).get(role, {}).get("instructions", p.DEFAULT_ROLES[role])
        c, r = common != p.DEFAULT_COMMON, authored != p.DEFAULT_ROLES[role]
        expected = common + "\n\n" + authored if c and r or not c and not r else authored if r else common
    require(result == expected, "control.prompts-composition", "compiled prompt changed authored text")


def check_context_packet(result, root, max_items, max_chars):
    from .context_import import read_import_selection
    selected = result["selected"]
    require(len(selected) <= max_items and sum(len(r["content"]) for r in selected) <= max_chars
            and result["sourceIds"] == [r["sourceId"] for r in selected]
            and all(r["contentHash"] == hashlib.sha256(r["content"].encode()).hexdigest() for r in selected),
            "control.import-packet", "packet exceeds bounds or changes content identity")
    for row in selected:
        if root is None or not row.get("importId"):
            continue
        imported = read_import_selection(root, row["importId"])
        item = next((r for r in imported["items"] if r["sourceItemId"] == row["sourceId"]), None)
        require(item is not None and item["content"].startswith(row["content"])
                and row["sourceSha256"] == imported["sourceSha256"],
                "control.import-packet", "packet widened durable import scope or source hash")
    ids = sorted({r["importId"] for r in selected if r.get("importId")})
    hashes = sorted({r["sourceSha256"] for r in selected if r.get("sourceSha256")})
    require(result["importIds"] == ids and result["sourceSha256s"] == hashes
            and result["sourceSha256"] == (hashes[0] if len(hashes) == 1 else None),
            "control.import-packet", "packet lineage projection differs")


def check_context_status(manager, status):
    ratio = manager.used_tokens / manager.max_tokens if manager.max_tokens > 0 else 1.0
    expected = next((name for threshold, name in ((manager.hard_stop_threshold, "hard_stop"),
                    (manager.rollover_threshold, "rollover"), (manager.warn_threshold, "warn")) if ratio >= threshold), "ok")
    require(status == expected and manager.used_tokens == sum(e.tokens for e in manager.events),
            "control.context-budget", "context status or accumulated tokens disagree")


def check_context_compaction(events, result):
    users = [{"role": e.role, "content": e.content} for e in events if e.role == "user"]
    other = [e for e in events if e.role != "user"]
    require(result[:len(users)] == users and len(result) == len(users) + bool(other)
            and (not other or result[-1]["role"] == "system" and "[compacted_context]" in result[-1]["content"]),
            "control.context-compaction", "compaction lost exact user content or assistant activity marker")


def check_image_magic(data, result):
    signatures = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"))
    expected = next((suffix for magic, suffix in signatures if data.startswith(magic)),
                    ".webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else "")
    require(result == expected, "control.image-magic", "extension must derive from file bytes")


def check_attachments(folder, decoded, paths):
    require(len(paths) == len(decoded), "control.attachments-content", "attachment count changed")
    for (name, data), path in zip(decoded, paths):
        require(path.parent == folder and path.name == hashlib.sha256(data).hexdigest()[:16] + "-" + name
                and path.read_bytes() == data, "control.attachments-content", "attachment escaped its folder or differs from its content identity")


def check_attachment_message(message, paths, result):
    text = (message or "").rstrip()
    lead = text or f"Look at the attached file{'s' if len(paths) > 1 else ''}."
    require(result == (lead + "\n\n" + "\n".join(f"Attached file: {p}" for p in paths) if paths else message),
            "control.attachments-message", "message changed or omitted an attachment path")


def check_upload(target, receipt):
    data = (Path(target) / "content").read_bytes()
    require(receipt["uploadId"].startswith("upload-") and Path(receipt["displayName"]).name == receipt["displayName"]
            and receipt["sha256"] == hashlib.sha256(data).hexdigest() and receipt["sizeBytes"] == len(data)
            and json.loads((Path(target) / "receipt.json").read_text(encoding="utf-8")) == receipt,
            "control.import-upload", "upload identity, byte count, content hash or durable receipt differs")


def check_import(preview, selected, receipt, loaded):
    expected = {r["itemId"]: r for r in preview["items"] if r["itemId"] in selected}
    require({r["sourceItemId"] for r in loaded["items"]} == selected
            and loaded["importId"] == receipt["importId"] and loaded["sourceSha256"] == preview["source"]["sha256"]
            and receipt["sourceSha256"] == preview["source"]["sha256"]
            and all(r["content"] == expected[r["sourceItemId"]]["content"] and r["role"] == expected[r["sourceItemId"]]["role"]
                    for r in loaded["items"]), "control.import-selection", "durable rows widened or changed reviewed selection")
    require(receipt["lineage"] == {"sourceProvider": preview["provider"], "sourceSha256": preview["source"]["sha256"],
            "selectionExplicit": True, **({"uploadId": preview["source"]["uploadId"]} if preview["source"].get("uploadId") else {})},
            "control.import-selection", "lineage differs from explicit source")


def check_import_read(receipt, result):
    expected = set(receipt["scope"]["selectedItemIds"])
    require(len(result["items"]) == len(expected) and {r["sourceItemId"] for r in result["items"]} == expected
            and all(r["importId"] == result["importId"] and r["sourceSha256"] == result["sourceSha256"] for r in result["items"]),
            "control.import-read", "read accepted duplicate, foreign or unreceipted rows")


def check_import_preview(path, result):
    from . import context_import as c
    require(result["requiresExplicitSelection"] is True and result["counts"]["available"] == len(result["items"])
            and result["counts"]["credentialRedactions"] == sum(r["credentialRedactions"] for r in result["items"])
            and all(not any(p.search(r["content"]) for p in c._SECRET_PATTERNS) for r in result["items"]),
            "control.import-preview", "preview count, explicit selection or credential redaction differs")
    name = result["source"].get("displayName", Path(path).name)
    if result["provider"] == "codex" and Path(name).suffix.lower() in {".jsonl", ".ndjson"}:
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(isinstance(r, dict) and r.get("type") == "response_item" for r in rows):
            messages = [r for r in rows if isinstance(r, dict) and r.get("type") == "response_item"
                        and isinstance(r.get("payload"), dict) and r["payload"].get("type") == "message"
                        and r["payload"].get("role") in {"user", "assistant"}]
            expected = [(r["payload"].get("id"), r["payload"]["role"], r.get("timestamp", ""))
                        for r in messages if c._content(r["payload"].get("content")).strip()][:c.MAX_ITEMS]
            require(len(expected) == len(result["items"])
                    and all((not identity or item["itemId"] == identity) and item["role"] == role and item["createdAt"] == stamp
                            for (identity, role, stamp), item in zip(expected, result["items"])),
                    "control.import-preview", "rollout leaked non-message/developer rows or changed identity/order/timestamp")


def check_bundle(bundle):
    require(bundle["schema"] == "neyvia.context_bundle.v1" and bool(bundle["cache_key"])
            and bool(bundle["stable_prefix_cache_key"]) and isinstance(bundle["items"], list),
            "control.context-bundle", "durable model bundle lost cache identity or items")


def check_cache(key, provider, result):
    key = str(key or "").strip()
    provider = str(provider or "").strip().lower()
    supported = bool(key and (provider in {"anthropic", "claude", "openai", "openai-codex", "codex"}
                             or provider.startswith("anthropic") or provider.startswith("openai")))
    require(result["stable_prefix_cache_key"] == key and result["supported"] is supported,
            "control.context-cache", "cache identity or provider support fabricated")
    if key:
        ephemeral = provider in {"anthropic", "claude"} or provider.startswith("anthropic")
        require(result["cache_control"]["type"] == "ephemeral" if ephemeral else result["cache_control"]["cache_key"] == key,
                "control.context-cache", "cache hint changed stable prefix")
    if key and (provider in {"openai", "openai-codex", "codex"} or provider.startswith("openai")):
        require(result["provider_fields"]["prompt_cache_key"] == key,
                "control.context-cache", "OpenAI prompt cache key missing")


def check_cache_wire(payload, cache):
    require(payload.get("cache_control") == cache
            and all(payload.get(k) == cache[k] for k in ("cache_key", "stable_prefix_cache_key") if cache.get(k))
            and (not cache.get("provider_fields", {}).get("prompt_cache_key")
                 or payload.get("prompt_cache_key") == cache["provider_fields"]["prompt_cache_key"]),
            "control.context-cache-wire", "provider wire omitted attached cache identity")


def check_metrics(path, metrics):
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    require(all(result.get(field) == getattr(metrics, field) for field in
            ("mission_id", "session_id", "model_invocations_per_task", "sequential_tool_round_trips", "uncached_input_tokens",
             "cached_input_tokens", "tool_output_tokens_injected", "images_sent_to_main_model")),
            "control.context-metrics", "durable metrics omitted or changed recorded counters")


def check_tool_discovery(specs, result, include_schemas):
    require({r["name"] for r in result} == set(specs)
            and all(("inputSchema" in r) is include_schemas for r in result),
            "control.tools-deferred-schema", "catalog omitted a tool or exposed schemas without request")


def check_tool_description(spec, result):
    require(result["inputSchema"] == dict(spec.input_schema or {}) and result["name"] == spec.name,
            "control.tools-deferred-schema", "described schema or tool identity changed")


def check_vision_input(source, result):
    images = [part for item in source if isinstance(item, dict) and item.get("type") == "function_call_output"
              and isinstance(item.get("output"), list) for part in item["output"]
              if isinstance(part, dict) and part.get("type") == "input_image"]
    if images:
        last = result[-1]
        require(last.get("role") == "user" and [p for p in last["content"] if p.get("type") == "input_image"] == images[-2:]
                and all(not any(isinstance(p, dict) and p.get("type") == "input_image" for p in item["output"])
                        for item in result if isinstance(item, dict) and item.get("type") == "function_call_output" and isinstance(item.get("output"), list)),
                "control.vision-wire", "tool pixels not moved intact to the two latest user-content images")


def check_image_output(candidate, output):
    import base64
    from .image_budget import shrunk_image
    require(base64.b64decode(output.image_url.split(",", 1)[1]) == shrunk_image(Path(candidate).read_bytes())[1],
            "control.vision-pixels", "image tool returned a path or changed encoded image bytes")


def check_submission(receipt, result):
    from .agent_submission_gate import _contains_secret_like
    require(result.ok is (not bool(result.errors)), "control.submission-verdict", "receipt verdict contradicts validation errors")
    if _contains_secret_like(receipt):
        require(result.errors == ("receipt contains secret-like key or value",),
                "control.submission-secrets", "secret-like receipt material echoed or accepted")


def _refusal(action, word=None):
    try:
        action()
    except ValueError as exc:
        require(word is None or word in str(exc), "control.self-check", "wrong refusal")
        return
    raise ValueError("Contract control.self-check: action unexpectedly accepted")


def self_check(root):
    # Focused browser contracts execute their complete real procedures. The
    # full adapter still runs every original check, including manual grounding.
    import os
    requested = set(json.loads(os.environ.get("NEYVIA_GATE_CONTRACTS", "[]")))
    browser_contracts = {"control.chrome-live-action", "control.neyvia-live-action"}
    if requested and requested <= browser_contracts:
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        receipts = _chrome_procedure(root)
        if "control.neyvia-live-action" in requested:
            receipts.extend(_neyvia_browser_procedure(root))
        receipts.extend(_cu_procedure(root))
        return {"ok": True, "contracts": sorted(requested), "self_check": receipts,
                "authority": "owned local CDP browser and absent CU fixture; no desktop or provider"}
    from . import approval_modes as a, agent_questions as q, agent_prompt_library as p
    from .context_manager import ContextWindowManager
    root = Path(root)
    receipts = []
    # Operator approval journey: all modes, first-server trust and action grants.
    for mode in a.MODES:
        session = a.SessionApprovals(mode)
        for category in (*a.ALWAYS_ASK, *a.ROUTINE, "unknown"):
            a.evaluate({"category": category}, session)
    current = a.SessionApprovals(a.MODE_ALL)
    action = {"category": "read", "mcpServer": "Local-fixture"}
    require(not a.evaluate(action, current).allowed, "control.self-check", "new server bypassed consent")
    current.trust_server("Local-fixture")
    require(a.evaluate(action, current).allowed, "control.self-check", "trusted routine call rejected")
    spend = {"category": "spend", "instance": "scratch"}
    current.grant(a.evaluate(spend, current), granted_by="scratch-operator")
    require(a.evaluate(spend, current).allowed and not a.evaluate({**spend, "category": "destroy"}, current).allowed,
            "control.self-check", "grant crossed action fingerprint")
    try:
        a.require({"category": "destroy"}, a.SessionApprovals(a.MODE_ALL))
    except a.ApprovalRequired as exc:
        require(exc.decision.always_ask, "control.self-check", "refusal lost decision")
    else:
        raise ValueError("Destruction admitted without approval")
    _refusal(lambda: current.set_mode("invalid"))
    require(a.SessionApprovals().mode == a.MODE_SAFE and not a.SessionApprovals().trusted_servers,
            "control.self-check", "authority survived fresh session")
    a.describe_modes()
    receipts.append({"procedure": "approval-authority", "ok": True})
    # A question can be retried, answered once and reopened with exact answer.
    first = q.request_question(root, "s1", "Choose scope", ["A", "B"], "needed")
    second = q.request_question(root, "s2", "Choose scope")
    require(first["questionId"] != second["questionId"]
            and q.request_question(root, "s1", "Choose scope", ["A", "B"], "needed") == first,
            "control.self-check", "request identity not stable and scoped")
    q.list_questions(root, "s1")
    _refusal(lambda: q.request_question(root, "s1", "Different"), "already has a pending")
    answer = q.answer_question(root, first["questionId"], "A")
    require(q.answer_question(root, first["questionId"], "A") == answer and q.answer_pending_question(root, "s1", "A") is None,
            "control.self-check", "answer retry changed history")
    _refusal(lambda: q.answer_question(root, first["questionId"], "B"), "already answered")
    for options in (["A", "A"], ["A", "B", "C", "D"]):
        _refusal(lambda options=options: q.request_question(root, "s3", "Q", options))
    _refusal(lambda: q.request_question(root, "s3", ""))
    require(q.list_questions(root, "s1", pending_only=False) == [answer], "control.self-check", "reopened answer differs")
    receipts.append({"procedure": "questions-request-answer-reopen", "ok": True})
    library = p.load_prompt_library(root)
    require(library["revision"] == 0, "control.self-check", "fresh prompt store not revision zero")
    saved = p.save_prompt_library(root, {"expectedRevision": 0, "roles": {"reader": {"instructions": "Reader authored."}, "planner": {"instructions": "Planner authored."}}})
    require(saved["revision"] == 1 and p.load_prompt_library(root)["roles"]["reader"]["instructions"] == "Reader authored.",
            "control.self-check", "partial override not durable")
    _refusal(lambda: p.save_prompt_library(root, {"expectedRevision": 0, "common": {"instructions": "stale"}}), "revision conflict")
    reset = p.reset_prompt_library(root, "reader", 1)
    require(reset["roles"]["planner"]["instructions"] == "Planner authored." and reset["roles"]["reader"]["instructions"] == p.DEFAULT_ROLES["reader"],
            "control.self-check", "reset changed unrelated role")
    _refusal(lambda: p.save_prompt_library(root, {"expectedRevision": 2, "nope": {}}), "unknown prompt library fields")
    _refusal(lambda: p.save_prompt_library(root, {"expectedRevision": 2, "common": {"instructions": "sk-abcdefghijklmnopqrstuvwxyz123456"}}), "credential-like")
    p.save_prompt_library(root, {"expectedRevision": 2, "common": {"instructions": "Common."}, "roles": {"chat": {"instructions": "Chat."}}})
    require(p.compiled_role_prompt(root, "chat") == "Common.\n\nChat.", "control.self-check", "common/role composition differs")
    receipts.append({"procedure": "prompts-author-reset-compose", "ok": True})
    manager = ContextWindowManager(max_tokens=100)
    require(manager.record("user", "a" * 120) == "ok" and manager.record("assistant", "b" * 220) == "rollover",
            "control.self-check", "budget transitions changed")
    manager.compact_window()
    receipts.append({"procedure": "context-budget-and-compaction", "ok": True})
    # Mislabelled JPEG and PNG are detected from bytes through the real reporter.
    import importlib.util
    reporter = Path(__file__).resolve().parents[2] / "scripts/run_controlled_ai_safety_review.py"
    spec = importlib.util.spec_from_file_location("proofs_safety_reporter", reporter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for magic, expected in ((b"\xff\xd8\xff\xe0\x00\x10JFIF", ".jpg"), (b"\x89PNG\r\n\x1a\nIHDR", ".png")):
        file = root / "mislabelled.png"
        file.write_bytes(magic)
        require(module.detected_image_extension(file) == expected, "control.self-check", "image signature differs")
    receipts.append({"procedure": "image-content-signature", "ok": True})
    receipts.extend(_attachment_import_procedures(root))
    receipts.extend(_context_microkernel_procedure(root))
    receipts.extend(_vision_procedure(root))
    receipts.extend(_submission_procedure(root))
    receipts.extend(_stream_procedure(root))
    receipts.extend(_bridge_procedure(root))
    receipts.extend(_execution_procedure(root))
    receipts.extend(_chrome_procedure(root))
    receipts.extend(_neyvia_browser_procedure(root))
    receipts.extend(_browser_preflight_procedure(root))
    receipts.extend(_plan_procedure(root))
    receipts.extend(_cu_procedure(root))
    return {"ok": True, "contracts": list(CONTRACTS), "self_check": receipts,
            "authority": "scratch files/processes and owned local CDP browser only; no providers, credentials, physical devices or NAS sync"}


def _attachment_import_procedures(root):
    import base64
    from .connected_sessions import attachments as a
    from . import context_import as c
    from .neyvia_runtime_invocation import build_selected_context_packet
    folder = root / "attachments"
    raw = [{"name": "../../report?.pdf", "data": base64.b64encode(b"%PDF-1.7 hello").decode()},
           {"name": "notes.txt", "data": base64.b64encode(b"plain notes").decode()}]
    paths = a.save_files(raw, folder)
    require(a.save_files(raw[:1], folder) == paths[:1] and paths[0].name.endswith("-report_.pdf"),
            "control.self-check", "attachment retry/sanitization differs")
    a.with_files("summarise these", paths)
    a.with_files("", paths[:1])
    require(a.with_files("unchanged", []) == "unchanged", "control.self-check", "empty attachment changed message")
    for invalid, code in (([{"name": "x", "data": "not base64!"}], "invalid_file"),
                           ([raw[0]] * 11, "too_many_files"),
                           ([{"name": "large", "data": base64.b64encode(b"x" * (a.MAX_FILE_BYTES + 1)).decode()}], "file_too_large")):
        try:
            a.save_files(invalid, folder)
        except a.AttachmentError as exc:
            require(exc.code == code, "control.self-check", "attachment rejection code differs")
        else:
            raise ValueError("Oversized/invalid attachment admitted")
    export = root / "claude-export.json"
    export.write_text(json.dumps([{"id": "chosen", "role": "user", "content": "Keep selected content."},
                                  {"id": "excluded", "role": "assistant", "content": "Exclude this."}]), encoding="utf-8")
    receipt = c.import_selection(root, provider="claude-code", export_path=export, selected_item_ids=["chosen"])
    loaded = c.read_import_selection(root, receipt["importId"])
    packet = build_selected_context_packet([{"importId": receipt["importId"]}], root=root)
    require(packet["importIds"] == [receipt["importId"]] and packet["sourceSha256"] == receipt["source"]["sha256"]
            and packet["selected"][0]["content"] == loaded["items"][0]["content"]
            and packet["selected"][0]["importId"] == receipt["importId"]
            and packet["selected"][0]["sourceSha256"] == receipt["source"]["sha256"],
            "control.self-check", "selected packet lost content/hash/identity")
    content_path = Path(receipt["contentPath"])
    with content_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**loaded["items"][0], "sourceItemId": "foreign"}) + "\n")
    _refusal(lambda: c.read_import_selection(root, receipt["importId"]), "does not match its durable receipt")
    rollout = [{"type": "event_msg", "payload": {"type": "user_message", "message": "duplicate excluded"}},
               {"type": "response_item", "timestamp": "t1", "payload": {"type": "message", "id": "u", "role": "user", "content": "Keep api_key=sk-12345678901234567890"}},
               {"type": "response_item", "timestamp": "t2", "payload": {"type": "message", "id": "a", "role": "assistant", "content": "Keep assistant."}},
               {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": "developer excluded"}},
               {"type": "response_item", "payload": {"type": "reasoning", "content": "reasoning excluded"}},
               {"type": "response_item", "payload": {"type": "function_call", "content": "tool excluded"}},
               {"type": "turn_context", "payload": {"world_state": "excluded"}}]
    data = ("\n".join(json.dumps(r) for r in rollout) + "\n").encode()
    upload = c.stage_upload(root, filename=r"..\unsafe\codex.jsonl", chunks=[data[:12], data[12:]])
    preview = c.preview_export("codex", root=root, staged_upload_id=upload["uploadId"])
    require([r["itemId"] for r in preview["items"]] == ["u", "a"] and "path" not in preview["source"]
            and preview["source"]["displayName"] == "codex.jsonl" and preview["counts"]["credentialRedactions"] == 1
            and "[REDACTED_CREDENTIAL]" in preview["items"][0]["content"],
            "control.self-check", "rollout filtering/redaction or staged source changed")
    imported = c.import_selection(root, provider="codex", staged_upload_id=upload["uploadId"], selected_item_ids=["u"], expected_sha256=upload["sha256"])
    require(imported["scope"]["selectedItemIds"] == ["u"] and imported["importedItems"] == 1 and imported["excludedItems"] == 1,
            "control.self-check", "import counts/selection changed")
    text = (Path(imported["contentPath"]).parent / "receipt.json").read_text(encoding="utf-8")
    require("Keep api" not in text and c.read_import_selection(root, imported["importId"])["items"][0]["content"].endswith("[REDACTED_CREDENTIAL]"),
            "control.self-check", "receipt copied content or import lost redaction")
    # Import both accepted transcript roles, preserving only their selected lineage.
    c.import_selection(root, provider="codex", staged_upload_id=upload["uploadId"], selected_item_ids=["u", "a"], expected_sha256=upload["sha256"])
    second = c.import_selection(root, provider="codex", staged_upload_id=upload["uploadId"], selected_item_ids=["a"], expected_sha256=upload["sha256"])
    require(second["importedItems"] == 1 and second["excludedItems"] == 1 and second["lineage"]["selectionExplicit"] is True
            and c.read_import_selection(root, second["importId"])["items"][0]["content"] == "Keep assistant."
            and "sk-12345678901234567890" not in Path(second["contentPath"]).read_text(encoding="utf-8"),
            "control.self-check", "selected second transcript item lost explicit scope or leaked excluded credentials")
    staged = root / ".agent_control/neyvia/context_uploads" / upload["uploadId"] / "content"
    staged.write_bytes(data + b"tampered")
    _refusal(lambda: c.preview_export("codex", root=root, staged_upload_id=upload["uploadId"]), "changed")
    return [{"procedure": "attachment-save-retry-message-refusal", "ok": True},
            {"procedure": "context-upload-preview-import-packet-reopen-tamper", "ok": True}]


def _context_microkernel_procedure(root):
    from .context_engine import DurableContextEngine
    from .context_microkernel import ModelVisibleContext, ContextTurnMetrics, emit_prompt_cache_control
    from .openai_adapter import apply_cache_control_to_payload, build_responses_request
    from .progressive_tools import ProgressiveToolSurface, ProgressiveToolSpec
    engine = DurableContextEngine(root, "bundle", max_context_tokens=4000)
    engine.append("system", "stable policy", kind="contract", pinned=True, importance=1.0)
    engine.append("user", "perform the task", kind="message")
    bundle = engine.bundle("perform the task")
    require(bundle["items"], "control.self-check", "durable recorded messages lost")
    context = ModelVisibleContext(root, "context", max_tokens=3000)
    context.record("system", "policy", kind="instruction", pinned=True)
    context.record("user", "task")
    require(context.model_messages("task"), "control.self-check", "model context empty")
    prompt = context.prompt_with_cache("task", provider="openai")
    require(prompt["prompt_cache_key"] == prompt["cache_control"]["provider_fields"]["prompt_cache_key"]
            == prompt["stable_prefix_cache_key"], "control.self-check", "assembled wire cache identity differs")
    for provider in ("openai", "minimax", "anthropic"):
        emit_prompt_cache_control(stable_prefix_cache_key="stable-prefix", provider=provider)
    require(apply_cache_control_to_payload({"model": "gpt", "input": []}, stable_prefix_cache_key="stable-prefix", provider="openai")["prompt_cache_key"] == "stable-prefix",
            "control.self-check", "adapter cache key missing")
    wire = build_responses_request(objective="task", model="local-fixture", tools=[], stable_prefix_cache_key="stable-prefix").to_provider_payload()
    require(wire["prompt_cache_key"] == wire["stable_prefix_cache_key"] == "stable-prefix" and "cache_control" in wire,
            "control.self-check", "request wire dropped cache controls")
    metrics = ContextTurnMetrics(mission_id="scratch", session_id="context")
    metrics.record_model_invocation(role="executor", uncached_input_tokens=100, cached_input_tokens=20)
    metrics.record_tool_round_trip(tool_name="local.echo", output_text="x" * 40)
    metrics.record_model_invocation(images_sent=1)
    metrics.write_receipt(root)
    surface = ProgressiveToolSurface([ProgressiveToolSpec(name="local.echo", description="Echo", category="local", aliases=("echo",), input_schema={"type": "object"})])
    surface.list_tools()
    surface.describe("local.echo")
    require(surface.search("echo")[0]["name"] == "local.echo" and "inputSchema" not in surface.search("echo")[0],
            "control.self-check", "progressive discovery broke name or schema deferral")
    return [{"procedure": "durable-model-bundle-cache-wire-metrics-discovery", "ok": True}]


def _vision_procedure(root):
    import asyncio, base64
    from agents import OpenAIProvider
    from agents.tool_context import ToolContext
    from agents.run_config import CallModelData, ModelInputData
    from agents.models.chatcmpl_converter import Converter
    from openai import AsyncOpenAI
    from PIL import Image
    from .agent_vision import chat_completions_vision_input
    from .neyvia_agent import NeyviaAgentConfig, build_neyvia_agent
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    # The production image budget preserves already bounded JPEG bytes.
    # Use that exact-input path for this byte-identity/wire contract.
    path = root / "proof.jpg"
    Image.new("RGB", (16, 16), (25, 90, 160)).save(path)
    provider = OpenAIProvider(openai_client=AsyncOpenAI(api_key="scratch-fixture", base_url=proof_text("http://127.0.0.1:48469/v1")), use_responses=False)
    agent, config, _ = build_neyvia_agent(NeyviaAgentConfig(root=root, session_id="vision-scratch", agent_role="verifier",
        transport="chat-completions", model="glm-5.3-flash", provider_id="opencode-go", enable_specialists=False,
        base_url="https://opencode.ai/zen/go/v1", reasoning_effort="low"), provider=provider)
    require(agent.model_settings.reasoning is None and agent.model_settings.extra_body == {"reasoning_effort": "low"},
            "control.self-check", "Chat Completions reasoning route changed")
    describe = next(t for t in agent.tools if t.name == "neyvia_tools_describe")
    description_context = ToolContext(context=None, tool_name=describe.name, tool_call_id="describe", tool_arguments="{}")
    asyncio.run(describe.on_invoke_tool(description_context, json.dumps({"tool_id": "neyvia_view_image"})))
    tool = next(t for t in agent.tools if t.name == "neyvia_view_image")
    context = ToolContext(context=None, tool_name=tool.name, tool_call_id="image", tool_arguments="{}")
    output = asyncio.run(tool.on_invoke_tool(context, json.dumps({"path": "proof.jpg"})))
    require(base64.b64decode(output.image_url.split(",", 1)[1]) == path.read_bytes(), "control.self-check", "tool image bytes differ")
    raw = [{"type": "function_call", "call_id": "image", "name": "neyvia_view_image", "arguments": "{}"},
           {"type": "function_call_output", "call_id": "image", "output": [{"type": "input_image", "image_url": output.image_url}]}]
    filtered = config.call_model_input_filter(CallModelData(model_data=ModelInputData(input=raw, instructions=agent.instructions), agent=agent, context=None))
    import inspect
    if inspect.isawaitable(filtered):
        filtered = asyncio.run(filtered)
    messages = Converter.items_to_messages(filtered.input, model="glm-5.3-flash")
    require(messages[-1]["role"] == "user" and any(i.get("type") == "image_url" and i["image_url"]["url"] == output.image_url for i in messages[-1]["content"])
            and raw[1]["output"][0]["type"] == "input_image", "control.self-check", "SDK wire changed pixels or source tool input")
    outside = root.parent / (root.name + "-outside.png")
    Image.new("RGB", (8, 8)).save(outside)
    try:
        denied = asyncio.run(tool.on_invoke_tool(context, json.dumps({"path": str(outside.resolve())})))
        require("inside the workspace" in str(denied), "control.self-check", "out-of-workspace image not refused")
    finally:
        outside.unlink()
    raw = [{"type": "function_call_output", "call_id": str(n), "output": [{"type": "input_image", "image_url": f"data:image/png;base64,scratch{n}"}]} for n in range(4)]
    filtered = chat_completions_vision_input(CallModelData(model_data=ModelInputData(input=raw, instructions="inspect"), agent=None, context=None))
    require([i["image_url"] for i in filtered.input[-1]["content"] if i["type"] == "input_image"] == ["data:image/png;base64,scratch2", "data:image/png;base64,scratch3"],
            "control.self-check", "image observations not bounded to two latest")
    return [{"procedure": "workspace-image-to-sdk-wire-and-scope-refusal", "ok": True}]


def _submission_procedure(root):
    import copy, subprocess
    from .agent_submission_gate import SCHEMA, validate_receipt
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    folder = root / "submission"
    (folder / "src").mkdir(parents=True)
    source = folder / "src/document.txt"
    obsolete = folder / "src/obsolete.txt"
    source.write_bytes(b"before\n")
    obsolete.write_bytes(b"obsolete\n")
    def git(*args):
        return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True,
                              **hidden_windows_subprocess_kwargs()).stdout.strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Scratch", "-c", "user.email=scratch@example.invalid", "commit", "-qm", "scratch baseline")
    baseline = git("rev-parse", "HEAD")
    source.write_bytes(b"after\n")
    proof = folder / "proof.json"
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    proof.write_text(json.dumps({"sourceHashes": {"src/document.txt": digest(source)}}), encoding="utf-8")
    base = {"schema": SCHEMA, "agent": "scratch-verifier", "phase": "local", "lane": "documents",
        "baseline": {"commit": baseline}, "allowedFiles": ["src/**", "proof.json"], "forbiddenFiles": [".agent_control/**"],
        "changedFiles": [{"path": "src/document.txt", "changeType": "modified", "beforeSha256": hashlib.sha256(b"before\n").hexdigest(), "afterSha256": digest(source)},
                         {"path": "proof.json", "changeType": "added", "beforeSha256": None, "afterSha256": digest(proof)}],
        "commands": [{"command": "local proof observer", "exitCode": 0, "result": {"passed": 1, "failed": 0, "skipped": 0}}],
        "proofs": [{"path": "proof.json", "sha256": digest(proof), "kind": "local", "sourceHashes": {"src/document.txt": digest(source)}}],
        "blockers": [], "claims": {"live": {"claimed": False}, "physicalDevice": {"claimed": False}},
        "summary": {"changedFiles": 2, "proofFiles": 1, "commandCount": 1}}
    accepted = validate_receipt(base, root=folder, phase_policy={"local": {"allowedFiles": ["src/**", "proof.json"], "forbiddenFiles": []}})
    require(accepted.ok and accepted.checked_files == 2 and accepted.checked_proofs == 1,
            "control.self-check", "current hash-bound receipt rejected")
    def denied(receipt, fragments, **kwargs):
        result = validate_receipt(receipt, root=folder, **kwargs)
        require(not result.ok and all(any(fragment in error for error in result.errors) for fragment in fragments),
                "control.self-check", "invalid submission lost a specific refusal")
    source.write_bytes(b"drift\n")
    altered = copy.deepcopy(base)
    altered["changedFiles"].append({"path": "src/missing.txt", "changeType": "added", "beforeSha256": None, "afterSha256": "0" * 64})
    altered["summary"]["changedFiles"] = 3
    denied(altered, ("hash drift", "missing", "out-of-phase"), phase_policy={"local": {"allowedFiles": ["src/other/**"], "forbiddenFiles": []}})
    source.write_bytes(b"after\n")
    proof.write_text(json.dumps({"nested": {"sourceHashes": {"src/document.txt": "f" * 64}}}), encoding="utf-8")
    altered = copy.deepcopy(base)
    altered["proofs"][0]["sha256"] = digest(proof)
    altered["claims"]["live"]["claimed"] = True
    altered["summary"]["proofFiles"] = 7
    denied(altered, ("stale nested", "unproven live", "contradicts"))
    proof.write_text(json.dumps({"sourceHashes": {"src/document.txt": digest(source)}}), encoding="utf-8")
    altered = copy.deepcopy(base)
    altered["changedFiles"][0].update(path="proof.json", beforeSha256="a" * 64, afterSha256=digest(proof))
    altered["allowedFiles"] = ["**"]
    altered["forbiddenFiles"] = ["proof.json"]
    altered["commands"][0]["result"]["failed"] = 1
    denied(altered, ("forbidden", "unstable", "zero exit"))
    obsolete.unlink()  # owned disposable scratch project, never a real workspace file
    altered = copy.deepcopy(base)
    altered["changedFiles"].append({"path": "src/obsolete.txt", "changeType": "deleted", "beforeSha256": hashlib.sha256(b"obsolete\n").hexdigest(), "afterSha256": None})
    altered["summary"]["changedFiles"] = 3
    require(validate_receipt(altered, root=folder).ok, "control.self-check", "exact deleted-file delta rejected")
    (folder / "src/omitted.txt").write_bytes(b"omitted\n")
    denied(altered, ("in-scope Git diff",))
    altered = copy.deepcopy(base)
    altered["agent"] = "sk-DO_NOT_ECHO_1234567890abcdef"
    result = validate_receipt(altered, root=folder)
    require(result.errors == ("receipt contains secret-like key or value",) and altered["agent"] not in " ".join(result.errors),
            "control.self-check", "secret refusal echoed material")
    return [{"procedure": "git-delta-submission-source-hash-phase-lineage-secret-gate", "ok": True}]


def _stream_procedure(root):
    import subprocess, sys, time
    from .chat_stream import StreamCoalescer, begin_chat_stream, append_chat_stream, read_chat_stream, last_stream_event
    from .chat_run_control import record_chat_run_result, compact_recorded_results
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from . import web_backend
    seen = []
    delta = lambda text, item="one": {"kind": "runtime.answer_delta", "message": text, "data": {"itemId": item}}
    relay = StreamCoalescer(seen.append, window=0.1)
    relay.push(delta("hello"))
    relay.push(delta(" world"))
    require(not seen and 0 < relay.due() <= 0.1, "control.self-check", "text not held during bounded window")
    time.sleep(0.12)
    relay.flush_due()
    require(seen[0]["message"] == "hello world" and relay.due() is None,
            "control.self-check", "window expiration did not release text")
    relay.push(delta("next"))
    relay.push({"kind": "runtime.tool", "message": "inspect", "data": {}})
    relay.push(delta("a"))
    relay.push(delta("b", "two"))
    relay.flush()
    require([event["message"] for event in seen] == ["hello world", "next", "inspect", "a", "b"]
            and isinstance(seen[0]["at"], float), "control.self-check", "delivery changed ordering/item boundary/arrival")
    bounded = []
    relay = StreamCoalescer(bounded.append, window=10)
    for _ in range(5):
        relay.push(delta("x" * 1500))
    relay.flush()
    require([len(event["message"]) for event in bounded] == [3000, 3000, 1500], "control.self-check", "coalesced frame unbounded")
    begin_chat_stream(root, "proof-stream")
    append_chat_stream(root, "proof-stream", {**delta("hi"), "at": 1790793676.1304})
    append_chat_stream(root, "proof-stream", {"kind": "runtime.done", "at": "invalid"})
    require(read_chat_stream(root, "proof-stream")["events"][0]["at"] == 1790793676.13,
            "control.self-check", "persisted supplied timestamp changed")
    for used in (1000, 2000):
        append_chat_stream(root, "proof-stream", {"data": {"eventType": "context.usage", "inputTokens": used}})
    for _ in range(400):
        append_chat_stream(root, "proof-stream", delta("word " * 100))
    append_chat_stream(root, "proof-stream", {"data": {"eventType": "context.usage", "inputTokens": 248092}})
    append_chat_stream(root, "proof-stream", delta("tail"))
    head = [row for row in read_chat_stream(root, "proof-stream")["events"] if row["data"].get("eventType") == "context.usage"]
    require(head[-1]["data"]["inputTokens"] == 2000 and last_stream_event(root, "proof-stream", "context.usage", tail_bytes=700)["data"]["inputTokens"] == 248092
            and last_stream_event(root, "proof-stream", "absent") is None and last_stream_event(root, "missing", "context.usage") is None,
            "control.self-check", "tail scan did not find newest split-block event")
    script = root / "stream-protocol.py"
    script.write_text('import json,time\nfor part in ["The"," search"," returned"," 0 matches"]:\n print("FLUXIO_EVENT:"+json.dumps({"kind":"runtime.reasoning_summary_delta","message":part,"data":{"eventType":"x"}}),flush=True)\ntime.sleep(0.6)\nprint("FLUXIO_EVENT:"+json.dumps({"kind":"runtime.tool","message":"inspect","data":{"eventType":"tool_called"}}),flush=True)\nprint(json.dumps({"output":"done"}),flush=True)\n', encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", **hidden_windows_subprocess_kwargs())
    arrivals = []
    stdout, _ = web_backend._communicate_runtime_events(process, timeout=30,
        on_event=lambda event: arrivals.append((event, time.monotonic())))
    require(process.returncode == 0 and stdout.count("FLUXIO_EVENT:") == 5 and len(arrivals) == 2
            and arrivals[0][0]["message"] == "The search returned 0 matches" and arrivals[1][1] - arrivals[0][1] >= 0.4,
            "control.self-check", "actual child relay changed raw output or withheld text during silence")
    usage = {"inputTokens": 10, "outputTokens": 2}
    base = {"reply": "ok", "status": "completed", "conversationPersistence": {"conversationId": "c", "turnId": "t"},
            "turnReceipt": {"usage": usage}, "toolTimeline": [{"summary": "turn"}],
            "compartment": {"state": "ready", "messages": [{"text": "window"}], "turnReceipts": [{}]}}
    def save(identity, value):
        record_chat_run_result(root, identity, value)
        return json.loads((root / ".agent_control/chat_runs/results" / (identity + ".json")).read_text(encoding="utf-8"))
    whole = save("small", base)
    require(whole["compartment"] == {"state": "ready", "windowRef": {"conversationId": "c", "turnId": "t"}}
            and "resultTruncated" not in whole and "usage" not in whole, "control.self-check", "small result changed durable fields")
    large = save("large", {**base, "compartment": {"detail": "m" * (4 * 1024 * 1024)}})
    require("compartment" not in large and large["resultTruncated"] is True and large["turnReceipt"]["usage"] == usage
            and large["toolTimeline"], "control.self-check", "oversize did not drop compartment first")
    huge = save("huge", {**base, "toolTimeline": [{"summary": "m" * (4 * 1024 * 1024)}]})
    require(not {"compartment", "toolTimeline", "turnReceipt"} & huge.keys() and huge["usage"] == usage and huge["reply"] == "ok",
            "control.self-check", "deep oversize lost provider usage or reply")
    directory = root / "old-results/.agent_control/chat_runs/results"
    directory.mkdir(parents=True)
    old = directory / "old.json"
    old.write_text(json.dumps({"reply": "ok", "compartment": {"state": "ready", "messages": [{"text": "m" * 4000}], "turnReceipts": [{}]}}), encoding="utf-8")
    (directory / "new.json").write_text(json.dumps({"reply": "ok", "compartment": {"state": "ready"}}), encoding="utf-8")
    before = old.read_bytes()
    dry = compact_recorded_results(root / "old-results", dry_run=True)
    require(dry["compacted"] == 1 and old.read_bytes() == before, "control.self-check", "dry compaction changed storage")
    report = compact_recorded_results(root / "old-results")
    require(report["compacted"] == 1 and report["bytesAfter"] < report["bytesBefore"]
            and json.loads(old.read_text(encoding="utf-8"))["compartment"] == {"state": "ready"},
            "control.self-check", "compaction failed exact window removal")
    return [{"procedure": "stream-order-bounds-real-child-silence-tail-and-durable-usage", "ok": True}]


def _bridge_procedure(root):
    from . import connected_device_bridge as b
    from .models import WorkspaceProfile
    folder = root / "bridge-policy"
    local, remote = folder / "local", folder / "remote-label-only"
    local.mkdir(parents=True)
    remote.mkdir()
    workspace = WorkspaceProfile(workspace_id="bridge-proof", name="Scratch bridge", root_path=str(remote),
        default_runtime="hermes", workspace_type="python", local_project_path=str(local), nas_project_path=str(remote),
        sync_mode="manual", sync_direction="bidirectional")
    presence = {"local": {"gh": True, "git": True}, "nas": {"gh": False, "git": False}}
    def snapshot():
        return b.build_dual_path_bridge_snapshot(folder, workspaces=[workspace], provider_auth_presence={"github": True}, command_presence=presence)
    initial = snapshot()
    require(initial["schemaVersion"] == "connected-device-bridge/v1" and initial["status"] == "ready"
            and {h["hostId"] for h in initial["hosts"]} == {"local", "nas"} and initial["sync"][0]["direction"] == "bidirectional"
            and "Local gh/git can perform authenticated GitHub work" in initial["manualGitHubBridge"]["summary"],
            "control.self-check", "snapshot lost host mapping or local-only command truth")
    local_payload = next(h for h in initial["hosts"] if h["hostId"] == "local")
    remote_payload = next(h for h in initial["hosts"] if h["hostId"] == "nas")
    require(local_payload["githubAuth"]["authenticated"] and any(c["command"] == "gh" and c["available"] for c in local_payload["commandCapabilities"])
            and not next(c for c in remote_payload["commandCapabilities"] if c["command"] == "gh")["available"],
            "control.self-check", "snapshot claimed remote tools or lost supplied auth presence")
    hosts = b.build_connected_host_manifests(folder, workspaces=[workspace], provider_auth_presence={"github": True}, command_presence=presence)
    merge = b.BridgeActionRequest("merge-plan", "use_github_auth", "nas_to_local", "nas", "local", command="gh pr merge --merge")
    pending = b.evaluate_bridge_action(hosts, merge, audit_root=folder)
    require(pending.status == "pending_approval" and pending.approval_required and "requires approval" in pending.reason,
            "control.self-check", "authenticated identity bypassed operator consent")
    outside = b.BridgeActionRequest("outside", "read_file", "nas_to_local", "nas", "local", path=str(folder / "outside.txt"))
    denied = b.evaluate_bridge_action(hosts, outside, audit_root=folder)
    require(denied.status == "denied" and "outside approved file roots" in denied.reason,
            "control.self-check", "outside root file not refused")
    blocked = b.build_bridge_operation_receipt(hosts, [merge, outside], operation_id="blocked-plan", audit_root=folder)
    require(blocked["status"] == "denied" and blocked["hostStatus"]["local"] == "denied"
            and blocked["pendingApprovals"][0]["actionId"] == "merge-plan" and blocked["denials"][0]["actionId"] == "outside"
            and all(s["resultStatus"] == "not_executed" for s in blocked["steps"]), "control.self-check", "blocked plan hid a verdict or claimed execution")
    for capability in ("command.run", "github.auth"):
        b.upsert_bridge_permission_grant(folder, "local", b.PermissionGrant(capability, "approved", "gh", "scratch operator grant", "scratch"))
    reopened = snapshot()
    require(("local", "command.run", "gh") not in {(r["hostId"], r["capability"], r["scope"]) for r in reopened["pendingApprovals"]}
            and b.load_bridge_permission_grants(folder)["local"][0].capability == "command.run", "control.self-check", "durable scoped grants not reopened")
    hosts = b.build_connected_host_manifests(folder, workspaces=[workspace], provider_auth_presence={"github": True}, command_presence=presence)
    require(b.evaluate_bridge_action(hosts, merge).status == "approved", "control.self-check", "scoped reopened grants not admitted")
    actions = b.manual_github_bridge_actions(str(remote), str(local))
    approved = b.build_bridge_operation_receipt(hosts, actions, operation_id="approved-plan", audit_root=folder)
    require(approved["status"] == "approved" and approved["hostStatus"] == {"local": "approved", "nas": "approved"}
            and approved["steps"][1]["performedByHost"] == "local" and approved["steps"][-1]["performedByHost"] == "nas"
            and approved["steps"][0]["syncStatus"] == "queued" and not approved["pendingApprovals"] and not approved["denials"],
            "control.self-check", "approved metadata plan lost host/queued truth")
    unsafe = b.BridgeActionRequest("unsafe", "run_command", "nas_to_local", "nas", "local", command="gh pr view 1; echo forbidden")
    refused = b.evaluate_bridge_action(hosts, unsafe)
    require(refused.status == "denied" and "unsafe shell operators" in refused.reason, "control.self-check", "prefix gate admitted shell operator")
    bad_lane = b.BridgeActionRequest("bad-lane", "read_file", "nas_to_local", "local", "local", path=str(local))
    require("requires source=nas and target=local" in b.evaluate_bridge_action(hosts, bad_lane).reason,
            "control.self-check", "reversed lane not refused")
    local_host = next(h for h in hosts if h.host_id == "local")
    local_host.app_surfaces = [b.AppSurfaceCapability("browser", "Scratch browser", "browser", True, "approved")]
    inspect = b.BridgeActionRequest("inspect", "inspect_browser", "nas_to_local", "nas", "local", surface_id="browser")
    require(b.evaluate_bridge_action(hosts, inspect).status == "pending_approval", "control.self-check", "surface declaration bypassed explicit inspection grant")
    local_host.permissions.append(b.PermissionGrant("surface.inspect", "approved", "browser"))
    require(b.evaluate_bridge_action(hosts, inspect).status == "approved", "control.self-check", "surface grant not honored")
    last = b.evaluate_bridge_action(hosts, actions[-1])
    path = b.record_bridge_audit_event(folder, last)
    audits = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    require(any(r["actionId"] == "outside" and r["status"] == "denied" and r["performedByHost"] == "local" for r in audits)
            and audits[-1]["actionId"] == "sync_result_to_nas", "control.self-check", "durable audit lost denied/approved host attribution")
    feedback = b.build_live_review_structured_feedback_receipt(event_id="scratch-feedback", route_context={"route": "live-review"},
        task_context={"objective": "retain context"}, verifier_feedback={"summary": "scoped feedback"},
        planner_executor_handoff_id="scratch-handoff", next_idea="show receipt ID", audit_root=folder)
    rows = b.load_bridge_receipts(folder)
    require(rows[-1] == feedback and rows[-1]["receiptKind"] == "live_review_structured_feedback"
            and rows[-1]["eventId"] == "scratch-feedback", "control.self-check", "received feedback differs from durable row")
    require(not list(local.iterdir()) and not list(remote.iterdir()), "control.self-check", "policy planning executed a file operation")
    return [{"procedure": "bridge-scoped-permissions-reopen-denial-audit-plan-feedback", "ok": True,
             "boundary": "local metadata only; labels nas/local denote fixtures; no sync, gh command, identity or device executed"}]


def _execution_procedure(root):
    import subprocess, sys
    from . import action_executor as e
    from .crashproof import CrashProofStore
    from .models import ActionProposal, PlannedStep
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    project = root / "action-project"
    project.mkdir(parents=True)
    readme = project / "README.md"
    readme.write_text("# Scratch\n", encoding="utf-8")
    (project / ".agent_control").mkdir()
    (project / ".agent_control/private-fixture.txt").write_text("owned fixture", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules/cache.txt").write_text("owned cache", encoding="utf-8")
    direct = e.prepare_execution_scope(project, "direct", requested_scope="direct")
    require(not direct.isolated and direct.strategy == "direct" and direct.execution_target == "workspace"
            and direct.storage_mode == "local_disk" and direct.host_locality == "local_machine",
            "control.self-check", "direct action scope misrepresented locality")
    copy = e.prepare_execution_scope(project, "copy")
    copied = Path(copy.execution_root)
    copied.resolve().relative_to(root.resolve())
    require(copy.isolated and copy.strategy == "filesystem_copy" and copied != project
            and (copied / "README.md").read_text(encoding="utf-8") == "# Scratch\n"
            and not (copied / ".agent_control").exists() and not (copied / "node_modules").exists(),
            "control.self-check", "filesystem isolation copied private state/cache or lost source")
    require(e.cleanup_execution_scope(copy)["cleaned"] and not copied.exists(), "control.self-check", "copy cleanup left isolated root")
    from .models import ExecutionScope
    _refusal(lambda: e.cleanup_execution_scope(ExecutionScope(isolated=True, strategy="filesystem_copy", workspace_root=str(project),
        execution_root=str(root), worktree_path=str(root))), "cleanup target escaped")
    require(root.exists() and readme.exists(), "control.self-check", "refused escaped cleanup removed scratch source")
    def git(*args):
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True,
                              **hidden_windows_subprocess_kwargs())
    git("init", "-q")
    git("add", "README.md")
    git("-c", "user.name=Scratch", "-c", "user.email=scratch@example.invalid", "commit", "-qm", "scratch baseline")
    isolated = e.prepare_execution_scope(project, "git-isolation")
    tree = Path(isolated.execution_root)
    tree.resolve().relative_to(root.resolve())
    require(isolated.strategy == "git_worktree" and isolated.isolated and isolated.execution_target == "worktree"
            and isolated.storage_mode == "local_disk" and isolated.host_locality == "local_machine"
            and tree != project and tree.exists(), "control.self-check", "Git worktree scope not real/local")
    require(e.cleanup_execution_scope(isolated)["cleaned"] and not tree.exists(), "control.self-check", "Git isolation cleanup failed")
    handsfree = e.build_execution_policy("experimental")
    step = PlannedStep(step_id="write", title="Implement smallest vertical slice")
    proposal = e.build_action_proposal(step, "Implement and update README.md with mission notes", project, [],
                                      runtime_id="openclaw", execution_scope=direct, execution_policy=handsfree)
    result = e.execute_action(proposal, project, execution_scope=direct, execution_policy=handsfree)
    require(proposal.kind == "file_patch" and not proposal.requires_approval and result.result.ok
            and "Neyvia Mission Note" in readme.read_text(encoding="utf-8"), "control.self-check", "handsfree write not performed and read back")
    builder = e.build_execution_policy("builder")
    review = PlannedStep(step_id="review", title="Review referenced docs and extract constraints")
    proposal = e.build_action_proposal(review, "Implement product files first. After product files change run only focused verification.",
                                     project, [], execution_scope=direct, execution_policy=builder)
    require(proposal.kind != "test_run", "control.self-check", "objective verification words changed non-verification step")
    proposal = e.build_action_proposal(review, "Verify repo with approval-gated verification", project, ["git reset --hard"],
                                     execution_scope=direct, execution_policy=builder, route_configs=[])
    require(proposal.kind != "runtime_delegate", "control.self-check", "delegation hid approval-gated verification")
    phase = e.delegated_cycle_phase_for_step(PlannedStep(step_id="execute", title="Implement smallest vertical slice in product files",
        description="Patch model and UI before focused verification.", kind="primary"), "EXECUTE FIRST, NO PREFLIGHT TESTS. After product files change run focused verification.",
        [{"role": "planner"}, {"role": "executor"}, {"role": "verifier"}])
    require(phase == "execute" and e.delegated_cycle_phase_for_step(review, route_configs=[{"role": "planner"}]) == "plan",
            "control.self-check", "step or explicit route phase changed")
    lease = CrashProofStore(project).create_autonomy_lease(mission_id="scratch-autonomy", duration_seconds=600,
        policy={"allowedActions": ["shell_command"], "allowedRoots": [str(project.resolve())], "destructiveAllowed": False,
                "publicCommunicationAllowed": False, "maxSpend": 0})
    command = ActionProposal(action_id="autonomy", kind="shell_command", title="Scratch command",
        command=f'"{sys.executable}" -c "print(\'autonomy-ready\')"', requires_approval=True,
        policy_decision="requires_approval", mutability_class="read", risk_level="medium")
    for _ in range(2):
        record = e.execute_action(command, project, execution_scope=direct, autonomy_lease_id=lease["leaseId"])
        require(record.result.ok and record.gate.status == "approved" and record.gate.approved_by == "autonomy:" + lease["leaseId"]
                and "autonomy-ready" in record.result.stdout, "control.self-check", "repeated scoped lease command did not execute")
    timeout = ActionProposal(action_id="timeout", kind="test_run", title="Finite deadline command",
        command=f'"{sys.executable}" -c "import time; print(\'started\',flush=True); time.sleep(2)"',
        target_path=str(project), mutability_class="execute", policy_decision="auto_run", requires_approval=False)
    record = e.execute_action(timeout, project, execution_scope=direct, execution_policy=builder, timeout_seconds=1)
    require(not record.result.ok and record.result.exit_code == 124 and "timed out" in record.result.error.lower()
            and "timed out" in record.result.stderr.lower(), "control.self-check", "real subprocess deadline lost failed receipt")
    return [{"procedure": "direct-copy-git-isolation-cleanup-write-lease-repeat-timeout-phase", "ok": True,
             "boundary": "disposable local Git/files/subprocesses; no runtime supervisor or provider delegation"}]


def _owned_console(root, port):
    from contextlib import contextmanager, ExitStack
    @contextmanager
    def opened():
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from playwright.sync_api import sync_playwright
        from .browser_obscura import ObscuraEngine, managed_executable, proof_ports
        from .connected_chrome import owned_tab_transport
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args): pass
        fixture_port = proof_port(48469)
        with ExitStack() as resources:
            server = ThreadingHTTPServer(("127.0.0.1", fixture_port), partial(Handler, directory=str(root)))
            resources.callback(server.server_close)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            resources.callback(thread.join, timeout=2)
            resources.callback(server.shutdown)
            engine = ObscuraEngine(root / "engine", managed_executable(), port=port,
                                   fixtures=True, assigned_ports=proof_ports())
            resources.callback(engine.close)
            playwright = resources.enter_context(sync_playwright())
            browser = playwright.chromium.connect_over_cdp(engine.endpoint,
                headers={"Authorization": "Bearer " + engine.token}, timeout=15000)
            resources.callback(browser.close)
            context = browser.new_context()
            resources.callback(context.close)
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{fixture_port}/console.html", wait_until="domcontentloaded")
            session = context.new_cdp_session(page)
            resources.callback(session.detach)
            browser_session = browser.new_browser_cdp_session()
            resources.callback(browser_session.detach)
            targets = browser_session.send("Target.getTargets")["targetInfos"]
            matching = [row for row in targets if row.get("type") == "page" and row.get("url") == page.url]
            require(len(matching) == 1, "control.self-check", "owned browser target metadata unavailable: " + repr(targets))
            target = matching[0]["targetId"]
            def command(method, arguments):
                return (browser_session if method.startswith("Target.") else session).send(method, arguments)
            resources.enter_context(owned_tab_transport(port, target, command))
            yield
    return opened()


def _chrome_procedure(root):
    from . import connected_chrome as c, connected_chrome_policy as p, thunder_compute as t
    require(not p.assess({"kind": "navigate", "url": "https://example.invalid"}).requires_approval,
            "control.self-check", "routine navigation unnecessarily gated")
    action = {"kind": "click", "x": 1, "y": 1}
    for label in ("Delete instance", "Terminate", "Destroy volume", "Revoke API key"):
        result = p.assess(action, label=label)
        require(result.requires_approval and result.risk == p.RISK_DESTRUCTIVE, "control.self-check", "destruction not gated")
    for label in ("Start instance", "Stop", "Resize disk", "Upgrade machine type", "Restart job"):
        require(p.assess(action, label=label).requires_approval, "control.self-check", "capacity/work control not gated")
    unknown = p.assess(action)
    require(unknown.requires_approval and any("unknown" in reason for reason in unknown.reasons), "control.self-check", "unknown click unattended")
    stop = p.assess(action, label="Stop instance scratch")
    delete = p.assess({**action, "x": 2, "y": 2}, label="Delete instance scratch")
    approval = p.grant_approval(stop, granted_by="scratch operator")
    p.ensure_approved(stop, approval)
    for assessment, grant in ((delete, approval), (delete, None)):
        try:
            p.ensure_approved(assessment, grant)
        except p.ApprovalRequired:
            pass
        else:
            raise ValueError("Contract control.self-check: browser action admitted missing/replayed grant")
    require(t._assess_authentication("Sign in to continue\nContinue with Google\nForgot password?")[:2] == (False, "high")
            and t._assess_authentication("Totally unrelated content")[:2] == (None, "none"),
            "control.self-check", "console observer guessed sign-in state")
    rows = t._extract_instances("scratch-trainer A100 running\nold-box t4 stopped\nnot an instance line")
    require(len(rows) == 2 and rows[0]["status"] == "running" and rows[0]["gpu"] == "a100"
            and all(row["source"] == "visible-text-heuristic" for row in rows), "control.self-check", "console rows lost status/GPU/provenance")
    memory_root = root / "compute-memory"
    require(not t.load_project_memory(memory_root)["known"], "control.self-check", "fresh project memory falsely known")
    saved = t.save_project_memory(memory_root, {"purpose": "scratch fine-tune", "latestCheckpoint": "scratch-4200", "apiKey": "synthetic-rejected-marker"})
    stored = t.project_memory_path(memory_root).read_text(encoding="utf-8")
    require(saved["rejectedFields"] == ["apiKey"] and "apiKey" not in saved and "synthetic-rejected-marker" not in stored
            and t.load_project_memory(memory_root)["latestCheckpoint"] == "scratch-4200" and t.load_project_memory(memory_root)["known"],
            "control.self-check", "project memory leaked unknown input or lost reopened checkpoint")
    # This is an owned empty browser profile, never an existing user tab/session.
    port = proof_port(48466)
    require(c.probe_endpoint(port) is None and c._port_is_free(port),
            "control.self-check", "explicit owned browser proof port already occupied")
    browser_root = (root / "owned-browser").resolve()
    browser_root.mkdir(parents=True)
    fixture = browser_root / "console.html"
    fixture.write_text('<!doctype html><title>Instances</title><h1>Instances</h1><p>Sign out</p><p>scratch-trainer A100 running</p><div id="result">idle</div><button onclick="document.getElementById(\'result\').textContent=\'instance stopped\'">Stop instance</button>', encoding="utf-8")
    owned = _owned_console(browser_root, port)
    owned.__enter__()
    try:
        tabs = c.list_tabs(port=port)
        require(bool(tabs), "control.self-check", "owned browser exposed no actual page targets")
        observed_tabs = [(tab, c.observe(tab.target_id, port=port, with_screenshot=False)) for tab in tabs]
        selected = [(tab, observation) for tab, observation in observed_tabs if "console.html" in observation.get("url", "")]
        require(len(selected) == 1, "control.self-check", "owned console document did not have one actual observed target")
        tab, observation = selected[0]
        require("scratch-trainer" in observation["text"] and observation["settled"] is True,
                "control.self-check", "real controlled document not settled/readable")
        proposal = t.propose_action(tab.target_id, "Stop instance", port=port)
        require(proposal["assessment"]["requiresApproval"], "control.self-check", "real control proposal not gated")
        try:
            t.execute_proposal(tab.target_id, proposal, approval=None, port=port)
        except p.ApprovalRequired:
            pass
        else:
            raise ValueError("Contract control.self-check: real browser click bypassed approval")
        require("instance stopped" not in c.observe(tab.target_id, port=port, with_screenshot=False)["text"],
                "control.self-check", "refused browser action still changed controlled document")
        assessment = p.assess(proposal["action"], label=proposal["control"]["label"], page_url=proposal["pageUrl"])
        approval = p.grant_approval(assessment, granted_by="scratch operator")
        result = t.execute_proposal(tab.target_id, proposal, approval=approval, port=port, expect="instance stopped", evidence_dir=browser_root / "evidence")
        require(result["verdict"] == "verified" and result["expectationMet"] is True,
                "control.self-check", "approved real browser control did not verify changed DOM")
    finally:
        owned.__exit__(None, None, None)
    require(c.probe_endpoint(port) is None, "control.self-check", "owned browser did not close")
    return [{"procedure": "browser-policy-project-memory-owned-chrome-refusal-approve-observe", "ok": True,
             "boundary": proof_text("controlled local HTTP document in empty admitted Obscura profile, CDP48466; no authenticated provider or user browser")}]


def _neyvia_browser_procedure(root):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from .neyvia_browser import BrowserService, BrowserError
    from . import connected_chrome_policy as policy, thunder_compute
    identity = "control.neyvia-live-action"
    fixture = root / "owned-browser"
    service = BrowserService(root / "owned-neyvia-browser")
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args): pass
    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48469)), partial(Handler, directory=str(fixture)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tab = None
    try:
        service.request("headless.start", {"port": proof_port(48466), "allowLocalFixtures": True,
            "assignedPorts": [proof_port(48469), proof_port(48466)]}, owner=True)
        tab = service.request("tab.open", {"url": f"http://127.0.0.1:{proof_port(48469)}/console.html", "engine": "obscura"}, owner=True)["tabId"]
        before = service.request("observe", {"tabId": tab})
        button = next(row for row in before["elements"] if row.get("name") == "Stop instance")
        action = {"revision": before["revision"], "element": button["id"], "action": "click"}
        proposal = {"action": action}
        assessment = policy.assess({**action, "kind": "click"}, label=button["name"],
            page_url=before["url"], page_text=before["text"])
        approval = policy.grant_approval(assessment, granted_by="scratch operator")
        try:
            thunder_compute.execute_neyvia_proposal(service, tab, proposal, expect="instance stopped")
        except policy.ApprovalRequired:
            pass
        else:
            raise ValueError("Native consequential action bypassed recomputed approval")
        try:
            thunder_compute.execute_neyvia_proposal(service, tab, proposal, approval=approval, expect="instance stopped")
        except BrowserError as error:
            require(error.code == "tab_not_granted", identity, "wrong missing owner-grant refusal")
        else:
            raise ValueError("Native action bypassed owner tab grant")
        require(service.request("observe", {"tabId": tab})["revision"] == before["revision"], identity,
                "refused action changed the controlled document")
        service.request("tab.grant", {"tabId": tab, "enabled": True}, owner=True)
        try:
            thunder_compute.execute_neyvia_proposal(service, tab,
                {"action": {**action, "revision": "controlled-stale"}}, approval=approval)
        except BrowserError as error:
            require(error.code == "stale_projection", identity, "stale observed revision admitted")
        else:
            raise ValueError("Native action accepted an unobserved revision")
        result = thunder_compute.execute_neyvia_proposal(service, tab, proposal, approval=approval, expect="instance stopped")
        require(result["backend"] == "neyvia-integrated-browser" and result["verdict"] == "verified"
                and result["readBack"] and result["expectationMet"] and result["changed"], identity,
                "native completion/expected effect lacked actual fresh DOM readback")
        return [{"procedure": "neyvia-owned-dom-approval-grant-stale-refusal-action-readback", "ok": True,
                 "contracts": [identity], "result": result}]
    finally:
        try:
            if tab is not None:
                service.request("tab.close", {"tabId": tab}, owner=True)
        finally:
            service.request("headless.stop", {}, owner=True)
            server.shutdown(); server.server_close(); thread.join(timeout=2)


def _browser_preflight_procedure(root):
    import os, shutil, subprocess
    from .browser_preflight import build_browser_dependency_preflight, repair_browser_dependencies
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    folder = (root / "browser-probe-protocol").resolve()
    folder.mkdir(parents=True)
    # A finite executable protocol fixture proves discovery, subprocess env and
    # diagnostic handling; it is not evidence of a real Linux browser install.
    source = folder / "Probe.cs"
    source.write_text('using System; using System.IO; class Probe { static int Main() { File.WriteAllText(Environment.GetEnvironmentVariable("NEYVIA_PROOF_BROWSER_ENV_FILE"), Environment.GetEnvironmentVariable("LD_LIBRARY_PATH") ?? ""); if(Environment.GetEnvironmentVariable("NEYVIA_PROOF_BROWSER_FAULT")=="1") { Console.Error.WriteLine("chrome: error while loading shared libraries: libatk-1.0.so.0: missing"); return 127; } Console.WriteLine("Chromium protocol fixture 126.0.0.0"); return 0; } }', encoding="utf-8")
    executable = folder / "probe.exe"
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = "Add-Type -Path " + quote(source) + " -OutputAssembly " + quote(executable) + " -OutputType ConsoleApplication"
    completed = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    require(completed.returncode == 0 and executable.exists(), "control.self-check", "finite browser probe fixture compilation failed")
    base = folder / "layout"
    release = base / "releases/stamp"
    release.mkdir(parents=True)
    cache = base / "runtime/home/.cache/ms-playwright"
    browser = cache / "chromium-123/chrome-linux64/chrome"
    browser.parent.mkdir(parents=True)
    shutil.copyfile(executable, browser)
    libraries = base / "runtime/browser-libs-bullseye/root/usr/lib/x86_64-linux-gnu"
    libraries.mkdir(parents=True)
    environment_file = folder / "observed-library-path.txt"
    for name in ("apt-get", "sudo"):
        (folder / (name + ".cmd")).write_text("@echo off\r\nexit /b 77\r\n", encoding="ascii")
    updates = {"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH": str(executable), "PLAYWRIGHT_BROWSERS_PATH": str(cache),
               "PATH": str(folder / "empty-path"), "NEYVIA_PROOF_BROWSER_FAULT": "1", "NEYVIA_PROOF_BROWSER_ENV_FILE": str(environment_file)}
    original = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        missing = build_browser_dependency_preflight(release)
        require(missing["status"] == "dependency_missing" and not missing["browserProofAvailable"]
                and missing["missingLibraries"] == ["libatk-1.0.so.0"] and "Install" in missing["installHint"]
                and missing["repairPlan"]["schema"] == "fluxio.browser_dependency_repair_plan.v1"
                and "libatk1.0-0" in missing["repairPlan"]["packages"] and missing["repairPlan"]["nextAction"],
                "control.self-check", "real probe diagnostic lost missing library or repair package")
        os.environ["PATH"] = str(folder)
        dry = repair_browser_dependencies(release, dry_run=True)
        require(dry["schema"] == "fluxio.browser_dependency_repair.v1" and dry["status"] == "planned"
                and dry["actions"] and Path(dry["receiptPath"]).exists(), "control.self-check", "dry repair failed durable planned command receipt")
        os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = ""
        os.environ["NEYVIA_PROOF_BROWSER_FAULT"] = "0"
        cached = build_browser_dependency_preflight(release)
        require(cached["status"] == "passed" and cached["browserProofAvailable"] and cached["chromeExecutable"] == str(browser)
                and str(libraries) in cached["ldLibraryPath"] and str(libraries) in environment_file.read_text(encoding="utf-8"),
                "control.self-check", "runtime browser cache/library search did not reach actual subprocess environment")
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return [{"procedure": "browser-probe-missing-library-dry-plan-cache-env", "ok": True,
             "boundary": "finite compiled diagnostic protocol fixture; no browser/package download, install or Linux browser availability claim"}]


def _plan_procedure(root):
    import subprocess, sys
    from .connected_sessions import plan as p, plan_limits as limits, claude_transcript as transcript
    from .connected_sessions.claude_items import tool_data, apply_tool_result
    from .connected_sessions.codex_items import plan_item, plan_from_rollout
    from .connected_sessions.model import Item, TurnOptions
    from .connected_sessions.dashboard import _row, doing_now, subagents
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.claude_stream import ClaudeRun
    from .connected_sessions.registry import _build
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    def tool(seq, name, args, structured=None):
        data = tool_data(name, args)
        apply_tool_result(data, text="ok", is_error=False, structured=structured)
        return Item(str(seq), seq, "tool", str(seq), data)
    items = [tool(1, "TaskCreate", {"subject": "Read", "activeForm": "Reading"}, {"task": {"id": "1"}}),
             tool(2, "TaskCreate", {"subject": "Build"}, {"task": {"id": "2"}}),
             tool(3, "TaskCreate", {"subject": "Prove"}), tool(4, "TaskUpdate", {"taskId": "1", "status": "completed"}),
             tool(5, "TaskUpdate", {"taskId": "2", "status": "in_progress"}), tool(6, "TaskGet", {"taskId": "1"})]
    plan = p.latest_plan(items)
    require([(row["id"], row["status"]) for row in plan["items"]] == [("1", "completed"), ("2", "in_progress"), ("3", "pending")]
            and plan["source"] == "claude-tasks" and plan["throughSeq"] == 5
            and p.plan_summary(plan) == {"done": 1, "total": 3, "current": "Build", "next": None},
            "control.self-check", "task checklist lost stable IDs or last-changing sequence")
    require([row["id"] for row in p.latest_plan(items + [tool(9, "TaskUpdate", {"taskId": "3", "status": "deleted"})])["items"]] == ["1", "2"],
            "control.self-check", "task deletion not folded")
    todo = tool(1, "TodoWrite", {"todos": [{"content": "Ship", "status": "in_progress", "activeForm": "Shipping"}, {"content": "Rest", "status": "pending"}]})
    require(p.plan_summary(p.latest_plan([todo]))["current"] == "Shipping"
            and p.latest_plan([todo, tool(2, "TodoWrite", {"todos": []})]) is None and "plan" not in tool_data("TodoWrite", {}),
            "control.self-check", "TodoWrite replacement/clear/empty-input changed")
    live = plan_item("turn", 5, "timestamp", [{"step": "Look", "status": "completed"}, {"step": "Fix", "status": "inProgress"}], None)
    require(p.plan_summary(p.latest_plan([live])) == {"done": 1, "total": 2, "current": "Fix", "next": None}, "control.self-check", "live Codex plan normalization changed")
    folder = root / "connected-plan"
    folder.mkdir(parents=True)
    rollout = folder / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "response_item", "timestamp": "t1", "payload": {"type": "function_call", "name": "update_plan",
        "arguments": json.dumps({"plan": [{"step": "A", "status": "completed"}, {"step": "B", "status": "pending"}]})}}) + "\n" + json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n", encoding="utf-8")
    found = plan_from_rollout(str(rollout))
    require([row["status"] for row in found["items"]] == ["completed", "pending"] and found["updatedAt"] == "t1", "control.self-check", "rollout plan lost source ordering/timestamp")
    day = folder / "codex/sessions/2026/10/02"
    day.mkdir(parents=True)
    windows = {"primary": {"used_percent": 48.0, "window_minutes": 10080, "resets_at": 1791139436},
               "secondary": {"used_percent": 12.5, "window_minutes": 300, "resets_at": 1791000000}}
    (day / "rollout-limits.jsonl").write_text(json.dumps({"type": "event_msg", "timestamp": "t", "payload": {"type": "token_count", "rate_limits": windows}}) + "\n", encoding="utf-8")
    rows = limits.codex_limits(folder / "codex")
    require([(row["window"], row["usedPercent"]) for row in rows] == [("weekly", 48.0), ("five_hour", 12.5)]
            and rows[0]["resetsAt"] == "2026-10-04T18:43:56Z", "control.self-check", "reported Codex windows changed labels/percent/reset")
    limits.record_claude({"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.82, "resetsAt": 1791000000}, folder / "fractions")
    row = limits.claude_limits(folder / "fractions")[0]
    require(row["usedPercent"] == 82.0 and row["label"] == "5-hour" and row["status"] == "allowed_warning", "control.self-check", "Claude fraction or reported status changed")
    actual = {"id": "collab", "kind": "tool", "data": {"name": "spawn_agent", "category": "agent", "title": "Sub-agent: spawn_agent", "status": "running"}}
    notices = [{"id": str(n), "kind": "tool", "data": {"name": "sub_agent", "category": "agent", "title": "Sub-agent activity"}} for n in range(3)]
    require([row["id"] for row in subagents([actual, *notices])] == ["collab"], "control.self-check", "dashboard duplicated notice calls")
    source = [{"kind": "user", "at": "earlier"}, {"kind": "user", "at": "latest"}, {"kind": "reasoning", "data": {"summary": "synthetic private reasoning"}}]
    session = {"id": "s", "app": "claude-code", "status": "working"}
    row = _row(session, {"items": source}, None, None)
    require(row["since"] == "latest" and row["now"] == {"kind": "text", "text": "Writing a reply"}
            and _row(session, {"items": source}, {"state": "running", "startedAt": "owned-run"}, None)["since"] == "owned-run"
            and _row({**session, "status_since": "reported"}, {"items": source}, None, None)["since"] == "reported"
            and doing_now([actual, {"kind": "assistant"}], None)["kind"] == "tool"
            and doing_now([{"kind": "assistant"}], None) == {"kind": "text", "text": "Writing a reply"}
            and doing_now([{"kind": "user"}], None) is None, "control.self-check", "dashboard lost owner activity precedence")
    def call(identity, name, args):
        return {"type": "assistant", "timestamp": identity, "message": {"content": [{"type": "tool_use", "id": identity, "name": name, "input": args}]}}
    def result(identity, task=None, error=False):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": identity, "content": "ok", "is_error": error}]},
                "toolUseResult": {"task": {"id": task}} if task else {}}
    def write(path, records, append=False):
        with path.open("a" if append else "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
    for late in (False, True):
        path = folder / ("late.jsonl" if late else "history.jsonl")
        before = [call("old-todo", "TodoWrite", {"todos": [{"content": "Old", "status": "pending"}]}), result("old-todo"),
                  call("old-clear", "TodoWrite", {"todos": []}), result("old-clear"),
                  call("create", "TaskCreate", {"subject": "Build"}), result("create", "41"),
                  call("bad", "TaskCreate", {"subject": "Rejected"}), result("bad", error=True),
                  {**call("side", "TodoWrite", {"todos": []}), "isSidechain": True}, call("second", "TaskCreate", {"subject": "Check"})]
        acknowledgement = result("second", "77")
        if not late:
            before.append(acknowledgement)
        after = ([acknowledgement] if late else []) + [call("update", "TaskUpdate", {"taskId": "41", "status": "completed"}), result("update"),
            call("failed", "TaskUpdate", {"taskId": "77", "status": "completed"}), result("failed", error=True), {"type": "user", "message": {"content": "Continue"}}]
        write(path, before + [{"type": "user", "message": {"content": "x" * (transcript.INITIAL_WINDOW + 1024)}}] + after)
        store = transcript.ItemStore(path, "scratch")
        store.refresh()
        observed = store.plan()
        cached_history = store._plan_history[1]
        require(store.tail_start > 0 and "create" not in store.by_id and [(r["id"], r["text"], r["status"]) for r in observed["items"]] == [("41", "Build", "completed"), ("77", "Check", "pending")]
                and store.plan() == observed, "control.self-check", "history lost IDs or replayed failed/sidechain operations")
        require(store._plan_history[1] is cached_history, "control.self-check", "unchanged tail rescanned plan history")
        write(path, [call("late-update", "TaskUpdate", {"taskId": "77", "status": "in_progress"}), result("late-update")], append=True)
        store.refresh()
        require(store.plan()["items"][1]["status"] == "in_progress", "control.self-check", "appended update not folded")
        before_paging = store.plan()
        while store.load_earlier():
            pass
        require(store.plan() == before_paging, "control.self-check", "earlier paging replayed TaskCreate")
        write(path, [call("clear", "TodoWrite", {"todos": []}), result("clear")], append=True)
        store.refresh()
        require(store.plan() is None, "control.self-check", "empty TodoWrite did not clear paged history")
    state_root, wrong = (folder / "service").resolve(), (folder / "wrong-cwd").resolve()
    wrong.mkdir()
    adapter = _build(ClaudeAdapter, "claude-code", state_root, None)
    require(adapter.state_root == state_root, "control.self-check", "adapter misplaced service root")
    run = ClaudeRun(cli="unused", run_id="r", session_id=None, message="", options=TurnOptions(), cwd=str(wrong), emit=lambda _: None, state_root=adapter.state_root)
    run._handle({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.28}})
    expected = limits.claude_limits(state_root)
    require(expected[0]["usedPercent"] == 28.0 and expected[0]["at"] and limits.claude_limits(folder / "other") == []
            and not (wrong / ".neyvia").exists(), "control.self-check", "stream limits persisted under chat cwd or foreign root")
    restarted = subprocess.run([sys.executable, "-c", "import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[2]);from grant_agent.proof_credential_guard import install;install(Path(sys.argv[1]));from grant_agent.connected_sessions.plan_limits import claude_limits;print(json.dumps(claude_limits(Path(sys.argv[1]))))", str(state_root), str(Path(__file__).resolve().parents[1])],
                              capture_output=True, text=True, check=True, **hidden_windows_subprocess_kwargs())
    require(json.loads(restarted.stdout) == expected and not list((state_root / ".neyvia").glob("*.tmp")), "control.self-check", "fresh process lost durable reported windows/timestamp")
    from . import neyvia_manuals
    from .native_tools import NativeToolRegistry
    from .neyvia_workspace_tools import workspace_for
    import os
    manual_root = (folder / "manual-service").resolve()
    previous = os.environ.get("NEYVIA_UI_STATE_ROOT")
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(manual_root)
    try:
        registry = NativeToolRegistry(_fixture_root(manual_root), nas_root=manual_root / "unused-local-label")
        service = workspace_for(manual_root)
        manual = neyvia_manuals.call(service, "manual.load", {"id": "agents"}, registry=registry)
    finally:
        workspace_for(manual_root).close()
        if previous is None:
            os.environ.pop("NEYVIA_UI_STATE_ROOT", None)
        else:
            os.environ["NEYVIA_UI_STATE_ROOT"] = previous
    index = neyvia_manuals.index()
    require("agents" in neyvia_manuals.prompt_index() and any(row["id"] == "agents" for row in index["manuals"])
            and manual["ok"] and manual["sha256"] and manual["text"], "control.self-check", "agents manual not discoverable/loadable")
    return [{"procedure": "checklist-transcript-history-paging-reported-limits-restart-dashboard-manual", "ok": True,
             "boundary": "real parsers with disposable transcripts and process restart; no provider CLI/model invoked"}]


def _cu_procedure(root):
    import socket, subprocess, sys
    from . import cu_acceptance as c
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    with socket.socket() as sock:
        require(sock.connect_ex(("127.0.0.1", proof_port(48465))) != 0, "control.self-check", "explicit CU absent-server proof port occupied")
    folder = root / "cu-offline"
    payload = {"pass": True, "revision": 2, "semanticHash": "abc123", "matches": [{"query": "N-E-Y-V-I-A", "matchCount": 1, "sampleNames": ["N-E-Y-V-I-A"]}],
               "treeOmitted": True, "nodes": [{"id": "giant-marker"}] * 3, "tree": {"giant": True}, "accessibilityTree": {"hidden": True}}
    path = c.write_receipt("compact-proof", payload, root=folder)
    stored = json.loads(path.read_text(encoding="utf-8"))
    require(stored["schema"] == "neyvia.cu_acceptance.v2" and stored["pass"] is True and stored["revision"] == 2
            and "giant-marker" not in path.read_text(encoding="utf-8")
            and (path.parent / "compact-proof_latest.json").read_bytes() == path.read_bytes(),
            "control.self-check", "compact v2 receipt lost accepted identity or persisted tree")
    urls = [proof_text("http://127.0.0.1:48465")]
    for flow, expected in (("login_session_smoke", "login_session"), ("surface_nav_interaction_smoke", "surface_navigation")):
        result = c.run_flow(flow, root=folder, discovery_urls=urls)
        require(result["flow"] == expected and result["requestedFlow"] == flow and result["pass"] is False and result["skipped"] is False
                and result["status"] == "server_unavailable" and Path(result["receiptPath"]).is_file(),
                "control.self-check", "canonical alias or absent-server fail-closed receipt changed")
        emitted = json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8"))["reason"]
        require("npm run frontend:dev" in emitted and "npm run verify:cu" in emitted and "pytest" not in emitted.lower()
                and "127.0.0.1:1420" in emitted and proof_text("127.0.0.1:48465") in emitted,
                "control.self-check", "real missing-server durable response lost standalone recovery instructions or probed-port explanation")
    suite = c.run_suite(flows=["login_session", "control_room"], root=folder, discovery_urls=urls)
    require(suite["pass"] is False and suite["summary"] == {"passed": 0, "failed": 2, "total": 2}
            and all(row["status"] == "server_unavailable" for row in suite["results"]) and Path(suite["receiptPath"]).is_file(),
            "control.self-check", "standalone suite admitted unavailable server or lost durable failure receipt")
    listed = subprocess.run([sys.executable, "-m", "grant_agent.cu_acceptance", "--list"], capture_output=True, text=True,
                            check=True, **hidden_windows_subprocess_kwargs())
    require(set(listed.stdout.splitlines()) == set(c.CANONICAL_FLOWS) and "login_session" in listed.stdout and "surface_navigation" in listed.stdout,
            "control.self-check", "actual standalone CLI did not list canonical flows")
    return [{"procedure": "cu-compact-receipts-alias-cli-explicit-absent-server-failclosed", "ok": True,
             "boundary": proof_text("HTTP probes only explicit vacant48465; no default discovery ports, browser or real product UI acceptance")}]


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
