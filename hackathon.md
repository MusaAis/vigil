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
- Entire: CLI 0.11.4; enabled with the OpenCode agent. Checkpoints (all on branch main): `01M4JHV41G3A3SRKC5C8ETWGWY` (commit 35155c5, batch 1) and `01M4JYYS4PAB86K9FFD5E9F6FE` (commit 7e5510f, batch 2; created with a shim, Entire warned that no user prompts were parsed — see FEEDBACK E3/E5). Both are listed by `entire checkpoint list` and pushed to origin. Checkpoint links: PENDING
- cfo.ai: account created. Business plan: PENDING

## Build log
### 2026-10-10 (WAT)
- Done: Entire CLI 0.11.4 installed on the build server; `entire login` (file token store); repo `~/vigil` initialised;
  `entire enable` run; first commit `de613c7` ("chore: enable Entire"); Entire re-enabled for the OpenCode agent.
- Done (sandbox, not yet run on the server): T-02..T-04 code and 34 passing tests (canonical JSON, chain, SPEC 9.7 vectors, tamper tests).
- Done on server: T-01 hello trace (Doctor probe PASS; trace id confirmed against dashboard), 34 tests pass; batch 1 committed as `dc0b24d` via OpenCode.
- Problem: Entire shows 0 checkpoints for that commit (OpenCode 2.0.26 vs Entire export step). See DECISIONS D-004 and FEEDBACK E2/E3. Not fixed yet.
- Not done: everything else in PLAN.md.

### 2026-10-10 later (WAT)
- Written in Claude chat, tested in its sandbox, then verified on the server (102 tests pass; committed via OpenCode; the hash changed with later amends, see the checkpoint list): T-05..T-09 — simulator, detector, typed tools, policy gate, verifier, executor. 99 tests pass in the sandbox; mutation spot-checks found and closed two test gaps.
- FEEDBACK.md started (neatlogs / Entire / cfo.ai / organisers).
- Entire: batch 1 has checkpoint 01M4JHV41G3A3SRKC5C8ETWGWY; batch 2 has 01M4JYYS4PAB86K9FFD5E9F6FE after attaching the session with an `opencode export` shim.
- Not done: agent loop, receipts, eval, API/dashboard, demo, deploy.

### 2026-10-10 15:19 (WAT)
- Written in Claude chat and tested in its sandbox (144 tests pass there with a minimal stand-in test runner because the sandbox has no pytest; NOT yet run on the build server): T-10 invariant property tests, T-11 agent loop with an offline model, T-12 receipts and `scripts/verify_receipt`.
- The property tests found and fixed two defects in our own code (gate crashed on malformed arguments; repeated `escalate` leaked a raw exception). See DECISIONS D-007.
- Live LLM adapter and neatlogs span wiring are written but unverified against the real services (D-009). Span attributes are not attached yet.
- Not done: eval runner and baseline, API/dashboard, demo, deploy, business plan.

## Build in public
- 2026-10-10 14:20 WAT — first #neatHack post (idea, first neatlogs trace, repo) and a reply on tests/gate and the Entire+OpenCode snag: https://x.com/musa_ais/status/2108910440721813529
- Next planned: failing baseline trace; first published chain-head hash.

## Demo
PENDING

## Known limitations and next steps
See PLAN.md. The decision chain is tamper-evident, not tamper-proof.

## Submission
Added at submission time.
