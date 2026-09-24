"""Start at login (M5 step 3): the window starts hidden in the tray when the
player signs in, so the app is passive in practice.

The operating system is the source of truth, not ``config.json``: on Windows
a value under ``HKCU\\...\\CurrentVersion\\Run``, on Linux an XDG autostart
``.desktop`` file. Both start the GUI entry point with ``--background``.
Only a real launcher can be registered — the bundle's ``PreviouslyOn.exe``,
or the ``previously-on-app`` script of an installed environment — never
``python -m``, which would open a console on every sign-in.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

BACKGROUND_FLAG = "--background"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PreviouslyOn"
DESKTOP_NAME = "previously-on.desktop"


def launcher() -> list[str] | None:
    """The command sign-in should run, or None when this install has no
    launcher that starts without a console."""
    if getattr(sys, "frozen", False):
        return [sys.executable, BACKGROUND_FLAG]
    bindir = Path(sys.executable).parent
    script = bindir / ("previously-on-app.exe" if sys.platform == "win32" else "previously-on-app")
    if script.is_file():
        return [str(script), BACKGROUND_FLAG]
    return None


class _Registry:
    """``HKCU\\...\\Run``. ``winreg`` is a parameter so tests can fake it."""

    def __init__(self, winreg=None) -> None:
        if winreg is None:
            import winreg
        self.w = winreg

    def get(self) -> str | None:
        try:
            with self.w.OpenKey(self.w.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = self.w.QueryValueEx(key, VALUE_NAME)
        except OSError:
            return None
        return str(value)

    @staticmethod
    def render(command: list[str]) -> str:
        return subprocess.list2cmdline(command)

    def set(self, command: list[str]) -> None:
        with self.w.CreateKey(self.w.HKEY_CURRENT_USER, RUN_KEY) as key:
            self.w.SetValueEx(key, VALUE_NAME, 0, self.w.REG_SZ, self.render(command))

    def delete(self) -> None:
        try:
            with self.w.OpenKey(self.w.HKEY_CURRENT_USER, RUN_KEY, 0, self.w.KEY_SET_VALUE) as key:
                self.w.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass


class _DesktopFile:
    """``$XDG_CONFIG_HOME/autostart/previously-on.desktop``."""

    def __init__(self, directory: Path | None = None) -> None:
        if directory is None:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            directory = Path(base) / "autostart"
        self.path = directory / DESKTOP_NAME

    def get(self) -> str | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return next((line[5:] for line in text.splitlines() if line.startswith("Exec=")), "")

    @staticmethod
    def render(command: list[str]) -> str:
        return shlex.join(command)

    def set(self, command: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Previously On\n"
            "Comment=Passive session memory for long single-player games\n"
            f"Exec={self.render(command)}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


_DETECT = object()


class Autostart:
    """``store`` and ``command`` are injectable for the tests; by default the
    platform's store (None elsewhere) and this install's launcher."""

    def __init__(self, store=_DETECT, command=_DETECT) -> None:
        if store is _DETECT:
            if sys.platform == "win32":
                store = _Registry()
            elif sys.platform.startswith("linux"):
                store = _DesktopFile()
            else:
                store = None
        self.store = store
        self.command: list[str] | None = launcher() if command is _DETECT else command

    @property
    def supported(self) -> bool:
        return self.store is not None and self.command is not None

    def enabled(self) -> bool:
        return self.store is not None and self.store.get() is not None

    def set(self, on: bool) -> None:
        if not self.supported:
            raise RuntimeError("starting at login is not available for this install")
        if on:
            self.store.set(self.command)
        else:
            self.store.delete()

    def refresh(self) -> bool:
        """An entry that points at another launcher (the bundle's folder was
        moved or replaced by a newer version) is rewritten to this one.
        True when it was."""
        if not self.supported:
            return False
        current = self.store.get()
        if current is None or current == self.store.render(self.command):
            return False
        self.store.set(self.command)
        return True

    def to_dict(self) -> dict:
        return {"supported": self.supported, "enabled": self.enabled()}
