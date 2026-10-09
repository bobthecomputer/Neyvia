"""Use the production study HTTP, native and desktop paths on the owned MS host."""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    if args.port not in range(48611, 48620):
        parser.error("Only assigned MS ports")
    root = args.root.resolve()
    root.relative_to(REPO / ".agent_control")
    base = f"http://127.0.0.1:{args.port}"
    os.environ.update(NEYVIA_UI_BACKEND_URL=base, FLUXIO_WEB_BACKEND_URL=base,
        NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    observations, checks = {}, {}

    def request(key, path, data=None):
        req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=120) as response:
                code, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, raw = error.code, error.read()
        value = json.loads(raw)
        if key != "local-session":
            observations[key] = {"status": code, "body": value}
        return code, value.get("data", value)

    checks["health"] = request("health", "/api/health")[1]["ok"] is True
    checks["local-session"] = request("local-session", "/api/auth/local-session", {})[0] == 200
    _, state = request("state", "/api/ui/scroll?pack=ms-course")
    cards = [row for chapter in state["active"]["review"]["chapters"] for row in chapter["cards"]]
    checks["persisted-live-pack"] = len(cards) == 54 and all(row["status"] == "approved" for row in cards)
    code, validation = request("validate", "/api/ui/scroll", {"operation": "validate", "pack": "ms-course"})
    checks["http-validation"] = code == 200 and validation["ok"]
    code, stats = request("stats", "/api/ui/scroll", {"operation": "stats", "pack": "ms-course"})
    checks["measured-cost-per-card"] = code == 200 and stats["costPerCard"]["tokens"] > 0
    code, exported = request("pack", "/api/ui/scroll", {"operation": "pack", "pack": "ms-course"})
    checks["http-export-exact-hash"] = code == 200 and hashlib.sha256(Path(exported["path"]).read_bytes()).hexdigest() == exported["sha256"]
    checks["unknown-pack-refused"] = request("unknown-pack", "/api/ui/scroll?pack=not-imported")[0] >= 400
    checks["other-workspace-refused"] = request("wrong-root", "/api/ui/scroll", {"operation": "state", "_expectedStateRoot": str(root / "wrong")})[0] == 409
    request("import-pending", "/api/ui/scroll", {"operation": "import", "paths": [str(REPO / "scripts/fixtures/ms-chain-rule-course.md")], "packId": "ms-http-pending", "subject": "math"})
    code, refusal = request("pending-export", "/api/ui/scroll", {"operation": "pack", "pack": "ms-http-pending"})
    checks["unreviewed-export-refused"] = code >= 400 and "Review every card" in json.dumps(refusal)
    code, tools = request("native-stats", "/api/ui/tools/call", {"tool": "neyvia.scroll.stats", "arguments": {"pack": "ms-course"}})
    checks["native-shared-state"] = code == 200 and tools["result"]["costPerCard"] == stats["costPerCard"]
    code, facade = request("backend-facade", "/api/backend", {"command": "scroll_stats_command", "payload": {"pack": "ms-course"}})
    checks["backend-command"] = code == 200 and facade.get("costPerCard") == stats["costPerCard"]
    from grant_agent.desktop_bridge import dispatch_desktop_command
    desktop = dispatch_desktop_command(root, "scroll_stats_command", {"pack": "ms-course"})
    observations["desktop-stats"] = desktop
    checks["desktop-shared-state"] = desktop["costPerCard"] == stats["costPerCard"]
    code, preview = request("preview", "/api/ui/scroll", {"operation": "preview", "pack": "ms-course"})
    checks["phone-preview-generated"] = code == 200 and preview["preview"]["url"].startswith("/api/")
    # Reopen a fresh owner over the same SQLite state: no cached response proves persistence.
    from grant_agent.neyvia_scroll import load
    persisted = load(root, "ms-course")
    checks["new-owner-persistence"] = len(persisted["value"]["cards"]) == len(cards) and persisted["value"]["status"] == "ready"
    receipt = {"schema": "neyvia.ms.http-proof.v1", "port": args.port, "checks": checks,
               "allPassed": all(checks.values()), "observations": observations,
               "limitations": ["Browser surfaces unavailable; generated preview route and real player engine proven separately, no rendered UI interaction claim."]}
    path = REPO / "scripts/evidence/MS-runs/study/http.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"allPassed": receipt["allPassed"], "checks": checks}))
    if not receipt["allPassed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
