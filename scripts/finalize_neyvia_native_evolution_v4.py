from __future__ import annotations

import ast
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def patch_spawn_receipt() -> None:
    path = "src/grant_agent/native_spawn_contracts.py"
    text = read(path)
    old = '''        receipt = {
            "schema": SPAWN_RECEIPT_SCHEMA,
            **contract,
            "status": normalized_status,
'''
    new = '''        receipt = {
            **contract,
            "schema": SPAWN_RECEIPT_SCHEMA,
            "status": normalized_status,
'''
    text = replace_once(text, old, new, "spawn receipt schema order")
    write(path, text)


def patch_spawn_evaluator() -> None:
    path = "src/grant_agent/native_spawn_evaluator.py"
    text = read(path)
    anchor = '''    if not receipt.get("contractHash"):
        failures.append("spawn contract hash is missing")
    if not receipt.get("receiptHash"):
        failures.append("spawn receipt hash is missing")
'''
    replacement = '''    supplied_contract_hash = str(receipt.get("contractHash") or "")
    if not supplied_contract_hash:
        failures.append("spawn contract hash is missing")
    else:
        contract_material = {
            "schema": "neyvia.native-spawn-contract/v1",
            "spawnId": receipt.get("spawnId"),
            "parentSessionId": receipt.get("parentSessionId"),
            "childSessionId": receipt.get("childSessionId"),
            "role": receipt.get("role"),
            "task": receipt.get("task"),
            "route": receipt.get("route"),
            "planHash": receipt.get("planHash"),
            "status": "running",
            "createdAt": receipt.get("createdAt"),
            "startedAt": receipt.get("startedAt"),
        }
        contract_material["contractHash"] = _hash(contract_material)
        if contract_material["contractHash"] != supplied_contract_hash:
            failures.append("spawn contract hash does not match the reconstructed contract")
    supplied_receipt_hash = str(receipt.get("receiptHash") or "")
    if not supplied_receipt_hash:
        failures.append("spawn receipt hash is missing")
    else:
        receipt_material = {key: value for key, value in receipt.items() if key not in {"receiptHash", "receiptPath"}}
        if _hash(receipt_material) != supplied_receipt_hash:
            failures.append("spawn receipt hash does not match the receipt")
'''
    text = replace_once(text, anchor, replacement, "spawn hash verification")
    write(path, text)


def patch_spawn_evaluator_test() -> None:
    path = "tests/test_native_spawn_evaluator.py"
    text = read(path)
    old = '''        "contractHash": "contract",
        "receiptHash": "receipt",
        "status": "completed",
'''
    new = '''        "status": "completed",
'''
    text = replace_once(text, old, new, "remove fake hashes")
    old_return = '''    receipt.update(overrides)
    return receipt
'''
    new_return = '''    receipt.update(overrides)
    contract_material = {
        "schema": "neyvia.native-spawn-contract/v1",
        "spawnId": receipt["spawnId"],
        "parentSessionId": receipt["parentSessionId"],
        "childSessionId": receipt["childSessionId"],
        "role": receipt["role"],
        "task": receipt["task"],
        "route": receipt["route"],
        "planHash": receipt["planHash"],
        "status": "running",
        "createdAt": receipt.get("createdAt"),
        "startedAt": receipt.get("startedAt"),
    }
    receipt["contractHash"] = __import__("hashlib").sha256(
        __import__("json").dumps(contract_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt["receiptHash"] = __import__("hashlib").sha256(
        __import__("json").dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipt
'''
    text = replace_once(text, old_return, new_return, "real test hashes")
    # Contract creation includes timestamps; explicitly include them in the fixture.
    text = text.replace(
        '        "status": "completed",\n',
        '        "status": "completed",\n        "createdAt": "2026-08-26T20:00:00Z",\n        "startedAt": "2026-08-26T20:00:00Z",\n',
        1,
    )
    # Mutating the route after sealing must reseal if the test wants to isolate authority logic.
    text = text.replace(
        '''    receipt = _receipt()
    receipt["route"] = {**receipt["route"], "allowMutations": True}
    result = evaluate_spawn_receipt(receipt)
''',
        '''    receipt = _receipt()
    receipt["route"] = {**receipt["route"], "allowMutations": True}
    contract_material = {
        "schema": "neyvia.native-spawn-contract/v1",
        "spawnId": receipt["spawnId"],
        "parentSessionId": receipt["parentSessionId"],
        "childSessionId": receipt["childSessionId"],
        "role": receipt["role"],
        "task": receipt["task"],
        "route": receipt["route"],
        "planHash": receipt["planHash"],
        "status": "running",
        "createdAt": receipt["createdAt"],
        "startedAt": receipt["startedAt"],
    }
    import json
    receipt["contractHash"] = hashlib.sha256(json.dumps(contract_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt["receiptHash"] = hashlib.sha256(json.dumps({k: v for k, v in receipt.items() if k != "receiptHash"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = evaluate_spawn_receipt(receipt)
''',
        1,
    )
    write(path, text)


def patch_checkpoint_integration_test() -> None:
    path = "tests/test_native_checkpoint_integration_contract.py"
    text = read(path)
    text = text.replace('    assert "path", "static guard"\n', '    assert "_checkpoint_argument_paths" in source\n')
    write(path, text)


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v3.py"))
    namespace["main"]()
    patch_spawn_receipt()
    patch_spawn_evaluator()
    patch_spawn_evaluator_test()
    patch_checkpoint_integration_test()
    for relative in (
        "src/grant_agent/native_spawn_contracts.py",
        "src/grant_agent/native_spawn_evaluator.py",
        "tests/test_native_spawn_evaluator.py",
    ):
        ast.parse(read(relative), filename=relative)
    print("NEYVIA_NATIVE_FINALIZED_V4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
