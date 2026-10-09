"""Runtime/provider manual invariants and confined host self-check procedures.

Checks receive the actual arguments and returned value at the owning function,
so direct Python callers share the same contracts as tool/CLI callers.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import inspect
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from fnmatch import fnmatch
from functools import wraps
from pathlib import Path


def require(condition, contract, reason):
    if not condition:
        raise ValueError(f"Contract {contract}: {reason}")


def checked(contract, function):
    signature = inspect.signature(function)

    @wraps(function)
    def invoke(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        result = function(*args, **kwargs)
        check(contract, bound.arguments, result)
        return result

    return invoke


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check_package_export(name, attribute_name, value):
    require(getattr(value, "__name__", None) == attribute_name == name,
            "d.runtime.package.export", "lazy export must retain its public class identity")


def check(contract, args, result):
    if contract == "d.runtime.handback.identity":
        invocation = args["invocation"]
        identity = str(invocation.get("invocationId") or "").strip()
        runtime = str(invocation.get("runtime") or "").strip() or "unknown"
        seen = set(args.get("already_carried") or ())
        expected_counts, expected_rows, skipped = {}, {}, 0
        returns = invocation.get("returns") or {}
        for kind in ("messages", "changes", "artifacts", "receipts"):
            items = returns.get(kind)
            items = [item for item in items if item is not None] if isinstance(items, list) else []
            expected_counts[kind] = len(items)
            expected_rows[kind] = []
            for item in items:
                digest = _digest([identity, kind, item])
                if digest in seen:
                    skipped += 1
                else:
                    seen.add(digest)
                    expected_rows[kind].append({"item": item, "digest": digest,
                        "origin": {"runtime": runtime, "invocationId": identity, "kind": kind}})
        total = sum(map(len, expected_rows.values()))
        require(identity and result["invocationId"] == identity and result["runtime"] == runtime
                and result["carried"] == expected_rows and result["counts"] == expected_counts
                and result["carriedCount"] == total and result["skippedCount"] == skipped
                and result["digests"] == sorted(seen), contract, "content/provenance or duplicate accounting changed")
        require(result["empty"] is (sum(expected_counts.values()) == 0)
                and result["nothingNew"] is (total == 0 and sum(expected_counts.values()) != 0),
                contract, "empty output and repeated output must remain distinct")
        name = str(invocation.get("runtime") or "").strip() or "The runtime"
        parts = []
        for kind, noun in (("messages", "message"), ("changes", "file change"), ("artifacts", "artifact"), ("receipts", "receipt")):
            count = expected_counts[kind]
            if count:
                parts.append(f"{count} {noun}{'s' if count != 1 else ''}")
        text = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]
        require(result["summary"] == (f"{name} returned {text}." if parts else f"{name} returned no output."),
                contract, "summary must report only actual output")
    elif contract == "d.runtime.handback.transcript":
        handback = args["handback"]
        candidates = []
        for row in handback.get("carried", {}).get("messages", []):
            item = row["item"]
            content = next((item.get(k) for k in ("content", "text", "summary", "message") if item.get(k)), None) if isinstance(item, dict) else item
            if not str(content or "").strip():
                continue
            role = str(item.get("role") or "").strip().lower() if isinstance(item, dict) else ""
            user = role in {"user", "operator"}
            candidates.append({"role": "user" if user else "assistant", "author": "You" if user else handback.get("runtime") or "runtime",
                "content": content, "source": "runtime-handback", "origin": row["origin"], "digest": row["digest"]})
        require(result == candidates, contract, "transcript changed author, role, text or origin")
    elif contract == "d.runtime.wrapper.spec":
        runtime = str(args["runtime_id"] or "").strip().lower()
        require(result.schema == "fluxio.runtime_wrapper.v1" and result.runtime_id == runtime
                and runtime in {"hermes", "openclaw", "opencode", "codex"}
                and result.command == [str(v) for v in args["command"] if str(v or "").strip()]
                and result.command and result.cwd == str(Path(args["cwd"]))
                and result.environment_keys == sorted(str(k) for k in (args["environment"] or {}))
                and result.timeout_seconds == max(1, int(args["timeout_seconds"] or 1)),
                contract, "runtime, command, timeout or environment-key projection changed")
    elif contract == "d.runtime.wrapper.state":
        spec = args["spec"]
        limit = max(1, int(args["tail_bytes"] or 1))
        require(result.schema == "fluxio.runtime_wrapper_state.v1" and result.runtime_id == spec.runtime_id
                and result.cwd == spec.cwd and result.env_status == dict(args["env_status"] or {})
                and result.process_tree == list(args["process_tree"] or [])
                and result.ttl_seconds == max(1, int(args["ttl_seconds"] if args["ttl_seconds"] is not None else spec.timeout_seconds))
                and result.stdout_tail_path == spec.stdout_tail_path and result.stderr_tail_path == spec.stderr_tail_path,
                contract, "state must retain wrapper origin, process observation and TTL")
        for value, path in ((result.stdout_tail, spec.stdout_tail_path), (result.stderr_tail, spec.stderr_tail_path)):
            require(len(value) <= limit and (bool(path) or not value), contract, "tail must be bounded and cannot exist without a source")
        require(result.heartbeat_age_seconds is None or result.heartbeat_age_seconds >= 0,
                contract, "heartbeat age cannot be negative")
    elif contract == "d.runtime.wrapper.event":
        spec = args["spec"]
        require(result["schema"] == "fluxio.runtime_wrapper_phase_event.v1" and result["runtimeId"] == spec.runtime_id
                and result["cwd"] == spec.cwd and result["eventStreamPath"] == spec.event_stream_path
                and all(result[k] == str(args[k] or "") for k in ("phase", "status", "message"))
                and result["missionId"] == args["mission_id"] and result["missionRunId"] == args["mission_run_id"],
                contract, "phase event lost runtime/mission association")
    elif contract == "d.runtime.wrapper.receipt":
        spec, state = args["spec"], args["state"]
        require(result.schema == "fluxio.execution_receipt.v1" and result.runtime == spec.runtime_id
                and result.mission_id == args["mission_id"] and result.mission_run_id == args["mission_run_id"]
                and result.changed_files == list(args["changed_files"] or [])
                and result.commands_run == [{"command": " ".join(spec.command), "cwd": spec.cwd, "status": args["status"]}]
                and result.stdout_summaries == ([state.stdout_tail[-500:]] if state.stdout_tail else [])
                and result.stderr_summaries == ([state.stderr_tail[-500:]] if state.stderr_tail else [])
                and result.outputs == {"envStatus": state.env_status, "processTree": state.process_tree,
                    "heartbeatAgeSeconds": state.heartbeat_age_seconds, "ttlSeconds": state.ttl_seconds},
                contract, "execution receipt diverged from observed wrapper state")
    elif contract == "d.runtime.wrapper.replay":
        require(result["schema"] == "fluxio.runtime_wrapper_replay.v1"
                and result["eventStreamPath"] == str(args["event_stream_path"])
                and result["eventCount"] == len(result["events"])
                and result["receiptCount"] == len(result["receipts"])
                and all(isinstance(row, dict) for row in result["events"] + result["receipts"])
                and len(result["events"]) <= max(1, int(args["limit"] or 1)),
                contract, "replay invented rows or exceeded bound")
        statuses = [str(r.get("status") or "") for r in result["receipts"][-1:]]
        statuses += [str(r.get("status") or "") for r in reversed(result["events"])]
        require(result["latestStatus"] == next((s for s in statuses if s), "unknown"), contract, "replay latest status differs from observed rows")
    elif contract == "d.runtime.profile.resolve":
        registry = args["self"]
        expected = registry.profiles.get(args["requested_name"])
        root = args["workspace_root"]
        if expected is None and root:
            for rule in registry.workspace_profiles:
                pattern, name = str(rule.get("pattern", "")).strip(), str(rule.get("profile", "")).strip()
                if pattern and name and (fnmatch(root.as_posix(), pattern) or fnmatch(root.name, pattern)) and name in registry.profiles:
                    expected = registry.profiles[name]
                    break
        if expected is None:
            expected = registry.profiles.get(registry.default_profile)
        require(result is expected, contract, "explicit, workspace and default precedence changed")
    elif contract == "d.runtime.openai.tools":
        skills, execution = args["skills"], args["code_execution"]
        expected = [{"type": "function", "name": s.name, "description": s.description,
            "parameters": s.schema or {"type": "object", "properties": {}}, "strict": True} for s in skills]
        if execution and execution.enabled:
            container = execution.container_id or {"type": "auto", "memory_limit": execution.memory_limit or "4g"}
            if isinstance(container, dict) and execution.file_ids:
                container["file_ids"] = list(execution.file_ids)
            expected.append({"type": "code_interpreter", "container": container})
        require(result == expected, contract, "function schema or code-interpreter configuration changed")
    elif contract == "d.runtime.openai.request":
        plan = args["self"]
        expected = asdict(plan)
        expected = {k: v for k, v in expected.items() if v is not None or k not in {"previous_response_id", "conversation", "instructions", "tool_choice"}}
        require(all(result.get(k) == v for k, v in expected.items()), contract, "serialized request changed route, prompt, tool, storage or continuation")
        require(not any(k in result for k in {"previous_response_id", "conversation", "instructions", "tool_choice"} if getattr(plan, k) is None),
                contract, "unset optional provider field serialized")
    elif contract == "d.runtime.lineage.source":
        expected = []
        for identity in args["lineage"]:
            path = Path(args["base_dir"]) / identity / "timeline.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    expected.append({**row, "session_id": identity})
        require(result == expected, contract, "lineage must preserve source order/content and session origin")
    elif contract == "d.runtime.platform.roots":
        from .platform_config import DEFAULT_NAS_VOLUME_ROOT, DEFAULT_NAS_PROJECT_NAME, DEFAULT_WINDOWS_NAS_VOLUME_MIRROR
        require(result.workspace_root == Path(args["root"] or os.environ.get("FLUXIO_WORKSPACE_ROOT") or ".").expanduser()
                and result.nas_volume_root == Path(os.environ.get("FLUXIO_NAS_VOLUME_ROOT") or DEFAULT_NAS_VOLUME_ROOT).expanduser()
                and result.nas_project_name == (os.environ.get("FLUXIO_NAS_PROJECT_NAME", DEFAULT_NAS_PROJECT_NAME).strip() or DEFAULT_NAS_PROJECT_NAME)
                and result.windows_nas_volume_mirror == Path(os.environ.get("FLUXIO_WINDOWS_NAS_VOLUME_MIRROR") or DEFAULT_WINDOWS_NAS_VOLUME_MIRROR).expanduser(),
                contract, "path configuration ignored explicit/environment roots")
    elif contract == "d.runtime.platform.candidates":
        config = args["self"]
        raw = str(args["value"] or "").strip().replace("\x00", "").replace("\\", "/")
        keys = [str(p).replace("\\", "/").rstrip("/").lower() for p in result]
        require(len(keys) == len(set(keys)), contract, "path candidates must be unique")
        for remote_root in (config.nas_project_root, config.windows_nas_project_root):
            prefix = str(remote_root).replace("\\", "/").rstrip("/")
            if raw == prefix or raw.startswith(prefix + "/"):
                relative = raw[len(prefix):].lstrip("/")
                require(config.workspace_root / relative in result, contract, "remote project path omitted corresponding workspace path")
        prefix = str(config.nas_volume_root).replace("\\", "/").rstrip("/")
        if raw.lower() == prefix.lower() or raw.lower().startswith(prefix.lower() + "/"):
            require(config.windows_nas_volume_mirror / raw[len(prefix):].lstrip("/") in result,
                    contract, "remote path omitted configured mirror")
    elif contract == "d.runtime.platform.coerce":
        import re
        raw = str(args["value"] or "").strip().replace("\x00", "")
        posix = os.name != "nt" if args["posix"] is None else args["posix"]
        matches = list(re.finditer(r"([A-Za-z]):[\\/]", raw)) if posix else []
        expected = Path(raw).expanduser()
        if matches:
            match = matches[-1]
            expected = Path("/mnt") / match[1].lower() / raw[match.end():].replace("\\", "/").lstrip("/")
        require(result == expected, contract, "embedded drive must map to its POSIX mount")
    elif contract == "d.runtime.cache.compatibility":
        service = args["self"]
        sidecar = service._sidecar_integrity()
        require(result["transport"]["sidecarAvailable"] == sidecar["available"]
                and result["limitations"]["remoteFetchConfigured"] == (sidecar["available"] and bool(service.policy.get("peers")))
                and result["limitations"]["localCasImplemented"] is True
                and result["limitations"]["irohSidecarImplemented"] is True
                and result["limitations"]["remoteFetchImplemented"] is True
                and result["policy"]["publicDiscoveryDefault"] == bool(service.policy.get("publicDiscoveryDefault", False)),
                contract, "configured transport cannot be reported as available")
        require(all(result["transport"].get(k) == service.transport.get(k) for k in ("name", "version", "blobsVersion", "docsVersion", "gossipVersion")),
                contract, "compatibility projection changed transport version")
    elif contract == "d.runtime.cache.bootstrap":
        service = args["self"]
        stats = service.stats()["summary"]
        require(all(result[k] == stats[k] for k in ("objects", "bytes", "pinned"))
                and result["localLookupReady"] is True
                and result["remoteLookupReady"] == (service._sidecar_integrity()["available"] and bool(service.policy.get("peers"))),
                contract, "bootstrap differs from persisted local objects or admitted transport")
    elif contract == "d.runtime.cache.plan":
        service = args["self"]
        path = Path(args["path"]).expanduser()
        path = (path if path.is_absolute() else service.root / path).resolve()
        require(path.is_relative_to(service.root) and result["sourcePath"] == str(path)
                and result["workspacePath"] == path.relative_to(service.root).as_posix()
                and result["sourceSize"] == path.stat().st_size
                and result["algorithm"] == "blake3" and result["summary"]["networkRequired"] is False
                and result["summary"]["remotePublish"] is False
                and result["planHash"] == service._plan_hash(result),
                contract, "import intent must bind workspace, source and content without network")
    elif contract == "d.runtime.cache.import":
        if not args["approved"]:
            require(result.get("ok") is False and result.get("status") == "approval_required", contract, "unapproved import claimed execution")
            return
        plan = args["plan"]
        require(result["objectHash"] == plan["objectHash"] and result["planHash"] == plan["planHash"]
                and result["planId"] == plan["planId"] and result["bytes"] == plan["sourceSize"]
                and result["pinned"] is bool(plan["pin"]) and result["kind"] == plan["kind"]
                and result["copied"] is not result["deduplicated"]
                and result["integrityVerified"] is True and result["networkUsed"] is False,
                contract, "admission receipt lost approval/content binding or deduplication truth")
    elif contract == "d.runtime.cache.read":
        service = args["self"]
        length = int(args["length"] if args["length"] is not None else service.cache.get("maxTextReadBytes") or 65536)
        require(result["objectHash"] == str(args["object_hash"]).strip().lower()
                and result["offset"] == args["offset"] and 0 <= result["bytesRead"] <= length
                and result["networkUsed"] is False and result["source"] == "local-cas",
                contract, "local context read changed identity or exceeded limit")
        with service._object_path(result["objectHash"]).open("rb") as handle:
            handle.seek(args["offset"])
            data = handle.read(length)
        require(result["text"] == data.decode(args["encoding"], errors="replace") and result["bytesRead"] == len(data)
                and result["truncated"] == (args["offset"] + len(data) < service._object_path(result["objectHash"]).stat().st_size),
                contract, "context projection differs from actual admitted object")
    elif contract == "d.runtime.version.order":
        import re
        left, right = (tuple(int(n) for n in re.findall(r"\d+", str(args[k] or ""))) for k in ("current", "latest"))
        require(result == ((left > right) - (left < right)), contract, "semantic/date version comparison must use numeric tokens")
    elif contract == "d.runtime.lane.aliases":
        aliases = {"open-code": "opencode", "opencode-native": "opencode", "native-opencode": "opencode",
            "openclaw-local": "openclaw", "cursor-agent": "cursor", "cursor-native": "cursor"}
        require([row["role"] for row in result[:4]] == ["context-reader", "planner", "executor", "verifier"],
                contract, "required lane role order changed")
        for row in result[:4]:
            override = next((r for r in args["route_overrides"] if isinstance(r, dict)
                and str(r.get("role") or "").strip().lower() == row["role"]), {})
            if row["role"] == "executor" and not override:
                override = next((r for r in args["route_overrides"] if isinstance(r, dict)
                    and str(r.get("role") or "").strip().lower() in {"frontend_executor", "backend_executor"}), {})
            value = override.get("runtimeId") or override.get("runtime_id") or override.get("runtime") or ("neyvia-context" if row["role"] == "context-reader" else args["default_runtime"])
            normalized = str(value or "hermes").strip().lower().replace("_", "-")
            require(row["runtimeId"] == (aliases.get(normalized, normalized) or "hermes"),
                    contract, "lane runtime alias or selected runtime changed")
    elif contract == "d.runtime.bridge.bytes":
        source, destination = Path(args["source"]), Path(args["destination"])
        require(result.source == str(source) and result.destination == str(destination)
                and result.sha256 == args["digest"] and result.size_bytes == source.stat().st_size
                and result.size_bytes == destination.stat().st_size
                and _file_sha256(destination) == args["digest"],
                contract, "bridge completion must match actual destination bytes")
        if result.status == "deduplicated":
            require(result.bytes_transferred == 0 and result.reused_bytes == result.size_bytes,
                    contract, "deduplication must reuse all bytes without transfer")
        else:
            require(result.bytes_transferred + result.resumed_from_bytes == result.size_bytes and result.reused_bytes == 0,
                    contract, "resume accounting must include exactly the remaining bytes")
    elif contract == "d.runtime.bridge.envelope":
        envelope = {k: v for k, v in result.items() if k not in {"inboxPath", "outboxPath", "transferredBytes", "reusedBytes"}}
        require(all(json.loads(Path(result[k]).read_text(encoding="utf-8")) == envelope for k in ("inboxPath", "outboxPath"))
                and result["message"] == str(args["message"] or "").strip()
                and result["transferredBytes"] == sum(r["transfer"]["bytes_transferred"] for r in result["attachments"])
                and result["reusedBytes"] == sum(r["transfer"]["reused_bytes"] for r in result["attachments"]),
                contract, "message receipt differs from persisted envelopes or attachment accounting")
    elif contract == "d.runtime.bridge.receive":
        require(len(result["messages"]) <= max(1, int(args["limit"])), contract, "inbox exceeded requested bound")
        for envelope in result["messages"]:
            for row in envelope.get("receivedAttachments", []):
                path = Path(row["path"])
                require(path.is_relative_to(Path(args["output_dir"]).expanduser().resolve())
                        and _file_sha256(path) == row["transfer"]["sha256"],
                        contract, "received attachment escaped output root or changed bytes")
            if args["acknowledge"]:
                require(json.loads(Path(envelope["ackPath"]).read_text(encoding="utf-8"))["messageId"] == envelope["messageId"],
                        contract, "acknowledgement lost envelope identity")
    elif contract == "d.runtime.transfer.file":
        source, destination = Path(args["source"]), Path(args["destination"])
        require(result["files"] == 1 and result["bytes"] == source.stat().st_size
                and result["bytes"] == destination.stat().st_size
                and result["transferredFiles"] + result["skippedFiles"] == 1,
                contract, "file transfer count or destination size differs")
        if result["transferredFiles"]:
            require(result["transferredBytes"] + result["resumedFromBytes"] == result["bytes"]
                    and _file_sha256(destination) == result["sha256"],
                    contract, "completed file transfer must be hash verified and resume bounded")
        else:
            require(result["transferredBytes"] == 0 and result["sha256"] is None,
                    contract, "unchanged-metadata skip must avoid hashing or transfer")
    elif contract == "d.runtime.transfer.directory":
        require(result["files"] == result["transferredFiles"] + result["skippedFiles"]
                and result["exclusions"]["enabled"] is (not args["include_all"])
                and result["verification"]["files"] == result["transferredFiles"],
                contract, "directory receipt lost filtered/changed/skipped accounting")
        for row in result["verification"].get("sha256Manifest", []):
            target = Path(args["destination"]) / row["path"]
            require(target.stat().st_size == row["bytes"] and _file_sha256(target) == row["sha256"],
                    contract, "transferred directory file diverged from hash receipt")
        if not result["transferredFiles"]:
            require(result["verification"]["status"] == "not-required" and result["verification"]["sha256Manifest"] == [],
                    contract, "metadata skip fabricated verification work")
    elif contract == "d.runtime.transfer.receipt":
        require(result["status"] == "completed" and all(json.loads(Path(result[k]).read_text(encoding="utf-8")) == result
            for k in ("localReceiptPath", "nasReceiptPath")), contract, "returned receipt was not persisted identically at both protocol roots")
    else:
        raise ValueError("Unknown runtime manual contract " + contract)


def self_check(root):
    """Use actual serializers and file-backed replay, with no runtime launch."""
    from . import runtime_handback as hb, runtime_wrapper as rw
    from .profiles import ProfileRegistry
    from .openai_adapter import CodeExecutionConfig, tools_from_skills, build_responses_request
    from .skills import SkillRegistry
    from .replay import build_lineage_timeline
    from .platform_config import PlatformConfig

    started = time.perf_counter()
    root = Path(root).resolve() / "runtime-provider"
    root.mkdir(parents=True, exist_ok=True)
    checks, rejected = [], []
    def record(contract, **details):
        checks.append({"contract": contract, "ok": True, **details})
    def refuse(contract, action):
        try:
            action()
        except (ValueError, TypeError):
            rejected.append({"contract": contract, "rejected": True})
        else:
            raise ValueError("Manual adverse path accepted: " + contract)

    invocation = {"invocationId": "scratch-invocation", "runtime": "opencode", "parentSessionId": "scratch-parent",
        "returns": {"messages": [{"role": "user", "text": "Inspect output"}, {"role": "assistant", "text": "Observed output"}],
            "changes": ["artifact.txt", "receipt.json"], "artifacts": [{"path": "artifact.txt"}], "receipts": []}}
    (root / "invocation.json").write_text(json.dumps(invocation), encoding="utf-8")
    first = hb.build_handback(json.loads((root / "invocation.json").read_text(encoding="utf-8")))
    rows = hb.handback_messages(first)
    require(rows[0]["author"] == "You" and rows[1]["author"] == "opencode", "d.runtime.handback.transcript", "role/author goal failed")
    repeat = hb.build_handback(invocation, already_carried=set(first["digests"]))
    require(repeat["nothingNew"] and not repeat["empty"] and repeat["skippedCount"] == 5,
            "d.runtime.handback.identity", "idempotent handback failed")
    invocation["returns"]["messages"].append({"content": "New output"})
    require(hb.build_handback(invocation, already_carried=set(first["digests"]))["carriedCount"] == 1,
            "d.runtime.handback.identity", "resumed output was dropped")
    empty = hb.build_handback({"invocationId": "empty", "runtime": "opencode", "returns": {}})
    require(empty["empty"] and empty["summary"] == "opencode returned no output.", "d.runtime.handback.identity", "empty runtime invented output")
    refuse("d.runtime.handback.identity", lambda: hb.build_handback({"runtime": "opencode"}))
    refuse("d.runtime.handback.identity", lambda: hb.build_handback("not a record"))
    refuse("d.runtime.handback.identity", lambda: check("d.runtime.handback.identity", {"invocation": invocation, "already_carried": None}, {**hb.build_handback(invocation), "runtime": "invented"}))
    record("d.runtime.handback.identity", calls=7)
    record("d.runtime.handback.transcript", calls=1)

    stdout, stderr, events = root / "stdout.tail", root / "stderr.tail", root / "events.jsonl"
    stdout.write_bytes(b"a" * 5000 + b"done")
    stderr.write_bytes(b"warning\n")
    for runtime in rw.SUPPORTED_RUNTIME_WRAPPERS:
        spec = rw.build_runtime_wrapper_spec(runtime_id=runtime, command=[runtime, "--version"], cwd=root,
            environment={"PROOF_ONLY_TOKEN": "scratch-value", "PATH": "scratch"}, stdout_tail_path=str(stdout),
            stderr_tail_path=str(stderr), event_stream_path=str(events), timeout_seconds=120)
        require("scratch-value" not in json.dumps(rw.runtime_wrapper_payload(spec)), "d.runtime.wrapper.spec", "environment value leaked")
    refuse("d.runtime.wrapper.spec", lambda: rw.build_runtime_wrapper_spec(runtime_id="unknown", command=["x"], cwd=root))
    refuse("d.runtime.wrapper.spec", lambda: rw.build_runtime_wrapper_spec(runtime_id="codex", command=[], cwd=root))
    state = rw.build_runtime_wrapper_state(spec, env_status={"PROOF_ONLY_TOKEN": "present_masked"},
        process_tree=[{"pid": os.getpid(), "status": "running"}], heartbeat_at=datetime.now(timezone.utc).isoformat(), tail_bytes=16)
    require(state.stdout_tail == "a" * 12 + "done" and state.stderr_tail == "warning\n", "d.runtime.wrapper.state", "real file tail differs")
    event = rw.build_runtime_wrapper_phase_event(spec, mission_id="scratch-mission", mission_run_id="scratch-run",
        phase="executor", status="completed", message="Local serializer procedure completed")
    receipt = rw.build_runtime_wrapper_execution_receipt(spec, state, receipt_id="scratch-receipt", mission_id="scratch-mission",
        mission_run_id="scratch-run", host="scratch", workspace=str(root), status="completed", summary="Serializer procedure", changed_files=["artifact.txt"])
    events.write_text(json.dumps({**event, "status": "running"}) + "\n{invalid}\n" + json.dumps(event) + "\n", encoding="utf-8")
    receipt_path = root / "execution_receipt.json"
    receipt_path.write_text(json.dumps(asdict(receipt)), encoding="utf-8")
    replay = rw.replay_runtime_wrapper(event_stream_path=events, receipt_paths=[receipt_path, root / "missing.json"])
    require(replay["eventCount"] == 2 and replay["receiptCount"] == 1 and replay["latestStatus"] == "completed",
            "d.runtime.wrapper.replay", "file-backed replay lost actual rows")
    refuse("d.runtime.wrapper.replay", lambda: check("d.runtime.wrapper.replay", {"event_stream_path": events, "limit": 100}, {**replay, "latestStatus": "invented"}))
    for identity in ("spec", "state", "event", "receipt", "replay"):
        record("d.runtime.wrapper." + identity)

    repo = Path(__file__).resolve().parents[2]
    registry = ProfileRegistry(repo / "config/profiles.json")
    require(registry.resolve(None, repo).name == registry.default_profile and registry.resolve(None, repo).agent.parallel_agents >= 1,
            "d.runtime.profile.resolve", "checked-in default profile unavailable")
    require(registry.resolve("minimal_focus", repo).agent.merge_policy == "risk_averse", "d.runtime.profile.resolve", "named profile lost risk policy")
    fixture = root / "profiles.json"
    fixture.write_text(json.dumps({"default_profile": "default", "profiles": {"default": {}, "work": {}, "explicit": {}},
        "workspace_profiles": [{"pattern": "runtime-provider", "profile": "work"}]}), encoding="utf-8")
    scoped = ProfileRegistry(fixture)
    require(scoped.resolve("explicit", root).name == "explicit" and scoped.resolve(None, root).name == "work"
            and scoped.resolve(None, root / "other").name == "default", "d.runtime.profile.resolve", "profile precedence failed")
    record("d.runtime.profile.resolve", calls=5)

    skills = SkillRegistry(repo / "config/skills.json").retrieve("verification and tests", top_k=2)
    tools = tools_from_skills(skills)
    require(bool(tools), "d.runtime.openai.tools", "real skill catalog produced no tools")
    plan = build_responses_request("Inspect local proof", model="scratch-model", tools=tools)
    require(plan.as_dict()["model"] == "scratch-model", "d.runtime.openai.request", "request route changed")
    tools = tools_from_skills(skills[:1], code_execution=CodeExecutionConfig(enabled=True, memory_limit="4g", required=True))
    payload = build_responses_request("Inspect local proof", model="scratch-model", tools=tools, tool_choice="required").as_dict()
    require(payload["tools"][-1]["container"] == {"type": "auto", "memory_limit": "4g"} and payload["tool_choice"] == "required",
            "d.runtime.openai.request", "required interpreter lost configuration")
    refuse("d.runtime.openai.request", lambda: check("d.runtime.openai.request", {"self": plan}, {**plan.as_dict(), "model": "different-model"}))
    record("d.runtime.openai.tools", calls=2)
    record("d.runtime.openai.request", calls=2)

    for identity in ("first", "second"):
        directory = root / identity
        directory.mkdir(exist_ok=True)
        (directory / "timeline.jsonl").write_text(json.dumps({"kind": identity, "message": "local observation"}) + "\n{invalid}\n", encoding="utf-8")
    lineage = build_lineage_timeline(root, ["first", "missing", "second"])
    require([r["session_id"] for r in lineage] == ["first", "second"], "d.runtime.lineage.source", "session order differs")
    refuse("d.runtime.lineage.source", lambda: check("d.runtime.lineage.source", {"base_dir": root, "lineage": ["first", "second"]}, []))
    record("d.runtime.lineage.source")

    env_names = ("FLUXIO_NAS_VOLUME_ROOT", "FLUXIO_NAS_PROJECT_NAME", "FLUXIO_WINDOWS_NAS_VOLUME_MIRROR")
    previous = {k: os.environ.get(k) for k in env_names}
    try:
        os.environ.update(FLUXIO_NAS_VOLUME_ROOT="/scratch/volume", FLUXIO_NAS_PROJECT_NAME="scratch-project", FLUXIO_WINDOWS_NAS_VOLUME_MIRROR="D:/scratch-mirror")
        config = PlatformConfig.from_env(root)
        candidates = config.path_candidates("/scratch/volume/projects/scratch-project/.agent_control/runtime_sessions/delegate.json")
        require(root / ".agent_control/runtime_sessions/delegate.json" in candidates
                and Path("D:/scratch-mirror/projects/scratch-project/.agent_control/runtime_sessions/delegate.json") in candidates,
                "d.runtime.platform.candidates", "relative project correspondence failed")
        require(str(config.coerce_path("/tmp/mirror/C:\\scratch\\project", posix=True)).replace("\\", "/") == "/mnt/c/scratch/project",
                "d.runtime.platform.coerce", "embedded path recovery failed")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    for identity in ("roots", "candidates", "coerce"):
        record("d.runtime.platform." + identity)
    from .p2p_cache import P2PCacheService
    cache_root = root / "cache"
    cache_root.mkdir(exist_ok=True)
    configuration = {"schema": "neyvia.p2p-cache-config/v1", "transport": {"name": "Iroh", "version": "1.0.3", "blobsVersion": "0.103.0", "docsVersion": "0.101.0", "gossipVersion": "0.101.0", "state": "not-installed", "sidecarState": "not-installed", "executable": "", "stateRoot": str(cache_root / "transport"), "storeRoot": str(cache_root / "store")},
        "cache": {"root": str(cache_root / "objects"), "maxImportBytes": 1048576, "maxTextReadBytes": 128, "copyBufferBytes": 64, "verifyOnChangedMetadata": True},
        "policy": {"importsWorkspaceOnly": True, "allowedKinds": ["context-chunk", "artifact", "index"], "peers": [], "publicDiscoveryDefault": False, "publicRelayDefault": False}}
    config_path = cache_root / "cache.json"
    config_path.write_text(json.dumps(configuration), encoding="utf-8")
    cache = P2PCacheService(cache_root, config_path=config_path)
    snapshot, bootstrap = cache.compatibility_snapshot(), cache.bootstrap()
    require(snapshot["transport"]["sidecarAvailable"] is False and bootstrap["remoteLookupReady"] is False
            and not cache.index_path.exists(), "d.runtime.cache.bootstrap", "observation allocated an index or invented transport")
    source = cache_root / "context.txt"
    source.write_text("local context " * 30, encoding="utf-8")
    plan = cache.plan_import(source, kind="context-chunk")
    require(cache.import_object(plan)["status"] == "approval_required" and not cache.index_path.exists(),
            "d.runtime.cache.import", "blocked import mutated store")
    receipt = cache.import_object(plan, approved=True)
    duplicate = cache.import_object(cache.plan_import(source, kind="context-chunk"), approved=True)
    projected = cache.read_text(receipt["objectHash"], length=32)
    require(receipt["copied"] and duplicate["deduplicated"] and projected["bytesRead"] == 32
            and projected["truncated"] and cache.stats()["summary"]["objects"] == 1,
            "d.runtime.cache.import", "file-backed import/dedup/read goal failed")
    refuse("d.runtime.cache.read", lambda: cache.read_text(receipt["objectHash"], length=129))
    refuse("d.runtime.cache.read", lambda: cache.read_text("invalid-object-hash"))
    refuse("d.runtime.cache.plan", lambda: cache.plan_import(root / "invocation.json"))
    refuse("d.runtime.cache.import", lambda: cache.import_object({**plan, "kind": "index"}, approved=True))
    source.write_text("changed source", encoding="utf-8")
    refuse("d.runtime.cache.import", lambda: cache.import_object(plan, approved=True))
    cache._object_path(receipt["objectHash"]).write_bytes(b"tampered admitted object")
    try:
        cache.read_text(receipt["objectHash"])
    except RuntimeError:
        rejected.append({"contract": "d.runtime.cache.read", "rejected": True})
    else:
        raise ValueError("Tampered admitted object was read")
    for identity in ("compatibility", "bootstrap", "plan", "import", "read"):
        record("d.runtime.cache." + identity)
    from .runtime_updates import compare_version_tokens
    require(compare_version_tokens("2026.2.15", "2026.4.14") < 0
            and compare_version_tokens("v0.4.0", "v0.9.0") < 0
            and compare_version_tokens("v1.2.3", "1.2.3") == 0
            and compare_version_tokens("v2.0", "1.99") > 0,
            "d.runtime.version.order", "numeric version order goal failed")
    record("d.runtime.version.order", calls=4)
    import importlib.util
    repair_path = repo / "scripts/repair_nas_opencode_go_auth.py"
    repair_spec = importlib.util.spec_from_file_location("proofs_d_go_env", repair_path)
    repair = importlib.util.module_from_spec(repair_spec)
    repair_spec.loader.exec_module(repair)
    original = "# scratch input only\nexport OPENAI_API_KEY='scratch-other-value'\n"
    merged = repair.merge_provider_env(original, "scratch-go-value")
    require(original.strip() in merged and merged.count("OPENCODE_API_KEY=") == 1,
            "d.runtime.go-env.merge", "unrelated provider entry was changed")
    merged = repair.merge_provider_env("OPENCODE_API_KEY=old\nexport OPENCODE_API_KEY='stale'\nexport MINIMAX_API_KEY='scratch-other'\n", "new-scratch-value")
    require(merged.count("OPENCODE_API_KEY=") == 1 and "MINIMAX_API_KEY='scratch-other'" in merged,
            "d.runtime.go-env.merge", "duplicate export repair failed")
    require("scratch-redaction-value" not in repair._redact("before scratch-redaction-value after", "scratch-redaction-value"),
            "d.runtime.go-env.redact", "in-memory redaction failed")
    refuse("d.runtime.go-env.merge", lambda: repair.merge_provider_env(original, " "))
    refuse("d.runtime.go-env.merge", lambda: repair.check_provider_env_merge(original, "scratch-go-value", merged))
    record("d.runtime.go-env.merge", calls=2)
    record("d.runtime.go-env.redact")

    import subprocess
    import sys
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    # A fresh interpreter is necessary to observe package import laziness.
    code = "import json,sys; import grant_agent; before='grant_agent.engine' in sys.modules; from grant_agent import AutonomousEngine, CapabilityService; print(json.dumps({'engineInitiallyLoaded':before,'exports':[AutonomousEngine.__name__,CapabilityService.__name__],'engineLoaded':'grant_agent.engine' in sys.modules,'capabilityLoaded':'grant_agent.capability_service' in sys.modules}))"
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(repo / "src")
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=child_env, capture_output=True,
        text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    require(completed.returncode == 0, "d.runtime.package.export", "fresh package import failed")
    imported = json.loads(completed.stdout)
    require(imported == {"engineInitiallyLoaded": False, "exports": ["AutonomousEngine", "CapabilityService"],
            "engineLoaded": True, "capabilityLoaded": True}, "d.runtime.package.export", "lazy import behavior changed")
    refuse("d.runtime.package.export", lambda: check_package_export("Expected", "Expected", object()))
    record("d.runtime.package.export", childReturnCode=completed.returncode)
    from .runtime_supervisor import _coerce_platform_path
    require(str(_coerce_platform_path(r"C:\scratch\project", posix=True)).replace("\\", "/") == "/mnt/c/scratch/project"
            and str(_coerce_platform_path(r"/tmp/mirror/C:\scratch\project", posix=True)).replace("\\", "/") == "/mnt/c/scratch/project",
            "d.runtime.platform.coerce", "supervisor helper lost drive-path recovery")
    from .runtime_lane_cycle import normalize_lane_routes
    routes = normalize_lane_routes([{"role": "planner", "runtimeId": "cursor-agent"},
        {"role": "executor", "runtimeId": "native-opencode"}, {"role": "verifier", "runtimeId": "openclaw-local"}])
    require([r["runtimeId"] for r in routes[1:4]] == ["cursor", "opencode", "openclaw"], "d.runtime.lane.aliases", "lane alias normalization failed")
    record("d.runtime.lane.aliases")
    def load_script(name):
        spec = importlib.util.spec_from_file_location("proofs_d_" + name, repo / "scripts" / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    setup = load_script("nas_setup")
    require(setup.collect_add_users(["theo", "sam"], "") == ["theo", "sam"]
            and setup.collect_add_users(["theo,sam", "sam"], "alex, theo") == ["theo", "sam", "alex"]
            and setup.collect_add_users(["", "  ,  "], "theo,,") == ["theo"],
            "d.runtime.nas-setup.users", "local setup parser lost order/deduplication")
    https = load_script("setup_nas_https")
    require(https.split_hosts(["scratch.example.test", "127.0.0.1", "scratch.example.test."]) == (["scratch.example.test"], ["127.0.0.1"]),
            "d.runtime.nas-setup.hosts", "DNS/IP partition goal failed")
    command = https.backend_start_command(proof_text("https://127.0.0.1:48499"), root / "server.crt", root / "server.key", proof_port(48499))
    require(proof_text("--port 48499") in command and "--tls-cert-file " + str(root / "server.crt") in command
            and "--tls-key-file " + str(root / "server.key") in command,
            "d.runtime.nas-setup.tls-command", "TLS command dropped explicit port or certificate paths")
    installer = load_script("install_nas_runtime_stack")
    require(installer.node_platform_arch("x86_64") == "x64" and installer.node_platform_arch("aarch64") == "arm64"
            and installer.node_dist_url("22.22.0", "x64") == "https://nodejs.org/dist/v22.22.0/node-v22.22.0-linux-x64.tar.xz",
            "d.runtime.nas-setup.node-plan", "CPU/package plan changed")
    # Unsupported architecture/version must stop before any download path.
    for action in (lambda: installer.node_platform_arch("unsupported"), lambda: installer.node_dist_url("", "x64")):
        try:
            action()
        except SystemExit:
            rejected.append({"contract": "d.runtime.nas-setup.node-plan", "rejected": True})
        else:
            raise ValueError("Unsupported install plan was accepted")
    for identity in ("users", "hosts", "tls-command", "node-plan"):
        record("d.runtime.nas-setup." + identity)
    from .nas_bridge import NasBridge
    sender, mirror = root / "protocol-sender", root / "protocol-mirror" / "projects"
    sender.mkdir(exist_ok=True)
    mirror.mkdir(parents=True, exist_ok=True)
    attachment = sender / "proof.json"
    attachment.write_bytes((b"local-protocol-proof\n" * 1000) + b"done")
    bridge = NasBridge(sender, mirror)
    first = bridge.send_message(sender="scratch-sender", recipient="scratch-reader", message="Inspect local artifact", attachments=[attachment])
    second = bridge.send_message(sender="scratch-sender", recipient="scratch-reader", message="Reuse local artifact", attachments=[attachment])
    received = bridge.receive_messages(recipient="scratch-reader", output_dir=sender / "received", acknowledge=True)
    require(first["transferredBytes"] == attachment.stat().st_size and second["transferredBytes"] == 0
            and second["reusedBytes"] == attachment.stat().st_size and len(received["messages"]) == 2,
            "d.runtime.bridge.envelope", "local message/dedup protocol failed")
    materialized = Path(received["messages"][0]["receivedAttachments"][0]["path"])
    require(_file_sha256(materialized) == _file_sha256(attachment) and materialized.suffix == ".json",
            "d.runtime.bridge.receive", "materialized attachment differs")
    interrupted = sender / "partial.bin"
    interrupted.write_bytes(b"partial-scratch-bytes" * 1000)
    digest = _file_sha256(interrupted)
    target = bridge._blob_path(digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_suffix(".partial").write_bytes(interrupted.read_bytes()[:512])
    resumed = bridge.send_file(interrupted)
    require(resumed["transfer"]["resumed_from_bytes"] == 512 and not target.with_suffix(".partial").exists(),
            "d.runtime.bridge.bytes", "interrupted local blob did not resume")
    refuse("d.runtime.bridge.bytes", lambda: check("d.runtime.bridge.bytes", {"source": interrupted, "destination": target, "digest": "0" * 64},
        type("AlteredReceipt", (), {"source": str(interrupted), "destination": str(target), "sha256": digest, "size_bytes": interrupted.stat().st_size})()))
    for identity in ("bytes", "envelope", "receive"):
        record("d.runtime.bridge." + identity)

    from .nas_transfer import NasTransfer, NasTransferError, MANIFEST_SCHEMA
    transfer = NasTransfer(sender, mirror, allow_local_nas_root=True)
    receipt = transfer.send(attachment, "drops/proof.json")
    require(receipt["verification"]["status"] == "verified" and receipt["verification"]["sha256"] == _file_sha256(attachment),
            "d.runtime.transfer.file", "single-action file receipt lost actual integrity")
    partial_target = mirror / "drops" / "resume.bin"
    partial_target.with_name(".resume.bin.neyvia-partial").write_bytes(interrupted.read_bytes()[:500])
    receipt = transfer.send(interrupted, "drops/resume.bin")
    require(receipt["resumedFromBytes"] == 500 and receipt["verification"]["sha256"] == digest,
            "d.runtime.transfer.file", "resumed transfer hash/accounting failed")
    project = sender / "project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "src" / "app.txt").write_text("current content", encoding="utf-8")
    for excluded in (".git", "node_modules", "build", "logs", ".agent_control", ".venv"):
        (project / excluded).mkdir(exist_ok=True)
        (project / excluded / "scratch.txt").write_text("scratch generated data", encoding="utf-8")
    (project / "runtime.log").write_text("scratch generated data", encoding="utf-8")
    directory_target = mirror / "drops" / "project"
    (directory_target / "src").mkdir(parents=True, exist_ok=True)
    (directory_target / "src" / "app.txt").write_text("old", encoding="utf-8")
    keeper = directory_target / "unrelated.txt"
    keeper.write_text("keep", encoding="utf-8")
    directory = transfer.send(project, "drops/project")
    require(directory["files"] == 1 and keeper.read_text(encoding="utf-8") == "keep"
            and (directory_target / "src" / "app.txt").read_text(encoding="utf-8") == "current content"
            and not (directory_target / "node_modules").exists() and not (directory_target / "runtime.log").exists(),
            "d.runtime.transfer.directory", "directory collision/filter preservation failed")
    repeated = transfer.send(project, "drops/project")
    require(repeated["transferredFiles"] == 0 and repeated["skippedFiles"] == 1 and repeated["verification"]["sha256Manifest"] == [],
            "d.runtime.transfer.directory", "unchanged directory did verification/transfer work")
    unrestricted = transfer.send(project, "drops/all-project", include_all=True)
    require(unrestricted["files"] == 8 and not unrestricted["exclusions"]["enabled"]
            and (mirror / "drops/all-project/node_modules/scratch.txt").is_file(),
            "d.runtime.transfer.directory", "explicit include-all lost generated fixture files")
    for action in (lambda: transfer.send(attachment, "../escape.txt"),
                   lambda: NasTransfer(sender, root / "missing-mirror" / "projects", allow_local_nas_root=True).send(attachment)):
        try:
            action()
        except NasTransferError:
            rejected.append({"contract": "d.runtime.transfer.receipt", "rejected": True})
        else:
            raise ValueError("Invalid transfer destination was accepted")
    manifest = sender / "invalid-transfer.json"
    manifest.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "destinationRoot": "drops/preflight",
        "entries": [{"source": "proof.json"}, {"source": "missing-file.txt"}]}), encoding="utf-8")
    try:
        transfer.send_manifest(manifest)
    except NasTransferError:
        require(not (mirror / "drops/preflight").exists(), "d.runtime.transfer.receipt", "invalid batch copied before complete preflight")
        rejected.append({"contract": "d.runtime.transfer.receipt", "rejected": True})
    else:
        raise ValueError("Invalid transfer batch was accepted")
    for identity in ("file", "directory", "receipt"):
        record("d.runtime.transfer." + identity)
    from .proofs_d_runtime_auth import self_check as auth_self_check
    auth = auth_self_check(root)
    checks.extend(auth["checks"])
    rejected.extend(auth["rejections"])
    return {"ok": True, "contracts": [r["contract"] for r in checks], "checks": checks, "rejections": rejected,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": auth["frontier"], "truthBoundary": auth["truthBoundary"]}
