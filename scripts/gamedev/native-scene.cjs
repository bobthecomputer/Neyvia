// Native semantic harness, explicitly Babylon NullEngine (no WebGL/UI claim).
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), crypto = require('node:crypto');
const B = require('./vendor/babylon.js');
globalThis.BABYLON = B;
for (const file of ['babylonjs.loaders.min.js','babylonjs.serializers.min.js']) {
  vm.runInThisContext('(function(exports,module,define){'+fs.readFileSync(path.join(__dirname,'vendor',file),'utf8')+'})(undefined,undefined,undefined);', {filename:file});
}
const NeyviaScene = require('./scene-runtime.js');
const project = fs.realpathSync(process.argv[2]);
const config = JSON.parse(fs.readFileSync(path.join(project,'.neyvia/gamedev-bridge.json'),'utf8'));
if (config.httpUrl !== 'http://127.0.0.1:48261') throw Error('T12 harness requires owned backend 48261');
const scenePath = path.join(project,'.neyvia/scene.babylon');
let websocket;
const useWebSocket = process.argv.includes('--websocket');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function safe(value) {
  if (typeof value !== 'string' || !value) throw Error('Select an output path');
  const target=path.resolve(project,value);
  if (!target.startsWith(project + path.sep)) throw Error('Path outside project');
  let parent=path.dirname(target);
  while(!fs.existsSync(parent)) parent=path.dirname(parent);
  if(!fs.realpathSync(parent).startsWith(project)) throw Error('Linked parent outside project');
  return target;
}
function write(target, data, expected) {
  if (fs.existsSync(target) && hash(fs.readFileSync(target)) !== expected) throw Error('Existing file hash changed or expectedSha256 missing');
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,data);
  return {path:target,sha256:hash(data),bytes:Buffer.byteLength(data)};
}
const engine=new B.NullEngine({renderWidth:640,renderHeight:480,textureSize:512});
const runtime=new NeyviaScene(B,engine,{
  headless:true,
  beforeMutate:async expected=>{if(fs.existsSync(scenePath)&&hash(fs.readFileSync(scenePath))!==expected)throw Error('Persisted scene changed; reload before editing');},
  persist:async(data,expected)=>write(scenePath,data,expected),
  exportAsset:async(target,bytes,expected)=>write(safe(target),Buffer.from(bytes),expected),
  loadAsset:async(target,scene)=>B.SceneLoader.ImportMeshAsync('', '', new Uint8Array(fs.readFileSync(safe(target))), scene, null, '.glb'),
});
async function post(op,payload){let answer;if(useWebSocket){answer=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{websocket.removeEventListener('message',receive);reject(Error('WebSocket response deadline'));},5000);const receive=event=>{clearTimeout(timer);resolve(JSON.parse(event.data));};websocket.addEventListener('message',receive,{once:true});websocket.send(JSON.stringify({op,token:config.token,...payload}));});}else{const response=await fetch(config.httpUrl+'/api/gamedev/bridge/'+op,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+config.token},body:JSON.stringify(payload)});answer=await response.json();}if(!answer.ok)throw Error(answer.error);return answer.data;}
async function main(){
  if(useWebSocket){websocket=new WebSocket(config.websocketUrl);await new Promise((resolve,reject)=>{websocket.addEventListener('open',resolve,{once:true});websocket.addEventListener('error',reject,{once:true});});}
  if(fs.existsSync(scenePath)){
    const saved=fs.readFileSync(scenePath);
    const restored=await B.SceneLoader.LoadAsync('', 'data:'+saved.toString('utf8'),engine);
    runtime.scene.dispose();runtime.scene=restored;
    runtime.camera=restored.activeCamera;
    runtime.revision=restored.metadata?.neyviaRevision || 0;
    runtime.savedHash=hash(saved);
    runtime.scene.onBeforeRenderObservable.add(()=>{if(runtime.running)for(const mesh of runtime.scene.meshes)if(mesh.metadata?.spin)mesh.rotation.y+=.015;});
  }
  const {sessionId}=await post('register',{engine:'babylon',projectPath:project,context:'Edit',environment:useWebSocket?'headless-native-proof-ws':'headless-native-proof',capabilities:['inspect','select','edit','run','interact','console','stop','test','export','load_asset']});
  console.log(JSON.stringify({sessionId,nativeEngine:'Babylon NullEngine',project}));
  const renderTimer=setInterval(()=>runtime.scene.render(),20);
  const halt=()=>{clearInterval(renderTimer);runtime.scene.dispose();engine.dispose();process.exit(0);};
  process.on('SIGTERM',halt);process.on('SIGINT',halt);
  for(;;){
    try{
      const {request}=await post('poll',{sessionId});
      if(request){let result={},error='',status='succeeded';try{result=await runtime.dispatch(request.action,request.args);}catch(e){status='failed';error=e.message;runtime.logs.push({level:'error',message:error});}
        await post('complete',{sessionId,requestId:request.requestId,status,result,error});}
    }catch(e){console.error(String(e));}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
