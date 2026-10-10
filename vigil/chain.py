"""SHA-256 hash-chained, append-only decision chain (SPEC 9). Tamper-evident, NOT tamper-proof."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Optional

from .canonical import GENESIS_HASH, CanonicalError, canonical_json, sha256_json
from .clock import Clock

KINDS = frozenset({
    "INCIDENT_OPENED", "OBSERVATION", "DECISION", "GATE_VERDICT",
    "ACTION_INTENT", "ACTION_RESULT", "VERIFICATION", "OUTCOME",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_chain(
  seq         INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL,
  incident_id TEXT NOT NULL,
  kind        TEXT NOT NULL,
  body_json   TEXT NOT NULL,
  trace_id    TEXT NOT NULL,
  prev_hash   TEXT NOT NULL,
  entry_hash  TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS chain_no_update BEFORE UPDATE ON decision_chain
  BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_no_delete BEFORE DELETE ON decision_chain
  BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""

# Serializes appends inside one process. BEGIN IMMEDIATE covers other processes.
_APPEND_LOCK = threading.RLock()


def entry_hash(entry: dict) -> str:
    """Hash of the entry WITHOUT the entry_hash field (SPEC 16 mistake #6)."""
    return sha256_json(entry)


def _entry(seq: int, ts: str, incident_id: str, kind: str, body: Any,
           trace_id: str, prev_hash: str) -> dict:
    return {"seq": seq, "ts": ts, "incident_id": incident_id, "kind": kind,
            "body": body, "trace_id": trace_id, "prev_hash": prev_hash}


class Chain:
    def __init__(self, db_path: str, clock: Clock) -> None:
        self.db_path = db_path
        self.clock = clock
        self._con = sqlite3.connect(db_path, isolation_level=None, timeout=30,
                                    check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=FULL")
        self._con.executescript(SCHEMA)

    def close(self) -> None:
        self._con.close()

    def append(self, incident_id: str, kind: str, body: dict, trace_id: str) -> dict:
        """Append one entry. Returns the entry dict plus 'entry_hash'. Committed on return."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        if not isinstance(body, dict):
            raise TypeError("body must be a dict")
        if not trace_id or not isinstance(trace_id, str):
            raise ValueError("trace_id required (use 'offline-<n>' if tracing is off)")
        body_json = canonical_json(body)  # rejects floats/NaN before anything is written
        with _APPEND_LOCK:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                row = self._con.execute(
                    "SELECT seq, entry_hash FROM decision_chain ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq, prev = (0, GENESIS_HASH) if row is None else (row[0] + 1, row[1])
                ts = self.clock.now()
                entry = _entry(seq, ts, incident_id, kind, body, trace_id, prev)
                h = entry_hash(entry)
                self._con.execute(
                    "INSERT INTO decision_chain(seq,ts,incident_id,kind,body_json,"
                    "trace_id,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?)",
                    (seq, ts, incident_id, kind, body_json, trace_id, prev, h))
                self._con.execute("COMMIT")
            except BaseException:
                self._con.execute("ROLLBACK")
                raise
        return {**entry, "entry_hash": h}

    def head(self) -> Optional[dict]:
        r = self._con.execute(
            "SELECT seq, entry_hash FROM decision_chain ORDER BY seq DESC LIMIT 1").fetchone()
        return None if r is None else {"seq": r[0], "entry_hash": r[1]}

    def entries(self, incident_id: Optional[str] = None) -> list[dict]:
        q = ("SELECT seq,ts,incident_id,kind,body_json,trace_id,prev_hash,entry_hash "
             "FROM decision_chain")
        args: tuple = ()
        if incident_id is not None:
            q += " WHERE incident_id=?"
            args = (incident_id,)
        out = []
        for s, ts, inc, kind, bj, tid, prev, h in self._con.execute(q + " ORDER BY seq", args):
            out.append({"seq": s, "ts": ts, "incident_id": inc, "kind": kind,
                        "body": json.loads(bj), "trace_id": tid, "prev_hash": prev,
                        "entry_hash": h})
        return out

    def has_committed_intent(self, incident_id: str, tool: str, args_sha256: str) -> bool:
        """True iff an ACTION_INTENT for (tool, args_sha256) is already committed (INV-5)."""
        for e in self.entries(incident_id):
            if e["kind"] == "ACTION_INTENT" and e["body"].get("tool") == tool \
                    and e["body"].get("args_sha256") == args_sha256:
                return True
        return False


# ---------------------------------------------------------------- verification

@dataclass
class VerifyResult:
    ok: bool
    count: int = 0
    head_seq: Optional[int] = None
    head_hash: Optional[str] = None
    broken_seq: Optional[int] = None
    reason: Optional[str] = None
    message: str = ""

    def line(self) -> str:
        if self.ok:
            if self.head_seq is None:
                return "OK empty chain"
            return f"OK seq=0..{self.head_seq} head={self.head_hash}"
        return f"BROKEN at seq={self.broken_seq}: {self.reason}" + \
               (f" ({self.message})" if self.message else "")


_ANCHOR_RE = re.compile(
    r"^(?P<ts>\S+) run=(?P<run>\S+) seq=(?P<seq>\d+) head=(?P<head>sha256:[0-9a-f]{64}) "
    r"git=(?P<git>\S+)$")


def parse_anchors(text: str) -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ANCHOR_RE.match(line)
        if not m:
            raise ValueError(f"anchors line {n} is malformed")
        out.append({"ts": m["ts"], "run": m["run"], "seq": int(m["seq"]),
                    "head": m["head"], "git": m["git"]})
    return out


def verify(db_path: str, anchors_path: Optional[str] = None, run: Optional[str] = None) -> VerifyResult:
    """Walk the chain from genesis (SPEC 9.5). Returns the first problem found.

    With run=<label>, only anchors written for that run label are checked (one anchors file can serve several chains)."""
    con = sqlite3.connect(db_path, timeout=30)
    try:
        rows = con.execute(
            "SELECT seq,ts,incident_id,kind,body_json,trace_id,prev_hash,entry_hash "
            "FROM decision_chain ORDER BY seq").fetchall()
    finally:
        con.close()

    expected, prev = 0, GENESIS_HASH
    by_seq: dict[int, str] = {}
    for seq, ts, inc, kind, bj, tid, prev_hash, ehash in rows:
        if seq != expected:
            return VerifyResult(False, broken_seq=expected, reason="SEQ_GAP",
                                message=f"found seq {seq}, expected {expected}")
        if prev_hash != prev:
            return VerifyResult(False, broken_seq=seq,
                                reason="GENESIS_MISMATCH" if seq == 0 else "PREV_MISMATCH")
        try:
            body = json.loads(bj)
            if canonical_json(body) != bj:
                raise CanonicalError("body_json is not canonical")
            recomputed = entry_hash(_entry(seq, ts, inc, kind, body, tid, prev_hash))
        except (ValueError, CanonicalError) as exc:
            return VerifyResult(False, broken_seq=seq, reason="HASH_MISMATCH", message=str(exc))
        if recomputed != ehash:
            return VerifyResult(False, broken_seq=seq, reason="HASH_MISMATCH")
        by_seq[seq] = ehash
        prev, expected = ehash, expected + 1

    if anchors_path:
        try:
            with open(anchors_path, encoding="utf-8") as f:
                anchors = parse_anchors(f.read())
        except FileNotFoundError:
            anchors = []
        except ValueError as exc:
            return VerifyResult(False, broken_seq=-1, reason="ANCHOR_MISMATCH", message=str(exc))
        for a in anchors:
            if run is not None and a["run"] != run:
                continue
            if a["seq"] not in by_seq:
                return VerifyResult(False, broken_seq=a["seq"], reason="ANCHOR_SEQ_MISSING",
                                    message="chain is shorter than a published anchor")
            if by_seq[a["seq"]] != a["head"]:
                return VerifyResult(False, broken_seq=a["seq"], reason="ANCHOR_MISMATCH")

    if not rows:
        return VerifyResult(True)
    return VerifyResult(True, count=len(rows), head_seq=rows[-1][0], head_hash=rows[-1][7])


def append_anchor(chain: Chain, anchors_path: str, run_label: str, git_sha: str) -> str:
    """Append the current chain head to anchors.txt. Refuses if the chain does not verify."""
    res = verify(chain.db_path, anchors_path)
    if not res.ok:
        raise RuntimeError(f"refusing to anchor a broken chain: {res.line()}")
    if res.head_seq is None:
        raise RuntimeError("refusing to anchor an empty chain")
    line = f"{chain.clock.now()} run={run_label} seq={res.head_seq} head={res.head_hash} git={git_sha}"
    with open(anchors_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line
