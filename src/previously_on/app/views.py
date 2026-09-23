"""What each screen shows, as plain dicts the page renders. Everything here
is offline and read-only: session logs and recap records in, JSON out. The
numbers come from ``stats``, the text from ``recap.gap``, the lookup from
``recap.index`` — nothing is re-derived.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..events import Event, EventType
from ..recap import index as index_mod
from ..recap.gap import Tier, describe_gap, pick_tier, render
from ..recap.schema import RecapRecord
from ..recap.store import read_record, recap_path, session_id, sessions_dir
from ..session import SessionMeta, read_session
from ..stats import SessionStats, compute, format_duration, summary_line


def list_logs(game: str, data_dir: Path | None) -> list[Path]:
    """Session logs, oldest first (stamps sort chronologically)."""
    directory = sessions_dir(game, data_dir)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.jsonl"))


def _record_for(log: Path) -> RecapRecord | None:
    path = recap_path(log)
    if not path.exists():
        return None
    try:
        return read_record(path)
    except ValueError:
        return None


def _clock(t_rel: float) -> str:
    h, rem = divmod(int(t_rel), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _boss(b) -> dict:
    return {"name": b.name, "attempts": b.attempts, "defeated": b.defeated, "phases": list(b.phases)}


def _state(record: RecapRecord | None) -> dict | None:
    if record is None:
        return None
    st = record.recap.state
    return {
        "location": st.location,
        "objective": st.current_objective,
        "threads": [{"who": t.who, "what": t.what, "status": t.status} for t in st.threads if t.status != "done"],
        "npcs": [{"name": n.name, "location": n.last_location, "notes": n.notes} for n in st.npcs],
        "items": list(st.notable_items),
    }


def _session_row(log: Path, meta: SessionMeta, events: list[Event], stats: SessionStats, record) -> dict:
    return {
        "session": session_id(log),
        "started": meta.started.isoformat(timespec="seconds"),
        "ended": (meta.ended or meta.started).isoformat(timespec="seconds"),
        "date": f"{meta.started:%a %d %b %Y, %H:%M}",
        "duration": format_duration(stats.duration),
        "seconds": stats.duration,
        "one_line": summary_line(stats),
        "deaths": stats.deaths,
        "bosses": [_boss(b) for b in stats.bosses],
        "areas": list(stats.areas),
        "checkpoints": stats.checkpoints,
        "items": stats.items,
        "dialogue_lines": stats.dialogue_lines,
        "events": len(events),
        "has_recap": record is not None,
        "summary": record.recap.summary if record else None,
    }


def games(profiles, data_dir: Path | None) -> list[dict]:
    """Every known game with how many sessions it has and when it was last
    played (the newest log's stamp; stamps sort across games too), in the
    profiles' order."""
    rows = []
    for p in profiles:
        logs = list_logs(p.id, data_dir)
        rows.append(
            {"id": p.id, "name": p.display_name, "sessions": len(logs), "last": session_id(logs[-1]) if logs else None}
        )
    return rows


def last_played(profiles, data_dir: Path | None) -> str | None:
    """Id of the game with the newest session log, or None if nothing is logged."""
    played = [g for g in games(profiles, data_dir) if g["last"]]
    return max(played, key=lambda g: g["last"])["id"] if played else None


# --- screens ------------------------------------------------------------------


def home(game: str, data_dir: Path | None, now: datetime | None = None) -> dict:
    """The resume screen: the gap-scaled text for the latest session, the
    playthrough state that goes with it, and whether a recap is missing."""
    now = now or datetime.now()
    logs = list_logs(game, data_dir)
    if not logs:
        return {"empty": True}
    log = logs[-1]
    meta, events = read_session(log)
    stats = compute(events, duration=meta.duration)
    ended = meta.ended or meta.started
    record = _record_for(log)
    out = _session_row(log, meta, events, stats, record)
    out.update({"empty": False, "gap": describe_gap(ended, now), "needs_recap": record is None})
    if record is None:
        # No recap for the newest session (no key when it ended, or the app
        # was closed first). The one-liner needs no model; the state shown is
        # the newest one that exists, and says which session it is from.
        out["tier"] = "one_line"
        out["text"] = f"Last session, {describe_gap(ended, now)}: {summary_line(stats)}"
        out["full_text"] = None
        older = [_record_for(p) for p in reversed(logs[:-1])]
        prev = next((r for r in older if r is not None), None)
        out["state"] = _state(prev)
        out["state_from"] = prev.session if prev else None
        return out
    tier: Tier = pick_tier(ended, now)
    out["tier"] = tier
    out["text"] = render(record, log, tier, now)
    out["full_text"] = render(record, log, "full", now) if tier != "full" else None
    out["state"] = _state(record)
    out["state_from"] = record.session
    return out


def sessions(game: str, data_dir: Path | None) -> list[dict]:
    """Newest first."""
    rows = []
    for log in reversed(list_logs(game, data_dir)):
        meta, events = read_session(log)
        stats = compute(events, duration=meta.duration)
        rows.append(_session_row(log, meta, events, stats, _record_for(log)))
    return rows


def session(game: str, data_dir: Path | None, stamp: str) -> dict | None:
    log = sessions_dir(game, data_dir) / f"{stamp}.jsonl"
    if not log.is_file():
        return None
    meta, events = read_session(log)
    stats = compute(events, duration=meta.duration)
    record = _record_for(log)
    out = _session_row(log, meta, events, stats, record)
    out["event_list"] = [
        {"index": i, "at": _clock(ev.t_rel), "t_rel": ev.t_rel, "type": ev.type.value, "text": ev.text, "conf": ev.conf}
        for i, ev in enumerate(events)
    ]
    out["conversations"] = []
    out["dropped"] = []
    out["state"] = _state(record)
    if record is not None:
        for c in record.recap.conversations:
            first = min((i for i in c.events if 0 <= i < len(events)), default=None)
            out["conversations"].append(
                {
                    "speaker": c.speaker,
                    "basis": c.speaker_basis,
                    "location": c.location,
                    "at": _clock(events[first].t_rel) if first is not None else None,
                    "events": list(c.events),
                    "gist": c.gist,
                }
            )
        out["dropped"] = list(record.dropped)
        out["model"] = record.model
        out["short_recap"] = record.recap.short_recap
        out["full_recap"] = record.recap.full_recap
    return out


def timeline(game: str, data_dir: Path | None) -> list[dict]:
    """The playthrough oldest → newest: per session, its areas and boss
    fights in order, with items folded into a count (names on request) and
    checkpoints counted — the banner names no grace."""
    by_session: dict[str, list[index_mod.Entry]] = {}
    for e in index_mod.build(game, data_dir).entries:
        by_session.setdefault(e.session, []).append(e)
    out = []
    for log in list_logs(game, data_dir):
        meta, events = read_session(log)
        stats = compute(events, duration=meta.duration)
        row = _session_row(log, meta, events, stats, _record_for(log))
        entries = sorted(by_session.get(row["session"], []), key=lambda e: e.t_rel)
        moments = []
        item_counts: dict[str, int] = {}
        for e in entries:
            if e.kind == "item":
                item_counts[e.name] = item_counts.get(e.name, 0) + 1
            elif e.kind in ("area", "boss"):
                moments.append(
                    {"kind": e.kind, "name": e.name, "at": _clock(e.t_rel), "location": e.location, "detail": e.detail}
                )
        row["moments"] = moments
        row["item_names"] = [f"{n} ×{c}" if c > 1 else n for n, c in item_counts.items()]
        out.append(row)
    return out


def totals(game: str, data_dir: Path | None) -> dict:
    """``112 hours · 847 deaths · Bayle took 34 tries`` — the whole playthrough in one line."""
    seconds = 0.0
    deaths = 0
    felled: list[dict] = []
    first: datetime | None = None
    last: datetime | None = None
    logs = list_logs(game, data_dir)
    for log in logs:
        meta, events = read_session(log)
        stats = compute(events, duration=meta.duration)
        seconds += stats.duration
        deaths += stats.deaths
        felled.extend(_boss(b) for b in stats.bosses if b.defeated)
        first = meta.started if first is None else min(first, meta.started)
        ended = meta.ended or meta.started
        last = ended if last is None else max(last, ended)
    hardest = max(felled, key=lambda b: b["attempts"], default=None)
    hours = seconds / 3600
    parts = [f"{hours:.0f} hour{'s' if round(hours) != 1 else ''}" if hours >= 1 else format_duration(seconds)]
    parts.append(f"{deaths} death{'s' if deaths != 1 else ''}")
    if hardest is not None and hardest["attempts"] > 1:
        parts.append(f"{hardest['name']} took {hardest['attempts']} tries")
    return {
        "sessions": len(logs),
        "seconds": seconds,
        "playtime": format_duration(seconds),
        "deaths": deaths,
        "bosses_felled": len(felled),
        "hardest": hardest,
        "first": first.isoformat(timespec="seconds") if first else None,
        "last": last.isoformat(timespec="seconds") if last else None,
        "line": " · ".join(parts) if logs else "",
    }


def search(game: str, data_dir: Path | None, query: str, kinds: list[str] | None = None) -> list[dict]:
    index = index_mod.build(game, data_dir)
    hits = index_mod.search(index, query, set(kinds) if kinds else None)
    return [
        {
            "kind": e.kind,
            "name": e.name,
            "session": e.session,
            "date": f"{e.started:%Y-%m-%d}",
            "at": _clock(e.t_rel),
            "location": e.location,
            "detail": e.detail,
        }
        for e in hits
    ]


EVENT_TYPES = [t.value for t in EventType]
