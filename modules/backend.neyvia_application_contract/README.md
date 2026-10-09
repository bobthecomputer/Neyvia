# neyvia_application_contract

N-E-Y-V-I-A application contract — two developer propositions, one core.

- **Public API:** `adopt_additional_services`, `bind_application_capabilities`, `build_application_registry`, `bundled_application_catalog`, `describe_developer_propositions`, `install_bundled_application`, `load_sdk_applications`, `normalize_application_kind`, `normalize_application_manifest`, `register_sdk_application`, `resolve_application_embedding`, `uninstall_bundled_application`, `unregister_sdk_application`, `workspace.read`.
- **Manual:** [design.cl](../../manuals/cl/design.cl), [host-runtime.cl](../../manuals/cl/host-runtime.cl), [local-browser-sdk.cl](../../manuals/cl/local-browser-sdk.cl), [memory.cl](../../manuals/cl/memory.cl), [nearby-send-runtime.cl](../../manuals/cl/nearby-send-runtime.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [proofs.cl](../../manuals/cl/proofs.cl), [runtime-provider.cl](../../manuals/cl/runtime-provider.cl), [slim-installer.cl](../../manuals/cl/slim-installer.cl), [tools-depth.cl](../../manuals/cl/tools-depth.cl), [workspace.cl](../../manuals/cl/workspace.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `neyvia-core.application-projection`, `neyvia-core.bundled-catalog`, `neyvia-core.bundled-durable`, `neyvia-core.hosted-entrypoint`, `neyvia-core.sdk-durable`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.github_release_source](../backend.github_release_source/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.module_marketplace](../backend.module_marketplace/README.md), [backend.proofs_d_neyvia](../backend.proofs_d_neyvia/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / design.
- **Files:** [src/grant_agent/neyvia_application_contract.py](../../src/grant_agent/neyvia_application_contract.py).
