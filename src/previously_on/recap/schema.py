"""The structured-output contract for the recap pass, and the on-disk record.

Every structured field that names something (a speaker, an item, a place)
carries evidence: event references. A conversation belongs to one session
and cites plain indices; state entries outlive the session, so they cite
``"<session>#<index>"`` and keep the old references when carried forward.
``verify`` checks them; anything that cannot point at an event is dropped
rather than shown. The free-prose fields (``summary``, the recaps) are read by people
and audited by hand.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SpeakerBasis = Literal["named", "inferred", "unknown"]
ThreadStatus = Literal["open", "done", "unclear"]


class Conversation(BaseModel):
    """One exchange with an NPC. Subtitles carry no speaker name, so the
    speaker is the model's attribution and ``speaker_basis`` says how it
    knows: ``named`` = the name appears in the cited lines or in the previous
    state; ``inferred`` = from location or context (shown as "probably…");
    ``unknown`` = no idea, and that is fine."""

    speaker: str | None = None
    speaker_basis: SpeakerBasis = "unknown"
    location: str | None = None
    events: list[int] = Field(default_factory=list, description="indices of the dialogue events")
    gist: str = Field(description="one or two sentences: what was said, and anything asked of the player")


class Thread(BaseModel):
    """An open quest hook: someone asked the player to do something."""

    who: str
    what: str
    status: ThreadStatus = "open"
    evidence: list[str] = Field(default_factory=list, description='"<session>#<event index>" references')


class NpcState(BaseModel):
    name: str
    last_location: str | None = None
    notes: str = ""
    evidence: list[str] = Field(default_factory=list, description='"<session>#<event index>" references')


class PlaythroughState(BaseModel):
    """The rolling memory. Passed in from the previous session, returned
    updated. It is what makes a 100-hour playthrough summarisable for the
    price of one session."""

    location: str | None = Field(default=None, description="where the player was last seen")
    current_objective: str | None = None
    threads: list[Thread] = Field(default_factory=list)
    npcs: list[NpcState] = Field(default_factory=list)
    notable_items: list[str] = Field(default_factory=list)


class SessionRecap(BaseModel):
    summary: str = Field(description="what happened this session, 2-5 sentences, past tense")
    short_recap: str = Field(description="for a return after days: current objective and the last major event")
    full_recap: str = Field(description="for a return after weeks: the full 'Previously on…'")
    state: PlaythroughState
    conversations: list[Conversation] = Field(default_factory=list)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class RecapRecord(BaseModel):
    """What is written beside the session log."""

    session: str  # the .jsonl stem
    game: str
    generated_at: datetime
    model: str
    usage: Usage = Field(default_factory=Usage)
    recap: SessionRecap
    dropped: list[str] = Field(default_factory=list)  # what verification removed, and why
