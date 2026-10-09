"""Check current native launcher, local lazy history, and manual discovery."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

import verify_follow_failures as failures


def main():
    failures.SCRATCH = failures.REPO / ".agent_control/follow-current-fixtures"
    failures.isolate()
    checks = []
    selections = {
        "test_web_backend": ["test_conversation_bootstrap_is_index_first_and_session_detail_is_lazy",
                             "test_neyvia_agent_chat_resolves_cli_from_source_workspace"],
        "test_connected_plan": ["test_agents_manual_is_discoverable_and_loadable"],
        "test_claude_code_mods": ["test_plugin_skills_match_the_manuals"],
    }
    for module_name, names in selections.items():
        path = failures.REPO / "tests" / (module_name + ".py")
        spec = importlib.util.spec_from_file_location("follow_current_" + module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for name in names:
            owner = module.FluxioWebBackendTests(name) if module_name == "test_web_backend" else module
            identifier = "tests/" + module_name + ".py::" + ("FluxioWebBackendTests::" if module_name == "test_web_backend" else "") + name
            try:
                getattr(owner, name)()
            except Exception as exc:
                frames = [f for f in traceback.extract_tb(exc.__traceback__) if "tests" in Path(f.filename).parts]
                checks.append({"id": identifier, "passed": False, "exceptionType": type(exc).__name__, "line": frames[-1].lineno if frames else None})
            else:
                checks.append({"id": identifier, "passed": True})
    http_checks = []
    with failures.real_http() as (_, request):
        assert request("/api/auth/local-session", {})["http"] == 200
        for name, arguments in (("manual.index", {}), ("manual.load", {"id": "agents"}),
                                ("manual.validate", {"id": "agents"}), ("manual.load", {"id": "settings"})):
            row = request("/api/ui/tools/call", {"tool": "neyvia." + name, "arguments": arguments})
            assert row["http"] == 200 and row["body"]["ok"] and row["body"]["data"]["ok"], name
            http_checks.append({"tool": name, "id": arguments.get("id"), "passed": True})
    receipt = {"cases": checks, "passed": all(row["passed"] for row in checks), "http": http_checks,
               "port": 48449, "ownedServerStopped": True,
               "boundary": "Current declared launcher/environment and local lazy-history fixtures; real manual HTTP discovery/loading. No provider execution, NAS, or rendered UI claim."}
    (failures.REPO / "scripts/evidence/FOLLOW-current-fixtures.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt))
    if not receipt["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    # No fixture may open a terminal as a side effect of readiness discovery.
    with patch("winpty.PtyProcess.spawn", side_effect=PermissionError("Fixture terminal execution denied")):
        main()
