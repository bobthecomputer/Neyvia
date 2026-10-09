"""Build the C7e case denominator from source-bound receipts and declarations."""
import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys
import subprocess

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def generation_signature(source):
    """These two builders assign IDs/contracts in run, not effect callbacks."""
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                or node.name in {'run', 'run_observed', 'blocker'}]
    return hashlib.sha256(ast.dump(ast.Module(body=selected, type_ignores=[]), include_attributes=False).encode('utf8')).hexdigest()


def compatible_history(module_relative, expected_digest):
    """Verify generation equality without treating old effect results as passes."""
    current = (REPO / module_relative).read_text(encoding='utf8')
    signature = generation_signature(current)
    commits = subprocess.check_output(['git', 'log', '-30', '--format=%H', '--', module_relative], cwd=REPO, encoding='utf8').splitlines()
    for commit in commits:
        source = subprocess.check_output(['git', 'show', commit + ':' + module_relative], cwd=REPO, encoding='utf8')
        if hashlib.sha256(source.encode('utf8')).hexdigest() == expected_digest:
            if generation_signature(source) == signature:
                return {'commit': commit, 'historicalModuleSha256': expected_digest,
                        'generationSha256': signature, 'boundary': 'Same case declarations and outer generation; historical effects remain unverified'}
            return None
    return None


def _planned_cases(family, module_name):
    """Extract only reviewed, literal case declarations; never call fixture runners."""
    module = importlib.import_module(module_name)
    source = Path(module.__file__).resolve()
    source_text = source.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if family == "c7d-rendered":
        ids = ast.literal_eval(next(node.value for node in tree.body
                                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "IDS" for t in node.targets)))
        from grant_agent.edge_contracts import CATEGORIES
        return [{"id": f"c7d.native-rendered.{identity}.{category}", "category": category,
                 "contracts": [identity]} for category in CATEGORIES for identity in sorted(ids)], \
               {"path": source.relative_to(REPO).as_posix(), "sha256": digest, "kind": "declared_not_built"}
    if family == "host-actions-completion":
        node = next(node for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "PAIRS" for t in node.targets))
        pairs = ast.literal_eval(node.value)
        return [{"id": f"c7d-host-actions:{identity}:{category}", "category": category,
                 "contracts": [identity]} for identity in sorted(pairs) for category in sorted(pairs[identity])], \
               {"path": source.relative_to(REPO).as_posix(), "sha256": digest, "kind": "declared_not_built"}
    if family == "host-runtime":
        from grant_agent.edge_contracts import CATEGORIES, inventory
        registered = inventory()[1]
        planned = []
        for group, (_, identities, supported) in module.FAMILIES.items():
            bindings = sorted(identities & registered.keys())
            for category in CATEGORIES:
                if category not in supported:
                    continue
                selected = module.ADVERSE_BINDINGS.get((group, category), set(bindings))
                contracts = sorted(set(bindings) & selected)
                if group == "stages":
                    contracts = [identity for identity in contracts
                                 if identity != "d.host.stage-refusal" or category in module.TEXT]
                    if category == "concurrency" and "d.host.stage-parallel" in registered:
                        contracts.append("d.host.stage-parallel")
                if contracts:
                    planned.append({"id": f"host-runtime.{group}.{category}",
                                    "category": category, "contracts": contracts})
        return planned, {"path": source.relative_to(REPO).as_posix(),
                         "sha256": digest, "kind": "declared_not_built"}
    if family == "session-completion":
        from grant_agent.edge_contracts import CATEGORIES, inventory
        registered_contracts = inventory()[1]
        ids_node = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "IDS" for t in node.targets))
        if not isinstance(ids_node, ast.SetComp) or not isinstance(ids_node.elt, ast.BinOp):
            raise ValueError("Unsupported session IDS declaration")
        prefix = ast.literal_eval(ids_node.elt.left)
        generator = ids_node.generators[0]
        values = ast.literal_eval(generator.iter)
        ids = {prefix + value for value in values}
        intended = {identity: set(CATEGORIES) for identity in ids}
        for node in tree.body:
            if not isinstance(node, ast.For) or not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Attribute) or node.iter.func.attr != "items":
                continue
            try:
                mapping = ast.literal_eval(node.iter.func.value)
            except (ValueError, TypeError):
                continue
            for suffix, categories in mapping.items():
                intended[prefix + suffix] = set(categories.split())
        planned = [{"id": f"c7d-sessions:{identity}:{category}", "category": category,
                    "contracts": [identity]} for identity in sorted(ids & registered_contracts.keys())
                   for category in CATEGORIES if category in intended[identity]
                   if module.blocker(registered_contracts[identity], category) is None]
        return planned, \
               {"path": source.relative_to(REPO).as_posix(), "sha256": digest, "kind": "declared_not_built"}
    raise ValueError("No planned case declaration extractor for " + family)


def build_inventory(proofs_root=None):
    from grant_agent.edge_fixture_catalog import BUILDERS
    from grant_agent.proof_contracts import source_digest

    proofs_root = Path(proofs_root or REPO / ".agent_control/proofs/c7").resolve()
    proofs_root.relative_to((REPO / ".agent_control/proofs/c7").resolve())
    family_cases = {}
    digest_cache = {}

    def source_current(raw):
        for name, expected in raw.get('sourceBindings', {}).items():
            if name not in digest_cache:
                source = (REPO / name).resolve()
                source.relative_to(REPO)
                digest_cache[name] = source_digest(source) if source.is_file() else None
            if digest_cache[name] != expected:
                return False
        return bool(raw.get('sourceBindings'))
    for family, module_name in BUILDERS.items():
        module = importlib.import_module(module_name)
        module_path = Path(module.__file__).resolve()
        module_relative = module_path.relative_to(REPO).as_posix()
        current_digest = source_digest(module_path)
        matching = []
        historical = []
        for receipt_path in sorted(proofs_root.glob("*/semantic-fixtures/" + family + ".receipt.json")):
            raw_bytes = receipt_path.read_bytes()
            raw = json.loads(raw_bytes)
            if raw.get("family") != family:
                raise ValueError("Receipt filename/family mismatch: " + str(receipt_path))
            if raw.get("sourceStable") is not True:
                continue
            if raw.get("sourceBindings", {}).get(module_relative) == current_digest:
                matching.append((receipt_path, raw_bytes, raw))
            elif family in {'c7d-desktop', 'c7d-control-completion'}:
                historical.append((receipt_path, raw_bytes, raw))
        generation = None
        current_matching = [entry for entry in matching if source_current(entry[2])]
        if current_matching:
            matching = current_matching
        if not matching and historical:
            for receipt_path, raw_bytes, raw in sorted(historical, key=lambda item: item[0].stat().st_mtime, reverse=True):
                generation = compatible_history(module_relative, raw['sourceBindings'][module_relative])
                if generation:
                    matching = [(receipt_path, raw_bytes, raw)]
                    break
        if matching:
            definitions = None
            refs = []
            for receipt_path, raw_bytes, raw in matching:
                rows = raw.get("rows", [])
                current = {row["id"]: {"id": row["id"], "category": row.get("category")} for row in rows}
                if len(current) != len(rows):
                    raise ValueError("Duplicate IDs in historical receipt: " + family)
                if definitions is not None and current != definitions:
                    raise ValueError("Current-source receipts disagree on case inventory: " + family)
                definitions = current
                refs.append({"path": receipt_path.resolve().relative_to(REPO).as_posix(),
                             "sha256": hashlib.sha256(raw_bytes).hexdigest()})
            family_cases[family] = {"family": family,
                                    "cases": [definitions[key] for key in sorted(definitions)],
                                    "casesTotal": len(definitions), "plannedCasesTotal": 0,
                                    "receipts": refs, "moduleSource": {"path": module_relative, "sha256": current_digest}}
            if generation:
                family_cases[family]['inventoryGeneration'] = generation
        elif family in {"c7d-rendered", "session-completion", "host-actions-completion", "host-runtime"}:
            cases, declaration = _planned_cases(family, module_name)
            family_cases[family] = {"family": family, "cases": cases,
                                    "casesTotal": len(cases), "plannedCasesTotal": len(cases),
                                    "plannedSource": declaration, "receipts": [],
                                    "moduleSource": {"path": module_relative, "sha256": current_digest}}
        else:
            raise ValueError("No receipt bound to current family source: " + family)

    all_ids = [case["id"] for item in family_cases.values() for case in item["cases"]]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Case IDs collide across registered families")
    authority_path = REPO / "scripts/evidence/C7d-authority.json"
    authority_bytes = authority_path.read_bytes()
    authority = json.loads(authority_bytes)
    for family, field in (("scheduler", "originalAuthorityBlockers"),
                          ("c7d-control-completion", "additionalAuthorityBlockers")):
        rows = authority[field]
        if len(rows) != 8:
            raise ValueError("Expected exactly eight authority cases: " + field)
        family_cases[family]["authorityCases"] = [{"contract": row["contract"], "category": row["category"],
                                                    "neededAuthority": row.get("neededAuthority")} for row in rows]
    for family in set(family_cases) - {"scheduler", "c7d-control-completion"}:
        family_cases[family]["authorityCases"] = []
    return {"schema": "neyvia.c7e-case-inventory.v1", "historyOnly": True,
            "families": [family_cases[name] for name in BUILDERS],
            "fixtureCasesTotal": sum(item["casesTotal"] for item in family_cases.values()),
            "authorityCasesTotal": 16,
            "casesTotal": sum(item["casesTotal"] for item in family_cases.values()) + 16,
            "authoritySha256": hashlib.sha256(authority_bytes).hexdigest(),
            "boundary": "Historical receipt IDs establish built inventory only. They do not establish current passes; declarations without receipts remain planned and unbuilt."}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proofs-root", type=Path, default=REPO / ".agent_control/proofs/c7")
    parser.add_argument("--output", type=Path, default=REPO / "scripts/evidence/C7e-case-inventory.json")
    args = parser.parse_args()
    target = args.output.resolve()
    target.relative_to((REPO / "scripts/evidence").resolve())
    inventory = build_inventory(args.proofs_root)
    target.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "families": len(inventory["families"]),
                      "fixtureCasesTotal": inventory["fixtureCasesTotal"],
                      "authorityCasesTotal": inventory["authorityCasesTotal"],
                      "casesTotal": inventory["casesTotal"],
                      "plannedCasesTotal": sum(item["plannedCasesTotal"] for item in inventory["families"])}))


if __name__ == "__main__":
    main()
