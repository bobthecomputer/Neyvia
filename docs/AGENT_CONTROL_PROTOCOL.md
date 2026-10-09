# Agent Control Protocol

This desktop backend exposes a typed command protocol for safe agent control.

## Command envelope

Commands are JSON objects with a discriminated `command` field and an optional `payload`:

```json
{
  "command": "overlay.set_mode",
  "payload": {
    "modeId": "coding"
  }
}
```

## Supported commands

- `overlay.open`
- `overlay.close`
- `overlay.pin` with payload `{ "pinned": true|false }`
- `overlay.set_mode` with payload `{ "modeId": "coding|youtube|writing" }`
- `context.capture` with payload `{ "clipboard": bool, "activeWindow": bool, "screenshot": bool }`
- `ui.ask` with payload `{ "questionId"?: string, "question": string, "choices": [{ "choiceId": string, "label": string }] }`
- `ui.answer` with payload `{ "questionId": string, "choiceId": string, "customAnswer"?: string }`
- `action.request` with payload `{ "toolId": string, "args": object, "source"?: string }`

## Response shape

All protocol execution paths return:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

If `ok` is `false`, `error` contains a human-readable reason.

## Safety behavior

- Tool execution is mode-gated by explicit allowlists.
- High-risk tool requests become approval requests and emit question bubbles.
- No destructive action is executed without explicit approval.

## OpenClaw gateway bridge

- Inbound gateway events are validated before execution (`clarify`, `action.request`, `agent.message`).
- Inbound gateway events are validated before execution (`clarify`, `action.request`, `agent.message`, `ack`).
- Rejected/unparsed events are audited and emitted to UI diagnostics (`openclaw://rejected`, `openclaw://raw`).
- `ui.answer` responses for gateway-origin questions are sent back to OpenClaw (`type: ui.answer`).
- `action.request` outcomes are sent back to OpenClaw (`type: action.result`) for both immediate and approval-resolved paths.
- Outbound gateway payloads are queued while offline and replayed on reconnect.
- Recent event-id history is used to suppress duplicate inbound gateway events.
- Outbound gateway payloads include `messageId`, `nonce`, `sentAt`, and `integrity` fields.
- Ack-tracked outbound messages stay pending until a matching `ack` event clears them.
- Prompt forwarding includes task-routing hints (`taskType`, `taskRouting`, `verification`) so the gateway can pick different models per workload.
