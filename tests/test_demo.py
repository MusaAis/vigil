"""Batch 8 (T-19): make demo, make verify/anchor/evidence, CI workflow (SPEC TS-10, section 14)."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
import yaml

from vigil.demo import DEMO_LABEL, check_demo, run_demo
from vigil.web.service import VigilService, summarize_entry
from vigil.web.settings import WebSettings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_MAKE = shutil.which("make") is not None


def demo(tmp_path, **kw):
    lines = []
    db, rec = str(tmp_path / "demo.db"), str(tmp_path / "receipts")
    code = run_demo(db, rec, ROOT, anchors_path=kw.get("anchors"), out=lines.append)
    return code, "\n".join(lines), db, rec


def tamper(db_path, seq=5):
    con = sqlite3.connect(db_path)
    con.execute("DROP TRIGGER chain_no_update")
    body = json.loads(con.execute("SELECT body_json FROM decision_chain WHERE seq=?", (seq,)).fetchone()[0])
    body["tampered"] = True
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=?", (json.dumps(body, sort_keys=True, separators=(",", ":")), seq))
    con.commit()
    con.close()


def test_demo_passes_and_is_labelled(tmp_path):
    code, out, db, rec = demo(tmp_path)
    assert code == 0
    assert out.startswith("Vigil demo (SIMULATED)") and "DEMO OK (SIMULATED)" in out and "tamper-evident, not tamper-proof" in out
    for sid, outcome in (("D1", "RESOLVED"), ("D2", "ESCALATED"), ("D3", "SKIPPED")):
        assert f"scenario {sid}: {outcome} (expected {outcome}) OK" in out
    assert "gate ESCALATE AMOUNT_OVER_INCIDENT_CAP" in out and "gate ALLOW OK" in out
    assert out.count("receipt inc_000") == 3 and "BROKEN" not in out
    assert sorted(os.listdir(rec)) == ["inc_0001.json", "inc_0002.json", "inc_0003.json"]


def test_demo_is_reproducible_and_matches_the_served_chain(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, out_a, _, _ = demo(tmp_path / "a")
    _, out_b, _, _ = demo(tmp_path / "b")
    head = [l for l in out_a.splitlines() if l.startswith("chain head ")][0]
    assert head == [l for l in out_b.splitlines() if l.startswith("chain head ")][0]
    svc = VigilService(WebSettings(db_path=str(tmp_path / "web.db"), receipts_dir=str(tmp_path / "wr")))
    svc.ensure_seeded()
    assert svc.verify_chain()["head"] in head  # `make demo` and the web app use the same seed code


def test_demo_starts_from_nothing_every_time(tmp_path):
    code, _, db, rec = demo(tmp_path)
    open(os.path.join(rec, "stale.json"), "w").write("{}")
    open(os.path.join(rec, "keep.txt"), "w").write("x")
    code2, out, _, _ = demo(tmp_path)
    assert code == code2 == 0
    assert not os.path.exists(os.path.join(rec, "stale.json")) and os.path.exists(os.path.join(rec, "keep.txt"))
    assert len([l for l in out.splitlines() if l.startswith("  #")]) == 38  # one chain, not appended to the old one


def test_check_demo_fails_when_the_chain_is_edited(tmp_path):
    _, _, db, rec = demo(tmp_path)
    assert check_demo(db, rec)["ok"] is True
    tamper(db)
    res = check_demo(db, rec)
    assert res["ok"] is False and res["chain_ok"] is False and "HASH_MISMATCH" in res["chain_line"]
    assert any(not r["ok"] for r in res["receipts"])


def test_check_demo_fails_when_a_receipt_is_edited_or_missing(tmp_path):
    _, _, db, rec = demo(tmp_path)
    p = os.path.join(rec, "inc_0001.json")
    r = json.load(open(p))
    r["payload"]["actions"][0]["amount_minor"] = 1
    json.dump(r, open(p, "w"))
    res = check_demo(db, rec)
    assert res["chain_ok"] is True and res["ok"] is False
    assert [x["ok"] for x in res["receipts"]] == [False, True, True]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert check_demo(db, str(empty))["ok"] is False  # no receipts means nothing proven


def test_check_demo_uses_demo_anchors_only(tmp_path):
    _, _, db, rec = demo(tmp_path)
    head = check_demo(db, rec)["head"]
    good = tmp_path / "good.txt"
    good.write_text(f"2026-10-11T10:00:00Z run=demo seq=37 head={head} git=abc1234\n"
                    f"2026-10-11T10:00:00Z run=v0 seq=111 head=sha256:{'0' * 64} git=abc1234\n")
    assert check_demo(db, rec, str(good))["ok"] is True  # the v0 line is another run's and is ignored
    bad = tmp_path / "bad.txt"
    bad.write_text(f"2026-10-11T10:00:00Z run=demo seq=37 head=sha256:{'1' * 64} git=abc1234\n")
    res = check_demo(db, rec, str(bad))
    assert res["ok"] is False and "ANCHOR_MISMATCH" in res["chain_line"]


def test_run_demo_returns_nonzero_when_verification_fails(tmp_path, monkeypatch):
    import vigil.demo as d
    real = d.check_demo
    monkeypatch.setattr(d, "check_demo", lambda *a, **k: {**real(*a, **k), "chain_ok": False, "ok": False, "chain_line": "BROKEN at seq=3: HASH_MISMATCH"})
    code, out, _, _ = demo(tmp_path)
    assert code == 1 and "DEMO FAILED: decision chain does not verify" in out and "DEMO OK" not in out


def test_summary_omits_missing_idempotency_key():
    e = {"kind": "ACTION_INTENT", "body": {"tool": "escalate", "idempotency_key": None}}
    assert summarize_entry(e) == "intent escalate (committed before execution)"
    e["body"] = {"tool": "issue_refund", "idempotency_key": "inc_0001:refund:1"}
    assert summarize_entry(e) == "intent issue_refund key inc_0001:refund:1 (committed before execution)"


# ---------------------------------------------------------------- Makefile (SPEC 14: these targets MUST exist)
@pytest.mark.skipif(not HAS_MAKE, reason="make not installed")
@pytest.mark.parametrize("target", ["setup", "test", "invariants", "eval", "eval-check", "demo", "verify", "anchor RUN=x", "serve", "evidence"])
def test_required_make_targets_exist(target):
    r = subprocess.run(["make", "-n", *target.split()], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def sandbox(tmp_path):
    """A scratch repo layout: the real Makefile, scripts and package, an empty data dir."""
    shutil.copy(os.path.join(ROOT, "Makefile"), tmp_path / "Makefile")
    for name in ("scripts", "vigil", "sim", "eval", "policy.yaml"):
        os.symlink(os.path.join(ROOT, name), tmp_path / name)
    (tmp_path / "anchors.txt").write_text("")
    (tmp_path / "data").mkdir()
    return tmp_path


def make(sandbox, *args):
    return subprocess.run(["make", f"PY={sys.executable}", *args], cwd=sandbox, capture_output=True, text=True)


@pytest.mark.skipif(not HAS_MAKE, reason="make not installed")
def test_make_verify_refuses_when_there_is_nothing_to_verify(sandbox):
    r = make(sandbox, "verify")
    assert r.returncode != 0 and "nothing to verify" in r.stdout


@pytest.mark.skipif(not HAS_MAKE, reason="make not installed")
def test_make_verify_passes_then_fails_after_tampering(sandbox):
    assert run_demo(str(sandbox / "data" / "demo.db"), str(sandbox / "receipts" / "demo"), ROOT, out=lambda *_: None) == 0
    ok = make(sandbox, "verify")
    assert ok.returncode == 0 and "1 chain database(s) verified" in ok.stdout
    tamper(str(sandbox / "data" / "demo.db"))
    bad = make(sandbox, "verify")
    assert bad.returncode != 0 and "BROKEN at seq=5: HASH_MISMATCH" in bad.stdout


@pytest.mark.skipif(not HAS_MAKE, reason="make not installed")
def test_make_verify_checks_eval_chains_against_their_own_anchors(sandbox):
    from eval.run import run_eval
    from vigil.config import Config
    run_eval(label="t1", mode="offline", only=["D1"], config=Config(), receipts_dir=str(sandbox / "receipts" / "t1"),
             db_path=str(sandbox / "data" / "eval-t1.db"), scenario_dir=os.path.join(ROOT, "eval", "scenarios"),
             policy_path=os.path.join(ROOT, "policy.yaml"))
    assert make(sandbox, "verify").returncode == 0
    (sandbox / "anchors.txt").write_text(f"2026-10-11T10:00:00Z run=t1 seq=0 head=sha256:{'2' * 64} git=abc1234\n")
    bad = make(sandbox, "verify")
    assert bad.returncode != 0 and "ANCHOR_MISMATCH" in bad.stdout


@pytest.mark.skipif(not HAS_MAKE, reason="make not installed")
def test_make_anchor_needs_a_run_label_and_a_database(sandbox):
    r = make(sandbox, "anchor")
    assert r.returncode == 2 and "usage: make anchor RUN=" in r.stdout
    r = make(sandbox, "anchor", "RUN=nope")
    assert r.returncode == 2 and "database not found" in r.stdout
    run_demo(str(sandbox / "data" / "demo.db"), str(sandbox / "receipts" / "demo"), ROOT, out=lambda *_: None)
    ok = make(sandbox, "anchor", "RUN=demo", "DB=data/demo.db")
    assert ok.returncode == 0 and "run=demo seq=37 head=sha256:58a61f12" in (sandbox / "anchors.txt").read_text()
    assert make(sandbox, "verify").returncode == 0  # the new anchor is checked and matches


@pytest.mark.skipif(not HAS_MAKE or os.path.exists(os.path.join(ROOT, "scripts", "check_evidence")), reason="check_evidence exists (T-21)")
def test_make_evidence_fails_clearly_until_t21(sandbox):
    r = make(sandbox, "evidence")
    assert r.returncode != 0 and "check_evidence does not exist yet" in r.stdout


# ---------------------------------------------------------------- CI and ignore rules
def test_ci_workflow_runs_the_spec_steps_without_secrets():
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    text = open(path, encoding="utf-8").read()
    wf = yaml.safe_load(text)
    assert "push" in (wf.get(True) or wf.get("on"))  # PyYAML reads the key `on` as True
    steps = [s for job in wf["jobs"].values() for s in job["steps"]]
    runs = [s["run"] for s in steps if "run" in s]
    assert runs == ["make setup", "make test", "make invariants", "make eval-check", "make verify", "make demo"]
    assert "secrets." not in text and "LLM_API_KEY" not in text


def test_demo_outputs_are_ignored_by_git():
    lines = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read().split()
    assert "receipts/demo/" in lines and "data/*.db" in lines and "data/*.db-*" in lines
    if shutil.which("git"):
        r = subprocess.run(["git", "check-ignore", "data/demo.db", "receipts/demo/inc_0001.json"], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0 and len(r.stdout.split()) == 2


def test_proof_page_sees_the_ci_workflow(tmp_path):
    svc = VigilService(WebSettings(db_path=str(tmp_path / "c.db"), receipts_dir=str(tmp_path / "r")), now=lambda: "2026-10-11T12:00:00Z")
    svc.ensure_seeded()
    svc.verify_chain()
    t = svc.proof()["data"]["tests"]
    assert t["ci_workflows"] == ["ci.yml"] and t["ci_url"].endswith("/actions")
    assert t["ci_last_run"] is None  # the server never reads GitHub; a run result stays PENDING until someone links it


def test_run_demo_fails_on_a_wrong_demo_anchor(tmp_path):
    bad = tmp_path / "anchors.txt"
    bad.write_text(f"2026-10-11T10:00:00Z run=demo seq=37 head=sha256:{'1' * 64} git=abc1234\n")
    code, out, _, _ = demo(tmp_path, anchors=str(bad))
    assert code == 1 and "ANCHOR_MISMATCH" in out and "DEMO FAILED: decision chain does not verify" in out and "DEMO OK" not in out
