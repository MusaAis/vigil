# Feedback for neatHack sponsors (neatlogs, Entire, cfo.ai) and organisers

Written during the build, with the evidence we had at the time. Entries marked *observed* are things we saw;
anything we have not verified is labelled *hypothesis*. Severity: low / medium / high (for a first-time user).

## neatlogs

**What worked well**
- `python -m neatlogs doctor --probe` gave a clear end-to-end PASS (8 checks incl. TRACE_VISIBLE, TRACE_FINALIZED,
  HIERARCHY_VALID) in one command. It is the fastest "is my setup real?" check we have used.
- `@neatlogs.span(kind=...)` nesting rendered as written: WORKFLOW → AGENT → TOOL, with input and output shown.
- `neatlogs.inject_trace_context()` returned a W3C `traceparent` whose trace id matched the id in the dashboard URL.

| # | When (WAT) | What we tried | What happened | Expected | Sev | Workaround |
|---|---|---|---|---|---|---|
| N1 | 2026-10-10 (morning) | Read the current trace id in Python to store it next to our own audit records | No documented helper. OpenTelemetry `get_current_span()` returned an invalid span context inside `@neatlogs.span` (*observed*). The documented `inject_trace_context()` works but is a propagation API, not an id getter | A `neatlogs.current_trace_id()` (or documented equivalent) | low | Parse the `traceparent` that `inject_trace_context()` writes (see `scripts/hello_trace.py`) |
| N2 | 2026-10-10 (before 09:32) | Ran `npx @neatlogs/wizard@latest` on a repo that has `@neatlogs.span`-decorated functions but no LLM client yet | Printed "Setup failed — No agentic/LLM code detected" | A non-error message such as "nothing to instrument yet" (nothing was actually wrong) | low | Skip the wizard; follow the manual setup |
| N3 | 2026-10-10 | Looked for key rotation in the setup guide | Guide says the Project API key cannot be rotated or revoked (*as documented*) | Rotation, or a per-project revocable key, so a leaked key can be replaced | medium | Keep the key in the shell environment only; never commit it |

## Entire

**What worked well**
- The install script verified checksums and printed clear steps; `entire enable` was one command.
- `entire login` on a headless server failed with a keyring error, but the message named the fix
  (`ENTIRE_TOKEN_STORE=file`) and it worked first time.
- `entire doctor` output was easy to read.

| # | When (WAT) | What we tried | What happened | Expected | Sev | Workaround |
|---|---|---|---|---|---|---|
| E1 | 2026-10-10 (morning) | Ran `entire enable` by mistake in `$HOME` instead of the project folder (our error) | It initialised a git repo in `~` and installed hooks there without any warning | A warning or confirmation when the directory is a home directory | low | Removed `.git`/`.entire` from `~`, re-ran inside the project |
| E2 | 2026-10-10 10:06 | Committed through OpenCode 2.0.26 after `entire enable --agent opencode`; no "link this commit" prompt appeared | `entire checkpoint list` → 0 checkpoints; `entire session list` → "No sessions" even though OpenCode listed the session (*observed*) | A checkpoint for the session that made the commit | high | Under investigation (see E3) |
| E3 | 2026-10-10 10:15–10:25 | `entire session attach <real-id> -a opencode` | "OpenCode could not export session" (*observed*). OpenCode 2.0.26 has `opencode session export` but no top-level `opencode export` (*observed*). Entire's OpenCode docs mention `opencode export` (*hypothesis*: the integration still calls the old command) | Attach works on current OpenCode | high | Testing a small `opencode export` → `opencode session export` shim (not yet confirmed) |
| E4 | 2026-10-10 09:56 | First OpenCode session started in "Plan" mode (read-only) | It could run tests but not commit, and said so | — | low | Press Tab to switch to Build |

## cfo.ai
- Signed up through the neatHack link and cancelled the subscription in Settings → Billing straight away, as the email instructed.
  No problems so far. Business plan: not started.

## neatHack (organisers)
- Clear, well-structured setup emails (check-in, AWS allowance, credits). The AWS email's private link is a good pattern.
- The first announced start time was wrong in some places and had to be re-confirmed (we noted a mismatch between
  the welcome email and what organisers later said). One canonical, timezone-labelled time on the site would avoid this.
