"""Local search over everything logged: items, places, bosses, and — from the
recap records — who the player has talked to. No model involved; an item
lookup is "which session, when, and where were you".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from ..classify import normalize
from ..events import Event, EventType
from ..session import read_session
from ..stats import compute
from .store import list_records, read_record, sessions_dir

Kind = str  # item | area | checkpoint | boss | npc

MATCH = 82.0  # "Renala" still finds Rennala (83); "golden seed" no longer finds Golden Centipede (80)


@dataclass(slots=True)
class Entry:
    kind: Kind
    name: str
    session: str
    started: datetime
    t_rel: float
    location: str | None = None
    detail: str = ""  # boss outcome, conversation gist, speaker basis


@dataclass(slots=True)
class Index:
    entries: list[Entry] = field(default_factory=list)


def _entries_from_events(sid: str, started: datetime, events: list[Event], duration: float) -> list[Entry]:
    out: list[Entry] = []
    location: str | None = None
    first_bar: dict[str, Event] = {}
    for ev in events:
        match ev.type:
            case EventType.AREA_DISCOVERED:
                location = ev.text
                out.append(Entry("area", ev.text, sid, started, ev.t_rel, None))
            case EventType.CHECKPOINT_DISCOVERED:
                out.append(Entry("checkpoint", ev.text, sid, started, ev.t_rel, location))
            case EventType.ITEM_ACQUIRED:
                out.append(Entry("item", ev.text, sid, started, ev.t_rel, location))
            case EventType.BOSS_ENGAGED:
                first_bar.setdefault(normalize(ev.text), ev)
    for boss in compute(events, duration=duration).bosses:
        bar = first_bar.get(normalize(boss.name))
        t_rel = bar.t_rel if bar else 0.0
        where = None
        if bar is not None:
            before = [e.text for e in events if e.type is EventType.AREA_DISCOVERED and e.t_rel <= bar.t_rel]
            where = before[-1] if before else None
        if boss.defeated:
            detail = f"felled in {boss.attempts} {'try' if boss.attempts == 1 else 'tries'}"
        else:
            detail = f"{boss.attempts} death{'s' if boss.attempts != 1 else ''}, still standing"
        out.append(Entry("boss", boss.name, sid, started, t_rel, where, detail))
    return out


def build(game: str, data_dir: Path | None = None) -> Index:
    index = Index()
    directory = sessions_dir(game, data_dir)
    if not directory.is_dir():
        return index
    logs: dict[str, tuple[datetime, list[Event]]] = {}
    for path in sorted(directory.glob("*.jsonl")):
        sid = path.name.removesuffix(".jsonl")
        meta, events = read_session(path)
        logs[sid] = (meta.started, events)
        index.entries.extend(_entries_from_events(sid, meta.started, events, meta.duration))
    for path in list_records(game, data_dir):
        record = read_record(path)
        started, events = logs.get(record.session, (datetime.min, []))
        for c in record.recap.conversations:
            if not c.speaker:
                continue
            # The record cites event indices; the log has the timestamps.
            first = min((i for i in c.events if 0 <= i < len(events)), default=None)
            t_rel = events[first].t_rel if first is not None else 0.0
            basis = "" if c.speaker_basis == "named" else f" ({c.speaker_basis})"
            index.entries.append(Entry("npc", c.speaker, record.session, started, t_rel, c.location, c.gist + basis))
    return index


def search(index: Index, query: str, kinds: set[Kind] | None = None) -> list[Entry]:
    """Entries whose name matches ``query``, newest first."""
    q = normalize(query)
    if not q:
        return []
    hits = []
    for e in index.entries:
        if kinds and e.kind not in kinds:
            continue
        name = normalize(e.name)
        # partial_ratio finds the shorter string inside the longer, so it only
        # counts when the query is the shorter one ("malenia" must not hit Enia).
        fuzzy = len(q) >= 4 and (
            (len(name) >= len(q) and fuzz.partial_ratio(q, name) >= MATCH)
            or fuzz.ratio(q.replace(" ", ""), name.replace(" ", "")) >= MATCH
        )
        if q in name or fuzzy:
            hits.append(e)
    hits.sort(key=lambda e: (e.started, e.t_rel), reverse=True)
    return hits


def format_hits(hits: list[Entry]) -> str:
    if not hits:
        return "nothing found"
    lines = []
    for e in hits:
        h, rem = divmod(int(e.t_rel), 3600)
        m = rem // 60
        when = f"{e.started:%Y-%m-%d} +{h}h{m:02d}"
        where = f" @ {e.location}" if e.location else ""
        detail = f" — {e.detail}" if e.detail else ""
        lines.append(f"{e.kind:10s} {e.name}{where}  [{when}]{detail}")
    return "\n".join(lines)
