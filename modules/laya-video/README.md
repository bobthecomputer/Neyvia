# LAYA video

LAYA edits video by itself: a CL brief becomes a first draft from real captures, the shared Scene core judges the rendered file and keeps only fixes that remove findings; A/B votes become personal taste episodes.

- **Public API:** `draft`, `improve`, `inspect`, `verify`, `vote`, `neyvia.mod.laya_video.draft`, `neyvia.mod.laya_video.improve`, `neyvia.mod.laya_video.inspect`, `neyvia.mod.laya_video.verify`, `neyvia.mod.laya_video.vote`.
- **Manual:** [laya-video.cl](../../manuals/cl/laya-video.cl).
- **Contracts:** `run laya-video.verify-greeting()`, `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.cl_skill](../backend.cl_skill/README.md), [hyperframes](../hyperframes/README.md).
- **Owner:** Marketplace / Mods.
- **Files:** [apps/laya-video/briefs/neyvia-launch.cl](../../apps/laya-video/briefs/neyvia-launch.cl), [apps/laya-video/briefs/practice.cl](../../apps/laya-video/briefs/practice.cl), [apps/laya-video/host-contract.json](../../apps/laya-video/host-contract.json), [apps/laya-video/laya_video_mod.py](../../apps/laya-video/laya_video_mod.py), [apps/laya-video/manual.cl](../../apps/laya-video/manual.cl), [apps/laya-video/neyvia.module.json](../../apps/laya-video/neyvia.module.json).
