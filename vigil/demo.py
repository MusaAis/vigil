"""Seeds the demo chain: three scenarios run by the deterministic offline model on a virtual clock (SIMULATED data).

Used by the web app (first start) and by `make demo`. Same code, same scenarios, same hashes every time.
"""
from __future__ import annotations

import os
from typing import Optional

from eval.run import run_eval
from vigil.config import Config

DEMO_LABEL = "demo"
DEMO_SCENARIOS = ("D1", "D3", "D2")  # resolved duplicate, skipped trap, escalated cap case


def seed_demo(db_path: str, receipts_dir: str, root: Optional[str] = None) -> dict:
    """Run the demo scenarios into a fresh chain at db_path and write receipts. Returns the eval result dict."""
    root = root or os.getcwd()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    return run_eval(label=DEMO_LABEL, mode="offline", only=list(DEMO_SCENARIOS), config=Config(),
                    receipts_dir=receipts_dir, db_path=db_path,
                    scenario_dir=os.path.join(root, "eval", "scenarios"),
                    policy_path=os.path.join(root, "policy.yaml"))
