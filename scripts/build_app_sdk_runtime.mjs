// Bundle the editable SDK modules for embedded runtimes that support classic
// scripts. esbuild is already supplied by the workspace; no package install.
import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const project = resolve(process.argv[2]);
const entry = resolve(project, 'www/app.js');
const source = await readFile(entry, 'utf8');
// The SDK template has static imports followed by async initialization.
// Keep module imports at module scope and wrap initialization before bundling.
const imports = source.match(/^import .*?;\s*$/gm) || [];
const body = source.replace(/^import .*?;\s*$/gm, '');
await build({ stdin: { contents: imports.join('\n') + '\n(async () => {\n' + body + '\n})().catch(error => {\n'
  + 'const message=document.querySelector("#message");if(message)message.textContent=error.message;console.error(error);\n});',
  resolveDir: resolve(project, 'www'), sourcefile: entry, loader: 'js' },
  bundle: true, format: 'iife', target: 'es2020', outfile: resolve(project, 'www/app.bundle.js'),
  sourcemap: false, legalComments: 'inline', logLevel: 'error' });
