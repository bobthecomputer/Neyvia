"""File-backed system overlay for the installed Hermes CLI.

Executed with Hermes' own Python, without importing Neyvia dependencies. Hermes
retains its native tools, plugins and permission handling. This is an additive
system overlay, not a claim to replace Hermes' base instructions.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("Expected instructions file, SHA-256, and Hermes arguments")
    path, expected = Path(sys.argv[1]), sys.argv[2]
    text = path.read_text(encoding="utf-8")
    if not text.strip() or len(text) > 250000:
        raise SystemExit("Invalid Hermes system instructions")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected:
        raise SystemExit("Hermes system instructions changed before launch")
    # This script lives beside Neyvia's own cli.py. Do not let that directory
    # shadow Hermes' top-level cli module when using its interpreter.
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != script_dir]
    from hermes_cli.main import main as hermes_main
    cli = importlib.util.find_spec("cli")
    if not cli or not cli.origin or "HERMES_EPHEMERAL_SYSTEM_PROMPT" not in Path(cli.origin).read_text(encoding="utf-8"):
        raise SystemExit("Installed Hermes does not support system overlays; refusing user-channel fallback")
    # Hermes resolves its session overlay through this function. Bind only this
    # child process, retaining its normal CLI/plugin setup and avoiding Windows'
    # 32767-character environment-variable ceiling. Never edit Hermes' source,
    # shared config, personality, or the user's message.
    from hermes_cli import personality
    resolver = personality.resolve_ephemeral_system_prompt
    if list(inspect.signature(resolver).parameters) != ["cfg"]:
        raise SystemExit("Unsupported Hermes overlay resolver; no task-context fallback")
    os.environ.pop("HERMES_EPHEMERAL_SYSTEM_PROMPT", None)
    personality.resolve_ephemeral_system_prompt = lambda cfg: text
    sys.argv = ["hermes", *sys.argv[3:]]
    hermes_main()


if __name__ == "__main__":
    main()
