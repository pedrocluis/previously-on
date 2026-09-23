"""The capture loop as a background thread: wait for the game, capture a
session, write the recap, wait again. This is what lets a tester start the
app and forget about it. Everything game-specific still comes from the
profile; everything network-bound goes through ``summarize_after_run``.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..capture import FrameSource, open_source
from ..events import Event
from ..game_process import is_running as _is_running
from ..game_process import lower_priority
from ..games import GameProfile
from ..pipeline import Detector
from ..recap.schema import RecapRecord
from ..recap.store import session_id, summarize_after_run
from ..session import SessionLog

State = str  # idle | waiting | capturing | summarizing | error

POLL = 2.0  # seconds between process checks
RECENT = 50  # events kept for the live feed


@dataclass(slots=True)
class WatcherStatus:
    state: State = "idle"
    message: str = ""
    session: str | None = None  # stamp of the session being captured / just captured
    started: str | None = None
    events: int = 0
    ocr_calls: int = 0
    frames: int = 0
    last_event: dict | None = None
    recap_ready: bool = False  # the last capture ended with a record written

    def to_dict(self) -> dict:
        return asdict(self)


def event_to_dict(ev: Event) -> dict:
    return {"t_rel": round(ev.t_rel, 1), "type": ev.type.value, "text": ev.text, "conf": round(ev.conf, 2)}


Summarizer = Callable[[Path, GameProfile], tuple[RecapRecord | None, str]]


class Watcher:
    """``start()`` runs the loop in a daemon thread; ``stop()`` asks it to
    finish the current step (the detector closes the log, a recap in flight
    completes) and ``join()`` waits for that.

    ``source_factory`` opens the frame source for a capture; the default is
    the live screen. With ``wait_for_game=False`` the loop captures once and
    stops — replay mode, used to drive the UI from a recording on a machine
    without the game."""

    def __init__(
        self,
        profile: GameProfile,
        data_dir: Path | None,
        *,
        monitor: int = 1,
        source_factory: Callable[[], FrameSource] | None = None,
        wait_for_game: bool = True,
        is_running: Callable[[], bool] | None = None,
        summarize: Summarizer = summarize_after_run,
        ocr_threads: int = 2,
        low_priority: bool = True,
        get_ocr: Callable[[int], object] | None = None,
    ) -> None:
        self.profile = profile
        self.data_dir = data_dir
        self.source_factory = source_factory or (lambda: open_source("screen", monitor=monitor))
        self.wait_for_game = wait_for_game
        self.is_running = is_running or (lambda: _is_running(profile))
        self.summarize = summarize
        self.ocr_threads = ocr_threads
        self.low_priority = low_priority
        self._get_ocr = get_ocr
        self._ocr = None
        self._status = WatcherStatus()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector: Detector | None = None
        self.recent: deque[dict] = deque(maxlen=RECENT)

    # --- control -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="watcher", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self) -> dict:
        with self._lock:
            d = self._status.to_dict()
            if self._detector is not None and d["state"] == "capturing":
                d["ocr_calls"] = self._detector.stats.ocr_calls
                d["frames"] = self._detector.stats.frames
        d["running"] = self.running
        return d

    def recent_events(self) -> list[dict]:
        return list(self.recent)

    # --- the loop ------------------------------------------------------------

    def _set(self, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(self._status, k, v)

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                if self.wait_for_game:
                    self._set(state="waiting", message=f"Waiting for {self.profile.display_name}…")
                    if not self._wait(running=True):
                        break
                self._capture_one()
                if not self.wait_for_game:
                    break
        except Exception as exc:  # noqa: BLE001 - the UI shows it; the log on disk is safe
            print(f"watcher stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._set(state="error", message=f"{type(exc).__name__}: {exc}")
            return
        self._set(state="idle")  # the message keeps the last outcome

    def _wait(self, running: bool) -> bool:
        """Block until the game's state matches; False if stopped meanwhile."""
        while not self._stop.is_set():
            if self.is_running() == running:
                return True
            self._stop.wait(POLL)
        return False

    def _ocr_engine(self):
        if self._ocr is None:
            self._set(message="Loading OCR models…")
            if self._get_ocr is not None:
                self._ocr = self._get_ocr(self.ocr_threads)
            else:
                from ..ocr import get_ocr

                self._ocr = get_ocr(self.ocr_threads)
        return self._ocr

    def _capture_one(self) -> None:
        ocr = self._ocr_engine()
        if self.wait_for_game and self.low_priority:
            lower_priority()
        source = self.source_factory()
        log = SessionLog.open(self.profile.id, source.name, data_dir=self.data_dir)
        print(f"session log: {log.path}", file=sys.stderr)
        self.recent.clear()
        self._set(
            state="capturing",
            message=f"Capturing via {source.name}",
            session=session_id(log.path),
            started=datetime.now().isoformat(timespec="seconds"),
            events=0,
            ocr_calls=0,
            frames=0,
            last_event=None,
            recap_ready=False,
        )
        game_gone = threading.Event()
        if self.wait_for_game:
            threading.Thread(target=self._watch_exit, args=(game_gone,), daemon=True).start()
        detector = Detector(
            source,
            self.profile,
            ocr,
            log,
            on_event=self._record,
            should_stop=lambda: self._stop.is_set() or game_gone.is_set(),
        )
        self._detector = detector
        try:
            stats = detector.run()
        finally:
            self._detector = None
            game_gone.set()  # releases the exit poller
        print(
            f"done: {stats.frames} frames, {stats.ocr_calls} OCR calls, {stats.events} events → {log.path}",
            file=sys.stderr,
        )
        self._set(state="summarizing", message="Writing the recap…", ocr_calls=stats.ocr_calls, frames=stats.frames)
        record, message = self.summarize(log.path, self.profile)
        print(message, file=sys.stderr)
        self._set(message=message, recap_ready=record is not None)

    def _watch_exit(self, game_gone: threading.Event) -> None:
        while not self._stop.is_set() and not game_gone.is_set():
            if not self.is_running():
                game_gone.set()
                return
            game_gone.wait(POLL)

    def _record(self, ev: Event) -> None:
        Detector._print_event(ev)
        d = event_to_dict(ev)
        self.recent.append(d)
        with self._lock:
            self._status.events += 1
            self._status.last_event = d
