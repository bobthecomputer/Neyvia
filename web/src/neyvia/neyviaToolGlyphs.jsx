/**
 * Neyvia custom tool glyphs — distinct SVG marks where Lucide collides
 * (research vs search, PDF vs citations, translate vs languages pack, etc.).
 * Presentation only; never implies backend execution success.
 */

const GLYPH_SIZE = 14;

function GlyphShell({ children, size = GLYPH_SIZE, className = "", title }) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      className={className || undefined}
      fill="none"
      height={size}
      role={title ? "img" : undefined}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.75"
      viewBox="0 0 24 24"
      width={size}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

/** Magnifier + book spine — research (not plain Search). */
export function NeyviaGlyphResearch(props) {
  return (
    <GlyphShell {...props}>
      <path d="M4 5h8v14H4z" />
      <path d="M7 8h2M7 11h2M7 14h1.5" />
      <circle cx="16.5" cy="15.5" r="3.2" />
      <path d="m18.8 17.8 2 2" />
    </GlyphShell>
  );
}

/** Folded page + corner mark — PDF / documents. */
export function NeyviaGlyphPdf(props) {
  return (
    <GlyphShell {...props}>
      <path d="M7 3h7l5 5v13H7z" />
      <path d="M14 3v5h5" />
      <path d="M9.5 13h5M9.5 16h3.5" />
      <path d="M9.5 10h2.2" />
    </GlyphShell>
  );
}

/** Dual arrows between A / B blocks — translate. */
export function NeyviaGlyphTranslate(props) {
  return (
    <GlyphShell {...props}>
      <path d="M4 7h7M7.5 7v2.5c0 2.2-1.4 3.5-3.5 4" />
      <path d="M9.5 13.5 8 16" />
      <path d="M14 8h6M17 8v8" />
      <path d="M14 16h6" />
      <path d="m13 11 2.5-2.5L18 11" />
      <path d="m11 13-2.5 2.5L6 13" />
    </GlyphShell>
  );
}

/** Check + underline squiggle — grammar correct. */
export function NeyviaGlyphGrammar(props) {
  return (
    <GlyphShell {...props}>
      <path d="M5 12.5 8.5 16 14 8" />
      <path d="M4 19c1.2-.9 2.4-1.4 4-1.4s2.8.5 4 1.4c1.2-.9 2.4-1.4 4-1.4s2.8.5 4 1.4" />
    </GlyphShell>
  );
}

/** Scan frame + text lines — OCR. */
export function NeyviaGlyphOcr(props) {
  return (
    <GlyphShell {...props}>
      <path d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3" />
      <path d="M8 9h8M8 12h6M8 15h4" />
    </GlyphShell>
  );
}

/** Cube with orbit ring — 3D / CAD / scene. */
export function NeyviaGlyphCad(props) {
  return (
    <GlyphShell {...props}>
      <path d="m12 4 6 3.5v7L12 18l-6-3.5v-7Z" />
      <path d="M12 11.5 18 8M12 11.5 6 8M12 11.5V18" />
      <ellipse cx="12" cy="12" rx="9" ry="3.2" opacity="0.55" />
    </GlyphShell>
  );
}

/** Shield with lock notch — security. */
export function NeyviaGlyphSecurity(props) {
  return (
    <GlyphShell {...props}>
      <path d="M12 3 19 6.5v5.2c0 4.2-2.8 7.3-7 8.8-4.2-1.5-7-4.6-7-8.8V6.5Z" />
      <rect height="5" rx="1" width="6" x="9" y="10.5" />
      <path d="M12 10.5V9.2a1.3 1.3 0 0 1 2.6 0V10.5" />
    </GlyphShell>
  );
}

/** Paperclip + corner fold — file / attach. */
export function NeyviaGlyphFile(props) {
  return (
    <GlyphShell {...props}>
      <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v5h5" />
      <path d="M10.2 14.2a1.6 1.6 0 0 1 2.3-2.2l2.4 2.4a1.1 1.1 0 0 1-1.6 1.5l-1.7-1.7" />
    </GlyphShell>
  );
}

/** Plug + node ring — MCP. */
export function NeyviaGlyphMcp(props) {
  return (
    <GlyphShell {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 5v2.2M12 16.8V19M5 12h2.2M16.8 12H19" />
      <path d="M7.2 7.2 8.8 8.8M15.2 15.2l1.6 1.6M16.8 7.2 15.2 8.8M8.8 15.2 7.2 16.8" />
      <path d="M9.5 19.5h5M9.5 4.5h5" opacity="0.45" />
    </GlyphShell>
  );
}

/** Spark + pencil — authored tools. */
export function NeyviaGlyphAuthored(props) {
  return (
    <GlyphShell {...props}>
      <path d="m14.5 4.5 1.2 2.6 2.6 1.2-2.6 1.2-1.2 2.6-1.2-2.6-2.6-1.2 2.6-1.2Z" />
      <path d="M5 19.5 13 11.5l2.2 2.2L7.2 21.7H5z" />
    </GlyphShell>
  );
}

/** Streaming caret waves — compose / agent-write. */
export function NeyviaGlyphCompose(props) {
  return (
    <GlyphShell {...props}>
      <path d="M5 7h10M5 11h14M5 15h8" />
      <path d="M17.5 14.5v5.5" />
      <path d="M15.5 20h4" opacity="0.7" />
    </GlyphShell>
  );
}

/**
 * Glyph key → component. Keys match category / dedicated tool ids.
 */
export const NEYVIA_TOOL_GLYPHS = Object.freeze({
  research: NeyviaGlyphResearch,
  pdf: NeyviaGlyphPdf,
  "document.pdf-analysis": NeyviaGlyphPdf,
  translate: NeyviaGlyphTranslate,
  "writing.translation-alignment": NeyviaGlyphTranslate,
  "tool.argos-translate": NeyviaGlyphTranslate,
  "grammar-correct": NeyviaGlyphGrammar,
  "incorrect-grammar": NeyviaGlyphGrammar,
  "tool.languagetool": NeyviaGlyphGrammar,
  "writing.editorial-redline": NeyviaGlyphGrammar,
  ocr: NeyviaGlyphOcr,
  "document.fast-ocr": NeyviaGlyphOcr,
  "tool.tesseract": NeyviaGlyphOcr,
  "tool.ocrmypdf": NeyviaGlyphOcr,
  "tool.paddleocr": NeyviaGlyphOcr,
  scene: NeyviaGlyphCad,
  "object-to-design": NeyviaGlyphCad,
  "maker.cad-fabrication": NeyviaGlyphCad,
  "tool.blender": NeyviaGlyphCad,
  "tool.freecad": NeyviaGlyphCad,
  "tool.openscad": NeyviaGlyphCad,
  "three-d.blender-scene": NeyviaGlyphCad,
  security: NeyviaGlyphSecurity,
  "security.ai-red-team": NeyviaGlyphSecurity,
  "security.threat-model": NeyviaGlyphSecurity,
  "tool.trivy": NeyviaGlyphSecurity,
  "tool.semgrep": NeyviaGlyphSecurity,
  "tool.owasp-zap": NeyviaGlyphSecurity,
  "tool.ghidra": NeyviaGlyphSecurity,
  file: NeyviaGlyphFile,
  attach: NeyviaGlyphFile,
  "file-attached": NeyviaGlyphFile,
  "artifact.register": NeyviaGlyphFile,
  mcp: NeyviaGlyphMcp,
  "mcp.call": NeyviaGlyphMcp,
  "mcp.list_tools": NeyviaGlyphMcp,
  authored: NeyviaGlyphAuthored,
  "tool.author.search": NeyviaGlyphAuthored,
  "tool.author.execute": NeyviaGlyphAuthored,
  compose: NeyviaGlyphCompose,
});

/** Category → glyph when tool id has no dedicated mark but category collides. */
export const NEYVIA_CATEGORY_GLYPHS = Object.freeze({
  research: NeyviaGlyphResearch,
  pdf: NeyviaGlyphPdf,
  documents: NeyviaGlyphPdf,
  translate: NeyviaGlyphTranslate,
  grammar: NeyviaGlyphGrammar,
  ocr: NeyviaGlyphOcr,
  "design/3d": NeyviaGlyphCad,
  maker: NeyviaGlyphCad,
  security: NeyviaGlyphSecurity,
  file: NeyviaGlyphFile,
  mcp: NeyviaGlyphMcp,
  authored: NeyviaGlyphAuthored,
  compose: NeyviaGlyphCompose,
  writing: NeyviaGlyphCompose,
});

/**
 * Resolve a custom glyph for a tool id / category, or null to fall back to Lucide.
 * @param {string} [toolId]
 * @param {string} [category]
 */
export function resolveNeyviaToolGlyph(toolId = "", category = "") {
  const id = String(toolId || "").trim();
  if (id && NEYVIA_TOOL_GLYPHS[id]) return NEYVIA_TOOL_GLYPHS[id];
  const cat = String(category || "").trim().toLowerCase();
  if (cat && NEYVIA_CATEGORY_GLYPHS[cat]) return NEYVIA_CATEGORY_GLYPHS[cat];
  return null;
}
