"""SIMULATED payment provider (SPEC 3). All data is fake. Deterministic given a Clock and a fault plan.

Safe-by-construction: free text from customers/webhooks is stored in a separate untrusted store.
Trusted code (detector, gate, verifier) only receives a TrustedView, which has no way to read it.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from vigil.canonical import sha256_json
from vigil.clock import Clock, parse_ts

from .ledger import Ledger


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err(error_type: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "error_type": error_type, "message": message, "retryable": retryable}


class World:
    def __init__(self, clock: Clock, faults: Optional[list] = None) -> None:
        self.clock = clock
        self.ledger = Ledger(clock)
        self.orders: dict[str, dict] = {}
        self.charges: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.payouts: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self._untrusted: dict[tuple, str] = {}
        self._idem: dict[str, tuple] = {}
        self._counters: dict[str, int] = {}
        self._calls: dict[str, int] = {}
        self.faults = list(faults or [])
        self.log: list[str] = []

    # ------------------------------------------------------------ helpers
    def _id(self, prefix: str, width: int = 4) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}_{self._counters[prefix]:0{width}d}"

    def set_untrusted(self, kind: str, obj_id: str, text: str) -> None:
        self._untrusted[(kind, obj_id)] = text

    def untrusted_for(self, kind: str, obj_id: str) -> Optional[str]:
        return self._untrusted.get((kind, obj_id))

    def trusted(self) -> "TrustedView":
        return TrustedView(self)

    def with_faults(self, tool: str, fn):
        """Apply the fault plan to one provider-facing tool call (SPEC 3.3, 7.3)."""
        n = self._calls[tool] = self._calls.get(tool, 0) + 1
        for f in self.faults:
            if f.get("tool") != tool:
                continue
            on = f.get("on_call")
            hit = (n == on) if isinstance(on, int) else (n in on if on else True)
            if not hit:
                continue
            if f["kind"] == "http_500":
                return err("HTTP_500", "provider returned 500", True)
            if f["kind"] == "timeout":
                if f.get("apply_before_timeout"):
                    fn()
                return err("TIMEOUT", "provider timed out", True)
        return fn()

    def _idempotent(self, key: str, body: dict, fn) -> dict:
        if not key:
            return err("MISSING_IDEMPOTENCY_KEY", "idempotency key required")
        h = sha256_json(body)
        if key in self._idem:
            old_h, resp = self._idem[key]
            if old_h != h:
                return err("IDEMPOTENCY_CONFLICT", "key reused with a different request body (409)")
            return copy.deepcopy(resp)
        resp = fn()
        self._idem[key] = (h, copy.deepcopy(resp))
        return resp

    # ------------------------------------------------------------ fixtures / provider side
    def create_order(self, customer_id: str, amount_minor: int) -> str:
        oid = self._id("ord")
        self.orders[oid] = {"order_id": oid, "order_ref": oid, "customer_id": customer_id,
                            "amount_minor": amount_minor, "status": "created",
                            "created_at": self.clock.now()}
        return oid

    def create_charge(self, order_ref: str, amount_minor: int, status: str = "succeeded",
                      memo: Optional[str] = None, webhook: str = "deliver",
                      delay_seconds: int = 0, event_note: Optional[str] = None) -> str:
        """webhook: 'deliver' | 'drop' | 'duplicate' | 'delay'."""
        order = self.orders[order_ref]
        cid = self._id("ch")
        self.charges[cid] = {"charge_id": cid, "order_ref": order_ref, "customer_id": order["customer_id"],
                             "amount_minor": amount_minor, "currency": "NGN", "status": status,
                             "created_at": self.clock.now()}
        if memo is not None:
            self.set_untrusted("charge", cid, memo)
        etype = "charge.succeeded" if status == "succeeded" else "charge.failed"
        eid = self._id("evt")
        due = parse_ts(self.clock.now()).timestamp() + (delay_seconds if webhook == "delay" else 0)
        self.events[eid] = {"event_id": eid, "type": etype, "charge_id": cid, "order_ref": order_ref,
                            "created_at": self.clock.now(), "delivered": False, "attempts": 0,
                            "deliver_at": due, "drop": webhook == "drop"}
        if event_note:
            self.set_untrusted("event", eid, event_note)
        if webhook in ("deliver", "duplicate"):
            self._deliver(eid)
        if webhook == "duplicate":
            self._deliver(eid)
        return cid

    def process_due_events(self) -> None:
        now = parse_ts(self.clock.now()).timestamp()
        for e in self.events.values():
            if not e["delivered"] and not e["drop"] and e["deliver_at"] <= now:
                self._deliver(e["event_id"])

    def create_payout(self, amount_minor: int, status: str = "pending", retryable: bool = True,
                      group: Optional[str] = None) -> str:
        pid = self._id("po")
        self.payouts[pid] = {"payout_id": pid, "amount_minor": amount_minor, "status": status,
                             "retryable": retryable, "group": group or pid, "created_at": self.clock.now()}
        return pid

    def fail_payout(self, payout_id: str) -> None:
        self.payouts[payout_id]["status"] = "failed"

    def settle_payout(self, payout_id: str) -> None:
        """Provider settles on its own (e.g. a race with the agent)."""
        p = self.payouts[payout_id]
        if p["status"] != "paid":
            p["status"] = "paid"
            self.ledger.post("payouts_payable", "provider_clearing", p["amount_minor"], payout_id,
                             None, f"payout:{payout_id}")

    def inject_ledger_credit(self, charge_id: str) -> None:
        """FIXTURE ONLY: create a ledger/provider disagreement (scenario X1)."""
        c = self.charges[charge_id]
        self.ledger.post("provider_clearing", "revenue", c["amount_minor"], charge_id, c["order_ref"],
                         f"fixture:{charge_id}")

    # ------------------------------------------------------------ merchant webhook handler
    def _deliver(self, event_id: str) -> str:
        e = self.events[event_id]
        e["attempts"] += 1
        e["delivered"] = True
        if e["type"] != "charge.succeeded":
            return "ignored"
        c = self.charges[e["charge_id"]]
        if self.ledger.revenue_credits(c["charge_id"]):
            self.log.append(f"duplicate delivery ignored for {event_id}")
            return "duplicate_ignored"
        self.ledger.post("provider_clearing", "revenue", c["amount_minor"], c["charge_id"],
                         c["order_ref"], f"charge:{c['charge_id']}")
        o = self.orders[c["order_ref"]]
        if o["status"] == "created":
            o["status"] = "paid"
        return "credited"

    # ------------------------------------------------------------ provider API (called via tools)
    def create_refund(self, charge_id: str, amount_minor: Optional[int], key: str) -> dict:
        c = self.charges.get(charge_id)
        if c is None:
            return err("NOT_FOUND", f"{charge_id} not found")
        amt = c["amount_minor"] if amount_minor is None else amount_minor

        def run() -> dict:
            if c["status"] != "succeeded":
                return err("CHARGE_NOT_SUCCEEDED", "charge did not succeed")
            already = sum(r["amount_minor"] for r in self.refunds.values()
                          if r["charge_id"] == charge_id and r["status"] == "succeeded")
            if amt <= 0 or amt + already > c["amount_minor"]:
                return err("REFUND_EXCEEDS_CHARGE", "refund exceeds remaining charge amount (422)")
            rid = self._id("rf")
            self.refunds[rid] = {"refund_id": rid, "charge_id": charge_id, "amount_minor": amt,
                                 "status": "succeeded", "created_at": self.clock.now(),
                                 "idempotency_key": key}
            self.ledger.post("refunds", "provider_clearing", amt, rid, c["order_ref"], f"refund:{rid}")
            o = self.orders[c["order_ref"]]
            total = sum(r["amount_minor"] for r in self.refunds.values()
                        if self.charges[r["charge_id"]]["order_ref"] == o["order_id"])
            o["status"] = "refunded" if total >= o["amount_minor"] else "partially_refunded"
            return ok({"refund_id": rid, "charge_id": charge_id, "amount_minor": amt, "status": "succeeded"})

        return self._idempotent(key, {"op": "refund", "charge_id": charge_id, "amount_minor": amt}, run)

    def replay_webhook(self, event_id: str, key: str) -> dict:
        if event_id not in self.events:
            return err("NOT_FOUND", f"{event_id} not found")

        def run() -> dict:
            return ok({"event_id": event_id, "result": self._deliver(event_id)})

        return self._idempotent(key, {"op": "replay", "event_id": event_id}, run)

    def retry_payout(self, payout_id: str, key: str) -> dict:
        p = self.payouts.get(payout_id)
        if p is None:
            return err("NOT_FOUND", f"{payout_id} not found")

        def run() -> dict:
            if not p["retryable"]:
                return err("PAYOUT_NOT_RETRYABLE", "payout is not retryable")
            if p["status"] == "paid":
                return err("PAYOUT_NOT_RETRYABLE", "payout already paid")
            self.settle_payout(payout_id)
            return ok({"payout_id": payout_id, "status": p["status"]})

        return self._idempotent(key, {"op": "retry", "payout_id": payout_id}, run)


class TrustedView:
    """Read-only facade for trusted code. It has NO method that returns untrusted free text (INV-6)."""

    def __init__(self, world: World) -> None:
        self._w = world

    def now(self) -> str:
        return self._w.clock.now()

    def order(self, order_id: str) -> Optional[dict]:
        o = self._w.orders.get(order_id)
        return dict(o) if o else None

    def charge(self, charge_id: str) -> Optional[dict]:
        c = self._w.charges.get(charge_id)
        return dict(c) if c else None

    def charges(self) -> list[dict]:
        return [dict(c) for c in self._w.charges.values()]

    def refund(self, refund_id: str) -> Optional[dict]:
        r = self._w.refunds.get(refund_id)
        return dict(r) if r else None

    def refunds(self) -> list[dict]:
        return [dict(r) for r in self._w.refunds.values()]

    def payout(self, payout_id: str) -> Optional[dict]:
        p = self._w.payouts.get(payout_id)
        return dict(p) if p else None

    def payouts(self) -> list[dict]:
        return [dict(p) for p in self._w.payouts.values()]

    def event(self, event_id: str) -> Optional[dict]:
        e = self._w.events.get(event_id)
        return self._safe_event(e) if e else None

    def events_for_charge(self, charge_id: str) -> list[dict]:
        return [self._safe_event(e) for e in self._w.events.values() if e["charge_id"] == charge_id]

    @staticmethod
    def _safe_event(e: dict) -> dict:
        return {k: e[k] for k in ("event_id", "type", "charge_id", "order_ref", "created_at",
                                  "delivered", "attempts")}

    def ledger_lines(self, ref: Optional[str] = None, order_id: Optional[str] = None) -> list[dict]:
        return self._w.ledger.lines_for(ref=ref, order_id=order_id)

    def revenue_credits(self, charge_id: str) -> list[dict]:
        return self._w.ledger.revenue_credits(charge_id)

    def ledger_balanced(self) -> bool:
        return self._w.ledger.balanced()

    def exists(self, obj_id: str) -> bool:
        pre = obj_id.split("_", 1)[0]
        table = {"ch": self._w.charges, "rf": self._w.refunds, "po": self._w.payouts,
                 "evt": self._w.events, "ord": self._w.orders}.get(pre)
        return table is not None and obj_id in table
