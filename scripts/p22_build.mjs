// Build an exact historical frontend without checking out or merging a track.
import { build } from 'vite';
import config from '../vite.config.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, relative, dirname } from 'node:path';
import { createHash } from 'node:crypto';
const args=process.argv.slice(2), option=name=>args.indexOf(name)<0?undefined:args[args.indexOf(name)+1];
const current=args.includes('--current'), ref=current?'HEAD':option('--ref'), output=option('--out');
if(!ref || !output)throw Error('Explicit ref/current mode and task-local output required');
const out=resolve(output);
if(!out.startsWith(resolve('.agent_control/p22')+'/') && !out.startsWith(resolve('.agent_control/p22')+'\\')) throw Error('Task-local output required');
const git=(...args)=>execFileSync('git',args,{cwd:process.cwd(),encoding:'utf8',windowsHide:true,maxBuffer:16*1024*1024});
const commit=git('rev-parse','--verify',ref+'^{commit}').trim(), bindings={};
const known=new Set(git('ls-tree','-r','--name-only',commit,'web/src').trim().split('\n'));
const source=path=>{const value=git('show',commit+':'+path);bindings[path]=createHash('sha256').update(value).digest('hex');return value;};
const historical={name:'p22-exact-history',enforce:'pre',
  resolveId(source,importer){
    if(!importer || !source.startsWith('.'))return;
    const candidate=resolve(dirname(importer.split('?')[0]),source);
    for(const suffix of ['', '.js','.jsx','.ts','.tsx']){
      const path=relative(process.cwd(),candidate+suffix).replaceAll('\\','/');
      if(known.has(path))return candidate+suffix;
    }
  },
  load(id){const path=relative(process.cwd(),id.split('?')[0]).replaceAll('\\','/');
    if(path.startsWith('web/src/') && /\.(?:[cm]?js|jsx|tsx?|css)$/.test(path)) return source(path);
  },
  transformIndexHtml:{order:'pre',handler(){return source('web/index.html');}}
};
const resolved=config({command:'build',mode:'production'});
await build({...resolved,configFile:false,cacheDir:resolve(out,'../vite-cache'),plugins:[...(current?[]:[historical]),...resolved.plugins],build:{...resolved.build,outDir:out}});
mkdirSync(out,{recursive:true});writeFileSync(resolve(out,'source-receipt.json'),JSON.stringify({commit,mode:current?'working-source':'historical-source',bindings},null,2)+'\n');
