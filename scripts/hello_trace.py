"""T-01: send one small trace to neatlogs. No LLM key needed.

Run:  NEATLOGS_API_KEY=... python scripts/hello_trace.py
Uses the PROJECT API key (Settings > API keys, the top one). NOT the nlw_ HTTP ingest key.
"""
import os
import sys

import neatlogs

key = os.environ.get("NEATLOGS_API_KEY")
if not key:
    sys.exit("NEATLOGS_API_KEY is not set (export it in this shell; never commit it).")

neatlogs.init(api_key=key, workflow_name="vigil-hello")


def current_trace_id():
    """Read the active trace id via the documented W3C traceparent injection (SDK docs: Cross-process propagation)."""
    headers = {}
    if neatlogs.inject_trace_context(headers):
        parts = headers.get("traceparent", "").split("-")
        if len(parts) == 4 and len(parts[1]) == 32:
            return parts[1]
    return None


@neatlogs.span(kind="TOOL", tool_name="get_provider_charge")
def get_provider_charge(charge_id: str) -> dict:
    return {"ok": True, "data": {"charge_id": charge_id, "status": "succeeded", "source": "SIMULATED"}}


@neatlogs.span(kind="AGENT", name="vigil_hello_agent")
def agent(incident_id: str) -> dict:
    return get_provider_charge("ch_0001")


@neatlogs.span(kind="WORKFLOW", name="incident")
def incident(incident_id: str) -> dict:
    print("neatlogs trace id (compare with the dashboard):", current_trace_id())
    return agent(incident_id)


print(incident("inc_0001"))
neatlogs.flush()
neatlogs.shutdown()
print("flushed. Open Traces in app.neatlogs.com, workflow 'vigil-hello'.")
