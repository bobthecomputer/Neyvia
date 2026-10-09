"""Production HTTP handler, explicit INT3 port and disposable account only."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def install_guard(root):
    """No provider-launch restriction: model calls use their normal authorized path."""
    protected = tuple((Path("C:/Users/user/Projects") / name).resolve() for name in ("Neyvia", "Neyvia-next"))

    def audit(event, args):
        if event in {"open", "sqlite3.connect"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
            candidate = Path(os.fsdecode(args[0])).absolute()
            if any(candidate == path or candidate.is_relative_to(path) for path in protected):
                raise PermissionError("INT3 refuses protected project access")
            sensitive = re.search(r"(?i)(?:nas_access_runbook|nas_codex2_|credential|password|(?:^|[_.-])(?:auth|oauth|secrets|tokens)(?:[_.-]|$))", candidate.name)
            if sensitive and candidate.suffix.lower() not in {".py", ".pyc", ".js", ".mjs"} and not candidate.is_relative_to(root):
                raise PermissionError("INT3 refuses saved credentials outside disposable state")
        if event in {"socket.connect", "socket.bind"} and len(args) > 1 and isinstance(args[1], tuple):
            host, port = args[1][:2]
            if host not in {"127.0.0.1", "localhost", "::1"} or port not in range(48651, 48660):
                raise PermissionError("INT3 sockets require explicit owned loopback ports")

    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.port != 48651 or not root.is_relative_to(REPO / ".agent_control/int3"):
        parser.error("Production integration proof requires port48651 and an INT3 scratch root")
    if not os.environ.get("SYNTELOS_ACCOUNT_PASSWORD"):
        parser.error("The owning proof parent must supply an ephemeral in-memory account environment")
    root.mkdir(parents=True, exist_ok=True)
    authority = root/'config/neyvia_browser_authority.json'
    authority.parent.mkdir(parents=True, exist_ok=True)
    if not authority.exists():
        authority.write_text('{"schema":"neyvia.browser-authority.v1","proofPorts":[48651]}\n', encoding='utf-8')
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", FLUXIO_RUNTIME_AUTO_UPDATE="0",
                      NEYVIA_UI_BACKEND_URL=f"http://127.0.0.1:{args.port}",
                      FLUXIO_WEB_BACKEND_URL=f"http://127.0.0.1:{args.port}",
                      NEYVIA_UI_STATE_ROOT=str(root), FLUXIO_WORKSPACE_ROOT=str(root),
                      SYNTELOS_ACCOUNT_USER=os.environ.get("SYNTELOS_ACCOUNT_USER", "int3-proof"))
    install_guard(root)
    from grant_agent.local_network_policy import install
    install(root)
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    backend = FluxioWebBackend(root, REPO / ".agent_control/int3/build")
    server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", args.port), make_handler(backend))
    print(f"INT3 production handler ready on {args.port}; parent-owned environment account", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
