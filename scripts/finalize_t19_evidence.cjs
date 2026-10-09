// Run after restarting both owned scratch backends without the proof-loopback flag.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const repo=path.resolve(__dirname,'..'),file=path.join(__dirname,'evidence/T19.json');
const e=JSON.parse(fs.readFileSync(file,'utf8'));assert.equal(e.passed,true);
function check(name,value){assert.ok(value,name);e.checks.push({name,passed:true});}
(async()=>{
 for(const port of [48271,48279]){
  const base='http://127.0.0.1:'+port;
  const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const cookie=auth.headers.getSetCookie().map(s=>s.split(';')[0]).join('; ');
  const state=await (await fetch(base+'/api/ui/remote/state',{headers:{Cookie:cookie}})).json();
  check(`Backend ${port} restart restored no consent or capability`,state.ok&&state.data.sessions.length===0&&state.data.connections.length===0);
  const r=await fetch(base+'/api/ui/remote/peer/windows',{method:'POST',headers:{'Content-Type':'application/json','Tailscale-User-Login':'spoofed-owner','X-Forwarded-For':'192.0.2.10'},body:'{}'});
  const body=await r.json();check(`Backend ${port} default loopback peer denial ignores spoofed tailnet headers`,r.status===403&&body.code==='tailnet_required');
 }
 e.lifecycle={disabledAfterRestart:true,proofLoopbackDisabledAfterRun:true,servers:'owned scratch, grants cleared, no public service touched'};
 e.registrations={
  commands:['remote_state_command','remote_targets_command','remote_enable_command','remote_kill_command','remote_connect_command','remote_disconnect_command','remote_windows_command','remote_snapshot_command','remote_input_command','remote_log_command'],
  http:'neyvia_ui_api.serve -> neyvia_remote.serve_http; fixed /api/ui/remote and capability-only /peer operations',
  tools:['neyvia.remote.state','neyvia.remote.windows','neyvia.remote.snapshot','neyvia.remote.log'],
  dispatch:'neyvia_workspace_tools.DEFINITIONS/tool_specs/WorkspaceService.call -> neyvia_remote.call',
  desktop:'desktop_bridge.ALLOWED_DESKTOP_COMMANDS + dispatch_desktop_command -> remote.forward_desktop -> persistent same-root owner HTTP',
  tauri:'existing generic call_desktop_backend_command -> Python bridge; fresh IPC worker actually exercised, native shell not separately run',
  models:'plugins/neyvia/mcp/neyvia_mcp.py PORTED read-only remote observations; human-only grants/input',
  manual:'config/neyvia_manuals.json -> manuals/remote.manual.json; validate/observe/run real scoped tool path verified',
  privacy:'CuaService ephemeral frames/log; NativeToolRegistry suppresses remote receipts; remote manual runs/observers do not persist live results'
 };
 e.validation={nativeBuild:true,nodeSyntax:true,remoteManual:true,fullManualCheck:'inherited manuals/neyvia.manual.json neyvia.pane.show schema drift; no unrelated refresh',pythonTests:'none',productUI:'Claude-owned, pending'};
 e.limits=['Actual second-PC/tailnet and Zen not exercised','Only supported native background patterns; unsupported controls refuse','Credential protection depends on truthful UIA flags/metadata; opaque controls fail closed where detected, no universal canvas/misreported-field claim','Already dispatched native input cannot be undone by kill; no subsequent queued dispatch admitted','No product recording opt-in feature; volatile sessions only','Embedded/standalone product UI and its screenshot proof remain Claude-owned'];
 e.preservation={local:'task-local source checkpoint, verification recorded after commit',nas:'pending: explicit task port/Tailscale isolation prohibits NAS route'};
 e.sourceSha256={};
 const sources=['src/grant_agent/neyvia_remote.py','src/grant_agent/neyvia_cua.py','src/grant_agent/cua_native.py','src/grant_agent/native_tools.py','src/grant_agent/neyvia_manuals.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/desktop_bridge.py','tools/cua-driver-win/NativeWorker.cs','tools/cua-driver-win/driver.ps1','tools/cua-driver-win/remote-indicator.cs','tools/cua-driver-win/remote-probe.cs','manuals/remote.manual.json','config/neyvia_manuals.json','plugins/neyvia/mcp/neyvia_mcp.py','scripts/verify_t19.cjs','scripts/finalize_t19_evidence.cjs'];
 for(const p of sources)e.sourceSha256[p]=crypto.createHash('sha256').update(fs.readFileSync(path.join(repo,p))).digest('hex');
 e.artifacts=['scripts/evidence/T19-host-indicator.png','scripts/evidence/T19-remote-frame.png','scripts/evidence/T19-scaled-frame.png'].map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(repo,p))).digest('hex')}));
 e.at=new Date().toISOString();fs.writeFileSync(file,JSON.stringify(e,null,2)+'\n');console.log(JSON.stringify({passed:true,checks:e.checks.length,killMs:e.receipts.kill.elapsedMs}));
})().catch(err=>{console.error(err.message);process.exitCode=1});
