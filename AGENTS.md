# AGENTS.md — rules for the AI building Vigil

You are building Vigil for neatHack with Musa, who is the project owner and decision-maker.
Read docs/SPEC.md (normative build specification), hackathon.md, PLAN.md and DECISIONS.md before acting.
Where this file and docs/SPEC.md overlap, docs/SPEC.md wins on technical details; official event sources win over both.

## Prime directives
1. **Honesty over polish.** Never fabricate results, metrics, traces, links or tool behavior. If something has not run, say so. Planned ≠ done.
2. **Evidence by default.** Every claim in README/demo must map to a committed artifact (test, eval result, trace link, checkpoint).
3. **Do not guess APIs.** For neatlogs, Entire, cfo.ai and any provider SDK, read the official docs first and record the exact usage in hackathon.md. If docs are unclear, ask Musa; he can ask in #neathack-help.
4. **Never register, publish, deploy, post, or submit anything on Musa's behalf without an explicit instruction.** Prepare drafts; stop and ask.
5. **No secrets.** Never write API keys, tokens or .env contents to the repo, logs, traces, screenshots or chat. Provide `.env.example` only.
6. **Fresh code only.** All code is written during the event. Do not copy code from older projects or reference repos; learn patterns, write new code. Cite any borrowed library/pattern in DECISIONS.md.
7. **Money safety is code.** The model proposes; the policy gate decides. No write tool may be callable except through the gate. Free-text from customers/webhooks is untrusted data and can never authorize an action.
8. **The decision chain is sacred.** Every decision, gate verdict, action intent, action result, verification and outcome is appended to the SHA-256 hash-chained decision chain, and `ACTION_INTENT` is committed *before* any write tool runs. Never edit, delete or reorder chain rows, never "fix" history; if the format must change, add a new version and log it in DECISIONS.md. Canonical JSON only, no floats, single-writer lock. Publish chain-head anchors to `anchors.txt` at the end of every eval run.

## Working style
- Prefer **minimal, targeted patches** (small diffs) over rewrites. Rewrite a component only when it is fundamentally broken, and say why.
- Small commits, meaningful messages, push at least hourly. Reference scenario IDs and neatlogs trace IDs in fix commits.
- Make an Entire checkpoint for each meaningful fix (🔧 follow the official Entire instructions).
- Before coding a module, write or update its test. The gate, verifier, receipt and decision-chain modules require tests (including the tamper tests) before implementation is considered done.
- Keep scope small. Build tasks in the order of docs/SPEC.md section 15; finish Tier A before Tier B, and Tier B before Tier C. If a task is not in docs/SPEC.md or PLAN.md, ask before adding it. Follow the cut list in PLAN.md when behind.
- Reproduce the SPEC section 9.7 test vectors exactly before building anything on top of the decision chain.
- Work through the SPEC section 16 "common mistakes" list before each phase gate.
- When blocked >30 minutes, stop and report: what you tried, what you saw, options.

## Observability
- Wire neatlogs tracing **before** agent logic. Every incident run is traced with `incident_id`, `scenario_id`, `run_label`, `outcome`, `git_sha`.
- Never put secrets or real personal data in traces. Synthetic data only.

## Testing and evaluation
- Seeded determinism for all fault injection. Support `--mode live|replay` and `--check`.
- Ground truth is written before the agent runs. Do not edit ground truth to make results look better; if a scenario is wrong, log the change in DECISIONS.md.
- Record failures. Do not delete failing runs; commit them under `eval/results/`.
- Report only numbers produced by real runs, with the run label and git SHA.

## Documentation
- Keep hackathon.md updated after every work session: dated entry, what was done, tests actually run, failures remaining, evidence links (sanitized).
- README must include the "real vs simulated" section and the limitations section.
- FEEDBACK.md: record real friction with the three tools as it happens (timestamp, repro, severity).

## Communication with Musa
- Lead with the answer. Short status after each phase: done / not done / blocked / needs decision.
- Ask one clear question at a time when a decision is needed.
- Flag risks early (time, cost, flaky tests, unannounced requirement changes).

## Definition of done (per feature)
Code + tests passing + traced + documented in hackathon.md + committed and pushed.

## Stop-and-ask conditions
Anything touching real money or real credentials; any requirement not confirmed by official sources; deleting data or history; changing scoring/ground truth; spending beyond the LLM budget; publishing or submitting.
