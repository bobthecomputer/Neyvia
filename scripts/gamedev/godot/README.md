# Godot 4 native bridge

Copy `addons/neyvia_bridge` into your Godot project, run Neyvia Game Dev setup for that exact project to create `.neyvia/gamedev-bridge.json`, then enable **Neyvia Game Dev Bridge** in Project Settings → Plugins. Keep the private config out of source control. Uses only `ws://127.0.0.1:48263`. No third-party package or executable is installed.

Enabling the plugin adds a `NeyviaGameBridge` autoload; disabling removes it. The editor registers context **Edit**. Running the project's main scene starts a separate **Play** session. Select that exact session for runtime inspection and interaction. A launch receipt means launch was requested; the Play session and observed state prove the game actually runs.

Editor actions:

| Action | Arguments | Result |
| --- | --- | --- |
| inspect | `{}` | Scene path, actual node tree/transforms, playing state |
| select | `{node:"Character"}` | Native editor selection; node is relative to edited root |
| edit | `{node:"Character",property:"position",value:[1,2,3]}` | Undoable native transform (rotation in radians), scale or boolean visibility; scene is dirty |
| validate | `{path:"res://character.gd"}` | Godot GDScript reload/compile result, not a simulated validator |
| run | `{}` | Calls editor play_main_scene; select subsequent Play session |
| stop | `{}` | Calls editor stop_playing_scene; returns observed playing state |
| load_asset | `{path:"res://exports/model.glb"}` | Instantiates a glTF already imported by Godot; explicit failure while import is unavailable |

Runtime actions: `inspect {}` returns the actual running node tree, positions, process-frame count, and optional `neyvia_inspect()` game state. `interact {node:"Character",input:{...}}` calls only the target's explicitly provided `neyvia_interact(input)` method, which must return a Dictionary. Missing method fails visibly. `stop {}` sends a quit request; use editor `stop` or session expiry to confirm exit.

An example game-owned seam (attach to your existing gameplay node and invoke its real gameplay behavior):

```gdscript
func neyvia_interact(input: Dictionary) -> Dictionary:
    if input.get("action") != "jump":
        return {"accepted": false, "reason": "Unknown action"}
    jump() # your game's real existing action
    return {"accepted": true, "velocity": [velocity.x, velocity.y, velocity.z]}

func neyvia_inspect() -> Dictionary:
    return {"grounded": is_on_floor(), "velocity": [velocity.x, velocity.y, velocity.z]}
```

This bridge never injects arbitrary script/eval or claims a node edit proves gameplay. A game must provide its interaction seam for its own mechanics. No Godot executable was found on PATH, standard Program Files locations, project-root names, or Downloads filenames during this task: native compilation/run/interaction remains **Needs Paul**. Disable/re-enable the plugin after backend restart; failed connection does not silently replay actions.

API references: [EditorInterface](https://docs.godotengine.org/en/4.5/classes/class_editorinterface.html), [EditorUndoRedoManager](https://docs.godotengine.org/en/stable/classes/class_editorundoredomanager.html), [Script.reload](https://docs.godotengine.org/en/4.5/classes/class_script.html).
