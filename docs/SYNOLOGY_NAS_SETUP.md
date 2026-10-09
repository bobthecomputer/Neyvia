# Neyvia On Synology NAS

Neyvia turns AI agents into second brains and can run as a private web console on a Synology NAS or any Linux box with Python 3.11+ and Node 22+. The public repository does not include account passwords, provider keys, Codex data, MiniMax tokens, or local NAS paths.

## First Install

```bash
git clone https://github.com/bobthecomputer/vibe-coding-platform.git syntelos
cd syntelos
python -m pip install -e .
python scripts/nas_setup.py --account-user paul --display-name "Paul"
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880
```

The setup script checks Python, Node, and npm; installs frontend dependencies; builds `web/dist`; and creates an ignored local account file under `.agent_control/`. After first login, the in-app setup screen can install or update Hermes, OpenClaw, and the optional Image tools package (OpenCV) used for screenshot comparison and future visual features. The generated account password is written to `.agent_control/neyvia_admin_password.txt` on that machine only. Existing legacy account config is imported automatically into the Neyvia-named files.

## NAS Runtime Stack

Hermes, OpenClaw, and Codex must be installed on the NAS/runtime host when the web backend runs on the NAS. Do not install them into the operator PC or WSL and expect the NAS-hosted backend to see them.

For the Saclay NAS layout, the isolated runtime lives at:

```text
/volume1/Saclay/projects/syntelos/runtime
```

The backend now auto-detects this sibling runtime bin directory:

```text
/volume1/Saclay/projects/syntelos/runtime/bin
```

You can also make the route explicit in a DSM task or SSH session:

```bash
export SYNTELOS_RUNTIME_BIN_DIR=/volume1/Saclay/projects/syntelos/runtime/bin
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880
```

Install or refresh the runtime stack from the NAS checkout:

```bash
python scripts/install_nas_runtime_stack.py \
  --runtime-root /volume1/Saclay/projects/syntelos/runtime \
  --install-openclaw \
  --install-hermes \
  --json
```

Run the NAS runtime doctor after installation:

```bash
python scripts/nas_runtime_doctor.py \
  --extra-bin-dir /volume1/Saclay/projects/syntelos/runtime/bin \
  --json
```

After the backend starts, open:

```text
http://<NAS-IP>:47880/control
```

Use the username and password from the generated password file.

## HTTPS Access

The preferred NAS setup is HTTPS at the browser edge and HTTP only on the local backend port.
In DSM, create a Login Portal or Reverse Proxy rule:

- Source: `https://<your-syntelos-host>`
- Destination protocol: `http`
- Destination host: `127.0.0.1`
- Destination port: `47880`
- WebSocket support: enabled if DSM exposes the option

Then run setup with the browser-facing base URL so the ignored password note and startup
output point at the real HTTPS address:

```bash
python scripts/nas_setup.py --account-user paul --display-name "Paul" --public-url https://<your-syntelos-host>
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880 --public-url https://<your-syntelos-host>
```

If you are not using DSM reverse proxy and already have certificate files on the NAS, the
backend can serve direct HTTPS:

```bash
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880 \
  --public-url https://<your-syntelos-host>:47880 \
  --tls-cert-file /path/to/fullchain.pem \
  --tls-key-file /path/to/privkey.pem
```

Do not expose the private control room to the public internet without Tailscale, DSM account
protection, or another network-level access boundary.

Current live NAS web state on this machine:

- Neyvia is not currently listening on `192.0.2.10:47880`; deploy or start `scripts/run_web_backend.py` on the NAS before treating that URL as live.
- The intended operating model is web-first: open the NAS URL, authenticate in the browser, then operate from the web UI. SSH/SMB are deployment and file-sync paths, not the main operator surface.

## Add One or More Users

To add or reset one additional local account without rebuilding the frontend:

```bash
python scripts/nas_setup.py --skip-npm --add-user theo --display-name "Theo"
```

To add several users at once:

```bash
python scripts/nas_setup.py --skip-npm --add-user theo --add-user sam
python scripts/nas_setup.py --skip-npm --add-users theo,sam,alex
```

The command writes each user's temporary password to an ignored file under `.agent_control/`, for example `.agent_control/syntelos_theo_password.txt`. Each user can personalize workspaces, provider setup, and runtime preferences after login while secrets stay local to the NAS process.

## Synology Task Scheduler

In DSM:

1. Open Control Panel -> Task Scheduler.
2. Create -> Triggered Task -> User-defined script.
3. Run as the NAS user that owns the checkout.
4. Use this script, adjusted to your checkout path:

```bash
cd /volume1/docker/syntelos
python scripts/run_web_backend.py --host 0.0.0.0 --port 47880
```

For HTTPS, put Synology Login Portal or Reverse Proxy in front of `http://127.0.0.1:47880`
and start Neyvia with `--public-url https://<your-neyvia-host>`.

## Computer/NAS File Bridge

The web and desktop app now surface Synology Fast Sync as a connected app bridge. Use it when
the project files are edited on the computer but a NAS-hosted Neyvia process should keep
running continuously.

- Computer source: the local editable project folder.
- NAS target: the mounted or copied folder under `/volume1/...`.
- Write policy: preview first, then require approval before uploads or downloads are queued.
- Conflict policy: keep newer files and log the decision unless the bridge reports a stricter policy.

The default connected app manifest is `synology-fast-sync` in `config/connected_apps.json`.
Point its `bridge.endpoint` at the Fast Sync HTTP surface and its `workspace_root` at the
local bridge checkout. Once the bridge responds on `/api/status`, Neyvia shows the route,
source folder, target folder, active transfer, and safe directions in Settings -> Storage.
For phone or browser use, keep `bridge.endpoint` on the local health-check URL and set
`bridge.public_endpoint` to the DSM HTTPS reverse-proxy URL. The UI displays the HTTPS route
while health checks can still use the local bridge service.

This workstation also has a direct Tailscale SMB target recorded in the Cowork bridge config:

- NAS host: `192.0.2.10`
- SSH/SFTP control: `nas-user@192.0.2.10:22`
- Requested SSH port: `22`
- Share: `Saclay`
- Mapped project target: `Y:\projects`
- Local source root: `C:\Users\example\Projects`

The manifest keeps these values as bridge metadata so the web and desktop UI can show the
route even before the Fast Sync HTTP service is online. The operator-configured NAS control path is
SSH/SFTP on port `22`; the `Y:\projects` SMB mapping is an optional drive-letter sync path.
Current Synology bridge config enables automatic bidirectional sync (`write_policy=automatic_bidirectional`)
without per-transfer approval. Set `requires_approval_for_write` back to `true` if you want
preview-first operator confirmation.
Password-based SSH checks must not store the NAS password in Git or command history. Use
the Settings -> Storage `Verify NAS SSH` action after setting `FLUXIO_NAS_SSH_PASSWORD`
only in the backend process environment, or run an interactive local check:

```powershell
python scripts/nas_ssh_probe.py --host 192.0.2.10 --port 22 --user nas-user --remote-root /volume1/Saclay/projects --prompt
```

On Windows, use the local prompt wrapper when the current terminal is not an interactive TTY:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_nas_ssh_prompt.ps1
```

It prompts through `Read-Host -AsSecureString`, sets `FLUXIO_NAS_SSH_PASSWORD` only for the
child probe process, and writes the JSON result to `tmp\nas_ssh_probe_prompt.json`.

If the current shell is not running inside the Core/Cowork activation context, the NAS peer
can still appear in Tailscale while `Y:\projects` is unavailable. In that state Neyvia keeps
the SSH route visible and marks only the drive-letter mapping as activation-required, pointing at:
`C:\Users\example\Projects\Cowork\map-synology-fast-path.cmd`.

## Cloud Drive Bridge

Neyvia also registers `cloud-drive-sync` as a storage bridge for Google Drive and other
mounted cloud folders. It detects common local roots such as Google Drive for desktop,
OneDrive, Dropbox, and custom paths from environment variables:

- `FLUXIO_GOOGLE_DRIVE_ROOT`
- `GOOGLE_DRIVE_ROOT`
- `FLUXIO_CLOUD_DRIVE_ROOT`

For Google login readiness, the backend only reports presence. It checks
`FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT`, `GOOGLE_DRIVE_OAUTH_TOKEN`,
`GOOGLE_APPLICATION_CREDENTIALS`, and ignored local token files under `.agent_control/`
or the user's config folder. OAuth secrets are not written to Git or returned to the
browser. Settings -> Storage shows whether Google login or a mounted cloud folder is ready,
then applies preview-first approval by default before upload/download transfers.

## Reset Account Password

```bash
python scripts/nas_setup.py --skip-npm --account-user paul --display-name "Paul" --reset-account-password
```

This rewrites the ignored local account config and password file.

## Provider Secrets

Use environment variables in the NAS task, a local shell profile, or the in-app provider form after login:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY`
- `MINIMAX_API_KEY`
- `MINIMAX_OAUTH_TOKEN`
- Telegram connection token (`TELEGRAM_BOT_TOKEN` if you use Telegram)

The web backend returns presence only. It does not send raw provider keys to the browser or write them into Git.

## Public Static Hosting

GitHub Pages and Vercel can serve the static Neyvia presentation shell, but full machine control requires the NAS backend. Use NAS hosting for private operations; use Vercel/GitHub Pages only for public preview, screenshots, or explaining the product.

Publication note: local account paths and network identifiers in this document are neutral examples.
