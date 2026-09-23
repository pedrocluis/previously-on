"""Dark Souls II: Scholar of the First Sin profile (PC, 16:9).

Region coordinates and the rules below were measured from a 1080p60 YouTube
playthrough (``recordings/ds2/``, gitignored; ``t`` in the comments is the
second within chunk 00 unless noted) with the add-game survey, then checked
with ``previously-on calibrate --game ds2``. Fractions are of the full frame.

The game draws two kinds of banner in two places: area reveals are Title
Case mid-screen over a thin rule (``Things Betwixt``, y 0.42-0.50), event
banners (``YOU DIED``, ``BONFIRE LIT``) are caps in the lower third
(y 0.63-0.80). They get a region each.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..classify import is_all_caps, join_rows, match_vocab, normalize, respace, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region, crop

# Area reveals: Title Case, y 0.416-0.506, over a rule at 0.51 ("Things
# Betwixt" x 0.35-0.66, t 284; "Forest of Fallen Giants" x 0.29-0.71,
# t 1244); the fade-in reads taller ("Majula" 0.385-0.511, t 707). Starts
# at 0.36 so the tutorial line at y 0.28-0.31 ("You may level up by the
# power of the Emerald Herald", t 903) stays out, ends at 0.55, above the
# third row of a stacked pickup (0.585). The character-creation prompt "Try
# to recall your name" (y 0.44, h 0.035, centred, t 416) and the publisher
# splash (y 0.50, h 0.036, t 1-9) fall inside; height rejects them.
AREA_BANNER = Region("area_banner", x=0.15, y=0.36, w=0.70, h=0.19)
# Event banners: BONFIRE LIT y 0.647-0.766, x 0.32-0.68 (t 663, 746, 1277,
# 1613); YOU DIED y 0.634-0.801, x 0.30-0.69 (the death montage, see
# tests/fixtures/ds2/README.md). The band also holds the pickup panel's
# name rows (0.63-0.71), its "A: Close" button (0.775-0.805), interaction
# prompts ("A:Light bonfire", 0.763-0.796) and a cutscene subtitle row
# (0.778-0.822): all under 0.053 tall, so height tells them apart.
CENTER_BANNER = Region("center_banner", x=0.15, y=0.60, w=0.70, h=0.23)
# Subtitles: one to three rows at y0 0.774 / 0.82 / 0.86, y1 up to 0.906,
# x 0.175-0.793 on the longest line ("If that frightens you, then you ought
# to just give up right now.", t 1127). The quick-slot label bottom-left
# ("Estus Flask", "16Lifegem" — it names whatever is equipped, so unlike
# Remastered's fixed label it cannot be matched by text) sits at
# x 0.14-0.285, y 0.888-0.933. A strip ending at 0.895 lost the last row's
# full stop ("…the outer world" read without its period, t 600, and a
# subtitle without its punctuation is rejected), so the strip runs to 0.915
# and takes the label's top third: OCR reads nothing in it on the
# fixtures. The souls counter (x 0.83+, y 0.88+) stays right of the strip.
SUBTITLE = Region("subtitle", x=0.17, y=0.77, w=0.64, h=0.145)
# Boss name, left-aligned at x 0.279, y 0.808-0.842 ("Old Dragonslayer",
# chunk 01 t 1109-1173). The strip stops above the bar's top border line
# (0.850): the fill under it changes with every hit, and the damage numbers
# that pop up at the bar's right end (x 0.79-0.83, y 0.81-0.84, "147",
# "136") stay right of it.
BOSS_BAR = Region("boss_bar", x=0.27, y=0.80, w=0.45, h=0.046)
# The bar itself: two thin *black* border lines at y 0.850-0.853 and
# 0.860-0.863 spanning x 0.29-0.81, a red fill between them that shrinks
# as the boss loses HP and the scene showing through where it has gone.
# Validated on its dark lines (has_boss_hp_bar), as in Remastered.
BOSS_HP_BAR = Region("boss_hp_bar", x=0.30, y=0.846, w=0.50, h=0.020)
# A multi-boss fight stacks bars 0.0685 apart (the three Ruin Sentinels,
# chunk 02 t 803: border lines at 0.850/0.861, 0.782/0.793 and 0.713/0.725,
# names at y 0.81, 0.74 and 0.67). Raised copies of the strip and bar
# catch the second and third; the topmost strip overlaps the pickup
# panel's bottom row (0.668-0.707), which BOSS_NAME_MAX_X0 and the bar
# check keep out.
BOSS_BAR_RAISED = Region("boss_bar_raised", x=0.27, y=0.7315, w=0.45, h=0.046)
BOSS_HP_BAR_RAISED = Region("boss_hp_bar_raised", x=0.30, y=0.7775, w=0.50, h=0.020)
BOSS_BAR_RAISED_2 = Region("boss_bar_raised_2", x=0.27, y=0.663, w=0.45, h=0.046)
BOSS_HP_BAR_RAISED_2 = Region("boss_hp_bar_raised_2", x=0.30, y=0.709, w=0.50, h=0.020)
# Item pickups: a dark panel x 0.28-0.76 with an icon at x 0.30-0.32, the
# name left-aligned at x 0.322-0.326 (y 0.668-0.707 for a single row,
# t 753.5: "Soul of a Nameless Soldier" over "Lifegem"), the count "×1"
# right-aligned at x 0.73, and "A: Close" below at y 0.79. Rows stack
# *upward* 0.045 apart (0.63, 0.585); the crop takes three rows. The panel
# stays until dismissed.
ITEM_POPUP = Region("item_popup", x=0.29, y=0.57, w=0.47, h=0.15)
# The HP and stamina bars, top-left: a dark-red fill (x 0.155-0.30, y
# 0.10-0.125) over a green one (0.125-0.14). Drawn whenever the HUD is; the
# splash, menus, cutscenes and the death screen have none. The fill shrinks
# with damage — 0.29-0.32 at full HP (t 600, 663, 753), 0.11 at half HP in
# a dark scene (t 284) — so the gate is low; without a HUD the zone scores
# 0.00-0.002 (shop menu t 1855, YOU DIED).
HUD_BARS = Region("hud_bars", x=0.155, y=0.098, w=0.145, h=0.047)
HUD_BARS_MIN = 0.05

BANNER_VOCAB: dict[str, EventType] = {
    # Dark red, lower third, on a darkened scene. The playthrough never
    # shows one (its deaths are edited out), so the frames come from a
    # second recording.
    "YOU DIED": EventType.DEATH,
    # Chunk 01 t 1174 (Old Dragonslayer): y 0.66-0.76, wider than the
    # other banners (x 0.23-0.76), read "VICTORY ACHIE VED" on the fade.
    "VICTORY ACHIEVED": EventType.BOSS_DEFEATED,
    # The four Great Ones get their own banner (The Lost Sinner, chunk 02
    # t 2853): same band and font as VICTORY ACHIEVED.
    "GREAT SOUL EMBRACED": EventType.BOSS_DEFEATED,
    # t 663, 746, 1277, 1613. Never names the bonfire (the bonfire menu
    # that opens next does, top-left, but it opens on every rest).
    "BONFIRE LIT": EventType.CHECKPOINT_DISCOVERED,
}
# Lower-band banners that are not events, all rejected by the band rule
# (nothing tall there but the vocabulary is an event): "RETRIEVAL" (souls
# recovered from the bloodstain — implies a death the recording cut,
# chunk 03 t 143), "INVADER BANISHED" (an NPC invader killed, t 540; no bar
# to credit it to, so not an enemy_defeated).
# A centred banner that only half-matches the vocabulary is a mangled
# banner, never a place name.
BANNER_PARTIAL_REJECT = 80.0

# Area-reveal banners seen so far, for snapping OCR slips to the real name.
# Unknown names are kept as read, so the list need not be complete — but
# every entry here was read from a frame.
KNOWN_AREAS = (
    "Things Betwixt",  # t 284
    "Majula",  # t 705
    "Forest of Fallen Giants",  # t 1244 (a fade read gave "Forestof Fallen Giants")
    "Cathedral of Blue",  # chunk 01 t 1088
    "Heide's Tower of Flame",  # chunk 01 t 1291
    "No-man's Wharf",  # chunk 01 t 1968
    "The Lost Bastille",  # chunk 01 t 3097
    "Belfry Luna",  # chunk 02 t 1272
    "Sinners' Rise",  # chunk 02 t 2323, read "Sinners'Rise"
    "Huntsman's Copse",  # chunk 02 t 3168
    "Undead Purgatory",  # chunk 02 t 3593
    "Harvest Valley",  # chunk 03 t 1567
    "Earthen Peak",  # chunk 03 t 2149
    "Iron Keep",  # chunk 03 t 2849
    "Grave of Saints",  # chunk 04 t 1347
    "The Gutter",  # chunk 04 t 1879
    "Black Gulch",  # chunk 04 t 2689
    "Shaded Woods",  # chunk 04 t 3552
    "Doors of Pharros",  # chunk 05 t 1280
    "Brightstone Cove Tseldora",  # chunk 05 t 1644
    "Lord's Private Chamber",  # chunk 05 t 2861
    "Shrine of Winter",  # chunk 05 t 3261
    "Drangleic Castle",  # chunk 05 t 3359
    "King's Passage",  # chunk 06 t 1633
    "Shrine of Amana",  # chunk 06 t 1852 (a mid-fade read gave "Shrineof Aiman", 93)
    "Undead Crypt",  # chunk 06 t 3413
)
# No two entries score above 71 against each other ("Shrine of Winter" vs
# "Shrine of Amana"), so snapping at 85 cannot turn one into another.
KNOWN_AREA_MATCH = 85.0

# Centre-screen text that is not an event and must never become an "area".
BANNER_STOPLIST = {
    # The publisher splash, t 1-9, y 0.50: too short for the height gate,
    # listed so a taller re-render never slips through.
    "BANDAI NAMCO GAMES INC",
    "FROMSOFTWARE",
}
_BANNER_STOPLIST_NOSPACE = {s.replace(" ", "") for s in BANNER_STOPLIST}
BANNER_STOPLIST_MATCH = 85.0

# System notices share the subtitle bar and end like sentences: "Invaded
# by dark spirit Forlorn!" (chunk 03 t 503), "Dark spirit Woodland Child
# Victor has been vanquished." (chunk 04 t 2801). Not speech. They arrive
# glued to whatever else is in the strip — a menu fragment before them
# ("anyspelluses Invaded by…", t 2832) or a prompt ("Restatbonfire
# Darkspirit…", t 2801) — so the phrase is searched for space-stripped
# rather than matched at the start.
_NOTICE = ("invadedby", "hasbeenvanquished")
# The end credits and the licence screen scroll through the subtitle strip
# (chunk 08, from t 1660): staff lines carry a company in brackets
# ("nabe (Frognation Ltd)", "va (Teco Co.,Ltd.)", "ons Consultant-
# Tintagel K.K.)") and the licence text carries an address
# ("openssl-core@openssl.org.") or a long glued run of capitals
# ("LIMITEDTOTHEWARRANTIESOFMERCHANTABILITY,FITNESS..."). None of the 764
# dialogue lines the nine chunks logged has a bracket, an "@", a company
# suffix or a 12-letter run of capitals; every credits line has one. The
# four real ending lines ("Great Sovereign, take your throne.") have none.
_CREDITS_TOKEN = re.compile(r"[()@]|(?i:\b(?:inc|ltd|corp|pty)\b)|\bK\.K\.|\b(?:Co|CO)\b[.,]|[A-Z]{12,}")
# Button glyphs OCR as a letter and a colon: "A:Close", "A:Light bonfire",
# "A:Touch bloodstain", ":Select A:Done B:Back" (the menu hint row at
# y 0.91 shares the strip's bottom edge).
_BUTTON_PROMPT = re.compile(r"(?:^|\s)[A-Z]\s?[:：]|[:：]\s?[A-Z]")
_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_END = set(".!?,;:…'\")»")
# Names are Latin text; OCR garbage from icons and effects often comes back as CJK glyphs.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")
# The pickup font glues its small words: "Soul ofa Nameless Soldier"
# (t 753.5), "Soulofa Lost Undead" (t 1237, chunk 00 run). A lowercase
# token made only of small words is split back, and so is an "of…" run of
# three or more letters glued to the tail of a word of four or more
# ("Soulofa") when a capitalised word follows — no name ends that way
# ("Sofa" is too short, "Waterproof" ends in a bare "of"). A bare "of" on
# the tail is split only when the next token is itself a small word
# ("Soulof the Last Giant", chunk 01 t 113.5; classify.respace wants four
# lowercase letters before it and "Soul" has three). "HollowInfantry
# Armor" (t 1375) and "theLast" are the camel-case glue respace splits.
_SMALL_WORDS = ("of", "the", "and", "an", "a")
_SMALL_TOKEN = re.compile(r"^(?:of|the|and|an|a)+$")
_SMALL_TAIL = re.compile(r"(?<=[A-Za-z]{4})(of(?:the|and|an|a)+)(?=\s[A-Z])|(?<=[A-Za-z]{4})(of)(?=\s(?:the|an?)\s[A-Z])")

# Banner text is tall: the shortest banner read is 0.076 ("Majula",
# t 2044), VICTORY ACHIEVED 0.094-0.097, BONFIRE LIT 0.114-0.119, YOU DIED
# 0.116-0.167. Everything
# else that passes through either band — item rows (0.024-0.037),
# prompts (0.030-0.033), subtitles (up to 0.052), menu labels (0.030) — is
# under 0.055.
MIN_BANNER_HEIGHT = 0.065
# A banner is alone in the band and centred; menus fill it with many small
# left-aligned labels.
MAX_BANNER_LINES = 2
BANNER_CENTER_TOLERANCE = 0.06
# The boss name starts at x 0.279 of the frame = 0.02 of the crop; a
# pickup row under the topmost raised strip starts at x 0.322 = 0.115,
# menu labels further right or cut by the crop edge.
BOSS_NAME_MAX_X0 = 0.08
# Item names start at x 0.322-0.326 of the frame = 0.068-0.077 of the crop
# on every survey read. Menu lists cut by the crop's left edge start at 0;
# the shop's description row ("Opens Blacksmith Lenigrast's shop in
# Majula", x 0.083, t 1855) is cut the same way.
ITEM_NAME_X0 = (0.04, 0.11)
# The count column: "×1" at x 0.705-0.73 of the frame = 0.88-0.94 of the crop.
ITEM_COUNT_COLUMN_X0 = 0.85
# Decorative flourishes beside a banner OCR as a tiny box of 1-3 letters.
FLOURISH_MAX_WIDTH = 0.05
# A pickup panel holds three name rows at most (the count column is "×N",
# read as its own box or not at all).
MAX_ITEM_LINES = 4


class Ds2Profile:
    id = "ds2"
    display_name = "Dark Souls II: Scholar of the First Sin"
    process_names = ("DarkSoulsII.exe",)
    aspect_ratio = (16, 9)
    regions = [AREA_BANNER, CENTER_BANNER, SUBTITLE, BOSS_BAR, BOSS_BAR_RAISED, BOSS_BAR_RAISED_2, ITEM_POPUP]
    cooldowns = {
        EventType.DEATH: 8.0,
        EventType.BOSS_DEFEATED: 30.0,
        EventType.ENEMY_DEFEATED: 8.0,
        EventType.CHECKPOINT_DISCOVERED: 8.0,
        # The area banner replays on every entry and NPCs repeat their
        # lines; neither is news within ten minutes.
        EventType.AREA_DISCOVERED: 600.0,
        EventType.BOSS_ENGAGED: 120.0,
        # The pickup panel stays up until dismissed.
        EventType.ITEM_ACQUIRED: 8.0,
        EventType.DIALOGUE: 600.0,
    }
    dedupe_by_type = {
        EventType.DEATH,
        EventType.BOSS_DEFEATED,
        EventType.ENEMY_DEFEATED,
        EventType.CHECKPOINT_DISCOVERED,
    }
    quiet_after_event = {
        BOSS_BAR.name: 30.0,
        BOSS_BAR_RAISED.name: 30.0,
        BOSS_BAR_RAISED_2.name: 30.0,
        CENTER_BANNER.name: 3.0,
        AREA_BANNER.name: 3.0,
        ITEM_POPUP.name: 1.5,
        SUBTITLE.name: 1.5,
    }
    recap_notes = (
        "Checkpoints are bonfires; the banner reads BONFIRE LIT and never names the bonfire. "
        "Area names appear as banners on entry and replay on every visit. Subtitles carry no "
        "speaker name; NPCs rarely introduce themselves. A boss kill shows VICTORY ACHIEVED and "
        "the boss's soul (\"Old Dragonslayer Soul\") is logged as an item pickup right after it; the "
        "four Great Ones (The Lost Sinner, Old Iron King, Duke's Dear Freja, The Rotten) show "
        "GREAT SOUL EMBRACED instead. Some fights have several bars (the three Ruin Sentinels): "
        "each name is a boss_engaged of the same fight. "
        "Some encounters have no boss bar and no banner (the Pursuer's first appearance in the "
        "Forest of Fallen Giants is fought like a regular enemy), so a boss soul pickup on its own "
        "(\"Soul of the Pursuer\") proves that boss was killed. "
        "Souls picked up (Soul of a Lost Undead, Soul of a Nameless Soldier) are consumable "
        "currency, not story items; Lifegems and Estus Flask Shards are healing supplies. "
        "Deaths in the open world are logged the same as deaths to a boss. "
        "A boss bar name can be misread by a letter; keep the transcript's spelling."
    )
    MIN_CONF = {
        AREA_BANNER.name: 0.85,
        CENTER_BANNER.name: 0.85,
        BOSS_BAR.name: 0.80,
        BOSS_BAR_RAISED.name: 0.80,
        BOSS_BAR_RAISED_2.name: 0.80,
        ITEM_POPUP.name: 0.80,
        SUBTITLE.name: 0.60,
    }

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        if not lines:
            return []
        if region.name == ITEM_POPUP.name:
            if frame is not None and not has_hud(frame):
                return []
            return self._item_popup(lines, frame)
        bars = {
            BOSS_BAR.name: BOSS_HP_BAR,
            BOSS_BAR_RAISED.name: BOSS_HP_BAR_RAISED,
            BOSS_BAR_RAISED_2.name: BOSS_HP_BAR_RAISED_2,
        }
        if region.name in bars:
            hit = self._boss_bar(lines)
            if hit and frame is not None and not (has_hud(frame) and has_boss_hp_bar(frame, bar=bars[region.name])):
                return []
            return [hit] if hit else []
        handler = {
            AREA_BANNER.name: self._area_banner,
            CENTER_BANNER.name: self._center_banner,
            SUBTITLE.name: self._subtitle,
        }.get(region.name)
        hit = handler(lines) if handler else None
        return [hit] if hit else []

    # -- region handlers -------------------------------------------------

    def _tall_centred(self, lines: list[OcrLine], region: Region) -> list[OcrLine]:
        """The banner rows in a crop: few, confident, tall and centred."""
        confident = [l for l in lines if l.conf >= 0.6]
        if len(confident) > MAX_BANNER_LINES:
            return []  # a menu full of labels and values, not a banner
        rows = join_rows(
            [
                l
                for l in confident
                if re.search(r"[A-Za-z]", l.text) and not (l.width < FLOURISH_MAX_WIDTH and len(l.text) <= 3)
            ]
        )
        return [
            l
            for l in rows
            if l.height * region.h >= MIN_BANNER_HEIGHT
            and abs((l.x0 + l.x1) / 2 - 0.5) <= BANNER_CENTER_TOLERANCE
        ]

    def _center_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        tall = self._tall_centred(lines, CENTER_BANNER)
        if not tall:
            return None
        joined = " ".join(l.text for l in tall)
        conf = min(l.conf for l in tall)
        hit = match_vocab(joined, BANNER_VOCAB)
        if hit is not None:
            typ, score, phrase = hit
            return typ, phrase, min(conf, score / 100.0)
        # The lower band shows fixed phrases only; area names have their
        # own band. Anything else tall here is a mangled banner.
        return None

    def _area_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        tall = self._tall_centred(lines, AREA_BANNER)
        if not tall:
            return None
        joined = " ".join(l.text for l in tall)
        conf = min(l.conf for l in tall)
        if match_vocab(joined, BANNER_VOCAB) is not None:
            return None
        norm = normalize(joined)
        if any(fuzz.partial_ratio(norm, normalize(v)) >= BANNER_PARTIAL_REJECT for v in BANNER_VOCAB):
            return None
        # Area names are drawn in Title Case ("Things Betwixt"); an all-caps
        # read in this band is a stoplisted notice or a splash, never a
        # place.
        # Respace before the name check and the snap: the banner font glues
        # small words on a mid-fade read ("Shrine ofAmana", chunk 06
        # t 1853; "Forestof Fallen Giants", chunk 00 t 1246).
        name = respace(_tidy_name(joined))
        squashed = norm.replace(" ", "")
        # A fade-in read glues small words ("Forestof Fallen Giants",
        # t 1246); a read that snaps to a known area is taken on that
        # strength, an unknown name has to look like one.
        snapped = _snap_area(name)
        if (
            conf >= self.MIN_CONF[AREA_BANNER.name]
            and 1 <= word_count(norm) <= 5
            and len(norm) >= 4
            and not is_all_caps(joined)
            and not any(fuzz.ratio(squashed, s) >= BANNER_STOPLIST_MATCH for s in _BANNER_STOPLIST_NOSPACE)
            and not _HAS_DIGIT.search(joined)
            and _LATIN_WORD.search(joined)
            and (snapped != name or _looks_like_name(name))
        ):
            return EventType.AREA_DISCOVERED, snapped, conf
        return None

    def _subtitle(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        lines = [l for l in lines if re.search(r"[A-Za-z]", l.text)]
        if not lines:
            return None
        strong = [l for l in lines if l.conf >= 0.8]
        if strong and len(strong) < len(lines):
            lines = strong
        text = " ".join(l.text for l in join_rows(lines)).strip()
        conf = min(l.conf for l in lines)
        if conf < self.MIN_CONF[SUBTITLE.name] or word_count(text) < 3 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences (or fragments continued on the next line):
        # they end in punctuation. Labels and button hints don't.
        if text[-1] not in _SENTENCE_END:
            return None
        squashed = text.replace(" ", "").lower()
        if any(n in squashed for n in _NOTICE):
            return None
        if _BUTTON_PROMPT.search(text) or _CREDITS_TOKEN.search(text) or match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.DIALOGUE, text, conf

    def _boss_bar(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        named = join_rows([l for l in lines if any(c.isalpha() for c in l.text)])
        if len(named) > 1:
            return None  # a menu: one name fits the strip
        named = [l for l in named if l.x0 <= BOSS_NAME_MAX_X0]
        if not named:
            return None
        best = max(named, key=lambda l: l.conf)
        text = " ".join(_strip_edges(w) for w in best.text.split())
        if best.conf < self.MIN_CONF[BOSS_BAR.name] or not 1 <= word_count(text) <= 7:
            return None
        # Prompts and tooltips that stray into the strip end in punctuation
        # or carry digits or button glyphs; names don't.
        if text[-1] in ".!?;:" or _HAS_DIGIT.search(text) or not _LATIN_WORD.search(text):
            return None
        if _BUTTON_PROMPT.search(text) or not _looks_like_name(text) or text.isupper():
            return None
        if match_vocab(text, BANNER_VOCAB) is not None:
            return None
        # The name's punctuation loses its space like an item's
        # ("Aldia,Scholar of the First Sin", chunk 08 t 1288).
        return EventType.BOSS_ENGAGED, respace(text), best.conf

    def _item_popup(self, lines: list[OcrLine], frame: np.ndarray | None) -> list[tuple[EventType, str, float]]:
        # A number anywhere left of the count column is a stat table or a
        # shop grid (prices under every icon, t 1855), not a pickup.
        if any(l.text.strip().isdigit() and l.x0 < ITEM_COUNT_COLUMN_X0 for l in lines):
            return []
        candidates = [l for l in lines if l.x0 < ITEM_COUNT_COLUMN_X0 and re.search(r"[A-Za-z]", l.text)]
        if len(candidates) > MAX_ITEM_LINES:
            return []
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows(candidates):
            text = _tidy_item_punct(_unglue_small(respace(_COUNT_SUFFIX.sub("", row.text.strip()))))
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            # Left-aligned after the icon; a menu list cut by the crop edge
            # starts at 0.
            if not ITEM_NAME_X0[0] <= row.x0 <= ITEM_NAME_X0[1]:
                continue
            if not 1 <= word_count(text) <= 7 or not _LATIN_WORD.search(text) or _HAS_DIGIT.search(text):
                continue
            # Names are Title Case; a banner cut by the crop is all caps,
            # and prompts carry button glyphs.
            if text.isupper() or not _looks_like_name(text) or _BUTTON_PROMPT.search(text):
                continue
            if match_vocab(text, BANNER_VOCAB) is not None:
                continue
            if frame is not None and not has_item_panel(frame, row):
                continue
            events.append((EventType.ITEM_ACQUIRED, text, row.conf))
        return events


def has_boss_hp_bar(
    frame: np.ndarray, bar: Region = BOSS_HP_BAR, min_row_fraction: float = 0.85, max_value: float = 45
) -> bool:
    """True when the bar's two black border lines span the bar strip.

    Measured on chunk 01 (1080p): with a bar drawn, one row in the top half
    of the strip and one in the bottom half are 1.00 dark (V < 45) across
    x 0.30-0.80 (t 1110 at full HP, t 1150 mid-fight: 0.99-1.00 both). The
    fill or the scene shows between the lines (0.00-0.02 dark), so a
    uniformly dark frame would pass on the lines alone; the row midway must
    be lighter than the lines. Without a bar the rows score 0.14-0.54 on
    the same frames' scenery (t 600, 753 of chunk 00).
    """
    strip = crop(frame, bar)
    if strip.size == 0:
        return False
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    dark = (hsv[:, :, 2] < max_value).mean(axis=1)
    half = len(dark) // 2
    top, bottom = int(dark[:half].argmax()), half + int(dark[half:].argmax())
    if dark[top] < min_row_fraction or dark[bottom] < min_row_fraction:
        return False
    middle = dark[(top + bottom) // 2]
    return middle < min(dark[top], dark[bottom]) - 0.1


# The pickup panel around a name row: on every fixture >= 0.97 of the
# pixels right of the name (up to the count column) and in the 0.03-tall
# bands above and below the row have V < 60.
ITEM_PANEL_DARK = 0.95
ITEM_PANEL_MAX_V = 60


def has_item_panel(frame: np.ndarray, row: OcrLine, region: Region = ITEM_POPUP) -> bool:
    """True when ``row`` (crop fractions) sits on the pickup panel's dark background."""
    c = crop(frame, region)
    if c.size == 0:
        return False
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    h, w = c.shape[:2]
    y0, y1 = int(row.y0 * h), int(row.y1 * h)
    x_left, x_right = int(ITEM_NAME_X0[0] * w), int(ITEM_COUNT_COLUMN_X0 * w)
    margin = int(0.03 * h)
    parts = (
        hsv[y0:y1, int(row.x1 * w) : x_right],
        hsv[max(0, y0 - margin) : y0, x_left:x_right],
        hsv[y1 : min(h, y1 + margin), x_left:x_right],
    )
    return all(p.size and float((p[:, :, 2] < ITEM_PANEL_MAX_V).mean()) >= ITEM_PANEL_DARK for p in parts)


def has_hud(frame: np.ndarray) -> bool:
    """True when the HP/stamina bars are drawn (see HUD_BARS)."""
    zone = crop(frame, HUD_BARS)
    if zone.size == 0:
        return False
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 50)).mean()) >= HUD_BARS_MIN


def _tidy_item_punct(text: str) -> str:
    """Restore the spaces the pickup font drops around punctuation.

    "Pharros'Lockstone" (chunk 04 t 1658) and "Smooth&SilkyStone"
    (t 2047). Only before a capital, so "Executioner's Chariot" and
    "Pharros' Lockstone" as read correctly are left alone.
    """
    text = re.sub(r"(?<=[a-z])'(?=[A-Z])", "' ", text)
    return re.sub(r"\s*&\s*", " & ", text)


def _split_run(run: str) -> list[str]:
    words = []
    while run:
        w = next(w for w in _SMALL_WORDS if run.startswith(w))
        words.append(w)
        run = run[len(w) :]
    return words


def _unglue_small(text: str) -> str:
    """Split glued small words: "Soul ofa Lost" / "Soulofa Lost" -> "Soul of a Lost"."""
    text = _SMALL_TAIL.sub(lambda m: " " + " ".join(_split_run(m.group(1) or m.group(2))), text)
    out = []
    for token in text.split():
        if _SMALL_TOKEN.match(token) and token not in _SMALL_WORDS:
            out.extend(_split_run(token))
        else:
            out.append(token)
    return " ".join(out)


def _strip_edges(word: str) -> str:
    """Strip symbols from a word's edges, keeping inner ones ("Lenigrast's")."""
    return re.sub(r"^[^A-Za-z0-9(]+|[^A-Za-z0-9).!?,]+$", "", word)


def _snap_area(name: str) -> str:
    """Replace a near-miss of a known area name with the real one."""
    norm = normalize(name)
    squashed = norm.replace(" ", "")
    best, score = None, 0.0
    for known in KNOWN_AREAS:
        target = normalize(known)
        r = max(fuzz.ratio(norm, target), fuzz.ratio(squashed, target.replace(" ", "")))
        if r > score:
            best, score = known, r
    return best if best is not None and score >= KNOWN_AREA_MATCH else name


def _looks_like_name(text: str) -> bool:
    """Title Case or ALL CAPS: every word starts with a capital (small words aside)."""
    words = [w for w in re.split(r"[\s,]+", text) if any(c.isalpha() for c in w)]
    if not words:
        return False
    small = {"of", "the", "and", "or", "in", "at", "on", "to", "a", "an"}
    return all(next(c for c in w if c.isalpha()).isupper() or w.strip("()\"'").lower() in small for w in words)


def _tidy_name(text: str) -> str:
    """Drop ornaments read as stray symbols or single letters; title-case an all-caps read."""
    text = " ".join(_strip_edges(w) for w in text.split())
    text = " ".join(w for w in text.split() if any(c.isalpha() for c in w) and len(w) > 1)
    if text.isupper():
        small = {"OF", "THE", "AND", "OR", "IN", "AT", "ON", "TO", "A", "AN"}
        words = text.split()
        return " ".join(w.capitalize() if (i == 0 or w not in small) else w.lower() for i, w in enumerate(words))
    return " ".join(text.split())
