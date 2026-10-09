# neyvia_comments

Workspace comments: immutable events, derived current view and real session delivery.

- **Public API:** `Store`, `anchor`, `call`, `changed`, `compose`, `deliver`, `listing`, `mutate`, `send`, `text`, `neyvia.comments.add`, `neyvia.comments.list`, `neyvia.comments.resolve`, `neyvia.comments.send`.
- **Manual:** [comments.cl](../../manuals/cl/comments.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `comments.append-only`, `comments.send`.
- **Dependencies:** [backend.claude_code_host](../backend.claude_code_host/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / comments.
- **Files:** [src/grant_agent/neyvia_comments.py](../../src/grant_agent/neyvia_comments.py).
