# Neyvia model portfolio and Capability Treasury

Recorded: 2026-07-30

## Goal

The milestone turns Neyvia into a more useful local-native agent ecosystem without making one model, one provider, or one conversation the permanent center of the product.

The intended experience is:

1. Describe the work in human terms.
2. See a small, honest task lane for routine, deep, or verification work.
3. Keep the model already proven on the machine.
4. Add Kimi K3-capable routes without pretending that installation equals authentication.
5. Recover useful apps, skills, proof, plans, receipts, and artifact lineages from prior work.
6. Prepare a bounded recovery mission for review instead of silently running, activating, publishing, or raising trust.

## Implemented outcome

### Task-first model portfolio

Neyvia now exposes three task lanes:

| Lane | Intended work | Current ready route | Additional declared routes |
| --- | --- | --- | --- |
| Routine | Everyday questions, small-file edits, bounded inspections | `openai-codex / gpt-5.6-sol / low` | Kimi Code `k3-256k / low`, OpenCode Go `kimi-k3 / low` |
| Deep | Large codebases, multi-file changes, long documents | `openai-codex / gpt-5.6-sol / high` | Kimi Code `k3 / high`, OpenCode Go `kimi-k3 / high` |
| Verification | Independent proof and review | `openai-codex / gpt-5.6-sol / high` | OpenCode Go `kimi-k3 / high` |

The existing Codex model remains usable and is currently the ready recommendation. The local Kimi CLI is installed, but `kimi provider list` reports `No providers configured.` Kimi therefore remains setup-required and cannot launch from Neyvia. OpenCode Go is also shown as authentication-required. No fallback is automatic, and every route requires operator confirmation.

### Provider ID boundary

Neyvia keeps provider-specific identifiers distinct:

- Kimi Code uses the managed aliases `k3` and `k3-256k`.
- Moonshot's direct Kimi K3 platform uses `kimi-k3`.
- OpenCode Go exposes its own `kimi-k3` route.

Neyvia does not convert one of these identifiers into another. This avoids an apparently successful launch that actually calls a different provider or silently falls back to another model.

Kimi Code's current model documentation describes `k3-256k` as the fixed 256K, quota-efficient route for routine and small-file work, while `k3` can expose up to a 1M context window depending on membership. K3 accepts `low`, `high`, and `max` reasoning efforts. Neyvia writes a selected model into the durable run request and uses the documented `KIMI_MODEL_*` environment channel for an exact temporary provider. It does not invent a Kimi CLI reasoning flag.

Primary sources:

- Kimi Code model configuration: https://www.kimi.com/code/docs/en/kimi-code/models.html
- Kimi Code environment variables and temporary providers: https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/env-vars
- Kimi Code provider and model configuration: https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/providers.html
- Moonshot Kimi K3 model and direct API notes: https://github.com/MoonshotAI/Kimi-K3
- OpenCode Go: https://opencode.ai/go

### Capability Treasury

The live workspace scan produced:

- 41 bounded local asset capsules
- 11 capsules with typed verified state
- 30 capsules requiring review
- 8 prepared recovery missions
- 8,163,298 bytes indexed by metadata and SHA-256

The indexed kinds are:

- 16 plan-like documents
- 15 proof bundles
- 3 local apps
- 3 artifact lineages
- 2 skill packages
- 1 verified App Factory package
- 1 receipt ledger

The first current recovery is **Reuse Neyvia Quick Notes**. Its deterministic `.nyapp` package and passing App Factory receipt already exist. Neyvia proposes inspecting and rehashing that evidence before considering reuse or a minimal repair.

Recovery types cover:

- reusing a verified app
- reviewing a skill lineage
- composing an artifact lineage
- packaging existing proof
- reviewing a shelved plan

The treasury stores no document body, transcript body, app body, prompt transcript, credential, or secret-named file. It stores paths, typed states, counts, timestamps, sizes, SHA-256 digests, and lineage references. A file is skipped if it is larger than 16 MiB, symlinked, under an excluded build or dependency directory, or has a secret-like name. Bundle scans stop at 160 files and the whole inventory stops at 180 assets.

Every recovery stays:

- `review_required`
- inactive
- unpublished
- unable to raise trust
- unable to expand authority
- unable to include transcripts

Selecting **Prepare recovery mission** places an inspection-only prompt into Agent Live. It does not start a run. The recommended route is applied only when that exact route is ready.

### Skill evolution

Skill iteration now has a safer upstream discovery path. Old skill packages and available backup lineage can become a review mission, but repetition or age cannot promote them.

A recovered skill must still pass the existing Neyvia evolution gates:

1. exact package sealing
2. comparable baseline and candidate receipts
3. unchanged authority or an explicit authority decision
4. Counterfactual Skill Forge review
5. rollback evidence
6. explicit human acceptance
7. inactive materialization before any later activation

This separates finding value from trusting value. The treasury helps Neyvia notice useful prior work, while the receipt-bound evolution system decides whether an iteration is actually better.

## Competitive position

The comparison is intentionally narrow and evidence-based.

- The Codex app offers parallel agents, skills, automations, worktrees, and review surfaces: https://openai.com/index/introducing-the-codex-app/
- Cursor offers project memories with approval and remote background agents: https://docs.cursor.com/en/context/memories and https://docs.cursor.com/background-agent
- OpenCode provides configurable primary agents, subagents, model selection, and permission policies: https://opencode.ai/docs/agents

Neyvia's implemented difference in this milestone is not a claim that competitors lack memory or agents. It is the combination of:

- task-first routing across already configured and future providers
- explicit provider/model identity with no silent fallback
- local recovery across apps, skills, plans, proof, receipts, and artifact graphs
- exact hash and typed-proof references instead of full conversation capture
- review-only recovery missions
- receipt-bound skill evolution, rollback, activation, and publication gates

This lets old work become new leverage without making historical text or model confidence an authority source.

## Alternatives considered

### Cheapest-model automatic routing

This would feel fast but could silently change provider, privacy boundary, quota, or model behavior. Neyvia instead recommends a route and records the exact selection.

### Full-text or transcript vector memory

This could improve semantic search, but it would persist private text and make deletion, trust, and provenance harder. The implemented treasury starts with typed metadata, hashes, and bounded lineage. A future semantic index would need a separate opt-in privacy contract.

### Rebuild old apps from prompts

This wastes verified packages and can lose the exact proof that made an app trustworthy. Neyvia now prefers rehashing and reusing an existing package, then applying the smallest repair only if current proof requires it.

### Remote agent history as the source of truth

Remote background execution can be valuable, but it should not own Neyvia's durable trust state. Local receipts and explicit promotion decisions remain authoritative.

## User-like verification

Verification used the Chrome plugin only. The integrated navigator was not used.

The verified journey:

1. Opened the live capability evolution surface.
2. Confirmed 41 local assets, 11 verified assets, and 8 review missions.
3. Prepared **Reuse Neyvia Quick Notes**.
4. Confirmed the prompt appeared in Agent Live without starting a run.
5. Confirmed the ready Codex route changed to low effort for the routine inspection.
6. Opened Harness Control and selected Kimi Code.
7. Confirmed the visible readiness was `provider setup required`.
8. Confirmed Routine `k3-256k` and Deep `k3` remained distinct.
9. Entered a harmless local inspection objective and confirmed Launch stayed disabled.
10. Confirmed the profile showed `k3`, `k3-256k`, and `KIMI_API_KEY`, without entering or saving a credential.
11. Confirmed zero application console errors.

## Automated and native verification

- Full frontend model suite: 128 passed.
- Focused provider, treasury, backend, routing, harness, and UI Python suite: 45 passed.
- Production frontend build: passed, 6,353 modules transformed.
- Optimized Tauri application: built.
- Windows MSI: built.
- Windows NSIS installer: built.
- Supported local native command `npm run tauri build -- --no-sign`: passed.

The normal signed build also compiled the app and produced both installers, then stopped at the expected updater signing gate because a public key is configured but no `TAURI_SIGNING_PRIVATE_KEY` is present. No signing key or forgotten password was searched for, printed, copied, or fabricated.

## Current limits

- Kimi K3 was not executed live. The installed Kimi CLI has no configured provider.
- Neyvia does not claim a 1M K3 context window for this account. That depends on provider and membership.
- OpenCode Go Kimi K3 is declared but not authenticated.
- A recovery mission is a review prompt, not proof that the recovered asset still works.
- The treasury is deliberately bounded and metadata-first. It does not yet offer opt-in semantic search across private content.
- Signed public release publication still requires the release signing environment.

## Main implementation files

- `src/grant_agent/model_portfolio.py`
- `src/grant_agent/legacy_asset_treasury.py`
- `src/grant_agent/model_routing.py`
- `src/grant_agent/opencode_go_models.py`
- `src/grant_agent/harness_registry.py`
- `src/grant_agent/external_cli_bridge.py`
- `src/grant_agent/web_backend.py`
- `src/grant_agent/runtimes/managed_cli.py`
- `web/src/neyvia/providerModelCatalog.js`
- `web/src/neyvia/HarnessesSurface.jsx`
- `web/src/neyvia/NeyviaCapabilityEvolutionPanel.jsx`
- `web/src/neyvia/neyviaCapabilityEvolutionModel.js`
- `web/src/neyvia/neyviaCapabilityEvolution.css`
- `web/src/neyvia/NeyviaShell.jsx`
- `vite.config.mjs`

## NAS handoff

The immutable work-in-progress target is:

`/volume1/Saclay/projects/syntelos/work-in-progress/20260730-014211-neyvia-model-portfolio-treasury`

This is a WIP snapshot only. It must not alter the public release pointer.
