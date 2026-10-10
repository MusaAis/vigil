"""Load policy.yaml (SPEC 6.1). Integers only; policy_sha256 = sha256 of canonical JSON of the parsed file."""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from .canonical import sha256_json


@dataclass(frozen=True)
class Policy:
    raw: dict
    sha256: str
    version: int
    currency: str
    max_refund_per_incident_minor: int
    max_refund_per_day_minor: int
    max_write_actions_per_incident: int
    allowed_actions: tuple
    duplicate_window_hours: int
    credit_grace_seconds: int
    payout_sla_seconds: int


def from_dict(raw: dict) -> Policy:
    lim = raw["limits"]
    return Policy(
        raw=raw, sha256=sha256_json(raw), version=raw["version"], currency=raw["currency"],
        max_refund_per_incident_minor=lim["max_refund_per_incident_minor"],
        max_refund_per_day_minor=lim["max_refund_per_day_minor"],
        max_write_actions_per_incident=lim["max_write_actions_per_incident"],
        allowed_actions=tuple(raw["allowed_actions"]),
        duplicate_window_hours=raw["duplicate_charge"]["window_hours"],
        credit_grace_seconds=raw["credit_grace_seconds"],
        payout_sla_seconds=raw["payout_sla_seconds"])


def load_policy(path: str = "policy.yaml") -> Policy:
    with open(path, encoding="utf-8") as f:
        return from_dict(yaml.safe_load(f))
