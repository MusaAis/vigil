"""Typed tools (SPEC 5). Strict schemas, uniform error shape, untrusted text only under 'untrusted'.
Write tools are NOT callable by the agent directly: only vigil.executor.Executor calls Tools.write()."""
from __future__ import annotations

import re
from typing import Any

from .canonical import MAX_INT
from .incidents import IncidentStore
from sim.world import World, err, ok

ID_RE = re.compile(r"^(cust|ord|ch|rf|po|evt|inc)_[0-9a-z]+$")
REASON_RE = re.compile(r"^[A-Z_]{3,40}$")

READ_TOOLS = ("get_incident", "get_ledger_entries", "get_provider_charge", "list_provider_charges",
              "get_webhook_events", "get_provider_status")
WRITE_TOOLS = ("issue_refund", "replay_webhook", "retry_payout", "escalate")

# name -> (required, optional, exactly-one-of groups)
SCHEMAS: dict[str, tuple] = {
    "get_incident": ({"incident_id": "id"}, {}, []),
    "get_ledger_entries": ({}, {"ref": "id", "order_id": "id"}, [("ref", "order_id")]),
    "get_provider_charge": ({"charge_id": "id"}, {}, []),
    "list_provider_charges": ({}, {"order_ref": "id", "customer_id": "id"}, [("order_ref", "customer_id")]),
    "get_webhook_events": ({}, {"charge_id": "id", "order_ref": "id"}, [("charge_id", "order_ref")]),
    "get_provider_status": ({}, {"refund_id": "id", "payout_id": "id"}, [("refund_id", "payout_id")]),
    "issue_refund": ({"charge_id": "id", "idempotency_key": "str", "evidence_refs": "ids"},
                     {"amount_minor": "pos_int"}, []),
    "replay_webhook": ({"event_id": "id", "idempotency_key": "str", "evidence_refs": "ids"}, {}, []),
    "retry_payout": ({"payout_id": "id", "idempotency_key": "str", "evidence_refs": "ids"}, {}, []),
    "escalate": ({"reason_code": "reason", "summary": "summary", "evidence_refs": "ids"}, {}, []),
}


def _bad(msg: str) -> dict:
    return err("INVALID_ARGUMENT", msg, False)


def _valid(kind: str, v: Any) -> bool:
    if kind == "id":
        return isinstance(v, str) and bool(ID_RE.match(v))
    if kind == "str":
        return isinstance(v, str) and 0 < len(v) <= 80
    if kind == "pos_int":
        return isinstance(v, int) and not isinstance(v, bool) and 0 < v <= MAX_INT
    if kind == "ids":
        return isinstance(v, list) and len(v) <= 10 and all(isinstance(x, str) and ID_RE.match(x) for x in v)
    if kind == "reason":
        return isinstance(v, str) and bool(REASON_RE.match(v))
    if kind == "summary":
        return isinstance(v, str) and 0 < len(v) <= 500
    return False


def validate(tool: str, args: Any) -> dict | None:
    """Returns an INVALID_ARGUMENT error dict, or None if valid."""
    if tool not in SCHEMAS:
        return err("UNKNOWN_TOOL", f"unknown tool {tool!r}", False)
    if not isinstance(args, dict):
        return _bad("arguments must be an object")
    req, opt, one_of = SCHEMAS[tool]
    for k in args:
        if k not in req and k not in opt:
            return _bad(f"unexpected argument {k!r}")
    for k, kind in req.items():
        if k not in args:
            return _bad(f"missing required argument {k!r}")
    for k, v in args.items():
        kind = req.get(k) or opt.get(k)
        if not _valid(kind, v):
            return _bad(f"argument {k!r} has an invalid value")
    for group in one_of:
        if sum(1 for g in group if g in args) != 1:
            return _bad(f"exactly one of {list(group)} is required")
    return None


class Tools:
    def __init__(self, world: World, store: IncidentStore) -> None:
        self.world, self.store = world, store

    # ------------------------------------------------------------ read tools (agent-callable)
    def call_read(self, tool: str, args: dict) -> dict:
        if tool not in READ_TOOLS:
            return err("UNKNOWN_TOOL", f"{tool!r} is not a read tool", False)
        bad = validate(tool, args)
        if bad:
            return bad
        return self.world.with_faults(tool, lambda: getattr(self, "_" + tool)(**args))

    def _get_incident(self, incident_id: str) -> dict:
        inc = self.store.get(incident_id)
        if inc is None:
            return err("NOT_FOUND", f"{incident_id} not found")
        return ok({k: inc[k] for k in ("incident_id", "type", "related", "status")})

    def _get_ledger_entries(self, ref: str | None = None, order_id: str | None = None) -> dict:
        lines = self.world.ledger.lines_for(ref=ref, order_id=order_id)
        return ok({"entries": lines, "balanced": self.world.ledger.balanced()})

    def _charge_item(self, cid: str) -> dict:
        item = dict(self.world.charges[cid])
        memo = self.world.untrusted_for("charge", cid)
        if memo is not None:
            item["untrusted"] = {"customer_memo": memo}
        return item

    def _get_provider_charge(self, charge_id: str) -> dict:
        if charge_id not in self.world.charges:
            return err("NOT_FOUND", f"{charge_id} not found")
        return ok({"charge": self._charge_item(charge_id)})

    def _list_provider_charges(self, order_ref: str | None = None, customer_id: str | None = None) -> dict:
        items = [self._charge_item(c["charge_id"]) for c in self.world.charges.values()
                 if (order_ref and c["order_ref"] == order_ref) or (customer_id and c["customer_id"] == customer_id)]
        return ok({"charges": items})

    def _get_webhook_events(self, charge_id: str | None = None, order_ref: str | None = None) -> dict:
        out = []
        for e in self.world.events.values():
            if (charge_id and e["charge_id"] == charge_id) or (order_ref and e["order_ref"] == order_ref):
                item = {k: e[k] for k in ("event_id", "type", "charge_id", "order_ref", "created_at",
                                          "delivered", "attempts")}
                note = self.world.untrusted_for("event", e["event_id"])
                if note is not None:
                    item["untrusted"] = {"note": note}
                out.append(item)
        return ok({"events": out})

    def _get_provider_status(self, refund_id: str | None = None, payout_id: str | None = None) -> dict:
        from .clock import parse_ts
        now = parse_ts(self.world.clock.now())
        if refund_id:
            r = self.world.refunds.get(refund_id)
            if r is None:
                return err("NOT_FOUND", f"{refund_id} not found")
            return ok({"refund_id": refund_id, "status": r["status"], "charge_id": r["charge_id"],
                       "amount_minor": r["amount_minor"]})
        p = self.world.payouts.get(payout_id)
        if p is None:
            return err("NOT_FOUND", f"{payout_id} not found")
        age = int((now - parse_ts(p["created_at"])).total_seconds())
        return ok({"payout_id": payout_id, "status": p["status"], "age_seconds": age,
                   "retryable": p["retryable"], "group": p["group"]})

    # ------------------------------------------------------------ write tools (executor only)
    def write(self, tool: str, args: dict, incident_id: str) -> dict:
        if tool not in WRITE_TOOLS:
            return err("UNKNOWN_TOOL", f"{tool!r} is not a write tool", False)
        bad = validate(tool, args)
        if bad:
            return bad
        if tool == "escalate":
            inc = self.store.get(incident_id)
            if inc is None:
                return err("NOT_FOUND", f"{incident_id} not found")
            if self.store.is_terminal(incident_id):
                return err("INCIDENT_CLOSED", f"{incident_id} is already {inc['status']}", False)
            pkt = self.store.escalate(incident_id, args["reason_code"], args["summary"], args["evidence_refs"])
            return ok({"escalated": True, "incident_id": incident_id, "evidence_refs": pkt["evidence_refs"]})
        key = args["idempotency_key"]
        if tool == "issue_refund":
            fn = lambda: self.world.create_refund(args["charge_id"], args.get("amount_minor"), key)
        elif tool == "replay_webhook":
            fn = lambda: self.world.replay_webhook(args["event_id"], key)
        else:
            fn = lambda: self.world.retry_payout(args["payout_id"], key)
        return self.world.with_faults(tool, fn)
