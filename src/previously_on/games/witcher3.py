"""The Witcher 3: Wild Hunt profile (PC, 16:9; measured on the next-gen update).

Region coordinates and the rules below were measured from a 1080p60 YouTube
playthrough (MKIceAndFire, ``Eyob-Abhx54``, recorded in 4K on PC;
``recordings/witcher3/``, gitignored; ``t`` in the comments is the second
within chunk 00 unless noted) with the add-game survey, then checked with
``previously-on calibrate --game witcher3``. Fractions are of the full frame.

The Witcher is not built like the Souls games. Nothing is announced in a
centred banner. What the game tells the player goes into one slot on the left
of the screen: a small caps header ("NEW QUEST", "QUEST UPDATED!", "QUEST
COMPLETED!", "NEW ITEM RECEIVED") over a larger caps name ("LILAC AND
GOOSEBERRIES", "A MIRACULOUS GUIDE TO GWENT"). That slot is also where the
tutorial cards, the menus' left column and the glossary notices are drawn,
so a notice is taken only as a header *at the header's position* with a name
row directly under it. Region names come bottom-right, right-aligned, and
subtitles in two bands like Sekiro's: field lines carry the speaker's name
("Vesemir: …"), cutscene lines do not.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..classify import is_all_caps, join_rows, match_vocab, normalize, title_case, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region, crop

# -- regions -----------------------------------------------------------------
# The notice slot. Header row y 0.392-0.420 ("NEW QUEST" t 343, "QUEST
# UPDATED!" t 391, "QUEST COMPLETED!" t 2827) or 0.401-0.431 ("NEW ITEM
# RECEIVED" t 2222, "NEW CRAFTING DIAGRAM" t 3019); the name under it y
# 0.434-0.480, left-aligned with the header. The longest name of the hour,
# "TORN-OUT PAGE: FORKTAIL DECOCTION" (t 3022), ends at x 0.457. The crop
# stops at y 0.50: below it come the glossary lines a notice adds
# ("YENNEFER OF VENGERBERG" y 0.530, "GHOULS" / "VESEMIR", t 343 and 1268)
# and a completed quest's rewards ("EXPERIENCE POINTS: 10", "BAKED APPLE
# X5", t 3120), none of which is logged.
QUEST_NOTICE = Region("quest_notice", x=0.02, y=0.385, w=0.53, h=0.115)
# Region names: caps, right-aligned at x 0.939-0.941, y 0.587-0.622.
# "TEMERIA, ROAD TO VIZIMA" (t 1029, over a cutscene, with "MAY, 1272" under
# it at y 0.635-0.661, outside the crop) and "WHITE ORCHARD" (t 1569, in
# play). The cutscene cards "SOME TIME LATER..." are drawn in the same place
# (t 1378). The dialogue-choice list (x 0.62-0.79, y 0.68-0.74, t 1500) sits
# below and left of the crop.
AREA_BANNER = Region("area_banner", x=0.55, y=0.575, w=0.42, h=0.057)
# Field lines, spoken while the player walks: one row at y 0.757-0.793,
# centred, x as wide as 0.205-0.768; 145 of the 148 the first 48 minutes
# read start with the speaker's name ("Yennefer: Geralt, stop fingering my
# toiletries.", t 397).
SUBTITLE_FIELD = Region("subtitle_field", x=0.10, y=0.745, w=0.80, h=0.053)
# Cutscene and conversation lines: one or two rows at y 0.801-0.872, no
# speaker, as wide as x 0.081-0.918 ("Listen, we can work this out man to
# man…", t 2742). The HUD outside cutscenes reaches into the band from both
# edges: the quick slots bottom-left ("5 Bread" / "2 Water", x 0.09-0.12,
# y 0.83-0.88, t 1265-2828) and the control hints bottom-right ("Strong
# Attack", "Dodge", x 0.83-0.91, y 0.80-0.92) — dropped before the rows are
# joined, see _subtitle.
SUBTITLE = Region("subtitle", x=0.05, y=0.798, w=0.90, h=0.085)

# A boss's name, top centre above its bar: "Royal Griffin" at x 0.475-0.527,
# y 0.021-0.047 (chunk 02 t 1100 and 1160). The strip stops above the bar,
# whose fill changes on every hit. What else reaches the top centre: the
# menus' tab row (y 0.06-0.08, below the strip), the underwater "BREATH"
# label (y 0.06), a combat bark over an enemy ("Your arse is mine.", y 0.11),
# and interaction tags that float with whoever they belong to ("Talk" over
# "Ciri", anywhere) — the bar check is what rules those out.
BOSS_BAR = Region("boss_bar", x=0.30, y=0.012, w=0.40, h=0.042)
# The bar: a dark frame x 0.422-0.581, y 0.0565-0.073, silver fill for
# monsters (red for people, per the game's tutorial). Its bottom edge
# (y 0.0713) reads V 46-55 across 99 % of the width and its top edge
# (y 0.057-0.059) V 70-90, full or empty; the scene just above and below
# it is whatever the sky is. The strip covers the edges and a margin of
# scene on each side.
BOSS_HP_BAR = Region("boss_hp_bar", x=0.43, y=0.048, w=0.145, h=0.033)

# The death screen: "You Are Dead", centred, x 0.45-0.55, y 0.36-0.40
# (h 0.031-0.042), over a menu at y 0.55-0.63 (LOAD MOST RECENT SAVE / LOAD
# SAVED GAME / QUIT TO MAIN MENU). The playthrough edits its deaths out;
# the frames come from two short clips (tests/fixtures/witcher3/README.md),
# one of them 720p, which agree to 0.003.
DEATH_BANNER = Region("death_banner", x=0.35, y=0.335, w=0.30, h=0.09)

# -- vocabulary --------------------------------------------------------------
# Notice headers -> the event the name under them becomes. Headers seen and
# deliberately not here: "RECEIVED:" (experience points, t 1852), "NEW
# MARKER" (a map marker: "CROSSROADS", "NOTICE BOARD", "PLACE OF POWER",
# t 1342-3474 — markers, not places the player went), "BESTIARY ENTRY ADDED"
# ("WOLVES", t 3146). The last two are drawn at x 0.031, left of the header
# column, so NOTICE_HEADER_X rejects them before the vocabulary is asked.
NOTICE_HEADERS: dict[str, EventType] = {
    "NEW QUEST": EventType.QUEST_STARTED,
    "QUEST UPDATED": EventType.QUEST_UPDATED,
    "QUEST COMPLETED": EventType.QUEST_COMPLETED,
    "NEW ITEM RECEIVED": EventType.ITEM_ACQUIRED,
    # A diagram or formula is an item the game files elsewhere: "DIAGRAM:
    # BLUNT CROSSBOW BOLT" (t 3019), "TORN-OUT PAGE: FORKTAIL DECOCTION"
    # (t 3022).
    "NEW CRAFTING DIAGRAM": EventType.ITEM_ACQUIRED,
    "NEW ALCHEMY FORMULA": EventType.ITEM_ACQUIRED,
}
NOTICE_HEADER_MATCH = 85.0
DEATH_PHRASE = "YOU ARE DEAD"
DEATH_MATCH = 88.0
# A passer-by's bark "You're dead!" (t 2439, y 0.24, h 0.022) scores 95
# against the phrase space-stripped. The screen's line has no apostrophe
# and no "!", and is taller.
MIN_DEATH_HEIGHT = 0.028
# Header x0, frame: quest headers 0.082-0.085, item headers 0.069-0.074
# (0.061 once, with the icon read as "se": "seNEWCRAFTINGDIAGRAM", t 3019).
# Tutorial titles in the same slot are centred in their panel and start
# further right — "QUEST UPDATES" at 0.145 (t 2480), which scores 92 against
# "QUEST UPDATED", and "ACTIVE OBJECTIVE" at 0.139 (t 3357). The notice
# slides in from the left, and a frame of the slide reads "ESTUPDATED" over
# "HEBEASTOFWHII" at x0 0.095 (chunk 01 t 854) — 91 against the header, so
# the column's right edge is what rejects it.
NOTICE_HEADER_X = (0.055, 0.090)
# The name row: its top 0.010-0.045 below the header's bottom and its x0
# within 0.015 of the header's. Quest names are 0.037-0.051 tall, item names
# smaller (0.023-0.034: "A MIRACULOUS GUIDE TO GWENT", t 2222-2224). What
# rejects the other rows that sit there — "Track Quest" (0.019-0.022, x0
# 0.074), tutorial lines — is that they are not in caps; the height floor
# only keeps out the glyph noise.
NAME_GAP = (-0.005, 0.045)
NAME_X_TOLERANCE = 0.015
MIN_NAME_HEIGHT = 0.022
# A name split into two boxes continues within a word gap (frame width).
NAME_WORD_GAP = 0.02
# Items that are not worth an event: money ("CROWNS X 20", t 2794).
ITEM_STOPLIST = {"CROWNS", "ORENS", "FLORENS"}

# Quest names seen, for snapping a glued read back ("LILACANDGOOSEBERRIES",
# "AFRYING PAN SPICKAND SPAN"). Unknown quests are kept as read; every entry
# here was read from a frame. The closest pair scores well under the bar.
KNOWN_QUESTS = (
    "Kaer Morhen",  # t 343
    "Lilac and Gooseberries",  # t 1268
    "Contract: Devil by the Well",  # t 2481
    "Missing in Action",  # t 2485
    "Twisted Firestarter",  # t 2588
    "A Frying Pan, Spick and Span",  # t 2992
    "Precious Cargo",  # t 3354
    "The Beast of White Orchard",  # chunk 01 t 387
    "Scavenger Hunt: Viper School Gear",  # chunk 01 t 770
    "Temerian Valuables",  # chunk 01 t 1909
    "Dirty Funds",  # chunk 01 t 2098, completed as "DIRTYFUNDS"
    "Deserter Gold",  # chunk 01 t 2222
    "On Death's Bed",  # chunk 01 t 1980, completed as "ONDEATH'SBED"
    "Evil's Soft First Touches",  # chunk 03 t 118
    "Wild at Heart",  # chunk 03 t 139
    "Contract: Missing Brother",  # chunk 03 t 207
    "Hunting a Witch",  # chunk 03 t 896
    "Bloody Baron",  # chunk 03 t 901, started as "BLOODYBARON"
    "Contract: The Beast of Honorton",  # chunk 03 t 1305
    "Contract: Shrieker",  # chunk 03 t 1311
    "Ciri's Story: The King of the Wolves",  # chunk 03 t 1583, never read with its spaces
    "Family Matters",  # chunk 03 t 2591, started as "FAMILYMATTERS"
    "Ciri's Room",  # chunk 03 t 2599
    "Fists of Fury: Velen",  # chunk 03 t 3369
    "Gwent: Velen Players",  # chunk 03 t 3373, "GWENT:VELENPLAYERS"
    "Races: Crow's Perch",  # chunk 03 t 3378, "RACES:CROW'SPERCH"
    "Contract: Jenny o' the Woods",  # chunk 04 t 989, "CONTRACT:JENNY O'THEWOODS"
    "Wandering in the Dark",  # chunk 04 t 2294, "WANDERINGINTHEDARK"
    "Imperial Audience",  # chunk 02
    "The Nilfgaardian Connection",  # chunk 02
)
KNOWN_QUEST_MATCH = 90.0

# Area names seen, for snapping a glued read back ("TEMERIA,ROADTOVIZIMA",
# "WHITEORCHARD"): the caps font loses its spaces on about half the frames.
KNOWN_AREAS = (
    "Temeria, Road to Vizima",  # t 1029
    "White Orchard",  # t 1569
    "Nilfgaardian Garrison",  # chunk 01 t 63
    "White Orchard Cemetery",  # chunk 01 t 697; 75 against "White Orchard"
    "Vizima, Capital of Occupied Temeria",  # chunk 02
    "Amavet Fortress Ruins",  # chunk 02
    "Velen, Northern Temeria",  # chunk 03 t 65, "VELEN,NORTHERNTEMERIA"
    "Northwest of the Village of Byways",  # chunk 04 t 2274, a cutscene card, read glued
)
KNOWN_AREA_MATCH = 90.0
# Cutscene cards drawn where a region name goes (t 1378-1383, read "SOME
# TIME LATER.", "SOMETIMELATER."). Matched space-stripped.
AREA_STOPLIST = {"SOME TIME LATER", "THE PREVIOUS NIGHT"}
# Those cards end in an ellipsis ("SOME TIME LATER...", "THE PREVIOUS
# NIGHT...", chunk 03 t 568); no place name does.
_ELLIPSIS = re.compile(r"(?:\.\.|…)\s*$")
AREA_STOPLIST_MATCH = 85.0
# Area banner right edge, frame: 0.939-0.941.
AREA_RIGHT_EDGE = (0.925, 0.955)
MIN_AREA_HEIGHT = 0.024  # of the frame: 0.028-0.035 on every read

# The boss name is centred on x=0.5 (0.501 on both reads).
BOSS_NAME_CENTER_TOLERANCE = 0.03

# -- subtitle guards ---------------------------------------------------------
# Subtitles are centred on x=0.5 (frame) within this much.
SUBTITLE_CENTER_TOLERANCE = 0.05
# HUD boxes pinned to a screen edge: centre outside this band and narrower
# than a subtitle row can be.
EDGE_BOX_CENTER = (0.25, 0.75)
EDGE_BOX_MAX_WIDTH = 0.20
_SENTENCE_END = set(".!?,;:…'\")»-")
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")
# A dot OCR puts in a caps name's word gap ("TWISTED.FIRESTARTER", t 2600;
# "RANSACKED.VILLAGE", t 1364).
_CAPS_DOT = re.compile(r"(?<=[A-Z])\.(?=[A-Z])")
# The caps font loses the space after a colon or comma too ("DIAGRAM:BLUNT
# CROSSBOW BOLT", t 3021; "TEMERIA,ROAD TO VIZIMA", t 1029).
_GLUED_PUNCT = re.compile(r"([:,])(?=\S)")
# A Gwent card's description is drawn centred in the cutscene band ("Morale
# Boost" over "Adds +1 to all units in the row (excluding itself).", t 2069)
# and ends like a sentence; its "+1" gives it away. No subtitle carries one.
_GAME_NUMBER = re.compile(r"\+\d|[A-Za-z]\d|\d[A-Za-z]")
# The world map's pin tooltips are drawn in the cutscene band: a caps title
# glued to its description ("PLAYER'SCURRENTPOSITION The witcher's current
# location.", "UNDISCOVEREDLOCATION Location or artifact…", "BLOWBALL Used
# in alchemy.", "TEMERIANVALUABLES Find the lost Temerian treasure…") — 20
# lines in chunks 00-02, which no rule caught until they were read against
# the log. Of the 947 lines those hours logged, none that was speech starts
# with a caps word of five letters or more; every tooltip does.
_CAPS_TITLE = re.compile(r"^[A-Z'’:,-]*[A-Z]{5}[A-Z'’:,-]*(?:\s|$)")
# The loot window's buttons, read as one row ("KTake TakeAll Compare
# Close,", chunk 01 t 2106).
_LOOT_BUTTONS = re.compile(r"(?:Take\s?All|Compare|Close)\b.*(?:Take\s?All|Compare|Close)\b")
# A field line starts with its speaker: "Vesemir: …", "Emhyr's
# Chamberlain: …", up to four words. OCR sometimes reads the colon as a
# full stop after a one-word name ("Geralt. No. Really upset him…", chunk 00
# t 1348). What else is drawn centred in the field band has no speaker: the
# loading screen's tips ("Only three out of ten boys survive the Trial of
# the Grasses…", chunk 01 t 2391), the Gwent tutorial ("To begin, you draw
# 10 cards…", chunk 00 t 2066) and the sign wheel's tooltip ("Influences
# opponents' minds.", chunk 01 t 2164). Requiring the name cost three real
# lines in three hours whose name OCR mangled or lost ("A magic trap.",
# "G ot his blood.") against four invented.
_SPEAKER = re.compile(r"^(?:(?:[A-Z][A-Za-z'’-]+\s){0,3}[A-Z][A-Za-z'’-]+\s?:|[A-Z][a-z]+\.\s)")
_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
# Small words title_case leaves lower case, plus the ones quest names use:
# "CONTRACT: DEVIL BY THE WELL" (t 2481).
_SMALL = {"of", "the", "and", "or", "in", "at", "on", "to", "a", "an", "by", "for", "with", "from"}


class Witcher3Profile:
    id = "witcher3"
    display_name = "The Witcher 3: Wild Hunt"
    process_names = ("witcher3.exe",)
    aspect_ratio = (16, 9)
    regions = [QUEST_NOTICE, AREA_BANNER, SUBTITLE_FIELD, SUBTITLE, BOSS_BAR, DEATH_BANNER]

    cooldowns = {
        EventType.DEATH: 8.0,
        EventType.BOSS_DEFEATED: 30.0,
        EventType.ENEMY_DEFEATED: 8.0,
        EventType.CHECKPOINT_DISCOVERED: 8.0,
        EventType.AREA_DISCOVERED: 600.0,
        EventType.BOSS_ENGAGED: 120.0,
        EventType.ITEM_ACQUIRED: 8.0,
        EventType.DIALOGUE: 600.0,
        EventType.QUEST_STARTED: 600.0,
        # One step of a quest often updates it two or three times in half a
        # minute ("PRECIOUS CARGO" at t 3444, 3457 and 3465).
        EventType.QUEST_UPDATED: 60.0,
        EventType.QUEST_COMPLETED: 600.0,
    }
    dedupe_by_type = {EventType.DEATH, EventType.BOSS_DEFEATED, EventType.ENEMY_DEFEATED}
    # No defeat banner: when the Royal Griffin dies (chunk 02 t 1168) its bar
    # just goes, and a quest update follows. A fight's outcome is unknown, so
    # stats must not call the boss "still standing".
    closes_fights = False
    # A notice stays up ~4 s and an area name ~6 s; both are read on every
    # frame of it, and the deduper keeps the best read.
    quiet_after_event = {
        QUEST_NOTICE.name: 1.0,
        AREA_BANNER.name: 1.0,
        SUBTITLE.name: 1.5,
        SUBTITLE_FIELD.name: 1.5,
        BOSS_BAR.name: 30.0,
        DEATH_BANNER.name: 3.0,
    }
    recap_notes = (
        "The Witcher 3 announces quests: quest_started, quest_updated and quest_completed carry the "
        "quest's name as the game shows it. A quest is finished only when quest_completed says so. "
        "Names starting with \"Contract:\" are witcher contracts (monster-hunting jobs). "
        "Field subtitles start with the speaker's name (\"Vesemir: Let's go.\"); that names the speaker. "
        "Cutscene and conversation subtitles carry no speaker name. The player character is Geralt. "
        "Items are only what the game announced as a new item, diagram or formula; Gwent cards are "
        "items named after characters (a card called \"Zoltan Chivay\" is not a meeting with him). "
        "Area names appear when a region is entered and on cutscene title cards. "
        "The game shows no defeat banner: a boss_engaged is never followed by boss_defeated, and "
        "the log cannot say how a fight ended. Do not call a boss beaten or still standing; say it "
        "was fought, and use what came after (a quest update, a trophy, the dialogue) only as "
        "that evidence allows."
    )
    MIN_CONF = {
        QUEST_NOTICE.name: 0.85,
        AREA_BANNER.name: 0.85,
        # Of the 1856 dialogue lines chunks 00-04 logged, one read under
        # 0.80, and it was the oil menu's "lmiunster lests." (chunk 04 t 182).
        SUBTITLE_FIELD.name: 0.80,
        SUBTITLE.name: 0.80,
        BOSS_BAR.name: 0.80,
        DEATH_BANNER.name: 0.85,
    }

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        if not lines:
            return []
        if region.name == QUEST_NOTICE.name:
            hit = self._notice(lines, frame)
        elif region.name == AREA_BANNER.name:
            hit = self._area_banner(lines)
        elif region.name in (SUBTITLE.name, SUBTITLE_FIELD.name):
            hit = self._subtitle(lines, region)
        elif region.name == DEATH_BANNER.name:
            hit = self._death(lines)
        elif region.name == BOSS_BAR.name:
            hit = self._boss_bar(lines)
            if hit and frame is not None and not has_boss_hp_bar(frame):
                hit = None
        else:
            hit = None
        return [hit] if hit else []

    # -- region handlers -------------------------------------------------

    def _notice(self, lines: list[OcrLine], frame: np.ndarray | None) -> tuple[EventType, str, float] | None:
        r = QUEST_NOTICE
        # Raw boxes, not joined rows: the header and the name are one box
        # each, and joining glued whatever else shared the header's row onto
        # it — a floating NPC tag ("QUEST COMPLETED! Merchant", chunk 01
        # t 35) or a tooltip line ("am:SerpentineSiversword NEW.QUEST",
        # chunk 01 t 771), neither of which matches the vocabulary.
        boxes = [l for l in lines if re.search(r"[A-Za-z]", l.text)]
        # Frame coordinates from here on.
        framed = [
            (l, r.x + l.x0 * r.w, r.y + l.y0 * r.h, r.y + l.y1 * r.h, l.height * r.h) for l in boxes
        ]
        for head, hx0, _, hy1, _ in framed:
            if not NOTICE_HEADER_X[0] <= hx0 <= NOTICE_HEADER_X[1]:
                continue
            hit = match_vocab(head.text, NOTICE_HEADERS, NOTICE_HEADER_MATCH)
            if hit is None or head.conf < self.MIN_CONF[QUEST_NOTICE.name]:
                continue
            typ, score, _ = hit
            below = [
                (l, x0, y0, h)
                for l, x0, y0, _, h in framed
                if l is not head
                and NAME_GAP[0] <= y0 - hy1 <= NAME_GAP[1]
                and abs(x0 - hx0) <= NAME_X_TOLERANCE
                and h >= MIN_NAME_HEIGHT
            ]
            if not below:
                return None
            name_line = _continue_right(min(below, key=lambda b: b[2])[0], boxes)
            if name_line.conf < self.MIN_CONF[QUEST_NOTICE.name]:
                return None
            if frame is not None and not has_solid_name(frame, name_line):
                return None  # the notice is dissolving; its name is half gone
            raw = _CAPS_DOT.sub(" ", name_line.text.strip())
            if typ is EventType.ITEM_ACQUIRED:
                raw = _COUNT_SUFFIX.sub("", raw)
            # The name is drawn in caps; a lower-case letter means the row
            # is a tutorial line or a menu entry that happens to sit there.
            if not is_all_caps(raw) or not _LATIN_WORD.search(raw) or not 1 <= word_count(raw) <= 10:
                return None
            if match_vocab(raw, NOTICE_HEADERS, NOTICE_HEADER_MATCH) is not None:
                return None  # two headers stacked, no name
            squashed = normalize(raw).replace(" ", "")
            if typ is EventType.ITEM_ACQUIRED and squashed in {s.replace(" ", "") for s in ITEM_STOPLIST}:
                return None
            name = _name_case(raw)
            if typ is not EventType.ITEM_ACQUIRED:
                name = _snap(name, KNOWN_QUESTS, KNOWN_QUEST_MATCH)
            return typ, name, min(head.conf, name_line.conf, score / 100.0)
        return None

    def _area_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        r = AREA_BANNER
        rows = join_rows([l for l in lines if re.search(r"[A-Za-z]", l.text)])
        rows = [
            l
            for l in rows
            if AREA_RIGHT_EDGE[0] <= r.x + l.x1 * r.w <= AREA_RIGHT_EDGE[1] and l.height * r.h >= MIN_AREA_HEIGHT
        ]
        if len(rows) != 1:
            return None
        row = rows[0]
        if row.conf < self.MIN_CONF[AREA_BANNER.name]:
            return None
        if _ELLIPSIS.search(row.text):
            return None  # a cutscene card
        raw = _CAPS_DOT.sub(" ", row.text.strip())
        if not is_all_caps(raw) or not _LATIN_WORD.search(raw) or re.search(r"\d", raw):
            return None
        squashed = normalize(raw).replace(" ", "")
        if any(fuzz.ratio(squashed, normalize(s).replace(" ", "")) >= AREA_STOPLIST_MATCH for s in AREA_STOPLIST):
            return None
        if not 1 <= word_count(raw) <= 6:
            return None
        return EventType.AREA_DISCOVERED, _snap(_name_case(raw), KNOWN_AREAS, KNOWN_AREA_MATCH), row.conf

    def _death(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        r = DEATH_BANNER
        for l in join_rows([l for l in lines if re.search(r"[A-Za-z]", l.text)]):
            cx = r.x + (l.x0 + l.x1) / 2 * r.w
            if abs(cx - 0.5) > 0.03 or l.height * r.h < MIN_DEATH_HEIGHT or l.conf < self.MIN_CONF[r.name]:
                continue
            if re.search(r"['’!]", l.text):
                continue  # "You're dead!", a bark
            squashed = normalize(l.text).replace(" ", "")
            score = fuzz.ratio(squashed, DEATH_PHRASE.replace(" ", ""))
            if score >= DEATH_MATCH:
                return EventType.DEATH, DEATH_PHRASE, min(l.conf, score / 100.0)
        return None

    def _boss_bar(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        named = join_rows([l for l in lines if re.search(r"[A-Za-z]", l.text)])
        if len(named) != 1:
            return None  # one name fits the strip
        row = named[0]
        cx = BOSS_BAR.x + (row.x0 + row.x1) / 2 * BOSS_BAR.w
        if abs(cx - 0.5) > BOSS_NAME_CENTER_TOLERANCE or row.conf < self.MIN_CONF[BOSS_BAR.name]:
            return None
        text = " ".join(row.text.split())
        if not 1 <= word_count(text) <= 6 or re.search(r"\d", text) or text[-1] in ".!?:;":
            return None
        if not _LATIN_WORD.search(text) or not _looks_like_name(text) or text.isupper():
            return None
        return EventType.BOSS_ENGAGED, text, row.conf

    def _subtitle(self, lines: list[OcrLine], region: Region) -> tuple[EventType, str, float] | None:
        def frame_x(l: OcrLine) -> tuple[float, float]:
            return region.x + l.x0 * region.w, region.x + l.x1 * region.w

        kept = []
        for l in lines:
            if not re.search(r"[A-Za-z]", l.text):
                continue
            x0, x1 = frame_x(l)
            cx = (x0 + x1) / 2
            if not EDGE_BOX_CENTER[0] <= cx <= EDGE_BOX_CENTER[1] and x1 - x0 < EDGE_BOX_MAX_WIDTH:
                continue  # quick slots, control hints
            kept.append(l)
        if not kept:
            return None
        strong = [l for l in kept if l.conf >= 0.8]
        if strong and len(strong) < len(kept):
            kept = strong
        rows = []
        for l in join_rows(kept):
            x0, x1 = frame_x(l)
            if abs((x0 + x1) / 2 - 0.5) <= SUBTITLE_CENTER_TOLERANCE:
                rows.append(l)
        if not rows:
            return None
        text = " ".join(l.text for l in rows).strip()
        conf = min(l.conf for l in rows)
        if conf < self.MIN_CONF[region.name] or word_count(text) < 2 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences (or a fragment continued on the next
        # line): they end in punctuation. Labels and button hints don't.
        if text[-1] not in _SENTENCE_END:
            return None
        if _GAME_NUMBER.search(text) or _CAPS_TITLE.match(text) or _LOOT_BUTTONS.search(text):
            return None
        if region.name == SUBTITLE_FIELD.name and not _SPEAKER.match(text):
            return None
        return EventType.DIALOGUE, text, conf


# A notice leaves by dissolving from the right while it fades, and for a
# frame or two the header still reads whole while the name is cut short:
# "QUESTUPDATED" over "TWSTEDTI" (t 2604, logged as a quest of its own
# before this check). The letters of a notice at full opacity are near
# white: the 98th percentile of V inside the name's box is 197-243 on every
# notice fixture (the lowest a warm-lit room, quest_updated_kaermorhen),
# 162 on the frame where the fade starts and 127 half-way through it.
SOLID_NAME_V = 180


def has_solid_name(frame: np.ndarray, line: OcrLine) -> bool:
    """True when the notice name in ``line`` (crop coordinates) is drawn at full opacity."""
    zone = crop(frame, QUEST_NOTICE)
    if zone.size == 0:
        return False
    h, w = zone.shape[:2]
    box = zone[int(line.y0 * h) : max(int(line.y1 * h), int(line.y0 * h) + 1), int(line.x0 * w) : max(int(line.x1 * w), int(line.x0 * w) + 1)]
    if box.size == 0:
        return False
    v = cv2.cvtColor(box, cv2.COLOR_BGR2HSV)[:, :, 2]
    return float(np.percentile(v, 98)) >= SOLID_NAME_V


def _continue_right(first: OcrLine, boxes: list[OcrLine]) -> OcrLine:
    """``first`` plus the boxes that carry its row on to the right.

    The detector sometimes splits a long name in two; a piece belongs to it
    when it sits on the same row and starts within a word gap of where the
    name so far ends. Anything further right is something else.
    """
    parts = [first]
    for box in sorted(boxes, key=lambda b: b.x0):
        last = parts[-1]
        same_row = abs((box.y0 + box.y1) / 2 - (last.y0 + last.y1) / 2) <= 0.5 * max(box.height, last.height)
        if box is not first and same_row and 0 <= (box.x0 - last.x1) * QUEST_NOTICE.w <= NAME_WORD_GAP:
            parts.append(box)
    if len(parts) == 1:
        return first
    return OcrLine(
        text=" ".join(p.text for p in parts),
        conf=min(p.conf for p in parts),
        x0=parts[0].x0,
        y0=min(p.y0 for p in parts),
        x1=parts[-1].x1,
        y1=max(p.y1 for p in parts),
    )


def _looks_like_name(text: str) -> bool:
    """Every word starts with a capital, small words aside: "Royal Griffin"."""
    words = [w for w in re.split(r"[\s,]+", text) if any(c.isalpha() for c in w)]
    if not words or not next(c for c in words[0] if c.isalpha()).isupper():
        return False
    return all(
        next(c for c in w if c.isalpha()).isupper() or w.lower().strip("'") in _SMALL or _OF_THE.match(w)
        for w in words
    )


# "o'" and "o'the" join a name like "of the": "Jenny o'the Woods" (chunk 04,
# read 78 times on her bar and rejected for its lower-case word).
_OF_THE = re.compile(r"^o['’](?:the)?$", re.IGNORECASE)


# has_boss_hp_bar: the bar's two edges must each be darker than the scene
# directly outside them, column by column, across most of its width. A
# uniformly dark scene has no such contrast and fails, which is the price:
# a fight in the dark is logged only once the scene around the bar lightens.
BAR_EDGE_CONTRAST = 30  # V: edge vs. the scene 0.003-0.008 outside it
BAR_EDGE_SHARE = 0.9  # of the columns


def has_boss_hp_bar(frame: np.ndarray, bar: Region = BOSS_HP_BAR) -> bool:
    """True when the boss bar's dark frame is drawn under the name."""
    strip = crop(frame, bar)
    if strip.size == 0 or strip.shape[0] < 12:
        return False
    v = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)[:, :, 2].astype(int)
    h = v.shape[0]

    def row(y: float) -> int:
        return min(h - 1, max(0, int((y - bar.y) / bar.h * h)))

    above = np.median(v[row(0.049) : row(0.0555) + 1], axis=0)
    below = np.median(v[row(0.0745) : row(0.080) + 1], axis=0)
    # The darkest row in each edge band, per column.
    top = v[row(0.0560) : row(0.0600) + 1].min(axis=0)
    bottom = v[row(0.0700) : row(0.0735) + 1].min(axis=0)
    top_ok = float((top <= above - BAR_EDGE_CONTRAST).mean())
    bottom_ok = float((bottom <= below - BAR_EDGE_CONTRAST).mean())
    if top_ok >= BAR_EDGE_SHARE and bottom_ok >= BAR_EDGE_SHARE:
        return True
    return has_boss_bar_fill(frame)


# In a dark scene the frame's edges are no darker than what surrounds them
# and the test above fails: "King of Wolves" (chunk 03 t 2137-2158, Ciri's
# flashback, at night) was read for twenty seconds and never logged. What
# stands out there is the fill: at the bar's left end, a light band exactly
# the bar's height between the two dark edges. On the three fight frames
# (night and day, full and nearly empty) the edges read V 4-90, the fill
# 158-192. The left end is filled whenever the boss has health left, which
# is whenever the bar is drawn.
BOSS_BAR_FILL_END = Region("boss_bar_fill_end", x=0.424, y=0.0565, w=0.016, h=0.0175)
FILL_MIN_V = 140
FILL_EDGE_CONTRAST = 80


def has_boss_bar_fill(frame: np.ndarray, end: Region = BOSS_BAR_FILL_END) -> bool:
    """True when the bar's left end holds a light fill between its dark edges."""
    zone = crop(frame, end)
    if zone.size == 0 or zone.shape[0] < 10:
        return False
    v = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)[:, :, 2].astype(int)
    h = v.shape[0]

    rows = np.median(v, axis=1)  # one value per row of the strip

    def band(y0: float, y1: float) -> np.ndarray:
        a = min(h - 1, max(0, int((y0 - end.y) / end.h * h)))
        b = min(h, max(a + 1, int(np.ceil((y1 - end.y) / end.h * h))))
        return rows[a:b]

    # The darkest row of each edge (a row either way must not matter), the
    # median of the fill.
    top = float(band(0.0565, 0.0600).min())
    fill = float(np.median(band(0.0640, 0.0697)))
    bottom = float(band(0.0700, 0.0740).min())
    return fill >= FILL_MIN_V and fill - top >= FILL_EDGE_CONTRAST and fill - bottom >= FILL_EDGE_CONTRAST


def _name_case(text: str) -> str:
    """"CONTRACT: DEVIL BY THE WELL" -> "Contract: Devil by the Well"."""
    words = title_case(" ".join(_GLUED_PUNCT.sub(r"\1 ", text).split())).split()
    # A small word after a colon starts a title of its own: "Contract: The
    # Beast of Honorton" (chunk 03 t 1305).
    return " ".join(
        w.lower() if i and w.lower() in _SMALL and not words[i - 1].endswith(":") else w
        for i, w in enumerate(words)
    )


def _snap(name: str, known: tuple[str, ...], threshold: float) -> str:
    """Replace a near-miss of a known name with the real one, compared space-stripped."""
    squashed = normalize(name).replace(" ", "")
    best, score = None, 0.0
    for k in known:
        s = fuzz.ratio(squashed, normalize(k).replace(" ", ""))
        if s > score:
            best, score = k, s
    return best if best is not None and score >= threshold else name
