"""Suppress repeats, and keep the best read of each.

A banner stays on screen for seconds and the watcher may fire more than once
as it fades in/out; dialogue lines get re-OCR'd as the camera moves behind
them. Anything with the same type and text inside the cooldown is dropped.

The first read of a banner is often the worst one — mid fade-in, glued or
garbled — and the clean read a second later used to be the one dropped. So a
repeat that is clearly better than what was kept *upgrades* it: the caller
revises the logged event's text and keeps its time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
# A repeat replaces the kept read when it has the same letters with more word
# breaks (OCR glues words far more often than it splits them: "A warleading
# to abandonmentby the GreaterWill." kept, "A war leading to abandonment by
# the Greater Will." dropped, Elden Ring hour 0), or when its confidence is
# clearly higher — a mid-fade read against the settled banner. OCR confidence
# moves by ±0.03 between two clean reads of one line (0.941, 0.965, 0.974
# above), so a smaller gap decides nothing.
BETTER_CONF = 0.05
# ...and never for a read that lost part of the text on the way.
MIN_LENGTH_KEPT = 0.95


class Verdict(Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    UPGRADE = "upgrade"


@dataclass(slots=True)
class _Seen:
    event: Event  # the logged event; its text is updated on an upgrade
    text: str  # normalised
    t: float


class Deduper:
    def __init__(
        self, cooldowns: dict[EventType, float] | None = None, by_type: set[EventType] | None = None
    ) -> None:
        self.cooldowns = dict(cooldowns or {})
        # Types whose text is evidence, not identity: a boss cannot be
        # defeated twice within the cooldown, whether the second sighting is
        # the banner or the drop that implies it.
        self.by_type = set(by_type or ())
        self._recent: list[_Seen] = []

    def accept(self, event: Event) -> bool:
        return self.offer(event)[0] is Verdict.NEW

    def offer(self, event: Event) -> tuple[Verdict, Event | None]:
        """``NEW``: log it. ``DUPLICATE``: drop it. ``UPGRADE``: drop it, but
        it reads better than the event returned alongside, which the caller
        should revise to ``event``'s text (``better`` says when)."""
        window = self.cooldowns.get(event.type, DEFAULT_COOLDOWN)
        text = normalize(event.text)
        horizon = max(self.cooldowns.values(), default=DEFAULT_COOLDOWN)
        self._recent = [r for r in self._recent if event.t_rel - r.t < horizon]
        for seen in self._recent:
            if seen.event.type is not event.type or event.t_rel - seen.t >= window:
                continue
            if event.type in self.by_type:
                return Verdict.DUPLICATE, None
            # Two different texts read from the same frame are two rows of a
            # stacked pickup list ("Gargoyle's Shield" / "Gargoyle Helm",
            # ratio 80), never a re-read of one banner.
            if seen.t == event.t_rel and text != seen.text:
                continue
            if _similar(text, seen.text):
                if better(event, seen.event):
                    seen.text = text
                    return Verdict.UPGRADE, seen.event
                return Verdict.DUPLICATE, None
        self._recent.append(_Seen(event, text, event.t_rel))
        return Verdict.NEW, None


def better(new: Event, old: Event) -> bool:
    """Is ``new`` a clearly better read of the same thing than ``old``?"""
    a, b = normalize(new.text), normalize(old.text)
    if a == b:
        return False
    if a.replace(" ", "") == b.replace(" ", ""):
        return a.count(" ") > b.count(" ")
    return new.conf >= old.conf + BETTER_CONF and len(a) >= MIN_LENGTH_KEPT * len(b)


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def _similar(a: str, b: str) -> bool:
    """Near-identical text, except that differing numbers mean different things
    ("Smithing Stone [7]" and "Smithing Stone [8]" picked up together)."""
    if _digits(a) != _digits(b):
        return False
    return fuzz.ratio(a, b) >= SIMILARITY
