# Decisions

## D-001 Stack: Python 3.12 + SQLite (+ FastAPI later) — 2026-10-10
Context: neatlogs has a first-class Python SDK; the server runs Python 3.12.3. Options: Python, TypeScript.
Choice: Python 3.12, stdlib `sqlite3`, FastAPI for the API/dashboard (T-17). Consequences: one language end to end.

## D-002 No Claude Code; build workflow — 2026-10-10
The owner has no Claude Code subscription. Code is written and tested in Claude chat (sandbox), uploaded to the
server over SFTP, and committed through a supported coding agent (OpenCode) so Entire can capture sessions.
The Entire checkpoint therefore shows the session that applied and committed the code; the authoring/reasoning
happened in Claude chat. This is stated in README/hackathon.md; we do not claim the agent authored the code.

## D-003 Reading the neatlogs trace id — 2026-10-10
`scripts/hello_trace.py` reads the active trace id through the documented `neatlogs.inject_trace_context()`
(W3C `traceparent`). A direct OpenTelemetry `get_current_span()` lookup returned no valid span, so it is not used.
STATUS: CONFIRMED 2026-10-10: the printed id 9f8b58522abae5f0fc5f4ef444ef6b03 matches the dashboard trace URL.
