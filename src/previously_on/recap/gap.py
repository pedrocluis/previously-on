"""Gap-scaled output: how much recap the player gets depends on how long they
have been away. Shown after every session at constant detail, the recap
becomes a loading screen; the daily version's only job is to be present and
fast to ignore. Nothing here touches the network — the tiers were written at
session end and picked here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from ..session import read_session
from ..stats import compute, format_duration, summary_line
from .schema import RecapRecord

Tier = Literal["one_line", "short", "full"]

SHORT_AFTER = timedelta(hours=48)
FULL_AFTER = timedelta(days=14)


def pick_tier(last_ended: datetime, now: datetime | None = None) -> Tier:
    gap = (now or datetime.now()) - last_ended
    if gap < SHORT_AFTER:
        return "one_line"
    if gap < FULL_AFTER:
        return "short"
    return "full"


def describe_gap(last_ended: datetime, now: datetime | None = None) -> str:
    days = ((now or datetime.now()) - last_ended).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def render(record: RecapRecord, session_path: Path, tier: Tier, now: datetime | None = None) -> str:
    """The text for the resume screen. ``session_path`` is the log the record
    was made from; the one-line tier is pure stats and never LLM prose."""
    meta, events = read_session(session_path)
    stats = compute(events, duration=meta.duration)
    ended = meta.ended or meta.started
    line = summary_line(stats)
    if tier == "one_line":
        return f"Last session, {describe_gap(ended, now)}: {line}"
    head = f"Last played {describe_gap(ended, now)} ({meta.started:%d %b %Y}, {format_duration(stats.duration)})."
    body = record.recap.short_recap if tier == "short" else record.recap.full_recap
    return f"{head}\n\n{body.strip()}"
