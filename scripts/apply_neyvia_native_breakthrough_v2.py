from __future__ import annotations

import ast
import runpy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "src" / "grant_agent" / "neyvia_agent.py"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, value: str) -> None:
    path = ROOT / relative
    normalized = value.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, anchor + addition, 1)


def patch_turn_budget(text: str) -> str:
    text = text.replace("    max_turns: int = 24\n", "    max_turns: int = 40\n", 1)
    text = text.replace('    parser.add_argument("--max-turns", type=int, default=24)\n', '    parser.add_argument("--max-turns", type=int, default=40)\n', 1)
    return text


def patch_plan_seal(text: str) -> str:
    early = '''    event_stream.emit(
        "plan.compiled",
        {
            "planHash": behavior_plan.get("planHash"),
            "capsuleId": (behavior_plan.get("capsule") or {}).get("id"),
            "skillPlanHash": skill_plan.get("planHash"),
            "resourceMode": resource_profile.get("mode"),
        },
    )
    plan_hooks = hook_runner.run(
        "plan.compiled",
        {"runId": run_id, "planHash": behavior_plan.get("planHash")},
    )
    event_stream.emit("hooks.plan_compiled", plan_hooks)
    if plan_hooks.get("blocked"):
        raise RuntimeError("A blocking Neyvia plan.compiled hook failed.")
'''
    if early in text:
        text = text.replace(early, "", 1)
    mutation_block = '''    if selected.allow_mutations and (behavior_plan.get("capsule") or {}).get("id") in {
        "direct-verified",
        "implementation",
        "diagnosis-repair",
        "design-evolution",
    }:
        behavior_plan["capsule"]["mutationExpected"] = True
        gates = set(behavior_plan["capsule"].get("proofGates") or ())
        gates.update({"workspace_delta", "deterministic_check", "receipt_integrity"})
        behavior_plan["capsule"]["proofGates"] = sorted(gates)
'''
    finalization = '''    behavior_plan["proofGates"] = sorted(
        set(behavior_plan.get("proofGates") or ())
        | set((behavior_plan.get("capsule") or {}).get("proofGates") or ())
    )
    behavior_plan["planHash"] = canonical_hash(
        {key: value for key, value in behavior_plan.items() if key != "planHash"}
    )
    event_stream.emit(
        "plan.compiled",
        {
            "planHash": behavior_plan.get("planHash"),
            "capsuleId": (behavior_plan.get("capsule") or {}).get("id"),
            "skillPlanHash": skill_plan.get("planHash"),
            "resourceMode": resource_profile.get("mode"),
        },
    )
    plan_hooks = hook_runner.run(
        "plan.compiled",
        {"runId": run_id, "planHash": behavior_plan.get("planHash")},
    )
    event_stream.emit("hooks.plan_compiled", plan_hooks)
    if plan_hooks.get("blocked"):
        raise RuntimeError("A blocking Neyvia plan.compiled hook failed.")
'''
    text = insert_after(text, mutation_block, finalization, "final behavior plan seal")
    return text


def patch_phase_receipt_directory(text: str) -> str:
    return replace_once(
        text,
        '''            phase_path = state_root / "phase_receipts" / f"{run_id}-{phase_id}.json"
            atomic_write_json(phase_path, phase_receipt)
''',
        '''            phase_path = state_root / "phase_receipts" / f"{run_id}-{phase_id}.json"
            phase_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(phase_path, phase_receipt)
''',
        "phase receipt directory",
    )


def patch_final_proof_seal(text: str) -> str:
    anchor = '''    event_stream.emit(
        "run.finished",
        {
            "status": proof_audit.get("runStatus"),
            "proofStatus": proof_audit.get("status"),
        },
    )
    event_stream_verification = event_stream.verify()
'''
    replacement = '''    proof_audit["sealedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    proof_audit["auditHash"] = canonical_hash(
        {key: value for key, value in proof_audit.items() if key != "auditHash"}
    )
    event_stream.emit(
        "proof.sealed",
        {
            "status": proof_audit.get("status"),
            "runStatus": proof_audit.get("runStatus"),
            "auditHash": proof_audit.get("auditHash"),
        },
    )
    event_stream.emit(
        "run.finished",
        {
            "status": proof_audit.get("runStatus"),
            "proofStatus": proof_audit.get("status"),
        },
    )
    event_stream_verification = event_stream.verify()
'''
    return replace_once(text, anchor, replacement, "final proof seal")


def patch_branding() -> None:
    roots = [ROOT / "web" / "src"]
    direct_files = [ROOT / "web" / "index.html"]
    paths = list(direct_files)
    for root in roots:
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".css", ".html"})
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = (
            text.replace("NEYVIA Native", "Neyvia Native")
            .replace("NEYVIA Hybrid", "Neyvia Hybrid")
            .replace("N-E-Y-V-I-A", "Neyvia")
        )
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def patch_browser_capture() -> None:
    path = "scripts/capture_native_evolution.mjs"
    text = read(path)
    text = text.replace(
        'await page.goto(baseURL, { waitUntil: "networkidle", timeout: 120000 });',
        'await page.goto(baseURL, { waitUntil: "domcontentloaded", timeout: 120000 });',
        1,
    )
    text = text.replace(
        'const page = await browser.newPage({ viewportSize: viewport, reducedMotion: "reduce" });',
        'const page = await browser.newPage({ viewport, reducedMotion: "reduce" });',
        1,
    )
    write(path, text)


def patch_tests() -> None:
    path = "tests/test_native_phase_controller_contract.py"
    text = read(path)
    if "test_behavior_plan_hash_is_resealed_after_skill_and_mutation_contracts" not in text:
        text += '''


def test_behavior_plan_hash_is_resealed_after_skill_and_mutation_contracts() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")
    proof_gate_position = source.index('behavior_plan["proofGates"] = sorted')
    hash_position = source.index('behavior_plan["planHash"] = canonical_hash', proof_gate_position)
    hook_position = source.index('hook_runner.run(\n        "plan.compiled"', hash_position)
    assert proof_gate_position < hash_position < hook_position
    assert 'event_stream.emit(\n        "proof.sealed"' in source
'''
    write(path, text)

    ui_path = "tests/test_native_evolution_ui_contract.py"
    ui = read(ui_path)
    if "test_browser_capture_uses_supported_viewport_and_nonblocking_load_state" not in ui:
        ui += '''


def test_browser_capture_uses_supported_viewport_and_nonblocking_load_state() -> None:
    capture = (ROOT / "scripts" / "capture_native_evolution.mjs").read_text(encoding="utf-8")
    assert "browser.newPage({ viewport, reducedMotion" in capture
    assert 'waitUntil: "domcontentloaded"' in capture
    assert "viewportSize" not in capture
'''
    write(ui_path, ui)


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "apply_neyvia_native_breakthrough.py"))
    namespace["main"]()
    text = AGENT.read_text(encoding="utf-8")
    text = patch_turn_budget(text)
    text = patch_plan_seal(text)
    text = patch_phase_receipt_directory(text)
    text = patch_final_proof_seal(text)
    ast.parse(text, filename=str(AGENT))
    AGENT.write_text(text, encoding="utf-8")
    patch_branding()
    patch_browser_capture()
    patch_tests()
    print("NEYVIA_NATIVE_BREAKTHROUGH_V2_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
