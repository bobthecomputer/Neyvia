import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const result=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,time,tempfile
from pathlib import Path
from PIL import Image,ImageChops
from grant_agent.visual_specifications import composite_region
with tempfile.TemporaryDirectory() as folder:
 p=Path(folder);size=(1024,1024);box=(400,400,600,600)
 base=Image.new('RGBA',size,(20,30,40,255));edit=Image.new('RGBA',size,(60,70,80,255))
 base.save(p/'base.png');edit.save(p/'edit.png')
 start=time.perf_counter();receipt=composite_region(p/'base.png',p/'edit.png',p/'result.png',{'x':400,'y':400,'width':200,'height':200});whole_ms=(time.perf_counter()-start)*1000
 checked=Image.open(p/'result.png').convert('RGBA')
 start=time.perf_counter();legacy=any(base.getpixel((x,y))!=checked.getpixel((x,y)) for y in range(base.height) for x in range(base.width) if not(box[0]<=x<box[2] and box[1]<=y<box[3]));legacy_ms=(time.perf_counter()-start)*1000
 start=time.perf_counter();diff=ImageChops.difference(base,checked);diff.paste((0,0,0,0),box);current=diff.getbbox(alpha_only=False) is not None;current_ms=(time.perf_counter()-start)*1000
 checked.putpixel((1,1),(21,30,40,255));rgb=ImageChops.difference(base,checked);rgb.paste((0,0,0,0),box)
 checked.putpixel((2,2),(20,30,40,0));alpha=ImageChops.difference(base,checked);alpha.paste((0,0,0,0),box)
 print(json.dumps({'checks':{'sameVerdict':legacy==current==False,'protectedPixels':receipt['outsideProtectedPixelsUnchanged'],'rgbCorruptionDetected':rgb.getbbox(alpha_only=False) is not None,'alphaCorruptionDetected':alpha.getbbox(alpha_only=False) is not None},'measurement':{'imageSize':size,'legacyCompareMs':legacy_ms,'currentCompareMs':current_ms,'productionReadCompositeSaveVerifyMs':whole_ms},'boundary':'Same decoded 1024x1024 fixture; comparison timing is not model generation latency.'}))
`],{env:{...process.env,PYTHONPATH:'src'},encoding:'utf8',timeout:30000});
assert.equal(result.status,0,result.stderr||result.stdout);
const report=JSON.parse(result.stdout); for(const [key,value] of Object.entries(report.checks))assert.equal(value,true,key);
console.log(JSON.stringify(report,null,2));
