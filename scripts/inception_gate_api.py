"""JSON batch interface to the same Inception gate used by native tools."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.neyvia_inception import inventory, aggregate, validate_bindings
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--stdin", required=True, action="store_true")
parser.parse_args()
sys.stdin.reconfigure(encoding="utf-8")
payload = json.load(sys.stdin)
outputs = []
for request in payload["requests"]:
    if request["op"] == "inventory":
        outputs.append(inventory())
    elif request["op"] == "aggregate":
        outputs.append(aggregate(request["catalog"], request["results"], request["provenance"]))
    elif request["op"] == "bindings":
        outputs.append(validate_bindings(request["catalog"], request["bindings"]))
    else:
        raise ValueError("Unknown gate operation")
print(json.dumps(outputs))
