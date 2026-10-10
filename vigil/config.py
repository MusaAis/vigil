"""Runtime configuration read from the environment. Variable names are listed in .env.example; values never live in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_MAX_STEPS = 8
DEFAULT_LLM_BASE_URL = "https://litellm.vision.aivar.app/v1"
MODES = ("live", "replay", "offline")


def load_env_file(path: str = ".env", environ: Optional[dict] = None) -> int:
    """Load KEY=VALUE lines from a .env file into the environment without overriding values already set.

    Blank values are skipped, '#' starts a comment (inline comments need a space before the '#'), and one pair of
    surrounding quotes is removed. Returns the number of variables set. A missing file is not an error.
    """
    target = os.environ if environ is None else environ
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return 0
    n = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if value[:1] in ("'", '"') and value.count(value[0]) >= 2:
            value = value[1:value.index(value[0], 1)]
        else:
            value = value.split(" #", 1)[0].strip()
        if key and value and key not in target:
            target[key] = value
            n += 1
    return n


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
        if env is None:
            load_env_file()
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
