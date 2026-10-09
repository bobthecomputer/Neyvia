# Roblox Studio bridge

Setup replaces `__NEYVIA_CONFIG_JSON__` with project-local JSON and writes a Lua
script. Save it as a **local plugin** in Studio. Grant this plugin localhost HTTP
and script editing permissions when Studio asks. Never publish the token-bearing
generated plugin. Keep the selected project path and place paired; plugins cannot
read the `.rbxl` filesystem path, so setup supplies project affinity.

Each loaded plugin has a fresh `studio_id`. Context comes from `RunService` and
registration changes when the data model changes. A plugin runs only in the data
models Studio actually instantiates it in; missing Client/Server sessions remain
unavailable. This bridge does not manufacture contexts or route into another one.

Typed arguments: `inspect {path?,depth?}`, `select {path}`, `console {}`,
`edit {path,property,value}` or `edit {path,source,expectedSource}`,
`run {mode:"simulation"}` or `run {mode:"play",testArgs?:...}`,
`stop {mode:"play",result?:...}` in the exact **Server** context, or
`stop {preserveChanges:true}` for simulation. Paths use
`game/Workspace/Part`, and duplicate sibling names are rejected. Vector values use
`{type:"Vector3",x,y,z}`; colors use `{type:"Color3",r,g,b}`.

Current Studio's `StudioTestService.ExecutePlayModeAsync` starts a real solo
player test. The launch receipt observes `EditModeActive == false`; it still
requires actual Client/Server sessions for inspection and interaction. Stop via
`EndTest` on the Server; inspect the Edit session's `playResult` to confirm it
ended. Old editors without this API fail visibly. Plugins run only in contexts
actually provided by Studio, so absent Server/Client sessions need native Studio
controls and are never fabricated. `RunService.Run` starts simulation. `RunService.Stop` preserves
physics/script changes, unlike Studio's Stop button; explicit consent in args is
required. Use Studio Stop for restoration. Script updates compare the current
editor source before writing; no arbitrary eval, remote asset loading, or fake
compile/test operation is offered.

Official APIs: [RunService](https://create.roblox.com/docs/reference/engine/classes/RunService),
[ScriptEditorService](https://create.roblox.com/docs/reference/engine/classes/ScriptEditorService),
[PluginCapabilities](https://create.roblox.com/docs/reference/engine/classes/PluginCapabilities).
[StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService)
documents the player-launch/end APIs; this new path needs native host proof.
Native host verification requires Roblox Studio; source inspection alone is not
a playtest or Client/Server proof.
