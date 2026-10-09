/** Refresh pinned upstream metadata only; never download or activate an engine. */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const specs = {
  'pack.documents-office': [
    ['github', 'jgm/pandoc', '3.10.1', 'pandoc-3.10.1-windows-x86_64.zip'],
    ['pypi', 'libretranslate', '1.9.6', 'libretranslate-1.9.6-py3-none-any.whl'],
  ],
  'pack.ocr-local': [
    ['pypi', 'paddleocr', '3.7.0', 'paddleocr-3.7.0-py3-none-any.whl'],
    ['pypi', 'ocrmypdf', '17.8.1', 'ocrmypdf-17.8.1-py3-none-any.whl'],
  ],
  'pack.android-lab': [['github', 'Genymobile/scrcpy', 'v4.1', 'scrcpy-win64-v4.1.zip']],
  'pack.developer-toolchains': [
    ['github', 'duckdb/duckdb', 'v1.5.4', 'duckdb_cli-windows-amd64.zip'],
    ['pypi', 'polars', '1.44.2', 'polars-1.44.2-py3-none-any.whl'],
  ],
  'pack.models-gpu': [
    ['pypi', 'torch', '2.14.1', 'torch-2.14.1-cp313-cp313-win_amd64.whl'],
    ['pypi', 'transformers', '5.18.0', 'transformers-5.18.0-py3-none-any.whl'],
  ],
  'pack.media-creative': [
    ['github', 'godotengine/godot', '4.7.1-stable', 'Godot_v4.7.1-stable_win64.exe.zip'],
    ['github', 'FreeCAD/FreeCAD', '1.1.0', 'FreeCAD_1.1.0-Windows-x86_64-py311.7z'],
  ],
  'pack.mesh-control-plane': [['github', 'juanfont/headscale', 'v0.29.4', 'headscale_0.29.4_linux_amd64']],
};
const blockers = {
  'pack.documents-office': ['Provide portable Poppler, LibreOffice, LaTeX, LanguageTool and Argos payloads with redistribution provenance; resolve and lock translation/model dependencies.', 'Pandoc archive and LibreTranslate wheel are pinned source inputs; extraction, dependencies and scoped runtime activation remain.'],
  'pack.ocr-local': ['Provide pinned GLM-OCR model, compatible inference runtime, Tesseract and Paddle runtime/models; approve any model payload above 200 MB.', 'PaddleOCR and OCRmyPDF wheels are pinned inputs; native dependencies, models and runtime activation remain.'],
  'pack.android-lab': ['Select and approve Android SDK components and licenses; provide Appium server/driver lock and portable Node runtime.', 'scrcpy archive is pinned; extraction and physical device authorization remain.'],
  'pack.developer-toolchains': ['Provide scoped Git, Docker engine and PostgreSQL payloads; choose a scientific Python dependency lock and compatible portable environment.', 'DuckDB archive and Polars frontend wheel are pinned; native Polars runtime and dependency installation remain.'],
  'pack.models-gpu': ['Choose and approve a GPU/CUDA-compatible torch build and complete dependency lock; the pinned PyPI wheel is a CPU/source input, not proof of GPU readiness.', 'Select authorized model weights, licenses and evaluation payloads; approve each download above 200 MB.'],
  'pack.media-creative': ['Approve FreeCAD portable archive (418105231 bytes, above 200 MB) before downloading.', 'Provide pinned FFmpeg, ImageMagick, GIMP, Blender, KiCad, OpenSCAD, Inkscape and Scribus payloads and extraction/runtime adapters.', 'Godot and FreeCAD source archives are pinned; extraction and engine launch verification remain.'],
  'pack.mesh-control-plane': ['Approve target Linux/NAS worker and protected control-plane configuration; the pinned Linux Headscale binary does not run on Windows.', 'Provide private WireGuard relay, DNS/routes/policy deployment payload and protected identity; no network services are changed by this track.'],
};
async function metadata(spec) {
  const [kind, project, version, filename] = spec;
  const url = kind === 'github' ? `https://api.github.com/repos/${project}/releases/tags/${version}` : `https://pypi.org/pypi/${project}/${version}/json`;
  const response = await fetch(url, { headers: { 'User-Agent': 'neyvia-release-source-lock' } });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const body = await response.json();
  const asset = (kind === 'github' ? body.assets : body.urls).find(item => (item.name || item.filename) === filename);
  if (!asset) throw new Error(`Pinned asset not found: ${filename}`);
  const sha256 = kind === 'github' ? asset.digest?.replace(/^sha256:/, '') : asset.digests.sha256;
  if (!/^[a-f0-9]{64}$/.test(sha256 || '')) throw new Error(`Upstream did not publish SHA-256: ${filename}; use a locally reviewed payload instead.`);
  return { path: 'inputs/' + filename, url: asset.browser_download_url || asset.url, size: asset.size, sha256,
    source: { project, version, metadataUrl: url, kind, role: 'source-input', platform: /linux/.test(filename) ? 'linux-amd64' : /whl/.test(filename) ? 'python' : 'windows-amd64' }, requiresPaulApproval: asset.size > 200_000_000 };
}
const registryPath = join(root, 'config/onboarding_packs.json');
const registry = JSON.parse(readFileSync(registryPath));
for (const [packId, selections] of Object.entries(specs)) {
  const files = await Promise.all(selections.map(metadata));
  const totalSize = files.reduce((sum, row) => sum + row.size, 0);
  const version = createHash('sha256').update(JSON.stringify(files)).digest('hex').slice(0, 16);
  const manifest = { schema: 'neyvia.base-pack/v1', packId, version, channel: 'external-source-inputs', deliveryStatus: 'needs-paul',
    description: 'Pinned upstream source artifacts; incomplete runtime delivery. Downloading these files does not install or activate the pack.',
    totalSize, files, needsPaul: blockers[packId] };
  const relative = `config/onboarding_packs/${packId}/manifest.json`;
  mkdirSync(dirname(join(root, relative)), { recursive: true });
  writeFileSync(join(root, relative), JSON.stringify(manifest, null, 2) + '\n');
  registry.manifests[packId] = relative;
  registry.packages[packId].sourceInputs = files.map(file => file.path);
  registry.packages[packId].missing = blockers[packId];
  console.log(`${packId}: ${files.length} SHA-256-pinned official source inputs, ${totalSize} bytes; needs-paul`);
}
writeFileSync(registryPath, JSON.stringify(registry, null, 2) + '\n');
