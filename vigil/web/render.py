"""Server-rendered HTML pages (no JavaScript needed). Jinja2 with autoescape: every value from the chain is escaped."""
from __future__ import annotations

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .service import VigilService
from .settings import ROOT

_ENV = Environment(loader=FileSystemLoader(os.path.join(ROOT, "web", "templates")),
                   autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


def money(minor: Optional[int], currency: str = "NGN") -> str:
    """Integer minor units -> '25,000.00 NGN'. Integer arithmetic only."""
    if minor is None:
        return "n/a"
    sign, m = ("-", -minor) if minor < 0 else ("", minor)
    return f"{sign}{m // 100:,}.{m % 100:02d} {currency}"


def pct(n: Optional[int]) -> str:
    return "n/a" if n is None else f"{n}%"


def short(h: Optional[str], n: int = 14) -> str:
    return "n/a" if not h else (h if len(h) <= n + 7 else h[: 7 + n] + "…")


def ratio(n: Optional[int], d: Optional[int]) -> int:
    """Integer percent of n in d, clamped to 0..100 (bar widths). Integer arithmetic only."""
    return 0 if not d or n is None else max(0, min(100, n * 100 // d))


def ts(s: Optional[str]) -> str:
    """2026-10-10T08:01:00Z -> 2026-10-10 08:01Z"""
    return "n/a" if not s else s[:16].replace("T", " ") + "Z"


_ENV.filters.update(money=money, pct=pct, short=short, ratio=ratio, ts=ts)


def render(name: str, **ctx) -> str:
    ctx.setdefault("active", "")
    return _ENV.get_template(name).render(**ctx)


def home_html(svc: VigilService) -> str:
    proof = svc.proof()["data"]
    return render("home.html", active="home", chain=svc.chain_status(), strip=svc.chain_strip(), runs=proof["eval"]["runs"],
                  commands=proof["verify"]["commands"], limits=proof["limits"]["items"], repo_url=svc.s.repo_url)


def dashboard_html(svc: VigilService) -> str:
    inc = svc.incidents()["data"]
    m = {x["name"]: x for x in svc.metrics()["data"]}
    ch = svc.chain_status()
    after = (ch["head_seq"] if ch["head_seq"] is not None else -1) - 20
    return render("dashboard.html", active="dashboard", repo_url=svc.s.repo_url, incidents=inc, metrics=m, exposure=svc.exposure(), chain=ch,
                  recent=svc.stream_entries(after_seq=max(after, -1), limit=50))


def incident_html(svc: VigilService, incident_id: str, verify_result: Optional[dict] = None) -> Optional[str]:
    d = svc.incident(incident_id)
    if d is None:
        return None
    import json
    receipt_json = json.dumps(d["receipt"], indent=2, sort_keys=True, ensure_ascii=False) if d["receipt"] else None
    return render("incident.html", active="dashboard", repo_url=svc.s.repo_url, d=d, receipt_json=receipt_json, verify=verify_result,
                  currency=svc.exposure()["currency"])


def proof_html(svc: VigilService) -> str:
    return render("proof.html", active="proof", p=svc.proof(), repo_url=svc.s.repo_url)


def status_html(svc: VigilService) -> str:
    return render("status.html", active="status", repo_url=svc.s.repo_url, h=svc.health())
