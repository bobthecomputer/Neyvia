# CL examples: six real layers, today vs CL

Each `*.cl` file holds one layer at L0, L1 and L2, followed by a runtime block (`K S E do R D I`). Every layer comes from the real code and manuals, and every runtime block comes from real output:

| File | Source of the declarations | Source of the runtime block |
|---|---|---|
| `notes.cl` | `manuals/notes.manual.json`, `neyvia_notes_tools.py` | a run of `list_notes` and `write_note` (append with CAS) in a scratch folder, shown as the default "Neyvia Notes" |
| `files.cl` | `manuals/files.manual.json`, `neyvia_files_tools.py` | `files.list` of `nx-cl/manuals`, plus `files.move` in a scratch workspace shown as `C:/ws` |
| `window.cl` | `neyvia_cua.py`, `neyvia_cua_mcp.py`, `computer-use.manual.json` | the GPT-6 Luna T16 proof run (`scripts/evidence/T16-luna.json`: inspect, type, verify, click, inspect) |
| `web.cl` | `neyvia_perception.py`, `perception_browser.py`, perception manual (browser chapter) | the T18 web-text run (`scripts/evidence/T18-runs/web-text-…/calls.jsonl`) |
| `chart.cl` | `perception_visual.py` (`VISUAL_SCHEMA`), perception manual (image chapter) | the T18 chart extraction (`scripts/evidence/T18.json`) |
| `codex-run.cl` | `connected_sessions/plan.py`, `neyvia_awareness.py` | the CL track's own plan, built with the real `plan_op` and `apply_op` functions; the `K` lines come from real sessions |

`today/` holds the same content in today's model-facing format: the rendered manual chapter (`neyvia_manuals.render`), the tool schemas, and the exact tool calls and results.

## Token comparison

o200k counts are exact (`tiktoken` `o200k_base`). Reproduce them with `python docs/standard/examples/measure.py`.

| layer | today manual + schemas | CL L0–L2 (L0–L1) | today runtime | CL runtime | today total | CL total (of which new K/Q/M/V) | saved | Claude approx. today → CL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| notes | 1446 | 870 (498) | 414 | 264 | 1860 | 1134 (106) | 39% | 2184 → 1257 |
| files | 1230 | 864 (570) | 2097 | 859 | 3327 | 1723 (76) | 48% | 3473 → 1606 |
| window (T16) | 1615 | 875 (630) | 1109 | 490 | 2724 | 1365 (80) | 50% | 3141 → 1466 |
| web (T18) | 983 | 505 (383) | 3973 | 224 | 4956 | 729 (56) | 85% | 4513 → 765 |
| chart (T18) | 866 | 452 (311) | 1122 | 417 | 1988 | 869 (65) | 56% | 2203 → 860 |
| codex run plan | 340 | 477 (326) | 572 | 326 | 912 | 803 (228) | 12% | 1049 → 869 |
| **total** | **6480** | **4043 (2718)** | **9287** | **2580** | **15767** | **6623 (611)** | **58%** | 16563 → 6823 |

How to read the table:

- **Context needed to start acting.** Today an agent loads the full manual chapter and the tool schemas: 6480 tokens. CL L0–L1 is 2718 tokens, **58% less**, and every action in it is checked and impact-aware. L2 (procedures, judgement points, pitfalls) loads only when the task reaches it. The one-time primer costs 1401 tokens and is shared by every layer. The L0 index for all six layers is 167 tokens.
- **Runtime.** CL is 72% smaller here: 9287 → 2580. Most of the gain is in the observations:
  - Today the web page arrives four times over, as `text`, `elements`, `tables` and `accessibility`, and after each action the full observation is resent along with a JSON Patch.
  - Today's T16 result carries both `tree_markdown` and `elements`, and the token must be re-read before every action.
  - In CL there is one tree, element handles (`@1`) that re-bind automatically, and one-line `D` diffs.
- **CL carries more information.** The CL column includes 611 tokens of awareness that today's format does not have at all: `K` (who else works and what they claim), `Q`, `M` and `V`. Every action also has `I` lines (writes, dependents, undo, approval) and automatic checks. The codex-run row saves little because CL adds the work board and routing, and the plan itself is still smaller.
- **Notes saves least (39%).** Its manual is short already, and its glosses carry real constraints: CAS stamps, tag rules and scan bounds. Its L0–L1 still saves 66% (1446 → 498).
- **The verify round-trips disappear.** In the T16 Luna run, one append plus one click cost 12 MCP calls and 496,959 input tokens (448,256 of them cached), because every step re-read the window and verification was a separate call. In CL the same work is 2 `do` lines. Each returns its own check results (`+value-is`, `+shows`) and a `D` diff, so no separate verify call or re-read is needed.

## Method and caveats

- **Today's JSON was counted compact, which favors today.** The `today/*.json` files were re-serialized without spaces before counting, so today's numbers are lower bounds. The T16 and T18 results are counted exactly as the model received them as text; for T16 that means only the MCP `content` text, not `structured_content` (which the run also delivered).
- **Comments are not counted. Glosses are.** Comment lines (`-- …`) in the `.cl` files hold provenance and are excluded. Glosses (` -- …` after content) are content and are counted.
- **The Claude column is an estimate.** It is `ceil(UTF-8 bytes / 3.5)` and must not be quoted as a Claude token count. No Claude tokenizer is available locally.
- **The examples use closed objects, as §4 recommends.** An exact round trip of today's open Neyvia schemas would add ` ..` to each signature, about one token each.
- **Formatting-only changes in the runtime blocks.** Scratch paths were renamed for privacy and stability, and Windows `\` became `/` in CL, as §2.9 requires. No values were changed.
- **Two receipt fields in `window.cl` are composed from separate calls.** The `win.type_text` receipt's `2.6s` is the real `verify_state` time (2620 ms), which under CL is part of the action. The `win.click` receipt's `+shows` reflects the Luna run's next inspect, which read the "Applied: … Luna verified …" text. Under CL that check would run automatically.
