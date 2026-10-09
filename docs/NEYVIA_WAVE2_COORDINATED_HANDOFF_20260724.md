# Neyvia coordinated Wave 2 handoff — 2026-07-24

## Accepted integration

- Branch: `wave2/final-integration`
- Accepted code commit: `95a44c7de973c6de8624f7674a2d46b81e657f5a`
- Wave 1 baseline: `c3c8a2fc56f972f22b8324e411ed02eaf86312bd`
- Delta: 35 commits, 44 files, 27,062 insertions, 565 deletions
- GitHub: not pushed
- Live NAS release: not changed

The integration was rebuilt from explicit reviewed commits in a clean Temp
worktree after an external concurrent writer reached the original coordinator
worktree. No uncommitted or moving worktree state was copied into this branch.

## Implemented in Wave 2

### Private mesh identity

- Durable enrollment, device, rotation, recovery, revocation, quarantine, ACL,
  and service-owner state.
- Cross-process locking, revisions, and compare-and-swap checks.
- External Ed25519 approval and provider-enrollment receipts.
- Workspace configuration and SDK calls cannot mint authority.
- Canonical provider/lifecycle device identity.
- Default configuration is unprovisioned and mutations fail closed.

### Nearby Send resume

- Content-addressed chunk manifests and exact-boundary resume.
- Ordered remote acknowledgements and integrity receipts.
- Cooperative cancellation every 256 KiB during negotiated chunk streaming.
- Safe migration of pre-upgrade hash-bound plans.
- Physical-device and multi-recipient claims remain unproven.

### P2P scheduling, replication planning, and garbage collection

- Deterministic peer health/latency scoring and bounded failover.
- Execution-time policy, endpoint, sidecar, offer, health, score, and byte-limit
  revalidation.
- External Ed25519 garbage-collection approvals with an outside-workspace
  replay ledger; shipped configuration is disabled/unprovisioned.
- Crash-recoverable quarantine journal, pin/LRU/hash rechecks, import/GC
  serialization, and reparse-aware path rejection.
- Replication distinguishes verified, reported, and planned copies.

### Marketplace OCI foundation

- Deterministic OCI planning and final-manifest digest binding.
- Immutable content-addressed archive intake and installed-tree verification.
- Required publisher, signature, SBOM, vulnerability, malware, permission, and
  isolation evidence.
- External Ed25519 verifier trust; checked-in policy is unprovisioned.
- Staged-only activation, crash-safe promotion, runtime trust/dependency
  revalidation, and fail-closed rollback.
- Legacy direct activation and rollback bypasses are blocked.

### SDK application surfaces

- Optional desktop/web surface schema and semantic validation.
- Non-removable baseline permissions and hash-bound non-executing launch plans.
- Evidence-graded readiness, bounded/redacted logs and proofs, and lifecycle
  chain validation.
- Default workspace receipts remain unproven.
- This is a disabled planning foundation, not production launch authorization.

### Updater foundation

- Stable, beta, and development channel contracts.
- Real Ed25519 verification for manifests, artifacts, gates, delta, and peer
  delivery receipts.
- SemVer prerelease ordering, exact HTTPS origin/path validation, replay ledger,
  safe full-artifact fallback, and distinct rollback outcomes.
- Checked-in trust roots are `provisioned: false`; production acceptance remains
  unavailable until a genuine key ceremony and trusted device/request context.

### OCR benchmark foundation

- Deterministic v2 manifest, schema, evaluator, and receipt.
- Source/reference/hypothesis/collector/model-registry/tool-lock bindings.
- Structured text, layout, table, math, omission, hallucination, latency,
  memory, and throughput fields.
- Bounded input memory and newline-independent canonical registry anchors.
- Results are integrity-only and self-declared:
  `promotionEligible: false`.

### Folder-sync conflicts and reconnect state

- Peer/path-scoped conflicts, durable revisions, cross-process locks, and
  guarded keep-local/keep-remote/keep-both plans.
- Remote destinations fail closed without remote attestation.
- Remote-source execution requires separately staged bytes and exact SHA-256.
- Local destructive resolution requires provider-verified bytes, identity,
  membership, and versioning.
- Create-exclusive keep-both semantics and crash-safe authorization-journal
  supersession.

### Performance

- Runtime recorder with exact build/config binding, bounded raw samples, strict
  loopback/same-origin collection, real wall-clock deadlines, and process-tree
  cleanup.
- Local evidence is explicitly not cryptographic attestation.
- Oversized shell files were split into cacheable support chunks.
- This split improves per-file size and cacheability; it does not materially
  reduce cold-route bytes.

## Verification

### Focused and cluster gates

- Nearby Send: 19 passed
- OCR benchmark: 30 passed
- Cluster 1 — folder sync, mesh, SDK: 72 passed, 1 skipped
- Cluster 2 — P2P, marketplace, updater: 123 passed
- P2P final focused gate: 53 passed
- Navigation contract: 11 passed
- Frontend production build: passed, 6,294 modules

### Final combined gate

- 497 passed
- 6 skipped
- 11 subtests passed
- 306.33 seconds

The first combined attempt hit the five-minute command ceiling while a stale
P2P pytest process from an abandoned worktree was still present. That exact
stale test process was stopped, the gate was rerun in the clean final
integration worktree with visible progress, and the result above completed.

### Exact-build performance evidence

Build fingerprint:
`b0e8aeb8abe8dfdd4a62ee079842231b2d99d14906a1f652d85ce98618f6f395`

| Metric | Result | Budget | Status |
|---|---:|---:|---|
| Initial JavaScript | 370,516 B | 650,000 B | pass |
| Initial CSS | 978,584 B | 1,000,000 B | pass |
| Maximum lazy chunk | 495,904 B | 525,000 B | pass |
| Bootstrap response | 241 B | 250,000 B | pass |
| Startup P95 | 2,793.052 ms | 5,000 ms | pass |
| Root-process memory P95 | 59.129 MiB | 700 MiB | pass |
| Root-process CPU P95 | 81.5% | 85% | pass |
| Initial response-body bytes | 1,350,604 B | 1,500,000 B | pass |
| Battery drain | unproven | 12%/h | unproven |

Overall performance status remains `unproven` and
`promotionEligible: false` because battery was not measured and verifier
attestation is not provisioned.

## Honest remaining blockers

- Real Windows/Android/NAS/remote-WAN mesh and Nearby proofs.
- Deployed control plane, relay, Matrix homeserver, and Vaultwarden roles.
- External approval/verifier/signing services and protected operating-system
  trust roots for mesh, marketplace, P2P GC, updater, and app launching.
- Remote folder-versioning attestation and a real sync executor.
- Real OCR model downloads and representative corpus measurements.
- Production updater key ceremony and trusted enrolled-device/request context.
- Authorized Mac worker and complete Android/iOS build pipelines.
- Battery measurement and signed performance attestation.
- True cold-route reduction, aggregate dynamic-route budgets, and deeper CSS
  splitting.
- npm audit currently reports 5 dependency advisories: 2 low, 1 moderate, and
  2 high. No automatic dependency upgrades were applied.

## Browser proof status

The previously committed Wave 1 Personal Mesh browser proof remains valid for
the unchanged UI behavior. Wave 2 changed chunk packaging but did not change the
Personal Mesh UI source.

An exact-build replay was attempted through the required in-app browser control
surface. Its control transport returned `Transport closed`, including after a
reconnect and reset attempt. No alternate browser system was substituted.
Therefore exact-build browser replay is pending rather than falsely reported as
passed.

## Safety and release state

- No GitHub push.
- No live release-pointer change.
- No production trust-root provisioning.
- No physical network, marketplace activation, updater acceptance, or app
  execution claim.
- The WIP NAS snapshot is created only after this handoff and receipt are
  committed and verified.
