#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import process from "node:process";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:");
const code = String.raw`
import hashlib, json, tempfile
from pathlib import Path
from grant_agent.living_applications import ArtifactRecord, LivingApplication, SupervisedAutonomy

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "build.bin"
    path.write_bytes(b"living-app-build")
    artifact = ArtifactRecord.from_file("build-1", path, kind="build")
    app = LivingApplication("demo")
    app.add_artifact(artifact)
    receipt = app.record_deployment({"deploymentId":"d1", "artifactId":"build-1", "environment":"staging"})
    assert receipt["artifactSha256"] == hashlib.sha256(b"living-app-build").hexdigest()
    path.write_bytes(b"tampered")
    try:
        app.record_deployment({"deploymentId":"d2", "artifactId":"build-1"})
    except ValueError:
        pass
    else:
        raise AssertionError("tampered artifact was accepted")

    policy = SupervisedAutonomy("maintain demo", permitted_actions={"inspect"}, budget=1, evidence_threshold=1, state_path=str(Path(directory) / "autonomy.json"))
    assert policy.authorize("inspect", authority=True, evidence_count=1, cost=1)["allowed"]
    assert not policy.authorize("inspect", authority=True, evidence_count=1, cost=1)["allowed"]
    assert not policy.authorize("publish", authority=True, evidence_count=1)["allowed"]
    policy2 = SupervisedAutonomy.from_state_file(Path(directory) / "autonomy.json")
    assert policy2.budget_used == 1 and not policy2.authorize("inspect", authority=True, evidence_count=1, cost=1)["allowed"]
    policy2.revoke("operator stop")
    assert not SupervisedAutonomy.from_state_file(Path(directory) / "autonomy.json").authorize("inspect", authority=True, evidence_count=1)["allowed"]
print(json.dumps({"passed": True, "checks": ["artifact-hash", "receipt-only-deployment", "budget", "permission", "revocation", "durable-state"]}))
`;
const result = spawnSync(process.env.PYTHON || "python", ["-c", code], {
  cwd: root,
  encoding: "utf8",
  env: { ...process.env, PYTHONPATH: `${root}/src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""}` },
});
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || "living application verification failed\n");
  process.exit(result.status || 1);
}
process.stdout.write(result.stdout);

