"""The tray icon (M5 step 3): the app keeps watching with its window closed,
and a sign-in start (``--background``) opens straight into the tray.

pystray picks the platform backend: the Win32 one runs its own message loop
in a thread; the GTK and AppIndicator ones hook into the GTK loop pywebview
runs, which is why ``run_detached`` is called from the main thread before
``webview.start``. When no backend works (a Linux desktop without a tray),
``start_tray`` returns None and the window behaves as it did without one.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from .watcher import Watcher

TITLE = "Previously On"
REFRESH = 2.0  # seconds between status checks for the tooltip and menu

# The page's palette (ui/app.css), as sRGB.
INK = (17, 20, 14, 255)
RUST = (224, 124, 85, 255)
FAINT = (122, 124, 111, 255)
LICHEN = (180, 203, 142, 255)


def icon_image(state: str = "waiting", size: int = 64):
    """A rewind mark — two chevrons pointing back — on the page's ink.
    Rust while watching, grey when not, with a lichen dot while capturing."""
    from PIL import Image, ImageDraw

    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=INK)
    colour = FAINT if state in ("idle", "error") else RUST
    top, bottom, mid = s * 0.24, s * 0.76, s * 0.5
    for x in (s * 0.16, s * 0.46):
        d.polygon([(x, mid), (x + s * 0.34, top), (x + s * 0.34, bottom)], fill=colour)
    if state == "capturing":
        r = s * 0.15
        cx, cy = s * 0.80, s * 0.80
        d.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=INK)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LICHEN)
    return img


def status_line(status: dict, watching_for: str) -> str:
    """What the tooltip and the menu's first line say."""
    state = status.get("state")
    if state == "capturing":
        n = status.get("events", 0)
        return f"Capturing · {n} event{'s' if n != 1 else ''}"
    if state == "summarizing":
        return "Writing the recap…"
    if state == "waiting":
        return f"Waiting for {watching_for}"
    if state == "error":
        return "Stopped: " + (status.get("message") or "error")
    return "Watching" if status.get("running") else "Not watching"


class Tray:
    def __init__(
        self,
        watcher: Watcher | None,
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        import pystray

        self.watcher = watcher
        self._on_open = on_open
        self._on_quit = on_quit
        self._stop = threading.Event()
        self._shown_hint = False
        self._key: tuple | None = None
        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        entries = [
            item("Open Previously On", lambda: self._on_open(), default=True),
            sep,
            item(lambda _: self._status_text(), None, enabled=False),
        ]
        if watcher is not None:
            entries.append(item(lambda _: "Stop watching" if watcher.running else "Start watching", self._toggle))
        entries += [sep, item("Quit", lambda: self._on_quit())]
        self.icon = pystray.Icon("previously-on", icon_image(self._state()), TITLE, pystray.Menu(*entries))

    # --- state -------------------------------------------------------------

    def _status(self) -> dict:
        return self.watcher.status() if self.watcher else {"state": "idle", "running": False}

    def _state(self) -> str:
        s = self._status()
        if s.get("state") == "error":
            return "error"
        if not s.get("running"):
            return "idle"
        return s.get("state") or "waiting"

    def _status_text(self) -> str:
        if self.watcher is None:
            return "Not watching"
        s = self._status()
        text = status_line(s, self.watcher.waiting_for())
        if s.get("state") == "capturing" and self.watcher.profile is not None:
            text = f"{self.watcher.profile.display_name} · {text}"
        return text

    def _toggle(self) -> None:
        assert self.watcher is not None
        if self.watcher.running:
            self.watcher.stop()
        else:
            self.watcher.start()
        self.refresh(force=True)

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.icon.run_detached()
        self.icon.visible = True
        threading.Thread(target=self._refresh_loop, name="tray", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001 - shutting down anyway
            pass

    def refresh(self, force: bool = False) -> None:
        text, state = self._status_text(), self._state()
        if not force and (text, state) == self._key:
            return
        if state != (self._key or (None, None))[1]:
            self.icon.icon = icon_image(state)
        self._key = (text, state)
        self.icon.title = f"{TITLE} — {text}"
        self.icon.update_menu()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(REFRESH):
            try:
                self.refresh()
            except Exception as exc:  # noqa: BLE001 - a stale tooltip is not worth a crash
                print(f"tray: {type(exc).__name__}: {exc}", file=sys.stderr)

    def hint_hidden(self) -> None:
        """The first time the window is closed to the tray, say where it went."""
        if self._shown_hint:
            return
        self._shown_hint = True
        if getattr(self.icon, "HAS_NOTIFICATION", False):
            try:
                self.icon.notify("Still watching from the tray. Quit from the tray menu.", TITLE)
            except Exception:  # noqa: BLE001
                pass


def start_tray(watcher: Watcher | None, on_open: Callable[[], None], on_quit: Callable[[], None]) -> Tray | None:
    try:
        tray = Tray(watcher, on_open, on_quit)
        tray.start()
    except Exception as exc:  # noqa: BLE001 - no tray: the window closes as it used to
        print(f"no tray icon: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    return tray
