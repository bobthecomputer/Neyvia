# neyvia_remote

Live, owner-consented remote windows on T16's background preview service.

- **Public API:** `Indicator`, `NoRedirect`, `RemoteError`, `RemoteService`, `call`, `forward_desktop`, `serve_http`, `service_for`, `neyvia.remote.log`, `neyvia.remote.snapshot`, `neyvia.remote.state`, `neyvia.remote.windows`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [remote.cl](../../manuals/cl/remote.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.remote-transport`.
- **Dependencies:** [backend.cua_native](../backend.cua_native/README.md), [backend.neyvia_cua](../backend.neyvia_cua/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia-core.
- **Files:** [src/grant_agent/neyvia_remote.py](../../src/grant_agent/neyvia_remote.py).
