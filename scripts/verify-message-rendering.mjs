import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-message-render-'));
try {
  const file=path.join(root,'render.cjs');
  await build({stdin:{contents:`import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; import Body from './web/src/neyvia/NeyviaMessageBody.jsx';
    const texts=${JSON.stringify(['## Hero\n\n**One clear choice.**\n\n1. First\n2. Second\n\n`<button>`','[unsafe](javascript:alert%281%29)\n\n<script>alert(1)</script>\n\n![remote image](https://example.test/pixel?private=value)','```html\n<img src=x onerror=alert(1)>\n```'])};console.log(JSON.stringify(texts.map(text=>renderToStaticMarkup(React.createElement(Body,{text})))));`,resolveDir:process.cwd(),loader:'jsx'},jsx:'automatic',bundle:true,platform:'node',format:'cjs',outfile:file,loader:{'.css':'empty'},logLevel:'silent'});
  const result=spawnSync(process.execPath,[file],{encoding:'utf8',timeout:10000});
  assert.equal(result.status,0,result.stderr);const [normal,unsafe,code]=JSON.parse(result.stdout);
  assert.match(normal,/<h2>Hero<\/h2>/);assert.match(normal,/<strong>One clear choice.<\/strong>/);assert.match(normal,/<ol>/);assert.match(normal,/<code>&lt;button&gt;<\/code>/);
  assert(!/<script|<img|javascript:|onerror=/i.test(unsafe));assert.match(unsafe,/remote image/);assert.match(unsafe,/rel="noopener noreferrer"/);
  assert.match(code,/&lt;img/);assert(!/<img/.test(code));
  console.log('MESSAGE_RENDERING_VERIFIED: production component, headings/lists/emphasis/code, unsafe HTML and URL rejection, no automatic model-authored image requests');
}finally{if(path.dirname(path.resolve(root))===path.resolve(tmpdir())&&path.basename(root).startsWith('neyvia-message-render-'))rmSync(root,{recursive:true,force:true});}
