"""Runtime configuration read from the environment. Variable names are listed in .env.example; values never live in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_MAX_STEPS = 8
DEFAULT_LLM_BASE_URL = "https://litellm.vision.aivar.app/v1"
MODES = ("live", "replay", "offline")


@dataclass(frozen=True)
class Config:
    mode: str = "offline"
    max_steps: int = DEFAULT_MAX_STEPS
    db_path: str = "data/vigil.db"
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = "claude-haiku"
    llm_api_key: Optional[str] = field(default=None, repr=False)
    daily_live_budget_tokens: int = 200_000

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "Config":
        e = os.environ if env is None else env
        mode = e.get("VIGIL_MODE", "offline")
        if mode not in MODES:
            raise ValueError(f"VIGIL_MODE must be one of {MODES}, got {mode!r}")
        return cls(
            mode=mode,
            max_steps=int(e.get("VIGIL_MAX_STEPS", DEFAULT_MAX_STEPS)),
            db_path=e.get("VIGIL_DB_PATH", "data/vigil.db"),
            llm_base_url=e.get("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL,
            llm_model=e.get("LLM_MODEL") or "claude-haiku",
            llm_api_key=e.get("LLM_API_KEY") or e.get("LITELLM_API_KEY") or None,
            daily_live_budget_tokens=int(e.get("DAILY_LIVE_BUDGET_TOKENS", 200_000)),
        )
