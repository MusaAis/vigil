"""The only path to a write tool (SPEC 7.2/7.3, INV-5). Commit-then-act: ACTION_INTENT must be committed
to the chain before the tool is called, and the gate verdict must be ALLOW."""
from __future__ import annotations

from typing import Callable, Optional

from .canonical import sha256_json
from .chain import Chain
from .tools import Tools

MAX_ATTEMPTS = 3


class NotAllowed(RuntimeError):
    pass


class IntentMissing(RuntimeError):
    pass


class Executor:
    def __init__(self, tools: Tools, chain: Chain, sleep: Optional[Callable[[float], None]] = None) -> None:
        self.tools, self.chain = tools, chain
        self.sleep = sleep or (lambda s: None)

    def commit_intent(self, incident_id: str, step: int, tool: str, args: dict,
                      expected_effect: str, trace_id: str) -> dict:
        body = {"step": step, "tool": tool, "args": args, "args_sha256": sha256_json(args),
                "idempotency_key": args.get("idempotency_key"), "expected_effect": expected_effect}
        return self.chain.append(incident_id, "ACTION_INTENT", body, trace_id)

    def execute(self, incident_id: str, step: int, tool: str, args: dict, verdict: dict, trace_id: str) -> dict:
        """Run one write tool with bounded retries on retryable errors, same idempotency key each time.
        Appends one ACTION_RESULT per attempt. Raises if the verdict is not ALLOW or no intent is committed."""
        if verdict.get("verdict") != "ALLOW":
            raise NotAllowed(f"gate verdict {verdict.get('verdict')}/{verdict.get('code')}")
        if not self.chain.has_committed_intent(incident_id, tool, sha256_json(args)):
            raise IntentMissing("no committed ACTION_INTENT for this exact call (INV-5)")
        resp: dict = {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = self.tools.write(tool, args, incident_id)
            self.chain.append(incident_id, "ACTION_RESULT",
                              {"step": step, "tool": tool, "attempt": attempt, "ok": resp["ok"],
                               "response_sha256": sha256_json(resp),
                               "error_type": resp.get("error_type")}, trace_id)
            if resp["ok"] or not resp.get("retryable"):
                break
            self.sleep(0.2 * (2 ** (attempt - 1)))
        return resp
