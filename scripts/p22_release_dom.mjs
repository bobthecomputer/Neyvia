// Compile a production component for the native DOM observer; no fixture clone.
import {build} from 'esbuild';
import {resolve} from 'node:path';
const output=resolve(process.argv[2]);
if (!output.toLowerCase().startsWith('d:\\neyviaruns\\') && !output.startsWith('D:/NeyviaRuns/')) throw new Error('DOM artifacts belong under D:/NeyviaRuns');
await build({stdin:{contents:`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {ArtifactThumb} from './web/src/neyvia/ImagePlayground.jsx';
window.p22MissingImage=()=>{
  const host=document.createElement('div');host.id='p22-missing-image';host.style.cssText='position:fixed;top:60px;left:60px;z-index:99999;background:#222;padding:20px';
  document.body.append(host);window.p22MissingImageCount=0;
  const root=createRoot(host);root.render(React.createElement(ArtifactThumb,{src:'/__p22_missing_image__.png',alt:'Owned missing file',onMissing:()=>window.p22MissingImageCount++}));
  window.p22RemoveImage=()=>{root.unmount();host.remove();};
};`,resolveDir:process.cwd(),loader:'jsx'},bundle:true,format:'iife',platform:'browser',jsx:'automatic',
  outfile:output,define:{'process.env.NODE_ENV':'"production"'},logLevel:'silent',minify:true});
