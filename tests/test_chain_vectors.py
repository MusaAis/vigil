"""SPEC 9.7 test vectors. If these fail, canonicalization is wrong. Do not edit the constants."""
from vigil.canonical import canonical_json, sha256_json
from vigil.chain import Chain
from vigil.clock import VirtualClock

GENESIS = "sha256:847e4febfe1c429a14d7a66675ec721211b2e9487306986f7c1060f8d80766db"
E0_JSON = ('{"body":{"related":["ch_A","ch_B"],"type":"duplicate_charge"},"incident_id":"inc_0001",'
           '"kind":"INCIDENT_OPENED","prev_hash":"sha256:847e4febfe1c429a14d7a66675ec721211b2e9487306986f7c1060f8d80766db",'
           '"seq":0,"trace_id":"trace_demo","ts":"2026-10-10T08:00:00Z"}')
E0_HASH = "sha256:ee36486ef4c173ecd5a00515e752a9de6516ced241fcc6042046316fa2ab0d86"
E1_JSON = ('{"body":{"args":{"charge_id":"ch_B"},"decision":"ACT","rationale":"duplicate confirmed by provider",'
           '"tool":"issue_refund"},"incident_id":"inc_0001","kind":"DECISION",'
           '"prev_hash":"sha256:ee36486ef4c173ecd5a00515e752a9de6516ced241fcc6042046316fa2ab0d86",'
           '"seq":1,"trace_id":"trace_demo","ts":"2026-10-10T08:00:02Z"}')
E1_HASH = "sha256:720dc29828e4068374e543c826e3313f79054a64e12433884fad0cb10660a84a"
DIGEST_PAYLOAD = {"entry_hashes": [E0_HASH, E1_HASH], "incident_id": "inc_0001",
                  "outcome": "RESOLVED"}
DIGEST = "sha256:b0afaa83cf98f373a0988095b4786e935a58c7f6af22758c67c1b3ab22e761be"


def _build(tmp_path):
    clock = VirtualClock("2026-10-10T08:00:00Z")
    chain = Chain(str(tmp_path / "v.db"), clock)
    e0 = chain.append("inc_0001", "INCIDENT_OPENED",
                      {"type": "duplicate_charge", "related": ["ch_A", "ch_B"]}, "trace_demo")
    clock.advance(2)
    e1 = chain.append("inc_0001", "DECISION",
                      {"decision": "ACT", "tool": "issue_refund", "args": {"charge_id": "ch_B"},
                       "rationale": "duplicate confirmed by provider"}, "trace_demo")
    return e0, e1


def test_entry_vectors(tmp_path):
    e0, e1 = _build(tmp_path)
    assert e0["prev_hash"] == GENESIS
    h0 = e0.pop("entry_hash")
    h1 = e1.pop("entry_hash")
    assert canonical_json(e0) == E0_JSON
    assert h0 == E0_HASH
    assert canonical_json(e1) == E1_JSON
    assert h1 == E1_HASH


def test_digest_vector():
    assert sha256_json(DIGEST_PAYLOAD) == DIGEST
