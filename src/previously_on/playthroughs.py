"""Several playthroughs of one game: a second character, or New Game+.

The screen shows nothing that tells two characters apart, so the player says
which one they are playing and every session log records it (``session.py``).
Recaps chain their state within a playthrough only, and every screen, the
timeline, search and the share card show one playthrough at a time.

The list lives beside the logs as ``sessions/<game>/playthroughs.json``:
names, which one is current (where the next capture goes), and for a New
Game+ cycle the run it follows. It is local; a log carries its playthrough's
name and cycle, so logs synced from another PC bring theirs with them and
show up here even if this file has never heard of them.

A game with a single, unnamed playthrough writes no file and tags no log —
that is every game until the player makes a second one.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .session import DEFAULT_PLAYTHROUGH, playthrough_of, sessions_dir

FILE_NAME = "playthroughs.json"
DEFAULT_NAME = "First playthrough"
MAX_NAME = 60


@dataclass(slots=True)
class Playthrough:
    id: str
    name: str | None = None
    cycle: int = 0  # New Game+ count: 0 = the first run, 1 = NG+, 2 = NG++
    follows: str | None = None  # the playthrough this NG+ cycle continues
    created: str | None = None

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        if self.id == DEFAULT_PLAYTHROUGH:
            return DEFAULT_NAME
        return f"Playthrough {self.id}"

    def to_json(self) -> dict:
        return {**asdict(self), "label": self.label}


def _clean(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("a playthrough needs a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"keep the name under {MAX_NAME} characters")
    return name


def ng_suffix(cycle: int) -> str:
    return "NG" + "+" * cycle if cycle <= 3 else f"NG+{cycle}"


class Registry:
    """One game's playthroughs. Load, change, ``save``."""

    def __init__(self, game: str, data_dir: Path | None = None) -> None:
        self.game = game
        self.directory = sessions_dir(game, data_dir)
        self.path = self.directory / FILE_NAME
        self.current_id = DEFAULT_PLAYTHROUGH
        self._items: dict[str, Playthrough] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for row in raw.get("playthroughs", []) if isinstance(raw, dict) else []:
            if isinstance(row, dict) and row.get("id"):
                fields = {k: row.get(k) for k in ("name", "follows", "created")}
                self._items[str(row["id"])] = Playthrough(str(row["id"]), cycle=int(row.get("cycle") or 0), **fields)
        if isinstance(raw, dict) and raw.get("current"):
            self.current_id = str(raw["current"])
        # Logs name their playthrough; one this file lacks (synced from
        # another PC, or the file was lost) is added with the name it carries.
        for log in self.logs():
            pid, name, cycle = playthrough_of(log)
            if pid not in self._items:
                self._items[pid] = Playthrough(pid, name, cycle)
        self._items.setdefault(DEFAULT_PLAYTHROUGH, Playthrough(DEFAULT_PLAYTHROUGH))
        if self.current_id not in self._items:
            self.current_id = DEFAULT_PLAYTHROUGH

    @classmethod
    def load(cls, game: str, data_dir: Path | None = None) -> Registry:
        return cls(game, data_dir)

    def logs(self, playthrough: str | None = None) -> list[Path]:
        """Session logs, oldest first; only ``playthrough``'s when given."""
        if not self.directory.is_dir():
            return []
        logs = sorted(self.directory.glob("*.jsonl"))
        if playthrough is None:
            return logs
        return [log for log in logs if playthrough_of(log)[0] == playthrough]

    # --- reading ----------------------------------------------------------------

    def all(self) -> list[Playthrough]:
        """The default first, then in order of creation."""
        rest = [p for p in self._items.values() if p.id != DEFAULT_PLAYTHROUGH]
        rest.sort(key=lambda p: (p.created or "", p.id))
        return [self._items[DEFAULT_PLAYTHROUGH], *rest]

    def get(self, pid: str) -> Playthrough:
        try:
            return self._items[pid]
        except KeyError:
            raise KeyError(f"no playthrough {pid!r} for {self.game}") from None

    def current(self) -> Playthrough:
        return self._items[self.current_id]

    def rows(self) -> list[dict]:
        """Every playthrough with its session count, for the picker."""
        counts: dict[str, int] = {}
        last: dict[str, str] = {}
        for log in self.logs():
            pid = playthrough_of(log)[0]
            counts[pid] = counts.get(pid, 0) + 1
            last[pid] = log.stem
        return [
            {**p.to_json(), "sessions": counts.get(p.id, 0), "last": last.get(p.id), "current": p.id == self.current_id}
            for p in self.all()
        ]

    # --- changing -----------------------------------------------------------------

    def create(self, name: str, *, follows: str | None = None, now: datetime | None = None) -> Playthrough:
        """A new playthrough, made current. With ``follows``, a New Game+
        cycle of that one (the same character, the world reset)."""
        now = now or datetime.now()
        cycle = 0
        if follows is not None:
            cycle = self.get(follows).cycle + 1
        pid = f"{now:%Y%m%d-%H%M%S}"
        while pid in self._items:  # two in the same second
            pid += "x"
        p = Playthrough(pid, _clean(name), cycle, follows, now.isoformat(timespec="seconds"))
        self._items[pid] = p
        self.current_id = pid
        return p

    def new_game_plus(self, of: str, now: datetime | None = None) -> Playthrough:
        base = self.get(of)
        root = base.label.split(" · NG")[0]
        return self.create(f"{root} · {ng_suffix(base.cycle + 1)}", follows=of, now=now)

    def rename(self, pid: str, name: str) -> Playthrough:
        p = self.get(pid)
        p.name = _clean(name)
        return p

    def select(self, pid: str) -> Playthrough:
        self.get(pid)
        self.current_id = pid
        return self._items[pid]

    def delete(self, pid: str) -> None:
        """Only an empty playthrough, never the default: logs are never deleted here."""
        if pid == DEFAULT_PLAYTHROUGH:
            raise ValueError("the first playthrough cannot be deleted")
        self.get(pid)
        if self.logs(pid):
            raise ValueError("move or delete its sessions first; only an empty playthrough can be deleted")
        del self._items[pid]
        for p in self._items.values():
            if p.follows == pid:
                p.follows = None
        if self.current_id == pid:
            self.current_id = DEFAULT_PLAYTHROUGH

    def save(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "current": self.current_id,
            "playthroughs": [
                {k: v for k, v in asdict(p).items() if v not in (None, 0) or k == "id"} for p in self.all()
            ],
        }
        tmp = self.path.with_name(FILE_NAME + ".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path

    def tag(self, pid: str | None = None) -> dict:
        """What a new session log records: ``SessionLog.open(**tag)``."""
        p = self.get(pid) if pid else self.current()
        return {"playthrough": p.id, "playthrough_name": p.name, "cycle": p.cycle}


def logs(game: str, data_dir: Path | None = None, playthrough: str | None = None) -> list[Path]:
    """Session logs of one playthrough (the current one when not given), oldest first."""
    reg = Registry.load(game, data_dir)
    return reg.logs(playthrough or reg.current_id)
