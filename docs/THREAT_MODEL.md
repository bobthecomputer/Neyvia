# Threat Model (Desktop Overlay)

## Scope

This model covers the local Tauri desktop runtime, localhost automation API, OpenClaw gateway link, and tool execution path.

## Assets

- User prompts and transcripts
- Context payloads (clipboard, active window metadata, optional screenshot reference)
- Approval decisions and audit logs
- OpenClaw gateway credentials

## Trust boundaries

- UI <-> backend command boundary
- localhost clients <-> backend boundary
- backend <-> OpenClaw local gateway boundary
- backend <-> external command execution boundary

All tools/skills/plugins are treated as untrusted by default.

## Main risks and mitigations

1. **Untrusted tool execution**
   - Mitigation: per-mode allowlists and explicit tool gating
   - Mitigation: high-risk tools require explicit approval
   - Mitigation: node command execution uses exact allowlist matches (no wildcards)

2. **Destructive actions without consent**
   - Mitigation: destructive tool IDs route to pending approval records
   - Mitigation: question bubbles capture user decision before execution

3. **Credential leakage**
   - Mitigation: OpenClaw token stored in OS keychain via `keyring` (encrypted at rest)
   - Mitigation: provider credentials are stored in OS keychain per provider id
   - Mitigation: tokens are never written to plaintext config files

4. **Silent/opaque agent activity**
   - Mitigation: append-only JSONL audit log for key actions and decisions
   - Mitigation: structured events emitted for UI visibility
   - Mitigation: OpenClaw reconnect/error/rejection events are audited for post-incident analysis
   - Mitigation: OpenClaw ack telemetry tracks pending/unacked outbound messages

5. **Over-capture of user context**
   - Mitigation: context capture is trigger-based only (never continuous)
   - Mitigation: screenshot capture remains explicit and gated

## Residual risk

- If no localhost API token is configured, local processes on the same machine can call the API.
- Allowlisted external commands may still run harmful subcommands if the allowlist is too broad.
- OpenClaw replay protection now includes event-id dedupe, nonce/integrity envelope fields, and ack-tracked outbound replay.

## Recommended hardening next

- Rotate localhost API token periodically and scope token distribution.
- Add stricter per-tool arg validation and command timeout/output quotas.
- Upgrade integrity checksum to shared-secret/HMAC verification between desktop and gateway.
- Add encrypted transcript-at-rest option.
