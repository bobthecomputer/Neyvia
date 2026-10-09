"""Copy complete real comparator receipts byte-for-byte, without printing answers."""
import argparse
import hashlib
import json
from pathlib import Path

from c10c_quality import RUNS, load_panel, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--destination-run", required=True)
    args = parser.parse_args()
    for name in (args.source_run, args.destination_run):
        if not name.replace("-", "").replace("_", "").isalnum():
            parser.error("Simple local run names required")
    if args.source_run == args.destination_run:
        parser.error("Distinct runs required")
    for panel_name in ("development", "holdout"):
        panel, _ = load_panel(panel_name)
        original = RUNS / args.source_run / panel_name
        destination = RUNS / args.destination_run / panel_name
        manifest = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "requests-returned" or manifest["panelSha256"] != panel["panel_sha256"]:
            raise ValueError("Original paired requests must have returned on this frozen panel")
        entries = []
        for task in panel["questions"]:
            source = original / "openai" / (task["id"] + ".json")
            target = destination / "openai" / source.name
            data = source.read_bytes()
            receipt = json.loads(data)
            if receipt["status"] != "completed":
                continue  # The normal runner executes missing comparator requests again.
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Refusing to overwrite a different comparator receipt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Comparator readback mismatch")
            entries.append({"taskId": task["id"], "source": str(source), "destination": str(target),
                            "sha256": digest, "status": "completed"})
        write_json(destination / "comparator-reuse.json", {"sourceRun": args.source_run,
            "panelSha256": panel["panel_sha256"], "entries": entries,
            "boundary": "Unchanged complete real comparator outputs and original usage/cost; no comparator answers reach Neyvia. Missing or failed originals are freshly executed by the runner."})
        print(json.dumps({"panel": panel_name, "comparatorReceiptsReused": len(entries)}))


if __name__ == "__main__":
    main()
