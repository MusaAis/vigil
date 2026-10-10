"""Two real calls to the team LiteLLM gateway: a plain completion, then a tool-calling proposal for a sample incident.
Prints replies and token usage; never prints the key.

Usage: python scripts/live_smoke.py [model]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from vigil.config import Config  # noqa: E402

cfg = Config.from_env()
if not cfg.llm_api_key:
    print("ERROR: LLM_API_KEY is not set (put it in .env or the shell)")
    sys.exit(2)
from openai import OpenAI  # noqa: E402

model = sys.argv[1] if len(sys.argv) > 1 else cfg.llm_model
client = OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)
try:
    resp = client.chat.completions.create(model=model, max_tokens=30,
                                          messages=[{"role": "user", "content": "Reply with the single word: ready"}])
except Exception as exc:
    print(f"FAILED model={model} base_url={cfg.llm_base_url}: {type(exc).__name__}: {str(exc)[:300]}")
    sys.exit(1)
u = resp.usage
print(f"OK model={model} reply={resp.choices[0].message.content!r} "
      f"tokens_in={getattr(u, 'prompt_tokens', '?')} tokens_out={getattr(u, 'completion_tokens', '?')}")

from vigil.config import Config as _Config  # noqa: E402
from vigil.llm import LiveModel  # noqa: E402

sample = {"incident_id": "inc_0001", "type": "duplicate_charge", "related": ["ch_0001", "ch_0002"]}
try:
    p = LiveModel(_Config(llm_base_url=cfg.llm_base_url, llm_model=model, llm_api_key=cfg.llm_api_key)).propose(sample, [], 1)
except Exception as exc:
    print(f"TOOL-CALL FAILED model={model}: {type(exc).__name__}: {str(exc)[:300]}")
    sys.exit(1)
print(f"TOOL-CALL kind={p.kind} tool={p.tool} args={p.args} rationale={p.rationale!r} "
      f"tokens_in={p.tokens_in} tokens_out={p.tokens_out}")
sys.exit(0 if p.kind == "tool" and p.tool else 1)
