# Neyvia Modular Platform and Personal Mesh Plan

Status: active platform expansion goal  
Baseline date: 2026-07-23  
Scope: module SDK, marketplace, desktop/mobile apps, private mesh, nearby sharing,
continuous synchronization, encrypted messaging, secrets, and distance-insensitive
context bootstrap

## Product outcome

Neyvia must let an operator or agent:

1. create a capability, workflow, content pack, service, or complete application in
   the workspace;
2. add an embedded, web, mobile, or native desktop surface when useful;
3. test it against the same permissions, artifacts, receipts, emulators, and
   verifiers used by the core product;
4. package it once as a signed, versioned module;
5. publish it to a marketplace;
6. install or update it without patching the Neyvia core tree;
7. remove or roll it back without damaging other modules or user data;
8. make its complete operation surface progressively discoverable to agents; and
9. use the same module on authorized phones, computers, NAS workers, and remote
   workers through the private mesh.

The marketplace is an extension plane, not a second application installer bolted
onto the UI. Installed modules become first-class agent capabilities and, when they
declare a surface, first-class user tools.

## Honest current baseline

The repository already has:

- a thin Python runtime client in `src/grant_agent/sdk.py`;
- a draft app capability manifest and scoped bridge in
  `src/grant_agent/app_capability_standard.py`;
- connected-app sessions and capability grants;
- a Tauri 2 desktop/mobile shell;
- durable mission, artifact, permission, receipt, and external-session contracts;
- NAS-aware cluster and desktop-gateway routing; and
- early Tailscale-address fields for existing workers.

It does not yet have a public marketplace, OCI publication, isolated native-service
or full-app activation, a private network control plane, integrated multi-device
messaging, or a secret broker. Signed content-pack activation, zero-grant WebAssembly
smoke execution, dependency gating, disable, and rollback are now real locally.

The signed local marketplace slice is now implemented:

- `config/neyvia_module_manifest_schema.json` defines the versioned module contract;
- `src/grant_agent/module_marketplace.py` validates manifests, rejects secret-bearing
  metadata, verifies immutable archive size and SHA-256, rejects path traversal,
  symbolic links, duplicate entries, decompression bombs, missing entrypoints,
  missing signature/SBOM/context resources, undeclared permissions, unsafe runtime
  combinations, and non-recoverable migrations;
- deterministic `.nymod` archives use a detached signature envelope, so the
  canonical manifest can bind the final archive hash without a circular
  self-signature;
- Cosign 3.1.2, Wasmtime 47.0.2, Syft 1.49.0, Grype 0.116.0, and the current
  Windows Defender platform are installed as portable hash-pinned tools under
  `D:\Neyvia\apps`, without mutating the system `PATH`;
- publisher trust, exact hash/size checks, safe quarantine extraction, Defender
  scanning, declared and independently generated SBOM checks, Grype policy,
  dependency resolution, permission review, and isolated smoke tests fail closed;
- immutable version directories and `current.json` provide atomic activation,
  disable, and rollback for content packs and zero-grant WebAssembly modules;
- build, detached signing, validation, local content-addressed publishing, trust,
  review, install, catalog, disable, and rollback are exposed through the Python
  SDK and web command boundary; and
- the five verification engines also have typed, permission-aware agent operations
  with workspace path confinement and structured receipts; and
- `marketplace_toolchain.py` plus the scheduled maintenance workflow stream-verify
  installed hashes, discover only official stable GitHub assets carrying an exact
  SHA-256 digest, cache checks off the startup path, and fail the maintenance gate
  when a reviewed pin is no longer current. Dependency candidates activate only
  through a tested, signed Neyvia release.

The end-to-end proof at
`.agent_control/capability_os/qa/marketplace-activation-proof/20260724-024836`
passed all ten gates. Once the Grype database was warm, Cosign took 639 ms,
Defender 262 ms, Syft 1.35 s, and Grype 2.27 s in that transaction. Native-service
and full-app activation remain intentionally blocked until their OS/container
sandbox and first-run health-window rollback are real.

## Stable extension boundary

Marketplace modules never write into the core installation or repository. Every
module receives:

```text
D:\Neyvia\modules\<module-id>\<version>\
D:\Neyvia\module-data\<module-id>\
D:\Neyvia\module-cache\<module-id>\
D:\Neyvia\module-logs\<module-id>\
```

Activation is one atomic pointer:

```text
D:\Neyvia\modules\<module-id>\current.json
```

A transaction stages a new version, verifies it, starts it in isolation, runs its
health and user-flow proof, then atomically changes the pointer. The previous pointer
and a data backup remain available for rollback. A failed stage never changes the
active module.

Modules cannot replace core routes, permission policy, artifact receipts, trust
roots, updater logic, or another module's data. Capability operations, surface
IDs, and app routes are publisher-qualified. Their claims are persisted in the
active pointer and compared across all active modules under a marketplace-wide
activation lock. A collision blocks activation or rollback atomically and leaves
the staged package inactive with a durable receipt.

## Module classes

| Class | Best use | Runtime | Default isolation |
|---|---|---|---|
| WASM component | Small deterministic tools, parsers, transforms, validators | Wasmtime and WASI Component Model | No ambient filesystem, network, process, clock, or secrets |
| Isolated service | Long-running engines, model servers, database-backed tools | Native worker or container | Dedicated identity, ports, directories, quotas, and healthcheck |
| Full app | Desktop/mobile/web product with agent capabilities | Tauri or project-native build plus app bridge | Separate process and signed surface bundle |
| Content pack | Skills, prompts, schemas, templates, models, reference data | Data-only loader | No executable permission |

WASM is the default for third-party logic because it has the smallest authority
surface. Native services and complete applications remain possible when their
function genuinely requires system APIs, GPU access, GUI integration, or an
upstream runtime.

## Module manifest and SDK

The v1 manifest records:

- module, publisher, version, license, source, and compatibility identity;
- immutable package hash and size;
- Sigstore/Cosign bundle, publisher identity, and issuer;
- runtime class, isolation, entrypoint, typed healthcheck, and supported platforms;
- required and optional permissions with exact scopes and reasons;
- typed capabilities with JSON input/output schemas;
- desktop, mobile, web, embedded, or headless surfaces;
- authoritative OCI registry reference and optional private P2P mirrors;
- update channel, reversible migrations, backup strategy, and rollback support; and
- a compact summary index plus lazy resources for fast model discovery.

The SDK must grow from a thin HTTP client into:

- `neyvia module init`, `validate`, `test`, `pack`, `sign`, `publish`, `install`,
  `verify`, and `rollback`;
- Python, TypeScript, Rust, Kotlin, and Swift bindings generated from the same
  module API;
- typed task, context, event, artifact, approval, secret-handle, and receipt APIs;
- a local module host and permission simulator;
- an emulator matrix for web, Windows, Android, and authorized remote Apple builds;
- reference templates for WASM tools, services, embedded panels, and full Tauri apps;
- compatibility and migration test fixtures; and
- deterministic package and SBOM generation.

The existing Tauri dependencies must be updated through a compatibility branch and
full Windows/Android build proof. Tauri 2.11.5 is the current candidate checked on
the baseline date, but its Rust dependency advisories must be resolved or explicitly
accepted before pinning. The active frontend is not upgraded in place while Cursor
work is ongoing.

## Marketplace architecture

### Authority and package storage

- OCI artifacts are the authoritative package and metadata channel.
- ORAS provides generic OCI push, pull, copy, and discovery.
- Cosign verifies publisher identity, signature bundle, transparency evidence, and
  attestations.
- A private NAS registry keeps an available local mirror.
- Package identity is the archive SHA-256, never a mutable URL or tag alone.
- Stable, beta, nightly, and project-pinned channels remain separate.

### Review and discovery

Marketplace listings expose:

- exact capabilities and operation schemas;
- required permissions and default-denied optional permissions;
- supported platforms and resource estimates;
- package, SBOM, signature, scan, build, and test receipts;
- source and license;
- update and rollback history;
- compatibility matrix;
- human reviews separated from automated verification; and
- reproducible proof artifacts.

Popularity is useful evidence, but does not override signature, maintenance,
security, compatibility, or license policy.

### Installation transaction

1. Resolve the immutable registry digest.
2. Prefer a verified local/NAS/private-peer copy with that digest.
3. Download into a new staging directory.
4. Verify hash, size, archive safety, Cosign identity, SBOM, license, vulnerability,
   and malware policy.
5. Compare requested permissions with the installed version.
6. Require approval for new sensitive permissions or irreversible migrations.
7. Start in the declared sandbox with temporary data.
8. Run typed health, capability, and surface user-flow tests.
9. Back up module-owned data when a migration is needed.
10. Atomically activate the new version.
11. Watch the first-run health window.
12. Roll back automatically on a verified regression.

Dependency conflicts never install packages into the core Python, Node, Rust, Java,
or system environment. Each service or app owns its runtime lock and cache.

## Where P2P helps

| Area | Use P2P | Reason |
|---|---|---|
| Signed module archives | Yes, private mesh only | Immutable hash makes peers safe distribution caches |
| Models, SDKs, emulator images, and large build artifacts | Yes | Large immutable blobs benefit most from NAS and peer locality |
| Selected user folders | Yes, explicit folder grants | Continuous peer sync avoids unnecessary cloud round trips |
| Nearby one-shot files, links, and text | Yes | Direct LAN transfer is fast and intuitive |
| Context summaries and content-addressed chunks | Yes | Local replicas make normal session bootstrap independent of WAN latency |
| Marketplace ranking, publisher identity, revocation, and policy | No | These require an authoritative signed control plane |
| Permission grants and approval decisions | No | Local authority and audit ordering must remain unambiguous |
| Raw passwords or private keys | No | Secrets use an encrypted vault and opaque handles |
| Mutable databases and active job state | Usually no | Durable primary ownership and conflict rules are safer |

Kubo/IPFS 0.40.1 is the current content-addressed distribution candidate. It must run
as a private-mesh cache with explicit peers and quotas by default, not join the public
DHT automatically. OCI remains authoritative; P2P only supplies a blob whose digest
has already been selected and trusted.

## Neyvia Mesh

Neyvia should own the user experience, identity mapping, policies, health, and agent
operations while reusing reviewed network primitives.

NetBird is the initial reference implementation because it already provides:

- WireGuard tunnels;
- direct peer discovery through ICE/STUN;
- relay fallback;
- management and signal services;
- groups, access rules, routes, private DNS, posture checks, exit nodes, setup keys,
  SSO/MFA, activity logs, API automation, and mobile/desktop clients; and
- self-hosted operation.

NetBird 0.75.0 was released on the baseline date and is the selected feature line.
Its daemon HTTP/JSON gateway, status and event streams, richer peer/network APIs,
client-side config generation, probe throttling, and lazy-connection warming are
material advantages for an agent-controlled, latency-sensitive product. Headscale
0.29.2 remains the Tailscale-compatible alternative, but requires more client and
control integration for the same Neyvia surface.

The first provider-neutral Neyvia Mesh foundation is implemented:

- `config/neyvia_mesh.json` separates the current transport bridge from the target
  provider and keeps cutover disabled;
- `mesh_service.py` exposes sanitized peer health, direct/relay probes, explicit
  private service discovery, and fail-closed migration gates;
- provider-owned Funnel ingress peers are removed from model context while real
  enrolled and shared devices remain visible;
- live status is cached for three seconds and full provider details stay off the
  compact application bootstrap path;
- typed Capability OS operations expose status, probe, service listing,
  advertisement, revocation, and migration planning; network writes still require
  explicit approval; and
- the current Tailscale bridge completed a sanitized live snapshot in about 240 ms,
  while the NAS route passed direct peer-to-peer at 6 ms.

The bridge is not the final architecture. NetBird client/control-plane installation,
Android enrollment, relay fallback, DNS/routes, revocation, and recovery must all
pass before `cutoverEnabled` can change.

Neyvia Mesh adds:

- device identity linked to the Neyvia account and capability grants;
- one-click enrollment with short-lived setup material;
- agent-readable peer, route, latency, relay, posture, and health state;
- policy templates for personal devices, NAS workers, guests, build workers, and
  isolated security labs;
- automatic selection of direct LAN, direct WAN, or relay paths;
- file, context, marketplace, app-bridge, chat, and vault service discovery;
- revocation and remote lock;
- signed connection receipts; and
- a recovery path that does not depend on one workstation.

Neyvia must not invent a new VPN cipher or fork WireGuard merely for branding. A
small maintained NetBird fork is justified only if its public control APIs cannot
support required module, agent, or recovery semantics.

## AirDrop-like transfer and continuous sync

Two workflows are intentionally separate:

### Nearby Send

LocalSend 1.17.0 is the current cross-platform reference for nearby discovery and
encrypted local file/text transfer. Neyvia integrates its protocol or a bounded
sidecar so the operator can:

- choose one or more nearby trusted devices;
- send files, folders, links, or text;
- preview destination, size, and collision policy;
- require recipient acceptance unless a favorite-device policy allows automatic
  receipt;
- see transfer progress and final hashes; and
- register sent and received files in the artifact graph.

The first sender slice is implemented. The optional LocalSend 1.17.0 Windows client
is installed under `D:\Neyvia`, with the Winget installer hash, installed executable
hash, and clean Defender scan recorded; it is not launched or added to autostart.
Neyvia's native LocalSend v2.1 client now provides bounded multicast discovery,
certificate-fingerprint pinning, workspace-only source access, immutable transfer
previews, changed-source rejection, up to four parallel uploads, cancellation,
non-retention of file/session tokens, and durable artifact receipts. A real
two-file protocol transfer passed against a loopback receiver. The receiver sidecar,
first-class text/link payloads, favorite-device policy, remote hash acknowledgement,
and Windows-to-Android physical-device proof remain pending.

### Folder Sync

Syncthing 2.1.2 is the current continuous P2P sync reference. It is used only for
explicitly selected folders with:

- send-only, receive-only, or bidirectional direction;
- ignore patterns;
- versioning and conflict retention;
- quotas and bandwidth policies;
- device and folder health;
- NAS availability; and
- approval before enabling deletion propagation.

Nearby Send is a deliberate one-shot action. Folder Sync is an ongoing replicated
state relationship. Mixing them would make destructive synchronization too easy.

The first Folder Sync control slice is implemented. Syncthing 2.1.2 is staged at
`D:\Neyvia\apps\syncthing\2.1.2`; its official Winget archive hash, installed
executable hash, Windows signature, reported version, and clean Defender result
are recorded. It was not started and no startup entry or folder relationship was
created.

Neyvia now owns a credential-hiding REST contract rather than exposing Syncthing
directly. The contract provides cached sanitized health, optional detailed folder
status, bounded events, send-only/receive-only/bidirectional plans, safe ignore
rules, local versioning gates, paused application, explicit deletion-propagation
activation, pause, rescan, and separately confirmed override/revert. Plans bind the
observed folder and ignore state; stale plans fail closed. A partial apply restores
the previous folder configuration. External versioner commands and ignore-file
include directives are not accepted from an agent.

The authenticated loopback protocol harness and Capability OS regressions pass
59 tests. Production service creation, NAS and Android device pairing, physical
disconnect/reconnect convergence, conflict and version-restore drills, and large
tree performance measurements remain. The proof is stored in
`.agent_control/capability_os/qa/folder-sync-foundation-proof-20260724.json`.

## Encrypted multi-device chat and link sharing

The selected foundation is a private Matrix deployment:

- Synapse 1.157.1 on the NAS as the homeserver;
- Matrix Rust SDK 0.18.0 inside Neyvia clients;
- Element X Android 26.07.x as the initial Android compatibility client; and
- Element Web 1.12.24 as a reference client and fallback surface.

Federation is disabled by default for the personal mesh. Rooms use end-to-end
encryption, device verification, key backup/recovery, retention policy, attachments,
reactions, replies, search indexes, and delivery/read state.

Neyvia exposes:

- personal notes-to-self;
- direct device/user conversations;
- mission rooms;
- links, text, voice notes, images, and artifact references;
- optional message-to-task and message-to-artifact conversion;
- explicit agent participation per room; and
- local notifications and offline queues.

The agent never receives all rooms by default. Room access, history range, attachment
access, and message sending are separate capabilities. Agent messages are visibly
attributed and receipt-backed.

The first encrypted-chat control slice is implemented. Element Desktop 1.12.24 is
installed with its package hash, executable hash, Windows signature, and clean
Defender result recorded. The agent transport derives from matrix-commander-rs
0.11.0 and Matrix Rust SDK 0.18.0. Neyvia removes its unused forced vendored
OpenSSL dependency, avoiding a Perl/NASM/NMake/OpenSSL build and retaining the
Rust TLS path already used by the Matrix SDK. The resulting 69,102,592-byte
optimized executable is pinned by source-tree and binary SHA-256, is
Defender-clean, and passes its zero-side-effect health probe in 62.76 ms median
and 113.27 ms p95 across five launches. Whole-program LTO was rejected after
measurement because full LTO consumed roughly 5.98 GB and thin LTO roughly
2.43 GB during linking without evidence of a runtime benefit.

The `chat.control` contract exposes compatibility, opaque account/room scopes,
hash-bound message plans, approval-gated sends, bounded sanitized history, and a
durable local Matrix lifecycle ledger. Enrollment intents create separate
secret-free account, device, and expiring session records. Device removal first
disables the local device and remains `remote_removal_required`; recovery remains
`operator_action_required`; neither state claims a server action. When Synapse is
not deployed, each applicable operation instead reports
`blocked_homeserver_unavailable`.

Typed self-chat planning supports links, workspace files, clipboard text, and
notes in the single allowed encrypted self room. Link credentials are rejected;
model-facing lifecycle results use opaque references; and persisted self-chat
receipts contain payload kinds, hashes, and byte counts rather than plaintext.
The transport refuses likely passwords, API keys, JWTs, and long hex secrets;
accepts workspace attachments only; verifies each room is encrypted immediately before
send or history access; passes message and file content over stdin; and stores
receipts without message content or credentials. Raw Matrix user, device,
homeserver, and room identifiers are not part of agent-facing catalogs.

No production Matrix account, crypto store, homeserver, or room has been created.
The secret-broker contract now exists, but production activation remains blocked
on its OS-protected credential store and the NAS vault/homeserver deployments.
Native stdin/IPC transport, actual account login and device verification, offline
delivery, server-side device removal and token invalidation, cross-signing
recovery, and physical Windows/Android proof are still required for production
activation.

SimpleX remains an evaluated privacy-focused alternative for conversations needing
stronger metadata protection, but its relay topology and integration model are not
the default Neyvia collaboration substrate.

## Password manager and secret broker

Vaultwarden 1.36.0 is the current lightweight self-hosted Bitwarden-compatible
server candidate. It provides established desktop/mobile/browser clients, personal
vaults, organizations, collections, attachments, sharing, and Send-style protected
exchange.

The Neyvia secret broker sits in front of the vault:

- secrets are addressed by opaque handles, never returned in marketplace manifests,
  context indexes, logs, prompts, receipts, or chat history;
- agents request a handle for a specific tool, account, operation, worker, and TTL;
- the user approves sensitive release;
- the broker injects the secret only into the destination process or protocol field;
- clipboard use is exceptional, visible, and automatically cleared;
- one-time and time-limited sharing uses the vault's encrypted sharing mechanism;
- every access records identity, scope, destination, and expiry without recording the
  secret value; and
- revocation invalidates future handle resolution.

Chat is for links, coordination, and encrypted attachments. It is not the password
transport.

The first secret-broker slice is implemented. The current Bitwarden CLI OSS
2026.7.0 Windows release is staged from its official immutable GitHub asset; its
release digest, executable hash, Bitwarden Inc. signature, reported version, and
clean Defender result are recorded. The CLI state root is redirected to
`D:\Neyvia\state\bitwarden-cli`; the accidental empty default bootstrap file
created during version verification was moved there and its empty source directory
removed.

Neyvia does not expose the CLI directly. The `secret.broker` contract provides a
redacted compatibility report, opaque handle/destination catalogs, short-lived
hash-bound use plans, plan-hash-bound approval artifacts, atomic one-time
consumption, durable device/session revocation, and bounded content-free audit.
Each delivery has a random opaque handle and is bound to fixed destinations,
operations, workers, devices, sessions, and executable hashes. The broker resolves
the value into memory with the vault session in the child environment, then injects
it through environment or stdin. It rejects secret-bearing arguments, inherits only
a minimal environment, disables clipboard by default, returns no destination output
to model context, and treats any exact-value output as a policy violation. Provider
exceptions are reduced to error classes before a receipt is returned or persisted.

No production Vaultwarden server, account, session key, vault item, or destination
binding has been created. NAS deployment, OS credential-store-backed session
provisioning, official desktop/mobile/browser client interoperability, physical
autofill and protected-share proof, rotation, recovery, and backup drills remain.
Bitwarden Secrets Manager stays an optional paid provider rather than a hidden
requirement for the free local-first path. The retained proof is
`.agent_control/capability_os/qa/secret-broker-foundation-proof-20260724.json`.

## Fast context regardless of distance

Physical distance cannot be removed, so the architecture removes remote reads from
the critical session-start path.

Every module and workspace supplies:

1. a compact local bootstrap index, normally 8 KB or less;
2. content-addressed summary chunks;
3. a local SQLite search/index cache;
4. lazy schemas, docs, artifacts, and history loaded only after selection;
5. predictive prefetch for the active workspace and likely next operation;
6. NAS and authorized peer replicas for immutable chunks;
7. delta transfer rather than full context copies;
8. stale-while-revalidate behavior for non-authoritative summaries; and
9. authoritative freshness checks before writes or security-sensitive decisions.

The target is local-speed capability discovery even when the source worker is far
away. Remote distance should affect only the first missing chunk or the actual remote
operation, not every prompt.

The first fast-context cache slice is implemented. Iroh 1.0.3 is selected as the
private peer transport, with iroh-blobs 0.103.0 for BLAKE3 verified/resumable
content transfer and iroh-docs/iroh-gossip 0.101.0 reserved for replicated indexes
and live invalidation. Kubo 0.42.0 remains an optional public-IPFS gateway, not a
default personal-mesh dependency.

The current `cache.p2p` implementation stays local-first: it creates hash-bound
import previews for workspace files, rechecks source size/time/hash, stream-copies
through a temporary file, fsyncs and verifies BLAKE3 before atomic placement,
deduplicates immutable objects, and records bounded metadata in a SQLite WAL
index. Bounded text ranges are served without a network round trip; object content
is rehashed if indexed size or modification time changes.

The first real peer-fetch transport is also implemented. A 12,035,584-byte
Neyvia Rust sidecar pins Iroh 1.0.3 and iroh-blobs 0.103.0, accepts its control
request only as a bounded JSON line on stdin, persists stable endpoint identity,
uses no public discovery or public relay, and rejects non-allowlisted endpoint
identities through Iroh's post-handshake hook before the blob protocol executes.
The Python contract exposes only opaque peer references; endpoint IDs and blob
tickets stay below the agent boundary. Fetch plans bind the offer digest, object
hash, size ceiling, kind, peer, and pin policy. Downloads remain in the Iroh
staging store until a second local BLAKE3 check passes, then enter the Neyvia CAS
through an atomic replace.

A real 1,769,728-byte loopback transfer passed in 207.4 ms inside the sidecar
(599.1 ms including two one-shot process lifecycles), with matching BLAKE3,
denied-peer rejection, clean shutdown, and public infrastructure disabled. A
separate full Python-wrapper-to-sidecar proof passed and retained a bounded local
read without exposing the provider identity or ticket. Production peers are
still empty, so remote lookup is implemented but not configured.

The client sidecar now starts lazily and persists behind parent-owned pipes. Its
endpoint, identity, async runtime, and blob database are reused while the exact
executable hash and peer allowlist stay unchanged; a peer-policy change closes
the old session before creating a new one. In a two-fetch proof, the first fully
wrapped fetch paid the 1.11-second lazy startup cost and the warm fetch completed
in 182.1 ms, compared with roughly 1.14 seconds for the earlier one-shot wrapper
path. This measured path is about 6.3 times faster without adding a listening
control port.

Remaining work is supervised long-lived provider lifecycle, secret-broker/OS-backed
endpoint identity protection, production peer enrollment, private relay
deployment, multi-peer scheduling and performance tuning, publish/replication
policy, package/model replication, quotas and garbage collection, mobile
bindings, and retained Windows/Android/NAS cold-versus-warm latency receipts.
The proofs are stored in
`.agent_control/capability_os/qa/p2p-cache-foundation-proof-20260724.json` and
`.agent_control/capability_os/qa/iroh-peer-fetch-proof-20260724.json`.

## Delivery phases

### Phase 0: contract foundation, complete

- Versioned module manifest.
- Safe immutable ZIP inspection.
- Secret-key rejection.
- Runtime/isolation and permission consistency checks.
- Reversible migration policy.
- Honest activation blockers for unsupported runtime classes.

### Phase 1: SDK and signed marketplace core, in progress

- Build, sign, inspect, trust, review, install, catalog, disable, and rollback SDK
  operations are implemented; command-line ergonomics and generated language
  bindings remain.
- Cosign, Wasmtime, Syft, Grype, and Windows Defender are installed, pinned, and
  integrated with real proof receipts.
- Local content-addressed registry seed publishing is implemented.
- Add a local/NAS OCI registry.
- Content-pack and WebAssembly staging, atomic activation, disable, and rollback
  are implemented; native-service/full-app sandboxing and the post-activation
  health window remain.
- Build one WASM reference module and one Tauri full-app module.

### Phase 2: app builder and emulator matrix

- Add module templates and generated bindings.
- Build, test, and package web, Windows, Android, and authorized Apple targets.
- Add desktop and embedded surfaces to the app bridge.
- Run real user flows before publishing.

### Phase 3: private mesh and sharing

- Deploy the selected NetBird line on NAS, Windows, and Android.
- Add peer/policy/route/relay/DNS health to the agent control plane.
- Integrate Nearby Send through LocalSend.
- Integrate selected-folder sync through Syncthing.

### Phase 4: personal communications and secrets

- Deploy Synapse and the integrated Matrix client surface.
- Add notes-to-self, mission rooms, file/link sharing, and explicit agent room grants.
- Deploy Vaultwarden.
- Add secret handles, TTLs, approvals, injection, revocation, and audit receipts.

### Phase 5: private P2P distribution and fast context

- Deploy private Kubo cache peers on NAS and selected devices.
- Mirror immutable marketplace packages, models, SDKs, emulator images, and artifact
  bundles by digest.
- Add compact module/workspace indexes, lazy chunk retrieval, predictive prefetch,
  and cache quality metrics.

## Acceptance gates

- Installing, updating, crashing, or removing a third-party module cannot modify or
  prevent startup of the Neyvia core.
- No module activates without a matching immutable hash and verified publisher
  signature.
- Sensitive permission changes are previewed and approved.
- Every module class has resource limits, health, cancellation, receipts, and
  rollback.
- A full app can be built, packaged, installed, opened as a user, controlled as an
  agent, updated, and rolled back on Windows and Android.
- Nearby transfer works between Windows and Android with matching file hashes.
- Selected-folder synchronization survives disconnect/reconnect and retains
  conflicts.
- Direct mesh traffic, relay fallback, device revocation, and NAS recovery are
  verified.
- Chat works across phone, computer, and NAS-backed service with device verification
  and offline delivery.
- A secret reaches an authorized tool through a handle without appearing in chat,
  prompt context, logs, or receipts.
- Capability discovery remains local and compact when remote peers are slow or
  offline.

## Primary open-source references

- Tauri: <https://github.com/tauri-apps/tauri>
- Wasmtime: <https://github.com/bytecodealliance/wasmtime>
- ORAS: <https://github.com/oras-project/oras>
- Cosign: <https://github.com/sigstore/cosign>
- NetBird: <https://github.com/netbirdio/netbird>
- LocalSend: <https://github.com/localsend/localsend>
- Syncthing: <https://github.com/syncthing/syncthing>
- Kubo/IPFS: <https://github.com/ipfs/kubo>
- Matrix Rust SDK: <https://github.com/matrix-org/matrix-rust-sdk>
- Synapse: <https://github.com/element-hq/synapse>
- Element Web: <https://github.com/element-hq/element-web>
- Element X Android: <https://github.com/element-hq/element-x-android>
- SimpleX: <https://github.com/simplex-chat/simplex-chat>
- Vaultwarden: <https://github.com/dani-garcia/vaultwarden>
