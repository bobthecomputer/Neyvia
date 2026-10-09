"""Real hidden Office journeys; never creates a preview or visible window."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_office import APPS, run_office_tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", choices=list(APPS), action="append")
    parser.add_argument("--receipt", type=Path, default=ROOT / "scripts/evidence/C11f-office.json")
    args = parser.parse_args()
    result = run_office_tasks(ROOT, apps=args.app)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    if args.receipt.exists():
        previous = args.receipt.read_bytes()
        archive = args.receipt.parent / "C11f-office-runs"
        archive.mkdir(exist_ok=True)
        (archive / (hashlib.sha256(previous).hexdigest() + ".json")).write_bytes(previous)
    args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("ok", "appsCompleted", "distinctTasksCompleted",
        "deterministicReplayTasksCompleted", "actionAndReadbackP50Ms", "modelTokens")}))
    print(json.dumps({"apps": [{"app": row["app"], "ok": row["ok"], "error": row.get("error"),
        "cleanup": row.get("cleanup")} for row in result["apps"]], "guard": result["guard"]["ok"]}))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
