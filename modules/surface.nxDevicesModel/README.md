# nxDevicesModel

Provides LOCAL_DRAG, REMOTE_DRAG, dragSource, hasDrag for Neyvia's UI state and behavior.

- **Public API:** `ACTIVE`, `LOCAL_DRAG`, `REMOTE_DRAG`, `deviceStatusText`, `dragSource`, `dropIntent`, `hasDrag`, `isActive`, `parsePcTarget`, `pcTarget`, `sendTarget`, `shareSummary`, `transferFraction`, `transferLine`.
- **Manual:** [cross-pc.cl](../../manuals/cl/cross-pc.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `devices.dropIntent`, `devices.parsePcTarget`, `devices.pcTarget`, `devices.sendTarget`, `devices.transferFraction`, `devices.transferLine`.
- **Dependencies:** [surface.nxProofsEContracts](../surface.nxProofsEContracts/README.md).
- **Owner:** Neyvia / nxDevicesModel.
- **Files:** [web/src/neyvia/next/nxDevicesModel.js](../../web/src/neyvia/next/nxDevicesModel.js).
