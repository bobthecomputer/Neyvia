from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .native_tools import NativeToolRegistry, ReusablePlaywrightRuntime
from .subprocess_utils import install_hidden_subprocess_default


WORKER_PROTOCOL = "neyvia.native_tool_worker.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Neyvia's persistent native tool worker.")
    parser.add_argument("--root", default=".", help="Default workspace root")
    parser.add_argument("--nas-root", default="", help="Default NAS root override")
    parser.add_argument('--browser-transport', choices=('playwright','obscura','neyvia'), default='playwright')
    parser.add_argument('--browser-port', type=int, help='Explicit Neyvia loopback backend port')
    return parser


def _response(request_id: object, *, data: Any = None, error: str = "") -> dict[str, Any]:
    return {
        "protocol": WORKER_PROTOCOL,
        "id": request_id,
        "ok": not bool(error),
        "data": data,
        "error": error,
    }


def run_worker(default_root: Path, default_nas_root: str = "", *, browser_transport='playwright', browser_port=None) -> int:
    if browser_transport=='neyvia':
        from .neyvia_browser_capture import NeyviaCaptureRuntime, authenticated_request
        cookie=os.environ.pop('NEYVIA_BROWSER_OWNER_COOKIE','')
        runtime=NeyviaCaptureRuntime(authenticated_request(browser_port,cookie),initial_url=os.environ.pop('NEYVIA_BROWSER_CONTEXT_URL',''))
    elif browser_transport in {'playwright', 'obscura'}:
        runtime = ReusablePlaywrightRuntime(default_root, transport=browser_transport, port=browser_port)
    else:
        raise ValueError('Choose an explicit supported browser transport')
    registries: dict[tuple[str, str], NativeToolRegistry] = {}
    requests_served = 0
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            request_id: object = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Worker request must be a JSON object.")
                request_id = request.get("id")
                if request.get("command") == "shutdown":
                    # Acknowledgement means owned browser resources are closed.
                    runtime.close()
                    print(json.dumps(_response(request_id, data={"shutdown": True})), flush=True)
                    return 0
                tool = str(request.get("tool") or request.get("name") or "").strip()
                if not tool:
                    raise ValueError("tool is required")
                arguments = request.get("arguments")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                root = Path(str(request.get("root") or default_root)).expanduser().resolve()
                nas_root = str(request.get("nasRoot") or request.get("nas_root") or default_nas_root).strip()
                key = (str(root), nas_root)
                registry = registries.get(key)
                if registry is None:
                    registry = NativeToolRegistry(
                        root,
                        nas_root=(nas_root or None),
                        browser_runtime=runtime,
                    )
                    registries[key] = registry
                requests_served += 1
                started = time.perf_counter()
                receipt = registry.call(tool, arguments)
                receipt["worker"] = {
                    "kind": "persistent-native-tool-worker",
                    "protocol": WORKER_PROTOCOL,
                    "pid": os.getpid(),
                    "requestIndex": requests_served,
                    "durationMs": round((time.perf_counter() - started) * 1000),
                    "browserStarts": runtime.browser_starts,
                    "contextsCreated": runtime.contexts_created,
                }
                from .proofs_d_native import require
                observation = (receipt.get("result") or {}).get("browserRuntime") or {}
                if observation:
                    require(observation.get("browserStarts") == runtime.browser_starts
                            and observation.get("contextsCreated") == runtime.contexts_created
                            and runtime.contexts_created > 0,
                            "native.worker.reuse", "worker receipt differs from actual browser/context counters")
                print(json.dumps(_response(request_id, data=receipt), ensure_ascii=True), flush=True)
            except Exception as exc:
                print(json.dumps(_response(request_id, error=str(exc)), ensure_ascii=True), flush=True)
    finally:
        runtime.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    args = _parser().parse_args(argv)
    return run_worker(Path(args.root).resolve(), str(args.nas_root or ""),browser_transport=args.browser_transport,browser_port=args.browser_port)


if __name__ == "__main__":
    raise SystemExit(main())
