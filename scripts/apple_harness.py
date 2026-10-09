"""Manual-first Apple commands through the worktree's production Neyvia harness.

Transport fallback when the host does not expose its attached MCP server.
Does not start cloud runs, install runtimes, publish, or contact live services.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_workspace_tools import WorkspaceTools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / ".agent_control/apple/runtime")
    parser.add_argument("--tool")
    parser.add_argument("--args-file", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--prove", action="store_true")
    parser.add_argument("--adverse", action="store_true", help="C7 cases on disposable copies of real retained artifacts")
    parser.add_argument("--render", action="store_true", help="C7 real authenticated headless UI journey")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    service = WorkspaceTools(args.root.resolve())
    log = []
    def call(tool, arguments):
        value = service.call(tool.removeprefix("neyvia."), arguments)
        log.append({"tool": tool, "arguments": arguments, "result": value})
        return value
    try:
        loaded = call("manual.load", {"id": "mobile-studio", "chapter": "apple-targets", "maxChars": 512})
        if not loaded.get("ok"):
            raise RuntimeError("Executable Apple manual failed to load")
        if args.render:
            if not args.project: parser.error("--render requires --project")
            from grant_agent.edge_fixture_mobile import run_apple_preview
            log.append({"tool":"C7.apple-preview", "arguments":{"project":str(args.project.resolve())},
                        "result":run_apple_preview(args.project.resolve())})
        elif args.adverse:
            if not args.project: parser.error("--adverse requires --project")
            from grant_agent.edge_fixture_mobile import run_apple_artifacts
            import uuid
            log.append({"tool":"C7.apple-artifacts", "arguments":{"project":str(args.project.resolve())},
                        "result":{"cases":run_apple_artifacts(args.root.resolve()/('adverse_'+uuid.uuid4().hex[:8]),args.project.resolve())}})
        elif args.prove:
            if not args.project:
                parser.error("--prove requires --project")
            project = str(args.project.resolve())
            for target in ("ios", "macos", "ipados"):
                outcome = call("manual.run", {"id": "mobile-studio", "chapter": "apple-targets", "procedure": "build-verify-preview-" + target,
                                              "inputs": {"project": project}})
                if outcome.get("status") != "completed":
                    raise RuntimeError(json.dumps(outcome))
            inputs = {"project": project}
            for _ in range(2):
                outcome = call("manual.run", {"id": "mobile-studio", "chapter": "apple-targets", "procedure": "verify-retained-artifact-macos", "inputs": inputs})
                if outcome.get("status") != "completed":
                    raise RuntimeError(json.dumps(outcome))
            compiled = call("manual.compile", {"id": "mobile-studio", "chapter": "apple-targets", "procedure": "verify-retained-artifact-macos", "inputs": inputs, "minRuns": 2})
            script = compiled.get("script") or compiled
            script_id = script.get("scriptId")
            if not script_id:
                raise RuntimeError(json.dumps(compiled))
            outcome = call("manual.script.run", {"scriptId": script_id, "inputs": inputs})
            if outcome.get("status") != "completed":
                raise RuntimeError(json.dumps(outcome))
            for procedure in ("prepare-cloud-off", "refuse-unsupported-watch"):
                outcome = call("manual.run", {"id": "mobile-studio", "chapter": "apple-targets", "procedure": procedure, "inputs": {"project": project}})
                if outcome.get("status") != "completed":
                    raise RuntimeError(json.dumps(outcome))
            for target in ("watchos", "tvos", "visionos"):
                refusal = call("mobile.build", {"project": project, "platform": target})
                if refusal.get("status") != "unsupported":
                    raise RuntimeError("Unsupported build was admitted")
        elif args.tool:
            arguments = json.loads(args.args_file.read_text(encoding="utf-8")) if args.args_file else {}
            call(args.tool, arguments)
        else:
            parser.error("Use --tool or --prove")
        result = {"ok": True, "transport": "local WorkspaceTools", "calls": log}
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "calls": len(log), "receipt": str(args.receipt) if args.receipt else None,
                          "last": log[-1]["result"]}, indent=2))
    finally:
        service.close()

if __name__ == "__main__":
    main()
