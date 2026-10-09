from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.local_provisioning import ensure_bytecode
ensure_bytecode(ROOT)

# Select explicit state before importing the backend; persisted privacy applies
# to import-time helpers too. Embedded callers install again in the constructor.
import argparse
import os
_bootstrap = argparse.ArgumentParser(add_help=False)
_bootstrap.add_argument("--root", default=os.environ.get("FLUXIO_WORKSPACE_ROOT"))
_bootstrap_args, _ = _bootstrap.parse_known_args()
if _bootstrap_args.root:
    if os.environ.get("NEYVIA_PROOF_CREDENTIAL_GUARD") == "1":
        from grant_agent.proof_credential_guard import install as install_proof_guard
        install_proof_guard(Path(_bootstrap_args.root))
    from grant_agent.local_network_policy import install
    install(Path(_bootstrap_args.root))

from grant_agent.web_backend import main


if __name__ == "__main__":
    raise SystemExit(main())
