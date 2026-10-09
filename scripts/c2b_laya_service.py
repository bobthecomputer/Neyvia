"""Start exactly one warm task-owned LAYA CPU process on an explicit port."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--candidate", default="g3-c2")
    args = parser.parse_args()
    if not 48721 <= args.port <= 48729:
        parser.error("C2b owns only ports 48721 through 48729")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="",
                      OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from grant_agent.laya_client.fast_cpu import FastCPU
    engine = FastCPU(args.project, args.candidate)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def write(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.write(200, engine.health()) if self.path == "/v1/health" else self.write(404, {"error": "unknown route"})

        def do_POST(self):
            if self.path != "/v1/decide":
                return self.write(404, {"error": "unknown route"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 200_000:
                    raise ValueError("Request body exceeds CPU budget")
                self.write(200, engine.decide(json.loads(self.rfile.read(length))))
            except (ValueError, KeyError, TypeError) as error:
                self.write(400, {"error": str(error), "policy": "escalate"})

    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(json.dumps({"endpoint": f"http://127.0.0.1:{args.port}", **engine.health()}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
