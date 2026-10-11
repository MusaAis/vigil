from tests.helpers import AMOUNT, Env, refund_args


def test_duplicate_fix_verified_and_unfixed_not(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    assert e.verifier.verify(inc)["ok"] is False  # nothing fixed yet
    assert e.world.create_refund(b, None, f"{inc['incident_id']}:refund:1")["ok"]
    res = e.verifier.verify(inc)
    assert res["ok"] and all(c["passed"] for c in res["checks"])
    assert e.verifier.net_credit(o) == AMOUNT


def test_refund_of_wrong_charge_or_amount_fails_verification(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    e.world.create_refund(a, None, "k")  # refunded the EARLIER charge, not the later one
    assert e.verifier.verify(inc)["ok"] is False


def test_partial_refund_fails_amount_check(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    e.world.create_refund(b, AMOUNT // 2, "k")
    res = e.verifier.verify(inc)
    assert not res["ok"] and not {c["check"]: c["passed"] for c in res["checks"]}["refund_amount_matches"]


def test_missing_webhook_verification(tmp_path):
    e = Env(tmp_path)
    o = e.world.create_order("cust_01", AMOUNT)
    c = e.world.create_charge(o, AMOUNT, webhook="drop")
    e.clock.advance(200)
    inc = e.open_incident()
    assert e.verifier.verify(inc)["ok"] is False
    evt = e.view.events_for_charge(c)[0]["event_id"]
    e.world.replay_webhook(evt, "k1")
    assert e.verifier.verify(inc)["ok"] is True


def test_stuck_payout_verification(tmp_path):
    e = Env(tmp_path)
    p = e.world.create_payout(9_000_000)
    e.clock.advance(1000)
    inc = e.open_incident()
    assert e.verifier.verify(inc)["ok"] is False
    e.world.retry_payout(p, "k1")
    assert e.verifier.verify(inc)["ok"] is True


def test_failed_payout_is_not_confirmed_as_no_action_until_it_is_paid(tmp_path):
    e = Env(tmp_path)
    p = e.world.create_payout(9_000_000, status="failed")
    inc = e.open_incident()
    assert e.verifier.confirm_no_action(inc)["ok"] is False
    assert e.verifier.verify(inc)["ok"] is False
    e.world.retry_payout(p, "k1")
    assert e.verifier.confirm_no_action(inc)["ok"] is True
    assert e.verifier.verify(inc)["ok"] is True


def test_evidence_conflict_needs_escalation_with_evidence(tmp_path):
    e = Env(tmp_path)
    o = e.world.create_order("cust_01", AMOUNT)
    c = e.world.create_charge(o, AMOUNT, status="failed")
    e.world.inject_ledger_credit(c)
    inc = e.open_incident()
    assert e.verifier.verify(inc)["ok"] is False
    e.store.escalate(inc["incident_id"], "EVIDENCE_CONFLICT", "ledger credit but provider says failed", [c])
    assert e.verifier.verify(inc)["ok"] is True


def test_confirm_no_action_false_while_problem_persists(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    res = e.verifier.confirm_no_action(inc)
    assert res["ok"] is False and res["condition_still_true"] is True


def test_confirm_no_action_true_when_provider_resolves_itself_X4(tmp_path):
    e = Env(tmp_path)
    o = e.world.create_order("cust_01", AMOUNT)
    c = e.world.create_charge(o, AMOUNT, webhook="drop")
    e.clock.advance(200)
    inc = e.open_incident()
    assert e.verifier.confirm_no_action(inc)["ok"] is False
    evt = e.view.events_for_charge(c)[0]["event_id"]
    e.world._deliver(evt)  # the webhook finally arrives on its own (race)
    assert e.verifier.confirm_no_action(inc)["ok"] is True


def test_two_partial_refunds_fail_exactly_one_refund(tmp_path):
    e = Env(tmp_path)
    o, a, b = e.d1()
    inc = e.open_incident()
    e.world.create_refund(b, AMOUNT // 2, "k1")
    e.world.create_refund(b, AMOUNT - AMOUNT // 2, "k2")  # sums to the full amount, but as two refunds
    res = e.verifier.verify(inc)
    checks = {c["check"]: c["passed"] for c in res["checks"]}
    assert checks["exactly_one_refund"] is False and res["ok"] is False
