# OpenCodeGo Provider Setup

Status: key-backed provider path wired for Neyvia.

## Safe Key Storage

Do not paste the OpenCodeGo API key into chat, source files, tests, screenshots, or mission objectives.

Preferred path:

1. Open Fluxio Settings.
2. Go to Tools and accounts.
3. Find OpenCodeGo.
4. Paste the key into the password field.
5. Click Save key.

Fluxio stores the value under ignored `.agent_control/provider_secrets.json` and mirrors it to the runtime env as `OPENCODE_API_KEY` for launched Hermes/OpenClaw processes. The key is not stored in Git.

Manual fallback on the runtime host:

```bash
export OPENCODE_API_KEY='paste-key-here'
```

Use the manual fallback only for a private shell session. Do not put the key in tracked scripts.

## Runtime Provider IDs

Fluxio accepts these aliases and normalizes them to `opencode-go`:

- `opencodego`
- `opencode-go`
- `opencode`

Hermes and OpenClaw route contracts can then use:

```json
{
  "role": "executor",
  "provider": "opencode-go",
  "model": "opencode-go/kimi-k2.5",
  "effort": "high"
}
```

Current Fluxio OpenCodeGo UI work should use `opencode-go/glm-5.2`. Other supported OpenCodeGo model refs include `opencode-go/kimi-k2.5` and `opencode-go/minimax-m2.5`.

## Start A Mission

From the web app:

1. Open Builder or Agent.
2. Select Hermes as the runtime.
3. Set the executor provider to OpenCodeGo.
4. Choose `opencode-go/glm-5.2` for UI work, or another OpenCodeGo model only when the mission explicitly calls for it.
5. Start the mission.

CLI equivalent:

```bash
python -m grant_agent.cli mission-start \
  --root /volume1/Saclay/projects/syntelos/current \
  --workspace-id <workspace_id> \
  --runtime hermes \
  --objective "Run a small OpenCodeGo route smoke test and report the provider/model used." \
  --route-overrides-json '[{"role":"executor","provider":"opencode-go","model":"opencode-go/kimi-k2.5","effort":"high"}]' \
  --launch-async
```

## Follow The Chat

Use the Agent surface in Fluxio. Select the mission row, then use the Agent thread. Runtime messages should appear as mission events, delegated runtime sessions, and provider-truth rows.

CLI detail view:

```bash
python -m grant_agent.cli control-room-mission-detail \
  --root /volume1/Saclay/projects/syntelos/current \
  --mission-id <mission_id>
```

## Notifications

Chrome notifications are browser Web Push. For phone/app-like notifications, Fluxio currently uses ntfy as the proven mobile push path. The longer-term worker layer is Huginn plus ntfy; Chrome remains a secondary desktop/browser channel.
