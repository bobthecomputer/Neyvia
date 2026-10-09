# Neyvia pre-beta backend

Development authority: `Neyvia-next`, branch `night/neyvia`, owned `src/`, `config/`, `docs/` only. This work does not deploy or modify live Neyvia. Test backend: `127.0.0.1:47891`, disposable `.sandbox-scratch/prebeta/root`. Linked `.venv` and `node_modules` must never receive installations.

## Implemented behavior

| Area | Actual behavior | Remaining boundary |
|---|---|---|
| Session clustering | Local project/title matching, confidence preview, explicit confirmation of uncertain/manual assignments, busy-chat exclusion, reversible moves and subject groups; no provider call | Matching scores are not calibrated semantic probabilities. Frontend subject grouping needs joined proof |
| Progressive manuals | Five grounded manuals; small discovery index; chapter/hash/continuation loader; actual workspace/app/session state | Reference data grants no authority; manual availability is not app readiness |
| Runtime | Nine-harness matrix distinguishes direct connected adapters, existing wrapped routes and planned integrations; owner permission/model ceilings and explicit planner/executor/verifier/classifier profiles | Unknown install/auth/version stays unknown; profiles do not reroute automatically |
| OpenCode | Native ACP session creation/resume, text/images, exact model/mode, streamed tools/diffs, owner allow-once/deny, interruption; unsupported effort refused | No joined browser/Tauri proof. Native context occupancy is not billable execution tokens. Shell permissions require owner review; this is not an OS filesystem sandbox |
| Missions | Dormant atomic graphs over the existing SQLite Night Shift engine; exact-intent approval; start/pause/stop/redirect branches; prerequisite/folder locks; deterministic morning summary | Acceptance checks plus harness/file/commit evidence do not automatically judge semantic quality |
| Resource accounting | Failed/retried task attempts retain reported usage beyond broker retention; mission token budgets serialize branches and constrain the remaining allowance | Missing usage blocks token-budget admission. Late provider reporting can overshoot. Subscription cash cost remains unknown |
| Owner review | Pending approval API includes exact stored prompts, routes, folders, permissions and budgets; duplicate suppression, resolved history, persisted denials | Frontend must show details and Deny. Models have no approval-grant endpoint/tool |
| Image Studio | Scoped open/state, real crop/resize/composite into new PNGs, outside-region protection, source hashes, approved new-file export, asynchronous existing-provider generation, stable IDs and uncertain-job recovery | Pixel verification does not prove aesthetic quality. No real provider image generation was run here. User app, layers and semantic segmentation remain incomplete |
| Improvement Lab | Existing records, frozen-instrument competitions, measured comparable Pareto sets, receipts and bounded history | No automatic promotion/training. Morph Evolver remains disconnected |
| Tool transport | Schema-aware normalization of unambiguous typed strings/array wrappers; nested validation before mutation ledger; exact discovery never substitutes a schema; source-pinned MCP bootstrap | Authored prompts/model IDs stay unchanged. Ambiguous input fails; uncertain actions never auto-replay |

Existing four-suite app registry, PDF tools, bus, analytics and connected image/trust controls are preserved. No frontend or package dependency changes were made. The compaction algorithm was not replaced, and no claim is made that this work improves model quality or beats Codex compaction.

## Owner/frontend contract

All these routes use the existing authenticated backend; POST and approval review require the PC owner's account.

- `GET /api/ui/runtime`; owner POST `{action:"policy",app,permissionCeiling,allowedModels?}` or `{action:"profile",name,route}`. The profile route contains explicit app/model/permissionMode and optional native-supported effort/transport. Existing active turns retain their original scope.
- `GET /api/ui/missions`; POST `{operation:"create",goal,folder,tasks,acceptanceChecks,budget?,id?}` or `{operation:"control",id,action,taskId?,prompt?,model?,effort?,permissionMode?}`. Each task has a local ID and exact prompt; `needs` references local IDs. Mission `status` is owner dispatch policy; `executionStatus` reports running/finished/blocked/waiting. `acceptance` still requires review.
- `GET /api/nightshift/summary` returns actual task evidence and retained reported usage without a model call. Existing `/api/nightshift/resources` continues to control pause/concurrency/harness/time/token/GPU admission.
- Owner-only `GET /api/ui/approvals[?includeResolved=1]`; POST `/api/ui/approve {id}` or `/api/ui/decline {id}`. Bus `notify` contains `approvalId` and `approvalDetail`. Pending native receipts remain `ok:false,status:approval_required,reviewRequired:true` without a fabricated failure/error. Session approval grants retain their documented folder/mode scope; mission/generation grants bind the saved intent. Image export approves new exports under the shown parent folder and never overwrites.
- `GET /api/ui/manuals` and tools `neyvia.manual.index/load/state`. Load just the relevant chapter; respect `truncated`/`nextOffset` and source hash.
- `neyvia.session.cluster {ids?,apply?,minConfidence?,confirmIds?,undoId?}` emits existing `session.moved`. Subject groups are returned separately; apply only moves confident project suggestions. Maximum 2,000 inspected chats, explicit continuation.
- Image tools: `neyvia.image.open/state/crop/resize/composite/export/generate`. The `image.open` event contains asset ID/path/hash/dimensions/provenance and an authenticated `/api/ui/image-file?id=...` URL. POST `/api/ui/app-state {app:"image-studio",state:{status,assetId,zoom,selection,regions,error},clientId}`. Acknowledge only after actual handling. Requested and observed state are distinct.
- Image generation returns running/blocked/uncertain/completed receipts from `image.state`; one job is active per backend. It reuses the existing configured Codex-subscription route with no paid fallback. Restart-orphaned work stays uncertain and is never resubmitted automatically.
- `GET /api/ui/lab` / `neyvia.lab.state`: actual saved local Improvement Lab records, at most 50, comparable finite measured Pareto vectors only.

## Verification

Operational fixtures use Node drivers and disposable data, not pytest or Python unit tests:

```powershell
node docs/verification/prebeta-backend.mjs
node docs/verification/backend-resources.mjs
node docs/verification/connected-images.mjs
node docs/verification/connected-trust.mjs
# With the owned scratch backend on 47891:
node docs/verification/prebeta-http.mjs
```

The pre-beta driver verifies real broker/task-store/mutation-ledger/pixel behavior with deterministic adapters and a native-protocol subprocess. It performs zero provider calls. The HTTP driver checks authentication, APIs, image transport/state/event acknowledgements and preservation of the four suites. API acknowledgements are not rendered UI proof.

Real native OpenCode 1.18.34 / `opencode/big-pickle` edited the disposable proof file after actual allow-once approval, emitted its diff, resumed the same session and cancelled a later turn before the forbidden write. The model-facing MCP chat called the 16 new tool contracts; export, generation and mission start intentionally stopped at owner approval. The real transport's string/array-wrapper argument mismatch was reproduced, fixed against declared schemas and retried. Image recovery used new explicit action IDs after inspecting original hashes/artifact absence; failed/uncertain ledgers were preserved. A final chat checked source-preserving pixel postconditions and clear approval receipts. Raw receipts live in `.sandbox-scratch/prebeta/` and the recoverable NAS WIP snapshot, not source control.

Three earlier real Codex discovery attempts failed to reach these tools. Their reported usage is retained in `verification-usage.json`: 433,879 input tokens (318,848 cached subset), 1,618 output tokens; cash cost unknown. The test driver imported stale modules through the linked environment. Production bootstrap now pins this checkout and has direct subprocess proof, but fresh joined Codex model-to-tool proof remains a release gate. OpenCode verification execution tokens are unknown, not zero. Do not exclude failed attempts from efficiency accounting.

## Time and proactivity

Time/proactivity extension: 10 new tools supplement the existing time.now/time.budget contracts. Persistent timer.start/read/lap/stop/list separates monotonic measurements from recovered wall-clock estimates; targets remain advisory. schedule.after reuses the durable scheduler. watch.create/list/cancel reacts once to retained run states and captures brief transitions while online; an optional model review needs exact-intent owner approval and stays read-only. attention.list and owner GET /api/ui/attention expose actual pending reviews, blocked tasks and recent failures with explicit paging/truncation. Idle watches do not poll or run model checks; at most 64 watches are active, and streamed text does not trigger them. Per-tool duration_ms and run elapsed analytics already existed and are retained.

Proof for this extension: docs/verification/proactivity-backend.mjs exercises real broker events, SQLite state, scheduler delivery, one approved deterministic follow-up, cancellation, duplicate suppression, transient-state capture and clock recovery in another Python process, with zero provider calls. A real OpenCode MCP conversation called all 12 time/proactivity contracts. The watched real connected OpenCode turn was refused by its provider with “OpenCode's free tier can only be used from within OpenCode”; its failed receipt is retained, no route was substituted, and the watch/inbox correctly surfaced that failure. The model-facing MCP turn succeeded. Empty scope text from the transport was reproduced and repaired only for the explicitly declared notification scope; a real-chat retry saved scope:{} without a fabricated note. Cancellation of an already fired watch correctly refused to retract delivery. The proposed model follow-up stayed at owner approval. Actual verification execution tokens/cash are unknown, never zero.

The live service and frontend are unchanged. Claude can evaluate the time/proactivity chapters in docs/manuals/neyvia.md and the final taskboard HANDOFF before adding any UI. No competitor superiority or lower overall cost has been measured. Thirty operational checks and eight HTTP checks passed, alongside the existing pre-beta/resource regression checks.

## Remaining pre-beta gates

1. Claude: render real bus/PDF journey (T07/T29), clustering (T17), Runtime (T21), Canopy (T24), exact prompt approval/deny, analytics and image app; preserve attachments, paste/drop and existing tool controls. No frontend feature was removed here.
2. Fresh Codex source-bound model-to-tool proof and joined OpenCode launch/diff/interrupt/resume through Neyvia UI; Tauri remains untested. Native OpenCode execution-token reporting must exist before token-budgeted tasks can run there.
3. Image generation through the actual approved subscription provider, model-driven export, layers/semantic segments and rendered visual judgement (T31 remains partial).
4. Morph Evolver integration and its actual measured running searches are separate work. Unity/Roblox remain planned until an installed healthy editor/bridge is verified; Unity installation is Paul's explicit task.
5. Identity waits on Paul's supplied images. No promotion to live Neyvia is authorized by this work.

Keep the taskboard HANDOFF current. Commit only owned paths. Save a hash-verified non-public NAS WIP snapshot and verify the public health endpoint before finishing; neither step publishes a release.
