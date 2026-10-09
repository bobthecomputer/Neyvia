# Real Feature Audit - 2026-04-27

This audit records what is implemented, what is only partially implemented, and what is blocked by the local machine or external services. It is meant to prevent calling a surface "real" before it has a working action path, visible state, and verification coverage.

## Implemented And Wired

- Web/private app shell: `web/src/neyvia/NeyviaShell.jsx` and `NeyviaWorkspace.jsx` load the live backend, persist UI state, expose Agent, Builder, Skills, Settings, and bridge surfaces.
- Website roadmap: the public roadmap is now event-based with animated milestone rows and a selected proof popup.
- Builder quality roadmap: the Builder drawer now shows an animated event line, selectable event details, and action buttons that route through real workspace actions.
- Computer/NAS/cloud bridge state: `storageBridge` is part of the mission-control snapshot and appears in Settings -> Storage.
- NAS control route: configured as SSH/SFTP `nas-user@192.0.2.10:22`; SMB `Y:\projects` is treated as optional drive-letter sync. Port 22 is reachable from this workstation; port 24 is closed.
- Cloud drive bridge: detects Google Drive, OneDrive, Dropbox, and custom mounted roots, and exposes Google Drive login/download links without storing OAuth secrets in Git.
- Tool and port management: Settings -> Tools & Ports lists managed services, bridge endpoints, statuses, ports, and service actions when actions are exposed by the backend.
- NAS SSH probe: `scripts/nas_ssh_probe.py` checks socket reachability, then password auth via `FLUXIO_NAS_SSH_PASSWORD` or an interactive prompt, without logging secrets.
- Windows NAS auth prompt: `scripts/verify_nas_ssh_prompt.ps1` prompts locally with `Read-Host -AsSecureString` and writes only the JSON probe result.
- Local network unlock action: `scripts/unblock_codex_network.ps1` can disable the specific local `codex_sandbox_offline_block_outbound` firewall rule through elevated PowerShell/UAC.
- Skills cleanup: older custom skills were archived; the active custom taste skills are the image/frontend/GPT taste skills plus system skills.

## Current Blockers

- The earlier local blocker, Windows outbound rule `codex_sandbox_offline_block_outbound`, has been disabled through the elevated unlock script.
- The VPN was also blocking the practical path; after it was disabled, general network checks improved.
- Tailscale is now connected, the NAS peer is online, and the route to `192.0.2.10/32` exists.
- Port `22` is the configured NAS control port. If a probe fails, the UI now reports the current blocker directly instead of changing the configured port.
- The remaining NAS verification step is entering the password through a prompt/backend environment and checking the remote root. The app and probe avoid logging the password.
- Neyvia itself is still not running from the NAS web backend: `192.0.2.10:47880` is closed from this workstation.
- Neyvia browser access is local account based. External tower/admin apps are not part of the Neyvia runtime path.
- Browser/computer-use are not yet full autonomous execution ports. The app now reserves and exposes the management surface, but the full action runner for broad computer-use workflows still needs dedicated implementation.
- Image management is setup-tracked and skill-supported, but it is not yet a complete asset library with selection, promotion, and project-folder lifecycle.

## Verification Performed

- Focused backend/frontend contract tests passed before this audit: `51 passed`.
- Frontend production build passed before this audit.
- New NAS diagnostics directly identify whether the blocker is Tailscale state, socket reachability, missing credentials, auth, or remote-root access.

## Definition Of Done For Remaining Work

- NAS route is ready only when `scripts/nas_ssh_probe.py --host 192.0.2.10 --port 22 --user nas-user --remote-root /volume1/Saclay/projects --prompt` reaches `stage: ready`.
- Browser/computer-use is ready only when the app can start a controlled session, perform a visible action, capture proof, and show the event in the mission timeline.
- Image management is ready only when generated/imported images are selectable, previewable, promotable into a project folder, and recorded in proof.
- Tool management is ready only when every listed service has status, endpoint/port when applicable, and at least one real repair or verify action where the backend can support it.

Publication note: local account paths and network identifiers in this document are neutral examples.
