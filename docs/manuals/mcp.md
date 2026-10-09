# Outbound MCP

## State observers
- `mcp.servers` returns configured transport/auth state, catalog and resource revisions, readiness, and drains the latest 128 incoming notifications per server.
- `mcp.search` discovers every page of a callable server's tool catalog and refreshes it after `notifications/tools/list_changed`.

## Typed actions
- `mcp.describe` takes `server` and `tool` to return that tool's schema after discovery.
- `mcp.call` takes `server`, `tool`, and `arguments`; mutations additionally require `approved` and can attach an `approvalId` and `missionId`.

## Executable checks
- `mcp.search` with `server` and an empty `query` returns a bounded selection from the complete catalog, without schemas.
- `mcp.servers` exposes incoming resource, progress and readiness notifications rather than discarding them.
- `node scripts/verify-fixwave-mcp.mjs` runs real HTTP sessions on 47962/47963 and a stdio subprocess, asserting pagination, notification refresh, errors, approval gates and session renewal.

## Procedures
- Use `mcp.servers`, then `mcp.search`, then `mcp.describe`, then `mcp.call`; schemas stay deferred until requested.
- Configure a plain `url` or `transport: streamable-http` in the existing broker configuration; optional static `headers` or `http_headers` stay in that configuration, outside model-visible discovery.
- Plain HTTP Codex config rows use the same broker via `CodexPluginAccess.search`, `.describe`, and `.call`; unresolved placeholders, OAuth and app-host transports remain adapter-required.

## Judgement points
- A configured callable transport is not proof of remote authentication; `mcp.call` records the actual call result or auth/approval barrier.
- A catalog that changes repeatedly during discovery fails explicitly; retry `mcp.search` after the server stabilizes.

## Pitfalls
- `mcp.search` returns at most 20 selected tools even though its cached catalog follows all pages.
- `mcp.servers` drains notification history; catalog/resource revisions persist and the queue is bounded.
- `notifications/resources/updated` records a resource revision; fetching a resource still needs its own supported tool.

## Frontier
- Legacy 2024 HTTP+SSE endpoints, OAuth login, sampling and elicitation are unsupported; unsupported HTTP client requests receive a JSON-RPC method-not-supported response.
- SSE reconnects currently do not replay event IDs, so disconnection does not guarantee delivery of every event.
