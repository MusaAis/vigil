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


# ---------------------------------------------------------------------------------------------------------------
# `make demo` (SPEC TS-10): seed, print the decision log, write receipts, verify chain and receipts, print the head.
# ---------------------------------------------------------------------------------------------------------------
DEFAULT_DEMO_DB = os.path.join("data", "demo.db")
DEFAULT_DEMO_RECEIPTS = os.path.join("receipts", "demo")


def reset_demo_files(db_path: str, receipts_dir: str) -> None:
    """Remove the previous demo chain and receipts so every run starts from nothing (the chain is append-only)."""
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            os.remove(db_path + suffix)
    if os.path.isdir(receipts_dir):
        for name in os.listdir(receipts_dir):
            if name.endswith(".json"):
                os.remove(os.path.join(receipts_dir, name))


def check_demo(db_path: str, receipts_dir: str, anchors_path: Optional[str] = None) -> dict:
    """Verify the demo chain from genesis and every receipt in receipts_dir against it. Pure checking, no printing."""
    import glob

    from vigil.chain import verify
    from vigil.receipts import load_receipt, verify_receipt

    chain = verify(db_path, anchors_path, run=DEMO_LABEL)
    receipts = []
    for path in sorted(glob.glob(os.path.join(receipts_dir, "*.json"))):
        try:
            res = verify_receipt(load_receipt(path), db_path)
            receipts.append({"file": os.path.basename(path), "ok": res.ok, "line": res.line()})
        except (OSError, ValueError) as exc:
            receipts.append({"file": os.path.basename(path), "ok": False, "line": f"UNREADABLE: {type(exc).__name__}"})
    return {"chain_ok": chain.ok, "chain_line": chain.line(), "head": chain.head_hash, "head_seq": chain.head_seq,
            "receipts": receipts, "ok": chain.ok and bool(receipts) and all(r["ok"] for r in receipts)}


def run_demo(db_path: str = DEFAULT_DEMO_DB, receipts_dir: str = DEFAULT_DEMO_RECEIPTS, root: Optional[str] = None,
             anchors_path: Optional[str] = None, out=print) -> int:
    """Run the whole demo. Returns 0 only if every scenario matched ground truth and the chain and receipts verify."""
    from vigil.web.service import read_entries, summarize_entry  # imported here: the web service imports this module

    root = root or os.getcwd()
    anchors_path = anchors_path or os.path.join(root, "anchors.txt")
    out("Vigil demo (SIMULATED): simulated payment provider and ledger, deterministic offline stub model (no LLM, no keys), virtual clock.")
    reset_demo_files(db_path, receipts_dir)
    result = seed_demo(db_path, receipts_dir, root)

    entries = read_entries(db_path)
    by_incident: dict = {}
    for e in entries:
        by_incident.setdefault(e["incident_id"], []).append(e)
    out("")
    for iid, es in by_incident.items():
        sid = next((s["id"] for s in result["scenarios"] if s["chain_first_seq"] <= es[0]["seq"] <= s["chain_last_seq"]), "?")
        out(f"== {iid}, scenario {sid} (SIMULATED) ==")
        for e in es:
            out(f"  #{e['seq']:<3} {e['ts']}  {e['kind']:<15} {summarize_entry(e)}")
    out("")
    problems = []
    for s in result["scenarios"]:
        flag = "OK " if s["correct"] else "BAD"
        out(f"scenario {s['id']}: {s['outcome']} (expected {s['expected_outcome']}) {flag} steps={s['steps']} denials={s['policy_denials']}")
        if not s["correct"]:
            problems.append(f"scenario {s['id']} did not match ground truth: {s.get('notes', '')}")

    chk = check_demo(db_path, receipts_dir, anchors_path)
    out("")
    out(f"decision chain: {chk['chain_line']}")
    for r in chk["receipts"]:
        out(f"receipt {r['file']}: {r['line']}")
    if not chk["chain_ok"]:
        problems.append("decision chain does not verify")
    if not chk["receipts"]:
        problems.append("no receipts were written")
    problems += [f"receipt {r['file']} does not verify" for r in chk["receipts"] if not r["ok"]]
    out("")
    if problems:
        for p in problems:
            out(f"DEMO FAILED: {p}")
        return 1
    out(f"DEMO OK (SIMULATED): {len(result['scenarios'])} scenarios matched ground truth; the chain and {len(chk['receipts'])} receipts verify.")
    out(f"chain head {chk['head']} (tamper-evident, not tamper-proof)")
    out(f"verify again yourself: scripts/verify_chain --db {db_path} --run {DEMO_LABEL} ; scripts/verify_receipt --db {db_path} {receipts_dir}")
    return 0


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Run the offline Vigil demo on simulated data (zero keys).")
    p.add_argument("--db", default=DEFAULT_DEMO_DB)
    p.add_argument("--receipts", default=DEFAULT_DEMO_RECEIPTS)
    a = p.parse_args(argv)
    return run_demo(a.db, a.receipts)


if __name__ == "__main__":
    raise SystemExit(main())
