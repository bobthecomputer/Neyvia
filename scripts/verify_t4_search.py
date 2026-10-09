"""Real rg/Python search receipts using disposable workspace files (no pytest)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.research import MAX_FILE_BYTES, search_workspace_bounded, search_workspace_detailed


def verify() -> dict:
    assert shutil.which("rg"), "The real rg executable is required for this receipt."
    checks = []
    with tempfile.TemporaryDirectory(prefix="t4-search-") as scratch:
        workspace = Path(scratch) / "workspace"
        outside = Path(scratch) / "outside"
        workspace.mkdir()
        outside.mkdir()
        (workspace / "src" / "deep").mkdir(parents=True)
        (workspace / "node_modules").mkdir()
        (workspace / "target").mkdir()
        (workspace / "root.py").write_text("Needle root\nneedle two\n", encoding="utf-8")
        (workspace / "src" / "app.py").write_text("Needle source\nnot matched\n", encoding="utf-8")
        (workspace / "src" / "deep" / "nested.py").write_text("Needle deep\n", encoding="utf-8")
        (workspace / "src" / "readme.txt").write_text("Needle text\n", encoding="utf-8")
        (workspace / "node_modules" / "ignored.py").write_text("Needle generated\n", encoding="utf-8")
        (workspace / "target" / "ignored.py").write_text("Needle generated\n", encoding="utf-8")
        (workspace / "binary.py").write_bytes(b"\0Needle binary\n")
        (workspace / "oversize.py").write_bytes(b"Needle oversized\n" + b"x" * MAX_FILE_BYTES)
        (outside / "secret.py").write_text("Needle outside\n", encoding="utf-8")
        link = workspace / "linked"
        if os.name == "nt":
            linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
            assert linked.returncode == 0, linked.stderr
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            for engine in ("rg", "python"):
                report = search_workspace_detailed(workspace, "needle", "**/*.py", engine=engine)
                assert report["engine"] == engine, report
                assert report["complete"] and report["count"] == 4, report
                assert all("outside" not in row["snippet"] and "generated" not in row["snippet"] for row in report["matches"])
                checks.append({"check": "real-engine-confined-glob", "engine": engine, "receipt": report})
                sensitive = search_workspace_detailed(workspace, "Needle", "*.py", case_sensitive=True, engine=engine)
                assert sensitive["count"] == 1 and sensitive["matches"][0]["path"] == "root.py", sensitive
                direct = search_workspace_detailed(workspace, "Needle", "src/*.py", engine=engine)
                assert direct["count"] == 1, direct
                capped = search_workspace_detailed(workspace, "needle", "**/*.py", max_results=1, engine=engine)
                assert capped["count"] == 1 and capped["truncated"] and not capped["complete"], capped
                checks.append({"check": "case-root-glob-directory-glob-result-limit", "engine": engine, "passed": True})
            rows, complete = search_workspace_bounded(workspace, "Needle", max_results=1)
            assert len(rows) == 1 and complete is False
            fallback = search_workspace_detailed(workspace, r"Needle(?= source)", "**/*.py", engine="rg")
            assert fallback["engine"] == "python" and fallback["fallbackReason"] and fallback["count"] == 1, fallback
            checks.append({"check": "unsupported-rg-regex-python-fallback", "receipt": fallback})
            for glob in ("../outside/*.py", str(outside / "*.py"), "src/../../outside/*.py"):
                try:
                    search_workspace_detailed(workspace, "Needle", glob)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Escaping glob was accepted: " + glob)
            try:
                search_workspace_detailed(workspace, "[")
            except re.error:
                pass
            else:
                raise AssertionError("Invalid regex was accepted")
            checks.append({"check": "invalid-regex-and-outside-globs-rejected", "passed": True})
            timed = search_workspace_detailed(workspace, "Needle", time_budget=0, engine="rg")
            assert timed["timedOut"] and not timed["complete"], timed
            (workspace / "evil.txt").write_text("a" * 100000 + "!", encoding="utf-8")
            timed_python = search_workspace_detailed(workspace, "(a+)+$", "evil.txt", time_budget=0.3, engine="python")
            assert timed_python["timedOut"] and not timed_python["complete"], timed_python
            checks.append({"check": "zero-budget-and-catastrophic-regex-timeouts", "receipt": timed_python})
        finally:
            if os.name == "nt":
                os.rmdir(link)  # Remove the fixture junction only, never its target.
            else:
                link.unlink()
    return {"passed": True, "rgExecutable": shutil.which("rg"), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
