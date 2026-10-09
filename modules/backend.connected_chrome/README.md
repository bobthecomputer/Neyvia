# connected_chrome

Operate the user's authenticated Chrome through the DevTools Protocol.

- **Public API:** `BrowserTab`, `ChromeEndpoint`, `ChromeInstallation`, `ConnectedChromeError`, `TabSession`, `act`, `capture_screenshot`, `connection_status`, `find_chrome`, `find_elements`, `find_tab`, `launch`, `list_tabs`, `managed_profile_dir`, `managed_profile_state`, `observe`, `open_tab`, `owned_tab_transport`, `probe_endpoint`, `shutdown`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cdp_client](../backend.cdp_client/README.md), [backend.chrome_environment](../backend.chrome_environment/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_chrome.py](../../src/grant_agent/connected_chrome.py).
