"""Append-only JSONL session logs.

Layout: ``<data_dir>/sessions/<game>/<YYYYMMDD-HHMMSS>.jsonl``. The first line
is ``session_start``, then one ``event`` per line, then ``session_end``. Every
write is flushed so a crash mid-session loses nothing already seen.

A ``revise`` line replaces the text of an event logged earlier (by its
position among the events) with a better read of the same banner; the log
stays append-only and ``read_session`` applies it.

A log belongs to one playthrough of its game (a character, or a New Game+
cycle of one): ``session_start`` names it, and a ``playthrough`` line after
``session_end`` moves a finished log to another one — the last such line
wins. A log that names none belongs to the default playthrough, so every
log written before playthroughs existed reads as it did. See
``playthroughs.py`` for the list of them.
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
DEFAULT_PLAYTHROUGH = "main"


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME))


def sessions_dir(game: str, data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "sessions" / game


@dataclass(slots=True)
class SessionMeta:
    game: str
    source: str
    started: datetime
    ended: datetime | None = None
    played: float | None = None  # seconds of game time covered (video position for replays)
    # False for a game that never announces a boss's defeat (the profile's
    # ``closes_fights``): a fight in its log has no known outcome. Written to
    # the log so that whoever reads it — the window, the website — knows.
    closes_fights: bool = True
    # Which playthrough the session belongs to, and the name and New Game+
    # cycle (0 = the first run) it had when written — names travel with the
    # log, so a second PC that downloads it knows what to call it.
    playthrough: str = DEFAULT_PLAYTHROUGH
    playthrough_name: str | None = None
    cycle: int = 0

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
    def open(
        cls,
        game: str,
        source: str,
        data_dir: Path | None = None,
        started: datetime | None = None,
        closes_fights: bool = True,
        playthrough: str = DEFAULT_PLAYTHROUGH,
        playthrough_name: str | None = None,
        cycle: int = 0,
    ) -> SessionLog:
        started = started or datetime.now()
        directory = (data_dir or default_data_dir()) / "sessions" / game
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{started:%Y%m%d-%H%M%S}.jsonl"
        fh = path.open("a", encoding="utf-8")
        meta = SessionMeta(
            game=game,
            source=source,
            started=started,
            closes_fights=closes_fights,
            playthrough=playthrough,
            playthrough_name=playthrough_name,
            cycle=cycle,
        )
        log = cls(path, fh, meta)
        start = {
            "kind": "session_start",
            "game": game,
            "source": source,
            "started": started.isoformat(timespec="milliseconds"),
        }
        if not closes_fights:  # only then, so every other game's log reads as before
            start["closes_fights"] = False
        tag = _tag(playthrough, playthrough_name, cycle)
        if tag:  # likewise only for a playthrough other than the unnamed default
            start["playthrough"] = tag
        log._write(start)
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


def _tag(playthrough: str, name: str | None, cycle: int) -> dict | None:
    if playthrough == DEFAULT_PLAYTHROUGH and not name and not cycle:
        return None
    tag: dict = {"id": playthrough}
    if name:
        tag["name"] = name
    if cycle:
        tag["cycle"] = cycle
    return tag


def _apply_tag(meta: SessionMeta, tag: dict) -> None:
    meta.playthrough = str(tag.get("id") or DEFAULT_PLAYTHROUGH)
    meta.playthrough_name = tag.get("name") or None
    meta.cycle = int(tag.get("cycle", 0) or 0)


def move_session(path: str | Path, playthrough: str, name: str | None = None, cycle: int = 0) -> None:
    """Move a finished log to another playthrough by appending a
    ``playthrough`` line; the log stays append-only. A log still being
    written (no ``session_end``) is refused: the capture owns it."""
    meta, _ = read_session(path)
    if meta.ended is None:
        raise ValueError("that session is still being recorded; move it once it has ended")
    tag = _tag(playthrough, name, cycle) or {"id": DEFAULT_PLAYTHROUGH}
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "playthrough", **tag}, ensure_ascii=False) + "\n")


_TAG_CACHE: dict[Path, tuple[float, int, tuple[str, str | None, int]]] = {}


def playthrough_of(path: str | Path) -> tuple[str, str | None, int]:
    """(id, name, cycle) of the playthrough a log belongs to, without parsing
    its events: the start line, then any move at the tail. Cached on the
    file's mtime and size, since every screen filters logs by it."""
    path = Path(path)
    st = path.stat()
    hit = _TAG_CACHE.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    meta = SessionMeta(game="", source="", started=datetime.min)
    with path.open("rb") as fh:
        first = fh.readline().decode("utf-8", "replace")
        try:
            start = json.loads(first)
        except ValueError:
            start = {}
        if isinstance(start.get("playthrough"), dict):
            _apply_tag(meta, start["playthrough"])
        fh.seek(max(0, st.st_size - 4096))
        for line in fh.read().decode("utf-8", "replace").splitlines():
            if '"kind": "playthrough"' in line:
                try:
                    _apply_tag(meta, json.loads(line))
                except ValueError:
                    pass
    out = (meta.playthrough, meta.playthrough_name, meta.cycle)
    _TAG_CACHE[path] = (st.st_mtime, st.st_size, out)
    return out


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
                    game=obj["game"],
                    source=obj.get("source", ""),
                    started=datetime.fromisoformat(obj["started"]),
                    closes_fights=bool(obj.get("closes_fights", True)),
                )
                if isinstance(obj.get("playthrough"), dict):
                    _apply_tag(meta, obj["playthrough"])
            elif kind == "playthrough" and meta is not None:
                _apply_tag(meta, obj)
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
