"""The desktop shell (M4): a pywebview window over ``app/ui`` with the
capture loop running in the same process, so a tester starts one thing.

``previously-on app`` from the CLI, or ``previously-on-app`` — the console-less
entry point for Windows, where stderr goes to ``<data dir>/app.log``.
With a tray icon, closing the window hides it and capture goes on; a start
at sign-in (``--background``) opens straight into the tray. One copy watches
at a time: a second start shows the first one's window instead, and
``--quit`` closes it (the installer's way to free the files it replaces).
"""

from __future__ import annotations

import sys
import threading
from importlib.resources import files
from pathlib import Path

from ..capture import open_source
from ..games import get_profile, list_profiles
from ..recap.store import summarize_after_run
from ..session import default_data_dir
from .account import Account
from .api import Api
from .autostart import BACKGROUND_FLAG, Autostart
from .config import AppConfig, default_config_path
from .instance import InstanceServer, signal_quit, signal_running
from .sync import SyncWorker
from .watcher import Watcher

WINDOW_TITLE = "Previously On"
RECAP_GRACE = 180.0  # seconds to let a recap in flight finish after the window closes
QUIT_FLAG = "--quit"


def ui_path() -> Path:
    return Path(str(files("previously_on.app") / "ui" / "index.html"))


def _log_to_file(data_dir: Path | None) -> None:
    """The window has no console; keep the detector's lines somewhere a
    player can find and attach to an issue."""
    import platform
    from datetime import datetime

    from .. import __version__

    directory = data_dir or default_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fh = (directory / "app.log").open("a", encoding="utf-8", buffering=1)
    sys.stderr = fh
    if sys.stdout is None:
        sys.stdout = fh
    frozen = " (bundle)" if getattr(sys, "frozen", False) else ""
    print(
        f"--- {datetime.now():%Y-%m-%d %H:%M:%S} previously-on {__version__}{frozen} · {platform.platform()}",
        file=fh,
    )


def _session_ending() -> bool:
    """Windows is signing out or shutting down. pywebview's closing event
    does not carry the close reason, and a window that cancels this close
    ("hide to the tray") holds up the shutdown."""
    if sys.platform != "win32":
        return False
    import ctypes

    SM_SHUTTINGDOWN = 0x2000
    return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))


def run_app(
    game: str | None = None,
    data_dir: Path | None = None,
    *,
    watch: bool = True,
    source: str = "screen",
    path: str | None = None,
    fps: float = 2.0,
    start: float = 0.0,
    duration: float | None = None,
    monitor: int | None = None,
    debug: bool = False,
    config_path: Path | None = None,
    background: bool = False,
    tray: bool = True,
) -> int:
    # Before importing webview: on Windows without a console its import
    # swaps a missing stderr for os.devnull, and the log would never open.
    if sys.stderr is None:
        _log_to_file(data_dir)

    # Live capture watches every game unless one is named; a replay has no
    # process to tell the game by, so it needs one (Elden Ring by default).
    profiles = list_profiles()
    config_path = config_path or default_config_path()
    live = source in ("screen", "dxcam", "mss")

    # Only a live watcher must be alone: two would log the same session twice.
    single = watch and live
    if single and signal_running(config_path.parent):
        print("already running: showed its window instead", file=sys.stderr)
        return 0

    import webview

    config = AppConfig.load(config_path)
    config.apply_env()
    autostart = Autostart()
    if getattr(sys, "frozen", False) and autostart.refresh():
        print("start at sign-in now points at this copy", file=sys.stderr)

    # Sign-in and sync. The api's config is the one Settings changes, so the
    # worker asks it for the synced games each time.
    account = Account()
    api: Api | None = None
    sync = SyncWorker(account, data_dir, lambda: api._config.sync_games if api else config.sync_games)
    account.on_signed_in = sync.enqueue_all

    def summarize_and_sync(log: Path, profile):
        """Upload a session when it ends, and again once its recap is written."""
        sync.enqueue(profile.id)
        try:
            return summarize_after_run(log, profile)
        finally:
            sync.enqueue(profile.id)

    watcher: Watcher | None = None
    if watch:
        mon = monitor or config.monitor
        if live:
            watcher = Watcher(
                [get_profile(game)] if game else profiles, data_dir, monitor=mon, summarize=summarize_and_sync
            )
        else:
            # Replay: drive the window from a recording, once (no game here).
            game = game or "eldenring"
            watcher = Watcher(
                get_profile(game),
                data_dir,
                source_factory=lambda: open_source(source, path, fps=fps, seek=start, duration=duration),
                wait_for_game=False,
                low_priority=False,
                ocr_threads=-1,
                summarize=summarize_and_sync,
            )
        if config.watch_on_start or not live:
            watcher.start()

    def save_dialog(filename: str, file_type: str) -> str | None:
        # ``window`` exists by the time the page can ask.
        chosen = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename, file_types=(file_type,))
        if isinstance(chosen, (list, tuple)):  # some backends return a sequence
            chosen = chosen[0] if chosen else None
        return chosen or None

    api = Api(
        profiles,
        data_dir,
        watcher,
        config,
        config_path,
        game=game,
        autostart=autostart,
        save_dialog=save_dialog,
        account=account,
        sync=sync,
    )
    sync.enqueue_all()  # catch up on whatever ended while the app was closed
    window = None
    quitting = threading.Event()

    def show() -> None:
        if window is not None:
            window.show()
            window.restore()

    def quit_app() -> None:
        quitting.set()
        if window is not None:
            window.destroy()

    def quit_requested() -> None:
        print("asked to quit by another copy", file=sys.stderr)
        quit_app()

    icon = None
    if tray:
        from .tray import start_tray

        icon = start_tray(watcher, show, quit_app)
    api.tray = icon is not None
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(ui_path()),
        js_api=api,
        width=1040,
        height=760,
        min_size=(720, 480),
        # Hidden only when the tray can bring it back.
        hidden=background and icon is not None,
    )
    server = InstanceServer(config_path.parent, show, quit_requested) if single else None

    def closing() -> bool:
        if quitting.is_set() or _session_ending():
            return True
        if icon is not None:
            # Keep watching from the tray. Hide off the GUI thread: this
            # handler runs on it and hide() waits for it on some backends.
            threading.Thread(target=window.hide, daemon=True).start()
            icon.hint_hidden()
            return False
        if watcher is not None and watcher.status().get("state") == "capturing" and watcher.profile:
            return bool(
                window.create_confirmation_dialog(
                    WINDOW_TITLE, f"{watcher.profile.display_name} is still being watched. Stop capturing and close?"
                )
            )
        return True

    window.events.closing += closing
    try:
        webview.start(debug=debug, http_server=True)
    finally:
        if server is not None:
            server.close()
        if icon is not None:
            icon.stop()

    if watcher is not None:
        watcher.stop()
        # The detector closes the log on the next frame; a recap in flight is
        # worth waiting for so nothing needs a manual re-run next time.
        watcher.join(RECAP_GRACE)
    return 0


def main() -> int:
    """``previously-on-app`` / ``PreviouslyOn.exe``: the GUI entry point. Its
    one argument is ``--background``, the sign-in start (tray only), or
    ``--quit``, which closes a running copy and exits 1 if it is still up
    after the recap grace. Always logs to ``app.log`` — whether stderr is
    missing depends on how the process was started, not on whether anyone
    sees it."""
    _log_to_file(None)
    if QUIT_FLAG in sys.argv[1:]:
        closed = signal_quit(default_config_path().parent, RECAP_GRACE + 30)
        print("quit: " + ("no copy running now" if closed else "the running copy did not exit"), file=sys.stderr)
        return 0 if closed else 1
    return run_app(background=BACKGROUND_FLAG in sys.argv[1:])
