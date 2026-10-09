/* Explicit-port operator; JSON uses base64 transport to avoid shell escaping. */
const [port,operation,...args]=process.argv.slice(2);
if(!/^4872[1-9]$/.test(port))throw Error('Explicit owned coordinator port required');
const body=operation==='json64'?JSON.parse(Buffer.from(args[0],'base64').toString('utf8')):{op:operation,id:args[0]};
fetch(`http://127.0.0.1:${port}/command`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)}).then(async r=>{
 const value=await r.json(),obs=value.observation||value;
 if(obs.elements){const re=process.env.C2D_RE?new RegExp(process.env.C2D_RE,'i'):null;obs.elements=obs.elements.filter(e=>(!process.env.C2D_ACTIONS||e.actions?.some(a=>a!=='scroll'))&&(!re||re.test([e.name,e.role,e.inputName,e.placeholder,e.type].join(' ')))).slice(0,Number(process.env.C2D_CONTROLS||100));obs.text=obs.text.slice(0,Number(process.env.C2D_TEXT||9000));}
 if(value.cl)value.cl=value.cl.slice(0,500);
 if(value.controls)value.controls=value.controls.slice(0,Number(process.env.C2D_CONTROLS||10));
 console.log(JSON.stringify(value));if(!r.ok)process.exitCode=1;
}).catch(e=>{console.error(e);process.exitCode=1;});
