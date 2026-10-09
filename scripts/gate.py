"""Impact-scoped Connected Language release gate (no pytest or full tour)."""
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(repo / "src"), str(repo)]
from grant_agent.contract_gate import main

if __name__ == "__main__":
    raise SystemExit(main())
