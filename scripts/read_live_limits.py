"""Read/refresh subscription windows through installed CLIs, with no AI turn."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.connected_sessions.live_limits import LiveLimits, service_for

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--last-known", action="store_true")
args = parser.parse_args()
service = LiveLimits(args.root) if args.last_known else service_for(args.root)
try:
    print(json.dumps(service.snapshot() if args.last_known else service.refresh(wait=True)))
finally:
    service.close()
