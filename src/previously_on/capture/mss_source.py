"""Live monitor capture via mss (Windows / X11)."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Iterator

import numpy as np

from . import Frame


def list_monitors() -> list[tuple[int, dict]]:
    """(index, geometry) for each physical monitor; index 0 (the virtual whole) is skipped."""
    import mss

    with mss.mss() as sct:
        return list(enumerate(sct.monitors))[1:]


class MssSource:
    name = "mss"

    def __init__(self, fps: float = 2.0, monitor: int = 1) -> None:
        import mss  # lazy: not needed for replay sources

        self._sct = mss.mss()
        monitors = self._sct.monitors
        if monitor >= len(monitors):
            raise ValueError(f"monitor {monitor} not found; available: 1..{len(monitors) - 1}")
        self._monitor = monitors[monitor]
        self.width = int(self._monitor["width"])
        self.height = int(self._monitor["height"])
        self._interval = 1.0 / fps

    def frames(self) -> Iterator[Frame]:
        start = time.monotonic()
        index = 0
        next_at = start
        while True:
            now = time.monotonic()
            if now < next_at:
                time.sleep(next_at - now)
            shot = self._sct.grab(self._monitor)
            # mss returns BGRA; drop alpha so downstream sees BGR like OpenCV.
            image = np.asarray(shot)[:, :, :3].copy()
            yield Frame(index=index, ts=datetime.now(), t_rel=time.monotonic() - start, image=image)
            index += 1
            next_at += self._interval

    def close(self) -> None:
        self._sct.close()
