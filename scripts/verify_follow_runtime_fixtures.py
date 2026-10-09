"""Direct replay of eight reviewed historical runtime fixture cases."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import socket
import sys
import traceback
from unittest.mock import patch

import verify_follow_failures as failures

REPO = failures.REPO
OUTPUT = REPO / "scripts/evidence/FOLLOW-runtime-fixtures.json"
SELECTED = {
    "tests/test_runtimes.py": ["test_hermes_adapter_reports_missing_runtime", "test_hermes_adapter_detects_runtime_inside_wsl", "test_hermes_launch_uses_wsl_bash_lc_when_hermes_only_in_wsl"],
    "tests/test_neyvia_agent.py": ["test_astra_effort_reaches_native_agent_and_specialists", "test_compatibility_specialists_do_not_send_openai_reasoning", "test_empty_workspace_keeps_native_tools_without_managed_catalog", "test_auto_transport_uses_codex_subscription_and_records_truthful_receipt"],
    "tests/test_web_backend.py": ["test_neyvia_agent_chat_applies_secret_free_chat_completions_profile"],
}


def assertions(source, names):
    tree = ast.parse(source)
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            result[node.name] = [ast.dump(child, include_attributes=False) for child in ast.walk(node)
                if isinstance(child, ast.Assert) or isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                and isinstance(child.value.func, ast.Attribute) and child.value.func.attr.startswith("assert")]
    return result


def main():
    failures.SCRATCH = REPO / ".agent_control/follow-runtime-fixtures"
    failures.isolate()
    permission = {"gitSourceRead": False}
    def deny_runtime_launch(event, args):
        if event == "subprocess.Popen" and not permission["gitSourceRead"]:
            raise PermissionError("Reviewed runtime fixtures cannot launch child runtimes")
        if event == "socket.bind" and isinstance(args[1], tuple) and args[1][1] not in range(48441, 48450):
            raise PermissionError("Reviewed runtime fixtures cannot bind non-task ports")
    sys.addaudithook(deny_runtime_launch)
    fixture_root = failures.SCRATCH / "agent-root"
    fixture_root.mkdir(exist_ok=True)
    results = []
    source_hashes = {}
    preserved = 0
    for relative, names in SELECTED.items():
        path = REPO / relative
        permission["gitSourceRead"] = True
        try:
            original = subprocess.check_output(["git", "show", "3de931ea:" + relative], cwd=REPO, text=True, encoding="utf-8")
        finally:
            permission["gitSourceRead"] = False
        current = path.read_text(encoding="utf-8")
        before, after = assertions(original, names), assertions(current, names)
        assert before == after, "Business assertion changed in " + relative
        preserved += sum(len(values) for values in before.values())
        source_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("follow_runtime_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        # These three reviewed agent constructors use the fixture constant,
        # never the repository's active control state or credential landscape.
        if relative == "tests/test_neyvia_agent.py":
            module.REPO_ROOT = fixture_root
        for name in names:
            owner = next(cls for cls in vars(module).values() if isinstance(cls, type) and hasattr(cls, name))
            identifier = relative + "::" + owner.__name__ + "::" + name
            try:
                if name == "test_auto_transport_uses_codex_subscription_and_records_truthful_receipt":
                    # Windows asyncio's wake-up pipe uses a TCP socketpair.
                    # Keep its listener on our explicit port too; no random
                    # listener or relaxed network audit is needed.
                    def task_socketpair(*args, **kwargs):
                        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        try:
                            listener.bind(("127.0.0.1", 48449))
                            listener.listen(1)
                            client.connect(("127.0.0.1", 48449))
                            server, _ = listener.accept()
                            return server, client
                        except BaseException:
                            client.close()
                            raise
                        finally:
                            listener.close()
                    with patch("socket.socketpair", task_socketpair):
                        getattr(owner(name), name)()
                else:
                    getattr(owner(name), name)()
            except Exception as exc:
                frames = [{"path": str(Path(frame.filename).relative_to(REPO)), "line": frame.lineno}
                          for frame in traceback.extract_tb(exc.__traceback__) if Path(frame.filename).is_relative_to(REPO)]
                results.append({"id": identifier, "passed": False, "exceptionType": type(exc).__name__, "locations": frames})
            else:
                results.append({"id": identifier, "passed": True})
    result = {"schema": "neyvia.FOLLOW.runtime-fixtures.v1", "passed": all(row["passed"] for row in results),
              "originalCasesReplayed": len(results), "unchangedOriginalAssertionASTs": preserved,
              "sourceSha256": source_hashes, "cases": results,
              "boundary": "reviewed direct cases, authentic production constructors/adapters, controlled subprocess/provider fixtures only; no model/runtime execution; no pytest runner; task-local agent root, protected paths and non-task sockets denied"}
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
