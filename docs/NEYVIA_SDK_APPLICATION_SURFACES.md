# SDK application surfaces

`neyvia.application-surface/v1` lets a workspace-built app optionally declare a
desktop or web surface as an agent-discoverable and user-controllable tool. The
contract is intentionally bounded: it validates declarations, reports current
evidence, binds permissions, creates launch plans, and reads log/proof hooks. It
does not build, install, launch, publish, or sign an app.

The optional block lives in the existing Fluxio app capability manifest under
`application_surface`. Apps without this block remain valid headless apps.

## Build a declaration

```python
from grant_agent.sdk import build_app_manifest, build_application_surface

surface = build_application_surface(
    surface_id="catalog.preview",
    title="Catalog Preview",
    description="Local web and Windows surfaces for the workspace catalog.",
    permissions={
        "inspect": ["workspace.read"],
        "launch": ["process.execute"],
        "control": ["device.control"],
    },
    targets=[
        {
            "target_id": "web.local",
            "kind": "web",
            "platform": "web",
            "build": {"status": "not_required"},
            "launch": {
                "kind": "url",
                "url": "http://127.0.0.1:4173",
            },
            "required_permissions": [],
            "readiness": {
                "receipt_id": "web-readiness-catalog",
                "max_age_seconds": 300,
            },
        },
        {
            "target_id": "windows.local",
            "kind": "desktop",
            "platform": "windows",
            "build": {
                "status": "available",
                "artifact": "dist/catalog.exe",
                "sha256": "<64 lowercase hex characters>",
                "size_bytes": 123456,
                "media_type": "application/vnd.microsoft.portable-executable",
                "architecture": "x86_64",
                "proof_paths": ["proof/windows-build.json"],
                "evidence": {
                    "receipt_id": "windows-build-catalog",
                    "max_age_seconds": 86400,
                },
            },
            "launch": {
                "kind": "artifact",
                "artifact": "dist/catalog.exe",
                "arguments": [],
            },
            "required_permissions": ["process.execute"],
        },
        {
            "target_id": "ios.phone",
            "kind": "desktop",
            "platform": "ios",
            "build": {
                "status": "unavailable",
                "reason": "No signed iOS artifact or device proof exists.",
            },
            "required_permissions": ["device.control"],
        },
    ],
    lifecycle={
        "status_file": ".agent_control/app-surface/status.json",
        "stream_id": "catalog-runtime",
        "max_age_seconds": 120,
    },
    observability={
        "log_paths": [".agent_control/app-surface/runtime.log"],
        "proof_paths": ["proof/browser-check.png"],
    },
)

manifest = build_app_manifest(
    app_id="catalog-studio",
    name="Catalog Studio",
    description="Workspace catalog app.",
    endpoint="local://catalog-studio",
    tasks=[{
        "task_id": "inspect-catalog",
        "label": "Inspect catalog",
        "description": "Read current catalog state.",
    }],
    context_surfaces=[{
        "surface_id": "catalog",
        "label": "Catalog",
        "description": "Current catalog state.",
        "access": "read",
    }],
    action_hooks=[{
        "hook_id": "plan-open",
        "label": "Plan open",
        "description": "Create a launch plan.",
        "mutability": "read",
    }],
    application_surface=surface,
)
```

The machine-readable schema is
`config/neyvia_application_surface_schema.json`. Runtime validation also
enforces relationships that JSON Schema alone cannot express:

- web targets use `platform: web`, `kind: web`, `build.status: not_required`,
  and an `http` or `https` launch URL;
- launchable desktop targets use a workspace-relative artifact that matches
  the declared build artifact;
- paths cannot be absolute or escape the workspace;
- an unavailable target includes a specific reason;
- a desktop artifact is launch-ready only on its matching host platform;
- Android and iOS targets remain `unavailable` in this v1 contract. A manifest
  cannot claim a launchable mobile build or device proof.

## Inspect and plan

```python
from grant_agent.sdk import (
    get_application_surface_status,
    observe_application_surface,
    plan_application_surface_launch,
)

status = get_application_surface_status(
    manifest,
    workspace_root=".",
    target_id="windows.local",
)

plan = plan_application_surface_launch(
    manifest,
    workspace_root=".",
    target_id="windows.local",
    permission_mode="always_ask",
    approval_id="approval-catalog-20260724",
)

evidence = observe_application_surface(
    manifest,
    workspace_root=".",
    max_log_lines=80,
    max_proof_files=20,
)
```

Those convenience functions deliberately use the fail-closed default and do
not load a receipt key from the workspace. A trusted host can inject a verifier
into its capability service without exposing a minting operation to the model:

```python
from grant_agent.application_surface import ExternalReceiptAuthority
from grant_agent.capability_service import CapabilityService

authority = ExternalReceiptAuthority(
    external_ledger_path,
    verification_key_from_host_broker,
)
capabilities = CapabilityService(
    ".",
    application_surface_receipt_authority=authority,
)
status = capabilities.application_surfaces.status(
    manifest,
    target_id="web.local",
)
```

A launch plan has one of four states:

- `ready`: the target evidence exists and a bound approval receipt grants the
  effective permissions;
- `approval_required`: the target exists, but explicit permissions are still
  required;
- `unavailable`: a build, artifact, URL, or target is unavailable;
- `blocked`: the permission mode denies the requested launch.

Every plan includes `executionPolicy.executes: false`. A caller can hand the
validated descriptor to a separately approved platform launcher, but the SDK
does not quietly spawn a process.

URL syntax alone is not readiness. A web target remains `declared` until a
fresh externally signed `neyvia.application-surface-web-proof/v1` receipt
binds the exact target and URL and identifies a trusted browser or health
verifier. A desktop file remains `present` until its actual SHA-256, size,
executable type, host architecture, platform-verified signature, and external
`neyvia.application-surface-desktop-proof/v1` build receipt all agree.

Launch permissions cannot be weakened by the manifest. Desktop plans always
include `process.execute`; web plans always include `network.read` and
`device.control`. Every launch remains approval-required until the host runtime
is provisioned with an `ExternalReceiptAuthority` whose key and append-only
ledger both live outside the editable workspace. It must verify a fresh,
single-use `neyvia.application-surface-approval/v1` receipt that binds the
exact plan hash, manifest hash, target, and complete permission set.
Caller-supplied `approvedPermissions` and workspace JSON have no authority.
The SDK exposes verification and planning only; it has no receipt-minting
helper, and the separate broker/launcher must consume an approval before use.
The host can inject the verify-only authority through
`CapabilityService(..., application_surface_receipt_authority=authority)`;
without that explicit provisioning every checked-in/default trust decision
remains unproven.

`planHash` is deterministic and covers the manifest, artifact/readiness
evidence, effective permissions, and launch descriptor. Changing any of those
invalidates an existing approval.

The approval payload below is wrapped in a signed
`neyvia.external-receipt-envelope/v1` by the external operator approval
workflow, never by the manifest or model-facing SDK:

```json
{
  "schema": "neyvia.application-surface-approval/v1",
  "approvalId": "approval-catalog-20260724",
  "status": "approved",
  "planHash": "<exact launch plan hash>",
  "manifestHash": "<exact application manifest hash>",
  "targetId": "web.local",
  "approvedPermissions": ["device.control", "network.read"],
  "approvedBy": "operator:paul",
  "approvedAt": "2026-07-24T10:29:00Z",
  "expiresAt": "2026-07-24T10:39:00Z"
}
```

Status is also evidence-bounded. Workspace lifecycle JSON may be returned as
`reportedState`, but it never controls status. Only an externally signed
ledger stream can do that. Its receipts require a monotonic sequence,
previous-receipt hash chain, valid state transitions, and bindings to the
current manifest, plan, target, artifact, and run ID. A running receipt also
binds the active process image, command hash, and creation identity. Web runs
add an exact URL and trusted readiness-receipt binding. A live PID alone is
never sufficient.

## Logs and proof

All observability hooks are workspace-relative. Log reads return at most 200
lines and 64 KiB of tail content per file, with 8 MiB source-file and 256 KiB
aggregate limits. The reader includes a bounded overlap for redaction, drops
the first partial line of a tail, and replaces model-visible secrets with
`[REDACTED]`. Proof hashes use 16 MiB per-file and 64 MiB aggregate limits.
Oversized files are reported without being read or hashed. Reads use a stable
file handle, reject links/reparse points, validate Windows kernel-resolved
final paths, and recheck identity after security-sensitive verification.

Each lifecycle envelope contains a payload like this:

```json
{
  "schema": "neyvia.application-surface-lifecycle/v1",
  "streamId": "catalog-runtime",
  "sequence": 3,
  "previousReceiptHash": "<hash of sequence 2 receipt>",
  "state": "running",
  "previousState": "launching",
  "updatedAt": "2026-07-24T10:30:00Z",
  "runId": "run-catalog-1",
  "manifestHash": "<manifest hash>",
  "planHash": "<launch plan hash>",
  "targetId": "web.local",
  "artifactSha256": "",
  "process": {
    "pid": 1234,
    "imagePath": "<kernel-resolved executable path>",
    "imageSha256": "<executable hash>",
    "commandHash": "<command line hash>",
    "creationIdentity": "<OS process creation identity>"
  },
  "listener": {
    "url": "http://127.0.0.1:4173",
    "host": "127.0.0.1",
    "port": 4173,
    "protocol": "tcp",
    "pid": 1234,
    "observedAt": "2026-07-24T10:30:00Z",
    "readinessReceiptId": "web-readiness-catalog",
    "readinessReceiptHash": "<trusted receipt hash>"
  },
  "detail": "Local preview server is accepting requests."
}
```

Allowed states are `declared`, `ready`, `launching`, `running`, `stopped`,
`failed`, and `unavailable`.

## Capability and remote SDK surface

The capability service exposes four progressively discoverable model tools:

- `app.surface.catalog`
- `app.surface.status`
- `app.surface.launch.plan`
- `app.surface.observe`

They keep schemas deferred until selection and report unavailable targets rather
than inventing a fallback.

`FluxioClient` exposes matching remote calls:

```python
client.application_surfaces()
client.validate_application_surface(manifest)
client.application_surface_status(manifest, target_id="web.local")
client.plan_application_surface_launch(
    manifest,
    target_id="web.local",
    permission_mode="workspace_safe",
    approval_id="approval-catalog-20260724",
)
client.observe_application_surface(manifest)
```

These map to backend commands with the same validation and permission binding.
