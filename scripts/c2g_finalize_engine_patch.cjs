/* Refresh cumulative portable patch after evidence-driven repairs. */
const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve('.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4');
const file='crates/obscura-js/js/bootstrap.js',target=path.join(root,file);let source=fs.readFileSync(target,'utf8');
source=source.replace(`          if(stream._source.pull&&!stream._pulling){
            stream._pulling=true;
            Promise.resolve().then(()=>stream._source.pull(stream._controller)).catch(error=>stream._controller.error(error)).finally(()=>{stream._pulling=false;});
          }`, `          const pull=()=>{
            if(!stream._source.pull||stream._pulling||stream._state!=="readable")return;
            stream._pulling=true;
            Promise.resolve().then(()=>stream._source.pull(stream._controller)).catch(error=>stream._controller.error(error)).finally(()=>{stream._pulling=false;if(stream._reads.length)pull();});
          };pull();`);
source=source.replace('    async text() { this._consumeBody();',`    async _readBodyBytes() {
      if(!this._fetchStream){this._consumeBody();return this._fetchBody?await this._fetchBody.promise:this._bodyBytes;}
      const reader=this.body.getReader(),parts=[];let length=0;
      try{while(true){const {value,done}=await reader.read();if(done)break;parts.push(value);length+=value.length;}}
      finally{reader.releaseLock();}
      const bytes=new Uint8Array(length);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}return bytes;
    }
    async text() { this._consumeBody();`);
source=source.replace('async text() { this._consumeBody(); return _decodeBodyWithCharset(this._fetchBody ? await this._fetchBody.promise : this._bodyBytes, this.headers); }','async text() { return _decodeBodyWithCharset(await this._readBodyBytes(), this.headers); }');
source=source.replace('async json() { this._consumeBody(); return JSON.parse(await _decodeBodyWithCharset(this._fetchBody ? await this._fetchBody.promise : this._bodyBytes, this.headers)); }','async json() { return JSON.parse(await this.text()); }');
source=source.replace('async arrayBuffer() { this._consumeBody(); return _arrayBufferFromBytes(this._fetchBody ? await this._fetchBody.promise : this._bodyBytes); }','async arrayBuffer() { return _arrayBufferFromBytes(await this._readBodyBytes()); }');
source=source.replace('async blob() { this._consumeBody(); return new Blob([this._fetchBody ? await this._fetchBody.promise : this._bodyBytes]); }','async blob() { return new Blob([await this._readBodyBytes()]); }');
if(!source.includes('if(response._fetchStream){__obscuraCore.ops.op_try_close'))source=source.replace('  if (response._bodyStream) response._bodyStream._controller.error(reason);','  if (response._bodyStream) response._bodyStream._controller.error(reason);\n  if(response._fetchStream){__obscuraCore.ops.op_try_close(response._fetchStream.rid);response._fetchStream.cleanup();}');
source=source.replace('    clone() {\n      const copy = _createInternalResponse','    clone() {\n      if(this._fetchStream)throw new DOMException("Incremental event-stream response cloning is unsupported", "NotSupportedError");\n      const copy = _createInternalResponse');
fs.writeFileSync(target,source);
const ops=path.join(root,'crates/obscura-js/src/ops.rs');
fs.writeFileSync(ops,fs.readFileSync(ops,'utf8').replace('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36','NeyviaAgent/1.0 (Automation; Obscura)').replace('value.split(\';\').next().unwrap_or("").trim() == "text/event-stream"','value.split(\';\').next().unwrap_or("").trim().eq_ignore_ascii_case("text/event-stream")'));
const files=['crates/obscura-js/src/ops.rs','crates/obscura-js/src/runtime.rs','crates/obscura-js/js/bootstrap.js','crates/obscura-browser/src/page.rs','crates/obscura-cdp/src/domains/emulation.rs','crates/obscura-render/src/css.rs'];
const changes=files.map(file=>{const before=path.resolve('.agent_control/C2g/engine-before',file),after=path.resolve('.agent_control/C2g/engine-after',file);fs.copyFileSync(path.join(root,file),after);const diff=cp.spawnSync('git',['diff','--no-index','--',before,after],{encoding:'utf8',windowsHide:true});if(diff.status!==1)throw Error(diff.stderr);return diff.stdout.replace(/^diff --git.*$/m,'diff --git a/'+file+' b/'+file).replace(/^---.*$/m,'--- a/'+file).replace(/^\+\+\+.*$/m,'+++ b/'+file);});
fs.writeFileSync('scripts/obscura-v024-C2g-capabilities.patch',changes.join('\n'));
console.log(JSON.stringify({patch:'scripts/obscura-v024-C2g-capabilities.patch',files:files.length}));
