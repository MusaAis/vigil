# Vigil — fixes payment failures, and proves every fix

Vigil is a payment-operations agent built for neatHack 2026 (Oct 10–12). It watches a **simulated** payment stack, opens incidents for duplicate charges, missing webhooks, stuck or failed payouts and ledger/provider conflicts, investigates them with read-only tools, and acts only through a code-enforced policy gate. A separate verifier, also code, decides whether an incident is resolved. Every decision, gate verdict, action and verification is written to a SHA-256 hash-chained decision chain before the action runs.

All payment data is simulated. No real money, no real customers.

**Status:** the agent, gate, verifier, decision chain, receipts, the reproducible eval, a read-only web app (overview, dashboard, proof, status, JSON API, live decision stream), `make demo`, CI and an evidence pack exist and are tested. The app is deployed at **https://vigil-xyz.duckdns.org** (all data simulated). Not done: the cfo.ai business plan, public links to the neatlogs traces, cost per incident (no token price supplied), and the Tier B items (`/try`, `/api/exposure`).

**Authorship:** the code was written and tested in a Claude chat sandbox, then applied and committed on the build server through OpenCode so that Entire could record the sessions. The coding agent did not author the code (see `DECISIONS.md` D-002).

## Try it in two minutes (no keys)

```
make setup
make test           # 266 tests, including the chain tamper tests, the invariant property tests, the web app and evidence tests
make eval-check     # replays every committed baseline (v0, v1, v1h, v1h2) from eval/cache and compares chain heads
make demo           # offline and SIMULATED: seeds a chain with D1, D3 and D2, writes receipts, verifies the chain and every receipt
make verify         # verifies every chain database present against its own anchors, plus its receipts
make evidence       # checks docs/evidence.json (an ok row needs an https URL; pending rows are listed)
.venv/bin/python scripts/verify_chain --db data/eval-v1.db --run v1
.venv/bin/python scripts/verify_receipt --db data/eval-v1.db receipts/v1
```

`eval-check` writes the eval chains to `data/eval-<label>.db`; the two verify commands then check the chain of label `v1` against its anchor in `anchors.txt` and every receipt in `receipts/v1` against that chain. `tests/test_chain_tamper.py` edits, deletes, reorders, inserts and truncates rows on a raw connection and asserts that verification fails each time.

## The web app (read-only, simulated)

The public instance is https://vigil-xyz.duckdns.org. `make serve` starts it on `127.0.0.1:8005` (change the port with `make serve PORT=...`). On first start it seeds its own chain database (`data/vigil.db`, not committed) with three simulated scenarios (D1 resolved, D3 skipped trap, D2 escalated cap case) decided by the deterministic **offline stub model on a virtual clock**, so the dashboard costs nothing and needs no key. These incidents say nothing about LLM quality: the LLM numbers are only the eval results above.

| Page | What it shows |
|---|---|
| `/` | overview: the chain of every demo incident as one cell per entry, how a fix is made, eval runs, the verify commands, limits |
| `/dashboard` | incident list, counters with their counting boundaries, exposure meter against the policy caps, live decision log |
| `/dashboard/incidents/<id>` | the chain entries of one incident, gate verdicts, verification checks, the receipt JSON and a Verify button |
| `/proof` | chain status and anchors, every eval label with its remaining failures, test counts, evidence links (PENDING until a real link exists), real vs simulated, the verify commands, limits, first and latest commit |
| `/status` | the same data as `/api/health` |

JSON: `/api/health`, `/api/metrics` (every metric has a `boundary` and the list has a `snapshot_sha256`), `/api/proof`, `/api/incidents`, `/api/incidents/<id>`, `/api/incidents/<id>/receipt`, `POST /api/incidents/<id>/receipt/verify`, and `/api/stream` (server-sent events, event `chain_entry`). Responses carry `"source": "simulated"` (`/api/health` reports `"mode": "simulated"`). The chain is fully verified at startup and every five minutes; `/api/health` reports `ok: false` if it does not verify. No endpoint accepts free text. The pages work without JavaScript (only the live log uses it).

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
| Incidents on `/dashboard` | Simulated scenarios decided by the deterministic offline stub, not an LLM; trace ids there are `offline-<n>` placeholders |

## How we used the required tools

- **neatlogs:** every live eval run is traced (workflow `vigil-eval-<label>`) and the trace ids are stored in `eval/results`; the v0 failures were found in the recorded runs and drove prompt v1. Span attributes are not attached yet. Public trace links: pending (dashboard links need a login).
- **Entire:** enabled with the OpenCode agent; the checkpoints are listed in `hackathon.md` and their refs are on origin under `refs/entire/checkpoints/`. They were created with `entire session attach` and Entire warned that no user prompts were parsed (`FEEDBACK.md` E3, E5, E6).
- **cfo.ai:** account created; the business plan (pricing, costs, revenue, runway) is not written yet. Measured token counts per incident are generated into `docs/business-plan-inputs.md`; no price has been assumed.

## Architecture

- `vigil/` — canonical JSON, decision chain, incident store, detector, tools, gate, verifier, executor, agent loop, receipts, prompt, model adapters, replay and stack builder; `vigil/demo.py` seeds the demo chain; `vigil/web/` is the framework-free web service, settings and HTML rendering.
- `api/` — the thin FastAPI app (`api/app.py`); `web/templates/` — the server-rendered pages.
- `sim/` — deterministic simulated provider and double-entry ledger with seeded fault injection.
- `eval/` — scenario files (`eval/scenarios`), runner (`python -m eval.run`), recorded results, baselines and the replay cache.
- `scripts/` — `verify_chain`, `verify_receipt`, `anchor`, `check_evidence`, `render_docs`, `live_smoke.py`; `vigil/docsgen.py` generates `docs/submission.md` and `docs/business-plan-inputs.md` from files (`make render`). `policy.yaml` holds the caps and limits (amounts are integer minor units, NGN).
- `deploy/vercel/` — a one-line proxy config (`vercel.json`) that forwards every path to the public instance; it holds no code and no secrets.
- Specification: `docs/SPEC.md`. Reviewer path: `docs/reviewer-start.md`. Evidence: `docs/submission.md`, `docs/evidence.json`. Threat model: `docs/threat-model.md`. Decisions: `DECISIONS.md`. Build log: `hackathon.md`. Tool feedback: `FEEDBACK.md`.

## Deployment

One Ubuntu server: `uvicorn` on `127.0.0.1:8005` as a systemd unit, behind an nginx site with a Let's Encrypt certificate for the DuckDNS host name, alongside other sites on the same nginx. The app never replaces an existing `data/vigil.db`: after changing the scenarios or the offline model, stop the service, delete `data/vigil.db*` and `receipts/web/`, and start it again. `deploy/vercel/` is a proxy config for a Vercel front; it has not been verified.

## Run it locally

```
make setup                 # venv + requirements
cp .env.example .env       # fill in your own keys; never commit .env
make test
make eval-offline          # deterministic stub model, no key
make serve                 # web app on 127.0.0.1:8005 (dashboard, /proof, /status, API)
```

A live run needs the gateway key in `.env` (`LLM_API_KEY`), and a neatlogs project key (`NEATLOGS_API_KEY`) for traces. Use a new label for every live run: `.venv/bin/python -m eval.run --label <new> --mode live --record --only <ids> --anchor`.

## Known limitations and next steps

- Provider and ledger are simulated; the suite is small and each label is a single live run on one model.
- v1 is tuned on the failures it fixes; only v1h and v1h2 are held-out, and X5b was informed by X5. X4 is a failing scenario whose cause has not been analysed.
- Replay of a baseline holds only while the code that builds the model request is unchanged; tool descriptions and schemas are not versioned yet.
- Cost per incident is not computed (no price configured).
- The public pages were opened from a phone on mobile data; the SSE stream returned entries through nginx (`/api/stream?once=true`). The live log in a browser and the Verify button have not been confirmed on the public URL.
- The `/proof` test count is counted from the test sources and the CI result is shown as PENDING; neither is a recorded run result. CI was green for 35707c7; the run for 9db1bb7 failed in `tests/test_evidence.py` because a shallow checkout has no real root commit. That is fixed in 4ff5333 (the Actions tab shows its result).
- Pending evidence: public neatlogs trace links (v0, v1, one recovery trace), the cfo.ai plan link. Not built: Tier B (`/try`, `/api/exposure`), neatlogs span attributes, cost per incident.

## Built during neatHack

Code and commits are dated inside the event window (Oct 10–12, 2026). Build log: [`hackathon.md`](hackathon.md). Public posts are listed there under "Build in public".

## License

No license has been chosen yet.
