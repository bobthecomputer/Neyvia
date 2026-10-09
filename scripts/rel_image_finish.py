"""One bounded migration of retained Image Studio styles and fresh defaults."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'web/src/neyvia'
css = root / 'imagePlaygroundScoped.css'
text = css.read_text(encoding='utf8').replace('.nx-classic-image-playground', '.nx-tool-screen-image-playground').replace('.nx-tool-image-playground', '.nx-tool-screen-image-playground')
text = re.sub(r'^/\*.*?\*/', '/* Image Studio owns these scoped rules; palette tokens come from nxAppSkins.css. */', text, count=1, flags=re.S)
css.write_text(text, encoding='utf8')
state = root / 'imagePlaygroundState.js'
text = state.read_text(encoding='utf8')
start = text.index('export const IMAGEGEN_LIBRARY_ARTIFACT') if 'export const IMAGEGEN_LIBRARY_ARTIFACT' in text else text.index('export const DEFAULT_IMAGE_PROJECT')
end = text.index('export function isRealImageSession', start)
text = text[:start] + '''// Fresh workspaces are empty. Existing stored layers and receipts are preserved.
export const DEFAULT_IMAGE_PROJECT = {
  id: "image-project-local", title: "Untitled image workspace", updatedAt: "",
  canvas: { width: 1024, height: 1024, background: "#111313", zoom: 0.62 },
  prompt: { mode: "generate", text: "", negative: "", style: "", strength: 0.72, preserveComposition: true },
  provider: { id: "codex_subscription_gpt_image2", model: "gpt-image-2", quality: "high", size: "1024x1024" },
  designReferences: [], annotationReadiness: { pins: [], rectangles: [], layers: [], comments: [] },
  skillsEvidence: [], focusedHistoryId: "", opsThreads: [], selectedLayerId: "", activeTool: "select",
  selection: { x: 0, y: 0, width: 0, height: 0, feather: 18, visible: false }, layers: [], history: [],
};

''' + text[end:]
text = text.replace('Array.isArray(next.layers) && next.layers.length ? next.layers : base.layers', 'Array.isArray(next.layers) ? next.layers : base.layers')
state.write_text(text, encoding='utf8')
view = root / 'ImagePlayground.jsx'
text = view.read_text(encoding='utf8').replace('className="reference-kicker"', 'className="image-kicker"')
text = text.replace('.reference-shell, .reference-main, .reference-main-panel, .reference-main-body, .image-playground-shell', '.nx-tool-screen-image-playground, .image-playground-shell')
text = text.replace('<h1>Image Generator</h1>', '<h1>Image Studio</h1>')
text = text.replace('This button bypasses the canvas-snapshot flow and writes a served PNG artifact directly into the workbench.', 'Choose a provider, describe your image, and inspect the result here. Generation needs a configured provider.')
view.write_text(text, encoding='utf8')
print('Image Studio scope and fresh defaults migrated; stored project data untouched')
