"""Tracing adapter. Uses neatlogs when NEATLOGS_API_KEY is set and the SDK is importable; otherwise runs
untraced with deterministic ids 'offline-<n>' (SPEC 10: never fabricate a neatlogs trace id).

Only SDK calls shown in the neatlogs setup guide are used: init, span(kind=..., name=.../tool_name=...),
inject_trace_context, flush, shutdown.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from .config import load_env_file


class Tracer:
    def __init__(self, neatlogs_module: Any = None) -> None:
        self._nl = neatlogs_module
        self._n = 0

    @property
    def enabled(self) -> bool:
        return self._nl is not None

    @classmethod
    def from_env(cls, workflow_name: str = "vigil", env: Optional[dict] = None) -> "Tracer":
        if env is None:
            load_env_file()
        e = os.environ if env is None else env
        key = e.get("NEATLOGS_API_KEY")
        if not key:
            return cls()
        try:
            import neatlogs  # type: ignore
        except ImportError:
            return cls()
        neatlogs.init(api_key=key, workflow_name=workflow_name)
        return cls(neatlogs)

    def _current_trace_id(self) -> Optional[str]:
        headers: dict = {}
        if self._nl.inject_trace_context(headers):
            parts = headers.get("traceparent", "").split("-")
            if len(parts) == 4 and len(parts[1]) == 32:
                return parts[1]
        return None

    def run_incident(self, incident_id: str, fn: Callable[[str], Any]) -> Any:
        """Run fn(trace_id) inside an 'incident' workflow span."""
        self._n += 1
        if self._nl is None:
            return fn(f"offline-{self._n}")

        def workflow() -> Any:
            return fn(self._current_trace_id() or f"offline-{self._n}")

        return self._nl.span(kind="WORKFLOW", name="incident")(workflow)()

    def call(self, kind: str, name: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run fn(*args, **kwargs) inside a span of the given kind (WORKFLOW, AGENT or TOOL)."""
        if self._nl is None:
            return fn(*args, **kwargs)
        opts = {"kind": kind, "tool_name": name} if kind == "TOOL" else {"kind": kind, "name": name}
        return self._nl.span(**opts)(fn)(*args, **kwargs)

    def close(self) -> None:
        if self._nl is not None:
            self._nl.flush()
            self._nl.shutdown()
