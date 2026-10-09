import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = mkdtempSync(path.join(os.tmpdir(), "neyvia-desktop-capability-fastpaths-"));
const workspace = path.join(temp, "workspace");
const profile = path.join(temp, "profile");
mkdirSync(workspace, { recursive: true });
mkdirSync(profile, { recursive: true });
const python = process.env.PYTHON || "python";
const env = {
  ...process.env,
  PYTHONPATH: [path.join(root, "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  USERPROFILE: profile,
  HOME: profile,
};

function invoke(command, payload = {}, inputPatch = {}) {
  return spawnSync(python, ["-m", "grant_agent.desktop_bridge", "--root", workspace], {
    input: JSON.stringify({ command, payload, ...inputPatch }),
    encoding: "utf8",
    env,
    timeout: 30000,
    maxBuffer: 16 * 1024 * 1024,
  });
}

try {
  const tools = invoke("get_native_tool_catalog_command", { root: workspace });
  assert.equal(tools.status, 0, `${tools.stderr}\n${tools.stdout.slice(-1000)}`);
  const toolEnvelope = JSON.parse(tools.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(toolEnvelope.ok, true, toolEnvelope.error);
  assert.equal(toolEnvelope.data.schema, "fluxio.native_tool_catalog.v1");
  assert.ok(toolEnvelope.data.total > 0);
  assert.ok(toolEnvelope.data.tools.some(row => row.name === "terminal.exec"));

  const describe = invoke("get_native_tool_catalog_command", { root: workspace, describe: "terminal.exec" });
  assert.equal(describe.status, 0, `${describe.stderr}\n${describe.stdout.slice(-1000)}`);
  const describedEnvelope = JSON.parse(describe.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(describedEnvelope.ok, true, describedEnvelope.error);
  assert.equal(describedEnvelope.data.name, "terminal.exec");
  assert.ok(describedEnvelope.data.inputSchema);

  const skills = invoke("get_skill_library_command", { root: workspace });
  assert.equal(skills.status, 0, `${skills.stderr}\n${skills.stdout.slice(-1000)}`);
  const skillEnvelope = JSON.parse(skills.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(skillEnvelope.ok, true, skillEnvelope.error);
  assert.ok(Array.isArray(skillEnvelope.data.userInstalledSkills));
  assert.ok(Array.isArray(skillEnvelope.data.curatedPacks));

  const outside = invoke("get_skill_library_command", { root: profile });
  assert.notEqual(outside.status, 0);
  assert.match(outside.stdout, /outside configured workspace roots/i);

  // Ordinary bridge requests keep their 2 MiB ceiling.
  const oversized = invoke("get_native_tool_catalog_command", { padding: "x".repeat(2 * 1024 * 1024 + 1) });
  assert.notEqual(oversized.status, 0);
  assert.match(oversized.stdout, /request is too large/i);

  // A controller completion larger than the ordinary request ceiling reaches
  // its trusted identity gate, proving the bounded 10 MiB completion path.
  const completion = invoke("desktop_controller_complete_command", {
    sessionId: "fixture-session", requestId: "fixture-request", ok: true,
    data: { catalogText: "x".repeat(3 * 1024 * 1024) },
  });
  assert.notEqual(completion.status, 0);
  assert.doesNotMatch(completion.stdout, /request is too large|bounded completion size/i);

  const rust = readFileSync(path.join(root, "src-tauri", "src", "lib.rs"), "utf8");
  assert.match(rust, /async fn get_native_tool_catalog_command[\s\S]*?command: "get_native_tool_catalog_command"\.to_string\(\)/);
  assert.match(rust, /async fn get_skill_library_command[\s\S]*?command: "get_skill_library_command"\.to_string\(\)/);
  assert.match(rust, /get_native_tool_catalog_command,[\s\S]{0,100}get_skill_library_command,/);
  assert.doesNotMatch(rust, /run_agent_cli_json\(&app, root, "native-tools"/);
  process.stdout.write("Desktop capability bridge passed: native catalog, tool schema, skill summary, scoped request caps, and Tauri handler registration.\n");
} finally {
  rmSync(temp, { recursive: true, force: true });
}
