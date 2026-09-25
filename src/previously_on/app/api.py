"""The object the page talks to (``window.pywebview.api``). Every public
method returns something JSON-serialisable and reports failure as
``{"error": ...}`` so the page handles one shape. No webview import here —
this is what the tests drive.

The window knows every game profile. The screens show one game at a time:
the one being captured when a capture starts, otherwise the one the player
picked (``select_game``), otherwise the one played last.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from .. import card as card_mod
from .. import export as export_mod
from ..games import GameProfile
from ..recap.store import sessions_dir, summarize_after_run
from ..session import default_data_dir
from . import views
from .account import Account, AccountError
from .autostart import Autostart
from .config import AppConfig, mask_key
from .sync import SyncWorker
from .watcher import Watcher

SITE = "https://previouslyon.gg"


class Api:
    def __init__(
        self,
        profiles: GameProfile | Sequence[GameProfile],
        data_dir: Path | None,
        watcher: Watcher | None,
        config: AppConfig,
        config_path: Path | None = None,
        *,
        game: str | None = None,
        autostart: Autostart | None = None,
        save_dialog: Callable[[str, str], str | None] | None = None,
        account: Account | None = None,
        sync: SyncWorker | None = None,
    ) -> None:
        self._profiles = {p.id: p for p in ((profiles,) if isinstance(profiles, GameProfile) else profiles)}
        if not self._profiles:
            raise ValueError("the app needs at least one game profile")
        if game is not None and game not in self._profiles:
            raise KeyError(f"unknown game {game!r}")
        self._selected = game
        self._followed: str | None = None  # the capture the screens last switched to
        self._data_dir = data_dir
        self._watcher = watcher
        self._config = config
        self._config_path = config_path
        self._summarize_lock = threading.Lock()
        self._summarizing: dict = {"state": "idle", "session": None, "message": ""}
        self._autostart = autostart
        self.tray = False  # set by run_app once the tray icon is up
        # Asks where to save a file (suggested name, file-type filter such as
        # "PNG image (*.png)" → path, or None if cancelled). Without one
        # (tests, no window) files go to the data dir.
        self._save_dialog = save_dialog
        # Sign-in and sync; None where there is no account (tests, --no-sync).
        self._account = account
        self._sync = sync

    # --- which game --------------------------------------------------------

    def _profile(self) -> GameProfile:
        """The game the screens show. A capture that starts brings them to
        its game once; the player can switch away and it sticks."""
        if self._watcher is not None:
            w = self._watcher.status()
            if w.get("game") and w.get("session") and w["session"] != self._followed:
                self._followed = w["session"]
                self._selected = w["game"]
        game = self._selected or views.last_played(self._profiles.values(), self._data_dir)
        return self._profiles.get(game or "", next(iter(self._profiles.values())))

    def games(self) -> dict:
        return self._guard(
            lambda: {"games": views.games(self._profiles.values(), self._data_dir), "current": self._profile().id}
        )

    def select_game(self, game: str) -> dict:
        if game not in self._profiles:
            return {"error": f"unknown game {game}"}
        self._selected = game
        return {"current": game}

    # --- screens -------------------------------------------------------------

    def home(self) -> dict:
        def load():
            p = self._profile()
            out = views.home(p.id, self._data_dir)
            out["game"] = p.display_name
            if out["empty"] and not any(g["sessions"] for g in views.games(self._profiles.values(), self._data_dir)):
                # Nothing logged for any game: the welcome screen.
                out["first_run"] = {
                    "games": [q.display_name for q in self._profiles.values()],
                    "has_key": self._has_key(),
                    "tray": self.tray,
                    "autostart": self._autostart_state(),
                }
            return out

        return self._guard(load)

    def sessions(self) -> dict:
        return self._guard(lambda: {"sessions": views.sessions(self._profile().id, self._data_dir)})

    def session(self, stamp: str) -> dict:
        def load():
            out = views.session(self._profile().id, self._data_dir, stamp)
            return out if out is not None else {"error": f"no session {stamp}"}

        return self._guard(load)

    def timeline(self) -> dict:
        def load():
            game = self._profile().id
            return {"totals": views.totals(game, self._data_dir), "sessions": views.timeline(game, self._data_dir)}

        return self._guard(load)

    def totals(self) -> dict:
        return self._guard(lambda: views.totals(self._profile().id, self._data_dir))

    def search(self, query: str, kinds: list[str] | None = None) -> dict:
        return self._guard(lambda: {"hits": views.search(self._profile().id, self._data_dir, query, kinds)})

    # --- share card -------------------------------------------------------------

    def card(self) -> dict:
        """The share card as a PNG data URL, for the page to show and copy."""

        def load():
            p = self._profile()
            play = card_mod.gather(p.id, self._data_dir)
            if not play.sessions:
                return {"error": "nothing logged yet: the card needs at least one session"}
            data = base64.b64encode(card_mod.png(play, p.display_name)).decode("ascii")
            return {
                "png": f"data:image/png;base64,{data}",
                "filename": card_mod.filename(p.id),
                "line": card_mod.line(play),
            }

        return self._guard(load)

    def save_card(self) -> dict:
        """Ask where to save the card and write it there."""

        def save():
            p = self._profile()
            play = card_mod.gather(p.id, self._data_dir)
            if not play.sessions:
                return {"error": "nothing logged yet: the card needs at least one session"}
            path = self._ask_save(card_mod.filename(p.id), "PNG image (*.png)", "cards")
            if path is None:
                return {"cancelled": True}
            if path.suffix.lower() != ".png":
                path = path.with_name(path.name + ".png")
            path.write_bytes(card_mod.png(play, p.display_name))
            return {"saved": str(path)}

        return self._guard(save)

    # --- export ------------------------------------------------------------------

    def export_session(self, stamp: str) -> dict:
        """Ask where to save one session's log + recap as a zip for an issue."""

        def save():
            game = self._profile().id
            log = export_mod.find_session(game, stamp, self._data_dir)
            path = self._ask_save(export_mod.filename(game, stamp), "Zip archive (*.zip)", "exports")
            if path is None:
                return {"cancelled": True}
            return {"saved": str(export_mod.write(log, path)), "issue_url": export_mod.ISSUE_URL}

        return self._guard(save)

    def open_url(self, url: str) -> dict:
        """Open a link in the player's browser (the window itself never navigates away)."""
        if not url.startswith(("https://github.com/pedrocluis/previously-on", f"{SITE}/")):
            return {"error": "only the project's own pages open from here"}
        import webbrowser

        return {"opened": webbrowser.open(url)}

    def _ask_save(self, name: str, file_type: str, fallback_dir: str) -> Path | None:
        if self._save_dialog is not None:
            chosen = self._save_dialog(name, file_type)
            return Path(chosen) if chosen else None
        path = (self._data_dir or default_data_dir()) / fallback_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # --- capture ---------------------------------------------------------------

    def status(self) -> dict:
        out = self._watcher.status() if self._watcher else {"state": "idle", "running": False, "message": ""}
        captured = self._profiles.get(out.get("game") or "")
        out["game_id"] = captured.id if captured else None
        out["game"] = captured.display_name if captured else None  # the game being / last captured
        out["watching"] = self._watcher.waiting_for() if self._watcher else None
        out["view"] = self._profile().id  # the game the screens show
        out["summarize"] = dict(self._summarizing)
        out["sync"] = self._sync.status() if self._sync and self._account and self._account.token() else None
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
        profile = self._profile()
        log = sessions_dir(profile.id, self._data_dir) / f"{stamp}.jsonl"
        if not log.is_file():
            return {"error": f"no session {stamp}"}
        if not self._summarize_lock.acquire(blocking=False):
            return {"error": "a recap is already being written"}
        self._summarizing = {"state": "running", "session": stamp, "message": "Writing the recap…"}

        def work() -> None:
            try:
                record, message = summarize_after_run(log, profile)
                self._summarizing = {"state": "done" if record else "failed", "session": stamp, "message": message}
            finally:
                self._summarize_lock.release()
            if self._sync is not None:
                self._sync.enqueue(profile.id)

        threading.Thread(target=work, name="summarize", daemon=True).start()
        return {"started": True}

    # --- account and sync ----------------------------------------------------------

    def account_status(self) -> dict:
        if self._account is None:
            return {"available": False}

        def load():
            return {
                "available": True,
                **self._account.status(),
                "sync": self._sync.status() if self._sync else None,
                "sync_games": list(self._config.sync_games),
                "games": [{"id": p.id, "name": p.display_name} for p in self._profiles.values()],
                "account_url": f"{SITE}/account",
            }

        return self._guard(load)

    def sign_in(self) -> dict:
        if self._account is None:
            return {"error": "sign-in is not available in this window"}
        try:
            return self._account.begin_link()
        except AccountError as e:
            return {"error": str(e)}

    def cancel_sign_in(self) -> dict:
        if self._account is not None:
            self._account.cancel_link()
        return {"ok": True}

    def sign_out(self) -> dict:
        if self._account is not None:
            self._account.sign_out()
        return {"ok": True}

    def set_sync_game(self, game: str, on: bool) -> dict:
        if game not in self._profiles:
            return {"error": f"unknown game {game!r}"}
        games = [g for g in self._config.sync_games if g != game] + ([game] if on else [])
        config = self._config.model_copy(update={"sync_games": sorted(games)})
        try:
            config.save(self._config_path)
        except OSError as exc:
            return {"error": f"could not write settings: {exc}"}
        self._config = config
        if on and self._sync is not None:
            self._sync.enqueue(game)
        return self.account_status()

    def sync_now(self) -> dict:
        if self._sync is not None:
            self._sync.enqueue_all()
        return {"ok": True}

    # --- settings --------------------------------------------------------------

    def _has_key(self) -> bool:
        """A key for the model recaps will use."""
        c = self._config
        if _default_model().startswith("claude"):
            return bool(c.anthropic_api_key.strip() or os.environ.get("ANTHROPIC_API_KEY"))
        return bool(c.openai_api_key.strip() or os.environ.get("OPENAI_API_KEY"))

    def _autostart_state(self) -> dict:
        if self._autostart is None:
            return {"supported": False, "enabled": False}
        try:
            return self._autostart.to_dict()
        except OSError:
            return {"supported": False, "enabled": False}

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
            "start_at_login": self._autostart_state(),
            "tray": self.tray,
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
        if changes.get("start_at_login") is not None:
            if self._autostart is None or not self._autostart.supported:
                return {"error": "starting at sign-in is not available for this install"}
            try:
                self._autostart.set(bool(changes["start_at_login"]))
            except OSError as exc:
                return {"error": f"could not change the sign-in start: {exc}"}
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
