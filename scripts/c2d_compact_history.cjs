/* Losslessly compress own untracked historical receipts; keep live citations. */
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const dir='scripts/evidence',tracked=new Set(execFileSync('git',['ls-files','--',dir+'/C2d*'],{encoding:'utf8',maxBuffer:1000000}).trim().split(/\r?\n/));
const sha=b=>crypto.createHash('sha256').update(b).digest('hex'),archives=[];
for(const name of fs.readdirSync(dir)){
 if(!/^C2d-(?:native-receipt-proof-source-before|native-pointer-fixture|webvoyager-final\.json\.before-resume|site-proof-source-before).*\.json$/.test(name))continue;
 const file=dir+'/'+name;if(tracked.has(file)||fs.statSync(file).size<500000)continue;
 const bytes=fs.readFileSync(file),output=file+'.gz';assert(!fs.existsSync(output));
 const gzip=zlib.gzipSync(bytes,{level:9});fs.writeFileSync(output,gzip);assert.equal(sha(zlib.gunzipSync(fs.readFileSync(output))),sha(bytes));
 archives.push({originalPath:file,originalSha256:sha(bytes),originalBytes:bytes.length,path:output,sha256:sha(gzip),bytes:gzip.length});
 fs.unlinkSync(file); // Exact original bytes remain recoverable from verified gzip.
}
const receipt={schema:'neyvia.C2d.history-archives@1',at:new Date().toISOString(),method:'Verified lossless gzip of own untracked historical copies only; current run, all cited observations and tracked files preserved',archives};
fs.writeFileSync(dir+'/C2d-history-archives.json',JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify({archives:archives.length,rawBytes:archives.reduce((n,a)=>n+a.originalBytes,0),gzipBytes:archives.reduce((n,a)=>n+a.bytes,0)}));
