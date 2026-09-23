"""Suppress repeats.

A banner stays on screen for seconds and the watcher may fire more than once
as it fades in/out; dialogue lines get re-OCR'd as the camera moves behind
them. Anything with the same type and text inside the cooldown is dropped.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from .classify import normalize
from .events import Event, EventType

DEFAULT_COOLDOWN = 8.0
# OCR reads the same banner slightly differently frame to frame
# ("Specimen Storehouse" / "Specimen Stbrehouse" 95, "Gargoyle's Shleld"
# 94, "Darkroot Basim" 93, a mid-fade "NChapelof Anticlpauon" 84); treat
# near-identical text of the same type inside the cooldown as the same
# event. Siblings share a prefix and must stay distinct: "Ruin Sentinel
# Yahim" / "Ruin Sentinel Alessia" 80 (two of the three bars of one Dark
# Souls II fight, read a frame apart — 80 folded the third away),
# "Divine Tower of Limgrave" / "of Caelid" 78, "Darkroot Garden" /
# "Darkroot Basin" 76. Every real re-read seen so far scores 84 or more
# and every sibling pair 80 or less, so the threshold sits between them.
SIMILARITY = 82.0


class Deduper:
    def __init__(
        self, cooldowns: dict[EventType, float] | None = None, by_type: set[EventType] | None = None
    ) -> None:
        self.cooldowns = dict(cooldowns or {})
        # Types whose text is evidence, not identity: a boss cannot be
        # defeated twice within the cooldown, whether the second sighting is
        # the banner or the drop that implies it.
        self.by_type = set(by_type or ())
        self._recent: list[tuple[EventType, str, float]] = []

    def accept(self, event: Event) -> bool:
        window = self.cooldowns.get(event.type, DEFAULT_COOLDOWN)
        text = normalize(event.text)
        self._recent = [r for r in self._recent if event.t_rel - r[2] < max(self.cooldowns.values(), default=DEFAULT_COOLDOWN)]
        for typ, seen, t in self._recent:
            if typ is not event.type or event.t_rel - t >= window:
                continue
            if typ in self.by_type:
                return False
            # Two different texts read from the same frame are two rows of a
            # stacked pickup list ("Gargoyle's Shield" / "Gargoyle Helm",
            # ratio 80), never a re-read of one banner.
            if t == event.t_rel and text != seen:
                continue
            if _similar(text, seen):
                return False
        self._recent.append((event.type, text, event.t_rel))
        return True


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def _similar(a: str, b: str) -> bool:
    """Near-identical text, except that differing numbers mean different things
    ("Smithing Stone [7]" and "Smithing Stone [8]" picked up together)."""
    if _digits(a) != _digits(b):
        return False
    return fuzz.ratio(a, b) >= SIMILARITY
