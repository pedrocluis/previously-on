"""Session log → the compact transcript the model reads.

One line per event, ``#<index>`` first so the model can cite it. Dialogue
lines that follow each other become one block under the place they were
heard; a run of identical item pickups folds to ``×N``; a boss kill carries
its attempt count from ``stats`` so the model never counts deaths itself.
About ten tokens per event.
"""

from __future__ import annotations

from .. import stats as stats_mod
from ..events import Event, EventType
from ..session import SessionMeta

DIALOGUE_GAP = 20.0  # seconds; a longer silence starts a new block


def _clock(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _fights_by_defeat(events: list[Event], stats: stats_mod.SessionStats) -> dict[int, stats_mod.BossStat]:
    """Map each defeat event's index to the fight ``stats`` attributed to it.

    The defeat banner names nothing (``GREAT ENEMY FELLED``); the boss name
    and the attempt count come from the bar. Mirrors the one rule in
    ``stats.compute`` that decides whether a defeat counts: ``ENEMY FELLED``
    with no bar seen since the last defeat is a stray.
    """
    defeated = [b for b in stats.bosses if b.defeated]
    out: dict[int, stats_mod.BossStat] = {}
    bar_seen = False
    for i, ev in enumerate(events):
        if ev.type is EventType.BOSS_ENGAGED:
            bar_seen = True
        elif ev.type is EventType.BOSS_DEFEATED or (ev.type is EventType.ENEMY_DEFEATED and bar_seen):
            if defeated:
                out[i] = defeated.pop(0)
            bar_seen = False
    return out


def compact(meta: SessionMeta, events: list[Event], stats: stats_mod.SessionStats | None = None) -> str:
    if stats is None:
        stats = stats_mod.compute(events, duration=meta.duration)
    fights = _fights_by_defeat(events, stats)
    lines = [f"Session {meta.started:%Y-%m-%d %H:%M} · {stats_mod.summary_line(stats)}", ""]

    location: str | None = None
    i = 0
    n = len(events)
    while i < n:
        ev = events[i]
        t = _clock(ev.t_rel)
        match ev.type:
            case EventType.DIALOGUE:
                where = f" @{location}" if location else ""
                lines.append(f"[{t}] dialogue{where}:")
                last_t = ev.t_rel
                while i < n and events[i].type is EventType.DIALOGUE and events[i].t_rel - last_t <= DIALOGUE_GAP:
                    lines.append(f"  #{i} {events[i].text}")
                    last_t = events[i].t_rel
                    i += 1
                continue
            case EventType.ITEM_ACQUIRED:
                j = i
                while j + 1 < n and events[j + 1].type is EventType.ITEM_ACQUIRED and events[j + 1].text == ev.text:
                    j += 1
                count = j - i + 1
                suffix = f" ×{count} (#{i}-#{j})" if count > 1 else ""
                lines.append(f"#{i} [{t}] item: {ev.text}{suffix}")
                i = j + 1
                continue
            case EventType.AREA_DISCOVERED:
                location = ev.text
                lines.append(f"#{i} [{t}] area: {ev.text}")
            case EventType.CHECKPOINT_DISCOVERED:
                lines.append(f"#{i} [{t}] checkpoint: {ev.text}")
            case EventType.BOSS_ENGAGED:
                lines.append(f"#{i} [{t}] boss fight: {ev.text}")
            case EventType.DEATH:
                lines.append(f"#{i} [{t}] died")
            case EventType.BOSS_DEFEATED | EventType.ENEMY_DEFEATED:
                fight = fights.get(i)
                if fight is None:
                    lines.append(f"#{i} [{t}] {ev.text.lower()} (no boss bar seen; may be a stray)")
                else:
                    tries = f"attempt {fight.attempts}" if fight.attempts > 1 else "first attempt"
                    lines.append(f"#{i} [{t}] defeated: {fight.name} ({tries}; banner {ev.text})")
        i += 1
    return "\n".join(lines)
