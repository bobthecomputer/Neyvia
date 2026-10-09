# Native request context repair — 2026-09-28

The affected OpenCode Go / deepseek-v4.1-flash session was rejected with HTTP 400: prompt 1,052,286 tokens, maximum context 1,048,571. This was a per-request context limit, not a subscription quota. No original task tool actions were replayed during diagnosis.

Model input now selects recent complete user exchanges, preserving tool call/result pairs and exact authored system instructions. Earlier records remain in the durable session database and UI. A continuity notice tells the model that older work exists and to check receipts before repeating actions. The filter targets 240,000 serialized characters and 400 records; the current exchange is always retained, so a single exceptionally large exchange can still exceed this target. Such provider rejections now report context_window_exceeded rather than a generic executor failure.

Live verification: replay of the affected history was rejected before the fix; bounded replay omitted 1,131 older records from the request (not storage) and returned NEYVIA_CONNECTION_OK from the same provider/model. Focused contract checks passed. All six existing Native streaming scenarios passed, covering Responses and Chat Completions, tool roundtrips, failed tools, provider failure, and competing-system-prompt rejection.

Original source and a SQLite-consistent session backup are stored under .agent_control/backups/request-context-20260928. No model/provider fallback was used.

Installed-runtime proof: the installed Python backend streamed NEYVIA_CONNECTION_OK and completed using a disposable copy of the affected session with the same DeepSeek model/provider and exact saved system instructions. Its receipt reports 1,131 omitted replay records, one validated instruction-contract call, and no recovery error. Mutations were disabled and the original task was not resumed. The original session remained unchanged.
