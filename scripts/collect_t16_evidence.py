"""Consolidate observed T16 outcomes and hashes without replacing adverse receipts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / "src"))
from grant_agent.neyvia_cua import COMMANDS
evidence = repo / "scripts/evidence"
read = lambda name: json.loads((evidence / name).read_text(encoding="utf-8-sig"))
core, ui, native, luna = (read(name) for name in ("T16.json", "T16-ui.json", "T16-native-contract.json", "T16-luna.json"))
assert core["passed"] and ui["passed"] and native["passed"] and luna["passed"]
sources = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=repo, text=True).splitlines()
sources += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo, text=True).splitlines()
sources = sorted(set(p for p in sources if not p.startswith("scripts/evidence/") and p.startswith(("src/", "scripts/", "config/", "tools/cua-driver-win/"))))
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
core["completion"] = {
    "nativeChecks": len(core["checks"]), "realUiChecks": len(ui["checks"]), "contractChecks": len(native["checks"]),
    "realModel": {"name": luna["model"], "effort": luna["effort"], "seconds": luna["seconds"], "usage": luna["usage"],
                  "completedMcpCalls": len([e for e in luna["actualMcpCalls"] if e["type"] == "item.completed"]),
                  "independentNativeResult": luna["independentNativeResult"]},
    "ports": {"backend": 48171, "vite": 48172}, "python": sys.executable,
    "runtime": read("../vendor-research/cua-driver/provenance.json"),
    "manualCheck": read("T16-manual-check.json"),
    "desktopCommands": sorted(COMMANDS),
    "registration": {"http": "neyvia_ui_api.py: /api/ui/cua POST, state/windows/tools/frame/stream GET",
                     "native": "neyvia_workspace_tools.py: eight cua tools, observers, external-action authority, pane.show preview",
                     "desktop": "desktop_bridge.py: allow-list and authenticated persistent-service forwarding with workspace check",
                     "cli": "cua_launch.py: process-local Codex/Claude/Neyvia MCP; connected adapters and native gateway bind chat identity",
                     "mcp": "neyvia_cua_mcp.py: exact 22 native upstream schemas plus five preview tools; immutable connection/session identity",
                     "manual": "config/neyvia_manuals.json: computer-use registration; Claude's actual JSON validates"},
    "sourceSha256": {p: digest(repo / p) for p in sources},
    "receiptSha256": {p.name: digest(p) for p in sorted(evidence.glob("T16*")) if p.name != "T16.json"},
    "replayOrder": ["system Python -B scripts/install_cua_driver.py", "start isolated backend48171 and Vite48172 with watchdog/autoupdate disabled",
                    "PYTHONPATH=src; system Python -B scripts/build_t16_probe.py", "system Python -B scripts/launch_t16_notepad.py",
                    "node scripts/verify_t16.cjs", "node scripts/verify_t16_ui.cjs", "system Python -B scripts/verify_t16_contract.py",
                    "system Python -B scripts/verify_t16_luna.py", "system Python -B scripts/collect_t16_evidence.py"]}
core["boundaries"].update({"realNativeApp": "Windows Notepad and the compiled WinForms task app", "modelTask": "real GPT-6 Luna CLI, actual MCP calls and independently saved output",
                         "modelFocusProof": "zero actual foreground transitions and fixed cursor for the complete successful model task",
                         "nativeProviders": "classic Edit/WinForms child HWND message routes and supported UIA ValuePattern; unfamiliar/caret/keyboard routes may refuse",
                         "verification": "stable native ValuePattern equality subset; unsupported predicates explicitly unknown without upstream dispatch",
                         "fullManualBuild": "blocked by neyvia pane.show enum and existing neyvia-reference mission.create schema drift; manuals outside Codex edit scope",
                         "installedDesktop": "not built/installed; real dev Chrome UI and authenticated desktop forwarding only",
                         "shutdown": "proof grants paused; task servers and disposable probe stopped; existing Notepad drafts retained"})
(evidence / "T16.json").write_text(json.dumps(core, indent=2), encoding="utf-8")
print(json.dumps({"passed": True, "native": len(core["checks"]), "ui": len(ui["checks"]), "contract": len(native["checks"]), "modelMcpCalls": core["completion"]["realModel"]["completedMcpCalls"]}))
