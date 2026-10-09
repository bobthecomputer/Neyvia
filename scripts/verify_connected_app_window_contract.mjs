import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.PYTHON || 'python';
const probe = String.raw`
import inspect, sys
sys.path.insert(0, sys.argv[1])
from grant_agent.connected_app_window import ConnectedAppWindow, _package_for_path
assert _package_for_path(r'C:\Program Files\WindowsApps\OpenAI.Codex_26.924.2738.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe') == 'codex'
assert _package_for_path(r'C:\Program Files\WindowsApps\Claude_2.9939.4.0_x64__pzs8sxrjxfjjc\app\Claude.exe') == 'claude'
assert _package_for_path(r'C:\Program Files\WindowsApps\OpenAI.CodexLookalike_26.924.2738.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe') is None
assert _package_for_path(r'C:\Program Files\WindowsApps\Claude_2.9939.4.0_x64__notourpublisher\app\Claude.exe') is None
assert _package_for_path(r'C:\Users\user\AppData\Local\OpenAI\Codex\bin\faa963e871dd422c\codex.exe') is None
assert _package_for_path(r'C:\Users\Public\Codex.exe') is None
assert _package_for_path(r'C:\Users\Public\WindowsApps\Claude_2.9939.4.0_x64__pzs8sxrjxfjjc\app\Claude.exe') is None
assert set(ConnectedAppWindow.__dict__) >= {'list_apps', 'frame', 'action'}
assert 'activate' in inspect.signature(ConnectedAppWindow.frame).parameters
print('connected app window package allowlist and API contract passed')
`;
const result = spawnSync(python, ['-c', probe, path.join(repo, 'src')], { cwd: repo, encoding: 'utf8', timeout: 15000 });
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || `Python exited ${result.status}`);
  process.exit(result.status || 1);
}
process.stdout.write(result.stdout);
