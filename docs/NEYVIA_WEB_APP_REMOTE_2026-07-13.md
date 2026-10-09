# Neyvia web app and phone remote

Neyvia now ships one web build that serves three related jobs:

- a public product page with an **Add Neyvia** installation action;
- the authenticated `/control` workbench on desktop;
- an installable `/control?surface=phone` remote for NAS and compute supervision.

## Publish and install

Build and serve the existing web backend:

```powershell
npm run frontend:build
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880
```

Put the backend behind an HTTPS reverse proxy before exposing it outside the
local machine. Browsers allow PWA installation from HTTPS origins (or
localhost during development). Chromium browsers use the native install
prompt when it is available. On iPhone and iPad, use Safari's Share menu and
choose **Add to Home Screen**.

The manifest opens the authenticated control route and includes direct Phone
and Images shortcuts. The service worker caches only immutable application
shell assets and the explicit offline page. It does not cache `/api`, auth,
health, mission, NAS, or compute responses, so an offline phone never presents
stale runtime state as live state.

## Phone controls

The Phone surface keeps the small set of controls that are useful away from a
desktop:

- NAS connection and compute-host heartbeat status;
- runtime, provider, model, reasoning effort, and execution target for the
  selected route;
- pause, resume, and proof access for the selected mission;
- Web Push and ntfy readiness;
- live mission, queue, blocker, and notification counts.

The route controls remain visible while the NAS summary is connecting. They
only report a saved state after the authenticated backend and a workspace are
available. Mission actions stay disabled until a real mission id and a
compatible runtime state are present.

## Image workspace

The Images surface keeps real GPT Image 2 sessions and imported PNG, JPEG, or
WebP references together. Imports are validated by file signature, limited to
15 MB, written below `.agent_control/design_references`, and accompanied by a
manifest. **Use in Agent** and **Use in Builder** write an adoption receipt and
attach the exact artifact to the receiving surface.

## Live skill iteration

The Skills surface reads the authoritative local `SKILL.md` instead of editing
a catalog summary. **Continue in Agent** creates or reuses the current chat
session and binds the skill above its composer. The Agent can then use the
first-class `skill.live.read` and `skill.live.iterate` native tools during that
same session. A revision is accepted only when its YAML frontmatter and body
validate and its expected SHA-256 still matches the loaded file.

Successful writes are atomic. Neyvia stores the prior content and a JSON
revision receipt under `.agent_control/skill_revisions`, plus a native-tool
receipt under `.agent_control/tool_receipts`. After every Agent turn, bound
skill files are re-read; a valid changed hash becomes the session's next live
version, while an invalid or unreadable revision remains unapplied and visible
as a warning. Other Agent sessions are not silently changed.

## Verification

Use the focused release checks:

```powershell
npm run verify:pwa
npm run frontend:build
$env:PYTHONPATH = "$PWD/src"
python -m pytest tests/test_native_tools.py -q -k "annotation_rectangle_is_clamped_and_w3c_capture_is_real or visual_search_catalog_and_ui_inspiration_contract"
python -m pytest tests/test_web_backend.py -q -k "image_workspace or image_playground or static_manifest or service_worker"
python -m unittest tests.test_web_backend.FluxioWebBackendTests.test_live_skill_iteration_versions_real_file_and_writes_receipt tests.test_web_backend.FluxioWebBackendTests.test_live_skill_iteration_rejects_invalid_or_stale_revision tests.test_native_tools.NativeToolTests.test_live_skill_iteration_is_a_receipted_native_tool
```

The annotation check launches a real browser, captures a base screenshot,
draws the selected rectangle and comment, exports the crop, writes a W3C-shaped
annotation receipt, and verifies all four artifacts exist.
