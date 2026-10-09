"""Owned MS HTTP host: explicit ports, disposable identity, no saved credentials."""
import argparse
import os
from pathlib import Path
import re
import secrets
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48611, 48620):
        parser.error("Only MS ports 48611-48619")
    root = args.root.resolve()
    if not root.is_relative_to(REPO / ".agent_control"):
        parser.error("Disposable state must be inside this worktree's .agent_control")

    def audit(event, values):
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = Path(os.fsdecode(values[0])).resolve()
            if path.suffix.lower() not in {".py", ".pyc", ".js", ".pyd", ".dll"} and (
                re.search(r"credential|password|secret|nas_codex2|runbook", path.name, re.I)
                or path.name.lower() in {"auth.json", "oauth_creds.json", "account.json", ".claude.json", "neyvia_web_admin.json"}
                or any(part in {".codex", ".claude", ".minimax", ".ssh"} for part in path.parts)):
                raise PermissionError("MS host refuses credential files")
        if event in {"socket.connect", "socket.bind"}:
            address = values[1]
            if isinstance(address, tuple) and len(address) >= 2:
                host, port = address[:2]
                if host not in {"127.0.0.1", "localhost", "::1"} or port not in range(48611, 48620):
                    raise PermissionError("MS host refuses unassigned network endpoints")

    sys.addaudithook(audit)
    base = f"http://127.0.0.1:{args.port}"
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
        FLUXIO_WATCHDOG_AUTOSTART="0", FLUXIO_RUNTIME_AUTO_UPDATE="0",
        NEYVIA_UI_BACKEND_URL=base, FLUXIO_WEB_BACKEND_URL=base,
        SYNTELOS_ACCOUNT_USER="ms-proof", SYNTELOS_ACCOUNT_PASSWORD=secrets.token_urlsafe(32),
        SYNTELOS_SESSION_SECRET=secrets.token_urlsafe(48), PYTHONDONTWRITEBYTECODE="1")
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler, tcp_port_accepts_connection
    from grant_agent.neyvia_ui_api import bind_backend
    if tcp_port_accepts_connection("127.0.0.1", args.port):
        raise SystemExit("Assigned MS port already listens; stop the verified task-owned host before restarting")
    backend = FluxioWebBackend(root, REPO / "apps/scroll-study/www")
    bind_backend(backend)
    server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", args.port), make_handler(backend))
    print(f"MS production HTTP handlers on {base}; disposable root {root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
