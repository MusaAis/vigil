"""Model interface for the agent loop (SPEC 7) and the deterministic offline model.

A model sees only structured facts: the incident summary and the transcript of earlier proposals with the
feedback they produced. The offline model reads named fields only and never touches 'untrusted' blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

DUPLICATE_WINDOW_SECONDS = 24 * 3600
MAX_READ_FAILURES = 3


@dataclass(frozen=True)
class Proposal:
    kind: str = "tool"                 # "tool" | "skip" | "none"
    tool: Optional[str] = None
    args: Any = field(default_factory=dict)
    rationale: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class Turn:
    proposal: Proposal
    feedback: dict


class ModelClient(Protocol):
    def propose(self, incident: dict, turns: list, step: int) -> Proposal: ...


def _find_read(turns: list, tool: str, args: dict):
    """Latest successful result for this read call and the number of failures since the last success."""
    last, fails = None, 0
    for t in turns:
        p = t.proposal
        if p.tool == tool and p.args == args and t.feedback.get("type") == "tool_result":
            res = t.feedback["result"]
            if res.get("ok"):
                last, fails = res, 0
            else:
                fails += 1
    return last, fails


def _escalation(incident: dict, code: str, summary: str, rationale: str) -> Proposal:
    return Proposal(tool="escalate", rationale=rationale,
                    args={"reason_code": code, "summary": summary, "evidence_refs": list(incident["related"])})


def _count_proposals(turns: list, tool: str) -> int:
    return sum(1 for t in turns if t.proposal.tool == tool)


class OfflineModel:
    """Rule-based stand-in for the LLM. Deterministic, zero cost, used by tests, `make demo` and CI."""

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        iid, itype, related = incident["incident_id"], incident["type"], incident["related"]

        if turns:
            fb = turns[-1].feedback
            if fb.get("type") == "gate" and fb.get("verdict") == "DENY":
                return _escalation(incident, "GATE_DENIED", f"Policy gate denied the proposed action ({fb.get('code')}).",
                                   "The gate denied the action; a human should review.")
            if fb.get("type") == "action_result" and not fb.get("verification_ok"):
                return _escalation(incident, "VERIFICATION_FAILED", "The action did not verify.",
                                   "Independent verification failed after the action.")
            if fb.get("type") == "skip_rejected":
                return _escalation(incident, "SKIP_REJECTED", "Verifier says the condition still holds.",
                                   "Verifier disagrees with skipping.")

        def need(tool: str, args: dict, why: str):
            res, fails = _find_read(turns, tool, args)
            if res is not None:
                return res["data"], None
            if fails >= MAX_READ_FAILURES:
                return None, _escalation(incident, "TOOL_UNAVAILABLE", f"{tool} kept failing.",
                                         f"{tool} failed {fails} times in a row.")
            return None, Proposal(tool=tool, args=args, rationale=why)

        _, p = need("get_incident", {"incident_id": iid}, "Read the incident record first.")
        if p:
            return p

        if itype == "duplicate_charge":
            charges = []
            for cid in related:
                data, p = need("get_provider_charge", {"charge_id": cid}, f"Read charge {cid} at the provider.")
                if p:
                    return p
                charges.append(data["charge"])
            return self._decide_duplicate(incident, turns, charges)

        if itype == "missing_webhook":
            cid = related[0]
            ch, p = need("get_provider_charge", {"charge_id": cid}, f"Read charge {cid} at the provider.")
            if p:
                return p
            ev, p = need("get_webhook_events", {"charge_id": cid}, "Check webhook delivery for the charge.")
            if p:
                return p
            led, p = need("get_ledger_entries", {"ref": cid}, "Check the merchant ledger for a credit.")
            if p:
                return p
            credited = any(l["account"] == "revenue" and l["credit_minor"] > 0 for l in led["entries"])
            if ch["charge"]["status"] != "succeeded" or credited:
                return Proposal(kind="skip", rationale="The charge is already credited or did not succeed.")
            events = [e for e in ev["events"] if e["type"] == "charge.succeeded"]
            if not events:
                return _escalation(incident, "EVIDENCE_MISSING", "No success event exists to replay.",
                                   "There is no webhook event to replay.")
            n = _count_proposals(turns, "replay_webhook") + 1
            return Proposal(tool="replay_webhook", rationale="Provider shows success but the ledger has no credit; replay the event once.",
                            args={"event_id": events[0]["event_id"], "idempotency_key": f"{iid}:replay:{n}",
                                  "evidence_refs": [cid, events[0]["event_id"]]})

        if itype == "stuck_payout":
            pid = related[0]
            st, p = need("get_provider_status", {"payout_id": pid}, f"Read payout {pid} status at the provider.")
            if p:
                return p
            if st["status"] == "paid":
                return Proposal(kind="skip", rationale="The payout is already paid.")
            if st["status"] == "failed" or st["retryable"]:
                n = _count_proposals(turns, "retry_payout") + 1
                return Proposal(tool="retry_payout", rationale="The payout is failed or stuck and the provider allows a retry.",
                                args={"payout_id": pid, "idempotency_key": f"{iid}:retry:{n}", "evidence_refs": [pid]})
            return _escalation(incident, "PAYOUT_NOT_RETRYABLE", "Payout is stuck and the provider does not allow a retry.",
                               "The provider does not allow a retry.")

        if itype == "evidence_conflict":
            cid = related[0]
            _, p = need("get_provider_charge", {"charge_id": cid}, f"Read charge {cid} at the provider.")
            if p:
                return p
            _, p = need("get_ledger_entries", {"ref": cid}, "Read the ledger entries for the charge.")
            if p:
                return p
            return _escalation(incident, "EVIDENCE_CONFLICT",
                               "The ledger shows a credit for a charge the provider reports as failed.",
                               "Ledger and provider disagree; a human must reconcile.")

        return _escalation(incident, "UNKNOWN_INCIDENT_TYPE", f"No playbook for {itype}.", "No playbook for this incident type.")

    @staticmethod
    def _decide_duplicate(incident: dict, turns: list, charges: list) -> Proposal:
        from .clock import parse_ts
        a, b = sorted(charges, key=lambda c: (c["created_at"], c["charge_id"]))
        same = (a["customer_id"], a["order_ref"], a["amount_minor"]) == (b["customer_id"], b["order_ref"], b["amount_minor"])
        gap = (parse_ts(b["created_at"]) - parse_ts(a["created_at"])).total_seconds()
        both = a["status"] == "succeeded" and b["status"] == "succeeded"
        if not (same and both and gap <= DUPLICATE_WINDOW_SECONDS):
            return Proposal(kind="skip", rationale="The two charges do not form a duplicate.")
        n = _count_proposals(turns, "issue_refund") + 1
        return Proposal(tool="issue_refund",
                        rationale="Two succeeded charges share customer, order and amount within the window; refund the later one.",
                        args={"charge_id": b["charge_id"], "idempotency_key": f"{incident['incident_id']}:refund:{n}",
                              "evidence_refs": [a["charge_id"], b["charge_id"]]})
