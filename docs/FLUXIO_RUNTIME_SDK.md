# Fluxio Runtime SDK

The SDK lets another local project call the same backend command surface the Fluxio UI uses.
It is intentionally thin: Fluxio owns auth, runtime routing, connected-app state, receipts, and proof files.

```python
from grant_agent.sdk import FluxioClient

client = FluxioClient(
    "https://your-fluxio-host:47880",
    username="operator",
    password="...",
)

receipt = client.runtime_lane_cycle(
    "Plan, implement, and verify the Solantir interior-materials import flow.",
    route_dictation="GPT-5.6 Sol X high for planner, GPT-5.6 Sol high for executor, GPT-5.6 Luna medium for verifier",
    route_overrides=[
        {"role": "planner", "runtimeId": "hermes", "provider": "openai-codex", "model": "gpt-5.6-sol", "effort": "xhigh"},
        {"role": "executor", "runtimeId": "hermes", "provider": "openai-codex", "model": "gpt-5.6-sol", "effort": "high"},
        {"role": "verifier", "runtimeId": "hermes", "provider": "openai-codex", "model": "gpt-5.6-luna", "effort": "medium"},
    ],
)
print(receipt["status"], receipt["receiptPath"])
```

Useful calls:

- `client.runtime_auto_update(force=False, dry_run=False)` checks/updates Hermes, OpenCLAW, native OpenCode, and Cursor Agent and returns the startup-style receipt.
- `client.runtime_lane_cycle(...)` runs planner, executor, and verifier as separate turns and returns a per-lane route/proof receipt.
- `client.start_mission(...)` launches a durable Control Room mission with route overrides and an optional structured mission contract.
- `client.mission_detail(...)` reads the mission, artifact gate, receipts, and current runtime state.
- `client.wait_for_mission(...)` polls until the mission reaches a truthful terminal state such as completed, blocked, or failed.
- `client.source_intelligence_mission(...)` launches the evidence-gated source workflow used by Mission 2. It requires consulted-source records, real screenshot files, a source manifest, and a linked typed verifier receipt.
- `client.following_digest_mission(...)` enumerates an operator's real X following list through the verified free, no-key FxTwitter route, reads public timelines through Folo/RSSHub, ranks recent findings, and produces a meeting-ready brief. It blocks instead of substituting a seeded list.
- `route_dictation="..."` on `runtime_lane_cycle(...)`, `workspace-save --route-dictation`, `mission-start --route-dictation`, or the `parse_route_dictation_command` backend call turns spoken routing text into planner/frontend/backend/verifier route rows.
- Cursor Agent routing and CLI setup are documented in `docs/CURSOR_AGENT_RUNTIME.md`.
- `client.solantir_intelligence_cycle(...)` remains a compatibility helper for a three-lane Solantir readiness cycle. Use `source_intelligence_mission(...)` when the result must be a durable mission with evidence-gated artifacts.
- `client.solantir_trading_platform_mission(...)` launches the typed Solantir product-rebuild contract. Its default `trading_rebuild` recipe uses Sol low for planning, OpenCodeGo GLM 5.2 for frontend execution, and Luna xhigh for verification. Pass `recipe="classic_intelligence"` to restore the previous source-intelligence prompt and route.
- `client.agent_chat(...)` sends one Agent Live turn through a selected runtime/provider/model.
- `client.connected_apps()` reads Fluxio connected-app bridge state.
- `client.application_surfaces()` lists optional workspace-built desktop/web surfaces with truthful target availability.
- `client.validate_application_surface(...)`, `client.application_surface_status(...)`, and `client.plan_application_surface_launch(...)` validate and permission-bind app launch descriptors without building, installing, or launching. Launch readiness requires current evidence plus an exact plan-bound approval receipt; caller-supplied permission lists do not approve it.
- `client.observe_application_surface(...)` reads bounded workspace-scoped log tails and proof hashes. See `docs/NEYVIA_SDK_APPLICATION_SURFACES.md`.
- `client.record_delivery_receipt(...)` records a DR row through Fluxio after a browser notification, preview check, or supervised app event.

Solantir feed and DR route:

```python
from grant_agent.sdk import FluxioClient

client = FluxioClient("http://127.0.0.1:47880", username="operator", password="...")

receipt = client.solantir_intelligence_cycle(
    "Verify RSS feeds, camera/live-news panels, browser preview, and DR receipts before improving the Solantir UI.",
    workspace_path="Y:/projects/solantir-mindtower-fusion/Solantir",
)

client.record_delivery_receipt(
    mission_id=receipt.get("missionId", ""),
    event_kind="solantir.verification.completed",
    event_message="Solantir feed, camera, preview, and DR checks completed.",
    origin_runtime="hermes",
    origin_provider="openai-codex",
    origin_model="gpt-5.6-luna",
)
```

Keep social credentials outside manifests, proof files, and browser-visible UI. Pass temporary credentials only through the local runtime/session that needs them, then rotate them.

## Evidence-gated source research

```python
from grant_agent.sdk import FluxioClient

client = FluxioClient("http://127.0.0.1:47880", username="operator", password="...")

launch = client.source_intelligence_mission(
    ["Solantir", "verified claims"],
    workspace_id="workspace_solantir",
    sources=["x-twitter", "open-web"],
    references=["https://example.com/reference"],
)

mission_id = launch.get("mission_id") or launch.get("missionId")
detail = client.wait_for_mission(mission_id, timeout_seconds=1800)
print(detail["artifactGate"]["status"])
```

This method requests the current default route:

- planner: `gpt-5.6-sol`, `xhigh`
- executor: `gpt-5.6-sol`, `high`
- verifier: `gpt-5.6-luna`, `medium`

The contract declares browser preview and source reading as required capabilities. Declaring a capability does not fabricate it. If the selected runtime cannot read the requested sources, the mission must remain blocked and explain the missing tool or authentication path.

For a followed-account meeting brief:

```python
launch = client.following_digest_mission(
    "PoleSoude",
    topics=["maritime autonomy", "AI coding workbenches"],
    lookback_days=7,
)
```

The default route needs no X login and no paid API key. It uses FxTwitter for the real following list and Folo/RSSHub for public recent posts, while preserving provider URLs, cursors, timestamps, counts, and failures in a source receipt. Authenticated browser or official API access remains an optional fallback only. The workflow never treats manually seeded accounts as the operator's real following list.

The same collection step is available directly from the local CLI:

```powershell
python scripts/run_grant_agent_cli.py x-following-collect --root . --username PoleSoude --output-dir .agent_control/mission_artifacts/following-digest/free-api-sources
```

It writes a timestamped following snapshot, recent-post dataset, access receipt, and SHA-256 source manifest without storing credentials.

For app integration manifests:

```python
from grant_agent.sdk import build_app_manifest, build_solantir_manifest, write_app_manifest

manifest = build_app_manifest(
    app_id="solantir-interior",
    name="Solantir Interior",
    description="Interior project catalog and workflow surfaces exposed to Fluxio.",
    endpoint="http://127.0.0.1:48710/fluxio",
    tasks=[{"task_id": "import-materials", "label": "Import materials", "description": "Import supplier materials into the catalog."}],
    context_surfaces=[{"surface_id": "material-catalog", "label": "Material catalog", "description": "Readable catalog status.", "access": "read"}],
    action_hooks=[{"hook_id": "queue-import", "label": "Queue import", "description": "Queue a material import job.", "mutability": "write"}],
)
write_app_manifest("config/connected_apps.solantir.json", manifest)

solantir_manifest = build_solantir_manifest(
    workspace_root="Y:/projects/solantir-mindtower-fusion/Solantir",
)
write_app_manifest("config/connected_apps.solantir-terminal.json", solantir_manifest)
```

## Signed module package preflight

The SDK now exposes the local, non-activating part of the marketplace contract. An
app builder can validate its module manifest, inspect the immutable package, and
produce the exact staged-install blockers before publication:

```python
import json

from grant_agent.sdk import (
    inspect_module_package,
    plan_module_install,
    validate_module_manifest,
)

manifest = json.loads(open("neyvia.module.json", encoding="utf-8").read())

validation = validate_module_manifest(manifest, workspace_root=".")
if not validation["valid"]:
    raise ValueError(validation["errors"])

inspection = inspect_module_package(
    manifest,
    "dist/my-app.nymod",
    workspace_root=".",
)
plan = plan_module_install(
    manifest,
    "dist/my-app.nymod",
    workspace_root=".",
)
print(inspection["safeToVerify"], plan["blockedBy"])
```

These helpers do not extract, execute, publish, install, or activate code. A safe
package still requires real Cosign, SBOM-policy, malware, permission-review, and
isolated smoke-test receipts. Runtime activation and marketplace publication remain
the next platform phase; the versioned contract is
`config/neyvia_module_manifest_schema.json`.
