"""The object the page talks to (``window.pywebview.api``). Every public
method returns something JSON-serialisable and reports failure as
``{"error": ...}`` so the page handles one shape. No webview import here —
this is what the tests drive.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from ..games import GameProfile
from ..recap.store import sessions_dir, summarize_after_run
from ..session import default_data_dir
from . import views
from .config import AppConfig, mask_key
from .watcher import Watcher


class Api:
    def __init__(
        self,
        profile: GameProfile,
        data_dir: Path | None,
        watcher: Watcher | None,
        config: AppConfig,
        config_path: Path | None = None,
    ) -> None:
        self._profile = profile
        self._data_dir = data_dir
        self._watcher = watcher
        self._config = config
        self._config_path = config_path
        self._summarize_lock = threading.Lock()
        self._summarizing: dict = {"state": "idle", "session": None, "message": ""}

    # --- screens -------------------------------------------------------------

    def home(self) -> dict:
        try:
            out = views.home(self._profile.id, self._data_dir)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        out["game"] = self._profile.display_name
        return out

    def sessions(self) -> dict:
        return self._guard(lambda: {"sessions": views.sessions(self._profile.id, self._data_dir)})

    def session(self, stamp: str) -> dict:
        def load():
            out = views.session(self._profile.id, self._data_dir, stamp)
            return out if out is not None else {"error": f"no session {stamp}"}

        return self._guard(load)

    def timeline(self) -> dict:
        return self._guard(
            lambda: {
                "totals": views.totals(self._profile.id, self._data_dir),
                "sessions": views.timeline(self._profile.id, self._data_dir),
            }
        )

    def totals(self) -> dict:
        return self._guard(lambda: views.totals(self._profile.id, self._data_dir))

    def search(self, query: str, kinds: list[str] | None = None) -> dict:
        return self._guard(lambda: {"hits": views.search(self._profile.id, self._data_dir, query, kinds)})

    # --- capture ---------------------------------------------------------------

    def status(self) -> dict:
        out = self._watcher.status() if self._watcher else {"state": "idle", "running": False, "message": ""}
        out["game"] = self._profile.display_name
        out["summarize"] = dict(self._summarizing)
        return out

    def recent_events(self) -> dict:
        return {"events": self._watcher.recent_events() if self._watcher else []}

    def start_watch(self) -> dict:
        if self._watcher is None:
            return {"error": "capture is disabled in this window (--no-watch)"}
        return {"started": self._watcher.start()}

    def stop_watch(self) -> dict:
        if self._watcher is None:
            return {"error": "capture is disabled in this window (--no-watch)"}
        self._watcher.stop()
        return {"stopped": True}

    def summarize(self, stamp: str) -> dict:
        """Backfill the recap for one session in the background; ``status``
        reports progress under ``summarize``."""
        log = sessions_dir(self._profile.id, self._data_dir) / f"{stamp}.jsonl"
        if not log.is_file():
            return {"error": f"no session {stamp}"}
        if not self._summarize_lock.acquire(blocking=False):
            return {"error": "a recap is already being written"}
        self._summarizing = {"state": "running", "session": stamp, "message": "Writing the recap…"}

        def work() -> None:
            try:
                record, message = summarize_after_run(log, self._profile)
                self._summarizing = {"state": "done" if record else "failed", "session": stamp, "message": message}
            finally:
                self._summarize_lock.release()

        threading.Thread(target=work, name="summarize", daemon=True).start()
        return {"started": True}

    # --- settings --------------------------------------------------------------

    def get_settings(self) -> dict:
        c = self._config
        return {
            "openai_api_key": mask_key(c.openai_api_key),
            "has_openai_key": bool(c.openai_api_key.strip() or os.environ.get("OPENAI_API_KEY")),
            "anthropic_api_key": mask_key(c.anthropic_api_key),
            "has_anthropic_key": bool(c.anthropic_api_key.strip() or os.environ.get("ANTHROPIC_API_KEY")),
            "model": c.model,
            "default_model": _default_model(),
            "monitor": c.monitor,
            "watch_on_start": c.watch_on_start,
            "data_dir": str(self._data_dir or default_data_dir()),
            "config_path": str(self._config_path) if self._config_path else None,
            "env_overrides": [v for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(v)],
        }

    def save_settings(self, changes: dict) -> dict:
        """``changes`` holds only the fields to change; a key field that is
        missing or empty keeps the stored key, ``clear_<field>: true`` removes it."""
        data = self._config.model_dump()
        for key in ("openai_api_key", "anthropic_api_key"):
            if changes.get(f"clear_{key}"):
                data[key] = ""
            elif changes.get(key):
                data[key] = str(changes[key]).strip()
        for key in ("model", "monitor", "watch_on_start"):
            if key in changes and changes[key] is not None:
                data[key] = changes[key]
        try:
            config = AppConfig.model_validate(data)
        except ValueError as exc:
            return {"error": _validation_message(exc)}
        try:
            path = config.save(self._config_path)
        except OSError as exc:
            return {"error": f"could not write settings: {exc}"}
        self._config = config
        config.apply_env()
        return {"saved": str(path), **self.get_settings()}

    def open_data_dir(self) -> dict:
        directory = self._data_dir or default_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(directory)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError as exc:
            return {"error": str(exc)}
        return {"opened": str(directory)}

    # --- helpers ---------------------------------------------------------------

    @staticmethod
    def _guard(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - shown on the page, never crashes the window
            return {"error": f"{type(exc).__name__}: {exc}"}


def _default_model() -> str:
    from ..recap.provider import default_model

    return default_model()


def _validation_message(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return "; ".join(f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors())
        except Exception:  # noqa: BLE001
            pass
    return str(exc)
