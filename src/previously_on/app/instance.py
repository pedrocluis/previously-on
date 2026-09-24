"""One watching window per user. With start-at-login and a tray icon the app
is often already running, hidden, when the player double-clicks it; a second
copy would capture the same game into a second log. So the first copy
listens on a localhost port (written to ``instance.port`` in the config dir)
and a later one, instead of starting, asks it to show its window and exits.

The first copy greets every connection with ``GREETING`` so a stale port
file that now belongs to some other program is not mistaken for it.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from typing import Callable

GREETING = b"previously-on\n"
SHOW = b"show\n"
PORT_FILE = "instance.port"
TIMEOUT = 1.0


def signal_running(directory: Path) -> bool:
    """Ask a running copy to show its window. True if one answered."""
    try:
        port = int((directory / PORT_FILE).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as conn:
            if conn.recv(len(GREETING)) != GREETING:
                return False
            conn.sendall(SHOW)
    except OSError:
        return False
    return True


class InstanceServer:
    """Accepts ``show`` requests from later copies and calls ``on_show``."""

    def __init__(self, directory: Path, on_show: Callable[[], None]) -> None:
        self.on_show = on_show
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        directory.mkdir(parents=True, exist_ok=True)
        self._file = directory / PORT_FILE
        self._file.write_text(str(self.port), encoding="ascii")
        self._closed = threading.Event()
        threading.Thread(target=self._serve, name="instance", daemon=True).start()

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return  # closed
            with conn:
                try:
                    conn.settimeout(TIMEOUT)
                    conn.sendall(GREETING)
                    if conn.recv(len(SHOW)) != SHOW:
                        continue
                except OSError:
                    continue
            try:
                self.on_show()
            except Exception as exc:  # noqa: BLE001 - keep serving
                print(f"could not show the window: {type(exc).__name__}: {exc}", file=sys.stderr)

    def close(self) -> None:
        self._closed.set()
        self._sock.close()
        try:
            if self._file.read_text(encoding="ascii").strip() == str(self.port):
                self._file.unlink()
        except OSError:
            pass
