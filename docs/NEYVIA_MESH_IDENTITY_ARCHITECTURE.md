# Neyvia Private Mesh and Identity Architecture

Status: Phase 1 architecture deliverable, proposed for coordinator approval
Baseline date: 2026-07-24
Author role: architecture / security / state-machine / critical-review lead (Kimi K3)
Scope: device identity, enrollment, revocation, key rotation, remote lock, trust
policies, route selection, recovery, identity separation, Iroh endpoint protection,
service-discovery authorization, and connection receipts for the Neyvia private mesh.

This document is a design deliverable. It implements no code. File-level
recommendations in section 13 are assignments for implementation agents after
approval. Nothing here modifies a sealed candidate, the live release pointer, or
another agent's owned files.

## 0. Grounding: verified current state (Phase 0 audit)

| Component | Verified state | Evidence |
|---|---|---|
| Mesh foundation | `mesh_service.py` (762 lines): sanitized bridge snapshots, direct/relay probes, service catalog with approval-gated advertise/revoke, fail-closed `migration_plan()`; 8 tests | `tests/test_mesh_service.py`, `qa/mesh-bridge-proof-20260724.json` |
| Mesh config | `config/neyvia_mesh.json` v1: `selectedProvider=tailscale-bridge`, `targetProvider=netbird` 0.75.0 `not-installed`, `cutoverEnabled:false`, agent enrollment/routes/revocation all denied | config lines 1–64 |
| Iroh transport | Rust sidecar pins iroh 1.0.3 / iroh-blobs 0.103.0; stdin-JSON control; Minimal preset (no public discovery/relay); `PeerAllowlist` post-handshake hook; BLAKE3 CAS; supervised lifecycle proven | `tools/neyvia-iroh-cache/`, `p2p_cache.py`, `p2p_provider.py`, `managed_local_service.py`, 3 proofs |
| Iroh endpoint identity | persisted `SecretKey` **in plaintext** in the sidecar state root; rotation absent; keystore protection listed as remaining in both Iroh proofs | `main.rs` `load_or_create_secret`, proof `remaining` lists |
| Device identity / enrollment / revocation / remote lock / posture / ACLs | **absent everywhere** — config policy explicitly disables agent enrollment, route changes, revocation | Phase 0 audit B-section |
| Bridge health | live snapshot 258.9 ms (budget 750 ms); NAS direct 6 ms; relay path observed (DERP par, 13 ms) | mesh proof |

Design constraints carried from the master plans:

- Reuse reviewed primitives (WireGuard via NetBird; Iroh). Do not invent ciphers.
- Small explicit state machines with rollback and recovery.
- Model context never receives raw endpoint IDs, tickets, keys, or secrets.
- `cutoverEnabled` may flip only after all five gates in the mesh proof pass.
- Recovery must not depend on the main workstation.

## 1. Provider-neutral state model

All mesh state is expressed in provider-neutral records. Provider-specific fields
live behind an opaque `providerRef` that never crosses the model boundary.

### 1.1 Entities

```text
DeviceIdentity
  deviceId          = "ndv_" + base32(Ed25519 public key fingerprint, 20 bytes)
  identityPublicKey = Ed25519 public key (signs connection receipts, enrollment proofs)
  createdAt, label, formFactor (windows|android|nas|mac|linux)
  hardwareHint      = non-unique operator label; no serial numbers

DeviceRecord
  deviceId
  state             = DeviceState (section 1.2)
  groups            = [personal|nas|guest|build-worker|security-lab]
  posture           = PostureSnapshot (1.4)
  providerRefs      = { netbird: opaque, iroh: opaque, syncthing: opaque, localsend: opaque }
  enrolledAt, lastSeenAt, revokedAt, lockState
  auditChain        = hash-linked record of all state transitions

EnrollmentGrant (short-lived setup material)
  grantId           = random 128-bit, opaque
  targetGroups, maxUses = 1, ttlSeconds (default 900, max 3600)
  state             = issued | redeemed | expired | revoked
  boundApproval     = approval receipt id that authorized issuance

ServiceAdvertisement
  serviceRef (opaque), serviceType (from config serviceTypes),
  deviceId, port, protocol, aclGroups, advertisedAt, revokedAt

RouteObservation
  devicePair, routeClass (direct-lan|direct-wan|relay),
  rttMs, observedAt, evidenceRef (probe receipt id)

ConnectionReceipt
  receiptId, schema = neyvia.connection-receipt/v1
  initiatorDeviceId, targetDeviceId, serviceRef
  routeClass, startedAt, durationMs, bytesTransferred,
  contentHash (when a transfer occurred), policyDecision,
  signature = Ed25519 sign(initiator identity key, canonical receipt)
```

### 1.2 DeviceState machine (normative)

```text
             enroll                 posture pass
  (none) ──────────────► ENROLLED ──────────────► ACTIVE
                            │                        │
                            │ posture fail           │ lock / suspend
                            ▼                        ▼
                        SUSPENDED ◄──────────── LOCK-PENDING ──► LOCKED
                            │                        │
                            │ re-verify              │ operator unlock
                            └──────────► ACTIVE ◄────┘
                                           
  Any non-terminal state ──► REVOKED ──► PURGED   (irreversible)
```

- `ENROLLED`: keys issued, no traffic authorization yet.
- `ACTIVE`: ACL-evaluated traffic allowed.
- `SUSPENDED`: posture failure or operator pause; sessions drained, re-verification
  can restore `ACTIVE`.
- `LOCK-PENDING`/`LOCKED`: remote lock requested/confirmed; all sessions dropped,
  re-auth denied. Reversible only by an operator-authenticated unlock.
- `REVOKED`: credentials invalidated at every provider and every Neyvia allowlist.
  Terminal for this identity; re-access requires a new enrollment.
- `PURGED`: records minimized to the audit chain only.

Invariants:

1. Only `ACTIVE` devices appear in agent-visible peer catalogs.
2. Every transition writes an audit-chain entry before taking effect.
3. `REVOKED` and `PURGED` can never transition out.
4. A device may hold at most one identity key per form factor; duplicates fail closed.

### 1.3 Where records live

- Authority: NAS (`/volume1/.../mesh/registry/`) — always on.
- Local replica: `.agent_control/mesh/registry.json` + append-only
  `.agent_control/mesh/audit.jsonl` per machine; SQLite WAL index for queries.
- Sync: registry replicated through the existing mission/NAS transfer discipline
  (Codex-owned); devices never write to the NAS registry directly except the
  enrollment service endpoint.

## 2. Enrollment state machine

```text
                 issue(grant)                 present(grant + device pubkey + posture)
  (none) ─────────────────────► GRANT-ISSUED ─────────────────────────► PRESENTED
                                       │                                    │
                                       │ ttl expiry / operator revoke       │ verify
                                       ▼                                    ▼
                                   EXPIRED /                         VERIFYING
                                   GRANT-REVOKED                          │
                                              ┌───────────────────────────┤
                                              │ pass                      │ fail
                                              ▼                           ▼
                                          KEYS-ISSUED                 SUSPENDED
                                              │                     (retry ≤ 3,
                                              │ enroll commit          then grant
                                              ▼                        consumed)
                                           ENROLLED
```

Rules:

1. Grants are single-use, TTL-bound (default 15 min), group-bound, and require an
   operator approval receipt at issuance. Agent-initiated issuance stays denied
   (`agentMayEnrollDevices:false` until the coordinator changes policy).
2. The device presents: grant id, freshly generated Ed25519 identity public key,
   form factor, and a posture snapshot. The private key never leaves the device.
3. Provider enrollment happens only after verification: NetBird setup key scoped to
   the same groups, Iroh endpoint allowlist entry, optional Syncthing/LocalSend
   pairing. Partial provider failure rolls back all providers and consumes the grant.
4. Every enrollment produces a signed `EnrollmentReceipt` (no secret material).
5. Android first-pass: enroll through the official NetBird client plus Neyvia-side
   registration; the Neyvia Android shell is not required for mesh enrollment.

## 3. Revocation and remote lock

Remote lock (reversible):

```text
ACTIVE ──operator──► LOCK-PENDING ──ack or timeout(60s)──► LOCKED
LOCKED ──operator unlock + posture re-check──► ACTIVE
```

- Effect: NetBird ACL deny-all for the peer, Iroh allowlist removal, service
  advertisements revoked, active sessions terminated, Syncthing folder shares paused.
- A locked device that is offline gets the lock on next contact; the NAS registry
  holds the pending action until acknowledged.

Revocation (irreversible):

```text
any state ──operator──► REVOKE-PENDING ──provider acks──► REVOKED ──(30d)──► PURGED
```

- Effect: NetBird peer deleted, Iroh allowlist purged, Syncthing device removed,
  LocalSend favorite removed, Matrix device flagged for the chat layer (Phase 3
  consumes this), vault destination bindings frozen (Phase 3), marketplace installs
  on the device remain but lose mesh services.
- Propagation receipt records per-provider ack/fail. Any provider ack failure keeps
  the record in `REVOKE-PENDING` with retry; it never silently reports success.
- Rollback: none. Revocation requires new enrollment. This is deliberate.

## 4. Key rotation

| Key | Owner | Rotation mechanism | Trigger |
|---|---|---|---|
| Device identity (Ed25519) | device | Re-enrollment under the same `DeviceRecord`; audit chain links old→new fingerprint; old key enters deny-list | operator request, suspected compromise, 12-month age |
| WireGuard peer keys | NetBird | Provider-managed re-registration during re-enrollment | follows identity rotation |
| Iroh `SecretKey` | sidecar | Generate new key, publish new endpoint to allowlist, drain old endpoint, purge old key after 24 h overlap | operator request, compromise, 12-month age |
| Setup material | NAS enrollment service | Single-use + TTL; no rotation concept | per issuance |
| Session/credential material (Matrix, Vaultwarden) | Phase 3 | consumed via secret broker; out of scope here | — |

Invariant: a rotation never changes `deviceId` continuity for audit; it changes
keys. Revocation invalidates keys and continuity together.

## 5. Route selection (direct LAN / direct WAN / relay)

Decision procedure per device pair, evaluated on connect and re-evaluated on
degradation:

1. Probe candidates in parallel with the existing probe path; budgets from
   `neyvia_mesh.json performanceBudgets`: direct-lan ≤ 15 ms, direct-wan ≤ 120 ms,
   relay ≤ 250 ms.
2. Preference order: `direct-lan` → `direct-wan` → `relay` (policy
   `directPeerPreferred:true`, `relayFallbackAllowed:true`).
3. Hysteresis: a route class change requires two consecutive probe windows better by
   ≥ 20 %, or a hard failure of the current route, to avoid flapping.
4. Relay-only pairs are flagged in the health surface; they work but are reported as
   degraded for capacity planning.
5. Every selection writes a `RouteObservation` and the chosen class is recorded on
   the `ConnectionReceipt`. Route changes are never agent-initiated
   (`agentMayChangeRoutes:false`).

## 6. Recovery design (main workstation unavailable)

Goals: an operator with only the Android phone (or a fresh machine) retains control;
the NAS is the always-on anchor; no secret lives only on the workstation.

1. **NAS holds the registry of record**, NetBird management, and (after Phase 3)
   Synapse + Vaultwarden. Workstation loss never loses identity state.
2. **Recovery enrollment path**: a pre-issued sealed recovery grant (printed/stored
   offline by the operator, TTL-armed on first use) allows one new device to enroll
   into the `personal` group. Redemption requires the operator's Vaultwarden-backed
   approval (Phase 3) — until then, a locally authenticated Control-UI approval on
   the NAS is the interim path.
3. **Fresh-workstation bootstrap**: install Neyvia core → redeem recovery grant →
   registry replica + tool locks restored from NAS WIP/candidate snapshots → mesh
   services resume. D:\ tool trees are re-materialized from pinned installers and
   `config/tool_suite_lock.json`; nothing is irreplaceable on the workstation.
4. **Workstation theft/loss**: operator revokes the lost device from any remaining
   device (section 3). Because secrets require broker handles bound to worker +
   executable hash, a stolen disk alone resolves nothing (Phase 3 binding).
5. **NAS unavailable**: devices keep last-known direct routes (LAN continues);
   enrollment, revocation, and registry writes queue and fail closed; nothing
   auto-trusts new state during the outage.
6. **Registry corruption**: audit chains are hash-linked; the registry rebuilds from
   per-device replicas + NAS audit log; mismatch fails closed to operator review.

## 7. Identity separation across NetBird, Iroh, Matrix, Vaultwarden

Decision (resolving Phase 0 D3): **separate provider identities, signed local
identity map, no shared keys.**

- Each provider gets its own credentials; none can impersonate another plane.
- `DeviceRecord.providerRefs` is the only join point and is operator-visible,
  agent-opaque. The map itself is integrity-protected (hash-chained with the audit
  log) because it is correlation-sensitive.
- Compromise of one plane (e.g., Matrix device keys) cannot authorize mesh traffic,
  vault release, or p2p fetches.
- Revocation propagation (section 3) is the only cross-plane action, and it is
  registry-driven with per-provider receipts, not shared credentials.

## 8. Iroh endpoint identity protection

Decision (resolving Phase 0 D2/D4 within Phase 1 scope):

1. Introduce `keystore` abstraction with backends: Windows DPAPI (CurrentUser),
   Android Keystore (Phase 4 surface), and a **headless-NAS file backend**: key file
   encrypted with a passphrase delivered via environment at service start by the
   operator/systemd unit — never stored beside the key.
2. The sidecar accepts `--secret-handle <opaque>` instead of reading a plaintext
   file; the Python supervisor resolves the handle through the keystore and passes
   key material over the existing stdin control channel at process start (never as
   a CLI argument, never logged).
3. Migration: first start with the new build imports the existing plaintext
   `SecretKey`, stores it in the keystore, and securely deletes the file. Rotation
   follows section 4.
4. Acceptance: theft of the state directory yields no usable key; `main.rs` health
   output continues to expose no endpoint id.

## 9. Service discovery authorization

- Discovery scope stays `private-mesh` (config). Only `ACTIVE` devices may query or
  answer.
- Advertisements are group-scoped: a service is visible only to devices whose
  groups intersect `aclGroups`.
- Guests receive no catalog by default; explicit per-service grants only.
- Advertise/revoke remain approval-gated (current behavior) and now additionally
  require the advertising device to be `ACTIVE` and posture-current.
- Discovery responses are sanitized exactly like today's bridge snapshots: opaque
  refs, no raw IPs/endpoint ids below the operator surface.

## 10. Connection receipt semantics

1. A receipt is produced for: file/object transfers, service connections initiated
   through Neyvia, enrollment, revocation, and recovery events.
2. Receipts are signed by the initiator's device identity key; verification uses the
   registry public key. A receipt without a verifiable signature is treated as
   malformed, not as a failed connection.
3. Receipts contain no payload content, no secrets, no raw provider identifiers —
   only hashes, opaque refs, route class, and policy decision.
4. Receipts are append-only (JSONL), replicated to the NAS, and bounded (rotation
   at 10k entries / 30 days, whichever first).
5. Semantics: a receipt proves a policy-evaluated connection occurred with these
   parameters. It does not prove intent, authorization beyond the recorded policy
   decision, or content correctness beyond the recorded hash.

## 11. Explicit trust boundaries

| # | Boundary | Rule |
|---|---|---|
| TB1 | Model/agent ↔ capability contracts | Agent sees opaque refs only; never endpoint ids, tickets, keys, raw peer IPs |
| TB2 | Python control ↔ Rust sidecar | Hash-pinned binary, bounded stdin JSON, no listening control port |
| TB3 | Device ↔ mesh control plane | Mutual auth via provider keys + single-use setup material; management API reachable only on the NAS and through the enrollment service |
| TB4 | Mesh transport ↔ Neyvia services | Transport connectivity never implies service authorization; per-service ACL evaluated at the registry |
| TB5 | Any host ↔ NAS services (NetBird mgmt, future Synapse/Vaultwarden) | TLS + per-service credentials delivered by secret-broker handles (Phase 3); interim: NAS-local only |
| TB6 | Secret-bearing processes ↔ OS keystore | DPAPI/Keystore/headless-file backends only; no plaintext key files after migration |
| TB7 | Publisher trust (marketplace) ↔ device trust (mesh) | Fully separate trust stores; a trusted publisher gains no mesh rights and vice versa |
| TB8 | Guest devices | No discovery catalog, no service defaults, explicit grants only, no agent surface |

## 12. Failure and rollback table

| Failure | Detection | Immediate behavior | Rollback / recovery |
|---|---|---|---|
| Grant TTL expiry before use | enrollment service | grant → `EXPIRED` | issue new grant (new approval) |
| Partial provider enrollment (e.g., NetBird ok, Iroh fail) | per-provider step receipts | roll back completed providers, consume grant | re-enroll with new grant |
| Posture check fail | verifier | device → `SUSPENDED` | re-verify; 3 failures consume grant |
| Cutover regression after `cutoverEnabled` flip | health probes vs budget | `migration_plan()` fail-closed path; flip back to `tailscale-bridge` | config restore + provider state receipt; bridge never uninstalled during transition |
| Relay unavailable, direct impossible | probe failures | pair marked degraded; transfers queue | automatic retry on next probe window |
| Revocation ack failure from a provider | propagation receipt | stay `REVOKE-PENDING`, retry with backoff, alert operator | manual provider console action recorded back into registry |
| Identity key compromise | operator report / anomaly | immediate lock → revoke; deny-list fingerprint | new enrollment; audit chain preserved |
| Iroh SecretKey file theft (pre-migration) | operator | revoke endpoint, rotate (section 4) | migration to keystore eliminates class |
| Keystore locked/unavailable (headless NAS reboot) | service start failure | fail closed; p2p inactive, local CAS still serves reads | operator/systemd re-arms passphrase |
| Clock skew beyond TTL window | receipt validation | grant/lease validation fails closed | re-sync clock; no auto-accept |
| Duplicate deviceId presentation | registry check | enrollment rejected, operator alerted | operator resolves; no silent overwrite |
| Registry/replica divergence | hash-chain verification | fail closed to operator review | rebuild from NAS audit log (6.6) |
| Stale Iroh allowlist after peer rotation | denied-peer events | fetch plan fails closed | allowlist refresh from registry, retry |

## 13. File-level implementation recommendations

New files (mesh/identity slice — assign to one implementing agent; design owner
reviews diffs):

- `src/grant_agent/mesh_identity.py` — Ed25519 device identity, fingerprints,
  receipt sign/verify (use reviewed `cryptography` package; add to `pyproject.toml`).
- `src/grant_agent/mesh_enrollment.py` — grant issuance/redemption, state machine,
  durable store under `.agent_control/mesh/`.
- `src/grant_agent/mesh_registry.py` — DeviceRecord store, hash-linked audit chain,
  NAS replica protocol (transfer-discipline compliant; no direct NAS writes from
  agents).
- `src/grant_agent/mesh_policy.py` — group/ACL templates: `personal`, `nas`,
  `guest`, `build-worker`, `security-lab` (default-deny, explicit allowlists).
- `src/grant_agent/mesh_routing.py` — route scorer with hysteresis (section 5).
- `src/grant_agent/mesh_receipts.py` — connection receipt schema + JSONL store.
- `src/grant_agent/keystore.py` — DPAPI / Android-Keystore-stub / headless-file
  backends behind one `get/put/delete` interface.
- `config/neyvia_mesh_identity.json` — registry config v1 (groups, TTLs, budgets).
- Tests: `tests/test_mesh_identity.py`, `test_mesh_enrollment.py`,
  `test_mesh_registry.py`, `test_mesh_policy.py`, `test_mesh_routing.py`,
  `test_mesh_receipts.py`, `test_keystore.py`.

Modifications (coordinate with owners before editing):

- `tools/neyvia-iroh-cache/src/main.rs` — `--secret-handle` mode, stdin key
  delivery, rotation command, plaintext-import migration. *Owner: Iroh implementer.*
- `src/grant_agent/mesh_service.py` — expose enrollment/revocation/lock through the
  existing sanitized surface; keep `migration_plan()` fail-closed. *Owner: mesh
  implementer.*
- `src/grant_agent/capability_adapters.py` — add `mesh.control` ops:
  `enroll_device`, `revoke_device`, `lock_device`, `unlock_device`,
  `rotate_endpoint`, `connection_receipts`; all write ops approval-gated.
  *Shared chokepoint — single-agent edit window required.*
- `config/neyvia_mesh.json` — schema bump to v2 adding `identity` section;
  keep `cutoverEnabled:false`.

Explicitly not in this slice (later phases / other owners): Synapse and Vaultwarden
deployment automation, secret-broker DPAPI session integration (consumes
`keystore.py`), marketplace publisher trust, Tauri Android shell.

## 14. Review of GROK's implementation diff

**Finding: no GROK mesh/identity implementation diff exists to review.**

- The only GROK runtime record in the workspace is
  `.agent_control/runtime_compartments/phase_c_grok_build.json` (2026-07-20):
  a failed probe — `grok` CLI not on PATH, `filesChanged: []`, zero proof artifacts.
- `docs/GROK_BUILD_OPEN_SURFACES.md` and `docs/NEYVIA_GROK_BUILD_CLAUDE_CODE_RESEARCH.md`
  are research/planning documents, not implementation.
- Consequence: deliverable "review of GROK's implementation diff" is discharged as
  **blocked — awaiting GROK delivery**. When a diff arrives, review it against:
  sections 1–5 (state machines), 8 (key protection), 11 (trust boundaries), 12
  (failure table), and the global rules (no invented crypto, approval gates, receipt
  discipline). Any diff touching `capability_adapters.py` or `mesh_service.py`
  requires the single-agent edit window (section 13).

## 15. Acceptance checklist

Windows:

- [ ] Device enrolls via single-use grant; identity key in DPAPI; plaintext key absent after migration.
- [ ] Direct-LAN route to NAS selected and ≤ 15 ms budget; receipt signed and verifiable.
- [ ] Lock → sessions drop ≤ 60 s; unlock → posture re-check → `ACTIVE`.
- [ ] Revoke → all providers ack; peer absent from catalogs; receipt complete.

Android:

- [ ] Enrollment via NetBird client + Neyvia registration; appears as `ACTIVE` in catalog.
- [ ] Phone-initiated recovery grant redemption works without the workstation.
- [ ] Nearby transfer Windows↔Android completes with matching hashes over the mesh.

NAS:

- [ ] Registry of record survives workstation shutdown; replicas converge on return.
- [ ] NetBird management + relay reachable only per TB3/TB5.
- [ ] Headless keystore backend: reboot → service fails closed until passphrase re-armed; drill recorded.

WAN / relay:

- [ ] Direct-WAN pair ≤ 120 ms selected when LAN absent.
- [ ] Forced-relay drill: traffic flows ≤ 250 ms, pair flagged degraded, receipt class = `relay`.
- [ ] Relay kill-drill: direct re-established by hysteresis rule without flapping.

Revocation / recovery:

- [ ] Stolen-device drill: revoke from phone; stolen device loses mesh, sync, discovery ≤ 5 min including offline-queued acks.
- [ ] Fresh-workstation drill: recovery grant → bootstrap from NAS snapshots → mesh services restored; no irreplaceable state identified.
- [ ] Registry-corruption drill: hash-chain mismatch fails closed; rebuild from audit log succeeds.

Blocking precondition for all of the above: D1 (NetBird self-host on NAS) executed
as deployment work by the assigned integrator; this document is its design basis.

## 16. Phase 0 decisions disposition

| Dec | Disposition |
|---|---|
| D1 NetBird hosting | Carried: recommendation stands (self-host on NAS); coordinator approval + integrator assignment required before deployment |
| D2 Iroh key protection | Resolved by section 8 (keystore abstraction + `--secret-handle`) |
| D3 Identity separation | Resolved by section 7 (separate identities + signed local map) |
| D4 Secret session storage | Resolved for mesh keys by section 8; Matrix/Vaultwarden sessions consume the same `keystore.py` in Phase 3 |
| D9 Private P2P distribution | Recommendation: Iroh-only for the mesh; Kubo stays optional public gateway. Awaits coordinator sign-off |
