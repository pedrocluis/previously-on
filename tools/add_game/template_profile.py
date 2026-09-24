"""{{display_name}} profile ({{aspect_w}}:{{aspect_h}}).

Scaffolded by `tools/add_game/scaffold.py` (see CONTRIBUTING.md). Every ``TODO`` below is a value that
must be measured from real frames (``survey.py``, then ``previously-on
calibrate --game {{id}}``); nothing here was verified against the game yet.
Fractions are of the full frame.
"""

from __future__ import annotations

import re

import numpy as np

from ..classify import join_rows, match_vocab, normalize, title_case, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region

# -- regions -----------------------------------------------------------------
# TODO measure each region from the survey's band table and check the crops
# with `previously-on calibrate --game {{id}} frame.jpg`: a crop must contain
# exactly the text it is for and no persistent HUD. Note the source
# resolution and frame in a comment, as games/eldenring.py does.
{{region_defs}}

# -- vocabulary --------------------------------------------------------------
# Fixed banner phrases -> generic event types. Types available:
#   DEATH, BOSS_ENGAGED, BOSS_DEFEATED, ENEMY_DEFEATED, CHECKPOINT_DISCOVERED,
#   AREA_DISCOVERED, ITEM_ACQUIRED, DIALOGUE
# TODO fill from the survey's "recurring phrases" (tall, centred, short).
BANNER_VOCAB: dict[str, EventType] = {}
# A centred banner that only half-matches the vocabulary is a mangled banner,
# never a place name.
BANNER_PARTIAL_REJECT = 80.0

# Centre-screen text that is not an event and must never become an "area":
# splash screens, multiplayer notices, tutorial titles. Matched space-stripped.
BANNER_STOPLIST: set[str] = set()
_BANNER_STOPLIST_NOSPACE = {s.replace(" ", "") for s in BANNER_STOPLIST}
# Interaction prompts and UI strings that drift into the subtitle strip.
PROMPT_STOPLIST: set[str] = set()
# UI strings that show up in the item box but are not item names.
ITEM_STOPLIST: set[str] = set()

# -- geometry guards (fractions of the region crop unless noted) --------------
# TODO confirm each against a fixture. Values are Elden Ring's, as a start.
MIN_BANNER_HEIGHT = 0.05  # of the frame: banners are tall, tooltips are not
MAX_BANNER_LINES = 2  # a menu fills the band with many small labels
BANNER_CENTER_TOLERANCE = 0.06  # of the frame width
FLOURISH_MAX_WIDTH = 0.05  # ornaments beside a banner OCR as 1-3 letter boxes

_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_END = set(".!?,;:…'\")»")
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")


class {{class_name}}:
    id = "{{id}}"
    display_name = "{{display_name}}"
    process_names = ({{process_names}},)
    aspect_ratio = ({{aspect_w}}, {{aspect_h}})
    regions = [{{region_list}}]

    # Seconds within which a repeat of the same event is the same event.
    # TODO tune: Elden Ring's values. Area banners replay on every respawn
    # and NPCs repeat their lines, hence the long ones.
    cooldowns = {
        EventType.DEATH: 8.0,
        EventType.BOSS_DEFEATED: 30.0,
        EventType.ENEMY_DEFEATED: 8.0,
        EventType.CHECKPOINT_DISCOVERED: 8.0,
        EventType.AREA_DISCOVERED: 600.0,
        EventType.BOSS_ENGAGED: 120.0,
        EventType.ITEM_ACQUIRED: 8.0,
        EventType.DIALOGUE: 600.0,
    }
    # Closed-vocabulary outcomes: differing text within the cooldown is OCR
    # noise, not a second event.
    dedupe_by_type = {
        EventType.DEATH,
        EventType.BOSS_DEFEATED,
        EventType.ENEMY_DEFEATED,
        EventType.CHECKPOINT_DISCOVERED,
    }
    # Seconds to skip OCR on a region after it produced an event.
    quiet_after_event = {{{quiet_after_event}}}
    # TODO what a checkpoint is called, whether subtitles carry a speaker
    # name, what item pickups mean — a few lines for the recap model.
    recap_notes = ""

    # Minimum OCR confidence per region: banners must be certain, subtitles
    # are small and lossy by design.
    MIN_CONF = {{{min_conf}}}

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        if not lines:
            return []
        handler = {
{{handler_map}}
        }.get(region.name)
        if handler is None:
            return []
        hits = handler(lines, frame)
        if hits is None:
            return []
        return hits if isinstance(hits, list) else [hits]

    # -- region handlers -------------------------------------------------
    # Every handler rejects by default. Loosen a rule only from a real frame
    # saved under tests/fixtures/{{id}}/ with a label, and add a unit test in
    # tests/test_classify_{{id}}.py with the real OCR read.
{{handlers}}
