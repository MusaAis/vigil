"""SIMULATED merchant double-entry ledger (SPEC 3.2)."""
from __future__ import annotations

from vigil.clock import Clock

ACCOUNTS = ("provider_clearing", "revenue", "refunds", "payouts_payable")


class Ledger:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.lines: list[dict] = []
        self._n = 0

    def post(self, debit_account: str, credit_account: str, amount_minor: int, ref: str,
             order_id: str | None, idempotency_key: str) -> bool:
        """Post one balanced transaction (2 lines). Returns False if the key was already posted."""
        assert debit_account in ACCOUNTS and credit_account in ACCOUNTS
        assert isinstance(amount_minor, int) and not isinstance(amount_minor, bool) and amount_minor > 0
        if any(l["idempotency_key"] == idempotency_key for l in self.lines):
            return False
        self._n += 1
        txn = f"tx_{self._n:04d}"
        now = self.clock.now()
        base = {"txn": txn, "ref": ref, "order_id": order_id,
                "idempotency_key": idempotency_key, "created_at": now}
        self.lines.append({**base, "account": debit_account, "debit_minor": amount_minor, "credit_minor": 0})
        self.lines.append({**base, "account": credit_account, "debit_minor": 0, "credit_minor": amount_minor})
        return True

    def lines_for(self, ref: str | None = None, order_id: str | None = None) -> list[dict]:
        return [dict(l) for l in self.lines
                if (ref is not None and l["ref"] == ref) or (order_id is not None and l["order_id"] == order_id)]

    def revenue_credits(self, charge_id: str) -> list[dict]:
        return [dict(l) for l in self.lines
                if l["account"] == "revenue" and l["credit_minor"] > 0 and l["ref"] == charge_id]

    def balanced(self) -> bool:
        return sum(l["debit_minor"] for l in self.lines) == sum(l["credit_minor"] for l in self.lines)
