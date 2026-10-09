"""Run the impact map against the real repo, including package imports and incremental refresh."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.neyvia_impact import impact, index


def main():
    path = "src/grant_agent/connected_sessions/plan.py"
    first = impact([path], gaps=False)
    repeats = [impact([path], gaps=False) for _ in range(3)]
    repeat = repeats[-1]
    assert "tests/test_connected_plan.py" in repeat["files"][0]["tests"]
    assert "tests/test_connected_plan.py" in repeat["files"][0]["dependents"]
    original_tree = index()["branches"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", prefix="impact_probe_", dir=ROOT / "tests", delete=False) as file:
        probe = Path(file.name)
        file.write("from grant_agent.connected_sessions.plan import latest_plan\n")
    try:
        added = impact([path], gaps=False)
        assert probe.relative_to(ROOT).as_posix() in added["files"][0]["tests"]
        # Registry trees are reused; changed files refresh their text and relationships.
        probe.write_text("from grant_agent.connected_sessions.runs import public_run\n", encoding="utf-8")
        changed = impact([path], gaps=False)
        assert probe.relative_to(ROOT).as_posix() not in changed["files"][0]["tests"]
        assert index()["branches"] == original_tree
    finally:
        probe.unlink()
    removed = impact([path], gaps=False)
    assert probe.relative_to(ROOT).as_posix() not in removed["files"][0]["tests"]
    result = {"ok": True, "packageImport": "tests/test_connected_plan.py", "coldMs": first["elapsedMs"],
              "repeatMs": [row["elapsedMs"] for row in repeats], "addedMs": added["elapsedMs"], "changedMs": changed["elapsedMs"],
              "removedMs": removed["elapsedMs"], "incrementalAddChangeDelete": True}
    print(json.dumps(result, indent=2))
    evidence = ROOT / "scripts/evidence/impact-loop.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
