# Remote project files and downloads — 25 September 2026

## Use it

On a device connected to the same Tailscale network, open:

<https://asuspsdlb.example.invalid:8443/control?surface=agent&controller=desktop>

Sign in with the existing Neyvia account. Open **Files** (folder icon near the top), choose the workspace, then:

- Open folders and preview text/code files.
- Use **Refresh** to see the current files on ASUSPSDLB, including newly created files.
- Use a file's download icon to save it on the current device.
- Use **Download ZIP** to retrieve the selected project or folder, then extract it on the other computer.

The controller uses the existing desktop conversation and command relay. Files are read directly from the registered workspace on the PC. They remain available when the desktop window is closed as long as the controller server is running; sending desktop commands still requires Neyvia Desktop to be open.

ASUSPSDLB must remain powered, awake, signed in, and connected to Tailscale. The new `Neyvia Remote Controller Backend` scheduled task starts at this user's Windows logon and supervises the backend on port 47881. Its launch and automatic recovery after a stopped backend were both verified. Existing Tailscale 443 and 8443 routes and the unrelated Phone PWA scheduled task were preserved.

## Implementation

- `src/grant_agent/project_files.py`: registered-workspace listing, paginated folders, bounded text preview, binary file streaming, ZIP export, file hashes and export manifest.
- `src/grant_agent/web_backend.py`: authenticated owner-only `/api/project-files`, `/preview`, `/download`, `/archive` routes. Downloads use streaming responses and temporary ZIP cleanup, independently of model/chat runtime limits.
- `web/src/neyvia/NeyviaProjectFiles.jsx` and `.css`: responsive Files drawer, workspace selector, breadcrumbs, modification times, preview, refresh, and downloads. Stale folder/preview responses are cancelled; keyboard focus stays in the dialog.
- `web/src/neyvia/NeyviaWorkspace.jsx`: browser/controller Files entry.
- `scripts/start-neyvia-controller.ps1` and `install-neyvia-controller-startup.ps1`: per-user hidden supervisor with no elapsed-time task limit, automatic restart, and duplicate/foreign-process protection.

Production frontend was built in a staging folder and copied into `web/dist`, replacing `index.html` last and retaining old hashed assets for tabs already open. The desktop executable was left running; this feature is delivered in the remote web controller.

## Verified

- Signed into the actual HTTPS Tailscale controller; it reported **Connected · ASUSPSDLB** and displayed the shared conversation list.
- Opened Files, switched to RentSecurity, and triggered its project ZIP through the browser. The HTTP transfer retrieved **2,250 files / 103,718,861 source bytes**, compressed to approximately **36.2 MB**. Every file in that downloaded archive matched its SHA-256 manifest entry.
- Retrieved a binary fixture byte for byte over Tailscale; text preview matched the source.
- Opened a live folder in the browser, created a harmless fixture on the PC, clicked Refresh, saw the new file, previewed its exact content, and downloaded it in the phone layout.
- Inspected desktop (1440×900) and phone (390×844) layouts. This is responsive browser proof, not a physical second-computer/phone network test.
- LAYA ran the actual Files → Refresh browser journey: two actions, both independent postconditions passed, zero model calls. Initial cold Chrome startup failed; after confirming Chrome was listening, the journey passed. LAYA did not verify archive bytes; the separate HTTP/download checks did.
- Production file export fixtures passed: registry, pagination, text limits, binary download, traversal and disabled-workspace rejection, symlink/junction handling, exclusion policy, manifest collisions, ZIP timestamps, concurrent same-size file changes.
- Anonymous, foreign-origin, unregistered workspace, and protected-path HTTP requests were rejected.
- Scheduled supervisor launched backend PID 35768, then automatically restored it as PID 37852 after a controlled stop with no active controller requests. See `proof/project-downloads-20260925/controller-recovery.json` for the timestamped observation.

Evidence: `proof/project-downloads-20260925/http-downloads.json`, `archive-integrity.json`, `laya-files-receipt.json`, `files-desktop.png`, `files-phone.png`, `files-phone-preview.png`, and the build/check logs.

## Boundaries

Downloads are snapshots, not automatic two-way synchronization or a deployment to the NAS. New downloads reflect the current PC files. Dependency/cache directories, VCS/internal control metadata, common credential files, and nested symlinks/junctions are excluded. Each ZIP includes `NEYVIA_EXPORT.json` (or a collision-free variant) recording the policy, skipped counts, included paths, sizes, and hashes. Reinstall dependencies and configure credentials on the destination computer as needed.

ZIP requests are limited to 25,000 files / 4 GiB of source data per selected folder. Larger projects can be downloaded by subfolder; individual binary downloads stream without loading the whole file in memory. If an included file changes during ZIP creation, the export fails with a refresh/retry error instead of returning a known partial archive. Text previews are limited to 256 KiB; full downloads retain the entire file.

No user project files were edited by the verification. Test files were created only under Neyvia's proof directory. The retrieved RentSecurity archive is local proof and is excluded from the Neyvia NAS source checkpoint. No provider/model task, hardware operation, Git commit, or public release was performed.

Publication note: local account paths and network identifiers in this document are neutral examples.
