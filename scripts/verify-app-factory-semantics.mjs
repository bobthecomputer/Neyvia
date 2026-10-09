#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import process from "node:process";
import assert from "node:assert/strict";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:");
const code = String.raw`
import json, tempfile
from pathlib import Path
from grant_agent.app_factory import AppFactory
from grant_agent.app_factory_semantics import register_app_factory_job
from grant_agent.living_applications import LivingApplicationRegistry
from unittest.mock import patch

with tempfile.TemporaryDirectory() as d:
    workspace = Path(d) / "workspace"; workspace.mkdir()
    job = AppFactory(workspace).create(name="Semantic Demo", brief="A real local notes application for semantic proof", target="neyvia", template="notes", directory="demo")
    registry = LivingApplicationRegistry(); app = register_app_factory_job(job, registry=registry, persist_path=workspace / ".agent_control" / "living.json")
    checks = {'source': bool(app.source['revision']) and any(a.kind == 'source' for a in app.artifacts),
              'package': any(a.artifact_id == 'build:package' and a.verify() for a in app.artifacts),
              'localOnly': app.health['deployment'] == 'not attempted', 'permissions': app.permissions == [],
              'productionHook': (AppFactory(workspace).state_root / 'living-applications.json').is_file()}
    first = app.source["revision"]
    root = Path(job["projectRoot"])
    (root / "src" / "index.html").write_text("<h1>changed</h1>", encoding="utf-8")
    app2 = register_app_factory_job({**job, "jobId":"app-test-2"}, registry=registry, persist_path=workspace / ".agent_control" / "living.json")
    checks['lineage'] = app2.source['revision'] != first and app2.rollback['previousRevision'] == first
    checks['noFalseRollback'] = app2.rollback['available'] is False
    history_count = len(app2.history); proof_count = len(app2.proofs)
    fresh = register_app_factory_job(job, persist_path=workspace / '.agent_control' / 'living.json')
    checks['reload'] = fresh.source['revision'] == app2.source['revision']
    checks['unchangedRegistrationHasNoDuplicates'] = len(fresh.history) == history_count and len(fresh.proofs) == proof_count
    checks['unchangedRegistrationPreservesRollbackBoundary'] = fresh.rollback['previousRevision'] == first

    factory = AppFactory(workspace)
    lineage_job = factory.create(name="Lineage Demo", brief="A local checklist app for source revision checks", target="desktop", template="checklist", directory="lineage-demo")
    job_id = lineage_job['jobId']
    original = factory.get_job(job_id)
    original_source = original['verification'].get('sourceSha256')
    original_package = original['package'].get('sha256')
    original_receipt = Path(original['verification']['receiptPath'])
    checks['staticChecksAreLabeled'] = original['verification'].get('kind') == 'static-source-and-package' and original['verification'].get('runtimeVerified') is False and 'runtime behavior was not tested' in original['verification'].get('summary', '')
    checks['receiptBindsSourceAndPackage'] = json.loads(original_receipt.read_text(encoding='utf-8')).get('sourceSha256') == original_source and json.loads(original_receipt.read_text(encoding='utf-8')).get('package', {}).get('sha256') == original_package

    # Simulate a completed native build receipt, then edit an app source file.
    # The artifact stays on disk for audit, but its ready claim must go stale.
    native_artifact = Path(lineage_job['projectRoot']) / '.neyvia' / 'build' / 'demo.exe'
    native_artifact.parent.mkdir(parents=True, exist_ok=True)
    native_artifact.write_bytes(b'old native build receipt fixture')
    saved = factory.get_job(job_id)
    saved['nativeBuild'].update({'state': 'ready', 'sourceSha256': original_source, 'artifactPath': str(native_artifact), 'sha256': __import__('hashlib').sha256(native_artifact.read_bytes()).hexdigest(), 'bytes': native_artifact.stat().st_size})
    factory._save_job(saved)
    source = Path(lineage_job['projectRoot']) / 'src' / 'app.js'
    source.write_text(source.read_text(encoding='utf-8') + '\n// revision after ready\n', encoding='utf-8')
    stale = factory.get_job(job_id)
    checks['editInvalidatesAllClaims'] = stale['verification'].get('state') == 'pending' and stale['registration'].get('state') == 'stale' and stale['nativeBuild'].get('state') == 'stale' and stale['stages'][2]['state'] == 'pending' and stale['stages'][3]['state'] == 'pending' and stale['stages'][4]['state'] == 'pending'
    checks['staleNativeArtifactRetainedAsEvidence'] = stale['nativeBuild'].get('staleArtifactPath') == str(native_artifact) and native_artifact.is_file()

    # Prevent a real compiler launch while proving the stale executable is not returned as ready.
    rejected_stale_build = False
    with patch('grant_agent.app_factory.shutil.which', side_effect=lambda name: None if name in ('cargo', 'rustc') else None):
        try:
            factory.start_native_build(job_id)
        except RuntimeError as exc:
            rejected_stale_build = 'Cargo and Rust are required' in str(exc)
    checks['nativeBuildCannotReturnStaleArtifact'] = rejected_stale_build

    rebuilt = factory.resume(job_id)
    new_receipt = Path(rebuilt['verification']['receiptPath'])
    registry = json.loads(factory.registry_path.read_text(encoding='utf-8'))
    entry = next(item for item in registry['applications'] if item.get('jobId') == job_id)
    checks['resumeReassemblesAndReverifies'] = rebuilt['verification'].get('state') == 'passed' and rebuilt['verification'].get('sourceSha256') != original_source and rebuilt['package'].get('sha256') != original_package and rebuilt['verification'].get('packageSha256') == rebuilt['package'].get('sha256')
    checks['newReceiptAndRegistryBindNewBuild'] = json.loads(new_receipt.read_text(encoding='utf-8')).get('sourceSha256') == rebuilt['verification'].get('sourceSha256') and rebuilt['verification'].get('receiptSha256') == __import__('hashlib').sha256(new_receipt.read_bytes()).hexdigest() and entry.get('sourceSha256') == rebuilt['verification'].get('sourceSha256') and entry.get('packageSha256') == rebuilt['package'].get('sha256') and entry.get('runtimeVerified') is False
    checks['previewReassembledFromEditedSource'] = (Path(rebuilt['projectRoot']) / 'dist' / 'app.js').read_bytes() == source.read_bytes()
    print(json.dumps(checks))
`;
const result = spawnSync(process.env.PYTHON || "python", ["-c", code], {
  cwd: root, encoding: "utf8",
  env: { ...process.env, PYTHONPATH: `${root}/src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""}` },
});
if (result.status !== 0) { process.stderr.write(result.stderr || result.stdout || "app factory semantic verification failed\n"); process.exit(result.status || 1); }
const checks=JSON.parse(result.stdout);
for (const [name,passed] of Object.entries(checks)) assert.equal(passed,true,name);
console.log(JSON.stringify({status:'verified',checks}));
