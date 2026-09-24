"""Session statistics — the headline "attempt count".

Attribution rule: every death after a boss bar has been seen, until that
boss is defeated, is credited to the fight, named after the first boss bar
seen since the previous defeat (multi-phase bosses rename their bar mid-fight: "Messmer the
Impaler" → "Base Serpent Messmer"). When a ``boss_defeated`` lands — or an
``enemy_defeated``, which is what field bosses and evergaol bosses get —
attempts = those deaths + the winning try. A different bar after a
checkpoint or area banner is a new fight, not a phase: the previous boss
is left standing (its defeat banner may have been missed). OCR variants of the same name
("Messmer the Impaler T") are folded into the fight.

The *kill* is credited to the fight's first name only while the bar's
names stay related. When the last bar shares nothing with the first —
"Radagon of the Golden Order" then "Elden Beast", "Beast Clergyman" then
"Maliketh, the Black Blade" — the kill goes to the last name, which is
what the player actually put down. "Malenia, Blade of Miquella" renaming
to "Malenia, Goddess of Rot" shares a name and keeps the first, as does
"Sister Friede" becoming "Blackflame Friede". Every other name of the
fight is in ``phases`` either way, so nothing is lost.

This matters most in a game with no defeat banner for its lesser bosses.
Sekiro gives one only for main bosses, so two consecutive miniboss fights
with no idol between them fold into one, and crediting the first name put
the kill on the wrong boss in 5 of that game's 15 defeats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .classify import normalize
from .events import Event, EventType

UNKNOWN_BOSS = "unknown boss"
SAME_NAME = 85.0
# A word long enough to be part of a creature's name rather than grammar.
# Four letters keeps "Malenia", "Friede", "Demon" and "Prince" and drops
# "the", "of", "Way".
_NAME_TOKEN = re.compile(r"[A-Za-z]{4,}")
SAME_AREA = 75.0  # OCR variants of one banner ("Specimdrhorehouse") score ~78; distinct areas < 40


@dataclass(slots=True)
class BossStat:
    name: str
    attempts: int
    defeated: bool
    phases: list[str] = field(default_factory=list)  # other bar names seen during the fight


@dataclass(slots=True)
class SessionStats:
    duration: float
    deaths: int
    bosses: list[BossStat] = field(default_factory=list)
    checkpoints: int = 0
    areas: list[str] = field(default_factory=list)
    items: int = 0
    dialogue_lines: int = 0

    @property
    def current_boss(self) -> BossStat | None:
        """The boss still standing at the end of the session, if any."""
        if self.bosses and not self.bosses[-1].defeated:
            return self.bosses[-1]
        return None


def compute(events: list[Event], duration: float | None = None) -> SessionStats:
    if duration is None:
        duration = events[-1].t_rel if events else 0.0
    stats = SessionStats(duration=duration, deaths=0)

    current_name: str | None = None
    last_name: str | None = None  # the most recent bar, which may be a later phase
    phases: list[str] = []
    deaths_since_defeat = 0
    moved_on = False  # a checkpoint/area banner since the last boss bar

    for ev in events:
        match ev.type:
            case EventType.BOSS_ENGAGED:
                known = current_name is not None and (
                    _same_name(ev.text, current_name) or any(_same_name(ev.text, p) for p in phases)
                )
                if current_name is not None and not known and moved_on:
                    stats.bosses.append(BossStat(current_name, deaths_since_defeat, False, phases))
                    current_name, phases, deaths_since_defeat = None, [], 0
                if current_name is None:
                    current_name = ev.text
                elif not known:
                    phases.append(ev.text)
                last_name = ev.text
                moved_on = False
            case EventType.DEATH:
                stats.deaths += 1
                if current_name is not None:
                    deaths_since_defeat += 1
            case EventType.BOSS_DEFEATED | EventType.ENEMY_DEFEATED:
                # "ENEMY FELLED" only appears for enemies that had a bar; with
                # no bar seen it is a stray (or the bar was missed) and says
                # nothing about a fight.
                if ev.type is EventType.ENEMY_DEFEATED and current_name is None:
                    continue
                name, others = current_name or UNKNOWN_BOSS, phases
                if current_name and last_name and not _related(current_name, last_name):
                    # The credited name comes out of ``phases`` and the
                    # first name goes in: every bar of the fight is still
                    # recorded, exactly once.
                    name = last_name
                    others = [current_name] + [p for p in phases if not _same_name(p, last_name)]
                stats.bosses.append(BossStat(name, deaths_since_defeat + 1, True, others))
                current_name = None
                last_name = None
                phases = []
                deaths_since_defeat = 0
            case EventType.CHECKPOINT_DISCOVERED:
                stats.checkpoints += 1
                moved_on = True
            case EventType.AREA_DISCOVERED:
                moved_on = True
                if not any(fuzz.ratio(normalize(ev.text), normalize(a)) >= SAME_AREA for a in stats.areas):
                    stats.areas.append(ev.text)
            case EventType.ITEM_ACQUIRED:
                stats.items += 1
            case EventType.DIALOGUE:
                stats.dialogue_lines += 1

    if current_name is not None:
        stats.bosses.append(BossStat(current_name, deaths_since_defeat, False, phases))
    return stats


def _same_name(a: str, b: str) -> bool:
    return fuzz.ratio(normalize(a), normalize(b)) >= SAME_NAME


def _related(a: str, b: str) -> bool:
    """True when two bar names look like the same creature.

    Either they match outright, or they share a word long enough to be a
    name: "Malenia, Blade of Miquella" / "Malenia, Goddess of Rot",
    "Lorian, Elder Prince" / "Lothric, Younger Prince". "Radagon of the
    Golden Order" and "Elden Beast" share nothing, and neither do "Juzou
    the Drunkard" and "Lady Butterfly".
    """
    if _same_name(a, b):
        return True
    return bool({w.lower() for w in _NAME_TOKEN.findall(a)} & {w.lower() for w in _NAME_TOKEN.findall(b)})


def format_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def summary_line(stats: SessionStats) -> str:
    """``3h 12m · 14 deaths · Bayle still standing``"""
    parts = [format_duration(stats.duration), f"{stats.deaths} death{'s' if stats.deaths != 1 else ''}"]
    boss = stats.current_boss
    if boss is not None:
        parts.append(f"{boss.name} still standing")
    elif stats.bosses:
        last = stats.bosses[-1]
        parts.append(f"{last.name} felled in {last.attempts} {'try' if last.attempts == 1 else 'tries'}")
    return " · ".join(parts)


def across_sessions(fights: list[BossStat]) -> list[BossStat]:
    """Join fights that span sessions, for playthrough totals.

    ``compute`` sees one session, so a boss that took 20 deaths one evening
    and 14 the next is two fights: one still standing, one felled in 15.
    Here a fight left standing is carried into the next fight with the same
    boss (any of its bar names) and its deaths are added to that one's
    tries. ``fights`` is every session's ``bosses`` in play order; the
    result keeps that order, each joined fight at the place it resumed.

    A standing fight joins the *next* fight with that name, wherever it
    is — two different Night's Cavalry share a name, and a death to the
    first counts toward the second. Rare, and not a fight the card leads
    with.
    """
    out: list[BossStat] = []
    for fight in fights:
        names = [fight.name, *fight.phases]
        prior = next(
            (
                f
                for f in out
                if not f.defeated and any(_same_name(a, b) for a in (f.name, *f.phases) for b in names)
            ),
            None,
        )
        if prior is not None:
            out.remove(prior)
            extra = [p for p in (prior.name, *prior.phases) if not any(_same_name(p, n) for n in names)]
            fight = BossStat(fight.name, prior.attempts + fight.attempts, fight.defeated, [*fight.phases, *extra])
        out.append(fight)
    return out
