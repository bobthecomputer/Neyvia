import { THEME_SCHEME } from "./nxThemeRegistry.js";
// Executable postconditions of the PROOFS-e model chapters. Every public
// observer checks the claims before its value is delivered to its consumer.
// Errors identify the contract only: inputs can include private drafts.
export class ProofsEContractError extends Error {
  constructor(id) { super(`Model contract ${id} failed`); this.name = "ProofsEContractError"; this.contract = id; }
}
export const same = (a, b) => {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  if (a instanceof Map || b instanceof Map) return a instanceof Map && b instanceof Map && same([...a], [...b]);
  return Array.isArray(a) === Array.isArray(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && same(a[k], b[k]));
};
export const PROOFS_E_MODEL_CONTRACTS = {};
let proofObserver = null;
export function observeProofsEModels(observer) { proofObserver = observer; }
const rule = (id, claim, check) => { PROOFS_E_MODEL_CONTRACTS[id] = { id, claim, check }; };
export function checkedProofsEModel(id, args, result) {
  const contract = PROOFS_E_MODEL_CONTRACTS[id];
  if (!contract || !contract.check(args, result)) throw new ProofsEContractError(id);
  proofObserver?.(id, args, result);
  return result;
}
const ids = rows => rows.map(row => row.id);
const states = ["waiting", "running", "blocked", "needs_review", "done"];
const counts = rows => Object.fromEntries(states.map(state => [state, rows.filter(row => row.status === state).length]));
const token = value => !value || typeof value !== "object" ? null : Number.isFinite(value.total) ? value.total : (Number(value.input) || 0) + (Number(value.output) || 0) || null;
const kind = reason => /^intent checklist/i.test(String(reason)) ? "plan" : /^judgement:/i.test(String(reason)) ? "judge" : /^disagreement:/i.test(String(reason)) ? "second" : /^frontier/i.test(String(reason)) ? "frontier" : "other";
rule("autopilot.scopeTools", "Unknown scopes are read-only; edit adds only workspace.write", ([scope], out) => same(out, ["workspace.read", "workspace.search", "runtime.environment", "neyvia.manual.compiled", "neyvia.manual.versions", "neyvia.manual.index", "neyvia.notes.list", "neyvia.notes.read", "neyvia.files.list", "neyvia.files.stat", "neyvia.files.read", ...(scope === "edit" ? ["workspace.write"] : [])]));
rule("autopilot.scopeOf", "Only a named CAS workspace.write grants edit scope", ([tools], out) => out === (Array.isArray(tools) && tools.includes("workspace.write") ? "edit" : "look"));
rule("autopilot.attributeCalls", "Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order", ([run], out) => {
  const source = run?.models || [], items = run?.items || [];
  if (!out || out.calls.length !== source.length || out.perItem.length !== items.length) return false;
  if (!out.calls.every((call, i) => same({ ...call, index: undefined, purpose: undefined, total: undefined }, { ...source[i], index: undefined, purpose: undefined, total: undefined }) && call.index === i && call.total === token(source[i].tokens) && call.purpose.kind === kind(source[i].reason))) return false;
  const all = [...out.runLevel, ...out.perItem.flat()];
  if (!same(all.map(c => c.index).sort((a,b) => a-b), source.map((_,i) => i))) return false;
  let judge = 0, frontier = 0;
  const judging = out.calls.filter(c => ["judge","second"].includes(c.purpose.kind)), exploring = out.calls.filter(c => c.purpose.kind === "frontier");
  for (let i = 0; i < items.length; i++) {
    const expected = [];
    for (let r=0;r<(items[i].modelReasons || []).length && judge<judging.length;r++) {
      expected.push(judging[judge++].index);
      while (judging[judge]?.purpose.kind === "second") expected.push(judging[judge++].index);
    }
    for (let r=0;r<(items[i].frontier || []).length && frontier<exploring.length;r++) expected.push(exploring[frontier++].index);
    if (!same(out.perItem[i].map(c => c.index), expected)) return false;
  }
  return out.runLevel.every(c => ["plan","other"].includes(c.purpose.kind) || !out.perItem.flat().some(p => p.index === c.index));
});
rule("autopilot.shapeRun", "Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations", ([run], out) => {
  if (!run) return out === null;
  if (!out || out.items.length !== (run.items || []).length) return false;
  const done = out.items.filter(i => i.status === "completed");
  return out.done === done.length && out.noModel === done.filter(i => ["script","manual"].includes(i.how.kind)).length && out.scripts === done.filter(i => i.how.kind === "script").length && out.total === out.items.length && out.totalTokens === (token(run.tokens) ?? out.calls.reduce((sum,c) => sum+(c.total || 0),0)) && out.items.every((item,i) => item.index === i && item.how.kind === ((item.frontier || []).length ? "frontier" : (item.modelReasons || []).length ? "model" : item.route === "script" ? "script" : "manual") && item.how.tokens === item.modelCalls.reduce((sum,c) => sum+(c.total || 0),0));
});
rule("autopilot.checkLine", "Final verification text names the real tool, target, observed path and exact operation/value", ([v], out) => {
  if (!v) return out === "";
  const e=v.expect || {}, target=v.args?.path || v.args?.query || "", value=typeof e.value === "string" ? `“${e.value}”` : JSON.stringify(e.value);
  return out === `${v.tool}${target ? ` ${target}` : ""}: ${e.path || "result"} ${{contains:"contains",eq:"is",exists:"exists"}[e.op] || e.op}${e.op === "exists" ? "" : ` ${value}`}`;
});
const namedKeys = { Enter:"enter",Backspace:"backspace",Tab:"tab",Escape:"escape",Delete:"delete",Insert:"insert",ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right",Home:"home",End:"end",PageUp:"pageup",PageDown:"pagedown"," ":"space",ContextMenu:"menu" };
rule("cua.toCapture", "Frame clicks map from shown pixels to capture pixels and outside/empty frames are refused", ([x,y,rect,frame], out) => {
  if (!rect?.width || !rect?.height || !frame?.width || !frame?.height) return out === null;
  const cx=((x-rect.left)/rect.width)*frame.width, cy=((y-rect.top)/rect.height)*frame.height;
  return cx<0 || cy<0 || cx>frame.width || cy>frame.height ? out===null : same(out,{x:Math.min(frame.width-1,Math.round(cx)),y:Math.min(frame.height-1,Math.round(cy))});
});
rule("cua.keyToInput", "Characters, named keys and chords retain exact modifiers; dead/modifier keys never send input", ([e], out) => {
  if (!e.key || ["Control","Shift","Alt","Meta","AltGraph","CapsLock","NumLock","ScrollLock","OS","Dead","Unidentified","Process"].includes(e.key)) return out===null;
  if (!e.ctrlKey && !e.altKey && !e.metaKey && e.key.length===1) return same(out,{kind:"text",text:e.key});
  const key=namedKeys[e.key] || (/^F([1-9]|1[0-9]|2[0-4])$/.test(e.key) || e.key.length===1 ? e.key.toLowerCase() : null);
  if (!key) return out===null;
  const mods=[e.ctrlKey && "ctrl",e.altKey && "alt",e.shiftKey && "shift",e.metaKey && "win"].filter(Boolean);
  return same(out,e.ctrlKey || e.altKey || e.metaKey ? {kind:"hotkey",keys:[...mods,key]} : {kind:"press_key",key,...(mods.length ? {modifiers:mods} : {})});
});
rule("cua.wheelToScroll", "Dominant axis determines direction; gesture amount is 1–10 lines with pixel/line/page conversion", ([x,y,mode=0], out) => {
  const vertical=Math.abs(y)>=Math.abs(x), delta=vertical?y:x;
  return !delta ? out===null : same(out,{direction:vertical ? delta>0?"down":"up" : delta>0?"right":"left",amount:Math.max(1,Math.min(10,Math.round(Math.abs(delta)*(mode===1?1:mode===2?10:1/40))))});
});
rule("cua.elementAt", "Choose the smallest containing observed element, preserve first match on equal area", ([elements,x,y], out) => {
  const matches=(elements || []).filter(e => e.screenshot_frame && x>=e.screenshot_frame.x && y>=e.screenshot_frame.y && x<=e.screenshot_frame.x+e.screenshot_frame.w && y<=e.screenshot_frame.y+e.screenshot_frame.h);
  const best=matches.reduce((a,b) => !a || b.screenshot_frame.w*b.screenshot_frame.h<a.screenshot_frame.w*a.screenshot_frame.h ? b : a,null);
  return out===best;
});
rule("cua.pickSession", "Named sessions must exist; otherwise the most recent live session wins, with ended fallback", ([sessions,target], out) => {
  const rows=sessions || [];
  if (target) return out===(rows.find(s=>s.id===target) || null);
  const live=rows.filter(s=>s.status!=="ended"), candidates=live.length?live:rows;
  const expected=[...candidates].sort((a,b)=>String(b.lastActionAt || b.startedAt || "").localeCompare(String(a.lastActionAt || a.startedAt || "")))[0] || null;
  return out===expected;
});
rule("cua.mergeLog", "Updates preserve entry identity and data; new rows are sequence sorted and bounded", ([rows,entry,limit=400], out) => {
  const merged=(rows.some(r=>r.id===entry.id) ? rows.map(r=>r.id===entry.id?{...r,...entry}:r) : [...rows,entry]).sort((a,b)=>a.seq-b.seq);
  return same(out,merged.length>limit?merged.slice(-limit):merged);
});
rule("outputs.perceptionTarget", "Typed pane target preserves the caller's full path/session identifier", ([layer,value,window], out)=>out===(layer==="window"?`window:${value}:${window}`:`${layer}:${value}`));
rule("outputs.parsePerceptionTarget", "Only image/file paths, HTTP(S) URLs and integer window targets are accepted; delimiters in paths/session ids survive", ([value], out)=>{
  const text=String(value || ""), colon=text.indexOf(":"), layer=text.slice(0,colon), rest=text.slice(colon+1);
  if (colon<1) return out===null;
  if (["image","file"].includes(layer)) return rest ? same(out,{layer,path:rest}) : out===null;
  if (layer==="browser") return /^https?:\/\//i.test(rest) ? same(out,{layer,url:rest}) : out===null;
  if (layer==="window") { const split=rest.lastIndexOf(":"), sessionId=split>0?rest.slice(0,split):"", windowId=Number(rest.slice(split+1)); return sessionId && Number.isInteger(windowId) ? same(out,{layer,sessionId,windowId}) : out===null; }
  return out===null;
});
rule("outputs.outsideDock", "Undocking requires crossing a known dock boundary by the requested margin", ([point,rect,margin=28],out)=>out===Boolean(rect && (point.x<rect.left-margin || point.x>rect.right+margin || point.y<rect.top-margin || point.y>rect.bottom+margin)));
rule("outputs.dropSpot", "Floating drops choose nearest side and a clamped vertical fraction", ([p,w,h],out)=>same(out,{x:p.x<w/2?0:1,y:Math.min(1,Math.max(0,p.y/Math.max(1,h)))}));
rule("devices.dropIntent", "Only local move, remote take and local-to-remote send are offered; remote-to-remote is refused", ([from,to],out)=>out===(!from?.path || !to ? null : from.device ? to.device?null:"take" : to.device?"send":"move"));
rule("devices.sendTarget", "Remote writes require inbox, writable share or explicit write-anywhere permission", ([device,place,folder],out)=>out===(folder && (place?.kind==="inbox" || place?.write || device?.theyShare?.writeAnywhere)?folder:null));
rule("devices.transferFraction", "Known byte progress clamps to 0..1; unknown sizes stay unknown except completed transfers", ([t],out)=>Object.is(out,Number(t?.size)>0?Math.max(0,Math.min(1,Number(t.done || 0)/Number(t.size))):t?.status==="done"?1:null));
rule("devices.pcTarget", "Other-PC navigation preserves path delimiters", ([device,path=""],out)=>out===`pc:${device}${path?`|${path}`:""}`);
rule("devices.parsePcTarget", "Only pc: identifiers are decoded, splitting device once and preserving all path bars", ([value],out)=>{
  const text=String(value || ""); if (!text.startsWith("pc:")) return out===null;
  const [device,...path]=text.slice(3).split("|"); return device?same(out,{device,path:path.join("|") || null}):out===null;
});
const bytes = n => { if(n==null || !Number.isFinite(Number(n))) return ""; const v=Number(n); if(v<1024)return `${v} B`; const power=[4,3,2,1].find(p=>v>=1024**p), amount=v/1024**power; return `${amount>=10?Math.round(amount):amount.toFixed(1)} ${["B","KB","MB","GB","TB"][power]}`; };
rule("devices.transferLine", "Transfer labels preserve bytes, file counts, failure reason, measured speed and rounded remaining time", ([t],out)=>{
  if(!t)return out===""; const done=t.done || 0,total=t.size,speed=t.bytesPerSecond, files=t.files, count=files?.total>1?` · ${files.done || 0} of ${files.total} files`:"";
  const fixed={done:`Done · ${bytes(total ?? done)}${files?.total>1?` · ${files.total} files`:""} · checked`,failed:t.error?`Stopped: ${t.error}`:"Stopped",cancelled:"Cancelled",queued:"Waiting to start",verifying:`Checking the copy${count}`};
  if(Object.hasOwn(fixed,t.status))return out===fixed[t.status];
  const progress=total>0?`${bytes(done)} of ${bytes(total)}`:bytes(done);
  if(t.status==="paused")return out===`Paused at ${progress}${count}`;
  const seconds=total>0 && speed>0?(total-done)/speed:0, minutes=Math.round(seconds/60);
  const left=seconds>0 && Number.isFinite(seconds) ? seconds<60?"less than a minute":minutes<60?`about ${minutes} min`:`about ${Math.floor(minutes/60)} h${minutes%60?` ${minutes%60} min`:""}` : "";
  return out===[progress+count,speed>0?`${bytes(speed)}/s`:"",left?`${left} left`:""].filter(Boolean).join(" · ");
});
const imageTypes=["image/png","image/jpeg","image/webp","image/gif"], perImage=12*1024*1024, allImages=24*1024*1024;
function admitted(current,incoming,metadata) {
  let total=current.reduce((s,i)=>s+i.data.length,0); const accepted=[],refused=[];
  for(const i of incoming){const size=metadata?4*Math.ceil(Math.max(0,Number(i.size)||0)/3):i.data.length;
    if(!imageTypes.includes(metadata?i.type:i.mime))refused.push(`${i.name || "That file"} isn't a PNG, JPEG, WebP or GIF image.`);
    else if(current.length+accepted.length>=6)refused.push("At most 6 images go with one message.");
    else if(size>perImage)refused.push(`${i.name || "That image"} is larger than about 9 MB.`);
    else if(total+size>allImages)refused.push("The images together would be larger than about 18 MB.");
    else {total+=size;accepted.push(i);}
  }
  return {[metadata?"read":"accepted"]:accepted,refused:[...new Set(refused)]};
}
rule("composer.admitImages", "Before adding bytes, each image has a supported MIME, fits six-count/per-file/aggregate limits, and every refusal explains the gate", ([current,incoming],out)=>same(out,admitted(current,incoming,false)));
rule("composer.planImageReads", "Unsupported, oversized and over-count metadata never reaches FileReader; estimated base64 totals obey limits", ([current,files],out)=>same(out,admitted(current,files,true)));
rule("composer.base64Chars", "Metadata byte counts become rounded base64 quadruplets", ([size],out)=>out===4*Math.ceil(Math.max(0,Number(size)||0)/3));
rule("composer.stripDataUrl", "Only bytes following the first data URL comma are kept", ([text],out)=>out===(String(text || "").includes(",")?text.slice(String(text || "").indexOf(",")+1):""));
rule("composer.imageBlocker", "Only image-capable apps and models admit images on either route; blocked choices explain the app/model", ([v],out)=>!v.capabilities?.images?same(out,{reason:`${v.appName || "This app"} chats from Neyvia can't carry images yet.`}):v.model?.images===false?same(out,{reason:`${v.model.label || v.model.id} doesn't accept images. Pick another model to send them.`}):out===null);
const canonical=v=>Array.isArray(v)?`[${v.map(canonical).join(",")}]`:v && typeof v==="object"?`{${Object.keys(v).sort().filter(k=>v[k]!==undefined).map(k=>`${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`:JSON.stringify(v??null);
const imageDigest=text=>{let h=2166136261;for(const ch of text.split(""))h=Math.imul(h^ch.charCodeAt(0),16777619);return(h>>>0).toString(36);};
rule("composer.sendIdentity", "Retry identity includes canonical options and every image's byte digest, MIME/name/size; no image bytes are retained", ([scope,message,options={}],out)=>out===`${scope}\0${message}\0${canonical({...options,images:(options.images || []).map(i=>({mime:i.mime,name:i.name || "",size:i.data.length,digest:imageDigest(i.data)}))})}`);
rule("composer.toolMutates", "Only read mutability is presented as non-mutating", ([tool],out)=>out===(String(tool?.mutability_class || "read")!=="read"));
rule("composer.argumentSkeleton", "Argument examples contain exactly required fields with enum/default/type initial values", ([s],out)=>{
  const fallback={string:"",integer:0,number:0,boolean:false,array:[],object:{}}, expected={};
  for(const name of s?.required || []){const f=s?.properties?.[name] || {}; expected[name]=f.enum?.length?f.enum[0]:f.default??fallback[f.type]??"";}
  return out===JSON.stringify(expected,null,2);
});
rule("composer.parseArguments", "Tools receive JSON objects only; malformed JSON has an explicit error and empty input means an empty object", ([source],out)=>{
  try{const value=JSON.parse(String(source || "").trim() || "{}"); return value && typeof value==="object" && !Array.isArray(value) ? same(out,{value}) : typeof out?.error==="string" && /JSON object/.test(out.error) && !Object.hasOwn(out,"value");}
  catch {return typeof out?.error==="string" && /valid JSON/.test(out.error) && !Object.hasOwn(out,"value");}
});
rule("composer.filterTools", "Every query term must match catalog text; available tools lead and names break ties", ([rows,query],out)=>{
  const terms=String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  return same(out,(rows || []).filter(r=>terms.every(t=>`${r.name} ${r.category || ""} ${r.description || ""} ${(r.aliases || []).join(" ")}`.toLowerCase().includes(t))).sort((a,b)=>Number(b.available)-Number(a.available)||a.name.localeCompare(b.name)));
});
rule("composer.toolScope", "UI tools and desktop calls disclose their own state folder; ordinary workspace tools report the chat root", ([v],out)=>{
  if(String(v.tool || "").startsWith("neyvia."))return out?.root===null && out.label==="Runs in Neyvia's own workspace (sidebar, projects, sessions), not in this chat's folder.";
  if(v.desktop)return same(out,{root:v.cwd || null,label:"The desktop app runs a short list of Neyvia tools in Neyvia's own state folder, not in this chat's folder."});
  return same(out,v.cwd?{root:v.cwd,label:`Runs in this chat's folder: ${v.cwd}`}:{root:null,label:"This chat has no folder, so the tool runs in Neyvia's own state folder."});
});
rule("composer.draftUpdate", "A draft write changes its named chat only and keeps one stable empty value for subscriptions", ([id,before,others,value,store,empty],out)=>out===value && store.get(id)===(value.length?value:empty) && others.every(([key,old])=>key===id || store.get(key)===old));
rule("composer.attachResult", "Committed attachment bytes pass the second admission gate and origin drafts stay within limits", ([id,store],out)=>typeof out==="string" && store.get(id).length<=6 && store.get(id).every(i=>imageTypes.includes(i.mime) && i.data.length<=perImage) && store.get(id).reduce((sum,i)=>sum+i.data.length,0)<=allImages);
rule("conductor.turnKind", "Only classify/plan suffixes identify planning turns; acceptance verifier remains a task", ([run="",job=""],out)=>{const tail=String(run).startsWith(`${job}-`)?String(run).slice(job.length+1):String(run).split("-").at(-1);return out===(tail==="classify"?"classify":tail==="plan"?"plan":"task");});
rule("conductor.mergeJobs", "Job paging upserts by id with later data and keeps newest-created first", ([current=[],page=[]],out)=>{const byId=new Map([...current,...page].map(j=>[j.id,j]));return same(out,[...byId.values()].sort((a,b)=>String(b.createdAt || "").localeCompare(String(a.createdAt || ""))));});
rule("conductor.planProblems", "Goal, folder, acceptance checks and all required planner/executor/verifier routes are required", ([v,profiles={}],out)=>{
  const expected=[]; if(!String(v.goal || "").trim())expected.push("Say what should be true when it's done.");if(!String(v.folder || "").trim())expected.push("Choose the folder it works in.");if(!String(v.checks || "").split("\n").some(l=>l.trim()))expected.push("Add at least one check the verifier can prove.");
  const absent=["planner","executor","verifier"].filter(k=>!profiles[k]);if(absent.length)expected.push(`Choose who does the ${absent.join(", ")} work.`);return same(out,expected);
});
function taskLevels(tasks,levels){
  if(!Array.isArray(levels) || !same(ids(levels.flat().filter(Boolean)),ids(tasks))) {
    // Different dependency groups legitimately reorder input tasks.
    if(!same(ids(levels?.flat().filter(Boolean)||[]).sort(),ids(tasks).sort()))return false;
  }
  const positions=new Map(); levels.forEach((group,level)=>(group || []).forEach(t=>positions.set(t.id,level)));
  const byId=new Map(tasks.map(t=>[t.id,t]));
  const cyclic=id=>{const active=new Set(),seen=new Set();const walk=k=>{if(active.has(k))return true;if(seen.has(k)||!byId.has(k))return false;active.add(k);const c=(byId.get(k).needs || []).some(walk);active.delete(k);seen.add(k);return c;};return walk(id);};
  return tasks.every(t=>Number.isInteger(positions.get(t.id)) && (cyclic(t.id) || positions.get(t.id)===(t.needs || []).reduce((m,id)=>byId.has(id)?Math.max(m,positions.get(id)+1):m,0)));
}
rule("conductor.shapeJob", "Worker terminal status overrides saved phase; dependency levels, totals, unknown usage and one-time start/pause/resume controls remain honest", ([job],out)=>{
  if(!job)return out===null; const s=job.conductor || job.result?.conductor || {}, tasks=s.tasks || [], receipts=s.receipts || [], live=["queued","running"].includes(job.status);
  const phase=job.status==="interrupted"?"interrupted":["cancelled","cancelling"].includes(job.status)?"stopped":job.status==="failed"?"failed":s.phase || (job.status==="queued"?"queued":"planning");
  const usage=receipts.map(r=>r.usage?.totalTokens??r.usage?.threadTotal?.totalTokens).filter(Number.isFinite);
  return out?.phase===phase && out.live===live && same(ids(out.tasks),ids(tasks)) && taskLevels(out.tasks,out.levels) && out.done===tasks.filter(t=>t.status==="completed").length && out.tokens===(usage.length?usage.reduce((a,b)=>a+b,0):null) && out.tokensComplete===(usage.length===receipts.length) && out.durationMs===receipts.reduce((sum,r)=>sum+(r.durationMs || 0),0) && out.canStart===(live && phase==="ready" && !job.conductorControl?.approved) && out.canPause===(live && phase==="running") && out.canResume===(live && phase==="paused") && out.canStop===live && same(out.planning,out.receipts.filter(r=>r.kind!=="task"));
});
rule("gamedev.keepSelection", "Native selection never changes implicitly; browser reload affinity follows only one same-project/context replacement", ([current,sessions],out)=>{
  const live=sessions.filter(s=>s.status==="connected"), picked=sessions.find(s=>s.sessionId===current);
  const scene=s=>/^browser-/.test(String(s?.environment || ""));
  if(current && scene(picked) && picked.status!=="connected") {const replacements=live.filter(s=>scene(s) && s.projectPath===picked.projectPath && s.context===picked.context);if(replacements.length===1)return out===replacements[0].sessionId;}
  return out===(current || (live.length===1?live[0].sessionId:""));
});
rule("gamedev.tabForStage", "Explicit known tabs win, then launcher app aliases, then embedded Browser 3D", ([app,target],out)=>{const wanted=String(target || "").toLowerCase();return out===(["babylon","godot","unity","roblox","blender","assets"].includes(wanted)?wanted:({godot:"godot",unity:"unity",roblox:"roblox","asset-checks":"assets",playtest:"babylon"}[app] || "babylon"));});
rule("gamedev.actionFields", "Godot edit/interact and Unity test forms retain their typed bridge fields/defaults; other actions return valid field arrays", ([engine,action],out)=>{
  if(!Array.isArray(out) || out.some(f=>!f.key || !["text","vec3","number","bool","choice","json"].includes(f.kind)))return false;
  if(engine==="godot" && action==="edit")return same(out.map(f=>[f.key,f.kind,f.initial]),[["node","text","Player"],["property","choice","position"],["value","vec3",[0,0,0]],["value","bool",true]]) && out[2].when({property:"position"}) && !out[2].when({property:"visible"}) && out[3].when({property:"visible"}) && !out[3].when({property:"position"});
  if(engine==="godot" && action==="interact")return same(out.map(f=>[f.key,f.kind,f.initial]),[["node","text","Player"],["input","json",{action:"jump"}]]);
  if(engine==="unity" && action==="test")return same(out.map(f=>[f.key,f.kind,f.initial]),[["*","json",{mode:"EditMode"}]]);
  return true;
});
rule("gamedev.visibleFields", "Conditional controls show exactly fields whose predicates hold", ([fields,values],out)=>same(out,fields.filter(f=>!f.when || f.when(values))));
rule("gamedev.initialValues", "Form defaults resolve duplicate keys according to their condition", ([fields],out)=>{const value={};for(const f of fields)if(!(f.key in value)||(f.when && f.when(value)))value[f.key]=f.initial;return same(out,value);});
rule("gamedev.buildArgs", "Visible fields become exact bridge args; vectors/numbers are finite, JSON text must parse as an object and wildcard fields are flattened", ([fields,values],out)=>{
  const expected={};for(const f of fields.filter(f=>!f.when || f.when(values))) {const v=values[f.key];
    if(f.kind==="json"){let parsed;try{parsed=typeof v==="string"?JSON.parse(v || "{}"):v;}catch{return false;}if(f.key==="*")Object.assign(expected,parsed);else expected[f.key]=parsed;}
    else if(f.kind==="vec3"){if(!Array.isArray(v)||v.length!==3||v.map(Number).some(n=>!Number.isFinite(n)))return false;expected[f.key]=v.map(Number);}
    else if(f.kind==="number"){if(!Number.isFinite(Number(v)))return false;expected[f.key]=Number(v);}
    else if(f.kind==="bool")expected[f.key]=Boolean(v);
    else if(String(v??"").trim())expected[f.key]=String(v??"").trim();
  }return same(out,expected);
});
rule("missions.shapeMission", "Mission observers retain tasks, normalize unknown states, compute prerequisite levels and progress, and preserve draft/paused/stopped phases", ([m],out)=>{
  if(!out || !same(ids(out.tasks),ids(m.tasks || [])))return false;
  return out.tasks.every((t,i)=>t.key===t.id && t.localId===(String(t.id).startsWith(`${m.id}:`)?String(t.id).slice(m.id.length+1):String(t.id)) && t.status===(states.includes(m.tasks[i].status)?m.tasks[i].status:"waiting")) && taskLevels(out.tasks,out.levels) && same(out.counts,counts(out.tasks)) && out.progress===(out.tasks.length?out.counts.done/out.tasks.length:0) && out.phase===(["draft","paused","stopped"].includes(m.status)?m.status:m.executionStatus || "waiting");
});
rule("missions.draftProblems", "Mission drafts need a goal, folder, task prompts, acceptance and a positive optional budget", ([d],out)=>{
  const expected=[];if(!d.goal.trim())expected.push("Say what the mission should achieve.");if(!d.folder.trim())expected.push("Choose the project folder it works in.");if(!d.tasks.length)expected.push("Add at least one task.");d.tasks.forEach((t,i)=>{if(!t.prompt.trim())expected.push(`Task ${i+1} needs a prompt.`);});if(!d.acceptance.split("\n").some(t=>t.trim()))expected.push("Add at least one acceptance check: how you'll know it's done.");if(d.maxTokens && !(Number(d.maxTokens)>0))expected.push("The token budget must be a positive number.");return same(out,expected);
});
rule("missions.createRequest", "Creation trims fields, preserves harness/model routing and removes self/missing prerequisites; optional positive budget is rounded", ([d],out)=>same(out,{
  goal:d.goal.trim(),folder:d.folder.trim(),acceptanceChecks:d.acceptance.split("\n").map(s=>s.trim()).filter(Boolean),...(Number(d.maxTokens)>0?{budget:{maxTokens:Math.round(Number(d.maxTokens))}}:{}),tasks:d.tasks.map(t=>({id:t.id,prompt:t.prompt.trim(),...(t.title.trim()?{title:t.title.trim()}:{}),harness:t.harness,...(t.model.trim()?{model:t.model.trim()}:{}),needs:t.needs.filter(id=>id!==t.id && d.tasks.some(row=>row.id===id))}))
}));
rule("missions.planPrompt", "Planning asks for the real mission.create tool and explicitly leaves starting to the person", ([goal,folder],out)=>typeof out==="string" && out.startsWith(`Plan a Neyvia mission for this goal: ${goal.trim()}\nProject folder: ${folder.trim()}\n`) && out.includes("Store it with neyvia.mission.create. Do not start it: I'll review and start it from Missions."));
rule("nightshift.shapeBoard", "Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts", ([rows=[],opts={}],out)=>{
  const all=rows.filter(t=>t && t.id), wanted=all.filter(t=>opts.includeMissions || !t.missionId);
  if(!out || !same(ids(out.tasks),ids(wanted)) || !taskLevels(out.tasks,out.levels))return false;
  return out.tasks.every((t,i)=>t.status===(states.includes(wanted[i].status)?wanted[i].status:"waiting") && t.paul===(String(t.owner || "").toLowerCase()==="paul") && same(t.missing,t.needs.filter(n=>!all.some(row=>row.id===n))) && same(t.open,t.needs.filter(n=>all.find(row=>row.id===n)?.status!=="done")) && same(t.dependents,ids(out.tasks.filter(row=>row.needs.includes(t.id)))) && out.byId.get(t.id)===t) && out.missionCount===all.filter(t=>t.missionId).length && same(out.counts,counts(out.tasks)) && same(out.edges,out.tasks.flatMap(t=>t.needs.filter(n=>out.byId.has(n)).map(from=>({from,to:t.id})))) && out.progress===(out.tasks.length?out.counts.done/out.tasks.length:0);
});
rule("nightshift.startable", "Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded", ([rows=[]],out)=>same(out,rows.filter(t=>!t.paul && String(t.owner || "").toLowerCase()!=="paul" && !t.armed && t.status==="waiting")));
rule("nightshift.evidenceView", "Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning", ([e],out)=>{
  if(!e)return out===null;if(typeof e==="string")return same(out,{kind:"note",label:e,detail:e});
  if(e.type==="file")return out?.kind==="file" && out.path===e.path && out.label===(String(e.path || "").split(/[\\/]/).filter(Boolean).at(-1) || String(e.path || "")) && out.detail===`${e.path}${e.sha256?`\nSHA-256 ${e.sha256}`:""}`;
  if(e.type==="commit")return same(out,{kind:"commit",label:`Commit ${String(e.hash || "").slice(0,8)}`,detail:e.hash,hash:e.hash});
  if(e.type==="run")return same(out,{kind:"run",label:"Agent run finished",detail:e.runId,sessionId:e.sessionId || "",runId:e.runId});
  if(e.type==="command")return same(out,{kind:"command",label:`Command: ${String(e.command || "").slice(0,60)}`,detail:`${e.command}\nexit ${e.exitCode}\n${e.output || ""}`,owner:true});
  return same(out,{kind:"note",label:String(e.type || "Evidence"),detail:JSON.stringify(e)});
});
rule("nightshift.morning", "Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence", ([s],out)=>{
  if(!s)return out===null;const tasks=(s.tasks || []).filter(t=>!t.missionId), done=tasks.filter(t=>t.status==="done");
  const u=s.usage || {}, split=[u.inputTokens,u.outputTokens,u.cachedInputTokens].every(v=>Number.isFinite(v) && v>=0);
  if(out?.newTokens!==(split ? Math.max(0,u.inputTokens-u.cachedInputTokens)+u.outputTokens : null) || out?.cacheReadTokens!==(split ? u.cachedInputTokens : null) || out?.tokenBreakdownUnknownRuns!==(u.tokenBreakdownUnknownRuns || 0))return false;
  return out?.unknownRuns===Object.values(s.perHarness || {}).reduce((sum,r)=>sum+(r?.unknownCompletedRuns || 0),0) && out.tokens===(s.usage?.reportedTokens || 0) && same(out.running,tasks.filter(t=>t.status==="running")) && same(out.blocked,(s.blocked || []).filter(t=>!t.missionId)) && same(out.needsReview,(s.needsReview || []).filter(t=>!t.missionId)) && same(out.waitingOnPaul,(s.waitingOnPaul || []).filter(t=>!t.missionId)) && same(out.done,done.map(task=>({task,evidence:(s.evidenceLinks || []).filter(e=>e.taskId===task.id).at(-1) || task.evidence || null}))) && out.nightSeconds===(s.night?.elapsedSeconds || 0);
});
const clock=/^(?:[01]\d|2[0-3]):[0-5]\d$/;
rule("nightshift.quietNow", "Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day", ([q,now=new Date()],out)=>{
  if(!q || !clock.test(q.start || "") || !clock.test(q.end || ""))return out===false;
  const minutes=q.timeZone==="UTC"?now.getUTCHours()*60+now.getUTCMinutes():now.getHours()*60+now.getMinutes(), to=s=>Number(s.slice(0,2))*60+Number(s.slice(3)), start=to(q.start),end=to(q.end);
  return out===(start===end || (start<end?minutes>=start && minutes<end:minutes>=start || minutes<end));
});
rule("nightshift.treeLayout", "Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks", ([board,{width=280,height=180}={}],out)=>{
  const levels=board?.levels || []; if(!out || out.width!==width || out.height!==height || out.mid!==width/2 || out.ground!==height-12 || !same(out.leaves.map(l=>l.task.id).sort(),ids(levels.flat()).sort()))return false;
  return out.leaves.every(leaf=>{
    const i=levels.findIndex(rows=>rows.includes(leaf.task)),at=levels[i].indexOf(leaf.task),sign=(at+i)%2?1:-1;
    const side=levels[i].filter((task,index)=>(index+i)%2===(at+i)%2), position=side.indexOf(leaf.task),mid=width/2,spacing=Math.min(22,(mid-30)/side.length),x=mid+sign*(18+spacing*position+spacing*0.6),y=height-12-26-i*Math.min(34,(height-12-44)/Math.max(1,levels.length));
    return leaf.sign===sign && leaf.x===Math.round(x*10)/10 && leaf.y===Math.round((y+4-position*1.6-(x-mid)*sign*0.06)*10)/10;
  });
});
rule("nightshift.policyForm", "Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets", ([p={}],out)=>{
  const blank=v=>v==null?"":String(v), units=(v,n)=>v?String(Math.round(v/n*10)/10):"";
  return out?.paused===Boolean(p.paused) && out.maxConcurrent===blank(p.maxConcurrent) && out.maxNightHours===units(p.maxNightSeconds,3600) && out.maxTaskMinutes===units(p.maxTaskSeconds,60) && out.maxTaskTokens===blank(p.maxTaskTokens) && out.holdOn===(p.holdAtPlanPercent!=null) && out.holdAt===blank(p.holdAtPlanPercent??70) && out.gpuForAsr===Boolean(p.gpuReservedFor) && out.gpuReservedFor===(p.gpuReservedFor || "ASR") && out.quietOn===Boolean(p.quietGpuHours) && out.quietStart===(p.quietGpuHours?.start || "08:00") && out.quietEnd===(p.quietGpuHours?.end || "23:00") && out.quietTz===(p.quietGpuHours?.timeZone || "local") && ["codex","claude-code","neyvia","opencode"].every(id=>same(out.budgets[id],{tokens:blank(p.perHarnessBudgets?.[id]?.maxTokens),hours:units(p.perHarnessBudgets?.[id]?.maxSeconds,3600)}));
});
rule("nightshift.policyPatch", "Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget", ([f],out)=>{
  let problems=0;const count=(v,max)=>{const text=String(v??"").trim().replace(/[\s,_]/g,"");if(!text)return null;const n=Number(text);if(!Number.isInteger(n)||n<1||(max && n>max)){problems++;return null;}return n;};
  const seconds=(v,unit)=>{const text=String(v??"").trim().replace(",",".");if(!text)return null;const n=Number(text);if(!Number.isFinite(n)||n<=0){problems++;return null;}return Math.max(1,Math.round(n*unit));};
  const expected={paused:Boolean(f.paused),maxConcurrent:count(f.maxConcurrent),maxNightSeconds:seconds(f.maxNightHours,3600),maxTaskSeconds:seconds(f.maxTaskMinutes,60),maxTaskTokens:count(f.maxTaskTokens),holdAtPlanPercent:f.holdOn?count(f.holdAt,100)??70:null,gpuReservedFor:f.gpuForAsr?(f.gpuReservedFor || "ASR"):null,quietGpuHours:null,perHarnessBudgets:{}};
  if(f.quietOn){if(!clock.test(f.quietStart)||!clock.test(f.quietEnd))problems++;else expected.quietGpuHours={start:f.quietStart,end:f.quietEnd,timeZone:f.quietTz==="UTC"?"UTC":"local"};}
  for(const id of ["codex","claude-code","neyvia","opencode"]){const b=f.budgets?.[id] || {}, maxTokens=count(b.tokens),maxSeconds=seconds(b.hours,3600);if(id==="opencode" && maxTokens!=null)problems++;if(maxTokens!=null || maxSeconds!=null)expected.perHarnessBudgets[id]={maxTokens,maxSeconds};}
  return same(out?.patch,expected) && out.problems.length===problems && out.problems.every(s=>typeof s==="string" && s.length>0);
});
const regions=["sidebar","main","panel","canopy"], limits={sidebar:[220,440],panel:[300,600],canopy:[240,440],dock:[300,680]}, widgets={continue:["m","l"],needs:["s","m","l"],running:["s","m","l"],nightshift:["s","m"],projects:["s","m","l"],usage:["s","m"]};
const clamp=(id,value)=>{const [min,max]=limits[id] || [0,Infinity];return Math.round(Math.min(max,Math.max(min,Number(value)||min)));};
const reorder=(rows,from,to)=>{if(from<0 || from===to)return rows;const result=rows.slice(), moved=result.splice(from,1)[0];result.splice(Math.max(0,Math.min(result.length,to)),0,moved);return result;};
rule("layout.normalizeLayout", "Stored junk cannot remove regions or add unknown widths/widgets; modes/defaults are normalized and duplicate widgets disappear", ([s],out)=>{
  const v=s && typeof s==="object"?s:{}, order=Array.isArray(v.order)?v.order.filter((id,i,l)=>regions.includes(id)&&l.indexOf(id)===i):[];
  for(const id of regions)if(!order.includes(id))order.splice(id==="sidebar"?0:order.length,0,id);
  const widths=Object.fromEntries(Object.entries(v.widths || {}).filter(([id,w])=>limits[id]&&Number.isFinite(Number(w))).map(([id,w])=>[id,clamp(id,w)]));
  const base=[{id:"continue",size:"l"},{id:"needs",size:"m"},{id:"running",size:"m"},{id:"nightshift",size:"s"},{id:"usage",size:"s"},{id:"projects",size:"m"}], seen=new Set(), want=(Array.isArray(v.widgets)?v.widgets:base).filter(w=>w && widgets[w.id] && !seen.has(w.id) && seen.add(w.id)).map(w=>({id:w.id,size:widgets[w.id].includes(w.size)?w.size:widgets[w.id][0]}));
  return same(out,{order,widths,canopy:["auto","on","off"].includes(v.canopy)?v.canopy:"auto",dock:v.dock==="left"?"left":"right",sidebarHidden:v.sidebarHidden===true,widgets:want});
});
for(const name of ["moveRegion","nudgeRegion"])rule(`layout.${name}`, "Region movement preserves all other layout fields and clamps target order", ([layout,id,to],out)=>same(out,{...layout,order:reorder(layout.order,layout.order.indexOf(id),name==="nudgeRegion"?layout.order.indexOf(id)+to:to)}));
rule("layout.setWidth", "Pointer widths clamp to the selected region and leave all others intact", ([l,id,value],out)=>same(out,{...l,widths:{...l.widths,[id]:clamp(id,value)}}));
rule("layout.keyWidth", "Keyboard resizing uses 16px or shifted 48px, with Home/End bounds and no action for unknown keys", ([id,value,key,shift=false],out)=>out===(key==="Home"?limits[id][0]:key==="End"?limits[id][1]:key==="ArrowLeft"?clamp(id,value-(shift?48:16)):key==="ArrowRight"?clamp(id,value+(shift?48:16)):null));
rule("layout.sideOf", "Splitter sides follow region position relative to the conversation", ([order,id],out)=>out===(order.indexOf(id)<order.indexOf("main")?"start":"end"));
rule("layout.fitLayout", "Resize preserves saved values, gives proportional slack before dropping Canopy, keeps conversation comfort/minimum, then floats panel", ([layout,{viewport,present,defaults}],out)=>{
  const wanted=["sidebar","panel","canopy"].filter(id=>present[id]), without=wanted.filter(id=>id!=="canopy");
  const candidates=[[wanted,false,640],[without,false,640],[without,false,440],[without,wanted.includes("panel"),440]];
  const base=Object.fromEntries(Object.keys(limits).map(id=>[id,clamp(id,layout.widths[id]??defaults[id])]));
  const choice=candidates.find(([shown,float,main])=>shown.filter(id=>!(id==="panel"&&float)).reduce((sum,id)=>sum+limits[id][0],main)<=viewport) || candidates[3];
  const [shown,float,main]=choice, columns=shown.filter(id=>!(id==="panel"&&float)), over=columns.reduce((s,id)=>s+base[id],main)-viewport, slack=columns.reduce((s,id)=>s+base[id]-limits[id][0],0), widths={...base};
  if(over>0 && slack>0)for(const id of columns)widths[id]-=Math.ceil(Math.min(over,slack)*(base[id]-limits[id][0])/slack);
  return same(out,{widths,show:Object.fromEntries(["sidebar","panel","canopy"].map(id=>[id,shown.includes(id)])),dropped:wanted.filter(id=>!shown.includes(id)),floatPanel:float});
});
for(const name of ["moveWidget","nudgeWidget","cycleWidgetSize","removeWidget","addWidget"])rule(`layout.${name}`, "Widget edits preserve layout, prevent duplicates, obey each widget's sizes and move only the requested item", ([layout,id,to],out)=>{
  const rows=layout.widgets, from=rows.findIndex(w=>w.id===id);let result=rows;
  if(name==="moveWidget"){const target=rows.findIndex(w=>w.id===to);if(from>=0&&target>=0)result=reorder(rows,from,target);}
  if(name==="nudgeWidget" && from>=0)result=reorder(rows,from,from+to);
  if(name==="cycleWidgetSize")result=rows.map(w=>w.id===id?{...w,size:widgets[id][(widgets[id].indexOf(w.size)+1)%widgets[id].length]}:w);
  if(name==="removeWidget")result=rows.filter(w=>w.id!==id);
  if(name==="addWidget" && widgets[id] && from<0)result=[...rows,{id,size:widgets[id][0]}];
  return same(out,{...layout,widgets:result});
});
rule("layout.hiddenWidgets", "Add list names exactly known widgets absent from layout", ([layout],out)=>same(out,Object.keys(widgets).filter(id=>!layout.widgets.some(w=>w.id===id))));
rule("onboarding.interestsFor", "Direct interests win over tiers; unknown/missing tiers select nothing", ([catalog,{interests=[],tier=""}={}],out)=>same(out,interests.length?interests:catalog?.tiers?.find(t=>t.id===tier)?.interests || []));
rule("onboarding.recommend", "Recommendations union selected interest resources in catalog order and preserve unconditional tour chapters", ([c,chosen],out)=>{
  const union=key=>[...new Set((c?.interests || []).filter(r=>chosen.includes(r.id)).flatMap(r=>r[key] || []))], wanted=union("chapters");
  return same(out,{apps:union("apps"),packs:union("packs"),runtimes:union("runtimes"),chapters:(c?.tutorial?.chapters || []).filter(r=>!r.interests.length || wanted.includes(r.id))});
});
rule("onboarding.timeline", "Tour duration is 60–90 seconds when nonempty, proportional chapters are contiguous and last chapter consumes rounding remainder", ([chapters],out)=>{
  const total=chapters.reduce((sum,c)=>sum+c.durationMs,0);if(!total)return same(out,{chapters:[],totalMs:0});
  const target=Math.min(90000,Math.max(60000,total));let at=0,elapsed=0;
  return out?.totalMs===Math.round(target) && out.chapters.length===chapters.length && out.chapters.every((c,i)=>{elapsed+=chapters[i].durationMs;const end=i===chapters.length-1?Math.round(target):Math.round(elapsed*(target/total)), duration=end-at, valid=c.start===at && c.durationMs===duration && c.durationMs>=0 && same({...c,start:undefined,durationMs:undefined},{...chapters[i],start:undefined,durationMs:undefined});at=end;return valid;});
});
rule("onboarding.locate", "Every playhead maps to its containing chapter with clamped progress; empty tours have no chapter", ([p,time],out)=>{
  if(!p.chapters.length)return same(out,{index:0,chapter:null,progress:0});const at=Math.max(0,Math.min(time,p.totalMs)), next=p.chapters.findIndex(c=>at<c.start+c.durationMs), index=next<0?p.chapters.length-1:next,c=p.chapters[index];return same(out,{index,chapter:c,progress:c.durationMs>0?Math.max(0,Math.min(1,(at-c.start)/c.durationMs)):1});
});
const onboardBytes=n=>{const v=Number(n)||0;return v<1024?`${v} B`:v<1024**2?`${(v/1024).toFixed(0)} KB`:v<1024**3?`${(v/1024**2).toFixed(1)} MB`:`${(v/1024**3).toFixed(2)} GB`;};
rule("onboarding.downloadView", "Download percent uses measured bytes; busy/end/error words reflect state and measured ETA", ([s],out)=>{
  const state=s?.state || "idle", total=Number(s?.totalBytes)||0,done=Math.min(total || Infinity,Number(s?.doneBytes)||0),speed=Number(s?.bytesPerSecond)||0,left=speed&&total?Math.ceil((total-done)/speed):null;
  const headlines={paused:"Paused",done:"Essentials ready",failed:"The download stopped"}, detail=state==="done"?`${onboardBytes(total)} · every file checked`:state==="failed"?(s?.error || "Something went wrong."):state==="paused"?`${onboardBytes(done)} of ${onboardBytes(total)} · resumes where it left off`:total?`${onboardBytes(done)} of ${onboardBytes(total)}${left!=null && left>0?` · about ${left<60?`${left} s`:`${Math.ceil(left/60)} min`} left`:""}`:"Starting…";
  return same(out,{state,percent:total?Math.floor(done/total*100):state==="done"?100:0,headline:headlines[state] || "Getting the essentials",detail,busy:["starting","running","verifying"].includes(state)});
});
rule("onboarding.packView", "Pack installation controls reflect actual availability and copying state; receipt detail names verified file count/bytes", ([row,status],out)=>{
  const state=status?.state || (row?.ready===false?"unavailable":"not-installed"),total=Number(status?.totalBytes)||0,done=Math.min(total || Infinity,Number(status?.doneBytes)||0),files=status?.files?.total || 0,missing=status?.missing?.length?status.missing:row?.missing || [],size=row?.resourceClass==="heavy"?"Large":row?.resourceClass==="light"?"Tiny":"Small";
  const details={unavailable:`Not ready yet · ${missing.length || "some"} thing${missing.length===1?"":"s"} missing`,"not-installed":`${size} pack · ${missing.length?"some parts still to come":"installs on its own"}`,queued:"Starting…",installing:total?`${onboardBytes(done)} of ${onboardBytes(total)}`:"Installing…",installed:`Installed · ${files?`${files} file${files===1?"":"s"} checked`:"checked"}${total?` · ${onboardBytes(total)}`:""}`,failed:status?.error || "The install stopped."};
  return same(out,{state,percent:total?Math.floor(done/total*100):state==="installed"?100:0,detail:details[state] || "",missing,busy:["queued","installing"].includes(state),canInstall:["not-installed","failed"].includes(state)});
});
const toolNames={"latex-suite":"LaTeX","pytorch-huggingface":"PyTorch and Hugging Face","scientific-python":"Scientific Python","docker-engine":"Docker","android-sdk":"Android SDK",glmocr:"GLM-OCR",paddleocr:"PaddleOCR",ocrmypdf:"OCRmyPDF",libreoffice:"LibreOffice",languagetool:"LanguageTool","argos-translate":"Argos Translate",libretranslate:"LibreTranslate",ffmpeg:"FFmpeg",imagemagick:"ImageMagick",kicad:"KiCad",freecad:"FreeCAD",openscad:"OpenSCAD",postgresql:"PostgreSQL",duckdb:"DuckDB",gimp:"GIMP"};
rule("onboarding.plainMissing", "Catalog gaps use plain tool names without hiding unavailable payloads", ([value],out)=>{const text=String(value || ""),name=id=>toolNames[id] || id[0].toUpperCase()+id.slice(1),match=/No scoped redistributable runtime payload for tool\.([\w.-]+)/.exec(text);return out===(match?`${name(match[1])} isn't packaged yet`:text.replace(/\btool\.([\w-]+)/g,(_,id)=>name(id)));});
rule("onboarding.runtimeHeadline", "Only observed found runtimes produce set-to-start wording and names; no result stays checking", ([r],out)=>{
  const found=(r?.runtimes || []).filter(row=>row.found).map(row=>row.label);return same(out,!r?{title:"Looking at this PC…",sub:""}:found.length?{title:"You're set to start",sub:`Found ${found.length===1?found[0]:`${found.slice(0,-1).join(", ")} and ${found.at(-1)}`} on this PC.`}:{title:"Begin with…",sub:"No agent app was found on this PC yet. Pick one to set up, or start with Neyvia Native."});
});
function planStep(plan,op,{at=null,seq=null}={}) {
  if(!op || typeof op!=="object")return plan;let items=(plan?.items || []).map(t=>({...t})),explanation=plan?.explanation??null;
  if(op.op==="replace"){items=(op.items || []).filter(Boolean).map(t=>({...t}));explanation=op.explanation??null;}
  else if(op.op==="add"){if(plan?.source!==op.source){items=[];explanation=null;}const entry={...(op.item || {})},numbers=items.map(t=>Number(t.id)).filter(Number.isInteger);entry.id=entry.id || String((numbers.length?Math.max(...numbers):0)+1);items=items.filter(t=>t.id!==entry.id).concat(entry);}
  else if(op.op==="update"){if(!plan)return null;const found=items.find(t=>t.id===op.id);if(!found)return plan;if(op.status==="deleted")items=items.filter(t=>t.id!==op.id);else for(const key of ["status","text","active"])if(op[key])found[key]=op[key];}
  else return plan;
  return items.length?{items,source:op.source || plan?.source || null,explanation,updatedAt:at??plan?.updatedAt??null,throughSeq:seq??plan?.throughSeq??null}:null;
}
rule("plan.applyPlanOp", "Plan replacement clears empty lists, add upserts by id/source, update preserves unknown ids, delete clears the last item", (args,out)=>same(out,planStep(...args)));
rule("plan.planOf", "Only nonoptimistic live operations beyond the saved sequence fold onto the saved plan", ([thread],out)=>{
  if(!thread)return out===null;let expected=thread.plan || null;for(const i of thread.items || [])if(i?.data?.plan && !i.optimistic && Number(i.seq)>(Number.isFinite(thread.planSeq)?thread.planSeq:-Infinity))expected=planStep(expected,i.data.plan,{at:i.at,seq:Number(i.seq)});return same(out,expected);
});
rule("plan.planProgress", "Checklist progress normalizes states, counts completed items, chooses first active/next pending and recognizes nonempty completion", ([plan],out)=>{
  const items=(plan?.items || []).map(i=>({...i,status:["pending","in_progress","completed"].includes(i.status)?i.status:"pending"})),done=items.filter(i=>i.status==="completed").length,current=items.find(i=>i.status==="in_progress") || null;return same(out,{items,done,total:items.length,current,next:current?null:items.find(i=>i.status==="pending") || null,finished:items.length>0 && done===items.length});
});
rule("plan.showChecklist", "Unfinished checklists stay visible; complete lists remain only while agent works; empty lists hide", ([plan,working],out)=>out===Boolean(plan?.items?.length && (plan.items.some(i=>i.status!=="completed") || working)));
rule("plan.planFromPage", "Absent plan fields preserve shown plan; explicit clears advance sequence to the read's last item", ([page,existing=null],out)=>{
  if(!page || !("plan" in page))return same(out,{plan:existing?.plan??null,planSeq:existing?.planSeq??null});const seqs=(page.items || []).map(i=>Number(i.seq)).filter(Number.isFinite);return same(out,{plan:page.plan || null,planSeq:Number.isFinite(page.plan?.throughSeq)?page.plan.throughSeq:seqs.length?Math.max(...seqs):null});
});
rule("dashboard.resetsIn", "Reset words reflect measured rounded minutes/hours/days; missing reset is blank and elapsed reset is now", ([iso,now=Date.now()],out)=>{
  const at=iso?Date.parse(iso):NaN;if(!Number.isFinite(at))return out==="";const m=Math.round((at-now)/60000),h=Math.floor(m/60);return out===(m<=0?"now":m<60?`in ${m}m`:h<24?`in ${h}h${m%60?` ${m%60}m`:""}`:`in ${Math.floor(h/24)}d${h%24?` ${h%24}h`:""}`);
});
rule("dashboard.limitTone", "Provider warnings/rejections outrank percent; stale/unavailable/unknown limits never show reassuring green", ([v],out)=>{
  const n=v?.usedPercent==null || v.usedPercent===""?null:Number(v.usedPercent),percent=Number.isFinite(n)?n:null;
  return out===(!v || v.stale || v.availability==="unavailable"?"idle":v.status==="rejected"?"red":percent===null && v.status!=="allowed_warning"?"idle":percent!==null && percent>=90?"red":v.status==="allowed_warning" || percent!==null && percent>=75?"caution":"green");
});
rule("dashboard.mergePages", "Moving dashboard rows appear once in first-seen order; final page controls paging, first page keeps limits", ([pages=[]],out)=>{
  const seen=new Set(),sessions=[];for(const p of pages)for(const r of p?.sessions || [])if(r?.id && !seen.has(r.id)){seen.add(r.id);sessions.push(r);}const first=pages[0] || {},last=pages.at(-1) || {};return same(out,{...first,sessions,total:Number.isFinite(last.total)?last.total:sessions.length,nextOffset:last.nextOffset??null,hasMore:Boolean(last.hasMore??last.nextOffset!=null)});
});
rule("replay.buildTimeline", "Replay preserves sequence and real recorded span, excludes optimistic items, caps idle gaps and fills missing stamps without jumps", ([items,{idleCap=4000}={}],out)=>{
  const rows=[...(items || [])].filter(i=>i&&!i.optimistic).sort((a,b)=>Number(a.seq)-Number(b.seq)), stamps=rows.map(i=>{const n=typeof i.at==="number"?i.at:Date.parse(i.at || "");return Number.isFinite(n)?n:null;});let last=null;
  for(let i=0;i<stamps.length;i++){if(stamps[i]==null)stamps[i]=last;else last=Math.max(stamps[i],last??stamps[i]);}const first=stamps.find(n=>n!=null)??0;let previous=first,replay=0;
  const entries=rows.map((item,i)=>{const at=stamps[i]??first;replay+=Math.min(Math.max(0,at-previous),idleCap);previous=Math.max(previous,at);return {item,t:at-first,rt:replay,at};});return same(out,{entries,duration:entries.at(-1)?.t || 0,replayDuration:entries.at(-1)?.rt || 0,startedAt:first || null});
});
rule("replay.visibleCount", "Exactly entries at or before the replay playhead are visible", ([t,rt],out)=>out===t.entries.filter(e=>e.rt<=rt).length);
rule("replay.recordedAt", "Recorded clock follows the last visible entry and stays at start before the first", ([t,rt],out)=>out===(t.entries.filter(e=>e.rt<=rt).at(-1)?.at??t.startedAt));
rule("replay.playbackMs", "Playback wall time is replay time divided by at least 1x, rounded upward", ([t,speed],out)=>out===Math.ceil(t.replayDuration/Math.max(1,speed)));
rule("replay.timelineMarks", "Scrubber marks retain meaningful item identity/order, normalize position and distinguish tool errors", ([t],out)=>same(out,t.entries.filter(e=>["user","assistant","tool","approval","question","diff","compaction"].includes(e.item.kind)).map(({item,rt})=>({id:item.id,at:rt/(t.replayDuration || 1),tone:item.kind==="user"?"user":item.kind==="tool"?item.data?.status==="error"?"error":"tool":["approval","question"].includes(item.kind)?"needs":item.kind==="assistant"?"reply":"other"}))));
rule("replay.formatSpan", "Measured spans round to seconds, then zero-padded minutes and hours", ([ms],out)=>{const s=Math.max(0,Math.round(ms/1000)),m=Math.floor(s/60);return out===(s<60?`${s}s`:m<60?`${m}m ${String(s%60).padStart(2,"0")}s`:`${Math.floor(m/60)}h ${String(m%60).padStart(2,"0")}m`);});
rule("runtime.mergeRuntimes", "Catalog aliases join live rows once; readiness/capabilities/auth/model/owner policy are observed from their authoritative source", ([catalog,matrix],out)=>{
  const catalogRows=Array.isArray(catalog?.harnesses)?catalog.harnesses:[], live=Array.isArray(matrix?.runtimes)?matrix.runtimes:[], alias={neyvia:"neyvia-agent",kimi:"kimi-code",grok:"grok-build"}, pairs=catalogRows.map(h=>[h,live.find(r=>(alias[r.id] || r.id)===h.harnessId) || null]);
  for(const r of live)if(!pairs.some(([,p])=>p?.id===r.id))pairs.push([null,r]);
  if(!Array.isArray(out) || out.length!==pairs.length)return false;
  return out.every((row,i)=>{const pair=pairs.find(([h,r])=>(r?.id || h?.harnessId)===row.id);if(!pair)return false;const [h,r]=pair,installed=Boolean(h?.installed??r?.installed),connected=Boolean(r?.connected),ready=connected || h?.readiness==="ready",policy=r?matrix?.policies?.[r.id] || null:null,models=r?.options?.models || [],auth=h?.authState || (r?.auth?.authenticated || r?.auth?.loggedIn?"authenticated-live":null),authNames={"authenticated-live":"Signed in","account-action-required":"Sign-in needed","provider-setup-required":"Provider setup needed","route-setup-required":"Route setup needed","route-dependent":"Uses the chosen model's sign-in","security-scope-required":"Security profile needed","not-installed":"Not installed",unverified:"Not checked"};
    return row.name===(h?.label || r?.id) && row.installed===installed && row.mode===(r?({native:"Native",connected:"Connected",wrapped:"Wrapped",planned:"Not wired yet"}[r.kind] || r.kind):"Catalog only") && row.version===(h?.version || r?.version || "") && row.starts===Boolean(r?.capabilities?.start) && same(row.can,r?["start","continue","interrupt","approve"].filter(k=>r.capabilities?.[k]):[]) && row.status===(ready?"Ready":installed?"Installed, not usable yet":"Not installed") && row.tone===(ready?"green":installed?"caution":"idle") && row.defaultModel===(h?.defaultModel || models.find(m=>m.default)?.id || "") && row.policyId===(r && ["neyvia","codex","claude-code","opencode"].includes(r.id)?r.id:null) && row.ceiling===(policy?.permissionCeiling || "") && same(row.allowedModels,policy?.allowedModels || []) && row.auth===(auth?authNames[auth] || auth:r?.auth?.status && r.auth.status!=="unknown"?r.auth.status:"Not checked") && row.rank===(connected?8:0)+(ready?4:0)+(installed?2:0)+(r?1:0) && (!i || out[i-1].rank>=row.rank);
  });
});
rule("runtime.runtimeSummary", "Ready and installed counts come from rendered runtime rows without inventing detection", ([rows],out)=>same(out,{ready:rows.filter(r=>r.tone==="green").length,installed:rows.filter(r=>r.installed).length,total:rows.length}));
// Placement (nxPlacementModel): every app or pane is one window with one place. Moves never lose a
// window the user placed, a window's description is never rebuilt, and single places hold one window.
const PLACES = ["main", "side", "full", "bubble"];
const winKey = d => (!d || typeof d !== "object" ? "" : d.type === "pane" ? `pane:${d.kind}:${d.target ?? ""}` : d.type === "app" && d.app ? `app:${d.app}` : "");
const placed = ws => Array.isArray(ws) && ws.every(w => w && typeof w.id === "string" && PLACES.includes(w.placement) && Object.keys(w).length === 7)
  && new Set(ws.map(w => w.id)).size === ws.length && ["main", "side", "full"].every(p => ws.filter(w => w.placement === p).length <= 1)
  && ws.filter(w => w.placement === "bubble").length <= 6 && ws.filter(w => w.peek && w.placement === "bubble").length <= 1
  && ws.every(w => w.x >= 0 && w.x <= 1 && w.y >= 0 && w.y <= 1);
// Every input window is still there with its own description, unless it was the one replaced or a capped bubble.
const keeps = (input, out, allowed = () => false) => input.every(w => {
  const after = out.find(o => o.id === w.id);
  return after ? after.desc === w.desc || allowed(w, after) : allowed(w, null) || (out.filter(o => o.placement === "bubble").length === 6);
});
rule("placement.windowKey", "An app is one window whatever it shows; a pane is one per kind and target; nothing else opens", ([d], out) => out === winKey(d));
rule("placement.placeWindow", "A move puts the window in its place, swaps or bubbles the occupant, closes nothing and keeps every description", ([ws, id, place], out) => {
  if (!ws.some(w => w.id === id)) return out === ws;
  const mover = out.find(w => w.id === id);
  return placed(out) && mover?.placement === place && mover.desc === ws.find(w => w.id === id).desc && keeps(ws, out)
    && (out.length === ws.length || out.filter(w => w.placement === "bubble").length === 6);
});
rule("placement.restoreWindow", "Full screen and bubbles go back where they came from; other windows stay put", ([ws, id], out) => {
  const before = ws.find(w => w.id === id);
  if (!before || !["full", "bubble"].includes(before.placement)) return out === ws;
  const after = out.find(w => w.id === id);
  return placed(out) && after?.placement === (before.back === "side" ? "side" : "main") && keeps(ws, out) && out.length >= ws.length - 1;
});
rule("placement.openWindow", "Opening shows the window with its new description; an open one stays where the user put it; a new one replaces only its own place", ([ws, d, opts = {}], out) => {
  const id = winKey(d), before = ws.find(w => w.id === id), after = out.find(w => w.id === id);
  if (!placed(out) || !after || after.desc !== d) return false;
  if (before) return (opts.placement ? true : after.placement === before.placement) && (after.placement !== "bubble" || after.peek) && keeps(ws, out, w => w.id === id) && out.length === ws.length;
  return keeps(ws, out, (w, kept) => !kept && w.placement === after.placement && after.placement !== "bubble");
});
rule("placement.closeWindow", "Closing removes exactly that window", ([ws, id], out) => Array.isArray(out) && !out.some(w => w.id === id) && out.length === ws.length - (ws.some(w => w.id === id) ? 1 : 0) && out.every(w => ws.includes(w)));
rule("placement.moveBubble", "A bubble moves within the window; nothing else changes", ([ws, id, x, y], out) => Array.isArray(out) && out.length === ws.length && out.every((w, i) => {
  const was = ws[i];
  if (w.id !== was.id || w.desc !== was.desc || w.placement !== was.placement) return false;
  return w.id === id && was.placement === "bubble" ? w.x === Math.min(1, Math.max(0, Number.isFinite(Number(x)) ? Number(x) : 0)) && w.y === Math.min(1, Math.max(0, Number.isFinite(Number(y)) ? Number(y) : 0)) : w === was;
}));
rule("placement.peekBubble", "At most one bubble peeks; places and descriptions never change", ([ws, id, open], out) => Array.isArray(out) && out.length === ws.length
  && out.every((w, i) => w.id === ws[i].id && w.placement === ws[i].placement && w.desc === ws[i].desc) && out.filter(w => w.peek && w.placement === "bubble").length <= 1
  && (!ws.some(w => w.id === id && w.placement === "bubble") || out.find(w => w.id === id).peek === (open === undefined ? !ws.find(w => w.id === id).peek : Boolean(open))));
rule("placement.syncStage", "A stage set directly opens its window; a cleared stage closes the window beside the chat, else the full-screen one", ([ws, before, after], out) => {
  if (after === before) return out === ws;
  if (after) return placed(out) && out.some(w => w.id === winKey(after) && w.desc === after);
  const target = ws.find(w => w.placement === "main") || ws.find(w => w.placement === "full");
  return target ? out.length === ws.length - 1 && !out.some(w => w.id === target.id) && out.every(w => ws.includes(w)) : out === ws;
});
rule("placement.rememberPlacement", "Only beside-the-chat and side are remembered homes, per app or pane kind", ([prefs, d, place], out) => {
  const key = d?.type === "pane" ? `pane:${d.kind}` : d?.type === "app" ? `app:${d.app}` : "";
  if (!key || !["main", "side"].includes(place) || prefs[key] === place) return out === prefs;
  return same(out, { ...prefs, [key]: place });
});
rule("placement.normalizePrefs", "Stored placement homes keep only app/pane keys with main or side", ([saved], out) => out && typeof out === "object" && !Array.isArray(out)
  && Object.entries(out).every(([k, v]) => /^(app|pane):/.test(k) && ["main", "side"].includes(v) && saved?.[k] === v));
rule("placement.dropZone", "Outer fifths dock left or right, the top band is full screen, the bottom band a bubble, the rest beside the chat", ([p, w, h], out) => {
  const x = p.x / Math.max(1, w), y = p.y / Math.max(1, h);
  const want = x < 0.2 ? { placement: "side", side: "left" } : x > 0.8 ? { placement: "side", side: "right" } : y < 0.16 ? { placement: "full", side: null } : y > 0.84 ? { placement: "bubble", side: null } : { placement: "main", side: null };
  return same(out, want);
});
rule("placement.orderWithPanel", "The side panel moves next to the conversation on the asked side; no region is lost or duplicated", ([order, side], out) => {
  if (!order.includes("main")) return out === order;
  return Array.isArray(out) && out.length === order.filter(id => id !== "panel").length + 1 && same([...out].sort(), [...new Set([...order, "panel"])].sort())
    && out.indexOf("panel") === out.indexOf("main") + (side === "left" ? -1 : 1);
});
// App skins (nxAppSkinModel): every app wears a look made from what it is, in every theme. The shell
// carries the theme; app content is never painted green, and every text colour reads at WCAG AA.
const SKIN_IDS = ["code", "reader", "notebook", "finder", "web", "monitor", "studio", "graphite", "darkroom", "scholar"];
const rgbOf = value => { const m = /^#([0-9a-f]{6})$/i.exec(String(value || "")); if (!m) return null; const n = parseInt(m[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const lum = rgb => { const [r, g, b] = rgb.map(v => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const over = (top, alpha, under) => top.map((v, i) => v * alpha + under[i] * (1 - alpha));
// Green is a hue between 75 and 165 degrees with real saturation; near-greys carry no hue.
const greenish = rgb => { const [r, g, b] = rgb.map(v => v / 255), max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (!d || d / (1 - Math.abs(max + min - 1) || 1) < 0.18) return false;
  const h = max === r ? 60 * (((g - b) / d) % 6) : max === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
  const hue = (h + 360) % 360; return hue >= 75 && hue <= 165; };
const SKIN_EXPECT = { "pane:terminal": "code", "app:pdf": "reader", "app:notes": "notebook", "app:files": "finder", "app:browser": "web", "app:3d-studio": "graphite",
  "app:image-studio": "darkroom", "app:app-factory": "studio", "app:mobile-studio": "studio", "app:research": "scholar", "app:laya": "monitor", "pane:preview": "monitor" };
rule("appskin.skinFor", "Each app and app pane wears its own skin (terminal code, PDF reader, notes notebook, files finder, 3D graphite, images darkroom, factory studio, research scholar, agents monitor); the shell's own panes wear none", ([d], out) => {
  if (!d || typeof d !== "object" || !["app", "pane"].includes(d.type)) return out === null;
  if (d.type === "pane" && d.kind === "preview" && String(d.target || "").startsWith("remote")) return out === null;
  const key = d.type === "pane" ? `pane:${d.kind}` : `app:${d.app}`;
  return key in SKIN_EXPECT ? out === SKIN_EXPECT[key] : out === null || SKIN_IDS.includes(out);
});
rule("appskin.skinPalette", "A skin's text reads at 4.5:1 on every surface and hover, its accent text on every surface, its on-accent ink on the accent; dark skins are dark, the light themes' (Morning, Paper) are light, and no surface or accent is green", ([skin, theme], out) => {
  if (!SKIN_IDS.includes(skin)) return out === null;
  if (!out || out.skin !== skin || out.theme !== theme || out.tone !== (THEME_SCHEME[theme] === "light" ? "light" : "dark") || Object.keys(out).length !== 16) return false;
  const c = Object.fromEntries(["bg", "sidebar", "panel", "raised", "raised2", "text", "text2", "muted", "faint", "accent", "accentHi", "accentText", "onAccent"].map(k => [k, rgbOf(out[k])]));
  if (Object.values(c).some(v => !v)) return false;
  const surfaces = [c.bg, c.sidebar, c.panel, c.raised, c.raised2];
  const dark = out.tone === "dark";
  const lit = [...surfaces, over(c.text, dark ? 0.055 : 0.05, c.panel), over(c.text, dark ? 0.09 : 0.085, c.raised)];
  const texts = [c.text, c.text2, c.muted, c.faint];
  if (!texts.every(t => lit.every(s => ratio(t, s) >= 4.5))) return false;
  if (![c.bg, c.panel, c.raised].every(s => ratio(c.accentText, s) >= 4.5) || ratio(c.onAccent, c.accent) < 4.5 || ratio(c.accent, c.panel) < 3) return false;
  if (dark ? lum(c.bg) > 0.03 : lum(c.bg) < 0.7) return false;
  return ![...surfaces, c.accent, c.accentHi, c.accentText].some(greenish);
});
rule("appskin.skinTokens", "A window's custom properties are its skin's palette, with the 16 terminal colours readable on the code surface; an unknown skin sets nothing", ([skin, theme], out) => {
  if (!SKIN_IDS.includes(skin)) return out === null;
  if (!out || typeof out !== "object" || Object.keys(out).length !== 41 || !Object.keys(out).every(k => k.startsWith("--nx-"))) return false;
  const names = ["--nx-bg", "--nx-sidebar", "--nx-panel", "--nx-raised", "--nx-raised-2", "--nx-text", "--nx-text-2", "--nx-muted", "--nx-faint", "--nx-accent", "--nx-accent-hi", "--nx-accent-text", "--nx-on-accent", "--nx-hover", "--nx-active", "--nx-line", "--nx-line-strong", "--nx-selection", "--nx-focus-ring", "--nx-card-shadow"];
  if (!names.every(n => typeof out[n] === "string" && out[n].length > 3)) return false;
  const ansi = Object.keys(out).filter(k => k.startsWith("--nx-ansi-"));
  if (ansi.length !== 16 || !ansi.every(k => rgbOf(out[k]))) return false;
  const panel = rgbOf(out["--nx-panel"]), dark = THEME_SCHEME[theme] !== "light";
  const skip = dark ? ["--nx-ansi-black", "--nx-ansi-bright-black"] : ["--nx-ansi-white", "--nx-ansi-bright-white"];
  return ansi.filter(k => !skip.includes(k)).every(k => ratio(rgbOf(out[k]), panel) >= 4.5) && ratio(rgbOf(out["--nx-text"]), panel) >= 7;
});
