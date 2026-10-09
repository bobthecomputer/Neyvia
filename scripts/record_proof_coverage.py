from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.proof_coverage import record_coverage, retirement_gate, render_map, revalidate_existing, revalidate_coverage
parser = argparse.ArgumentParser(description="Record verified coverage; gate test retirement without deleting anything")
parser.add_argument("--receipt", type=Path)
parser.add_argument("--retire", action="append", default=[])
parser.add_argument("--paths-file", type=Path, help="JSON list restricting changed inventory rows to this task's ownership")
parser.add_argument("--proofs-b", action="store_true", help="Update only Paul's owned rows; revalidate other unchanged claims in a separate receipt")
parser.add_argument("--test", action="append", help="Restrict changed inventory rows to these test paths")
parser.add_argument("--scope", type=Path, help="JSON list restricting changed rows to this migration")
parser.add_argument("--only-test", action="append", help="Restrict writes to these owned rows")
parser.add_argument("--revalidate", type=Path, help="Renew exact existing coverage with fresh source-bound evidence")
args = parser.parse_args()
renewed = revalidate_coverage(args.revalidate) if args.revalidate else []
scope = set(json.loads(args.paths_file.read_text(encoding="utf-8"))) if args.paths_file else None
if args.scope:
    requested = set(json.loads(args.scope.read_text(encoding="utf-8")))
    scope = requested if scope is None else scope & requested
if args.only_test is not None:
    requested = set(args.only_test)
    scope = requested if scope is None else scope & requested
if args.test:
    scope = set(args.test) if scope is None else scope & set(args.test)
refreshed = []
if args.proofs_b:
    from summarize_proofs_b import SCOPE
    scope = SCOPE if scope is None else set(SCOPE) & scope
    if args.receipt:
        refreshed = revalidate_existing(args.receipt, exclude=scope)
mapped = record_coverage(args.receipt, paths=scope) if args.receipt else []
allowed = retirement_gate(args.retire) if args.retire else []
render_map()
print(json.dumps({"mapped": len(mapped), "revalidatedWithoutRowEdits": len(refreshed), "revalidatedAreas": renewed, "retirementAllowed": [str(p) for p in allowed]}))
