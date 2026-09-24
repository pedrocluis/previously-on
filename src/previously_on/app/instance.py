"""One watching window per user. With start-at-login and a tray icon the app
is often already running, hidden, when the player double-clicks it; a second
copy would capture the same game into a second log. So the first copy
listens on a localhost port (written to ``instance.port`` in the config dir)
and a later one, instead of starting, asks it to show its window and exits.

The first copy greets every connection with ``GREETING`` so a stale port
file that now belongs to some other program is not mistaken for it.

The installer uses the same channel to close a running copy before it
replaces or removes its files (``PreviouslyOn.exe --quit``): the copy
answers with its process id, quits as the tray's Quit does (the session log
gets its end, a recap in flight its grace), and the caller waits for that
process to be gone — its DLLs stay locked until then.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable

import psutil

GREETING = b"previously-on\n"
SHOW = b"show\n"
QUIT = b"quit\n"
PORT_FILE = "instance.port"
TIMEOUT = 1.0


def _send(directory: Path, command: bytes) -> bytes | None:
    """Send one command to a running copy; its reply (possibly empty), or
    None when no copy of this program answered."""
    try:
        port = int((directory / PORT_FILE).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as conn:
            if conn.recv(len(GREETING)) != GREETING:
                return None
            conn.sendall(command)
            reply = b""
            while chunk := conn.recv(64):
                reply += chunk
    except OSError:
        return None
    return reply


def signal_running(directory: Path) -> bool:
    """Ask a running copy to show its window. True if one answered."""
    return _send(directory, SHOW) is not None


def signal_quit(directory: Path, timeout: float) -> bool:
    """Ask a running copy to quit and wait until its process has exited.
    True when none is running any more (or none was); False when it is still
    up after ``timeout`` seconds."""
    reply = _send(directory, QUIT)
    if reply is None:
        return True
    try:
        proc = psutil.Process(int(reply.strip()))
    except (ValueError, psutil.NoSuchProcess):
        return True
    try:
        proc.wait(timeout)
    except psutil.TimeoutExpired:
        return False
    except psutil.NoSuchProcess:
        pass
    return True


class InstanceServer:
    """Accepts ``show`` and ``quit`` requests from later copies and calls
    ``on_show`` or ``on_quit``."""

    def __init__(
        self, directory: Path, on_show: Callable[[], None], on_quit: Callable[[], None] | None = None
    ) -> None:
        self.on_show = on_show
        self.on_quit = on_quit
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
                    command = conn.recv(max(len(SHOW), len(QUIT)))
                    if command == QUIT and self.on_quit is not None:
                        conn.sendall(f"{os.getpid()}\n".encode("ascii"))
                        action = self.on_quit
                    elif command == SHOW:
                        action = self.on_show
                    else:
                        continue
                except OSError:
                    continue
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - keep serving
                print(f"could not {command.decode().strip()}: {type(exc).__name__}: {exc}", file=sys.stderr)

    def close(self) -> None:
        self._closed.set()
        self._sock.close()
        try:
            if self._file.read_text(encoding="ascii").strip() == str(self.port):
                self._file.unlink()
        except OSError:
            pass
