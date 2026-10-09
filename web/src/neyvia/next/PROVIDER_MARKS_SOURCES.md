# Provider mark sources

Vector paths for `ProviderMark` (see `providerMarksData.js`). All marks are inline SVG paths; no
raster or data URI is embedded anywhere. The licences below cover the vector files. The logos
themselves remain trademarks of their owners and are used here only to identify the product.

Packages pinned when the marks were fetched (2026-09-29):

| Package | Version | Licence | Used for |
|---|---|---|---|
| `simple-icons` | 16.33.0 | CC0-1.0 | single-colour marks and every mono variant of a multi-colour mark |
| `@lobehub/icons-static-svg` | 1.95.1 | MIT | AI-provider marks that simple-icons lacks or has old (Hermes, OpenClaw, Gemini colour, Grok, MiniMax) |
| `@iconify-json/logos` (gilbarbara/logos) | 1.2.15 | CC0-1.0 | flat multi-colour marks (Gmail, Drive, Calendar, Slack, Figma) |
| `lucide-react` | 0.564.0 | ISC | generic `browser` globe (already an app dependency) |

## Per mark

Status: **fetched** = path data copied from the source file, **drawn** = made here, **derived** =
own artwork traced from an asset in this repo.

| id | Status | Source file | Licence | Notes |
|---|---|---|---|---|
| `claude` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/claude.svg | CC0-1.0 | Claude spark, terracotta `#D97757` |
| `claude-code` | fetched | same as `claude` | CC0-1.0 | Claude Code uses the Claude spark (product decision), so the path is shared |
| `codex` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/openai.svg | CC0-1.0 | OpenAI knot, theme ink (near-white on dark, near-black on light) |
| `opencode` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/opencode.svg | CC0-1.0 | Frame mark, theme ink |
| `neyvia` | **in-house (generated)** | `scripts/brand/neyvia_sun_mark.py` | Neyvia | Own mark, see below |
| `hermes` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@latest/icons/nousresearch.svg | MIT | Nous Research mark (an illustration, so it reads as a small figure at 12 to 16px). simple-icons' `hermes` is a different brand and was not used |
| `openclaw` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@latest/icons/openclaw-color.svg | MIT | Mono variant from `openclaw.svg` (eyes knocked out) |
| `cursor` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/cursor.svg | CC0-1.0 | Theme ink |
| `gemini` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@latest/icons/gemini-color.svg | MIT | Blue star with three gradient overlays; mono reuses the silhouette |
| `grok` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@latest/icons/grok.svg | MIT | Theme ink |
| `deepseek` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/deepseek.svg | CC0-1.0 | Brand blue `#4D6BFE` taken from LobeHub `deepseek-color.svg` |
| `minimax` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@latest/icons/minimax-color.svg | MIT | Pink to orange gradient |
| `kimi` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.1/icons/kimi-color.svg | MIT | Moonshot's Kimi mark (also `kimi-code`, `moonshot`). The K follows the theme ink; the dot keeps the brand blue `#1783FF` |
| `openrouter` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.1/icons/openrouter.svg | MIT | Routing loop, theme ink. simple-icons `openrouter` (CC0) is the same idea drawn as two arrows; the LobeHub path matches the current wordmark icon |
| `glm` | fetched | https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.1/icons/zai.svg | MIT | Z.ai's Z, the brand the GLM models ship under (aliases `zai`, `z-ai`, `zhipu`). Theme ink |
| `gptme` | fetched | https://raw.githubusercontent.com/gptme/gptme/master/media/icon-mono.svg | MIT (gptme repository `LICENSE`) | The project's own mono icon (helmet with a face cut-out). Its circles were rewritten as arc paths so the whole mark is `<path>`s; geometry is unchanged |
| `pi` | **drawn** | Lucide style, not copied | n/a | A stroked pi sign for the Pi coding agent. No official vector could be obtained (LobeHub's `pi` is Inflection's Pi, a different product) |
| `prime-agent` | **drawn** | Lucide style, not copied | n/a | Hexagon with a P, for Prime Agent. No official vector could be obtained |
| `rook` | **drawn** | Lucide style, not copied | n/a | Chess-rook outline for Rook. No official vector could be obtained |
| `wallbreaker` | **drawn** | Lucide style, not copied | n/a | A brick wall with a crack, for Wallbreaker. No official vector could be obtained |
| `github` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/github.svg | CC0-1.0 | Theme ink |
| `gmail` | fetched | https://api.iconify.design/logos/google-gmail-2020.svg | CC0-1.0 | Four-colour 2020 envelope. Mono from simple-icons `gmail` |
| `google-drive` | fetched | https://api.iconify.design/logos/google-drive-2020.svg | CC0-1.0 | 2020 colour triangle. Mono from simple-icons `googledrive` |
| `google-calendar` | fetched | https://api.iconify.design/logos/google-calendar-2020.svg | CC0-1.0 | 2020 colour calendar. Mono from simple-icons `googlecalendar` |
| `slack` | fetched | https://api.iconify.design/logos/slack-icon.svg | CC0-1.0 | Four-colour hash. Mono from simple-icons `slack` |
| `linear` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/linear.svg | CC0-1.0 | Brand indigo `#5E6AD2` |
| `notion` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/notion.svg | CC0-1.0 | Theme ink; the N is a cut-out so the background shows through |
| `figma` | fetched | https://api.iconify.design/logos/figma.svg | CC0-1.0 | Five-colour mark. Mono outline from simple-icons `figma` |
| `vercel` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/vercel.svg | CC0-1.0 | Theme ink |
| `mcp` | fetched | https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/modelcontextprotocol.svg | CC0-1.0 | Theme ink |
| `browser` | fetched | https://github.com/lucide-icons/lucide (`globe`) | ISC | Circle converted to a path; stroke 2, inherits `currentColor` |
| `terminal` | **drawn** | Lucide style, not copied | n/a | Rounded frame, larger chevron and cursor than Lucide's `square-terminal` so the prompt survives at 12px |
| fallback | **drawn** | n/a | n/a | First letter in a rounded square, neutral `--ny-*` tokens (in `providerMarkModel.js` and `providerMark.css`) |

### Alternates (not required, one id away)

| id | Source file | Licence | Why it exists |
|---|---|---|---|
| `openai` | simple-icons `openai.svg` | CC0-1.0 | Same knot as `codex`, for model-provider rows |
| `codex-app` | LobeHub `codex.svg` | MIT | The Codex product mark (cloud with a terminal prompt), in case `codex` should use the product logo rather than the OpenAI knot |
| `claude-code-clawd` | LobeHub `claudecode-color.svg` | MIT | The Claude Code pixel mascot, in case `claude-code` should be distinguishable from `claude` in a mixed list |

## Approximated or drawn

- **`neyvia`** is Neyvia's own sun mark: a broad tree against a banded southern sunset. It is
  generated, not traced: `scripts/brand/neyvia_sun_mark.py` writes `neyviaSunMarkData.js` and the
  standalone SVGs in `docs/brand/`, so the in-app mark and the app icons share one source. Colour
  mode draws the banded disc, a radial glow and the tree; mono mode draws the tree alone.
- **`terminal`**, **`pi`**, **`prime-agent`**, **`rook`** and **`wallbreaker`** are drawn in the Lucide style (stroke 2, round joins) rather than copied. Replace the last four with the official marks if their owners publish vectors.
- No other mark is approximated. Every other mark is the source path as published.

## Choices worth knowing

- Gmail, Drive and Calendar use the 2020 flat marks. `@iconify-json/logos` also carries a newer
  gradient-and-mask generation (`google-gmail`, `google-drive`, `google-calendar`), but those use
  filters and masks that render poorly at 12 to 20px, so they were not used.
- `mono` on a multi-colour mark uses the simple-icons silhouette, because the colour art separates
  its parts by colour alone (Figma's five pieces touch each other).
- Black brand marks are stored as `ink: true` and drawn in `currentColor` through
  `.ny-pmark--ink`, which reads `--ny-pmark-ink` from the nearest theme scope (`data-theme`,
  `data-neyvia-appearance`), see `providerMark.css`.

## Adding or changing a mark

1. Fetch the SVG from a source above and note the URL and licence in this file and in the header
   of `providerMarksData.js`.
2. Add an entry to `providerMarksData.js` with `d` strings copied as they are and a square
   `viewBox` centred on the mark's ink (bounding box centre) so the longest side fills roughly 82
   to 92% of the box. Dense solid marks go toward the low end.
3. Run `node web/src/neyvia/next/build-provider-marks-preview.mjs`, open
   `provider-marks-preview.html`, tick "Show 1:1 boxes" and check the mark at 12, 16, 20, 28 and
   48px on both themes, in colour and mono.
4. Run `node --test tests/neyvia_provider_marks.test.mjs`.
