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

## D-004 Entire + OpenCode capture problem — 2026-10-10 (PARTLY RESOLVED)
Symptom: commit `dc0b24d` was made through OpenCode 2.0.26, but Entire shows 0 checkpoints and "No sessions".
`entire session attach` fails with "OpenCode could not export session". OpenCode 2.0.26 has `opencode session export`
but no top-level `opencode export`. Hypothesis: Entire's integration calls the old command.
Update 14:00: the shim worked: batch 1 -> checkpoint 01M4JHV41G3A3SRKC5C8ETWGWY, batch 2 -> 01M4JYYS4PAB86K9FFD5E9F6FE. Still open: the second checkpoint was created with a 'no user prompts parsed' warning; asking organisers (#neathack-help) whether that is acceptable evidence. Fallback if not: switch to another Entire-supported agent for later commits.
Update 14:37: the duplicate trailer on the batch-2 commit was removed by amending; both checkpoints appear in `entire checkpoint list` and the checkpoint refs were pushed to origin together with main.
Original plan: try a one-command shim (`opencode export` -> `opencode session export`) for `attach`; if that fails, switch to
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

## D-007 Property tests use seeded `random`, not Hypothesis — 2026-10-10
The sandbox that builds the code has no network, so Hypothesis could not be installed or run. `tests/test_invariants.py`
generates adversarial proposal streams with `random.Random(seed)`: every failure is reproducible from its seed and there
is no extra dependency. `VIGIL_PROP_CASES` raises the case count (`make invariants` uses 300).
The tests found two real defects, both fixed: (1) the gate raised on malformed arguments (missing or mistyped fields,
unhashable ids, non-iterable evidence) and could ALLOW an `escalate` whose arguments the tool layer then rejected;
(2) a second `escalate` on a closed incident leaked a raw RuntimeError across the tool boundary (SPEC 2.6).
Changes: the gate returns `DENY INVALID_ARGUMENT` for non-object arguments and, after check 5, for arguments that fail the
tool schema; `escalate` arguments are schema-checked before the always-allow rule; `pos_int` is capped at 2^53; writing
`escalate` to a closed incident returns `INCIDENT_CLOSED`. Check order 1-11 is otherwise unchanged.
Known overlaps found by mutation checks: removing `REFUND_EXCEEDS_CHARGE` is masked by `ALREADY_REFUNDED`, and removing the
duplicate-delivery ignore in the simulator is masked by the ledger's idempotency key. Both are independent guards.
INV-3 is checked per charge (each charge credited at most once); a duplicate pair legitimately has two credits until refunded.

## D-008 Agent loop choices where SPEC is silent — 2026-10-10
- Each read appends `DECISION(INVESTIGATE)` then `OBSERVATION`, so every step has a rationale in the chain.
- `OBSERVATION` carries two extra fields, `untrusted_fields` and `injection_suspected` (a regex flag, never an input to any decision). Untrusted text itself is never written to the chain.
- A skip appends a `VERIFICATION` entry (`no_action_needed`); an escalation appends one too (`verify_escalation`).
- Code-initiated escalations (gate ESCALATE verdict, exhausted step budget) go through the same gate and ACTION_INTENT path as any write.
- A model-proposed `escalate` keeps only evidence refs that exist, falling back to the incident's related ids; the DECISION entry records `args_normalized`.
- Unknown tools, malformed arguments and responses with no tool call are logged and fed back; they never reach a write tool.
- The model sees `untrusted` blocks (as SPEC 7.4 expects) and is told not to follow them; the gate and verifier cannot read them.

## D-009 Live model adapter and tracing — 2026-10-10 (plain call verified 2026-10-10; tool-calling and neatlogs spans still unverified)
`vigil/llm.py` talks to an OpenAI-compatible endpoint (the event LiteLLM gateway) with `tool_choice="auto"`, temperature 0.
Key variable: `LLM_API_KEY`, with `LITELLM_API_KEY` as a fallback name. Default model `claude-haiku`. Not yet run against the
real endpoint from the build sandbox (no key there); tests use a fake client. `make live-smoke` makes one real call from the server.
Configuration is read from the environment; `.env` is loaded by a small built-in loader that never overrides values already set in the shell.
`vigil/tracing.py` uses only SDK calls documented in the neatlogs setup guide (`init`, `span` with kinds WORKFLOW, AGENT, TOOL,
`inject_trace_context`, `flush`, `shutdown`). Span attributes (`incident_id`, `scenario_id`, `run_label`, `outcome`, `git_sha`)
are NOT attached yet: the exact SDK call is still to be read from the docs. Without a key the agent runs untraced with ids `offline-<n>`.

## D-010 Receipt cross-checks beyond SPEC 10 — 2026-10-10
`verify_receipt` also recomputes each listed entry's hash from the stored chain row and compares outcome, verification result
and action hashes with the chain. A receipt that is edited and re-digested therefore still fails. Each action also records
`executed`. The digest still detects edits only; it is not a signature.
