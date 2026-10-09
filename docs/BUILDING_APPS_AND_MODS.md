# Building apps and mods

Neyvia owns provider sign-in and model routing, shared private memory, the LAYA client, Connected Language and app hosting. Apps own their feature logic and content. Use the [SDK ABI 1](../packages/neyvia-sdk/README.md), not copies of those services. [MODULES.md](../MODULES.md) and generated `modules/*/README.md` describe current repository APIs and dependencies.

## Reuse the shared services

Browser apps import `createNeyviaClient` from `/api/sdk/neyvia-sdk.js` on the authenticated Neyvia host. Python imports `NeyviaClient` from `neyvia_sdk` with an explicit local backend URL. Both use the same existing commands and tools. One Neyvia owner sign-in gives apps access to the owner's existing provider connections; provider-specific OAuth remains owned by Neyvia. No app stores provider secrets.

- `providers` and `providerStatus`: existing connected-provider inventory/auth.
- `modelCall`/`modelResult`: existing read-only connected sessions, with explicit provider, project folder, model and request ID.
- `remember`/`recall`: existing cue memory; the authenticated owner is supplied by the server.
- `verify`: existing `efficiency.laya_verify`, preserving confidence and escalation.
- `manual`/`cl`: the existing executable manual runtime and its permission/goal checks.
- `registerApp`/`applications`: the existing application registry. Marketplace source apps use its existing catalog projection and `/api/application/<id>/` host.

## Build an app

Start from `templates/neyvia-app`, or the existing `app_sdk.new` kit for its CL state/reducer conventions. Add `neyvia.app.json`, a static `webRoot/index.html`, an executable `.cl` manual and `host-contract.json`. Declare the SDK services you consume. Keep feature state such as a study feed in the app; shared cross-app memory goes through Neyvia.

Install the folder from Marketplace → Apps & mods, or call `marketplace.install(source='C:/your/app')` through CL. Git sources accept `https://github.com/<owner>/<repo>.git` and a branch, tag or commit. Downloads and expanded snapshots are capped at 200 MB. This path never installs dependencies or runs install hooks. Install starts disabled; enable after inspecting its manual and declared contracts.

Source versions are content addressed under the selected workspace's `.agent_control/source-marketplace`. Update reads the original source again, preserves older versions and current enable state, and refuses an identity change. Disabling removes the hosted app route and refuses SDK calls carrying that app's ID. This developer-source path is explicitly separate from signed/OCI packages; it does not invent attestations. Private GitHub repositories reuse an existing `gh` owner sign-in; credentials are neither stored in snapshots nor forwarded on archive redirects.

## Build a mod

Start from `templates/neyvia-module`. Choose a unique module ID and `neyvia.mod.<namespace>.<verb>` action. Declare its exact schema, real mutability, owned Python entrypoint, manual, contracts and dependencies. The trusted entrypoint receives `(args, root=selected_workspace)`. The runtime refuses paths outside that version's owned snapshot and protects active dependencies.

Install its folder in the same marketplace, enable it, then restart only the owned dev backend to discover new action schemas. Calls and disabling share a lifecycle lock; disabling waits for admitted calls before blocking new calls. The `hello-module` example implements a real personal greeting and `run hello-module.verify-greeting()` verifies its output.

## Verify and commit

Author checks/procedures in `manuals/cl/*.cl`, then run `scripts/cl_compile_manuals.py`. Run `scripts/generate_module_map.py` to update the registry, MODULES.md and per-module READMEs. The compiler's `--check` rejects missing actions, unowned/new source files, map/doc drift and missing entry-point manual links. Run the real app/mod journey; no new test files.

From `web`, run `npx vite build --configLoader runner`. Runner mode preserves the shared dependency junction; the web config uses a task-local cache. Commit reviewed source, manuals, generated artifacts and proof together. No push, merge or public-service restart.

## Scroll Study integration

`apps/scroll-study/www/neyvia-services.js` consumes the shared SDK. Connect reads the existing Codex provider status and shared memory. Remember progress writes through cue memory. Ask Neyvia starts an existing read-only provider session; Read answer reads that session. It contains no provider OAuth implementation, model HTTP client, LAYA runtime or second shared-memory database. Feed progress remains its existing IndexedDB feature state.

The installable integration lives in this worktree's Scroll Study source, derived from the existing local/GitHub project. The external `C:/Users/example/Projects/scroll-study` checkout is preserved; integrate the small `neyvia-services.js`/HTML/manifest changes there after this branch lands.

## Consolidated ownership

- Marketplace's duplicate JSON/fetch command wrapper now uses the SDK transport.
- Installed app/mod enable state and mod action admission use SourceMarketplace; the earlier separate repository-module toggle store was removed.
- Source app discovery uses `ModuleMarketplace.installed_catalog` → existing application-registry projection → existing application host. There is no second app host.
- The SDK delegates to existing provider sessions, cue memory, LAYA hooks, CL and app registration. Those owners were not rewritten or claimed to be duplicate implementations.

Publication note: local account paths and network identifiers in this document are neutral examples.
