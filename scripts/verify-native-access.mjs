import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = fs.readFileSync(path.join(root, "src/grant_agent/web_backend.py"), "utf8");
const agent = fs.readFileSync(path.join(root, "src/grant_agent/neyvia_agent.py"), "utf8");
const stdio = fs.readFileSync(path.join(root, "src/grant_agent/neyvia_mcp_stdio.py"), "utf8");

const pythonCode = String.raw`
import json, sys
from grant_agent.native_access import normalize_permission_mode, mutation_tools_for_mode, access_context
from grant_agent.web_backend import _agent_chat_max_turns
from grant_agent.neyvia_agent import _failure_for_agent_exception

legacy = normalize_permission_mode({"workspaceToolsAllowed": True})
default = normalize_permission_mode({})
override = normalize_permission_mode({"permissionMode": "read-only", "workspaceToolsAllowed": True})
workspace = set(mutation_tools_for_mode("workspace"))
full = set(mutation_tools_for_mode("full-access"))
environment = {"ok": True, "result": {
    "operatingSystem": "Windows", "cwd": "C:/service", "workspaceRoot": "C:/selected/project",
    "python": {"executable": "C:/Python/python.exe", "version": "3.13"},
    "executables": {"python": "C:/Python/python.exe", "node": "C:/node.exe", "git": "C:/git.exe",
                    "shells": {"powershell": "C:/pwsh.exe", "cmd": "C:/cmd.exe", "bash": None}},
    "environmentValuesIncluded": False,
}}
workspace_context = access_context("workspace", environment=environment)
full_context = access_context("full-access", environment=environment)
class MaxTurnsExceeded(Exception): pass
limit_failure = _failure_for_agent_exception(MaxTurnsExceeded(), max_turns=32,
    session_id="session-check", session_database=__import__("pathlib").Path("session.sqlite3"))
turn_budgets = {
    "fullDefault": _agent_chat_max_turns({"runtime": "neyvia-agent", "_permissionMode": "full-access"}),
    "workspaceDefault": _agent_chat_max_turns({"runtime": "neyvia-agent", "_permissionMode": "workspace"}),
    "otherRuntimeDefault": _agent_chat_max_turns({"runtime": "codex", "_permissionMode": "full-access"}),
    "fullExplicit": _agent_chat_max_turns({"runtime": "neyvia-agent", "_permissionMode": "full-access", "maxTurns": 48}),
    "fullClamp": _agent_chat_max_turns({"runtime": "neyvia-agent", "_permissionMode": "full-access", "maxTurns": 90}),
}
print(json.dumps({"legacy": legacy, "default": default, "override": override,
                  "workspace": sorted(workspace), "full": sorted(full),
                  "workspaceContext": workspace_context, "context": full_context,
                  "turnBudgets": turn_budgets, "limitFailure": limit_failure}))
`;

function runPython(code = pythonCode, args = [], extraEnv = {}) {
  const env = { ...process.env, PYTHONPATH: [path.join(root, "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) };
  Object.assign(env, extraEnv);
  const candidates = process.env.PYTHON ? [[process.env.PYTHON, []]] : [["python", []], ["py", ["-3"]]];
  let lastError = "no Python launcher found";
  for (const [command, prefix] of candidates) {
    const result = spawnSync(command, [...prefix, "-c", code, ...args], { cwd: root, env, encoding: "utf8", timeout: 20000 });
    if (!result.error && result.status === 0) return JSON.parse(result.stdout.trim());
    lastError = result.error?.message ?? result.stderr ?? `exit ${result.status}`;
  }
  throw new Error(`Native permission helper check could not run: ${lastError}`);
}

const permission = runPython();
assert.equal(permission.legacy, "workspace", "legacy bool maps to workspace");
assert.equal(permission.default, "read-only", "omitted mode defaults read-only");
assert.equal(permission.override, "read-only", "new mode overrides legacy bool");
assert.ok(!permission.workspace.includes("terminal.exec") && !permission.workspace.includes("workspace.browser"));
assert.ok(["workspace.write", "preview.screenshot", "preview.taste", "laya.native.neyvia_navigation"].every((id) => permission.workspace.includes(id)));
assert.ok(permission.full.includes("terminal.exec") && permission.full.includes("workspace.browser"));
assert.ok(permission.workspace.every((id) => permission.full.includes(id)));
assert.equal(permission.workspaceContext.effectiveAccess.defaultCommandCwd, "");
assert.equal(permission.workspaceContext.capabilities.powershellCommands, false);
assert.equal(permission.workspaceContext.capabilities.pythonCommands, false);
assert.equal(permission.context.effectiveAccess.defaultCommandCwd, "C:/selected/project");
assert.equal(permission.context.effectiveAccess.cwdIsSandboxed, false);
assert.equal(permission.context.capabilities.powershellCommands, true);
assert.equal(permission.context.capabilities.pythonCommands, true);
assert.equal(permission.context.capabilities.localCommandsMayAccessNetwork, true);
assert.match(permission.context.capabilities.laya.scope, /no generic desktop control/);
const routes = permission.context.toolRoutes;
assert.ok(routes.some((route) => route.toolId === "terminal.exec" && route.available));
assert.ok(routes.some((route) => route.toolId === "runtime.environment"));
assert.ok(routes.some((route) => route.toolId === "preview.taste" && route.requiredInputs.includes("goal") && route.requiredInputs.includes("journey")));
assert.ok(routes.some((route) => route.toolIds?.includes("neyvia_situation") && route.approvedOriginsRequired));
assert.ok(routes.some((route) => route.toolId === "laya.native.neyvia_navigation" && /no generic desktop control/.test(route.scope)));
assert.equal(permission.turnBudgets.fullDefault, 32);
assert.equal(permission.turnBudgets.workspaceDefault, 12);
assert.equal(permission.turnBudgets.otherRuntimeDefault, 12);
assert.equal(permission.turnBudgets.fullExplicit, 48);
assert.equal(permission.turnBudgets.fullClamp, 64);
assert.equal(permission.limitFailure.code, "run_limit_reached");
assert.equal(permission.limitFailure.exceptionType, "MaxTurnsExceeded");
assert.equal(permission.limitFailure.maxTurns, 32);
assert.match(permission.limitFailure.message, /turn limit before completing/);
assert.match(permission.limitFailure.nextAction, /resume this session/i);
assert.match(backend, /normalize_permission_mode\(chat_payload\)/);
assert.match(backend, /chat_payload\.pop\("_nativeMutationTools", None\)/);
assert.match(backend, /native_runtime[\s\S]*?mutation_tools_for_mode\(effective_mode\)/);
assert.match(backend, /"appliedToRuntime": native_runtime/);
assert.match(agent, /"terminal\.exec"/);
assert.match(agent, /Local commands require Full access in the composer/);
assert.match(agent, /tool_id in \{"workspace\.write", "terminal\.exec"\}/);
assert.match(agent, /permission_mode=selected\.permission_mode/);
assert.match(agent, /selected\.root,[\s\S]{0,120}allow_mutations=selected\.allow_mutations/);
assert.match(agent, /name_override="neyvia_access_context"/);
assert.match(agent, /permission_mode=config\.permission_mode/);
assert.match(stdio, /"neyvia\.access\.context"/);
assert.match(stdio, /permission_mode=self\.permission_mode/);
assert.match(stdio, /Local command execution requires Full access in the composer/);
assert.match(agent, /failure\.get\("message"\) or "The Native run failed before completing\."/);
assert.match(agent, /failure\["message"\] \+ " Saved session and action receipts are available; resume the unfinished work\."/);
assert.doesNotMatch(agent, /Provider stream ended before the agent completed\./);
assert.match(agent, /instructions_file\.open\("r", encoding="utf-8", newline=""\)/);
assert.match(agent, /return text\.replace\("\\r\\n", "\\n"\)\.replace\("\\r", "\\n"\)/);
assert.match(backend, /instructions = instructions\.replace\("\\r\\n", "\\n"\)\.replace\("\\r", "\\n"\)/);
assert.match(backend, /instruction_path\.write_text\(instructions, encoding="utf-8", newline="\\n"\)/);

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "neyvia-native-access-prompt-"));
try {
  const promptText = "Keep  exact spacing.\r\nSecond line with π.\n";
  const promptBytes = Buffer.from(promptText, "utf8");
  const promptPath = path.join(tempRoot, "custom-prompt.txt");
  fs.writeFileSync(promptPath, promptBytes);
  const promptCheckCode = String.raw`
import json, sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaAgentConfig, _role_instructions
root, prompt = Path(sys.argv[1]), Path(sys.argv[2])
config = NeyviaAgentConfig(root=root, session_id="prompt-check", instructions_file=prompt)
print(json.dumps(_role_instructions(config)))
`;
  const decoded = runPython(promptCheckCode, [tempRoot, promptPath]);
  assert.equal(decoded, promptText.replace(/\r\n?/g, "\n"), "saved custom prompt text must remain intact apart from established newline canonicalization");

  const gateCode = String.raw`
import json, os, sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaAgentConfig, NeyviaToolGateway
root, sentinel = Path(sys.argv[1]), Path(sys.argv[2])
def gateway_for(mode, allow, tools):
    config = NeyviaAgentConfig(root=root, session_id="gate-check-" + mode.replace("-", ""),
        allow_mutations=allow, native_mutation_tools=tools, permission_mode=mode).validated()
    gateway = NeyviaToolGateway(root, allow_mutations=config.allow_mutations,
        allowed_mutation_tools=set(config.native_mutation_tools or ()), permission_mode=config.permission_mode)
    return config, gateway
readonly, ro_gateway = gateway_for("read-only", False, ("terminal.exec",))
ro_result = ro_gateway.call_native("terminal.exec", {"command": "import os,pathlib;pathlib.Path(os.environ['VERIFY_SENTINEL']).write_text('unexpected')", "shell": "python"})
workspace, ws_gateway = gateway_for("workspace", True, None)
ws_result = ws_gateway.call_native("terminal.exec", {"command": "import os,pathlib;pathlib.Path(os.environ['VERIFY_SENTINEL']).write_text('unexpected')", "shell": "python"})
full, full_gateway = gateway_for("full-access", True, None)
full_result = full_gateway.call_native("terminal.exec", {"command": "print('native command output')", "shell": "python"}, action_id="full-command-success")
failed_result = full_gateway.call_native("terminal.exec", {"command": "print('partial output'); raise SystemExit(7)", "shell": "python"}, action_id="full-command-failure")
print(json.dumps({"readonly": {"mode": readonly.permission_mode, "allowMutations": readonly.allow_mutations,
                      "tools": list(readonly.native_mutation_tools or ()), "result": ro_result},
                  "workspace": {"mode": workspace.permission_mode, "result": ws_result},
                  "full": {"mode": full.permission_mode, "result": full_result, "failedResult": failed_result},
                  "sentinelExists": sentinel.exists()}))
`;
  const sentinel = path.join(tempRoot, "must-not-exist.txt");
  const denied = runPython(gateCode, [tempRoot, sentinel], { VERIFY_SENTINEL: sentinel });
  assert.equal(denied.readonly.mode, "read-only", "read-only config wins over a stray terminal grant");
  assert.equal(denied.readonly.allowMutations, false);
  assert.equal(denied.readonly.tools.length, 0);
  assert.equal(denied.readonly.result.status, "approval_required");
  assert.match(denied.readonly.result.message, /Full access/);
  assert.equal(denied.workspace.mode, "workspace");
  assert.equal(denied.workspace.result.status, "mutation_outside_contract");
  assert.match(denied.workspace.result.message, /Full access/);
  assert.equal(denied.full.mode, "full-access");
  assert.equal(denied.full.result.ok, true);
  assert.equal(denied.full.result.toolResult.exitCode, 0);
  assert.match(denied.full.result.toolResult.stdout, /native command output/);
  assert.equal(denied.full.failedResult.ok, false);
  assert.equal(denied.full.failedResult.status, "failed");
  assert.equal(denied.full.failedResult.toolResult.exitCode, 7);
  assert.match(denied.full.failedResult.toolResult.stdout, /partial output/);
  assert.equal(denied.sentinelExists, false, "denied terminal call creates no file");
} finally {
  fs.rmSync(tempRoot, { recursive: true, force: true });
}

console.log(`NATIVE_ACCESS_OK mode=${permission.context.permissionMode} workspaceDeniesTerminal=true fullAllowsTerminal=true customPrompt=preserved-with-LF-canonicalization`);
