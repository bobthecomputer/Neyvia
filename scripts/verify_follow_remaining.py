"""Bounded replay of the remaining historical backend/source invariants."""
from __future__ import annotations

from contextlib import redirect_stdout, ExitStack
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import traceback
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]
scratch = REPO / ".agent_control/follow-remaining"
scratch.mkdir(exist_ok=True)
tempfile.tempdir = str(scratch)
active = False


def guard(event, args):
    if not active:
        return
    if event in {"socket.connect", "subprocess.Popen", "os.system"}:
        raise PermissionError("Remaining replay forbids external process/network")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0]).resolve()
        if not path.is_relative_to(REPO) and path.suffix not in {".py", ".pyc", ".pyd"}:
            raise PermissionError("Remaining replay forbids external data files")


sys.addaudithook(guard)
ledger = json.loads((REPO / "scripts/evidence/FOLLOW-failures.json").read_text(encoding="utf-8"))
done = {"test_hook_runs_without_shell_and_writes_receipt", "test_resource_mode_aliases_and_rejection", "test_detect_default_commands"}
checks = []
context_sources = {}
modules = {}
for case in ledger["cases"]:
    if case["rootCauseGroup"] != "remaining-behavior-review":
        continue
    parts = case["id"].split("::")
    if parts[-1] in done:
        continue
    path = REPO / parts[0]
    if path not in modules:
        spec = importlib.util.spec_from_file_location("follow_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[path] = module
    module = modules[path]
    target = getattr(module, parts[1])() if len(parts) == 3 else module
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        arguments = {"tmp_path": Path(directory)}
        output = io.StringIO()
        def readouterr():
            captured = output.getvalue()
            output.seek(0)
            output.truncate()
            return SimpleNamespace(out=captured, err="")
        arguments["capsys"] = SimpleNamespace(readouterr=readouterr)
        function = getattr(target, parts[-1])
        import inspect
        parameters = {name: arguments[name] for name in inspect.signature(function).parameters}
        try:
            active = True
            with redirect_stdout(output), ExitStack() as stack:
                if parts[-1] == "test_run_command_flows_bounded_base_and_dependency_context_without_future_context":
                    original = module.FluxioWebBackend._run_neyvia_agent_node
                    def capture_context(backend, **kwargs):
                        context_sources[kwargs["node"]["nodeId"]] = [
                            {"sourceId": row.get("sourceId"), "kind": row.get("kind"), "chars": len(str(row.get("content") or ""))}
                            for row in kwargs["context_selection"]
                        ]
                        return original(backend, **kwargs)
                    stack.enter_context(mock.patch.object(module.FluxioWebBackend, "_run_neyvia_agent_node", capture_context))
                function(**parameters)
        except Exception as exc:
            frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if "/tests/" in frame.filename.replace("\\", "/")]
            checks.append({"id": case["id"], "passed": False, "exception": type(exc).__name__,
                           "failureLine": frames[-1].lineno if frames else None,
                           "diagnostic": str(exc)[:250] if not isinstance(exc, AssertionError) else "Original assertion failed",
                           "boundary": "Failed or authority-blocked bounded original-case replay"})
        else:
            checks.append({"id": case["id"], "passed": True, "boundary": "Original case on disposable fixture; no live release/runtime proof"})
        finally:
            active = False
receipt = {"boundary": "Seven original remaining backend/source cases under disposable fixture/no external process-network-data guard. No assertions removed, no live services/release changed.",
           "checks": checks, "passed": sum(row["passed"] for row in checks), "unmet": sum(not row["passed"] for row in checks)}
scanner = modules[REPO / "tests/test_windows_hidden_subprocesses.py"]
receipt["visibleSpawnFindings"] = [list(row) for row in scanner._product_findings() if (row[0], row[3]) not in scanner.VISIBLE_ALLOWLIST]
receipt["fixtureContextSources"] = context_sources
(REPO / "scripts/evidence/FOLLOW-remaining.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({key: receipt[key] for key in ("passed", "unmet")}))
