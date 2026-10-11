"""Scenario loader (SPEC 12.1). Scenarios declare setup, a timed script, faults and ground truth; no randomness at run time."""
from __future__ import annotations

import glob
import os
from typing import Optional

import yaml

from vigil.clock import VirtualClock, parse_ts

SCENARIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios")
REQUIRED = ("id", "type", "setup", "script", "ground_truth")
# State changes a scenario may apply to the simulated provider while the agent is running (see install_mid_run).
MID_RUN_OPS = ("settle_payout", "fail_payout", "inject_ledger_credit")


class ScenarioError(ValueError):
    pass


def load_scenario(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise ScenarioError(f"{path}: missing keys {missing}")
    spec.setdefault("faults", [])
    spec.setdefault("untrusted", {})
    spec.setdefault("llm_fixture", None)
    spec.setdefault("mid_run", [])
    for step in spec["mid_run"]:
        if step.get("op") not in MID_RUN_OPS or int(step.get("after_read_calls", 0)) < 1:
            raise ScenarioError(f"{path}: bad mid_run step {step}; ops {MID_RUN_OPS}, after_read_calls >= 1")
    return spec


def load_all(directory: str = SCENARIO_DIR, only: Optional[list] = None) -> list:
    specs = [load_scenario(p) for p in sorted(glob.glob(os.path.join(directory, "*.yaml")))]
    if only:
        wanted = set(only)
        unknown = wanted - {s["id"] for s in specs}
        if unknown:
            raise ScenarioError(f"unknown scenario ids: {sorted(unknown)}")
        specs = [s for s in specs if s["id"] in wanted]
    return specs


def world_faults(spec: dict) -> list:
    """Scenario fault declarations (target/name) -> the simulator's fault plan (tool/...)."""
    out = []
    for f in spec["faults"]:
        if f.get("target") != "tool":
            raise ScenarioError(f"{spec['id']}: only tool faults are supported, got {f}")
        item = {"tool": f["name"], "kind": f["kind"]}
        if "on_call" in f:
            item["on_call"] = f["on_call"]
        if f.get("apply_before_timeout"):
            item["apply_before_timeout"] = True
        out.append(item)
    return out


def _expect(spec: dict, what: str, got: str, declared: str) -> None:
    if got != declared:
        raise ScenarioError(f"{spec['id']}: {what} was generated as {got} but the scenario declares {declared}")


def _apply_state_op(spec: dict, step: dict, world) -> None:
    """Provider-side state changes shared by the timed script and the mid-run hook."""
    op = step["op"]
    if op == "fail_payout":
        world.fail_payout(step["id"])
    elif op == "settle_payout":
        world.settle_payout(step["id"])
    elif op == "inject_ledger_credit":
        world.inject_ledger_credit(step["charge"])
    else:
        raise ScenarioError(f"{spec['id']}: unknown script op {op!r}")


def install_mid_run(spec: dict, tools, world) -> None:
    """Apply each `mid_run` step once, right after the agent's Nth read-tool call returns.

    The Nth call itself still sees the earlier state, so the change happens between two agent steps. The trigger counts
    read calls only, so it is deterministic for a given sequence of model proposals (live, replay and offline alike).
    """
    plan = spec.get("mid_run") or []
    if not plan:
        return
    inner = tools.call_read
    state = {"reads": 0, "done": set()}

    def call_read(tool: str, args: dict) -> dict:
        result = inner(tool, args)
        state["reads"] += 1
        for i, step in enumerate(plan):
            if i not in state["done"] and state["reads"] >= int(step["after_read_calls"]):
                state["done"].add(i)
                _apply_state_op(spec, step, world)
        return result

    tools.call_read = call_read


def apply_script(spec: dict, world, clock: VirtualClock) -> int:
    """Create the setup and play the script on a fresh world. Returns the virtual start time (epoch seconds)."""
    start = int(parse_ts(clock.now()).timestamp())

    def advance_to(t: int) -> None:
        delta = start + int(t) - int(parse_ts(clock.now()).timestamp())
        if delta < 0:
            raise ScenarioError(f"{spec['id']}: script times must not go backwards (t={t})")
        clock.advance(delta)

    for o in spec["setup"].get("orders", []):
        _expect(spec, "order id", world.create_order(o["customer_id"], o["amount_minor"]), o["id"])
    for step in spec["script"]:
        advance_to(step["t"])
        op = step["op"]
        if op == "charge":
            cid = world.create_charge(step["order_ref"], step["amount_minor"], status=step.get("status", "succeeded"),
                                      webhook=step.get("webhook", "deliver"),
                                      delay_seconds=step.get("delay_seconds", 0))
            _expect(spec, "charge id", cid, step["id"])
        elif op == "payout":
            pid = world.create_payout(step["amount_minor"], status=step.get("status", "pending"),
                                      retryable=step.get("retryable", True))
            _expect(spec, "payout id", pid, step["id"])
        else:
            _apply_state_op(spec, step, world)
    for obj_id, fields in spec["untrusted"].items():
        kind = {"ch": "charge", "evt": "event"}.get(obj_id.split("_", 1)[0])
        if kind is None or len(fields) != 1:
            raise ScenarioError(f"{spec['id']}: bad untrusted entry {obj_id}")
        world.set_untrusted(kind, obj_id, next(iter(fields.values())))
    last = max([int(s["t"]) for s in spec["script"]] or [0])
    advance_to(int(spec.get("detect_at", last)))
    world.process_due_events()
    return start
