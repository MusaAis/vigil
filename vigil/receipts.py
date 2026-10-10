"""Portable per-incident receipts (SPEC 10, TS-7).

A receipt lists every decision-chain entry of one incident and carries a SHA-256 digest of its canonical payload.
The digest detects later edits to the receipt. It is NOT a signature and does not prove who produced the receipt.
verify_receipt() additionally checks the receipt against the chain so that a receipt edited and re-digested still fails.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from .canonical import sha256_json
from .chain import Chain, _entry, entry_hash
from .incidents import IncidentStore
from sim.world import TrustedView

RECEIPT_VERSION = 1
MODE = "simulated"


def build_receipt(chain: Chain, incident: dict, view: TrustedView, policy_currency: str, *, scenario_id: str,
                  run_label: str, git_sha: str, entire_checkpoint: Optional[str] = None) -> dict:
    iid = incident["incident_id"]
    entries = chain.entries(iid)
    if not entries or entries[-1]["kind"] != "OUTCOME":
        raise ValueError(f"{iid} has no OUTCOME entry; receipts are issued for closed incidents only")
    outcome = entries[-1]
    verifications = [e for e in entries if e["kind"] == "VERIFICATION"]
    verdicts = [e for e in entries if e["kind"] == "GATE_VERDICT"]
    results = [e["body"] for e in entries if e["kind"] == "ACTION_RESULT"]
    refund_amounts = {r["idempotency_key"]: r["amount_minor"] for r in view.refunds()}

    actions = []
    for e in entries:
        if e["kind"] != "ACTION_INTENT":
            continue
        b = e["body"]
        key = b.get("idempotency_key")
        actions.append({
            "tool": b["tool"], "args_sha256": b["args_sha256"], "idempotency_key": key,
            "amount_minor": refund_amounts.get(key) if b["tool"] == "issue_refund" else None,
            "executed": any(r["step"] == b["step"] and r["tool"] == b["tool"] and r["ok"] for r in results)})

    payload = {
        "incident_id": iid, "scenario_id": scenario_id, "type": incident["type"],
        "outcome": outcome["body"]["outcome"], "reason_code": outcome["body"]["reason_code"],
        "opened_at": entries[0]["ts"], "closed_at": outcome["ts"], "mode": MODE, "currency": policy_currency,
        "entries": [{"seq": e["seq"], "hash": e["entry_hash"]} for e in entries],
        "actions": actions,
        "verification": ({"ok": verifications[-1]["body"]["ok"], "checks": verifications[-1]["body"]["checks"]}
                         if verifications else {"ok": False, "checks": []}),
        "policy_sha256": verdicts[-1]["body"]["policy_sha256"] if verdicts else None,
        "run_label": run_label, "git_sha": git_sha,
        "neatlogs_trace_id": entries[0]["trace_id"], "entire_checkpoint": entire_checkpoint,
    }
    return {"receipt_version": RECEIPT_VERSION, "payload": payload, "digest": sha256_json(payload)}


def write_receipt(receipt: dict, directory: str = "receipts") -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{receipt['payload']['incident_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return path


def load_receipt(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- verification

@dataclass
class ReceiptVerification:
    ok: bool
    incident_id: str = ""
    digest: str = ""
    n_entries: int = 0
    problems: list = field(default_factory=list)

    def line(self) -> str:
        if self.ok:
            return f"OK incident={self.incident_id} entries={self.n_entries} digest={self.digest}"
        first = self.problems[0]
        return f"BROKEN incident={self.incident_id}: {first['code']}: {first['detail']}"


def _read_chain_rows(db_path: str, incident_id: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT seq,ts,incident_id,kind,body_json,trace_id,prev_hash,entry_hash FROM decision_chain "
            "WHERE incident_id=? ORDER BY seq", (incident_id,)).fetchall()
    finally:
        con.close()
    out = []
    for s, ts, inc, kind, bj, tid, prev, h in rows:
        body = json.loads(bj)
        out.append({"seq": s, "ts": ts, "kind": kind, "body": body, "stored_hash": h,
                    "recomputed_hash": entry_hash(_entry(s, ts, inc, kind, body, tid, prev))})
    return out


def verify_receipt(receipt: dict, db_path: str) -> ReceiptVerification:
    problems: list[dict] = []

    def bad(code: str, detail: str) -> None:
        problems.append({"code": code, "detail": detail})

    payload = receipt.get("payload") if isinstance(receipt, dict) else None
    if not isinstance(payload, dict) or receipt.get("receipt_version") != RECEIPT_VERSION:
        return ReceiptVerification(False, problems=[{"code": "MALFORMED", "detail": "unsupported receipt shape"}])
    iid = str(payload.get("incident_id", ""))
    res = ReceiptVerification(False, incident_id=iid, digest=str(receipt.get("digest", "")))

    try:
        if sha256_json(payload) != receipt.get("digest"):
            bad("DIGEST_MISMATCH", "payload does not match its digest (receipt was edited)")
    except ValueError as exc:
        bad("MALFORMED", f"payload is not canonical JSON: {exc}")

    rows = _read_chain_rows(db_path, iid)
    by_seq = {r["seq"]: r for r in rows}
    listed = payload.get("entries") or []
    res.n_entries = len(listed)

    for item in listed:
        row = by_seq.get(item.get("seq"))
        if row is None:
            bad("ENTRY_MISSING", f"seq {item.get('seq')} is not in the chain for {iid}")
        elif row["stored_hash"] != item.get("hash"):
            bad("ENTRY_HASH_MISMATCH", f"seq {row['seq']}: receipt hash differs from the chain")
        elif row["recomputed_hash"] != row["stored_hash"]:
            bad("HASH_MISMATCH", f"seq {row['seq']}: chain row does not match its hash (chain was edited)")
    listed_seqs = {item.get("seq") for item in listed}
    for r in rows:
        if r["seq"] not in listed_seqs:
            bad("ENTRY_UNLISTED", f"chain entry seq {r['seq']} ({r['kind']}) is missing from the receipt")
    if [i.get("seq") for i in listed] != sorted(listed_seqs):
        bad("ENTRY_ORDER", "entries are not listed in ascending seq order")

    outcomes = [r for r in rows if r["kind"] == "OUTCOME"]
    if len(outcomes) != 1:
        bad("OUTCOME_MISMATCH", f"expected exactly one OUTCOME entry, found {len(outcomes)}")
    else:
        ob = outcomes[0]["body"]
        if (ob["outcome"], ob["reason_code"]) != (payload.get("outcome"), payload.get("reason_code")):
            bad("OUTCOME_MISMATCH", "receipt outcome differs from the chain OUTCOME entry")
    vers = [r for r in rows if r["kind"] == "VERIFICATION"]
    if vers and (payload.get("verification") or {}).get("ok") != vers[-1]["body"]["ok"]:
        bad("VERIFICATION_MISMATCH", "receipt verification result differs from the chain")
    intents = [r["body"]["args_sha256"] for r in rows if r["kind"] == "ACTION_INTENT"]
    if [a.get("args_sha256") for a in payload.get("actions") or []] != intents:
        bad("ACTIONS_MISMATCH", "receipt actions differ from the ACTION_INTENT entries in the chain")

    res.problems, res.ok = problems, not problems
    return res
