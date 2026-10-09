"""Retain independently observed historical UIA facts as replay-only decisions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main():
    evidence = Path(__file__).resolve().parent / "evidence"
    path = evidence / "T16-independent-readback.json"
    raw = path.read_bytes()
    observed = json.loads(raw)
    window, node = observed["window"], observed["nodes"][0]
    facts = [
        ("application", "Which application is the independently observed editor?", "Notepad", "Calculator", window["processName"] == "Notepad", "window.processName == Notepad"),
        ("title", "Which filename is in the observed native window title?", "T16-native-note.txt", "C2b-new-note.txt", "T16-native-note.txt" in window["title"], "window.title contains T16-native-note.txt"),
        ("minimized", "Is the observed editor window minimized?", "The editor window is not minimized", "The editor window is minimized", window["minimized"] is False, "window.minimized == false"),
        ("role", "Which accessible role does the observed text editor node expose?", "Document", "Button", node["role"] == "Document", "nodes[0].role == Document"),
        ("enabled", "Is the observed document control enabled?", "The document is enabled", "The document is disabled", node["enabled"] is True, "nodes[0].enabled == true"),
        ("offscreen", "Is the observed document control offscreen?", "The document is onscreen", "The document is offscreen", node["offscreen"] is False, "nodes[0].offscreen == false"),
        ("patterns", "Which UIA pattern allows a value readback on the observed editor?", "value", "invoke", "value" in node["patterns"] and "invoke" not in node["patterns"], "nodes[0].patterns includes value and excludes invoke"),
        ("prefix", "Which proof prefix occurs in the independently read document value?", "T16 native background proof.", "C2b current browser proof.", "T16 native background proof." in node["value"], "nodes[0].value contains T16 native background proof."),
        ("continuation", "Which continuation is actually visible in the independent native readback?", "Agent wrote this through UI Automation.", "Agent wrote this through browser screenshots.", "Agent wrote this through UI Automation." in node["value"], "nodes[0].value contains Agent wrote this through UI Automation."),
        ("bounds", "What is the width of the independently observed native editor window?", "1086", "599", window["bounds"]["width"] == 1086, "window.bounds.width == 1086"),
    ]
    rows = []
    for index, (name, goal, yes, no, verified, check) in enumerate(facts):
        if not verified:
            raise ValueError("Historical independent observation changed: " + name)
        options = [("observed", yes), ("unobserved", no)]
        if index % 2:
            options.reverse()
        rows.append({"id": "computer-T16-" + name, "split": "heldout", "domain": "computer",
                     "family": "historical_uia_evidence", "group": "computer:T16-notepad-2026-10-02",
                     "provenance": {"run_id": "T16-native-independent-readback-2026-10-02", "window": window["windowId"],
                        "observed_at": "2026-10-02", "observation_path": "scripts/evidence/T16-independent-readback.json",
                        "observation_sha256": hashlib.sha256(raw).hexdigest(), "historical_replay_only": True},
                     "state": observed, "question": {"type": "choice", "instructions": goal, "criteria": dict(options)},
                     "gold": "observed", "expected_check": check})
    output = evidence / "C2b-computer-decisions.jsonl"
    output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "count": len(rows), "historical_replay_only": True,
                      "source": str(path), "source_sha256": hashlib.sha256(raw).hexdigest()}))


if __name__ == "__main__":
    main()
