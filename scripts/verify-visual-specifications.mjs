#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import process from "node:process";
const root = new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:");
const code = String.raw`
import json, tempfile
from pathlib import Path
from PIL import Image
from grant_agent.visual_specifications import VisualSpecification, VisualSpecificationRegistry, composite_region, inspect_image
with tempfile.TemporaryDirectory() as d:
    root=Path(d); source=root/'source.png'; edit=root/'edit.png'; out=root/'out.png'
    Image.new('RGBA',(6,6),(10,20,30,255)).save(source)
    patch=Image.new('RGBA',(6,6),(10,20,30,255)); patch.putpixel((2,2),(240,0,0,255)); patch.save(edit)
    spec=VisualSpecification('visual-1','proposal',text_references=['hero title'],protected_regions=[{'x':2,'y':2,'width':1,'height':1}],region_intent={'hero':'accent'})
    spec.add_asset(source,label='source')
    registry=VisualSpecificationRegistry(root/'visual.json'); registry.register(spec)
    result=composite_region(source,edit,out,{'x':2,'y':2,'width':1,'height':1})
    assert result['outsideProtectedPixelsUnchanged'] and inspect_image(out)['dimensions']=={'width':6,'height':6}
    try: composite_region(source,edit,out,{'x':6,'y':6,'width':1,'height':1})
    except ValueError: pass
    else: raise AssertionError('invalid region accepted')
    loaded=VisualSpecificationRegistry(root/'visual.json').get('visual-1'); assert loaded and loaded.assets[0]['sha256']==inspect_image(source)['sha256']
print(json.dumps({'passed':True,'checks':['roles','real-hash-dimensions-alpha','protected-pixels','invalid-region','persistent-provenance']}))
`;
const result = spawnSync(process.env.PYTHON || "python", ["-c", code], {cwd: root, encoding: "utf8", env: {...process.env, PYTHONPATH: `${root}/src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""}`}});
if (result.status !== 0) { process.stderr.write(result.stderr || result.stdout || "visual specification verification failed\n"); process.exit(result.status || 1); }
process.stdout.write(result.stdout);
