"""Event model and JSONL serialization.

Event type names are deliberately game-agnostic (``checkpoint_discovered``
rather than "grace"); each game profile maps its own vocabulary onto them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventType(StrEnum):
    DEATH = "death"
    BOSS_ENGAGED = "boss_engaged"
    BOSS_DEFEATED = "boss_defeated"
    ENEMY_DEFEATED = "enemy_defeated"
    CHECKPOINT_DISCOVERED = "checkpoint_discovered"
    AREA_DISCOVERED = "area_discovered"
    ITEM_ACQUIRED = "item_acquired"
    DIALOGUE = "dialogue"


# Fixed-position, high-contrast HUD announcements. These must be precise;
# dialogue is allowed to be lossy.
BANNER_TYPES = frozenset(
    {
        EventType.DEATH,
        EventType.BOSS_DEFEATED,
        EventType.ENEMY_DEFEATED,
        EventType.CHECKPOINT_DISCOVERED,
        EventType.AREA_DISCOVERED,
    }
)


@dataclass(slots=True)
class Event:
    ts: datetime
    t_rel: float  # seconds since session start
    type: EventType
    text: str
    conf: float
    region: str
    raw: list[str] = field(default_factory=list)  # OCR lines this was built from
    frame_index: int = 0
    # Position in the session log (what a recap cites as #n); set when the
    # event is logged or read back, never serialised.
    index: int = field(default=-1, compare=False)

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": "event",
                "ts": self.ts.isoformat(timespec="milliseconds"),
                "t_rel": round(self.t_rel, 3),
                "type": self.type.value,
                "text": self.text,
                "conf": round(self.conf, 3),
                "region": self.region,
                "raw": self.raw,
                "frame_index": self.frame_index,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            ts=datetime.fromisoformat(d["ts"]),
            t_rel=float(d["t_rel"]),
            type=EventType(d["type"]),
            text=d["text"],
            conf=float(d["conf"]),
            region=d["region"],
            raw=list(d.get("raw", [])),
            frame_index=int(d.get("frame_index", 0)),
        )

    @classmethod
    def from_json(cls, line: str) -> Event:
        return cls.from_dict(json.loads(line))
