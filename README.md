# Vigil — fixes payment failures, and proves every fix

Vigil is a payment-operations agent built for neatHack 2026 (Oct 10–12). It watches a **simulated** payment stack, opens incidents for duplicate charges, missing webhooks, stuck or failed payouts and ledger/provider conflicts, investigates them with read-only tools, and acts only through a code-enforced policy gate. A separate verifier, also code, decides whether an incident is resolved. Every decision, gate verdict, action and verification is written to a SHA-256 hash-chained decision chain before the action runs.

All payment data is simulated. No real money, no real customers.

**Status:** the agent, gate, verifier, decision chain, receipts and the reproducible eval exist and are tested. Not built yet: the HTTP API, dashboard, proof page, `make demo` and a public deployment. There is no live URL.

**Authorship:** the code was written and tested in a Claude chat sandbox, then applied and committed on the build server through OpenCode so that Entire could record the sessions. The coding agent did not author the code (see `DECISIONS.md` D-002).

## Try it in two minutes (no keys)

```
make setup
make test           # 177 tests, including the chain tamper tests and the invariant property tests
make eval-check     # replays every committed baseline (v0, v1, v1h, v1h2) from eval/cache and compares chain heads
.venv/bin/python scripts/verify_chain --db data/eval-v1.db --run v1
.venv/bin/python scripts/verify_receipt --db data/eval-v1.db receipts/v1
```

`eval-check` writes the eval chains to `data/eval-<label>.db`; the two verify commands then check the chain of label `v1` against its anchor in `anchors.txt` and every receipt in `receipts/v1` against that chain. `tests/test_chain_tamper.py` edits, deletes, reorders, inserts and truncates rows on a raw connection and asserts that verification fails each time.

## What Vigil does

Incident types the detector opens (plain code, no model): `duplicate_charge` (rules DUP and the looser SUSPECT_DUP that creates the "different order" trap), `missing_webhook`, `stuck_payout` (pending or processing beyond the SLA, or failed) and `evidence_conflict`.

Per incident the agent loop investigates with read tools, proposes one action, and the gate decides. Possible outcomes: **RESOLVED** (only when the verifier confirms the end state), **ESCALATED** (with an evidence packet) or **SKIPPED** (only when the verifier confirms nothing needs fixing). The model saying "done" never closes an incident. Write tools: `issue_refund`, `replay_webhook`, `retry_payout`, `escalate`, all reachable only through the gate and the executor.

## Why you can trust it

- **Policy gate (code):** allowed actions, per-incident and daily caps, idempotency keys, no repeated action, evidence must exist, and a type-specific predicate computed from provider and ledger state. The model's free text and any `untrusted` field never reach it.
- **Independent verifier (code):** re-reads provider and ledger; it never trusts tool responses or the model.
- **Decision chain:** append-only SHA-256 hash chain; `ACTION_INTENT` is committed before any write tool runs. Verify with `scripts/verify_chain`.
- **Receipts:** one JSON per incident with a digest over its payload and the hashes of its chain entries; `scripts/verify_receipt` re-checks them against the chain. The digest detects edits; it is not a signature.
- **Anchors:** the chain head of every eval run is appended to `anchors.txt`. The chain is tamper-evident, not tamper-proof.
- **Invariants:** the eight invariants of the spec (refund caps per day and per incident, one credit per paid charge, balanced ledger, no write without a committed intent, no write derived from untrusted text, refund at most the charge, idempotent replay) are enforced in code and checked by tests: property tests in `tests/test_invariants.py` and the injection tests.

## Results

Live runs of `claude-haiku` through the neatHack gateway; full tables, token counts and failures in [`docs/results.md`](docs/results.md).

| label | scenarios | correct | unsafe actions executed | note |
|---|---|---|---|---|
| v0 | 7 starred | 5/7 (71%) | 0 | baseline; D3 and P3 failed and are kept |
| v1 | same 7 | 7/7 (100%) | 0 | prompt-only fix written after seeing the v0 failures: tuned, not held-out |
| v1h | D2 X1 X5 | 2/3 (67%) | 0 | held-out; X5 failed (the 3-step budget did not bind) |
| v1h2 | P2 X4 X5b | 2/3 (67%) | 0 | held-out; X4 failed (ESCALATED instead of SKIPPED) |

The suite is small, each label is one live run, and `eval-check` only proves that replaying the recorded responses reproduces the committed baselines.

## What is real and what is simulated

| Component | Real or simulated |
|---|---|
| Payment provider, charges, refunds, payouts, webhooks | Simulated (`sim/`) |
| Merchant accounting ledger | Simulated (`sim/`) |
| Agent, policy gate, verifier, decision chain, receipts, eval runner | Real code that really ran (tests, chains, receipts) |
| LLM calls | Real in the live runs (`claude-haiku`); recorded responses in replay (`eval/cache`) |
| neatlogs traces | Real traces from the live runs; ids in `eval/results/<label>.json` |

## How we used the required tools

- **neatlogs:** every live eval run is traced (workflow `vigil-eval-<label>`) and the trace ids are stored in `eval/results`; the v0 failures were found in the recorded runs and drove prompt v1. Span attributes are not attached yet. Public trace links: pending (dashboard links need a login).
- **Entire:** enabled with the OpenCode agent; eight checkpoints are listed in `hackathon.md`. They were created with `entire session attach` and Entire warned that no user prompts were parsed (`FEEDBACK.md` E3, E5, E6).
- **cfo.ai:** account created; the business plan (pricing, costs, revenue, runway) is not written yet. Measured token counts per incident are in `docs/results.md`; no price has been assumed.

## Architecture

- `vigil/` — canonical JSON, decision chain, incident store, detector, tools, gate, verifier, executor, agent loop, receipts, prompt, model adapters, replay and stack builder.
- `sim/` — deterministic simulated provider and double-entry ledger with seeded fault injection.
- `eval/` — scenario files (`eval/scenarios`), runner (`python -m eval.run`), recorded results, baselines and the replay cache.
- `scripts/` — `verify_chain`, `verify_receipt`, `anchor`, `live_smoke.py`. `policy.yaml` holds the caps and limits (amounts are integer minor units, NGN).
- Specification: `docs/SPEC.md`. Decisions: `DECISIONS.md`. Build log: `hackathon.md`. Tool feedback: `FEEDBACK.md`.

## Run it locally

```
make setup                 # venv + requirements
cp .env.example .env       # fill in your own keys; never commit .env
make test
make eval-offline          # deterministic stub model, no key
```

A live run needs the gateway key in `.env` (`LLM_API_KEY`), and a neatlogs project key (`NEATLOGS_API_KEY`) for traces. Use a new label for every live run: `.venv/bin/python -m eval.run --label <new> --mode live --record --only <ids> --anchor`.

## Known limitations and next steps

- Provider and ledger are simulated; the suite is small and each label is a single live run on one model.
- v1 is tuned on the failures it fixes; only v1h and v1h2 are held-out, and X5b was informed by X5. X4 is a failing scenario whose cause has not been analysed.
- Replay of a baseline holds only while the code that builds the model request is unchanged; tool descriptions and schemas are not versioned yet.
- Cost per incident is not computed (no price configured).
- Not built yet: API and SSE, dashboard, `/proof`, `/status`, `make demo`, deployment, evidence pack, cfo.ai plan.

## Built during neatHack

Code and commits are dated inside the event window (Oct 10–12, 2026). Build log: [`hackathon.md`](hackathon.md). Public posts are listed there under "Build in public".

## License

No license has been chosen yet.
