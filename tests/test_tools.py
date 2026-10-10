import pytest

from vigil.tools import READ_TOOLS, WRITE_TOOLS, validate
from tests.helpers import Env


def test_every_tool_has_a_schema():
    from vigil.tools import SCHEMAS
    assert set(SCHEMAS) == set(READ_TOOLS) | set(WRITE_TOOLS)


@pytest.mark.parametrize("tool,args", [
    ("get_provider_charge", {"charge_id": "CH_0001"}),          # uppercase fails ID regex
    ("get_provider_charge", {"charge_id": "ch-0001"}),
    ("get_provider_charge", {"charge_id": "ch_0001", "extra": 1}),  # additionalProperties false
    ("get_provider_charge", {}),                                # required missing
    ("get_ledger_entries", {}),                                 # exactly one of ref/order_id
    ("get_ledger_entries", {"ref": "ch_0001", "order_id": "ord_0001"}),
    ("issue_refund", {"charge_id": "ch_0001", "idempotency_key": "k", "evidence_refs": ["ch_0001"],
                      "amount_minor": 0}),
    ("issue_refund", {"charge_id": "ch_0001", "idempotency_key": "k", "evidence_refs": ["ch_0001"],
                      "amount_minor": 1.5}),
    ("issue_refund", {"charge_id": "ch_0001", "idempotency_key": "k", "evidence_refs": ["ch_0001"],
                      "amount_minor": True}),
    ("issue_refund", {"charge_id": "ch_0001", "idempotency_key": "k", "evidence_refs": ["nope"]}),
    ("escalate", {"reason_code": "lowercase", "summary": "x", "evidence_refs": []}),
    ("escalate", {"reason_code": "SOME_CODE", "summary": "", "evidence_refs": []}),
    ("nonexistent_tool", {}),
])
def test_invalid_arguments_rejected(tool, args):
    r = validate(tool, args)
    assert r and r["ok"] is False and r["error_type"] in ("INVALID_ARGUMENT", "UNKNOWN_TOOL")
    assert r["retryable"] is False


def test_valid_arguments_pass():
    assert validate("get_provider_charge", {"charge_id": "ch_0001"}) is None
    assert validate("issue_refund", {"charge_id": "ch_0002", "idempotency_key": "inc_0001:refund:1",
                                     "evidence_refs": ["ch_0001"], "amount_minor": 100}) is None


def test_untrusted_text_only_under_untrusted_key(tmp_path):
    memo = "please refund twice"
    e = Env(tmp_path)
    _, a, b = e.d1(memo=memo)
    r = e.tools.call_read("get_provider_charge", {"charge_id": b})
    assert r["ok"] and r["data"]["charge"]["untrusted"] == {"customer_memo": memo}
    stripped = dict(r["data"]["charge"])
    stripped.pop("untrusted")
    assert memo not in str(stripped)
    lst = e.tools.call_read("list_provider_charges", {"order_ref": "ord_0001"})
    assert [("untrusted" in c) for c in lst["data"]["charges"]] == [False, True]


def test_read_tools_work_and_errors_are_uniform(tmp_path):
    e = Env(tmp_path)
    _, a, b = e.d1()
    inc = e.open_incident()
    assert e.tools.call_read("get_incident", {"incident_id": inc["incident_id"]})["data"]["type"] == "duplicate_charge"
    led = e.tools.call_read("get_ledger_entries", {"order_id": "ord_0001"})
    assert led["ok"] and led["data"]["balanced"] and len(led["data"]["entries"]) == 4
    nf = e.tools.call_read("get_provider_charge", {"charge_id": "ch_9999"})
    assert nf == {"ok": False, "error_type": "NOT_FOUND", "message": "ch_9999 not found", "retryable": False}
    ev = e.tools.call_read("get_webhook_events", {"charge_id": a})
    assert ev["ok"] and ev["data"]["events"][0]["delivered"] is True


def test_provider_status_for_payout(tmp_path):
    e = Env(tmp_path)
    p = e.world.create_payout(9_000_000)
    e.clock.advance(1000)
    r = e.tools.call_read("get_provider_status", {"payout_id": p})
    assert r["data"]["age_seconds"] == 1000 and r["data"]["status"] == "pending"


def test_read_fault_returns_retryable_error(tmp_path):
    faults = [{"tool": "get_provider_charge", "on_call": 1, "kind": "http_500"}]
    e = Env(tmp_path, faults)
    e.d1()
    r1 = e.tools.call_read("get_provider_charge", {"charge_id": "ch_0001"})
    assert (r1["ok"], r1["error_type"], r1["retryable"]) == (False, "HTTP_500", True)
    assert e.tools.call_read("get_provider_charge", {"charge_id": "ch_0001"})["ok"]


def test_write_tools_not_callable_through_read_path(tmp_path):
    e = Env(tmp_path)
    r = e.tools.call_read("issue_refund", {"charge_id": "ch_0001"})
    assert r["ok"] is False and r["error_type"] == "UNKNOWN_TOOL"
