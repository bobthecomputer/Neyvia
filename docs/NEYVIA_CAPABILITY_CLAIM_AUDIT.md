# Neyvia capability claim audit

**Date:** 2026-07-23  
**Repo:** `C:\Users\example\projects\vibe-coding-platform`  
**Method:** Claimed surface (UI copy, catalogs, docs) vs backend implementation vs frontend wiring. Inventory baseline: `docs/NEYVIA_TOOL_ICON_ANIMATION_COVERAGE.md` (icon/animation inventory; **partially stale** on Chat Tools count — see §3). Capability contract: `docs/NEYVIA_CAPABILITY_BACKEND.md`, packs: `config/capability_packs.json`, suite lock: `config/tool_suite_lock.json`, extension bar: `docs/NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md`.

**Verdict (one line):** Neyvia’s *architecture* for capabilities is real and often honest; the *product claim* of a broad, operator-usable tool suite is not. Backend depth is concentrated in a few managed document tools + progressive/MCP/CU plumbing; the shell mostly catalogs stubs and falls through without execute bindings.

> **Implementation update — 2026-07-26:** The scorecards below preserve the
> original 2026-07-23 audit baseline. The following high-priority findings are
> now closed on `codex/neyvia-realization` and must not be reimplemented as
> parallel systems:
>
> - `neyvia:*` capability actions no longer fall through silently to Agent.
> - Agent-ready managed tools expose typed inputs and execute through the real
>   suite operation path with receipts and honest backend failure states.
> - Lab exposes bounded structured Computer Use verification with per-run
>   approval, live/replay truth, compact metrics, exact flow failures, and saved
>   twins.
> - Security runtime audit, scope validation, purple-team planning, and
>   action evaluation are first-class progressive tools and a fail-closed Lab
>   workbench; this screen never launches a probe.
> - Specialist roster assignment creates a real durable requested constellation
>   node and hands the operator into Orchestration.
> - The MCP broker now has a first-class Lab surface for configured servers,
>   deferred search/describe, explicit one-run approval, and retained call
>   receipts. Production no longer inherits the standalone demo MCP fallback.
>
> The authored-tool browser/runner gap is now closed in Lab: it lists and
> searches only saved manifests, describes real adapter availability, generates
> inputs from each schema, requires explicit per-run and per-permission approval,
> and renders the backend execution receipt. An empty workspace stays honestly
> empty. The broad planned/blocked catalog must still remain visually subordinate
> to execution-ready tools.

**Paul’s differentiation bar:** wrapping an open-source tool only counts if the Neyvia path feels like a different, better-integrated product. Rated informally **/20** below (Neyvia integration vs raw upstream). Target: Neyvia score **higher** than “just shelling the second thing.”

---

## 0. How to read this audit

| Column | Meaning |
| --- | --- |
| **Claimed** | What UI labels, docs, or catalogs imply an operator can do |
| **Backend** | What Python/Capability OS actually implements (handlers, progressive tools, commands) |
| **Frontend wiring** | Whether the React shell calls those APIs and renders truthful states |
| **Maturity** | `verified` · `partial` · `stub` · `planned` · `missing` |

Honesty vocabulary from the capability backend (do not confuse these):

- `available: true` ≠ executable  
- `supportsExecution: true` requires a dedicated allowlisted handler  
- `delegation_required` / `neyvia.agent` = plan/handoff, not a domain tool  
- Chat tiles labeled **Not connected** are currently the most honest UI signal

---

## 1. Headline scoreboard

| Layer | Catalog / surface size | Backend reality | Frontend wiring | Overall |
| --- | ---: | --- | --- | --- |
| Capability packs | **15 packs / 61 capabilities** (`config/capability_packs.json`) | Catalog + plan/search/describe real; **~2** paths with strong direct handlers historically cited; most → `neyvia.agent` or missing adapter | Library **search/inspect** partial; **execute/plan approve not bound** from Chat tiles | Catalog-strong, run-weak |
| Managed suite | **42** tools (`config/tool_suite_lock.json`) | States: **6 installed, 3 verified, 31 planned, 2 blocked**; typed ops concentrated on Poppler/Tesseract/Pandoc/LibreOffice | Library shows **42** suite tiles; all click → `not_connected` | Catalog-strong, agent-ready few |
| Progressive Capability OS | **~31** tools (`capability_service.register_with_progressive_surface`) | Implemented for models/MCP | Chat lists extras as stubs; no operator execute UX | Backend-first |
| Native tools | **~20** (`native_tools.py`) | Implemented in native runtime | Chat maps loosely to search/capture stubs | Partial |
| Compact UI / CU (`ui.*`) | **8** tools (`ui_tools.py`) | Real Playwright/a11y graph path + verifier | Catalog stubs only; Lab does not drive `ui.do` | Backend-strong, UI-missing |
| MCP broker | **4** + dynamic servers (`mcp_broker.py`) | Search/describe/call surface | Chat `mcp.*` stubs | Partial |
| Neyvia MCP server | **~28** + re-exports (`neyvia_mcp.py`) | Task starters, autonomy, conversation, orchestration | Not a first-class operator catalog | Backend-first |
| Adapters | Discoverable set in `capability_adapters.py` | **Executable handlers:** `pdf.pdftotext`, `ocr.tesseract`, `document.pandoc`, `document.libreoffice`, `device.android` (+ builtins). Others discovered **without** handlers | Lab reads snapshot counts; no per-adapter console | Uneven |
| Authored tools | Dynamic under `.agent_control/capability_os/authored_tools/` | Factory + commands exist | No Library browser for authored tools | Missing UI |
| Chat tools panel | **~105** catalog tiles (`neyviaToolVisuals.js` → `NEYVIA_CHAT_TOOL_CATALOG`) | N/A (UI) | Nearly all emit `neyvia:tool:<id>` with `status: "not_connected"`; **shell has no dedicated `neyvia:tool:*` handler** (falls through to agent surface) | Expanded stubs |
| Toolbar | **9** slots (`neyviaShellPreferences.js`) | N/A | Attach partial; others open panels/stubs | Stub chrome |
| Notebook | Surface + 3 drawers | Snapshot/contract fetch | Sections are static; plan action unbound | Partial shell |
| Lab | Stage + adapter snapshot | `get_capability_os_snapshot_command` | Viewport + lineage list; Image Playground nav | Partial shell |
| Orchestration / multi-agent | Constellation fabric + mission control | Conversation plan/transition/synthesis commands + durable mission approvals | Orchestration mode **more wired** than Chat tools; specialist roster still stub | Mixed strength |
| Marketplace / mesh | Module schema + staging plans | Staging-only; activation/mesh **planned** (`NEYVIA_CAPABILITY_BACKEND.md`) | Not productized | Planned |

**Master-plan maturity (backend, 2026-07-23):** from `docs/NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md` — Direct bounded execution **2**; Detected executable only **8**; Generic `neyvia.agent` handoff **44**; Missing required runtime **7**. Treat this as the authoritative *capability execution* claim, not the UI tile count.

---

## 2. Layer-by-layer audit

### 2.1 Capability packs (`config/capability_packs.json`)

**Claimed:** Profession/domain packs covering research, education, writing, OCR/PDF/LaTeX, office, communication, software, AI/ML, security, media, 3D/games, maker, fashion, device lab, niche — each with verbs, adapters, permissions, verifiers.

**Backend:**

- Loaded/searched/planned via `capability_catalog.py` / `capability_service.py`.
- UI contract + run lifecycle states are real (`docs/NEYVIA_CAPABILITY_BACKEND.md`).
- Adapter field is often `neyvia.agent` (delegation), not a typed suite operation.
- Nine capabilities are explicitly native reasoning paths in `tool_suite_lock.json` → `nativeCapabilities` (campaign, message draft, tutorials, curriculum, repair guidance, image routing, culinary, custom-pack authoring, threat model). These are **orchestration/reasoning**, not “installed apps.”

**Frontend:**

- `NeyviaLibrarySurface` (`web/src/neyvia/NeyviaShellSurfaces.jsx`) calls `get_capability_ui_contract_command` + `search_capabilities_command`, shows cards + Inspect (`neyvia:library:describe`).
- Capability plan sheet loads **contract only**, not `plan_capability_run_command` for a selected capability; Approve emits `neyvia:plan:approve-requested` without a proven shell binding.
- Chat Tools now *lists* many capability/progressive ids as inventory tiles, but still marks them not connected.

| Claim class | Reality |
| --- | --- |
| “61 capabilities available” | **Catalog available** — yes. **Runnable as domain tools** — mostly no. |
| “Library is the pack browser” | **Partial** — discover/inspect only. |
| “Plan → approve → execute → artifacts” | Backend contract exists; **operator loop not closed** in shell. |

---

### 2.2 Managed tool suite (`config/tool_suite_lock.json`)

**Claimed:** Locked inventory of upstream suites under `D:\Neyvia\...` with states, health, operations.

**Backend truth (lock file, 2026-07-23):**

| State | Count | Examples |
| --- | ---: | --- |
| `installed` | 6 | poppler, latex-suite, playwright, git, docker-engine, ffmpeg |
| `verified` | 3 | tesseract, libreoffice, pandoc |
| `planned` | 31 | languagetool, argos, duckdb, blender, ghidra, … |
| `blocked` | 2 | seamly, mobile-security |

Typed `operations` in lock: **12** total across Poppler (1), Tesseract (5), LibreOffice (3), Pandoc (3). Progressive path: `tool.suite.search` → `describe` → `execute` (`capability_service` + `tool_manifest_registry.py`). `agentReady` requires `verified` + healthy install + operations.

**Frontend:**

- Library renders `NEYVIA_MANAGED_SUITE_CATALOG` (42) with dedicated visuals from `neyviaToolVisualsInventory.js`.
- Clicks stay `not_connected` — **does not** call `tool.suite.execute` or show lock `state`/`agentReady` badges from live registry.

| Claim | Reality |
| --- | --- |
| “42 managed tools” | **Catalog claim true**; **agent-ready claim false** for most. |
| “Pandoc/LibreOffice reference integrations” | **Backend true** (see §4); **UI does not expose them as working tools**. |

---

### 2.3 Progressive Capability OS tools

**Claimed (docs):** Deferred-schema progressive tools for capability, suite, authored tools, CU twin/verify, artifacts, model-tool intelligence.

**Backend:** Registered in `src/grant_agent/capability_service.py` (search/describe/plan/execute, pack validate/save, `tool.author.*`, `cu.twin.*`, `computer_use.verify`, `artifact.*`, `model.tools.*`).

**Frontend:** A subset appears in `NEYVIA_CHAT_PROGRESSIVE_EXTRA` inside Chat Tools — still stubs. Library uses only a few `*_command` endpoints. No progressive “describe → show schema → run” operator wizard.

---

### 2.4 Native tools (`src/grant_agent/native_tools.py`)

| Tool family | Backend | Frontend |
| --- | --- | --- |
| `workspace.search`, `context.*`, `orchestration.compile` | Present | Mostly invisible as tools |
| `web.search`, `web.fetch`, `web.image_search` | Present | Chat “Web Search” / “Web Capture” stubs |
| `preview.inspect/screenshot/annotate` | Present | Capture stub |
| `video.inspect/digest` | Present | Missing as UI tool |
| `nas.message.*`, `nas.file.send`, `nas.transfer` | Present | Missing |
| `codex.assets.*`, `skill.live.*` | Present | Skills surface separate (Fluxio), not Chat tool tile |

---

### 2.5 Computer use / compact UI (`ui_tools.py`, verifier, twin)

**Claimed:** Structured CU preferred over screenshot spam; verify change; optional Twin comparison lane; remote `browser_verify` dispatch (NAS fallback prohibited).

**Backend:** Strong relative to other layers.

- Tools: `ui.ls`, `ui.find`, `ui.get`, `ui.diff`, `ui.wait`, `ui.do`, `ui.see`, `ui.observe` (`src/grant_agent/ui_tools.py`).
- Primary gate: `verify_computer_use_change_command` / progressive `computer_use.verify` (`computer_use_verifier.py`, `cu_acceptance.py`).
- Twin: validate/save/run/dispatch commands (`computer_use_twin.py`).
- Docs record a **bounded** reuse speedup sample — not a 10× product claim (`NEYVIA_CAPABILITY_BACKEND.md`).

**Frontend:** Chat lists `ui.*` / `cu.twin.run` as stubs. Lab mentions twins in lineage if snapshot returns them. No operator CU console binding `ui.observe` → `ui.do` with live graph.

**Maturity:** Backend **partial→verified** for acceptance flows; product UI **missing**.

---

### 2.6 MCP

**Broker (`mcp_broker.py`):** `mcp.servers`, `mcp.search`, `mcp.describe`, `mcp.call` + demo stubs. Foreign servers from `.agent_control/mcp_broker.json` / `mcp_servers.json` are dynamic.

**Neyvia MCP (`neyvia_mcp.py`):** Durable starters (`neyvia.research.start`, `browser.start`, `computer.start`, `training.batch.start`), progressive search, autonomy grant/check/revoke, conversation fabric, `neyvia.orchestration.plan/graph`, plus re-exported `ui.*` / `mcp.*`.

**Claim gap:** Older matrix (`docs/NEYVIA_RUNTIME_CAPABILITY_MATRIX_2026-07-12.md`) said MCP was “linked / metadata gap.” Code now has a callable broker — **advance the claim to “broker present, operator UX missing, auth/approval receipts incomplete vs Codex-class apps.”** Do not claim “full MCP apps/connectors” yet.

---

### 2.7 Chat, Notebook, Lab, Library (shell surfaces)

Sources: `web/src/neyvia/NeyviaShellSurfaces.jsx`, `neyviaToolVisuals.js`, `neyviaShellPreferences.js`, `NeyviaShell.jsx` (`handleReferenceAction`).

| Surface | What it claims | What it does |
| --- | --- | --- |
| **Chat Tools** | ~105 tiles across categories; “never fake success” | Honest stub labels; **no execute**; shell ignores `neyvia:tool:*` (default opens agent) |
| **Toolbar** | Attach, Search, PDF, Data, Images, Canvas, Citations, Terminal, Diff | Navigation/chrome; not suite execute |
| **Library** | Capability packs + managed suite | Search/inspect packs; suite tiles stub; file type icons are **demo stubs** (`NEYVIA_LIBRARY_FILE_STUBS`) |
| **Notebook** | Documents/research/lessons with lineage | Contract + artifact count; TOC buttons static; drawers navigate |
| **Lab** | Shared stage for code/models/devices/3D/media | Snapshot counters; Image Playground button; no adapter control plane |
| **PDF / Scene / Translate / Grammar / Research / Roster panels** | Domain tool stages | Empty/stub stages; roster assigns with `not_connected` |
| **Plan sheet** | Approval gate | Shows UI contract; approve event unbound to `execute_capability_command` |
| **Sources** | Citations | Empty until provenance — honest |

**Critical wiring finding:** `NeyviaShellSurfaces.jsx` emits many `neyvia:*` actions, but `NeyviaShell.jsx` `handleReferenceAction` contains essentially **no** `neyvia:tool|library|plan|pdf|roster|scene` cases (only unrelated `neyvia:conversation-updated` events). Unhandled actions fall through to “open agent run.” Catalog expansion without handlers **increases claimed surface without increasing capability**.

---

### 2.8 Orchestration, specialists, approvals, proof

**Strengths (real):**

- Mission control approvals, pending lists, proof digests, lane handoffs (`mission_control.py`, Fluxio agent/workbench UI).
- Durable conversation constellation: `create_neyvia_orchestration_plan_command`, node lifecycle transitions, synthesis gate (`neyvia_conversations.py`; wired in `NeyviaProductModePanels.jsx`).
- Context ledger / NEYVIA/1 IR (`docs/NEYVIA_CONTEXT_ORCHESTRATION.md`, runtime matrix).
- Permission classes and high-risk approval gates in capability runtime.
- Hermes/OpenClaw continuity as supervised runtimes (product shell mature relative to capability tiles).

**Gaps:**

- Chat **Specialists** roster is cosmetic (`standby` / `not_connected`), not the constellation fabric.
- Capability-pack “multi-profession” ≠ multi-agent specialists with proof.
- Sub-agent composer path explicitly warns no launch until backend reports lane support (`composer:plus:subagent`).
- Synthesis requires completed nodes + evidence — good gate — but specialist Chat UX does not feed it.
- Marketplace activation, mesh, secret broker: **planned**, not claimable (`NEYVIA_CAPABILITY_BACKEND.md`).

---

## 3. Inventory doc drift note

`docs/NEYVIA_TOOL_ICON_ANIMATION_COVERAGE.md` remains useful for **backend enumeration** and for the historical “~9 chat stubs” gap. **Update these claims when citing it:**

| Inventory (earlier) | Current workspace |
| --- | --- |
| Chat Tools = 9 stubs | `NEYVIA_CHAT_TOOL_CATALOG.length` ≈ **105** (priority + 42 suite + progressive extras) |
| Per-tool icons missing | `neyviaToolVisuals.js` + `neyviaToolVisualsInventory.js` + `NeyviaToolVisuals.jsx` — dedicated/generic marks + animation classes |
| Managed suite UI missing | Library **renders** 42 suite tiles (still not connected) |

The inventory’s core thesis still holds: **backend callable surface ≫ operator-executable UI.**

---

## 4. Open-source wraps: thin vs differentiated (/20)

Scale: **0** = name only in JSON; **10** = thin CLI wrap; **15+** = Neyvia feels like a better product than raw upstream for the job. Paul’s bar: Neyvia must beat the raw tool.

| Upstream | Lock / adapter | Integration depth | Score /20 | Notes |
| --- | --- | --- | ---: | --- |
| **Pandoc** | `tool.pandoc` verified | Typed ops, sandbox, schema, receipts, lineage, proof docs | **16** | Reference Wave-1 integration (`NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md`) |
| **LibreOffice Portable** | `tool.libreoffice` verified | Isolated profiles, convert/render-pdf, round-trip checks, lineage | **16** | Same bar; still no Chat execute UX |
| **Poppler (`pdftotext`)** | `tool.poppler` installed | Bounded extract, page range, char limits, handler | **14** | Strong PDF path; UI PDF panel still stub |
| **Tesseract** | `tool.tesseract` verified | Multi-op OCR, workers, profiles, PDF via pdftoppm | **14** | Handler present; operator tile not live |
| **Playwright / structured UI** | `tool.playwright` installed; `ui.*` | Compact graph tools + verifier/twin — differentiation vs raw Playwright is real | **15** | Product UI for CU still missing |
| **Android ADB** | `device.android` handler | Allowlisted ops + explicit `approved: true` | **12** | Good safety shape; SDK often planned/unavailable |
| **Git / Docker / FFmpeg** | installed, **0 ops** in lock | Discovery / PATH; no typed suite operations | **4–6** | Thin or none — below Paul’s bar |
| **LaTeX suite** | installed, 0 ops | Adapter discoverable; **no** `_handler_for` for `latex.compiler` | **5** | Detected ≠ integrated |
| **Blender / Unity / Godot** | planned / discoverable | Metadata + optional bridges without execution clients | **3–5** | Names in catalog only |
| **LanguageTool / Argos / LibreTranslate** | planned | No ops | **2** | Chat “Grammar/Translate” tiles are aspirational |
| **Security suite (Trivy, Semgrep, ZAP, Ghidra)** | planned/blocked | None | **1–2** | Do not claim |
| **Fashion (Seamly)** | blocked | None | **0–1** | Explicitly blocked |
| **MCP foreign servers** | broker | Callable if configured; auth/approval UX incomplete | **8** | Better than metadata-only; not Codex Apps |
| **Generic `neyvia.agent`** | resident | Planning/handoff to scheduler | **7** (as orchestrator) / **3** (as “tool”) | Must not be sold as domain software |

**Bottom line:** Differentiation is **proven for Pandoc, LibreOffice, Poppler/Tesseract, and structured CU**. Everything else in the 42-tool lock is mostly **inventory + intent**. Catalog breadth without wrap depth fails Paul’s bar.

---

## 5. Multi-agent: strengths and gaps

### Strengths

1. **Supervision shell** — approvals, proof, lanes, restart continuity (Fluxio/`mission_control`) is a real product strength vs raw CLIs.  
2. **Constellation fabric** — plan → node lifecycle → synthesis gate with evidence (`neyvia_conversations.py` + Orchestration UI).  
3. **Progressive tool belt** — models can discover without stuffing thousands of schemas.  
4. **Permission/approval taxonomy** — capability runtime + Android mutation gates.  
5. **CU verification receipts** — flow success, latency, compact bytes, live vs replay labeling.

### Gaps

1. **Specialists in Chat ≠ constellation agents** — roster is decorative.  
2. **Capability packs are not specialist runtimes** — 44× `neyvia.agent` handoffs are planning intelligence, not domain executors.  
3. **Handoff proof** for capability execute → artifact lineage is backend-ready but not operator-closed.  
4. **Approvals** are strong for missions; weak/absent for Chat tool tiles and suite execute.  
5. **No unified “proof drawer”** for capability runs in Library/Lab matching mission proof maturity.

---

## 6. Claimed vs reality matrix (selected high-signal claims)

| Claim (UI/docs tone) | Backend | Frontend | Honest restatement |
| --- | --- | --- | --- |
| Broad profession capability packs | Catalog yes | Discover/inspect | “61 capability *definitions*; few domain *executors*” |
| Managed suite of 42 tools | Lock yes | Tiles yes, execute no | “42 locked intents; ≤ handful agent-ready” |
| PDF / OCR / Office as product tools | Handlers yes (PDF/OCR/Pandoc/LO) | Stub panels | “Backend can; Chat cannot yet” |
| Grammar / Translate tools | Planned only | Stub tiles | “UI placeholders” |
| 3D / Blender / CAD / Fashion | Mostly planned | Stub | “Not integrated” |
| Device lab (Android/Apple) | Android handler; Apple remote bridge missing | Stub | “Android path exists when SDK ready; Apple is remote-only planned” |
| Security red team pack | Agent/Python adapters declared | Stub | “Policy + planning; suite tools not agent-ready” |
| Computer use | Strong | Stub | “Verifier/twin backend; no CU console” |
| MCP platform | Broker + Neyvia server | Stub | “Model-facing MCP yes; operator catalog no” |
| Multi-agent specialists | Constellation + missions | Roster stub; Orchestration better | “Use Orchestration mode, not Chat roster” |
| Marketplace / personal mesh | Staging validators | Absent | “Foundation/planned” |
| 10× performance | Explicitly disallowed without receipts | N/A | Keep non-claim |

---

## 7. Efficiency / differentiation recommendations (prioritized)

### P0 — Stop false completeness; close the loop on winners

1. **Bind Chat/Library tiles to live registry state** (`agentReady`, `state`, `supportsExecution`) — never show 105 equal “tools.”  
2. **Implement `neyvia:tool:*` / plan / library describe handlers** in `NeyviaShell.jsx` that call `tool.suite.*` / `plan_capability_run_command` / `execute_capability_command` with approval.  
3. **Ship operator UX only for Wave-1 winners:** Pandoc, LibreOffice, Poppler, Tesseract — plan → preview → artifact → lineage. That is the differentiation proof.  
4. **Collapse or hide planned/blocked suite tools** behind an “Upcoming” filter so the product does not look like a wallpaper of stubs.

### P1 — Raise wrap depth before catalog width

5. Promote **Git / FFmpeg / Playwright** from installed-zero-ops to typed operations with receipts (same bar as Pandoc).  
6. Finish **LaTeX** handler or demote adapter claims.  
7. Wire **CU verifier** into Lab as a first-class proof surface (reuse mission proof patterns).  
8. Align Chat **Specialists** with constellation create/transition APIs or remove the roster claim.

### P2 — Multi-agent and MCP productization

9. One **approval + proof** path shared by capability runs and mission lanes.  
10. MCP broker: auth state + approval receipts before claiming apps/connectors (matrix gap #3).  
11. Authored-tool Library browser (`list_authored_tools_command`) — small surface, high leverage.  
12. Keep marketplace/mesh **out of marketing** until activation is real.

### P3 — Efficiency of engineering effort

13. Prefer **deepening 5 tools** over listing 42. Catalog growth without handlers is negative ROI (UI debt).  
14. Auto-generate suite tiles from `tool_suite_lock.json` **with live health**, delete hand-synced inventory drift.  
15. Treat `neyvia.agent` capabilities as **skills/prompts**, not tools, in the UI taxonomy.

---

## 8. Source index (absolute paths)

| Artifact | Path |
| --- | --- |
| This audit | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_CAPABILITY_CLAIM_AUDIT.md` |
| Icon/animation inventory | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_TOOL_ICON_ANIMATION_COVERAGE.md` |
| Capability backend contract | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_CAPABILITY_BACKEND.md` |
| Agent extension / wrap bar | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md` |
| Runtime capability matrix | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_RUNTIME_CAPABILITY_MATRIX_2026-07-12.md` |
| Context / NEYVIA/1 | `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_CONTEXT_ORCHESTRATION.md` |
| Packs | `C:\Users\example\projects\vibe-coding-platform\config\capability_packs.json` |
| Suite lock | `C:\Users\example\projects\vibe-coding-platform\config\tool_suite_lock.json` |
| Adapters / handlers | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\capability_adapters.py` |
| Capability facade | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\capability_service.py` |
| Tool manifests | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\tool_manifest_registry.py` |
| UI/CU tools | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\ui_tools.py` |
| Native tools | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\native_tools.py` |
| MCP | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\mcp_broker.py`, `neyvia_mcp.py` |
| Conversations / constellation | `C:\Users\example\projects\vibe-coding-platform\src\grant_agent\neyvia_conversations.py` |
| Shell surfaces | `C:\Users\example\projects\vibe-coding-platform\web\src\neyvia\NeyviaShellSurfaces.jsx` |
| Tool visuals / catalogs | `C:\Users\example\projects\vibe-coding-platform\web\src\neyvia\neyviaToolVisuals.js` |
| Action router | `C:\Users\example\projects\vibe-coding-platform\web\src\neyvia\NeyviaShell.jsx` (`handleReferenceAction`) |
| Orchestration UI | `C:\Users\example\projects\vibe-coding-platform\web\src\neyvia\NeyviaProductModePanels.jsx` |

---

## 9. Closing judgment

Neyvia’s capability system is **not vaporware**: packs, permissions, progressive schemas, managed Pandoc/LibreOffice/PDF/OCR paths, CU verification, and constellation orchestration are substantive engineering. It is also **not yet the product the catalogs suggest**. The dominant failure mode is **catalog inflation + unbound UI actions**, which makes the shell look complete while execute paths remain model/backend-only.

Until Wave-1 tools are first-class in Chat/Library with approvals and artifacts, and until planned suite rows are demoted visually, Neyvia will lose Paul’s differentiation test against raw Pandoc/LibreOffice/Playwright — ironically, those are the few places where Neyvia already *could* win.

### Ecosystem follow-up (2026-07-23, same evening)

Session tool panes + silent ecosystem rewrite landed as product-surface work (`docs/NEYVIA_ECOSYSTEM_INTEGRATION.md`). **Do not re-break honest `agentReady`:** Chat/Library badges and plan→approve still require backend suite lock / describe truth. Pane hosts and coaching packs must never paint stubs as executors.

*Generated for local academic audit. Not committed by request.*

Publication note: local account paths and network identifiers in this document are neutral examples.
