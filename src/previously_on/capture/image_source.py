"""Replay a folder of screenshots in sorted filename order.

Each image is treated as one frame ``1/fps`` seconds after the previous one.
Useful for fixtures and for hand-built scenario tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import cv2

from . import Frame

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class ImageDirSource:
    name = "images"

    def __init__(self, path: str | Path, fps: float = 2.0, start: datetime | None = None) -> None:
        self.path = Path(path)
        if not self.path.is_dir():
            raise NotADirectoryError(self.path)
        self.files = sorted(p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        self._interval = 1.0 / fps
        self._start = start or datetime.now()

    def frames(self) -> Iterator[Frame]:
        for index, file in enumerate(self.files):
            image = cv2.imread(str(file), cv2.IMREAD_COLOR)
            if image is None:
                continue
            t = index * self._interval
            yield Frame(index=index, ts=self._start + timedelta(seconds=t), t_rel=t, image=image)

    def close(self) -> None:
        pass
