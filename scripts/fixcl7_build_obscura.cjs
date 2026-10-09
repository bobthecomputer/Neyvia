/* Task-local offline build of the actual iframe renderer patch. Existing local
 * compiler/V8 assets are read; all source, Cargo cache and outputs stay here. */
const fs = require('fs'), path = require('path'), cp = require('child_process'), crypto = require('crypto');
const repo = path.resolve(__dirname, '..'), task = path.join(repo, '.agent_control/fixcl7');
const donor = 'C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f';
const source = path.join(task, 'obscura-source');
const toolchain = 'C:/Users/user/.rustup/toolchains/1.91.0-x86_64-pc-windows-msvc/bin';
const vc = 'C:/Program Files/Microsoft Visual Studio/18/Insiders/VC/Tools/MSVC/14.50.35503';
const sdk = 'C:/Program Files (x86)/Windows Kits/10', version = '10.0.26100.0';
const cmake = 'C:/Program Files/Microsoft Visual Studio/18/Insiders/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin';
const env = {...process.env, CARGO_HOME:path.join(task,'cargo-home'), CARGO_TARGET_DIR:path.join(task,'obscura-target'),
  CARGO_NET_OFFLINE:'true', RUSTC:path.join(toolchain,'rustc.exe'),
  RUSTY_V8_ARCHIVE:path.join(donor,'v8-v150.4.0/rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz'),
  RUSTY_V8_SRC_BINDING_PATH:path.join(donor,'v8-v150.4.0/src_binding_simdutf_release_x86_64-pc-windows-msvc.rs'),
  LIBCLANG_PATH:path.join(donor,'libclang18/extracted/libclang-18.1.1.data/platlib/clang/native'),
  HTTP_PROXY:'http://127.0.0.1:48789', HTTPS_PROXY:'http://127.0.0.1:48789', ALL_PROXY:'http://127.0.0.1:48789',
  PATH:[toolchain,vc+'/bin/Hostx64/x64',sdk+'/bin/'+version+'/x64',cmake,process.env.PATH].join(';'),
  INCLUDE:[vc+'/include',sdk+'/Include/'+version+'/ucrt',sdk+'/Include/'+version+'/shared',sdk+'/Include/'+version+'/um',sdk+'/Include/'+version+'/winrt'].join(';'),
  LIB:[vc+'/lib/x64',sdk+'/Lib/'+version+'/ucrt/x64',sdk+'/Lib/'+version+'/um/x64'].join(';'),
  CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER:vc+'/bin/Hostx64/x64/link.exe',
  VCToolsInstallDir:vc+'/', WindowsSdkDir:sdk+'/', WindowsSDKVersion:version+'/'};
const receipt = path.join(repo,'scripts/evidence/FIXCL7-renderer-build.json');
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const inputs = ['crates/obscura-js/src/ops.rs','crates/obscura-js/src/runtime.rs','crates/obscura-render/src/paint.rs','Cargo.lock']
  .map(name => ({path:name,sha256:sha(path.join(source,name))}));
const log = path.join(task,'renderer-build.log'), fd = fs.openSync(log,'w');
const args = ['build','--offline','--locked','--release','-p','obscura-cli','--features','render','-j2'];
const report = {schema:'neyvia.FIXCL7.renderer-build.v1',source,inputs,command:['cargo',...args],offline:true,stealth:false,startedAt:new Date().toISOString(),log};
const save = () => fs.writeFileSync(receipt,JSON.stringify(report,null,2)+'\n');
const child = cp.spawn(path.join(toolchain,'cargo.exe'),args,{cwd:source,env,windowsHide:true,stdio:['ignore',fd,fd]});
fs.closeSync(fd); report.pid=child.pid; save();
child.on('error', error => {report.error=error.message;save();process.exitCode=1});
child.on('exit', code => {report.exitCode=code;report.finishedAt=new Date().toISOString();
  if(code===0)report.artifacts=['obscura.exe','obscura-worker.exe'].map(name => {const file=path.join(task,'obscura-target/release',name);return {path:file,sha256:sha(file),bytes:fs.statSync(file).size};});
  save();console.log(JSON.stringify({exitCode:code,receipt}));process.exitCode=code||0;});
