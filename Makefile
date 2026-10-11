PY ?= .venv/bin/python

.PHONY: setup test invariants verify hello live-smoke eval eval-check eval-offline serve
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

verify:
	$(PY) scripts/verify_chain --run demo
	@if ls receipts/web/*.json >/dev/null 2>&1; then $(PY) scripts/verify_receipt receipts/web; fi

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

# serve: the read-only web app (dashboard, proof, status, API) on 127.0.0.1:8000. Seeds data/vigil.db on first start (simulated, offline model).
serve:
	$(PY) -m uvicorn api.app:app --host 127.0.0.1 --port $(PORT)

# Targets still to come (SPEC 14): demo, anchor, evidence
