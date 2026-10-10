"""Live model adapter for an OpenAI-compatible endpoint (the event LiteLLM gateway).

The client is injectable so tests run without a network or key. The real client is created lazily from the
`openai` package with base_url and api_key taken from Config.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .config import Config
from .models import Proposal, Turn
from .prompt import SYSTEM_PROMPT, tool_specs

RATIONALE_MAX = 300


class LiveModel:
    def __init__(self, config: Config, client: Any = None, max_tokens: int = 600) -> None:
        self.config, self.max_tokens = config, max_tokens
        if client is None:
            if not config.llm_api_key:
                raise RuntimeError("LLM_API_KEY (or LITELLM_API_KEY) is not set")
            from openai import OpenAI  # imported lazily so offline runs need no SDK
            client = OpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)
        self.client = client
        self._tools = tool_specs()

    def build_messages(self, incident: dict, turns: list, step: int) -> list[dict]:
        msgs: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"incident": incident, "step": step}, sort_keys=True)},
        ]
        for i, t in enumerate(turns):
            p = t.proposal
            name = "skip" if p.kind == "skip" else (p.tool or "none")
            call_id = f"call_{i + 1}"
            args = dict(p.args) if isinstance(p.args, dict) else {}
            args["rationale"] = p.rationale
            msgs.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args, sort_keys=True, default=str)}}]})
            msgs.append({"role": "tool", "tool_call_id": call_id,
                         "content": json.dumps(t.feedback, sort_keys=True, default=str)})
        return msgs

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        resp = self.client.chat.completions.create(
            model=self.config.llm_model, messages=self.build_messages(incident, turns, step),
            tools=self._tools, tool_choice="auto", temperature=0, max_tokens=self.max_tokens)
        usage = getattr(resp, "usage", None)
        tin = int(getattr(usage, "prompt_tokens", 0) or 0)
        tout = int(getattr(usage, "completion_tokens", 0) or 0)
        msg = resp.choices[0].message
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            return Proposal(kind="none", rationale=(getattr(msg, "content", "") or "")[:RATIONALE_MAX],
                            tokens_in=tin, tokens_out=tout)
        fn = calls[0].function
        try:
            args: Any = json.loads(fn.arguments or "{}")
        except (TypeError, ValueError):
            return Proposal(kind="tool", tool=fn.name, args=None, rationale="unparseable arguments",
                            tokens_in=tin, tokens_out=tout)
        rationale = ""
        if isinstance(args, dict):
            r = args.pop("rationale", "")
            rationale = r[:RATIONALE_MAX] if isinstance(r, str) else ""
        if fn.name == "skip":
            return Proposal(kind="skip", rationale=rationale, tokens_in=tin, tokens_out=tout)
        return Proposal(kind="tool", tool=fn.name, args=args, rationale=rationale, tokens_in=tin, tokens_out=tout)
