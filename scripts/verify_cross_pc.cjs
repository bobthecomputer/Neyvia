/* Real two-process API journey; no Python tests, mocks, tailnet mutations or installs.
 * node scripts/verify_cross_pc.cjs [--keep-running]
 * Receipts/fixtures live in a disposable OS temp directory printed on completion.
 */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const net = require('node:net');
const project = path.resolve(__dirname, '..');
const python = process.env.CROSS_PC_PYTHON || 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'neyvia-cross-pc-'));
const checks = [], processes = new Map();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const pcs = [47919, 47929].map((port, index) => ({port, root: path.join(scratch, index ? 'B' : 'A'), cookie: '', base: `http://127.0.0.1:${port}`}));
for (const pc of pcs) {
  for (const folder of ['shared', 'inbox', 'unshared', 'taken']) fs.mkdirSync(path.join(pc.root, folder), { recursive: true });
}
async function http(pc, route, method = 'GET', body, headers = {}) {
  const response = await fetch(pc.base + route, { method, body: body === undefined ? undefined : Buffer.isBuffer(body) ? body : JSON.stringify(body),
    headers: { ...(pc.cookie ? {Cookie: pc.cookie} : {}), ...(!Buffer.isBuffer(body) && body !== undefined ? {'Content-Type':'application/json'} : {}), ...headers }, signal: AbortSignal.timeout(30000) });
  const cookie = response.headers.get('set-cookie');
  if (cookie) pc.cookie = cookie.split(';')[0];
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  return {status:response.status, data, headers:response.headers};
}
async function op(pc, name, args = {}) {
  const result = await http(pc, '/api/ui/devices', 'POST', {op:name, args});
  assert.equal(result.status, 200, `${name}: ${JSON.stringify(result.data)}`);
  assert.notEqual(result.data.ok, false, `${name}: ${JSON.stringify(result.data)}`);
  return result.data.data;
}
function record(name, detail) { checks.push({name, detail, ok:true}); console.log('PASS ' + name); }
async function start(pc) {
  // Refuse to attach to somebody else's proof server on the same assigned port.
  await new Promise((resolve,reject)=>{const probe=net.createServer();probe.once('error',reject);probe.listen(pc.port,'127.0.0.1',()=>probe.close(resolve));});
  const child = spawn(python, ['scripts/run_web_backend.py', '--host', '127.0.0.1', '--port', String(pc.port), '--root', pc.root,
    '--static-root', path.join(pc.root, 'static'), '--skip-runtime-auto-update'], {cwd:project, windowsHide:true,
    env:{...process.env, NEYVIA_PEER_ALLOW_LOOPBACK:'1', NEYVIA_PEER_DEFAULT_SHARE:path.join(pc.root,'shared'), NEYVIA_PEER_DEFAULT_INBOX:path.join(pc.root,'inbox'),
      NEYVIA_COORDINATOR_AUTOSTART:'0', FLUXIO_WATCHDOG_AUTOSTART:'0', NEYVIA_TOOL_AUTO_UPDATE:'0', FLUXIO_RUNTIME_AUTO_UPDATE:'0'}});
  processes.set(pc.port, child);
  let diagnostic = '';
  child.stdout.on('data', () => {});
  child.stderr.on('data', data => { diagnostic = (diagnostic + data).slice(-6000); });
  for (let index = 0; index < 120; index++) {
    if (child.exitCode !== null) throw Error(`Backend ${pc.port} exited ${child.exitCode}: ${diagnostic}`);
    try { if ((await http(pc, '/api/peer/v1/hello')).status === 200) {
      assert.equal((await http(pc, '/api/auth/local-session', 'POST', {})).status, 200);
      return;
    }} catch {}
    await sleep(500);
  }
  throw Error(`Backend ${pc.port} did not become ready: ${diagnostic}`);
}
async function stop(pc) {
  const child = processes.get(pc.port);
  if (!child) return;
  if (child.exitCode === null) {
    child.kill();
    await new Promise(resolve => child.once('exit', resolve));
  }
  processes.delete(pc.port); pc.cookie = '';
}
async function until(predicate, message, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const result = await predicate(); if (result) return result; await sleep(100); }
  throw Error(message);
}
async function transfer(pc, id) {
  return until(async () => { const row = (await op(pc,'transfers',{id})).transfers[0];
    if (row.status === 'failed') throw Error(row.error); return row.status === 'done' ? row : null; }, 'Transfer did not finish', 120000);
}
async function main() {
  await offlineSafety();
  if(process.argv.includes('--offline-only')) {
    fs.writeFileSync(path.join(scratch,'receipt.json'),JSON.stringify({at:new Date().toISOString(),checks},null,2));
    console.log(JSON.stringify({ok:true,checks:checks.length,receipt:path.join(scratch,'receipt.json')}));
    return;
  }
  const [A,B] = pcs;
  await Promise.all(pcs.map(start));
  record('two independent backends', {ports:pcs.map(pc=>pc.port), roots:pcs.map(pc=>pc.root)});
  fs.writeFileSync(path.join(B.root,'shared','readme.txt'),'Remote scoped text\n');
  const binary = crypto.randomBytes(17 * 1024 * 1024 + 123);
  fs.writeFileSync(path.join(B.root,'shared','payload.bin'),binary);
  fs.writeFileSync(path.join(A.root,'shared','send.bin'),binary);
  fs.mkdirSync(path.join(B.root,'shared','folder','nested'),{recursive:true});
  fs.writeFileSync(path.join(B.root,'shared','folder','nested','one.txt'),'folder one');
  fs.writeFileSync(path.join(B.root,'shared','folder','two.txt'),'folder two');
  const before = await http(A,'/api/ui/devices','POST',{op:'list'},{Cookie:''});
  assert.equal(before.status,401); record('owner session required',401);
  const pair = await op(A,'pair',{url:B.base,name:'PC B'});
  const request = (await op(B,'requests')).requests[0];
  assert.equal(pair.code,request.code);
  const stolen = await http(B,'/api/peer/v1/pair/status?request='+request.id);
  assert.equal(stolen.status,401); record('pair status blocks token theft',401);
  await op(B,'approve',{request:request.id,folders:[{path:path.join(B.root,'shared'),write:false}],inbox:path.join(B.root,'inbox'),writeAnywhere:false});
  const peerA = await until(async () => (await op(A,'list')).devices.find(row=>row.status==='paired'), 'Pair poll did not finish');
  const peerB = (await op(B,'list')).devices.find(row=>row.status==='paired');
  assert.ok(peerA.theyShare?.inbox); assert.ok(peerB.theyShare?.inbox);
  await op(A,'shares.set',{device:peerA.id,folders:[{path:path.join(A.root,'shared'),write:false}],inbox:path.join(A.root,'inbox'),writeAnywhere:false});
  record('owner-approved bidirectional pairing', {a:peerA.id,b:peerB.id,codeMatched:true});
  for (const pc of pcs) {
    const state = JSON.parse(fs.readFileSync(path.join(pc.root,'.neyvia','devices','peers.json')));
    const row = Object.values(state.peers)[0];
    assert.match(row.hash,/^[a-f0-9]{64}$/); assert.ok(row.outbound && row.outbound.length>100); assert.ok(!JSON.stringify(row).includes('Neyvia-Peer '));
  }
  record('hashed inbound and OS-encrypted outbound secrets', 'salted SHA-256 + Windows DPAPI, no raw tokens on disk');
  const listing = await op(A,'files.list',{device:peerA.id,path:path.join(B.root,'shared')});
  assert.ok(listing.entries.some(row=>row.name==='readme.txt')); assert.equal(listing.place.write,false);
  const read = await op(A,'files.read',{device:peerA.id,path:path.join(B.root,'shared','readme.txt'),offset:7,length:6});
  assert.equal(read.content,'scoped'); record('remote listing and ranged text read', {length:read.length,encoding:read.encoding});
  for(const args of [{offset:-1},{length:1024*1024+1}]) assert.equal((await http(A,'/api/ui/devices','POST',{op:'files.read',args:{device:peerA.id,path:path.join(B.root,'shared','readme.txt'),...args}})).status,400);
  record('negative and over-limit read ranges rejected',400);
  for (const rejected of [path.join(B.root,'unshared'), path.join(B.root,'shared','..','unshared'), 'C:\\Users\\user\\Projects\\Neyvia\\never-open', path.join(B.root,'.neyvia','devices','peers.json')]) {
    assert.equal((await http(A,'/api/ui/devices','POST',{op:'files.list',args:{device:peerA.id,path:rejected}})).status,403);
  }
  record('unshared/traversal/live/private paths rejected',403);
  try {
    fs.symlinkSync(path.join(B.root,'unshared'),path.join(B.root,'shared','escape'),'junction');
    assert.equal((await http(A,'/api/ui/devices','POST',{op:'files.list',args:{device:peerA.id,path:path.join(B.root,'shared','escape')}})).status,403);
    record('symlink/junction escape rejected',403);
  } catch(error) { if (error.code!=='EPERM') throw error; record('symlink fixture unavailable',{note:'Windows did not permit disposable junction'}); }
  const taken = await op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','payload.bin'),to:path.join(A.root,'taken'),wait:120});
  assert.equal(taken.transfer.status,'done'); assert.equal(sha(fs.readFileSync(taken.transfer.to)),sha(binary));
  const concurrent = await Promise.all([1,2].map(()=>op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','payload.bin'),to:path.join(A.root,'taken'),wait:120})));
  assert.equal(new Set([taken.transfer.to,...concurrent.map(row=>row.transfer.to)]).size,3);
  for(const row of concurrent) {assert.equal(row.transfer.status,'done');assert.equal(sha(fs.readFileSync(row.transfer.to)),sha(binary));}
  record('chunked Take and concurrent never overwrite',{bytes:binary.length,sha256:sha(binary)});
  const needApproval = await http(A,'/api/ui/tools/call','POST',{tool:'neyvia.devices.files.send',arguments:{device:peerA.id,from:path.join(A.root,'shared','send.bin')}});
  assert.equal(needApproval.data.data.result.status,'approval_required');
  record('model Send requires per-device owner approval','approval_required');
  const sent = await op(A,'files.send',{device:peerA.id,from:path.join(A.root,'shared','send.bin'),wait:120});
  assert.equal(sent.transfer.status,'done'); assert.equal(sha(fs.readFileSync(sent.transfer.to)),sha(binary));
  assert.equal((await http(A,'/api/ui/devices','POST',{op:'files.send',args:{device:peerA.id,from:path.join(A.root,'shared','send.bin'),to:path.join(B.root,'shared')}})).status,403);
  record('chunked Send, verified finish and inbox write boundary',{bytes:binary.length,sha256:sha(binary)});
  await op(B,'shares.set',{device:peerB.id,folders:[{path:path.join(B.root,'shared'),write:false}],inbox:path.join(B.root,'inbox'),writeAnywhere:true});
  const permitted=await op(A,'files.send',{device:peerA.id,from:path.join(A.root,'shared','send.bin'),to:path.join(B.root,'unshared'),wait:120});
  assert.equal(permitted.transfer.status,'done');assert.equal(sha(fs.readFileSync(permitted.transfer.to)),sha(binary));
  assert.equal((await http(A,'/api/ui/devices','POST',{op:'files.list',args:{device:peerA.id,path:path.join(B.root,'unshared')}})).status,403);
  await op(B,'shares.set',{device:peerB.id,folders:[{path:path.join(B.root,'shared'),write:false}],inbox:path.join(B.root,'inbox'),writeAnywhere:false});
  record('explicit writeAnywhere permits Send without granting unshared reads',true);
  const folder = await op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','folder'),to:path.join(A.root,'taken'),wait:120});
  assert.equal(folder.transfer.files.done,2); assert.equal(fs.readFileSync(path.join(folder.transfer.to,'nested','one.txt'),'utf8'),'folder one');
  record('recursive folder Take',folder.transfer.files);
  fs.writeFileSync(path.join(B.root,'shared','empty.txt'),'');
  const empty=await op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','empty.txt'),to:path.join(A.root,'taken'),wait:120});
  assert.equal(empty.transfer.status,'done');assert.equal(fs.statSync(empty.transfer.to).size,0);
  record('zero-byte Take publishes a verified empty file',true);
  const pending=await op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','payload.bin'),to:path.join(A.root,'taken')});
  assert.equal((await op(A,'transfer.pause',{id:pending.transfer.id})).transfer.status,'paused');
  await stop(A); await start(A);
  assert.equal((await op(A,'transfers',{id:pending.transfer.id})).transfers[0].status,'paused');
  await op(A,'transfer.resume',{id:pending.transfer.id});
  const resumedTake=await transfer(A,pending.transfer.id);assert.equal(sha(fs.readFileSync(resumedTake.to)),sha(binary));
  const cancelled=await op(A,'files.fetch',{device:peerA.id,from:path.join(B.root,'shared','payload.bin'),to:path.join(A.root,'taken')});
  await op(A,'transfer.pause',{id:cancelled.transfer.id});
  assert.equal((await op(A,'transfer.cancel',{id:cancelled.transfer.id})).transfer.status,'cancelled');
  assert.ok(!fs.existsSync(cancelled.transfer.to+'.neyvia-part'));
  record('UI pause, persisted restart/resume, and cancel removes partial',true);
  const native = await http(A,'/api/ui/tools/call','POST',{tool:'neyvia.devices.files.read',arguments:{device:peerA.id,path:path.join(B.root,'shared','readme.txt')}});
  assert.equal(native.data.data.ok,true); assert.equal(native.data.data.result.encoding,'utf-8');
  const mcp = await http(A,'/mcp','POST',{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'neyvia.devices.list',arguments:{}}});
  assert.ok(!mcp.data.error); assert.equal(mcp.data.result.isError,false);
  record('native tools and MCP same-state calls','neyvia.devices.files.read / neyvia.devices.list');
  // Protocol resume: interrupt after a verified chunk, restart receiving backend,
  // resume from the persisted offset, then prove corruption cannot publish.
  const outboundA = JSON.parse(fs.readFileSync(path.join(A.root,'.neyvia','devices','peers.json'))).peers[peerA.id].outbound;
  const token = await new Promise((resolve,reject)=>{
    const child=spawn(python,['-c',"import os; from grant_agent.neyvia_devices import _protect; print(_protect(os.environ['CROSS_PC_PROOF_BLOB'], True))"],
      {cwd:project,windowsHide:true,env:{...process.env,PYTHONPATH:path.join(project,'src'),CROSS_PC_PROOF_BLOB:outboundA}});
    let out=''; child.stdout.on('data',b=>out+=b); child.once('exit',code=>code?reject(Error('DPAPI protocol proof failed')):resolve(out.trim()));
  });
  const auth = {Authorization:'Neyvia-Peer '+token};
  const uploadId = crypto.randomBytes(16).toString('hex');
  const remotePath = path.join(B.root,'inbox','resume.bin');
  const first = binary.subarray(0,8*1024*1024);
  const put = (offset, data) => http(B,'/api/peer/v1/files/upload?'+new URLSearchParams({id:uploadId,path:remotePath,offset:String(offset),total:String(binary.length)}),'PUT',data,{...auth,'X-Neyvia-Chunk-Sha256':sha(data)});
  assert.equal((await put(0,first)).status,200);
  await stop(B); await start(B);
  const resumed = await http(B,'/api/peer/v1/files/upload?id='+uploadId,'GET',undefined,auth);
  assert.equal(resumed.data.received,first.length);
  let offset=first.length;
  while(offset<binary.length) {const data=binary.subarray(offset,offset+8*1024*1024); assert.equal((await put(offset,data)).status,200);offset+=data.length;}
  const finish=await http(B,'/api/peer/v1/files/upload/finish','POST',{id:uploadId,sha256:sha(binary)},auth);
  assert.equal(finish.status,200); assert.equal(sha(fs.readFileSync(finish.data.path)),sha(binary));
  record('upload resume after backend restart',{verifiedOffset:first.length,bytes:binary.length});
  const badId=crypto.randomBytes(16).toString('hex'),badPath=path.join(B.root,'inbox','bad.bin');
  assert.equal((await http(B,'/api/peer/v1/files/upload?'+new URLSearchParams({id:badId,path:badPath,offset:'0',total:'3'}),'PUT',Buffer.from('abc'),{...auth,'X-Neyvia-Chunk-Sha256':sha('abc')})).status,200);
  assert.equal((await http(B,'/api/peer/v1/files/upload/finish','POST',{id:badId,sha256:'0'.repeat(64)},auth)).status,409);
  assert.ok(!fs.existsSync(badPath+'.neyvia-part')); assert.equal((await http(B,'/api/peer/v1/files/upload?id='+badId,'GET',undefined,auth)).data.received,0);
  record('SHA mismatch drops partial and persisted upload state',409);
  await op(B,'revoke',{device:peerB.id});
  assert.equal((await http(B,'/api/peer/v1/files/list','POST',{},auth)).status,401);
  record('revoked token rejected after receiver restart',401);
  // Network gate proof with loopback allowance off is performed by receiver restart.
  const original=process.env.NEYVIA_PEER_ALLOW_LOOPBACK;
  await stop(B);
  const child=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(B.port),'--root',B.root,'--static-root',path.join(B.root,'static'),'--skip-runtime-auto-update'],
    {cwd:project,windowsHide:true,env:{...process.env,NEYVIA_PEER_ALLOW_LOOPBACK:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_TOOL_AUTO_UPDATE:'0'}});
  processes.set(B.port,child); child.stdout.resume(); child.stderr.resume();
  await until(async()=>{try{return(await http(B,'/api/peer/v1/hello')).status===403;}catch{return false;}},'Network gate backend did not start');
  record('peer API rejects ordinary loopback without dev allowance',403);
  const receipt={at:new Date().toISOString(),scratch,ports:pcs.map(pc=>pc.port),checks,claim:'two local PCs only; tailnet deployment and rendered Claude UI are separate'};
  fs.writeFileSync(path.join(scratch,'receipt.json'),JSON.stringify(receipt,null,2));
  console.log(JSON.stringify({ok:true,checks:checks.length,receipt:path.join(scratch,'receipt.json')}));
}
async function offlineSafety() {
  const code = String.raw`
import os, hashlib, json, secrets
from pathlib import Path
from grant_agent.neyvia_devices import Devices, PeerError, _digest, _protect, _unique, network_allowed, _url, _verified_part, call_devices
root=Path(os.environ['CROSS_PC_OFFLINE_ROOT']); root.mkdir(parents=True,exist_ok=True)
shared=root/'shared'; shared.mkdir(exist_ok=True); inbox=root/'inbox'; inbox.mkdir(exist_ok=True)
service=Devices(root)
secret=secrets.token_urlsafe(40); pair='pair'; salt=secrets.token_hex(16)
peer={'id':'existing','name':'Original','url':'http://127.0.0.1:47929','status':'paired','pairId':pair,'salt':salt,'hash':_digest(secret,salt),
      'outbound':_protect(pair+'.'+secret),'iShare':{'folders':[{'path':str(shared),'write':False}],'inbox':str(inbox),'writeAnywhere':False}}
with service.state() as state: state['peers']['existing']=peer
token='Neyvia-Peer '+pair+'.'+secret
assert service.auth(token)['name']=='Original'
try: service.auth(pair+'.'+secret); raise AssertionError('bare capability accepted')
except PeerError as e: assert e.status==401
os.environ['NEYVIA_PEER_ALLOW_LOOPBACK']='1'
request=service.incoming({'fromId':'existing','fromName':'Impostor','fromUrl':'http://127.0.0.1:47919','code':'1234','token':'new.'+secrets.token_urlsafe(40)},'127.0.0.1')['request']
assert service.auth(token)['name']=='Original'
call_devices(root,'deny',{'request':request['id']},source='ui')
assert service.auth(token)['name']=='Original'
for path in [root/'outside', shared/'..'/'outside','C:/Users/user/Projects/Neyvia/never-open',root/'.neyvia/devices/peers.json']:
    try: service.scoped(peer,str(path)); raise AssertionError('unshared path accepted')
    except PeerError as e: assert e.status==403
try: service.scoped(peer,str(shared/'write.txt'),True); raise AssertionError('read-only write accepted')
except PeerError as e: assert e.status==403
assert service.scoped(peer,str(inbox/'write.txt'),True)==inbox/'write.txt'
for address in ['192.0.2.10','192.0.2.10','fd7a:115c:a1e0::2']: assert network_allowed(address,{})
for address in ['8.8.8.8','192.168.1.2','100.128.0.1','invalid']: assert not network_allowed(address,{})
os.environ['NEYVIA_PEER_ALLOW_LOOPBACK']='0'
assert not network_allowed('127.0.0.1',{})
assert network_allowed('127.0.0.1',{'Tailscale-User-Login':'owner'})
target=root/'partial.bin'; part=target.with_name(target.name+'.neyvia-part'); part.write_bytes(b'abcBAD')
row={'chunks':[{'length':3,'sha256':hashlib.sha256(b'abc').hexdigest()},{'length':3,'sha256':hashlib.sha256(b'def').hexdigest()}]}
assert _verified_part(target,row)==3 and part.read_bytes()==b'abc' and len(row['chunks'])==1
target.write_bytes(b'keeper'); assert _unique(target).name=='partial (2).bin'
service.revoke('existing',False)
try: service.auth(token); raise AssertionError('revoked capability accepted')
except PeerError as e: assert e.status==401
stored=(service.folder/'peers.json').read_text(); assert secret not in stored
print('scoped guards, network ranges, corrupt chunk rewind, non-overwrite, authenticated tokens, re-pair preservation, revoke')
`;
  await new Promise((resolve,reject)=>{
    const child=spawn(python,['-c',code],{cwd:project,windowsHide:true,env:{...process.env,PYTHONPATH:path.join(project,'src'),CROSS_PC_OFFLINE_ROOT:path.join(scratch,'offline')}});
    let out='',err='';child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);
    child.once('exit',status=>status?reject(Error(err)):resolve(record('offline security invariants',out.trim())));
  });
}
main().catch(error=>{console.error(error.stack);fs.writeFileSync(path.join(scratch,'failure.json'),JSON.stringify({at:new Date().toISOString(),error:String(error),checks},null,2));process.exitCode=1;})
  .finally(async()=>{if(!process.argv.includes('--keep-running'))await Promise.all(pcs.map(stop));});
