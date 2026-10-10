"""Scenario builders shared by tests. All data is SIMULATED."""
from vigil.chain import Chain
from vigil.clock import VirtualClock
from vigil.detector import Detector
from vigil.executor import Executor
from vigil.gate import Gate
from vigil.incidents import IncidentStore
from vigil.policy import load_policy
from vigil.tools import Tools
from vigil.verifier import Verifier
from sim import World

AMOUNT = 2_500_000


class Env:
    def __init__(self, tmp_path, faults=None):
        self.clock = VirtualClock("2026-10-10T08:00:00Z")
        self.world = World(self.clock, faults)
        self.view = self.world.trusted()
        self.policy = load_policy("policy.yaml")
        self.store = IncidentStore(self.clock)
        self.chain = Chain(str(tmp_path / "t.db"), self.clock)
        self.tools = Tools(self.world, self.store)
        self.detector = Detector(self.view, self.policy, self.store)
        self.gate = Gate(self.policy, self.view, self.chain, self.store)
        self.verifier = Verifier(self.view, self.policy, self.store)
        self.executor = Executor(self.tools, self.chain)

    def d1(self, amount=AMOUNT, memo=None):
        """Duplicate charge: two succeeded charges, same order, 40 s apart, both credited."""
        o = self.world.create_order("cust_01", amount)
        a = self.world.create_charge(o, amount)
        self.clock.advance(40)
        b = self.world.create_charge(o, amount, memo=memo)
        return o, a, b

    def open_incident(self):
        opened = self.detector.run()
        assert opened, "detector opened nothing"
        return opened[0]


def refund_args(incident_id, charge_id, n=1, evidence=None, **extra):
    a = {"charge_id": charge_id, "idempotency_key": f"{incident_id}:refund:{n}",
         "evidence_refs": evidence if evidence is not None else [charge_id]}
    a.update(extra)
    return a
