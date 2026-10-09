/* Apply the bounded C2g browser feature patch to the already admitted source. */
const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve('.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4'),changes=[];
function edit(file,fn){const target=path.join(root,file),before=fs.readFileSync(target,'utf8'),after=fn(before);if(after===before)throw Error('Patch made no change: '+file);fs.writeFileSync(target,after);const old=path.resolve('.agent_control/C2g/engine-before',file),now=path.resolve('.agent_control/C2g/engine-after',file);fs.mkdirSync(path.dirname(old),{recursive:true});fs.mkdirSync(path.dirname(now),{recursive:true});fs.writeFileSync(old,before);fs.writeFileSync(now,after);const result=cp.spawnSync('git',['diff','--no-index','--',old,now],{encoding:'utf8',windowsHide:true});if(result.status!==1)throw Error(result.stderr);changes.push(result.stdout.replaceAll(old.replaceAll('\\','/'),'a/'+file).replaceAll(now.replaceAll('\\','/'),'b/'+file).replaceAll('a/a/','a/').replaceAll('b/b/','b/'));}
function replace(text,a,b){if(!text.includes(a))throw Error('Missing patch seam '+a.slice(0,70));return text.replace(a,b);}
edit('crates/obscura-render/src/css.rs',s=>{
 s=replace(s,'    PrintReducedMotion,','    PrintReducedMotion,\n    ScreenDark,\n    PrintDark,\n    ScreenDarkReducedMotion,\n    PrintDarkReducedMotion,');
 const start=s.indexOf('    pub fn with_reduced_motion'),end=s.indexOf('\n}\n',start);
 s=s.slice(0,start)+`    pub fn with_reduced_motion(self, reduce: bool) -> Self {
        Self::preferences(self.print(), self.dark(), reduce)
    }
    pub fn with_dark(self, dark: bool) -> Self {
        Self::preferences(self.print(), dark, self.reduced_motion())
    }
    fn preferences(print: bool, dark: bool, reduce: bool) -> Self {
        match (print,dark,reduce) {
            (false,false,false)=>Self::Screen,(false,false,true)=>Self::ScreenReducedMotion,
            (false,true,false)=>Self::ScreenDark,(false,true,true)=>Self::ScreenDarkReducedMotion,
            (true,false,false)=>Self::Print,(true,false,true)=>Self::PrintReducedMotion,
            (true,true,false)=>Self::PrintDark,(true,true,true)=>Self::PrintDarkReducedMotion,
        }
    }
    pub fn print(self) -> bool { matches!(self, Self::Print | Self::PrintReducedMotion | Self::PrintDark | Self::PrintDarkReducedMotion) }
    pub fn dark(self) -> bool { matches!(self, Self::ScreenDark | Self::ScreenDarkReducedMotion | Self::PrintDark | Self::PrintDarkReducedMotion) }
    pub fn reduced_motion(self) -> bool { matches!(self, Self::ScreenReducedMotion | Self::PrintReducedMotion | Self::ScreenDarkReducedMotion | Self::PrintDarkReducedMotion) }
`+s.slice(end);
 s=replace(s,'matches!(media_type, CssMediaType::Screen | CssMediaType::ScreenReducedMotion)','!media_type.print()');
 s=replace(s,'matches!(media_type, CssMediaType::Print | CssMediaType::PrintReducedMotion)','media_type.print()');
 return replace(s,'if compact.contains("prefers-color-scheme:dark") {','if (compact.contains("prefers-color-scheme:dark") && !media_type.dark()) || (compact.contains("prefers-color-scheme:light") && media_type.dark()) {');
});
edit('crates/obscura-js/src/runtime.rs',s=>replace(s,'    pub fn set_reduced_motion(&mut self, reduce: bool) {',`    pub fn set_dark(&mut self, dark: bool) {
        #[cfg(feature = "render")]
        {
            let media = self.state.borrow().render_media.with_dark(dark);
            self.set_render_media(media);
        }
        let _ = self.execute_runtime_script("<color-scheme>", format!("globalThis.__obscura_dark={dark};globalThis.__obscura_recompute_media_queries();"));
    }
    pub fn set_reduced_motion(&mut self, reduce: bool) {`));
edit('crates/obscura-browser/src/page.rs',s=>{
 s=replace(s,'    reduced_motion: bool,','    reduced_motion: bool,\n    dark: bool,');
 s=replace(s,'            reduced_motion: false,','            reduced_motion: false,\n            dark: false,');
 s=replace(s,'    pub fn set_reduced_motion(&mut self, reduce: bool) {','    pub fn set_dark(&mut self, dark: bool) {\n        self.dark = dark;\n        if let Some(js) = &mut self.js { js.set_dark(dark); }\n    }\n\n    pub fn set_reduced_motion(&mut self, reduce: bool) {');
 return replace(s,'        rt.set_reduced_motion(self.reduced_motion);','        rt.set_reduced_motion(self.reduced_motion);\n        rt.set_dark(self.dark);');
});
edit('crates/obscura-cdp/src/domains/emulation.rs',s=>replace(s,'                ctx.get_session_page_mut(session_id).ok_or("No page for session")?\n                    .set_reduced_motion(value == "reduce");',`                let color = features.iter().find(|feature| feature["name"] == "prefers-color-scheme")
                    .and_then(|feature| feature["value"].as_str()).unwrap_or("light");
                if !matches!(color, "light" | "dark" | "no-preference") { return Err("Invalid prefers-color-scheme value".into()); }
                let page = ctx.get_session_page_mut(session_id).ok_or("No page for session")?;
                page.set_reduced_motion(value == "reduce");
                page.set_dark(color == "dark");`));
edit('crates/obscura-js/src/ops.rs',s=>{
 s=replace(s,'struct FetchBodyResource {',`struct FetchStreamResource {
    response: RefCell<Option<reqwest::Response>>,
    cancel: Rc<CancelHandle>,
    total: Cell<usize>,
    network: RefCell<FetchNetworkGuard>,
    _in_flight: PageInFlightGuard,
}
impl Resource for FetchStreamResource {
    fn close(self: Rc<Self>) { self.cancel.cancel(); self.response.borrow_mut().take(); }
}
#[op2]
#[serde]
async fn op_fetch_stream_read(state: Rc<RefCell<OpState>>, rid: u32) -> Result<serde_json::Value, deno_error::JsErrorBox> {
    let resource = state.borrow().resource_table.get::<FetchStreamResource>(rid)
        .map_err(|e| deno_error::JsErrorBox::generic(e.to_string()))?;
    let mut response = resource.response.borrow_mut().take()
        .ok_or_else(|| deno_error::JsErrorBox::type_error("Stream is already reading or closed"))?;
    let chunk = response.chunk().or_cancel(resource.cancel.clone()).await
        .map_err(|_| deno_error::JsErrorBox::generic("Stream cancelled"))?
        .map_err(|e| deno_error::JsErrorBox::generic(e.to_string()))?;
    if let Some(chunk) = chunk {
        let total = resource.total.get() + chunk.len();
        if total > fetch_max_body_bytes() { resource.close(); return Err(deno_error::JsErrorBox::generic("Stream exceeds body limit")); }
        resource.total.set(total);
        *resource.response.borrow_mut() = Some(response);
        Ok(serde_json::json!({"done":false,"data":BASE64.encode(&chunk)}))
    } else {
        resource.network.borrow_mut().event = None;
        if let Ok(resource) = state.borrow_mut().resource_table.take_any(rid) { resource.close(); }
        Ok(serde_json::json!({"done":true}))
    }
}
struct FetchBodyResource {`);
 s=replace(s,'    // A resource must not form an ownership cycle with its OpState table.',`    // SSE remains incremental: one awaited chunk per reader pull, bounded total
    // bytes, normal routing/CORS/redirect checks and abort ownership retained.
    if !internal_load && !opaque && resp_headers.get("content-type").is_some_and(|value| value.split(';').next().unwrap_or("").trim() == "text/event-stream") {
        let rid = state.borrow_mut().resource_table.add(FetchStreamResource {
            response: RefCell::new(Some(response)), cancel: cancel.unwrap_or_else(CancelHandle::new_rc),
            total: Cell::new(0), network: RefCell::new(network_guard), _in_flight: _page_in_flight,
        });
        let mut metadata = metadata;
        metadata["streamRid"] = serde_json::json!(rid);
        return Ok(metadata.to_string());
    }
    // A resource must not form an ownership cycle with its OpState table.`);
 return replace(s,'        op_fetch_body(),','        op_fetch_body(),\n        op_fetch_stream_read(),');
});
edit('crates/obscura-js/js/bootstrap.js',s=>{
 s=replace(s,'if (compact.includes("prefers-color-scheme:dark")) return false;','if (compact.includes("prefers-color-scheme:dark") && !globalThis.__obscura_dark) return false;');
 s=replace(s,"if (match) return match[1] === 'light';","if (match) return match[1] === (globalThis.__obscura_dark ? 'dark' : 'light');");
 s=replace(s,"if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {",`if (href && !href.startsWith('javascript:')) {
          const oldURL=location.href,next=new URL(href,oldURL);
          const old=new URL(oldURL);
          if(next.origin===old.origin&&next.pathname===old.pathname&&next.search===old.search&&next.hash){
            history.pushState(null,'',next.href);
            let id;try{id=decodeURIComponent(next.hash.slice(1));}catch(_){id=next.hash.slice(1);}
            const target=document.getElementById(id)||Array.from(document.querySelectorAll('a[name]')).find(e=>e.getAttribute('name')===id);
            if(target)target.scrollIntoView({block:'start',behavior:'instant'});
            return;
          }`);
 s=replace(s,"  if (typeof parsed.bodyRid === 'number') {","  if (typeof parsed.streamRid === 'number') {\n    response._fetchStream = {rid:parsed.streamRid,cleanup};\n  } else if (typeof parsed.bodyRid === 'number') {");
 s=replace(s,"            if (this._fetchBody) this._fetchBody.promise.then(deliver, error => controller.error(error));","            if (this._fetchStream) return;\n            if (this._fetchBody) this._fetchBody.promise.then(deliver, error => controller.error(error));");
 s=replace(s,'          cancel: () => {\n            this._bodyUsed = true;',`          pull: async controller => {
            if(!this._fetchStream)return;
            try{
              const chunk=await __obscuraCore.ops.op_fetch_stream_read(this._fetchStream.rid);
              if(chunk.done){controller.close();this._fetchStream.cleanup();}
              else controller.enqueue(_base64ToUint8Array(chunk.data));
            }catch(error){controller.error(error);this._fetchStream.cleanup();}
          },
          cancel: () => {
            this._bodyUsed = true;
            if(this._fetchStream){__obscuraCore.ops.op_try_close(this._fetchStream.rid);this._fetchStream.cleanup();}`);
 s=replace(s,'          return new Promise((resolve, reject) => stream._reads.push({resolve, reject}));',`          const pending=new Promise((resolve, reject) => stream._reads.push({resolve, reject}));
          if(stream._source.pull&&!stream._pulling){
            stream._pulling=true;
            Promise.resolve().then(()=>stream._source.pull(stream._controller)).catch(error=>stream._controller.error(error)).finally(()=>{stream._pulling=false;});
          }
          return pending;`);
 const start=s.indexOf("if (typeof EventSource === 'undefined') {"),end=s.indexOf("\nif (typeof WebSocket === 'undefined')",start);
 s=s.slice(0,start)+fs.readFileSync('src/grant_agent/browser_event_source.js','utf8')+'\n'+s.slice(end);
 return s;
});
fs.writeFileSync('scripts/obscura-v024-C2g-capabilities.patch',changes.join('\n'));
console.log(JSON.stringify({patched:changes.length,patch:'scripts/obscura-v024-C2g-capabilities.patch'}));
