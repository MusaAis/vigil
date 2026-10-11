"""Thin FastAPI wrapper around vigil.web.service (SPEC TS-3 to TS-8). Read-only for the public: no endpoint takes free text.

Run: uvicorn api.app:app --host 127.0.0.1 --port 8000   (from the repository root; `make serve`)
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Path, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from vigil.web import render
from vigil.web.service import VigilService
from vigil.web.settings import WebSettings

ID_PATTERN = r"^inc_[0-9a-z]+$"


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error_type": code, "message": message, "retryable": False}, status_code=status)


def create_app(service: Optional[VigilService] = None, *, background: bool = True) -> FastAPI:
    svc = service or VigilService(WebSettings.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if background:
            svc.start()  # seeds if needed, verifies the whole chain, then re-verifies every 5 minutes
        else:
            svc.ensure_seeded()
            svc.verify_chain()
        yield
        svc.stop()

    app = FastAPI(title="Vigil (simulated)", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service = svc

    def html(body: Optional[str], status: int = 200) -> HTMLResponse:
        return HTMLResponse(body if body is not None else "<h1>Not found</h1>", status_code=status if body else 404)

    # ------------------------------------------------------------ JSON API
    @app.get("/api/health")
    def health():
        return svc.health()

    @app.get("/api/metrics")
    def metrics():
        return svc.metrics()

    @app.get("/api/proof")
    def proof():
        return svc.proof()

    @app.get("/api/incidents")
    def incidents():
        return svc.incidents()

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: str = Path(pattern=ID_PATTERN)):
        d = svc.incident(incident_id)
        return d if d is not None else _err(404, "NOT_FOUND", "no such incident")

    @app.get("/api/incidents/{incident_id}/receipt")
    def receipt(incident_id: str = Path(pattern=ID_PATTERN)):
        d = svc.receipt(incident_id)
        return d if d is not None else _err(404, "NOT_FOUND", "no receipt for this incident")

    @app.post("/api/incidents/{incident_id}/receipt/verify")
    def receipt_verify(incident_id: str = Path(pattern=ID_PATTERN)):
        d = svc.verify_receipt_for(incident_id)
        return d if d is not None else _err(404, "NOT_FOUND", "no receipt for this incident")

    @app.get("/api/stream")
    async def stream(after: int = Query(-1, ge=-1), once: bool = False):
        """Server-sent events, event name chain_entry. `after` is the last seq the client has; `once` ends after the backlog."""
        async def gen():
            last = after
            idle = 0
            while True:
                batch = await asyncio.to_thread(svc.stream_entries, last, 200)
                for e in batch:
                    last = e["seq"]
                    yield f"id: {e['seq']}\nevent: chain_entry\ndata: {json.dumps(e, separators=(',', ':'))}\n\n"
                if once:
                    return
                idle = 0 if batch else idle + 1
                if idle and idle % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ pages
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return html(render.dashboard_html(svc))

    @app.get("/dashboard/incidents/{incident_id}", response_class=HTMLResponse)
    def incident_page(incident_id: str = Path(pattern=ID_PATTERN)):
        return html(render.incident_html(svc, incident_id))

    @app.post("/dashboard/incidents/{incident_id}/verify", response_class=HTMLResponse)
    def incident_verify(incident_id: str = Path(pattern=ID_PATTERN)):
        return html(render.incident_html(svc, incident_id, svc.verify_receipt_for(incident_id)))

    @app.get("/proof", response_class=HTMLResponse)
    def proof_page():
        return html(render.proof_html(svc))

    @app.get("/status", response_class=HTMLResponse)
    def status_page():
        return html(render.status_html(svc))

    return app


app = create_app()
