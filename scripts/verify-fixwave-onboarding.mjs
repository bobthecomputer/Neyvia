import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";

const repo = path.resolve(import.meta.dirname, "..");
const python = process.env.NX_PYTHON || "C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe";
const scratch = mkdtempSync(path.join(tmpdir(), "fixwave-item6-"));
const url = "http://127.0.0.1:47966";
const env = { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.join(repo, "src") };
const processServer = spawn(python, ["scripts/run_web_backend.py", "--host", "127.0.0.1", "--port", "47966", "--root", scratch, "--skip-runtime-auto-update"], { cwd: repo, env, windowsHide: true, stdio: "ignore" });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let cookie = "";
const command = async (command, payload = {}) => {
  const response = await fetch(`${url}/api/backend`, { method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie }, body: JSON.stringify({ command, payload }) });
  const body = await response.json();
  assert.equal(response.status, 200, JSON.stringify(body));
  assert.equal(body.ok, true, JSON.stringify(body));
  return body.data;
};
const waitInstalled = async packId => {
  for (let tick = 0; tick < 200; tick++) {
    const row = (await command("onboarding_pack_status_command", { packId })).packs[0];
    if (row.state === "installed") return row;
    assert.notEqual(row.state, "failed", row.error);
    await sleep(100);
  }
  throw new Error(`${packId} did not complete its worker`);
};
try {
  let ready = false;
  for (let tick = 0; tick < 300; tick++) {
    if (processServer.exitCode !== null) throw new Error(`Backend exited ${processServer.exitCode}`);
    try { await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(500) }); ready = true; break; } catch { await sleep(100); }
  }
  assert.equal(ready, true, "Local backend never listened");
  const auth = await fetch(`${url}/api/auth/local-session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  assert.equal(auth.status, 200);
  cookie = auth.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
  const before = (await command("onboarding_pack_status_command")).packs;
  assert.equal(before.length, 15);
  const installed = [], unavailable = [];
  for (const row of before) {
    const first = (await command("onboarding_pack_install_command", { packId: row.packId })).packs[0];
    if (first.state === "unavailable") {
      assert.ok(first.missing.length > 0, `${row.packId} lacks an exact missing payload list`);
      unavailable.push({ packId: row.packId, missing: first.missing, error: first.error });
      continue;
    }
    const done = await waitInstalled(row.packId);
    assert.equal(done.stagedOnly, true);
    assert.equal(done.deliveryScope, "local-components");
    assert.equal(done.runtimeReady, false);
    const receipt = JSON.parse(readFileSync(done.receipt, "utf8"));
    for (const file of receipt.files) {
      const bytes = readFileSync(path.join(done.target, file.path));
      assert.equal(bytes.length, file.size);
      assert.equal(createHash("sha256").update(bytes).digest("hex"), file.sha256);
    }
    assert.ok(existsSync(path.join(done.target, "package.json")));
    const [module, method] = done.entrypoints[0].split(":");
    const probe = spawnSync(python, ["-c", `
import importlib,json,sys
from pathlib import Path
mod=importlib.import_module(sys.argv[1]); name=sys.argv[2]
assert Path(mod.__file__).resolve().is_relative_to(Path(sys.argv[3]).resolve())
target=Path(sys.argv[3]); root=target/'proof-workspace'; root.mkdir(exist_ok=True)
sample=root/'sample.txt'; sample.write_text('Local payload proof')
if name=='NearbySendService.build_plan':
 value=mod.NearbySendService(root).build_plan([sample],recipient_endpoint='http://127.0.0.1:47969')
elif name=='FolderSyncService.policy': value=mod.FolderSyncService(root).policy
elif name=='EncryptedChatService.lifecycle_snapshot': value=mod.EncryptedChatService(root).lifecycle_snapshot()
elif name=='SecretBrokerService.audit': value=mod.SecretBrokerService(root).audit()
elif name=='P2PCacheService.import_object':
 config=json.loads((target/'config/neyvia_p2p_cache.json').read_text()); config['cache']['root']=str(root/'objects')
 settings=root/'p2p.json'; settings.write_text(json.dumps(config))
 service=mod.P2PCacheService(root,config_path=settings); plan=service.plan_import(sample)
 imported=service.import_object(plan,approved=True); value=service.read_text(plan['objectHash'])
 assert value['text']=='Local payload proof'
else:
 fn=getattr(mod,name)
 value=fn('Hello iOS') if name=='_safe_slug' else fn('folder/file.txt','file.txt') if name=='_safe_relative_destination' else fn({'file':'local-proof','version':1})
print(json.dumps({'module':str(Path(mod.__file__).relative_to(Path(sys.argv[3]))),'result':str(value)}))
`, module, method, done.target], { cwd: scratch, env: { ...env, PYTHONPATH: path.join(done.target, "src") }, encoding: "utf8", windowsHide: true });
    assert.equal(probe.status, 0, probe.stderr);
    installed.push({ packId: row.packId, state: done.state, target: done.target, receipt: done.receipt, fileCount: receipt.files.length, bytes: done.totalBytes,
      payloadExecution: JSON.parse(probe.stdout), missing: done.missing, stagedOnly: done.stagedOnly });
  }
  assert.equal(installed.length, 8);
  assert.equal(unavailable.length, 7);
  // A durable receipt must never hide a corrupted delivery; the public install command repairs it.
  const selected = installed.find(row => row.packId === "pack.nas-worker");
  const payload = path.join(selected.target, "src/grant_agent/nas_transfer.py");
  writeFileSync(payload, "corrupt");
  const broken = (await command("onboarding_pack_status_command", { packId: selected.packId })).packs[0];
  assert.equal(broken.state, "failed");
  assert.match(broken.error, /checksum/);
  await command("onboarding_pack_install_command", { packId: selected.packId });
  await waitInstalled(selected.packId);
  const after = (await command("onboarding_state_command")).packs;
  assert.equal(after.filter(row => row.ready).length, 8);
  const receipt = { item: 6, timestamp: new Date().toISOString(), port: 47966, scratch, installedCount: installed.length, unavailableCount: unavailable.length,
    proof: "Authenticated real backend commands spawned downloader workers; all receipt bytes/SHA-256 and executable functions from delivered modules verified; corrupted payload detected and repaired through the same command.",
    installed, unavailable, corruptionRepair: { packId: selected.packId, detectedState: broken.state, repairedState: "installed" },
    limitations: ["Only the declared local helper/library/SDK components are staged; no system/runtime/service activation occurred.", "External engines and production pairing/signing/credentials remain explicitly listed by pack.", "UI wiring belongs to the Claude wave."] };
  writeFileSync(path.join(repo, "scripts/evidence/fixwave-item6.json"), JSON.stringify(receipt, null, 2) + "\n");
  console.log(JSON.stringify({ installed: installed.length, unavailable: unavailable.length, corruptedPayloadRepaired: true, receipt: "scripts/evidence/fixwave-item6.json" }));
} finally {
  processServer.kill();
  await Promise.race([new Promise(resolve => processServer.once("exit", resolve)), sleep(5000)]);
}
