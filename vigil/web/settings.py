"""Web settings read from the environment (names in .env.example). Paths default to the repository root."""
from __future__ import annotations

import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_REPO_URL = "https://github.com/MusaAis/vigil"
VERIFY_INTERVAL_S = 300  # SPEC TS-5: the chain is fully verified at startup and at least every 5 minutes


@dataclass(frozen=True)
class WebSettings:
    root: str = ROOT
    db_path: str = os.path.join(ROOT, "data", "vigil.db")
    receipts_dir: str = os.path.join(ROOT, "receipts", "web")
    anchors_path: str = os.path.join(ROOT, "anchors.txt")
    results_dir: str = os.path.join(ROOT, "eval", "results")
    evidence_path: str = os.path.join(ROOT, "docs", "evidence.json")
    policy_path: str = os.path.join(ROOT, "policy.yaml")
    tests_dir: str = os.path.join(ROOT, "tests")
    ci_workflow_dir: str = os.path.join(ROOT, ".github", "workflows")
    repo_url: str = DEFAULT_REPO_URL
    verify_interval_s: int = VERIFY_INTERVAL_S

    @classmethod
    def from_env(cls, env: dict | None = None) -> "WebSettings":
        e = os.environ if env is None else env
        db = e.get("VIGIL_DB_PATH") or os.path.join(ROOT, "data", "vigil.db")
        if not os.path.isabs(db):
            db = os.path.join(ROOT, db)
        rec = e.get("VIGIL_RECEIPTS_DIR") or os.path.join(ROOT, "receipts", "web")
        if not os.path.isabs(rec):
            rec = os.path.join(ROOT, rec)
        return cls(db_path=db, receipts_dir=rec, repo_url=(e.get("VIGIL_REPO_URL") or DEFAULT_REPO_URL).rstrip("/"))
