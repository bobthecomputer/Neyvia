# Unity editor bridge

Copy `Editor/` into the selected project's `Assets/NeyviaBridge/Editor/` (or install
this directory as a local UPM package). Project setup writes
`.neyvia/gamedev-bridge.json` with its private token. The bridge checks project
affinity and only uses the literal loopback HTTP port in that config (never 47881).
The package declares the built-in JSON, UnityWebRequest and Physics modules it
compiles against, so a minimal project manifest still loads the bridge. EditorApplication.update polls
asynchronously; no blocking network waits. Pending receipts survive domain reloads
in Unity SessionState. A stopped editor is not treated as connected.

Typed operations:

- `inspect {path?}` observes the active scene, up to 1000 objects, and component
  types at a slash-separated object path. Duplicate sibling names are refused.
- `transcribe {}` returns Scene v1 nodes (hierarchy path, local scale, collider
  count, Rigidbody collider intent, missing scripts/materials/meshes) for the
  shared scene_core predicates.
- `select {path}` selects the real scene GameObject.
- `edit {path,component,property,value?,vector?,save?}` changes a serialized
  string/bool/int/float/Vector3 property with Undo. `Transform` position is
  `m_LocalPosition` and uses `vector:[x,y,z]`. Edits require idle Edit mode.
- `edit {path:"Assets/...cs",source,expectedSha256}` preserves existing source
  unless its current hash matches. Existing assets only; writes reject traversal
  and linked paths. This records an edit, not compilation success.
- `reload {}` refreshes AssetDatabase and completes after import/compile is idle;
  inspect `console` for compilation errors. It does not claim script validation.
- `run {}` / `stop {}` complete after Unity enters/exits Play mode.
- `console {}` reports the last 200 captured editor logs.
- `load_asset {path:"Assets/..."}` instantiates a real imported GameObject with
  Undo; raw glTF requires a glTF importer already installed in the project.
- `test {mode:"EditMode"|"PlayMode"}` is advertised only with the adapter below.

If `com.unity.test-framework` is already present, copy the two `OptionalTests/`
templates into `Editor/Tests/`, removing `.template` from each name. Its separate
assembly references Unity's TestRunnerApi; no package is downloaded. The adapter
registers callbacks across domain reload, runs the actual Unity test suite, and
returns pass/fail/skip counts. Failing or empty suites yield failed receipts.
Without that optional assembly, `test` is not advertised. Setup can do this
conditionally by checking the project's `Packages/manifest.json`.

Official API:
[TestRunnerApi](https://docs.unity.cn/Packages/com.unity.test-framework@1.1/api/UnityEditor.TestTools.TestRunner.Api.TestRunnerApi.html),
[ICallbacks](https://docs.unity.cn/Packages/com.unity.test-framework@1.6/api/UnityEditor.TestTools.TestRunner.Api.ICallbacks.html).
Source inspection is not native compile/play/test proof; Unity Editor must be
present to perform that acceptance journey.
