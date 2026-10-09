# Game Dev bridge backend

Owner HTTP commands and `neyvia.gamedev.*` tools share the persistent service.
Install project-local bridges through `gamedev_setup_command`; no system/editor
installation is performed. Configure a process-local `NEYVIA_GAMEDEV_WORKSPACE`
when backend scratch state is separate from editable projects. Native packages
are in `unity/`, `roblox/`, `godot/`, `blender/` with their actual API arguments.
The browser workspace is `/api/gamedev/browser?project=<workspace-project>` and
requires the owner's backend session. It uses vendored Babylon WebGL Engine,
not a CDN at runtime. UI buttons queue the same operations used by agents.

Transport is local HTTP 48261 and Godot WebSocket 48263 in this isolated task.
Editor plugins accept only these explicit task endpoints. Session affinity,
capabilities, serial operation assignment, busy heartbeats, stable request IDs,
deadline failures and restart interruption are enforced by the backend.
Project bridge capability tokens are hashed in the service; the raw token lives
only in the ignored project config (Roblox generated local plugin embeds it).

The executable manual is `manuals/game-dev.manual.json`; regenerate only its
schemas/content with `python scripts/gamedev/build-manual.py`. Claude owns the
human-facing generated Markdown and product UI.

`node scripts/verify-t12.mjs` runs actual localhost commands and the shared
scene implementation in Babylon **NullEngine**, exports GLB, runs the official
Khronos validator, and reloads it through Babylon's glTF loader. It is semantic
engine proof, not rendered browser or native editor proof. Output is
`scripts/evidence/T12.json`; no mock editors or synthetic completion receipts.

Bundled runtime sources are official Babylon CDN builds (Apache-2.0) and the
official `gltf-validator` npm package (Apache-2.0); versions, sizes and hashes are
in `vendor/manifest.json`. No individual download exceeds 10 MB. No packages are
installed into the shared `node_modules` junction.

Authoritative references: [Babylon glTF loader](https://github.com/BabylonJS/Documentation/blob/master/content/features/featuresDeepDive/importers/glTF.md),
[Babylon exporter](https://github.com/BabylonJS/Documentation/blob/master/content/features/featuresDeepDive/Exporters/glTFExporter.md),
[Khronos validator API](https://github.com/KhronosGroup/glTF-Validator/blob/main/node/README.md).
