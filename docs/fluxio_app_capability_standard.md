# Fluxio App Capability Standard

Status: bridge contract implemented; signed module platform foundation implemented;
runtime publication and activation pending.

This standard defines how a local app can expose agent-native capabilities to
Neyvia/Fluxio without embedding a full autonomous-agent control plane, and how the
same app can become an independently versioned marketplace module without patching
the core product.

## Core Pieces

1. App Manifest
   Declares app identity, bridge transport, auth requirements, permissions, supported tasks, context surfaces, action hooks, and UI hints.

2. Local Bridge
   A localhost or IPC endpoint for handshake, health, task execution, event streaming, and approval callbacks.

3. Capability Grants
   Explicit grants that scope what Fluxio is allowed to do inside the app. Fluxio should not assume unrestricted code execution.

4. Module Manifest
   `neyvia.module-manifest/v1` declares package identity, runtime isolation,
   compatibility, typed capabilities, surfaces, permission needs, rollback,
   signatures, SBOM, distribution, and a compact context index.

5. Optional User Surfaces
   A full app can add desktop, mobile, web, embedded, or headless surfaces. Surfaces
   remain isolated module resources and do not replace the typed capability API.

6. Staged Installation
   Packages are inspected and verified in an inactive version root. Activation is a
   later atomic pointer switch only after security, permission, health, and
   user-flow receipts pass.

## Design Principles

- Capability-scoped control only
- Local-first transport
- Reviewable permissions and approval requirements
- App-native workflows remain in the app
- Fluxio stays the orchestration shell
- No module patches the core application
- Publisher identity and package content are independently verifiable
- Peer-to-peer transport never bypasses signature or permission checks
- Context is compact and lazy-loaded; large help/schema payloads stay out of startup
- Module data, cache, logs, and executable versions have separate roots
- Uninstall and rollback are explicit, testable operations

## Phase Plan

- Phase A: bridge schema and one owned-app reference integration
- Phase B: module schema, package inspection, and staging-only install plan
- Phase C: Wasmtime/isolated-service runners, Cosign verification, OCI registry, and
  atomic activation/rollback
- Phase D: desktop/mobile/web surface builder and public SDK
- Phase E: verified P2P cache, private mesh, nearby sharing, chat, and opaque secret
  handles

## Current Status

The current implementation provides:

- a manifest schema draft
- example manifests in `config/connected_apps.json`
- a bridge handshake shape
- bridge-lab registry snapshots in the control room
- `config/neyvia_module_manifest_schema.json`
- a real `ModuleMarketplace` validator and hostile-archive preflight
- immutable package hash and entrypoint/SBOM/signature-presence checks
- permission/capability consistency and rollback validation
- an honest staging plan that remains `activationReady: false`

It does not yet ship third-party module activation, registry publication, runtime
sandboxing, or the personal mesh services. The complete design and phased acceptance
gates are in `docs/NEYVIA_MODULAR_PLATFORM_AND_PERSONAL_MESH_PLAN.md`.
