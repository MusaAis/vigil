import copy
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from vigil.canonical import sha256_json
from vigil.chain import verify
from vigil.receipts import build_receipt, load_receipt, verify_receipt, write_receipt
from tests.helpers import Env
from tests.test_agent import make_agent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolved_d1(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    make_agent(e).run(inc)
    r = build_receipt(e.chain, e.store.get(inc["incident_id"]), e.view, e.policy.currency,
                      scenario_id="D1", run_label="t0", git_sha="abc1234")
    return e, inc, r, str(tmp_path / "t.db")


def redigest(r):
    r["digest"] = sha256_json(r["payload"])
    return r


def codes(res):
    return [p["code"] for p in res.problems]


def test_receipt_shape_and_digest(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    p = r["payload"]
    assert r["receipt_version"] == 1 and r["digest"] == sha256_json(p)
    assert (p["outcome"], p["reason_code"], p["mode"], p["currency"]) == ("RESOLVED", "VERIFIED_OK", "simulated", "NGN")
    assert p["neatlogs_trace_id"] == "offline-1" and p["entire_checkpoint"] is None
    assert [x["seq"] for x in p["entries"]] == [x["seq"] for x in e.chain.entries(inc["incident_id"])]
    assert p["actions"] == [{"tool": "issue_refund", "args_sha256": p["actions"][0]["args_sha256"],
                             "idempotency_key": f"{inc['incident_id']}:refund:1", "amount_minor": 2_500_000,
                             "executed": True}]
    assert p["verification"]["ok"] is True and p["policy_sha256"] == e.policy.sha256
    assert (p["run_label"], p["git_sha"], p["scenario_id"]) == ("t0", "abc1234", "D1")


def test_a_clean_receipt_verifies(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    res = verify_receipt(r, db)
    assert res.ok and res.n_entries == len(r["payload"]["entries"])
    assert res.line().startswith(f"OK incident={inc['incident_id']}")


def test_editing_the_receipt_breaks_the_digest(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    r["payload"]["actions"][0]["amount_minor"] = 1
    res = verify_receipt(r, db)
    assert not res.ok and "DIGEST_MISMATCH" in codes(res)


def test_editing_and_redigesting_still_fails_against_the_chain(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    forged = copy.deepcopy(r)
    forged["payload"]["outcome"] = "SKIPPED"
    res = verify_receipt(redigest(forged), db)
    assert not res.ok and codes(res) == ["OUTCOME_MISMATCH"]

    forged = copy.deepcopy(r)
    forged["payload"]["verification"]["ok"] = False
    assert "VERIFICATION_MISMATCH" in codes(verify_receipt(redigest(forged), db))

    forged = copy.deepcopy(r)
    forged["payload"]["actions"] = []
    assert "ACTIONS_MISMATCH" in codes(verify_receipt(redigest(forged), db))


def test_dropping_inserting_or_changing_listed_entries_is_detected(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)

    dropped = copy.deepcopy(r)
    gone = dropped["payload"]["entries"].pop(3)
    res = verify_receipt(redigest(dropped), db)
    assert codes(res) == ["ENTRY_UNLISTED"] and str(gone["seq"]) in res.problems[0]["detail"]

    extra = copy.deepcopy(r)
    extra["payload"]["entries"].append({"seq": 9999, "hash": "sha256:" + "0" * 64})
    assert "ENTRY_MISSING" in codes(verify_receipt(redigest(extra), db))

    changed = copy.deepcopy(r)
    changed["payload"]["entries"][2]["hash"] = "sha256:" + "f" * 64
    assert "ENTRY_HASH_MISMATCH" in codes(verify_receipt(redigest(changed), db))

    swapped = copy.deepcopy(r)
    swapped["payload"]["entries"][1], swapped["payload"]["entries"][2] = \
        swapped["payload"]["entries"][2], swapped["payload"]["entries"][1]
    assert "ENTRY_ORDER" in codes(verify_receipt(redigest(swapped), db))


def test_a_tampered_chain_row_fails_receipt_verification_at_that_seq(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    target = r["payload"]["entries"][4]["seq"]
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("DROP TRIGGER chain_no_update")
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=?", ('{"edited":true}', target))
    con.close()
    res = verify_receipt(r, db)
    assert not res.ok and res.problems[0]["code"] == "HASH_MISMATCH" and str(target) in res.problems[0]["detail"]
    assert not verify(db).ok


def test_receipts_for_escalated_and_skipped_incidents(tmp_path):
    e = Env(tmp_path)
    e.d1(amount=6_000_000)
    inc = e.open_incident()
    make_agent(e).run(inc)
    r = build_receipt(e.chain, e.store.get(inc["incident_id"]), e.view, "NGN", scenario_id="D2",
                      run_label="t0", git_sha="abc1234")
    p = r["payload"]
    assert (p["outcome"], p["reason_code"]) == ("ESCALATED", "AMOUNT_OVER_INCIDENT_CAP")
    assert [(a["tool"], a["idempotency_key"], a["amount_minor"], a["executed"]) for a in p["actions"]] == \
        [("escalate", None, None, True)]
    assert verify_receipt(r, str(tmp_path / "t.db")).ok


def test_open_incidents_get_no_receipt(tmp_path):
    e = Env(tmp_path)
    e.d1()
    inc = e.open_incident()
    with pytest.raises(ValueError):
        build_receipt(e.chain, inc, e.view, "NGN", scenario_id="D1", run_label="t0", git_sha="x")


def test_identical_runs_produce_identical_digests(tmp_path):
    digests = []
    for n in range(2):
        (tmp_path / str(n)).mkdir()
        digests.append(resolved_d1(tmp_path / str(n))[2]["digest"])
    assert digests[0] == digests[1]


def test_malformed_receipts_are_reported_not_raised(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    for junk in ({}, {"receipt_version": 2, "payload": {}}, {"receipt_version": 1, "payload": "x"}, []):
        res = verify_receipt(junk, db)
        assert not res.ok and codes(res) == ["MALFORMED"]


def test_verify_receipt_script_exit_codes(tmp_path):
    e, inc, r, db = resolved_d1(tmp_path)
    path = write_receipt(r, str(tmp_path / "receipts"))
    assert load_receipt(path) == r
    script = os.path.join(ROOT, "scripts", "verify_receipt")

    def run(*args):
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, cwd=ROOT)

    ok = run("--db", db, path)
    assert ok.returncode == 0 and "OK incident=" in ok.stdout
    assert run("--db", db, str(tmp_path / "receipts")).returncode == 0

    edited = json.loads(open(path).read())
    edited["payload"]["outcome"] = "SKIPPED"
    bad_path = tmp_path / "receipts" / "bad.json"
    bad_path.write_text(json.dumps(edited))
    bad = run("--db", db, str(bad_path))
    assert bad.returncode == 1 and "BROKEN" in bad.stdout and "DIGEST_MISMATCH" in bad.stdout

    assert run("--db", str(tmp_path / "missing.db"), path).returncode == 2
