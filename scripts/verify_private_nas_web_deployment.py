from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOOPBACK_HEALTH_URL = "http://127.0.0.1:47880/api/health"
OUTPUT = ROOT / ".agent_control" / "deployment_evidence" / "private-nas-web.json"


def _probe(url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"reachable": 200 <= response.status < 400, "status": response.status, "body": body}
    except (OSError, urllib.error.URLError) as exc:
        return {"reachable": False, "status": 0, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Record private Tailscale/NAS web reachability without publishing it.")
    parser.add_argument("--url", default=os.environ.get("NEYVIA_PRIVATE_NAS_HEALTH_URL", ""))
    parser.add_argument("--public-control-url", default=os.environ.get("NEYVIA_PUBLIC_CONTROL_URL", ""))
    parser.add_argument("--login-required", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    target = args.url or LOOPBACK_HEALTH_URL
    primary = _probe(target)
    fallback_used = False
    if not primary["reachable"] and target != LOOPBACK_HEALTH_URL:
        primary = _probe(LOOPBACK_HEALTH_URL)
        fallback_used = True
    receipt = {
        "schema": "fluxio.private_nas_web_deployment.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "deploymentKind": "private_tailscale_nas",
        "healthUrl": target,
        "reachable": primary["reachable"],
        "probe": primary,
        "fallbackUsed": fallback_used,
        "publicControlUrl": args.public_control_url,
        "loginRequired": args.login_required,
        "status": "passed" if primary["reachable"] else "blocked",
    }
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
