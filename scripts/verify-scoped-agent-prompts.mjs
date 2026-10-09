import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(".");
const scratch = mkdtempSync(join(tmpdir(), "neyvia-scoped-prompts-"));
const store = join(scratch, "agent_prompts.json");
const startPython = (source, env) => new Promise((resolvePromise, rejectPromise) => {
  const child = spawn("python", ["-c", source], { cwd: root, encoding: "utf8", env });
  let stdout = ""; let stderr = "";
  child.stdout.setEncoding("utf8").on("data", chunk => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", chunk => { stderr += chunk; });
  child.on("error", rejectPromise);
  child.on("close", code => code === 0 ? resolvePromise(JSON.parse(stdout.trim())) : rejectPromise(new Error(stderr || "concurrent prompt writer failed")));
});
const python = String.raw`
import json, os
from pathlib import Path
from grant_agent.agent_prompt_library import load_prompt_library, save_prompt_library, reset_prompt_library, compiled_role_prompt
root = Path(os.environ["NEYVIA_TEST_ROOT"])
def save(revision, scope_id, role, text, **route):
    payload = {"expectedRevision": revision, "scopeId": scope_id, "role": role, "instructions": text, **route}
    return save_prompt_library(root, payload)
state = load_prompt_library(root)
state = save_prompt_library(root, {"expectedRevision": state["revision"], "roles": {"chat": {"instructions": "GLOBAL_DISPOSABLE_PROMPT"}}})
global_text = compiled_role_prompt(root, "chat")
state = save(state["revision"], "runtime:neyvia native", "chat", "RUNTIME_DISPOSABLE_PROMPT", runtime="Neyvia Native", provider=None, model=None)
runtime_text = compiled_role_prompt(root, "chat", runtime=" NEYVIA NATIVE ", provider="DeepSeek", model="V4.1 Flash")
state = save(state["revision"], "model:deepseek|v4.1 flash", "chat", "MODEL_A_DISPOSABLE_PROMPT", runtime=None, provider="DeepSeek", model="V4.1 Flash")
model_a = compiled_role_prompt(root, "chat", runtime="Neyvia Native", provider=" deepseek ", model="v4.1 flash")
state = save(state["revision"], "route:neyvia native|openai|gpt-6 luna", "chat", "MODEL_B_DISPOSABLE_PROMPT", runtime="Neyvia Native", provider="OpenAI", model="GPT-6 Luna")
model_b = compiled_role_prompt(root, "chat", runtime="NEYVIA NATIVE", provider="OPENAI", model="gpt-6 luna")
resolved = load_prompt_library(root, runtime="Neyvia Native", provider="DeepSeek", model="V4.1 Flash")
assert global_text == "GLOBAL_DISPOSABLE_PROMPT"
assert runtime_text == "RUNTIME_DISPOSABLE_PROMPT"
assert model_a == "MODEL_A_DISPOSABLE_PROMPT"
assert model_b == "MODEL_B_DISPOSABLE_PROMPT"
assert resolved["resolutions"]["chat"]["scopeId"] == "model:deepseek|v4.1 flash"
assert resolved["resolutions"]["chat"]["hash"]
old_revision = state["revision"]
state = reset_prompt_library(root, "chat", old_revision, scope_id="model:deepseek|v4.1 flash", provider="DeepSeek", model="V4.1 Flash")
assert compiled_role_prompt(root, "chat", runtime="Neyvia Native", provider="DeepSeek", model="V4.1 Flash") == "RUNTIME_DISPOSABLE_PROMPT"
assert compiled_role_prompt(root, "chat") == "GLOBAL_DISPOSABLE_PROMPT"
try:
    save_prompt_library(root, {"expectedRevision": old_revision, "scopeId": "runtime:neyvia native", "runtime": "Neyvia Native", "role": "chat", "instructions": "STALE"})
except ValueError as exc:
    assert "revision conflict" in str(exc)
else:
    raise AssertionError("stale scoped save was accepted")
print(json.dumps({"globalUnchanged": True, "runtimeIndependent": True, "twoModelRoutesIndependent": True, "caseWhitespaceCanonical": True, "resetInherits": True, "staleRevisionRejected": True, "resolutionHashReturned": True}))
`;
try {
  const result = spawnSync("python", ["-c", python], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: `${resolve("src")};${process.env.PYTHONPATH || ""}`, NEYVIA_AGENT_PROMPT_FILE: store, NEYVIA_TEST_ROOT: root },
  });
  assert.equal(result.status, 0, result.stderr || "prompt library check failed");
  const report = JSON.parse(result.stdout.trim());
  for (const [name, passed] of Object.entries(report)) assert.equal(passed, true, `${name} failed`);

  const revisionResult = spawnSync("python", ["-c", "import json,os; from pathlib import Path; from grant_agent.agent_prompt_library import load_prompt_library; print(load_prompt_library(Path(os.environ['NEYVIA_TEST_ROOT']))['revision'])"], {
    cwd: root, encoding: "utf8", env: { ...process.env, PYTHONPATH: `${resolve("src")};${process.env.PYTHONPATH || ""}`, NEYVIA_AGENT_PROMPT_FILE: store, NEYVIA_TEST_ROOT: root },
  });
  assert.equal(revisionResult.status, 0, revisionResult.stderr);
  const concurrentEnv = { ...process.env, PYTHONPATH: `${resolve("src")};${process.env.PYTHONPATH || ""}`, NEYVIA_AGENT_PROMPT_FILE: store, NEYVIA_TEST_ROOT: root, EXPECTED_REVISION: revisionResult.stdout.trim() };
  const writer = text => startPython(String.raw`
import json, os
from pathlib import Path
from grant_agent.agent_prompt_library import save_prompt_library
payload = {"expectedRevision": int(os.environ["EXPECTED_REVISION"]), "scopeId": "runtime:concurrency probe", "runtime": "Concurrency Probe", "role": "chat", "instructions": os.environ["TEST_PROMPT"]}
try:
    save_prompt_library(Path(os.environ["NEYVIA_TEST_ROOT"]), payload)
    print(json.dumps({"result": "saved"}))
except ValueError as exc:
    if "revision conflict" not in str(exc): raise
    print(json.dumps({"result": "conflict"}))
`, { ...concurrentEnv, TEST_PROMPT: text });
  const concurrentResults = await Promise.all([writer("CONCURRENT_DISPOSABLE_A"), writer("CONCURRENT_DISPOSABLE_B")]);
  assert.deepEqual(concurrentResults.map(item => item.result).sort(), ["conflict", "saved"]);

  const importModule = await import(pathToFileURL(resolve("web/src/neyvia/promptFileImport.js")));
  const importedTxt = await importModule.readPromptImport(new File(["\uFEFF# Keep  all  spaces\r\n"], "prompt.txt", { type: "text/plain" }));
  assert.equal(importedTxt.text, "# Keep  all  spaces\r\n");
  assert.equal(importedTxt.fileName, "prompt.txt");
  const importedMd = await importModule.readPromptImport(new File(["# Markdown prompt"], "prompt.md", { type: "text/markdown" }));
  assert.equal(importedMd.text, "# Markdown prompt");
  await assert.rejects(importModule.readPromptImport(new File(["x"], "prompt.pdf")), /\.txt or \.md/);
  console.log(JSON.stringify({ ...report, crossProcessRevisionConflict: true, txtImport: true, markdownImport: true, unsupportedImportRejected: true }));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
