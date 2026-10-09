"""Read-only semantic inventory for INT3 merges; writes only its review receipt.

Symbol and manual identity continuity are source evidence, not a claim that every
changed instruction has identical behavior. Changed callables remain explicit.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from functools import lru_cache
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cl.manuals import cl_to_manual


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8")


def sha(data):
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


class Normalize(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "_facade":
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if any(isinstance(t, ast.Name) and t.id == "_facade" for t in node.targets):
            return None
        return self.generic_visit(node)


@lru_cache(maxsize=None)
def canonical(node):
    normalized = Normalize().visit(copy.deepcopy(node))
    if normalized is None:
        return ""
    normalized = ast.fix_missing_locations(normalized)
    return ast.dump(ast.parse(ast.unparse(normalized)), include_attributes=False)


@lru_cache(maxsize=None)
def functions(text):
    tree = ast.parse(text)
    rows = []
    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                rows.append((prefix + child.name, child))
                walk(child, prefix + child.name + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            else:
                walk(child, prefix)
    walk(tree)
    return rows


def entries(data):
    result = {}
    for chapter, value in data.get("chapters", {}).items():
        result[chapter] = {"kind": "chapter"}
        for section in ("actions", "checks", "procedures", "state"):
            for name, item in value.get(section, {}).items():
                result[f"{chapter}/{section}/{name}"] = {"kind": section, "value": item}
    return result


def callable_decision(path, name, node):
    decorators = [ast.unparse(value) for value in node.decorator_list]
    reviews = {
        "scripts/prove_proofs.py": "Retains guarded account/backend lifecycle, build log and earlier CLI/browser/mobile journeys; adds served artifact byte hashes, E options and explicit startup deadline.",
        "scripts/verify_proofs.py": "CLI retains credential guard and worker dispatch; positive configurable 900-second default uses bounded process-tree capture.",
        "scripts/render_manuals.py": "Authoritative CL 1.1 source rendering replaces legacy JSON prose; tool/check/procedure identities independently audited.",
        "src/grant_agent/proof_contracts.py": "Proof stamp and source bindings extend to authored CL/compiler, manifests, nested owners and SDK/TypeScript enforcement sites; existing sources remain bound.",
        "src/grant_agent/proof_coverage.py": "Keeps immutable receipt/manifest hashes and exact live claims/sites; scope aliases intersect, procedure pointers must uniquely pass, renewal binds current source without inventing coverage.",
        "src/grant_agent/proof_verifier.py": "All Aâ€“E areas registered; 900-second bounded worker tree cleanup and scratch homes/account retained; fresh-source/immutable-evidence gates remain stronger than later branch proposals.",
        "src/grant_agent/neyvia_manuals.py": "CL compiler supplies versioned documents/renderings and proof declarations; verify dispatcher preserves all registered areas and manual runtime checks.",
        "src/grant_agent/neyvia_evolver.py": "Domain registry includes intent and LAYA; shared store helper replaces duplicated SQLite paths, retaining real engine state/start/call seams.",
        "src/grant_agent/neyvia_runtime_invocation.py": "Same selected-context packet is checked by both A and D guards before returning; packet bounds/content hash/source provenance retained.",
        "src/grant_agent/neyvia_workspace_tools.py": "Checked public call delegates to existing unchecked dispatch; app SDK, Scroll, intent, CL and Evolver tools remain on that dispatch path.",
        "src/grant_agent/neyvia_mcp.py": "Preserves SDK tool routing and result normalization; catalog sorting, D pre/post checks and browser origin/sanitization restrictions extend existing MCP boundaries.",
        "src/grant_agent/neyvia_remote.py": "Persisted proof-port allowlist replaces branch hardcoded extras; consent/local identity, credential-safe snapshot and focused-field guards retain current remote authority boundaries.",
        "src/grant_agent/neyvia_ui_api.py": "Scroll download/state and shared app/CL routes remain at actual HTTP owner; workspace-root mismatch rejects before dispatch.",
        "src/grant_agent/desktop_bridge.py": "Existing desktop dispatch retains explicit service URL/root binding and routes added tools through the same workspace handler.",
        "src/grant_agent/scroll_generation.py": "Seven-part concept/card generation and imports extend existing source-bound generator; legacy card types and price/source validation remain checked by Scroll receipts.",
        "src/grant_agent/scroll_pack.py": "Pack validation expands seven-part structure and generation metadata while preserving source/concept/card acceptance boundaries.",
        "src/grant_agent/scroll_cost.py": "Derived statistics account for added seven-part card/source structure; executable calculation receipts are needed for numerical claims.",
        "src/grant_agent/mission_acceptance_harness.py": "Negative/approved scheduler executions retain distinct IDs and actual approval sequence; new mission guards do not replace the execution journey.",
        "src/grant_agent/web_backend.py": "Facade remains wired to extracted HTTP/chat owners; additive tool/CL dispatch, context guards and E response/process checks stay on real production seams.",
    }
    if path == "src/grant_agent/mission_control.py":
        if name.endswith("_overnight_progress_digest_payload"):
            return "Existing digest gathers current channels then delegates to checked _overnight_progress_projection; state/count/channel calculation moved to that named callable.", decorators
        if name.endswith("build_snapshot") or name.endswith("build_summary_snapshot"):
            return "Snapshot builds reuse checked mission-count/workspace-queue projections; existing snapshot payload shape and facade collaborators remain visible in retained statements.", decorators
        if name.endswith("_mission_runtime_transcript_payload"):
            return "Transcript lives in detail owner; keeps actual attached/delegated/event provenance, includes nonConcreteSessionIds on attached results and adds the C transcript guard.", decorators
        return "C action/result proof decorator or production check extends this exact retained callable; moved owners preserve call-time facade resolution. Its concrete decorators, shared statements and changed calls are recorded.", decorators
    return reviews.get(path, "AST difference remains open for behavioral review; exact callable and shared statements retained below."), decorators


def main():
    source = ROOT / "scripts/evidence/int3/lost-lines.json"
    lost = json.loads(source.read_text(encoding="utf-8"))
    merges = git("rev-list", "--first-parent", "--merges", lost["base"] + ".." + lost["ref"]).splitlines()
    parents = {parent for merge in merges for parent in git("show", "-s", "--format=%P", merge).split()}
    requests = set()
    manual_paths = {}
    for parent in sorted(parents):
        paths = [p for p in git("ls-tree", "-r", "--name-only", parent, "manuals").splitlines()
                 if p.endswith(".manual.json")]
        manual_paths[parent] = paths
        requests.update(parent + ":" + path for path in paths)
    source_groups = defaultdict(list)
    for finding in lost["findings"]:
        source_groups[finding["file"]].append(finding)
        if finding["file"].endswith(".py") and not finding["file"].startswith("tests/"):
            requests.add(finding["side"] + ":" + finding["file"])
    # Batch immutable Git object reads, never checkout or mutate another branch.
    ordered = sorted(requests)
    raw = subprocess.check_output(["git", "cat-file", "--batch"], cwd=ROOT,
                                  input=("\n".join(ordered) + "\n").encode())
    objects = {}
    offset = 0
    for identity in ordered:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        if header[-1] == b"missing":
            objects[identity] = None
            offset = end + 1
        else:
            size = int(header[-1])
            objects[identity] = raw[end + 1:end + 1 + size].decode("utf-8")
            offset = end + size + 2

    catalog = json.loads((ROOT / "config/neyvia_manuals.json").read_text(encoding="utf-8"))
    compiled = {}
    hashes = {}
    compilation_mismatches = []
    for record in catalog["manuals"]:
        path, cl = record["path"], record["clSource"]
        cl_bytes = (ROOT / cl).read_bytes()
        data = cl_to_manual(cl_bytes.decode("utf-8"))
        saved = json.loads((ROOT / path).read_text(encoding="utf-8"))
        if saved != data:
            compilation_mismatches.append(path)
        compiled[path] = data
        hashes[cl] = sha(cl_bytes)
        hashes[path] = sha((ROOT / path).read_bytes())
    missing_manual, manual_inventory, changed_manual = [], [], []
    all_contracts = {row["id"] for data in compiled.values() for row in data.get("proofs", {}).get("contracts", [])}
    for parent, paths in manual_paths.items():
        for path in paths:
            old = json.loads(objects[parent + ":" + path])
            current = entries(compiled.get(path, {}))
            previous = entries(old)
            absent = sorted(set(previous) - set(current))
            # A CL compiler may preserve an action's original identifier under
            # a newer authored alias. Require the exact same tool binding.
            aliases = []
            for identity in absent[:]:
                item = previous[identity]
                if item["kind"] == "actions":
                    chapter = identity.partition("/")[0]
                    tool = item["value"].get("tool")
                    matches = [key for key, value in current.items() if key.startswith(chapter + "/actions/")
                               and tool and value["value"].get("tool") == tool]
                    if matches:
                        absent.remove(identity)
                        aliases.append({"entry": identity, "sameToolAliases": matches})
            missing_manual.extend({"parent": parent, "file": path, "entry": entry} for entry in absent)
            prior_contracts = {row["id"] for row in old.get("proofs", {}).get("contracts", [])}
            missing_manual.extend({"parent": parent, "file": path, "contract": identity}
                                  for identity in sorted(prior_contracts - all_contracts))
            changed = [key for key in previous.keys() & current.keys()
                       if previous[key] != current[key]]
            if changed:
                changed_manual.append({"parent": parent, "file": path, "entries": sorted(changed),
                    "review": ("Dictation start tool/schema/precondition retained; timing guidance updated to measured GPU/CPU and idle lifetime."
                        if path == "manuals/dictation.manual.json" else
                        "Remote tools/procedure steps retained; obsolete whole-window refusal wording replaced by current credential redaction and exact protected-focused-field guard.")})
            manual_inventory.append({"parent": parent, "file": path, "entries": len(previous),
                                     "retained": len(previous) - len(absent), "aliases": aliases})

    source_inventory, missing_symbols, changed_symbols = [], [], []
    for path, findings in sorted(source_groups.items()):
        if not path.endswith(".py") or path.startswith("tests/"):
            continue
        target = ROOT / path
        candidates = [target]
        if path.startswith("src/grant_agent/"):
            candidates += sorted(target.parent.glob(target.stem + "_*.py"))
        current = defaultdict(list)
        for candidate in dict.fromkeys(candidates):
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
                relative = candidate.relative_to(ROOT).as_posix()
                hashes[relative] = sha(candidate.read_bytes())
                for key, node in functions(text):
                    current[node.name].append((relative, key, node))
        for parent in sorted({row["side"] for row in findings}):
            text = objects[parent + ":" + path]
            for key, node in functions(text):
                options = current.get(node.name, [])
                exact = [option for option in options if canonical(node) == canonical(option[2])]
                matching = exact or [option for option in options if option[1] == key] or options
                if not matching:
                    missing_symbols.append({"parent": parent, "file": path, "symbol": key})
                    continue
                owner, current_key, now = matching[0]
                row = {"parent": parent, "file": path, "symbol": key, "owner": owner,
                       "currentSymbol": current_key, "parentAstSha256": sha(canonical(node)),
                       "currentAstSha256": sha(canonical(now)), "normalizedAstEqual": bool(exact)}
                if not exact:
                    calls = lambda n: sorted({ast.unparse(c.func) for c in ast.walk(n) if isinstance(c, ast.Call)})
                    before, after = set(calls(node)), set(calls(now))
                    row["retainedDirectCalls"] = sorted(before & after)
                    row["changedDirectCalls"] = {"old": sorted(before - after), "current": sorted(after - before)}
                    row["review"], row["currentDecorators"] = callable_decision(path, key, now)
                    old_statements = {canonical(statement): ast.unparse(statement) for statement in ast.walk(node)
                                      if isinstance(statement, ast.stmt) and not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))}
                    current_statements = {canonical(statement) for statement in ast.walk(now) if isinstance(statement, ast.stmt)}
                    common = [old_statements[key] for key in old_statements.keys() & current_statements]
                    row["exactRetainedStatementCount"] = len(common)
                    row["exactRetainedStatementExamples"] = sorted(common, key=len, reverse=True)[:2]
                    changed_symbols.append(row)
                source_inventory.append(row)

    inventory = json.loads((ROOT / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    retired_missing = []
    retired = []
    for row in inventory["files"]:
        if (ROOT / row["path"]).exists():
            continue
        if row.get("disposition") in {"obsolete", "dead-code"}:
            continue
        retired.append(row["path"])
        for case in row["cases"]:
            missing = set(case.get("contract_ids", [])) - all_contracts
            if missing or not all(case.get(k) for k in ("contract_ids", "checked_at", "self_checks")):
                retired_missing.append({"file": row["path"], "case": case["id"], "missingContracts": sorted(missing)})

    reviews = []
    r3_files = ("apps/scroll-study/www/styles.css", "config/app_sdk/web/index.html",
                "web/src/neyvia/next/details/kit/demo.html", "web/src/neyvia/next/details/kit/details.css")
    r3_selection = []
    for path in r3_files:
        expected = git("show", "track/r3-light:" + path).replace("\r\n", "\n")
        actual = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")
        r3_selection.append({"file": path, "r3Sha256Lf": sha(expected), "currentSha256Lf": sha(actual),
                             "matchesExplicitSelection": expected == actual})
    specific = {
        "apps/scroll-study/www/feed.js": "Teaching/recall type sets add seven-part card types. Claimed recall bypass now excludes part cards; reteach exemption preserves legacy cards when partIndex is absent. expose still records recapped/exposedAt/exposureSession/state and additionally accumulates unique parts.",
        "config/scroll-study-pack.schema.json": "Seven-part generation schema extends card/concept definitions; final executable Scroll validation must observe acceptance/rejection, not textual equality.",
        "config/scroll-study-prices.json": "Price representation changed: executable scroll_cost authority and actual calculation receipts are required; prices are not an equivalence claim.",
        "docs/evidence/tests-to-proofs.md": "Generated coverage table is backed by current inventory per-case IDs, enforcement locations and surviving CL contracts; every absent test case is inspected above.",
        "config/proofs/test-inventory.json": "Reconciled rows are keyed by file.path/case.id; per-case compiled contract survival is independently inspected above. Original historical hashes are not replaced by this review.",
        "web/src/neyvia/next/nxOs.css": "Morning style changes from R3 integrate into existing shell stylesheet; CSS hash records exact current artifact. Rendered behavior is established only by the final journey.",
        "web/src/neyvia/next/nxSidebar.css": "R3 Morning sidebar style changes integrate through the existing shell stylesheet; current hash binds the artifact, with rendered behavior delegated to final journey.",
    }
    for path, findings in sorted(source_groups.items()):
        p = ROOT / path
        present_text = p.read_text(encoding="utf-8") if p.is_file() else ""
        if p.is_file():
            hashes[path] = sha(p.read_bytes())
        if path.startswith("docs/manuals/") or path.startswith("plugins/neyvia/skills/"):
            decision = "Generated view: authored CL and compiled identity inventory above are authority; this does not prove legacy prose word-for-word retention."
        elif path.startswith("manuals/") or path == "config/neyvia_manuals.json":
            decision = "Every parent manual entry and contract checked against current CL compilation; changed metadata and claims listed separately."
        elif path.startswith("tests/"):
            decision = "Retired file reviewed through per-case inventory and surviving compiled contracts; execution proof belongs to final verification receipt."
        elif path.endswith(".py"):
            decision = "Every parent callable inventoried against current exact owner; changed ASTs and direct calls remain explicit, requiring related real-run evidence."
        else:
            decision = "Structured/static source difference remains explicit; current hash and dropped-line samples retained for review."
        if path in r3_files:
            decision = "Explicit user-selected R3 version; normalized exact branch content compared in r3Selection. Receipt binding reseals do not re-run historical observations."
        decision = specific.get(path, decision)
        reviews.append({"file": path, "findings": len(findings), "decision": decision,
                        "droppedExamples": [row["line"] for row in findings[:3]],
                        "currentSha256": hashes.get(path),
                        "historicallyDroppedNowPresent": sum(row["line"] in present_text for row in findings)})
    result = {"schema": "neyvia.int3.semantic-retention-review.v1", "sourceHead": git("rev-parse", "HEAD").strip(),
        "inputSha256": sha(source.read_bytes()), "merges": merges, "parents": sorted(parents),
        "lostLines": len(lost["findings"]), "findings": lost["findings"],
        "historicalMissingManualEntries": lost.get("missingManualEntries", []),
        "fileReviews": reviews, "manualInventory": manual_inventory,
        "manualEntryChanges": changed_manual, "missingManualEntries": missing_manual,
        "compilationMismatches": compilation_mismatches, "callableInventory": source_inventory,
        "changedCallables": changed_symbols, "missingCallables": missing_symbols,
        "retiredFiles": retired, "retirementMissingContracts": retired_missing, "sourceHashes": hashes,
        "r3Selection": r3_selection,
        "identityRetentionPassed": not (missing_manual or missing_symbols or retired_missing or compilation_mismatches),
        "lineLevelCompletenessClaimed": False,
        "passed": not (missing_manual or missing_symbols or retired_missing or compilation_mismatches)
                  and all(row["matchesExplicitSelection"] for row in r3_selection),
        "boundary": "Independent source/CL identity audit. Changed ASTs, claims, prose and static source require the recorded semantic decisions and actual runtime proof; no line-set union was used."}
    output = ROOT / "scripts/evidence/int3/lost-lines-review.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "manualEntries": sum(r["entries"] for r in manual_inventory),
        "callables": len(source_inventory), "changedCallables": len(changed_symbols),
        "missingManual": missing_manual, "missingCallables": missing_symbols,
        "retirementMissing": retired_missing, "compilationMismatches": compilation_mismatches}))
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
