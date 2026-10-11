PY ?= .venv/bin/python

.PHONY: setup test invariants verify hello live-smoke eval eval-check eval-offline serve demo anchor evidence
LABEL ?= v0
PORT ?= 8005
setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -r requirements.txt

test:
	$(PY) -m pytest -q tests

invariants:
	VIGIL_PROP_CASES=$${VIGIL_PROP_CASES:-300} $(PY) -m pytest -q tests/test_invariants.py

# verify: verifies every chain database present, each against the anchors of its own run label, plus its receipts.
#   data/eval-<label>.db (made by eval-check or an eval run) with receipts/<label>/, data/demo.db with receipts/demo/,
#   data/vigil.db (the web app's chain) with receipts/web/. Fails if there is nothing to verify.
verify:
	@n=0; \
	for db in data/eval-*.db; do \
	  [ -e "$$db" ] || continue; run=$$(basename $$db .db); run=$${run#eval-}; \
	  $(PY) scripts/verify_chain --db $$db --run $$run || exit 1; \
	  if ls receipts/$$run/*.json >/dev/null 2>&1; then $(PY) scripts/verify_receipt --db $$db receipts/$$run || exit 1; fi; \
	  n=$$((n+1)); \
	done; \
	if [ -e data/demo.db ]; then \
	  $(PY) scripts/verify_chain --db data/demo.db --run demo || exit 1; \
	  if ls receipts/demo/*.json >/dev/null 2>&1; then $(PY) scripts/verify_receipt --db data/demo.db receipts/demo || exit 1; fi; \
	  n=$$((n+1)); \
	fi; \
	if [ -e data/vigil.db ]; then \
	  $(PY) scripts/verify_chain --db data/vigil.db --run demo || exit 1; \
	  if ls receipts/web/*.json >/dev/null 2>&1; then $(PY) scripts/verify_receipt --db data/vigil.db receipts/web || exit 1; fi; \
	  n=$$((n+1)); \
	fi; \
	[ $$n -gt 0 ] || { echo "nothing to verify: run make eval-check or make demo first"; exit 1; }; \
	echo "verify: $$n chain database(s) verified (SIMULATED data)"

hello:
	$(PY) scripts/hello_trace.py

live-smoke:
	$(PY) scripts/live_smoke.py

# eval: live model, records responses (needs the key; spends tokens). Use a NEW label for every run: make eval LABEL=v0
eval:
	$(PY) -m eval.run --label $(LABEL) --mode live --record

# eval-check: replays every committed baseline from eval/cache with the virtual clock; exits non-zero on any difference
eval-check:
	@ls eval/baselines/*.json >/dev/null 2>&1 || { echo "no baselines in eval/baselines yet"; exit 1; }
	@for f in eval/baselines/*.json; do $(PY) -m eval.run --label $$(basename $$f .json) --mode replay --check || exit 1; done

# eval-offline: deterministic stub model, zero cost, no key
eval-offline:
	$(PY) -m eval.run --label offline --mode offline

# serve: the read-only web app (dashboard, proof, status, API) on 127.0.0.1:$(PORT) (default 8005). Seeds data/vigil.db on first start (simulated, offline model).
serve:
	$(PY) -m uvicorn api.app:app --host 127.0.0.1 --port $(PORT)

# demo: zero keys, offline, SIMULATED. Seeds data/demo.db, runs D1 (resolved), D3 (skipped trap), D2 (escalated cap case),
# prints the decision log, writes receipts/demo/, verifies the chain and every receipt, prints the head. Exit 0 only if all verify.
demo:
	$(PY) -m vigil.demo

# anchor: append a chain head to anchors.txt (publish it too). Usage: make anchor RUN=<label> [DB=<path>]
#   e.g. make anchor RUN=v2   (uses data/eval-v2.db)      make anchor RUN=demo DB=data/demo.db
DB ?= data/eval-$(RUN).db
anchor:
	@test -n "$(RUN)" || { echo "usage: make anchor RUN=<label> [DB=<path to the chain database>]"; exit 2; }
	@test -e "$(DB)" || { echo "database not found: $(DB)"; exit 2; }
	$(PY) scripts/anchor --run $(RUN) --db $(DB)

# evidence: checks docs/evidence.json (a claim marked ok needs a real URL). The script is built in T-21.
evidence:
	@test -f scripts/check_evidence || { echo "scripts/check_evidence does not exist yet (task T-21)"; exit 1; }
	$(PY) scripts/check_evidence
