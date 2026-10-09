---
name: imagegen
description: Generate or edit a raster image through Neyvia's configured Codex subscription image route. Use for Image Playground requests; use Image Studio tools for crop, resize, composite and export of existing assets.
---

Use the current Image Playground request and its selected reference images. Preserve the requested subject, composition, dimensions and edit boundaries in the prompt. Keep the operation inside the selected workspace.

Inspect `image_playground_readiness_command` before generation. Submit `image_playground_operation_command` with the requested operation and `skillInvocation: {skillId: "imagegen"}` through the available Neyvia bridge. The backend checks the configured provider, subscription authentication, exact model and output PNG. Skill installation alone does not establish provider readiness.

Use the configured Codex subscription route. If it is unavailable, return the backend's blocker. Do not replace it with an API-key provider, another model or a fabricated artifact.

After generation, inspect the returned PNG and its request-bound manifest. Report the artifact path, verified dimensions and hash from that receipt. A successful process or valid PNG does not prove that the image matches the prompt; review the actual pixels before claiming the request complete.
