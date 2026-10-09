# N-E-Y-V-I-A Capability Backend

Status: local backend implementation  
Visual owner: Cursor  
Public release status: not published

## Product boundary

The capability backend owns:

- capability packs and validation;
- fast capability search and description;
- intent-to-plan routing;
- adapter discovery and availability;
- permission decisions;
- artifact registration and lineage;
- plan, live, and result preview events;
- run lifecycle persistence;
- performance receipts;
- progressive MCP tools;
- web-backend commands.
- native tool authoring and external-schema adaptation;
- primary structured Computer Use verification and remote worker dispatch;
- optional Computer Use comparison lane (internally called Twin).

Cursor owns:

- visual layout;
- component design;
- motion and transitions;
- responsive behavior;
- visual previews;
- user-facing copy refinements.

The UI must not invent installed tools, successful execution, artifacts, or
permissions. It renders the backend states below.

## Core files

| File | Responsibility |
|---|---|
| `config/capability_packs.json` | Built-in profession and domain packs |
| `src/grant_agent/capability_contracts.py` | Stable typed payload contracts |
| `src/grant_agent/capability_adapters.py` | Demand-start adapter discovery and safe execution boundary |
| `src/grant_agent/capability_catalog.py` | Catalog loading, search, and plan compilation |
| `src/grant_agent/artifact_graph.py` | Content hashes and source-to-result lineage |
| `src/grant_agent/capability_runtime.py` | Permissions, preview runs, and telemetry |
| `src/grant_agent/capability_service.py` | Backend facade and progressive tools |
| `src/grant_agent/tool_factory.py` | Native tool manifests, adaptation, validation, and safe argv templates |
| `src/grant_agent/computer_use_twin.py` | Structured CU comparison, baseline gates, replay labeling, and worker dispatch |
| `src/grant_agent/computer_use_verifier.py` | Primary change-verification API and claim policy |
| `src/grant_agent/module_marketplace.py` | Module manifest, package, permission, archive-safety, and staging-plan validation |
| `config/neyvia_module_manifest_schema.json` | Versioned module and marketplace contract |

## Bounded local executors

Executable discovery and executable support are separate states. A discovered
program becomes directly executable only when the backend has a dedicated,
allowlisted handler for it.

The current direct handlers are:

- `pdf.pdftotext`: real Poppler extraction with page-range, timeout, and
  model-visible character bounds;
- `ocr.paddle`: primary bounded GPU OCR. It uses PP-OCRv6 medium for ordinary text
  and PaddleOCR-VL 1.6 for complex structure, renders only the requested PDF page
  range, writes atomic workspace artifacts, and validates the exact
  Paddle/PaddleOCR/PaddleX/CUDA/cuDNN runtime before execution;
- `ocr.tesseract`: real image OCR plus bounded PDF page rendering through
  `pdftoppm`, with stable page ordering and at most four workers. This is the
  explicit CPU emergency fallback, not the automatic primary route;
- `device.android`: real ADB inspection and allowlisted test operations.
  Device mutations require an explicit `approved: true`; emulator startup also
  requires the Android `emulator` binary.
- `document.pandoc`: pinned Pandoc 3.10.1 format discovery, bounded JSON AST
  inspection, and semantic conversion using sandbox mode, atomic output,
  deterministic reference styles, readback verification, and artifact lineage.
- `document.libreoffice`: pinned LibreOffice Portable 26.2.4.2 version inspection,
  allowlisted office conversion, and PDF rendering with isolated profiles, atomic
  output, editable round-trip checks, independent PDF page-count verification, and
  artifact lineage.

The handlers never interpolate a shell command. Output paths are restricted to
the selected workspace, stdout/stderr are bounded, and an unavailable
dependency remains `adapter_required`. PaddleOCR, Tesseract, LibreOffice, Pandoc,
Android SDK, and other large optional runtimes are managed under `D:\Neyvia`, not
bundled into the repository.

Pandoc and LibreOffice are the reference managed-tool integrations. Models first call
`tool.suite.search` for compact matching rows, then `tool.suite.describe` for one
tool's complete schemas, and finally `tool.suite.execute`. Execution validates the
operation schema and permissions, records telemetry and a versioned tool receipt,
and registers declared source/output artifacts and their relationship.

The current snapshot contains more than 40 tool records and four verified,
agent-ready managed tools: PaddleOCR, Tesseract fallback, Pandoc, and LibreOffice.
The rest of the catalog remains honestly planned, installed-but-unbound, or
unavailable according to its manifest state.

## Module and marketplace boundary

`neyvia.module-manifest/v1` describes a separately versioned capability, service,
content pack, or full app. A full app may declare desktop, mobile, web, embedded, or
headless surfaces. The validator checks compatibility, isolation, permissions,
capability schemas, rollback metadata, compact context indexes, immutable package
hashes, required SBOM/signature metadata, and hostile ZIP conditions.

`ModuleMarketplace.build_install_plan` is deliberately staging-only. OCI activation
requires real Cosign, SBOM-policy, malware, permission-review, and isolated
smoke-test receipts before the lifecycle service may switch a version pointer.
Operation IDs, surface IDs, and internal app routes must be qualified by the
publisher namespace. The accepted claims are bound into the activation pointer;
activation and rollback compare them with every active module under one
marketplace-wide lock. A conflict writes a blocked receipt and changes no active
pointer. Mesh distribution and registry publication remain planned rather than
simulated. Encrypted chat now has a typed,
credential-hiding Matrix foundation plus durable, opaque enrollment, device,
session-expiration, removal, and recovery request records. The lifecycle state
machine never converts a local request into server success: with the current
configuration it reports `homeserver_unavailable`, and even an active
configuration still requires real login/removal/recovery verification. Typed
self-chat plans support links, workspace files, clipboard text, and notes while
persisted receipts retain hashes and kinds rather than content. The production
homeserver, accounts, device verification, remote session revocation, cross-signing
recovery, and live room proof remain intentionally unconfigured.
The password-vault path now has a typed opaque secret-broker foundation over the
verified Bitwarden CLI OSS client, with one-time destination-bound leases and
content-free audit. Vaultwarden deployment, protected production sessions, and
live secret-use proof remain intentionally unconfigured.

PDF analysis is immediately executable on a host with `pdftotext`. Scanned-PDF OCR
uses page-bounded `pdftoppm` rendering plus the healthy Paddle GPU adapter.
Tesseract remains available when the GPU path is unavailable or when a legacy
output format is explicitly requested. This split returns native PDF text quickly
without spending OCR resources on every page.

## Web commands

### Catalog and UI contract

- `get_capability_os_snapshot_command`
- `get_capability_ui_contract_command`
- `search_capabilities_command`
- `describe_capability_command`
- `benchmark_capability_os_command`

### External adapter sessions

- `register_capability_adapter_session_command`
- `heartbeat_capability_adapter_session_command`
- `disconnect_capability_adapter_session_command`

Session registration requires approval and stores only an `authRef`; payloads
containing raw token, password, secret, API-key, or cookie fields are rejected
recursively. Registration returns a one-time `heartbeatKey`; only its SHA-256
hash is persisted, and later heartbeats must present the key.
Discovery does not grant execution. A bridge requires an explicit in-process
client before `supportsExecution` can become true.

### Capability-pack authoring

- `validate_capability_pack_command`
- `save_capability_pack_command`

Saving requires `approved: true`. Built-in packs cannot be overwritten.
Existing custom packs require `replaceExisting: true`.

### Authored tools

- `list_authored_tools_command`
- `search_authored_tools_command`
- `describe_authored_tool_command`
- `adapt_authored_tool_command`
- `validate_authored_tool_command`
- `save_authored_tool_command`
- `execute_authored_tool_command`

The factory adapts MCP tools, OpenAI-function definitions, and argv command
definitions into `neyvia.authored_tool.v1` drafts. Saving and execution are
separate approvals. Command tools select a discovered executable adapter and
run an argv list with `shell=false`; they cannot inject shell expressions.
Workspace paths are bounded, output is size-limited, permissions are evaluated
before launch, and secret-looking environment variables are removed unless
`secret.use` was explicitly approved. Composite tools can call only the
backend operation allowlist.
`search_capabilities_command` also returns compact `authoredTools` matches, so
the model can select custom and built-in abilities through one deferred-schema
search without loading a thousand manifests.

### MCP operator broker

- `get_mcp_broker_snapshot_command`
- `search_mcp_tools_command`
- `describe_mcp_tool_command`
- `call_mcp_tool_command`

The product path never inserts the broker's standalone demo server. It lists
only configured servers, keeps environment values hidden, defers foreign
schemas until an explicit search/selection, validates call arguments, gates
mutating tools behind one-run approval, and persists the broker receipt.

### Computer Use Verifier

- `verify_computer_use_change_command`
- `dispatch_computer_use_verification_command`

This is the primary product gate. It runs real changes through
`ui.observe` → `ui.find` / `ui.diff` → revision-gated `ui.do`. The
accessibility graph and compact deltas are primary; full screenshots are not
sent every turn and `ui.see` is reserved for a visual page fault. Receipts
include flow success, deterministic agreement, P50/P95 latency, compact
model-visible bytes, live-versus-replay evidence, and comparative-claim gates.
The same verification payload can be carried to another isolated
browser-capable worker.

The suite reuses one browser runtime and context across its flows. On the
2026-07-23 two-flow live sample (`control_room` + `surface_navigation`), this
kept 100% flow success while reducing P95 wall time from 19,960.609 ms to
15,773.107 ms (1.2655× faster; accuracy delta 0). This is a bounded sample,
not a 10× product claim.

### Optional Computer Use comparison lane

- `list_computer_use_twins_command`
- `validate_computer_use_twin_command`
- `save_computer_use_twin_command`
- `run_computer_use_twin_command`
- `dispatch_computer_use_twin_command`

A Twin is an optional repeated comparison lane. It runs the structured UI acceptance
flows, optionally repeats them, and measures flow success, deterministic
agreement, P50/P95 latency, and compact receipt bytes. With a retained
baseline, it gates accuracy regression and latency ratio. “Faster and more
accurate” is not a valid claim unless both baseline and candidate are live.
Replay mode is supported for an unstable app, but is labeled `replay` and
cannot count as live product proof.

Remote dispatch creates a `browser_verify` cluster job requiring
`browser.verify` and `computer.use.isolated`. It may target another healthy
workstation/CPU; NAS runtime fallback is prohibited.

### Planning and execution

- `plan_capability_run_command`
- `create_capability_run_command`
- `get_capability_run_command`
- `execute_capability_command`
- `record_capability_preview_command`
- `finish_capability_run_command`

### Artifact lineage

- `register_capability_artifact_command`
- `relate_capability_artifacts_command`
- `get_capability_artifact_lineage_command`

## Progressive tools

The same backend is exposed through the progressive tool surface:

- `capability.search`
- `capability.describe`
- `capability.plan`
- `capability.execute`
- `capability.pack.validate`
- `capability.pack.save`
- `capability.ui.contract`
- `capability.benchmark`
- `tool.author.search`
- `tool.author.describe`
- `tool.author.adapt`
- `tool.author.validate`
- `tool.author.save`
- `tool.author.execute`
- `cu.twin.validate`
- `cu.twin.save`
- `cu.twin.run`
- `cu.twin.dispatch`
- `computer_use.verify`
- `computer_use.dispatch_verification`
- `artifact.register`
- `artifact.lineage`

Schemas remain deferred until `describe`.

## UI state contract

### Plan readiness

| State | Meaning |
|---|---|
| `ready` | Required adapters and permissions are ready |
| `approval_required` | User approval is required |
| `adapter_required` | One or more real adapters are not installed or connected |
| `blocked` | The permission policy denies the plan |

### Run lifecycle

| State | Meaning |
|---|---|
| `ready` | Durable run exists and can begin |
| `awaiting_approval` | Run exists but must not execute yet |
| `running` | At least one live preview event was recorded |
| `completed` | Terminal successful result |
| `failed` | Terminal failed result with retained partial proof |
| `cancelled` | Terminal user or policy cancellation |

### Capability execution

| State | Meaning |
|---|---|
| `completed` | A real registered handler executed |
| `delegation_required` | Work must be dispatched to a N-E-Y-V-I-A agent lane |
| `approval_required` | Exact permissions are returned |
| `permission_denied` | Selected policy forbids execution |
| `adapter_required` | The required external program or bridge is unavailable |
| `not_executable` | The program was discovered but no approved handler exists |

`available: true` never means an arbitrary external process can be executed.
Only adapters with `supportsExecution: true` can run directly.

## Experience levels

The backend uses:

- `guided`
- `standard`
- `advanced`
- `expert`

The level changes explanation, disclosure, defaults, and tutorial behavior. It
does not create separate capability catalogs or hide fundamental abilities.

## Permission classes

- `context.read`
- `artifact.read`
- `artifact.write`
- `workspace.read`
- `workspace.write`
- `process.execute`
- `network.read`
- `network.write`
- `secret.use`
- `external.side_effect`
- `compute.spend`
- `destructive`

High-risk permissions require approval even under autonomous scoped operation.

## Preview phases

Every durable run can record:

1. `plan` — selected capabilities, permissions, resources, and expected output;
2. `live` — structured progress, partial outputs, warnings, and artifacts;
3. `result` — terminal output, proof, limitations, and artifact identifiers.

Cursor should render the event payload appropriate to the selected artifact.
It should not require a separate backend lifecycle for PDF, spreadsheet, 3D,
video, model-training, or device previews.

## Artifact relationships

Supported relations:

- `derived_from`
- `edited_from`
- `compiled_from`
- `extracted_from`
- `references`
- `verified_by`
- `rendered_from`
- `trained_from`
- `tested_by`
- `exported_from`
- `contains`

Files are content-hashed when they exist. Missing paths remain explicitly
`exists: false`; no hash or output is fabricated.

## Cursor integration sequence

1. Call `get_capability_ui_contract_command`.
2. Call `get_capability_os_snapshot_command` without full capabilities.
3. Search with `search_capabilities_command`.
4. Load a selected row through `describe_capability_command`.
5. Compile a plan through `plan_capability_run_command`.
6. Show the returned readiness and permission state.
7. Create a run only when the user accepts the plan.
8. Subscribe or poll the selected run and render preview events.
9. Display result artifacts through artifact lineage.

The first viewport should have one dominant object: search, plan, run, or
artifact. Adapter diagnostics and raw telemetry belong in disclosure.

## Performance contract

Current initial budgets:

- warm capability search P95: 50 ms;
- local routing P95: 250 ms;
- UI acknowledgement: 100 ms;
- idle CPU: less than 1 percent;
- core UI plus resident services: less than 450 MiB working set;
- heavy adapters: demand-start and release resources when inactive.

`benchmark_capability_os_command` emits a retained receipt. A 10x claim is
invalid unless a baseline and candidate receipt compare time-to-first-result,
manual interactions, throughput, model context bytes, or operator wait time.

## Verification

Focused backend tests:

```powershell
python -m pytest tests/test_capability_os.py -q
```

Run them in the locked environment so JSON-schema validation is active:

```powershell
uv run --isolated --with pytest python -m pytest tests/test_capability_os.py tests/test_model_tool_intelligence.py -q
```

Marketplace contract tests:

```powershell
uv run --isolated --with pytest python -m pytest tests/test_module_marketplace.py -q
```

Compatibility tests:

```powershell
python -m pytest tests/test_neyvia_mcp.py tests/test_neyvia_stage_scheduler.py tests/test_web_backend.py tests/test_mission_artifacts.py -q
```

Product UI acceptance remains a separate joint step after Cursor implements
the visual surfaces. Backend tests must not be used to claim that the final UI
is beautiful or usable.
