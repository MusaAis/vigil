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

## D-004 Entire + OpenCode capture problem — 2026-10-10 (OPEN)
Symptom: commit `dc0b24d` was made through OpenCode 2.0.26, but Entire shows 0 checkpoints and "No sessions".
`entire session attach` fails with "OpenCode could not export session". OpenCode 2.0.26 has `opencode session export`
but no top-level `opencode export`. Hypothesis: Entire's integration calls the old command.
Plan: try a one-command shim (`opencode export` -> `opencode session export`) for `attach`; if that fails, switch to
another Entire-supported agent. Logged as E2/E3 in FEEDBACK.md. Not claimed fixed until a checkpoint ID exists.

## D-005 Choices where SPEC is silent (batch 2) — 2026-10-10
- `order_ref` equals the order's id (`ord_NNNN`) so it satisfies the ID regex used for tool arguments.
- Idempotency-key action names: `issue_refund` -> `refund`, `replay_webhook` -> `replay`, `retry_payout` -> `retry`
  (key format `<incident_id>:<action>:<n>`, n >= 1).
- Gate code `ALREADY_REFUNDED` when the charge is already fully refunded; a refund of a charge that is not succeeded,
  has no duplicate mate, or is not the later charge returns `NOT_DUPLICATE`; unknown charge -> `EVIDENCE_NOT_FOUND`.
- Check 5 returns `MISSING_IDEMPOTENCY_KEY` for both a missing and a malformed key (SPEC names only that code).
- Per-incident refund total is derived from provider refunds whose idempotency key starts with the incident id.
- Incident dedup is by (type, sorted related ids) for the life of the store, including terminal incidents.

## D-006 Free text can never reach trusted code — 2026-10-10
Customer memos and webhook notes live in a separate untrusted store. Detector, gate and verifier only receive a
`TrustedView` that has no method returning them; read tools expose them only under an `untrusted` key. Tests compare
detector and gate output with and without an injection string and require identical results (INV-6).
