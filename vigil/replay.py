"""Record and replay of model responses (SPEC 2.5, 12.5).

Cache key = SHA-256 of canonical JSON of {model, system, messages, tools, temperature}. A missing entry in replay mode is
a hard error (REPLAY_MISS): replay never calls the network. Cache files hold the model's proposal and its token counts,
never request text, keys or headers.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from .canonical import sha256_json
from .config import Config
from .llm import LiveModel
from .models import Proposal

TEMPERATURE = 0  # integer on purpose: floats are not allowed in hashed objects


class ReplayMiss(RuntimeError):
    """REPLAY_MISS: no recorded response for this request."""


class _NoClient:
    """Stands in for the API client in replay mode. Any call is a bug."""

    def __getattr__(self, name: str) -> Any:
        raise ReplayMiss("REPLAY_MISS: replay mode must never call the API")


def request_key(model: str, messages: list, tools: list) -> str:
    return sha256_json({"model": model, "system": messages[0]["content"], "messages": messages[1:],
                        "tools": tools, "temperature": TEMPERATURE})


def _path(cache_dir: str, key: str) -> str:
    return os.path.join(cache_dir, key.split(":", 1)[1] + ".json")


def _to_dict(p: Proposal) -> dict:
    return {"kind": p.kind, "tool": p.tool, "args": p.args, "rationale": p.rationale,
            "tokens_in": p.tokens_in, "tokens_out": p.tokens_out}


def _from_dict(d: dict) -> Proposal:
    return Proposal(kind=d["kind"], tool=d["tool"], args=d["args"], rationale=d["rationale"],
                    tokens_in=d["tokens_in"], tokens_out=d["tokens_out"])


class RecordingModel:
    """Calls the live model and stores each response in the cache."""

    def __init__(self, live: LiveModel, cache_dir: str) -> None:
        self.live, self.cache_dir = live, cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        key = request_key(self.live.config.llm_model, self.live.build_messages(incident, turns, step), self.live._tools)
        p = self.live.propose(incident, turns, step)
        with open(_path(self.cache_dir, key), "w", encoding="utf-8") as f:
            json.dump({"key": key, "model": self.live.config.llm_model, "proposal": _to_dict(p)}, f,
                      sort_keys=True, indent=1)
            f.write("\n")
        return p


class ReplayModel:
    """Serves recorded responses. Builds the exact request the live model would send, then looks it up."""

    def __init__(self, model: str, cache_dir: str, config: Optional[Config] = None) -> None:
        self.model, self.cache_dir = model, cache_dir
        self._shape = LiveModel(config or Config(llm_model=model), client=_NoClient())

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        key = request_key(self.model, self._shape.build_messages(incident, turns, step), self._shape._tools)
        path = _path(self.cache_dir, key)
        if not os.path.exists(path):
            raise ReplayMiss(f"REPLAY_MISS: no recorded response for request {key}")
        with open(path, encoding="utf-8") as f:
            return _from_dict(json.load(f)["proposal"])


class FixtureModel:
    """Forces one proposal at step 1 (scenario X3: a hallucinated action), then defers to the real model."""

    def __init__(self, inner: Any, fixture: dict) -> None:
        self.inner, self.fixture = inner, fixture

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        if step != 1:
            return self.inner.propose(incident, turns, step)
        iid = incident["incident_id"]
        args = json.loads(json.dumps(self.fixture["args"]).replace("{incident_id}", iid))
        return Proposal(kind="tool", tool=self.fixture["tool"], args=args,
                        rationale=self.fixture.get("rationale", "forced proposal (scenario fixture)"))


class BudgetExceeded(RuntimeError):
    pass


class BudgetModel:
    """Stops live runs once the token budget is used (DAILY_LIVE_BUDGET_TOKENS)."""

    def __init__(self, inner: Any, limit_tokens: int) -> None:
        self.inner, self.limit, self.used = inner, limit_tokens, 0

    def propose(self, incident: dict, turns: list, step: int) -> Proposal:
        if self.used >= self.limit:
            raise BudgetExceeded(f"token budget {self.limit} used up")
        p = self.inner.propose(incident, turns, step)
        self.used += p.tokens_in + p.tokens_out
        return p
