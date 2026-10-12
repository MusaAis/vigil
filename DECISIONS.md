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

## D-011 SUSPECT_DUP detector rule and eval-runner choices — 2026-10-10
SUSPECT_DUP (SPEC 12.2 trap D3): same customer and amount but a DIFFERENT order_ref within the window.
It is looser than DUP on purpose: the trap must open an incident so the eval exercises the agent and the
gate, instead of trivially reporting NO_INCIDENT. The gate still refuses any refund on such an incident
(DUP does not hold -> NOT_DUPLICATE; `test_suspect_dup_never_allows_a_refund`), so the rule cannot cause
an unsafe write. Consequence: `test_daily_cap_binds_when_many_duplicates_are_refunded` now filters
`detector_rule == "DUP"` because SUSPECT_DUP also fires for those same-customer orders.
Eval choices where SPEC is silent: all scenarios of one run share one decision chain (`data/eval-<label>.db`)
and one virtual clock, each on a fresh simulated world; incident ids stay unique via an `IncidentStore`
offset; replay reuses the baseline's trace ids (FixedTracer) so the chain hashes identically and no new
neatlogs traces are created; the replay cache stores only the proposal and token counts (never request
text, keys or headers); percentages are integers rounded half up with counts stored alongside; cost is
computed only when `LLM_PRICE_IN/OUT_USD_MICRO_PER_MTOK` are set.

Update 2026-10-11 (to D-004): eight Entire checkpoints now exist, all created with `entire session attach` (see hackathon.md for ids and commits). Entire still warns that no user prompts were parsed (FEEDBACK E6).
Update 2026-10-11 (to D-009): tool-calling through the gateway is verified (live eval runs v0, v1, v1h, v1h2 and `make live-smoke`). neatlogs span attributes are still not attached. `DAILY_LIVE_BUDGET_TOKENS` caps tokens per run, not per day.

## D-012 Prompt versioning and replay — 2026-10-11
The system prompt is part of the replay cache key, so editing it would break replay of every earlier baseline. `vigil/prompt.py` therefore keeps `PROMPT_V0` verbatim (hash-tested)
and adds `PROMPT_V1` as the default. Baselines store `prompt_version` (older ones default to v0) and replay uses it. A prompt change needs a new label.
Known gap: tool descriptions and schemas are not versioned, so changing them would also break replay of existing baselines.

## D-013 Anchors are checked per run label — 2026-10-11
`append_anchor` and `scripts/verify_chain --run <label>` only compare the anchors of that run label. Before this fix, appending the v1 anchor was checked against the v0 anchor
and failed because the two runs have different chains. Each eval run has its own chain database (`data/eval-<label>.db`, not committed) and its own anchor line in `anchors.txt`.

## D-014 Eval harness: per-scenario max_steps, replay scope, mid-run hook — 2026-10-11
- A scenario may set `max_steps`. It is not part of the replay cache key, so existing baselines are unaffected.
- Replay runs exactly the scenarios listed in the baseline, so later catalogue additions never break `make eval-check` for older labels.
- A scenario may declare `mid_run` steps (`after_read_calls`, `op` in settle_payout, fail_payout, inject_ledger_credit). Each applies once, right after the agent's Nth read-tool call returns.
  The trigger counts read calls only, so it is deterministic for a given sequence of model proposals (live, replay and offline). Used by X4.

## D-015 Failed payouts open an incident (deviation from SPEC 4) — 2026-10-11
SPEC 4 opens `stuck_payout` only for pending or processing payouts older than the SLA. A payout already `failed` at the provider opened nothing, although the gate (SPEC 6.2 check 8) and the verifier already treat it as retryable.
Choice: the detector also opens `stuck_payout` for a `failed` payout, with no age requirement, and `confirm_no_action` returns not-ok while the payout is failed. The gate is unchanged.
Cost: a failed payout the provider will never accept again still opens an incident; the agent can only retry or escalate. Covered by `test_failed_payout_opens_an_incident_without_waiting_for_the_sla` and `test_failed_payout_is_not_confirmed_as_no_action_until_it_is_paid`; scenario P2.

## D-016 Reporting rules for held-out scenarios, and scenarios not built — 2026-10-11
- Held-out means: the prompt was not changed after seeing the scenario. D2, X1, X5 (label v1h) and P2, X4, X5b (label v1h2) were run with prompt v1 unchanged. v1 itself was tuned on the v0 failures of the same 7 starred scenarios, so it is not held-out.
- X5b was written after X5 showed that a 3-step budget did not bind, so it is informed by that result and not a blind test.
- A label is never overwritten and failures stay in `eval/results` and `eval/baselines`: X5 (v1h) and X4 (v1h2) failed and are kept as recorded.
- W2 (webhook delivered twice) and P1 (payout within the SLA) are not eval scenarios because the correct behaviour is that no incident opens; they are covered by detector unit tests.
  X6 (same refund proposed twice) cannot occur through the loop because a verified refund closes the incident; the gate's DUPLICATE_ACTION check is covered by the gate and invariant tests.

## D-017 Web app: FastAPI + Jinja2, logic outside the framework, port 8005 — 2026-10-11
- Choice: FastAPI and uvicorn for HTTP, Jinja2 for server-rendered pages (they work without JavaScript; only the live log uses a few lines of JS). All logic is in `vigil/web/service.py` (plain functions returning dicts, one per endpoint); `api/app.py` is a thin wrapper. Reason: every number and link can then be tested without the framework (tests in `tests/test_web_service.py`, wrapper checked with FastAPI's TestClient in `tests/test_web_app.py`).
- Deviation from the handoff plan: `make serve` uses a `PORT` variable, default 8005, because port 8000 was already in use on the build server.
- The public surface is read-only: no endpoint accepts free text, incident ids must match `^inc_[0-9a-z]+$`, the OpenAPI and docs pages are off.

## D-018 What the web app serves — 2026-10-11
- It opens its own chain database (`VIGIL_DB_PATH`, default `data/vigil.db`, not committed) and, only when that database is missing or empty, seeds it with D1, D3 and D2 using the offline stub model and a virtual clock (`vigil/demo.py`). Reason: no key, no cost, reproducible hashes (the head is the same on the sandbox and on the server).
- Consequence: incidents on the dashboard say nothing about LLM quality. LLM numbers on `/proof` come only from `eval/results`. An existing database is never replaced (delete `data/vigil.db*` and `receipts/web/` by hand if the scenarios change); an unreadable database is reported as `ok: false`, not replaced.
- The whole chain is verified from genesis at startup and again every five minutes in a background thread; `/api/health` reports `ok: false` if it fails. Reads use read-only SQLite connections.

## D-019 Proof, metrics and health details — 2026-10-11
- `snapshot_sha256` (of `/api/proof` and `/api/metrics`) covers `data` only; time stamps sit outside it, so the hash changes only when the content changes.
- Every metric has a `boundary` string. Eval metrics sum over every file in `eval/results`; the incident and gate-denial counters count the demo chain only, and say so.
- `/api/health` `built_at` is the time of the HEAD commit, and `llm` is `offline-stub` because the web app never calls a model.
- `/proof` counts test functions from the test sources (not a run result); CI and the last CI result render PENDING; evidence rows render PENDING unless they have status ok and an https URL (`docs/evidence.json` was added in T-21, D-024).
- `make verify` checks `data/vigil.db` with `--run demo` (the anchors of the eval labels do not apply to that chain) and the receipts in `receipts/web` when they exist.
- The dashboard exposure meter is computed from the demo chain and its receipts (peak refunded per virtual day against the daily cap, most write actions in one incident). `/api/exposure` (Tier B) is not built.

## D-020 Web redesign: overview page, chain ribbon, system fonts only — 2026-10-11
- `/` is an overview page instead of a redirect: the real chain as one cell per entry (each links to its entry), a legend of the kinds present, how a fix is made, eval runs, the verify commands and limits. Every number and command is built from files or the chain (the verify commands from the repository URL).
- Pages stay self-contained: no external fonts, scripts or images; light and dark by `prefers-color-scheme`. The only JavaScript is the dashboard live log, written with `textContent` (a test fails on `innerHTML`). Ribbon colours are scoped to `.cell` and `.legend i` so timeline classes cannot collide (a test guards it).

## D-021 Batch 8: demo, verify, anchor, evidence, CI — 2026-10-11
- `make demo` runs `python -m vigil.demo` (offline, virtual clock, writes `data/demo.db` and `receipts/demo/`). `make verify` checks every chain database present against the anchors of its own run label, plus its receipts, and fails when there is nothing to verify. `make anchor RUN=<label>` wraps `scripts/anchor`. `make evidence` runs `scripts/check_evidence`.
- `.github/workflows/ci.yml` (SPEC 14) runs setup, test, invariants, eval-check, verify and demo on every push; it uses no secrets because the eval check replays committed recordings.

## D-022 Deployment on one host behind nginx — 2026-10-11
- The whole app (FastAPI, SQLite) runs on the build server as the systemd unit `vigil.service` on 127.0.0.1:8005, behind a separate nginx site with a certbot certificate for a DuckDNS host name. This replaces the earlier Caddy plan: nginx already served other sites on the host, so Vigil is one more site (other sites' files are never touched; `nginx -t` before every reload). Pages are server-rendered and the stream is on one origin, so there is no CORS.
- The app never replaces an existing `data/vigil.db`: after a scenario or model change, stop the service, delete `data/vigil.db*` and `receipts/web/`, then start it.

## D-023 Vercel front as a thin proxy — 2026-10-11
- `deploy/vercel/vercel.json` has one catch-all rewrite to the public instance and holds no code, environment or secrets (`tests/test_deploy.py` checks the folder). Reason: no second frontend to maintain, no CORS, and the no-JavaScript pages keep working. Not verified: the proxy itself, and whether the event stream passes through it.

## D-024 Evidence pack generated from files; CI needs history — 2026-10-12
- `docs/evidence.json` is the only hand-edited evidence source (real https URLs only; anything else is `pending` with a null URL). `docs/submission.md` and `docs/business-plan-inputs.md` are generated from it, `eval/results`, `anchors.txt` and the git root commit by `make render`, and a test fails when the committed copies are stale. `scripts/check_evidence` fails on an ok row without an https URL, a bad status, a pending row with a URL, or a missing required claim.
- Rows that carry only part of a claim say so in `kind` (for example eval numbers for "agent improved"; the trace rows stay pending). Cost per incident is not computed and no token price is assumed.
- The first CI run of T-21 failed because a default checkout is shallow and the "first commit" is then HEAD. `_root_commit` now returns nothing for a shallow clone, the staleness test compares the rest of the file in that case, and the workflow checks out full history.
