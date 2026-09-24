"""Append-only JSONL session logs.

Layout: ``<data_dir>/sessions/<game>/<YYYYMMDD-HHMMSS>.jsonl``. The first line
is ``session_start``, then one ``event`` per line, then ``session_end``. Every
write is flushed so a crash mid-session loses nothing already seen.

A ``revise`` line replaces the text of an event logged earlier (by its
position among the events) with a better read of the same banner; the log
stays append-only and ``read_session`` applies it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

import platformdirs

from .events import Event

APP_NAME = "previously-on"


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME))


@dataclass(slots=True)
class SessionMeta:
    game: str
    source: str
    started: datetime
    ended: datetime | None = None
    played: float | None = None  # seconds of game time covered (video position for replays)

    @property
    def duration(self) -> float:
        if self.played is not None:
            return self.played
        end = self.ended or datetime.now()
        return (end - self.started).total_seconds()


class SessionLog:
    def __init__(self, path: Path, fh: IO[str], meta: SessionMeta) -> None:
        self.path = path
        self._fh = fh
        self.meta = meta
        self.count = 0

    @classmethod
    def open(cls, game: str, source: str, data_dir: Path | None = None, started: datetime | None = None) -> SessionLog:
        started = started or datetime.now()
        directory = (data_dir or default_data_dir()) / "sessions" / game
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{started:%Y%m%d-%H%M%S}.jsonl"
        fh = path.open("a", encoding="utf-8")
        meta = SessionMeta(game=game, source=source, started=started)
        log = cls(path, fh, meta)
        log._write(
            {
                "kind": "session_start",
                "game": game,
                "source": source,
                "started": started.isoformat(timespec="milliseconds"),
            }
        )
        return log

    def _write(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fh.flush()

    def append(self, event: Event) -> None:
        event.index = self.count
        self._fh.write(event.to_json() + "\n")
        self._fh.flush()
        self.count += 1

    def revise(self, event: Event) -> None:
        """Record ``event``'s current text, conf and raw lines as the better
        read of the event already logged at ``event.index``."""
        if not 0 <= event.index < self.count:
            raise ValueError(f"event {event.index} is not in this log")
        self._write(
            {
                "kind": "revise",
                "index": event.index,
                "text": event.text,
                "conf": round(event.conf, 3),
                "raw": event.raw,
            }
        )

    def close(self, ended: datetime | None = None, played: float | None = None) -> None:
        """``played`` is the session length in seconds of game time; for a
        replay that is the video position, not the wall clock."""
        if self._fh.closed:
            return
        ended = ended or datetime.now()
        self.meta.ended = ended
        self.meta.played = played
        end: dict = {"kind": "session_end", "ended": ended.isoformat(timespec="milliseconds"), "events": self.count}
        if played is not None:
            end["played"] = round(played, 3)
        self._write(end)
        self._fh.close()

    def __enter__(self) -> SessionLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_session(path: str | Path) -> tuple[SessionMeta, list[Event]]:
    meta: SessionMeta | None = None
    events: list[Event] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            kind = obj.get("kind")
            if kind == "session_start":
                meta = SessionMeta(
                    game=obj["game"], source=obj.get("source", ""), started=datetime.fromisoformat(obj["started"])
                )
            elif kind == "session_end" and meta is not None:
                meta.ended = datetime.fromisoformat(obj["ended"])
                if "played" in obj:
                    meta.played = float(obj["played"])
            elif kind == "event":
                event = Event.from_dict(obj)
                event.index = len(events)
                events.append(event)
            elif kind == "revise" and 0 <= obj.get("index", -1) < len(events):
                event = events[obj["index"]]
                event.text = obj["text"]
                event.conf = float(obj.get("conf", event.conf))
                event.raw = list(obj.get("raw", event.raw))
    if meta is None:
        raise ValueError(f"{path}: missing session_start line")
    return meta, events
