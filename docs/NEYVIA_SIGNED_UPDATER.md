# Neyvia signed updater contract

`config/neyvia_updater.json` and `grant_agent.updater_contract` define the
fail-closed trust boundary for desktop updates. They do not make network calls,
download files, execute installers, or treat discovery as verification.

Admission also rebuilds the canonical dependency inventory from the current
lockfiles, rejects stale or hand-edited reports and unresolved critical
owner/license responsibility, and binds its SHA-256 into the signed manifest
and every signed local gate receipt. See `NEYVIA_DEPENDENCY_INVENTORY.md`.
The resulting plan binds the request nonce hash, exact receipt-set digest,
creation time, and earliest receipt expiry. It is deliberately marked
non-executable: staging or installation must rerun the inventory and artifact
preflight immediately before execution.

## Channels and discovery

- `stable` accepts production releases without prerelease suffixes.
- `beta` is explicit opt-in and accepts signed preview releases.
- `development` is explicit opt-in and accepts signed engineering releases.

An external supervised adapter may retrieve one bounded manifest over
allowlisted HTTPS. Redirects remain on an allowlisted origin. The adapter must
return the manifest and local verification receipts; discovery metadata alone
never makes a release installable.

Origins are parsed as exact HTTPS origins, not prefix-matched URLs. Manifest
templates are fixed safe paths with one channel substitution. Artifact and
delta names are leaf filenames; absolute paths, traversal, separators, drive
prefixes, control characters, and Windows reserved device names are rejected.

## Admission gates

The canonical manifest and the final artifact both require trusted detached
signatures. The manifest fixes the version, channel, exact artifact byte count,
SHA-256, reproducible build identity, compatibility range, and artifact
signature. Admission also requires digest-addressed local receipts for:

1. platform, architecture, version, migration, and data compatibility;
2. SPDX license, dependency, and notice policy;
3. malware and supply-chain scanning;
4. startup, update-time, memory, disk, and regression budgets.

Each receipt is canonical JSON signed with Ed25519 by a configured local
verifier. Its pinned identity and public-key fingerprint, exact manifest and
artifact hashes, platform, architecture, installed and target versions,
channel, opt-in decision, gate kind, opaque device reference, update request
ID, request nonce, issued time, expiry, and deterministic receipt digest are
verified locally. Time comes from the updater's internal UTC clock; callers
cannot supply an assessment time. A caller-provided `verified: true`, `passed:
true`, or arbitrary receipt ID is never evidence.

Accepted receipt digests are inserted transactionally into a durable local
SQLite ledger. A digest can be consumed once, including after process restart,
so an otherwise identical signed request cannot be replayed. Peer receipts also
bind the selected content hash, peer identity, allowlist-policy hash, session
identity, and configured private-transport identity.

Unsigned, untrusted, malformed, downgraded, incompatible, or gate-incomplete
candidates fail before a download/install plan is returned.

The checked-in release and local-verifier trust-root records are explicitly
`provisioned: false`. Therefore production cryptographic acceptance remains
unproven and fail-closed until protected release/verifier key ceremonies
replace and enable those records. The focused tests use ephemeral keys and do
not turn the checked-in placeholders into production trust.

## Delivery, rollback, and recovery

A delta is eligible only when the installed base hash and patch signature were
verified and the delta is meaningfully smaller. A peer cache is eligible only
when the peer is allowlisted, private, and bound to the requested content hash.
Missing, stale, replayed, or otherwise invalid optional optimization evidence
does not become trusted: it falls back to the complete signed artifact or the
supervised upstream. Required artifact, gate, and approval evidence remains
fail-closed. Every path retains the complete artifact's detached signature,
reproducible build identity, and final full-artifact SHA-256 verification.

The state machine is explicit:

`idle -> discovering -> candidate_found -> verifying_signature -> gating ->
ready -> downloading -> verifying_artifact -> staging -> installing ->
health_check -> completed`

Install or health failure enters `rollback -> recovery`. Recovery restores the
previous version and compatible data snapshot first, then safe mode with
updates disabled, and finally operator repair. A successful target install ends
as `completed` with outcome `target-installed`; recovery ends separately as
`restored_previous` with outcome `previous-version-restored`. Invalid state
jumps are refused. Progress construction validates the state and exact
percentage, while detail is control-character-cleaned, secret-redacted, and
bounded.
