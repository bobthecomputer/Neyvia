import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const temporaryRoot = mkdtempSync(join(tmpdir(), "neyvia-provider-catalog-proof-"));
const py = process.env.NEYVIA_PYTHON || "python";
const pythonEnv = { ...process.env, PYTHONPATH: [join(root, "src"), process.env.PYTHONPATH].filter(Boolean).join(";") };
const runPython = source => execFileSync(py, ["-c", source], {
  cwd: root,
  env: pythonEnv,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});

try {
  const catalogPath = join(temporaryRoot, ".agent_control", "provider_model_catalog.modelsdev.json");
  mkdirSync(join(temporaryRoot, ".agent_control"), { recursive: true });
  writeFileSync(catalogPath, JSON.stringify({ fetchedAt: new Date().toISOString(), catalog: {
    deepinfra: {
      id: "deepinfra", name: "Deep Infra", env: ["DEEPINFRA_API_KEY"], npm: "@ai-sdk/deepinfra",
      models: {
        "deepseek-ai/DeepSeek-V3.2": {
          id: "deepseek-ai/DeepSeek-V3.2", name: "DeepSeek V3.2", reasoning: true, tool_call: true,
          modalities: { input: ["text"] }, limit: { context: 128000, output: 32000 }, release_date: "2026-09-01",
        },
      },
    },
  } }), "utf8");

  const authPath = join(temporaryRoot, "opencode-auth.json");
  writeFileSync(authPath, JSON.stringify({ retained: { type: "api", key: "KEEPER_FIXTURE_VALUE" } }), "utf8");
  const inputKey = "PROVIDER_FIXTURE_SECRET";
  const result = JSON.parse(runPython([
    "import json,sys",
    "from pathlib import Path",
    "from grant_agent.provider_catalog import build_provider_catalog, save_opencode_provider_api_key",
    `root=Path(${JSON.stringify(temporaryRoot)})`,
    `auth=Path(${JSON.stringify(authPath)})`,
    "catalog=build_provider_catalog(root, refresh=False)",
    `saved=save_opencode_provider_api_key('deepinfra', ${JSON.stringify(inputKey)}, workspace_root=root, auth_path=auth)`,
    "before=auth.read_bytes()",
    `replace=save_opencode_provider_api_key('deepinfra', 'SECOND_FIXTURE_SECRET', workspace_root=root, auth_path=auth)`,
    "unchanged=before==auth.read_bytes()",
    "document=json.loads(auth.read_text(encoding='utf-8'))",
    "model=catalog['providers'][0]['models'][0]",
    "print(json.dumps({'providerCount':catalog['providerCount'],'modelCount':catalog['modelCount'],'routeId':model['routeId'],'routeListed':model['routeListed'],'toolCall':model['toolCall'],'save':saved,'replace':replace,'unchangedOnUnconfirmedReplace':unchanged,'retainedProvider':document['retained']['type'],'storedProvider':document['deepinfra']['type'],'storedKeyMatches':document['deepinfra']['key']==" + JSON.stringify(inputKey) + "}))",
  ].join("\n")));
  assert.equal(result.providerCount, 1);
  assert.equal(result.modelCount, 1);
  assert.equal(result.routeId, "deepinfra/deepseek-ai/DeepSeek-V3.2");
  assert.equal(result.routeListed, false);
  assert.equal(result.toolCall, true);
  assert.equal(result.save.ok, true);
  assert.equal(result.save.credentialsPresent, true);
  assert.equal(JSON.stringify(result).includes(inputKey), false, "result must not echo provider secret");
  assert.equal(result.replace.error, "credential_replace_confirmation_required");
  assert.equal(result.unchangedOnUnconfirmedReplace, true);
  assert.equal(result.retainedProvider, "api");
  assert.equal(result.storedProvider, "api");
  assert.equal(result.storedKeyMatches, true);
  console.log("Provider catalog/auth integration passed: nested route IDs, tool metadata, safe provider-store merge, and explicit replacement confirmation.");
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
