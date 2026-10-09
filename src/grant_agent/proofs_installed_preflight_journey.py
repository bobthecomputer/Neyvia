"""Read-only outcome contract for local installed-program discovery and resolution."""
from __future__ import annotations

import time
import uuid
import sys
import tempfile
from pathlib import Path


CONTRACT = "runtime.program.local-python-preflight"
CONTRACTS = (CONTRACT,)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(f"Contract {CONTRACT}: {detail}")


def _inspect_fixture(fixture_root: Path) -> dict:
    from .installed_programs import InstalledPrograms
    from .runtimes import runtime_adapter_map

    source = fixture_root / "preflight_fixture.py"
    source.write_text("# Owned source fixture; this contract resolves it and never executes it.\n",
                      encoding="utf-8", newline="\n")

    owner = InstalledPrograms(fixture_root)
    discovery = owner.discover()
    executable = Path(sys.executable).resolve()
    matches = [row for row in discovery["programs"] if Path(row["path"]).resolve() == executable]
    require(bool(matches), "discovery omitted the exact current Python executable")
    require(discovery.get("installationRequired") is False,
            "availability inspection reported that installation was required")

    recipe = owner.prepare_file(source)
    resolved_source = Path(recipe["arguments"][0]).resolve()
    require(Path(recipe["executable"]).resolve() == executable and resolved_source == source.resolve(),
            "owned Python source did not resolve to the exact current interpreter and source")
    require(recipe.get("installationRequired") is False
            and recipe.get("dependenciesVerified") is False,
            "preflight misreported installation or dependency readiness")

    outside = fixture_root.parent / (fixture_root.name + "-outside.py")
    try:
        owner.prepare_file(outside)
    except ValueError as error:
        message = str(error).lower()
        require(any(word in message for word in ("relative", "subpath", "outside", "workspace")),
                "outside-root refusal did not identify the workspace boundary")
        outside_refused = True
    else:
        outside_refused = False
    require(outside_refused, "preparation accepted a path outside its managed workspace")

    adapters = runtime_adapter_map()
    python_adapter = adapters.get("python")
    require(python_adapter is None,
            "a provider-free Python route appeared; stop for a new managed lifecycle contract")
    return {
        "id": CONTRACT,
        "status": "PASS",
        "availability": {
            "executable": str(executable),
            "matchingPathCount": len(matches),
            "installationRequired": False,
        },
        "resolution": {
            "source": str(resolved_source),
            "executable": str(Path(recipe["executable"]).resolve()),
            "arguments": recipe["arguments"],
            "installationRequired": False,
            "dependenciesVerified": False,
        },
        "refusal": {"outsideWorkspace": outside_refused},
        "delegatedRuntime": {
            "pythonAdapterAvailable": False,
            "knownAdapterIds": sorted(adapters),
            "supervisorStart": "not attempted; no provider-free Python route is registered",
        },
        "notAttempted": [
            "DelegatedRuntimeSupervisor.start_session",
            "runtime_auto_update.ensure_runtime_auto_update",
            "provider/account execution",
            "managed worker process",
        ],
        "boundary": (
            "Pure local discovery and command resolution. No script or process is started; "
            "availability does not establish dependencies, engine execution, authentication, "
            "or provider readiness."
        ),
    }


def _journey(workspace: Path) -> dict:
    """Keep the owned source fixture temporary even when an observer raises."""
    with tempfile.TemporaryDirectory(prefix=f"installed-preflight-{uuid.uuid4().hex[:8]}-",
                                     dir=workspace) as directory:
        return _inspect_fixture(Path(directory))


def self_check(root: str | Path | None = None) -> dict:
    """Resolve an owned scratch source without launching it or contacting a provider."""
    from .contract_gate import wants

    if not wants(CONTRACTS):
        return {"ok": True, "outcomes": [], "unselected": list(CONTRACTS)}
    started = time.perf_counter()
    workspace = Path(root or Path("D:/NeyviaRuns/P22/measurement")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        outcome = _journey(workspace)
        outcome["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
        return {"ok": True, "outcomes": [outcome]}
    except Exception as error:
        return {
            "ok": False,
            "outcomes": [{
                "id": CONTRACT,
                "status": "FAIL",
                "error": f"{type(error).__name__}: {error}",
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
            }],
        }
