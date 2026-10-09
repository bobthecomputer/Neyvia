"""Real local compiler/search/read journey plus silent map-integrity checks."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grant_agent.compiled_tool_maps import CompiledToolMapStore
from grant_agent.neyvia_agent import NeyviaToolGateway


def expect_error(action, kind):
    try:
        action()
    except kind as error:
        return str(error)
    raise AssertionError(f"Expected {kind.__name__}")


def verify_integrity():
    store = CompiledToolMapStore()
    compiled = {"callMap": {"files.read": {
        "callTarget": "workspace.read", "boundArguments": {"path": "alpha.txt", "options": {"limit": 10}},
        "requiresApproval": False}}}
    alpha = store.retain(compiled)
    compiled["callMap"]["files.read"]["boundArguments"]["path"] = "beta.txt"
    beta = store.retain(compiled)
    assert alpha != beta
    assert store.resolve(f"files.read@{alpha}", {})["arguments"]["path"] == "alpha.txt"
    assert store.resolve(f"files.read@{beta}", {})["arguments"]["path"] == "beta.txt"
    resolved = store.resolve(f"files.read@{alpha}", {})
    resolved["arguments"]["path"] = "tampered.txt"
    resolved["arguments"]["options"]["limit"] = 999
    assert store.resolve(f"files.read@{alpha}", {})["arguments"]["path"] == "alpha.txt"
    assert store.resolve(f"files.read@{alpha}", {})["arguments"]["options"]["limit"] == 10
    return {
        "sourceMutationCannotChangeRetainedMap": True,
        "resolvedArgumentsCannotChangeRetainedMap": True,
        "collidingProviderNamesRemainVersionBound": True,
        "ambiguousUnversionedRejected": expect_error(lambda: store.resolve("files.read", {}), ValueError),
        "unknownVersionRejected": expect_error(lambda: store.resolve("files.read@unknown", {}), KeyError),
        "wrongNamespaceRejected": expect_error(lambda: store.resolve(f"other.read@{alpha}", {}), KeyError),
    }


def main():
    with TemporaryDirectory(prefix="fixwave-item3-") as temp:
        root = Path(temp)
        content = "Earlier selection still reads the real alpha file after later search."
        (root / "alpha.txt").write_text(content, encoding="utf-8")
        gateway = NeyviaToolGateway(root)
        alpha = gateway.search("read text file workspace", 8)["compiler"]
        selection = next(row["providerCall"] for row in alpha["providerCalls"]
                         if row["providerCall"].startswith("files.workspace_read@"))
        beta = gateway.search("microphone dictation transcribe audio", 8)["compiler"]
        assert alpha["callMapHash"] != beta["callMapHash"]
        assert not any(row["providerCall"].startswith("files.workspace_read@")
                       for row in beta["providerCalls"])
        result = gateway.call_compiled(selection, {"path": "alpha.txt"})
        assert result["ok"], result
        assert result["callMapHash"] == alpha["callMapHash"]
        assert content in json.dumps(result["run"]), result
        legacy = gateway.call_compiled("files.workspace_read", {"path": "alpha.txt"})
        assert legacy["ok"]
        receipt = {
            "item": 3, "observedAt": datetime.now(timezone.utc).isoformat(),
            "status": "passed", "boundary": "Real local gateway search/compiler and workspace.read; no model/provider/browser call",
            "earlierCompile": alpha, "laterCompile": beta, "earlierSelection": selection,
            "earlierCallAfterLaterSearch": result,
            "legacyUnambiguousSelectionWorks": legacy["ok"],
            "compilerSnapshot": gateway.compiler_snapshot(),
            "silentIntegrityChecks": verify_integrity(),
            "missing": ["Map versions are retained for the gateway lifetime, not persisted across separate runs."],
        }
        destination = Path(__file__).resolve().parent / "evidence" / "fixwave-item3.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "passed", "receipt": str(destination),
                          "retainedVersions": gateway.compiler_snapshot()["retainedVersions"],
                          "realCallTarget": result["callTarget"]}))


if __name__ == "__main__":
    main()
