"""HTTP wrapper tests (FastAPI TestClient). The logic is tested in test_web_service.py; these check routing, shapes and limits."""
import json

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from vigil.web.service import VigilService  # noqa: E402
from vigil.web.settings import WebSettings  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    svc = VigilService(WebSettings(db_path=str(tmp_path / "c.db"), receipts_dir=str(tmp_path / "r"),
                                   evidence_path=str(tmp_path / "e.json")), now=lambda: "2026-10-11T12:00:00Z")
    with TestClient(create_app(svc, background=False)) as c:
        yield c


def test_json_endpoints_return_service_data(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["mode"] == "simulated" and h["chain"]["verified_ok"] is True
    m = client.get("/api/metrics").json()
    assert m["snapshot_sha256"].startswith("sha256:") and all(x["boundary"] for x in m["data"])
    assert list(client.get("/api/proof").json()["data"])[0] == "chain"
    inc = client.get("/api/incidents").json()["data"]
    assert [i["incident_id"] for i in inc] == ["inc_0001", "inc_0002", "inc_0003"] and all(i["source"] == "simulated" for i in inc)
    assert client.get("/api/incidents/inc_0001").json()["incident"]["outcome"] == "RESOLVED"
    assert client.get("/api/incidents/inc_0001/receipt").json()["payload"]["incident_id"] == "inc_0001"


def test_receipt_verify_endpoint(client):
    r = client.post("/api/incidents/inc_0001/receipt/verify").json()
    assert r["ok"] is True and r["line"].startswith("OK incident=inc_0001")
    assert client.get("/api/incidents/inc_0001/receipt/verify").status_code == 405  # verification is a POST


def test_unknown_and_malformed_ids(client):
    r = client.get("/api/incidents/inc_9999")
    assert r.status_code == 404 and r.json() == {"ok": False, "error_type": "NOT_FOUND", "message": "no such incident", "retryable": False}
    assert client.post("/api/incidents/inc_9999/receipt/verify").status_code == 404
    for bad in ("INC_0001", "inc_0001;x", "..%2Fsecret"):
        assert client.get(f"/api/incidents/{bad}").status_code in (404, 422)
    assert client.get("/dashboard/incidents/inc_9999").status_code == 404


def test_stream_replays_the_chain_as_sse(client):
    r = client.get("/api/stream?once=true")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    blocks = [b for b in r.text.split("\n\n") if b.strip()]
    events = [json.loads(next(l for l in b.splitlines() if l.startswith("data: "))[6:]) for b in blocks]
    assert all("event: chain_entry" in b for b in blocks)
    assert [e["seq"] for e in events] == list(range(len(events))) and len(events) == client.get("/api/health").json()["chain"]["length"]
    assert set(events[0]) == {"seq", "kind", "incident_id", "summary", "entry_hash"}
    after = client.get(f"/api/stream?once=true&after={events[-3]['seq']}").text
    assert after.count("event: chain_entry") == 2
    assert client.get("/api/stream?after=abc").status_code == 422  # integers only


def test_pages_work_without_javascript(client):
    for path in ("/dashboard", "/proof", "/status", "/dashboard/incidents/inc_0001"):
        r = client.get(path)
        assert r.status_code == 200 and "SIMULATED" in r.text, path
    assert client.get("/", follow_redirects=False).headers["location"] == "/dashboard"
    # the verify button is a plain form post
    r = client.post("/dashboard/incidents/inc_0001/verify")
    assert r.status_code == 200 and "OK incident=inc_0001" in r.text


def test_read_only_surface(client):
    assert client.post("/api/incidents", json={"x": "free text"}).status_code == 405
    assert client.post("/api/health", json={}).status_code == 405
    assert client.get("/openapi.json").status_code == 404 and client.get("/docs").status_code == 404
    assert client.get("/api/try").status_code == 404  # Tier B, not built yet
