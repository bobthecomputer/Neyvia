"""Real disposable-Git outcomes for path policy and changed-line admission."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .contract_diff import changed_lines
from .contract_coverage import classify, model
from .contract_measurements import admission, digest, measured_record


IDENTITY = "p22.path-policy-outcomes"


def path_policy_classification(root):
    """Exercise actual Git changes, then check policy and admission decisions."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    local_scratch = root
    if not local_scratch.is_relative_to(Path('D:/NeyviaRuns/P22').resolve()):
        raise ValueError('Path-policy fixtures belong under D:/NeyviaRuns/P22')
    local_scratch.mkdir(parents=True, exist_ok=True)
    timing_path = local_scratch / "path-policy-stage-timing.jsonl"

    def breadcrumb(stage, **details):
        row = {"stage": stage, "elapsedMs": round((time.perf_counter() - started) * 1000, 2), **details}
        with timing_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()

    timing_path.write_text("", encoding="utf-8")
    breadcrumb("fixture_start")
    result = None
    try:
        with tempfile.TemporaryDirectory(prefix="path-policy-git-", dir=local_scratch) as temporary:
            repo = Path(temporary)

            def git(*args, input_bytes=None):
                label = " ".join(args[:2])
                breadcrumb("git_call_start", command=label)
                git_started = time.perf_counter()
                try:
                    output = subprocess.run(
                        ["git", "-C", str(repo), *args], check=True,
                        input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    ).stdout
                except Exception as error:
                    breadcrumb("git_call_failed", command=label,
                               durationMs=round((time.perf_counter() - git_started) * 1000, 2),
                               error=type(error).__name__)
                    raise
                breadcrumb("git_call_complete", command=label,
                           durationMs=round((time.perf_counter() - git_started) * 1000, 2))
                return output

            template = local_scratch / "empty-git-template"
            template.mkdir(exist_ok=True)
            breadcrumb("git_setup_start")
            git("init", "-q", f"--template={template}")
            git("config", "user.name", "P22 local verifier")
            git("config", "user.email", "p22-local@example.invalid")
            breadcrumb("git_setup_complete")

            filler = "x" * 64
            changed_names = [f"src/changed-{index:04}-{filler}.py" for index in range(400)]
            aux_names = ["src/space 雪.py", "src/deleted-lines.py", "src/deleted-file.py",
                         "assets/owned.bin", "src/new file.py"]
            unicode_path = repo / "src" / "space 雪.py"
            deleted_line_path = repo / "src" / "deleted-lines.py"
            deleted_path = repo / "src" / "deleted-file.py"
            binary_path = repo / "assets" / "owned.bin"
            added_path = repo / "src" / "new file.py"

            # Represent the 400 long-path files as real tree entries that all
            # point at shared Git blobs. This exercises real Git diffs/pathspec
            # batching without hundreds of per-file filesystem writes.
            breadcrumb("initial_writes_start", pathCount=4)
            unicode_path.parent.mkdir(parents=True, exist_ok=True)
            unicode_path.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
            deleted_line_path.write_text("keep = 1\nremove_a = 2\nremove_b = 3\n", encoding="utf-8")
            deleted_path.write_text("removed = True\n", encoding="utf-8")
            binary_path.parent.mkdir(parents=True, exist_ok=True)
            binary_path.write_bytes(b"\0before")
            breadcrumb("initial_writes_complete", pathCount=4)

            blob_before = git("hash-object", "-w", "--stdin", input_bytes=b"value = 1\n").decode("ascii").strip()
            blob_after = git("hash-object", "-w", "--stdin", input_bytes=b"value = 2\n").decode("ascii").strip()
            git("add", "--", *aux_names[:-1])
            initial_index = "".join(f"100644 {blob_before}\t{name}\0" for name in changed_names).encode("utf-8")
            breadcrumb("baseline_git_start", indexedLongPaths=len(changed_names))
            git("update-index", "--add", "-z", "--index-info", input_bytes=initial_index)
            base_tree = git("write-tree").decode("ascii").strip()
            base = git("commit-tree", base_tree, "-m", "fixture baseline").decode("ascii").strip()
            git("update-ref", "HEAD", base)
            breadcrumb("baseline_git_complete", indexedLongPaths=len(changed_names))

            second_index = "".join(f"100644 {blob_after}\t{name}\0" for name in changed_names).encode("utf-8")
            git("update-index", "--add", "-z", "--index-info", input_bytes=second_index)
            second_tree = git("write-tree").decode("ascii").strip()
            second = git("commit-tree", second_tree, "-p", base, "-m", "fixture changed long paths").decode("ascii").strip()
            git("update-ref", "HEAD", second)

            breadcrumb("changed_writes_start", pathCount=4)
            unicode_path.write_text("first = 1\nsecond = 3\n", encoding="utf-8")
            deleted_line_path.write_text("keep = 1\n", encoding="utf-8")
            deleted_path.unlink()
            binary_path.write_bytes(b"\0after")
            added_path.write_text("ready = True\n", encoding="utf-8")
            breadcrumb("changed_writes_complete", pathCount=5)

            changed_at = time.perf_counter()
            breadcrumb("changed_lines_committed_start", paths=len(changed_names))
            committed_changes = changed_lines(repo, base, committed_only=True, paths=changed_names)
            committed_ms = round((time.perf_counter() - changed_at) * 1000, 2)
            breadcrumb("changed_lines_committed_complete", durationMs=committed_ms,
                       changedPaths=len(committed_changes))
            changed_at = time.perf_counter()
            breadcrumb("changed_lines_worktree_start", paths=len(aux_names))
            working_changes = changed_lines(repo, base, paths=aux_names)
            working_ms = round((time.perf_counter() - changed_at) * 1000, 2)
            breadcrumb("changed_lines_worktree_complete", durationMs=working_ms,
                       changedPaths=len(working_changes))
            changes = {**committed_changes, **working_changes}
            measurement_ms = round(committed_ms + working_ms, 2)
            expected_count = 405
            if len(changes) != expected_count:
                raise AssertionError(f"Git returned {len(changes)} changed paths, expected {expected_count}")
            if changes["src/space 雪.py"].get("lines") != [2]:
                raise AssertionError(f"Unicode or space path lost changed line 2: {changes['src/space 雪.py']}")
            if changes["src/new file.py"].get("lines") != [1]:
                raise AssertionError(f"Untracked addition lost line 1: {changes['src/new file.py']}")
            if changes["assets/owned.bin"].get("lineData") is not False:
                raise AssertionError("Binary change did not request file-level coverage")
            if changes["src/deleted-file.py"].get("status") != "deleted":
                raise AssertionError("True deletion lost its explicit Git deleted status")
            deletion_lines = changes["src/deleted-lines.py"]
            if (deletion_lines.get("lineData") is not False
                    or deletion_lines.get("fallback") != "removed_lines_have_no_new_side_lines"):
                raise AssertionError(f"Surviving file deletion did not request file-level fallback: {deletion_lines}")
            # Mirror the documented 9,000-character cap to prove this fixture
            # crosses several real batches, not merely the OS command-line limit.
            pathspecs = [f":(literal){relative}" for relative in changed_names]
            pathspec_chars = sum(len(value) + 1 for value in pathspecs)
            batch_sizes = []
            current_batch, current_chars = 0, 0
            for pathspec in pathspecs:
                if current_batch and current_chars + len(pathspec) + 1 > 9000:
                    batch_sizes.append(current_batch)
                    current_batch, current_chars = 0, 0
                current_batch += 1
                current_chars += len(pathspec) + 1
            if current_batch:
                batch_sizes.append(current_batch)
            if pathspec_chars <= 32767 or len(batch_sizes) < 4:
                raise AssertionError(
                    f"Fixture did not cross Windows argv and several batch boundaries: "
                    f"{pathspec_chars} literal pathspec characters in {len(batch_sizes)} batches")
            boundary_indices = (0, batch_sizes[0], sum(batch_sizes[:-1]), len(changed_names) - 1)
            boundary_paths = [changed_names[index] for index in boundary_indices]
            if any(changes[path].get("lines") != [1] for path in boundary_paths):
                raise AssertionError(f"Bounded pathspec batches lost changed lines at a batch boundary: {boundary_paths}")
            if measurement_ms >= 60_000:
                raise AssertionError(f"Large pathspec changed-line measurement took {measurement_ms} ms")

            breadcrumb("model_admission_start")
            policy = json.loads((Path(__file__).resolve().parents[2] / "config/contract_path_policy.json").read_text(encoding="utf-8"))
            policy_paths = {
                "generated-projects/demo/src/main.py": "no behaviour",
                "apps/example/dist/app.js": "no behaviour",
                "tools/vendor/library.py": "no behaviour",
                "third_party/lib/source.c": "no behaviour",
                "scripts/scroll_vendor/python/qrcode/main.py": "no behaviour",
                "src/grant_agent/neyvia_scroll.py": "behaviour",
                "config/proofs/resource-outcomes.json": "no behaviour",
                "src/grant_agent/proofs_resource_outcomes.py": "behaviour",
                ".github/workflows/release.yaml": "configuration",
                ".github/workflows/verify.yml": "configuration",
            }
            actual = {path: classify(path, policy)["kind"] for path in policy_paths}
            if actual != policy_paths:
                raise AssertionError(f"Path policy classifications changed: {actual}")

            coverage_model = model(Path(__file__).resolve().parents[2],
                {path: {"status": "changed", "lines": [1], "lineData": True} for path in policy_paths},
                {}, lambda _: set())
            if any(path in coverage_model["origins"] for path, kind in policy_paths.items() if kind == "configuration"):
                raise AssertionError("CI workflow configuration entered behavior coverage origins")
            vendor_path = "scripts/scroll_vendor/python/qrcode/main.py"
            consumer_path = "src/grant_agent/neyvia_scroll.py"
            if vendor_path in coverage_model["origins"] or consumer_path not in coverage_model["origins"]:
                raise AssertionError("Third-party vendor classification masked the Neyvia QR consumer")
            project = Path(__file__).resolve().parents[2]
            consumer_source = (project / consumer_path).read_text(encoding="utf-8")
            if "import qrcode" not in consumer_source or "qrcode.make(" not in consumer_source:
                raise AssertionError("The classified product consumer no longer calls the vendored QR implementation")
            consumer_admission = admission(project,
                {consumer_path: {"status": "changed", "lines": [398], "lineData": True}}, [], {})
            if consumer_path not in consumer_admission["uncovered"] or consumer_path in consumer_admission["coverage"]:
                raise AssertionError("The QR product consumer passed without an actual measured outcome")

            deleted_only = admission(repo, {"src/deleted-file.py": changes["src/deleted-file.py"]}, [], {})
            if deleted_only["uncovered"] or deleted_only["coverage"]:
                raise AssertionError(f"Deleted paths were incorrectly admitted as current behavior obligations: {deleted_only}")
            identity = IDENTITY
            contracts = {identity: {"phase": "post", "claim": "file-level removal outcome"}}
            trace = {"ok": True, "sourceStable": True, "contracts": [identity],
                     "files": {"src/deleted-lines.py": {"lines": [1], "lineData": True,
                                                            "sha256": digest(deleted_line_path)}}}
            receipt_path = repo / ".agent_control/p22/execution.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
            record = measured_record(repo, "path-policy-outcomes", [identity], trace, contracts,
                                     receipt=receipt_path)
            fallback = admission(repo, {"src/deleted-lines.py": deletion_lines}, [record], contracts)
            if fallback["coverage"].get("src/deleted-lines.py") != [identity]:
                raise AssertionError(f"File-level measurement did not cover removed-line fallback: {fallback}")

            result = {
            "status": "passed", "changedPaths": len(changes),
            "changedLineMeasurementMs": measurement_ms,
            "committedChangedLineMeasurementMs": committed_ms,
            "workingTreeChangedLineMeasurementMs": working_ms,
                "unicodeSpacePath": {"path": "src/space 雪.py", "changedLines": changes["src/space 雪.py"]["lines"]},
                "untrackedAddition": changes["src/new file.py"],
                "binaryFileLevelFallback": changes["assets/owned.bin"],
                "survivingDeletedLines": {"change": deletion_lines, "admittedBy": fallback["coverage"]["src/deleted-lines.py"]},
                "deletedPathExempt": {"status": "deleted", "uncovered": deleted_only["uncovered"]},
                "pathPolicyKinds": actual,
                "workflowExcludedFromBehaviorOrigins": True,
                "thirdPartyQrcode": {"path": vendor_path, "kind": actual[vendor_path],
                                     "excludedFromBehaviorOrigins": vendor_path not in coverage_model["origins"]},
                "productQrcodeConsumer": {"path": consumer_path, "kind": actual[consumer_path],
                                          "behaviorOrigin": consumer_path in coverage_model["origins"],
                                          "uncoveredWithoutMeasuredOutcome": consumer_path in consumer_admission["uncovered"]},
                "boundedPathspecBoundary": {
                    "fixturePaths": len(changed_names),
                    "literalPathspecCharacters": pathspec_chars,
                    "windowsCommandLineLimit": 32767,
                    "batchLimitCharacters": 9000,
                    "actualBatchCountExpected": len(batch_sizes),
                    "batchSizes": batch_sizes,
                    "firstAndLastWitnessPaths": [changed_names[0], changed_names[-1]],
                    "crossBatchWitnessPaths": boundary_paths,
                    "allWitnessChangedLines": [changes[path]["lines"] for path in boundary_paths],
                },
                "scope": "actual local Git commits and worktree changes; no network or provider calls",
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            }
            breadcrumb("model_admission_complete", deletedPathAdmitted=not deleted_only["uncovered"], consumerStillUncovered=consumer_path in consumer_admission["uncovered"])
            breadcrumb("journey_result_ready", changedPaths=len(changes), resultStatus=result["status"])

        breadcrumb("temporary_fixture_cleanup_complete")
        breadcrumb("journey_return", status=result["status"])
        return result
    except Exception as error:
        breadcrumb("fixture_failed", error=type(error).__name__, message=str(error)[:300])
        raise


def self_check(root):
    from .contract_gate import wants
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(IDENTITY):
        try:
            result = path_policy_classification(root / "fixture")
            cases.append({"id": IDENTITY, "contracts": [IDENTITY], "ok": True, "observed": result})
        except Exception as error:
            cases.append({"id": IDENTITY, "contracts": [IDENTITY], "ok": False, "error": str(error)})
    report = {"schema": "neyvia.p22.path-policy-outcomes.v1", "area": "path-policy-outcomes",
              "ok": bool(cases) and all(row["ok"] for row in cases), "cases": cases,
              "contracts": [IDENTITY] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    receipt = Path("D:/NeyviaRuns/P22/path-policy-outcomes/outcomes.json")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**report, "receipt": str(receipt)}
