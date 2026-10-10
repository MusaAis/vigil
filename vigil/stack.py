"""Production wiring of the agent stack (clock, world, store, tools, gate, verifier, executor, detector, agent).

One decision chain and one clock can be shared by several stacks (the eval runner builds a fresh simulated world per
scenario but appends every scenario to the same chain). Incident ids stay unique through `incident_start`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from sim import World
from sim.world import TrustedView

from .agent import Agent
from .chain import Chain
from .clock import Clock
from .detector import Detector
from .executor import Executor
from .gate import Gate
from .incidents import IncidentStore
from .models import ModelClient
from .policy import Policy
from .tools import Tools
from .tracing import Tracer
from .verifier import Verifier


@dataclass
class Stack:
    policy: Policy
    world: World
    view: TrustedView
    store: IncidentStore
    tools: Tools
    gate: Gate
    verifier: Verifier
    executor: Executor
    detector: Detector
    agent: Agent


def build_stack(*, chain: Chain, clock: Clock, policy: Policy, model: ModelClient,
                faults: Optional[list] = None, tracer: Optional[Tracer] = None, max_steps: int = 8,
                incident_start: int = 0, sleep: Optional[Callable[[float], None]] = None) -> Stack:
    world = World(clock, faults)
    view = world.trusted()
    store = IncidentStore(clock, incident_start)
    tools = Tools(world, store)
    gate = Gate(policy, view, chain, store)
    verifier = Verifier(view, policy, store)
    executor = Executor(tools, chain, sleep)
    detector = Detector(view, policy, store)
    agent = Agent(tools=tools, gate=gate, verifier=verifier, executor=executor, chain=chain, store=store,
                  view=view, model=model, tracer=tracer, max_steps=max_steps)
    return Stack(policy, world, view, store, tools, gate, verifier, executor, detector, agent)
