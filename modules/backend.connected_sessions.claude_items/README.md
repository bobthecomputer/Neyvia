# claude_items

Pure helpers that turn Claude Code data into connected-session items.

- **Public API:** `agent_shell`, `answers_by_id`, `apply_tool_result`, `attachment_dict`, `bound_output`, `bound_text`, `classify_user_text`, `collapse`, `context_used`, `edit_diff`, `flatten_result_content`, `folder_name`, `helper_reports`, `image_token`, `int_or_none`, `is_harness_cwd`, `mcp_parts`, `now_iso`, `parse_identity`, `parse_time`, `question_data`, `ref_token`, `session_identity`, `session_origin`, `task_notification`, `text_media_refs`, `tool_category`, `tool_data`, `tool_files`, `tool_title`, `valid_session_id`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `providers.claude.category`, `providers.claude.classify`, `providers.claude.identity`, `providers.claude.origin`, `providers.claude.output`, `providers.claude.title`, `transparency.helper-reports`.
- **Dependencies:** [backend.connected_chat_media](../backend.connected_chat_media/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.connected_sessions.transparency](../backend.connected_sessions.transparency/README.md), [backend.external_chat_inventory](../backend.external_chat_inventory/README.md), [backend.proofs_a_providers](../backend.proofs_a_providers/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/claude_items.py](../../src/grant_agent/connected_sessions/claude_items.py).
