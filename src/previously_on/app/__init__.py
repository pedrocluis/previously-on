"""The desktop shell (M4): a pywebview window over ``app/ui`` with the
capture loop running in the same process, so a tester starts one thing.

``previously-on app`` from the CLI, or ``previously-on-app`` — the console-less
entry point for Windows, where stderr goes to ``<data dir>/app.log``.
"""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from ..capture import open_source
from ..games import get_profile
from ..session import default_data_dir
from .api import Api
from .config import AppConfig, default_config_path
from .watcher import Watcher

WINDOW_TITLE = "Previously On"
RECAP_GRACE = 180.0  # seconds to let a recap in flight finish after the window closes


def ui_path() -> Path:
    return Path(str(files("previously_on.app") / "ui" / "index.html"))


def _log_to_file(data_dir: Path | None) -> None:
    """Under pythonw there is no console; keep the detector's lines somewhere
    a tester can send."""
    directory = data_dir or default_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fh = (directory / "app.log").open("a", encoding="utf-8", buffering=1)
    sys.stderr = fh
    if sys.stdout is None:
        sys.stdout = fh


def run_app(
    game: str = "eldenring",
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
) -> int:
    import webview

    if sys.stderr is None:
        _log_to_file(data_dir)
    profile = get_profile(game)
    config_path = config_path or default_config_path()
    config = AppConfig.load(config_path)
    config.apply_env()

    watcher: Watcher | None = None
    if watch:
        live = source in ("screen", "dxcam", "mss")
        mon = monitor or config.monitor
        if live:
            watcher = Watcher(profile, data_dir, monitor=mon)
        else:
            # Replay: drive the window from a recording, once (no game here).
            watcher = Watcher(
                profile,
                data_dir,
                source_factory=lambda: open_source(source, path, fps=fps, seek=start, duration=duration),
                wait_for_game=False,
                low_priority=False,
                ocr_threads=-1,
            )
        if config.watch_on_start or not live:
            watcher.start()

    api = Api(profile, data_dir, watcher, config, config_path)
    window = webview.create_window(
        WINDOW_TITLE, url=str(ui_path()), js_api=api, width=1040, height=760, min_size=(720, 480)
    )

    def closing() -> bool:
        if watcher is not None and watcher.status().get("state") == "capturing":
            return bool(
                window.create_confirmation_dialog(
                    WINDOW_TITLE, f"{profile.display_name} is still being watched. Stop capturing and close?"
                )
            )
        return True

    window.events.closing += closing
    webview.start(debug=debug, http_server=True)

    if watcher is not None:
        watcher.stop()
        # The detector closes the log on the next frame; a recap in flight is
        # worth waiting for so nothing needs a manual re-run next time.
        watcher.join(RECAP_GRACE)
    return 0


def main() -> int:
    """``previously-on-app``: the GUI entry point, no arguments."""
    return run_app()
