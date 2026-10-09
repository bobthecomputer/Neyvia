# Build Roadmap

Current roadmap span:

- `Fluxio 1.0`
- the immediate `1.1` leverage release

Current source-of-truth docs:

- `docs/FLUXIO_1_0_RELEASE.md`
- `docs/FLUXIO_1_0_POLISH_PLAN.md`
- `docs/CHATGPT_TERMINOLOGY_THEO_GAP.md`

## Fixed Next Steps

1. Reliability contract and launch safety
   - close launch and restart reliability gaps
   - treat `npm run verify:desktop` as the canonical desktop validation command
   - keep Hermes and `uv` as hard blockers
2. Human-quality workbench and personalization
   - run the human-feel audit
   - resolve the ranked fix list before adding new surface area
   - make `Beginner`, `Builder`, and `Advanced` feel materially different
3. Skill Studio completion
   - finish create, import, edit, test, enable, disable, archive, promote, and reuse
   - back visible actions with persisted library state
4. Service Management completion
   - finish the shared detect, install, verify, repair, and manage loop
   - keep local services, MCP/tool servers, runtimes, and bridges distinct
5. Workflow Studio and agency hardening
   - keep workflow scope narrow: save-run, replay, and reviewed recipe composition only
   - harden continue, ask, replan, and context-preservation behavior
6. `1.0` validation cycle
   - validate on Windows desktop + WSL2 only
   - require proof capture plus real OpenClaw and Hermes missions
7. `1.1` leverage release
   - add reviewed workflow packs, stronger skill reuse, service drift detection, and trust scoring
   - do not widen into cloud sync, inbox or thread products, container abstractions, or a heavyweight workflow builder

## Release Gates

Keep these gates for desktop release readiness:

- `python -m pytest tests -q`
- `npm run frontend:build`
- `npm run tauri build -- --debug`
- `npm run verify:desktop`
