"""Pin stdio imports to this checkout, even with a shared/linked Python environment."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grant_agent.neyvia_mcp_stdio import main

if __name__ == "__main__":
    raise SystemExit(main())
