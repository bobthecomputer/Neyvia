import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const base = process.env.NEYVIA_CONTROLLER_URL || 'http://127.0.0.1:47881';
const statusPath='/api/desktop-controller/status';
const anonymous = await fetch(base+statusPath);
assert.equal(anonymous.status,401);
const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
assert.equal(login.status,200);
const cookie=login.headers.get('set-cookie')?.split(';')[0];
assert.ok(cookie);
const send=(body,extra={})=>fetch(base+'/api/backend',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie,Origin:base,...extra},body:JSON.stringify(body)});
const status=await fetch(base+statusPath,{headers:{Cookie:cookie}}).then(r=>r.json());
assert.equal(status.ok,true);
const reserved=await send({command:'desktop_controller_poll_command',payload:{}});
assert.equal(reserved.status,403);
const foreign=await send({command:'get_agent_prompt_library_command',payload:{}},{'X-Neyvia-Controller':'desktop',Origin:'https://unrelated.invalid'});
assert.equal(foreign.status,403);
let offline;
if (!status.data.online) {
  const request=await send({command:'get_agent_prompt_library_command',payload:{},controllerRequestId:crypto.randomUUID()},{'X-Neyvia-Controller':'desktop'});
  assert.equal(request.status,503);
  offline={status:request.status,handledWithoutFallback:true};
}
const proof={anonymousStatus:anonymous.status,reservedHostCommandStatus:reserved.status,foreignOriginStatus:foreign.status,desktopOnline:status.data.online,...(offline?{offline}:{})};
await writeFile(new URL('../proof/desktop-controller-20260925/http-boundary.json',import.meta.url),JSON.stringify(proof,null,2));
console.log(JSON.stringify(proof));
