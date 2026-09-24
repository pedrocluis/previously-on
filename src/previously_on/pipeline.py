"""The detector loop: frames → regions → diff → OCR → classify → dedupe → log."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .capture import Frame, FrameSource
from .dedupe import Deduper, Verdict
from .diff import RegionWatcher, has_text_like_content
from .events import Event
from .games import GameProfile
from .ocr import Ocr, OcrLine
from .regions import Region, crop
from .session import SessionLog


@dataclass(slots=True)
class DetectorStats:
    frames: int = 0
    ocr_calls: int = 0
    events: int = 0
    suppressed: int = 0
    revised: int = 0  # suppressed repeats that replaced a worse read


def classify_image(image, profile: GameProfile, ocr: Ocr, only_region: str | None = None):
    """OCR + classify every region of a single still image.

    Bypasses the diff/settle logic; used by ``calibrate``, ``ocr`` and the
    regression tests, where each image is meant to be inspected on its own.
    """
    results: list[tuple[Region, list[OcrLine], list[tuple]]] = []
    for region in profile.regions:
        if only_region and region.name != only_region:
            continue
        lines = ocr.read(crop(image, region))
        results.append((region, lines, profile.classify(region, lines, image) if lines else []))
    return results


class Detector:
    def __init__(
        self,
        source: FrameSource,
        profile: GameProfile,
        ocr: Ocr,
        log: SessionLog,
        on_event: Callable[[Event], None] | None = None,
        on_revise: Callable[[Event], None] | None = None,
        verbose: bool = False,
        debug_dir: Path | None = None,
        debug_every: float = 30.0,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.source = source
        self.profile = profile
        self.ocr = ocr
        self.log = log
        self.on_event = on_event or self._print_event
        # Called with a logged event whose text was just replaced by a better read.
        self.on_revise = on_revise or self._print_revise
        # Checked once per frame; live sources never end on their own, so this
        # is how the game exiting (or the app closing) stops the loop from
        # another thread. Ctrl-C still works for the CLI.
        self.should_stop = should_stop or (lambda: False)
        self.verbose = verbose
        self.watchers = [RegionWatcher(r) for r in profile.regions]
        self.deduper = Deduper(profile.cooldowns, getattr(profile, "dedupe_by_type", None))
        self.stats = DetectorStats()
        self._quiet = dict(getattr(profile, "quiet_after_event", {}))
        self._quiet_until: dict[str, float] = {}
        self._first_t: float | None = None
        self._last_t = 0.0
        self.debug_dir = debug_dir
        self.debug_every = debug_every
        self._next_debug = 0.0
        self._black_since: float | None = None
        self._warned_black = False

    @staticmethod
    def _print_event(ev: Event) -> None:
        print(f"[{ev.t_rel:8.1f}s] {ev.type.value:22s} {ev.text}  ({ev.conf:.2f})", file=sys.stderr)

    @staticmethod
    def _print_revise(ev: Event) -> None:
        print(f"[{ev.t_rel:8.1f}s] {'  ↳ better read':22s} {ev.text}  ({ev.conf:.2f})", file=sys.stderr)

    def process(self, frame: Frame) -> list[Event]:
        self.stats.frames += 1
        if self._first_t is None:
            self._first_t = frame.t_rel
        self._last_t = frame.t_rel
        self._debug(frame)
        emitted: list[Event] = []
        for watcher in self.watchers:
            region = watcher.region
            region_crop = crop(frame.image, region)
            result = watcher.update(region_crop)
            if not result.fired:
                continue
            # Once a region has produced an event, its content is known for a
            # while (a boss bar stays up all fight): skip OCR until it is stale.
            if frame.t_rel < self._quiet_until.get(region.name, 0.0):
                continue
            if not has_text_like_content(region_crop):
                continue
            self.stats.ocr_calls += 1
            lines = self.ocr.read(region_crop)
            if self.verbose and lines:
                print(f"    ocr {region.name}: {[l.text for l in lines]}", file=sys.stderr)
            for typ, text, conf in self.profile.classify(region, lines, frame.image):
                event = Event(
                    ts=frame.ts,
                    t_rel=frame.t_rel,
                    type=typ,
                    text=text,
                    conf=conf,
                    region=region.name,
                    raw=[l.text for l in lines],
                    frame_index=frame.index,
                )
                self._quiet_until[region.name] = frame.t_rel + self._quiet.get(region.name, 0.0)
                verdict, kept = self.deduper.offer(event)
                if verdict is Verdict.UPGRADE and kept is not None:
                    # A better read of something already logged: keep its
                    # time, take the new text.
                    kept.text, kept.conf, kept.raw = event.text, event.conf, event.raw
                    self.log.revise(kept)
                    self.stats.revised += 1
                    self.on_revise(kept)
                if verdict is not Verdict.NEW:
                    self.stats.suppressed += 1
                    continue
                self.log.append(event)
                self.stats.events += 1
                self.on_event(event)
                emitted.append(event)
        return emitted

    def _debug(self, frame: Frame) -> None:
        """Save a small copy of the frame periodically and warn when the
        capture is black — the symptom of an exclusive-fullscreen game that
        GDI capture cannot see (switch the game to borderless windowed)."""
        mean = float(frame.image[::8, ::8].mean())
        if mean < 4.0:
            if self._black_since is None:
                self._black_since = frame.t_rel
            elif frame.t_rel - self._black_since > 20.0 and not self._warned_black:
                self._warned_black = True
                print(
                    "warning: captured frames have been black for 20 s. If the game is running, "
                    "the capture backend cannot see it (GDI/mss cannot capture exclusive fullscreen; "
                    "use the default dxcam backend on Windows) or --monitor is wrong.",
                    file=sys.stderr,
                )
        else:
            self._black_since = None
            self._warned_black = False
        if self.debug_dir is not None and frame.t_rel >= self._next_debug:
            self._next_debug = frame.t_rel + self.debug_every
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            h, w = frame.image.shape[:2]
            small = cv2.resize(frame.image, (1280, int(1280 * h / w))) if w > 1280 else frame.image
            cv2.imwrite(str(self.debug_dir / f"{frame.t_rel:08.1f}s.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 80])

    def run(self) -> DetectorStats:
        try:
            for frame in self.source.frames():
                if self.should_stop():
                    break
                self.process(frame)
        except KeyboardInterrupt:
            print("\nstopping…", file=sys.stderr)
        finally:
            self.source.close()
            self.log.close(played=self._last_t - (self._first_t or 0.0))
        return self.stats
