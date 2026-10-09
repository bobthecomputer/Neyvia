# AI Agent Usability Assessment

## Current Read

Fluxio is materially closer to a usable supervised-agent product than it was before the current web rebase, but the agent feature is still only partially trustworthy as a system. The main supervision shell is now strong enough to understand runs, approvals, proof, and restart continuity, yet the provider layer, plan-mode defaults, and skill packaging still drift in ways that make the product feel more complete than it actually is.

## Findings

- `P0: provider truth is still incomplete.`
  The current orchestration stack only treats `codex` and `claudeAgent` as first-class providers, while MiniMax is absent from contracts, server settings, registries, and web registries. That means Fluxio cannot honestly promise provider portability yet; MiniMax currently belongs in the custom Codex `model_provider` path, not the first-class picker.

- `P0: custom-provider capability truth was unsafe.`
  Before this pass, custom Codex-provider model slugs inherited generic Codex reasoning and fast-mode controls. That is not honest for custom profiles such as MiniMax, which means the UI could imply controls the runtime does not actually support. Unknown custom models must stay capability-light until Fluxio has verified metadata for them.

- `P1: exposed OpenAI model defaults drifted away from the current docs.`
  The user-facing and server-facing defaults need to converge on GPT-5.6 Sol,
  with GPT-5.6 Luna used only where the route deliberately favors efficiency.
  Older model IDs remain compatibility inputs, not active defaults. If the
  picker, bridge, and provider registry disagree here, operators stop trusting
  the thread state and model routing story.

- `P1: long-run continuity is regression-tested, but not yet soak-tested.`
  The delegated-runtime path is in much better shape than before. The repo already proves approval wait across restart, delegated runtime activity across restart, truthful time-budget status, pause reason, and current runtime lane in `tests/test_mission_control.py`, `tests/test_release_acceptance.py`, and `tests/test_runtime_supervisor.py`, and the runtime worker race around approval-file cleanup has been fixed. What is still missing is a longer real-world soak path outside mocked acceptance coverage.

- `P1: skill packaging is split across two systems.`
  Fluxio has product-level skills in `config/skills.json`, while Codex-native skills live as `SKILL.md` folders under the Codex home. That split is workable, but only if important operational knowledge is mirrored into both surfaces. Before this pass, provider-conformance knowledge existed in neither.

- `P1: runtime/provider switching still needs clearer operator proof.`
  Hermes and OpenClaw continuity is visible in the workbench, but the provider/config layer still lacks an equally strong proof surface for custom model-provider routing, degraded provider availability, or why a given thread is pinned to a certain provider/model family.

- `P2: acceptance coverage is still too narrow for provider setup quality.`
  There is good restart and supervision coverage, but not enough end-to-end coverage for doc-conformant provider setup paths such as custom Codex `model_provider` usage, MiniMax-specific configuration warnings, or plan-first default behavior through thread creation and replay.

## Polish Priorities

- Finish the provider truth model before adding more providers to the picker.
- Keep plan mode as the boot default and only switch to build mode once there is real execution evidence.
- Keep unknown custom models capability-light until Fluxio can prove their exact controls.
- Add a provider/setup proof surface that explains auth state, custom provider routing, model family, and why the current configuration is safe or blocked.
- Unify important operational skills so the same guidance exists in Codex `SKILL.md` form and Fluxio’s product skill catalog.
- Add acceptance tests for custom Codex model-provider paths, MiniMax-specific setup guidance, and plan-first boot flows.

## Confidence

This assessment is grounded directly in the current repo state: the Fluxio backend planning policy, the current provider contracts, Codex adapter/app-server integration, server settings, web draft defaults, and the current skill catalog. The MiniMax recommendation is based on current official MiniMax docs rather than local implementation, because the repo does not yet contain a first-class MiniMax provider.
