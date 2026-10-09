"""Contracts for authored argv tools and honest Computer Use replay receipts."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text
import json
import hashlib
from pathlib import Path
from .proofs_a_capabilities import require


def check_authored_save(result, store, manifest, *, approved=False):
    if result["status"] == "saved":
        require(approved and Path(result["path"]).is_relative_to(store.directory) and json.loads(Path(result["path"]).read_text(encoding="utf-8")) == result["tool"], "a.authored-tool", "authored manifest lacks approval or exact scoped persistence")
    elif not approved and result.get("validation", {}).get("valid"):
        require(result["status"] == "approval_required", "a.authored-tool", "manifest bypassed approval")


def check_authored_command(result, service, tool, arguments, **kwargs):
    from .tool_factory import render_templates
    if "argvCount" in result:
        require(result["argvCount"] == len(render_templates(tool["command"]["argvTemplate"], arguments)) + 1 and result["ok"] == (result["exitCode"] == 0 and not result["parseError"]) and result["toolId"] == tool["toolId"], "a.authored-argv", "command lost scalar argv count, identity or exit/parse truth")
        require(service.authored_tools.resolve_working_directory(tool["command"].get("workingDirectory")).is_relative_to(service.root), "a.authored-argv", "authored command escaped workspace")


def check_metrics(result, receipts):
    outcomes = [bool(row.get("pass")) and not bool(row.get("skipped")) for receipt in receipts for row in receipt.get("results", []) if isinstance(row, dict) and str(row.get("flow") or "")]
    require(result["repetitions"] == len(receipts) and result["flowObservations"] == len(outcomes) and result["flowSuccessRate"] == (round(sum(outcomes) / len(outcomes), 6) if outcomes else 0), "a.cu-metrics", "metrics lost repetitions or classified accuracy")
    require(result["compactReceiptBytes"] == sum(len(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")).encode()) for receipt in receipts) and result["structuredTreeOmitted"] == all(bool(receipt.get("treeOmitted")) for receipt in receipts), "a.cu-metrics", "compactness differs from observed receipt inputs")
    grouped = {}
    for receipt in receipts:
        for row in receipt.get("results", []):
            if isinstance(row, dict) and row.get("flow"):
                grouped.setdefault(str(row["flow"]), []).append(bool(row.get("pass")) and not bool(row.get("skipped")))
    agreement = round(sum(len(set(values)) <= 1 for values in grouped.values()) / len(grouped), 6) if grouped else 0
    require(result["deterministicAgreement"] == agreement and result["liveReceiptCount"] == sum(str(row.get("baseUrl") or "").startswith(("http://", "https://")) for row in receipts), "a.cu-metrics", "agreement or declared URL-source count differs from receipt inputs")
    if all(isinstance(row.get("durationMs"), (int, float)) and row["durationMs"] >= 0 for row in receipts):
        import math
        durations = sorted(row["durationMs"] for row in receipts)
        p95 = round(durations[max(0, math.ceil(len(durations) * .95) - 1)], 3) if durations else 0
        require(result["latency"]["p95Ms"] == p95, "a.cu-metrics", "latency percentile differs from classified direct-duration inputs")


def check_twin_run(result, service, spec_id):
    if result["evidenceMode"] == "replay":
        require(result["liveProof"] is False and result["comparison"]["comparativeClaimAllowed"] is False, "a.cu-replay", "recorded evidence became live proof")
    require(json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8")) == {key: value for key, value in result.items() if key != "receiptPath"}, "a.cu-replay", "twin receipt differs from durable record")


def check_dispatch(result, service, spec_id, **kwargs):
    job = result["job"]
    require(result["nasExecutionAllowed"] is False and job["payload"]["allowNasFallback"] is False and job["jobKind"] == "browser_verify" and job["payload"]["runner"] == "computer_use_twin" and isinstance(job["payload"]["twinSpec"], dict) and "computer.use.isolated" in result["requiredCapabilities"], "a.cu-portable", "dispatch lost isolation or allowed NAS fallback")


def check_worker(result, payload, *, root):
    if "computerUseTwin" in result:
        require(result["returnCode"] == (0 if result["computerUseTwin"]["status"] == "passed" else 1) and result["artifacts"][0]["kind"] == "computer_use_twin_receipt" and Path(result["artifacts"][0]["path"]).resolve().is_relative_to(Path(root).resolve()), "a.cu-portable", "worker used controller paths or fabricated return code")


def check_verification(result, service, payload):
    if not payload.get("approved"):
        require(result["status"] == "approval_required", "a.cu-verifier", "verification ran without approval")
    elif "claims" in result:
        require(result["claims"]["functionalChangeVerified"] == (result["status"] == "passed" and result["liveProof"]) and (result["evidenceMode"] != "replay" or not result["liveProof"] and not result["claims"]["functionalChangeVerified"] and not result["claims"]["comparisonAllowed"]), "a.cu-verifier", "replay earned live verification authority")


def check_tool_manifest(result, cls, payload):
    require(result.agent_ready == (result.state == "verified" and result.health_status == "healthy" and bool(result.package_sha256) and bool(result.operations)), "a.tool-readiness", "tool contract readiness lacks health/hash/typed operation evidence")
    if result.tool_id == "tool.pandoc" and result.metadata.get("defaultReferenceDoc"):
        from zipfile import ZipFile
        from xml.etree import ElementTree
        path = Path(__file__).resolve().parents[2] / result.metadata["defaultReferenceDoc"]
        require(path.resolve().is_relative_to(Path(__file__).resolve().parents[2]) and hashlib.sha256(path.read_bytes()).hexdigest() == result.metadata["defaultReferenceDocSha256"], "a.tool-reference", "Pandoc default reference escaped repo or changed pinned bytes")
        with ZipFile(path) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml")); styles = ElementTree.fromstring(archive.read("word/styles.xml"))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        size = document.find(".//" + ns + "pgSz"); margins = document.find(".//" + ns + "pgMar")
        require(size is not None and size.get(ns + "w") == "12240" and size.get(ns + "h") == "15840" and margins is not None and all(margins.get(ns + side) == "1440" for side in ["top", "right", "bottom", "left"]) and {"Heading1", "Table", "Compact"} <= {node.get(ns + "styleId") for node in styles.findall(ns + "style")} and styles.find(".//" + ns + "keepLines") is not None, "a.tool-reference", "pinned Word reference lost page geometry or document styles")


def check_tool_snapshot(result, registry, *, include_operations=False):
    require(result["summary"]["tools"] == len(registry.tools) and result["summary"]["nativeCapabilities"] == len(registry.native_capabilities) and result["summary"]["typedOperations"] == sum(len(tool.operations) for tool in registry.tools.values()) and result["operationsDeferred"] == (not include_operations), "a.tool-readiness", "tool inventory count or progressive operation boundary differs")
    require(all(row["executionReady"] is False or row["readiness"]["executionReadinessEvaluated"] and row["readiness"]["runtimeEvidence"]["runtimeIdentityVerified"] for row in result["tools"]), "a.tool-readiness", "execution readiness came from pin metadata without current runtime identity")


def check_tool_search(result, registry, query, **kwargs):
    require(result["summary"]["operationsDeferred"] and all("operations" not in row and row["toolId"] in registry.tools for row in result["results"]), "a.tool-readiness", "tool search eagerly expanded operations or invented a tool")


def check_operation(result, service, payload):
    if result.get("ok"):
        require(result["inputValidation"]["valid"] and result["outputValidation"]["valid"] and result["toolReceipt"]["packageSha256"] == service.tool_manifests.tools[result["toolId"]].package_sha256, "a.tool-typed", "successful operation skipped typed validation or pinned tool identity")
    operation = result.get("operationId")
    if operation in {"chat.compatibility", "secret.compatibility", "cache.provider-status"} and result.get("ok"):
        forbidden = {"credentialsPath", "accessToken", "sessionEnvRef", "appDataDir", "heartbeatKeyHash", "endpointId", "ticket"}
        def clean(value):
            return (not forbidden.intersection(value) and all(clean(child) for child in value.values())) if isinstance(value, dict) else all(clean(child) for child in value) if isinstance(value, list) else True
        require(clean(result["result"]), "a.tool-private", "typed compatibility exposed private paths, tokens, endpoints or tickets")
        flags = {"chat.compatibility": ["tokensExposed", "credentialPathsExposed"], "secret.compatibility": ["sessionKeysExposed", "itemIdsExposed", "secretValuesExposed"], "cache.provider-status": ["endpointIdsExposed", "ticketsExposed"]}[operation]
        require(all(result["result"][field] is False for field in flags) and (operation != "chat.compatibility" or result["result"]["accounts"]["credentialsExposed"] is False), "a.tool-private", "typed compatibility explicitly exposed private values")


def check_adapter_private(result, registry, *args, **kwargs):
    if "session" in result:
        require("heartbeatKeyHash" not in result["session"], "a.adapter-session", "public session exposed heartbeat verifier hash")


def check_pdf(result, registry, adapter_id, arguments=None):
    arguments = arguments or {}
    if adapter_id == "pdf.pdftotext" and result.get("ok"):
        data = result["result"]
        require(data["engine"] == "poppler-pdftotext" and len(data["text"]) <= int(arguments.get("maxChars", 1000000)) and data["truncated"] == (data["characterCount"] > len(data["text"])) and Path(data["sourcePath"]).is_file(), "a.pdf-bounded", "real PDF handler lost selected source or text bound")
    if adapter_id == "device.android" and arguments.get("operation") in {"tap", "swipe", "input_text", "keyevent", "install", "uninstall"} and not arguments.get("approved") and registry.descriptor(adapter_id).available:
        require(not result["ok"] and result["status"] == "approval_required", "a.android-approval", "device mutation ran without approval")


def check_direct_path(result, registry, value):
    require(result.is_relative_to(registry.root) and result.exists(), "a.tool-workspace", "direct marketplace operation escaped active workspace")


def check_benchmark(result, service, payload=None):
    require(result["search"]["status"] == ("pass" if result["search"]["p95Ms"] <= result["search"]["budgetP95Ms"] else "fail") and result["tenXAcceptance"]["baselineRequired"] is True and result["telemetry"]["schema"] == "neyvia.capability_telemetry.v1", "a.capability-benchmark", "budget status or ten-times baseline requirement was invented")


def self_check(scratch):
    from .capability_service import CapabilityService
    from .computer_use_twin import ComputerUseTwinService, summarize_cu_receipts, execute_cluster_twin_job
    from .computer_use_verifier import ComputerUseVerifierService
    root = scratch / "capability-tools"; root.mkdir()
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    service = CapabilityService(root)
    from .tool_manifest_registry import ToolManifest, ToolManifestRegistry
    registry = ToolManifestRegistry(Path(__file__).resolve().parents[2] / "config/tool_suite_lock.json")
    inventory = registry.snapshot()
    require(inventory["summary"]["tools"] >= 40 and inventory["summary"]["nativeCapabilities"] == 9 and inventory["summary"]["typedOperations"] >= 7 and inventory["summary"]["verified"] >= 10 and inventory["summary"]["agentReady"] >= 10 and inventory["operationsDeferred"], "a.tool-readiness", "pinned inventory lost declared breadth or deferred operations")
    require(registry.describe("tool.tesseract")["selectedVersion"] == "5.5.2" and registry.describe("tool.tesseract")["metadata"]["selectionRole"] == "emergency-fallback" and registry.describe("tool.paddleocr")["selectedVersion"] == "3.7.0" and registry.describe("tool.paddleocr")["agentReady"] and not registry.describe("tool.poppler")["agentReady"] and registry.describe("tool.pandoc")["agentReady"] and registry.describe("tool.libreoffice")["agentReady"], "a.tool-readiness", "selected pins or declared contract-readiness changed")
    catalog = json.loads(service.registry.catalog_path.read_text())
    pack_ids = [row["packId"] for row in catalog["packs"]]
    capability_ids = [row["capabilityId"] for pack in catalog["packs"] for row in pack["capabilities"]]
    require(len(pack_ids) == len(set(pack_ids)) and len(capability_ids) == len(set(capability_ids)), "a.tool-readiness", "default catalog contains duplicate declared identities")
    catalog_ids = set(capability_ids)
    require(catalog_ids <= {capability for row in inventory["tools"] for capability in row["capabilities"]} | {row["capabilityId"] for row in inventory["nativeCapabilities"]}, "a.tool-readiness", "catalog capability has no external/native tool owner")
    sample = registry.describe("tool.pandoc"); sample.pop("readiness", None)
    invalid = {**sample, "packageSha256": ""}
    for payload, detail in [(invalid, "packageSha256"), ({**sample, "metadata": {"apiKey": "empty-fixture-marker"}}, "secret")]:
        try:
            ToolManifest.from_payload(payload)
        except ValueError as error:
            require(detail in str(error), "a.tool-readiness", "malformed tool manifest rejected for wrong reason")
        else:
            require(False, "a.tool-readiness", "malformed tool manifest entered inventory")
    snapshot = service.snapshot(); search = service.search_tool_suite({"query": "semantic document conversion", "agentReadyOnly": True})
    require(snapshot["toolSuite"]["summary"]["tools"] >= 40 and snapshot["summary"]["selectedTools"] == snapshot["toolSuite"]["summary"]["tools"] and snapshot["summary"]["agentReadyTools"] >= 10 and search["results"][0]["toolId"] == "tool.pandoc" and search["results"][0]["agentReady"] and "operations" not in search["results"][0] and search["summary"]["operationsDeferred"], "a.tool-readiness", "service lost honest pinned readiness or deferred tool search")
    benchmark = service.benchmark({"iterations": 12, "warmups": 2})
    require(benchmark["schema"] == "neyvia.capability_benchmark.v1" and benchmark["search"]["status"] == "pass" and benchmark["search"]["p95Ms"] <= benchmark["search"]["budgetP95Ms"] and benchmark["tenXAcceptance"]["baselineRequired"] and benchmark["telemetry"]["schema"] == "neyvia.capability_telemetry.v1", "a.capability-benchmark", "benchmark lost bounded search or baseline claim policy")
    # Construct a genuine two-page PDF for the installed Poppler executable.
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>", b"", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index, word in [(3, b"one"), (5, b"two")]:
        stream = b"BT /F1 12 Tf 50 750 Td (Page " + word + b") Tj ET"
        objects[index] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    document = bytearray(b"%PDF-1.4\n"); offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(document)); document.extend(str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(document); document.extend(b"xref\n0 8\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010} 00000 n \n".encode())
    document.extend(f"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    source = root / "source.pdf"; source.write_bytes(document)
    extracted = service.adapters.execute("pdf.pdftotext", {"path": str(source), "firstPage": 1, "lastPage": 2, "maxChars": 1000})
    require(extracted["ok"] and extracted["status"] == "completed" and extracted["result"]["pageCountExtracted"] == 2 and extracted["result"]["text"].startswith("Page one") and extracted["result"]["engine"] == "poppler-pdftotext", "a.pdf-bounded", "installed Poppler failed bounded genuine two-page extraction")
    from .capability_contracts import AdapterDescriptor
    import sys
    service.adapters.register(AdapterDescriptor(adapter_id="device.android", label="Nonexecuting Android approval fixture", kind="external_executable", available=True, executable=sys.executable, supports_execution=True), service.adapters._execute_android)
    android = service.adapters.execute("device.android", {"operation": "tap", "x": 10, "y": 20})
    require(not android["ok"] and android["status"] == "approval_required" and android["result"]["requiredPermission"] == "external.side_effect", "a.android-approval", "tap passed without explicit approval")
    outside = scratch / "outside-marketplace"; outside.mkdir()
    service.adapters.register(AdapterDescriptor(adapter_id="marketplace.syft", label="Nonexecuting workspace-boundary fixture", kind="external_executable", available=True, executable=sys.executable, supports_execution=True), service.adapters._execute_marketplace_syft)
    outside_result = service.adapters.execute("marketplace.syft", {"operation": "generate_sbom", "path": str(outside), "outputPath": str(root / "outside.spdx.json")})
    require(not outside_result["ok"] and outside_result["status"] == "failed" and "limited to the active workspace" in outside_result["result"]["error"], "a.tool-workspace", "direct handler invoked an executable before rejecting outside workspace")
    blocked_session = service.register_adapter_session({"adapterId": "device.apple-remote", "transport": "remote_runner"})
    require(blocked_session["status"] == "approval_required", "a.adapter-session", "external session entered without approval")
    for private in [{"token": "empty-fixture-marker"}, {"metadata": {"credentials": {"apiKey": "empty-fixture-marker"}}}]:
        try:
            service.register_adapter_session({"adapterId": "device.apple-remote", "transport": "remote_runner", "approved": True, **private})
        except ValueError:
            pass
        else:
            require(False, "a.adapter-session", "secret-shaped session fields were persisted")
    connected = service.register_adapter_session({"adapterId": "device.apple-remote", "label": "Scratch remote runner", "transport": "remote_runner", "endpoint": "runner://scratch", "authRef": "credential://reference-only", "capabilities": ["xcode.build", "simulator.run"], "grantedPermissions": ["artifact.read", "artifact.write"], "approved": True})
    descriptor = service.adapters.descriptor("device.apple-remote")
    require(connected["status"] == "connected" and "heartbeatKeyHash" not in connected["session"] and descriptor.available and not descriptor.supports_execution, "a.adapter-session", "session registration implied execution or exposed verifier hash")
    try:
        service.heartbeat_adapter_session({"sessionId": connected["session"]["sessionId"], "heartbeatKey": "wrong-key"})
    except PermissionError:
        pass
    else:
        require(False, "a.adapter-session", "wrong heartbeat secret accepted")
    heartbeat = service.heartbeat_adapter_session({"sessionId": connected["session"]["sessionId"], "heartbeatKey": connected["heartbeatKey"]})
    refused_disconnect = service.disconnect_adapter_session({"sessionId": connected["session"]["sessionId"]})
    disconnected = service.disconnect_adapter_session({"sessionId": connected["session"]["sessionId"], "approved": True})
    require(heartbeat["status"] == "connected" and refused_disconnect["status"] == "approval_required" and disconnected["status"] == "disconnected", "a.adapter-session", "heartbeat/disconnect lifecycle lost identity or approval")
    for tool, operation, checks in [("tool.neyvia-encrypted-chat", "chat.compatibility", ["tokensExposed", "credentialPathsExposed"]), ("tool.neyvia-secret-broker", "secret.compatibility", ["sessionKeysExposed", "itemIdsExposed", "secretValuesExposed"]), ("tool.neyvia-p2p-cache", "cache.provider-status", ["active", "endpointIdsExposed", "ticketsExposed"])]:
        output = service.execute_tool_operation({"toolId": tool, "operationId": operation, "arguments": {}})
        require(output["ok"] and output["inputValidation"]["valid"] and output["outputValidation"]["valid"] and all(output["result"][key] is False for key in checks), "a.tool-private", "typed compatibility exposed private state")
        if operation == "chat.compatibility":
            require(output["result"]["accounts"]["credentialsExposed"] is False, "a.tool-private", "chat account projection exposed credentials")
    cache = service.execute_tool_operation({"toolId": "tool.neyvia-p2p-cache", "operationId": "cache.compatibility", "arguments": {}})
    require(cache["ok"] and cache["inputValidation"]["valid"] and cache["outputValidation"]["valid"] and all(cache["result"]["limitations"][key] for key in ["localCasImplemented", "irohSidecarImplemented", "remoteFetchImplemented"]) and cache["result"]["limitations"]["remoteFetchConfigured"] is False and cache["result"]["policy"]["publicDiscoveryDefault"] is False, "a.tool-typed", "cache implementation was confused with configured remote discovery")
    adapted = service.adapt_authored_tool({"sourceType": "mcp", "adapterId": "browser.firefox-bidi", "source": {"name": "inspect_page", "description": "Inspect a page through an external bridge.", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}}}})
    blocked = service.save_authored_tool({"tool": adapted["manifest"]}); saved = service.save_authored_tool({"tool": adapted["manifest"], "approved": True}); described = service.describe_authored_tool(adapted["manifest"]["toolId"])
    require(adapted["status"] == "draft" and adapted["validation"]["valid"] and blocked["status"] == "approval_required" and saved["status"] == "saved" and described["kind"] == "delegated" and described["available"] is False and service.search({"query": "inspect page external bridge"})["authoredTools"][0]["toolId"] == described["toolId"], "a.authored-tool", "adaptation lost validation, approval or discovery")
    command = {"schema": "neyvia.authored_tool.v1", "toolId": "custom.json-echo", "name": "JSON echo", "description": "Emit a scalar as JSON using discovered Python", "kind": "command", "version": "1.0.0", "permissions": ["process.execute"], "inputSchema": {"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}}, "outputSchema": {"type": "object"}, "command": {"adapterId": "runtime.python", "argvTemplate": ["-c", "import json,sys; print(json.dumps({'value':sys.argv[1]}))", "{{input.value}}"], "workingDirectory": ".", "timeoutSeconds": 15, "outputParser": "json"}}
    require(service.save_authored_tool({"tool": command, "approved": True})["status"] == "saved", "a.authored-tool", "command manifest did not save")
    value = "hello; this is data, not shell"
    result = service.execute_authored_tool({"toolId": command["toolId"], "arguments": {"value": value}})
    require(result["ok"] and result["output"] == {"value": value} and result["argvCount"] == 4 and result["telemetry"]["schema"] == "neyvia.capability_telemetry.v1", "a.authored-argv", "actual Python command split scalar shell characters or lost typed output")
    receipt = {"status": "passed", "pass": True, "baseUrl": proof_text("http://127.0.0.1:48462"), "durationMs": 120, "treeOmitted": True, "results": [{"flow": name, "pass": True, "skipped": False} for name in ["control_room", "surface_navigation"]]}
    metrics = summarize_cu_receipts([receipt, dict(receipt)])
    require(metrics["flowSuccessRate"] == metrics["deterministicAgreement"] == 1 and metrics["latency"]["p95Ms"] == 120 and metrics["structuredTreeOmitted"] and metrics["liveReceiptCount"] == 2, "a.cu-metrics", "typed metrics lost agreement, latency or declared URL-source count")
    replay = root / "recorded-cu.json"; replay.write_text(json.dumps(receipt))
    twin = ComputerUseTwinService(root)
    saved = twin.save_spec({"name": "Recorded local semantics", "mode": "replay", "flows": ["control_room"], "replayReceiptPath": str(replay)}, approved=True)
    result = twin.run(saved["spec"]["specId"])
    require(result["schema"] == "neyvia.computer_use_twin_run.v1" and result["evidenceMode"] == "replay" and not result["liveProof"] and not result["comparison"]["comparativeClaimAllowed"], "a.cu-replay", "replay was mislabeled live")
    live = twin.save_spec({"name": "Queued isolated candidate", "mode": "live", "baseUrl": proof_text("http://127.0.0.1:48462"), "flows": ["control_room"]}, approved=True)
    dispatched = twin.dispatch(live["spec"]["specId"], preferred_host="PROOFS-SCRATCH-HOST")
    require(dispatched["status"] == "queued" and dispatched["job"]["preferredHost"] == "PROOFS-SCRATCH-HOST", "a.cu-portable", "worker request lost queued explicit host")
    verifier = ComputerUseVerifierService(root)
    refused = verifier.verify({"mode": "replay", "flows": ["control_room"], "replayReceiptPath": str(replay)})
    verified = verifier.verify({"changeId": "scratch-change", "mode": "replay", "flows": ["control_room"], "replayReceiptPath": str(replay), "approved": True})
    require(refused["status"] == "approval_required" and verified["schema"] == "neyvia.computer_use_verification.v1" and verified["status"] == "failed" and verified["liveProof"] is False and verified["claims"]["functionalChangeVerified"] is False and verified["claims"]["comparisonAllowed"] is False, "a.cu-verifier", "primary facade admitted replay as live proof")
    portable = {"runner": "computer_use_twin", "twinSpec": {**saved["spec"], "replayReceiptPath": "controller-only-path.json", "thresholds": {**saved["spec"]["thresholds"], "requireLiveProof": False}}, "replayReceipt": receipt}
    worker = execute_cluster_twin_job(portable, root=root / "worker")
    require(worker["status"] == "completed" and worker["returnCode"] == 0 and worker["computerUseTwin"]["evidenceMode"] == "replay" and worker["artifacts"][0]["kind"] == "computer_use_twin_receipt", "a.cu-portable", "portable replay depended on missing controller file")
