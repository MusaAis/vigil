"""Web service tests (SPEC TS-3 to TS-8). Framework-free: these run without FastAPI."""
import json
import os
import re
import sqlite3

import pytest

from vigil.canonical import sha256_json
from vigil.web import render
from vigil.web.service import REQUIRED_CLAIMS, VigilService, summarize_entry
from vigil.web.settings import WebSettings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make(tmp_path, sub=None, **over):
    if sub:
        tmp_path = tmp_path / sub
        tmp_path.mkdir()
    s = WebSettings(db_path=str(tmp_path / "chain.db"), receipts_dir=str(tmp_path / "receipts"),
                    evidence_path=str(tmp_path / "evidence.json"), **over)
    svc = VigilService(s, now=lambda: "2026-10-11T12:00:00Z")
    svc.ensure_seeded()
    svc.verify_chain()
    return svc


def no_floats(x):
    if isinstance(x, float):
        return False
    if isinstance(x, dict):
        return all(no_floats(v) for v in x.values())
    if isinstance(x, list):
        return all(no_floats(v) for v in x)
    return True


def tamper(db_path, seq=5):
    con = sqlite3.connect(db_path)
    con.execute("DROP TRIGGER chain_no_update")
    body = json.loads(con.execute("SELECT body_json FROM decision_chain WHERE seq=?", (seq,)).fetchone()[0])
    body["tampered"] = True
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=?", (json.dumps(body, sort_keys=True, separators=(",", ":")), seq))
    con.commit()
    con.close()


def test_seed_is_reproducible(tmp_path):
    a = make(tmp_path, "a")
    b = make(tmp_path, "b")
    assert a.chain_status()["head"] == b.chain_status()["head"]
    assert a.chain_status()["ok"] and a.chain_status()["length"] > 0


def test_ensure_seeded_keeps_existing_chain(tmp_path):
    svc = make(tmp_path)
    head = svc.chain_status()["head"]
    assert svc.ensure_seeded() is False
    assert svc.verify_chain()["head"] == head


def test_unreadable_chain_is_reported_not_replaced(tmp_path):
    p = tmp_path / "chain.db"
    p.write_bytes(b"this is not a sqlite database" * 50)
    svc = VigilService(WebSettings(db_path=str(p), receipts_dir=str(tmp_path / "r")), now=lambda: "2026-10-11T12:00:00Z")
    assert svc.ensure_seeded() is False
    assert p.read_bytes().startswith(b"this is not")
    st = svc.verify_chain()
    assert st["ok"] is False and st["reason"] == "UNREADABLE"
    assert svc.health()["ok"] is False


def test_health_shape_and_labels(tmp_path):
    h = make(tmp_path).health()
    assert h["ok"] is True and h["service"] == "vigil" and h["mode"] == "simulated"
    assert set(h["chain"]) == {"length", "head", "verified_ok", "verified_at", "verify_mode"}
    assert h["chain"]["verify_mode"] == "full" and h["chain"]["head"].startswith("sha256:")
    assert h["llm"] == {"provider": "offline-stub", "mode": "offline"}
    assert h["last_eval"]["label"] and h["policy_sha256"].startswith("sha256:")
    assert no_floats(h)


def test_health_goes_false_when_chain_is_edited(tmp_path):
    svc = make(tmp_path)
    tamper(svc.s.db_path)
    st = svc.verify_chain()
    assert st["ok"] is False and st["reason"] == "HASH_MISMATCH" and st["broken_seq"] == 5
    h = svc.health()
    assert h["ok"] is False and h["chain"]["verified_ok"] is False
    assert svc.proof()["data"]["chain"]["verified_ok"] is False


def test_metrics_have_boundaries_and_snapshot_hash(tmp_path):
    m = make(tmp_path).metrics()
    assert m["data"] and all(x["boundary"].strip() for x in m["data"])
    assert m["snapshot_sha256"] == sha256_json(m["data"])
    assert no_floats(m)
    by = {x["name"]: x["value"] for x in m["data"]}
    assert by["incidents_resolved"] == 1 and by["incidents_escalated"] == 1 and by["incidents_skipped"] == 1
    assert by["unsafe_actions_executed"] == 0 and by["recorded_runs"] >= 1
    files = [json.load(open(f)) for f in sorted(__import__("glob").glob(os.path.join(ROOT, "eval", "results", "*.json")))]
    assert by["recorded_runs"] == len(files)
    assert by["eval_scenarios_run"] == sum(f["metrics"]["n_total"] for f in files)
    assert by["eval_scenarios_correct"] == sum(f["metrics"]["n_correct"] for f in files)
    assert by["unsafe_actions_executed"] == sum(f["metrics"]["unsafe_actions_executed"] for f in files)


def test_incidents_list(tmp_path):
    rows = make(tmp_path).incidents()["data"]
    assert [(r["incident_id"], r["scenario_id"], r["outcome"]) for r in rows] == [
        ("inc_0001", "D1", "RESOLVED"), ("inc_0002", "D2", "ESCALATED"), ("inc_0003", "D3", "SKIPPED")]
    assert all(r["source"] == "simulated" and r["has_receipt"] for r in rows)


def test_incident_detail(tmp_path):
    d = make(tmp_path).incident("inc_0001")
    assert d["source"] == "simulated"
    assert [t["seq"] for t in d["timeline"]] == sorted(t["seq"] for t in d["timeline"])
    assert d["gate_verdicts"][0]["verdict"] == "ALLOW"
    assert d["verification"]["ok"] and all(c["ok"] for c in d["verification"]["checks"])
    assert d["receipt"]["payload"]["incident_id"] == "inc_0001"
    skipped = make(tmp_path, "s").incident("inc_0003")
    assert skipped["incident"]["outcome"] == "SKIPPED" and skipped["gate_verdicts"] == []
    assert [c["name"] for c in skipped["verification"]["checks"]] == ["no_action_needed"]


@pytest.mark.parametrize("bad", ["../etc/passwd", "inc_0001/../../x", "INC_0001", "inc_", "", "inc_9999", "x" * 500, "inc_0001;drop"])
def test_bad_incident_ids_return_nothing(tmp_path, bad):
    svc = make(tmp_path)
    assert svc.incident(bad) is None and svc.receipt(bad) is None and svc.verify_receipt_for(bad) is None


def test_receipt_verify_ok_then_fails_after_edit(tmp_path):
    svc = make(tmp_path)
    assert svc.verify_receipt_for("inc_0001")["ok"] is True
    path = os.path.join(svc.s.receipts_dir, "inc_0001.json")
    rec = json.load(open(path))
    rec["payload"]["actions"][0]["amount_minor"] = 1
    json.dump(rec, open(path, "w"))
    res = svc.verify_receipt_for("inc_0001")
    assert res["ok"] is False and any(p["code"] == "DIGEST_MISMATCH" for p in res["problems"])


def test_receipt_verify_fails_when_chain_is_edited(tmp_path):
    svc = make(tmp_path)
    tamper(svc.s.db_path, seq=3)
    res = svc.verify_receipt_for("inc_0001")
    assert res["ok"] is False


def test_stream_entries_after_seq(tmp_path):
    svc = make(tmp_path)
    everything = svc.stream_entries(-1, 1000)
    assert [e["seq"] for e in everything] == list(range(len(everything)))
    assert set(everything[0]) == {"seq", "kind", "incident_id", "summary", "entry_hash"}
    tail = svc.stream_entries(5, 1000)
    assert tail[0]["seq"] == 6 and len(tail) == len(everything) - 6
    assert svc.stream_entries(everything[-1]["seq"]) == []


def test_exposure_meter_stays_inside_caps(tmp_path):
    ex = make(tmp_path).exposure()
    assert ex["source"] == "simulated"
    assert ex["peak_day_refunded_minor"] <= ex["caps"]["per_day_minor"]
    assert ex["max_write_actions_in_one_incident"] <= ex["caps"]["max_write_actions_per_incident"]
    assert ex["refunded_by_utc_day_minor"] == {"2026-10-10": 2500000}


def test_proof_has_the_eight_sections_in_order(tmp_path):
    p = make(tmp_path).proof()
    assert list(p["data"]) == ["chain", "eval", "tests", "evidence", "real_vs_simulated", "verify", "limits", "event_window"]
    assert all("source" in sec for sec in p["data"].values())
    assert p["snapshot_sha256"] == sha256_json(p["data"]) and no_floats(p)
    assert [r["label"] for r in p["data"]["eval"]["runs"]]
    for a in p["data"]["chain"]["anchors"]:
        assert a["commit_url"].endswith("/commit/" + a["git"])


def test_proof_snapshot_is_stable_and_follows_content(tmp_path):
    svc = make(tmp_path)
    assert svc.proof()["snapshot_sha256"] == svc.proof()["snapshot_sha256"]
    before = svc.proof()["snapshot_sha256"]
    tamper(svc.s.db_path)
    svc.verify_chain()
    assert svc.proof()["snapshot_sha256"] != before


def test_proof_eval_rows_come_from_result_files(tmp_path):
    runs = make(tmp_path).proof()["data"]["eval"]["runs"]
    for r in runs:
        f = json.load(open(os.path.join(ROOT, "eval", "results", r["label"] + ".json")))
        assert (r["n_correct"], r["n_total"]) == (f["metrics"]["n_correct"], f["metrics"]["n_total"])
        assert r["failures"] == [{"id": s["id"], "outcome": s["outcome"], "expected_outcome": s["expected_outcome"],
                                  "notes": s.get("notes", "")} for s in f["scenarios"] if not s["correct"]]
    assert any(r["failures"] for r in runs)  # failing runs stay visible


def test_evidence_pending_rules(tmp_path):
    svc = make(tmp_path)
    assert [e["claim"] for e in svc.evidence()] == list(REQUIRED_CLAIMS) and all(e["status"] == "pending" for e in svc.evidence())
    json.dump([
        {"claim": "used neatlogs", "kind": "trace", "url": "https://example.com/t/1", "added_at": "x", "status": "ok"},
        {"claim": "used Entire", "kind": "x", "url": None, "added_at": "x", "status": "ok"},
        {"claim": "built in public", "kind": "x", "url": "javascript:alert(1)", "added_at": "x", "status": "ok"},
        {"claim": "used cfo.ai (business plan)", "kind": "x", "url": "https://example.com/p", "added_at": "x", "status": "pending"},
    ], open(svc.s.evidence_path, "w"))
    by = {e["claim"]: e for e in svc.evidence()}
    assert by["used neatlogs"]["status"] == "ok" and by["used neatlogs"]["url"] == "https://example.com/t/1"
    for claim in ("used Entire", "built in public", "used cfo.ai (business plan)"):
        assert by[claim]["status"] == "pending" and by[claim]["url"] is None
    assert by["recovers from failures"]["status"] == "pending"  # required claims missing from the file are added as pending


def test_pages_render_and_are_labelled(tmp_path):
    svc = make(tmp_path)
    for html in (render.home_html(svc), render.dashboard_html(svc), render.proof_html(svc), render.status_html(svc),
                 render.incident_html(svc, "inc_0001", svc.verify_receipt_for("inc_0001"))):
        assert "SIMULATED" in html and "tamper-evident, not tamper-proof" in html
        assert "src=\"http" not in html and "<script src" not in html  # self-contained
        assert all(h.startswith("data:") for h in re.findall(r'<link[^>]*href="([^"]*)"', html))  # only an inline icon
    assert render.incident_html(svc, "inc_9999") is None
    assert "PENDING" in render.proof_html(svc)
    assert "OK incident=inc_0001" in render.incident_html(svc, "inc_0001", svc.verify_receipt_for("inc_0001"))


def test_pages_escape_untrusted_text(tmp_path):
    svc = make(tmp_path)
    json.dump([{"claim": "<script>alert(1)</script>", "kind": "<b>x</b>", "url": "https://example.com/?a=<i>", "added_at": "x", "status": "ok"}],
              open(svc.s.evidence_path, "w"))
    html = render.proof_html(svc)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_dashboard_shows_counting_boundaries_and_meter(tmp_path):
    svc = make(tmp_path)
    html = render.dashboard_html(svc)
    for x in svc.metrics()["data"]:
        if x["name"] in ("incidents_resolved", "unsafe_actions_executed", "gate_denials"):
            assert x["boundary"].split(";")[0][:30] in html
    assert "Exposure meter" in html and "500,000.00 NGN" in html and "25,000.00 NGN" in html


def test_money_and_pct_are_integer_only():
    assert render.money(2500000) == "25,000.00 NGN" and render.money(5) == "0.05 NGN" and render.money(-150) == "-1.50 NGN"
    assert render.money(None) == "n/a" and render.pct(None) == "n/a" and render.pct(71) == "71%"


def test_summaries_use_structured_fields():
    e = {"kind": "OBSERVATION", "body": {"tool": "get_provider_charge", "result_summary": "charge ch_1 succeeded", "injection_suspected": True}}
    assert summarize_entry(e) == "read get_provider_charge: charge ch_1 succeeded [injection suspected]"
    assert summarize_entry({"kind": "GATE_VERDICT", "body": {"verdict": "DENY", "code": "NOT_DUPLICATE"}}) == "gate DENY NOT_DUPLICATE"


def test_decision_summary_has_no_stray_spaces():
    assert summarize_entry({"kind": "DECISION", "body": {"decision": "SKIP", "tool": None, "rationale": "x"}}) == "SKIP: x"
    assert summarize_entry({"kind": "DECISION", "body": {"decision": "ACT", "tool": "issue_refund", "rationale": "y"}}) == "ACT issue_refund: y"


def test_receipt_lookup_cannot_escape_the_receipts_directory(tmp_path):
    svc = make(tmp_path)
    outside = json.load(open(os.path.join(svc.s.receipts_dir, "inc_0001.json")))
    json.dump(outside, open(tmp_path / "secret.json", "w"))  # a valid receipt, but outside receipts/
    assert os.path.exists(os.path.join(svc.s.receipts_dir, "..", "secret.json"))
    for bad in ("../secret", "..%2Fsecret", "inc_0001/../../secret"):
        assert svc.receipt(bad) is None and svc.verify_receipt_for(bad) is None and svc.incident(bad) is None


# ---------------------------------------------------------------- redesign: overview page, ribbon, accessibility basics
def test_chain_strip_is_the_real_chain(tmp_path):
    svc = make(tmp_path)
    strip = svc.chain_strip()
    assert strip["source"] == "simulated"
    seqs = [c["seq"] for g in strip["groups"] for c in g["cells"]]
    assert seqs == list(range(svc.chain_status()["length"]))
    assert [(g["incident_id"], g["scenario_id"], g["outcome"]) for g in strip["groups"]] == [
        ("inc_0001", "D1", "RESOLVED"), ("inc_0002", "D2", "ESCALATED"), ("inc_0003", "D3", "SKIPPED")]
    classes = {c["cls"] for g in strip["groups"] for c in g["cells"]}
    assert {x["cls"] for x in strip["legend"]} == classes  # the legend lists exactly the kinds that appear
    assert "GATE_ESCALATE" in classes and "GATE_DENY" not in classes and "OUTCOME_RESOLVED" in classes
    heads = {c["seq"]: c["entry_hash"] for g in strip["groups"] for c in g["cells"]}
    assert heads[0] == [e for e in svc.stream_entries(-1, 1)][0]["entry_hash"]


def test_overview_shows_every_chain_entry_and_real_numbers(tmp_path):
    svc = make(tmp_path)
    html = render.home_html(svc)
    assert html.count('class="cell ') == svc.chain_status()["length"]
    assert 'href="/dashboard/incidents/inc_0002#e21"' in html  # each cell links to its entry
    for r in svc.proof()["data"]["eval"]["runs"]:
        assert f"{r['n_correct']} of {r['n_total']} correct" in html
    assert svc.chain_status()["head"][:25] in html and "Chain verified from genesis" in html


def test_overview_warns_when_the_chain_does_not_verify(tmp_path):
    svc = make(tmp_path)
    tamper(svc.s.db_path)
    svc.verify_chain()
    html = render.home_html(svc)
    assert "Chain does not verify." in html and "Chain verified from genesis" not in html


def test_verify_commands_come_from_the_repo_url(tmp_path):
    svc = make(tmp_path, repo_url="https://github.com/example/vigil-fork")
    assert svc.verify_commands()[0] == "git clone https://github.com/example/vigil-fork && cd vigil"
    assert "https://github.com/example/vigil-fork" in render.home_html(svc)
    assert svc.proof()["data"]["verify"]["commands"] == svc.verify_commands()


def test_exposure_reports_the_largest_refund_in_one_incident(tmp_path):
    ex = make(tmp_path).exposure()
    assert ex["peak_incident_refunded_minor"] == 2500000 <= ex["caps"]["per_incident_minor"]


def test_pages_have_basic_accessibility_structure(tmp_path):
    svc = make(tmp_path)
    pages = {"home": render.home_html(svc), "dashboard": render.dashboard_html(svc), "proof": render.proof_html(svc),
             "status": render.status_html(svc), "incident": render.incident_html(svc, "inc_0001")}
    for name, html in pages.items():
        assert '<html lang="en">' in html and 'name="viewport"' in html, name
        assert 'class="skip" href="#content"' in html and '<main id="content">' in html, name
        assert html.count("<h1") == 1, name
        assert "prefers-reduced-motion" in html and "focus-visible" in html, name
        assert html.count('aria-current="page"') == 1 or name == "incident", name
    assert 'href="/proof" aria-current="page"' in pages["proof"]
    # the live log is the only script, and it builds nodes with textContent (no innerHTML from stream data)
    assert "innerHTML" not in pages["dashboard"] and pages["dashboard"].count("<script") == 1
    assert all("<script" not in pages[n] for n in ("home", "proof", "status", "incident"))


def test_timeline_classes_do_not_collide_with_ribbon_colours(tmp_path):
    html = render.incident_html(make(tmp_path), "inc_0001")
    assert 'class="k-DECISION"' in html and 'class="DECISION"' not in html


def test_hostile_text_in_the_chain_is_escaped_on_every_page(tmp_path):
    svc = make(tmp_path)
    con = sqlite3.connect(svc.s.db_path)
    con.execute("DROP TRIGGER chain_no_update")
    body = json.loads(con.execute("SELECT body_json FROM decision_chain WHERE seq=30").fetchone()[0])
    body["result_summary"] = "<script>alert(1)</script>"
    con.execute("UPDATE decision_chain SET body_json=? WHERE seq=30", (json.dumps(body, sort_keys=True, separators=(",", ":")),))
    con.commit()
    con.close()
    for html in (render.home_html(svc), render.dashboard_html(svc), render.incident_html(svc, "inc_0003")):
        assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
