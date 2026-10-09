# neyvia_mobile_studio

Mobile Studio (Studio suite): a phone preview beside the chat, iPhone builds

- **Public API:** `android_toolchain`, `build`, `call`, `create`, `install`, `ios_toolchain`, `now`, `preview`, `preview_token`, `project_info`, `report_state`, `serve_preview`, `simulate`, `state`, `status`, `neyvia.mobile.build`, `neyvia.mobile.create`, `neyvia.mobile.install`, `neyvia.mobile.preview`, `neyvia.mobile.setup`, `neyvia.mobile.simulate`, `neyvia.mobile.status`, `neyvia.mobile.verify`.
- **Manual:** [mobile-studio.cl](../../manuals/cl/mobile-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `neyvia-core.mobile-confinement`, `neyvia-core.mobile-injection`, `neyvia-core.mobile-project`, `neyvia-core.mobile-storage`.
- **Dependencies:** [backend.app_sdk](../backend.app_sdk/README.md), [backend.apple_targets](../backend.apple_targets/README.md), [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.ios_studio](../backend.ios_studio/README.md), [backend.proofs_d_neyvia](../backend.proofs_d_neyvia/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.windows_ios_compiler](../backend.windows_ios_compiler/README.md), [backend.windows_macos_compiler](../backend.windows_macos_compiler/README.md).
- **Owner:** Neyvia / mobile-studio.
- **Files:** [src/grant_agent/neyvia_mobile_studio.py](../../src/grant_agent/neyvia_mobile_studio.py).
