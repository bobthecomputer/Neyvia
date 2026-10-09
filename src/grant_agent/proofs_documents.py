"""Fast outcome contracts for study documents (manuals/cl/documents.cl, plan 22).

Each case acts through the same workspace operations the manual exposes, in a
disposable scratch root, and checks what the build produced: the PDF, its log,
its aux records and rendered pixels. One case feeds a broken document and
requires the checks to fail, so a check that always passes cannot hide here.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

BROKEN = r"""\documentclass[course]{neyvia-study}
\studytitle{Broken}
\begin{document}
\maketitle
\studychapter{Wrong order}
\begin{concept}{Reflex first}{}
\begin{reflex}
Cue \ra{} action, see \ref{missing-label}.
\end{reflex}
\begin{definition}
\noindent\hbox{An unbreakable line that is far too long for the text block of the page, and it keeps going past the margin on purpose.}
\end{definition}
\end{concept}
\end{document}
"""


def _require(condition, contract, message):
    if not condition:
        raise AssertionError(contract + ": " + message)


def _text(pdf):
    from .pdf_compat import text
    return text(pdf)


def self_check(root):
    from . import neyvia_documents as tools, study_docs
    started = time.perf_counter()
    root = Path(root) / "documents"
    root.mkdir(parents=True, exist_ok=True)
    tools.study_docs.RUNS = root / "runs"  # builds stay inside the disposable root
    cases = []

    def case(contracts, procedure):
        try:
            detail = procedure()
            cases.append({"contracts": contracts, "ok": True, **(detail or {})})
        except Exception as error:  # the receipt names the failed outcome
            cases.append({"contracts": contracts, "ok": False, "error": f"{type(error).__name__}: {error}"})

    def course():
        made = tools.run(root, "documents.create", {"path": "course.tex", "variant": "course", "title": "Proof course",
                                                    "chapters": ["Sets", "Maps"]})
        _require(made["ok"] and Path(made["tex"]).is_file(), "documents.create.course", "no document written")
        built = tools.run(root, "documents.build", {"path": "course.tex"})
        _require(built["ok"] and built["pages"] >= 4, "documents.create.course", f"build failed: {built.get('errors')}")
        checked = tools.run(root, "documents.check", {"path": "course.tex"})
        _require(checked["ok"], "documents.checks.pass", str([row for row in checked["checks"] if not row["ok"]]))
        blocks = next(row for row in checked["checks"] if row["name"] == "blocks")
        _require(blocks["concepts"] == 2, "documents.create.course", "one concept per chapter expected")
        text = _text(built["pdf"])
        _require("1 DEFINITION / FORMULA" in text and "6 TINY CHANGED EXAMPLE / PRACTICE" in text and "Chapter 2" in text,
                 "documents.create.course", "course labels or chapters missing from the PDF text")
        return {"seconds": built["seconds"], "pages": built["pages"]}
    case(["documents.create.course", "documents.checks.pass"], course)

    def sheet():
        tools.run(root, "documents.create", {"path": "sheet.tex", "variant": "sheet", "title": "Proof sheet", "chapters": ["Sets"]})
        built = tools.run(root, "documents.build", {"path": "sheet.tex"})
        checked = tools.run(root, "documents.check", {"path": "sheet.tex"})
        _require(built["ok"] and checked["ok"], "documents.sheet.variant", "sheet did not build and pass")
        text = _text(built["pdf"])
        _require("METHOD" in text and "REFLEX" in text, "documents.sheet.variant", "sheet lost method or reflex")
        _require("The mistake people make" not in text and "Try:" not in text, "documents.sheet.variant",
                 "sheet printed traps or practice")
        return {"pages": built["pages"]}
    case(["documents.sheet.variant"], sheet)

    def broken():
        (root / "broken.tex").write_text(BROKEN, encoding="utf-8")
        built = tools.run(root, "documents.build", {"path": "broken.tex"})
        checked = tools.run(root, "documents.check", {"path": "broken.tex"})
        _require(built["ok"], "documents.checks.catch", "the broken document should still compile")
        _require(not checked["ok"] and not checked["blocks"] and not checked["references"] and not checked["overfull"],
                 "documents.checks.catch", f"checks missed a fault: {[(r['name'], r['ok']) for r in checked['checks']]}")
        blocks = next(row for row in checked["checks"] if row["name"] == "blocks")
        _require(blocks["outOfOrder"] and blocks["untagged"], "documents.checks.catch", "order or tag fault not named")
        return {"failed": [row["name"] for row in checked["checks"] if not row["ok"]]}
    case(["documents.checks.catch"], broken)

    def render():
        from PIL import Image
        rendered = tools.run(root, "documents.render", {"path": "course.tex", "pages": "3", "dpi": 60})
        _require(len(rendered["pngs"]) == 1, "documents.render.pages", "page 3 not rendered")
        with Image.open(rendered["pngs"][0]) as png:
            pixmap = png.convert("RGB")
        samples = pixmap.tobytes()
        dark = sum(1 for index in range(0, len(samples), 3 * 7) if samples[index] < 128)
        _require(dark > 50, "documents.render.pages", "rendered page is blank")
        return {"png": rendered["pngs"][0]}
    case(["documents.render.pages"], render)

    def glance():
        saved = os.environ.pop("NEYVIA_LAYA_GLANCE", None)
        try:
            result = tools.run(root, "documents.glance", {"path": "course.tex", "pages": "3"})
        finally:
            if saved is not None:
                os.environ["NEYVIA_LAYA_GLANCE"] = saved
        _require(result["status"] == "not available" and result["ok"] is False, "documents.glance.pending",
                 "an absent judge must never report a pass")
        return {"status": result["status"]}
    case(["documents.glance.pending"], glance)

    def registered():
        from .neyvia_workspace_tools import DEFINITIONS
        names = {row[0] for row in DEFINITIONS}
        _require({"documents.create", "documents.build", "documents.check", "documents.render", "documents.glance"} <= names,
                 "documents.tools.registered", "documents tools are not workspace tools")
        _require(study_docs.toolchain()["ok"], "documents.tools.registered", "Tectonic or the bundled Inter files are missing")
    case(["documents.tools.registered"], registered)

    return {"ok": all(row["ok"] for row in cases), "cases": cases,
            "durationMs": round((time.perf_counter() - started) * 1000)}


if __name__ == "__main__":
    import json
    import sys
    import tempfile
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="documents-proof-", dir="D:/NeyviaRuns/docs"))
    print(json.dumps(self_check(target), indent=2))
