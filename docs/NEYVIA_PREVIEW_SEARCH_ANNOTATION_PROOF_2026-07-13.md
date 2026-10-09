# Neyvia preview, visual search, and annotation proof

Date: 2026-07-13

## Outcome

Neyvia now exposes preview review and UI inspiration as first-class Agent Live tools instead of a separate browser workspace. The tools can open before a mission exists, so they are usable from the main composer on a new workspace.

## Implemented

- `web.image_search`: structured image search using configured SearXNG first and maintained DDGS as the local fallback.
- `ui.inspiration.search`: query enrichment for interface surface, platform, and visual style, returning a visual board with source links.
- `preview.screenshot`: defaults to `domcontentloaded` instead of `networkidle`, avoiding long waits on polling applications.
- `preview.annotate`: captures the page, exact crop, annotated image, and a W3C-shaped JSON receipt with SHA-256 hashes.
- Agent Live review controls: drag a rectangle over the embedded preview, write a comment, and send the real evidence into the agent context.
- Desktop bridge: Tauri now exposes native tool catalog and native tool execution commands.
- Fresh-workspace tool launch: UI inspiration and preview review open without requiring an existing mission or thread message.

## Research basis

- SearXNG search API: https://docs.searxng.org/dev/search_api.html
- DDGS maintained search library: https://github.com/deedy5/ddgs
- Hermes DDGS research skill: https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/duckduckgo-search/SKILL.md
- Playwright screenshots and clipping: https://playwright.dev/docs/next/screenshots
- W3C Web Annotation Data Model: https://www.w3.org/TR/annotation-model/
- Annotorious rectangle and image annotation model reviewed as an alternative: https://annotorious.dev/api-reference/shape/

Annotorious was not added because the current requirement is bounded rectangle feedback with proof. It becomes a useful next option if Neyvia needs polygons, editable handles, or collaborative annotations.

## Verified behavior

- 14 focused Python tests passed.
- Frontend production build passed with 6,270 transformed modules.
- Rust `cargo check` passed.
- Windows debug MSI and NSIS installer builds passed.
- User-like Playwright flow passed:
  - authenticated isolated Neyvia session
  - UI inspiration opened from the composer plus menu
  - 12 visual result cards rendered from DDGS
  - native search HTTP response completed in 476 ms during the proof run
  - preview review opened from the plus menu
  - pointer drag produced `xywh=percent:18,22,37,26`
  - comment and annotated region were sent
- Native annotation proof produced `preview.png`, `annotated.png`, `region.png`, and `annotation.json`.

## Build hashes

- MSI: `6fce0b53b5ce83a1a5c71dc20850176c526f5b7435e19efcc6fe892678c14b65`
- NSIS: `42fcee4e02857b21fc8c0874735645897e004210b1463a4c6291c646395b695b`

## Known limitation

The original proof used a fresh Playwright process per capture. Neyvia now uses a supervised persistent worker for desktop screenshot and annotation calls while keeping a fresh isolated browser context per request. See `NEYVIA_NATIVE_TOOL_PERFORMANCE_2026-07-13.md` for measurements and recovery behavior.
