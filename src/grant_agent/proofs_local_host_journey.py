"""A scoped local-host journey through Neyvia's native managed-process owner."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


CONTRACTS = ("p22.local-host.managed-process-journey",)


def require(condition, detail):
    if not condition:
        raise AssertionError("Contract " + CONTRACTS[0] + ": " + detail)


def self_check(root=None):
    """Launch one owned Python child, observe its state and output, then refuse an ungranted launch."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    scratch_root = Path(root or "D:/NeyviaRuns/P22").resolve()
    allowed_root = Path("D:/NeyviaRuns/P22").resolve()
    require(scratch_root.is_relative_to(allowed_root),
            "local-host proof scratch root must stay under D:/NeyviaRuns/P22")
    state_root = scratch_root / "local-host-journey" / uuid.uuid4().hex
    require(state_root.is_relative_to(allowed_root),
            "local-host managed state escaped D:/NeyviaRuns/P22")
    state_root.mkdir(parents=True, exist_ok=False)
    fixture = state_root / "journey"
    fixture.mkdir()
    source = fixture / "write_result.py"
    output = fixture / "observed-result.json"
    nonce = uuid.uuid4().hex
    expected = {"journey": "local-host", "nonce": nonce, "saved": True}
    source.write_text(
        "import json, pathlib, sys\n"
        "target = pathlib.Path(sys.argv[1])\n"
        "value = json.loads(sys.argv[2])\n"
        "target.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')\n"
        "print(json.dumps({'completed': True, 'nonce': value['nonce']}))\n",
        encoding="utf-8",
        newline="\n",
    )

    from .cl.fixcl4_host_effects import checks_for, snapshot_for
    from .creative_tools import CreativeToolRuntime
    from .installed_programs import InstalledPrograms

    arguments = {
        "path": str(source),
        "arguments": [str(output), json.dumps(expected, sort_keys=True)],
        "timeoutSeconds": 10,
    }
    owner = InstalledPrograms(state_root)
    runtime = CreativeToolRuntime(state_root)
    protocol = SimpleNamespace(gateway=SimpleNamespace(root=state_root))
    session_id = None
    try:
        before = snapshot_for(protocol, "host.launch_file", arguments)
        dispatched = runtime.call("host.launch_file", arguments)
        value = dispatched.get("session") if isinstance(dispatched, dict) else None
        require(isinstance(value, dict) and value.get("sessionId"),
                "the native host response omitted its owned session identity")
        session_id = value["sessionId"]
        checks = checks_for(protocol, "host.launch_file", arguments)
        require(len(checks) == 1 and checks[0]["observer"] and checks[0]["effect"],
                "the production local-host observer was not attached")
        require(checks[0]["check"](arguments, dispatched, before),
                "the fresh managed-process owner observation failed")

        observed = owner.status(session_id)
        deadline = time.monotonic() + 10
        while observed.get("status") in {"queued", "starting", "running"} and time.monotonic() < deadline:
            time.sleep(.05)
            observed = owner.status(session_id)
        require(observed.get("status") == "completed" and observed.get("exitCode") == 0,
                "the fresh owned session state was not a successful completion: " + json.dumps(observed, default=str)[:1000])
        require(observed.get("logsComplete") is True and observed.get("outputTruncated") is False,
                "the managed owner did not preserve the full child result")
        require(json.loads(output.read_text(encoding="utf-8")) == expected,
                "the child did not write the exact nonce-bearing result bytes")
        stdout = observed.get("stdout", "")
        require(json.loads(stdout.strip()) == {"completed": True, "nonce": nonce},
                "a fresh managed stdout observation did not match the child result")

        prior_sessions = {row["sessionId"] for row in owner.list_sessions()["sessions"]}
        try:
            runtime.call("host.launch_file", {"path": str(Path(__file__).resolve()), "arguments": [], "timeoutSeconds": 10})
        except ValueError as error:
            require(any(word in str(error).lower() for word in ("outside", "relative", "workspace", "subpath")),
                    "an escaped source path must explain its workspace boundary: " + str(error))
        else:
            raise AssertionError("a script outside the selected managed root was launched")
        require({row["sessionId"] for row in owner.list_sessions()["sessions"]} == prior_sessions,
                "the refused source path changed the managed-session owner state")
        case = {"id": "local-host.managed-process-journey", "contracts": list(CONTRACTS),
                "ok": True, "sessionStatus": observed["status"], "exitCode": observed["exitCode"],
                "exactOutputObserved": True, "escapedPathRefused": True}
        return {
            "ok": True,
            "contracts": list(CONTRACTS),
            "cases": [case],
            "failures": [],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "stateRoot": str(state_root),
            "frontier": "Runs a real scoped host.launch_file action and fresh local owner observer; no device, UI window, plugin provider, or external service is involved.",
        }
    except Exception as error:
        return {
            "ok": False,
            "contracts": list(CONTRACTS),
            "cases": [{"id": "local-host.managed-process-journey", "contracts": list(CONTRACTS),
                       "ok": False, "error": str(error)}],
            "failures": [str(error)],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "stateRoot": str(state_root),
        }
    finally:
        if session_id:
            fresh = owner.status(session_id)
            if fresh.get("status") in {"queued", "starting", "running", "unknown"}:
                owner.stop(session_id, expectedRevision=fresh.get("control", {}).get("revision", 0))
