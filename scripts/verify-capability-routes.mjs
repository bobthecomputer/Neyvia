#!/usr/bin/env node
/** Small executable contract check for capability routing.
 * It exercises the Python module through its public function, including the
 * important requested-versus-observed route boundary.
 */
import { spawnSync } from "node:child_process";
import process from "node:process";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:");
const code = String.raw`
import json
from grant_agent.capability_routes import route_capability

routes = [
 {"routeId":"local-safe","provider":"local","runtime":"neyvia-agent","model":"local-1","effort":"high","capabilities":["planning","tools"],"tools":["read"],"contextTokens":32768,"privacyBoundary":"local","budget":{"latencyMs":5000}},
 {"routeId":"remote-fast","provider":"remote","runtime":"codex","model":"gpt-5.6-sol","effort":"high","capabilities":["planning"],"tools":["read"],"contextTokens":0,"privacyBoundary":"remote"},
]
req = {"preferredRouteId":"local-safe","capabilities":["planning","tools"],"minimumEffort":"high","tools":["read"],"minimumContextTokens":16000,"privacyBoundary":"local"}
first = route_capability(routes, req)
assert first["status"] == "selected" and first["evidenceStatus"] == "unobserved"
assert first["routeEvidence"] is None
fallback = route_capability(routes, {"preferredRouteId":"missing", "capabilities":["planning"], "minimumEffort":"high"}, fallback_authorized=True)
assert fallback["status"] == "selected" and fallback["fallback"]["used"] is True
unauthorized = route_capability(routes, {"preferredRouteId":"missing", "capabilities":["planning"], "minimumEffort":"high"})
assert unauthorized["status"] == "blocked"  # missing preference is never silently substituted
observed = route_capability(routes, req, observed={"routeId":"remote-fast","model":"gpt-5.6-sol","runtime":"codex"})
assert observed["evidenceStatus"] == "mismatch"
print(json.dumps({"passed": True, "checks": ["constraints", "explicit-fallback", "observed-route-boundary"]}))
`;
const result = spawnSync(process.env.PYTHON || "python", ["-c", code], {
  cwd: root,
  encoding: "utf8",
  env: { ...process.env, PYTHONPATH: `${root}/src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""}` },
});
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || "capability route verification failed\n");
  process.exit(result.status || 1);
}
process.stdout.write(result.stdout);
