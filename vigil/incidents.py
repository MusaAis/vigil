"""Incident store (SPEC 4.2). Terminal states are immutable."""
from __future__ import annotations

from typing import Optional

TERMINAL = ("RESOLVED", "ESCALATED", "SKIPPED")
STATES = ("OPEN", "INVESTIGATING", "ACTING", "VERIFYING") + TERMINAL


class IncidentStore:
    def __init__(self, clock) -> None:
        self.clock = clock
        self._items: dict[str, dict] = {}
        self._keys: dict[tuple, str] = {}
        self._n = 0
        self.escalations: dict[str, dict] = {}

    def open(self, itype: str, related: list[str], rule: str) -> Optional[dict]:
        key = (itype, tuple(sorted(related)))
        if key in self._keys:  # dedup: one incident per (type, related ids), ever
            return None
        self._n += 1
        iid = f"inc_{self._n:04d}"
        inc = {"incident_id": iid, "type": itype, "related": sorted(related), "status": "OPEN",
               "detector_rule": rule, "opened_at": self.clock.now(), "outcome": None}
        self._items[iid] = inc
        self._keys[key] = iid
        return dict(inc)

    def get(self, incident_id: str) -> Optional[dict]:
        i = self._items.get(incident_id)
        return dict(i) if i else None

    def all(self) -> list[dict]:
        return [dict(i) for i in self._items.values()]

    def is_terminal(self, incident_id: str) -> bool:
        return self._items[incident_id]["status"] in TERMINAL

    def set_status(self, incident_id: str, status: str) -> None:
        if status not in STATES:
            raise ValueError(f"bad status {status}")
        inc = self._items[incident_id]
        if inc["status"] in TERMINAL:
            raise RuntimeError(f"{incident_id} is {inc['status']} (terminal, immutable)")
        inc["status"] = status
        if status in TERMINAL:
            inc["outcome"] = status

    def escalate(self, incident_id: str, reason_code: str, summary: str, evidence_refs: list[str]) -> dict:
        packet = {"incident_id": incident_id, "reason_code": reason_code, "summary": summary,
                  "evidence_refs": list(evidence_refs)}
        self.escalations[incident_id] = packet
        self.set_status(incident_id, "ESCALATED")
        return packet
