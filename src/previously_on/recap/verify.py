"""Grounding checks on the model's structured output.

The rule is precision over recall, same as the detector: an entry that
cannot point at an event it came from is dropped, never patched up. Free
prose is left alone — it is what the eval reads — but the structured fields
feed search and the rolling state, where an invented NPC would live forever.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..classify import normalize
from ..events import Event, EventType
from .schema import Conversation, NpcState, PlaythroughState, SessionRecap, Thread

MATCH = 85.0
MAX_ITEMS = 15  # the prompt asks for 12; anything past this is the model ignoring it
# One valid reference grounds an entry; the model keeps appending across
# sessions (Melina reached 63 by hour 15, half the output tokens). Newest kept.
MAX_REFS = 6
_ALT = re.compile(r"[/(),]")  # "Renna (Ranni)" → also try each part


def _key(text: str) -> str:
    return normalize(text).replace(" ", "")


def _mentioned(name: str, texts: list[str]) -> bool:
    """Does ``name`` occur in any of ``texts``, allowing OCR spacing and slips?"""
    k = _key(name)
    if not k:
        return False
    for t in texts:
        kt = _key(t)
        if k in kt:
            return True
        if len(k) >= 6 and fuzz.partial_ratio(k, kt) >= MATCH:
            return True
    return False


def _same(a: str, b: str) -> bool:
    return fuzz.ratio(_key(a), _key(b)) >= MATCH


def _parts(name: str) -> list[str]:
    """The name, then each piece of a combined one ("Tanith / Volcano Manor")."""
    parts = [p.strip() for p in _ALT.split(name) if p.strip()]
    return [name] + [p for p in parts if p != name]


def parse_ref(ref: str) -> tuple[str, int] | None:
    """``"20260916-220250#12"`` → ``("20260916-220250", 12)``; ``None`` if malformed."""
    session, sep, idx = ref.rpartition("#")
    if not sep or not session or not idx.isdigit():
        return None
    return session, int(idx)


def verify(
    recap: SessionRecap, events: list[Event], previous: PlaythroughState, session_id: str = ""
) -> tuple[SessionRecap, list[str]]:
    dropped: list[str] = []
    n = len(events)
    texts = [e.text for e in events]
    dialogue = [e.text for e in events if e.type is EventType.DIALOGUE]
    areas = [e.text for e in events if e.type is EventType.AREA_DISCOVERED]
    items = [e.text for e in events if e.type is EventType.ITEM_ACQUIRED]
    prior_names = [x.name for x in previous.npcs] + [t.who for t in previous.threads]
    prior_places = [previous.location] + [x.last_location for x in previous.npcs]
    prior_places = [p for p in prior_places if p]
    # References the previous state already held may be carried forward as
    # they are; a reference to an older session that was not there is made up.
    prior_refs = {r for t in previous.threads for r in t.evidence} | {r for x in previous.npcs for r in x.evidence}

    def cited(label: str, idx: list[int]) -> list[int]:
        good = [i for i in idx if 0 <= i < n]
        bad = [i for i in idx if not (0 <= i < n)]
        if bad:
            dropped.append(f"{label}: cited events {bad} do not exist")
        return good

    def cited_refs(label: str, refs: list[str]) -> tuple[list[str], list[int]]:
        """Keep valid references; return them and the indices into this session."""
        good: list[str] = []
        here: list[int] = []
        bad: list[str] = []
        for r in refs:
            parsed = parse_ref(r)
            if parsed is None:
                bad.append(r)
            elif parsed[0] == session_id or (session_id and parsed[0].endswith("-" + session_id)):
                # gpt-5.4-mini writes "20260916-20260916-214252#154" now and then;
                # the index is real, so the reference is kept in canonical form.
                if 0 <= parsed[1] < n:
                    good.append(f"{session_id}#{parsed[1]}")
                    here.append(parsed[1])
                else:
                    bad.append(r)
            elif r in prior_refs:
                good.append(r)
            else:
                bad.append(r)
        if bad:
            dropped.append(f"{label}: references {bad} do not exist")
        return good[-MAX_REFS:], here

    def place_ok(place: str | None) -> bool:
        if not place:
            return True
        return any(
            any(_same(part, a) for a in areas) or any(_same(part, p) for p in prior_places) or _mentioned(part, dialogue)
            for part in _parts(place)
        )

    def said_here(name: str, cited_texts: list[str], extra: list[str]) -> bool:
        """The log (cited lines first, then any line this session) or ``extra``
        must contain the name or, for a combined name, a part."""
        return any(
            _mentioned(part, cited_texts) or _mentioned(part, texts) or any(_same(part, x) for x in extra)
            for part in _parts(name)
        )

    def known_name(name: str, cited_texts: list[str], extra: list[str]) -> bool:
        """``said_here``, or the previous state holds the name."""
        return said_here(name, cited_texts, prior_names + extra)

    # Conversations: keep the ones with real citations; speakers must be earned.
    # A name established earlier this session ("Me. Varre.") carries to the
    # same speaker's later conversations. The previous state does not make a
    # speaker "named": knowing Gideon from last time is a guess about who is
    # talking at the Roundtable Hold tonight (the Elden Ring eval's chunk 12
    # stated it as fact with no "Gideon" in the session), so it is "inferred",
    # which the recap hedges.
    conversations: list[Conversation] = []
    named_here: list[str] = []
    for c in recap.conversations:
        c.events = cited(f"conversation {c.speaker or '?'}", c.events)
        if not c.events:
            dropped.append(f"conversation {c.speaker or '?'}: no events")
            continue
        if c.speaker and c.speaker_basis == "named":
            lines = [events[i].text for i in c.events]
            if said_here(c.speaker, lines, named_here):
                named_here.append(c.speaker)
            else:
                dropped.append(f"conversation {c.speaker}: 'named' but no line this session says the name; now inferred")
                c.speaker_basis = "inferred"
        if not c.speaker:
            c.speaker_basis = "unknown"
        if not place_ok(c.location):
            dropped.append(f"conversation {c.speaker or '?'}: location {c.location!r} not in the log")
            c.location = None
        conversations.append(c)
    recap.conversations = conversations
    speakers = [c.speaker for c in conversations if c.speaker]

    def name_ok(name: str, here: list[int]) -> bool:
        return known_name(name, [events[i].text for i in here], speakers)

    threads: list[Thread] = []
    for t in recap.state.threads:
        t.evidence, here = cited_refs(f"thread {t.who}", t.evidence)
        if not t.evidence:
            dropped.append(f"thread {t.who}: no evidence")
            continue
        if not name_ok(t.who, here):
            dropped.append(f"thread {t.who}: name not in the cited events or the previous state")
            continue
        threads.append(t)
    recap.state.threads = threads

    npcs: list[NpcState] = []
    for x in recap.state.npcs:
        x.evidence, here = cited_refs(f"npc {x.name}", x.evidence)
        if not x.evidence:
            dropped.append(f"npc {x.name}: no evidence")
            continue
        if not name_ok(x.name, here):
            dropped.append(f"npc {x.name}: name not in the cited events or the previous state")
            continue
        if not place_ok(x.last_location):
            dropped.append(f"npc {x.name}: location {x.last_location!r} not in the log")
            x.last_location = None
        npcs.append(x)
    recap.state.npcs = npcs

    keep_items = []
    for item in recap.state.notable_items:
        if any(_same(item, i) for i in items) or any(_same(item, i) for i in previous.notable_items):
            keep_items.append(item)
        else:
            dropped.append(f"item {item!r}: not picked up in the log")
    if len(keep_items) > MAX_ITEMS:
        dropped.append(f"items: {len(keep_items) - MAX_ITEMS} over the cap of {MAX_ITEMS}, oldest dropped")
        keep_items = keep_items[-MAX_ITEMS:]
    recap.state.notable_items = keep_items

    if not place_ok(recap.state.location):
        dropped.append(f"location {recap.state.location!r}: not in the log")
        recap.state.location = None

    _restore_forgotten(recap.state, previous, dropped)
    return recap, dropped


def _restore_forgotten(state: PlaythroughState, previous: PlaythroughState, dropped: list[str]) -> None:
    """The state is monotonic: the model may update an entry or mark a thread
    done, but an entry it leaves out comes back unchanged. Sonnet 5 once
    returned an empty state four hours in, erasing the playthrough memory;
    nothing about the prompt can rule that out, this does."""
    lost_npcs = [x for x in previous.npcs if not any(_same(x.name, y.name) for y in state.npcs)]
    if lost_npcs:
        state.npcs = lost_npcs + state.npcs
        dropped.append(f"restored {len(lost_npcs)} NPCs the model left out: " + ", ".join(x.name for x in lost_npcs))
    # Matched on who alone: the model rewords "what" every session, and a
    # reworded thread restored beside its new version duplicates forever.
    lost_threads = [t for t in previous.threads if not any(_same(t.who, u.who) for u in state.threads)]
    if lost_threads:
        state.threads = lost_threads + state.threads
        dropped.append(f"restored {len(lost_threads)} threads the model left out: " + ", ".join(t.who for t in lost_threads))
    lost_items = [i for i in previous.notable_items if not any(_same(i, j) for j in state.notable_items)]
    if lost_items:
        state.notable_items = (lost_items + state.notable_items)[-MAX_ITEMS:]
    if state.location is None and previous.location:
        state.location = previous.location
        dropped.append(f"restored location {previous.location!r}")
    if state.current_objective is None and previous.current_objective:
        state.current_objective = previous.current_objective
        dropped.append("restored the previous objective")
