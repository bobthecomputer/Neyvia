import { checkedChatAction } from "./neyviaChatContracts.js";
/**
 * Neyvia per-tool visual registry.
 * Maps catalog + backend tool ids → distinct icon keys, motion classes, and labels.
 * Icons are lucide-react name strings; resolve via resolveNeyviaToolIcon() in JSX consumers.
 * Never invents successful backend execution — visuals are presentation only.
 *
 * Inventory expansion: docs/NEYVIA_TOOL_ICON_ANIMATION_COVERAGE.md → neyviaToolVisualsInventory.js
 */

import { NEYVIA_INVENTORY_TOOL_VISUALS } from "./neyviaToolVisualsInventory.js";

/** @typedef {"idle"|"call"|"running"|"success"|"error"|"open"|"composing"} NeyviaToolPhase */

/**
 * @typedef {Object} NeyviaToolVisual
 * @property {string} icon Lucide icon name
 * @property {string} animationClass Base CSS class for catalog / panel chrome
 * @property {{idle?: string, call?: string, running?: string, success?: string, error?: string, open?: string, composing?: string}} labels
 * @property {string} [chipClass] Chip wrapper class for conversation / live stream
 * @property {string} [category] Catalog grouping
 * @property {boolean} [stub] Honest stub — backend not claimed live
 * @property {string[]} [aliases] Alternate tool ids / message match tokens
 */

/** App icon paths surfaced for Settings / docs / about. */
export const NEYVIA_APP_ICON_PATHS = Object.freeze({
  svg: "src-tauri/icons/neyvia-icon.svg",
  png: "src-tauri/icons/icon.png",
  ico: "src-tauri/icons/icon.ico",
  icns: "src-tauri/icons/icon.icns",
  brandDoc: "docs/NEYVIA_BRAND.md",
  brandRefs: "docs/brand/references/",
  reactMark: "web/src/neyvia/NeyviaBrandMark.jsx",
});

/** File-type icons for Library / attachments. */
export const NEYVIA_FILE_TYPE_VISUALS = Object.freeze({
  pdf: Object.freeze({ icon: "FileText", animationClass: "neyvia-file-anim-pdf", label: "PDF" }),
  csv: Object.freeze({ icon: "Table2", animationClass: "neyvia-file-anim-csv", label: "CSV" }),
  xlsx: Object.freeze({ icon: "Sheet", animationClass: "neyvia-file-anim-sheet", label: "Spreadsheet" }),
  image: Object.freeze({ icon: "Image", animationClass: "neyvia-file-anim-image", label: "Image" }),
  "3d": Object.freeze({ icon: "Box", animationClass: "neyvia-file-anim-3d", label: "3D" }),
  gltf: Object.freeze({ icon: "Box", animationClass: "neyvia-file-anim-3d", label: "glTF" }),
  md: Object.freeze({ icon: "FileCode2", animationClass: "neyvia-file-anim-md", label: "Markdown" }),
  docx: Object.freeze({ icon: "FileType", animationClass: "neyvia-file-anim-doc", label: "Document" }),
  txt: Object.freeze({ icon: "FileType", animationClass: "neyvia-file-anim-doc", label: "Text" }),
  json: Object.freeze({ icon: "Braces", animationClass: "neyvia-file-anim-json", label: "JSON" }),
  video: Object.freeze({ icon: "Clapperboard", animationClass: "neyvia-file-anim-video", label: "Video" }),
  audio: Object.freeze({ icon: "Headphones", animationClass: "neyvia-file-anim-audio", label: "Audio" }),
  zip: Object.freeze({ icon: "Archive", animationClass: "neyvia-file-anim-zip", label: "Archive" }),
  code: Object.freeze({ icon: "Code2", animationClass: "neyvia-file-anim-code", label: "Code" }),
  unknown: Object.freeze({ icon: "File", animationClass: "neyvia-file-anim-unknown", label: "File" }),
});

/**
 * Phase → CSS modifier for tool-call chips.
 * Applied as `neyvia-tool-chip--{phase}` plus optional per-tool running class.
 */
export const NEYVIA_TOOL_PHASE_CLASSES = Object.freeze({
  idle: "neyvia-tool-chip--idle",
  call: "neyvia-tool-chip--call",
  running: "neyvia-tool-chip--running",
  success: "neyvia-tool-chip--success",
  error: "neyvia-tool-chip--error",
  open: "neyvia-tool-chip--open",
  composing: "neyvia-tool-chip--composing",
});

/** Panel / drawer enter animation by surface id (distinct per tool open). */
export const NEYVIA_PANEL_ENTER_CLASSES = Object.freeze({
  tools: "neyvia-panel-enter-tools",
  pdf: "neyvia-panel-enter-pdf",
  scene: "neyvia-panel-enter-scene",
  roster: "neyvia-panel-enter-roster",
  sources: "neyvia-panel-enter-sources",
  plan: "neyvia-panel-enter-plan",
  folders: "neyvia-panel-enter-folders",
  research: "neyvia-panel-enter-research",
  translate: "neyvia-panel-enter-translate",
  grammar: "neyvia-panel-enter-grammar",
  chart: "neyvia-panel-enter-chart",
  "web-capture": "neyvia-panel-enter-web-capture",
  judgment: "neyvia-panel-enter-judgment",
  command: "neyvia-panel-enter-command",
  default: "neyvia-panel-enter-default",
});

/**
 * Full tool visual catalog — session toolbar, chat tools, dedicated stubs, and backend native tools.
 * @type {Readonly<Record<string, NeyviaToolVisual>>}
 */
const NEYVIA_TOOL_VISUALS_BASE = {
  // —— Session toolbar / chat catalog ——
  attach: Object.freeze({
    icon: "Paperclip",
    animationClass: "neyvia-tool-anim-attach",
    chipClass: "neyvia-chip-attach",
    category: "session",
    labels: {
      idle: "Attach",
      call: "Attaching…",
      running: "Uploading file",
      success: "File attached",
      error: "Attach failed",
    },
    aliases: ["file-attached", "file_attach", "attachment"],
  }),
  search: Object.freeze({
    icon: "Search",
    animationClass: "neyvia-tool-anim-search",
    chipClass: "neyvia-chip-search",
    category: "session",
    labels: {
      idle: "Web Search",
      call: "Searching…",
      running: "Scanning results",
      success: "Search complete",
      error: "Search failed",
    },
    aliases: ["web.search", "web-search", "web_search"],
  }),
  pdf: Object.freeze({
    icon: "FileText",
    animationClass: "neyvia-tool-anim-pdf",
    chipClass: "neyvia-chip-pdf",
    category: "session",
    labels: {
      idle: "PDF Reader",
      open: "Opening PDF…",
      call: "Reading PDF…",
      running: "Extracting pages",
      success: "PDF ready",
      error: "PDF unavailable",
    },
    aliases: ["pdf_reader", "pdf-reader", "document"],
  }),
  data: Object.freeze({
    icon: "Table2",
    animationClass: "neyvia-tool-anim-data",
    chipClass: "neyvia-chip-data",
    category: "session",
    labels: {
      idle: "Data Analyst",
      call: "Analyzing…",
      running: "Crunching tables",
      success: "Analysis ready",
      error: "Analysis failed",
    },
    aliases: ["data-analyst", "sheets"],
  }),
  chart: Object.freeze({
    icon: "ChartColumn",
    animationClass: "neyvia-tool-anim-chart",
    chipClass: "neyvia-chip-chart",
    category: "session",
    labels: {
      idle: "Chart Builder",
      call: "Building chart…",
      running: "Plotting",
      success: "Chart ready",
      error: "Chart failed",
    },
  }),
  images: Object.freeze({
    icon: "Image",
    animationClass: "neyvia-tool-anim-images",
    chipClass: "neyvia-chip-images",
    category: "session",
    labels: {
      idle: "Image Playground",
      call: "Opening images…",
      running: "Composing",
      success: "Image ready",
      error: "Image failed",
    },
    aliases: ["image", "image-playground"],
  }),
  canvas: Object.freeze({
    icon: "LayoutDashboard",
    animationClass: "neyvia-tool-anim-canvas",
    chipClass: "neyvia-chip-canvas",
    category: "session",
    labels: {
      idle: "Canvas",
      call: "Opening canvas…",
      running: "Rendering",
      success: "Canvas ready",
      error: "Canvas failed",
    },
  }),
  citations: Object.freeze({
    icon: "Quote",
    animationClass: "neyvia-tool-anim-citations",
    chipClass: "neyvia-chip-citations",
    category: "session",
    labels: {
      idle: "Citations",
      call: "Gathering sources…",
      running: "Scoring confidence",
      success: "Citations ready",
      error: "No provenance",
    },
    aliases: ["sources"],
  }),
  terminal: Object.freeze({
    icon: "SquareTerminal",
    animationClass: "neyvia-tool-anim-terminal",
    chipClass: "neyvia-chip-terminal",
    category: "session",
    labels: {
      idle: "Terminal",
      call: "Opening terminal…",
      running: "Running command",
      success: "Command finished",
      error: "Command failed",
    },
    aliases: ["shell", "bash", "powershell"],
  }),
  diff: Object.freeze({
    icon: "GitCompare",
    animationClass: "neyvia-tool-anim-diff",
    chipClass: "neyvia-chip-diff",
    category: "session",
    labels: {
      idle: "Diff",
      call: "Comparing…",
      running: "Reviewing changes",
      success: "Diff ready",
      error: "Diff failed",
    },
  }),
  scene: Object.freeze({
    icon: "Boxes",
    animationClass: "neyvia-tool-anim-scene",
    chipClass: "neyvia-chip-scene",
    category: "session",
    stub: true,
    labels: {
      idle: "3D / Scene",
      call: "Loading stage…",
      running: "Previewing mesh",
      success: "Scene ready",
      error: "Scene not connected",
    },
    aliases: ["object-to-design", "object_to_design", "3d", "gltf"],
  }),
  "web-capture": Object.freeze({
    icon: "Camera",
    animationClass: "neyvia-tool-anim-web-capture",
    chipClass: "neyvia-chip-web-capture",
    category: "session",
    stub: true,
    labels: {
      idle: "Web Capture",
      call: "Capturing page…",
      running: "Saving snapshot",
      success: "Page captured",
      error: "Capture blocked",
    },
    aliases: ["web_capture", "web.fetch"],
  }),
  notes: Object.freeze({
    icon: "NotebookPen",
    animationClass: "neyvia-tool-anim-notes",
    chipClass: "neyvia-chip-notes",
    category: "session",
    labels: {
      idle: "Notes",
      call: "Opening notes…",
      running: "Saving highlight",
      success: "Note saved",
      error: "Note failed",
    },
  }),
  specialists: Object.freeze({
    icon: "Users",
    animationClass: "neyvia-tool-anim-specialists",
    chipClass: "neyvia-chip-specialists",
    category: "session",
    labels: {
      idle: "Specialists",
      call: "Spinning up…",
      running: "Joining roster",
      success: "Specialist ready",
      error: "Assign failed",
    },
    aliases: ["subagent", "sub-agent", "roster"],
  }),

  // —— Dedicated capability stubs (unique icon + motion even when backend absent) ——
  research: Object.freeze({
    icon: "Microscope",
    animationClass: "neyvia-tool-anim-research",
    chipClass: "neyvia-chip-research",
    category: "capability",
    stub: true,
    labels: {
      idle: "Research",
      call: "Starting research…",
      running: "Gathering sources",
      success: "Research brief ready",
      error: "Research not connected",
    },
    aliases: ["research-workbench", "deep-research"],
  }),
  translate: Object.freeze({
    icon: "Languages",
    animationClass: "neyvia-tool-anim-translate",
    chipClass: "neyvia-chip-translate",
    category: "capability",
    stub: true,
    labels: {
      idle: "Translate",
      call: "Translating…",
      running: "Aligning phrases",
      success: "Translation ready",
      error: "Translate not connected",
    },
    aliases: ["translation", "argos-translate"],
  }),
  "grammar-correct": Object.freeze({
    icon: "SpellCheck2",
    animationClass: "neyvia-tool-anim-grammar",
    chipClass: "neyvia-chip-grammar",
    category: "capability",
    stub: true,
    labels: {
      idle: "Grammar correct",
      call: "Checking grammar…",
      running: "Correcting",
      success: "Grammar fixed",
      error: "Grammar tool unavailable",
    },
    aliases: ["grammar", "grammar_correct", "spellcheck"],
  }),
  "incorrect-grammar": Object.freeze({
    icon: "Highlighter",
    animationClass: "neyvia-tool-anim-grammar-mark",
    chipClass: "neyvia-chip-grammar-mark",
    category: "capability",
    stub: true,
    labels: {
      idle: "Grammar highlight",
      call: "Marking issues…",
      running: "Highlighting",
      success: "Issues marked",
      error: "Highlight unavailable",
    },
    aliases: ["grammar-highlight", "incorrect_grammar"],
  }),
  "file-attached": Object.freeze({
    icon: "Paperclip",
    animationClass: "neyvia-tool-anim-file-attached",
    chipClass: "neyvia-chip-file-attached",
    category: "capability",
    labels: {
      idle: "File attached",
      call: "Attaching…",
      running: "Indexing file",
      success: "Attached",
      error: "Attach failed",
    },
  }),
  "object-to-design": Object.freeze({
    icon: "BoxSelect",
    animationClass: "neyvia-tool-anim-object-design",
    chipClass: "neyvia-chip-object-design",
    category: "capability",
    stub: true,
    labels: {
      idle: "Object → Design",
      call: "Capturing object…",
      running: "Building 3D draft",
      success: "Design draft ready",
      error: "3D adapter not connected",
    },
  }),

  // —— Agent write / compose (conversation chrome) ——
  compose: Object.freeze({
    icon: "PenLine",
    animationClass: "neyvia-tool-anim-compose",
    chipClass: "neyvia-chip-compose",
    category: "agent",
    labels: {
      idle: "Compose",
      composing: "Writing…",
      running: "Streaming",
      success: "Reply ready",
      error: "Compose failed",
    },
    aliases: ["agent-write", "streaming", "writing"],
  }),

  // —— Backend native tools (grant_agent.native_tools) ——
  "workspace.search": Object.freeze({
    icon: "FolderSearch",
    animationClass: "neyvia-tool-anim-workspace-search",
    chipClass: "neyvia-chip-workspace-search",
    category: "backend",
    labels: {
      idle: "Workspace search",
      call: "Searching repo…",
      running: "Scanning files",
      success: "Matches found",
      error: "Search failed",
    },
    aliases: ["grep"],
  }),
  "context.search": Object.freeze({
    icon: "Library",
    animationClass: "neyvia-tool-anim-context-search",
    chipClass: "neyvia-chip-context-search",
    category: "backend",
    labels: {
      idle: "Context search",
      call: "Searching memory…",
      running: "Retrieving evidence",
      success: "Context ready",
      error: "Context miss",
    },
  }),
  "context.bundle": Object.freeze({
    icon: "Package",
    animationClass: "neyvia-tool-anim-context-bundle",
    chipClass: "neyvia-chip-context-bundle",
    category: "backend",
    labels: {
      idle: "Context bundle",
      call: "Bundling…",
      running: "Assembling pack",
      success: "Bundle ready",
      error: "Bundle failed",
    },
  }),
  "context.compact": Object.freeze({
    icon: "Minimize2",
    animationClass: "neyvia-tool-anim-context-compact",
    chipClass: "neyvia-chip-context-compact",
    category: "backend",
    labels: {
      idle: "Context compact",
      call: "Compacting…",
      running: "Archiving",
      success: "Compacted",
      error: "Compact failed",
    },
  }),
  "orchestration.compile": Object.freeze({
    icon: "GitBranch",
    animationClass: "neyvia-tool-anim-orch-compile",
    chipClass: "neyvia-chip-orch-compile",
    category: "backend",
    labels: {
      idle: "Compile orchestration",
      call: "Compiling plan…",
      running: "Validating DAG",
      success: "Plan compiled",
      error: "Compile failed",
    },
  }),
  "codex.assets.inspect": Object.freeze({
    icon: "ScanSearch",
    animationClass: "neyvia-tool-anim-codex-inspect",
    chipClass: "neyvia-chip-codex-inspect",
    category: "backend",
    labels: {
      idle: "Inspect Codex assets",
      call: "Inspecting…",
      running: "Reading assets",
      success: "Assets listed",
      error: "Inspect failed",
    },
  }),
  "codex.assets.import": Object.freeze({
    icon: "Download",
    animationClass: "neyvia-tool-anim-codex-import",
    chipClass: "neyvia-chip-codex-import",
    category: "backend",
    labels: {
      idle: "Import Codex assets",
      call: "Importing…",
      running: "Linking skills",
      success: "Imported",
      error: "Import failed",
    },
  }),
  "skill.live.read": Object.freeze({
    icon: "BookOpen",
    animationClass: "neyvia-tool-anim-skill-read",
    chipClass: "neyvia-chip-skill-read",
    category: "backend",
    labels: {
      idle: "Read live skill",
      call: "Opening skill…",
      running: "Validating",
      success: "Skill bound",
      error: "Skill unread",
    },
  }),
  "skill.live.iterate": Object.freeze({
    icon: "RefreshCw",
    animationClass: "neyvia-tool-anim-skill-iterate",
    chipClass: "neyvia-chip-skill-iterate",
    category: "backend",
    labels: {
      idle: "Iterate skill",
      call: "Iterating…",
      running: "Versioning",
      success: "Skill updated",
      error: "Iterate failed",
    },
  }),
  "web.search": Object.freeze({
    icon: "Globe2",
    animationClass: "neyvia-tool-anim-web-search",
    chipClass: "neyvia-chip-web-search",
    category: "backend",
    labels: {
      idle: "Web search",
      call: "Searching web…",
      running: "Fetching hits",
      success: "Results ready",
      error: "Web search failed",
    },
  }),
  "web.image_search": Object.freeze({
    icon: "Images",
    animationClass: "neyvia-tool-anim-web-image-search",
    chipClass: "neyvia-chip-web-image-search",
    category: "backend",
    labels: {
      idle: "Image search",
      call: "Searching images…",
      running: "Collecting refs",
      success: "Images ready",
      error: "Image search failed",
    },
  }),
  "ui.inspiration.search": Object.freeze({
    icon: "Sparkles",
    animationClass: "neyvia-tool-anim-ui-inspo",
    chipClass: "neyvia-chip-ui-inspo",
    category: "backend",
    labels: {
      idle: "UI inspiration",
      call: "Finding inspiration…",
      running: "Boarding refs",
      success: "Board ready",
      error: "Inspiration miss",
    },
  }),
  "web.fetch": Object.freeze({
    icon: "Link2",
    animationClass: "neyvia-tool-anim-web-fetch",
    chipClass: "neyvia-chip-web-fetch",
    category: "backend",
    labels: {
      idle: "Fetch URL",
      call: "Fetching…",
      running: "Downloading",
      success: "Fetched",
      error: "Fetch failed",
    },
  }),
  "preview.inspect": Object.freeze({
    icon: "ScanEye",
    animationClass: "neyvia-tool-anim-preview-inspect",
    chipClass: "neyvia-chip-preview-inspect",
    category: "backend",
    labels: {
      idle: "Inspect preview",
      call: "Inspecting…",
      running: "Reading DOM",
      success: "Inspected",
      error: "Inspect failed",
    },
  }),
  "preview.screenshot": Object.freeze({
    icon: "Camera",
    animationClass: "neyvia-tool-anim-preview-shot",
    chipClass: "neyvia-chip-preview-shot",
    category: "backend",
    labels: {
      idle: "Preview screenshot",
      call: "Capturing…",
      running: "Snapping",
      success: "Screenshot ready",
      error: "Screenshot failed",
    },
  }),
  "preview.annotate": Object.freeze({
    icon: "Pencil",
    animationClass: "neyvia-tool-anim-preview-annotate",
    chipClass: "neyvia-chip-preview-annotate",
    category: "backend",
    labels: {
      idle: "Annotate preview",
      call: "Annotating…",
      running: "Marking",
      success: "Annotated",
      error: "Annotate failed",
    },
  }),
  "video.inspect": Object.freeze({
    icon: "Film",
    animationClass: "neyvia-tool-anim-video-inspect",
    chipClass: "neyvia-chip-video-inspect",
    category: "backend",
    labels: {
      idle: "Inspect video",
      call: "Inspecting video…",
      running: "Reading frames",
      success: "Video inspected",
      error: "Video inspect failed",
    },
  }),
  "video.digest": Object.freeze({
    icon: "Clapperboard",
    animationClass: "neyvia-tool-anim-video-digest",
    chipClass: "neyvia-chip-video-digest",
    category: "backend",
    labels: {
      idle: "Digest video",
      call: "Digesting…",
      running: "Summarizing",
      success: "Digest ready",
      error: "Digest failed",
    },
  }),
  "nas.message.send": Object.freeze({
    icon: "Send",
    animationClass: "neyvia-tool-anim-nas-send",
    chipClass: "neyvia-chip-nas-send",
    category: "backend",
    labels: {
      idle: "NAS message send",
      call: "Sending…",
      running: "Transferring",
      success: "Sent",
      error: "Send failed",
    },
  }),
  "nas.message.receive": Object.freeze({
    icon: "Inbox",
    animationClass: "neyvia-tool-anim-nas-receive",
    chipClass: "neyvia-chip-nas-receive",
    category: "backend",
    labels: {
      idle: "NAS message receive",
      call: "Receiving…",
      running: "Pulling",
      success: "Received",
      error: "Receive failed",
    },
  }),
  "nas.file.send": Object.freeze({
    icon: "Upload",
    animationClass: "neyvia-tool-anim-nas-file",
    chipClass: "neyvia-chip-nas-file",
    category: "backend",
    labels: {
      idle: "NAS file send",
      call: "Uploading…",
      running: "Sending file",
      success: "File sent",
      error: "Upload failed",
    },
  }),
  "nas.transfer": Object.freeze({
    icon: "ArrowLeftRight",
    animationClass: "neyvia-tool-anim-nas-transfer",
    chipClass: "neyvia-chip-nas-transfer",
    category: "backend",
    labels: {
      idle: "NAS transfer",
      call: "Transferring…",
      running: "Syncing",
      success: "Transfer complete",
      error: "Transfer failed",
    },
  }),

  "browser.read": Object.freeze({
    icon: "Eye",
    animationClass: "neyvia-tool-anim-search",
    chipClass: "neyvia-chip-browser",
    category: "computer-use",
    labels: {
      idle: "Read the page",
      call: "Opening the page…",
      running: "Reading the page",
      success: "Read the page",
      error: "Could not read the page",
    },
    aliases: [
      "observe_tab",
      "connected_chrome_observe_command",
      "thunder_read_console_command",
      "ui.observe",
      "observe",
    ],
  }),
  "browser.act": Object.freeze({
    icon: "MousePointerClick",
    animationClass: "neyvia-tool-anim-search",
    chipClass: "neyvia-chip-browser",
    category: "computer-use",
    labels: {
      idle: "Use the browser",
      call: "Preparing the action…",
      running: "Using the browser",
      success: "Action verified",
      error: "Action could not be verified",
    },
    aliases: [
      "connected_chrome_act_command",
      "thunder_execute_proposal_command",
      "act",
      "cu.act",
    ],
  }),
  "browser.connect": Object.freeze({
    icon: "Plug",
    animationClass: "neyvia-tool-anim-unknown",
    chipClass: "neyvia-chip-browser",
    category: "computer-use",
    labels: {
      idle: "Connected browser",
      call: "Connecting…",
      running: "Starting the browser",
      success: "Browser connected",
      error: "Browser unavailable",
    },
    aliases: [
      "connected_chrome_status_command",
      "connected_chrome_launch_command",
      "connected_chrome_list_tabs_command",
    ],
  }),
  thunder: Object.freeze({
    icon: "Cpu",
    animationClass: "neyvia-tool-anim-unknown",
    chipClass: "neyvia-chip-thunder",
    category: "compute",
    labels: {
      idle: "Thunder Compute",
      call: "Opening the console…",
      running: "Working in Thunder Compute",
      success: "Thunder Compute updated",
      error: "Thunder Compute action failed",
    },
    aliases: ["thunder_open_console_command", "thundercompute", "thunder"],
  }),
  // —— Fallback ——
  unknown: Object.freeze({
    icon: "Wrench",
    animationClass: "neyvia-tool-anim-unknown",
    chipClass: "neyvia-chip-unknown",
    category: "fallback",
    labels: {
      idle: "Tool",
      call: "Calling tool…",
      running: "Running",
      success: "Done",
      error: "Failed",
    },
  }),
};

/** Merged session + inventory visuals (capabilities, suite, progressive, ui.*, mcp.*, adapters). */
export const NEYVIA_TOOL_VISUALS = Object.freeze({
  ...NEYVIA_TOOL_VISUALS_BASE,
  ...NEYVIA_INVENTORY_TOOL_VISUALS,
});

/** Preferred display order for Chat Tools / Library category groups. */
export const NEYVIA_TOOL_CATEGORY_ORDER = Object.freeze([
  "session",
  "research",
  "pdf",
  "ocr",
  "translate",
  "grammar",
  "documents",
  "latex",
  "office",
  "data",
  "media",
  "design",
  "design/3d",
  "maker",
  "security",
  "device",
  "browser",
  "computer-use",
  "software",
  "ai",
  "education",
  "fashion",
  "games",
  "niche",
  "mcp",
  "authored",
  "orchestration",
  "chat",
  "file",
  "capability",
  "adapters",
  "inventory",
  "fallback",
]);

const NEYVIA_CHAT_TOOL_PRIORITY = Object.freeze([
  Object.freeze({ id: "pdf", label: "PDF Reader", detail: "Maps to document.pdf-analysis / pdf.pdftotext when adapters report.", panel: "pdf", category: "pdf" }),
  Object.freeze({ id: "search", label: "Web Search", detail: "Maps to web.search when network.read is approved.", panel: "tools", category: "research" }),
  Object.freeze({ id: "research", label: "Research", detail: "Maps to neyvia.research.start / literature-review — stub until bound.", panel: "research", stub: true, category: "research" }),
  Object.freeze({ id: "translate", label: "Translate", detail: "Maps to tool.argos-translate / writing.translation-alignment.", panel: "translate", stub: true, category: "translate" }),
  Object.freeze({ id: "grammar-correct", label: "Grammar correct", detail: "Maps to tool.languagetool — stub until suite reports ready.", panel: "grammar", stub: true, category: "grammar" }),
  Object.freeze({ id: "incorrect-grammar", label: "Grammar highlight", detail: "Maps to writing.editorial-redline highlight path — visual stub.", panel: "grammar", stub: true, category: "grammar" }),
  Object.freeze({ id: "document.fast-ocr", label: "OCR", detail: "Maps to document.fast-ocr / tool.tesseract — not connected here.", panel: "pdf", stub: true, category: "ocr" }),
  Object.freeze({ id: "document.latex-production", label: "LaTeX", detail: "Maps to document.latex-production / tool.latex-suite.", panel: "tools", stub: true, category: "latex" }),
  Object.freeze({ id: "data", label: "Data Analyst", detail: "Maps to office.spreadsheet-analysis / tool.duckdb.", panel: "tools", category: "data" }),
  Object.freeze({ id: "chart", label: "Chart Builder", detail: "Visualize numbers from session artifacts.", panel: "chart", category: "data" }),
  Object.freeze({ id: "images", label: "Image Playground", detail: "Media tool drawer — not a rival app.", surface: "images", category: "media" }),
  Object.freeze({ id: "scene", label: "3D / Scene", detail: "Maps to three-d.blender-scene / tool.blender.", panel: "scene", category: "design/3d" }),
  Object.freeze({ id: "object-to-design", label: "Object → Design", detail: "3D object-to-design stub — unique icon + motion, no fake mesh.", panel: "scene", stub: true, category: "design/3d" }),
  Object.freeze({ id: "maker.cad-fabrication", label: "CAD", detail: "Maps to maker.cad-fabrication / FreeCAD / OpenSCAD.", panel: "scene", stub: true, category: "maker" }),
  Object.freeze({ id: "security.ai-red-team", label: "Security", detail: "Open Lab Security for the installed-runtime audit, bounded scope, purple-team plan, and action guard. Plans never launch probes.", panel: "tools", stub: false, category: "security" }),
  Object.freeze({ id: "device.android-test", label: "Device lab", detail: "Maps to device.android-test / Apple remote — stub.", panel: "tools", stub: true, category: "device" }),
  Object.freeze({ id: "fashion.collection-concept", label: "Fashion", detail: "Maps to fashion.* / tool.seamly — stub.", panel: "tools", stub: true, category: "fashion" }),
  Object.freeze({ id: "cu.twin.run", label: "CU twin", detail: "Open Lab Computer Use for approval-gated live or replay verification and saved twins.", panel: "tools", stub: false, category: "computer-use" }),
  Object.freeze({ id: "mcp.call", label: "MCP call", detail: "Open Lab MCP to inspect only configured servers, load schemas on demand, approve one call, and retain the real broker receipt.", panel: "tools", stub: false, category: "mcp" }),
  Object.freeze({ id: "tool.author.search", label: "Authored tools", detail: "Open the Lab browser for saved workspace manifests, schema-generated inputs, explicit permission approval, and real execution receipts.", panel: "tools", stub: false, category: "authored" }),
  Object.freeze({ id: "file-attached", label: "File attached", detail: "Attached-file treatment in stream and library.", panel: "tools", category: "file" }),
  Object.freeze({ id: "web-capture", label: "Web Capture", detail: "Maps to preview.screenshot / web.fetch.", panel: "web-capture", category: "browser" }),
  Object.freeze({ id: "notes", label: "Notes", detail: "Capture highlights into Notebook.", surface: "notebook", category: "session" }),
  Object.freeze({ id: "specialists", label: "Specialists", detail: "Sub-agent roster spin-up for Chat or Orchestration.", panel: "roster", category: "orchestration" }),
  Object.freeze({ id: "compose", label: "Agent write", detail: "Composing / streaming indicator treatment for agent replies.", panel: "tools", category: "session" }),
  Object.freeze({ id: "attach", label: "Attach", detail: "Add files to the session with typed icons.", panel: "tools", category: "file" }),
  Object.freeze({ id: "citations", label: "Citations", detail: "Source receipts when provenance exists.", panel: "sources", category: "research" }),
  Object.freeze({ id: "terminal", label: "Terminal", detail: "Runtime command surface.", panel: "tools", category: "software" }),
  Object.freeze({ id: "diff", label: "Diff", detail: "Review file changes.", panel: "tools", category: "software" }),
  Object.freeze({ id: "canvas", label: "Canvas", detail: "Open mixed artifact canvas.", panel: "tools", category: "design" }),
  Object.freeze({ id: "ui.observe", label: "UI observe", detail: "Open Lab Computer Use to verify a bounded observed flow with a compact receipt.", panel: "tools", stub: false, category: "computer-use" }),
]);

/** Extra progressive / MCP / capability ids to surface beyond the managed suite. */
const NEYVIA_CHAT_PROGRESSIVE_EXTRA = Object.freeze([
  "tool.suite.search",
  "tool.suite.describe",
  "tool.suite.execute",
  "capability.search",
  "capability.plan",
  "capability.execute",
  "tool.author.describe",
  "tool.author.execute",
  "computer_use.verify",
  "cu.twin.validate",
  "artifact.register",
  "artifact.lineage",
  "ui.ls",
  "ui.find",
  "ui.do",
  "ui.see",
  "mcp.servers",
  "mcp.search",
  "mcp.describe",
  "neyvia.research.start",
  "neyvia.browser.start",
  "neyvia.computer.start",
  "neyvia.orchestration.plan",
  "pdf.extract-text",
  "document.convert",
  "research.literature-review",
  "writing.translation-alignment",
  "writing.editorial-redline",
  "document.pdf-analysis",
  "office.spreadsheet-analysis",
  "three-d.blender-scene",
  "security.threat-model",
]);

function catalogTileFromVisual(id, visual) {
  const label = visual?.labels?.idle || id;
  const category = visual?.category || "inventory";
  let panel = "tools";
  if (category === "pdf" || category === "ocr") panel = "pdf";
  else if (category === "design/3d" || category === "maker") panel = "scene";
  else if (category === "research" && id.includes("research")) panel = "research";
  else if (category === "translate") panel = "translate";
  else if (category === "grammar") panel = "grammar";
  else if (category === "data" && (id === "chart" || id.includes("chart"))) panel = "chart";
  else if (category === "browser" && (id === "web-capture" || id.includes("capture") || id.includes("screenshot"))) {
    panel = "web-capture";
  } else if (category === "orchestration" && id.includes("specialist")) panel = "roster";
  return Object.freeze({
    id,
    label,
    detail: `Inventory id ${id} — candidate until execute path reports ready.`,
    panel,
    stub: true,
    category,
    inventory: true,
  });
}

function buildExpandedChatToolCatalog() {
  const seen = new Set();
  const tiles = [];
  const push = entry => {
    if (!entry?.id || seen.has(entry.id)) return;
    seen.add(entry.id);
    const visual = NEYVIA_TOOL_VISUALS[entry.id] || NEYVIA_INVENTORY_TOOL_VISUALS[entry.id];
    tiles.push(
      Object.freeze({
        ...entry,
        category: entry.category || visual?.category || "session",
        stub: entry.stub !== false,
      }),
    );
  };

  NEYVIA_CHAT_TOOL_PRIORITY.forEach(push);

  // Full managed suite (42) from inventory
  Object.entries(NEYVIA_INVENTORY_TOOL_VISUALS).forEach(([id, visual]) => {
    if (!id.startsWith("tool.") || id.startsWith("tool.suite") || id.startsWith("tool.author")) return;
    push(catalogTileFromVisual(id, visual));
  });

  NEYVIA_CHAT_PROGRESSIVE_EXTRA.forEach(id => {
    const visual = NEYVIA_TOOL_VISUALS[id] || NEYVIA_INVENTORY_TOOL_VISUALS[id];
    if (!visual) return;
    push(catalogTileFromVisual(id, visual));
  });

  return Object.freeze(tiles);
}

/**
 * Chat tools catalog — priority session stubs + full managed suite + progressive extras.
 * All inventory tiles stay honest not_connected until an execute path binds.
 */
export const NEYVIA_CHAT_TOOL_CATALOG = buildExpandedChatToolCatalog();

/**
 * Group catalog tiles by category for Chat Tools / Library browsers.
 * @param {readonly object[]} [catalog]
 */
export function groupNeyviaChatToolsByCategory(catalog = NEYVIA_CHAT_TOOL_CATALOG) {
  const groups = new Map();
  for (const tool of catalog) {
    const category = String(tool.category || getNeyviaToolVisual(tool.id).category || "inventory");
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(tool);
  }
  const ordered = NEYVIA_TOOL_CATEGORY_ORDER.filter(key => groups.has(key)).map(key =>
    Object.freeze({ category: key, label: titleizeNeyviaCategory(key), tools: Object.freeze(groups.get(key)) }),
  );
  for (const [key, tools] of groups.entries()) {
    if (NEYVIA_TOOL_CATEGORY_ORDER.includes(key)) continue;
    ordered.push(Object.freeze({ category: key, label: titleizeNeyviaCategory(key), tools: Object.freeze(tools) }));
  }
  return Object.freeze(ordered);
}

function titleizeNeyviaCategory(value = "") {
  return String(value || "Tools")
    .replace(/[_/-]+/g, " ")
    .replace(/\b\w/g, ch => ch.toUpperCase());
}

/** Managed suite tiles only (tool.* lock entries) for Library. */
export const NEYVIA_MANAGED_SUITE_CATALOG = Object.freeze(
  Object.entries(NEYVIA_INVENTORY_TOOL_VISUALS)
    .filter(([id]) => id.startsWith("tool.") && !id.startsWith("tool.suite") && !id.startsWith("tool.author"))
    .map(([id, visual]) => catalogTileFromVisual(id, visual)),
);

/** Demo library files for typed icon coverage (not claimed as real workspace data). */
export const NEYVIA_LIBRARY_FILE_STUBS = Object.freeze([
  Object.freeze({ id: "stub-pdf", name: "brief.pdf", kind: "pdf", detail: "Document shell — not loaded" }),
  Object.freeze({ id: "stub-csv", name: "metrics.csv", kind: "csv", detail: "Table shell — not loaded" }),
  Object.freeze({ id: "stub-img", name: "moodboard.png", kind: "image", detail: "Image shell — not loaded" }),
  Object.freeze({ id: "stub-3d", name: "prop.gltf", kind: "3d", detail: "3D shell — adapter idle" }),
  Object.freeze({ id: "stub-md", name: "notes.md", kind: "md", detail: "Markdown shell — not loaded" }),
  Object.freeze({ id: "stub-json", name: "receipt.json", kind: "json", detail: "Receipt shell — not loaded" }),
  Object.freeze({ id: "stub-vid", name: "walkthrough.mp4", kind: "video", detail: "Video shell — not loaded" }),
  Object.freeze({ id: "stub-code", name: "handler.py", kind: "code", detail: "Code shell — not loaded" }),
]);

const ALIAS_INDEX = (() => {
  /** @type {Map<string, string>} */
  const map = new Map();
  for (const [id, visual] of Object.entries(NEYVIA_TOOL_VISUALS)) {
    map.set(id.toLowerCase(), id);
    map.set(id.replace(/[._-]/g, "").toLowerCase(), id);
    for (const alias of visual.aliases || []) {
      map.set(String(alias).toLowerCase(), id);
      map.set(String(alias).replace(/[._-]/g, "").toLowerCase(), id);
    }
  }
  return map;
})();

/**
 * Resolve a tool id / alias / free-text blob to a registry key.
 * @param {string} [toolIdOrBlob]
 * @returns {string}
 */
export function resolveNeyviaToolId(toolIdOrBlob = "") {
  const raw = String(toolIdOrBlob || "").trim();
  if (!raw) return "unknown";
  const lower = raw.toLowerCase();
  if (NEYVIA_TOOL_VISUALS[raw]) return raw;
  if (ALIAS_INDEX.has(lower)) return ALIAS_INDEX.get(lower);
  const compact = lower.replace(/[._\s-]+/g, "");
  if (ALIAS_INDEX.has(compact)) return ALIAS_INDEX.get(compact);

  // Authored tools are dynamic — use shared authored visual
  if (lower.startsWith("authored.") || lower.includes("authored_tool") || lower.includes("authored-tool")) {
    return "authored";
  }

  // Heuristic match against known tokens in activity stream text
  for (const [alias, id] of ALIAS_INDEX.entries()) {
    if (alias.length >= 4 && lower.includes(alias)) return id;
  }
  if (/\b(pdf|document)\b/.test(lower)) return "pdf";
  if (/\b(search|web)\b/.test(lower)) return "search";
  if (/\b(translat)/.test(lower)) return "translate";
  if (/\b(grammar|spell|languagetool|redline)\b/.test(lower)) return "grammar-correct";
  if (/\b(research|zotero|literature)\b/.test(lower)) return "research";
  if (/\b(ocr|tesseract)\b/.test(lower)) return "document.fast-ocr";
  if (/\b(latex|miktex)\b/.test(lower)) return "document.latex-production";
  if (/\b(gltf|3d|scene|mesh|blender)\b/.test(lower)) return "scene";
  if (/\b(cad|freecad|openscad)\b/.test(lower)) return "maker.cad-fabrication";
  if (/\b(attach|upload|paperclip)\b/.test(lower)) return "attach";
  if (/\b(diff|patch)\b/.test(lower)) return "diff";
  if (/\b(terminal|shell|bash|powershell)\b/.test(lower)) return "terminal";
  if (/\b(compos|stream|writ)/.test(lower)) return "compose";
  if (/\b(specialist|sub.?agent|roster)\b/.test(lower)) return "specialists";
  if (/\b(mcp)\b/.test(lower)) return "mcp.call";
  if (/\b(ui\.(ls|find|get|do|see|observe|wait|diff))\b/.test(lower)) return lower.match(/ui\.\w+/)?.[0] || "ui.observe";
  return "unknown";
}

/**
 * @param {string} [toolIdOrBlob]
 * @returns {NeyviaToolVisual}
 */
export function getNeyviaToolVisual(toolIdOrBlob = "") {
  const id = resolveNeyviaToolId(toolIdOrBlob);
  return NEYVIA_TOOL_VISUALS[id] || NEYVIA_TOOL_VISUALS.unknown;
}

/**
 * Build class list for a conversation / live-action tool chip.
 * @param {string} [toolIdOrBlob]
 * @param {NeyviaToolPhase|string} [phase]
 */
export function neyviaToolChipClasses(toolIdOrBlob = "", phase = "idle") {
  const id = resolveNeyviaToolId(toolIdOrBlob);
  const visual = getNeyviaToolVisual(id);
  const phaseKey = String(phase || "idle").toLowerCase();
  const phaseClass = NEYVIA_TOOL_PHASE_CLASSES[phaseKey] || NEYVIA_TOOL_PHASE_CLASSES.idle;
  return [
    "neyvia-tool-chip",
    visual.chipClass || "neyvia-chip-unknown",
    visual.animationClass,
    phaseClass,
    `neyvia-tool-id-${id.replace(/[^a-z0-9_-]+/gi, "-")}`,
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * Label for a chip given tool + phase.
 * @param {string} [toolIdOrBlob]
 * @param {NeyviaToolPhase|string} [phase]
 */
/**
 * Turn a raw tool identifier into something a person would say.
 *
 * Used only when a tool is not in the registry. The previous fallback was the
 * literal word "Tool", which told the reader nothing and hid which tool had
 * actually run — the developer name is a far better answer than a generic one.
 *
 * MCP is the case that cannot be pre-registered: server names arrive at runtime,
 * so they are formatted as "Server · Action" rather than "mcp.call".
 *
 * @param {string} [rawId]
 * @returns {string}
 */
export function humanizeNeyviaToolId(rawId = "") {
  const raw = String(rawId || "").trim();
  if (!raw) return "Tool";

  // Sentence case, not title case: a chip reads better as "Fetch user profile"
  // than "Fetch User Profile". Words that are entirely uppercase are left alone
  // so acronyms survive — PDF, API, URL stay themselves.
  const words = (value) =>
    value
      .replace(/[._-]+/g, " ")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/\s+/g, " ")
      .trim()
      .split(" ")
      .map((word) => (word === word.toUpperCase() ? word : word.toLowerCase()))
      .join(" ");

  const mcp = raw.match(/^mcp[._-]+([^._-]+)[._-]+(.+)$/i);
  if (mcp) {
    const server = words(mcp[1]);
    const action = words(mcp[2]);
    return `${server.charAt(0).toUpperCase()}${server.slice(1)} · ${action.charAt(0).toLowerCase()}${action.slice(1)}`;
  }

  // Command handlers carry wrapper affixes that are noise to a reader.
  const stripped = raw
    .replace(/_command$/i, "")
    .replace(/^(tool|fn|handler)[._-]+/i, "");
  const text = words(stripped);
  if (!text) return "Tool";
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

export function neyviaToolPhaseLabel(toolIdOrBlob = "", phase = "idle") {
  const id = resolveNeyviaToolId(toolIdOrBlob);
  const phaseKey = String(phase || "idle").toLowerCase();

  // Keyed off the resolved id rather than the label text: the fallback entry's
  // phase labels ("Running", "Done", "Failed") are not the word "Tool", so
  // comparing text would let every unregistered tool keep its generic wording.
  if (id === "unknown") {
    const named = humanizeNeyviaToolId(toolIdOrBlob);
    if (named !== "Tool") return named;
  }

  const visual = getNeyviaToolVisual(id);
  return visual.labels?.[phaseKey] || visual.labels?.idle || visual.labels?.call || "Tool";
}

/**
 * Infer phase from live-action row shape (honest — uses pending/tone only).
 * @param {{pending?: boolean, tone?: string, status?: string}} [row]
 * @returns {NeyviaToolPhase}
 */
function inferNeyviaToolPhaseUnchecked(row = {}) {
  const tone = String(row.tone || "").toLowerCase();
  const status = String(row.status || "").toLowerCase();
  if (["failed", "error", "down", "danger"].includes(tone) || ["failed", "error", "timeout", "timed_out"].includes(status)) return "error";
  if (["cancelled", "canceled", "uncertain", "unknown", "blocked", "waiting_approval"].includes(status)) return "idle";
  if (row.pending || status === "running" || status === "streaming") return "running";
  if (["good", "completed", "success"].includes(tone) || ["success", "completed", "succeeded"].includes(status)) return "success";
  if (status === "call" || status === "queued") return "call";
  if (status === "composing" || status === "writing") return "composing";
  return "idle";
}

/** Chip / event tokens that should render as NeyviaToolCallChip in conversation history. */
const NEYVIA_TOOL_EVENT_CHIP_RE =
  /\b(tool[-_\s]?call|tool[-_\s]?result|tool[-_\s]?use|function[-_\s]?call|agent[-_\s]?write|compos(e|ing)|streaming|research|translat|grammar|ocr|mcp\.|ui\.|pdf|specialist|sub[-_\s]?agent|authored|file[-_\s]?attach|web[-_\s]?search|web[-_\s]?capture|languagetool|argos|tesseract|blender|cad)\b/i;

/**
 * True when a message chip / label looks like a tool invocation event (not pure provenance).
 * @param {string|object} chip
 */
export function isNeyviaToolEventChip(chip) {
  if (chip && typeof chip === "object") {
    const kind = String(chip.kind || chip.type || chip.event || "").toLowerCase();
    if (["tool", "tool-call", "tool-result", "tool_call", "tool_result", "agent-write", "compose", "process"].includes(kind)) {
      return true;
    }
    if (chip.toolId || chip.tool_id || chip.toolName) return true;
    return isNeyviaToolEventChip(chip.label || chip.title || chip.text || chip.id || "");
  }
  const text = String(chip || "").trim();
  if (!text) return false;
  // Skip pure provenance / session meta chips
  if (/^(real (runtime|model|transcript)|recovered persisted|fresh runtime|runtime output|live data|no fallback|proof attached|collapsed|live)$/i.test(text)) {
    return false;
  }
  if (NEYVIA_TOOL_EVENT_CHIP_RE.test(text)) return true;
  const resolved = resolveNeyviaToolId(text);
  return resolved !== "unknown";
}

/**
 * Resolve tool id + phase for a conversation message chip.
 * @param {string|object} chip
 * @param {{pending?: boolean, tone?: string, status?: string, messageKind?: string}} [message]
 */
function resolveNeyviaMessageChipUnchecked(chip, message = {}) {
  const raw =
    typeof chip === "object" && chip
      ? String(chip.toolId || chip.tool_id || chip.toolName || chip.label || chip.title || chip.text || chip.id || "").trim()
      : String(chip || "").trim();
  const toolId = resolveNeyviaToolId(
    (typeof chip === "object" && (chip.toolId || chip.tool_id || chip.toolName)) || raw,
  );
  const lower = raw.toLowerCase();
  let phase = inferNeyviaToolPhase(typeof chip === "object" && chip ? {...message, ...chip} : message);
  const explicitState = typeof chip === "object" && chip && (chip.phase || chip.status || chip.tone);
  if (typeof chip === "object" && chip?.phase) phase = inferNeyviaToolPhase({status:chip.phase});
  else if (explicitState || phase === "error") { /* Preserve the recorded outcome. */ }
  else if (/\b(tool[-_\s]?call|calling|queued|invok)/i.test(lower)) phase = "call";
  else if (/\b(tool[-_\s]?result|result)\b/i.test(lower) && !message.pending) phase = "idle";
  else if (/\b(error|fail)/i.test(lower)) phase = "error";
  else if (/\b(agent[-_\s]?write|compos|stream|writing)\b/i.test(lower) || message.pending) phase = message.pending ? "composing" : "running";
  else if (/\b(running|in progress)\b/i.test(lower)) phase = "running";
  return {
    toolId,
    phase,
    title: typeof chip === "object" ? chip.title || chip.label || raw : raw,
    detail: typeof chip === "object" ? chip.detail || chip.meta || "" : "",
    isToolEvent: isNeyviaToolEventChip(chip),
  };
}

/**
 * Resolve file kind visual from name / mime / explicit kind.
 * @param {{name?: string, mime?: string, kind?: string, path?: string}} [file]
 */
export function getNeyviaFileTypeVisual(file = {}) {
  const kindHint = String(file.kind || "").toLowerCase();
  if (NEYVIA_FILE_TYPE_VISUALS[kindHint]) return { id: kindHint, ...NEYVIA_FILE_TYPE_VISUALS[kindHint] };

  const mime = String(file.mime || "").toLowerCase();
  const name = String(file.name || file.path || "").toLowerCase();
  const ext = name.includes(".") ? name.split(".").pop() : "";

  if (mime.includes("pdf") || ext === "pdf") return { id: "pdf", ...NEYVIA_FILE_TYPE_VISUALS.pdf };
  if (mime.includes("csv") || ext === "csv") return { id: "csv", ...NEYVIA_FILE_TYPE_VISUALS.csv };
  if (mime.includes("sheet") || ["xlsx", "xls"].includes(ext)) return { id: "xlsx", ...NEYVIA_FILE_TYPE_VISUALS.xlsx };
  if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) {
    return { id: "image", ...NEYVIA_FILE_TYPE_VISUALS.image };
  }
  if (["gltf", "glb", "obj", "fbx", "usd", "usdz"].includes(ext) || kindHint === "3d") {
    return { id: "3d", ...NEYVIA_FILE_TYPE_VISUALS["3d"] };
  }
  if (ext === "md" || mime.includes("markdown")) return { id: "md", ...NEYVIA_FILE_TYPE_VISUALS.md };
  if (["doc", "docx", "rtf", "txt"].includes(ext)) return { id: "docx", ...NEYVIA_FILE_TYPE_VISUALS.docx };
  if (ext === "json" || mime.includes("json")) return { id: "json", ...NEYVIA_FILE_TYPE_VISUALS.json };
  if (mime.startsWith("video/") || ["mp4", "webm", "mov"].includes(ext)) {
    return { id: "video", ...NEYVIA_FILE_TYPE_VISUALS.video };
  }
  if (mime.startsWith("audio/") || ["mp3", "wav", "ogg"].includes(ext)) {
    return { id: "audio", ...NEYVIA_FILE_TYPE_VISUALS.audio };
  }
  if (["zip", "tar", "gz", "7z"].includes(ext)) return { id: "zip", ...NEYVIA_FILE_TYPE_VISUALS.zip };
  if (["js", "jsx", "ts", "tsx", "py", "rs", "go", "java", "css", "html"].includes(ext)) {
    return { id: "code", ...NEYVIA_FILE_TYPE_VISUALS.code };
  }
  return { id: "unknown", ...NEYVIA_FILE_TYPE_VISUALS.unknown };
}

/**
 * Panel enter class for overlays / drawers.
 * @param {string} [panelId]
 */
export function neyviaPanelEnterClass(panelId = "") {
  const key = String(panelId || "").toLowerCase();
  return NEYVIA_PANEL_ENTER_CLASSES[key] || NEYVIA_PANEL_ENTER_CLASSES.default;
}

/**
 * All registered tool ids (for coverage checks / docs).
 */
export function listNeyviaToolVisualIds() {
  return Object.keys(NEYVIA_TOOL_VISUALS).filter(id => id !== "unknown");
}

export function inferNeyviaToolPhase(...args) { return checkedChatAction("phase", args, inferNeyviaToolPhaseUnchecked(...args)); }

export function resolveNeyviaMessageChip(...args) { return checkedChatAction("chip", args, resolveNeyviaMessageChipUnchecked(...args)); }
