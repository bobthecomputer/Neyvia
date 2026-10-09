'use strict';
const fs=require('node:fs'),http=require('node:http'),crypto=require('node:crypto');
const [portText,out,enginePortText]=process.argv.slice(2),port=Number(portText),enginePort=Number(enginePortText);
if(!Number.isInteger(port)||port<48721||port>48739||!Number.isInteger(enginePort)||enginePort<48721||enginePort>48739||!out||fs.existsSync(out))throw Error('Explicit owned backend/engine ports and fresh receipt required');
const report={schema:'neyvia.C2h.websocket-proof@1',at:new Date().toISOString(),checks:[],server:{connections:0,messages:[]},ports:{http:48734,socket:48735,dead:48736},calls:[]};
const server=http.createServer();const fixture=http.createServer((q,r)=>{
 const mode=new URL(q.url,'http://127.0.0.1:48734').pathname.slice(1);
 const target=mode==='dead'?'ws://127.0.0.1:48736/':mode==='policy'?'wss://example.com/fixture':mode==='greet'?'ws://127.0.0.1:48735/greet':'ws://127.0.0.1:48735/echo';
 r.setHeader('Content-Type','text/html');r.end('<!doctype html><title>Socket '+mode+'</title><output>pending</output><script>const events=[];const show=()=>document.querySelector("output").textContent=JSON.stringify(events);const ws=new WebSocket('+JSON.stringify(target)+');ws.onopen=()=>{events.push("open");show();'+(mode==='echo'?'ws.send("hello");':'')+'};ws.onmessage=e=>{events.push("message:"+e.data);show();ws.close(4001,"done");};ws.onerror=()=>{events.push("error");show();};ws.onclose=e=>{events.push("close:"+e.code);show();};</script>');
});
function frame(opcode,data){const b=Buffer.from(data),h=Buffer.alloc(b.length<126?2:4);h[0]=128|opcode;if(b.length<126)h[1]=b.length;else{h[1]=126;h.writeUInt16BE(b.length,2);}return Buffer.concat([h,b]);}
// Disposable RFC6455 loopback fixture; only small text and Close frames are used.
server.on('upgrade',(q,s)=>{report.server.connections++;const key=crypto.createHash('sha1').update(q.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');s.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+key+'\r\n\r\n');if(q.url==='/greet')s.write(frame(1,'welcome'));
 let b=Buffer.alloc(0);s.on('error',()=>{});s.on('data',chunk=>{b=Buffer.concat([b,chunk]);while(b.length>=2){let size=b[1]&127,pos=2;if(size===126){if(b.length<4)return;size=b.readUInt16BE(2);pos=4;}if(size===127){s.destroy();return;}const masked=!!(b[1]&128);if(b.length<pos+(masked?4:0)+size)return;const mask=masked?b.subarray(pos,pos+4):null;if(masked)pos+=4;const payload=Buffer.from(b.subarray(pos,pos+size)),opcode=b[0]&15;b=b.subarray(pos+size);if(mask)for(let i=0;i<payload.length;i++)payload[i]^=mask[i%4];if(opcode===1){report.server.messages.push(payload.toString());s.write(frame(1,payload));}if(opcode===8){s.end(frame(8,payload));}}});
});
let cookie,tabs=[];
async function call(op,args={}){const t=performance.now(),r=await fetch('http://127.0.0.1:'+port+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)}),v=await r.json();report.calls.push({op,ms:performance.now()-t,http:r.status,response:v});if(!r.ok)throw Error(JSON.stringify(v));return v;}
async function contract(mode,tabId){
 const response=await fetch('http://127.0.0.1:'+port+'/api/ui/tools/call',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({tool:'neyvia.manual.run',arguments:{id:'browser',chapter:'c2h-sockets',procedure:'verify-socket-'+mode,inputs:{tabId},scopeTools:['neyvia.browser.observe']}}),signal:AbortSignal.timeout(60000)});
 const receipt=await response.json();report.calls.push({op:'manual.run',mode,http:response.status,response:receipt});
 if(!response.ok||!receipt.ok||receipt.data?.result?.status!=='completed')throw Error('Socket CL contract failed: '+JSON.stringify(receipt));
 return receipt.data.result;
}
(async()=>{try{await Promise.all([new Promise(r=>server.listen(48735,'127.0.0.1',r)),new Promise(r=>fixture.listen(48734,'127.0.0.1',r))]);const dead=http.createServer();await new Promise(r=>dead.listen(48736,'127.0.0.1',r));await new Promise(r=>dead.close(r));
 const auth=await fetch('http://127.0.0.1:'+port+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});cookie=auth.headers.get('set-cookie').split(';')[0];
 await call('headless.start',{port:enginePort,assignedPorts:'48721-48739',requestTimeoutMs:60000,allowLocalFixtures:true,allowPublicResources:false});
 report.engine=(await call('state')).headless;
 for(const mode of ['echo','greet','dead','policy']){const tabId=(await call('tab.open',{url:'http://127.0.0.1:48734/'+mode,engine:'obscura'})).tabId;tabs.push(tabId);let o;const end=Date.now()+15000;do{o=await call('observe',{tabId});if(o.text.includes('close:'))break;await new Promise(r=>setTimeout(r,100));}while(Date.now()<end);const events=JSON.parse(o.text);const manual=await contract(mode,tabId);report.checks.push({mode,passed:true,events,policy:o.networkPolicy,manual});await call('tab.close',{tabId});tabs=tabs.filter(t=>t!==tabId);}
 report.manual={path:'manuals/cl/browser.cl',sha256:crypto.createHash('sha256').update(fs.readFileSync('manuals/cl/browser.cl')).digest('hex'),chapter:'c2h-sockets'};report.passed=true;
 }catch(e){report.passed=false;report.error=e.stack;process.exitCode=1;}finally{for(const tabId of tabs)await call('tab.close',{tabId}).catch(()=>{});server.close();fixture.close();report.finishedAt=new Date().toISOString();fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:report.passed,error:report.error?.slice(0,800),checks:report.checks.map(c=>({mode:c.mode,passed:c.passed,events:c.events,manualRunId:c.manual?.runId}))}));}})();
