import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.PYTHON || 'python';
const code = String.raw`
import json
from grant_agent.external_cli_bridge import build_cli_args
cases = {
  "codex_read": build_cli_args(runtime="codex", command="codex", prompt="probe", mode="chat", permission_mode="read-only"),
  "codex_workspace": build_cli_args(runtime="codex", command="codex", prompt="probe", mode="mission", permission_mode="workspace"),
  "codex_full": build_cli_args(runtime="codex", command="codex", prompt="probe", mode="mission", permission_mode="full-access"),
  "claude_read": build_cli_args(runtime="claude-code", command="claude", prompt="probe", mode="chat", permission_mode="read-only"),
  "claude_workspace": build_cli_args(runtime="claude-code", command="claude", prompt="probe", mode="mission", permission_mode="workspace"),
  "claude_full": build_cli_args(runtime="claude-code", command="claude", prompt="probe", mode="mission", permission_mode="full-access"),
}
print(json.dumps(cases))
`;
const built = spawnSync(python, ['-c', code], {
  cwd: root,
  env: { ...process.env, PYTHONPATH: resolve(root, 'src') },
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(built.status, 0, `could not build production CLI args: ${built.stderr}`);
const args = JSON.parse(built.stdout.trim());
const hasPair = (argv, flag, value) => argv.some((item, index) => item === flag && argv[index + 1] === value);

assert(hasPair(args.codex_read, '--sandbox', 'read-only'));
assert(hasPair(args.codex_workspace, '--sandbox', 'workspace-write'));
assert(args.codex_full.includes('--dangerously-bypass-approvals-and-sandbox'));
assert(!args.codex_full.includes('--sandbox'));
assert(hasPair(args.claude_read, '--permission-mode', 'plan'));
assert(hasPair(args.claude_workspace, '--permission-mode', 'acceptEdits'));
assert(!args.claude_workspace.includes('Bash'), 'Claude workspace mode must not expose shell');
assert(hasPair(args.claude_full, '--permission-mode', 'bypassPermissions'));
assert(hasPair(args.claude_full, '--tools', 'default'));
assert(!args.claude_full.includes('--chrome'), 'Claude must not require its optional Chrome extension');

const backend = readFileSync(resolve(root, 'src/grant_agent/web_backend.py'), 'utf8');
assert(backend.includes('external_full_access_runtimes = {"codex", "claude-code", "hermes"}'));
assert(backend.includes('args.insert(prompt_index, "--dangerously-bypass-approvals-and-sandbox")'));
assert(backend.includes('native_args.append("--yolo")'));
assert(backend.includes('"harnessPermission": ('));
assert(backend.includes('"host-unrestricted" if effective_mode == "full-access" and external_runtime'));

console.log(JSON.stringify({
  passed: true,
  routes: {
    codex: { readOnly: 'read-only', workspace: 'workspace-write', fullAccess: 'host-wide approval and sandbox bypass' },
    claudeCode: { readOnly: 'plan', workspace: 'acceptEdits without Bash', fullAccess: 'bypassPermissions and all built-in tools' },
    hermes: { readOnly: 'configured tools on isolated mirror', workspace: 'reported unsupported', fullAccess: '--yolo' },
  },
}, null, 2));
