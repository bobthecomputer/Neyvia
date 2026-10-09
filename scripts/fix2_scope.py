"""FIX2-only proof authority; denials are visible, never remapped successes."""
from __future__ import annotations
import os
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
PROTECTED = tuple(REPO.parent / name for name in ("Neyvia", "Neyvia-next"))


def install():
    def audit(event, args):
        if event in {"open", "sqlite3.connect", "os.scandir", "os.listdir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if any(path == base or path.is_relative_to(base) for base in PROTECTED):
                raise PermissionError("FIX2 refuses protected-tree access")
        if event in {"socket.connect", "socket.bind"} and len(args) > 1 and isinstance(args[1], tuple):
            host, port = args[1][:2]
            if host not in {"127.0.0.1", "localhost", "::1"} or port not in range(48681, 48690):
                raise PermissionError("FIX2 requires an explicit assigned loopback port 48681-48689")
        if event == "subprocess.Popen":
            command = args[1]
            words = [str(word) for word in (command if isinstance(command, (tuple, list)) else [command])]
            if any(re.search(r"(?i)(?:^|[/\\\s])(?:tailscale|pytest)(?:\.exe|\.cmd)?(?:$|\s)", word) for word in words):
                raise PermissionError("FIX2 refuses supervisor, tailnet and Python test operations")
    sys.addaudithook(audit)


if os.environ.get("NEYVIA_FIX2_SCOPE") == "1":
    install()
