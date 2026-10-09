"""Read real PDF metadata/text with an installed pypdf interpreter, without installs."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from .subprocess_utils import hidden_windows_subprocess_kwargs


@lru_cache(maxsize=1)
def reader_python() -> str:
    candidates = [os.environ.get("NEYVIA_PDF_PYTHON"), sys.executable, shutil.which("python")]
    for candidate in dict.fromkeys(filter(None, candidates)):
        if Path(candidate).resolve() == Path(sys.executable).resolve():
            if importlib.util.find_spec("pypdf"):
                return candidate
            continue
        try:
            result = subprocess.run([candidate, "-c", "import pypdf"], capture_output=True,
                                    timeout=5, **hidden_windows_subprocess_kwargs())
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate
    raise RuntimeError("PDF text requires an installed pypdf interpreter; set NEYVIA_PDF_PYTHON. No installation was attempted.")


def read_pdf(path: Path, action="metadata", **arguments) -> dict:
    request = {"path": str(path), "action": action, **arguments}
    configured = os.environ.get("NEYVIA_PDF_PYTHON")
    if (not configured or Path(configured).resolve() == Path(sys.executable).resolve()) and importlib.util.find_spec("pypdf"):
        # Same installed parser, without two Python startups for each text read.
        # An explicitly different reader interpreter retains the isolated path.
        from .pdf_document_worker import read
        return read(request)
    worker = Path(__file__).with_name("pdf_document_worker.py")
    result = subprocess.run([reader_python(), str(worker)], input=json.dumps(request),
                            text=True, encoding="utf-8", capture_output=True, **hidden_windows_subprocess_kwargs())
    if result.returncode:
        raise ValueError(result.stderr.strip()[:500] or "PDF reader failed")
    return json.loads(result.stdout)
