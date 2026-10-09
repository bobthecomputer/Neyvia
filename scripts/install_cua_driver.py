"""Stage the pinned MIT Cua Driver for this user; never install globally or start services.

By default both hash-verified executables go to the shared per-user runtime
(%LOCALAPPDATA%/Neyvia/runtimes/cua-driver/<version>), which every Neyvia checkout and
release on this PC resolves. --target stages a copy somewhere else instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_upstream import DRIVER_VERSION as VERSION, RUNTIME_FILES, install_runtime  # noqa: E402

EXPECTED = dict(RUNTIME_FILES)


def install(source: Path | None = None, target: Path | None = None) -> dict:
    return install_runtime(source, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Copy both hash-verified binaries from an existing runtime directory; no download")
    parser.add_argument("--target", type=Path, help="Stage into this directory instead of the shared per-user runtime")
    arguments = parser.parse_args()
    print(json.dumps(install(arguments.source, arguments.target)))
