"""Lightweight command entry point for the Neyvia native harness."""

from __future__ import annotations

import sys

def main(argv: list[str] | None = None) -> int:
    """Answer readiness probes without importing the full agent runtime."""
    selected = list(sys.argv[1:] if argv is None else argv)
    if "--version" in selected:
        from .proofs_d_neyvia import agent_version
        print(agent_version())
        return 0

    from .neyvia_agent import main as run_agent

    return run_agent(selected)


if __name__ == "__main__":
    raise SystemExit(main())
