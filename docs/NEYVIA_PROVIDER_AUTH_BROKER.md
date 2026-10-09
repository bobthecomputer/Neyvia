# Neyvia provider-scoped authentication

## Contract

Authentication is shared per provider, not across unrelated providers.

- One OpenAI Codex OAuth login is owned and refreshed by the loopback
  CLIProxyAPI broker.
- Codex, Hermes, OpenClaw, Claude Code's OpenAI-compatible route, Kimi Code,
  Grok Build, and OpenCode consume the broker endpoint and its local client
  credential.
- Consumers do not receive or copy the upstream OAuth refresh token.
- Other providers keep independent login or API-key ownership.

Rotating OAuth refresh files must never be copied between Codex, OpenClaw,
Hermes, and CLIProxyAPI. Multiple refresh owners can produce
`refresh_token_reused` and invalidate every copy.

## Provider policy

OpenAI Codex OAuth is supported as the OpenAI login source. CLIProxyAPI remains
a third-party compatibility component, so the UI labels it accurately without
showing the Anthropic-specific consumer-subscription warning.

Anthropic Free, Pro, and Max credentials are not routed through a third-party
proxy. Claude Code must use official Claude login, an Anthropic API key,
Bedrock, Vertex, Foundry, or an approved Anthropic-compatible gateway. Neyvia
blocks a profile explicitly marked `anthropic-subscription`.

Hermes has a separate native Anthropic OAuth route in its own CLI. Neyvia's
**Hermes / Claude Max** connection delegates sign-in and token storage to that
CLI; it does not enable subscription credentials in Neyvia's proxy or native
Anthropic adapter. Hermes documents that this route requires Claude Max plus
purchased extra-usage credits and does not work with Claude Pro.

API-key and approved enterprise-gateway routes do not use consumer
subscription credentials.

## Runtime roles

Neyvia's OWN runtime is the provider-independent control layer. It owns
planning, policy, native tools, receipts, durable mission state, and
verification. It is not another language model and does not claim to be
intrinsically smarter than Codex, Hermes, Claude Code, or OpenClaw.

The external CLIs are supervised execution workers. Neyvia does more at the
cross-runtime control and evidence layer; each CLI can still do things Neyvia
delegates to it, such as Claude Code's native `Agent` subagent tool.

## Setup and acceptance

Run:

```text
python scripts/configure_nas_provider_auth_broker.py
python scripts/verify_nas_provider_cli_spawns.py
python scripts/verify_neyvia_runtime_stack.py
```

The setup script:

1. backs up every changed runtime/configuration file;
2. writes provider and auth-mode markers to the private runtime environment;
3. updates existing CLIProxy harness profiles to `openai` + `codex-oauth`;
4. configures OpenClaw's `neyvia-openai` provider with an environment
   reference, not a copied token;
5. retires stale direct Codex auth and removes copied OpenAI entries from
   Hermes while preserving unrelated providers.

The spawn verifier requires real model markers from OWN, Codex, Hermes,
OpenClaw, Claude Code, Kimi, Grok, and OpenCode. Its Claude proof additionally
requires an `Agent` tool-use event, `task_started`, a child marker, and the
parent marker. Cursor is reported separately because OpenAI Codex OAuth does
not authenticate Cursor.
