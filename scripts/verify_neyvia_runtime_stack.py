"""Verify real runtime bindings and every declared agent-ready tool.

The verifier never promotes planned tools. It executes one bounded, read-only
or isolated operation per agent-ready manifest and reports blockers verbatim.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from grant_agent.capability_service import CapabilityService  # noqa: E402
from nas_runtime_doctor import inspect_commands  # noqa: E402


SAFE_OPERATIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "tool.wasmtime": (
        "marketplace.smoke-test-wasm",
        {"entrypoint": "{wasm}", "healthTarget": "health", "timeoutSeconds": 10},
    ),
    "tool.syft": (
        "marketplace.generate-sbom",
        {
            "path": "{fixture}",
            "outputPath": "{sbom}",
            "format": "spdx-json",
        },
    ),
    "tool.grype": (
        "marketplace.scan-vulnerabilities",
        {"sbomPath": "{sbom}", "failOn": "critical", "updateDatabase": False},
    ),
    "tool.windows-defender": (
        "marketplace.scan-malware",
        {"path": "{fixture}", "timeoutSeconds": 120},
    ),
    "tool.neyvia-mesh": ("mesh.status", {"refresh": False}),
    "tool.neyvia-nearby-send": ("nearby.compatibility", {}),
    "tool.neyvia-folder-sync": ("sync.compatibility", {}),
    "tool.neyvia-encrypted-chat": ("chat.compatibility", {}),
    "tool.neyvia-secret-broker": ("secret.compatibility", {}),
    "tool.neyvia-p2p-cache": ("cache.compatibility", {}),
    "tool.tesseract": ("ocr.version", {"timeoutSeconds": 20}),
    "tool.paddleocr": ("ocr.paddle-health", {"timeoutSeconds": 60}),
    "tool.glmocr": ("ocr.glm-health", {"timeoutSeconds": 90}),
    "tool.libreoffice": ("office.version", {"timeoutSeconds": 30}),
    "tool.pandoc": ("document.list-formats", {"timeoutSeconds": 30}),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minimal_health_wasm() -> bytes:
    """Return a tiny module exporting ``health()`` with no imports."""

    return bytes.fromhex(
        "0061736d01000000"
        "010401600000"
        "03020100"
        "070a01066865616c74680000"
        "0a040102000b"
    )


def _replace_paths(value: object, paths: dict[str, str]) -> object:
    if isinstance(value, str):
        return paths.get(value.strip("{}"), value)
    if isinstance(value, dict):
        return {key: _replace_paths(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_paths(item, paths) for item in value]
    return value


def _cosign_proof(temp_root: Path) -> dict[str, Any]:
    output = temp_root / "marketplace-signature-proof"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_neyvia_marketplace_activation.py"),
            "--output-root",
            str(output),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    summary_path = output / "proof-summary.json"
    passed = completed.returncode == 0 and summary_path.is_file()
    return {
        "ok": passed,
        "status": "completed" if passed else "failed",
        "returnCode": completed.returncode,
        "summary": (
            "A fresh package was signed, verified, activated, and discovered."
            if passed
            else (completed.stderr or completed.stdout)[-1200:]
        ),
    }


def verify_agent_ready_tools() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="neyvia-runtime-acceptance-") as temp:
        temp_root = Path(temp).resolve()
        fixture = temp_root / "fixture.txt"
        fixture.write_text(
            "Neyvia runtime acceptance fixture. No executable content.\n",
            encoding="utf-8",
        )
        wasm = temp_root / "health.wasm"
        wasm.write_bytes(_minimal_health_wasm())
        sbom = temp_root / "fixture.spdx.json"
        paths = {
            "fixture": str(fixture),
            "wasm": str(wasm),
            "sbom": str(sbom),
        }
        service = CapabilityService(temp_root)
        ready = [
            tool
            for tool in service.tool_manifests.tools.values()
            if tool.agent_ready
        ]
        rows: list[dict[str, Any]] = []
        for tool in ready:
            descriptor_rows = []
            for adapter_id in tool.adapters:
                descriptor = service.adapters.descriptor(adapter_id)
                available, reason = service.adapters.available(adapter_id)
                descriptor_rows.append(
                    {
                        "adapterId": adapter_id,
                        "available": available,
                        "supportsExecution": descriptor.supports_execution,
                        "reason": reason,
                    }
                )
            if tool.tool_id == "tool.cosign":
                result = _cosign_proof(temp_root)
                operation_id = "marketplace.verify-signature"
            else:
                selected = SAFE_OPERATIONS.get(tool.tool_id)
                if selected is None:
                    result = {
                        "ok": False,
                        "status": "missing_acceptance_operation",
                        "summary": "No bounded acceptance operation is declared.",
                    }
                    operation_id = ""
                else:
                    operation_id, raw_arguments = selected
                    operation = next(
                        item
                        for item in tool.operations
                        if item.operation_id == operation_id
                    )
                    arguments = _replace_paths(raw_arguments, paths)
                    try:
                        result = service.execute_tool_operation(
                            {
                                "toolId": tool.tool_id,
                                "operationId": operation_id,
                                "arguments": arguments,
                                "permissionMode": "workspace_safe",
                                "approvedPermissions": list(operation.permissions),
                            }
                        )
                    except Exception as exc:  # live dependency truth belongs in the report
                        result = {
                            "ok": False,
                            "status": "exception",
                            "summary": f"{type(exc).__name__}: {exc}",
                        }
            rows.append(
                {
                    "toolId": tool.tool_id,
                    "name": tool.name,
                    "operationId": operation_id,
                    "passed": bool(result.get("ok")),
                    "status": str(result.get("status") or ""),
                    "summary": str(result.get("summary") or "")[:1200],
                    "adapters": descriptor_rows,
                }
            )
        passed = sum(1 for row in rows if row["passed"])
        return {
            "declaredAgentReady": len(ready),
            "executed": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "allPassed": bool(rows) and passed == len(rows),
            "rows": rows,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Neyvia's honest runtime and agent-ready tool acceptance matrix.",
    )
    parser.add_argument("--extra-bin-dir", action="append", default=[])
    parser.add_argument("--skip-runtimes", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    runtime = None if args.skip_runtimes else inspect_commands(args.extra_bin_dir)
    tools = None if args.skip_tools else verify_agent_ready_tools()
    runtime_ok = True if runtime is None else bool(runtime.get("ready"))
    tools_ok = True if tools is None else bool(tools.get("allPassed"))
    report = {
        "schema": "neyvia.runtime-stack-acceptance/v1",
        "generatedAt": _utc_now(),
        "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
        "passed": runtime_ok and tools_ok,
        "runtime": runtime,
        "agentReadyTools": tools,
        "claimPolicy": (
            "Only a successful executed operation counts as working. Planned, "
            "installed-only, blocked, or catalogue-only tools are not promoted."
        ),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        target = args.report.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
