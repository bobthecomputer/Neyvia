"""Optional explicit acquisition; first sidebar use runs the same provisioner."""
from __future__ import annotations
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.sidebar_model_assets import FILES, MAX_TOTAL_BYTES, MODEL_ID, REVISION, ensure_model, expected_receipt


def main():
    target = ensure_model()
    print(json.dumps({"ok": True, "revision": REVISION, "files": len(FILES),
                      "totalBytes": expected_receipt()["totalBytes"], "path": str(target / "receipt.json")}))


if __name__ == "__main__":
    main()
