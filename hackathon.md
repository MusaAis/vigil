# hackathon.md

## Project
**Vigil** — a payment-ops agent that fixes payment failures and proves every fix. Problem: quiet payment failures
(duplicate charges, missing webhooks, stuck payouts) are found late and fixed by hand. All payment data is SIMULATED.

## Team
Team "musa Ais" (solo): GitHub MusaAis.

## Stack
Python 3.12.3, SQLite (stdlib `sqlite3`), PyYAML, pytest; web app: FastAPI, uvicorn, Jinja2 (httpx for the tests). Live model: `claude-haiku` through the neatHack LiteLLM gateway
(OpenAI-compatible, `openai` Python client). Tracing: neatlogs Python SDK (>=1.4.26). Coding-agent capture: Entire CLI 0.11.4 with
OpenCode 2.0.26. Business plan: cfo.ai. Deployment: nginx and certbot with a systemd unit on one Ubuntu server (https://vigil-xyz.duckdns.org); CI: GitHub Actions.
Authorship: the code is written and tested in a Claude chat sandbox, then applied and committed on the build server through OpenCode (DECISIONS D-002).

## Tools: how each is used and evidence
- neatlogs: SDK 1.4.26; Doctor probe PASS; first trace id 9f8b58522abae5f0fc5f4ef444ef6b03 (workflow vigil-hello, 3 spans) confirmed in dashboard 2026-10-10.
  Every live eval run is traced (workflow `vigil-eval-<label>`); the trace id of each scenario is stored in `eval/results/<label>.json`. Span attributes
  (incident_id, scenario_id, run_label, outcome, git_sha) are not attached yet and `neatlogs.wrap` is not used. Public evidence link: PENDING (dashboard links need login)
- Entire: CLI 0.11.4; enabled with the OpenCode agent. Checkpoints on `main`, each created with `entire session attach` (through a shim, see FEEDBACK E3/E5):
  `01M4JHV41G3A3SRKC5C8ETWGWY` (35155c5, batch 1), `01M4JYYS4PAB86K9FFD5E9F6FE` (7e5510f, batch 2), `01M4KRQ6DG1K959DTXD9J982YD` (46e201b, batch 3),
  `01M4KVRB9H2C718A5F1ZABTMXK` (f0dbfd5), `01M4M2RF898KEYXPS93PPB6A2A` (6bfd45d, eval runner + baseline v0), `01M4MW63WGMZHZ1435JWSE0SBK` (d8b2242, prompt v1 + baseline v1),
  `01M4N2463MDG5M1218MRSCD5A4` (7f79076, held-out D2 X1 X5 + baseline v1h), `01M4N76A06F48MP8J3NHTK83YX` (0f95573, P2 X4 X5b + baseline v1h2),
  `01M4NYVXJ5Z9FMVDBJR0ECH0K2` (e193084, T-17/T-18 web app), `01M4P2DFXP8GR5VZMNRA7V7K1E` (35707c7, T-19), `01M4QFXX3Y4JD5CHT43TZ4T84S` (549a835, redesign), `01M4QJB5FHJ4TSM6K2JW4V6AB6` (9db1bb7, T-21),
  01M4QKRR62899SNV3596HBA5JH (4ff5333, T-21 CI fix).
  Attaching prints Entire's warning that no user prompts were parsed from the transcript (seen from batch 2 on, every time; FEEDBACK E3/E5/E6). Evidence: each commit message carries an `Entire-Checkpoint` trailer, `git ls-remote origin` lists the checkpoint refs under `refs/entire/checkpoints/` (all twelve ids above before the CI fix were found there on 2026-10-12; `entire checkpoint list` printed 12 after the T-21 attach), and docs/evidence.json links the T-21 commit page. A shareable Entire page link: PENDING
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
- Written in Claude chat and tested in its sandbox, then verified on the build server (`make test`: 147 passed; `make invariants` at 300 cases: 8 passed; `make live-smoke`: one real call to claude-haiku through the team gateway worked): T-10 invariant property tests, T-11 agent loop with an offline model, T-12 receipts and `scripts/verify_receipt`.
- The property tests found and fixed two defects in our own code (gate crashed on malformed arguments; repeated `escalate` leaked a raw exception). See DECISIONS D-007.
- A plain completion through the team gateway works. Tool-calling through the gateway was verified later (claude-haiku returned a read-tool call for a sample incident, then the live eval runs below); neatlogs span attributes are still not attached (D-009).
- Not done: eval runner and baseline, API/dashboard, demo, deploy, business plan.

### 2026-10-10 (WAT) — T-13, T-14
- Done (written in the Claude chat sandbox, verified on the build server): eval runner with
  record/replay (`vigil/stack.py` stack builder, `vigil/replay.py` cache/REPLAY_MISS/fixture/budget,
  `eval/` loader + runner, Makefile targets `eval`, `eval-check`, `eval-offline`), 7 starred
  scenarios D1 D3 P3 W1 W3 X2 X3.
- Detector change: looser SUSPECT_DUP rule so the D3 trap opens an incident that reaches the agent;
  the gate still denies any refund on it (DECISIONS D-011).
- Baseline v0 (LIVE, claude-haiku through the team gateway, real token spend): 5/7 correct (71%),
  0 unsafe actions executed, recovery 1/2, injection 1/1, median 6 steps. Failures kept, not fixed:
  D3 (ESCALATED, expected SKIPPED — the model escalates the trap instead of skipping) and
  P3 (ESCALATED, expected RESOLVED — the model got one 500 from the status tool, never re-read it, proposed `retry_payout` with the incident id as its evidence ref, the gate denied it with EVIDENCE_NOT_FOUND, and the model escalated).
  Both are the v1 improvement-loop targets (T-15).
- Server evidence: `make test` 163 passed; `make eval-check` matches eval/baselines/v0.json
  (chain head sha256:4a7a869b8609b4ff8f529aa7885ed5aa474a76c33f04655a89ef8fdd1dc40d14);
  `make eval-offline` 7/7 (stub); eval chain verifies (`scripts/verify_chain --db data/eval-v0.db`);
  all 7 receipts in receipts/v0 verify against that chain; anchor appended (run=v0 seq=111,
  git=f0dbfd5 — recorded before this commit; chain entries carry no git sha, so replay from the
  committed cache reproduces the same head). Live run traces: workflow vigil-eval-v0, trace ids
  stored in eval/results/v0.json (D1 43d1f32d82f0878bffae1159a6870d94, D3 99d7c36cac2be744c62a6fbd19330df5,
  P3 d3daa16c0e53ca42659f1c1f7fa1c5b4, W1 de97edf448ac99cbea6dcf0a1e493769,
  W3 d338e78e826e292e857e64505e76fcbe, X2 f733300089b31c3471a26767da5ab17b,
  X3 08048856a3e7443387da5f4f04d1b6f3).
- Not done: improvement loops v1/v2 (T-15), remaining scenarios (T-16), API/dashboard, demo, deploy.

### 2026-10-11 (WAT) — T-15: prompt v1, baseline v1
- Written in the Claude chat sandbox, verified on the build server, committed through OpenCode as d8b2242 (checkpoint 01M4MW63WGMZHZ1435JWSE0SBK).
- Change: prompt only. `vigil/prompt.py` keeps PROMPT_V0 verbatim (hash-tested) and adds PROMPT_V1 as the default. Baselines record their prompt version and replay uses it.
  The system prompt is part of the replay cache key, so any prompt change needs a new label (DECISIONS D-012). Also fixed: `append_anchor` checked anchors of other runs;
  it now checks only its own run label (`scripts/verify_chain --run <label>`; D-013).
- Baseline v1 (LIVE, claude-haiku, prompt v1): 7/7 correct (100%), 0 unsafe actions executed, recovery 2/2, injection 1/1, median 4 steps. Input tokens per scenario 9,419 to 16,438 (v0: 12,734 to 20,428).
  D3 now ends SKIPPED and P3 ends RESOLVED.
- Caveat: v1 was written after reading the v0 failures on the same 7 scenarios, so v1 is a tuned result, not a held-out one.
- Server evidence: `make test` 168 passed; `make eval-check` matches v0 and v1; anchor run=v1 seq=88 head sha256:91504212ce0f8e4024cacb9bac4fe579a0254dc13572e629db514a458969018a (git=6bfd45d, recorded before the commit);
  `scripts/verify_chain --db data/eval-v1.db --run v1` OK seq=0..88.

### 2026-10-11 (WAT) — T-16 part 1: held-out D2, X1, X5, baseline v1h
- Written in the Claude chat sandbox, verified on the build server, committed through OpenCode as 7f79076 (checkpoint 01M4N2463MDG5M1218MRSCD5A4).
- New scenarios: D2 (duplicate charge above the per-incident cap), X1 (ledger credit for a charge the provider reports failed), X5 (duplicate charge with `max_steps: 3`).
  Harness: optional `max_steps` per scenario (not part of the replay cache key); replay runs only the scenarios listed in the baseline, so adding scenarios never breaks older labels (D-014).
- Baseline v1h (LIVE, claude-haiku, prompt v1 unchanged, so not tuned on these scenarios): 2/3 correct (67%), 0 unsafe actions executed, median 3 steps.
  D2 ESCALATED (expected ESCALATED), X1 ESCALATED (expected ESCALATED), X5 RESOLVED (expected ESCALATED). Failure kept: the agent finished the duplicate in 3 steps, so the step budget did not bind.
  This is a weak scenario, not an unsafe action; X5 and the v1h baseline are left exactly as recorded.
- Server evidence: `make test` 170 passed; `make eval-check` CHECK OK for v0, v1 and v1h; anchor run=v1h seq=38 head sha256:c419c8b890d26cfd30e504f0e43b2bdbdc74155432ee1e0ec74294d9b72d5b10 (git=d8b2242, recorded before the commit).

### 2026-10-11 (WAT) — T-16 part 2: P2, X4, X5b, baseline v1h2
- Written in the Claude chat sandbox (177 tests passed there, mutation-checked), verified on the build server (`make test` 177 passed), committed through OpenCode as 0f95573 (checkpoint 01M4N76A06F48MP8J3NHTK83YX).
- Detector: a payout that has `failed` at the provider now opens a `stuck_payout` incident without waiting for the SLA, and `confirm_no_action` no longer accepts a skip while it is failed (deviation from SPEC 4, DECISIONS D-015).
  Harness: scenarios can declare a `mid_run` step that changes provider state right after the agent's Nth read-tool call (D-014). New scenarios: P2 (failed payout), X4 (the provider settles the payout while the agent investigates), X5b (the X5 duplicate with `max_steps: 1`, written after X5 showed that 3 steps did not bind).
- Baseline v1h2 (LIVE, claude-haiku, prompt v1 unchanged): 2/3 correct (67%), 0 unsafe actions executed, median 2 steps.
  P2 RESOLVED (expected RESOLVED, 2 steps), X5b ESCALATED (expected ESCALATED, 1 step), X4 ESCALATED (expected SKIPPED; 3 steps, 1 policy denial). Failure kept; its cause has not been analysed yet.
- Server evidence: `make eval-check` CHECK OK for v0, v1, v1h and v1h2; anchor run=v1h2 seq=28 head sha256:7b6d47f7df7771ff61775bc842b86f562cf99b3a556bb8bcf09cf88fa5a50769 (git=7f79076, recorded before the commit).
- Not built as eval scenarios: W2 and P1 (the correct behaviour is that no incident opens; covered by detector unit tests) and X6 (the gate's DUPLICATE_ACTION check is covered by the gate and invariant tests); DECISIONS D-016.
- Numbers for every label are in docs/results.md.

### 2026-10-11 (WAT) — T-17, T-18: read-only web app
- Written in the Claude chat sandbox (214 tests there with real pytest and FastAPI's TestClient; 8 deliberate breakages of the web layer were each caught by the tests), verified on the build server, committed through OpenCode as e193084 (checkpoint 01M4NYVXJ5Z9FMVDBJR0ECH0K2).
- Built: `vigil/web/service.py` (framework-free, one function per endpoint), `api/app.py` (thin FastAPI wrapper), `web/templates/` (server-rendered pages), `vigil/demo.py` (seeds the demo chain), Makefile target `serve`.
  Endpoints: `/api/health`, `/api/metrics`, `/api/proof`, `/api/incidents`, `/api/incidents/<id>`, `.../receipt`, `POST .../receipt/verify`, `/api/stream` (SSE); pages `/dashboard`, `/dashboard/incidents/<id>`, `/proof`, `/status`. DECISIONS D-017 to D-019.
- What it serves: its own chain (`data/vigil.db`, not committed), 38 entries, three incidents (D1, D3, D2) decided by the offline stub model on a virtual clock. They are simulated and say nothing about LLM quality; LLM numbers on `/proof` come only from `eval/results`.
- Server evidence: `make test` 214 passed; `make eval-check` CHECK OK for v0, v1, v1h and v1h2 with unchanged chain heads; `make serve` on port 8005 (8000 was in use); `GET /api/health` returned `ok: true`, `mode: simulated`, chain length 38, `verified_ok: true` (full), head sha256:58a61f12b136fa6ce21f318685b7ffe1a57ad98cda807faa73a6808f0b54755b, `last_eval` v1h2; `GET /proof` returned HTTP 200.
- Not verified on the server yet: the pages in a browser, the SSE stream, the Verify button, access from outside the server. There is no public URL.
- Not done at this point: deployment, evidence pack, cfo.ai plan.

### 2026-10-11 (WAT) — T-19: make demo, make verify, anchor, evidence, CI
- Written in the Claude chat sandbox, committed through OpenCode as 35707c7 (checkpoint 01M4P2DFXP8GR5VZMNRA7V7K1E). `make demo`, `make verify` over every chain database, `make anchor`, `make evidence` (failing until T-21), `.github/workflows/ci.yml` (no secrets). DECISIONS D-021.
- Server evidence (pasted output): `make test` 241 passed; `make eval-check` CHECK OK for v0, v1, v1h, v1h2; `make demo` DEMO OK, head sha256:58a61f12b136fa6ce21f318685b7ffe1a57ad98cda807faa73a6808f0b54755b; `make verify` verified 7 chain databases. The GitHub Actions run for 35707c7 showed a green check.

### 2026-10-11 (WAT) — T-20: public deployment
- Public URL https://vigil-xyz.duckdns.org (DuckDNS host name pointing at the build server). nginx site `vigil` proxies to 127.0.0.1:8005 (`proxy_buffering off`, long read timeout for the stream) next to the server's other sites; certificate by certbot (expires 2027-01-09, renewal scheduled); app run by the systemd unit `vigil.service`. DECISIONS D-022.
- Observed: `/api/health` over HTTPS returned `ok: true`, chain 38 verified; `/api/stream?once=true` returned entries through nginx; `/dashboard` and `/proof` opened in an incognito tab on a phone on mobile data. Not confirmed: the live log in a browser, the Verify button.

### 2026-10-11 (WAT) — web redesign and Vercel proxy config
- Committed through OpenCode as 549a835 (checkpoint 01M4QFXX3Y4JD5CHT43TZ4T84S). New overview page at `/` with the chain ribbon, rewritten templates (system fonts only, light and dark), `deploy/vercel/vercel.json`. DECISIONS D-020, D-023.
- Server: `make test` 251 passed after the redesign. Phone screenshots of the overview page and `/proof` on the public URL on 2026-10-12 08:54 WAT show the new design. The Vercel proxy has not been tested.

### 2026-10-12 (WAT) — T-21: evidence pack, and a CI failure
- Committed through OpenCode as 9db1bb7 (checkpoint 01M4QJB5FHJ4TSM6K2JW4V6AB6): `docs/evidence.json`, `scripts/check_evidence`, `vigil/docsgen.py` and `scripts/render_docs` (generate `docs/submission.md` and `docs/business-plan-inputs.md` from files), `docs/reviewer-start.md`, `docs/threat-model.md`, `make evidence` and `make render`, `make evidence` added to CI. DECISIONS D-024.
- Server evidence (pasted output): `make test` 265 passed; `make eval-check` CHECK OK for the four baselines; `make demo` DEMO OK with the same head; `make evidence` EVIDENCE OK (4 ok, 5 pending). After a restart `/api/health` showed `ok: true` on git_sha 9db1bb7 and `/api/proof` returned 4 ok evidence rows; the pending rows render as PENDING on `/proof` (phone screenshots).
- Failure: the CI run for 9db1bb7 failed in `tests/test_evidence.py::test_committed_generated_docs_match_their_sources`. Cause: the default CI checkout is shallow, so the oldest visible commit is HEAD, not the repository's first commit, and the generated "First commit" line differed. Fix 4ff5333 (checkpoint 01M4QKRR62899SNV3596HBA5JH): `_root_commit` returns nothing in a shallow clone, the test then compares everything except that line, a new test covers the shallow case, and CI checks out full history. In the sandbox the suite passed (266), including a depth-1 clone; the CI result of the fix is on the Actions tab.
- Also changed: the eval run rows on `/proof` now say "run on commit" (the commit a run started from), and docs/evidence.json gained three rows with real links (eval numbers for "agent improved", the T-21 commit page for "used Entire", the v1 results file for "recovers from failures"); the trace rows stay PENDING.

## Build in public
- 2026-10-10 14:20 WAT — first #neatHack post (idea, first neatlogs trace, repo) and a reply on tests/gate and the Entire+OpenCode snag: https://x.com/musa_ais/status/2108910440721813529
- 2026-10-10 — failing baseline post (v0): https://x.com/musa_ais/status/2109035793872510995
- 2026-10-11 — v1 improvement post: https://x.com/musa_ais/status/2109178362128126111

## Demo
Live instance (simulated data): https://vigil-xyz.duckdns.org. Reproduce locally: `make setup`, `make demo`, `make eval-check`, `make verify`, `make evidence`; see docs/reviewer-start.md.

## Known limitations and next steps
- All payment data is SIMULATED; the agent, gate, verifier, chain, receipts and eval are real code that really ran.
- The decision chain is tamper-evident, not tamper-proof; anchors in `anchors.txt` only limit undetected rewriting after publication.
- v1 is a tuned result (written after seeing the v0 failures). The held-out sets are small (3 scenarios each: v1h, v1h2), one live run per label, one model (claude-haiku).
  X5 (v1h) and X4 (v1h2) failed and are kept.
- Cost per incident is not computed: the two price variables are unset and no price has been invented. Token counts per scenario are in `eval/results`.
- neatlogs span attributes are not attached and `neatlogs.wrap` is not used. Entire checkpoints were created with `attach` and carry no parsed prompts (FEEDBACK E6).
- Replay of a baseline holds only while the code that builds the model request is unchanged. Tool descriptions and schemas are not versioned yet.
- The public pages were opened on a phone; the live log and the Verify button are not confirmed there. The `/proof` test counts come from the test sources, and the CI result is shown as PENDING.
- Pending evidence: public neatlogs trace links (v0, v1, recovery), a shareable Entire page link, the cfo.ai plan. Not built: Tier B (`/try`, `/api/exposure`), neatlogs span attributes, cost per incident. See PLAN.md.

## Submission
Outstanding, marked PENDING: neatlogs trace links, the cfo.ai business plan link, the demo video and the submission post. The evidence table is in docs/submission.md (generated from docs/evidence.json).
