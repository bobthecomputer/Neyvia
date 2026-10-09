# Claude Code integration boundary

Neyvia invokes the official `claude` executable as a user-owned child process.
It does not extract, copy, translate, or reuse OAuth tokens from Codex, ChatGPT,
or another subscription product.

## Supported authentication

- Official Claude Code login with a Claude subscription or Anthropic Console.
- `ANTHROPIC_API_KEY` supplied to the child process by the operator.
- Amazon Bedrock or Google Vertex AI using Claude Code's documented flags and
  ambient enterprise credentials.
- An operator-owned gateway that implements Anthropic's Messages API and uses
  its own gateway credential. A custom base URL must use the explicit
  `anthropic-gateway` or `enterprise-gateway` profile mode.
- An explicit `cliproxy` profile may launch the official Claude Code executable
  against Neyvia's loopback-only CLIProxyAPI service. CLIProxyAPI owns its
  upstream provider authentication; it is never reported as a Claude account.

Generic OpenAI-compatible URLs remain rejected because Claude Code needs an
Anthropic Messages-compatible client route. The narrowly named CLIProxyAPI mode
is accepted only on loopback and uses a separate private client credential.

## Execution constraints

Neyvia uses Claude Code's documented non-interactive JSON transport. A regular
chat turn is read-only, limited to eight turns, and exposes only Read, Glob, and
Grep. A user-authorized mission is limited to 24 turns and exposes Read, Glob,
Grep, Edit, Write, and Bash. Neyvia keeps artifact custody, permissions,
orchestration state, identity, durable memory, and evidence capture outside the
Claude subprocess.

## Operator setup

1. Install the official package: `npm install -g @anthropic-ai/claude-code`.
2. Use `claude auth login`, an Anthropic API key, Bedrock, or Vertex.
3. Verify with `claude auth status` and `claude --version`.
4. Select Claude Code in Neyvia and run a bounded read-only conversation before
   authorizing file-editing missions.

For another-model route, keep plain `claude` unchanged, authenticate
CLIProxyAPI's chosen upstream separately, and select the visible CLIProxyAPI
profile (or use the `claudex` wrapper).

Official references:

- https://docs.anthropic.com/en/docs/claude-code/getting-started
- https://docs.anthropic.com/en/docs/claude-code/cli-usage
- https://docs.anthropic.com/en/docs/claude-code/llm-gateway
