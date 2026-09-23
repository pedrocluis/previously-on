"""Replay a recorded gameplay video, sampled down to the target fps."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import cv2

from . import Frame


class VideoSource:
    name = "video"

    def __init__(self, path: str | Path, fps: float = 2.0, start: datetime | None = None) -> None:
        self.path = Path(path)
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise FileNotFoundError(f"could not open video: {self.path}")
        self._interval = 1.0 / fps
        self._start = start or datetime.now()

    def frames(self) -> Iterator[Frame]:
        index = 0
        next_at = 0.0
        while True:
            ok = self._cap.grab()
            if not ok:
                return
            t = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t + 1e-6 < next_at:
                continue
            ok, image = self._cap.retrieve()
            if not ok:
                return
            yield Frame(index=index, ts=self._start + timedelta(seconds=t), t_rel=t, image=image)
            index += 1
            next_at += self._interval

    def close(self) -> None:
        self._cap.release()
