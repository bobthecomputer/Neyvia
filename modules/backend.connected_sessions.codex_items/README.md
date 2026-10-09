# codex_items

Map Codex app-server records to connected-session shapes.

- **Public API:** `attachment`, `capabilities_for`, `classify_origin`, `clip`, `clip_tail`, `context_from_rollout`, `context_from_usage`, `diff_from_changes`, `iso_from_ms`, `iso_from_seconds`, `make_seq`, `map_thread_item`, `map_turns`, `media_refs_of_item`, `media_token`, `one_line`, `ordinal_from_seq`, `permission_mode_for`, `permission_modes`, `plan_from_rollout`, `plan_item`, `project_name`, `public_request`, `rate_limits_from_rollout`, `read_tail_rows`, `relative_path`, `rollout_activity`, `server_request_result`, `session_id_for`, `status_from_thread`, `strip_context_wrappers`, `strip_extended_prefix`, `summarize_thread`, `thread_permission_params`, `thread_title`, `turn_end_items`, `turn_permission_params`, `user_content`, `uuid7_ms`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.codex-threads`, `p22.sessions.codex-transcript-journal`, `sessions.codex.diff`, `sessions.codex.media`, `sessions.codex.origin`, `sessions.codex.permissions`, `sessions.codex.requests`, `sessions.codex.rollout`, `sessions.codex.sequence`, `sessions.codex.text`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_app_chats](../backend.connected_app_chats/README.md), [backend.connected_chat_context](../backend.connected_chat_context/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.connected_sessions.transparency](../backend.connected_sessions.transparency/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/connected_sessions/codex_items.py](../../src/grant_agent/connected_sessions/codex_items.py).
