"""Game profiles.

Everything a game contributes lives behind ``GameProfile``: which process to
watch for, which HUD regions to read, and how to turn OCR text from a region
into an event. The rest of the package never mentions a specific game.

Adding a game: write ``games/<id>.py`` implementing this protocol, register
it in ``_profiles()`` below and label real frames under
``tests/fixtures/<id>/``. Every coordinate and phrase in a profile is
measured from a frame, never recalled.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ..events import Event, EventType
from ..ocr import OcrLine
from ..regions import Region


@runtime_checkable
class GameProfile(Protocol):
    id: str
    display_name: str
    process_names: tuple[str, ...]
    aspect_ratio: tuple[int, int]
    regions: list[Region]
    cooldowns: dict[EventType, float]
    # Types deduped on type alone within their cooldown (closed-vocabulary
    # outcomes like a death or a boss kill, where differing text is OCR noise
    # or a second piece of evidence for the same thing). Missing = none.
    dedupe_by_type: set[EventType]
    # Seconds to skip OCR on a region after it produced an event (its
    # content is known; a boss bar stays up all fight). Missing = 0.
    quiet_after_event: dict[str, float]
    # A few lines for the recap model on how this game's events read (what a
    # checkpoint is called, that subtitles carry no speaker name). Missing = "".
    recap_notes: str

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        """Turn OCR output from ``region`` into ``(type, text, confidence)`` events.

        Usually zero or one; a stacked item-pickup list yields several.
        ``frame`` is the full BGR frame for pixel-level checks (e.g. "is the
        boss HP bar actually drawn under this name?"); it may be ``None``.
        Bias toward precision: returning nothing is always safe; a wrong
        event erodes trust far more than a missed one.
        """
        ...


def _profiles() -> dict[str, GameProfile]:
    from .eldenring import EldenRingProfile
    from .sekiro import SekiroProfile
    from .ds2 import Ds2Profile
    from .ds3 import Ds3Profile
    from .dsr import DsrProfile

    return {p.id: p for p in (EldenRingProfile(), DsrProfile(), Ds3Profile(), Ds2Profile(), SekiroProfile(),)}


def list_profiles() -> list[GameProfile]:
    return list(_profiles().values())


def get_profile(game_id: str) -> GameProfile:
    profiles = _profiles()
    try:
        return profiles[game_id]
    except KeyError:
        raise KeyError(f"unknown game {game_id!r}; available: {', '.join(profiles)}") from None


__all__ = ["GameProfile", "Event", "get_profile", "list_profiles"]
