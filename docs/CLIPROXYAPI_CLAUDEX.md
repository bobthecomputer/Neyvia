# CLIProxyAPI + claudex (Claude Code → ChatGPT/Codex)

Route **Claude Code** (orange crab harness) through a local **Anthropic-compatible** proxy so the model is a ChatGPT/Codex GPT (for example **GPT-5.6 Sol**). This does **not** use classical Anthropic `claude auth login`.

Recipe credit: Tibo’s “claudex” pattern + [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI).

## Proxy URL / port

| Setting | Default |
| --- | --- |
| Proxy listen port | `8317` |
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:8317` |
| Client token env | `CLIPROXY_API_KEY` → mapped to `ANTHROPIC_AUTH_TOKEN` |
| Default model | `gpt-5.6-sol` |
| Subagent model | `CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol` |
| Neyvia harness profile | `claude-code-claudex` |

Override the port with `CLIPROXY_PORT` before install/start.

## Architecture

```text
Claude Code  --Anthropic Messages API-->  CLIProxyAPI :8317  --Codex OAuth-->  ChatGPT/Codex GPT models
```

OpenCodeGo stays on its own `OPENCODE_API_KEY` path. Do not rotate or clear that secret when wiring claudex.

## NAS / Neyvia runtime install

Neyvia runtimes live on the Synology bridge (`nas-user@192.0.2.10`). Preferred bin root:

`/volume1/Saclay/runtime/bin`

Install + start from the Windows workspace (paramiko SSH, same credentials as `pull_nas_tree.py`):

```powershell
cd C:\Users\example\Projects\vibe-coding-platform
python scripts\nas_install_cliproxyapi.py
```

The script:

1. Downloads `CLIProxyAPI_*_linux_amd64_no-plugin.tar.gz` into `/volume1/Saclay/runtime/cliproxyapi/`
2. Installs `cli-proxy-api` (+ `cliproxyapi` alias) under `/volume1/Saclay/runtime/bin/`
3. Writes config with a generated `api-keys` token
4. Starts the proxy on port `8317`
5. Writes `/volume1/Saclay/runtime/home/.fluxio_cliproxy_env`
6. Attempts `cli-proxy-api -codex-login -no-browser` (browser OAuth URL; **not** device-code)
7. Saves a receipt under `.agent_control/nas_transfers/nas_cliproxyapi_install_*.json`
8. Writes `.agent_control/cliproxy_local.env` for Windows wrappers

To finish OAuth from existing Neyvia Codex tokens (preferred):

```powershell
python scripts\nas_seed_cliproxy_from_codex_oauth.py
```

Doctor recognition:

```bash
python scripts/nas_runtime_doctor.py --extra-bin-dir /volume1/Saclay/runtime/bin --json
```

Look for `cliproxy.ready`, `managedCliAuthentication.claude-code: proxy_backed`, and `managedCliAuthentication.cliproxyapi`.

## How Neyvia launches Claude through the proxy

1. Harness profile `.agent_control/harness_profiles.json` → id `claude-code-claudex`
2. `grant_agent.harness_registry.harness_gateway_environment` sets:
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_AUTH_TOKEN` (from `CLIPROXY_API_KEY`)
   - `CLAUDE_CODE_SUBAGENT_MODEL`
   - `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1`
   - `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`
   - `FLUXIO_HARNESS_COMPAT=cliproxy`
3. Managed Claude chat/mission paths pass `--harness-profile claude-code-claudex` into `external_cli_bridge`
4. Runtime home also loads `.fluxio_cliproxy_env` via `runtime_subprocess_env`

Chat payload example:

```json
{
  "runtime": "claude-code",
  "harnessProfileId": "claude-code-claudex",
  "route": { "model": "gpt-5.6-sol", "effort": "high" }
}
```

## Windows equivalents of the Unix alias

Unix (Tibo):

```bash
alias claudex='CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol \
  CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1 \
  ANTHROPIC_BASE_URL=http://localhost:8317 \
  claude'
```

### CMD wrapper

```bat
scripts\claudex.cmd
scripts\claudex.cmd -p "Reply with exactly: oauth-ok"
```

Loads `.agent_control\cliproxy_local.env` when present.

### PowerShell function

```powershell
. .\scripts\claudex.ps1
claudex
claudex -p "Reply with exactly: oauth-ok"
```

Plain `claude` is intentionally unchanged (no global Anthropic settings rewrite).

## OAuth (ChatGPT / Codex) — project-native path

CLIProxyAPI must authenticate against ChatGPT/Codex. Proxy can be healthy while `/v1/models` is empty until OAuth tokens land under runtime `~/.cli-proxy-api/`.

**Do not** run `claude auth login` for this route.

Neyvia already authenticates Codex as **OpenAI Codex OAuth** (browser redirect → tokens), documented in mission `provider_runtime_truth.authPath` and implemented by Fluxio `start_openai_codex_oauth_command` / `codex_local_oauth_helper.py`. OpenCodeGo stays on its separate **API key** path (`provider_secrets.json` → `OPENCODE_API_KEY`).

### Preferred — reuse existing OpenAI Codex OAuth tokens

If Fluxio/Neyvia already completed ChatGPT/Codex browser OAuth (tokens in `~/.codex/auth.json` or OpenClaw auth-profiles), seed the proxy **without** any device code:

```powershell
python scripts\nas_seed_cliproxy_from_codex_oauth.py
```

This imports the existing OAuth authorization into CLIProxyAPI's private auth
store via the NAS SSH bridge and checks `/v1/models`. Treat that store as a
credential store: never commit it or expose it in a receipt.

### Fallback — browser redirect + callback tunnel (same OAuth as Fluxio)

**Not** device-code / signing-letter login. Use the same authorize URL + `localhost:1455` callback pattern Neyvia already uses:

```powershell
ssh -L 1455:127.0.0.1:1455 nas-user@192.0.2.10
```

In a second SSH session:

```bash
export HOME=/volume1/Saclay/runtime/home PATH=/volume1/Saclay/runtime/bin:$PATH
cli-proxy-api -config /volume1/Saclay/runtime/cliproxyapi/config.yaml -codex-login
```

Browser:

1. Open the printed `https://auth.openai.com/oauth/authorize?...` URL
2. Sign in with the ChatGPT/Codex account
3. Select the correct workspace if prompted
4. Approve access
5. Wait for the `localhost:1455` success page
6. Verify:

```bash
source /volume1/Saclay/runtime/home/.fluxio_cliproxy_env
curl -s http://127.0.0.1:8317/v1/models -H "Authorization: Bearer $CLIPROXY_API_KEY"
```

### Deprecated — device code (`-codex-device-login`)

Do **not** use `cli-proxy-api -codex-device-login` or `https://auth.openai.com/codex/device` signing letters as the primary path. That flow does not stick for this project’s headless NAS setup and is not how Neyvia authenticated Codex before.

## Local Windows proxy (optional)

If Claude Code runs on the PC instead of the NAS worker:

- `winget install LuisPater.CLIProxyAPI` (when available), or download the Windows release asset from GitHub
- Point `ANTHROPIC_BASE_URL` at `http://127.0.0.1:8317`
- Or tunnel: `ssh -L 8317:127.0.0.1:8317 nas-user@192.0.2.10` and keep the NAS proxy

## Verify

```powershell
# After OAuth + proxy up (NAS-local or tunneled):
curl http://127.0.0.1:8317/
curl http://127.0.0.1:8317/v1/models -H "Authorization: Bearer <CLIPROXY_API_KEY>"
.\scripts\claudex.cmd -p "Reply with exactly: claudex-ok"
```

## Receipts

Install/OAuth evidence lands in:

`.agent_control/nas_transfers/nas_cliproxyapi_install_*.json`
`.agent_control/nas_transfers/nas_cliproxy_seed_codex_oauth_*.json`

Successful seed proof: models list non-empty after converting existing Neyvia OpenAI Codex OAuth tokens (not device-code).

Publication note: local account paths and network identifiers in this document are neutral examples.
