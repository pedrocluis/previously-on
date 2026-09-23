"""The app's settings file: API keys, model, capture options.

Lives under the platform user-config dir as JSON. Environment variables win
over the file — a variable that was set when the process started is never
touched, so a developer's shell setup keeps working — while a key pasted into
the Settings screen reaches ``make_provider`` (which reads the environment)
on the next recap without a restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import platformdirs
from pydantic import BaseModel, Field

from ..recap.provider import MODEL_ENV
from ..session import APP_NAME

CONFIG_NAME = "config.json"

# Which config fields feed which variables.
ENV_FIELDS = {
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "model": MODEL_ENV,
}

# The variables the process was started with; those are never overridden.
_STARTUP_ENV = frozenset(v for v in ENV_FIELDS.values() if os.environ.get(v))


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME)) / CONFIG_NAME


class AppConfig(BaseModel):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    model: str = ""  # empty = the provider default
    monitor: int = Field(default=1, ge=1)
    watch_on_start: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        """Defaults when the file is missing or unreadable — the app must open."""
        path = path or default_config_path()
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=1), encoding="utf-8")
        try:
            path.chmod(0o600)  # it holds API keys
        except OSError:
            pass
        return path

    def apply_env(self, startup: frozenset[str] = _STARTUP_ENV) -> None:
        """Push the file's values into the environment, except for variables
        that were already set when the process started. A value cleared in the
        settings clears the variable we set earlier."""
        for field_name, var in ENV_FIELDS.items():
            if var in startup:
                continue
            value = getattr(self, field_name).strip()
            if value:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)


def mask_key(key: str) -> str:
    """``sk-…abcd`` — enough to recognise a key, never enough to use it."""
    key = key.strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:3]}…{key[-4:]}"
