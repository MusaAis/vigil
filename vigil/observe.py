"""Helpers that turn a tool result into the short, structured summary stored in the decision chain.

Summaries are built from named structured fields only. Untrusted text is never copied into them; the
summary records which untrusted fields were present and whether their content looks like an injection.
"""
from __future__ import annotations

import re
from typing import Any

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+|any\s+|the\s+|previous\s+)*(rules|instructions|policy|policies)", re.I),
    re.compile(r"disregard", re.I),
    re.compile(r"refund\s+(everything|all)", re.I),
    re.compile(r"^\s*system\s*:", re.I | re.M),
    re.compile(r"(approve|authori[sz]e)\s+(the\s+)?(refund|payment|payout)", re.I),
    re.compile(r"you\s+(must|are now|should)\s", re.I),
    re.compile(r"override", re.I),
]


def untrusted_blocks(result: Any) -> list[dict]:
    """Every 'untrusted' dict found anywhere in a tool result."""
    found: list[dict] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            u = x.get("untrusted")
            if isinstance(u, dict):
                found.append(u)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(result)
    return found


def untrusted_fields(result: Any) -> list[str]:
    return sorted({k for blk in untrusted_blocks(result) for k in blk})


def injection_suspected(result: Any) -> bool:
    """Flagging only. The flag never feeds a decision; the gate and verifier cannot see untrusted text."""
    for blk in untrusted_blocks(result):
        for text in blk.values():
            if isinstance(text, str) and any(p.search(text) for p in INJECTION_PATTERNS):
                return True
    return False


def summarize(tool: str, result: dict) -> str:
    if not result.get("ok"):
        return f"{tool} error {result.get('error_type')} retryable={str(bool(result.get('retryable'))).lower()}"
    d = result["data"]
    if tool == "get_incident":
        return f"incident {d['incident_id']} {d['type']} related {','.join(d['related'])} status {d['status']}"
    if tool == "get_provider_charge":
        return _charge(d["charge"])
    if tool == "list_provider_charges":
        return f"{len(d['charges'])} charges: " + "; ".join(_charge(c) for c in d["charges"])
    if tool == "get_ledger_entries":
        return f"{len(d['entries'])} ledger lines, balanced={str(bool(d['balanced'])).lower()}"
    if tool == "get_webhook_events":
        return f"{len(d['events'])} events: " + "; ".join(
            f"{e['event_id']} {e['type']} delivered={str(bool(e['delivered'])).lower()} attempts={e['attempts']}"
            for e in d["events"])
    if tool == "get_provider_status":
        if "refund_id" in d:
            return f"refund {d['refund_id']} {d['status']} amount {d['amount_minor']}"
        return (f"payout {d['payout_id']} {d['status']} age {d['age_seconds']}s "
                f"retryable={str(bool(d['retryable'])).lower()}")
    return f"{tool} ok"


def _charge(c: dict) -> str:
    return (f"charge {c['charge_id']} {c['status']} {c['amount_minor']} {c['currency']} "
            f"order {c['order_ref']} customer {c['customer_id']} at {c['created_at']}")
