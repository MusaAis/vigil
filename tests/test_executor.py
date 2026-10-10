import pytest

from vigil.canonical import sha256_json
from vigil.executor import IntentMissing, NotAllowed
from tests.helpers import Env, refund_args


def allow():
    return {"verdict": "ALLOW", "code": "OK", "details": {}, "policy_version": 1, "policy_sha256": "x"}


def test_inv5_write_without_committed_intent_raises_and_changes_nothing(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    args = refund_args(inc["incident_id"], b)
    with pytest.raises(IntentMissing):
        e.executor.execute(inc["incident_id"], 1, "issue_refund", args, allow(), "t1")
    assert e.view.refunds() == []


def test_intent_for_different_args_does_not_authorise(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    iid = inc["incident_id"]
    e.executor.commit_intent(iid, 1, "issue_refund", refund_args(iid, b, n=1), "x", "t1")
    with pytest.raises(IntentMissing):
        e.executor.execute(iid, 1, "issue_refund", refund_args(iid, b, n=2), allow(), "t1")


def test_non_allow_verdict_cannot_execute(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    iid = inc["incident_id"]
    args = refund_args(iid, b)
    e.executor.commit_intent(iid, 1, "issue_refund", args, "x", "t1")
    for v in ("DENY", "ESCALATE"):
        with pytest.raises(NotAllowed):
            e.executor.execute(iid, 1, "issue_refund", args, {**allow(), "verdict": v}, "t1")
    assert e.view.refunds() == []


def test_happy_path_records_result_and_verifies(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    iid = inc["incident_id"]
    args = refund_args(iid, b)
    verdict = e.gate.evaluate(inc, "issue_refund", args)
    assert verdict["verdict"] == "ALLOW"
    e.executor.commit_intent(iid, 1, "issue_refund", args, "refund later duplicate charge", "t1")
    resp = e.executor.execute(iid, 1, "issue_refund", args, verdict, "t1")
    assert resp["ok"] and e.verifier.verify(inc)["ok"]
    kinds = [x["kind"] for x in e.chain.entries(iid)]
    assert kinds == ["ACTION_INTENT", "ACTION_RESULT"]


def test_timeout_after_effect_retry_same_key_one_refund_total(tmp_path):
    faults = [{"tool": "issue_refund", "on_call": 1, "kind": "timeout", "apply_before_timeout": True}]
    e = Env(tmp_path, faults)
    o, a, b = e.d1()
    inc = e.open_incident()
    iid = inc["incident_id"]
    args = refund_args(iid, b)
    verdict = e.gate.evaluate(inc, "issue_refund", args)
    e.executor.commit_intent(iid, 1, "issue_refund", args, "x", "t1")
    resp = e.executor.execute(iid, 1, "issue_refund", args, verdict, "t1")
    assert resp["ok"] and len(e.view.refunds()) == 1
    results = [x["body"] for x in e.chain.entries(iid) if x["kind"] == "ACTION_RESULT"]
    assert [(r["attempt"], r["ok"]) for r in results] == [(1, False), (2, True)]
    assert e.verifier.verify(inc)["ok"]


def test_retries_are_bounded(tmp_path):
    faults = [{"tool": "retry_payout", "on_call": [1, 2, 3, 4, 5], "kind": "http_500"}]
    e = Env(tmp_path, faults)
    p = e.world.create_payout(9_000_000)
    e.clock.advance(1000)
    inc = e.open_incident()
    iid = inc["incident_id"]
    args = {"payout_id": p, "idempotency_key": f"{iid}:retry:1", "evidence_refs": [p]}
    verdict = e.gate.evaluate(inc, "retry_payout", args)
    e.executor.commit_intent(iid, 1, "retry_payout", args, "x", "t1")
    resp = e.executor.execute(iid, 1, "retry_payout", args, verdict, "t1")
    assert not resp["ok"]
    assert len([x for x in e.chain.entries(iid) if x["kind"] == "ACTION_RESULT"]) == 3


def test_escalate_records_packet_and_terminal_state_is_immutable(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    iid = inc["incident_id"]
    args = {"reason_code": "AMOUNT_OVER_INCIDENT_CAP", "summary": "needs a human", "evidence_refs": [a, b]}
    e.executor.commit_intent(iid, 1, "escalate", args, "escalate", "t1")
    resp = e.executor.execute(iid, 1, "escalate", args, allow(), "t1")
    assert resp["ok"] and e.store.get(iid)["status"] == "ESCALATED"
    with pytest.raises(RuntimeError):
        e.store.set_status(iid, "RESOLVED")
