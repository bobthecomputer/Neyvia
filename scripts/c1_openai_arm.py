"""Launch the installed, official computer-use MCP runtime through codex exec."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PAUSE = Path('C:/Users/user/Projects/plans/logs/window-guard.pause')
RUNTIME = Path('C:/Users/user/AppData/Local/OpenAI/Codex/runtimes/cua_node/45309f9050f7314b/bin')


@contextmanager
def visible_arm_lease():
    if PAUSE.exists():
        raise RuntimeError('Existing window guard pause belongs to another run')
    PAUSE.write_text(str(int(time.time()) + 7200), encoding='ascii')
    try:
        yield
    finally:
        PAUSE.unlink(missing_ok=True)


def stop_owned(process):
    import psutil
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def probe(budget=60):
    area = ROOT / 'scripts/evidence/C1-openai-probe'
    area.mkdir(parents=True, exist_ok=True)
    for name in ('stdout.jsonl', 'stderr.txt', 'result.json'):
        path = area / name
        if path.exists():
            archive = area / (str(time.time_ns()) + '-' + name)
            path.rename(archive)
    command = [str(Path(os.environ['APPDATA']) / 'npm/codex.cmd'), '--no-daemon',
        'exec', '--ephemeral', '--ignore-user-config', '--json', '--color', 'never',
        '-C', str(ROOT), '--enable', 'computer_use', '--enable', 'plugins',
        '-c', 'mcp_servers.node_repl.command=' + json.dumps(str(RUNTIME / 'node_repl.exe')),
        '-c', 'mcp_servers.node_repl.args=["--disable-sandbox"]',
        '-c', 'mcp_servers.node_repl.cwd=' + json.dumps(str(RUNTIME)),
        '-c', 'mcp_servers.node_repl.startup_timeout_sec=15', '-']
    command[-1:-1] = ['-c', 'mcp_servers.node_repl.tools.js.approval_mode="approve"',
        '-c', 'mcp_servers.node_repl.tools.js_reset.approval_mode="approve"']
    started = time.perf_counter()
    result = {'command': command, 'budgetSeconds': budget, 'actions': 0,
        'cost': None, 'costReason': 'Subscription CLI does not report actual billed cost',
        'availabilityProbeOnly': True, 'model': None, 'tokens': None}
    with visible_arm_lease():
        try:
            with (area / 'stdout.jsonl').open('wb') as stdout, (area / 'stderr.txt').open('wb') as stderr:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                    cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    process.communicate((area / 'probe.txt').read_bytes(), timeout=budget)
                    result['exitCode'] = process.returncode
                except subprocess.TimeoutExpired:
                    stop_owned(process)
                    result.update(exitCode=process.returncode, timedOut=True)
        except OSError as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc)
    result['elapsedMs'] = round((time.perf_counter() - started) * 1000, 3)
    result['pauseRemoved'] = not PAUSE.exists()
    output = (area / 'stdout.jsonl').read_text(encoding='utf-8', errors='replace') if (area / 'stdout.jsonl').exists() else ''
    result['runtimeDriven'] = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'turn.completed':
            result['tokens'] = event.get('usage')
        item = event.get('item', {})
        # Require an actual MCP response, not a model's claim that the marker occurred.
        if item.get('type') == 'mcp_tool_call' and item.get('status') == 'completed':
            response = item.get('result')
            if 'C1_LIST_APPS_OK' in json.dumps(response):
                result['runtimeDriven'] = True
    result['stdout'] = 'scripts/evidence/C1-openai-probe/stdout.jsonl'
    result['stderr'] = 'scripts/evidence/C1-openai-probe/stderr.txt'
    (area / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(probe(), indent=2))
