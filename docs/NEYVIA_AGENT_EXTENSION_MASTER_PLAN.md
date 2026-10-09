# Neyvia Agent Extension Master Plan

Status: active engineering goal  
Baseline date: 2026-07-23  
Scope: local Windows workstation, authorized NAS workers, and authorized remote Apple runner

## Goal

Turn every Neyvia capability into a first-class extension of the agent rather than a
name, a detected executable, or a generic shell handoff.

For every external application, library, model, or service Neyvia uses, the finished
integration must:

1. select a maintained, automation-friendly implementation after an open-source
   preflight;
2. record the selected release, stable/LTS track, license, source, hashes, platform,
   and complete useful operation inventory;
3. install it on the correct worker without polluting the repository or filling the
   system drive;
4. expose typed, bounded operations instead of unrestricted command strings;
5. tell the model what the tool can do, what it cannot do, its resource cost, and the
   permission required for each operation;
6. stream progress, logs, previews, artifacts, warnings, and receipts into the
   workspace;
7. support cancellation, timeouts, recovery, reproducibility, and verification;
8. preserve editable source, provenance, and a reversible change history;
9. be tested through a realistic user workflow; and
10. be copied to an immutable, hash-verified NAS candidate after verification.

“Install everything” means install every approved suite component needed by the
declared capabilities. It does not mean installing duplicate tools with no purpose,
nightly builds, abandoned packages, unlicensed binaries, or unrestricted utilities
that bypass Neyvia permissions.

## Honest baseline

The catalog currently contains 15 packs and 61 capabilities.

External suites own 52 capability paths. Nine capabilities are explicitly native
Neyvia reasoning/orchestration paths: campaign planning, message drafting, adaptive
tutorials, curriculum planning, repair guidance, image-provider routing, culinary
development, custom-pack authoring, and threat modeling. They still use the common
artifact, permission, receipt, and verification contracts; they do not require a
pretend external executable.

| Current execution maturity | Count | Meaning |
| --- | ---: | --- |
| Direct bounded execution | 2 | A capability has a real handler and verified output |
| Detected executable only | 8 | A runtime can be found but has no complete capability handler |
| Generic `neyvia.agent` handoff | 44 | Planning intelligence exists, but domain actions are not native controls |
| Missing required runtime | 7 | The declared adapter cannot run on this workstation |

The completed backend slices provide real bounded Poppler PDF extraction, a hybrid
PaddleOCR GPU path, an explicit Tesseract CPU fallback, Pandoc and LibreOffice
document production, and Android ADB/emulator control. Android availability still
depends on the selected workstation and emulator state.

### Implemented Wave 1 reference integration

Pandoc 3.10.1 and LibreOffice Portable 26.2.4.2 now pass the managed-tool
gate. Pandoc provides the semantic authoring path:

- official Windows portable archive installed under `D:\Neyvia\apps`;
- archive and executable SHA-256 recorded;
- exact version and health probe verified;
- compact search and deferred full schema discovery exposed to models;
- typed `formats`, `inspect_ast`, and `convert` operations;
- permission and JSON Schema validation before execution;
- sandboxed local conversion with atomic output creation and no overwrite fallback;
- deterministic, hash-pinned `compact_reference_guide` DOCX reference document;
- Pandoc readback verification, telemetry, tool receipt, artifact registration, and
  source-to-output lineage;
- real Markdown-to-DOCX workflow completed against this master plan;
- structural page, heading, style, and accessibility audits completed; and
- a 20-page final proof rendered through LibreOffice and inspected page by page.

LibreOffice Portable 26.2.4.2 provides the editable-office and rendering path:

- official package, executable, and PDF verifier hashes are pinned;
- typed `office.version`, `office.convert`, and `office.render-pdf` operations;
- unique per-run profiles, bounded inputs and time, allowlisted filters, atomic
  outputs, and no overwrite fallback;
- editable output is reopened and rendered before it can pass verification;
- PDF page count is verified independently; and
- real DOCX-to-PDF and DOCX-to-ODT-to-PDF workflows retain artifact lineage.

The final Pandoc proof is
`.agent_control/capability_os/outputs/pandoc-agent-extension-proof-v6.docx`
(`df1855ecfb50b293737fd5a856ae0117b0dc3ed246177d21dd9dc0192df23b0e`).
The directly managed LibreOffice PDF proof is
`.agent_control/capability_os/outputs/libreoffice-agent-extension-proof-v1.pdf`
(`47aebf84a9186e88c03703c28896bc4b8220bf2ff14c514d588a02ed38c7e531`).

The broader modular application, signed marketplace, personal mesh, nearby sharing,
multi-device chat, and secret-broker design is maintained in
`docs/NEYVIA_MODULAR_PLATFORM_AND_PERSONAL_MESH_PLAN.md`. Those platform services
are planned or foundation-only unless explicitly marked verified there.

Workstation placement constraints:

- Windows 11, 64 GB RAM, NVIDIA RTX 3090.
- `C:` has only about 31 GB free and must not receive heavyweight SDK/model caches.
- `D:` is the default local location for managed applications, SDKs, models, build
  caches, emulators, and scratch work.
- NAS storage is for immutable candidates, source/model mirrors, cold artifacts,
  receipts, and recoverable backups; latency-sensitive databases and build scratch
  remain local.
- iOS/Xcode execution requires an authorized Mac worker. Windows may orchestrate and
  verify it but cannot replace Xcode or Apple Simulator.

## Selection policy

Popularity is evidence, not the only decision. Each selection is scored on:

- maintenance and stable release cadence;
- useful feature coverage;
- documented API, CLI, SDK, plugin, or headless automation surface;
- open-source license and redistribution constraints;
- Windows/NAS/GPU compatibility;
- structured error reporting and deterministic output;
- project format fidelity and round-trip safety;
- security history and supply-chain verifiability;
- active community and ecosystem interoperability; and
- measured startup, throughput, memory, and artifact quality in Neyvia workflows.

The default is the newest maintained stable release with a usable automation API.
For production workers, an older LTS or mature branch may win when it has materially
better compatibility. Nightly releases are never the default. The exact version and
hash are resolved again on installation day and then pinned in the lock manifest.

Neyvia does not fork a large upstream project merely to claim ownership. It first
builds a native adapter around the upstream API. A maintained patch or fork is
created only when the upstream automation boundary is insufficient, and the delta
must remain small, tested, documented, and rebased.

## Common agent-extension contract

Every tool integration implements the same control plane.

### Manifest

Each installed tool records:

- `toolId`, upstream name, homepage, source repository, license, selected version,
  release channel, download URL, archive/package hash, install path, and worker;
- supported input/output MIME types and project formats;
- operations, typed input/output schemas, examples, limits, destructive flags,
  permission class, expected artifacts, and verifier;
- health probe, version probe, dependency probe, GPU/CPU/RAM/disk estimates, cold and
  warm startup estimates, and concurrency limit;
- session support, cancellation method, timeout policy, retry policy, and recovery
  steps;
- provenance, SBOM, vulnerability scan result, and known compatibility notes; and
- model-facing summary plus deferred detailed documentation.

### Runtime lifecycle

1. Resolve the requested capability to candidate operations.
2. Validate artifacts, workspace scope, permissions, resources, and worker health.
3. Produce a preview or plan for material writes and external side effects.
4. Start or reuse a managed session.
5. Execute a typed operation with bounded paths and arguments.
6. Stream structured lifecycle events and progress.
7. Register source, intermediate, output, log, screenshot/render, and receipt
   artifacts in the artifact graph.
8. Run operation-specific verification.
9. Commit the artifact transaction only when verification passes; otherwise retain
   diagnostics and recover the last good state.
10. Close or return the managed session to its pool.

### Required operation families

Not every tool supports every family, but omissions must be explicit:

- inspect, search, read metadata, extract, and compare;
- create, import, modify, transform, and export;
- preview/render and structured diff;
- validate/lint/test/benchmark;
- batch and parameter sweep;
- session open/status/save/close;
- cancel, retry, resume, checkpoint, undo, and recover;
- enumerate formats, plugins, models, devices, filters, codecs, or drivers;
- resource estimate and health/status; and
- install/update/repair, restricted to the tool-management permission.

### Model discoverability

The model receives a compact capability index first. It can then request:

- matching operations for the current artifact and intent;
- the detailed schema for only the selected operation;
- examples and known limits;
- live worker/tool health and resource availability; and
- verifier expectations before execution.

This avoids placing hundreds of rarely used schemas in every model context while
still making the complete tool surface available on demand.

### Permission boundary

Deep control does not mean unlimited shell access. Operations are separated into:

- read-only inspection;
- workspace-local reversible writes;
- process execution;
- network reads;
- network writes and external side effects;
- device control;
- compute/spend;
- security-assessment actions; and
- administrator/tool-management actions.

All paths are resolved and bounded. Secrets are referenced by credential handle and
never placed in tool arguments, logs, receipts, or committed configuration.

## Selected suites and feature coverage

Versions below are the researched stable candidates on the baseline date. A version
marked “resolve at install” is deliberately not guessed; its official release feed
must be checked and pinned before installation.

### Documents, OCR, office, writing, and publishing — Wave 1

**Poppler**

- Current role: fast PDF metadata, native text, page rendering, fonts, images, and
  bounded page extraction.
- Exposed operations: `info`, `extract_text`, `render_pages`, `extract_images`,
  `list_fonts`, `page_bbox`, and `verify_page_count`.
- Neyvia enhancement: progressive first-page results, page-addressed citations,
  password/permission diagnostics, time and output caps, cached page renders, and
  artifact lineage.

**Tesseract 5.5.2, fallback only**

- Role: reliable CPU OCR and language-pack fallback.
- Useful features: multiple page-segmentation modes, orientation/script detection,
  searchable PDF, hOCR, TSV, ALTO, plain text, confidence/box output, user words,
  user patterns, and trained-data language packs.
- Exposed operations: inspect languages, detect orientation, OCR image/region/page,
  OCR to structured boxes, and benchmark a sample.
- Selection rule: never auto-select while the healthy Paddle GPU path is available.
  Tesseract remains useful for CPU recovery and deterministic hOCR, TSV, ALTO, and
  searchable-PDF export.

**OCRmyPDF 17.8.1**

- Role: preservation-friendly searchable PDF production.
- Useful features: native-text detection; default, skip, redo, and force modes;
  rotation, deskew, cleaning, optimization, PDF/A output, metadata preservation,
  plugins, sidecar text, page selection, and parallel jobs.
- Neyvia enhancement: preflight prevents destructive force mode without preview;
  before/after page renders and text coverage are verified.

**PaddleOCR 3.7.0, PaddleOCR-VL 1.6, and PP-OCRv6 medium**

- Role: primary GPU-accelerated text OCR and complex document intelligence.
- Useful features: unified 50-language PP-OCRv6 recognition,
  document orientation/unwarping,
  handwriting, tables, formulas, charts, seals, layout analysis, reading order,
  structured Markdown/JSON/DOCX workflows, and local pipelines.
- Installed runtime: official PaddlePaddle GPU 3.3.1 CUDA 12.9 wheel, PaddleX
  3.7.2, cuDNN 9.9, and an RTX 3090 worker. Exact package and model-tree hashes are
  recorded in `config/tool_suite_lock.json`.
- Neyvia enhancement: native PDF text first, PP-OCRv6 medium for ordinary scanned
  text, and PaddleOCR-VL 1.6 only for structurally complex pages. Every region or
  block retains page lineage, coordinates, confidence where available, an output
  hash, and readback verification.
- Measured proof: PP-OCRv6 found 27 correct regions on the reference page with
  0.827-second model inference after initialization. The VLM returned 21 ordered
  semantic blocks but took about 54 seconds in a fresh adapter process, so it is an
  escalation path until a resident or llama.cpp-backed worker removes startup cost.

**LibreOffice**

- Installed track: LibreOffice Portable 26.2.4.2. The 25.8 mature branch remains a
  compatibility fallback for a document or extension that fails a measured
  round-trip gate.
- Role: editable word-processing, spreadsheet, presentation, and drawing documents.
- Useful features: DOCX/XLSX/PPTX and ODF import/export, PDF export, tracked changes,
  comments, compare/merge, styles, fields, formulas, charts, pivots, macros,
  templates, print layout, UNO component model, headless filters, Python/Java/C++
  bindings, and document events.
- Current Neyvia integration: isolated headless profiles, allowlisted conversion and
  PDF filters, typed version/convert/render operations, atomic output, independent
  PDF verification, editable-output round-trip verification, and artifact lineage.
- Next integration: a persistent isolated UNO listener and warm worker pool, typed
  document/range/slide edits, tracked-edit transactions, formula recalculation, and
  filter enumeration.
- Stability decision: use UNO for structured edits and headless filters for batch
  conversion; GUI automation is a last-mile visual check, not the data API.

**Pandoc 3.10.1**

- Role: semantic conversion and publishing pipeline.
- Useful features: broad markup/document formats, citations and citeproc,
  bibliography/CSL, templates, metadata, sections, tables, footnotes, math, reference
  documents, tracked-change handling, Lua filters, custom readers/writers, and a
  server mode.
- Neyvia enhancement: precompiled format profiles, sandboxed Lua filters, reference
  document selection, AST inspection/diff, and round-trip loss reporting.

**LanguageTool**

- Version: resolve and pin from the official release at installation.
- Role: local multilingual spelling, grammar, typography, terminology, and style.
- Useful features: more than 20 languages, local HTTP server, Java embedding, custom
  XML/Java rules, n-grams, style and tone categories, disabled/enabled rule control,
  user dictionaries, and LaTeX-aware checking.
- Neyvia enhancement: project glossary and style-guide layers, explanation and
  confidence per suggestion, range-addressed accept/reject, false-positive memory,
  and protected spans for code, citations, names, and quoted text.

**Argos Translate plus LibreTranslate 1.9.6**

- Role: offline translation engine plus a self-hosted API/session boundary.
- Useful features: installable language packages, CTranslate2/OpenNMT inference,
  pivot translation, GPU option, files/HTML, language detection through the service,
  and a documented API.
- Neyvia enhancement: translation memory, protected terminology, sentence/paragraph
  alignment, source-target range links, glossary checks, back-translation sampling,
  reviewer decisions, and model/provider quality comparison.
- License note: Argos is MIT; LibreTranslate is AGPL-3.0. Distribution and network
  deployment obligations are recorded before shipping.

**MiKTeX/TeX Live plus latexmk**

- Role: reproducible LaTeX compilation and bibliography/index tooling.
- Useful features: incremental compilation, engine selection, package resolution,
  bibliography, indexes/glossaries, SyncTeX, diagnostics, and PDF output.
- Neyvia enhancement: isolated package cache, allowlisted shell escape (off by
  default), error-to-source mapping, render verification, and reproducible source
  bundles.

**Zotero 9.0.6**

- Role: reference library, metadata, attachments, annotations, notes, collections,
  duplicate management, document read-aloud, and citations in
  Word/LibreOffice/Google Docs.
- Integration: local API/translation services where supported, citation-key and
  attachment provenance, annotation-to-page links, collection-scoped retrieval, and
  explicit confirmation for library writes.

Wave 1 covers:

- `document.fast-ocr`, `document.pdf-analysis`,
  `document.office-conversion`, `document.latex-production`;
- `writing.manuscript-authoring`, `writing.editorial-redline`,
  `literature.critical-reading`, `writing.translation-alignment`;
- `office.spreadsheet-analysis`, `office.spreadsheet-edit`,
  `office.presentation-authoring`, `office.report-authoring`; and
- document-dependent parts of research, education, business, fashion, and maker
  packs.

### Browser, devices, and application engineering — Wave 2

**Playwright**

- Chromium, Firefox, WebKit, branded-browser channels, isolated contexts, locators,
  frames, downloads/uploads, network interception, authentication state, traces,
  screenshots, video, mobile/device emulation, locale/timezone/geolocation,
  permissions, accessibility snapshots, and experimental Android Chrome/WebView.
- Neyvia adds named permissioned sessions, semantic UI observations, locator repair,
  trace/video/screenshot receipts, responsive matrices, and an explicit external
  side-effect gate.

**Android command-line tools, Emulator, Gradle, and JDK**

- Build, bundle, install, launch, package/activity inspection, logcat, screenshots,
  recordings, file transfer, port forwarding, input, UI hierarchy, snapshots,
  virtual sensors/network/battery/location, and multiple form factors.
- SDKs, system images, Gradle caches, and AVDs live on `D:`. License acceptance and
  exact packages are captured in the install receipt.

**Appium 3 plus UiAutomator2/Espresso**

- Cross-platform WebDriver API, driver/plugin ecosystem, native/hybrid/web apps,
  Android/TV/Wear, accessibility identifiers, gestures, device state, and test
  framework interoperability.
- Neyvia pins each driver separately and exposes driver capability schemas rather
  than an arbitrary desired-capabilities map.

**scrcpy 4.1**

- Low-latency Android display/control, audio, recording, virtual displays, clipboard,
  camera, HID/OTG, screen-off operation, and configurable codecs/bitrate/resolution.
- Neyvia uses it for operator-visible supervision and recordings while ADB/Appium
  remain the structured control plane.

**Software suite**

- Git and worktrees for source control; ripgrep and language servers for navigation;
  tree-sitter for syntax; Docker/WSL isolated services; Playwright for UI proof;
  PostgreSQL plus DuckDB for durable and analytical data; project-native build,
  lint, type, unit, integration, and packaging commands.
- Typed operations cover repository inspection/diff, dependency graph, build/test,
  database schema/migration, service lifecycle, logs, profiling, release artifacts,
  SBOM, and rollback. No generic “run any command” operation is presented to models.

**Apple remote runner**

- Xcode, `xcodebuild`, Simulator, XCTest/XCUITest, signing checks, screenshots,
  recordings, logs, accessibility tree, and build artifacts run only on an
  authorized Mac.
- Windows dispatches a signed, content-addressed source package and receives a
  signed receipt. No iOS success is reported from a browser approximation.

Wave 2 covers all four software capabilities and all four device capabilities.
Godot is the open-source default application/game builder; Unity support remains an
optional compatibility adapter for existing licensed Unity projects.

### Research, education, data, AI, and ML — Wave 3

**DuckDB 1.5.4 and Polars**

- DuckDB: embedded analytical SQL, CSV/JSON/Parquet, Arrow, local/remote files,
  spatial extension, Excel extension, query plans/profiling, and Python/Rust/Go/JS
  clients.
- Polars: eager/lazy frames, streaming larger-than-memory work, multithreading, SIMD,
  Arrow, query optimization, SQL, and Python/Rust/Node/R bindings.
- Neyvia exposes typed table/query/plan/profile/export operations, read-only query by
  default, row/byte/time caps, deterministic snapshots, formula reconciliation, and
  chart-ready artifacts.

**Scientific Python and R**

- NumPy, SciPy, pandas/Polars, statsmodels, scikit-learn, SymPy, Matplotlib,
  Seaborn/Plotly, Jupyter, and selected R/Bioconductor packages when a workflow
  requires them.
- Every analysis captures environment lock, seed, assumptions, code/notebook,
  dataset hash, warnings, figures, tables, and reproducibility rerun.

**Zotero plus GROBID and source APIs**

- Bibliographic library, PDF structure/reference extraction, metadata normalization,
  citation graph, evidence matrix, duplicate resolution, and page-grounded notes.
- External source retrieval is provider-specific and citation-preserving; credentials
  and terms are not hidden behind a generic search scraper.

**Anki**

- Note types, templates, media, tags, decks, scheduling/spaced repetition, imports,
  exports, and add-on hooks.
- Neyvia creates source-linked notes with stable IDs and updates rather than
  duplicating cards. Review-history writes require explicit authorization.

**PyTorch and Hugging Face ecosystem**

- Transformers, Datasets, Tokenizers, Accelerate, PEFT, TRL, Evaluate, Safetensors,
  ONNX/Optimum where useful, plus MLflow or Trackio for experiments.
- Capabilities include dataset validation/versioning, training/fine-tuning,
  checkpoint/resume, quantization/export, batch inference, standardized evaluation,
  safety evaluation, resource estimation, telemetry, and model cards.
- Local RTX 3090 work is admitted by measured VRAM; jobs exceeding it route to an
  approved NAS/GPU worker or remain planned, never silently downgraded.

Wave 3 covers the four research/science, four education, and four AI/ML capabilities.

### Media, 3D, games, maker, fashion, and niche domains — Wave 4

**FFmpeg**

- Probe, decode/encode/transcode, trim/concat, complex filter graphs, subtitles,
  overlays, scaling, color management, audio mixing, loudness normalization,
  hardware acceleration, devices, streaming/package formats, thumbnails, and
  metadata.
- Neyvia compiles typed timeline/filter graphs, estimates output, previews short
  segments, records exact codecs/filters, and verifies duration, streams, loudness,
  frame rate, color metadata, and decode integrity.

**ImageMagick plus a nondestructive raster editor**

- Format conversion, resize/crop/rotate, compositing, masks, channels, morphology,
  color profiles/spaces, HDRI, metadata, batch pipelines, and resource policies.
- GIMP is used where a layered interactive source document is required; ImageMagick
  handles deterministic batch transforms. Operations always retain the editable
  source and before/after preview.

**Blender**

- Candidate: 5.1.1 current; 4.5 LTS for production compatibility through July 2027.
- Modeling, sculpting, Geometry Nodes, materials, UVs, rigging, animation,
  simulation, compositing, Cycles/Eevee rendering, video sequence editing, Python
  API, headless rendering, and glTF/USD interoperability.
- Neyvia uses a persistent Blender Python bridge with scene/object/material schemas,
  dependency-graph updates, viewport/render previews, scene diffs, validation,
  optimization, and transactional `.blend` saves.

**Godot 4.7.1**

- Open-source default for scene-based application/game building, 2D/3D, GDScript and
  C#, animation, physics, navigation, UI, audio, networking, import/export,
  automated/headless execution, and extensibility.
- Unity integration is retained only for projects that require Unity; it must use the
  licensed official editor and a version pinned by the project.

**KiCad 10.0.5**

- Schematic capture, PCB layout, libraries, rules, simulation, 3D viewer,
  manufacturing outputs, BOM/position data, ERC/DRC, command-line automation, and
  the language-agnostic IPC API with official Python bindings.
- Neyvia uses IPC for structured edits and CLI for checks/exports; every change gets
  electrical/rule review and rendered board/schematic proof.

**FreeCAD 1.1 and OpenSCAD**

- FreeCAD: parametric Part/Part Design, Sketcher, assemblies, TechDraw, FEM, CAM,
  materials, import/export, Python API, and headless workflows.
- OpenSCAD: deterministic code-defined solids, CLI rendering/export, parameter
  sweeps, animation, and STL/3MF/PDF/PNG outputs.
- Neyvia chooses FreeCAD for interactive parametric/assembly work and OpenSCAD for
  compact generative parts. Dimension, tolerance, mesh, and manufacturability checks
  are mandatory.

**ROS 2 and Gazebo**

- Robot graphs, messages/services/actions, bags, transforms, launch/config,
  visualization, simulation, sensors, physics, control, and repeatable scenarios.
- These run in a pinned WSL/container worker unless a project already provides a
  compatible native environment.

**Inkscape, Scribus, and Seamly2D**

- Inkscape: SVG/vector drawing, paths, text, clones, filters, extensions, and CLI
  export.
- Scribus: print layout, master pages, styles, preflight, color management, and PDF
  production.
- Seamly2D/SeamlyMe: measurement-driven garment pattern drafting and sizing.
- The Seamly project’s current maintenance state and exact release must be verified
  before selection; Valentina remains the evaluated alternative. Fashion compliance
  fields remain jurisdiction-specific and require sourced rules.

**Niche suites**

- Genealogy: Gramps-compatible graph/import/export and citation/provenance model.
- Astronomy: Astropy for coordinates/tables/FITS, Stellarium for planning, and
  Siril-compatible calibration/stacking where image workflows require it.
- Culinary: structured recipe schema, unit conversion, scaling, nutrition data from
  a declared source, costing, shopping lists, timers, and test logs.
- Custom packs: schema editor, vocabulary, examples, templates, permissions,
  verifiers, tests, signed package, and progressive model documentation.

Wave 4 covers business/design, media, 3D/game, maker, fashion, and niche packs.

### Authorized security assessment and hardening — Wave 5

Security tools are available only for authorized targets and defined lab or workspace
boundaries. Read-only discovery, threat modeling, detection, hardening, and
retesting are the default path.

**Trivy**

- Repository, filesystem, image, and Kubernetes scanning for vulnerabilities,
  misconfiguration, secrets, licenses, SBOMs, and multiple report formats including
  JSON and SARIF.

**Semgrep**

- Source-aware static analysis, custom rules, data-flow/taint features available in
  the selected edition, supply-chain integration where licensed, CI output, and
  autofix only when reviewed.
- Exact community/paid feature boundaries and current release must be verified
  before the manifest is pinned.

**OWASP ZAP 2.17.0**

- OpenAPI/GraphQL import, traditional and client spider, passive and active scans,
  authentication/session handling, AJAX/browser support, automation framework,
  add-ons, API, policies, and reports.
- Active scans require target authorization and a preview of scope, methods, rate,
  and excluded routes.

**Ghidra**

- Multi-architecture disassembly, decompilation, assembly, symbols/types, graphing,
  patch analysis, scripting, headless analysis, and Java/Python extensions.
- Samples execute only in an isolated analysis worker. Static inspection does not
  imply permission to run a binary.

**Mobile and runtime analysis**

- MobSF and Frida are evaluated for authorized mobile packages and lab devices.
  Their exact versions, deployment isolation, and operation boundaries must be
  verified before enabling them.

Wave 5 covers threat modeling, AI red-team evaluation, application assessment,
reverse engineering, remediation, and retest. Findings always include evidence,
severity rationale, affected artifact/version, remediation, and a clean retest
receipt.

## Capability-to-suite matrix

| Pack | Capability IDs | Primary suite | Wave |
| --- | --- | --- | ---: |
| Research/science | `research.literature-review`; `science.experiment-design`; `science.statistical-analysis`; `science.simulation-study` | Zotero/GROBID, scientific Python/R, DuckDB/Polars | 3 |
| Education | `learning.adaptive-tutorial`; `learning.flashcards`; `learning.graded-assessment`; `learning.curriculum-plan` | source graph, Anki, document suite, assessment engine | 3 |
| Literature/publishing | `writing.manuscript-authoring`; `writing.editorial-redline`; `literature.critical-reading`; `writing.translation-alignment` | LibreOffice UNO, Pandoc, LanguageTool, Argos/LibreTranslate, Zotero | 1 |
| Documents/OCR | `document.fast-ocr`; `document.pdf-analysis`; `document.office-conversion`; `document.latex-production` | Poppler, Tesseract, OCRmyPDF, PaddleOCR, LibreOffice, Pandoc, LaTeX | 1 |
| Office/data | `office.spreadsheet-analysis`; `office.spreadsheet-edit`; `office.presentation-authoring`; `office.report-authoring` | LibreOffice UNO, DuckDB/Polars, Pandoc | 1/3 |
| Business/design | `communication.campaign-plan`; `communication.message-drafting`; `design.card-and-invitation`; `design.label-and-packaging` | document suite, Inkscape, Scribus, image pipeline | 4 |
| Software/infrastructure | `software.application-engineering`; `software.network-architecture`; `software.database-engineering`; `software.delivery-pipeline` | Git/language tools, Docker/WSL, PostgreSQL/DuckDB, project-native toolchains, Playwright | 2 |
| AI/ML | `ai.assistant-architecture`; `ai.dataset-engineering`; `ai.model-training`; `ai.model-benchmarking` | PyTorch, Hugging Face, experiment/evaluation stack | 3 |
| Security/red team | `security.threat-model`; `security.ai-red-team`; `security.application-assessment`; `security.reverse-engineering`; `security.remediate-and-retest` | Trivy, Semgrep, ZAP, Ghidra, isolated mobile/runtime tools | 5 |
| Media | `media.photo-editing`; `media.image-generation`; `media.video-production`; `media.audio-production` | ImageMagick/GIMP, provider/model adapters, FFmpeg, transcription/audio tools | 4 |
| 3D/game | `three-d.blender-scene`; `game.unity-project`; `game.mod-development`; `three-d.runtime-export` | Blender, Godot, optional project-pinned Unity | 4 |
| Maker/engineering | `maker.electronics-design`; `maker.cad-fabrication`; `maker.robotics-system`; `maker.repair-guidance` | KiCad, FreeCAD, OpenSCAD, ROS 2/Gazebo, evidence pipeline | 4 |
| Fashion | `fashion.collection-concept`; `fashion.pattern-specification`; `fashion.label-system`; `fashion.production-pack` | Inkscape, Scribus, Blender, verified Seamly2D/Valentina path | 4 |
| Device/app lab | `device.android-test`; `device.apple-remote-test`; `device.browser-session`; `device.responsive-matrix` | Android SDK/Emulator, Appium, scrcpy, Playwright, remote Xcode | 2 |
| Niche/custom | `niche.genealogy-research`; `niche.astronomy-observation`; `niche.culinary-development`; `niche.custom-pack-authoring` | Gramps, Astropy/Stellarium/Siril, recipe schema, pack SDK | 4 |

## Installation and storage layout

No installer is run until its manifest entry has an official source, license, version,
hash/signature strategy, disk estimate, and uninstall/repair procedure.

Proposed managed roots:

```text
D:\Neyvia\apps\<tool>\<version>\
D:\Neyvia\sdk\<tool>\<version>\
D:\Neyvia\models\<provider>\<model>\<revision>\
D:\Neyvia\cache\<tool>\
D:\Neyvia\workers\<worker-id>\
D:\Neyvia\scratch\<run-id>\
D:\Neyvia\modules\<publisher>\<module>\<version>\
D:\Neyvia\module-data\<module>\<profile>\
D:\Neyvia\module-cache\<module>\
D:\Neyvia\module-logs\<module>\
Y:\projects\syntelos\source-mirrors\
Y:\projects\syntelos\model-mirrors\
Y:\projects\syntelos\module-registry\
Y:\projects\syntelos\module-cache\
Y:\projects\syntelos\work-in-progress\
Y:\projects\syntelos\candidates\
```

Environment variables are injected into managed worker processes, not permanently
overwritten system-wide unless the application requires it. Large caches such as
Android, Gradle, Hugging Face, Paddle, PyTorch, browsers, and compilation outputs are
redirected to `D:`. Installers may not write secrets into configuration or logs.

Each install produces:

- tool lock entry and package/archive hash;
- source/license/release metadata;
- before/after disk use;
- version and health output;
- SBOM or package inventory where available;
- a minimal real operation and verifier result;
- uninstall/repair instructions; and
- an immutable NAS receipt after verification.

## Implementation waves and gates

### Foundation gate

- Add tool-lock and operation-manifest schemas.
- Add health/resource/session/install registries.
- Add structured event, artifact, receipt, cancellation, and recovery contracts.
- Add compact discovery and deferred operation documentation.
- Acceptance: a model can discover, inspect, invoke, cancel, verify, and explain one
  reference integration without receiving or constructing a raw command.

### Wave 1 gate

- Install and deeply integrate the document suite.
- Real workflow: ingest mixed native/scanned PDFs, OCR difficult pages, correct text,
  translate selected ranges with alignment, redline a DOCX, recalculate an XLSX,
  render a PPTX, compile LaTeX, and publish a verified PDF/source bundle.
- Acceptance: page/range/slide provenance survives the full chain; editable source,
  previews, differences, and verification receipts are visible.

Current progress: Pandoc and LibreOffice conversion/rendering pass their bounded
execution gates. OCR, language correction, translation alignment, UNO structured
editing, spreadsheet recalculation, presentation editing, and the complete mixed
document workflow remain open.

### Modular platform gate

- Publish one schema-valid module from the workspace, package it as an immutable OCI
  artifact, sign it, verify its SBOM and requested permissions, and install it into a
  staging root without patching Neyvia core.
- Activate only after an isolated health and user-flow test; switch a versioned
  pointer atomically and retain the previous version for rollback.
- Support four module classes: Wasm capabilities, isolated services, full
  applications with optional desktop/mobile/web surfaces, and content packs.
- Add a local-first distribution layer using ORAS/OCI plus verified P2P cache
  transport. Peer retrieval never replaces publisher identity, signature, policy,
  or malware verification.
- Prove one nearby transfer, one private-mesh remote transfer, one encrypted
  multi-device message/link flow, and one opaque password-handle flow without
  exposing a secret to model context or chat history.
- Acceptance: an incompatible, unsigned, over-permissioned, unhealthy, or
  path-traversing module cannot activate; uninstall and rollback do not modify the
  live core application or another module's data.

The current code establishes the v1 manifest schema, archive inspection, immutable
hash checks, traversal/symlink/expansion defenses, permission consistency checks,
and a staging-only install plan. The local mesh contract, Nearby Send planning,
folder-sync control, encrypted Matrix transport foundation, opaque secret broker,
local BLAKE3 CAS, allowlisted Iroh fetch, and supervised Iroh provider lifecycle are
implemented and evidence-backed. Production identity enrollment, private relay,
registry publication, signature-backed runtime activation, real multi-device
accounts, and distance-sensitive replication proofs remain open.

Regression suite: the supervised provider slice passes 70 focused Python contract
and integration tests, Rust formatting, release clippy with warnings denied, the
optimized release build, and a real publish, serve, fetch, reload, restart, and stop
flow; the broader capability, SDK, web-backend, install-profile, conversation-store,
and conversation-navigation selection passes 245 tests, including exact-ID SQLite
replay, concurrent duplicate coalescing, paged durable history, and Web Push key
generation, and the frontend production build and real browser paging flow pass, so
there is no runtime regression.

Full-vision completion is now estimated at about 28.5 percent, up from 27 percent
because private object publication is no longer a manual sidecar process: it is a
typed, approval-gated, hash-pinned, demand-started, rollback-safe service available
through the capability registry, SDK, and web command bridge. The estimate remains
conservative because no production peer, relay, Matrix account, vault account, or
NAS publication was activated, and the largest remaining bodies of work are the
private Tailscale-like control plane, real multi-device chat and password delivery,
AirDrop-like discovery and transfer, marketplace signing and distribution, seamless
desktop/mobile app building and emulation, modern OCR model evaluation and runtime,
cross-domain dependency optimization, automatic dependency updates, and the
operator-facing one-button signed release updater.

The mobile reconnect path also avoids repeated model work when the same submitted
assistant-turn ID arrives again. The first request persists compact replay metadata
with the exact legacy user and assistant turn IDs; concurrent duplicates wait only
for that matching turn while independent chats remain parallel. A 200-sample local
replay benchmark measured 1.654 ms p50, 2.336 ms p95, and 2.609 ms maximum.
Opening durable history now fetches only the newest 80 turns and exposes an exact
cursor for older pages. On a 1,000-turn, 2.23 MB conversation this reduced the
initial response to 179 KB, about 92 percent smaller, with a 3.359 ms p50 and 4.311
ms p95 store read. A real browser flow opened 80 of 260 turns and expanded to 160
of 260 without duplicates. The remaining mobile-loading work includes frontend
route and component splitting because the production shell and CSS chunks are still
larger than the intended phone budget.

### Wave 2 gate

- Install Android/browser/app-engineering suites and connect the authorized Mac
  worker when available.
- Real workflow: build an application, start services, open it in browsers, complete
  responsive user flows, build/install Android, interact and record, capture logs,
  and return a single cross-platform proof packet.
- Acceptance: no “passed” state without trace, recording/screenshot, logs, build
  artifact, and verifier result.

### Wave 3 gate

- Install data/research/education/ML suites.
- Real workflow: build a cited evidence set, validate a dataset, run reproducible
  statistics, create source-linked study material, train/evaluate a small model, and
  reproduce the result from the lock and receipt.

### Wave 4 gate

- Install media/3D/game/maker/fashion/niche suites in storage-aware batches.
- Each domain must complete one editable-source-to-verified-output workflow.

### Wave 5 gate

- Install security tools in isolated workers.
- Real workflow: authorized scoped assessment, evidence-backed findings, remediation,
  and clean retest without crossing the declared boundary.

### Production gate

- All 61 capabilities have at least one native operation path or an explicit,
  evidence-backed platform blocker.
- No capability reports availability based only on finding an executable.
- Tool versions, licenses, operations, limits, and worker health are visible to the
  agent and operator.
- Failures are honest, cancellable, diagnosable, and recoverable.
- Relevant unit/contract tests, build/type checks, and user-like interaction tests
  pass.
- A complete immutable NAS candidate is hash-verified. Publishing to the live release
  boundary remains an explicit separate action.

## Alternatives retained

- Containerize a tool when isolation and reproducibility outweigh GUI/session
  integration. Prefer native managed sessions for LibreOffice, Blender, Android, and
  other interactive applications.
- Use a current branch for new features or an LTS/mature branch for compatibility.
  The manifest records the reason.
- Prefer upstream plus a Neyvia adapter. Maintain a fork only after a documented API
  gap and a costed maintenance decision.
- Use Godot for new open-source game/application work; retain Unity only for projects
  whose format, assets, or licensing require it.
- Use local/offline language and document processing by default; permit external
  providers only through explicit provider, privacy, spend, and provenance controls.

## Official research sources

Primary documentation checked for this baseline:

- Tesseract releases and source: <https://github.com/tesseract-ocr/tesseract/releases>
- OCRmyPDF documentation: <https://ocrmypdf.readthedocs.io/>
- PaddleOCR source and documentation: <https://github.com/PaddlePaddle/PaddleOCR>
- LibreOffice releases: <https://www.libreoffice.org/download/release-notes/>
- LibreOffice SDK/UNO: <https://api.libreoffice.org/>
- LibreOffice command-line help:
  <https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html>
- Pandoc releases: <https://github.com/jgm/pandoc/releases>
- LanguageTool source: <https://github.com/languagetool-org/languagetool>
- LanguageTool development documentation: <https://dev.languagetool.org/>
- Argos Translate source: <https://github.com/argosopentech/argos-translate>
- LibreTranslate source: <https://github.com/LibreTranslate/LibreTranslate>
- Zotero documentation: <https://www.zotero.org/support/>
- Playwright documentation: <https://playwright.dev/docs/intro>
- Android Emulator documentation:
  <https://developer.android.com/studio/run/emulator>
- Appium documentation: <https://appium.io/docs/en/latest/>
- scrcpy source: <https://github.com/Genymobile/scrcpy>
- DuckDB documentation: <https://duckdb.org/docs/stable/>
- Polars documentation: <https://docs.pola.rs/>
- Anki source and releases: <https://github.com/ankitects/anki/releases>
- FFmpeg documentation: <https://ffmpeg.org/documentation.html>
- ImageMagick documentation: <https://imagemagick.org/script/command-line-processing.php>
- Blender releases: <https://www.blender.org/download/releases/>
- Blender Python API: <https://docs.blender.org/api/current/>
- Godot documentation: <https://docs.godotengine.org/en/stable/>
- KiCad releases: <https://www.kicad.org/blog/>
- KiCad IPC API: <https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/>
- FreeCAD releases: <https://blog.freecad.org/>
- OpenSCAD documentation: <https://openscad.org/documentation.html>
- Trivy source: <https://github.com/aquasecurity/trivy>
- OWASP ZAP documentation: <https://www.zaproxy.org/docs/>
- Ghidra source: <https://github.com/NationalSecurityAgency/ghidra>
- Tauri releases: <https://github.com/tauri-apps/tauri/releases>
- Wasmtime documentation: <https://docs.wasmtime.dev/>
- ORAS releases: <https://github.com/oras-project/oras/releases>
- Cosign signing and verification: <https://docs.sigstore.dev/cosign/>
- NetBird source and releases: <https://github.com/netbirdio/netbird>
- LocalSend source and releases: <https://github.com/localsend/localsend>
- Syncthing releases: <https://github.com/syncthing/syncthing/releases>
- Kubo releases: <https://github.com/ipfs/kubo/releases>
- Matrix Synapse releases: <https://github.com/element-hq/synapse/releases>
- Matrix Rust SDK releases: <https://github.com/matrix-org/matrix-rust-sdk/releases>
- Element Web releases: <https://github.com/element-hq/element-web/releases>
- Vaultwarden releases: <https://github.com/dani-garcia/vaultwarden/releases>

The source list is a verification trail, not a frozen recommendation. Every exact
release is rechecked against the official source immediately before installation.
