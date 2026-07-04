"""Load .env and build application settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _float_env(env: dict, key: str, default: float) -> float:
    raw = env.get(key, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass
class Settings:
    download_dir: Path = Path("./downloads")
    request_timeout: float = 30.0
    rate_limit_delay: float = 1.0
    env: dict = field(default_factory=dict)   # raw environment for provider config checks


def load_settings() -> Settings:
    load_dotenv()
    env = dict(os.environ)
    return Settings(
        download_dir=Path(env.get("DOWNLOAD_DIR") or "./downloads"),
        request_timeout=_float_env(env, "REQUEST_TIMEOUT_SECONDS", 30.0),
        rate_limit_delay=_float_env(env, "RATE_LIMIT_DELAY_SECONDS", 1.0),
        env=env,
    )
