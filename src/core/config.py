from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


def load_env(env_path: str | None = None) -> None:
    load_dotenv(dotenv_path=env_path, override=False)


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key_env: str

    @property
    def api_key(self) -> str:
        key = os.getenv(self.api_key_env, "")
        if not key:
            raise ValueError(f"Missing API key in env var: {self.api_key_env}")
        return key
