"""Framework-free web service (SPEC TS-3 to TS-8). One method per endpoint, each returning plain dicts.

The FastAPI app (api/app.py) is a thin wrapper around this module, so every number and link can be tested without
the web framework. All numbers come from files and the chain database; nothing is typed by hand (SPEC 16.10).
Everything served here is SIMULATED. The chain is tamper-evident, not tamper-proof.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from vigil import __version__
from vigil.canonical import sha256_json
from vigil.chain import parse_anchors, verify
from vigil.clock import SystemClock
from vigil.demo import DEMO_LABEL, seed_demo
from vigil.policy import load_policy
from vigil.receipts import load_receipt, verify_receipt

from .settings import WebSettings

SOURCE = "simulated"
INCIDENT_ID_RE = re.compile(r"^inc_[0-9a-z]+$")
HTTPS_RE = re.compile(r"^https://[^\s<>\"']+$")
# Claims the evidence pack must cover (SPEC TS-11). Listing the claim names is not a result; a missing url renders PENDING.
REQUIRED_CLAIMS = (
    "agent improved (two traces and numbers)", "used neatlogs", "used Entire", "used cfo.ai (business plan)",
    "recovers from failures", "built in public", "wrote code during the hackathon",
)
REAL_VS_SIMULATED = (
    {"component": "Payment provider, charges, refunds, payouts, webhooks", "status": "Simulated", "evidence": "sim/ code"},
    {"component": "Merchant accounting ledger", "status": "Simulated", "evidence": "sim/ code"},
    {"component": "Agent, policy gate, verifier, decision chain, receipts", "status": "Real code that really ran",
     "evidence": "tests, traces, chain"},
    {"component": "LLM calls", "status": "Real in live eval runs; recorded in replay runs",
     "evidence": "eval/results, eval/cache"},
    {"component": "Incidents on /dashboard", "status": "Simulated scenarios decided by a deterministic offline stub model, not an LLM",
     "evidence": "vigil/demo.py, vigil/models.py"},
    {"component": "Traces", "status": "Real neatlogs traces in live eval runs (links in the evidence pack)",
     "evidence": "docs/evidence.json"},
)
CELL_LEGEND = (
    ("INCIDENT_OPENED", "Incident opened"), ("OBSERVATION", "Read"), ("DECISION", "Decision"),
    ("GATE_ALLOW", "Gate allows"), ("GATE_DENY", "Gate denies"), ("GATE_ESCALATE", "Gate escalates"),
    ("ACTION_INTENT", "Intent committed"), ("ACTION_RESULT", "Action result"), ("VERIFICATION", "Verified"),
    ("OUTCOME_RESOLVED", "Resolved"), ("OUTCOME_ESCALATED", "Escalated"), ("OUTCOME_SKIPPED", "Skipped"),
)
LIMITS = (
    "Everything here is simulated: the payment provider, the ledger and the incidents. No real money or customer data.",
    "The suite is small (a few scenarios per label) and the v1 prompt was tuned on the v0 failures of the same scenarios.",
    "The chain is tamper-evident, not tamper-proof. Anchors in anchors.txt make rewriting after publication detectable.",
    "A receipt digest detects later edits; it is not a signature and does not prove who produced it.",
    "Incidents on the dashboard are decided by an offline rule-based stub, so they say nothing about LLM quality; "
    "LLM numbers come only from the eval results above. The trace ids in the demo chain are offline-<n> placeholders, "
    "not neatlogs traces.",
)


def summarize_entry(e: dict) -> str:
    """One-line summary of a chain entry. Built from structured fields only."""
    k, b = e["kind"], e["body"]
    if k == "INCIDENT_OPENED":
        return f"opened {b.get('type')} by rule {b.get('detector_rule')}, related {', '.join(b.get('related', []))}"
    if k == "OBSERVATION":
        flag = " [injection suspected]" if b.get("injection_suspected") else ""
        return f"read {b.get('tool')}: {b.get('result_summary')}{flag}"
    if k == "DECISION":
        what = " ".join(x for x in (b.get("decision"), b.get("tool")) if x)
        return f"{what}: {b.get('rationale', '')}"
    if k == "GATE_VERDICT":
        return f"gate {b.get('verdict')} {b.get('code')}"
    if k == "ACTION_INTENT":
        key = f" key {b['idempotency_key']}" if b.get("idempotency_key") else ""
        return f"intent {b.get('tool')}{key} (committed before execution)"
    if k == "ACTION_RESULT":
        state = "ok" if b.get("ok") else f"failed {b.get('error_type')}"
        return f"{b.get('tool')} attempt {b.get('attempt')}: {state}"
    if k == "VERIFICATION":
        checks = b.get("checks", [])
        passed = sum(1 for c in checks if c.get("passed", c.get("ok")))
        return f"verification {'passed' if b.get('ok') else 'FAILED'} ({passed}/{len(checks)} checks)"
    if k == "OUTCOME":
        return f"{b.get('outcome')} {b.get('reason_code')}: {b.get('summary')}"
    return k


def _git(root: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _utc(iso: str) -> Optional[str]:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def read_entries(db_path: str, incident_id: Optional[str] = None, after_seq: int = -1, limit: int = 100000) -> list:
    """Read-only access to the chain database."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        q = ("SELECT seq,ts,incident_id,kind,body_json,trace_id,prev_hash,entry_hash FROM decision_chain "
             "WHERE seq>?")
        args: list = [after_seq]
        if incident_id is not None:
            q += " AND incident_id=?"
            args.append(incident_id)
        rows = con.execute(q + " ORDER BY seq LIMIT ?", (*args, limit)).fetchall()
    finally:
        con.close()
    return [{"seq": s, "ts": ts, "incident_id": i, "kind": k, "body": json.loads(bj), "trace_id": t,
             "prev_hash": p, "entry_hash": h} for s, ts, i, k, bj, t, p, h in rows]


class VigilService:
    def __init__(self, settings: Optional[WebSettings] = None, now: Optional[Callable[[], str]] = None) -> None:
        self.s = settings or WebSettings()
        self._now = now or SystemClock().now
        self.started_at = self._now()
        self._started_mono = datetime.now(timezone.utc)
        self._lock = threading.Lock()
        self._verified: Optional[dict] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ lifecycle
    def ensure_seeded(self) -> bool:
        """Seed the demo chain when the database is missing or empty. Returns True if it seeded."""
        if os.path.exists(self.s.db_path):
            try:
                if read_entries(self.s.db_path, limit=1):
                    return False
            except sqlite3.DatabaseError:
                return False  # an unreadable chain is reported by verification, never silently replaced
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.s.db_path + suffix):
                os.remove(self.s.db_path + suffix)
        seed_demo(self.s.db_path, self.s.receipts_dir, self.s.root)
        return True

    def start(self) -> None:
        """Seed if needed, verify the whole chain now, then verify again every verify_interval_s."""
        self.ensure_seeded()
        self.verify_chain()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vigil-chain-verifier", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.s.verify_interval_s):
            self.verify_chain()

    # ------------------------------------------------------------ chain
    def verify_chain(self) -> dict:
        """Full verification from genesis. Anchors of run 'demo' (if any) are checked too."""
        try:
            res = verify(self.s.db_path, self.s.anchors_path, run=DEMO_LABEL)
            info = {"ok": res.ok, "line": res.line(), "length": res.count, "head": res.head_hash,
                    "head_seq": res.head_seq, "reason": res.reason, "broken_seq": res.broken_seq}
        except (sqlite3.DatabaseError, OSError) as exc:
            info = {"ok": False, "line": f"UNREADABLE: {type(exc).__name__}", "length": 0, "head": None,
                    "head_seq": None, "reason": "UNREADABLE", "broken_seq": None}
        info.update(verified_at=self._now(), verify_mode="full")
        with self._lock:
            self._verified = info
        return info

    def chain_status(self) -> dict:
        with self._lock:
            cached = self._verified
        return cached if cached is not None else self.verify_chain()

    # ------------------------------------------------------------ evals
    def eval_results(self) -> list:
        out = []
        for path in sorted(glob.glob(os.path.join(self.s.results_dir, "*.json"))):
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        out.sort(key=lambda r: (r.get("recorded_at") or r.get("started_at") or "", r["run_label"]))
        return out

    def _eval_row(self, r: dict) -> dict:
        m = r["metrics"]
        return {
            "label": r["run_label"], "git_sha": r.get("git_sha"), "mode": r.get("mode"), "model": r.get("model"),
            "prompt_version": r.get("prompt_version"), "recorded_at": r.get("recorded_at"),
            "n_correct": m["n_correct"], "n_total": m["n_total"], "correct_resolution_pct": m["correct_resolution_pct"],
            "unsafe_actions_executed": m["unsafe_actions_executed"],
            "n_fault_correct": m["n_fault_correct"], "n_fault_scenarios": m["n_fault_scenarios"],
            "recovery_pct": m["recovery_pct"],
            "n_injection_correct": m["n_injection_correct"], "n_injection_scenarios": m["n_injection_scenarios"],
            "injection_resistance_pct": m["injection_resistance_pct"], "median_steps": m["median_steps"],
            "cost_per_incident_usd_micro": m["cost_per_incident_usd_micro"],
            "chain_head": r.get("chain_head"), "chain_head_seq": r.get("chain_head_seq"),
            "file": f"eval/results/{r['run_label']}.json",
            "file_url": f"{self.s.repo_url}/blob/main/eval/results/{r['run_label']}.json",
            "failures": [{"id": s["id"], "outcome": s["outcome"], "expected_outcome": s["expected_outcome"],
                          "notes": s.get("notes", "")} for s in r["scenarios"] if not s["correct"]],
            "source": SOURCE,
        }

    # ------------------------------------------------------------ incidents
    def _receipt_path(self, incident_id: str) -> str:
        return os.path.join(self.s.receipts_dir, f"{incident_id}.json")

    def _receipt(self, incident_id: str) -> Optional[dict]:
        if not INCIDENT_ID_RE.match(incident_id):
            return None
        try:
            return load_receipt(self._receipt_path(incident_id))
        except (OSError, ValueError):
            return None

    def _group(self) -> dict:
        groups: dict = {}
        for e in read_entries(self.s.db_path):
            groups.setdefault(e["incident_id"], []).append(e)
        return groups

    def _incident_row(self, iid: str, entries: list) -> dict:
        opened = next((e for e in entries if e["kind"] == "INCIDENT_OPENED"), None)
        outcome = next((e for e in reversed(entries) if e["kind"] == "OUTCOME"), None)
        rec = self._receipt(iid)
        steps = max([e["body"].get("step", 0) for e in entries] or [0])
        return {
            "incident_id": iid, "type": opened["body"].get("type") if opened else None,
            "related": opened["body"].get("related", []) if opened else [],
            "detector_rule": opened["body"].get("detector_rule") if opened else None,
            "scenario_id": rec["payload"].get("scenario_id") if rec else None,
            "outcome": outcome["body"]["outcome"] if outcome else "OPEN",
            "reason_code": outcome["body"]["reason_code"] if outcome else None,
            "steps": steps, "entries": len(entries), "opened_at": entries[0]["ts"],
            "closed_at": outcome["ts"] if outcome else None, "has_receipt": rec is not None, "source": SOURCE,
        }

    def incidents(self) -> dict:
        data = [self._incident_row(i, es) for i, es in self._group().items()]
        return {"source": SOURCE, "generated_at": self._now(), "data": data}

    def incident(self, incident_id: str) -> Optional[dict]:
        if not INCIDENT_ID_RE.match(incident_id):
            return None
        entries = read_entries(self.s.db_path, incident_id=incident_id)
        if not entries:
            return None
        timeline = [{"seq": e["seq"], "ts": e["ts"], "kind": e["kind"], "summary": summarize_entry(e),
                     "body": e["body"], "entry_hash": e["entry_hash"], "prev_hash": e["prev_hash"],
                     "trace_id": e["trace_id"]} for e in entries]
        gates = [{"seq": e["seq"], "step": e["body"].get("step"), "verdict": e["body"].get("verdict"),
                  "code": e["body"].get("code")} for e in entries if e["kind"] == "GATE_VERDICT"]
        ver = [e for e in entries if e["kind"] == "VERIFICATION"]
        checks = [{"name": c.get("check", c.get("name")), "ok": bool(c.get("passed", c.get("ok"))),
                   "detail": c.get("detail", "")} for c in (ver[-1]["body"].get("checks", []) if ver else [])]
        rec = self._receipt(incident_id)
        return {"source": SOURCE, "generated_at": self._now(), "incident": self._incident_row(incident_id, entries),
                "timeline": timeline, "gate_verdicts": gates,
                "verification": {"ok": ver[-1]["body"]["ok"], "checks": checks} if ver else None,
                "receipt": rec}

    def receipt(self, incident_id: str) -> Optional[dict]:
        rec = self._receipt(incident_id)
        return None if rec is None else {"source": SOURCE, **rec}

    def verify_receipt_for(self, incident_id: str) -> Optional[dict]:
        rec = self._receipt(incident_id)
        if rec is None:
            return None
        res = verify_receipt(rec, self.s.db_path)
        return {"source": SOURCE, "ok": res.ok, "incident_id": res.incident_id, "digest": res.digest,
                "n_entries": res.n_entries, "line": res.line(), "problems": res.problems,
                "note": "The digest detects later edits. It is not a signature and does not prove who produced the receipt."}

    # ------------------------------------------------------------ chain ribbon (landing page)
    def chain_strip(self) -> dict:
        """The real chain entries grouped by incident, one cell per entry, for the ribbon on the overview page."""
        rows = {r["incident_id"]: r for r in self.incidents()["data"]}
        groups: dict = {}
        present: set = set()
        for e in read_entries(self.s.db_path):
            b = e["body"]
            if e["kind"] == "GATE_VERDICT":
                cls = f"GATE_{b.get('verdict')}"
            elif e["kind"] == "OUTCOME":
                cls = f"OUTCOME_{b.get('outcome')}"
            else:
                cls = e["kind"]
            present.add(cls)
            g = groups.setdefault(e["incident_id"], [])
            g.append({"seq": e["seq"], "cls": cls, "label": f"#{e['seq']} {summarize_entry(e)}", "entry_hash": e["entry_hash"]})
        out = []
        for iid, cells in groups.items():
            r = rows.get(iid, {})
            out.append({"incident_id": iid, "scenario_id": r.get("scenario_id"), "type": r.get("type"),
                        "outcome": r.get("outcome"), "cells": cells})
        return {"source": SOURCE, "groups": out, "legend": [{"cls": c, "label": l} for c, l in CELL_LEGEND if c in present]}

    def verify_commands(self) -> list:
        return [f"git clone {self.s.repo_url} && cd vigil", "make setup", "make demo", "make eval-check",
                ".venv/bin/python scripts/verify_chain --db data/eval-v1.db --run v1",
                ".venv/bin/python scripts/verify_receipt --db data/eval-v1.db receipts/v1"]

    # ------------------------------------------------------------ stream
    def stream_entries(self, after_seq: int = -1, limit: int = 200) -> list:
        """Chain entries after after_seq in the SSE event shape (event name 'chain_entry')."""
        return [{"seq": e["seq"], "kind": e["kind"], "incident_id": e["incident_id"],
                 "summary": summarize_entry(e), "entry_hash": e["entry_hash"]}
                for e in read_entries(self.s.db_path, after_seq=after_seq, limit=limit)]

    # ------------------------------------------------------------ exposure meter (TS-2)
    def exposure(self) -> dict:
        pol = load_policy(self.s.policy_path)
        refunded: dict = {}
        per_incident: dict = {}
        for iid in self._group():
            rec = self._receipt(iid)
            if not rec:
                continue
            for a in rec["payload"]["actions"]:
                if a["tool"] == "issue_refund" and a.get("executed") and a.get("amount_minor"):
                    day = rec["payload"]["closed_at"][:10]
                    refunded[day] = refunded.get(day, 0) + a["amount_minor"]
                    per_incident[iid] = per_incident.get(iid, 0) + a["amount_minor"]
        intents: dict = {}
        for e in read_entries(self.s.db_path):
            if e["kind"] == "ACTION_INTENT" and e["body"].get("tool") != "escalate":
                intents[e["incident_id"]] = intents.get(e["incident_id"], 0) + 1
        return {"source": SOURCE, "currency": pol.currency,
                "caps": {"per_incident_minor": pol.max_refund_per_incident_minor,
                         "per_day_minor": pol.max_refund_per_day_minor,
                         "max_write_actions_per_incident": pol.max_write_actions_per_incident},
                "refunded_by_utc_day_minor": refunded, "peak_day_refunded_minor": max(refunded.values(), default=0),
                "peak_incident_refunded_minor": max(per_incident.values(), default=0),
                "max_write_actions_in_one_incident": max(intents.values(), default=0),
                "note": "Simulated chain on a virtual clock; days are virtual. Breaches are impossible by construction (gate)."}

    # ------------------------------------------------------------ metrics (TS-6)
    def _counts(self) -> dict:
        outcomes = {"RESOLVED": 0, "ESCALATED": 0, "SKIPPED": 0}
        verdicts = {"DENY": 0, "ESCALATE": 0}
        n = 0
        for e in read_entries(self.s.db_path):
            n += 1
            if e["kind"] == "OUTCOME" and e["body"]["outcome"] in outcomes:
                outcomes[e["body"]["outcome"]] += 1
            if e["kind"] == "GATE_VERDICT" and e["body"]["verdict"] in verdicts:
                verdicts[e["body"]["verdict"]] += 1
        return {"entries": n, "outcomes": outcomes, "verdicts": verdicts}

    def metrics(self) -> dict:
        evals = self.eval_results()
        c = self._counts()
        demo = "Simulated incidents in this instance's demo chain (offline stub model); not customer usage"
        data = [
            {"name": "recorded_runs", "value": len(evals),
             "boundary": "Eval result files committed in eval/results (live recordings by the team, including early baselines); "
                         "excludes the offline demo, replay re-runs and CI; not customer usage"},
            {"name": "eval_scenarios_run", "value": sum(r["metrics"]["n_total"] for r in evals),
             "boundary": "Scenario executions summed over all recorded runs; the same scenario counts once per run; simulated"},
            {"name": "eval_scenarios_correct", "value": sum(r["metrics"]["n_correct"] for r in evals),
             "boundary": "Executions whose outcome, final state and forbidden-action check matched ground truth, over all recorded runs"},
            {"name": "unsafe_actions_executed", "value": sum(r["metrics"]["unsafe_actions_executed"] for r in evals),
             "boundary": "Across all recorded eval runs; defined in docs/SPEC.md section 12.4; the demo chain is not counted"},
            {"name": "incidents_resolved", "value": c["outcomes"]["RESOLVED"], "boundary": demo},
            {"name": "incidents_escalated", "value": c["outcomes"]["ESCALATED"], "boundary": demo},
            {"name": "incidents_skipped", "value": c["outcomes"]["SKIPPED"], "boundary": demo},
            {"name": "gate_denials", "value": c["verdicts"]["DENY"],
             "boundary": "Gate DENY verdicts in the demo chain (simulated); informative, not failures"},
            {"name": "gate_escalations", "value": c["verdicts"]["ESCALATE"],
             "boundary": "Gate ESCALATE verdicts in the demo chain (simulated); a cap was hit and a human is asked"},
            {"name": "chain_entries", "value": c["entries"], "boundary": "Entries in the demo chain served by this instance"},
        ]
        return {"source": SOURCE, "generated_at": self._now(), "snapshot_sha256": sha256_json(data), "data": data}

    # ------------------------------------------------------------ health / status (TS-5)
    def health(self) -> dict:
        ch = self.chain_status()
        evals = self.eval_results()
        last = evals[-1] if evals else None
        sha = _git(self.s.root, "rev-parse", "--short", "HEAD")
        built = _git(self.s.root, "log", "-1", "--format=%cI")
        uptime = int((datetime.now(timezone.utc) - self._started_mono).total_seconds())
        return {
            "ok": bool(ch["ok"]), "service": "vigil", "version": __version__, "git_sha": sha,
            "built_at": _utc(built) if built else None, "mode": SOURCE, "started_at": self.started_at,
            "uptime_s": uptime,
            "chain": {"length": ch["length"], "head": ch["head"], "verified_ok": ch["ok"],
                      "verified_at": ch["verified_at"], "verify_mode": ch["verify_mode"]},
            "last_eval": ({"label": last["run_label"], "git_sha": last.get("git_sha"),
                           "correct_resolution_pct": last["metrics"]["correct_resolution_pct"]} if last else None),
            "llm": {"provider": "offline-stub", "mode": "offline"},
            "policy_sha256": load_policy(self.s.policy_path).sha256,
        }

    # ------------------------------------------------------------ evidence + proof (TS-3, TS-11)
    def evidence(self) -> list:
        rows: list = []
        try:
            with open(self.s.evidence_path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
        if raw is None:
            return [{"claim": c, "kind": None, "url": None, "added_at": None, "status": "pending"}
                    for c in REQUIRED_CLAIMS]
        for item in raw:
            url = item.get("url")
            ok = item.get("status") == "ok" and isinstance(url, str) and bool(HTTPS_RE.match(url))
            rows.append({"claim": item.get("claim"), "kind": item.get("kind"), "url": url if ok else None,
                         "added_at": item.get("added_at"), "status": "ok" if ok else "pending"})
        have = {r["claim"] for r in rows}
        rows += [{"claim": c, "kind": None, "url": None, "added_at": None, "status": "pending"}
                 for c in REQUIRED_CLAIMS if c not in have]
        return rows

    def _tests_info(self) -> dict:
        def count(path: str) -> int:
            try:
                with open(path, encoding="utf-8") as f:
                    return len(re.findall(r"^\s*def test_", f.read(), re.M))
            except OSError:
                return 0
        files = sorted(glob.glob(os.path.join(self.s.tests_dir, "test_*.py")))
        wf = sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.s.ci_workflow_dir, "*.y*ml")))
        return {"test_functions_total": sum(count(p) for p in files),
                "property_test_functions": count(os.path.join(self.s.tests_dir, "test_invariants.py")),
                "invariants": [f"INV-{i}" for i in range(1, 9)],
                "ci_workflows": wf, "ci_url": f"{self.s.repo_url}/actions" if wf else None,
                "ci_last_run": None,
                "note": "Counted from source files; this is not a test result. The last CI result is PENDING "
                        "until a workflow exists and its run is linked."}

    def _anchors(self) -> list:
        try:
            with open(self.s.anchors_path, encoding="utf-8") as f:
                anchors = parse_anchors(f.read())
        except (OSError, ValueError):
            return []
        return [{**a, "commit_url": f"{self.s.repo_url}/commit/{a['git']}"} for a in anchors]

    def _commits(self) -> dict:
        root = _git(self.s.root, "rev-list", "--max-parents=0", "HEAD")
        first = root.splitlines()[-1] if root else None

        def info(ref: str) -> Optional[dict]:
            out = _git(self.s.root, "log", "-1", "--format=%H|%cI|%s", ref)
            if not out:
                return None
            h, d, subj = out.split("|", 2)
            return {"hash": h, "short": h[:7], "committed_at": _utc(d), "subject": subj,
                    "url": f"{self.s.repo_url}/commit/{h}"}
        return {"first": info(first) if first else None, "latest": info("HEAD")}

    def proof(self) -> dict:
        ch = self.chain_status()
        data = {
            "chain": {"source": "decision_chain table and anchors.txt", "length": ch["length"], "head": ch["head"],
                      "verified_ok": ch["ok"], "verify_mode": ch["verify_mode"], "verify_line": ch["line"],
                      "anchors": self._anchors(), "run": DEMO_LABEL},
            "eval": {"source": "eval/results/*.json", "runs": [self._eval_row(r) for r in self.eval_results()]},
            "tests": {"source": "tests/ and .github/workflows", **self._tests_info()},
            "evidence": {"source": "docs/evidence.json", "items": self.evidence()},
            "real_vs_simulated": {"source": "SPEC TS-8", "rows": list(REAL_VS_SIMULATED)},
            "verify": {"source": "repository scripts", "commands": self.verify_commands()},
            "limits": {"source": "README and SPEC", "items": list(LIMITS)},
            "event_window": {"source": "git history of the deployed checkout", **self._commits()},
        }
        # snapshot_sha256 covers `data` only. Time stamps live outside it so the hash changes only when the content does.
        return {"source": SOURCE, "generated_at": self._now(), "verified_at": ch["verified_at"],
                "snapshot_sha256": sha256_json(data), "data": data}
