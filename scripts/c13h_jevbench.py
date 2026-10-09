"""Reuse the installed frozen public benchmark, keeping every write in this task."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/scripts/run_jevbench.py')
spec = importlib.util.spec_from_file_location('installed_jevbench_runner', SOURCE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
# VENDOR is already bound to the original read-only corpus. ROOT only scopes
# output receipts and fixes the upstream writer's relative_to assumption.
runner.ROOT = ROOT
sys.argv = [str(SOURCE), '--endpoint', 'http://127.0.0.1:48809/ai/run',
            '--name', 'C13h-frozen-after', '--output', str(ROOT/'proof/r11/jevbench-after.json'), '--timeout', '180']
runner.main()
