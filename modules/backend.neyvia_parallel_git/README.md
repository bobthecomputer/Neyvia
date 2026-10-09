# neyvia_parallel_git

Git effects for Parallel; all removal is confined to this run's worktree root.

- **Public API:** `ahead`, `clean`, `conflict_sides`, `git`, `merged`, `owned_worktree`, `remove_worktree`, `unlink_reparse_points`, `verify_resolution`, `worktree_status`, `worktrees`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.orphan-settle`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_parallel_git.py](../../src/grant_agent/neyvia_parallel_git.py).
