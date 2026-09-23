"""Live capture via DXGI Desktop Duplication (Windows), through ``dxcam``.

GDI capture (``mss``) returns black frames once a DirectX game enters
exclusive fullscreen; desktop duplication — what OBS's display capture uses —
sees the real output regardless of display mode.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Iterator

import numpy as np

from . import Frame


def list_outputs() -> list[str]:
    import dxcam

    return [line for line in str(dxcam.output_info()).splitlines() if line.strip()]


class DxcamSource:
    name = "dxcam"

    def __init__(self, fps: float = 2.0, monitor: int = 1) -> None:
        import dxcam  # lazy: Windows-only

        # ``monitor`` follows mss's 1-based numbering; dxcam outputs are 0-based.
        self._camera = dxcam.create(output_idx=max(monitor - 1, 0), output_color="BGR")
        if self._camera is None:
            raise RuntimeError(f"dxcam could not open monitor {monitor}")
        self.width, self.height = self._camera.width, self._camera.height
        self._interval = 1.0 / fps
        self._last: np.ndarray | None = None

    def _grab(self) -> np.ndarray | None:
        # grab() returns None when nothing on screen changed since the last
        # call; the previous frame is then still what is on screen.
        image = self._camera.grab()
        if image is not None:
            self._last = np.ascontiguousarray(image)
        return self._last

    def frames(self) -> Iterator[Frame]:
        start = time.monotonic()
        index = 0
        next_at = start
        while True:
            now = time.monotonic()
            if now < next_at:
                time.sleep(next_at - now)
            image = self._grab()
            if image is not None:
                yield Frame(index=index, ts=datetime.now(), t_rel=time.monotonic() - start, image=image)
                index += 1
            next_at += self._interval

    def close(self) -> None:
        try:
            self._camera.release()
        except Exception:
            pass
