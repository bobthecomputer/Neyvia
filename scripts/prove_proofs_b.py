"""Replay the defining proof-host journey using only PROOFS-b's owned port range."""
import os
from pathlib import Path
import tempfile

from prove_proofs import main


if __name__ == "__main__":
    # Keep runtime discovery away from the operator's existing credentials and
    # services. This task-owned home remains recoverable with the journey.
    base = Path(__file__).resolve().parents[1] / ".agent_control/proofs-b/host-homes"
    base.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="owner-", dir=base))
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR",
                 "APPDATA", "LOCALAPPDATA", "NEYVIA_MANAGED_RUNTIME_ROOT"):
        directory = home / name.lower()
        directory.mkdir()
        os.environ[name] = str(directory)
    main(port_range=(48471, 48479), evidence_path="scripts/evidence/PROOFS-b-host.json",
         build_root=".agent_control/proofs-b/build", build_log=".agent_control/proofs-b/build.log")
