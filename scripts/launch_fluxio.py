from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47880


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and launch the local Neyvia/Fluxio operator shell.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_build:
        build = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "frontend:build"], cwd=ROOT, check=False)
        if build.returncode:
            return build.returncode

    base_url = f"http://{args.host}:{args.port}"
    control_url = f"{base_url}/control"
    env = os.environ.copy()
    env["FLUXIO_WEB_HOST"] = args.host
    env["FLUXIO_WEB_PORT"] = str(args.port)
    process = subprocess.Popen([sys.executable, "scripts/run_web_backend.py"], cwd=ROOT, env=env)
    try:
        for _ in range(50):
            if process.poll() is not None:
                return int(process.returncode or 1)
            if _reachable(control_url):
                if not args.no_browser:
                    webbrowser.open(control_url)
                print(f"Neyvia is ready at {control_url}")
                return process.wait()
            time.sleep(0.2)
        print(f"Backend did not become ready at {control_url}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
