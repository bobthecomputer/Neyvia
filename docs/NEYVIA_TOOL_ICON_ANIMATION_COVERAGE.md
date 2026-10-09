# Neyvia tool / icon / animation coverage inventory

**Date:** 2026-07-23  
**Scope:** Every callable tool, capability, progressive entry point, MCP tool, authored-tool surface, adapter operation, and computer-use action the Neyvia backend can expose — compared to what the Fluxio/Neyvia frontend currently surfaces.  
**Verdict:** Paul is correct. The backend exposes **far more** callable surface than the UI. The shell mostly shows **~9 chat-tool stubs**, **~9 toolbar slots**, and a **dynamic Library search grid** without per-tool icons or dedicated animations.

Status vocabulary used below:

| Field | Values |
| --- | --- |
| **Frontend UI** | `missing` · `stub` · `partial` · `present` |
| **Icon** | `missing` · `generic` · `dedicated` |
| **Animation** | `none` · `shared` · `dedicated` |

**Shared animation** means shell motion from `web/src/neyvia/neyviaMotion.css` / `neyviaShell.css` (surface enter, overlay, live pulse) — not a tool-specific glyph animation.  
**Generic icon** means Lucide defaults (`Sparkles`, `FileText`, `Search`, `Paperclip`, `Palette`, etc.), not a Neyvia tool mark.

---

## 1. Headline counts

| Layer | Count | Frontend exposure |
| --- | ---: | --- |
| Capability packs (`config/capability_packs.json`) | **15 packs / 61 capabilities** | Library search grid only (`partial`); no per-capability tiles in Chat Tools |
| Managed tool suite (`config/tool_suite_lock.json`) | **42 tools** (most `planned`/`blocked`; few typed `operations`) | Not listed as tools in UI (`missing`); reachable only indirectly via capability search/execute |
| Progressive Capability OS tools (`capability_service.register_with_progressive_surface`) | **31** | Commands used by Library/plan sheet (`partial`); not in Chat Tools catalog |
| Native tools (`native_tools.py`) | **20** | Web Search / Web Capture / Images loosely map (`stub`); rest `missing` |
| Compact UI / computer-use graph tools (`ui_tools.py`) | **8** (`ui.*`) | `missing` as named tools (Lab/browser proof only) |
| MCP broker progressive tools (`mcp_broker.py`) | **4** (`mcp.*`) + demo stubs `echo` / `write_note` | `missing` |
| Neyvia MCP server tools (`neyvia_mcp.py`) | **~28** direct + task starters (+ re-exports `ui.*` / `mcp.*`) | `missing` as catalog entries |
| Capability OS Tauri/command surface (`*_command`) | **~40** | Library / plan / notebook call a subset (`partial`) |
| Authored tools (`tool_factory.AuthoredToolStore`) | **dynamic** under `.agent_control/capability_os/authored_tools/` | `missing` (no Library “authored tools” browser) |
| Computer-use twin / verify | **6 progressive** + `neyvia.computer.start` | `missing` |
| Frontend Chat Tools catalog | **9 stubs** | All `stub` / `not_connected` |
| Frontend Toolbar catalog | **9 slots** | `stub` / `partial` chrome |
| Notebook tool drawers | **3** | Navigation stubs |

---

## 2. Where Neyvia app icons live locally

Product / OS icons (app brand marks — **not** per-tool icons):

| Path | Role |
| --- | --- |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\neyvia-icon.svg` | Code-native Neyvia mark (source of truth for desktop) |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\icon.png` | Primary PNG |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\icon.ico` | Windows |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\icon.icns` | macOS |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\32x32.png` | Tray / small |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\64x64.png` | Small |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\128x128.png` | Standard |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\128x128@2x.png` | Retina |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\Square*.png` / `StoreLogo.png` | Windows Store tiles |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\android\**` | Android launcher mipmaps + adaptive XML |
| `C:\Users\example\projects\vibe-coding-platform\src-tauri\icons\ios\AppIcon-*.png` | iOS app icons |

Brand / design references:

| Path | Role |
| --- | --- |
| `C:\Users\example\projects\vibe-coding-platform\docs\NEYVIA_BRAND.md` | Brand contract |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\references\neyvia-app-icon-reference.jpg` | Operator app-icon reference |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\references\neyvia-lockup-reference.jpg` | Lockup |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\references\neyvia-mobile-reference.jpg` | Mobile |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\references\neyvia-monochrome-reference.jpg` | Mono |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\references\neyvia-web-reference.jpg` | Web |
| `C:\Users\example\projects\vibe-coding-platform\docs\brand\capos-ui-candidates\**` | CapOS UI inspo gallery (HTML/CSS/JS + inspo PNGs) |

React / legacy marks:

| Path | Role |
| --- | --- |
| `C:\Users\example\projects\vibe-coding-platform\web\src\neyvia\NeyviaBrandMark.jsx` | In-app React mark |
| `C:\Users\example\projects\vibe-coding-platform\desktop-ui\fluxio-logo-main.svg` | Legacy Fluxio lockup |
| `C:\Users\example\projects\vibe-coding-platform\desktop-ui\fluxio-logo-mark.svg` | Legacy Fluxio mark |

**Gap:** There is **no** `web/public/icons/` tree of per-tool glyphs in the live workspace. Tool UI currently borrows Lucide icons. Any future tool-icon set should be a new asset family (distinct from the app mark).

---

## 3. What the frontend currently shows

### 3.1 Chat tools panel — `NeyviaChatToolsPanel` / `CHAT_TOOL_CATALOG`

Source: `web/src/neyvia/NeyviaShellSurfaces.jsx`

| id | name | category | Frontend UI | Icon | Animation | Backend mapping (loose) |
| --- | --- | --- | --- | --- | --- | --- |
| `pdf` | PDF Reader | pdf / documents | stub (panel shell) | missing in grid; toolbar uses `FileText` | shared (overlay) | `document.pdf-analysis`, `pdf.pdftotext`, `tool.poppler` / `tool.tesseract` |
| `search` | Web Search | research / web | stub | generic (`Search` on toolbar) | shared | `web.search`, `web.fetch` |
| `data` | Data Analyst | office / data | stub | generic (`Sparkles`) | shared | `office.spreadsheet-*`, `tool.duckdb` / `tool.polars` |
| `chart` | Chart Builder | office / data | stub | missing | shared | spreadsheet / science analysis capabilities |
| `images` | Image Playground | media / design | partial (routes to Images surface) | generic (`Palette` in notebook) | shared | `media.image-generation`, Image Playground UI |
| `scene` | 3D / Scene | design/3d | stub (scene panel) | missing | shared | `three-d.*`, `tool.blender` |
| `web-capture` | Web Capture | browser / file | stub | missing | shared | `preview.screenshot`, `preview.annotate`, `device.browser-session` |
| `notes` | Notes | notebook | partial (routes to Notebook) | missing | shared | Notebook surface / artifacts |
| `specialists` | Specialists | orchestration | stub (roster panel) | missing | shared | conversation / orchestration MCP tools |

All nine emit `neyvia:tool:<id>` with `status: "not_connected"` unless they only navigate.

### 3.2 Toolbar — `NEYVIA_TOOLBAR_CATALOG`

Source: `web/src/neyvia/neyviaShellPreferences.js` + `NeyviaToolbarStrip`

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `attach` | Attach | file | partial (action hook) | dedicated Lucide `Paperclip` | shared / hover |
| `search` | Web Search | research | stub → tools panel | dedicated Lucide `Search` | shared |
| `pdf` | PDF Reader | pdf | stub → PDF panel | dedicated Lucide `FileText` | shared |
| `data` | Data Analyst | office / data | stub → tools panel | **generic** `Sparkles` | shared |
| `images` | Image Playground | media | partial → Images surface | **generic** `Sparkles` | shared |
| `canvas` | Canvas | design / artifacts | stub → tools panel | **generic** `Sparkles` | shared |
| `citations` | Citations | research | stub → sources panel | dedicated Lucide `FileText` (shared with PDF) | shared |
| `terminal` | Terminal | software | stub → tools panel | **generic** `Sparkles` | shared |
| `diff` | Diff | software / file | stub → tools panel | **generic** `Sparkles` | shared |

### 3.3 Library surface

`NeyviaLibrarySurface` calls:

- `get_capability_ui_contract_command`
- `search_capabilities_command`

| Concern | Frontend UI | Icon | Animation |
| --- | --- | --- | --- |
| Capability / pack results | **partial** — text cards + Inspect; not a tool launcher | missing (no pack/capability glyphs) | shared surface enter |
| Entry tiles (Settings / Skills / Workflows) | present as navigation | Lucide chrome icons | shared |
| Custom pack authoring | stub copy when backend down | missing | none |

Library can *discover* backend capabilities when connected, but does **not** render dedicated icons, animations, or execute UX per capability.

### 3.4 Notebook drawers

| id | name | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- |
| `images` | Image Playground | partial | Lucide `Palette` | shared |
| `harnesses` | Harnesses | stub / nav | Lucide `SquareTerminal` | shared |
| `skills` | Skills | stub / nav | Lucide `Grid2x2` | shared |

### 3.5 PDF / Scene / Sources / Plan / Roster overlays

| Surface | Frontend UI | Icon | Animation |
| --- | --- | --- | --- |
| PDF Reader panel | stub (empty stage) | missing | shared overlay |
| Scene / glTF panel | stub | missing | shared overlay |
| Sources & citations | stub until provenance | missing | shared overlay |
| Capability plan sheet | partial (contract shell) | missing | shared overlay |
| Specialist roster | stub | missing | shared overlay |

---

## 4. Capability catalog (61) — packs from `config/capability_packs.json`

Frontend baseline for **all** rows below: Library can search them when backend is up (`partial`); Chat Tools / Toolbar do **not** list them (`missing` as named tools). Icons/animations: **missing** / **none** unless noted.

### 4.1 `domain.research-science` — research / science

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `research.literature-review` | Literature review | research | partial (Library) | missing | none |
| `science.experiment-design` | Experiment design | research / science | partial | missing | none |
| `science.statistical-analysis` | Statistical analysis | research / data | partial | missing | none |
| `science.simulation-study` | Simulation study | research / science | partial | missing | none |

### 4.2 `domain.education-learning` — education

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `learning.adaptive-tutorial` | Adaptive tutorial | education | partial | missing | none |
| `learning.flashcards` | Source-grounded flashcards | education | partial | missing | none |
| `learning.graded-assessment` | Graded assessment | education | partial | missing | none |
| `learning.curriculum-plan` | Curriculum plan | education | partial | missing | none |

### 4.3 `domain.literature-publishing` — writing / translate / grammar-adjacent

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `writing.manuscript-authoring` | Manuscript authoring | writing | partial | missing | none |
| `writing.editorial-redline` | Editorial redline | grammar / writing | partial | missing | none |
| `literature.critical-reading` | Critical reading | literature | partial | missing | none |
| `writing.translation-alignment` | Translation alignment | translate | partial | missing | none |

### 4.4 `domain.documents-ocr` — pdf / ocr / latex

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `document.fast-ocr` | Fast progressive OCR | pdf / ocr | stub (PDF panel mentions adapters) | missing | none |
| `document.pdf-analysis` | PDF analysis | pdf | stub | generic toolbar `FileText` | shared |
| `document.office-conversion` | Office document conversion | office / file | missing | missing | none |
| `document.latex-production` | LaTeX production | latex / pdf | missing | missing | none |

### 4.5 `domain.office-data` — office / data

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `office.spreadsheet-analysis` | Spreadsheet analysis | office / data | stub (`data`) | generic | shared |
| `office.spreadsheet-edit` | Spreadsheet editing | office / data | missing | missing | none |
| `office.presentation-authoring` | Presentation authoring | office | missing | missing | none |
| `office.report-authoring` | Business report authoring | office | missing | missing | none |

### 4.6 `domain.business-communication` — communication / design

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `communication.campaign-plan` | Communication campaign | communication | missing | missing | none |
| `communication.message-drafting` | Message and email drafting | communication | missing | missing | none |
| `design.card-and-invitation` | Card and invitation design | design | missing | missing | none |
| `design.label-and-packaging` | Label and packaging design | design | missing | missing | none |

### 4.7 `domain.software-infrastructure` — software

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `software.application-engineering` | Application engineering | software | stub (`terminal`/`diff` chrome only) | generic | shared |
| `software.network-architecture` | Network architecture | software | missing | missing | none |
| `software.database-engineering` | Database engineering | software | missing | missing | none |
| `software.delivery-pipeline` | Build and delivery pipeline | software | missing | missing | none |

### 4.8 `domain.ai-ml` — AI / ML

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `ai.assistant-architecture` | AI assistant architecture | ai | missing | missing | none |
| `ai.dataset-engineering` | Dataset engineering | ai / data | missing | missing | none |
| `ai.model-training` | Model training | ai | missing | missing | none |
| `ai.model-benchmarking` | Model benchmarking | ai | missing | missing | none |

### 4.9 `domain.security-red-team` — security

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `security.threat-model` | Threat model | security | missing | missing | none |
| `security.ai-red-team` | AI red-team assessment | security | missing | missing | none |
| `security.application-assessment` | Application security assessment | security | missing | missing | none |
| `security.reverse-engineering` | Authorized reverse engineering | security | missing | missing | none |
| `security.remediate-and-retest` | Remediate and retest | security | missing | missing | none |

### 4.10 `domain.media-creative` — media

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `media.photo-editing` | Photo editing | media | missing | missing | none |
| `media.image-generation` | Image generation | media | partial (Images surface) | generic | shared |
| `media.video-production` | Video production | media | missing | missing | none |
| `media.audio-production` | Audio production | media | missing | missing | none |

### 4.11 `domain.three-d-game` — design/3d / games

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `three-d.blender-scene` | Blender scene engineering | design/3d | stub (`scene`) | missing | none |
| `game.unity-project` | Unity project engineering | games | missing | missing | none |
| `game.mod-development` | Game mod development | games | missing | missing | none |
| `three-d.runtime-export` | 3D runtime export | design/3d | stub (`scene`) | missing | none |

### 4.12 `domain.maker-engineering` — maker

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `maker.electronics-design` | Electronics design | maker | missing | missing | none |
| `maker.cad-fabrication` | CAD and fabrication planning | maker | missing | missing | none |
| `maker.robotics-system` | Robotics system engineering | maker | missing | missing | none |
| `maker.repair-guidance` | Repair and modification guidance | maker | missing | missing | none |

### 4.13 `domain.fashion-physical` — fashion / design

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `fashion.collection-concept` | Fashion collection concept | fashion | missing | missing | none |
| `fashion.pattern-specification` | Pattern and sizing specification | fashion | missing | missing | none |
| `fashion.label-system` | Clothing label system | fashion | missing | missing | none |
| `fashion.production-pack` | Fashion production pack | fashion | missing | missing | none |

### 4.14 `domain.device-app-lab` — device / browser

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `device.android-test` | Android emulator test | device | missing | missing | none |
| `device.apple-remote-test` | Remote Apple Simulator test | device | missing | missing | none |
| `device.browser-session` | Structured browser session | browser / computer-use | missing | missing | none |
| `device.responsive-matrix` | Responsive interaction matrix | browser / qa | missing | missing | none |

### 4.15 `domain.niche-knowledge` — niche

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `niche.genealogy-research` | Genealogy research | niche | missing | missing | none |
| `niche.astronomy-observation` | Astronomy observation | niche | missing | missing | none |
| `niche.culinary-development` | Culinary development | niche | missing | missing | none |
| `niche.custom-pack-authoring` | Custom capability-pack authoring | orchestration / niche | stub (Library empty-state copy) | missing | none |

---

## 5. Managed tool suite (`config/tool_suite_lock.json`) — 42 tools

These are pinned external suites exposed via progressive `tool.suite.search` / `describe` / `execute`.  
**Frontend:** all `missing` as first-class UI tools (no Library tool-suite browser, no icons).

| id | name | category | Frontend UI | Icon | Animation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `tool.poppler` | Poppler | pdf | missing | missing | none | `installed`; op `pdf.extract-text` |
| `tool.tesseract` | Tesseract OCR | ocr / pdf | missing | missing | none | planned |
| `tool.ocrmypdf` | OCRmyPDF | ocr / pdf | missing | missing | none | planned |
| `tool.paddleocr` | PaddleOCR | ocr / pdf | missing | missing | none | planned / GPU |
| `tool.libreoffice` | LibreOffice | office | missing | missing | none | planned |
| `tool.pandoc` | Pandoc | documents | missing | missing | none | verified; ops list/inspect/convert |
| `tool.languagetool` | LanguageTool | grammar | missing | missing | none | planned — **no Chat “Grammar” tool** |
| `tool.argos-translate` | Argos Translate | translate | missing | missing | none | planned — **no Chat “Translate” tool** |
| `tool.libretranslate` | LibreTranslate | translate | missing | missing | none | planned |
| `tool.latex-suite` | MiKTeX / TeX Live / latexmk | latex | missing | missing | none | installed |
| `tool.zotero` | Zotero | research | missing | missing | none | planned |
| `tool.playwright` | Playwright | browser / computer-use | missing | missing | none | installed |
| `tool.android-sdk` | Android SDK / Emulator | device | missing | missing | none | planned |
| `tool.appium` | Appium | device | missing | missing | none | planned |
| `tool.scrcpy` | scrcpy | device | missing | missing | none | planned |
| `tool.git` | Git | software / file | missing | missing | none | installed |
| `tool.docker-engine` | Docker Engine | software | missing | missing | none | installed |
| `tool.postgresql` | PostgreSQL | software / data | missing | missing | none | planned |
| `tool.duckdb` | DuckDB | data | missing | missing | none | planned |
| `tool.polars` | Polars | data | missing | missing | none | planned |
| `tool.scientific-python` | Scientific Python / Jupyter | research / science | missing | missing | none | planned |
| `tool.anki` | Anki | education | missing | missing | none | planned |
| `tool.pytorch-huggingface` | PyTorch / HF | ai | missing | missing | none | planned |
| `tool.ffmpeg` | FFmpeg | media | missing | missing | none | installed |
| `tool.imagemagick` | ImageMagick | media / design | missing | missing | none | planned |
| `tool.gimp` | GIMP | media | missing | missing | none | planned |
| `tool.blender` | Blender | design/3d | missing | missing | none | planned |
| `tool.godot` | Godot Engine | games | missing | missing | none | planned |
| `tool.kicad` | KiCad | maker | missing | missing | none | planned |
| `tool.freecad` | FreeCAD | maker | missing | missing | none | planned |
| `tool.openscad` | OpenSCAD | maker | missing | missing | none | planned |
| `tool.ros-gazebo` | ROS 2 / Gazebo | maker | missing | missing | none | planned |
| `tool.inkscape` | Inkscape | design | missing | missing | none | planned |
| `tool.scribus` | Scribus | design | missing | missing | none | planned |
| `tool.seamly` | Seamly2D / SeamlyMe | fashion | missing | missing | none | blocked |
| `tool.trivy` | Trivy | security | missing | missing | none | planned |
| `tool.semgrep` | Semgrep | security | missing | missing | none | planned |
| `tool.owasp-zap` | OWASP ZAP | security | missing | missing | none | planned |
| `tool.ghidra` | Ghidra | security | missing | missing | none | planned |
| `tool.mobile-security` | MobSF / Frida | security / device | missing | missing | none | blocked |
| `tool.gramps` | Gramps | niche | missing | missing | none | planned |
| `tool.astronomy-suite` | Astropy / Stellarium / Siril | niche | missing | missing | none | planned |

Typed operations currently declared in lock (executable via `tool.suite.execute`):

| operationId | parent tool | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `pdf.extract-text` | `tool.poppler` | pdf | missing | missing | none |
| `document.list-formats` | `tool.pandoc` | documents | missing | missing | none |
| `document.inspect-ast` | `tool.pandoc` | documents | missing | missing | none |
| `document.convert` | `tool.pandoc` | documents | missing | missing | none |

---

## 6. Progressive Capability OS tools

Source: `src/grant_agent/capability_service.py` → `register_with_progressive_surface`

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `tool.suite.search` | Search Managed Tool Suite | orchestration | missing | missing | none |
| `tool.suite.describe` | Describe Managed Tool | orchestration | missing | missing | none |
| `tool.suite.execute` | Execute Managed Tool Operation | orchestration | missing | missing | none |
| `capability.search` | Search capabilities | orchestration | partial (Library) | missing | shared |
| `capability.describe` | Describe capability | orchestration | partial (Inspect) | missing | shared |
| `capability.plan` | Plan capability run | orchestration | partial (plan sheet) | missing | shared |
| `capability.ui.contract` | Capability UI contract | orchestration | partial | missing | shared |
| `capability.benchmark` | Benchmark capability OS | orchestration | missing | missing | none |
| `capability.execute` | Execute capability | orchestration | missing | missing | none |
| `capability.pack.validate` | Validate pack | orchestration | missing | missing | none |
| `capability.pack.save` | Save pack | orchestration | missing | missing | none |
| `model.tools.compile` | Compile model tool belt | orchestration / ai | missing | missing | none |
| `model.tools.openai.compile` | Compile OpenAI tool belt | orchestration / ai | missing | missing | none |
| `model.tools.benchmark` | Benchmark tool routing | orchestration / ai | missing | missing | none |
| `model.tools.feedback` | Get tool feedback | orchestration / ai | missing | missing | none |
| `model.tools.feedback.record` | Record tool feedback | orchestration / ai | missing | missing | none |
| `model.tools.run` | Run model tool plan | orchestration / ai | missing | missing | none |
| `tool.author.search` | Search authored tools | authored | missing | missing | none |
| `tool.author.describe` | Describe authored tool | authored | missing | missing | none |
| `tool.author.adapt` | Adapt authored tool | authored | missing | missing | none |
| `tool.author.validate` | Validate authored tool | authored | missing | missing | none |
| `tool.author.save` | Save authored tool | authored | missing | missing | none |
| `tool.author.execute` | Execute authored tool | authored | missing | missing | none |
| `computer_use.verify` | Verify computer-use change | computer-use | missing | missing | none |
| `computer_use.dispatch_verification` | Dispatch CU verification | computer-use | missing | missing | none |
| `cu.twin.validate` | Validate CU twin | computer-use | missing | missing | none |
| `cu.twin.save` | Save CU twin | computer-use | missing | missing | none |
| `cu.twin.run` | Run CU twin | computer-use | missing | missing | none |
| `cu.twin.dispatch` | Dispatch CU twin | computer-use | missing | missing | none |
| `artifact.register` | Register artifact | file / artifacts | missing | missing | none |
| `artifact.lineage` | Artifact lineage | file / artifacts | partial (Notebook mentions lineage) | missing | shared |

---

## 7. Capability OS command surface (`*_command`)

Exposed for Tauri / web bridge (see `capability_service` command table). Frontend calls a **subset**.

| id | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- |
| `get_capability_os_snapshot_command` | orchestration | partial (Notebook) | missing | shared |
| `search_capabilities_command` | orchestration | partial (Library) | missing | shared |
| `describe_capability_command` | orchestration | partial (Inspect action) | missing | shared |
| `validate_capability_pack_command` | orchestration | missing | missing | none |
| `save_capability_pack_command` | orchestration | missing | missing | none |
| `plan_capability_run_command` | orchestration | stub/partial (plan sheet) | missing | shared |
| `create_capability_run_command` | orchestration | missing | missing | none |
| `get_capability_run_command` | orchestration | missing | missing | none |
| `record_capability_preview_command` | orchestration | missing | missing | none |
| `finish_capability_run_command` | orchestration | missing | missing | none |
| `register_capability_artifact_command` | file | missing | missing | none |
| `relate_capability_artifacts_command` | file | missing | missing | none |
| `get_capability_artifact_lineage_command` | file | missing | missing | none |
| `execute_capability_command` | orchestration | missing | missing | none |
| `benchmark_capability_os_command` | orchestration | missing | missing | none |
| `register_capability_adapter_session_command` | adapters | missing | missing | none |
| `heartbeat_capability_adapter_session_command` | adapters | missing | missing | none |
| `disconnect_capability_adapter_session_command` | adapters | missing | missing | none |
| `list_authored_tools_command` | authored | missing | missing | none |
| `search_authored_tools_command` | authored | missing | missing | none |
| `describe_authored_tool_command` | authored | missing | missing | none |
| `adapt_authored_tool_command` | authored | missing | missing | none |
| `validate_authored_tool_command` | authored | missing | missing | none |
| `save_authored_tool_command` | authored | missing | missing | none |
| `execute_authored_tool_command` | authored | missing | missing | none |
| `list_computer_use_twins_command` | computer-use | missing | missing | none |
| `validate_computer_use_twin_command` | computer-use | missing | missing | none |
| `save_computer_use_twin_command` | computer-use | missing | missing | none |
| `run_computer_use_twin_command` | computer-use | missing | missing | none |
| `dispatch_computer_use_twin_command` | computer-use | missing | missing | none |
| `verify_computer_use_change_command` | computer-use | missing | missing | none |
| `dispatch_computer_use_verification_command` | computer-use | missing | missing | none |
| `compile_model_tool_belt_command` | ai / orchestration | missing | missing | none |
| `compile_openai_tool_belt_command` | ai / orchestration | missing | missing | none |
| `benchmark_model_tool_routing_command` | ai / orchestration | missing | missing | none |
| `get_model_tool_feedback_command` | ai / orchestration | missing | missing | none |
| `record_model_tool_feedback_command` | ai / orchestration | missing | missing | none |
| `run_model_tool_plan_command` | ai / orchestration | missing | missing | none |
| `get_capability_ui_contract_command` | orchestration | partial | missing | shared |

---

## 8. Native tools (`src/grant_agent/native_tools.py`)

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `workspace.search` | Workspace search | file | missing | missing | none |
| `context.search` | Context search | orchestration / context | missing | missing | none |
| `context.bundle` | Context bundle | orchestration / context | missing | missing | none |
| `context.compact` | Context compact | orchestration / context | missing | missing | none |
| `orchestration.compile` | Orchestration compile | orchestration | missing | missing | none |
| `codex.assets.inspect` | Codex assets inspect | import / skills | missing | missing | none |
| `codex.assets.import` | Codex assets import | import / skills | missing | missing | none |
| `skill.live.read` | Live skill read | skills | missing | missing | none |
| `skill.live.iterate` | Live skill iterate | skills | missing | missing | none |
| `web.search` | Web search | research | stub (`search`) | generic | shared |
| `web.image_search` | Web image search | research / media | missing | missing | none |
| `ui.inspiration.search` | UI inspiration search | design | missing | missing | none |
| `web.fetch` | Web fetch | research / file | stub (`web-capture` loose) | missing | none |
| `preview.inspect` | Preview inspect | browser | missing | missing | none |
| `preview.screenshot` | Preview screenshot | browser / computer-use | stub (`web-capture`) | missing | none |
| `preview.annotate` | Preview annotate | browser | missing | missing | none |
| `video.inspect` | Video inspect | media | missing | missing | none |
| `video.digest` | Video digest | media | missing | missing | none |
| `nas.message.send` | NAS message send | messaging / file | missing | missing | none |
| `nas.message.receive` | NAS message receive | messaging / file | missing | missing | none |
| `nas.file.send` | NAS file send | file | missing | missing | none |
| `nas.transfer` | NAS transfer | file | missing | missing | none |

---

## 9. Compact UI / computer-use actions (`ui_tools.py`)

These are the structured computer-use / browser graph tools (preferred over raw screenshots).

| id | name | category | Frontend UI | Icon | Animation | Actions / notes |
| --- | --- | --- | --- | --- | --- | --- |
| `ui.ls` | List UI graph | computer-use / ui | missing | missing | none | role-filtered listing |
| `ui.find` | Find UI nodes | computer-use / ui | missing | missing | none | selector query |
| `ui.get` | Get UI node | computer-use / ui | missing | missing | none | by id |
| `ui.diff` | Diff UI graph | computer-use / ui | missing | missing | none | revision delta |
| `ui.wait` | Wait for UI | computer-use / ui | missing | missing | none | present/absent |
| `ui.do` | Act on UI | computer-use / ui | missing | missing | none | **actions:** `click`, `fill`, `press`, `select`, `toggle` |
| `ui.see` | Vision crop | computer-use / ui | missing | missing | none | Playwright/CDP clip |
| `ui.observe` | Observe page | computer-use / ui | missing | missing | none | refresh a11y graph |

Also registered on progressive surfaces and into the Neyvia MCP catalog.

Android adapter mutation actions (`capability_adapters.device.android`):  
`devices`, `device_info`, `packages`, `logcat`, `install`, `launch`, `tap`, `swipe`, `text`, `screenshot`, `list_avds`, `start_emulator` — Frontend: **missing** / icons **missing** / animation **none**.

---

## 10. MCP broker tools (`mcp_broker.py`)

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `mcp.servers` | List MCP servers | mcp / orchestration | missing | missing | none |
| `mcp.search` | Search brokered tools | mcp | missing | missing | none |
| `mcp.describe` | Describe brokered tool | mcp | missing | missing | none |
| `mcp.call` | Call brokered tool | mcp | missing | missing | none |
| `demo.echo` (stub) | Echo | mcp demo | missing | missing | none |
| `demo.write_note` (stub) | Write note | mcp demo | missing | missing | none |

Foreign MCP tools discovered at runtime via broker config (`.agent_control/mcp_broker.json` / `mcp_servers.json`) are **dynamic** and also UI-`missing`.

---

## 11. Neyvia MCP server tools (`neyvia_mcp.py`)

### 11.1 Durable task starters

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `neyvia.research.start` | Start resumable research | research | missing | missing | none |
| `neyvia.browser.start` | Start resumable browser work | browser | missing | missing | none |
| `neyvia.computer.start` | Start resumable computer use | computer-use | missing | missing | none |
| `neyvia.training.batch.start` | Start sparse model training batch | ai | missing | missing | none |

### 11.2 Progressive / host tools

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| `neyvia.time.now` | Current time | orchestration | missing | missing | none |
| `neyvia.tools.search` | Search tools (progressive) | orchestration | missing | missing | none |
| `neyvia.tools.describe` | Describe tool (progressive) | orchestration | missing | missing | none |
| `neyvia.time.budget` | Deadline budget | orchestration | missing | missing | none |
| `neyvia.task.status` | Durable task status | orchestration | missing | missing | none |
| `neyvia.result.summary` | Result set summary | orchestration | missing | missing | none |
| `neyvia.autonomy.grant` | Grant scoped autonomy | orchestration | missing | missing | none |
| `neyvia.autonomy.check` | Autonomy lease check | orchestration | missing | missing | none |
| `neyvia.autonomy.revoke` | Revoke autonomy | orchestration | missing | missing | none |
| `neyvia.conversation.list` | List conversations | chat / orchestration | missing | missing | none |
| `neyvia.conversation.search` | Search conversation fabric | chat / orchestration | missing | missing | none |
| `neyvia.question.branch` | Create read-only question branch | chat | missing | missing | none |
| `neyvia.question.action.check` | Check question branch action | chat | missing | missing | none |
| `neyvia.context.retrieve` | Retrieve cited context | research / context | missing | missing | none |
| `neyvia.orchestration.plan` | Build constellation | orchestration | missing | missing | none |
| `neyvia.orchestration.graph` | Read constellation graph | orchestration | partial (Orchestration surface exists) | missing | shared (node pulse CSS) |

Plus re-exported `ui.*` and `mcp.*` (see sections 9–10).

---

## 12. Adapters (`capability_adapters.py`)

Callable / registerable adapters the capability OS can report:

| id | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- |
| `neyvia.agent` | orchestration | missing | missing | none |
| `builtin.artifact.inspect` | file | missing | missing | none |
| `builtin.text.extract` | file | missing | missing | none |
| `ocr.tesseract` | ocr | stub (PDF copy) | missing | none |
| `pdf.pdftotext` | pdf | stub | missing | none |
| `document.libreoffice` | office | missing | missing | none |
| `document.pandoc` | documents | missing | missing | none |
| `latex.compiler` | latex | missing | missing | none |
| `media.ffmpeg` | media | missing | missing | none |
| `three_d.blender` | design/3d | stub (`scene`) | missing | none |
| `game.unity` | games | missing | missing | none |
| `device.android` | device | missing | missing | none |
| `code.git` | software | missing | missing | none |
| `runtime.python` | software | missing | missing | none |
| `runtime.node` | software | missing | missing | none |
| `device.apple-remote` | device (bridge) | missing | missing | none |
| `browser.firefox-bidi` | browser (bridge) | missing | missing | none |
| `office.document-session` | office (bridge) | missing | missing | none |
| `game.unity-bridge` | games (bridge) | missing | missing | none |
| `three_d.blender-bridge` | design/3d (bridge) | missing | missing | none |

---

## 13. Authored tools (`tool_factory.py`)

| id | name | category | Frontend UI | Icon | Animation |
| --- | --- | --- | --- | --- | --- |
| *(dynamic `toolId`)* | User/system authored manifests | authored | missing | missing | none |

Kinds: `command` · `composite` · `delegated`.  
Discovery/execute via `tool.author.*` progressive tools and `*_authored_tool_command`.  
Storage: `.agent_control/capability_os/authored_tools/<toolId>.json`.

---

## 14. Coverage gap summary (what UI lacks vs backend)

**Present or partial in UI chrome**

- Attach, Web Search, PDF, Data, Images, Canvas, Citations, Terminal, Diff (toolbar)
- Chat Tools 9 stubs (honest “not connected”)
- Library capability search cards
- Image Playground surface
- Orchestration surface (graph motion shared; not tool catalog)
- Plan / Sources / PDF / Scene / Roster overlay shells

**Missing as first-class UI tools (high-signal examples Paul likely expects)**

- Grammar (`tool.languagetool` / editorial redline)
- Translate (`tool.argos-translate`, `tool.libretranslate`, `writing.translation-alignment`)
- OCR as its own tool tile (beyond PDF stub)
- LaTeX, Zotero, Anki
- Spreadsheet edit / PPT / report authoring
- Blender / Unity / Godot as real Lab tools
- FFmpeg video/audio production
- Android / Apple device lab
- Security suite (Trivy, Semgrep, ZAP, Ghidra, MobSF)
- Maker CAD (KiCad, FreeCAD, OpenSCAD, ROS)
- Fashion (Seamly, label systems)
- Niche (Gramps, astronomy)
- Entire progressive MCP / authored-tool / CU-twin / model-tool-intelligence surfaces
- All `ui.*` computer-use actions as operator-visible tools
- Dedicated **tool icons** and **tool animations** for any of the above

**Icon / animation reality check**

- App icons: strong (`src-tauri/icons`, brand refs).
- Per-tool icons: essentially **none** (Lucide generics only).
- Per-tool animations: **none**; only shared shell motion + orchestration node pulse.

---

## 15. Source index

| Source | Path |
| --- | --- |
| Capability packs | `config/capability_packs.json` |
| Tool suite lock | `config/tool_suite_lock.json` |
| Capability service / progressive OS | `src/grant_agent/capability_service.py` |
| Capability adapters | `src/grant_agent/capability_adapters.py` |
| Progressive surface | `src/grant_agent/progressive_tools.py` |
| Tool factory / authored | `src/grant_agent/tool_factory.py` |
| Model tool intelligence | `src/grant_agent/model_tool_intelligence.py` |
| Neyvia MCP | `src/grant_agent/neyvia_mcp.py` |
| MCP broker | `src/grant_agent/mcp_broker.py` |
| UI / CU tools | `src/grant_agent/ui_tools.py` |
| Native tools | `src/grant_agent/native_tools.py` |
| CU twin / verifier | `src/grant_agent/computer_use_twin.py`, `computer_use_verifier.py` |
| Shell surfaces / Chat Tools | `web/src/neyvia/NeyviaShellSurfaces.jsx` |
| Toolbar prefs | `web/src/neyvia/neyviaShellPreferences.js` |
| Motion | `web/src/neyvia/neyviaMotion.css` |

---

## 16. Recommended next inventory work (not done here)

1. Generate per-tool SVG glyphs for Chat Tools + Library + Toolbar (separate from app mark).
2. Bind Library cards to `tool.suite.*` as well as capabilities.
3. Promote grammar / translate / OCR / latex / 3D / device lab from `missing` → honest stubs with backend availability badges.
4. Add `data-neyvia-tool-id` + dedicated CSS keyframes only for tools that have live adapters.

*Generated as a durable inventory; not committed by request.*

Publication note: local account paths and network identifiers in this document are neutral examples.
