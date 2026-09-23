"""Normalized screen regions.

Coordinates are fractions of the full frame so a profile works at any
resolution with the same aspect ratio. Game profiles own the actual numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Region:
    name: str
    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        for v in (self.x, self.y, self.w, self.h):
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{self.name}: coordinates must be in [0, 1], got {v}")
        if self.x + self.w > 1.0 + 1e-9 or self.y + self.h > 1.0 + 1e-9:
            raise ValueError(f"{self.name}: region extends past the frame")

    def pixel_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) in pixels for a frame of the given size."""
        x0 = int(round(self.x * width))
        y0 = int(round(self.y * height))
        x1 = int(round((self.x + self.w) * width))
        y1 = int(round((self.y + self.h) * height))
        return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def crop(frame: np.ndarray, region: Region) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = region.pixel_box(w, h)
    return frame[y0:y1, x0:x1]
