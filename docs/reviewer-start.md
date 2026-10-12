# Reviewer start: verify Vigil in two minutes

All payment data is simulated. Nothing here needs an API key.

## Two-minute path

```
git clone https://github.com/MusaAis/vigil.git && cd vigil
make setup
make demo           # seeds a SIMULATED chain with three scenarios, writes receipts, verifies both
make eval-check     # replays every committed baseline from eval/cache and compares outcomes and chain heads
make verify         # verifies every chain database present against its own anchors, plus its receipts
make evidence       # checks docs/evidence.json: a claim marked ok needs an https URL; pending rows are listed
```

To check one chain or one set of receipts directly:

```
.venv/bin/python scripts/verify_chain --db data/demo.db --run demo
.venv/bin/python scripts/verify_receipt --db data/demo.db receipts/demo
```

On the live site: `/proof` lists the eval runs, anchors and evidence rows; `/status` and `/api/health` show whether the
served chain verified; open any incident under `/dashboard` and press Verify on its receipt.

## What each check proves, and what it does not

| Check | Proves | Does not prove |
|---|---|---|
| `verify_chain` | Entries are contiguous, each links to the previous hash, each hash matches its stored content, and every published anchor still matches its entry | Who wrote the entries; that the chain was not rebuilt before the first anchor was published |
| `verify_receipt` | The receipt digest matches its payload, and every listed entry exists in the chain with the listed hash | A signature or authorship: the digest detects later edits only |
| `make eval-check` | The committed baselines reproduce from the recorded model responses with a virtual clock | That the model would answer the same way today; replay reuses recorded responses |
| `make demo` | The agent, gate, verifier and chain run end to end offline and match each scenario's ground truth | Anything about LLM quality: the demo uses a deterministic offline stub model |
| `make evidence` | The evidence file is well formed and no `ok` row lacks a URL | That a linked page says what its claim says; read the links |

## Where the retained digests and anchors are

- `anchors.txt`: one line per published chain head (run label, last sequence number, head hash, git commit).
- `eval/baselines/*.json` and `eval/results/*.json`: committed outcomes, chain heads and token counts per run.
- `receipts/<label>/`: receipts of recorded runs. The demo and web receipts are generated locally and not committed.

## Tamper test

```
make demo
cp data/demo.db /tmp/tamper.db
.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("/tmp/tamper.db")
c.execute("DROP TRIGGER chain_no_update")   # the triggers are a guard rail, not security
c.execute("UPDATE decision_chain SET body_json = replace(body_json, 'duplicate_charge', 'stuck_payout') WHERE seq = 0")
c.commit()
PY
.venv/bin/python scripts/verify_chain --db /tmp/tamper.db --run demo    # BROKEN at seq=0: HASH_MISMATCH, exit 1
.venv/bin/python scripts/verify_chain --db data/demo.db --run demo      # untouched copy: OK, exit 0
```

`tests/test_chain_tamper.py` does the same for edits, deletions, reordering, insertion and tail truncation.

## Limits

The chain is tamper-evident, not tamper-proof. The provider and ledger are simulated. The test and eval suites are
small, and the held-out scenarios are few: see `docs/submission.md` for the exact numbers and non-claims.
