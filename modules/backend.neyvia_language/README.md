# neyvia_language

No-slop language checks for UI strings and reports (plan 20, C5).

- **Public API:** `TextOutput`, `call`, `check`, `gate`, `load_skill`, `main`, `receipt`, `recent_text_files`, `segments_for`, `task_artifacts`, `tool`, `neyvia.language.check`.
- **Manual:** [language.cl](../../manuals/cl/language.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.language-copy`.
- **Dependencies:** [backend.cl_skill](../backend.cl_skill/README.md).
- **Owner:** Neyvia / language.
- **Files:** [src/grant_agent/neyvia_language.py](../../src/grant_agent/neyvia_language.py).
