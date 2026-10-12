# Threat model (short)

Scope: the read-only public web app and the agent pipeline, all on simulated data. No endpoint accepts free text.

| Threat | Mitigation | Residual risk |
|---|---|---|
| Prompt injection through customer text | Free text appears only under an `untrusted` block; the gate, verifier and detector never read it; the gate re-derives facts from provider and ledger state | A model could be steered to propose a bad action; the gate denies it, but a bad proposal still costs steps |
| Tool abuse or over-spend | Write tools are reachable only through the gate: allowed actions, per-incident and per-day caps, a maximum number of write actions, idempotency keys | Caps are code constants in `policy.yaml`; a wrong cap is a wrong limit |
| Replay and duplicate actions | Idempotency key per action, `DUPLICATE_ACTION` check, `ACTION_INTENT` committed before execution | Ambiguous timeouts are handled by retrying with the same key; only the simulator exercises this |
| Chain rewriting | Hash chain, append-only guard triggers, published anchors, `verify_chain` | Tamper-evident, not tamper-proof: whoever controls the system could rebuild the chain before its first anchor was published |
| Secret leakage in traces or files | `.env` is untracked, `.env.example` holds placeholders, traces use synthetic data only | Not scanned automatically; a manual scan is needed before submission |
| Demo abuse or cost blow-up | The public app is read-only, offline, and calls no LLM; there is no `/try` endpoint | None from cost; the host remains a normal internet-facing server behind nginx |
| Stale cached data | Replay keys include the model, system prompt, messages, tools and temperature; a missing key is a hard error | A changed prompt or tool text needs a new label and a new recording |
