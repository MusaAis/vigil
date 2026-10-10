PY ?= .venv/bin/python

.PHONY: setup test verify hello
setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -r requirements.txt

test:
	$(PY) -m pytest -q tests

verify:
	$(PY) scripts/verify_chain

hello:
	$(PY) scripts/hello_trace.py

# Targets still to come (SPEC 14): invariants, eval, eval-check, demo, anchor, serve, evidence
