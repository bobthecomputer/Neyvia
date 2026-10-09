/* Positional CLI to the owned task coordinator, never a second browser engine. */
const [port,op,id,...rest]=process.argv.slice(2);
if(!/^4872[1-6]$/.test(port))throw Error('Explicit owned coordinator port required');
const body=op==='json'?JSON.parse(require('node:fs').readFileSync(id,'utf8')):{op,id,...(rest[0]?JSON.parse(rest.join(' ')):{})};
fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)}).then(async r=>{console.log(JSON.stringify(await r.json()));if(!r.ok)process.exitCode=1;}).catch(e=>{console.error(e);process.exitCode=1;});
