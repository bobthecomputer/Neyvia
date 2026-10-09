"""C7 contract for fail-closed static web source reachability."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from .contract_web_reach import CLASSIFICATION, ReachabilityError, _JSImportParser, analyze, is_fresh


CONTRACT = "p22.static-web-reach"
CONTRACTS = (CONTRACT,)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exercise(scratch: str | Path) -> dict:
    """Prove graph precision and invalidation on tiny disposable source trees."""
    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="web-reach-", dir=scratch) as temporary:
        repo = Path(temporary)
        helper = Path(__file__).resolve().parents[2] / "scripts" / "p22_js_imports.cjs"
        (repo / "scripts").mkdir()
        shutil.copyfile(helper, repo / "scripts" / helper.name)
        js_parser = _JSImportParser(repo)
        source = repo / "src"
        source.mkdir()
        entry = source / "A.jsx"
        child = source / "B.js"
        disconnected = source / "C.js"
        entry.write_text('import "./B.js";\nexport const mounted = true;\n', encoding="utf-8")
        child.write_text("export const value = 7;\n", encoding="utf-8")
        disconnected.write_text("export const isolated = true;\n", encoding="utf-8")
        outcome = "fixture.passing-journey"
        journey = {outcome: {"status": "PASS", "sourceBindings": {"src/A.jsx": _sha(entry)},
                             "entries": ["src/A.jsx"]}}

        receipt = analyze(repo, journey, _js_parser=js_parser)
        expected_reached = {"src/A.jsx", "src/B.js"}
        if (receipt.get("classification") != CLASSIFICATION
                or set(receipt.get("files", {})) != expected_reached
                or receipt["files"]["src/B.js"]["journeyIDs"] != [outcome]
                or "src/C.js" in receipt["files"]
                or not is_fresh(repo, receipt, _js_parser=js_parser)):
            raise AssertionError("PASS entry A must reach imported B, exclude disconnected C, and be fresh")

        failed = {"fixture.failed-journey": {"status": "FAIL", "sourceBindings": {"src/A.jsx": _sha(entry)},
                                              "entries": ["src/A.jsx"]}}
        failed_result = analyze(repo, failed, _js_parser=js_parser)
        if failed_result.get("files") != {} or failed_result.get("journeys") != {}:
            raise AssertionError("A failed journey contributed static reachability")

        child.write_text("export const value = 8;\n", encoding="utf-8")
        if is_fresh(repo, receipt, _js_parser=js_parser):
            raise AssertionError("An edited transitively reached source left the old graph fresh")

        stale_entry = entry.read_text(encoding="utf-8")
        entry.write_text(stale_entry + "export const changed = true;\n", encoding="utf-8")
        try:
            analyze(repo, journey, _js_parser=js_parser)
        except ReachabilityError:
            pass
        else:
            raise AssertionError("A stale source-bound passing outcome was admitted")

        late_entry = source / "LateEntry.jsx"
        late_entry.write_text('import "./late.js";\n', encoding="utf-8")
        late_journey = {"fixture.late-import": {
            "status": "PASS", "sourceBindings": {"src/LateEntry.jsx": _sha(late_entry)},
            "entries": ["src/LateEntry.jsx"],
        }}
        missing = analyze(repo, late_journey, _js_parser=js_parser)
        if is_fresh(repo, missing, _js_parser=js_parser) is not True or not any(row["specifier"] == "./late.js" for row in missing["unresolved"]):
            raise AssertionError("Missing local import was not reported as an initially fresh unresolved edge")
        (source / "late.js").write_text("export const arrived = true;\n", encoding="utf-8")
        if is_fresh(repo, missing, _js_parser=js_parser):
            raise AssertionError("A newly resolvable local import left the cached graph fresh")

        alias_entry = source / "AliasEntry.jsx"
        alias_entry.write_text('import "@fixture/B.js";\n', encoding="utf-8")
        alias_journey = {"fixture.explicit-alias": {
            "status": "PASS", "sourceBindings": {"src/AliasEntry.jsx": _sha(alias_entry)},
            "entries": ["src/AliasEntry.jsx"],
        }}
        aliases = {"@fixture/": "src"}
        alias_receipt = analyze(repo, alias_journey, aliases=aliases, _js_parser=js_parser)
        if (set(alias_receipt["files"]) != {"src/AliasEntry.jsx", "src/B.js"}
                or not is_fresh(repo, alias_receipt, aliases=aliases, _js_parser=js_parser)
                or is_fresh(repo, alias_receipt, aliases={"@fixture/": "elsewhere"}, _js_parser=js_parser)):
            raise AssertionError("Explicit alias resolution or alias-bound freshness was inconsistent")

        # Babel parses valid regex, JSX, template, escaped-string and module
        # syntax as grammar, so text resembling an import stays inert.
        parser_entry = source / "ParserFixture.jsx"
        parser_entry.write_text(r'''import "./B.js";
const fake = /import\s+["']\.\/C\.js["']/;
const copy = "Paul's escaped\\n setup";
const view = <span title="it's fine">{`${copy} ready`}</span>;
export { value as forwarded } from "./D.js";
void import("./E.js");
void import(runtimeChunk);
const common = require("./F.cjs");
''', encoding="utf-8")
        (source / "D.js").write_text("export const value = 1;\n", encoding="utf-8")
        (source / "E.js").write_text("export const lazy = 1;\n", encoding="utf-8")
        (source / "F.cjs").write_text("module.exports = 1;\n", encoding="utf-8")
        parser_journey = {"fixture.babel-parser": {
            "status": "PASS", "sourceBindings": {"src/ParserFixture.jsx": _sha(parser_entry)},
            "entries": ["src/ParserFixture.jsx"],
        }}
        parser_receipt = analyze(repo, parser_journey, _js_parser=js_parser)
        parser_expected = {"src/ParserFixture.jsx", "src/B.js", "src/D.js", "src/E.js", "src/F.cjs"}
        parser_unresolved = parser_receipt["unresolved"]
        if (set(parser_receipt["files"]) != parser_expected
                or any(row["specifier"] == "./C.js" for row in parser_unresolved)
                or not any(row["reason"] == "nonliteral-module-specifier" for row in parser_unresolved)
                or parser_receipt["parserBinding"] != {"path": "scripts/p22_js_imports.cjs", "sha256": _sha(repo / "scripts" / helper.name)}
                or not is_fresh(repo, parser_receipt, _js_parser=js_parser)):
            raise AssertionError("Babel parser mishandled JSX/regex/string syntax or omitted a static import edge")
        helper_copy = repo / "scripts" / helper.name
        helper_copy.write_text(helper_copy.read_text(encoding="utf-8") + "\n// changed parser binding\n", encoding="utf-8")
        if is_fresh(repo, parser_receipt, _js_parser=js_parser):
            raise AssertionError("Editing the source-bound parser script left the static graph fresh")
        js_parser.close()

        return {
            "reached": sorted(expected_reached),
            "disconnectedExcluded": "src/C.js" not in receipt["files"],
            "failedJourneyNoCredit": failed_result["files"] == {},
            "staleOutcomeRefused": True,
            "transitiveSourceEditInvalidates": True,
            "newLocalEdgeInvalidates": True,
            "explicitAliasFreshnessBound": True,
            "babelParsesRegexJsxTemplates": True,
            "literalExportDynamicImportAndRequireReached": True,
            "nonliteralImportReportedUnresolved": True,
            "parserScriptBoundAndFreshnessChecked": True,
            "classification": CLASSIFICATION,
        }


def self_check(scratch: str | Path) -> dict:
    """Return the strict C7 case envelope expected by the gate adapter."""
    try:
        observed = _exercise(scratch)
        case = {"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed}
    except Exception as error:
        case = {"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                "error": f"{type(error).__name__}: {error}"}
    ok = case["ok"] is True
    return {"ok": ok, "contracts": [CONTRACT] if ok else [], "cases": [case]}
