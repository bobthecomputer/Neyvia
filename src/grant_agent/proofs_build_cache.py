"""Pure C7 invalidation cases for the D-only Vite build cache."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .contract_build_cache import save, load, source_paths


CONTRACT = "p22.build-cache.source-and-artifacts"
_STEP = {"step": "build", "ok": True, "exitCode": 0, "timedOut": False,
         "memoryExceeded": False, "durationMs": 17}


def _prepare(root: Path):
    repo = root / "repo"
    build = root / "build"
    repo.mkdir(parents=True)
    (repo / "web/src").mkdir(parents=True)
    (repo / "web/src/vendor").mkdir()
    (repo / "web/dist").mkdir(parents=True)
    (repo / "web/proof").mkdir(parents=True)
    (repo / "web/data").mkdir(parents=True)
    (repo / "web/public/data").mkdir(parents=True)
    (repo / "web/node_modules/pkg").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "public/fonts").mkdir(parents=True)
    (repo / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (repo / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (repo / "vite.config.mjs").write_text("export default {};\n", encoding="utf-8")
    (repo / "scripts/release-contracts.mjs").write_text("export const release = true;\n", encoding="utf-8")
    (repo / "tsconfig.json").write_text('{"compilerOptions":{}}\n', encoding="utf-8")
    (repo / "public/fonts/ui.woff2").write_bytes(b"font fixture")
    (repo / "web/src/main.js").write_text('document.body.textContent="ok";\n', encoding="utf-8")
    (repo / "web/src/vendor/thirdparty.js").write_text("export const bundled = true;\n", encoding="utf-8")
    (repo / "web/public/data/source.json").write_text('{"bundled":true}\n', encoding="utf-8")
    (repo / "web/dist/ignored.js").write_text("old output\n", encoding="utf-8")
    (repo / "web/proof/ignored.json").write_text('{"proof":true}\n', encoding="utf-8")
    (repo / "web/data/ignored.json").write_text('{"fixture":true}\n', encoding="utf-8")
    (repo / "web/node_modules/pkg/ignored.js").write_text("dependency\n", encoding="utf-8")
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text('<script src="assets/app.js"></script>\n', encoding="utf-8")
    (build / "assets/app.js").write_text('console.log("built");\n', encoding="utf-8")
    receipt = root / "build-receipt.json"
    receipt.write_text(json.dumps({"schema": "fixture.build-receipt.v1", "sourceStable": True,
                                   "steps": [_STEP]}) + "\n", encoding="utf-8")
    cache = root / "cache.json"
    bindings = source_paths(repo)
    return repo, build, cache, receipt, bindings


def _reset_fixture(fixture):
    repo, build, cache, receipt, _bindings = fixture
    (repo / "web/src/main.js").write_text('document.body.textContent="ok";\n', encoding="utf-8")
    (repo / "web/src/new.js").unlink(missing_ok=True)
    (build / "index.html").write_text('<script src="assets/app.js"></script>\n', encoding="utf-8")
    (build / "assets/app.js").write_text('console.log("built");\n', encoding="utf-8")
    receipt.write_text(json.dumps({"schema": "fixture.build-receipt.v1", "sourceStable": True,
                                   "steps": [_STEP]}) + "\n", encoding="utf-8")
    bindings = source_paths(repo)
    save(repo, cache, build, bindings, _STEP, receipt)
    return repo, build, cache, receipt, bindings


def _case_valid_load_and_scope(fixture):
    fixture = _reset_fixture(fixture)
    repo, build, cache, _receipt, bindings = fixture
    loaded = load(repo, cache)
    _require(loaded is not None and loaded["build"] == build.resolve()
             and loaded["sourceBindings"] == bindings
             and "web/dist/ignored.js" not in bindings
             and "web/proof/ignored.json" not in bindings
             and "web/data/ignored.json" in bindings
             and "web/public/data/source.json" in bindings
             and "web/src/vendor/thirdparty.js" in bindings
             and "web/node_modules/pkg/ignored.js" not in bindings,
             "valid cache failed or excluded outputs/proof/data/dependencies entered source inputs")
    return fixture


def _case_source_change(fixture, action):
    fixture = _reset_fixture(fixture)
    repo, _build, cache, _receipt, _bindings = fixture
    source = repo / "web/src/main.js"
    if action == "edit":
        source.write_text("document.body.textContent='changed';\n", encoding="utf-8")
    elif action == "add":
        (repo / "web/src/new.js").write_text("export {};\n", encoding="utf-8")
    else:
        source.unlink()
    _require(load(repo, cache) is None, f"source {action} did not invalidate cache")
    return fixture


def _case_artifact_change(fixture, action):
    fixture = _reset_fixture(fixture)
    repo, build, cache, _receipt, _bindings = fixture
    artifact = build / "assets/app.js"
    if action == "edit":
        artifact.write_text("console.log('edited');\n", encoding="utf-8")
    else:
        artifact.unlink()
    _require(load(repo, cache) is None, f"artifact {action} did not invalidate cache")
    return fixture


def _case_invalid_snapshot_or_build(fixture):
    fixture = _reset_fixture(fixture)
    repo, build, cache, receipt, bindings = fixture
    _expect_refused(lambda: save(repo, Path("C:/outside-build-cache.json"), build,
                                bindings, _STEP, receipt), "cache path outside D evidence root")
    bad_bindings = dict(bindings)
    bad_bindings["web/src/main.js"] = "0" * 64
    _expect_refused(lambda: save(repo, cache, build, bad_bindings, _STEP, receipt),
                    "mismatched source snapshot")
    failed = dict(_STEP)
    failed.update({"ok": False, "exitCode": 1})
    receipt.write_text(json.dumps({"sourceStable": True, "steps": [failed]}) + "\n", encoding="utf-8")
    _expect_refused(lambda: save(repo, cache, build, bindings, failed, receipt), "failed build")
    receipt.write_text(json.dumps({"sourceStable": False, "steps": [_STEP]}) + "\n", encoding="utf-8")
    _expect_refused(lambda: save(repo, cache, build, bindings, _STEP, receipt), "unstable receipt")
    return fixture


def _case_receipt_changed_after_save(fixture):
    fixture = _reset_fixture(fixture)
    repo, _build, cache, receipt, _bindings = fixture
    receipt.write_text(json.dumps({"sourceStable": True, "steps": [{"step": "build", "ok": False,
                                                                       "exitCode": 1}]}) + "\n", encoding="utf-8")
    _require(load(repo, cache) is None, "changed build receipt did not invalidate cache")
    return fixture


def _expect_refused(action, label):
    try:
        action()
    except ValueError:
        return
    raise AssertionError(f"{label} evidence was accepted")


def _root(name):
    base = _CASE_ROOT / f"{name}-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    return base


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


_BASE = Path("D:/NeyviaRuns/P22/build-cache-contract-cases").resolve()
_CASE_ROOT = _BASE
_CASES = (
    ("valid_load_and_exclusion_scope", _case_valid_load_and_scope),
    ("source_edit_invalidates", lambda fixture: _case_source_change(fixture, "edit")),
    ("source_addition_invalidates", lambda fixture: _case_source_change(fixture, "add")),
    ("source_deletion_invalidates", lambda fixture: _case_source_change(fixture, "delete")),
    ("artifact_edit_invalidates", lambda fixture: _case_artifact_change(fixture, "edit")),
    ("artifact_deletion_invalidates", lambda fixture: _case_artifact_change(fixture, "delete")),
    ("source_build_and_receipt_guards", _case_invalid_snapshot_or_build),
    ("receipt_change_invalidates", _case_receipt_changed_after_save),
)


def self_check(root=None, selected=None):
    """Run disposable-file C7 cases; no Node, build, network, or browser."""
    from .contract_gate import wants

    started = time.perf_counter()
    selected_ids = ({selected} if isinstance(selected, str)
                    else set(selected) if selected is not None else {CONTRACT})
    if CONTRACT not in selected_ids or not wants([CONTRACT]):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}
    base = Path(root).resolve() if root else _BASE
    if not base.is_relative_to(Path("D:/NeyviaRuns/P22").resolve()):
        raise ValueError("Build-cache cases may write only under D:/NeyviaRuns/P22")
    global _CASE_ROOT
    _CASE_ROOT = base / "build-cache-contract-cases"
    _CASE_ROOT.mkdir(parents=True, exist_ok=True)
    fixture = _prepare(_root("shared"))
    cases = []
    for name, action in _CASES:
        try:
            fixture = action(fixture)
            cases.append({"id": f"{CONTRACT}.{name}", "contracts": [CONTRACT], "ok": True})
        except Exception as error:
            cases.append({"id": f"{CONTRACT}.{name}", "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    passed = all(case["ok"] for case in cases)
    return {"schema": "neyvia.p22-build-cache.c7.v1", "area": "build-cache",
            "ok": passed, "contracts": [CONTRACT] if passed else [], "cases": cases,
            "durationMs": round((time.perf_counter() - started) * 1000, 3)}
