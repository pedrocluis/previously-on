"""Per-region change detection.

This is the cost-control layer: nearly every frame is discarded here for
free. A region is OCR'd only when it has changed, then stopped changing
(banners fade in over a few frames), and it looks like it contains text.

The diff is computed on a *bright-pixel mask*, not on raw pixels: the game
world keeps moving underneath a banner, but HUD text is bright and static.
Diffing the mask makes "settled" mean "the text stopped changing" rather
than "the camera stopped moving", which would never happen mid-fight.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

from .regions import Region


class State(Enum):
    IDLE = "idle"  # nothing happening
    CHANGING = "changing"  # saw a change, waiting for it to settle
    ARMED = "armed"  # fired for the current content; wait for the next change


@dataclass(slots=True)
class WatchResult:
    changed: bool
    settled: bool
    fired: bool
    diff: float


def text_mask(crop: np.ndarray, bright: int = 170, sat_value: int = 60, sat: int = 160) -> np.ndarray:
    """Boolean mask of pixels that look like HUD text.

    HUD text is either bright (white subtitles, gold banners) or strongly
    saturated even when dim: the red "YOU DIED" measures V≈75-110,
    S≈190-215 on a darkened screen. The game world is mostly neither.
    """
    if crop.ndim == 2:
        return crop > bright
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return (v > bright) | ((v > sat_value) & (s > sat))


def has_text_like_content(crop: np.ndarray, lo: float = 0.002, hi: float = 0.70) -> bool:
    """Cheap gate before OCR.

    Rejects both empty regions (nothing text-like) and regions that are almost
    entirely bright (sky, snow, a menu backdrop), which OCR would waste time on.
    """
    mask = text_mask(crop)
    frac = float(np.count_nonzero(mask)) / mask.size
    return lo <= frac <= hi


class RegionWatcher:
    def __init__(
        self,
        region: Region,
        change_threshold: float = 0.003,
        settle_threshold: float = 0.001,
        settle_frames: int = 1,
        max_wait: int = 2,
        thumb_width: int = 64,
    ) -> None:
        self.region = region
        self.change_threshold = change_threshold
        self.settle_threshold = settle_threshold
        self.settle_frames = settle_frames
        self.max_wait = max_wait
        self.thumb_width = thumb_width
        self.state = State.IDLE
        self._prev: np.ndarray | None = None  # last frame, for "settled"
        self._ref: np.ndarray | None = None  # content at the last settle, for "changed"
        self._stable = 0
        self._waiting = 0

    def _thumb(self, crop: np.ndarray) -> np.ndarray:
        """Downscaled text mask in [0, 1] (fractional after area resize)."""
        mask = text_mask(crop).astype(np.float32)
        h, w = mask.shape
        th = max(1, int(round(h * self.thumb_width / max(w, 1))))
        return cv2.resize(mask, (self.thumb_width, th), interpolation=cv2.INTER_AREA)

    def update(self, crop: np.ndarray) -> WatchResult:
        """Feed one crop. ``fired`` is True exactly once per settled change.

        "Changed" compares against the content at the last settle, not just
        the previous frame, so a banner that fades in over a second still
        registers even though no single frame-to-frame step is large.
        "Settled" is frame-to-frame. A change that has not settled after
        ``max_wait`` frames fires anyway: short banners ("YOU DIED" lasts
        ~2 s) fade the whole time they are on screen and never settle at
        2 fps. ``diff`` is the fraction of the region whose text mask differs
        from the reference: a banner appearing moves it by ~0.3-3 %, a
        static scene by ~0.
        """
        thumb = self._thumb(crop)
        if self._prev is None or self._ref is None:
            self._prev = self._ref = thumb
            return WatchResult(changed=False, settled=False, fired=False, diff=0.0)

        step = float(np.mean(np.abs(thumb - self._prev)))
        diff = float(np.mean(np.abs(thumb - self._ref)))
        self._prev = thumb
        changed = diff > self.change_threshold
        settled = step < self.settle_threshold
        fired = False

        if self.state is not State.CHANGING:
            if changed:
                self.state = State.CHANGING
                self._stable = 0
                self._waiting = 0
        else:
            self._waiting += 1
            self._stable = self._stable + 1 if settled else 0
            if self._stable >= self.settle_frames or self._waiting >= self.max_wait:
                fired = True
                self.state = State.ARMED
                self._ref = thumb

        return WatchResult(changed=changed, settled=settled, fired=fired, diff=diff)
