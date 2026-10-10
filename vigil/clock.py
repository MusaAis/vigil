"""Injectable clocks. Code must read time only through a Clock (SPEC 2.2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, _FMT).replace(tzinfo=timezone.utc)


def format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_FMT)


class Clock:
    def now(self) -> str:  # UTC ISO-8601, second precision, trailing Z
        raise NotImplementedError


class SystemClock(Clock):
    def now(self) -> str:
        return format_ts(datetime.now(timezone.utc))


class VirtualClock(Clock):
    """Deterministic clock for eval/tests. Time only moves when advance() is called."""

    def __init__(self, start: str = "2026-10-10T08:00:00Z") -> None:
        self._t = parse_ts(start)

    def now(self) -> str:
        return format_ts(self._t)

    def advance(self, seconds: int) -> None:
        self._t += timedelta(seconds=int(seconds))
