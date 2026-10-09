# Blender 4+ native bridge

Install the `neyvia_bridge` directory as a local legacy add-on (zip that directory if the Blender Install dialog requires an archive); enable **Neyvia Game Dev Bridge**. Run Neyvia Game Dev setup for your project. In Scene properties → Neyvia bridge, choose that project directory and click **Connect Neyvia bridge**. The add-on reads its private `.neyvia/gamedev-bridge.json`; keep the token/config out of source control. Uses literal `http://127.0.0.1:48261` with proxies disabled.

Networking runs in a background thread. Only a `bpy.app.timers` main-thread callback touches scenes/operators; render can occupy Blender until the native render finishes. This bridge registers context **Edit** with capabilities based on its real implementation.

| Action | Arguments | Observable result |
| --- | --- | --- |
| inspect | `{}` | Actual scene, camera, frame, names/types/transforms/selection |
| select | `{object:"Cube"}` | Native selected/active object |
| edit | `{object:"Cube",location:[1,2,3],rotation:[0,0,0],scale:[1,1,1]}` | Readback transforms; radians; omitted transforms retained |
| render | `{path:"exports/view.png",camera:"Camera"}` | Native still render, actual file bytes/camera/frame/resolution; restores render settings |
| export | `{path:"exports/model.glb",selectedOnly:false}` | Native glTF export, actual output file size; `.gltf` exports separate buffers |
| load_asset | `{path:"exports/model.glb"}` | Native glTF import and newly created object names |

All file outputs/inputs must resolve inside the selected project; symlink/traversal escapes are refused. Render and export use the existing scene/camera/settings; no placeholder image or asset is produced. Asset validation and subsequent Unity/Roblox/Godot engine-load are distinct backend actions and separate receipts. Scene edits remain native unsaved changes; save the blend explicitly in Blender. Re-enable the add-on after a backend restart to establish a fresh session; uncertain completions never replay the scene operation.

No Blender host was found on PATH, standard Program Files locations, project-root names, or Downloads filenames during this task. Python syntax was compiled only; real Blender inspect/edit/render/export/import remains **Needs Paul**.

API references: [Application timers](https://docs.blender.org/api/5.0/bpy.app.timers.html), [glTF export operator](https://docs.blender.org/api/main/bpy.ops.export_scene.html).
