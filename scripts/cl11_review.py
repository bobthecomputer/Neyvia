"""Bounded Claude review of the authored CL11 task set; no tool access."""
from pathlib import Path
import json
import os
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.provider11 import _claude_command
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

folder = REPO / '.agent_control/cl11/task-review'
folder.mkdir(parents=True, exist_ok=True)
prompt = ('Review the following CL1.1 benchmark task set before its first scored run. '
          'No tools, edits or implementation. Identify design mismatches, unfair native comparisons, '
          'missing goal coverage, and the nine-star versus ten-task ambiguity. '
          'Return a concise JSON object with approved boolean and blockers/findings. '
          'The lead is repairing API wiring and strengthening observer goals before freeze.\n' +
          (REPO / 'docs/standard/1.1/benchmark.md').read_text(encoding='utf-8') + '\n' +
          (REPO / 'config/cl_benchmark_1.1_tasks.json').read_text(encoding='utf-8'))
(folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
with (folder / 'events.json').open('wb') as output, (folder / 'stderr.txt').open('wb') as error:
    result = subprocess.run([*_claude_command(), '-p', '--model', 'haiku', '--effort', 'low',
        '--output-format', 'json', '--no-session-persistence', '--safe-mode',
        '--setting-sources', '', '--strict-mcp-config', '--no-chrome', '--disable-slash-commands',
        '--tools', '', '--max-budget-usd', '.15'], input=prompt.encode(), stdout=output,
        stderr=error, cwd=folder, timeout=180,
        env={**os.environ, 'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '1200'},
        **hidden_windows_subprocess_kwargs())
print(json.dumps({'exitCode': result.returncode, 'receipt': str(folder / 'events.json')}))
