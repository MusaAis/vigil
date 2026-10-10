"""Deterministic policy gate (SPEC 6). The model proposes; this code decides. No LLM, no free text in.

Inputs are ONLY: incident, tool name, args (not the agent's rationale), trusted provider/ledger state,
the chain (for prior intents), the policy and the clock. Untrusted text is unreachable by construction."""
from __future__ import annotations

from typing import Optional

from .canonical import sha256_json
from .chain import Chain
from .incidents import IncidentStore
from .policy import Policy
from sim.world import TrustedView

ACTION_NAME = {"issue_refund": "refund", "replay_webhook": "replay", "retry_payout": "retry"}


class Gate:
    def __init__(self, policy: Policy, view: TrustedView, chain: Chain, store: IncidentStore) -> None:
        self.policy, self.view, self.chain, self.store = policy, view, chain, store

    def _v(self, verdict: str, code: str, details: Optional[dict] = None) -> dict:
        return {"verdict": verdict, "code": code, "details": details or {},
                "policy_version": self.policy.version, "policy_sha256": self.policy.sha256}

    def _prior_intents(self, incident_id: str) -> list[dict]:
        return [e for e in self.chain.entries(incident_id) if e["kind"] == "ACTION_INTENT"]

    def evaluate(self, incident: dict, tool: str, args: dict) -> dict:
        p, iid = self.policy, incident["incident_id"]
        # 1. allowed action
        if tool not in p.allowed_actions:
            return self._v("DENY", "ACTION_NOT_ALLOWED")
        # 2. escalate is always allowed
        if tool == "escalate":
            return self._v("ALLOW", "OK")
        # 3. incident must not be terminal
        if self.store.is_terminal(iid):
            return self._v("DENY", "INCIDENT_CLOSED")
        prior = [e for e in self._prior_intents(iid) if e["body"].get("tool") != "escalate"]
        # 4. write-action budget
        if len(prior) >= p.max_write_actions_per_incident:
            return self._v("ESCALATE", "MAX_ACTIONS_EXCEEDED", {"actions_so_far": len(prior)})
        # 5. idempotency key format <incident_id>:<action>:<n>
        key = args.get("idempotency_key")
        action = ACTION_NAME[tool]
        import re
        if not isinstance(key, str) or not re.match(rf"^{re.escape(iid)}:{action}:[1-9][0-9]*$", key):
            return self._v("DENY", "MISSING_IDEMPOTENCY_KEY")
        # 6. no repeat of an already-committed identical intent
        h = sha256_json(args)
        if any(e["body"].get("tool") == tool and e["body"].get("args_sha256") == h for e in prior):
            return self._v("DENY", "DUPLICATE_ACTION")
        # 7. evidence must exist
        for ref in args.get("evidence_refs", []):
            if not self.view.exists(ref):
                return self._v("DENY", "EVIDENCE_NOT_FOUND", {"ref": ref})
        # 8. type-specific predicate, re-derived from trusted state
        amount = 0
        if tool == "issue_refund":
            r = self._refund_predicate(incident, args)
            if r is not None:
                return r
            ch = self.view.charge(args["charge_id"])
            amount = args.get("amount_minor", ch["amount_minor"])
        elif tool == "replay_webhook":
            r = self._replay_predicate(args)
            if r is not None:
                return r
        elif tool == "retry_payout":
            r = self._retry_predicate(args)
            if r is not None:
                return r
        if tool == "issue_refund":
            # 9. per-incident cap (provider-derived)
            spent = self._refunded_for_incident(iid)
            if spent + amount > p.max_refund_per_incident_minor:
                return self._v("ESCALATE", "AMOUNT_OVER_INCIDENT_CAP",
                               {"amount_minor": amount, "already_refunded_minor": spent,
                                "cap_minor": p.max_refund_per_incident_minor})
            # 10. per-day cap
            today = self.view.now()[:10]
            day = sum(r["amount_minor"] for r in self.view.refunds()
                      if r["status"] == "succeeded" and r["created_at"][:10] == today)
            if day + amount > p.max_refund_per_day_minor:
                return self._v("ESCALATE", "AMOUNT_OVER_DAILY_CAP",
                               {"amount_minor": amount, "refunded_today_minor": day,
                                "cap_minor": p.max_refund_per_day_minor})
        # 11.
        return self._v("ALLOW", "OK")

    # ---- predicates
    def _refunded_for_incident(self, incident_id: str) -> int:
        return sum(r["amount_minor"] for r in self.view.refunds()
                   if r["status"] == "succeeded" and r["idempotency_key"].startswith(incident_id + ":"))

    def _refund_predicate(self, incident: dict, args: dict) -> Optional[dict]:
        ch = self.view.charge(args["charge_id"])
        if ch is None:
            return self._v("DENY", "EVIDENCE_NOT_FOUND", {"ref": args["charge_id"]})
        amt = args.get("amount_minor", ch["amount_minor"])
        if amt > ch["amount_minor"]:
            return self._v("DENY", "REFUND_EXCEEDS_CHARGE")
        already = sum(r["amount_minor"] for r in self.view.refunds()
                      if r["charge_id"] == ch["charge_id"] and r["status"] == "succeeded")
        if already + amt > ch["amount_minor"]:
            return self._v("DENY", "ALREADY_REFUNDED", {"already_refunded_minor": already})
        # provider must show a genuine duplicate: another succeeded charge, same customer+order+amount, in window
        from .clock import parse_ts
        window = self.policy.duplicate_window_hours * 3600
        mates = [c for c in self.view.charges()
                 if c["charge_id"] != ch["charge_id"] and c["status"] == "succeeded"
                 and (c["customer_id"], c["order_ref"], c["amount_minor"])
                 == (ch["customer_id"], ch["order_ref"], ch["amount_minor"])
                 and abs((parse_ts(c["created_at"]) - parse_ts(ch["created_at"])).total_seconds()) <= window]
        if ch["status"] != "succeeded" or not mates:
            return self._v("DENY", "NOT_DUPLICATE")
        # only the LATER charge may be refunded
        if any((m["created_at"], m["charge_id"]) > (ch["created_at"], ch["charge_id"]) for m in mates):
            return self._v("DENY", "NOT_DUPLICATE", {"reason": "not the later charge"})
        return None

    def _replay_predicate(self, args: dict) -> Optional[dict]:
        ev = self.view.event(args["event_id"])
        if ev is None:
            return self._v("DENY", "EVIDENCE_NOT_FOUND", {"ref": args["event_id"]})
        ch = self.view.charge(ev["charge_id"])
        # charge must be succeeded at the provider AND have no ledger credit (SPEC 6.2)
        if ch is None or ch["status"] != "succeeded" or self.view.revenue_credits(ch["charge_id"]):
            return self._v("DENY", "NO_MISSING_CREDIT")
        return None

    def _retry_predicate(self, args: dict) -> Optional[dict]:
        p = self.view.payout(args["payout_id"])
        if p is None:
            return self._v("DENY", "EVIDENCE_NOT_FOUND", {"ref": args["payout_id"]})
        from .clock import parse_ts
        age = int((parse_ts(self.view.now()) - parse_ts(p["created_at"])).total_seconds())
        stuck = p["status"] in ("pending", "processing") and age > self.policy.payout_sla_seconds \
            and p["retryable"] is True
        if not (p["status"] == "failed" or stuck):
            return self._v("DENY", "PAYOUT_NOT_RETRYABLE")
        return None
