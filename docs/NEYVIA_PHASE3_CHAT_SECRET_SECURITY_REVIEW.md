# Neyvia Phase 3 — Matrix Chat and Secret Broker Security Review

Status: security review deliverable, 2026-07-24
Reviewer role: architecture / security / state-machine / critical-review lead (Kimi K3)
Scope honored: encrypted-chat and secret-broker implementation, their focused
configuration and tests, and the chat/secret sections of
`docs/NEYVIA_MODULAR_PLATFORM_AND_PERSONAL_MESH_PLAN.md`. No production, runtime,
UI, configuration, or test files were edited. Mesh, P2P, Nearby Send, folder sync,
marketplace, SDK surfaces, performance, OCR, updater, NAS, GitHub, live state, and
credentials were not touched.

Method: full-file reads of both implementations and both focused test files;
configuration and proof-receipt reads; pack-permission extraction; independent
SHA-256 hashing of all artifacts; execution of the two focused test suites only.

Companion machine-readable receipt:
`.agent_control/capability_os/qa/phase3-chat-secret-security-review-20260724.json`

## 1. Verified state: implemented versus unproven

Source hashes independently recomputed this review and **matching** the pinned
values in the two foundation proofs:

- `src/grant_agent/encrypted_chat.py` SHA-256
  `6f91354b6c5a99ae69d92a87be171c5516b226db6ad61c2c70e7d01d547dbb8f`
  (= proof `neyviaContract.sourceSha256`)
- `src/grant_agent/secret_broker.py` SHA-256
  `c1ab5aca73c522b5b8fcb32d9a9b1bd19acc254d21a8858a2ffed8f3d4653b64`
  (= proof `neyviaContract.sourceSha256`)

### 1.1 Matrix chat (`chat.control`) — implemented in code, contract-tested

| Behavior | State | Evidence (file:line) |
|---|---|---|
| Opaque account/room/user/device refs; raw Matrix IDs never returned | implemented, tested | `encrypted_chat.py` L55-58, L223-249; test L186-204 |
| Per-room agent grants (read/write/attachments) with allowlist | implemented, tested | L576-619 (`_resolve_room`), L612-618; test L342-372 |
| Hash-bound message plans (SHA-256 canonical JSON) | implemented, tested | L412-416, L566-574 |
| Outbound likely-secret refusal (password/api-key/JWT/hex patterns) | implemented, tested | L25-33, L310-315; test L231-237 |
| Workspace-only attachments, count/size caps, pre-send re-hash | implemented, tested | L358-410, L440-449; test L277-296 |
| Approval gate on send | implemented, tested | L424-430; test L253-256 (see §3-O3 for binding caveat) |
| Encryption re-verified immediately before send/history | implemented, tested — **heuristic** | L642-684; test L324-339 (see §2-T10) |
| Message/file content passed over stdin, never in argv | implemented, tested | L450-482; test L260-263 |
| Room ID passed in process argv | present, honestly disclosed | L727; config `neyvia_chat.json` L59; compatibility limitations L164-171 |
| Content-free receipts persisted atomically | implemented, tested | L493-515; test L264-274 |
| Bounded, sanitized history (≤100 events) | implemented, tested | L517-564, L820-848; test L299-321 |
| Credential/crypto-store path confinement to `secretRoot` | implemented | L621-640 |
| Transport binary hash verified before every invocation | implemented | L695-704 |

### 1.2 Matrix chat — unproven or absent (no code path, or no service proof)

| Behavior | State | Evidence |
|---|---|---|
| Synapse 1.157.1 homeserver deployed | **absent** — no deployment automation exists anywhere | config L7 `nas-deployment-pending`; proof L79-80 |
| Any production account, room, crypto store, or message | **absent** | config L49 `accounts: []`; proof `productionAccountConfigured:false`, `productionMessageSent:false` |
| Device verification / cross-signing / key backup / recovery | **no code path** | absent from L1-855; proof remaining L86 |
| Offline delivery across devices | **no code path, no proof** | proof remaining L87 |
| Session expiry model | **absent** — only `commandTimeoutSeconds` | config L55 |
| Device removal operation | **absent** | ops list `capability_adapters.py` L610-616 |
| At-rest protection of credential file (access token JSON) | **absent** — plaintext JSON, path-confined only; proof defers to broker | L621-640; proof remaining L84 |
| Element/Desktop/Android client interop | installed-not-started / install-pending | config L39, L44 |

### 1.3 Secret broker (`secret.broker`) — implemented in code, contract-tested

| Behavior | State | Evidence (file:line) |
|---|---|---|
| Opaque handles (SHA-256 of account+item+field, truncated); item IDs never exposed | implemented, tested | `secret_broker.py` L778-786, L189-204; test L190-193 |
| Handle→destination/operation/worker/injection-mode binding, double-checked at use | implemented, tested | L241-262, L607-632; test L214-217 |
| Destination executable pinned by SHA-256, verified at use | implemented | L547-550 |
| TTL 1–300 s, expiry enforced before any vault call | implemented, tested | L267-271, L601-605; test L269-284 (zero runner calls on expired) |
| One-time leases, atomic `O_CREAT\|O_EXCL` 0o600 reservation | implemented, tested | L640-664; test L240-241 |
| Approval gate on use/revoke | implemented, tested | L308-317, L419-424 (see §3-O3) |
| Secret-in-argv prevention (pre-launch check + env-name policy) | implemented, tested | L551-557, L571-577; test L52 |
| Minimal inherited environment; `BW_SESSION` only to the vault client | implemented, tested | L808-823, L521-523; test L238 |
| Exact-secret output detection → fail closed + redact + policy-violation receipt | implemented, tested | L339-345, L826-834; test L244-266 |
| Vault client hash verification; state confined to `stateRoot` | implemented, tested | L498-501, L714-724; test L287-302 |
| Bounded (≤200) content-free audit | implemented, tested | L449-493; test L305-320 |
| Secret size cap 64 KiB; field allowlist password/username/totp/notes | implemented | L29, L510-512, L536-538 |

### 1.4 Secret broker — unproven or absent

| Behavior | State | Evidence |
|---|---|---|
| Vaultwarden 1.36.0 server deployed | **absent** — no deployment automation exists | config L7 `nas-deployment-pending`; proof L76-78 |
| Real vault login / real secret resolution | **never performed** | proof `realVaultLoginPerformed:false`, `realSecretResolved:false` |
| Production accounts/handles/destinations | **none configured** | config L23-25 (all empty) |
| OS-protected session storage (DPAPI/Credential Manager) | **absent** — session read from process env var only | L788-806; proof remaining L83 |
| Handle-level revocation (invalidating future resolution) | **absent** — `revoke()` burns one lease only | L413-447 (see §3-O1) |
| Secret rotation, backup, recovery, autofill, protected sharing | **no code path** | proof remaining L85-86 |
| Session-expiry preflight | **absent** — stale session surfaces only as vault-call failure | L502-505, L531-532 |
| Machine/worker identity binding | **string label only**, not mesh device identity | L259-262 (see §3-O2) |

## 2. Threat model

### T1 — One-time handles
Lease consumption is atomic on the local filesystem (`O_CREAT|O_EXCL`, mode 0o600,
`secret_broker.py` L640-664); a second `use()` or `revoke()` on the same leaseId
fails closed. Handles themselves are non-bearer: knowing `secret-<hash>` grants
nothing without plan + approval + binding match. **Residual:** plan minting is
unthrottled and unaudited — an agent can mint arbitrarily many leases for an
allowed handle (each still requires approval to use). Reservation files accumulate;
no GC (bounded only by audit read limit, not storage).

### T2 — Expiration
TTL is clamped to 1–300 s (L267-271) and checked before the vault is called
(L601-605); the expired-lease test proves zero subprocess calls. Clock trust is
local-UTC; no monotonic guard — acceptable for 300 s windows. Chat has **no**
expiry concept for plans: a `chatplan_*` remains sendable indefinitely until
approval policy changes. **Gap (low):** add plan max-age to chat plans.

### T3 — Operation / destination / device / session binding
Binding is enforced twice (plan creation L241-262 and use-time L607-632) against
config policy, including destination executable SHA-256 (L547-550). Injection mode
is bound (L629-632). **Residuals:** (a) `worker` is a config *string*, not a mesh
device identity — on a multi-worker mesh, any process on any worker matching the
string passes; must bind to the Phase 1 `DeviceRecord` when mesh identity lands.
(b) Chat session binding = a credential file path confined to `secretRoot`
(L621-640); the file itself is plaintext JSON containing an access token.
(c) Broker session binding = an env var name pattern `NEYVIA_*` (L788-806); the
session key lives in the Neyvia backend process environment — readable by any
code executing in that process, and inherited by nothing else only because
`_minimal_environment` strips it (L808-823). This is the single most important
hardening target (Slice A).

### T4 — Replay
- Broker lease replay: prevented atomically; tested (test L240-241).
- Broker plan tamper: planHash binds all fields; modified operation fails
  (test L214-217).
- Chat attachment swap between plan and send: re-hashed pre-send, fails closed
  (test L277-296).
- Chat message plan replay: **open** — the same approved chat plan can be sent
  repeatedly (no one-time semantics, no plan consumed marker). For chat this is
  arguably by design (re-send), but receipts do not record a send counter; an
  approval intended for one message can be replayed to send N copies (see O3).

### T5 — Logs and model-context leakage
- Outbound: likely-secret regexes block credential-shaped chat text (L310-315);
  receipts persist no message content (L506-514).
- Inbound: history is regex-redacted only (L820-848). A secret not matching the
  four patterns reaches model context. More importantly, **history is untrusted
  content delivered into model context without an untrusted-content marker** —
  a remote room member can plant instruction-shaped text the model will read
  (prompt-injection channel). No labeling/wrapping exists today.
- Process metadata: room ID appears in transport argv (L727) — visible to local
  process inspection; honestly disclosed (config L59) but a real metadata leak.
- Broker: destination stdout/stderr is persisted in receipts (sanitized, ≤16 KiB,
  L368-375, L826-834) — bounded and redacted, but note chat persists *no* content
  while broker persists sanitized output; asymmetry is deliberate yet should be
  re-justified per destination.
- Vault session/item IDs: never serialized into catalogs, receipts, or audit
  (tests L193-197 chat-side equivalents L200-204). Verified clean.

### T6 — Device removal
**Absent for chat**: no device-list, device-verify, or device-remove operation
(ops list `capability_adapters.py` L610-616). Matrix device removal will need the
Phase 1 revocation hook (mesh device → Matrix device mapping). For broker,
"device removal" maps to destination freezing — also absent (no destination
disable op; requires config edit).

### T7 — Recovery
Matrix key backup/recovery: no code path (proof remaining L86). Vault
backup/recovery: no code path (proof remaining L85). Recovery today is entirely
procedural (operator reinstalls from pinned hashes). The Phase 1 recovery design
(sealed grant + NAS registry) covers mesh identity only; Matrix cross-signing
recovery and vault export/restore drills remain undefined — production blocker.

### T8 — Session expiry
Broker: no session-validity preflight; an expired `BW_SESSION` fails at vault-call
time as a generic `RuntimeError` (L531-532) after the lease is already reserved —
a **lease is consumed by an expired session**, and the failure receipt says only
`broker_failed`. Operator must mint a new lease after re-unlock; acceptable but
should be a typed `session_expired` status with a preflight check. Chat: no
session concept at all.

### T9 — Audit
Broker audit is bounded and content-free (L449-493; test L305-320). **Gap —
negative-path silence:** binding/permission/expiry failures raised before
`_reserve_lease` (L318-323) leave no audit record; chat send failures before
receipt write (e.g., unencrypted-room refusal L681-684) persist nothing. An
operator cannot distinguish "quiet day" from "hundred rejected attempts".
Plan-minting is likewise unaudited (both services).

### T10 — Transport / encryption assertion
`_assert_encrypted` (L642-684) string-matches serialized room JSON for
`"encrypted"` and rejects `"notencrypted"`/`"not_encrypted"`/`"encryption_state":null`.
This is a heuristic over transport output, not a cryptographic property: a
compromised or buggy transport could emit the substring in an unrelated field.
The real trust roots are the hash-pinned binary (verified per call, L700-704) and
the Matrix Rust SDK's own megolm enforcement. Acceptable as defense-in-depth for
the control slice; **must be replaced with a structured-field check** (require an
explicit encryption object from the transport) before production reliance.

## 3. Overclaims register

| # | Claim (source) | Reality (evidence) | Correction |
|---|---|---|---|
| O1 | "revocation invalidates future handle resolution" (modular plan §secret broker) | `revoke()` only consumes one lease; handles remain resolvable forever; no handle-revocation op exists (`secret_broker.py` L413-447) | Implement `revoke_handle` (Slice B) or reword plan |
| O2 | Broker adapter reason: "Destination-bound … worker" (`capability_adapters.py` L631-634) | `worker` is a case-folded config string (L259-262), not a machine identity | Reword to "worker-label-bound" until Phase 1 device binding lands |
| O3 | "approval-gated sends/uses" (both services, pack text) | At the contract layer `approved` is a bare caller-supplied boolean (`capability_adapters.py` L4274, L4316); no approval receipt is bound to the plan hash. Capability-layer permission gating is real (`secret.use`/`network.write` perms; `capability_runtime.py` L114-149) but the two layers are not cryptographically joined | Bind approval receipts to planHash, single-use (Slice B) |
| O4 | Chat adapter reason: "with E2EE proof" (`capability_adapters.py` L603-606); proof safety flag `encryptedRoomRecheckedBeforeUse` | Verification is heuristic substring matching over transport output (§2-T10); no E2EE behavior has ever executed against a real homeserver (zero accounts) | Reword to "encryption re-check (transport-reported)"; replace with structured check (Slice C) |
| O5 | `chat.message-send`/`chat.history` declare `secret.use` in `requiredPermissions` (pack extraction) | Chat never uses the vault; it reads a credential file. The permission taxonomy conflates vault-secret release with chat-credential use, over-scoping chat capabilities and weakening the meaning of `secret.use` | Introduce a distinct `credential.file.read` class in the permission taxonomy (Slice B note) |
| O6 | `messageSha256` on chat plans | Hashes the **pre-attribution** text (L341) while the attributed text is what is transmitted (L469-482); receipt hash ≠ sent bytes | Hash the attributed payload (Slice B) |
| O7 | `available: true` on both adapters (`capability_adapters.py` L602, L628) | With zero accounts/handles/destinations configured, no operation can succeed; "available" conflates code-presence with configured-readiness | Add `configured` field to adapter metadata (Slice C note) |

No overclaim rises to fabricated proof: both foundation proofs explicitly record
`productionAccountConfigured:false`, `productionMessageSent:false`,
`realVaultLoginPerformed:false`, `realSecretResolved:false`. The machine-readable
surfaces are honest; the overclaims above are wording/semantics issues at the
doc/adapter layer.

## 4. Three independently mergeable slices

### Slice A — OS-backed session and credential protection
- **Goal:** eliminate plaintext sessions in process env and plaintext Matrix
  access-token files.
- **Owned files:** `src/grant_agent/keystore.py` (new — DPAPI / Windows Credential
  Manager + headless-file backend per Phase 1 §8); session-resolution region of
  `src/grant_agent/secret_broker.py` (L788-806 replaced by `store:` refs, env kept
  as legacy fallback); credential-resolution region of
  `src/grant_agent/encrypted_chat.py` (L621-640 extended with store-backed
  credentials); `tests/test_keystore.py` (new); focused additions to
  `tests/test_secret_broker.py`, `tests/test_encrypted_chat.py`;
  `config/neyvia_secret_broker.json` + `config/neyvia_chat.json` (additive
  `sessionStore`/`credentialStore` sections).
- **Tests:** store/retrieve round-trip; locked store fails closed pre-vault;
  migration moves env session into store and scrubs env; no plaintext on disk;
  legacy env path still passes existing 14 tests.
- **Rollback:** config `sessionStore.enabled:false` reverts to the env-ref path;
  keystore module inert; no schema break.

### Slice B — Approval-bound plans, negative-path audit, handle revocation
- **Goal:** cryptographically join approval to plan; make denials visible;
  implement O1/O3/O5/O6 fixes.
- **Owned files:** `src/grant_agent/approval_receipts.py` (new — signed,
  single-use, planHash-bound approval records); plan/send/use/revoke regions of
  `src/grant_agent/secret_broker.py` and `src/grant_agent/encrypted_chat.py`;
  `tests/test_approval_receipts.py` (new); focused additions to the two existing
  test files.
- **Tests:** approval/planHash mismatch fails; approval replay fails; expired
  approval fails; denied attempt writes a bounded audit row; `revoke_handle`
  blocks subsequent `plan_use`; chat `messageSha256` covers attributed bytes;
  chat plan replay increments a receipt send-counter.
- **Rollback:** `approvalReceipts.required:false` returns to boolean gate;
  `revoke_handle` op unregistered; audit writer is additive-only.

### Slice C — Transport hardening and chat device/session lifecycle
- **Goal:** remove metadata from argv; replace heuristic encryption check;
  add device lifecycle + typed session-expiry status.
- **Owned files:** `src/grant_agent/encrypted_chat.py` (transport invocation and
  assertion regions); derivative transport patch under the pinned
  matrix-commander-rs source tree (room ID via env/stdin instead of argv — new
  build, new pinned hash); `src/grant_agent/chat_device_lifecycle.py` (new —
  unverified→verified→removed device model, session-expiry preflight, consuming
  the Phase 1 mesh revocation hook); `tests/test_chat_device_lifecycle.py` (new);
  focused additions to `tests/test_encrypted_chat.py`; `config/neyvia_chat.json`
  (additive `devices` section).
- **Tests:** argv contains no room ID; structured encryption proof required and
  fail-closed; device removal hides the device from catalogs; expired session
  yields typed `session_expired` receipt without consuming a lease.
- **Rollback:** config `transport.roomArgFallback:true` restores argv mode with
  the previous pinned binary; lifecycle module additive.

**Merge independence:** slices share only the two service files, with disjoint
edit regions (A: session/credential resolution; B: plan/audit/revoke; C:
transport/device). Any merge order works; recommended sequence A → B → C so the
session store exists before approval binding is load-bearing. No slice touches
mesh, P2P, marketplace, UI, or deployment files.

## 5. Production activation blockers

1. Synapse 1.157.1 NAS deployment + hardening — no automation exists.
2. Vaultwarden 1.36.0 NAS deployment + hardening — no automation exists.
3. Slice A (OS-backed sessions/credentials) — listed as remaining in both proofs.
4. Production provisioning: Matrix account/device/crypto store/room; Vaultwarden
   account/session/item/destination — all configs empty today.
5. Slice B items O1/O3 before any production secret release: handle-level
   revocation and approval-bound plans.
6. Physical-device proof: Windows + Android device verification, cross-signing
   recovery, offline delivery, autofill, protected share.
7. Machine-bound evidence: all staged binaries live on `D:\` of one workstation
   (absent on this review host); production activation needs on-machine
   re-verification.
8. Phase 1 mesh device identity for real worker binding (O2) — cross-phase
   dependency, design already approved-pending.
9. Recovery drills: Matrix key backup/restore and vault export/restore must be
   defined and rehearsed (§2-T7).

## 6. Evidence appendix

Tests run this review (only the two focused suites, as scoped):

```text
python -m pytest tests\test_encrypted_chat.py tests\test_secret_broker.py -q
14 passed in 2.15s   (7 encrypted-chat + 7 secret-broker)
```

Artifact SHA-256 (recomputed this review, 2026-07-24):

| Artifact | SHA-256 |
|---|---|
| `src/grant_agent/encrypted_chat.py` | `6f91354b6c5a99ae69d92a87be171c5516b226db6ad61c2c70e7d01d547dbb8f` |
| `src/grant_agent/secret_broker.py` | `c1ab5aca73c522b5b8fcb32d9a9b1bd19acc254d21a8858a2ffed8f3d4653b64` |
| `config/neyvia_chat.json` | `d736f7da88a82891d42a8072646882726f10cda04f65ea900e7996b9c7bc0242` |
| `config/neyvia_secret_broker.json` | `d34932f44c4a820cbb58ac58a1e73fafc1a13a3507c0386f03d7a2a36e971763` |
| `tests/test_encrypted_chat.py` | `f2cae10d53d1d9755c49a9d5c2e05d1877b3b2249d08978d05c637e47ca42593` |
| `tests/test_secret_broker.py` | `2e6af422e839c905e43c2960d28b3156b5ae87c4d2cbbca3c665671c672d9eb5` |

Both source hashes match the values pinned inside
`.agent_control/capability_os/qa/encrypted-chat-foundation-proof-20260724.json`
and `.agent_control/capability_os/qa/secret-broker-foundation-proof-20260724.json`,
so the reviewed code is exactly the code those proofs describe.

No production-readiness claim is made anywhere in this review. Both systems are
control-slice implementations with contract-level tests and zero production
service, account, or device proof.
