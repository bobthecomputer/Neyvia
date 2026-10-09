"""Outcome contract for the local game asset export and import boundary."""
from __future__ import annotations

import json
import subprocess
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

CONTRACT = "gamedev.export-validation-journey"
CONTRACTS = (CONTRACT,)
REPOSITORY = Path(__file__).resolve().parents[2]

_BABYLON_JOURNEY = r"""
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const dir=process.argv[1],B=require('./scripts/gamedev/vendor/babylon.js');globalThis.BABYLON=B;
for(const file of ['babylonjs.loaders.min.js','babylonjs.serializers.min.js'])
  vm.runInThisContext('(function(exports,module,define){'+fs.readFileSync('./scripts/gamedev/vendor/'+file,'utf8')+'})(undefined,undefined,undefined);',{filename:file});
const Scene=require('./scripts/gamedev/scene-runtime.js'),state=path.join(dir,'.neyvia','scene.babylon');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),inside=p=>path.resolve(p).startsWith(path.resolve(dir)+path.sep);
const write=(p,b,expected)=>{if(!inside(p))throw Error('outside project');if(fs.existsSync(p)&&(!expected||hash(fs.readFileSync(p))!==expected))throw Error('stale artifact');fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,b);return{sha256:hash(b)}};
const engine=new B.NullEngine({renderWidth:128,renderHeight:128});
const runtime=new Scene(B,engine,{headless:true,
  beforeMutate:async expected=>{if(fs.existsSync(state)&&hash(fs.readFileSync(state))!==expected)throw Error('stale scene');},
  persist:async(data,expected)=>write(state,Buffer.from(data),expected),
  exportAsset:async(p,b,expected)=>write(path.resolve(dir,p),b,expected)});
(async()=>{
  await runtime.dispatch('edit',{op:'create',name:'RoomCube',position:[1,2,3]});
  const created=runtime.observe().meshes.find(m=>m.name==='RoomCube');if(!created||created.vertices!==24)throw Error('native mesh geometry was not created');
  const savedBeforeRefusal=fs.readFileSync(state);
  try{await runtime.dispatch('edit',{op:'create',name:'WrongShape',shape:'capsule'});throw Error('unsupported scene primitive was accepted');}
  catch(error){if(!String(error).includes('Unsupported primitive'))throw error;}
  if(runtime.revision!==1||runtime.observe().meshes.some(m=>m.name==='WrongShape')||!fs.readFileSync(state).equals(savedBeforeRefusal))throw Error('refused edit changed the live or saved scene');
  await runtime.dispatch('edit',{op:'transform',name:'RoomCube',position:[4,5,6],expectedRevision:1});
  const restored=await B.SceneLoader.LoadAsync('','data:'+fs.readFileSync(state,'utf8'),engine);runtime.scene.dispose();runtime.scene=restored;
  const reopened=runtime.observe().meshes.find(m=>m.name==='RoomCube');
  if(!reopened||JSON.stringify(reopened.position)!=='[4,5,6]'||restored.metadata.neyviaRevision!==2)throw Error('saved scene did not reopen with its edit and revision');
  const test=await runtime.dispatch('test',{name:'RoomCube',position:[4,5,6],minVertices:24});
  if(!test.passed||test.checks.some(c=>!c.passed))throw Error('native scene behavior check failed');
  const exported=await runtime.dispatch('export',{path:'exports/room.glb'});engine.dispose();
  console.log(JSON.stringify({exportPath:'exports/room.glb',exportSha256:exported.sha256,vertices:reopened.vertices,
    position:reopened.position,revision:runtime.revision,sceneChecks:test.checks,wrongShapeRefused:true,savedEditReopened:true}));
})().catch(error=>{console.error(String(error));engine.dispose();process.exitCode=1;});
"""


def export_validation_journey(root: str | Path) -> dict:
    """Use the production game-dev command to validate and refuse local exports."""
    from .neyvia_gamedev import handle_command
    from .subprocess_utils import hidden_windows_subprocess_kwargs

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / "project"
    workspace.mkdir(exist_ok=True)
    invalid_path = workspace / "broken-scene.gltf"
    invalid_path.write_text(json.dumps({
        "asset": {"version": "2.0"},
        "scene": 7,
        "scenes": [],
        "nodes": [],
    }), encoding="utf-8")

    # Babylon NullEngine drives the production scene runtime without a browser,
    # editor, or backend port. It emits a real project scene file and glTF export.
    scene_process = subprocess.run(
        ["node", "-e", _BABYLON_JOURNEY, str(workspace)], cwd=REPOSITORY,
        capture_output=True, text=True, timeout=12, check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if scene_process.returncode:
        raise RuntimeError(f"Babylon scene journey failed: {scene_process.stderr[-1200:]}")
    scene = json.loads(scene_process.stdout.strip().splitlines()[-1])
    if (scene.get("vertices") != 24 or scene.get("position") != [4, 5, 6]
            or scene.get("revision") != 2 or scene.get("wrongShapeRefused") is not True
            or scene.get("savedEditReopened") is not True
            or not all(check.get("passed") for check in scene.get("sceneChecks", []))):
        raise AssertionError(f"Native scene journey did not preserve the edited mesh: {scene!r}")

    # Match the real task-selected workspace for this isolated command call.
    with patch.dict(os.environ, {"NEYVIA_GAMEDEV_WORKSPACE": str(workspace)}):
        valid = handle_command(root, "gamedev_asset_validate_command", {"path": scene["exportPath"]})
        if (valid.get("valid") is not True or valid.get("validator") != "Khronos glTF Validator"
                or valid.get("summary", {}).get("version") != "2.0"
                or valid.get("summary", {}).get("hasDefaultScene") is not True
                or valid.get("errors")):
            raise AssertionError(f"Valid scene export did not pass with its semantic summary: {valid!r}")

        invalid = handle_command(root, "gamedev_asset_validate_command", {"path": "broken-scene.gltf"})
        error_codes = {row.get("code") for row in invalid.get("errors", [])}
        if (invalid.get("valid") is not False or invalid.get("issueCounts", {}).get("numErrors", 0) < 1
                or "UNRESOLVED_REFERENCE" not in error_codes or invalid.get("summary", {}).get("hasDefaultScene") is not False):
            raise AssertionError(f"Broken scene export was not diagnosed before engine import: {invalid!r}")

        outside = root / "outside.gltf"
        outside.write_text(json.dumps({"asset": {"version": "2.0"}}), encoding="utf-8")
        try:
            handle_command(root, "gamedev_asset_validate_command", {"path": str(outside)})
        except ValueError as error:
            if "inside the selected workspace" not in str(error):
                raise
        else:
            raise AssertionError("An export outside the selected workspace was accepted")

    return {
        "scene": scene,
        "valid": {"validator": valid["validator"], "version": valid["summary"]["version"],
                  "hasDefaultScene": valid["summary"]["hasDefaultScene"],
                  "errorCount": valid["issueCounts"]["numErrors"]},
        "invalid": {"valid": invalid["valid"], "errorCount": invalid["issueCounts"]["numErrors"],
                    "errorCodes": sorted(error_codes), "hasDefaultScene": invalid["summary"]["hasDefaultScene"]},
        "outsideWorkspaceRefused": True,
    }


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            # Keep temporary authored exports under the caller's task-local SSD root.
            with tempfile.TemporaryDirectory(prefix="export-", dir=scratch) as folder:
                observed = export_validation_journey(Path(folder))
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
