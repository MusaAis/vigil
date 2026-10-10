# hackathon.md

## Project
**Vigil** — a payment-ops agent that fixes payment failures and proves every fix. Problem: quiet payment failures
(duplicate charges, missing webhooks, stuck payouts) are found late and fixed by hand. All payment data is SIMULATED.

## Team
Team "musa Ais" (solo): GitHub MusaAis.

## Stack
Python 3.12.3, SQLite. Planned: FastAPI, neatlogs Python SDK (>=1.4.26), Entire CLI 0.11.4 (OpenCode integration), cfo.ai.

## Tools: how each is used and evidence
- neatlogs: SDK 1.4.26; Doctor probe PASS; first trace id 9f8b58522abae5f0fc5f4ef444ef6b03 (workflow vigil-hello, 3 spans) confirmed in dashboard 2026-10-10. Public evidence link: PENDING (dashboard links need login)
- Entire: CLI installed and logged in; enabled in the repo; first commit made. Checkpoints: PENDING
- cfo.ai: account created.

## Build log
### 2026-10-10 (WAT)
- Done: Entire CLI 0.11.4 installed on the build server; `entire login` (file token store); repo `~/vigil` initialised;
  `entire enable` run; first commit `de613c7` ("chore: enable Entire"); Entire re-enabled for the OpenCode agent.
- Done (sandbox, not yet run on the server): T-02..T-04 code and 34 passing tests (canonical JSON, chain, SPEC 9.7 vectors, tamper tests).
- Planned: T-01 hello trace on the server; commit batch 1.
- Not done: everything else in PLAN.md.

## Demo
PENDING

## Known limitations and next steps
See PLAN.md. The decision chain is tamper-evident, not tamper-proof.

## Submission
Requirements are re-checked against neatlogs.com/hackathon and #neathack-announcements before submitting.
Format, judging weights and prizes: PENDING confirmation from official pages.
