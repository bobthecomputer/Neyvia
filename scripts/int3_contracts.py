"""Reconcile proof migrations by identity while keeping authored CL authoritative."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
SHARES = tuple("track/proofs-" + suffix for suffix in "abcde")
BASE = 'a18870b7602998728859ffcf25c7af6d497e53ea'
HOST_RESOLUTIONS = {"proofs.scratch-isolation": "track/proofs-b",
                    "proofs.retirement-coverage": "track/proofs-e"}


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=REPO, encoding="utf-8")


def object_json(branch, path):
    return json.loads(git("show", branch + ":" + path))


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def combine(left, right, context):
    if left == right:
        return deepcopy(left)
    if isinstance(left, dict) and isinstance(right, dict):
        result = deepcopy(left)
        for key, value in right.items():
            result[key] = combine(result[key], value, context + "." + key) if key in result else deepcopy(value)
        return result
    if isinstance(left, list) and isinstance(right, list):
        return deepcopy(left) + [deepcopy(value) for value in right if value not in left]
    if context.endswith(".proofs.area"):
        return ", ".join(sorted(set(left.split(", ")) | set(right.split(", "))))
    if context.endswith(".proofs.startup.runner"):
        # The integrated dispatcher invokes every registered Python/Node area.
        return "grant_agent.proof_verifier.run_verification"
    raise ValueError("Conflicting structured declaration: " + context)


def resolve_contract(old, incoming):
    if old is None or old == incoming:
        return deepcopy(incoming)
    identity = incoming["id"]
    if identity not in HOST_RESOLUTIONS:
        raise ValueError("Differing manual declaration: " + identity)
    preferred_branch = HOST_RESOLUTIONS[identity] if HOST_RESOLUTIONS[identity] in SHARES else SHARES[-1]
    preferred = next(row for row in object_json(preferred_branch, "manuals/proofs.manual.json")["proofs"]["contracts"]
                     if row["id"] == identity)
    if old["phase"] != preferred["phase"] or incoming["phase"] != preferred["phase"]:
        raise ValueError("Resolved host declaration changed phase: " + identity)
    return deepcopy(preferred)


def deleted_tests():
    return sorted({path for branch in SHARES for path in git(
        "diff", "--name-only", "--diff-filter=D", BASE + "..." + branch).splitlines()
        if path.startswith(("tests/", "web/"))})


def merge_map(write=False):
    inventories = [object_json(branch, "config/proofs/test-inventory.json") for branch in SHARES]
    merged = deepcopy(inventories[0])
    files = {row["path"]: row for row in merged["files"]}
    for inventory in inventories[1:]:
        if inventory["baseline_commit"] != merged["baseline_commit"]:
            raise ValueError("Proof shares have different inventory baselines")
        for incoming in inventory["files"]:
            row = files[incoming["path"]]
            if row["sha256"] != incoming["sha256"]:
                raise ValueError("Original test digest differs: " + row["path"])
            cases = {case["id"]: case for case in row["cases"]}
            if set(cases) != {case["id"] for case in incoming["cases"]}:
                raise ValueError("Original case identities differ: " + row["path"])
            for candidate in incoming["cases"]:
                case = cases[candidate["id"]]
                if candidate.get("contract_ids"):
                    if case.get("contract_ids") and set(case["contract_ids"]) != set(candidate["contract_ids"]):
                        raise ValueError("Conflicting migrated case contracts: " + case["id"])
                    if not case.get("contract_ids"):
                        case.clear()
                        case.update(deepcopy(candidate))
    for row in files.values():
        for field in ("contract_ids", "checked_at", "self_checks"):
            row[field] = sorted({value for case in row["cases"] for value in case.get(field, [])})
        covered = all(case.get("contract_ids") and case.get("checked_at") and case.get("self_checks") for case in row["cases"])
        if row["contract_ids"]:
            row["disposition"] = "covered" if covered else "partial"
            row["reason"] = "Identity-reconciled executable manual contracts; merged source requires fresh revalidation."
    mapped = sum(bool(case.get("contract_ids") and case.get("checked_at") and case.get("self_checks"))
                 for row in files.values() for case in row["cases"])
    total = sum(len(row["cases"]) for row in files.values())
    merged["totals"].update(mapped_case_definitions=mapped, coverage_percent=round(100 * mapped / total, 3),
                            deleted_files=sum(not (REPO / row["path"]).exists() for row in files.values()))
    if write:
        dump(REPO / "config/proofs/test-inventory.json", merged)
        from grant_agent.proof_coverage import render_map
        render_map(merged)
    return merged


def incoming_manuals():
    """Read added chapters and declarations from branch objects, never stale artifacts."""
    result = {}
    for branch in SHARES:
        base = git("merge-base", BASE, branch).strip()
        for line in git("diff", "--name-status", base, branch, "manuals").splitlines():
            status, path = line.split("\t", 1)
            if not path.endswith(".manual.json") or status not in {"A", "M"}:
                continue
            data = object_json(branch, path)
            original = object_json(base, path) if status == "M" else {"chapters": {}}
            entry = result.setdefault(data["id"], {"new": status == "A", "document": deepcopy(data),
                                                  "chapters": {}, "contracts": {}, "proofs": {}, "schemas": {}})
            if status == "A":
                entry["document"] = combine(entry["document"], data, data["id"])
            for name, chapter in data["chapters"].items():
                if name in original["chapters"]:
                    continue
                entry["chapters"][name] = combine(entry["chapters"][name], chapter, data["id"] + "." + name) if name in entry["chapters"] else deepcopy(chapter)
                for action in chapter["actions"].values():
                    key = action["schema"]
                    entry["schemas"][key] = combine(entry["schemas"][key], data["schemas"][key], data["id"] + ".schemas." + key) if key in entry["schemas"] else deepcopy(data["schemas"][key])
            proof = data.get("proofs", {})
            metadata = {key: value for key, value in proof.items() if key != "contracts"}
            entry["proofs"] = combine(entry["proofs"], metadata, data["id"] + ".proofs")
            for contract in proof.get("contracts", []):
                old = entry["contracts"].get(contract["id"])
                entry["contracts"][contract["id"]] = resolve_contract(old, contract)
    return result


def append_source(source, desired, added):
    """Keep existing CL lines; append converted chapters with disjoint type aliases."""
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    lines = source.splitlines()
    header_line = next(index for index, line in enumerate(lines) if line.startswith("-- @manual "))
    header = json.loads(lines[header_line][11:])
    proof = desired.get("proofs")
    if proof is not None:
        header["proofs"] = {key: value for key, value in proof.items() if key != "contracts"}
    extra = []
    if added:
        fragment = {**deepcopy(desired), "chapters": {name: desired["chapters"][name] for name in added}}
        fragment.pop("proofs", None)
        schemas = {action["schema"] for chapter in fragment["chapters"].values() for action in chapter["actions"].values()}
        fragment["schemas"] = {key: value for key, value in desired["schemas"].items() if key in schemas}
        rendered = manual_to_cl(fragment, tool_metadata=header["tool_metadata"])
        used = [int(match) for match in re.findall(r"\bt(\d+)\b", source)]
        offset = max(used, default=0) + 100
        rendered = re.sub(r"\bt(\d+)\b", lambda match: "t" + str(offset + int(match[1])), rendered)
        fragment_lines = rendered.splitlines()
        fragment_header = json.loads(next(line[11:] for line in fragment_lines if line.startswith("-- @manual ")))
        for name, alias in fragment_header["schemas"].items():
            if name not in header["schemas"]:
                header["schemas"][name] = alias
        header["chapters"].update(fragment_header["chapters"])
        header["tool_metadata"].update(fragment_header["tool_metadata"])
        extra = [line for line in fragment_lines if line != "CL 1" and not line.startswith("-- @manual ")
                 and not line.startswith("L " + desired["id"] + " v1 ")]
    lines[header_line] = "-- @manual " + json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    lines = [line for line in lines if not line.startswith("-- @proof ")]
    proof_lines = ["-- @proof " + json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                   for contract in (proof or {}).get("contracts", [])]
    lines[header_line + 1:header_line + 1] = proof_lines
    result = "\n".join(lines + extra) + "\n"
    if cl_to_manual(result) != desired:
        raise ValueError("CL append did not exactly preserve desired manual: " + desired["id"])
    return result


def port_contracts(write=False):
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    pending = {}
    for identity, incoming in incoming_manuals().items():
        path = REPO / "manuals/cl" / (identity + ".cl")
        source = path.read_text(encoding="utf-8") if path.exists() else None
        desired = cl_to_manual(source) if source else deepcopy(incoming["document"])
        for name, schema in incoming["schemas"].items():
            if name not in desired["schemas"]:
                desired["schemas"][name] = schema
        added = []
        amended = []
        for name, chapter in incoming["chapters"].items():
            if name not in desired["chapters"]:
                desired["chapters"][name] = chapter
                added.append(name)
            elif desired["chapters"][name] != chapter:
                if not incoming["new"]:
                    raise ValueError("Authored chapter conflicts with imported chapter: " + identity + "." + name)
                # A later CL source may already own a manual absent at the
                # proof branches' old baseline (notably Settings).
                # Preserve its richer authored chapter while retaining every
                # incoming executable entry, including legacy action aliases.
                current = desired['chapters'][name]
                for family in ('state', 'actions', 'checks', 'procedures', 'judge'):
                    for key, value in chapter.get(family, {}).items():
                        if key in current[family] and current[family][key] != value:
                            raise ValueError('Conflicting executable manual entry: ' + identity + '.' + name + '.' + family + '.' + key)
                        if key not in current[family]:
                            current[family][key] = deepcopy(value)
                            amended.append(name + '.' + family + '.' + key)
        contracts = {row["id"]: row for row in desired.get("proofs", {}).get("contracts", [])}
        for name, contract in incoming["contracts"].items():
            contracts[name] = resolve_contract(contracts.get(name), contract)
        if contracts:
            desired["proofs"] = {**incoming["proofs"], "contracts": list(contracts.values())}
        if source and amended:
            header = json.loads(next(line[11:] for line in source.splitlines() if line.startswith('-- @manual ')))
            text = manual_to_cl(desired, tool_metadata=header['tool_metadata'])
        else:
            text = append_source(source, desired, added) if source else manual_to_cl(desired, tool_metadata={})
        if cl_to_manual(text) != desired:
            raise ValueError("Manual roundtrip differs: " + identity)
        pending[path] = text
    if write:
        for path, text in pending.items():
            path.write_text(text, encoding="utf-8", newline="\n")
    return pending


def check_survival(inventory, sources=None):
    from grant_agent.cl.manuals import cl_to_manual
    live = {}
    pending = sources or {}
    paths = set((REPO / "manuals/cl").glob("*.cl")) | set(pending)
    for path in sorted(paths):
        data = cl_to_manual(pending[path] if path in pending else path.read_text(encoding="utf-8"))
        for contract in data.get("proofs", {}).get("contracts", []):
            if contract["id"] in live:
                raise ValueError("Duplicate compiled proof declaration: " + contract["id"])
            live[contract["id"]] = contract
    rows = {row["path"]: row for row in inventory["files"]}
    count = 0
    for path in deleted_tests():
        row = rows[path]
        if not row["cases"]:
            raise ValueError("Deleted test has no cases: " + path)
        for case in row["cases"]:
            if not case.get("contract_ids") or not case.get("checked_at") or not case.get("self_checks"):
                raise ValueError("Deleted case has incomplete coverage: " + case["id"])
            missing = set(case["contract_ids"]) - live.keys()
            if missing:
                raise ValueError("Deleted case lost compiled contracts: " + case["id"] + " " + str(sorted(missing)))
            count += 1
    return {"deletedFiles": len(deleted_tests()), "deletedCases": count, "compiledContracts": len(live), "survival": True}


def main():
    global SHARES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("merge-map", "port-contracts", "check-survival"))
    parser.add_argument("--write", action="store_true", help="Write reconciled map or authored sources after all checks pass")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument('--through', choices=list('abcde'), default='e')
    args = parser.parse_args()
    SHARES = SHARES[:'abcde'.index(args.through)+1]
    inventory = merge_map()
    if args.mode == "merge-map":
        result = {"mappedCases": inventory["totals"]["mapped_case_definitions"], "deletedFiles": len(deleted_tests())}
        if args.write:
            merge_map(write=True)
    else:
        sources = port_contracts() if args.mode == "port-contracts" else None
        result = check_survival(inventory, sources)
        if args.write and sources:
            for path, text in sources.items():
                path.write_text(text, encoding="utf-8", newline="\n")
    result.update(mode=args.mode, written=args.write, branches=list(SHARES))
    if args.receipt:
        dump(args.receipt.resolve(), result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
