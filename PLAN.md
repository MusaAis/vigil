# Plan (SPEC section 15). Tick only when done and verified on the server.

- [x] T-01 Repo, Makefile, .env.example, tracing wired, first trace visible (Doctor probe PASS; vigil-hello trace visible)
- [x] T-02 Canonical JSON + hash utilities (sandbox: tests green; server: 34 tests pass)
- [x] T-03 Decision chain + test vectors (sandbox: 9.7 vectors reproduce; server: 34 tests pass)
- [x] T-04 Tamper tests + verify_chain + anchor (sandbox: green; server: 34 tests pass)
- [x] T-05 Simulator (sandbox + server: 102 tests pass)
- [x] T-06 Detector (sandbox + server: 102 tests pass)
- [x] T-07 Tools (sandbox + server: 102 tests pass)
- [x] T-08 Policy gate (sandbox + server: 102 tests pass)
- [x] T-09 Verifier (sandbox + server: 102 tests pass)
- [x] T-10 Invariant property tests (server: 147 tests pass; invariants at 300 cases pass; mutation-checked)
- [x] T-11 Agent loop, offline model (server: 147 tests pass; live tool-calling verified through the team gateway)
- [x] T-12 Receipts + verify_receipt (server: 147 tests pass)
- [x] T-13 Eval runner, record/replay (server: `make test` 163 passed; `make eval-check` matches baseline v0; `make eval-offline` 7/7)
- [x] T-14 Baseline v0 (live, claude-haiku: 5/7 correct, 0 unsafe actions executed; failures D3, P3 kept)
- [x] T-15 Improvement loop v1 (live: 7/7, tuned on the v0 failures; no v2 run; see docs/results.md)
- [x] T-16 Remaining scenarios: D2, X1, X5 (v1h) and P2, X4, X5b (v1h2) added; W2, P1 (detector unit tests) and X6 (gate/invariant tests) not built as eval scenarios, see D-016 (server: 177 tests pass)
- [x] T-17 API + SSE (server: 214 tests pass; `/api/health` ok:true with the chain verified, commit e193084)
- [x] T-18 Dashboard, /proof, /status (server: `GET /proof` 200 via curl; not yet opened in a browser on the server; no public URL)
- [x] T-19 make demo, make verify, make anchor, CI workflow (server: 241 tests pass at the time, `make demo` DEMO OK; CI green for 35707c7)
- [x] T-20 Deploy public URL (https://vigil-xyz.duckdns.org; `/api/health` ok:true over HTTPS)
- [x] T-21 Reviewer docs, evidence pack, check_evidence (server: 265 tests pass; evidence rows for neatlogs traces and cfo.ai are still PENDING)
- [ ] T-22 Tier B
- [ ] T-23 README, FEEDBACK, hackathon.md final (updated 2026-10-12 for T-19 to T-21; final pass after the last evidence links)
- [ ] T-24 Final run, anchor, freeze

## Cut list (drop in this order if behind)
dashboard polish → X4/X5/X6 → P1/P2 variants → third improvement loop → extra docs.
Never cut: gate + tests, verifier, receipts, baseline→improvement evidence, recovery trace, neatlogs/Entire/cfo.ai evidence, demo.
