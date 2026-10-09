/**
 * Inventory-driven tool visuals — backend IDs from docs/NEYVIA_TOOL_ICON_ANIMATION_COVERAGE.md.
 * Each id gets a DISTINCT icon + animationClass. Stubs stay honest (no fake success).
 */

function tv(icon, animationClass, idle, opts = {}) {
  const chipClass = opts.chipClass || animationClass.replace("neyvia-tool-anim-", "neyvia-chip-");
  return Object.freeze({
    icon,
    animationClass,
    chipClass,
    category: opts.category || "inventory",
    stub: opts.stub !== false,
    labels: Object.freeze({
      idle,
      call: opts.call || `${idle}…`,
      running: opts.running || "Running",
      success: opts.success || "Ready",
      error: opts.error || "Not connected",
      open: opts.open,
      composing: opts.composing,
    }),
    aliases: Object.freeze(opts.aliases || []),
  });
}

/** Capability packs (61) + managed suite + progressive + ui.* + mcp.* + adapters + MCP starters. */
export const NEYVIA_INVENTORY_TOOL_VISUALS = Object.freeze({
  // —— domain.research-science ——
  "research.literature-review": tv("BookMarked", "neyvia-tool-anim-lit-review", "Literature review", {
    category: "research",
    running: "Reviewing literature",
    aliases: ["literature-review"],
  }),
  "science.experiment-design": tv("FlaskConical", "neyvia-tool-anim-experiment", "Experiment design", { category: "research" }),
  "science.statistical-analysis": tv("ChartColumn", "neyvia-tool-anim-stats", "Statistical analysis", { category: "research" }),
  "science.simulation-study": tv("Orbit", "neyvia-tool-anim-simulation", "Simulation study", { category: "research" }),

  // —— education ——
  "learning.adaptive-tutorial": tv("GraduationCap", "neyvia-tool-anim-tutorial", "Adaptive tutorial", { category: "education" }),
  "learning.flashcards": tv("Layers", "neyvia-tool-anim-flashcards", "Flashcards", { category: "education" }),
  "learning.graded-assessment": tv("ClipboardCheck", "neyvia-tool-anim-assessment", "Graded assessment", { category: "education" }),
  "learning.curriculum-plan": tv("Map", "neyvia-tool-anim-curriculum", "Curriculum plan", { category: "education" }),

  // —— writing / translate / grammar ——
  "writing.manuscript-authoring": tv("PenLine", "neyvia-tool-anim-manuscript", "Manuscript authoring", {
    category: "writing",
    composing: "Authoring…",
  }),
  "writing.editorial-redline": tv("Highlighter", "neyvia-tool-anim-redline", "Editorial redline", {
    category: "grammar",
    aliases: ["redline", "editorial-redline"],
  }),
  "literature.critical-reading": tv("BookOpen", "neyvia-tool-anim-critical-read", "Critical reading", { category: "literature" }),
  "writing.translation-alignment": tv("Languages", "neyvia-tool-anim-translation-align", "Translation alignment", {
    category: "translate",
    aliases: ["translation-alignment"],
  }),

  // —— documents / ocr / latex ——
  "document.fast-ocr": tv("ScanText", "neyvia-tool-anim-ocr", "Fast OCR", {
    category: "ocr",
    aliases: ["ocr", "fast-ocr"],
  }),
  "document.pdf-analysis": tv("FileText", "neyvia-tool-anim-pdf-analysis", "PDF analysis", {
    category: "pdf",
    aliases: ["pdf-analysis"],
  }),
  "document.office-conversion": tv("FileType", "neyvia-tool-anim-office-convert", "Office conversion", { category: "office" }),
  "document.latex-production": tv("Sigma", "neyvia-tool-anim-latex", "LaTeX production", {
    category: "latex",
    aliases: ["latex"],
  }),

  // —— office ——
  "office.spreadsheet-analysis": tv("Table2", "neyvia-tool-anim-sheet-analysis", "Spreadsheet analysis", { category: "office" }),
  "office.spreadsheet-edit": tv("Sheet", "neyvia-tool-anim-sheet-edit", "Spreadsheet edit", { category: "office" }),
  "office.presentation-authoring": tv("Presentation", "neyvia-tool-anim-pptx", "Presentation authoring", { category: "office" }),
  "office.report-authoring": tv("FileBarChart", "neyvia-tool-anim-report", "Report authoring", { category: "office" }),

  // —— communication / design ——
  "communication.campaign-plan": tv("Megaphone", "neyvia-tool-anim-campaign", "Campaign plan", { category: "communication" }),
  "communication.message-drafting": tv("Mail", "neyvia-tool-anim-message-draft", "Message drafting", { category: "communication" }),
  "design.card-and-invitation": tv("IdCard", "neyvia-tool-anim-card-design", "Card & invitation", { category: "design" }),
  "design.label-and-packaging": tv("Tag", "neyvia-tool-anim-label-design", "Label & packaging", { category: "design" }),

  // —— software ——
  "software.application-engineering": tv("AppWindow", "neyvia-tool-anim-app-eng", "Application engineering", { category: "software" }),
  "software.network-architecture": tv("Network", "neyvia-tool-anim-network", "Network architecture", { category: "software" }),
  "software.database-engineering": tv("Database", "neyvia-tool-anim-database", "Database engineering", { category: "software" }),
  "software.delivery-pipeline": tv("GitBranch", "neyvia-tool-anim-pipeline", "Delivery pipeline", { category: "software" }),

  // —— ai / ml ——
  "ai.assistant-architecture": tv("Bot", "neyvia-tool-anim-ai-arch", "AI assistant architecture", { category: "ai" }),
  "ai.dataset-engineering": tv("DatabaseZap", "neyvia-tool-anim-dataset", "Dataset engineering", { category: "ai" }),
  "ai.model-training": tv("BrainCircuit", "neyvia-tool-anim-train", "Model training", { category: "ai" }),
  "ai.model-benchmarking": tv("Gauge", "neyvia-tool-anim-benchmark", "Model benchmarking", { category: "ai" }),

  // —— security ——
  "security.threat-model": tv("ShieldAlert", "neyvia-tool-anim-threat", "Threat model", { category: "security" }),
  "security.ai-red-team": tv("Swords", "neyvia-tool-anim-red-team", "AI red-team", { category: "security" }),
  "security.application-assessment": tv("ShieldCheck", "neyvia-tool-anim-appsec", "App security assessment", { category: "security" }),
  "security.reverse-engineering": tv("Binary", "neyvia-tool-anim-re", "Reverse engineering", { category: "security" }),
  "security.remediate-and-retest": tv("ShieldPlus", "neyvia-tool-anim-remediate", "Remediate & retest", { category: "security" }),

  // —— media ——
  "media.photo-editing": tv("ImagePlus", "neyvia-tool-anim-photo-edit", "Photo editing", { category: "media" }),
  "media.image-generation": tv("Image", "neyvia-tool-anim-img-gen", "Image generation", { category: "media" }),
  "media.video-production": tv("Clapperboard", "neyvia-tool-anim-video-prod", "Video production", { category: "media" }),
  "media.audio-production": tv("Headphones", "neyvia-tool-anim-audio-prod", "Audio production", { category: "media" }),

  // —— 3d / games ——
  "three-d.blender-scene": tv("Boxes", "neyvia-tool-anim-blender", "Blender scene", {
    category: "design/3d",
    aliases: ["blender"],
  }),
  "game.unity-project": tv("Gamepad2", "neyvia-tool-anim-unity", "Unity project", { category: "games" }),
  "game.mod-development": tv("Puzzle", "neyvia-tool-anim-mod", "Game mod development", { category: "games" }),
  "three-d.runtime-export": tv("BoxSelect", "neyvia-tool-anim-3d-export", "3D runtime export", { category: "design/3d" }),

  // —— maker ——
  "maker.electronics-design": tv("CircuitBoard", "neyvia-tool-anim-electronics", "Electronics design", { category: "maker" }),
  "maker.cad-fabrication": tv("Ruler", "neyvia-tool-anim-cad", "CAD & fabrication", {
    category: "maker",
    aliases: ["cad"],
  }),
  "maker.robotics-system": tv("Bot", "neyvia-tool-anim-robotics", "Robotics system", { category: "maker" }),
  "maker.repair-guidance": tv("Wrench", "neyvia-tool-anim-repair", "Repair guidance", { category: "maker" }),

  // —— fashion ——
  "fashion.collection-concept": tv("Shirt", "neyvia-tool-anim-fashion", "Fashion collection", { category: "fashion" }),
  "fashion.pattern-specification": tv("Scissors", "neyvia-tool-anim-pattern", "Pattern specification", { category: "fashion" }),
  "fashion.label-system": tv("Tag", "neyvia-tool-anim-fashion-label", "Clothing label system", { category: "fashion" }),
  "fashion.production-pack": tv("Package", "neyvia-tool-anim-fashion-pack", "Fashion production pack", { category: "fashion" }),

  // —— device lab ——
  "device.android-test": tv("Smartphone", "neyvia-tool-anim-android", "Android emulator test", { category: "device" }),
  "device.apple-remote-test": tv("TabletSmartphone", "neyvia-tool-anim-apple", "Apple Simulator test", { category: "device" }),
  "device.browser-session": tv("Globe2", "neyvia-tool-anim-browser-session", "Browser session", { category: "browser" }),
  "device.responsive-matrix": tv("LayoutGrid", "neyvia-tool-anim-responsive", "Responsive matrix", { category: "browser" }),

  // —— niche ——
  "niche.genealogy-research": tv("GitFork", "neyvia-tool-anim-genealogy", "Genealogy research", { category: "niche" }),
  "niche.astronomy-observation": tv("MoonStar", "neyvia-tool-anim-astronomy", "Astronomy observation", { category: "niche" }),
  "niche.culinary-development": tv("Utensils", "neyvia-tool-anim-culinary", "Culinary development", { category: "niche" }),
  "niche.custom-pack-authoring": tv("PackagePlus", "neyvia-tool-anim-pack-author", "Custom pack authoring", { category: "orchestration" }),

  // —— managed tool suite (42) ——
  "tool.poppler": tv("FileText", "neyvia-tool-anim-poppler", "Poppler PDF", { category: "pdf", aliases: ["poppler", "pdf.extract-text"] }),
  "tool.tesseract": tv("ScanText", "neyvia-tool-anim-tesseract", "Tesseract OCR", { category: "ocr", aliases: ["tesseract"] }),
  "tool.ocrmypdf": tv("ScanText", "neyvia-tool-anim-ocrmypdf", "OCRmyPDF", { category: "ocr" }),
  "tool.paddleocr": tv("ScanSearch", "neyvia-tool-anim-paddleocr", "PaddleOCR", { category: "ocr" }),
  "tool.libreoffice": tv("FileType", "neyvia-tool-anim-libreoffice", "LibreOffice", { category: "office" }),
  "tool.pandoc": tv("FileCode2", "neyvia-tool-anim-pandoc", "Pandoc", { category: "documents" }),
  "tool.languagetool": tv("SpellCheck2", "neyvia-tool-anim-languagetool", "LanguageTool", {
    category: "grammar",
    aliases: ["languagetool"],
  }),
  "tool.argos-translate": tv("Languages", "neyvia-tool-anim-argos", "Argos Translate", {
    category: "translate",
    aliases: ["argos-translate", "argos"],
  }),
  "tool.libretranslate": tv("Languages", "neyvia-tool-anim-libretranslate", "LibreTranslate", {
    category: "translate",
    aliases: ["libretranslate"],
  }),
  "tool.latex-suite": tv("Sigma", "neyvia-tool-anim-latex-suite", "LaTeX suite", { category: "latex" }),
  "tool.zotero": tv("BookMarked", "neyvia-tool-anim-zotero", "Zotero", { category: "research", aliases: ["zotero"] }),
  "tool.playwright": tv("Drama", "neyvia-tool-anim-playwright", "Playwright", { category: "browser" }),
  "tool.android-sdk": tv("Smartphone", "neyvia-tool-anim-android-sdk", "Android SDK", { category: "device" }),
  "tool.appium": tv("Smartphone", "neyvia-tool-anim-appium", "Appium", { category: "device" }),
  "tool.scrcpy": tv("MonitorSmartphone", "neyvia-tool-anim-scrcpy", "scrcpy", { category: "device" }),
  "tool.git": tv("GitBranch", "neyvia-tool-anim-git", "Git", { category: "software" }),
  "tool.docker-engine": tv("Container", "neyvia-tool-anim-docker", "Docker Engine", { category: "software" }),
  "tool.postgresql": tv("Database", "neyvia-tool-anim-postgres", "PostgreSQL", { category: "software" }),
  "tool.duckdb": tv("DatabaseZap", "neyvia-tool-anim-duckdb", "DuckDB", { category: "data" }),
  "tool.polars": tv("Table2", "neyvia-tool-anim-polars", "Polars", { category: "data" }),
  "tool.scientific-python": tv("FlaskConical", "neyvia-tool-anim-scipy", "Scientific Python", { category: "research" }),
  "tool.anki": tv("Layers", "neyvia-tool-anim-anki", "Anki", { category: "education" }),
  "tool.pytorch-huggingface": tv("BrainCircuit", "neyvia-tool-anim-pytorch", "PyTorch / HF", { category: "ai" }),
  "tool.ffmpeg": tv("Film", "neyvia-tool-anim-ffmpeg", "FFmpeg", { category: "media" }),
  "tool.imagemagick": tv("ImagePlus", "neyvia-tool-anim-imagemagick", "ImageMagick", { category: "media" }),
  "tool.gimp": tv("Palette", "neyvia-tool-anim-gimp", "GIMP", { category: "media" }),
  "tool.blender": tv("Boxes", "neyvia-tool-anim-tool-blender", "Blender", { category: "design/3d" }),
  "tool.godot": tv("Gamepad2", "neyvia-tool-anim-godot", "Godot", { category: "games" }),
  "tool.kicad": tv("CircuitBoard", "neyvia-tool-anim-kicad", "KiCad", { category: "maker" }),
  "tool.freecad": tv("Ruler", "neyvia-tool-anim-freecad", "FreeCAD", { category: "maker" }),
  "tool.openscad": tv("Box", "neyvia-tool-anim-openscad", "OpenSCAD", { category: "maker" }),
  "tool.ros-gazebo": tv("Bot", "neyvia-tool-anim-ros", "ROS / Gazebo", { category: "maker" }),
  "tool.inkscape": tv("PenTool", "neyvia-tool-anim-inkscape", "Inkscape", { category: "design" }),
  "tool.scribus": tv("Newspaper", "neyvia-tool-anim-scribus", "Scribus", { category: "design" }),
  "tool.seamly": tv("Scissors", "neyvia-tool-anim-seamly", "Seamly2D", { category: "fashion" }),
  "tool.trivy": tv("ShieldAlert", "neyvia-tool-anim-trivy", "Trivy", { category: "security" }),
  "tool.semgrep": tv("Bug", "neyvia-tool-anim-semgrep", "Semgrep", { category: "security" }),
  "tool.owasp-zap": tv("Zap", "neyvia-tool-anim-zap", "OWASP ZAP", { category: "security" }),
  "tool.ghidra": tv("Binary", "neyvia-tool-anim-ghidra", "Ghidra", { category: "security" }),
  "tool.mobile-security": tv("Smartphone", "neyvia-tool-anim-mobsf", "Mobile security", { category: "security" }),
  "tool.gramps": tv("GitFork", "neyvia-tool-anim-gramps", "Gramps", { category: "niche" }),
  "tool.astronomy-suite": tv("MoonStar", "neyvia-tool-anim-astro-suite", "Astronomy suite", { category: "niche" }),

  // Typed operations
  "pdf.extract-text": tv("FileText", "neyvia-tool-anim-pdf-extract", "Extract PDF text", { category: "pdf" }),
  "document.list-formats": tv("List", "neyvia-tool-anim-doc-formats", "List document formats", { category: "documents" }),
  "document.inspect-ast": tv("Braces", "neyvia-tool-anim-doc-ast", "Inspect document AST", { category: "documents" }),
  "document.convert": tv("RefreshCw", "neyvia-tool-anim-doc-convert", "Convert document", { category: "documents" }),

  // —— progressive Capability OS ——
  "tool.suite.search": tv("Search", "neyvia-tool-anim-suite-search", "Search tool suite", { category: "orchestration" }),
  "tool.suite.describe": tv("Info", "neyvia-tool-anim-suite-describe", "Describe managed tool", { category: "orchestration" }),
  "tool.suite.execute": tv("Play", "neyvia-tool-anim-suite-execute", "Execute managed tool", { category: "orchestration" }),
  "capability.search": tv("Search", "neyvia-tool-anim-cap-search", "Search capabilities", { category: "orchestration" }),
  "capability.describe": tv("Info", "neyvia-tool-anim-cap-describe", "Describe capability", { category: "orchestration" }),
  "capability.plan": tv("ClipboardList", "neyvia-tool-anim-cap-plan", "Plan capability run", { category: "orchestration" }),
  "capability.ui.contract": tv("FileJson", "neyvia-tool-anim-cap-contract", "UI contract", { category: "orchestration" }),
  "capability.benchmark": tv("Gauge", "neyvia-tool-anim-cap-bench", "Benchmark capability OS", { category: "orchestration" }),
  "capability.execute": tv("Play", "neyvia-tool-anim-cap-execute", "Execute capability", { category: "orchestration" }),
  "capability.pack.validate": tv("ShieldCheck", "neyvia-tool-anim-pack-validate", "Validate pack", { category: "orchestration" }),
  "capability.pack.save": tv("Save", "neyvia-tool-anim-pack-save", "Save pack", { category: "orchestration" }),
  "model.tools.compile": tv("Cpu", "neyvia-tool-anim-model-compile", "Compile model tool belt", { category: "ai" }),
  "model.tools.openai.compile": tv("Cpu", "neyvia-tool-anim-openai-compile", "Compile OpenAI tool belt", { category: "ai" }),
  "model.tools.benchmark": tv("Gauge", "neyvia-tool-anim-model-bench", "Benchmark tool routing", { category: "ai" }),
  "model.tools.feedback": tv("MessageSquare", "neyvia-tool-anim-model-feedback", "Tool feedback", { category: "ai" }),
  "model.tools.feedback.record": tv("MessageSquarePlus", "neyvia-tool-anim-model-feedback-rec", "Record tool feedback", { category: "ai" }),
  "model.tools.run": tv("Play", "neyvia-tool-anim-model-run", "Run model tool plan", { category: "ai" }),
  "tool.author.search": tv("Search", "neyvia-tool-anim-author-search", "Search authored tools", { category: "authored" }),
  "tool.author.describe": tv("Info", "neyvia-tool-anim-author-describe", "Describe authored tool", { category: "authored" }),
  "tool.author.adapt": tv("WandSparkles", "neyvia-tool-anim-author-adapt", "Adapt authored tool", { category: "authored" }),
  "tool.author.validate": tv("ShieldCheck", "neyvia-tool-anim-author-validate", "Validate authored tool", { category: "authored" }),
  "tool.author.save": tv("Save", "neyvia-tool-anim-author-save", "Save authored tool", { category: "authored" }),
  "tool.author.execute": tv("Play", "neyvia-tool-anim-author-execute", "Execute authored tool", { category: "authored" }),
  "computer_use.verify": tv("ScanEye", "neyvia-tool-anim-cu-verify", "Verify computer-use", { category: "computer-use" }),
  "computer_use.dispatch_verification": tv("Send", "neyvia-tool-anim-cu-dispatch-verify", "Dispatch CU verification", { category: "computer-use" }),
  "cu.twin.validate": tv("ShieldCheck", "neyvia-tool-anim-cu-twin-validate", "Validate CU twin", { category: "computer-use" }),
  "cu.twin.save": tv("Save", "neyvia-tool-anim-cu-twin-save", "Save CU twin", { category: "computer-use" }),
  "cu.twin.run": tv("Play", "neyvia-tool-anim-cu-twin-run", "Run CU twin", { category: "computer-use" }),
  "cu.twin.dispatch": tv("Send", "neyvia-tool-anim-cu-twin-dispatch", "Dispatch CU twin", { category: "computer-use" }),
  "artifact.register": tv("PackagePlus", "neyvia-tool-anim-artifact-reg", "Register artifact", { category: "file" }),
  "artifact.lineage": tv("GitFork", "neyvia-tool-anim-artifact-lineage", "Artifact lineage", { category: "file" }),

  // —— ui.* computer-use ——
  "ui.ls": tv("ListTree", "neyvia-tool-anim-ui-ls", "List UI graph", { category: "computer-use" }),
  "ui.find": tv("ScanSearch", "neyvia-tool-anim-ui-find", "Find UI nodes", { category: "computer-use" }),
  "ui.get": tv("MousePointerClick", "neyvia-tool-anim-ui-get", "Get UI node", { category: "computer-use" }),
  "ui.diff": tv("GitCompare", "neyvia-tool-anim-ui-diff", "Diff UI graph", { category: "computer-use" }),
  "ui.wait": tv("Timer", "neyvia-tool-anim-ui-wait", "Wait for UI", { category: "computer-use" }),
  "ui.do": tv("Pointer", "neyvia-tool-anim-ui-do", "Act on UI", { category: "computer-use" }),
  "ui.see": tv("Eye", "neyvia-tool-anim-ui-see", "Vision crop", { category: "computer-use" }),
  "ui.observe": tv("ScanEye", "neyvia-tool-anim-ui-observe", "Observe page", { category: "computer-use" }),

  // —— mcp broker ——
  "mcp.servers": tv("Server", "neyvia-tool-anim-mcp-servers", "MCP servers", { category: "mcp" }),
  "mcp.search": tv("Search", "neyvia-tool-anim-mcp-search", "Search MCP tools", { category: "mcp" }),
  "mcp.describe": tv("Info", "neyvia-tool-anim-mcp-describe", "Describe MCP tool", { category: "mcp" }),
  "mcp.call": tv("Plug", "neyvia-tool-anim-mcp-call", "Call MCP tool", { category: "mcp" }),
  "demo.echo": tv("AudioLines", "neyvia-tool-anim-demo-echo", "Demo echo", { category: "mcp" }),
  "demo.write_note": tv("NotebookPen", "neyvia-tool-anim-demo-note", "Demo write note", { category: "mcp" }),

  // —— neyvia MCP starters / host ——
  "neyvia.research.start": tv("Microscope", "neyvia-tool-anim-neyvia-research", "Start research", {
    category: "research",
    aliases: ["research.start"],
  }),
  "neyvia.browser.start": tv("Globe2", "neyvia-tool-anim-neyvia-browser", "Start browser work", { category: "browser" }),
  "neyvia.computer.start": tv("Monitor", "neyvia-tool-anim-neyvia-computer", "Start computer use", { category: "computer-use" }),
  "neyvia.training.batch.start": tv("BrainCircuit", "neyvia-tool-anim-neyvia-training", "Start training batch", { category: "ai" }),
  "neyvia.time.now": tv("Clock", "neyvia-tool-anim-neyvia-time", "Current time", { category: "orchestration" }),
  "neyvia.tools.search": tv("Search", "neyvia-tool-anim-neyvia-tools-search", "Search tools", { category: "orchestration" }),
  "neyvia.tools.describe": tv("Info", "neyvia-tool-anim-neyvia-tools-describe", "Describe tool", { category: "orchestration" }),
  "neyvia.time.budget": tv("Timer", "neyvia-tool-anim-neyvia-budget", "Deadline budget", { category: "orchestration" }),
  "neyvia.task.status": tv("Activity", "neyvia-tool-anim-neyvia-task", "Task status", { category: "orchestration" }),
  "neyvia.result.summary": tv("FileBarChart", "neyvia-tool-anim-neyvia-result", "Result summary", { category: "orchestration" }),
  "neyvia.autonomy.grant": tv("KeyRound", "neyvia-tool-anim-autonomy-grant", "Grant autonomy", { category: "orchestration" }),
  "neyvia.autonomy.check": tv("KeyRound", "neyvia-tool-anim-autonomy-check", "Check autonomy", { category: "orchestration" }),
  "neyvia.autonomy.revoke": tv("KeyRound", "neyvia-tool-anim-autonomy-revoke", "Revoke autonomy", { category: "orchestration" }),
  "neyvia.conversation.list": tv("MessagesSquare", "neyvia-tool-anim-conv-list", "List conversations", { category: "chat" }),
  "neyvia.conversation.search": tv("Search", "neyvia-tool-anim-conv-search", "Search conversations", { category: "chat" }),
  "neyvia.question.branch": tv("GitBranch", "neyvia-tool-anim-question-branch", "Question branch", { category: "chat" }),
  "neyvia.question.action.check": tv("ShieldCheck", "neyvia-tool-anim-question-check", "Check branch action", { category: "chat" }),
  "neyvia.context.retrieve": tv("Library", "neyvia-tool-anim-ctx-retrieve", "Retrieve context", { category: "research" }),
  "neyvia.orchestration.plan": tv("Network", "neyvia-tool-anim-orch-plan", "Build constellation", { category: "orchestration" }),
  "neyvia.orchestration.graph": tv("Share2", "neyvia-tool-anim-orch-graph", "Constellation graph", { category: "orchestration" }),

  // —— adapters ——
  "neyvia.agent": tv("Bot", "neyvia-tool-anim-adapter-agent", "Neyvia agent adapter", { category: "adapters" }),
  "builtin.artifact.inspect": tv("ScanSearch", "neyvia-tool-anim-adapter-artifact", "Inspect artifact", { category: "adapters" }),
  "builtin.text.extract": tv("FileType", "neyvia-tool-anim-adapter-text", "Extract text", { category: "adapters" }),
  "ocr.tesseract": tv("ScanText", "neyvia-tool-anim-adapter-ocr", "OCR adapter", { category: "ocr" }),
  "pdf.pdftotext": tv("FileText", "neyvia-tool-anim-adapter-pdftotext", "pdftotext adapter", { category: "pdf" }),
  "document.libreoffice": tv("FileType", "neyvia-tool-anim-adapter-lo", "LibreOffice adapter", { category: "office" }),
  "document.pandoc": tv("FileCode2", "neyvia-tool-anim-adapter-pandoc", "Pandoc adapter", { category: "documents" }),
  "latex.compiler": tv("Sigma", "neyvia-tool-anim-adapter-latex", "LaTeX compiler", { category: "latex" }),
  "media.ffmpeg": tv("Film", "neyvia-tool-anim-adapter-ffmpeg", "FFmpeg adapter", { category: "media" }),
  "three_d.blender": tv("Boxes", "neyvia-tool-anim-adapter-blender", "Blender adapter", { category: "design/3d" }),
  "game.unity": tv("Gamepad2", "neyvia-tool-anim-adapter-unity", "Unity adapter", { category: "games" }),
  "device.android": tv("Smartphone", "neyvia-tool-anim-adapter-android", "Android adapter", { category: "device" }),
  "code.git": tv("GitBranch", "neyvia-tool-anim-adapter-git", "Git adapter", { category: "software" }),
  "runtime.python": tv("Code2", "neyvia-tool-anim-adapter-python", "Python runtime", { category: "software" }),
  "runtime.node": tv("Code2", "neyvia-tool-anim-adapter-node", "Node runtime", { category: "software" }),
  "device.apple-remote": tv("TabletSmartphone", "neyvia-tool-anim-adapter-apple", "Apple remote", { category: "device" }),
  "browser.firefox-bidi": tv("Globe2", "neyvia-tool-anim-adapter-firefox", "Firefox BiDi", { category: "browser" }),
  "office.document-session": tv("FileType", "neyvia-tool-anim-adapter-office-sess", "Office session", { category: "office" }),
  "game.unity-bridge": tv("Gamepad2", "neyvia-tool-anim-adapter-unity-bridge", "Unity bridge", { category: "games" }),
  "three_d.blender-bridge": tv("Boxes", "neyvia-tool-anim-adapter-blender-bridge", "Blender bridge", { category: "design/3d" }),

  // —— authored catch-all visual (dynamic ids resolve via prefix) ——
  authored: tv("WandSparkles", "neyvia-tool-anim-authored", "Authored tool", { category: "authored", aliases: ["tool.author"] }),
});
