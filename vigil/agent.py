"""Agent loop (SPEC 7). The model proposes; the gate decides; the verifier closes.

Every step is appended to the decision chain. A write is executed only after the gate returned ALLOW and an
ACTION_INTENT for that exact call was committed. The model never closes an incident: only the verifier can
mark it RESOLVED, and only a verifier-confirmed condition can mark it SKIPPED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .canonical import CanonicalError, canonical_json, sha256_json, sha256_text
from .chain import Chain
from .executor import Executor
from .gate import Gate
from .incidents import IncidentStore
from .models import ModelClient, Proposal, Turn
from .observe import injection_suspected, summarize, untrusted_fields
from .tools import ID_RE, READ_TOOLS, WRITE_TOOLS, Tools
from .tracing import Tracer
from .verifier import Verifier
from sim.world import TrustedView

RATIONALE_MAX = 300
EXPECTED_EFFECT = {
    "issue_refund": "refund the charge at the provider",
    "replay_webhook": "re-deliver the event so the ledger credits the charge once",
    "retry_payout": "retry the payout at the provider",
    "escalate": "close the incident as ESCALATED with an evidence packet",
}


@dataclass
class RunResult:
    incident_id: str
    outcome: str
    reason_code: str
    steps: int
    tool_calls: int
    policy_denials: int
    tokens_in: int
    tokens_out: int
    trace_id: str
    first_seq: Optional[int]
    last_seq: Optional[int]

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class _Run:
    incident: dict
    trace_id: str
    turns: list = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    policy_denials: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    first_seq: Optional[int] = None
    last_seq: Optional[int] = None
    outcome: Optional[str] = None
    reason_code: str = ""

    @property
    def iid(self) -> str:
        return self.incident["incident_id"]


def _rationale(text: Any) -> str:
    return re.sub(r"\s+", " ", text).strip()[:RATIONALE_MAX] if isinstance(text, str) else ""


def _loggable(args: Any) -> dict:
    """Arguments exactly as proposed when they are canonical JSON; otherwise a hash of their repr."""
    if isinstance(args, dict):
        try:
            canonical_json(args)
            return args
        except CanonicalError:
            pass
    return {"_non_canonical_arguments_sha256": sha256_text(repr(args))}


class Agent:
    def __init__(self, *, tools: Tools, gate: Gate, verifier: Verifier, executor: Executor, chain: Chain,
                 store: IncidentStore, view: TrustedView, model: ModelClient,
                 tracer: Optional[Tracer] = None, max_steps: int = 8) -> None:
        self.tools, self.gate, self.verifier, self.executor = tools, gate, verifier, executor
        self.chain, self.store, self.view, self.model = chain, store, view, model
        self.tracer = tracer or Tracer()
        self.max_steps = max_steps

    # ------------------------------------------------------------------ public
    def run(self, incident: dict) -> RunResult:
        return self.tracer.run_incident(incident["incident_id"], lambda trace_id: self._run(incident, trace_id))

    # ------------------------------------------------------------------ loop
    def _run(self, incident: dict, trace_id: str) -> RunResult:
        run = _Run(incident=incident, trace_id=trace_id)
        self._append(run, "INCIDENT_OPENED", {"type": incident["type"], "related": incident["related"],
                                              "detector_rule": incident["detector_rule"]})
        self.store.set_status(run.iid, "INVESTIGATING")
        for step in range(1, self.max_steps + 1):
            run.steps = step
            self.tracer.call("AGENT", "agent_step", self._step, run, step)
            if run.outcome:
                break
        if not run.outcome:
            self._escalate(run, self.max_steps, "STEP_BUDGET_EXHAUSTED",
                           f"No verified outcome within {self.max_steps} steps.",
                           "The step budget was exhausted before the incident was verified.")
        return RunResult(run.iid, run.outcome or "", run.reason_code, run.steps, run.tool_calls, run.policy_denials,
                         run.tokens_in, run.tokens_out, run.trace_id, run.first_seq, run.last_seq)

    def _step(self, run: _Run, step: int) -> None:
        public = {k: run.incident[k] for k in ("incident_id", "type", "related")}
        proposal = self.model.propose(public, run.turns, step)
        run.tokens_in += proposal.tokens_in
        run.tokens_out += proposal.tokens_out
        if proposal.kind == "skip":
            self._skip(run, step, proposal)
        elif proposal.kind == "none":
            self._append(run, "DECISION", {"step": step, "decision": "INVESTIGATE", "tool": None, "args": {},
                                           "rationale": _rationale(proposal.rationale) or "no tool call returned"})
            run.turns.append(Turn(proposal, {"type": "error", "error_type": "NO_TOOL_CALL",
                                             "message": "Respond with exactly one tool call."}))
        elif proposal.tool in READ_TOOLS:
            self._read(run, step, proposal)
        else:
            self._write(run, step, proposal)

    # ------------------------------------------------------------------ reads
    def _read(self, run: _Run, step: int, p: Proposal) -> None:
        self._append(run, "DECISION", {"step": step, "decision": "INVESTIGATE", "tool": p.tool,
                                       "args": _loggable(p.args), "rationale": _rationale(p.rationale)})
        result = self.tracer.call("TOOL", p.tool, self.tools.call_read, p.tool, p.args)
        run.tool_calls += 1
        try:
            digest = sha256_json(result)
        except CanonicalError:
            digest = sha256_text(repr(result))
        self._append(run, "OBSERVATION", {
            "step": step, "tool": p.tool, "args": _loggable(p.args), "result_sha256": digest,
            "result_summary": summarize(p.tool, result),
            "untrusted_fields": untrusted_fields(result), "injection_suspected": injection_suspected(result)})
        run.turns.append(Turn(p, {"type": "tool_result", "result": result}))

    # ------------------------------------------------------------------ skip
    def _skip(self, run: _Run, step: int, p: Proposal) -> None:
        self._append(run, "DECISION", {"step": step, "decision": "SKIP", "tool": None, "args": {},
                                       "rationale": _rationale(p.rationale)})
        c = self.tracer.call("TOOL", "verifier", self.verifier.confirm_no_action, self.store.get(run.iid))
        self._append(run, "VERIFICATION", {"step": step, "ok": c["ok"], "checks": [
            {"check": "no_action_needed", "passed": c["ok"],
             "detail": f"condition_still_true={str(c['condition_still_true']).lower()}"}]})
        if c["ok"]:
            self._close(run, "SKIPPED", "NO_ACTION_NEEDED", "Verifier confirmed no action is needed.")
        else:
            run.turns.append(Turn(p, {"type": "skip_rejected", "message":
                                      "Verifier disagrees: the incident condition still holds. Act or escalate."}))

    # ------------------------------------------------------------------ writes
    def _write(self, run: _Run, step: int, p: Proposal) -> None:
        tool = p.tool
        args = self._normalize_escalate(run, p.args) if tool == "escalate" else p.args
        body = {"step": step, "decision": "ESCALATE" if tool == "escalate" else "ACT",
                "tool": tool if isinstance(tool, str) else None, "args": _loggable(args),
                "rationale": _rationale(p.rationale)}
        if tool == "escalate" and args != p.args:
            body["args_normalized"] = True
        self._append(run, "DECISION", body)

        verdict = self._gate(run, step, tool, args)
        if verdict["verdict"] == "DENY":
            run.turns.append(Turn(p, {"type": "gate", "verdict": "DENY", "code": verdict["code"],
                                      "details": verdict["details"]}))
            return
        if verdict["verdict"] == "ESCALATE":
            self._escalate(run, step, verdict["code"], f"Policy gate returned ESCALATE ({verdict['code']}) for {tool}.",
                           "The policy gate requires a human decision.")
            return
        if tool == "escalate":
            self._execute_escalation(run, step, args, verdict, args["reason_code"])
            return

        self.store.set_status(run.iid, "ACTING")
        self.executor.commit_intent(run.iid, step, tool, args, EXPECTED_EFFECT[tool], run.trace_id)
        resp = self.tracer.call("TOOL", tool, self.executor.execute, run.iid, step, tool, args, verdict, run.trace_id)
        run.tool_calls += self.executor.last_attempts
        self.store.set_status(run.iid, "VERIFYING")
        v = self.tracer.call("TOOL", "verifier", self.verifier.verify, self.store.get(run.iid))
        self._append(run, "VERIFICATION", {"step": step, "ok": v["ok"], "checks": v["checks"]})
        if v["ok"]:
            self._close(run, "RESOLVED", "VERIFIED_OK", "Independent verification passed.")
            return
        self.store.set_status(run.iid, "INVESTIGATING")
        run.turns.append(Turn(p, {"type": "action_result", "ok": resp["ok"], "error_type": resp.get("error_type"),
                                  "verification_ok": False,
                                  "failed_checks": [c["check"] for c in v["checks"] if not c["passed"]]}))

    def _gate(self, run: _Run, step: int, tool: Any, args: Any) -> dict:
        verdict = self.tracer.call("TOOL", "policy_gate", self.gate.evaluate, self.store.get(run.iid), tool, args)
        self._append(run, "GATE_VERDICT", {
            "step": step, "verdict": verdict["verdict"], "code": verdict["code"], "details": verdict["details"],
            "policy_version": verdict["policy_version"], "policy_sha256": verdict["policy_sha256"]})
        if verdict["verdict"] != "ALLOW":
            run.policy_denials += 1
        return verdict

    # ------------------------------------------------------------------ escalation
    def _normalize_escalate(self, run: _Run, args: Any) -> Any:
        """Keep only evidence refs that exist; fall back to the incident's related ids."""
        if isinstance(args, dict) and isinstance(args.get("evidence_refs"), list):
            refs = [r for r in args["evidence_refs"]
                    if isinstance(r, str) and ID_RE.match(r) and self.view.exists(r)]
            return {**args, "evidence_refs": refs or list(run.incident["related"])}
        return args

    def _escalate(self, run: _Run, step: int, reason_code: str, summary: str, rationale: str) -> None:
        """Code-initiated escalation (gate ESCALATE verdict or exhausted budget), through the same gate and intent path."""
        args = {"reason_code": reason_code, "summary": summary[:500], "evidence_refs": list(run.incident["related"])}
        self._append(run, "DECISION", {"step": step, "decision": "ESCALATE", "tool": "escalate",
                                       "args": args, "rationale": rationale})
        verdict = self._gate(run, step, "escalate", args)
        if verdict["verdict"] != "ALLOW":
            raise RuntimeError(f"gate refused a code-initiated escalation: {verdict['code']}")
        self._execute_escalation(run, step, args, verdict, reason_code)

    def _execute_escalation(self, run: _Run, step: int, args: dict, verdict: dict, reason_code: str) -> None:
        self.executor.commit_intent(run.iid, step, "escalate", args, EXPECTED_EFFECT["escalate"], run.trace_id)
        resp = self.tracer.call("TOOL", "escalate", self.executor.execute, run.iid, step, "escalate", args,
                                verdict, run.trace_id)
        run.tool_calls += self.executor.last_attempts
        if not resp["ok"]:
            raise RuntimeError(f"escalation failed: {resp.get('error_type')}")
        v = self.tracer.call("TOOL", "verifier", self.verifier.verify_escalation, self.store.get(run.iid))
        self._append(run, "VERIFICATION", {"step": step, "ok": v["ok"], "checks": v["checks"]})
        self._close(run, "ESCALATED", reason_code, args["summary"], already_terminal=True)

    # ------------------------------------------------------------------ helpers
    def _close(self, run: _Run, outcome: str, reason_code: str, summary: str, already_terminal: bool = False) -> None:
        self._append(run, "OUTCOME", {"outcome": outcome, "reason_code": reason_code, "summary": summary})
        if not already_terminal:
            self.store.set_status(run.iid, outcome)
        run.outcome, run.reason_code = outcome, reason_code

    def _append(self, run: _Run, kind: str, body: dict) -> dict:
        e = self.chain.append(run.iid, kind, body, run.trace_id)
        run.last_seq = e["seq"]
        if run.first_seq is None:
            run.first_seq = e["seq"]
        return e
