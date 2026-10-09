# github_release_source

Resolve Neyvia marketplace applications from GitHub releases.

- **Public API:** `GitHubReleaseError`, `GitHubSource`, `check_for_update`, `compare_versions`, `download_asset`, `fetch_releases`, `find_checksum_for`, `normalize_version`, `parse_github_ref`, `release_channel`, `select_platform_asset`, `select_release`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `adapters.release.selection`, `adapters.release.staging`, `adapters.release.update`.
- **Dependencies:** [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.module_marketplace](../backend.module_marketplace/README.md), [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/github_release_source.py](../../src/grant_agent/github_release_source.py).
