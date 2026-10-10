PY ?= .venv/bin/python

.PHONY: setup test invariants verify hello
setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -r requirements.txt

test:
	$(PY) -m pytest -q tests

invariants:
	VIGIL_PROP_CASES=$${VIGIL_PROP_CASES:-300} $(PY) -m pytest -q tests/test_invariants.py

verify:
	$(PY) scripts/verify_chain
	@if ls receipts/*.json >/dev/null 2>&1; then $(PY) scripts/verify_receipt receipts; fi

hello:
	$(PY) scripts/hello_trace.py

# Targets still to come (SPEC 14): eval, eval-check, demo, anchor, serve, evidence
