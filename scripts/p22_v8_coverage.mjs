// Map a passing Obscura V8 precise-coverage snapshot through the exact built
// assets that the browser executed. A receipt describes one grouped journey;
// it never claims that each line belongs to each contract in that journey.
import { readFile, realpath, stat, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
import { TraceMap, decodedMappings } from '@jridgewell/trace-mapping';

const args = process.argv.slice(2);
const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
const normalized = text => text.replace(/\r\n?/g, '\n');
const digest = text => createHash('sha256').update(normalized(text), 'utf8').digest('hex');
const isInside = (parent, child) => {
  const rel = relative(parent, child);
  return rel === '' || (rel !== '..' && !rel.startsWith('..' + sep) && !isAbsolute(rel));
};

function positions(source) {
  const starts = [0];
  for (let i = 0; i < source.length; i++) if (source.charCodeAt(i) === 10) starts.push(i + 1);
  return offset => {
    let low = 0, high = starts.length;
    while (low < high) { const mid = (low + high) >> 1; if (starts[mid] <= offset) low = mid + 1; else high = mid; }
    const line = Math.max(0, low - 1);
    // JavaScript string offsets and source-map columns both count UTF-16 code units.
    return { line: line + 1, column: offset - starts[line] };
  };
}

function hitOffsets(script) {
  if (!Array.isArray(script.functions)) throw new Error('V8 script has no function ranges');
  const ranges = [];
  for (const fn of script.functions) {
    if (!fn || !Array.isArray(fn.ranges)) throw new Error('V8 function has no range list');
    for (const row of fn.ranges) {
      if (!row || !Number.isInteger(row.startOffset) || !Number.isInteger(row.endOffset)
          || row.startOffset < 0 || row.startOffset >= row.endOffset || row.endOffset > script.source.length
          || !Number.isInteger(row.count) || row.count < 0) {
        throw new Error('V8 coverage contains an invalid offset range or count');
      }
      ranges.push(row);
    }
  }
  // Detailed precise-coverage ranges are nested or disjoint. A crossing or
  // equal-span count conflict has no unambiguous most-specific owner.
  const ordered = [...ranges].sort((a,b) => a.startOffset - b.startOffset || b.endOffset - a.endOffset);
  const stack = [];
  for (const row of ordered) {
    while (stack.length && row.startOffset >= stack.at(-1).endOffset) stack.pop();
    const parent = stack.at(-1);
    if (parent && (row.endOffset > parent.endOffset
        || (row.startOffset === parent.startOffset && row.endOffset === parent.endOffset && row.count !== parent.count))) {
      throw new Error('V8 coverage ranges overlap ambiguously');
    }
    stack.push(row);
  }
  const boundaries = [...new Set(ranges.flatMap(row => [row.startOffset, row.endOffset]))].sort((a,b) => a-b);
  const hits = [];
  for (let i = 0; i + 1 < boundaries.length; i++) {
    const start = boundaries[i], end = boundaries[i + 1];
    const active = ranges.filter(row => row.startOffset <= start && row.endOffset >= end);
    if (!active.length) continue;
    // V8 nests ranges. The smallest enclosing range owns this segment, including
    // when that child has zero hits and an enclosing function has positive hits.
    const depth = Math.min(...active.map(row => row.endOffset - row.startOffset));
    if (active.some(row => row.endOffset - row.startOffset === depth && row.count > 0)) hits.push({ start, end });
  }
  return hits;
}

async function resolveObservedAsset(urlText, realBuild) {
  if (typeof urlText !== 'string' || !urlText) return null;
  let candidate;
  try {
    const url = new URL(urlText);
    if (url.protocol === 'file:') candidate = fileURLToPath(url);
    else if (url.protocol === 'http:' || url.protocol === 'https:') {
      const decoded = decodeURIComponent(url.pathname);
      candidate = resolve(realBuild, '.' + decoded);
    } else return null;
  } catch { return null; }
  try {
    const actual = await realpath(candidate);
    if (!isInside(realBuild, actual) || !['.js', '.mjs', '.cjs'].includes(extname(actual).toLowerCase())) return null;
    if (!(await stat(actual)).isFile()) return null;
    return actual;
  } catch { return null; }
}

async function parseMap(source, assetPath, realBuild) {
  const matches = source.match(/\/\/[#@]\s*sourceMappingURL=([^\s]+)/g);
  if (!matches?.length) return null;
  const ref = matches.at(-1).replace(/^\/\/[#@]\s*sourceMappingURL=/, '');
  if (ref.startsWith('data:')) {
    const split = ref.indexOf(','); if (split < 0) return null;
    const meta = ref.slice(0, split), body = ref.slice(split + 1);
    const text = meta.includes(';base64') ? Buffer.from(body, 'base64').toString('utf8') : decodeURIComponent(body);
    // Inline source maps resolve their source names beside the built JS asset.
    return { data: JSON.parse(text), url: pathToFileURL(assetPath + '.inline.map').href, ref };
  }
  let clean;
  try { clean = decodeURIComponent(ref.split(/[?#]/, 1)[0]); } catch { return null; }
  let candidate;
  try {
    const refUrl = new URL(clean);
    if (refUrl.protocol !== 'file:') return null;
    candidate = fileURLToPath(refUrl);
  } catch {
    if (/^[A-Za-z][A-Za-z\d+.-]*:/.test(clean) || clean.startsWith('//')) return null;
    candidate = clean.startsWith('/') ? resolve(realBuild, '.' + clean) : resolve(dirname(assetPath), clean);
  }
  try {
    const actual = await realpath(candidate);
    if (!isInside(realBuild, actual) || extname(actual).toLowerCase() !== '.map') return null;
    return { data: JSON.parse(await readFile(actual, 'utf8')), url: pathToFileURL(actual).href, ref, path: actual };
  } catch { return null; }
}

async function sourcePath(name, sourceRoot, mapURL, realRepo) {
  let value = name;
  try {
    if (/^file:/i.test(value)) value = fileURLToPath(value);
    else if (/^[A-Za-z]:[\\/]/.test(value)) value = resolve(value);
    else if (value.startsWith('/')) value = resolve(value);
    else {
      const base = sourceRoot ? new URL(sourceRoot, mapURL).href : mapURL;
      value = fileURLToPath(new URL(value, base));
    }
    value = await realpath(value);
  } catch { return null; }
  return isInside(realRepo, value) ? value : null;
}

function groupedMeasurement(contracts, declared) {
  const unique = [...new Set(contracts)];
  if (!unique.length || unique.some(id => typeof id !== 'string' || !id.trim())) throw new Error('Coverage requires named passing contracts');
  if (declared && (declared.kind !== 'grouped-outcome-journey' || declared.perContractAttribution !== false)) {
    throw new Error('This collector accepts only an explicitly grouped journey measurement');
  }
  if (declared?.contracts && JSON.stringify([...new Set(declared.contracts)].sort()) !== JSON.stringify([...unique].sort())) {
    throw new Error('Grouped measurement contract IDs do not match the passing contract list');
  }
  return { kind: 'grouped-outcome-journey', contracts: unique, perContractAttribution: false,
    attribution: 'union of executed source lines during the passing journey; no line is attributed to an individual contract' };
}

async function mapCoverage(raw, buildPath, repoPath) {
  const started = performance.now();
  if (!Array.isArray(raw.result) || !Array.isArray(raw.scripts) || !Array.isArray(raw.contracts) || !raw.contracts.length) {
    throw new Error('Raw coverage must contain V8 result, script source, and passing contract IDs');
  }
  const measurementUnit = groupedMeasurement(raw.contracts, raw.measurementUnit);
  const realRepo = await realpath(repoPath), realBuild = await realpath(buildPath);
  const scriptsById = new Map(raw.scripts.map(row => [String(row.scriptId), row]));
  const coveredByFile = new Map(), eligibleAssets = [], unmappedScripts = [], errors = [];
  const seenAssets = new Map();

  for (const entry of raw.result) {
    const sourceRow = scriptsById.get(String(entry.scriptId));
    if (!sourceRow || typeof sourceRow.source !== 'string') {
      unmappedScripts.push({ scriptId: entry.scriptId, url: entry.url, reason: 'missing-captured-script-source' });
      continue;
    }
    const assetPath = await resolveObservedAsset(sourceRow.url || entry.url, realBuild);
    if (!assetPath) {
      unmappedScripts.push({ scriptId: entry.scriptId, url: sourceRow.url || entry.url || '', reason: 'outside-measured-build-assets', relevant: false });
      continue;
    }
    const relativeAsset = relative(realBuild, assetPath).split(sep).join('/');
    const assetText = await readFile(assetPath, 'utf8');
    if (digest(assetText) !== digest(sourceRow.source)) {
      errors.push({ asset: relativeAsset, scriptId: entry.scriptId, reason: 'observed-script-source-differs-from-built-asset' });
      continue;
    }
    const assetDigest = digest(assetText);
    const previous = seenAssets.get(relativeAsset);
    if (previous && previous !== assetDigest) {
      errors.push({ asset: relativeAsset, reason: 'one-built-asset-produced-different-observed-sources' });
      continue;
    }
    seenAssets.set(relativeAsset, assetDigest);
    eligibleAssets.push({ path: relativeAsset, sha256: assetDigest });
    const parsedMap = await parseMap(sourceRow.source, assetPath, realBuild);
    if (!parsedMap) {
      unmappedScripts.push({ scriptId: entry.scriptId, url: sourceRow.url || entry.url, asset: relativeAsset, relevant: true,
        reason: 'eligible-built-app-asset-has-no-unambiguous-source-map' });
      continue;
    }
    try {
      const trace = new TraceMap(parsedMap.data, parsedMap.url);
      const hit = hitOffsets({ ...entry, source: sourceRow.source }), position = positions(sourceRow.source), mappings = decodedMappings(trace);
      const candidates = new Map();
      for (const range of hit) {
        const first = position(range.start), last = position(Math.max(range.start, range.end - 1));
        for (let line = first.line; line <= last.line; line++) {
          const lineStart = line === first.line ? first.column : 0;
          const lineEnd = line === last.line ? last.column + 1 : Number.MAX_SAFE_INTEGER;
          const segments = mappings[line - 1] || [];
          for (let i = 0; i < segments.length; i++) {
            const segment = segments[i], nextColumn = segments[i + 1]?.[0] ?? Number.MAX_SAFE_INTEGER;
            if (nextColumn <= lineStart || segment[0] >= lineEnd || segment.length < 4) continue;
            const sourceIndex = segment[1];
            if (!Number.isInteger(sourceIndex) || sourceIndex < 0 || sourceIndex >= trace.sources.length
                || !Number.isInteger(segment[2]) || segment[2] < 0) {
              errors.push({ asset: relativeAsset, scriptId: entry.scriptId, reason: 'source-map-segment-has-invalid-source-index-or-line' });
              continue;
            }
            const sourceName = trace.sources[sourceIndex];
            if (typeof sourceName !== 'string' || !sourceName) {
              errors.push({ asset: relativeAsset, scriptId: entry.scriptId, reason: 'source-map-index-has-no-source-name' });
              continue;
            }
            const resolved = await sourcePath(sourceName, parsedMap.data.sourceRoot, parsedMap.url, realRepo);
            if (!resolved) continue;
            const key = `${sourceIndex}\0${resolved}`;
            const candidate = candidates.get(key) || { sourceIndex, path: resolved, lines: new Set() };
            candidate.lines.add(segment[2] + 1); candidates.set(key, candidate);
          }
        }
      }
      let mapped = false;
      for (const { sourceIndex, path, lines } of candidates.values()) {
        const embedded = trace.sourcesContent?.[sourceIndex] ?? null;
        if (typeof embedded !== 'string') {
          errors.push({ asset: relativeAsset, path: relative(realRepo, path).split(sep).join('/'), reason: 'mapped-source-has-no-embedded-content' });
          continue;
        }
        const current = await readFile(path, 'utf8'), sourceHash = digest(current);
        if (digest(embedded) !== sourceHash) {
          errors.push({ asset: relativeAsset, path: relative(realRepo, path).split(sep).join('/'), reason: 'sourcemap-source-content-is-stale' });
          continue;
        }
        const sourceLineCount = normalized(current).split('\n').length;
        if ([...lines].some(line => line < 1 || line > sourceLineCount)) {
          errors.push({ asset: relativeAsset, path: relative(realRepo, path).split(sep).join('/'), reason: 'source-map-original-line-is-out-of-bounds' });
          continue;
        }
        const rel = relative(realRepo, path).split(sep).join('/');
        const existing = coveredByFile.get(rel) || new Set();
        for (const line of lines) existing.add(line);
        coveredByFile.set(rel, existing); mapped = true;
      }
      if (!mapped) unmappedScripts.push({ scriptId: entry.scriptId, url: sourceRow.url || entry.url, asset: relativeAsset, relevant: true,
        reason: 'eligible-built-app-asset-has-no-current-repository-lines-mapped' });
    } catch (error) {
      unmappedScripts.push({ scriptId: entry.scriptId, url: sourceRow.url || entry.url, asset: relativeAsset, relevant: true, reason: String(error).slice(0, 500) });
    }
  }

  const files = {};
  for (const [path, lines] of [...coveredByFile].sort(([a],[b]) => a.localeCompare(b))) {
    const full = resolve(realRepo, path), content = await readFile(full, 'utf8');
    files[path] = { sha256: digest(content), lines: [...lines].sort((a,b) => a-b), lineData: true };
  }
  const relevantUnmapped = unmappedScripts.filter(row => row.relevant !== false);
  const receipt = { schema: 'neyvia.p22.v8-source-coverage.v2', engine: 'Obscura CDP Profiler.takePreciseCoverage',
    ok: errors.length === 0 && relevantUnmapped.length === 0 && eligibleAssets.length > 0 && Object.keys(files).length > 0,
    sourceStable: errors.length === 0, measurementUnit, build: relative(realRepo, realBuild).split(sep).join('/'),
    assets: [...new Map(eligibleAssets.map(row => [row.path, row])).values()].sort((a,b) => a.path.localeCompare(b.path)),
    files, unmappedScripts, errors, durationMs: Math.round(performance.now() - started) };
  return receipt;
}

async function selfCheck() {
  const parent = resolve('D:/NeyviaRuns/P22');
  await mkdir(parent, { recursive: true });
  const root = await mkdtemp(resolve(parent, 'v8-mapper-self-check-'));
  try {
    const build = resolve(root, 'build'), assetDir = resolve(build, 'assets'), repo = resolve(root, 'repo'), sourcePathname = resolve(repo, 'src/ui.js');
    await mkdir(assetDir, { recursive: true }); await mkdir(dirname(sourcePathname), { recursive: true });
    const source = 'const icon = "😀";\nexport const label = "✓";\n';
    const asset = 'const icon = "😀";\nfunction render(){ return "✓"; }\n//# sourceMappingURL=app.js.map\n';
    const map = { version: 3, file: 'app.js', sources: ['../../repo/src/ui.js'], sourcesContent: [source], names: [], mappings: 'AAAA;AACA' };
    await writeFile(sourcePathname, source, 'utf8');
    await writeFile(resolve(assetDir, 'app.js'), asset, 'utf8');
    await writeFile(resolve(assetDir, 'app.js.map'), JSON.stringify(map), 'utf8');
    const start = asset.indexOf('function'), end = asset.indexOf('\n', start);
    const raw = { contracts: ['p22.self-check'], measurementUnit: { kind: 'grouped-outcome-journey', perContractAttribution: false },
      result: [{ scriptId: '1', url: 'http://127.0.0.1:49081/assets/app.js', functions: [{ ranges: [{ startOffset: start, endOffset: end, count: 1 }] }] }],
      scripts: [{ scriptId: '1', url: 'http://127.0.0.1:49081/assets/app.js', source: asset }] };
    let receipt = await mapCoverage(raw, build, repo);
    if (!receipt.ok || !receipt.files['src/ui.js']?.lines.includes(2) || receipt.measurementUnit.perContractAttribution !== false) {
      throw new Error('self-check positive current mapped asset failed: ' + JSON.stringify({ ok: receipt.ok, files: receipt.files, unmapped: receipt.unmappedScripts }));
    }
    const malformed = structuredClone(raw);
    malformed.result[0].functions[0].ranges = [{ startOffset: 0, endOffset: asset.length + 1, count: 1 }];
    receipt = await mapCoverage(malformed, build, repo);
    if (receipt.ok || !receipt.unmappedScripts.some(row => row.relevant && row.reason.includes('invalid offset range'))) {
      throw new Error('self-check out-of-bounds V8 range was not refused');
    }
    const crossing = structuredClone(raw);
    crossing.result[0].functions[0].ranges = [
      { startOffset: 0, endOffset: 12, count: 1 },
      { startOffset: 6, endOffset: 18, count: 0 }
    ];
    receipt = await mapCoverage(crossing, build, repo);
    if (receipt.ok || !receipt.unmappedScripts.some(row => row.relevant && row.reason.includes('overlap ambiguously'))) {
      throw new Error('self-check crossing V8 ranges were not refused');
    }
    const sameSourceDifferentContents = { ...map, sources: ['../../repo/src/ui.js', '../../repo/src/ui.js'],
      sourcesContent: [source, 'const staleSource = true;\n'], mappings: 'AAAA;ACAA' };
    await writeFile(resolve(assetDir, 'app.js.map'), JSON.stringify(sameSourceDifferentContents), 'utf8');
    receipt = await mapCoverage(raw, build, repo);
    if (receipt.ok || !receipt.errors.some(row => row.reason === 'sourcemap-source-content-is-stale')) {
      throw new Error('self-check duplicate source index with stale content was not refused');
    }
    await writeFile(resolve(assetDir, 'app.js.map'), JSON.stringify(map), 'utf8');
    const withoutMap = asset.replace('app.js.map', 'missing/app.js.map');
    await writeFile(resolve(assetDir, 'app.js'), withoutMap, 'utf8');
    await mkdir(resolve(assetDir, 'other'), { recursive: true });
    await writeFile(resolve(assetDir, 'other/app.js.map'), JSON.stringify(map), 'utf8');
    raw.scripts[0].source = withoutMap;
    receipt = await mapCoverage(raw, build, repo);
    if (receipt.ok || !receipt.unmappedScripts.some(row => row.relevant && row.reason === 'eligible-built-app-asset-has-no-unambiguous-source-map')) {
      throw new Error('self-check missing explicit map was not refused');
    }
    raw.scripts[0].source = withoutMap + '\n// changed after capture';
    receipt = await mapCoverage(raw, build, repo);
    if (receipt.ok || !receipt.errors.some(row => row.reason === 'observed-script-source-differs-from-built-asset')) {
      throw new Error('self-check observed source differing from built asset was not refused');
    }
    process.stdout.write(JSON.stringify({ ok: true, cases: [
      'exact-current-asset-and-UTF16-source-map', 'out-of-bounds-range-refused',
      'crossing-ranges-refused', 'duplicate-source-index-stale-content-refused',
      'missing-explicit-map-refused', 'observed-source-differs-from-built-asset-refused'
    ] }) + '\n');
  } finally { await rm(root, { recursive: true, force: true }); }
}

if (args.includes('--self-check')) await selfCheck();
else {
  const rawPath = option('--raw'), buildPath = option('--build'), repoPath = option('--repo'), outPath = option('--out');
  if (!rawPath || !buildPath || !repoPath || !outPath) throw new Error('Usage: node scripts/p22_v8_coverage.mjs --raw RAW.json --build BUILD --repo REPO --out RECEIPT.json');
  const raw = JSON.parse(await readFile(rawPath, 'utf8'));
  const receipt = await mapCoverage(raw, buildPath, repoPath);
  await writeFile(outPath, JSON.stringify(receipt, null, 2) + '\n', 'utf8');
  process.stdout.write(JSON.stringify({ ok: receipt.ok, measurementUnit: receipt.measurementUnit, assets: receipt.assets.length,
    files: Object.keys(receipt.files).length, mappedLines: Object.values(receipt.files).reduce((n,row) => n + row.lines.length, 0),
    unmappedRelevantScripts: receipt.unmappedScripts.filter(row => row.relevant !== false).length, errors: receipt.errors.length, durationMs: receipt.durationMs }) + '\n');
  if (!receipt.ok) process.exitCode = 1;
}
