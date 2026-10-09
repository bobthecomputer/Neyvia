# Localhost Automation API

The app starts a localhost API by default for CLI and automation integrations.

In the desktop UI, OpenClaw gateway routing is activated for autonomous agent modes (Autopilot / Deep Run / Swarms / Swarm Mega) and disabled outside those modes.

Default bind:

- Host: `127.0.0.1`
- Port: `47635`

## Endpoints

- `GET /health`
  - Returns `{ "ok": true }`
- `GET /v1/state`
  - Returns overlay state snapshot (settings, mode, performance, OpenClaw status, night mode)
- `POST /v1/command`
  - Body is an Agent Control Protocol command object
  - Returns protocol execution response (`ok`, `data`, `error`)

When a localhost API token is configured, both `/v1/state` and `/v1/command` require:

- `Authorization: Bearer <token>`

`/health` remains unauthenticated so supervisors can verify process liveness.

## Example command call

```bash
curl -X POST "http://127.0.0.1:47635/v1/command" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"command":"overlay.open"}'
```

## Managing auth token (Tauri invoke commands)

- `save_localhost_api_token_command` with payload `token: string`
- `clear_localhost_api_token_command`
- `has_localhost_api_token_command`

## OpenClaw gateway management (Tauri invoke commands)

- `get_openclaw_status`
- `connect_openclaw_gateway` with optional payload `{ payload: { gatewayUrl?: string } }`
- `disconnect_openclaw_gateway`
- `save_openclaw_gateway_token` with payload `token: string`
- `clear_openclaw_gateway_token`
- `has_openclaw_gateway_token`
- `send_openclaw_message` with payload `{ message: string }`

`get_openclaw_status` includes connection telemetry such as `connected`, `lastError`, `reconnectAttempt`, `queuedOutbound` (messages waiting for replay), and `pendingAckCount`.

## Desktop autonomous dashboard commands (Tauri invoke)

- `get_autonomy_dashboard_snapshot` with payload `{ payload?: { root?: string } }`
- `run_agent_vibe_status_command` with payload `{ payload?: { root?: string } }`
- `run_agent_vibe_continue_command` with payload `{ payload: { root?: string, cycles?: number, iterations?: number, mode?: string, profile?: string, mergePolicy?: string } }`
- `run_agent_soak_command` with payload `{ payload: { root?: string, objective: string, docs?: string[], cycles?: number, iterations?: number, mode?: string, profile?: string, mergePolicy?: string } }`

Desktop task-model routing lets users define provider/model preferences per task class (frontend/backend/verification/research/general); those preferences are forwarded to OpenClaw in prompt metadata.

## Provider secret management (keychain-backed)

- `save_provider_secret_command` with payload `{ provider_id: string, secret: string }`
- `clear_provider_secret_command` with payload `{ provider_id: string }`
- `has_provider_secret_command` with payload `{ provider_id: string }`
- `get_provider_secret_presence_command` with payload `{ provider_ids: string[] }`

## Security notes

- The server binds to loopback only.
- Optional bearer-token auth is enforced for sensitive API routes when configured.
- High-risk actions still go through the permission/approval gate.
- Node command execution requires exact command allowlist matches.
- OpenClaw gateway token and provider secrets are stored in the OS keychain, not plaintext config.
