"""Production invariants and confined startup checks for PROOFS-e's s-v share.

These checks observe host results; the startup procedure invokes the same host
functions on disposable data. No test modules or credentials are imported.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import inspect
import json
import math
import time
from dataclasses import asdict
from contextlib import nullcontext
from functools import wraps
from pathlib import Path
from zipfile import ZipFile


def require(condition, identity, detail):
    if not condition:
        raise ValueError(f"Manual contract {identity}: {detail}")


def enforced(identity):
    """Keep existing call signatures while checking every successful return."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def invoke(*args, **kwargs):
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            guard = nullcontext()
            if identity in {"sv.skills.create", "sv.skills.save"}:
                admitted = _skill_write_snapshot(identity, arguments.arguments, observe=False)
                if admitted["path"] is not None:
                    from .harness_jobs import _exclusive_job_lock
                    # Different skill files share one history document. Admission
                    # must cover its read/revision/write and checked readback too.
                    admitted["historyPath"].parent.mkdir(parents=True, exist_ok=True)
                    guard = _exclusive_job_lock(admitted["historyPath"], timeout_seconds=120)
            elif identity == "sv.skills.feedback":
                from .harness_jobs import _exclusive_job_lock

                library = arguments.arguments["self"]
                guard = _exclusive_job_lock(library.feedback_path, timeout_seconds=10)
            elif identity == "sv.sdk.generation":
                from .harness_jobs import _exclusive_job_lock
                project = Path(arguments.arguments["root"]).resolve()
                (project / ".agent_control").mkdir(parents=True, exist_ok=True)
                guard = _exclusive_job_lock(project / ".agent_control/sdk-binding-generation", timeout_seconds=120)
            elif identity == "sv.suite.artifacts":
                from .harness_jobs import _exclusive_job_lock
                project = Path(arguments.arguments["bundle_root"])
                project.mkdir(parents=True, exist_ok=True)
                # Competing suite writers must not replace either output while
                # the accepted receipt is independently read back below.
                guard = _exclusive_job_lock(project / (str(arguments.arguments["suite_name"]) + ".json"), timeout_seconds=120)
            with guard:
                return invoke_checked(arguments, args, kwargs)

        def invoke_checked(arguments, args, kwargs):
            if identity == "sv.ui.action-gates":
                graph = arguments.arguments["self"].graph
                arguments.arguments["_prior_revision"] = graph.revision
                arguments.arguments["_prior_hash"] = graph.semantic_hash
            if identity in {"sv.skills.create", "sv.skills.save"}:
                arguments.arguments["_prior_skill"] = _skill_write_snapshot(identity, arguments.arguments)
            try:
                result = function(*args, **kwargs)
            except RuntimeError:
                if identity in {"sv.skills.create", "sv.skills.save"}:
                    _check_failed_skill_write(identity, arguments.arguments)
                raise
            check(identity, result, arguments.arguments)
            return result
        return invoke
    return decorate


def check(identity, result, arguments):
    if identity == "sv.subagent.advisory-bounds":
        from .sub_agent_receipts import SUB_AGENT_ROLES, SUB_AGENT_STATUSES
        row = asdict(result)
        require(row["schema"] == "fluxio.sub_agent_receipt.v1" and row["advisory_only"] is True,
                identity, "subagent receipt must remain advisory")
        require(row["role"] in SUB_AGENT_ROLES and row["status"] in SUB_AGENT_STATUSES and
                math.isfinite(row["confidence"]) and 0 <= row["confidence"] <= 1,
                identity, "role/status/confidence outside normalized domain")
        require(len(row["files_inspected"]) <= 80 and len(row["proof_paths"]) <= 40 and
                len(row["findings"]) <= 16 and len(row["inputs"]) <= 24 and len(row["metadata"]) <= 20,
                identity, "receipt exceeds collection bounds")
        require(all(len(item["summary"]) <= 220 and len(item["evidence"]) <= 6 and
                    all(len(text) <= 180 for text in item["evidence"]) for item in row["findings"]),
                identity, "finding evidence is unbounded")
        require(all(len(text) <= 240 for text in row["files_inspected"] + row["proof_paths"]),
                identity, "receipt path is unbounded")
        require(all(not isinstance(value, str) or len(value) <= 240 for value in row["inputs"].values()),
                identity, "receipt embedded unbounded prompt input")
    elif identity == "sv.suite.summary":
        rows = arguments["results"]
        count = len(rows)
        require(result["preset_count"] == count and result["presets"] == [r.get("preset", "unknown") for r in rows],
                identity, "preset summary lost or fabricated rows")
        for key, expected in {
            "avg_score_delta": round(sum(int(r.get("training_comparison", {}).get("score_delta", 0)) for r in rows) / count, 2) if count else 0,
            "avg_resistance": round(sum(int(r.get("probe", {}).get("resistance_score", 0)) for r in rows) / count, 2) if count else 0,
            "probe_pass_rate": round(100 * sum(r.get("probe", {}).get("status") == "pass" for r in rows) / count, 1) if count else 0,
        }.items():
            require(result[key] == expected, identity, "summary aggregate does not match input observations")
    elif identity == "sv.suite.artifacts":
        json_path, report_path = Path(result["suite_json_path"]), Path(result["suite_report_path"])
        require(json.loads(json_path.read_text(encoding="utf-8")) == {
            "results": arguments["results"], "summary": arguments["summary"]}, identity, "saved suite JSON changed evidence")
        text = report_path.read_text(encoding="utf-8")
        require(text.endswith("\n") and all(f"`{row.get('preset', 'unknown')}`" in text for row in arguments["results"]),
                identity, "human report omitted per-preset results")
    elif identity == "sv.skills.retrieval":
        registry = arguments["self"]
        query = set(__import__("re").findall(r"[a-z0-9]+", arguments["task_brief"].lower()))
        def score(skill):
            tokens = set(__import__("re").findall(r"[a-z0-9]+", (skill.name + " " + skill.description).lower()))
            return len(query & tokens), -len(skill.name)
        ranked = sorted(registry.skills, key=score, reverse=True)[:arguments["top_k"]]
        positives = [row for row in ranked if score(row)[0] > 0]
        require(result == (positives or ranked), identity, "retrieval changed relevance ordering or fallback")
    elif identity == "sv.skills.capsule":
        unsigned = {key: value for key, value in result.items() if key != "planHash"}
        digest = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(result["planHash"] == digest and all(-.25 <= delta <= .25 for delta in result["behaviorVectorDelta"].values()),
                identity, "capsule plan/hash/vector disagree")
        require(all((row["available"] and len(row["sha256"]) == 64) or
                    (row["available"] is False and row["sha256"] == "") for row in result["instructionReceipts"]),
                identity, "instruction availability has no integrity receipt")
        selected = result["skills"]
        require(set(result["requiredToolScopes"]) == {scope for row in selected for scope in row["requiredToolScopes"]} and
                set(result["proofGates"]) == {gate for row in selected for gate in row["proofGates"]},
                identity, "executable gates/scopes were lost during compilation")
    elif identity == "sv.sdk.bindings":
        require(all(content.endswith(b"\n") and b"\r\n" not in content for content in result.values()),
                identity, "generated source must be canonical LF bytes")
        for path, content in result.items():
            if path.suffix == ".py":
                compile(content, str(path), "exec")
        require(len(result) == 2, identity, "language output omitted")
    elif identity == "sv.skills.brief":
        row = asdict(result)
        require(row["mission_id"] == arguments["mission_id"] and row["skill_count"] == len(row["selected_skills"]) and
                len(row["selected_skills"]) <= max(1, min(int(arguments["top_k"] or 1), 12)) and len(row["repo_specific_skills"]) <= 8,
                identity, "skill brief lost mission binding or collection bound")
        require(len(row["allowed_tools"]) <= 16 and len(row["known_failures"]) <= 8 and len(row["prior_successful_recipes"]) <= 8 and
                all(len(skill["description"]) <= 220 and len(skill["skillId"]) <= 120 for skill in row["selected_skills"] + row["repo_specific_skills"]),
                identity, "brief embedded unbounded instructions or history")
    elif identity == "sv.skills.discovery":
        require(len({row["skillId"] for row in result}) == len(result), identity, "duplicate skill origins survived discovery")
        control = arguments["control_dir"]
        if control is not None:
            for row in result:
                project = control.parent / ".codex/skills" / row["skillId"] / "SKILL.md"
                if project.is_file():
                    try:
                        project.read_text(encoding="utf-8")
                    except (OSError, UnicodeError):
                        # Existence does not grant readable instructions. The
                        # loader may select the permitted same-ID home origin.
                        continue
                    require(row["source"]["kind"] == "workspace" and row["source"]["path"] == str(project),
                            identity, "home skill displaced project instructions")
    elif identity == "sv.skills.feedback-summary":
        require(result["promotionGate"]["humanReviewRequired"] is True, identity, "feedback bypassed review authority")
        if result["trend"] == "stagnant":
            require(result["zeroImprovementStreak"] >= 2 and result["latestSystemLoss"] <= .15 and
                    result["selectionPolicy"]["state"] == "review" and result["promotionGate"]["eligible"] is False,
                    identity, "zero-lift slices gained promotion/reuse trust")
    elif identity == "sv.skills.feedback":
        library = arguments["self"]
        persisted = json.loads(library.feedback_path.read_text(encoding="utf-8"))
        require(all(row in persisted for row in result) and len(persisted) <= 500, identity, "feedback did not persist bounded result")
        for row in result:
            require(row["missionId"] == arguments["mission_id"] and row["stepId"] == arguments["step_id"] and
                    row["verificationFailureCount"] == len(arguments["verification_failures"]), identity, "feedback attribution changed")
            if row["systemLoss"] >= .55:
                require(row["nextAction"] == "repair", identity, "high-loss slice reinforced instead of repairing")
            if row["nextAction"] == "branch":
                require(row["systemLoss"] <= .15 and abs(row["improvementScore"]) <= .05, identity, "branch without stagnant low-loss evidence")
    elif identity == "sv.sdk.generation":
        project = Path(arguments["root"])
        require(result["ok"] == all(row["matched"] for row in result["outputs"]), identity, "generation receipt contradicts compared bytes")
        for row in result["outputs"]:
            if row["matched"]:
                content = (project / row["path"]).read_bytes()
                require(len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"],
                        identity, "matched generator receipt has different on-disk bytes")
    elif identity == "sv.sdk.manifest":
        require(result["app_id"] == arguments["app_id"] and result["bridge"]["endpoint"] == arguments["endpoint"].rstrip("/"),
                identity, "SDK manifest changed application identity/bridge")
        for field in ("tasks", "context_surfaces", "action_hooks"):
            require(len(result[field]) == len(arguments[field]) and all(all(output.get(key) == value for key, value in source.items())
                for source, output in zip(arguments[field], result[field])), identity, "SDK manifest weakened declared action/context/task semantics")
    elif identity == "sv.sdk.transport":
        payload = result[0] if arguments["return_headers"] else result
        require(isinstance(payload, dict), identity, "SDK HTTP response must remain a JSON object")
    elif identity == "sv.sdk.plan-only":
        if "executionPolicy" in result:
            policy = result["executionPolicy"]
            require(all(policy.get(key) is False for key in ("builds", "executes", "installs", "publishes")),
                    identity, "launch plan acquired execution authority")
        elif "canActivate" in result:
            require(result["canActivate"] is False, identity, "install plan acquired activation authority")
        elif "executionAllowed" in result:
            require(result["executionAllowed"] is False, identity, "profile plan acquired install authority")
        else:
            raise ValueError("Unknown nonexecuting SDK plan")
    elif identity == "sv.video.metadata":
        source = Path(result["path"])
        probe = result["rawProbe"]
        videos = [row for row in probe.get("streams", []) if row.get("codec_type") == "video"]
        audios = [row for row in probe.get("streams", []) if row.get("codec_type") == "audio"]
        require(result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest() and result["sizeBytes"] == source.stat().st_size,
                identity, "video probe is bound to different source bytes")
        require(result["audio"]["present"] == bool(audios) and result["audio"]["streamCount"] == len(audios) and
                (not videos or (result["video"]["width"] == int(videos[0].get("width") or 0) and result["video"]["height"] == int(videos[0].get("height") or 0))),
                identity, "model-readable metadata disagrees with real FFprobe streams")
    elif identity == "sv.video.digest":
        manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
        require(manifest["schema"] == "fluxio.video_digest.v1" and result["sampledFrameCount"] == len(manifest["frames"]) and
                result["frameCount"] == len(manifest["selectedFrames"]), identity, "digest result differs from saved frame manifest")
        for frame in manifest["frames"]:
            require(frame["sha256"] == hashlib.sha256(Path(frame["path"]).read_bytes()).hexdigest() and bool(frame["timecode"]),
                    identity, "sampled frame/timecode lacks source integrity")
        storyboard = manifest["storyboard"]
        require(storyboard["path"] == result["storyboardPath"] and storyboard["sha256"] == hashlib.sha256(Path(storyboard["path"]).read_bytes()).hexdigest(),
                identity, "storyboard differs from saved receipt")
    elif identity == "sv.snapshot.private-filter":
        parts = [part.casefold() for part in arguments["relative"].parts]
        private = {"memory", "browser-profile", "browser_profile", "chrome-profile", "chrome_profile"}
        if any(part in private for part in parts[:-1]) or parts == ["memory.md"]:
            require(result is True, identity, "staging filter admitted private memory/browser state")
    elif identity == "sv.update.package-parse":
        if result is not None:
            require(isinstance(result, str) and bool(result) and result + "@latest" in arguments["update_command"] and
                    __import__("re").fullmatch(r"(?:@[\w.-]+/)?[\w.-]+", result) is not None,
                    identity, "update parser invented a package or executable command")
    elif identity == "sv.suggestions.priority":
        limit = arguments["limit"]
        require((limit < 0 or len(result) <= limit) and len(set(result)) == len(result), identity, "suggestions duplicate or exceed limit")
        pending = arguments["run_state"].get("next_actions", [])
        if pending and result:
            require(result[0] == f"Finish remaining plan step: {pending[0]}", identity, "existing plan step lost priority")
    elif identity == "sv.suggestions.signals":
        require(set(result) == {"tests_count", "docs_count", "has_pyproject", "has_readme"} and
                all(type(result[key]) is int and result[key] >= 0 for key in ("tests_count", "docs_count")) and
                all(type(result[key]) is bool for key in ("has_pyproject", "has_readme")), identity, "invalid repository signal projection")
    elif identity == "sv.verification.result":
        require(len(result) == len(arguments["commands"]), identity, "command result omitted")
        for row in result:
            require(row.duration_ms >= 0 and row.status in {"blocked", "timeout", "executed"}, identity, "invalid command outcome")
            if row.status == "blocked":
                require(row.return_code == 126 and row.risk_level == "high", identity, "high-risk command was not blocked")
            if row.status == "timeout":
                require(row.return_code == 124 and "timed out" in row.stderr.lower(), identity, "timeout has no stable outcome")
    elif identity == "sv.verification.discovery":
        workdir = arguments["workdir"]
        require(isinstance(result, list) and all(isinstance(command, str) and command for command in result) and
                len(result) == len(set(result)), identity, "default commands invalid/duplicated")
        project, tests = (workdir / "pyproject.toml").exists(), (workdir / "tests").exists()
        require(("python -m compileall -q src" in result) == (project and (workdir / "src").exists()), identity, "compiler discovery ignored project/source metadata")
        require(sum(command in {"pytest tests -q", "python -m unittest discover -s tests"} for command in result) == int(project and tests), identity, "test discovery omitted or doubled available runner")
    elif identity == "sv.verification.normalize":
        original = str(arguments["command"] or "").strip()
        if original == "pytest" or original.startswith("pytest ") or original == "python -m pytest" or original.startswith("python -m pytest "):
            prefix = "pytest" if original.startswith("pytest") else "python -m pytest"
            expected = f'"{arguments["pytest_python"]}" -m pytest {original[len(prefix):].strip()}'.strip()
            require(result == expected, identity, "verification did not use selected Python")
        else:
            require(result == original, identity, "unrelated command was changed")
    elif identity == "sv.ladder.capacity":
        require(result["allowFrontendBuild"] == (result["pcGatewayOnline"] and result["timeBudgetSeconds"] >= result["frontendBuildMinSeconds"]),
                identity, "frontend capacity policy ignored gateway or time")
        require(result["allowBrowserVerification"] == (result["pcGatewayOnline"] and result["operatorPresent"] and result["timeBudgetSeconds"] >= result["browserVerificationMinSeconds"]),
                identity, "browser capacity policy ignored operator/time/gateway")
    elif identity == "sv.ladder.plan":
        require(len(result["changedFiles"]) <= 120 and len(set(result["changedFiles"])) == len(result["changedFiles"]),
                identity, "changed-file projection is unbounded")
        steps = result["steps"]
        require(result["requiredStepCount"] == sum(row["required"] for row in steps) and
                result["capacityGatedStepCount"] == sum(row["capacityGated"] for row in steps), identity, "ladder counts disagree")
        require(all(not (row["required"] and row["capacityGated"]) and
                    row["status"] == ("pending" if row["required"] else "skipped") for row in steps),
                identity, "gated check became required or falsely complete")
    elif identity == "sv.ladder.receipt":
        schema = result["schema"]
        if schema == "fluxio.syntax_import_receipt.v1":
            require(result["status"] == ("passed" if result["exitCode"] == 0 and not result["missingFiles"] else "failed"),
                    identity, "syntax receipt disagrees with command/missing files")
        elif schema == "fluxio.changed_file_targeted_receipt.v1":
            expected = "failed" if result["missingTestFiles"] or result["exitCode"] else "passed" if result["targetedTestFiles"] else "skipped"
            require(result["status"] == expected, identity, "targeted receipt falsely claims execution")
        elif schema == "fluxio.backend_command_smoke_receipt.v1":
            rows = result["commands"]
            expected = "skipped" if not rows else "failed" if any(row["exitCode"] for row in rows) else "passed"
            require(result["status"] == expected and all(not row["exitCode"] for row in rows[:-1]), identity, "backend receipt failed to stop at first failure")
        elif schema == "fluxio.ui_button_smoke_receipt.v1":
            rows = result["interactions"]
            expected = "skipped" if not rows else "failed" if any(row["status"] == "failed" for row in rows) else "passed"
            require(result["status"] == expected and len(rows) <= 20, identity, "UI evidence aggregation fabricated success")
        else:
            raise ValueError("Unknown verification receipt schema")
    elif identity == "sv.support.bundle":
        path = Path(result["output"])
        require(result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and result["bytes"] == path.stat().st_size,
                identity, "published support archive differs from its receipt")
        with ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        check_support_payload(files, arguments["max_jobs"])
    elif identity == "sv.performance.fail-closed":
        rows = result["results"]
        statuses = {row["status"] for row in rows}
        expected = "fail" if "fail" in statuses else "unproven" if "unproven" in statuses else "pass"
        require(result["localBudgetStatus"] == expected and result["promotionEligible"] is False and
                result["status"] == ("fail" if expected == "fail" else "unproven"), identity, "local checks bypassed promotion trust")
        require(result["summary"] == {"passed": sum(row["status"] == "pass" for row in rows),
                "failed": sum(row["status"] == "fail" for row in rows), "unproven": sum(row["status"] == "unproven" for row in rows)},
                identity, "performance aggregate contradicts metric observations")
        require(result["build"]["pathRef"] == "build-dir" and result["runtimeEvidence"]["pathRef"] == "runtime-evidence" and
                str(Path(arguments["build_dir"]).resolve()) not in json.dumps(result) and str(Path(arguments["runtime_evidence_path"]).resolve()) not in json.dumps(result),
                identity, "private evidence path was exposed")
    elif identity in {"sv.skills.create", "sv.skills.save"}:
        from .skill_package import validate_skill_markdown
        path = Path(result["path"])
        content = path.read_bytes()
        require(result["ok"] is True and result["validation"]["status"] == "passed" and
                validate_skill_markdown(content.decode("utf-8"))["status"] == "passed" and
                result["afterSha256"] == hashlib.sha256(content).hexdigest(), identity, "skill output bytes/hash/validation disagree")
        prior = arguments["_prior_skill"]
        require(prior["path"] == path.resolve(), identity, "skill write escaped selected scope")
        history_path = Path(result["evolutionReceiptPath"])
        rows = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
        if identity == "sv.skills.create":
            metadata = Path(result["metadataPath"])
            require(result["revision"] == 0 and result["status"] == "created" and
                    result["metadataSha256"] == hashlib.sha256(metadata.read_bytes()).hexdigest() and
                    f"${result['skillId']}" in metadata.read_text(encoding="utf-8") and
                    any(row.get("eventKind") == "created" and row.get("receiptId") == result["receiptId"] for row in rows), identity, "skill creation lacks complete interface/history")
        elif result["changed"]:
            backup = Path(result["backupPath"])
            require(prior["bytes"] is not None and backup.read_bytes() == prior["bytes"] and
                    result["beforeSha256"] == hashlib.sha256(prior["bytes"]).hexdigest() and
                    result["revision"] == prior["revision"] + 1 and
                    any(row.get("receiptId") == result["receiptId"] for row in rows), identity, "reviewed save lost prior bytes or manufactured revision")
        else:
            require(result["revision"] == prior["revision"] and content == prior["bytes"] and
                    result["backupPath"] == "" and rows == prior["history"], identity, "unchanged save altered content/history")
    elif identity == "sv.skills.catalog":
        for section in ("curatedPacks", "recommendedPacks", "userInstalledSkills", "learnedSkills"):
            for row in result[section]:
                evolution = row["evolutionSummary"]
                require(evolution["humanReviewRequired"] is True and evolution["usageCount"] >= evolution["helpedCount"] >= 0 and
                        evolution["latestRevision"] >= 0 and evolution["revisionCount"] >= 0 and
                        "Usage alone never raises trust" in evolution["trustPolicy"], identity, "catalog treated usage as trusted promotion")
    elif identity == "sv.ui.semantic-identity":
        node = arguments["self"]
        from .ui_graph import NOISE_STATES
        require(result == (node.id, node.role, node.name,
                tuple(sorted(state for state in node.states if state not in NOISE_STATES)),
                node.bounds.quantized(), tuple(sorted(node.actions)), node.parent_id, node.value),
                identity, "semantic identity retained volatile focus or lost durable node state")
    elif identity == "sv.ui.graph-state":
        graph = arguments["self"]
        from .ui_graph import compute_semantic_hash
        require(graph.revision >= 1 and all(node.id == key and node.revision == graph.revision for key, node in graph.nodes.items()) and
                graph.semantic_hash == compute_semantic_hash(graph.nodes.values()) and tuple(result) == graph.last_delta,
                identity, "resident graph revision/hash/delta disagree")
        require(all(row.kind in {"added", "changed", "removed"} and
                (row.node_id not in graph.nodes if row.kind == "removed" else row.node_id in graph.nodes) for row in result),
                identity, "delta contradicts resident nodes")
    elif identity == "sv.ui.delta":
        before, after = arguments["before"], arguments["after"]
        expected = {key: "added" for key in after.keys() - before.keys()}
        expected.update({key: "removed" for key in before.keys() - after.keys()})
        expected.update({key: "changed" for key in before.keys() & after.keys() if before[key].semantic_tuple() != after[key].semantic_tuple()})
        require({row.node_id: row.kind for row in result} == expected and len(result) == len(expected),
                identity, "delta omitted, duplicated or fabricated semantic changes")
    elif identity == "sv.ui.query":
        from .ui_graph import _QUERY_RE, _KNOWN_ROLES
        query = (arguments["query"] or "").strip()
        require(len(result) <= max(1, min(int(arguments["limit"]), 100)) and
                result == sorted(result, key=lambda node: (node.role, node.name, node.id)), identity, "query results unbounded or unordered")
        parsed = _QUERY_RE.match(query)
        structured = parsed and ("[" in query or parsed.group("name") is not None or parsed.group("id") or query.lower() in _KNOWN_ROLES)
        for node in result:
            if not query or query in {"*", "all"}:
                continue
            if structured:
                role, name, node_id = (parsed.group("role") or "").lower(), parsed.group("name") or "", parsed.group("id") or ""
                require((not role or node.role.lower() == role) and (not node_id or node.id == node_id) and
                        (not name or (name.lower() in node.name.lower() if parsed.group("op") == "~=" else name == node.name)),
                        identity, "structured query returned a nonmatching node")
            else:
                require(any(query.lower() in str(value).lower() for value in (node.role, node.name, node.id, *node.states)),
                        identity, "free text query returned a nonmatching node")
    elif identity == "sv.ui.compact-delta":
        graph = arguments["graph"]
        rows = list(arguments["deltas"] if arguments["deltas"] is not None else graph.last_delta)
        rows = rows[:max(1, min(int(arguments["limit"]), 200))]
        require(result.startswith(graph.header_line() + "\ndelta ") and
                all(row.compact_line() in result.splitlines() for row in rows), identity, "compact delta lost revision or changes")
    elif identity == "sv.ui.ax-normalization":
        require(all(node.id and node.role and node.source == arguments["source"] for node in result), identity, "AX normalization lost stable identity/source")
        if "snapshot" in arguments:
            require(all(node.role.lower() not in {"none", "presentation", "inline text box"} for node in result), identity, "AX normalization retained presentational noise")
        else:
            require(all(not (node.role.lower() in {"none", "ignored", "generic"} and not node.name) for node in result), identity, "CDP normalization retained uninteresting noise")
        require(all("click" not in node.actions or "disabled" not in node.states for node in result), identity, "disabled AX control exposed click action")
    elif identity == "sv.ui.compact-result":
        graph = arguments["self"].graph
        require(result["treeOmitted"] is True and result["revision"] == graph.revision and
                result["semanticHash"] == graph.semantic_hash and result["nodeCount"] == len(graph.nodes) and
                "children" not in result and "nodes" not in result and "tree" not in result,
                identity, "compact response exposed a tree or stale graph attribution")
    elif identity == "sv.ui.action-gates":
        args = arguments["args"]
        revision = args.get("ifRev", args.get("if_rev"))
        digest = str(args.get("ifHash") or args.get("if_hash") or "").strip()
        if (revision is not None and int(revision) != arguments["_prior_revision"]) or (digest and digest != arguments["_prior_hash"]):
            require(result["status"] == "stale_state" and result["ok"] is False and
                    arguments["self"].graph.revision == arguments["_prior_revision"], identity, "stale revision/hash did not reject before action")
    elif identity == "sv.ui.discovery":
        from .ui_tools import TOOL_NAMES
        require(set(result) == set(TOOL_NAMES) and len(result) == len(set(result)), identity, "UI registration omitted or duplicated tool names")
        if "registry" in arguments:
            require(all(callable(arguments["registry"]._handlers.get(name)) for name in result), identity, "native registration omitted action handler")
        else:
            surface = arguments["surface"]
            require(all(surface.describe(name).get("name") == name for name in result), identity, "progressive registration is not describable")
    else:
        raise ValueError("Unknown manual contract " + identity)


def _skill_write_snapshot(identity, arguments, *, observe=True):
    """Observe only allowed SKILL.md paths; rejected outside paths are never read."""
    from .web_backend import DEFAULT_ROOT
    payload = arguments["payload"]
    root = Path(arguments.get("root") or DEFAULT_ROOT).resolve()
    home = Path(arguments.get("home_root") or Path.home()).resolve()
    roots = {"project": root / ".codex" / "skills", "personal": home / ".codex" / "skills"}
    skill_id = str((payload.get("name") or payload.get("skillId") or payload.get("skill_id")) if identity == "sv.skills.create" else (payload.get("skillId") or payload.get("skill_id") or "")).strip()
    if identity == "sv.skills.create":
        scope = str(payload.get("scope") or "project").strip().lower()
        if scope not in roots or not __import__("re").fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
            return {"path": None}
        path = (roots[scope] / skill_id / "SKILL.md").resolve()
    else:
        value = str(payload.get("path") or payload.get("sourcePath") or payload.get("source_path") or "").strip()
        if not value:
            return {"path": None}
        path = Path(value).expanduser().resolve()
        scope = next((name for name, base in roots.items() if base.resolve() in path.parents), None)
        if scope is None or path.name != "SKILL.md":
            return {"path": None}
        skill_id = skill_id or path.parent.name
    if roots[scope].resolve() not in path.parents:
        return {"path": None}
    history_path = home / ".codex" / ".neyvia" / "skill_evolution_receipts.json" if scope == "personal" else root / ".agent_control" / "skill_evolution_receipts.json"
    if not observe:
        return {"path": path, "historyPath": history_path}
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        history = []
    history = [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []
    return {"path": path, "bytes": path.read_bytes() if path.is_file() else None, "dirExists": path.parent.exists(),
            "historyPath": history_path, "history": history,
            "revision": max((int(row.get("revision") or 0) for row in history if row.get("skillId") == skill_id), default=0)}


def _check_failed_skill_write(identity, arguments):
    prior = arguments["_prior_skill"]
    if prior["path"] is None:
        return
    path = prior["path"]
    require((path.read_bytes() if path.is_file() else None) == prior["bytes"] and path.parent.exists() == prior["dirExists"],
            identity, "failed skill write changed prior content or left incomplete folder")
    try:
        rows = json.loads(prior["historyPath"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    require(rows == prior["history"], identity, "failed skill write manufactured history")


def check_support_payload(files, max_jobs):
    from .support_bundle import _assert_bundle_safe
    identity = "sv.support.bundle"
    expected = {"manifest.json", "runtime.json", "harness-jobs.json", "logs/index.json", "redaction-policy.json"}
    require(set(files) == expected, identity, "support archive violated member allowlist")
    _assert_bundle_safe(files)
    manifest = json.loads(files["manifest.json"])
    require(manifest["rawProjectContentIncluded"] is False and manifest["rawCredentialsIncluded"] is False,
            identity, "support archive claims raw disclosure")
    jobs, logs = json.loads(files["harness-jobs.json"]), json.loads(files["logs/index.json"])
    require(len(jobs["jobs"]) <= max_jobs and jobs["health"]["selectedJobCount"] == len(jobs["jobs"]),
            identity, "support jobs are unbounded or count disagrees")
    for row in logs["logs"]:
        require(row["rawContentIncluded"] is False, identity, "raw log included")
        if row.get("inspectionTruncated"):
            require(row["inspectedBytes"] <= 2 * 1024 * 1024 and "sha256" not in row and
                    row.get("sampleScope") == "first-and-last-bounded-bytes", identity, "partial log inspection claimed full evidence")


def self_check(root):
    """A single startup procedure collects real host-call and adverse receipts."""
    from .proof_contracts import REPO
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases, contracts = [], set()
    def run(identity, contract_ids, action):
        from .contract_gate import wants
        if not wants(contract_ids):
            return
        try:
            detail = action()
            cases.append({"id": identity, "ok": True, "contracts": contract_ids, "detail": detail})
            contracts.update(contract_ids)
        except PermissionError as exc:
            cases.append({"id": identity, "ok": False, "status": "blocked", "contracts": contract_ids, "reason": str(exc)[:600]})
        except OSError as exc:
            if getattr(exc, "winerror", None) != 1314:
                cases.append({"id": identity, "ok": False, "contracts": contract_ids, "error": str(exc)[:600]})
            else:
                cases.append({"id": identity, "ok": False, "status": "blocked", "contracts": contract_ids,
                              "reason": "Windows denied symbolic-link creation (WinError 1314); symlink cases remain uncovered."})
        except Exception as exc:
            cases.append({"id": identity, "ok": False, "contracts": contract_ids, "error": str(exc)[:600]})
    _check_receipts(root, run)
    _check_skills(root, REPO, run)
    _check_sdk(root, REPO, run)
    _check_verification(root, run)
    _check_support(root, run)
    _check_performance(root, REPO, run)
    _check_video(root, run)
    _check_safe_metadata(root, REPO, run)
    _check_ui_graph(root, run)
    _check_skill_writes(root, REPO, run)
    return {"ok": all(row["ok"] or row.get("status") == "blocked" for row in cases), "cases": cases, "contracts": sorted(contracts),
            "durationMs": round((time.perf_counter() - started) * 1000), "scratchRoot": str(root),
            "boundary": "Local compiler, command, archive, policy and evidence validation; no release, vault, NAS or rendered UI claim."}


def _check_receipts(root, run):
    from .sub_agent_receipts import build_sub_agent_receipt
    from .suite_report import build_suite_summary, write_suite_artifacts
    from .vibe_suggestions import collect_repo_signals, build_vibe_next_steps
    def advisory():
        for role, status, confidence in [("diagnostics", "completed", 1.7), ("unknown", "running", -1)]:
            receipt = build_sub_agent_receipt(mission_id="scratch", assignment="Inspect receipt", role=role, status=status,
                confidence=confidence, inputs={"rawPrompt": "x" * 1000}, files_inspected=[f"src/file{i}.py" for i in range(100)],
                findings=[{"severity": "medium", "summary": "x" * 1000, "evidence": ["y" * 1000]} for _ in range(40)],
                proof_paths=["proof.json"])
            require(receipt.confidence == (1.0 if confidence > 1 else 0) and len(receipt.findings) == 16,
                    "sv.subagent.advisory-bounds", "adverse receipt not normalized")
        # The invariant itself must reject a forged success/authority receipt.
        receipt.advisory_only = False
        try:
            check("sv.subagent.advisory-bounds", receipt, {})
        except ValueError:
            return {"samples": 2, "forgedReceiptRejected": True}
        raise ValueError("forged receipt accepted")
    run("bounded_advisory_receipts", ["sv.subagent.advisory-bounds"], advisory)
    def suite():
        rows = [{"preset": "a", "training_comparison": {"score_delta": 3}, "probe": {"status": "pass", "resistance_score": 90}},
                {"preset": "b", "training_comparison": {"score_delta": 1}, "probe": {"status": "needs_hardening", "resistance_score": 60}}]
        summary = build_suite_summary(rows)
        require(summary["avg_score_delta"] == 2 and summary["probe_pass_rate"] == 50 and build_suite_summary([])["preset_count"] == 0,
                "sv.suite.summary", "suite aggregate sample failed")
        return write_suite_artifacts(root / "suite", "scratch", rows, summary)
    run("suite_artifact_roundtrip", ["sv.suite.summary", "sv.suite.artifacts"], suite)
    def suggestions():
        repo = root / "repo-signals"
        (repo / "tests").mkdir(parents=True)
        (repo / "docs").mkdir()
        (repo / "tests/sample.py").write_text("VALUE=1\n")
        (repo / "docs/a.md").write_text("# A\n")
        (repo / "pyproject.toml").write_text("[project]\nname='scratch'\n")
        signals = collect_repo_signals(repo)
        require(signals["tests_count"] == signals["docs_count"] == 1, "sv.suggestions.signals", "disk signals disagree")
        actions = build_vibe_next_steps("Improve UI preview", {"next_actions": ["Inspect preview"]}, ["m1"], signals, 6)
        require(len(actions) >= 3 and "Finish remaining plan step" in actions[0], "sv.suggestions.priority", "plan continuation lost")
        return {"signals": signals, "count": len(actions)}
    run("repo_signals_and_plan_continuation", ["sv.suggestions.signals", "sv.suggestions.priority"], suggestions)


def _check_skills(root, repo, run):
    from .skills import SkillRegistry
    from .skill_capsules import SkillCapsuleRegistry
    def retrieve():
        registry = SkillRegistry(repo / "config/skills.json")
        required = {"browser_use_local_inspection", "leon_lin_design_taste", "high_end_visual_design", "gpt_taste_frontend_motion",
                    "frontend_image_direction", "ui_refactor_expert", "frontend_taste_director", "jbheaven_godmode_lab",
                    "hermes_skill_packager", "runtime_loop_supervisor", "voice_accessibility_operator"}
        require(required <= {skill.name for skill in registry.skills}, "sv.skills.retrieval", "packaged capability missing")
        for query, expected in [("please run tests and build verification", "run_verification_suite"),
            ("run a JBHEAVEN Godmode G0DM0D3 red-team proof with OpenCode transcript", "jbheaven_godmode_lab"),
            ("improve voice dictation accessibility keyboard screen reader low typing composer", "voice_accessibility_operator")]:
            require(expected in {row.name for row in registry.retrieve(query, 4)}, "sv.skills.retrieval", "relevant packaged capability absent")
        require(len(registry.retrieve("zzzz unmatched tokens", 2)) == 2, "sv.skills.retrieval", "fallback sample failed")
        return {"packagedSkills": len(registry.skills), "queries": 4}
    run("skill_retrieval_and_packaged_capabilities", ["sv.skills.retrieval"], retrieve)
    def compile_capsules():
        capsule_root = root / "capsules"
        instruction = capsule_root / ".codex/skills/unlazy/SKILL.md"
        instruction.parent.mkdir(parents=True)
        instruction.write_text("# Scratch instruction\n", encoding="utf-8")
        registry = SkillCapsuleRegistry(capsule_root)
        basic = registry.compile(["unlazy", "missing-skill"])
        require(basic["missingSkillIds"] == ["missing-skill"] and basic["instructionReceipts"][0]["available"] and
                "receipt_integrity" in basic["proofGates"], "sv.skills.capsule", "instruction availability confused with capsule enforcement")
        design = registry.compile(["neyvia-aesthetic-innovation-master", "neyvia-design-taste-v2", "neyvia-design-taste-v3"])
        require(design["behaviorVectorDelta"]["exploration"] > 0 and "render-critic" in design["phaseBindings"] and
                "screenshot_set" in design["proofGates"] and all(row["available"] is False for row in design["instructionReceipts"]),
                "sv.skills.capsule", "design phases or absent instructions misrepresented")
        return {"planHash": basic["planHash"], "designPlanHash": design["planHash"]}
    run("capsule_instruction_and_execution_boundary", ["sv.skills.capsule"], compile_capsules)
    def briefs():
        from .skill_library import SkillLibrary, load_codex_home_skill_rows
        from .models import LearnedSkill, SkillSource, SkillUsageRecord
        work = root / "skill-library"
        home = root / "skill-home"
        control = work / ".agent_control"
        control.mkdir(parents=True)
        (control / "workspaces.json").write_text("{}")
        for base, description in [(work, "Project guidance"), (home, "Home guidance")]:
            skill = base / ".codex/skills/precedence/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(f"---\nname: precedence\ndescription: {description}\n---\n# Guidance\n")
        discovered = load_codex_home_skill_rows(control, home_root=home)
        winner = next(row for row in discovered if row["skillId"] == "precedence")
        require(winner["source"]["kind"] == "workspace" and winner["runtimeHints"]["loadMode"] == "project-skill-md",
                "sv.skills.brief", "home skill displaced project skill")
        full = "dangerously long instruction " * 200
        (control / "user_installed_skills.json").write_text(json.dumps([{"skillId": "workspace_long_skill", "label": "Workspace Long Skill",
            "description": full, "permissions": ["file_read"], "sourceKind": "workspace"}]))
        (control / "learned_skills.json").write_text(json.dumps([asdict(LearnedSkill(skill_id="learned_receipt_loop", label="Receipt Loop",
            description="Attach proof receipts before marking mission complete", prompt_hint="receipt proof", source=SkillSource(kind="learned", label="Learned"), confidence=.9))]))
        (control / "skill_usage.json").write_text(json.dumps([asdict(SkillUsageRecord(skill_id="workspace_search", label="Workspace Search",
            step_id="s1", mission_id="prior_success", helped=True, source_kind="curated"))]))
        (control / "skill_feedback.json").write_text(json.dumps([{"skillId": "run_verification_suite", "missionId": "prior_failed",
            "systemLoss": .8, "verificationFailures": ["checks skipped"], "nextAction": "repair"}]))
        library = SkillLibrary(work, SkillRegistry(repo / "config/skills.json"), home_root=home)
        brief = library.build_skill_brief(task_brief="Search workspace and verify receipts, then sync artifacts to NAS", mission_id="scratch", top_k=4)
        row = asdict(brief)
        require("workspace_search" in {item["skillId"] for item in row["selected_skills"]} and "file_read" in row["allowed_tools"] and
                any(item["skillId"] == "run_verification_suite" for item in row["known_failures"]) and
                any(item["missionId"] == "prior_success" for item in row["prior_successful_recipes"]) and
                row["relevant_examples"] and any("NAS sync" in text for text in row["forbidden_areas"]) and
                any("full skill catalog" in text for text in row["constraints"]), "sv.skills.brief", "brief lost relevant evidence/permissions/authority bounds")
        bounded = library.build_skill_brief(task_brief="workspace long skill", top_k=3)
        require(full not in json.dumps(asdict(bounded)) and len(json.dumps(asdict(bounded))) < 8000, "sv.skills.brief", "full instruction leaked into brief")
        return {"projectSkillPrecedence": True, "briefSkillCount": brief.skill_count, "historyBounded": True}
    run("skill_brief_context_and_instruction_bounds", ["sv.skills.brief", "sv.skills.discovery"], briefs)
    def feedback():
        from .skill_library import SkillLibrary
        library = SkillLibrary(root / "feedback", SkillRegistry(repo / "config/skills.json"), home_root=root / "empty-home")
        selected = [{"skillId": "verification-loop", "label": "Verification Loop", "sourceKind": "local"}]
        actions = [library.record_slice_feedback(mission_id=f"scratch{i}", step_id=f"step{i}", selected_skills=selected,
                   execution_ok=True, verification_failures=[], changed_files=["src/example.py"])[0]["nextAction"] for i in range(3)]
        summary = library._feedback_summary(selected[0], "verification-loop")
        require(actions == ["reinforce", "reinforce", "branch"] and summary["trend"] == "stagnant" and
                summary["zeroImprovementStreak"] == 2 and not summary["promotionGate"]["eligible"], "sv.skills.feedback", "zero-lift feedback gained trust")
        return {"actions": actions, "promotionEligible": False}
    run("skill_feedback_zero_lift_branch", ["sv.skills.feedback", "sv.skills.feedback-summary"], feedback)


def _check_verification(root, run):
    import sys
    from .verification import VerificationRunner, _normalize_verification_command
    from .verification_ladder import (build_verification_ladder, build_verification_capacity_policy,
        build_syntax_import_receipt, build_changed_file_targeted_receipt, build_backend_command_smoke_receipt,
        build_ui_button_smoke_receipt)
    work = root / "verification"
    work.mkdir()
    def commands():
        runner = VerificationRunner(default_timeout_seconds=1)
        blocked = runner.run(["rm -rf /tmp/disposable-never-executed"], work)[0]
        require(blocked.status == "blocked", "sv.verification.result", "high-risk command escaped safety policy")
        python = sys.executable
        timed = runner.run([f'"{python}" -c "import time;time.sleep(3)"'], work)[0]
        require(timed.status == "timeout" and timed.return_code == 124, "sv.verification.result", "actual child timeout not reported")
        for original in ["pytest sample.py -q", "python -m pytest sample.py -q", "echo sample"]:
            _normalize_verification_command(original, python)
        return {"blockedCode": blocked.return_code, "timeoutCode": timed.return_code}
    run("command_rejection_timeout_and_normalization", ["sv.verification.result", "sv.verification.normalize"], commands)
    def discovery():
        from .verification import detect_default_verification_commands
        folder = root / "command-discovery"
        folder.mkdir()
        (folder / "pyproject.toml").write_text("[project]\nname='scratch-proof'\nversion='0.0.0'\n", encoding="utf-8")
        (folder / "tests").mkdir()
        (folder / "src").mkdir()
        (folder / "package.json").write_text(json.dumps({"scripts": {"frontend:build": "local-declaration-only"}}), encoding="utf-8")
        unavailable = detect_default_verification_commands(folder, pytest_python=str(folder / "absent-python.exe"))
        require(unavailable == ["python -m compileall -q src", "python -m unittest discover -s tests", "npm run frontend:build"], "sv.verification.discovery", "unavailable interpreter did not choose fallback declarations")
        available = detect_default_verification_commands(folder, pytest_python=sys.executable)
        require(available[0] == "python -m compileall -q src" and available[-1] == "npm run frontend:build" and
                available[1] in {"pytest tests -q", "python -m unittest discover -s tests"}, "sv.verification.discovery", "actual interpreter availability discovery lost metadata")
        return {"unavailableInterpreterFallback": True, "actualRunnerDeclaration": available[1], "boundary": "actual Python import-availability probe; no pytest tests or declared verification commands executed"}
    run("default_verification_command_availability_discovery", ["sv.verification.discovery"], discovery)
    def capacity():
        samples = []
        for gateway, operator, seconds in [(False, True, 120), (True, False, 600), (True, True, 600), (True, True, 0)]:
            policy = build_verification_capacity_policy(pc_gateway_online=gateway, operator_present=operator, time_budget_seconds=seconds)
            ladder = build_verification_ladder(mission_id="scratch", changed_files=["web/src/view.jsx"], capacity_policy=policy)
            samples.append({"policy": policy, "required": ladder["requiredStepCount"]})
        backend = build_verification_ladder(mission_id="scratch", changed_files=["src/ok.py", "tests/test_sample.py"])
        require(backend["requiredStepCount"] == 3 and len(build_verification_ladder(mission_id="large", changed_files=[f"src/file{i}.py" for i in range(200)])["changedFiles"]) == 120,
                "sv.ladder.plan", "backend obligations or file bounds changed")
        return {"samples": len(samples), "backendRequired": 3}
    run("verification_capacity_and_required_steps", ["sv.ladder.capacity", "sv.ladder.plan"], capacity)
    def receipts():
        (work / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
        (work / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        (work / "README.md").write_text("# Scratch\n", encoding="utf-8")
        for files, expected in [(["ok.py", "README.md"], "passed"), (["bad.py"], "failed"), (["missing.py"], "failed")]:
            receipt = build_syntax_import_receipt(mission_id="scratch", workspace=work, changed_files=files)
            require(receipt["status"] == expected, "sv.ladder.receipt", "real compiler outcome lost")
        for files, expected in [(["ok.py"], "skipped"), (["tests/test_missing.py"], "failed")]:
            require(build_changed_file_targeted_receipt(mission_id="scratch", workspace=work, changed_files=files)["status"] == expected,
                    "sv.ladder.receipt", "target absence lost")
        first = build_backend_command_smoke_receipt(mission_id="scratch", workspace=work, commands=[[sys.executable, "-c", "print('backend ok')"]])
        require(first["status"] == "passed" and "backend ok" in first["commands"][0]["stdoutSummary"], "sv.ladder.receipt", "real backend command failed")
        failing = build_backend_command_smoke_receipt(mission_id="scratch", workspace=work,
            commands=[[sys.executable, "-c", "import sys;sys.exit(3)"], [sys.executable, "-c", "open('must-not-exist','w').write('ran')"]])
        require(failing["status"] == "failed" and len(failing["commands"]) == 1 and not (work / "must-not-exist").exists(),
                "sv.ladder.receipt", "commands continued after failure")
        require(build_backend_command_smoke_receipt(mission_id="scratch", workspace=work)["status"] == "skipped", "sv.ladder.receipt", "no command fabricated success")
        # Receipt aggregation only: these inputs assert no live browser proof.
        for interactions, expected in [([], "skipped"), ([{"label": "open", "status": "passed", "observed": "input receipt"}], "passed"),
                ([{"label": "open", "status": "passed"}, {"label": "save", "status": "failed", "observed": "disabled"}], "failed")]:
            require(build_ui_button_smoke_receipt(mission_id="scratch", target="local-receipt-fixture", interactions=interactions)["status"] == expected,
                    "sv.ladder.receipt", "UI receipt reducer changed supplied evidence")
        return {"realCompilerRuns": 2, "realCommandRuns": 2, "laterCommandNotRun": True, "uiScope": "receipt aggregation only"}
    run("verification_receipts_and_failure_short_circuit", ["sv.ladder.receipt"], receipts)


def _check_sdk(root, repo, run):
    import subprocess
    import typing
    import types
    from .sdk_codegen import (SchemaSource, generated_bindings, generate_sdk_bindings, load_schema_sources,
                              render_python, render_typescript, validate_portable_schema, LossySchemaError)
    def generated():
        first = generated_bindings(repo)
        require(first == generated_bindings(repo), "sv.sdk.bindings", "generation nondeterministic")
        receipt = generate_sdk_bindings(repo, check=True)
        require(receipt["ok"], "sv.sdk.generation", "checked-in SDK bindings stale")
        sources = load_schema_sources(repo)
        reordered = tuple(SchemaSource(name=source.name, root_type=source.root_type, path=source.path,
            schema=dict(reversed(list(source.schema.items()))), sha256=source.sha256) for source in sources)
        require(render_python(sources) == render_python(reordered) and render_typescript(sources) == render_typescript(reordered),
                "sv.sdk.bindings", "object insertion order altered bindings")
        # Execute generated declarations and resolve annotations, not string searches.
        module = types.ModuleType("scratch_sdk_contracts")
        import sys
        sys.modules[module.__name__] = module
        try:
            python = next(content for path, content in first.items() if path.suffix == ".py")
            exec(compile(python, "scratch-sdk.py", "exec"), module.__dict__)
            annotations = 0
            for value in module.__dict__.values():
                if inspect.isclass(value) and value.__name__.startswith("Neyvia"):
                    hints = typing.get_type_hints(value, vars(module), vars(module))
                    require(all(annotation is not typing.Any for annotation in hints.values()), "sv.sdk.bindings", "unbounded Any replaced wire contract")
                    annotations += len(hints)
        finally:
            sys.modules.pop(module.__name__, None)
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        ts_path = repo / "sdk/typescript/src/generated/neyvia-contracts.ts"
        completed = subprocess.run(["node", str(repo / "node_modules/typescript/bin/tsc"), "--noEmit", "--skipLibCheck", "--strict", "--target", "ES2022", str(ts_path)],
                                   cwd=repo, capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "sv.sdk.bindings", "checked-in TypeScript types contain unresolved/invalid references: " + completed.stdout[:300])
        return {"files": receipt["outputs"], "resolvedPythonAnnotations": annotations, "checkedInTypescriptNoEmitCompile": True}
    run("sdk_generation_integrity_and_annotation_resolution", ["sv.sdk.bindings", "sv.sdk.generation"], generated)
    def portable():
        rejected = 0
        for schema, pointer, keyword in [({"oneOf": [{"type": "string"}, {"type": "integer"}]}, "/", "oneOf"),
            ({"const": 1.5}, "/const", "const"), ({"const": {"nested": True}}, "/const", "const"),
            ({"enum": ["safe", ["not", "portable"]]}, "/enum/1", "enum"), ({"enum": [None, {"not": "portable"}]}, "/enum/1", "enum")]:
            try:
                validate_portable_schema(schema)
            except LossySchemaError as exc:
                require(exc.pointer == pointer and exc.keyword == keyword, "sv.sdk.portable-schema", "lossy schema diagnostic lost pointer")
                rejected += 1
            else:
                raise ValueError("lossy schema accepted")
        source = SchemaSource(name="sample", root_type="Sample", path=Path("sample.json"), sha256="sample",
            schema={"type": "object", "additionalProperties": False,
                    "required": ["anything", "openObject", "closedEmptyObject", "enabled", "missing", "choice"],
                    "properties": {"anything": {}, "openObject": {"type": "object"},
                        "closedEmptyObject": {"type": "object", "additionalProperties": False},
                        "enabled": {"const": True}, "missing": {"const": None}, "choice": {"enum": [False, None, 7, "seven"]}}})
        validate_portable_schema(source.schema)
        target = root / "sdk-types"
        target.mkdir()
        python = render_python((source,))
        ts = render_typescript((source,))
        module = {"__name__": "scratch_portable"}
        exec(compile(python, "sample.py", "exec"), module)
        hints = typing.get_type_hints(module["Sample"], module, module, include_extras=True)
        unwrap = lambda key: typing.get_args(hints[key])[0]
        require(typing.get_args(unwrap("enabled")) == (True,) and typing.get_args(unwrap("missing")) == (None,) and
                typing.get_args(unwrap("choice")) == (False, None, 7, "seven"), "sv.sdk.portable-schema", "scalar literal type was weakened")
        require(unwrap("openObject") != unwrap("closedEmptyObject") and unwrap("anything") != unwrap("closedEmptyObject"),
                "sv.sdk.portable-schema", "empty/open/unconstrained objects collapsed")
        (target / "sample.ts").write_bytes(ts)
        (target / "check.ts").write_text('import type { Sample } from "./sample";\n'
            'const good: Sample = {anything: 8, openObject: {a: true}, closedEmptyObject: {}, enabled: true, missing: null, choice: "seven"};\n'
            '// @ts-expect-error closed empty object rejects arbitrary keys\nconst closed: Sample["closedEmptyObject"] = {a: 1};\n'
            '// @ts-expect-error boolean const is not arbitrary boolean\nconst enabled: Sample["enabled"] = false;\n'
            '// @ts-expect-error enum excludes other numbers\nconst choice: Sample["choice"] = 8;\n', encoding="utf-8")
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        command = ["node", str(repo / "node_modules/typescript/bin/tsc"), "--noEmit", "--skipLibCheck", "--strict", "--target", "ES2022", str(target / "check.ts")]
        completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "sv.sdk.portable-schema", "TypeScript semantic assignment checks failed: " + completed.stdout[:300])
        return {"rejectedLossySchemas": rejected, "pythonLiteralTypesVerified": True, "typescriptAssignmentsVerified": True}
    run("sdk_portable_schema_type_semantics", ["sv.sdk.portable-schema"], portable)
    def checkout_lf():
        import shutil
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        work = root / "sdk-checkout"
        work.mkdir()
        shutil.copy2(repo / ".gitattributes", work / ".gitattributes")
        outputs = generated_bindings(repo)
        for path, content in outputs.items():
            target = work / path
            target.parent.mkdir(parents=True)
            target.write_bytes(content)
        for command in [["git", "init", "-q"], ["git", "config", "user.email", "proof@example.test"],
                ["git", "config", "user.name", "Scratch proof"], ["git", "config", "core.autocrlf", "true"],
                ["git", "add", "."], ["git", "-c", "core.hooksPath=NUL", "commit", "-qm", "scratch"]]:
            subprocess.run(command, cwd=work, capture_output=True, text=True, check=True, timeout=10, **hidden_windows_subprocess_kwargs())
        for path in outputs:
            (work / path).unlink()
        subprocess.run(["git", "checkout", "--", *(path.as_posix() for path in outputs)], cwd=work, capture_output=True,
                       text=True, check=True, timeout=10, **hidden_windows_subprocess_kwargs())
        require(all((work / path).read_bytes() == content for path, content in outputs.items()),
                "sv.sdk.bindings", "autocrlf checkout changed canonical binding bytes")
        return {"autocrlfCheckoutByteIdentical": True}
    run("sdk_git_checkout_line_ending_integrity", ["sv.sdk.bindings"], checkout_lf)
    def cli_plans():
        import argparse
        import contextlib
        import io
        from zipfile import ZIP_DEFLATED
        from .sdk_cli import register_sdk_cli, run_sdk_cli
        from .sdk import build_application_surface, build_app_manifest, build_solantir_manifest, get_install_profile_catalog, plan_install_profile
        work = root / "sdk-cli"
        work.mkdir()
        parser = argparse.ArgumentParser()
        register_sdk_cli(parser.add_subparsers(dest="command"))
        def cli(arguments):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = run_sdk_cli(parser.parse_args(["neyvia-sdk", *arguments, "--root", str(work)]))
            return code, json.loads(output.getvalue())
        archive = work / "sample.nymod"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
            package.writestr("module/index.json", "{}")
            package.writestr("context/index.json", '{"summary":"local proof"}')
            package.writestr("sbom.spdx.json", '{"spdxVersion":"SPDX-2.3"}')
        archive.with_name(archive.name + ".sigstore.json").write_text("{}")
        publisher = "https://github.com/example/reference/.github/workflows/release.yml@refs/heads/main"
        manifest = {"schema": "neyvia.module-manifest/v1", "moduleId": "community.reference.local-proof", "version": "1.2.3", "name": "Local proof",
            "summary": "Nonexecuting local SDK proof", "publisher": {"id": "community.reference", "name": "Reference", "identity": publisher},
            "compatibility": {"moduleApi": "neyvia.module-api/v1", "neyvia": ">=0.1.0 <0.2.0", "platforms": ["windows-x86_64"]},
            "runtime": {"kind": "content-pack", "isolation": "bridge-only", "entrypoint": "module/index.json"},
            "package": {"archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "archiveBytes": archive.stat().st_size,
                "mediaType": "application/vnd.neyvia.module+zip", "sbomPath": "sbom.spdx.json", "license": "Apache-2.0"},
            "signature": {"scheme": "sigstore-cosign-bundle", "bundlePath": archive.name + ".sigstore.json", "bundleLocation": "detached",
                "payload": "canonical-manifest", "identity": publisher, "issuer": "https://token.actions.githubusercontent.com"},
            "permissions": [], "capabilities": [], "surfaces": [], "distribution": {"registryRef": "registry.example/neyvia/community.local-proof:1.2.3",
                "p2pEligible": False, "pinPolicy": "publisher-only"}, "update": {"channel": "stable", "rollback": True, "migrations": []},
            "context": {"summaryIndex": "context/index.json", "lazyResources": True, "maxBootstrapBytes": 8192}}
        (work / "manifest.json").write_text(json.dumps(manifest))
        code, validated = cli(["manifest-validate", "--manifest", "manifest.json"])
        require(code == 0 and validated["valid"] is True, "sv.sdk.plan-only", "valid local manifest rejected")
        code, plan = cli(["package-plan", "--manifest", "manifest.json", "--archive", archive.name])
        require(code == 0 and plan["canActivate"] is False and "publisher-trust" in plan["blockedBy"],
                "sv.sdk.plan-only", "untrusted package activated during plan")
        code, catalog = cli(["catalog"])
        require(code == 0 and catalog["moduleCount"] == 0, "sv.sdk.plan-only", "planning installed a package")
        surface = build_application_surface(surface_id="sdk.preview", title="SDK Preview", description="Local declared surface",
            permissions={"inspect": [], "launch": [], "control": []}, targets=[{"target_id": "web.local", "kind": "web", "platform": "web",
                "build": {"status": "not_required"}, "launch": {"kind": "url", "url": proof_text("http://127.0.0.1:48509")},
                "required_permissions": [], "readiness": {"receipt_id": "local-proof"}}])
        (work / "surface.json").write_text(json.dumps(surface))
        code, observed = cli(["surface-status", "--manifest", "surface.json", "--target-id", "web.local"])
        require(code == 0 and observed["status"] == "declared" and observed["targets"][0]["available"] is False, "sv.sdk.plan-only", "declared surface falsely available")
        code, launch = cli(["launch-plan", "--manifest", "surface.json", "--target-id", "web.local"])
        require(code == 0 and launch["status"] == "unavailable" and launch["approval"]["valid"] is False,
                "sv.sdk.plan-only", "surface plan invented availability or approval")
        (work / "invalid.json").write_text("[]")
        code, error = cli(["manifest-validate", "--manifest", "invalid.json"])
        require(code == 2 and error["schema"] == "neyvia.sdk-cli-error/v1" and error["error"] == "JSON input must be an object",
                "sv.sdk.plan-only", "nonobject input lacked stable rejection")
        app = build_app_manifest(app_id="local-proof", name="Local proof", description="Manifest roundtrip", endpoint=proof_text("http://127.0.0.1:48509/"),
            tasks=[{"task_id": "inspect", "label": "Inspect", "description": "Inspect fixture", "requires_approval": True}],
            context_surfaces=[{"surface_id": "catalog", "label": "Catalog", "description": "Local metadata", "access": "read"}],
            action_hooks=[{"hook_id": "write", "label": "Write", "description": "Controlled write", "mutability": "write"}])
        require(app["tasks"][0]["requires_approval"] and app["action_hooks"][0]["mutability"] == "write", "sv.sdk.manifest", "manifest authority changed")
        solantir = build_solantir_manifest(workspace_root=str(work), endpoint=proof_text("http://127.0.0.1:48509"))
        require(solantir["app_id"] == "solantir-terminal" and "delivery.receipt" in solantir["permissions"] and
                "intelligence-feeds" in {row["surface_id"] for row in solantir["context_surfaces"]} and
                "verify-feeds" in {row["hook_id"] for row in solantir["action_hooks"]} and solantir["ui_hints"]["verificationLoop"],
                "sv.sdk.manifest", "Solantir declarations lost feed/receipt behavior")
        profiles = get_install_profile_catalog(workspace_root=work)
        plan = plan_install_profile("recommended", workspace_root=work)
        require(profiles["summary"]["corePackages"] == 9 and plan["profileId"] == "recommended" and not plan["executionAllowed"],
                "sv.sdk.plan-only", "profile plan acquired install authority")
        return {"cliOperations": 7, "installedModules": 0, "launchAvailable": False, "profileExecutionAllowed": False}
    run("sdk_cli_and_manifest_nonexecuting_plans", ["sv.sdk.plan-only", "sv.sdk.manifest"], cli_plans)
    def http_transport():
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from .sdk import FluxioClient
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                requests.append({"path": self.path, "body": body, "cookie": self.headers.get("Cookie", "")})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if self.path == "/api/auth/login":
                    self.send_header("Set-Cookie", "fluxio_session=synthetic-proof; Path=/")
                    result = {"ok": True, "data": {"user": "scratch"}}
                elif self.path == "/api/backend":
                    result = {"ok": True, "data": {"receivedCommand": body["command"], "receiptId": "local-http-receipt"}}
                else:
                    result = []
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        server = ThreadingHTTPServer(("127.0.0.1", proof_port(48508)), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = FluxioClient(proof_text("http://127.0.0.1:48508"), username="scratch", password="synthetic-proof-only", timeout_seconds=5)
            routes = [{"role": "planner", "runtimeId": "hermes", "provider": "openai-codex", "model": "gpt-5.5"},
                      {"role": "executor", "runtimeId": "opencode", "provider": "openrouter", "model": "glm-5.2"}]
            first = client.runtime_lane_cycle("Inspect protocol", route_overrides=routes, app_context={"apps": [{"appId": "solantir"}]}, workspace_path=str(root))
            second = client.solantir_intelligence_cycle("Inspect protocol", workspace_path=str(root))
            third = client.record_delivery_receipt(mission_id="scratch", event_kind="verification.completed", event_message="Local protocol receipt",
                origin_runtime="hermes", origin_provider="openai-codex", origin_model="gpt-5.5")
            require(first["receivedCommand"] == second["receivedCommand"] == "run_runtime_lane_cycle_command" and
                    third["receivedCommand"] == "record_delivery_receipt_command", "sv.sdk.transport", "HTTP transport lost backend command identity")
            require(len(requests) == 4 and requests[0]["path"] == "/api/auth/login" and not requests[0]["cookie"] and
                    all(row["cookie"] == "fluxio_session=synthetic-proof" for row in requests[1:]), "sv.sdk.transport", "SDK login/cookie dispatch lost session")
            lane = requests[1]["body"]["payload"]
            solantir = requests[2]["body"]["payload"]
            delivery = requests[3]["body"]["payload"]
            require(lane["routeOverrides"] == routes and lane["appContext"]["apps"][0]["appId"] == "solantir" and
                    solantir["workspacePath"] == str(root) and solantir["routeOverrides"][0]["model"] == "gpt-5.5" and
                    solantir["routeOverrides"][1]["model"] == "glm-5.2" and solantir["routeOverrides"][2]["role"] == "verifier" and
                    solantir["appContext"]["apps"][0]["appId"] == "solantir-terminal" and solantir["appContext"]["deliveryReceipts"]["requested"] and
                    "Do not store raw social credentials" in solantir["instructions"] and delivery["missionId"] == "scratch" and
                    delivery["originModel"] == "gpt-5.5", "sv.sdk.transport", "transport changed routes, app context, authority or attribution")
            try:
                client._post("/invalid-json-object", {}, include_cookie=False)
            except ValueError:
                pass
            else:
                raise ValueError("nonobject backend reply trusted")
            return {"localEndpoint": proof_text("http://127.0.0.1:48508"), "httpRequests": 5, "loginCookieVerified": True,
                    "boundary": "real HTTP protocol fixture; provider engine was not invoked"}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    run("sdk_real_http_cookie_route_and_receipt_protocol", ["sv.sdk.transport"], http_transport)


def _check_support(root, run):
    from .support_bundle import build_redacted_support_bundle
    def bundles():
        work = root / "support"
        jobs = work / ".agent_control/harness_jobs"
        jobs.mkdir(parents=True)
        raw_secret = "sk-abcdefghijklmnopqrstuvwxyz"
        for index in range(3):
            identity = f"harness-job-{index}"
            (jobs / f"{identity}.json").write_text(json.dumps({"id": identity, "schema": "neyvia.harness_job.v1", "status": "blocked",
                "prompt": "private project text", "request": {"apiKey": raw_secret}, "error": "AuthError: password=hunter2",
                "logPath": str(jobs / f"{identity}.log"), "result": {"blockedReason": "provider_auth_expired", "providerId": "openai-codex"}}), encoding="utf-8")
            (jobs / f"{identity}.log").write_text(f"private log line {raw_secret}\nAuthError: password=hunter2\n", encoding="utf-8")
        archive = root / "support.zip"
        summary = build_redacted_support_bundle(work, archive, max_jobs=2)
        with ZipFile(archive) as package:
            data = b"\n".join(package.read(name) for name in package.namelist())
        require(summary["selectedHarnessJobs"] == 2 and all(value not in data for value in [raw_secret.encode(), b"hunter2", b"private project", b"private log line", str(work).encode()]),
                "sv.support.bundle", "archive leaked excluded input")
        for output, maximum, exception in [(archive, 2, FileExistsError), (root / "bad.zip", 0, ValueError)]:
            try:
                build_redacted_support_bundle(work, output, max_jobs=maximum)
            except exception:
                pass
            else:
                raise ValueError("overwrite or invalid max jobs accepted")
        # Real 3 MiB log: only bounded first/last metadata may be exported.
        (jobs / "harness-job-0.log").write_bytes(raw_secret.encode() + b"\n" + b"x" * (3 * 1024 * 1024) + b"\nTimeoutError: tail\n")
        large = root / "support-large.zip"
        build_redacted_support_bundle(work, large)
        with ZipFile(large) as package:
            logs = json.loads(package.read("logs/index.json"))["logs"]
        require(any(row.get("inspectionTruncated") and row["inspectedBytes"] == 2 * 1024 * 1024 and "sampleSha256" in row for row in logs),
                "sv.support.bundle", "large log did not stay bounded")
        # Corrupt bytes must remain absent; hostile structured identifiers fail before archive publication.
        (jobs / "harness-job-corrupt.json").write_text("{private-corrupt-secret", encoding="utf-8")
        corrupt = root / "support-corrupt.zip"
        build_redacted_support_bundle(work, corrupt)
        with ZipFile(corrupt) as package:
            require(b"private-corrupt-secret" not in b"".join(package.read(name) for name in package.namelist()), "sv.support.bundle", "corrupt receipt leaked")
        hostile = jobs / "harness-job-evil.json"
        hostile.write_text(json.dumps({"id": "harness-job-evil", "status": "blocked", "result": {"status": "blocked", "providerId": raw_secret}}))
        rejected = root / "support-rejected.zip"
        try:
            build_redacted_support_bundle(work, rejected)
        except RuntimeError:
            require(not rejected.exists(), "sv.support.bundle", "failed archive was published")
        else:
            raise ValueError("hostile identifier escaped safety gate")
        return {"archives": 3, "maxInspectedLogBytes": 2 * 1024 * 1024, "hostileIdentifierRejected": True}
    run("support_allowlist_corrupt_bounds_and_secret_rejection", ["sv.support.bundle"], bundles)
    def links():
        work = root / "support-links"
        jobs = work / ".agent_control/harness_jobs"
        jobs.mkdir(parents=True)
        outside = root / "outside-support"
        outside.mkdir()
        (outside / "receipt.json").write_text('{"secret":"outside private bytes"}')
        (outside / "job.log").write_text("outside private log bytes")
        from .file_links import link_or_copy
        receipt_kind = link_or_copy(outside / "receipt.json", jobs / "harness-job-linked.json")
        log_kind = link_or_copy(outside / "job.log", jobs / "harness-job-linked.log")
        archive = root / "support-links.zip"
        build_redacted_support_bundle(work, archive)
        with ZipFile(archive) as package:
            require(b"outside private" not in b"".join(package.read(name) for name in package.namelist()), "sv.support.bundle", "linked bytes were disclosed")
            job = json.loads(package.read("harness-jobs.json"))["jobs"][0]
            log = json.loads(package.read("logs/index.json"))["logs"][0]
            if receipt_kind in {"symlink", "hardlink"}:
                require(job["readState"] == receipt_kind,
                        "sv.support.bundle", "linked receipt refusal did not emit metadata")
            else:
                require(job.get("schema") != "unreadable",
                        "sv.support.bundle", "independent copied receipt was not inspected")
            if log_kind in {"symlink", "hardlink"}:
                require(log["refusedSymlink" if log_kind == "symlink" else "refusedHardlink"] is True,
                        "sv.support.bundle", "linked log refusal did not emit metadata")
            else:
                require(log["present"] and not log["rawContentIncluded"],
                        "sv.support.bundle", "copied log was not bounded/redacted")
        linked_work = root / "support-root-link"
        (linked_work / ".agent_control").mkdir(parents=True)
        root_kind = link_or_copy(outside, linked_work / ".agent_control/harness_jobs")
        root_archive = root / "support-root-links.zip"
        build_redacted_support_bundle(linked_work, root_archive)
        with ZipFile(root_archive) as package:
            health = json.loads(package.read("harness-jobs.json"))["health"]
            if root_kind == "symlink":
                require(health["jobsRootState"] == "refused-symlink" and health["totalReceiptCount"] == 0,
                        "sv.support.bundle", "linked root was followed")
            else:
                require(root_kind == "copy" and health["jobsRootState"] == "available"
                        and b"outside private" not in b"".join(package.read(name) for name in package.namelist()),
                        "sv.support.bundle", "independent directory fallback disclosed private bytes")
        # A public C: source and a D: destination exercise real EXDEV copy
        # fallback on unprivileged Windows; never mock a filesystem error.
        source = Path(__file__).resolve().parents[2] / "package.json"
        original = source.read_bytes()
        copied = root / "support-cross-volume-copy.json"
        copy_kind = link_or_copy(source, copied)
        require(copied.read_bytes() == original, "sv.support.bundle", "fallback changed source bytes")
        if copy_kind == "copy":
            copied.write_bytes(b"independent destination")
            require(source.read_bytes() == original, "sv.support.bundle", "copy changed its source")
        try:
            link_or_copy(source, copied)
        except FileExistsError:
            pass
        else:
            raise ValueError("link fallback overwrote an existing destination")
        return {"receiptMaterialization": receipt_kind, "logMaterialization": log_kind,
                "rootMaterialization": root_kind, "crossVolumeMaterialization": copy_kind,
                "sourcePreserved": True, "overwriteRefused": True, "privateBytesExcluded": True}
    run("support_file_and_root_symlink_refusal", ["sv.support.bundle"], links)
    def root_link():
        import subprocess
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        work = root / "support-junction-root"
        (work / ".agent_control").mkdir(parents=True)
        outside = root / "outside-junction"
        outside.mkdir()
        (outside / "harness-job-outside.json").write_text('{"id":"harness-job-outside","status":"blocked","prompt":"outside private content"}')
        linked = work / ".agent_control/harness_jobs"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 1314:
                raise
            # A junction exercises the same resolved external-root boundary without privileges.
            completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                cwd=root, capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
            require(completed.returncode == 0, "sv.support.bundle", "scratch junction creation failed")
        archive = root / "support-junction.zip"
        build_redacted_support_bundle(work, archive)
        with ZipFile(archive) as package:
            health = json.loads(package.read("harness-jobs.json"))["health"]
            require(health["jobsRootPresent"] is False and health["jobsRootState"] in {"refused-symlink", "refused-outside-workspace"} and
                    health["totalReceiptCount"] == 0 and b"outside private content" not in b"".join(package.read(name) for name in package.namelist()),
                    "sv.support.bundle", "external linked root disclosed content")
        return {"externalRootRefused": True, "readState": health["jobsRootState"]}
    run("support_external_linked_root_refusal", ["sv.support.bundle"], root_link)


def _check_performance(root, repo, run):
    # Import the existing host-owned evaluator, rather than any former test.
    import importlib.util
    from datetime import datetime, timedelta, timezone
    spec = importlib.util.spec_from_file_location("proofs_performance_host", repo / "scripts/verify_performance_budget.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = root / "performance"
    (work / "dist/assets").mkdir(parents=True)
    assets = work / "dist/assets"
    (assets / "entry.js").write_bytes(b"j" * 20)
    (assets / "lazy.js").write_bytes(b"l" * 10)
    (assets / "entry.css").write_bytes(b"c" * 15)
    (work / "dist/index.html").write_text('<script type="module" src="/assets/entry.js"></script><link rel="stylesheet" href="/assets/entry.css">')
    config = {"schema": "neyvia.performance-budgets.v1", "maxEvidenceAgeHours": 24,
        "evidenceLimits": {"minStartupSamples": 3, "maxSamplesPerMetric": 20, "maxCaptureDurationSeconds": 300},
        "build": {"initialJavascriptBytes": 25, "initialCssBytes": 20, "lazyChunkMaxBytes": 12},
        "runtime": {name: 100 for name in module.REQUIRED_RUNTIME_METRICS}}
    now = datetime.now(timezone.utc)
    def seal(payload):
        payload.pop("evidenceBinding", None)
        payload["evidenceBinding"] = {"schema": module.EVIDENCE_BINDING_SCHEMA, "algorithm": "sha256",
            "canonicalization": "json-sort-keys-compact-v1", "digest": module._evidence_digest(payload)}
        return payload
    sources = {"bootstrapPayloadBytes": "http-response-body-bytes-v1", "startupP95Ms": "spawn-to-http-readiness-v1",
        "memoryP95MiB": "windows-root-process", "cpuP95Percent": "windows-root-process",
        "networkInitialBytes": "same-origin-initial-http-response-body-bytes-v1", "batteryDrainPercentPerHour": "os-battery-telemetry"}
    def valid_payload():
        return seal({"schema": module.RUNTIME_SCHEMA, "recorderSchema": module.RECORDER_SCHEMA,
            "captureStartedAt": (now - timedelta(seconds=1)).isoformat(), "capturedAt": now.isoformat(),
            "buildFingerprint": module.measure_build(work / "dist")[2], "budgetConfigFingerprint": module.config_fingerprint(config),
            "metrics": {name: 1 for name in config["runtime"]}, "rawSamples": {name: [1., 1., 1.] for name in config["runtime"]},
            "metricEvidence": {name: {"status": "measured", "source": sources[name], "sampleCount": 3,
                "aggregation": "p95" if name in {"startupP95Ms", "memoryP95MiB", "cpuP95Percent"} else "maximum"} for name in config["runtime"]}})
    def evaluate(payload=None, custom_config=None):
        evidence = work / "runtime.json"
        if payload is not None:
            evidence.write_text(json.dumps(payload), encoding="utf-8")
        elif evidence.exists():
            evidence.unlink()
        return module.evaluate(config=custom_config or config, build_dir=work / "dist", runtime_evidence_path=evidence, now=now)
    def policy():
        valid = evaluate(valid_payload())
        require(valid["localBudgetStatus"] == "pass" and valid["status"] == "unproven" and not valid["promotionEligible"],
                "sv.performance.fail-closed", "local fixture rejected: " + json.dumps(valid["results"]))
        missing = evaluate()
        require(missing["runtimeEvidence"]["status"] == "RUNTIME_EVIDENCE_MISSING", "sv.performance.fail-closed", "missing evidence trusted")
        budget = json.loads(json.dumps(config))
        budget["build"]["initialJavascriptBytes"] = 1
        require(evaluate(valid_payload(), budget)["status"] == "fail", "sv.performance.fail-closed", "over-budget build accepted")
        mutations = [
            ("stale", lambda p: p.update(capturedAt=(now-timedelta(hours=25)).isoformat(), captureStartedAt=(now-timedelta(hours=25, seconds=1)).isoformat()), "RUNTIME_EVIDENCE_STALE"),
            ("future", lambda p: p.update(capturedAt=(now+timedelta(minutes=6)).isoformat(), captureStartedAt=(now+timedelta(minutes=6)-timedelta(seconds=1)).isoformat()), "RUNTIME_CAPTURE_IN_FUTURE"),
            ("build", lambda p: p.update(buildFingerprint="different"), "RUNTIME_BUILD_FINGERPRINT_MISMATCH"),
            ("recorder", lambda p: p.pop("recorderSchema"), "RUNTIME_RECORDER_SCHEMA_UNSUPPORTED"),
            ("config", lambda p: p.update(budgetConfigFingerprint="different"), "RUNTIME_CONFIG_FINGERPRINT_MISMATCH"),
        ]
        for label, mutate, expected in mutations:
            payload = valid_payload()
            mutate(payload)
            report = evaluate(seal(payload))
            require(report["runtimeEvidence"]["status"] == expected, "sv.performance.fail-closed", f"{label} evidence accepted")
        tampered = valid_payload()
        tampered["metrics"]["startupP95Ms"] = 0
        require(evaluate(tampered)["runtimeEvidence"]["status"] == "RUNTIME_EVIDENCE_DIGEST_MISMATCH", "sv.performance.fail-closed", "tampered digest trusted")
        for label, mutate, reason in [
            ("provenance", lambda p: p["metricEvidence"].pop("memoryP95MiB"), "RUNTIME_METRIC_EVIDENCE_MISSING"),
            ("samples", lambda p: p["metricEvidence"]["memoryP95MiB"].update(sampleCount=21), "RUNTIME_METRIC_SAMPLE_COUNT_OUT_OF_BOUNDS"),
            ("aggregate", lambda p: p["metrics"].update(memoryP95MiB=0), "RUNTIME_METRIC_AGGREGATE_MISMATCH")]:
            payload = valid_payload()
            mutate(payload)
            report = evaluate(seal(payload))
            metric = next(row for row in report["results"] if row["name"] == "memoryP95MiB")
            require(metric["status"] == "unproven" and metric["reason"] == reason, "sv.performance.fail-closed", f"{label} metric evidence trusted")
        for bad in [-1, float("nan"), float("inf")]:
            payload = valid_payload()
            payload["metrics"]["cpuP95Percent"] = bad
            payload["rawSamples"]["cpuP95Percent"] = [bad] * 3
            if math.isfinite(bad):
                seal(payload)
            require(evaluate(payload)["localBudgetStatus"] == "unproven", "sv.performance.fail-closed", "invalid runtime metric trusted")
        unmeasured = valid_payload()
        unmeasured["metricEvidence"]["batteryDrainPercentPerHour"] = {"status": "unproven", "reasonCode": "BATTERY_NOT_MEASURED", "sampleCount": 0}
        unmeasured["metrics"]["batteryDrainPercentPerHour"] = None
        unmeasured["rawSamples"]["batteryDrainPercentPerHour"] = []
        battery = next(row for row in evaluate(seal(unmeasured))["results"] if row["name"] == "batteryDrainPercentPerHour")
        require(battery["status"] == "unproven" and battery["reason"] == "BATTERY_NOT_MEASURED", "sv.performance.fail-closed", "unmeasured battery became trusted")
        for section, name in [("build", "initialCssBytes"), ("runtime", "cpuP95Percent")]:
            invalid = json.loads(json.dumps(config))
            invalid[section].pop(name)
            try:
                evaluate(custom_config=invalid)
            except ValueError:
                pass
            else:
                raise ValueError("missing required budget accepted")
        return {"syntheticReceiptAcceptanceOnly": True, "tamperAndInvalidSamplesRejected": True, "promotionEligible": False}
    run("performance_evidence_trust_and_metric_validation", ["sv.performance.fail-closed"], policy)
    def build_assets():
        manifest_dir = work / "dist/.vite"
        manifest_dir.mkdir()
        manifest = manifest_dir / "manifest.json"
        manifest.write_text(json.dumps({"index.html": {"file": "assets/entry.js", "isEntry": True, "imports": ["dependency"]},
            "dependency": {"file": "assets/lazy.js", "css": ["assets/entry.css"]}}))
        metrics = module.measure_build(work / "dist")[0]
        require(metrics["initialJavascriptBytes"] == 30 and metrics["initialCssBytes"] == 15, "sv.performance.fail-closed", "transitive asset bytes omitted")
        for records in [
                {"index.html": {"file": "assets/missing.js", "isEntry": True}},
                {"index.html": {"isEntry": True}}, {"index.html": {"file": "", "isEntry": True}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "imports": {"shared": True}}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "imports": [7]}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "css": "bad"}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "css": [7]}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "imports": ["missing"]}},
                {"index.html": {"file": "assets/entry.js", "isEntry": True, "imports": ["shared"]}, "shared": {}}]:
            manifest.write_text(json.dumps(records))
            require(evaluate()["results"][0]["status"] == "unproven", "sv.performance.fail-closed", "invalid manifest accepted")
        manifest.unlink()
        html = work / "dist/index.html"
        html.write_text('<script type=module src=/assets/entry.js></script><link rel=stylesheet href=/assets/entry.css>')
        require(module.measure_build(work / "dist")[0]["initialJavascriptBytes"] == 20, "sv.performance.fail-closed", "unquoted asset lost")
        for broken in ['<script src="/assets/missing.js"></script>', '<script src="/assets/entry.js"></script><img src="/assets/missing-logo.png">']:
            html.write_text(broken)
            require(evaluate()["localBudgetStatus"] == "unproven", "sv.performance.fail-closed", "missing asset accepted")
        return {"transitiveAssetsMeasured": True, "invalidAssetsRejected": True}
    run("performance_build_asset_graph", ["sv.performance.fail-closed"], build_assets)
    def diagnostics():
        import contextlib
        import io
        report = module.evaluate(config=config, build_dir=work / "missing-dist", runtime_evidence_path=work / "absent.json", now=now)
        require(report["summary"]["unproven"] == 9 and str(work) not in json.dumps(report), "sv.performance.fail-closed", "missing build gate leaked or failed open")
        redacted = module._redact_diagnostic(r'C:\Users\private\secret.txt C:/workspace/private.txt \\nas\share\secret.txt /volume1/Saclay/private /mnt/data/private /workspace/repo /opt/app /srv/service Bearer abc.def token=secret-value password="a quoted secret value"')
        require(all(value not in redacted for value in ["private", "Saclay", "abc.def", "secret-value", "quoted secret value", "/mnt/data", "/workspace/repo", "/opt/app", "/srv/service"]),
                "sv.performance.fail-closed", "diagnostic redactor exposed local paths or secret-shaped data")
        output = io.StringIO()
        missing = work / "private/missing-config.json"
        with contextlib.redirect_stdout(output):
            code = module.main(["--config", str(missing), "--build-dir", str(work / "dist"), "--runtime-evidence", str(work / "absent.json")])
        require(code == 2 and "PERFORMANCE_VERIFICATION_FAILED" in output.getvalue() and str(missing) not in output.getvalue(),
                "sv.performance.fail-closed", "CLI error has no stable redacted outcome")
        return {"missingBuildUnprovenMetrics": 9, "cliErrorCode": code, "diagnosticsRedacted": True}
    run("performance_missing_build_and_redacted_cli", ["sv.performance.fail-closed"], diagnostics)


def check_video_proposal(proposal, path):
    require(proposal.kind == "native_tool" and proposal.args.get("tool") == "video.digest" and
            proposal.args.get("arguments", {}).get("path") == path,
            "sv.video.route", "video evidence request was routed away from its exact source")
    return proposal


def check_sdk_request(client, request, path, payload, include_cookie):
    require(request.full_url == client.base_url + path and request.get_method() == "POST" and
            json.loads(request.data.decode()) == payload, "sv.sdk.transport", "SDK wire request changed destination or payload")
    expected = client._cookie if include_cookie else ""
    require((request.get_header("Cookie") or "") == expected, "sv.sdk.transport", "SDK request leaked or omitted session cookie")


def _check_video(root, run):
    import shutil
    import subprocess
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    def video():
        from .native_tools import NativeToolRegistry
        from .action_executor import HybridExecutionAdapter
        from .models import PlannedStep
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not shutil.which("ffprobe"):
            raise PermissionError("FFmpeg and FFprobe must be installed for video startup proof")
        work = root / "video"
        work.mkdir()
        source = work / "three-scenes.mp4"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        for color in ("red", "blue", "green"):
            command += ["-f", "lavfi", "-i", f"color=c={color}:s=640x360:d=1:r=24"]
        command += ["-f", "lavfi", "-i", "sine=frequency=880:duration=3:sample_rate=16000", "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-y", str(source)]
        completed = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=60, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "sv.video.digest", "scratch video generation failed: " + completed.stderr[:300])
        registry = NativeToolRegistry(work)
        inspected = registry.call("video.inspect", {"path": str(source)})
        digested = registry.call("video.digest", {"path": str(source), "maxFrames": 6, "maxSceneFrames": 4, "sceneThreshold": .1, "transcribe": "none", "timeoutSeconds": 60})
        require(inspected["ok"] and inspected["result"]["durationSeconds"] > 2.5 and inspected["result"]["video"]["width"] == 640 and
                inspected["result"]["audio"]["present"], "sv.video.metadata", "real video metadata sample failed")
        require(digested["ok"], "sv.video.digest", "real digest failed: " + str(digested.get("error")))
        digest = digested["result"]
        manifest = json.loads(Path(digest["manifestPath"]).read_text(encoding="utf-8"))
        require(digest["sampledFrameCount"] == 6 and 3 <= digest["frameCount"] < 6 and digest["audio"]["status"] == "extracted" and
                any(row["quality"]["selected"] is False for row in manifest["frames"]), "sv.video.digest", "near-duplicate frames were not removed or audio lost")
        adapter = HybridExecutionAdapter()
        policy = adapter.build_policy("builder")
        scope = adapter.prepare_scope(work, "scratch-video", requested_scope="direct")
        proposal = adapter.build_action_proposal(PlannedStep(step_id="video", title="Analyze video", description=f"Create model-readable video evidence for {source}"),
            "Review video storyboard and scene changes", work, [], "hermes", scope, policy)
        check_video_proposal(proposal, str(source))
        return {"sourceSha256": inspected["result"]["sha256"], "sampledFrames": 6, "selectedFrames": digest["frameCount"],
                "manifest": digest["manifestPath"], "plannerTool": proposal.args["tool"], "audioStatus": digest["audio"]["status"]}
    run("real_video_native_inspection_digest_and_planner_route", ["sv.video.metadata", "sv.video.digest", "sv.video.route"], video)


def _check_skill_writes(root, repo, run):
    from .web_backend import _create_codex_skill, _save_codex_skill_file
    from .skill_library import SkillLibrary
    from .skills import SkillRegistry
    def writes():
        workspace, second, home = root / "skill-writes" / "project", root / "skill-writes" / "second", root / "skill-writes" / "home"
        for directory in (workspace, second, home):
            directory.mkdir(parents=True)
        for directory in (workspace, second):
            control = directory / ".agent_control"
            control.mkdir()
            (control / "workspaces.json").write_text("{}", encoding="utf-8")
        created = _create_codex_skill({"name": "evidence-loop", "description": "Review observed evidence and preserve a useful receipt.", "scope": "project", "changeNote": "Create reviewed starting point."}, root=workspace, home_root=home)
        path = Path(created["path"])
        original = path.read_bytes()
        for payload in [{"name": "evidence-loop", "description": "Reject duplicate."}, {"name": "invalid-", "description": "Reject malformed ID."}]:
            try:
                _create_codex_skill(payload, root=workspace, home_root=home)
            except RuntimeError:
                pass
            else:
                raise ValueError("Invalid/duplicate creation unexpectedly succeeded")
        require(path.read_bytes() == original and not (workspace / ".codex/skills/invalid-").exists(), "sv.skills.create", "invalid creation changed existing content")
        evolution = original.decode().replace("Verify the result with realistic evidence", "Verify the result with realistic evidence and compare the prior receipt")
        saved = _save_codex_skill_file({"skillId": "evidence-loop", "path": str(path), "content": evolution, "changeNote": "Compare prior evidence."}, root=workspace, home_root=home)
        require(saved["revision"] == 1 and Path(saved["backupPath"]).read_bytes() == original, "sv.skills.save", "revision or backup evidence lost")
        before = path.read_bytes()
        before_history = Path(saved["evolutionReceiptPath"]).read_bytes()
        unchanged = _save_codex_skill_file({"path": str(path), "content": evolution}, root=workspace, home_root=home)
        require(not unchanged["changed"] and unchanged["revision"] == 1 and Path(saved["evolutionReceiptPath"]).read_bytes() == before_history, "sv.skills.save", "idempotent save manufactured history")
        try:
            _save_codex_skill_file({"path": str(path), "content": "# Missing frontmatter"}, root=workspace, home_root=home)
        except RuntimeError:
            pass
        else:
            raise ValueError("Invalid skill content unexpectedly saved")
        require(path.read_bytes() == before and Path(saved["evolutionReceiptPath"]).read_bytes() == before_history, "sv.skills.save", "invalid save changed prior bytes/history")
        library = SkillLibrary(workspace, SkillRegistry(repo / "config/skills.json"), home_root=home)
        library.record_usage("evidence-loop", "Evidence Loop", "step-local", "mission-local", True, "workspace")
        catalog = library.build_catalog()
        row = next(row for row in catalog["userInstalledSkills"] if row["skillId"] == "evidence-loop")
        summary = row["evolutionSummary"]
        require(summary["latestRevision"] == 1 and summary["revisionCount"] == 1 and summary["usageCount"] == 1 and summary["helpedCount"] == 1 and
                summary["history"][0]["note"] == "Compare prior evidence." and summary["history"][1]["kind"] == "creation" and summary["state"] == "learning",
                "sv.skills.catalog", "catalog evolution history/trust lost actual writes")
        personal = _create_codex_skill({"name": "personal-evidence", "description": "Carry reviewed workflow between isolated projects.", "scope": "personal"}, root=workspace, home_root=home)
        personal_path = Path(personal["path"])
        require(personal_path == home / ".codex/skills/personal-evidence/SKILL.md" and Path(personal["evolutionReceiptPath"]) == home / ".codex/.neyvia/skill_evolution_receipts.json", "sv.skills.create", "personal creation contaminated project history")
        second_catalog = SkillLibrary(second, SkillRegistry(repo / "config/skills.json"), home_root=home).build_catalog()
        require(any(row["skillId"] == "personal-evidence" and row["evolutionSummary"]["history"][0]["kind"] == "creation" for row in second_catalog["userInstalledSkills"]), "sv.skills.catalog", "personal history not visible across projects")
        version = _save_codex_skill_file({"path": str(personal_path), "content": personal_path.read_text().replace("Verify the result with realistic evidence", "Verify the result with realistic evidence and preserve usefulness")}, root=second, home_root=home)
        require(version["scope"] == "personal" and version["revision"] == 1, "sv.skills.save", "cross-project save lost personal revision")
        first_catalog = SkillLibrary(workspace, SkillRegistry(repo / "config/skills.json"), home_root=home).build_catalog()
        require(next(row for row in first_catalog["userInstalledSkills"] if row["skillId"] == "personal-evidence")["evolutionSummary"]["latestRevision"] == 1, "sv.skills.catalog", "personal revision not visible in first project")
        return {"projectRevision": saved["revision"], "personalRevision": version["revision"], "invalidWritesPreserved": True, "unchangedSavePreservedHistory": True, "crossProjectCatalogVisible": True, "boundary": "real helper writes and catalog projection under explicit scratch project/home roots"}
    run("skill_project_personal_creation_reviewed_save_and_catalog", ["sv.skills.create", "sv.skills.save", "sv.skills.catalog"], writes)


def _check_ui_graph(root, run):
    from dataclasses import replace
    from .ui_graph import Bounds, UiGraph, UiNode, compute_semantic_hash, diff_graphs, find_nodes, format_compact_delta
    from .ui_observer import flatten_playwright_ax, flatten_cdp_ax_tree
    from .ui_tools import UiToolSurface, register_with_native_registry, register_with_progressive_surface, describe_api_surface
    from .progressive_tools import ProgressiveToolSurface
    def resident():
        export = UiNode("export", "button", "Export CSV", states=("focused",), bounds=Bounds(10, 20, 100, 28), actions=("click",))
        email = UiNode("email", "textbox", "Email", actions=("fill",))
        require(compute_semantic_hash([export]) == compute_semantic_hash([replace(export, states=("hovered",))]), "sv.ui.semantic-identity", "focus/hover noise changed hash")
        require(compute_semantic_hash([export]) != compute_semantic_hash([replace(export, name="Save CSV")]), "sv.ui.semantic-identity", "semantic rename disappeared from hash")
        graph = UiGraph()
        graph.replace_nodes([export, email])
        old = graph.snapshot_nodes()
        graph.replace_nodes([replace(export, name="Save CSV"), UiNode("help", "link", "Help")])
        expected = {"export": "changed", "email": "removed", "help": "added"}
        require({row.node_id: row.kind for row in graph.last_delta} == expected and
                {row.node_id: row.kind for row in diff_graphs(old, graph.nodes)} == expected and graph.revision == 2,
                "sv.ui.delta", "actual graph replacement lost added/removed/changed transitions")
        require("email" in format_compact_delta(graph), "sv.ui.compact-delta", "removed ID absent from compact delta")
        nodes = [export, email, UiNode("docs", "link", "Export docs")]
        for query, ids in [('button[name~="Export"]', ["export"]), ('textbox[name="Email"]', ["email"]), ("Email", ["email"]), ("button[id=export]", ["export"]), ("missing", [])]:
            require([node.id for node in find_nodes(nodes, query)] == ids, "sv.ui.query", "query identity/filter mismatch")
        forged = [replace(export, name="Cancel")]
        try:
            check("sv.ui.query", forged, {"query": 'button[name~="Export"]', "limit": 20})
        except ValueError:
            pass
        else:
            raise ValueError("UI query contract accepted a nonmatching forged response")
        return {"revisions": graph.revision, "transitions": expected, "queryModes": 5, "forgedResponseRejected": True}
    run("ui_resident_semantic_graph_query_and_delta", ["sv.ui.semantic-identity", "sv.ui.graph-state", "sv.ui.delta", "sv.ui.query", "sv.ui.compact-delta"], resident)
    def compact():
        ui = UiToolSurface()
        try:
            ui.call("ui.observe", {"nodes": [{"id": "export", "role": "button", "name": "Export CSV", "actions": ["click"], "bounds": {"x": 10, "y": 20, "w": 100, "h": 28}}]})
            for name, args in [("ui.find", {"query": 'button[name~="Export"]'}), ("ui.ls", {"role": "button"}), ("ui.get", {"id": "export"}), ("ui.diff", {})]:
                result = ui.call(name, args)
                require(result["ok"] and "export" in result["text"] and result["treeOmitted"], "sv.ui.compact-result", "compact operation lost graph attribution")
            for gate in [{"ifRev": 0}, {"ifHash": "forged"}]:
                denied = ui.call("ui.do", {"id": "export", "action": "click", **gate})
                require(denied["status"] == "stale_state" and not denied["ok"], "sv.ui.action-gates", "stale action passed")
            unavailable = ui.call("ui.do", {"id": "export", "action": "click", "ifRev": ui.graph.revision, "ifHash": ui.graph.semantic_hash})
            require(not unavailable["ok"] and unavailable["status"] == "no_page", "sv.ui.action-gates", "no attached browser falsely completed action")
            crop = ui.call("ui.see", {"id": "export", "path": str(root / "ui" / "no-page.png")})
            require(crop["status"] in {"crop_failed", "no_clip"} and not crop["ok"], "sv.ui.compact-result", "missing browser falsely produced crop")
            return {"compactOperations": 4, "staleGates": 2, "missingPageStatus": unavailable["status"], "cropStatus": crop["status"], "boundary": "real injected graph and no-page failure; no rendered browser claim"}
        finally:
            ui.close()
    run("ui_compact_queries_and_stale_no_page_failure", ["sv.ui.compact-result", "sv.ui.action-gates"], compact)
    def accessibility():
        snapshot = {"role": "RootWebArea", "name": "Demo", "children": [{"role": "button", "name": "Open", "focused": True}, {"role": "presentation", "name": ""}, {"role": "textbox", "name": "Query", "value": "local"}]}
        nodes = flatten_playwright_ax(snapshot)
        require({node.role for node in nodes} >= {"button", "textbox"} and all(node.role != "presentation" for node in nodes), "sv.ui.ax-normalization", "Playwright AX roles missing")
        require(next(node for node in nodes if node.role == "textbox").value == "local", "sv.ui.ax-normalization", "AX editable value lost")
        ax = [{"nodeId": "1", "role": {"value": "button"}, "name": {"value": "Open"}, "properties": [{"name": "focused", "value": {"value": True}}]}, {"nodeId": "2", "parentId": "1", "role": {"value": "generic"}, "name": {"value": ""}}]
        cdp = flatten_cdp_ax_tree(ax)
        require(len(cdp) == 1 and cdp[0].name == "Open" and cdp[0].backend_ref == "1", "sv.ui.ax-normalization", "CDP normalization lost actionable source identity")
        before = {"1": UiNode("1", "button", "Before")}
        after = {"1": UiNode("1", "button", "After"), "2": UiNode("2", "link", "Added")}
        require({row.kind for row in diff_graphs(before, after)} == {"changed", "added"}, "sv.ui.delta", "normalization helper diff lost semantic transitions")
        return {"playwrightNormalizedNodes": len(nodes), "cdpNormalizedNodes": len(cdp), "boundary": "AX payload normalization; no browser capture"}
    run("ui_accessibility_payload_normalization", ["sv.ui.ax-normalization", "sv.ui.delta"], accessibility)
    def discovery():
        from .native_tools import NativeToolRegistry
        native = NativeToolRegistry(root / "ui" / "native")
        ui = UiToolSurface()
        try:
            normalized = accessibility()
            names = register_with_native_registry(native, ui)
            progressive = ProgressiveToolSurface()
            register_with_progressive_surface(progressive, ui)
            search = progressive.search("ui find graph", limit=10)
            require(any(row["name"] == "ui.find" for row in search) and all("inputSchema" not in row for row in search), "sv.ui.discovery", "progressive search omitted tool or exposed full schemas")
            description = progressive.describe("ui.find")
            require("query" in description["inputSchema"]["properties"], "sv.ui.discovery", "described UI query lacks input schema")
            api = describe_api_surface()
            require(api["compactOnly"] and "ui.find" in api["tools"], "sv.ui.discovery", "declared discovery no longer compact")
            return {"registeredNativeTools": len(names), "searchCompact": True, "describeSchemaPresent": True, "accessibility": normalized}
        finally:
            ui.close()
    run("ui_native_and_progressive_registration", ["sv.ui.discovery", "sv.ui.ax-normalization"], discovery)


def _check_safe_metadata(root, repo, run):
    def filters():
        import importlib.util
        from .runtime_auto_update import npm_package_of
        for command, expected in [("npm install -g @openai/codex@latest", "@openai/codex"),
            ("npm install -g --ignore-scripts opencode-ai@latest", "opencode-ai"), ("kimi upgrade", None)]:
            require(npm_package_of(command) == expected, "sv.update.package-parse", "package metadata parse failed")
        spec = importlib.util.spec_from_file_location("proofs_snapshot_filter_host", repo / "scripts/stage_neyvia_wip_snapshot.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in ["artifacts/screenshots/run/chrome-profile/Default/Network/Cookies", "artifacts/screenshots/run/Chrome-Profile/Default/Login Data",
            "artifacts/browser_profile/Default/Local State", "memory/private.md", "MEMORY.md"]:
            require(module._is_excluded(Path(path)), "sv.snapshot.private-filter", "private candidate path admitted")
        require(module._is_excluded(Path("proof/redacted-receipt/CHROME_PROOF.json")) is False, "sv.snapshot.private-filter", "redacted evidence candidate lost")
        return {"packageMetadataSamples": 3, "privatePathSamples": 5, "redactedEvidenceRetained": True,
                "boundary": "path metadata only; no files selected/copied, no NAS/snapshot/update executed"}
    run("safe_update_and_snapshot_path_metadata", ["sv.snapshot.private-filter", "sv.update.package-parse"], filters)
