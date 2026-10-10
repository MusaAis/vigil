"""SPEC 9.8 required chain tests. Tamper tests use a RAW connection that drops the triggers first."""
import sqlite3
import threading

import pytest

from vigil.canonical import GENESIS_HASH, canonical_json, sha256_json
from vigil.chain import Chain, append_anchor, entry_hash, verify
from vigil.clock import VirtualClock


def make_chain(tmp_path, n=8, anchor=True):
    clock = VirtualClock("2026-10-10T08:00:00Z")
    db = str(tmp_path / "c.db")
    anchors = str(tmp_path / "anchors.txt")
    chain = Chain(db, clock)
    chain.append("inc_0001", "INCIDENT_OPENED", {"type": "duplicate_charge", "related": ["ch_1"]}, "t1")
    for i in range(1, n):
        clock.advance(2)
        chain.append("inc_0001", "OBSERVATION", {"step": i, "tool": "get_provider_charge",
                                                 "result_sha256": sha256_json({"i": i})}, "t1")
    if anchor:
        append_anchor(chain, anchors, "test", "abc1234")
    return chain, db, anchors


def raw(db):
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("DROP TRIGGER IF EXISTS chain_no_update")
    con.execute("DROP TRIGGER IF EXISTS chain_no_delete")
    return con


def test_clean_chain_verifies(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    res = verify(db, anchors)
    assert res.ok and res.head_seq == 7 and res.count == 8
    assert res.line().startswith("OK seq=0..7 head=sha256:")


def test_triggers_block_accidental_edits(tmp_path):
    chain, db, _ = make_chain(tmp_path, anchor=False)
    con = sqlite3.connect(db, isolation_level=None)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE decision_chain SET kind='OUTCOME' WHERE seq=2")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM decision_chain WHERE seq=2")


def test_edit_body_detected_at_that_seq(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    con = raw(db)
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=3",
                (canonical_json({"step": 3, "tool": "x", "result_sha256": "sha256:" + "0" * 64}),))
    res = verify(db, anchors)
    assert (res.ok, res.broken_seq, res.reason) == (False, 3, "HASH_MISMATCH")


def test_noncanonical_body_formatting_detected(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    con = raw(db)
    body = con.execute("SELECT body_json FROM decision_chain WHERE seq=2").fetchone()[0]
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=2", (body.replace(",", ", "),))
    res = verify(db, anchors)
    assert (res.broken_seq, res.reason) == (2, "HASH_MISMATCH")


def test_delete_middle_entry_detected(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    raw(db).execute("DELETE FROM decision_chain WHERE seq=3")
    res = verify(db, anchors)
    assert not res.ok and res.reason in ("SEQ_GAP", "PREV_MISMATCH") and res.broken_seq == 3


def test_reorder_two_entries_detected(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    con = raw(db)
    con.execute("UPDATE decision_chain SET seq=-1 WHERE seq=2")
    con.execute("UPDATE decision_chain SET seq=2 WHERE seq=3")
    con.execute("UPDATE decision_chain SET seq=3 WHERE seq=-1")
    res = verify(db, anchors)
    assert (res.ok, res.broken_seq, res.reason) == (False, 2, "PREV_MISMATCH")


def test_insert_forged_entry_detected(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    con = raw(db)
    for s in range(7, 3, -1):  # shift entries 4..7 up by one to make room at seq 4
        con.execute("UPDATE decision_chain SET seq=? WHERE seq=?", (s + 1, s))
    prev = con.execute("SELECT entry_hash FROM decision_chain WHERE seq=3").fetchone()[0]
    body = {"decision": "ACT", "tool": "issue_refund", "args": {"charge_id": "ch_X"},
            "rationale": "forged"}
    e = {"seq": 4, "ts": "2026-10-10T08:00:09Z", "incident_id": "inc_0001", "kind": "DECISION",
         "body": body, "trace_id": "t1", "prev_hash": prev}
    con.execute("INSERT INTO decision_chain VALUES(?,?,?,?,?,?,?,?)",
                (4, e["ts"], "inc_0001", "DECISION", canonical_json(body), "t1", prev, entry_hash(e)))
    res = verify(db, anchors)
    assert (res.ok, res.broken_seq, res.reason) == (False, 5, "PREV_MISMATCH")


def test_truncate_tail_detected_by_anchor(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    raw(db).execute("DELETE FROM decision_chain WHERE seq>=5")
    assert verify(db).ok  # internally consistent without the anchor...
    res = verify(db, anchors)  # ...but the published anchor exposes it
    assert (res.ok, res.broken_seq, res.reason) == (False, 7, "ANCHOR_SEQ_MISSING")


def test_rewritten_history_detected_by_anchor(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    con = raw(db)
    rows = con.execute("SELECT seq,ts,incident_id,kind,body_json,trace_id FROM decision_chain "
                       "ORDER BY seq").fetchall()
    con.execute("DELETE FROM decision_chain")
    import json
    prev = GENESIS_HASH
    for seq, ts, inc, kind, bj, tid in rows:
        body = json.loads(bj)
        if seq == 2:
            body["tool"] = "tampered"  # a consistent rewrite of the whole chain
        e = {"seq": seq, "ts": ts, "incident_id": inc, "kind": kind, "body": body,
             "trace_id": tid, "prev_hash": prev}
        h = entry_hash(e)
        con.execute("INSERT INTO decision_chain VALUES(?,?,?,?,?,?,?,?)",
                    (seq, ts, inc, kind, canonical_json(body), tid, prev, h))
        prev = h
    assert verify(db).ok  # self-consistent: only the anchor catches it
    res = verify(db, anchors)
    assert (res.ok, res.reason) == (False, "ANCHOR_MISMATCH")


def test_genesis_mismatch_detected(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    raw(db).execute("UPDATE decision_chain SET prev_hash='sha256:' || hex(zeroblob(32)) WHERE seq=0")
    res = verify(db, anchors)
    assert (res.broken_seq, res.reason) == (0, "GENESIS_MISMATCH")


def test_malformed_anchor_file_fails_closed(tmp_path):
    chain, db, anchors = make_chain(tmp_path)
    with open(anchors, "a") as f:
        f.write("garbage line\n")
    assert verify(db, anchors).ok is False


def test_float_and_nan_rejected_at_write_time(tmp_path):
    chain, db, _ = make_chain(tmp_path, anchor=False)
    before = chain.head()
    for bad in ({"amount": 1.5}, {"x": float("nan")}, {"y": [float("inf")]}):
        with pytest.raises(ValueError):
            chain.append("inc_0001", "OBSERVATION", bad, "t1")
    assert chain.head() == before  # nothing was written


def test_invalid_kind_and_missing_trace_rejected(tmp_path):
    chain, db, _ = make_chain(tmp_path, anchor=False)
    with pytest.raises(ValueError):
        chain.append("inc_0001", "NOPE", {}, "t1")
    with pytest.raises(ValueError):
        chain.append("inc_0001", "OBSERVATION", {}, "")


def test_concurrent_writers_no_fork(tmp_path):
    clock = VirtualClock()
    db = str(tmp_path / "conc.db")
    chains = [Chain(db, clock) for _ in range(3)]  # separate connections, like separate workers
    errors = []

    def work(c, tag):
        try:
            for i in range(40):
                c.append("inc_0001", "OBSERVATION", {"tag": tag, "i": i}, "t1")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(chains[i % 3], i)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    res = verify(db)
    assert res.ok and res.count == 240 and res.head_seq == 239


def test_same_scenario_twice_identical_hashes(tmp_path):
    def run(sub):
        d = tmp_path / sub
        d.mkdir()
        chain, db, _ = make_chain(d, anchor=False)
        return [e["entry_hash"] for e in chain.entries()]
    assert run("a") == run("b")


def test_has_committed_intent(tmp_path):
    chain, db, _ = make_chain(tmp_path, anchor=False)
    args = {"charge_id": "ch_B", "idempotency_key": "inc_0001:refund:1"}
    h = sha256_json(args)
    assert not chain.has_committed_intent("inc_0001", "issue_refund", h)
    chain.append("inc_0001", "ACTION_INTENT",
                 {"step": 2, "tool": "issue_refund", "args": args, "args_sha256": h,
                  "idempotency_key": "inc_0001:refund:1", "expected_effect": "refund ch_B"}, "t1")
    assert chain.has_committed_intent("inc_0001", "issue_refund", h)
    assert not chain.has_committed_intent("inc_0002", "issue_refund", h)


def test_empty_chain_and_anchor_refusal(tmp_path):
    chain = Chain(str(tmp_path / "e.db"), VirtualClock())
    assert verify(chain.db_path).ok
    with pytest.raises(RuntimeError):
        append_anchor(chain, str(tmp_path / "a.txt"), "x", "g")
