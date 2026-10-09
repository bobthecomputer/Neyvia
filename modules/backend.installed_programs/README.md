# installed_programs

Reuse existing host executables in managed work folders, without installation.

- **Public API:** `InstalledPrograms`, `installed_program_tool_definitions`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.local-host.managed-process-journey`, `runtime.program.local-python-preflight`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.resource_admission](../backend.resource_admission/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/installed_programs.py](../../src/grant_agent/installed_programs.py).
