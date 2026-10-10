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
- [x] T-11 Agent loop, offline model (server: 147 tests pass; plain gateway call verified; tool-calling check pending)
- [x] T-12 Receipts + verify_receipt (server: 147 tests pass)
- [ ] T-13 Eval runner, record/replay
- [ ] T-14 Baseline v0 (live)
- [ ] T-15 Improvement loops v1, v2
- [ ] T-16 Remaining scenarios
- [ ] T-17 API + SSE
- [ ] T-18 Dashboard, /proof, /status
- [ ] T-19 make demo, make eval-check
- [ ] T-20 Deploy public URL
- [ ] T-21 Reviewer docs, evidence pack
- [ ] T-22 Tier B
- [ ] T-23 README, FEEDBACK, hackathon.md final
- [ ] T-24 Final run, anchor, freeze

## Cut list (drop in this order if behind)
dashboard polish → X4/X5/X6 → P1/P2 variants → third improvement loop → extra docs.
Never cut: gate + tests, verifier, receipts, baseline→improvement evidence, recovery trace, neatlogs/Entire/cfo.ai evidence, demo.
