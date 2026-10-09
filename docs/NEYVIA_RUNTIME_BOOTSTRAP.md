# Neyvia Runtime Bootstrap

Neyvia uses two isolated prefixes on the Saclay NAS:

- Core runtime: `/volume1/Saclay/projects/syntelos/runtime`
- Optional CLIProxyAPI relay: `/volume1/Saclay/runtime`

The core prefix owns Node, Python, OpenClaw, Hermes, Codex, OpenCode,
Claude Code, Kimi Code, and Grok Build. The relay prefix owns only the
CLIProxyAPI executable, its loopback configuration, and its OAuth material.
Startup scripts export both roots with the core `bin` directory first, so a
stale proxy-side copy cannot shadow a core runtime.

## One-time core setup or repair

Run this from the checkout on the NAS:

```bash
python scripts/install_nas_runtime_stack.py \
  --runtime-root /volume1/Saclay/projects/syntelos/runtime \
  --install-all \
  --json
```

The installer obtains the official Node checksum, verifies the archive before
extraction, installs the pinned compatible Node release, and installs every
managed CLI into the isolated prefix. It does not copy provider credentials.

Use a no-change preflight at any time:

```bash
python scripts/install_nas_runtime_stack.py \
  --runtime-root /volume1/Saclay/projects/syntelos/runtime \
  --preflight-only
```

## Optional subscription relay

Official API keys or each provider's official login are the safer defaults.
CLIProxyAPI is an experimental third-party compatibility route. Consumer-plan
credentials used through a third-party relay may be throttled, suspended, or
terminated by the provider. Installation therefore fails closed unless the
operator explicitly acknowledges that risk:

```powershell
python scripts/nas_install_cliproxyapi.py `
  --accept-subscription-relay-risk
```

The installer:

- verifies the pinned release archive by SHA-256;
- stages and atomically replaces the executable;
- keeps rollback copies of the prior binary and configuration;
- binds the service to `127.0.0.1`;
- writes the private environment overlay with mode `600`;
- restores the previous files if the new listener fails health;
- never copies the NAS OAuth token back to Windows.

Neyvia applies relay settings only to a saved harness profile carrying the
current risk-acknowledgement version. Claude Code uses its documented
`ANTHROPIC_BASE_URL` gateway path. Grok Build uses
`GROK_MODELS_BASE_URL`. Kimi Code uses its documented ephemeral
`KIMI_MODEL_*` environment channel, so the relay secret is not written to
Kimi's TOML. Codex uses a separate empty `CODEX_HOME` plus a custom
`model_provider` with the Responses wire API, preventing a copied refresh token
from competing with the direct Codex login.

## Acceptance

Run the runtime doctor:

```bash
export SYNTELOS_RUNTIME_BIN_DIR=/volume1/Saclay/projects/syntelos/runtime/bin
export SYNTELOS_PROXY_RUNTIME_ROOT=/volume1/Saclay/runtime
python scripts/nas_runtime_doctor.py \
  --extra-bin-dir "$SYNTELOS_RUNTIME_BIN_DIR" \
  --extra-bin-dir "$SYNTELOS_PROXY_RUNTIME_ROOT/bin" \
  --json
```

Run the real tool acceptance suite from a machine with the locked toolchain:

```powershell
$env:PYTHONPATH = "src"
python scripts/verify_neyvia_runtime_stack.py `
  --report .agent_control/runtime_proof/runtime-stack-tools.json
```

Acceptance distinguishes executable tools from catalog entries. A tool is
`agent-ready` only after its adapter performs a bounded real operation. Provider
states remain explicit (`ready`, `blocked-auth`, `blocked-balance`,
`blocked-dependency`, `degraded`, or `not-installed`); a detected executable is
not treated as proof of an authenticated model request.
