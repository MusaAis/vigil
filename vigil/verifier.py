"""Independent verifier (SPEC 8). Re-derives truth from provider + ledger; never trusts tool responses
or the agent's claims. confirm_no_action() backs the agent's right to say 'nothing to do'."""
from __future__ import annotations

from .clock import parse_ts
from .incidents import IncidentStore
from .policy import Policy
from sim.world import TrustedView


class Verifier:
    def __init__(self, view: TrustedView, policy: Policy, store: IncidentStore) -> None:
        self.view, self.policy, self.store = view, policy, store

    # ---- helpers
    def _later_charge(self, related: list[str]) -> dict:
        cs = sorted((self.view.charge(r) for r in related), key=lambda c: (c["created_at"], c["charge_id"]))
        return cs[-1]

    def net_credit(self, order_id: str) -> int:
        credited = sum(l["credit_minor"] for l in self.view.ledger_lines(order_id=order_id)
                       if l["account"] == "revenue")
        refunded = sum(l["debit_minor"] for l in self.view.ledger_lines(order_id=order_id)
                       if l["account"] == "refunds")
        return credited - refunded

    @staticmethod
    def _c(name: str, passed: bool, detail: str = "") -> dict:
        return {"check": name, "passed": bool(passed), "detail": detail}

    # ---- verify
    def verify(self, incident: dict) -> dict:
        t, rel = incident["type"], incident["related"]
        checks: list[dict] = []
        if t == "duplicate_charge":
            later = self._later_charge(rel)
            refs = [r for r in self.view.refunds() if r["charge_id"] == later["charge_id"]]
            good = [r for r in refs if r["status"] == "succeeded"]
            checks.append(self._c("refund_succeeded", len(good) >= 1))
            checks.append(self._c("exactly_one_refund", len(refs) == 1, f"{len(refs)} refunds"))
            checks.append(self._c("refund_amount_matches",
                                  len(good) == 1 and good[0]["amount_minor"] == later["amount_minor"]))
            order = self.view.order(later["order_ref"])
            checks.append(self._c("net_credit_equals_order_amount",
                                  self.net_credit(order["order_id"]) == order["amount_minor"]))
            checks.append(self._c("ledger_balanced", self.view.ledger_balanced()))
        elif t == "missing_webhook":
            ch = self.view.charge(rel[0])
            cr = self.view.revenue_credits(ch["charge_id"])
            checks.append(self._c("single_credit", len(cr) == 1, f"{len(cr)} credits"))
            checks.append(self._c("credit_amount_matches",
                                  len(cr) == 1 and cr[0]["credit_minor"] == ch["amount_minor"]))
            checks.append(self._c("no_duplicate_credit",
                                  sum(c["credit_minor"] for c in cr) <= ch["amount_minor"]))
            checks.append(self._c("ledger_balanced", self.view.ledger_balanced()))
        elif t == "stuck_payout":
            p = self.view.payout(rel[0])
            same = [x for x in self.view.payouts() if x["group"] == p["group"] and x["status"] == "paid"]
            checks.append(self._c("payout_paid", p["status"] == "paid"))
            checks.append(self._c("no_second_successful_payout", len(same) <= 1, f"{len(same)} paid in group"))
            checks.append(self._c("ledger_balanced", self.view.ledger_balanced()))
        elif t == "evidence_conflict":
            pkt = self.store.escalations.get(incident["incident_id"])
            checks.append(self._c("escalation_recorded", pkt is not None))
            checks.append(self._c("evidence_packet_complete",
                                  bool(pkt) and bool(pkt["summary"]) and len(pkt["evidence_refs"]) >= 1))
        else:
            checks.append(self._c("known_incident_type", False, t))
        return {"ok": all(c["passed"] for c in checks), "checks": checks}

    # ---- may the agent legitimately skip?
    def confirm_no_action(self, incident: dict) -> dict:
        """ok=True only if the detector's predicate is now FALSE (recomputed from trusted state)."""
        t, rel = incident["type"], incident["related"]
        still = True
        if t == "duplicate_charge":
            a, b = (self.view.charge(r) for r in rel)
            both = a["status"] == "succeeded" and b["status"] == "succeeded"
            same = (a["customer_id"], a["order_ref"], a["amount_minor"]) == \
                   (b["customer_id"], b["order_ref"], b["amount_minor"])
            gap = abs((parse_ts(b["created_at"]) - parse_ts(a["created_at"])).total_seconds())
            refunded = any(r["charge_id"] in rel for r in self.view.refunds())
            still = both and same and gap <= self.policy.duplicate_window_hours * 3600 and not refunded
        elif t == "missing_webhook":
            ch = self.view.charge(rel[0])
            still = ch["status"] == "succeeded" and not self.view.revenue_credits(ch["charge_id"])
        elif t == "stuck_payout":
            p = self.view.payout(rel[0])
            age = int((parse_ts(self.view.now()) - parse_ts(p["created_at"])).total_seconds())
            still = p["status"] in ("pending", "processing") and age > self.policy.payout_sla_seconds
        elif t == "evidence_conflict":
            ch = self.view.charge(rel[0])
            still = ch["status"] == "failed" and bool(self.view.revenue_credits(ch["charge_id"]))
        return {"ok": not still, "condition_still_true": still}
