"""Elden Ring profile (PC, 16:9).

Region coordinates and the rules below were measured from a real 2-hour
1440p recording (see tests/fixtures/eldenring/README.md for how to re-tune
with ``previously-on calibrate``). Fractions are of the full frame.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..classify import join_rows, match_vocab, normalize, respace, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region, crop

# Centre banners: YOU DIED (y 0.47-0.54), LOST GRACE DISCOVERED (0.48-0.54),
# area reveals like "Specimen Storehouse" (0.46-0.54). Kept tight so the
# "NEW item" popup (y 0.58-0.63) and interaction prompts stay out.
# Starts at x 0.18: a streamer webcam in the top-left corner reaches 0.17.
CENTER_BANNER = Region("center_banner", x=0.18, y=0.43, w=0.64, h=0.14)
# Item pickups, lower right: a single "Beast Horn  x4" row sits at y 0.77-0.81;
# several at once stack upward in rows 0.06 apart (seen at 0.66 and 0.72).
# Names are right-aligned at x≈0.89 and grow leftwards, ~0.0055 per character
# (measured on "Remembrance of the Impaler", x 0.74-0.88); a crop starting at
# 0.73 cut "Remembrance of the Full Moon Queen" down to "brance of the Full
# Moon Queen". 0.64 leaves room for the longest name in the game (41 chars).
ITEM_POPUP = Region("item_popup", x=0.64, y=0.63, w=0.35, h=0.195)
# Boss name is left-aligned above the boss HP bar, y 0.78-0.80, x from 0.24.
# The strip stops above the bar itself (y 0.803+), whose red fill changes
# with every hit and would otherwise re-trigger OCR all fight long, and
# before the item box; the HP number at x 0.75 is not needed.
BOSS_BAR = Region("boss_bar", x=0.22, y=0.765, w=0.50, h=0.038)
# The bar under the name: a dark band with a thin light-grey border line
# spanning x 0.24-0.76. Its presence validates a boss name.
BOSS_HP_BAR = Region("boss_hp_bar", x=0.25, y=0.795, w=0.50, h=0.03)
# When a second bar is drawn above the boss bar (seen on Mohg, the Omen: a
# small bar with an icon at y 0.665) the whole block moves up by 0.051 — the
# border line measured at 0.762 instead of 0.813 — so the name is read from a
# raised copy of the strip, validated against a raised copy of the bar.
BOSS_BAR_RAISED = Region("boss_bar_raised", x=0.22, y=0.714, w=0.50, h=0.038)
BOSS_HP_BAR_RAISED = Region("boss_hp_bar_raised", x=0.25, y=0.744, w=0.50, h=0.03)
# NPC subtitles, y 0.87-0.91. Interaction prompts ("Rest at site of grace")
# sit just above at 0.83-0.87 and are stoplisted below.
SUBTITLE = Region("subtitle", x=0.15, y=0.86, w=0.70, h=0.07)

BANNER_VOCAB: dict[str, EventType] = {
    "YOU DIED": EventType.DEATH,
    "GREAT ENEMY FELLED": EventType.BOSS_DEFEATED,
    "DEMIGOD FELLED": EventType.BOSS_DEFEATED,
    "LEGEND FELLED": EventType.BOSS_DEFEATED,
    "GOD SLAIN": EventType.BOSS_DEFEATED,
    "ENEMY FELLED": EventType.ENEMY_DEFEATED,
    "LOST GRACE DISCOVERED": EventType.CHECKPOINT_DISCOVERED,
}
# A centred banner that only half-matches the vocabulary ("Jdied") is a
# mangled banner, never a place name.
BANNER_PARTIAL_REJECT = 80.0

# Area-reveal banners, for snapping OCR slips ("Stormveit Castle") to the
# real name. Unknown names are kept as read, so the list need not be complete.
KNOWN_AREAS = (
    "Chapel of Anticipation", "Stranded Graveyard", "Fringefolk Hero's Grave",
    "Limgrave", "Stormhill", "Weeping Peninsula", "Castle Morne", "Stormveil Castle", "Roundtable Hold",
    "Divine Tower of Limgrave", "Divine Tower of Liurnia", "Divine Tower of Caelid",
    "Divine Tower of East Altus", "Divine Tower of West Altus", "Isolated Divine Tower",
    "Liurnia of the Lakes", "Raya Lucaria Academy", "Caria Manor", "Moonlight Altar",
    "Caelid", "Dragonbarrow", "Redmane Castle", "Sellia, Town of Sorcery",
    "Altus Plateau", "Mt. Gelmir", "Volcano Manor", "Leyndell, Royal Capital",
    "Leyndell, Ashen Capital", "Subterranean Shunning-Grounds", "Forbidden Lands",
    "Mountaintops of the Giants", "Consecrated Snowfield", "Castle Sol",
    "Miquella's Haligtree", "Elphael, Brace of the Haligtree", "Crumbling Farum Azula",
    "Siofra River", "Nokron, Eternal City", "Deeproot Depths", "Ainsel River",
    "Ainsel River Main", "Nokstella, Eternal City", "Lake of Rot", "Mohgwyn Palace",
    "Academy of Raya Lucaria", "Bellum Highway", "Capital Outskirts", "Shaded Castle",
    "Elden Throne", "Erdtree Sanctuary", "Fractured Marika", "Three Fingers", "Cathedral of the Forsaken",
    "Gravesite Plain", "Belurat, Tower Settlement", "Castle Ensis", "Scadu Altus",
    "Shadow Keep", "Specimen Storehouse", "Cerulean Coast", "Charo's Hidden Grave",
    "Rauh Base", "Ancient Ruins of Rauh", "Jagged Peak", "Abyssal Woods", "Enir-Ilim",
    "Stone Coffin Fissure", "Finger Ruins of Rhia", "Finger Ruins of Dheo",
    "Finger Ruins of Miyr", "Hinterland", "Scaduview", "Dragon's Pit", "Ellac River",
    "Fort of Reprimand", "Midra's Manse", "Church of the Bud", "Shadow Keep, Church District",
)
KNOWN_AREA_MATCH = 85.0

# Centre-screen text that is not an event and must never become an "area".
BANNER_STOPLIST = {
    "HOST OF FINGERS VANQUISHED",
    "COOPERATOR",
    "SUMMONED TO ANOTHER WORLD",
    "RETURNED TO YOUR WORLD",
    "NEW GAME",
    "GAME OVER",
    "LOADING",
    "NEW",
    # The banner when a map fragment is read; the pickup itself is the event.
    "MAP FOUND",
    # Activating a Great Rune at its Divine Tower.
    "GREAT RUNE RESTORED",
    # Startup splash screens are big centred title-case text.
    "BANDAI NAMCO",
    "FROM SOFTWARE",
    "FROMSOFTWARE",
    "ELDEN RING",
    "SHADOW OF THE ERDTREE",
}
# The splash font loses its spaces under OCR too ("BANDAINAMCO"), so the
# stoplist is matched space-stripped like the vocabulary is.
_BANNER_STOPLIST_NOSPACE = {s.replace(" ", "") for s in BANNER_STOPLIST}
# Multiplayer outcome banners name the loser ("BLOODY FINGER VANQUISHED",
# "HOST VANQUISHED"); the last word is the tell, and OCR loses the spaces
# and mangles letters ("LOODYFINGERVANQUISHEI", "HOSTVANOUISHED"), so it is
# matched fuzzily. Not "SUMMONED": Summonwater Village scores 86 against it.
BANNER_REJECT_WORDS = ("VANQUISHED", "INVADED")
# 80: "SLOODYFINGERVANOUISHEI" (B→S, Q→O) scores exactly 80; no known area
# scores above 62.
BANNER_REJECT_MATCH = 80.0

# Interaction prompts and UI strings that can drift into the subtitle strip.
PROMPT_STOPLIST = {
    "REST AT SITE OF GRACE",
    "PICK UP ITEM",
    "TOUCH CROSS",
    "SWITCH ACTION",
    "RETRIEVE LOST RUNES",
    "OPEN",
    "TALK",
    "EXAMINE",
    "OK",
    "READ",
    "TRAVERSE THE MIST",
    "ENTER",
}

# UI strings that show up in the item box but are not item names.
ITEM_STOPLIST = {"OK", "CONFIRM", "BACK", "MAP", "MENU", "SORT", "EQUIP", "USE", "NEW"}
# Overlay toasts (Steam achievements) land in the lower-right too, and so does
# the Steam library page ("FRIENDS WHO PLAY") in the seconds between the game
# closing and the process watcher noticing; if any line in the box mentions
# one, nothing in it is a pickup.
ITEM_BOX_POISON = ("ACHIEVEMENT", "UNLOCKED", "STEAM", "FRIENDS")

_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
# A shardbearer drops its Great Rune and its Remembrance together, in one
# popup, and only when it dies — so the pair proves the kill even when the
# "DEMIGOD FELLED" banner was hidden (the first Great Rune opens a tutorial
# popup right over it). Either alone does not: the Divine Tower shows the
# rune again when it is restored, and a mausoleum duplicates Remembrances.
_GREAT_RUNE = re.compile(r"'s Great Rune$|^Great Rune of the Unborn$")
_REMEMBRANCE = re.compile(r"^Remembrance of ")
# Button glyphs OCR as a colon glued to a capitalised word (":OK", ":Close").
_BUTTON_PROMPT = re.compile(r"[:：]\s?[A-Z]")
_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_END = set(".!?,;:…'\")»")
# Names are Latin text; OCR garbage from icons and effects often comes back as CJK glyphs.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")

# Banner text is tall (~0.06-0.08 of the frame); map labels and tooltips
# that pass through the same band are ~0.02-0.03.
MIN_BANNER_HEIGHT = 0.05
# A banner is alone in the band and centred; menus fill it with many small
# left-aligned labels.
MAX_BANNER_LINES = 2
BANNER_CENTER_TOLERANCE = 0.06
# The boss name is left-aligned at the bar's edge (x 0.24 of the frame);
# item tooltips that drift into the strip start much further right.
BOSS_NAME_MAX_X0 = 0.15
# Item names are right-aligned against the count column, ending at x≈0.89 of
# the frame (0.66-0.76 of the crop). Menu labels in the same area are
# left-aligned and end much earlier.
ITEM_RIGHT_EDGE = (0.64, 0.78)
# The "xN" count column starts at ~0.90 of the frame (0.76 of the crop);
# whatever OCR makes of it ("x4", "X", "XI"), a box starting there is a
# count, not part of the name.
ITEM_COUNT_COLUMN_X0 = 0.75
_COUNT_BOX = re.compile(r"^[xX×]\s*[\dIlO|]{0,3}$")
# Decorative flourishes beside a banner OCR as a tiny box of 1-3 letters.
FLOURISH_MAX_WIDTH = 0.05


class EldenRingProfile:
    id = "eldenring"
    display_name = "Elden Ring"
    process_names = ("eldenring.exe", "start_protected_game.exe")
    aspect_ratio = (16, 9)
    regions = [CENTER_BANNER, SUBTITLE, BOSS_BAR, BOSS_BAR_RAISED, ITEM_POPUP]
    cooldowns = {
        EventType.DEATH: 8.0,
        # Long enough to cover the banner and the Great Rune pickup that
        # follows it (8 s apart when a tutorial popup delays the pickup).
        EventType.BOSS_DEFEATED: 30.0,
        EventType.ENEMY_DEFEATED: 8.0,
        EventType.CHECKPOINT_DISCOVERED: 8.0,
        # The area banner replays on every respawn and NPCs repeat their
        # lines; neither is news within ten minutes.
        EventType.AREA_DISCOVERED: 600.0,
        EventType.BOSS_ENGAGED: 120.0,
        EventType.ITEM_ACQUIRED: 8.0,
        EventType.DIALOGUE: 600.0,
    }

    # Outcomes with a fixed vocabulary: text differences within the cooldown
    # are OCR noise or, for a boss kill, the banner and the drop that proves it.
    dedupe_by_type = {
        EventType.DEATH,
        EventType.BOSS_DEFEATED,
        EventType.ENEMY_DEFEATED,
        EventType.CHECKPOINT_DISCOVERED,
    }

    quiet_after_event = {
        BOSS_BAR.name: 30.0,  # the name does not change mid-fight; fire effects would re-trigger it constantly
        BOSS_BAR_RAISED.name: 30.0,
        CENTER_BANNER.name: 3.0,  # a banner stays ~2-3 s
        ITEM_POPUP.name: 1.5,
        SUBTITLE.name: 1.5,
    }

    recap_notes = (
        "Checkpoints are Sites of Grace; the banner reads LOST GRACE DISCOVERED and never names the site. "
        "Subtitles carry no speaker name; NPCs often introduce themselves, and merchants and the same "
        "NPC can repeat lines. Item pickups are logged by name only; Remembrances and Great Runes come "
        "from boss kills. Deaths in the open world are logged the same as deaths to a boss. "
        "A boss bar name can be misread by a letter; keep the transcript's spelling."
    )

    # Minimum OCR confidence per region. Banners are crisp and must be certain;
    # subtitles are small and lossy by design.
    MIN_CONF = {
        CENTER_BANNER.name: 0.85,
        BOSS_BAR.name: 0.80,
        BOSS_BAR_RAISED.name: 0.80,
        ITEM_POPUP.name: 0.80,
        SUBTITLE.name: 0.60,
    }

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        if not lines:
            return []
        if region.name == ITEM_POPUP.name:
            return self._item_popup(lines)
        bars = {BOSS_BAR.name: BOSS_HP_BAR, BOSS_BAR_RAISED.name: BOSS_HP_BAR_RAISED}
        if region.name in bars:
            hit = self._boss_bar(lines)
            if hit and frame is not None and not has_boss_hp_bar(frame, bar=bars[region.name]):
                return []
            return [hit] if hit else []
        handler = {
            CENTER_BANNER.name: self._center_banner,
            SUBTITLE.name: self._subtitle,
        }.get(region.name)
        hit = handler(lines) if handler else None
        return [hit] if hit else []

    # -- region handlers -------------------------------------------------

    def _center_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        confident = [l for l in lines if l.conf >= 0.6]
        if len(confident) > MAX_BANNER_LINES:
            return None  # a menu full of labels and values, not a banner
        # Drop ornaments and OCR garbage (no Latin letters) before joining
        # rows, or they drag a real banner's row off-centre.
        rows = join_rows(
            [
                l
                for l in confident
                if re.search(r"[A-Za-z]", l.text) and not (l.width < FLOURISH_MAX_WIDTH and len(l.text) <= 3)
            ]
        )
        # Only tall, centred text counts as a banner; drop small labels first.
        tall = [
            l
            for l in rows
            if l.height * CENTER_BANNER.h >= MIN_BANNER_HEIGHT
            and abs((l.x0 + l.x1) / 2 - 0.5) <= BANNER_CENTER_TOLERANCE
        ]
        if not tall:
            return None
        joined = " ".join(l.text for l in tall)
        conf = min(l.conf for l in tall)
        hit = match_vocab(joined, BANNER_VOCAB)
        if hit is not None:
            typ, score, phrase = hit
            # Store the canonical phrase, not the OCR output. Combine OCR
            # confidence with match quality; both must be good.
            return typ, phrase, min(conf, score / 100.0)
        # Other tall centred text is an area reveal ("Specimen Storehouse"),
        # unless it half-matches a banner: then it is a banner OCR mangled.
        norm = normalize(joined)
        if any(fuzz.partial_ratio(norm, normalize(v)) >= BANNER_PARTIAL_REJECT for v in BANNER_VOCAB):
            return None
        # Respace before the name check: "Chapel ofAnticipation" is Title Case
        # once its space is back.
        name = respace(_tidy_name(joined))
        # Five words: "Elphael, Brace of the Haligtree" is the longest banner.
        if (
            conf >= self.MIN_CONF[CENTER_BANNER.name]
            and 1 <= word_count(norm) <= 5
            and len(norm) >= 4
            and norm.replace(" ", "") not in _BANNER_STOPLIST_NOSPACE
            and not any(fuzz.partial_ratio(norm.replace(" ", ""), w) >= BANNER_REJECT_MATCH for w in BANNER_REJECT_WORDS)
            and not _HAS_DIGIT.search(joined)
            and _LATIN_WORD.search(joined)
            and _looks_like_name(name)
        ):
            return EventType.AREA_DISCOVERED, _snap_area(name), conf
        return None

    def _subtitle(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        # A box with no letters ("1%", a HUD fragment) is never part of a line.
        lines = [l for l in lines if re.search(r"[A-Za-z]", l.text)] or lines
        # A weak box next to a clear line is OCR garbage ("AAVUA"), not speech.
        strong = [l for l in lines if l.conf >= 0.8]
        if strong and len(strong) < len(lines):
            lines = strong
        text = " ".join(l.text for l in lines).strip()
        conf = min(l.conf for l in lines)
        if conf < self.MIN_CONF[SUBTITLE.name] or word_count(text) < 3 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences (or sentence fragments continued on the next
        # line): they end in punctuation. Name rolls and labels don't.
        if text[-1] not in _SENTENCE_END:
            return None
        norm = normalize(text)
        if norm in PROMPT_STOPLIST or _BUTTON_PROMPT.search(text) or match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.DIALOGUE, text, conf

    def _boss_bar(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        # The boss's HP number shares this strip with the name; only lines
        # with letters are candidates. If OCR split the name, take the most
        # confident piece.
        named = join_rows([l for l in lines if any(c.isalpha() for c in l.text)])
        named = [l for l in named if l.x0 <= BOSS_NAME_MAX_X0]
        if not named:
            return None
        best = max(named, key=lambda l: l.conf)
        text = best.text.strip()
        # "Rennala, Queen of the Full Moon" and "Loretta, Knight of the
        # Haligtree" are six words; nothing legitimate is longer than seven.
        if best.conf < self.MIN_CONF[BOSS_BAR.name] or not 1 <= word_count(text) <= 7:
            return None
        # Tutorial popups and subtitles that stray into the strip read as
        # sentences: they end in punctuation or contain digits; names don't.
        if text[-1] in ".!?;:" or _HAS_DIGIT.search(text) or not _LATIN_WORD.search(text) or not _looks_like_name(text):
            return None
        if match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.BOSS_ENGAGED, respace(text), best.conf

    def _item_popup(self, lines: list[OcrLine]) -> list[tuple[EventType, str, float]]:
        if any(p in normalize(l.text) for l in lines for p in ITEM_BOX_POISON):
            return []
        # Drop the "x4" count if OCR read it as its own box, and the boss HP
        # number (x 0.75, y 0.78 of the frame — inside this box during a
        # fight; no item name is all digits), rejoin a name the detector
        # split into pieces, then strip a count glued onto the name. Each
        # remaining row is one pickup.
        candidates = [
            l
            for l in lines
            if not _COUNT_BOX.match(l.text.strip())
            and not l.text.strip().isdigit()
            and l.x0 < ITEM_COUNT_COLUMN_X0
            and normalize(l.text) not in ITEM_STOPLIST
        ]
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows(candidates):
            text = _COUNT_SUFFIX.sub("", row.text.strip())
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            if not ITEM_RIGHT_EDGE[0] <= row.x1 <= ITEM_RIGHT_EDGE[1]:
                continue
            if not 1 <= word_count(text) <= 6 or not _LATIN_WORD.search(text):
                continue
            events.append((EventType.ITEM_ACQUIRED, respace(text), row.conf))
        names = [e[1] for e in events]
        rune = next((e for e in events if _GREAT_RUNE.search(e[1])), None)
        if rune is not None and any(_REMEMBRANCE.match(n) for n in names):
            events.append((EventType.BOSS_DEFEATED, rune[1], rune[2]))
        return events


def has_boss_hp_bar(frame: np.ndarray, min_row_fraction: float = 0.6, bar: Region = BOSS_HP_BAR) -> bool:
    """True when the boss HP bar's light border line spans the bar strip.

    Measured on real frames: >= 0.95 of a row is light-grey when a bar is
    drawn, <= 0.15 otherwise (dark scenes, menus, credits).
    """
    strip = crop(frame, bar)
    if strip.size == 0:
        return False
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    line = (hsv[:, :, 2] > 100) & (hsv[:, :, 1] < 90)
    return float(line.mean(axis=1).max()) >= min_row_fraction


def _snap_area(name: str) -> str:
    """Replace a near-miss of a known area name with the real one."""
    norm = normalize(name)
    squashed = norm.replace(" ", "")
    best, score = None, 0.0
    for known in KNOWN_AREAS:
        target = normalize(known)
        # Compare space-stripped too: an ornament glued to the first word and a
        # dropped space ("NChapelof Anticlpauon") cost two edits on their own.
        r = max(fuzz.ratio(norm, target), fuzz.ratio(squashed, target.replace(" ", "")))
        if r > score:
            best, score = known, r
    return best if best is not None and score >= KNOWN_AREA_MATCH else name


def _looks_like_name(text: str) -> bool:
    """Title Case or ALL CAPS, i.e. every word starts with a capital.

    Judged on each word's first letter, so "Night's Cavalry (Glaive)" — the
    Consecrated Snowfield pair — passes despite the bracket.
    """
    words = [w for w in re.split(r"[\s,]+", text) if any(c.isalpha() for c in w)]
    if not words:
        return False
    small = {"of", "the", "and", "or", "in", "at", "on", "to", "a", "an"}
    return all(next(c for c in w if c.isalpha()).isupper() or w.strip("()\"'").lower() in small for w in words)


def _tidy_name(text: str) -> str:
    """Normalise an area banner for storage: "SPECIMEN STOREHOUSE" -> "Specimen Storehouse".

    Ornaments around the name OCR as stray symbols or single letters
    ("Specimen & Storehouse", "Specimen S Storehouse"); tokens without
    letters and one-letter tokens are dropped.
    """
    text = " ".join(w for w in text.split() if any(c.isalpha() for c in w) and len(w) > 1)
    if text.isupper():
        small = {"OF", "THE", "AND", "OR", "IN", "AT", "ON", "TO", "A", "AN"}
        words = text.split()
        return " ".join(w.capitalize() if (i == 0 or w not in small) else w.lower() for i, w in enumerate(words))
    return " ".join(text.split())

