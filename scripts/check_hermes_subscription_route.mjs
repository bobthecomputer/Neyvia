import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const base = process.argv[2] || "http://127.0.0.1:47884";
const login = await fetch(`${base}/api/auth/local-session`, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
});
assert.equal(login.status, 200);
const cookie = login.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
async function call(command, payload = {}) {
  const response = await fetch(`${base}/api/backend`, {
    method: "POST", headers: { "Content-Type": "application/json", Cookie: cookie },
    body: JSON.stringify({ command, payload }),
  });
  return { status: response.status, body: await response.json() };
}
const checks = [];
const state = await call("get_hermes_subscription_status_command");
assert.equal(state.status, 200);
assert.equal(state.body.data.provider, "claude-subscription-directsdk-experimental");
checks.push("readiness returned by authenticated backend");
const denied = await call("setup_hermes_subscription_command", { action: "install", acknowledged: false });
assert.equal(denied.body.ok, false);
assert.match(denied.body.error, /acknowledge/i);
checks.push("unacknowledged installation rejected before terminal launch");
if (!state.body.data.compatible) {
  for (const action of ["install", "login", "acknowledge"]) {
    const blocked = await call("setup_hermes_subscription_command", { action, acknowledged: true });
    assert.equal(blocked.body.ok, false);
    assert.match(blocked.body.error, /0\.21\.4|version|Install Hermes/i);
    checks.push(`incompatible runtime rejects ${action}`);
  }
}
mkdirSync("proof/claude-subscription-20260929", { recursive: true });
writeFileSync("proof/claude-subscription-20260929/backend-checks.json", JSON.stringify({
  checkedAt: new Date().toISOString(), checks, readiness: state.body.data, inferenceTested: false,
}, null, 2));
console.log(checks.join("\n"));
