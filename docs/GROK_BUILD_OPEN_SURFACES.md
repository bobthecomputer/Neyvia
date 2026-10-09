# Grok Build / xAI CLI — open vs proprietary surfaces

Inventory for Neyvia harness reuse. Prefer documented open hooks; do **not** ship reverse-engineered proprietary blobs.

## What makes Grok Build special (reusable ideas)

1. **Headless JSON as the supervision contract** — `--single` / `-p` plus `--output-format streaming-json` gives Fluxio a process it can supervise without owning the agent loop.
2. **ACP as an optional transport** — `grok agent stdio` is advertised; Neyvia flags `supports_acp=True` but only marks ACP ready after a live negotiation receipt.
3. **Pluggable inference behind a fixed harness** — documented custom models (`GROK_MODELS_BASE_URL`, `~/.grok/config.toml` `[model.*]`) let the same CLI tools/sessions/skills run against xAI, a corporate gateway, or a local OpenAI-compatible proxy (CLIProxyAPI-style).
4. **Non-classical auth first** — `XAI_API_KEY` (and `GROK_CODE_XAI_API_KEY`) for CI/headless; `grok login --device-auth` stays operator-owned, not the only path.

Neyvia mirrors that split: the **harness** (tools, sessions, JSON stream) is fixed; the **model route** is a profile overlay.

## Open / documented (safe to integrate)

| Surface | What it is | How Neyvia uses it |
| --- | --- | --- |
| Official installer | `https://x.ai/cli/install.sh` | `scripts/install_nas_runtime_stack.py --install-grok-build` |
| Public CLI docs | [Grok Build CLI reference](https://docs.x.ai/build/cli/reference) | Source of truth for flags, models, auth |
| Settings / custom models | [Settings](https://docs.x.ai/build/settings) — `GROK_HOME`, `config.toml`, `GROK_MODELS_BASE_URL` | Harness profiles map `baseUrl` → `GROK_MODELS_BASE_URL` |
| Headless JSON stream | `--output-format streaming-json` (with `--single`) | `grant_agent.external_cli_bridge` → `FLUXIO_EVENT:` |
| Model alias | Documented `grok-4.5` + custom CLI aliases | `normalize_managed_cli_model("grok-build", …)` |
| Non-interactive session id | `--session-id` | Stable Fluxio UUID5 per mission/chat |
| Auth env | `XAI_API_KEY` / `GROK_CODE_XAI_API_KEY` | Preferred non-interactive path |
| ACP transport | `grok agent stdio` | Capability `supports_acp=True`; ready only after negotiation receipt |

## Proprietary / closed (do not reverse-engineer)

| Surface | Guidance |
| --- | --- |
| Binary internals / private IPC | Opaque. Invoke only via published `grok` entrypoint |
| Undocumented wire protocols | Do not decode, patch, or redistribute proprietary parsers |
| Device-auth UI / OAuth browser flow | Operator-owned; document `grok login --device-auth`, do not automate secret capture |
| Third-party cracked or mirrored installs | Forbidden — official install URL only |

## Streaming events (legal reuse)

Neyvia only consumes **documented JSON frames** on stdout (NDJSON). The bridge normalizes common shapes into shared Agent Live kinds:

| Raw shape (examples) | Fluxio event |
| --- | --- |
| assistant / message / content deltas | `runtime.model_message` (aggregated) |
| tool_call / tool_use | `runtime.tool` |
| result / done / completed | final text + `runtime.finished` |
| non-JSON lines | `runtime.output` |
| process exit ≠ 0 | `runtime.failed` |

No proprietary packet parsers; unknown keys are ignored.

## ACP vs headless JSON

| | Headless JSON | ACP (`grok agent stdio`) |
| --- | --- | --- |
| Status in Neyvia | **Shipped** via `external_cli_bridge` | **Capability flagged**, negotiation receipt required |
| Auth | API key / gateway profile / ambient env | Same CLI process identity |
| Reuse rule | Documented flags only | Documented stdio agent mode only — no custom ACP client blobs |

NAS discovery (`grok 0.2.106`) also lists related **documented** `grok agent` subcommands/flags (do not scrape binaries):

- `stdio` — ACP over stdin/stdout
- `headless` / `serve` / `leader` — relay/server modes (operator-owned; not yet wired)
- `--xai-api-base-url`, `--cli-chat-proxy-base-url` — API/proxy overrides on the agent entrypoint
- Headless mission path still prefers `GROK_MODELS_BASE_URL` + `XAI_API_KEY` with `--single --output-format streaming-json`

## Pluggable harness adapter (Neyvia)

Profiles live in `.agent_control/harness_profiles.json` (no secrets). Module: `grant_agent.harness_registry`.

| Field | Purpose |
| --- | --- |
| `harnessId` | `grok-build`, `claude-code`, … |
| `baseUrl` | Public gateway URL |
| `credentialEnv` | **Name** of env var holding the key (value never persisted) |
| `credentialKind` | `api-key` vs token (Claude) |
| `model` / `smallModel` | CLI / gateway model aliases |
| `compatibilityMode` | `api-key`, `openai-compatible`, `cliproxy`, `local-proxy`, `xai-native` |

### Point Grok at alternate models

**Option A — xAI API key (no device login)**

```bash
export XAI_API_KEY=xai-...
# optional profile still useful for default model alias
```

**Option B — OpenAI-compatible / CLIProxy-style local proxy**

```json
{
  "id": "grok-open-proxy",
  "harnessId": "grok-build",
  "label": "Grok via local OpenAI-compatible proxy",
  "baseUrl": "http://127.0.0.1:8317/v1",
  "credentialEnv": "XAI_API_KEY",
  "credentialKind": "api-key",
  "compatibilityMode": "openai-compatible",
  "model": "my-open-model"
}
```

Then export the key the proxy expects into `XAI_API_KEY` (or the named `credentialEnv`), and pass `harnessProfileId: "grok-open-proxy"` on chat / mission routes.

Env overlay applied by `harness_gateway_environment`:

- `GROK_MODELS_BASE_URL` ← `baseUrl`
- `XAI_API_KEY` ← value of `credentialEnv` from the process environment
- `FLUXIO_HARNESS_MODEL` / `--model` ← profile model

**Option C — `~/.grok/config.toml` custom `[model.*]`** (operator-managed on the runtime host; Neyvia does not write secrets into TOML).

Claude sibling profiles use `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` the same way — coordinate so Claude and Grok proxy ports do not collide.

### Hooks

1. **Headless JSON** — `external_cli_bridge.build_cli_args` for `grok-build`:

   `grok --no-auto-update [--model …] [--session-id …] [--disallowed-tools Bash,Edit,Write] --single <prompt> --output-format streaming-json`

2. **Profile overlay** — `--workspace-root` + `--harness-profile` on the bridge; web chat via `harnessProfileId`.

3. **Catalog / save profile** — desktop commands `get_harness_catalog_command`, `save_harness_profile_command`.

4. **Doctor** — `nas_runtime_doctor.py` reports `managedCliDetected["grok-build"]` from `grok --version` without probing secrets.

## Sibling managed CLIs (same pattern)

- **Claude Code** — npm `@anthropic-ai/claude-code`; `--print … --output-format stream-json`; gateway via `ANTHROPIC_BASE_URL`.
- **Kimi Code** — npm `@moonshot-ai/kimi-code`; `--prompt … --output-format stream-json` (ACP claimed, unproven until negotiated).

All three share `ManagedCliRuntimeAdapter` + `external_cli_bridge` + optional `harness_registry` profiles. OpenCode / OpenCodeGo remain separate adapters and catalog routes.
