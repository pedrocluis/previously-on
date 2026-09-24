"""Dark Souls III profile (PC, 16:9).

Region coordinates and the rules below were measured from a 1080p60 YouTube
playthrough (``recordings/ds3/``, gitignored; ``t`` in the comments is the
second within chunk 00 unless noted) with the add-game survey, then checked
with ``previously-on calibrate --game ds3``. Fractions are of the full frame.
The recording is the PS5 version; the HUD layout is the PC one, button
glyphs aside (they OCR as a letter and a colon, like Remastered's).
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..classify import is_all_caps, is_name_row, join_rows, match_vocab, normalize, respace, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region, crop

# Centre banners, all on one row at y ~0.50: BONFIRE LIT y 0.44-0.56,
# x 0.33-0.67 (t 438); HEIR OF FIRE DESTROYED 0.455-0.547, x 0.17-0.83
# (t 591); EMBER RESTORED 0.45-0.555, x 0.25-0.74 (t 596); SOULS RETRIEVED
# 0.43-0.565, x 0.24-0.76 (t 2025); DARK SPIRIT DESTROYED x 0.16-0.84
# (t 3594); area reveals 0.44-0.53 ("High Wall of Lothric" x 0.29-0.71,
# t 1030). The band is wide because the boss banner nearly spans the frame,
# and stops at 0.60: the second row of a stacked pickup sits at 0.657 and
# the invasion notice at 0.70 (t 3463). The title splash (h 0.195, t 0-4)
# is inside; the stoplist takes it.
CENTER_BANNER = Region("center_banner", x=0.08, y=0.40, w=0.84, h=0.20)
# Subtitles, centred at y 0.874-0.919: cutscene lines reach x 0.13-0.87
# (t 2743), NPC lines x 0.24-0.76 (t 2118). Interaction prompts share the
# band ("X :Pillage remains" at y 0.87, t 507) and are rejected on their
# button glyph. The "Estus Flask" HUD label (x 0.12-0.19, y 0.917-0.943)
# and the streamer watermark (x 0.80-0.97, y 0.907-0.95) reach into the
# bottom of the strip by a few pixels; the label is stripped from the text.
SUBTITLE = Region("subtitle", x=0.12, y=0.855, w=0.76, h=0.07)
# Boss name, left-aligned at x 0.29, y 0.802-0.832 ("Iudex Gundyr", t 545;
# "Vordt of the Boreal Valley", t 2530). The strip stops above the bar's
# top border line (0.8315): the red fill under it changes with every hit.
BOSS_BAR = Region("boss_bar", x=0.28, y=0.796, w=0.45, h=0.034)
# The bar itself: two thin *light* border lines at y 0.8315 and 0.8444
# spanning x 0.29-0.81, a red fill under the top one that shrinks as the
# boss loses HP and a dark grey trough where it has gone.
BOSS_HP_BAR = Region("boss_hp_bar", x=0.30, y=0.826, w=0.50, h=0.024)
# A second boss gets its own bar 0.0602 higher (Demon in Pain above Demon
# from Below, chunk 08 t 350: border lines at 0.7713/0.7843 and
# 0.8315/0.8444). A raised copy of the strip and the bar catches it.
BOSS_BAR_RAISED = Region("boss_bar_raised", x=0.28, y=0.7358, w=0.45, h=0.034)
BOSS_HP_BAR_RAISED = Region("boss_hp_bar_raised", x=0.30, y=0.7658, w=0.50, h=0.024)
# Item pickups: a dark panel x 0.27-0.72 framed by light ornament lines —
# icon at x 0.33-0.37, name left-aligned at x 0.39 (y 0.768-0.796), count
# right-aligned at x 0.66 ("Titanite Shard  1", t 507) — with "X :OK" in
# its own box below (y 0.86-0.88). Pickups stack *upward* 0.11 apart
# (Titanite Shard + Ember, t 1544: rows at y 0.67 and 0.78); the crop
# takes two rows. A third row would sit at 0.56, inside the banner band;
# not covered. The panel is drawn with the HUD hidden (t 507): the game
# fades its HUD out of combat, so nothing here gates on it.
ITEM_POPUP = Region("item_popup", x=0.30, y=0.60, w=0.42, h=0.20)

BANNER_VOCAB: dict[str, EventType] = {
    # Dark red on a darkened scene, dim (V 35-60 on the letters at its
    # brightest, near black a second later). The playthrough never shows
    # one (its deaths are edited out; a SOULS RETRIEVED banner at t 2025
    # is the bloodstain from a cut death), so the frames come from a
    # second recording (tests/fixtures/ds3/README.md).
    "YOU DIED": EventType.DEATH,
    # t 591 (Iudex Gundyr), 2577 (Vordt of the Boreal Valley).
    "HEIR OF FIRE DESTROYED": EventType.BOSS_DEFEATED,
    # Chunk 03 t 816 (Abyss Watchers): the Lords of Cinder get their own
    # banner, same font and band.
    "LORD OF CINDER FALLEN": EventType.BOSS_DEFEATED,
    # t 438, 599, 734, 1047, 1411, 2584, 2661, 3132, 3474. Never names
    # the bonfire.
    "BONFIRE LIT": EventType.CHECKPOINT_DISCOVERED,
}
# A centred banner that only half-matches the vocabulary ("HEIR OFFIRE
# DESTROYED" scores 97, but a fragment cut by the crop may not) is a
# mangled banner, never a place name.
BANNER_PARTIAL_REJECT = 80.0

# Area-reveal banners seen so far, for snapping OCR slips to the real name.
# Unknown names are kept as read, so the list need not be complete — but
# every entry here was read from a frame.
KNOWN_AREAS = (
    "Cemetery of Ash",  # t 263 (the fade-in reads "emetery of Ash")
    "Firelink Shrine",  # t 673
    "High Wall of Lothric",  # t 1030 (a mid-fade read gave "High Wall ofL")
    "Undead Settlement",  # t 2657
    "Road of Sacrifices",  # chunk 01 t 1300
    "Cathedral of the Deep",  # chunk 01 t 3122 (chunk 02 t 1885 read "Iof the Deep" + "Cathedral")
    "Farron Keep",  # chunk 02 t 2083
    "Catacombs of Carthus",  # chunk 03 t 967
    "Smouldering Lake",  # chunk 03 t 2357, read as two boxes on one row
    "Irithyll of the Boreal Valley",  # chunk 03 t 2728 ("Irithyllc" + "of the Boreal Valley")
    "Anor Londo",  # chunk 04 t 1998
    "Irithyll Dungeon",  # chunk 04 t 2916
    "Profaned Capital",  # chunk 05 t 38
    "Lothric Castle",  # chunk 05 t 1617
    "Consumed King's Garden",  # chunk 05 t 1670, read as two boxes
    "Untended Graves",  # chunk 05 t 2156
    "Archdragon Peak",  # chunk 05 t 3543
    "Grand Archives",  # chunk 06 t 1834
    "Painted World of Ariandel",  # chunk 06 t 3280 (read "Painted Wod of Ariandel")
)
KNOWN_AREA_MATCH = 85.0

# Centre-screen text that is not an event and must never become an "area".
BANNER_STOPLIST = {
    # Using an ember, or the bonfire restoring it (t 596, 1998). Same font
    # and band as the event banners; not one of the event types.
    "EMBER RESTORED",
    # t 2025: souls recovered from the bloodstain. Implies a death (the
    # one that dropped it), but that death has its own banner.
    "SOULS RETRIEVED",
    # t 3594: an invader killed (an NPC one here, "Mad dark spirit Holy
    # Knight Hodrick has died" at y 0.71). Player invaders get the same
    # banner and there is no boss bar to credit it to, so it is not an
    # enemy_defeated; the notice above it names the invader if that is
    # ever wanted.
    "DARK SPIRIT DESTROYED",
    # The title splash (t 0-4, h 0.195): OCR reads "-DARK SOULSⅡI".
    "DARK SOULS III",
}
_BANNER_STOPLIST_NOSPACE = {s.replace(" ", "") for s in BANNER_STOPLIST}
# Matched fuzzily: OCR turned SOULS RETRIEVED into "JULS RETRIEVED" (t 2027)
# and the splash's roman numeral into a stray "I". No known area scores
# above 45 against any entry.
BANNER_STOPLIST_MATCH = 85.0

# The "Estus Flask" HUD label, glued to the front of a subtitle or read on
# its own; only its top few pixels fall inside the strip, so the read is a
# fragment ("Flask", "Estus", "EstusFlask").
_ESTUS_LABEL = re.compile(r"^\W*(?:(?i:Estus)\s*(?:F(?:l(?:a(?:sk?)?)?)?)?|Flask)\s*(?:[+f]\s*[0-9Ili|]{0,2})?\s*")
# Button glyphs OCR as a letter and a colon: "X :OK", ":Pillage remains",
# "X :OK O :Close" (the menu hint row at y 0.86, x 0.13-0.22, shares the
# subtitle strip).
_BUTTON_PROMPT = re.compile(r"(?:^|\s)[A-Z]\s?[:：]|[:：]\s?[A-Z]")
# The end credits (juggernaut4's `c8DyAJgWCxY`, recordings/ds3/credits/)
# scroll through the subtitle strip. At 2 fps the detector happened to log
# none of it, but read every half second 36 lines pass as speech: staff rows
# with the company in brackets ("Maaya Kawamura (Teco Co.,Lid.)",
# "(Tricrest,inc)"), the publisher's offices ("BANDAI NAMCO
# EntertainmentEuropeSA.S."), and the licence block ("Uses Bink
# Video.Copyright © 1997-2016 by RAD Game Tools, Inc.", "…trademarks of
# Autodesk, Inc."). The title screen's line ("Dark Souls™ Ⅲ & ©2016 BANDAI
# NAMCO Entertainment Inc.") is the same thing, and chunk 00 had logged it
# as dialogue at t 1. Brackets, a company suffix ("Co." however the rest is
# misread), a copyright word or sign, "rights reserved", "trademark", a year
# range, a web address or the publisher's name: none of the 899 dialogue
# lines of the ten chunks has one (not "lad" or "lid", which are words).
# A staff row without a company is a row of names (`classify.is_name_row`).
_CREDITS_TOKEN = re.compile(
    r"[()@©®]|(?i:\b(?:inc|ltd|llc|corp|copyright)\b|\bwww\.|\.com\b|rights\s*reserved|trademark|bandai\s*namco)"
    r"|\b(?:Co|CO)\b[.,]|[A-Z]{12,}|\b(?:19|20)\d\d\s*-\s*(?:19|20)\d\d"
)

_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_END = set(".!?,;:…'\")»")
# Names are Latin text; OCR garbage from icons and effects often comes back as CJK glyphs.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")

# Banner text is tall: the shortest banner read is 0.073 ("Firelink
# Shrine", t 673), the tallest 0.134 ("SOULS RETRIEVED"). Everything else
# that passes through the band — item rows (0.028), damage numbers
# (0.025), menu labels (0.030) — is under 0.045.
MIN_BANNER_HEIGHT = 0.06
# A banner is alone in the band and centred; menus fill it with many small
# left-aligned labels.
MAX_BANNER_LINES = 2
BANNER_CENTER_TOLERANCE = 0.06
# The boss name starts at x 0.29 of the frame = 0.02 of the crop; a pickup
# name cut by the strip's top edge starts at 0.24, menu labels further right.
BOSS_NAME_MAX_X0 = 0.08
# Item names start at x 0.39 of the frame = 0.21 of the crop on every
# fixture. Menu lists cut by the crop's left edge start at 0.0.
ITEM_NAME_X0 = (0.17, 0.25)
# The count column: "1" at x 0.66 of the frame = 0.86 of the crop.
ITEM_COUNT_COLUMN_X0 = 0.80
# Pickup rows sit at fixed heights: the panel grows upward from the row at
# y 0.768-0.796 of the frame (0.905 of the crop, centre) in 0.11 steps
# (the upper row of a stack at 0.657-0.685, 0.36 of the crop). The
# invasion notices ("Invaded by dark spirit Obscur!", "Dark spirit
# Yellowfinger Heysel has died", chunk 01 t 3361 / 2327) are drawn on a
# panel styled like a pickup's — dark, ornament lines above and below —
# but at y 0.697-0.726, between the rows.
ITEM_ROW_CENTERS = (0.905, 0.36)
ITEM_ROW_TOLERANCE = 0.06
# Decorative flourishes beside a banner OCR as a tiny box of 1-3 letters.
FLOURISH_MAX_WIDTH = 0.05
# A pickup panel holds two name rows at most in the crop (the count column
# is digits); more boxes than that is a menu or the credits.
MAX_ITEM_LINES = 3


class Ds3Profile:
    id = "ds3"
    display_name = "Dark Souls III"
    # PCGamingWiki's name for the executable; unverified on the PC.
    process_names = ("DarkSoulsIII.exe",)
    aspect_ratio = (16, 9)
    regions = [CENTER_BANNER, SUBTITLE, BOSS_BAR, BOSS_BAR_RAISED, ITEM_POPUP]
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
        CENTER_BANNER.name: 3.0,
        ITEM_POPUP.name: 1.5,
        SUBTITLE.name: 1.5,
    }
    recap_notes = (
        "Checkpoints are bonfires; the banner reads BONFIRE LIT and never names the bonfire. "
        "Area names appear as banners on entry and replay on every visit. Subtitles carry no "
        "speaker name; NPCs rarely introduce themselves. A boss kill shows HEIR OF FIRE DESTROYED "
        "and the boss's soul is logged as an item pickup right after it (\"Soul of Boreal Valley "
        "Vordt\"). Souls picked up (Fading Soul, Soul of an Unknown Traveler) and Embers are "
        "consumable currency, not story items; a gesture learned at a bonfire or from an NPC "
        "(\"Rest\") comes through the same pickup panel, as does joining a covenant (\"Way of "
        "Blue\"). Deaths in the open world are logged the same as deaths to a boss. "
        "A boss bar name can be misread by a letter; keep the transcript's spelling."
    )
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
            return self._item_popup(lines, frame)
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
        rows = join_rows(
            [
                l
                for l in confident
                if re.search(r"[A-Za-z]", l.text) and not (l.width < FLOURISH_MAX_WIDTH and len(l.text) <= 3)
            ]
        )
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
            return typ, phrase, min(conf, score / 100.0)
        norm = normalize(joined)
        if any(fuzz.partial_ratio(norm, normalize(v)) >= BANNER_PARTIAL_REJECT for v in BANNER_VOCAB):
            return None
        # Other tall centred text is an area reveal. Area names are drawn in
        # Title Case ("Undead Settlement"); every all-caps banner is a fixed
        # phrase, so an all-caps read that matched nothing is a mangled one
        # or a stoplisted notice, never a place.
        name = _tidy_name(joined)
        squashed = norm.replace(" ", "")
        # A mid-fade read loses the first letter ("emetery of Ash", t 261)
        # or glues words ("UndeadS&ttlement", t 2964); a read that snaps
        # to a known area is taken on that strength, an unknown name has
        # to look like one.
        snapped = _snap_area(name)
        if (
            conf >= self.MIN_CONF[CENTER_BANNER.name]
            and 1 <= word_count(norm) <= 5
            and len(norm) >= 4
            and not is_all_caps(joined)
            and not any(fuzz.ratio(squashed, s) >= BANNER_STOPLIST_MATCH for s in _BANNER_STOPLIST_NOSPACE)
            and not _HAS_DIGIT.search(joined)
            and _LATIN_WORD.search(joined)
            and (snapped != name or _looks_like_name(name))
        ):
            return EventType.AREA_DISCOVERED, snapped if snapped != name else respace(name), conf
        return None

    def _subtitle(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        # The flask label read on its own is not speech; glued to a line it
        # is stripped below.
        lines = [l for l in lines if re.search(r"[A-Za-z]", l.text) and not _is_estus_label(l.text)]
        if not lines:
            return None
        strong = [l for l in lines if l.conf >= 0.8]
        if strong and len(strong) < len(lines):
            lines = strong
        text = _ESTUS_LABEL.sub("", " ".join(l.text for l in join_rows(lines)).strip()).strip()
        conf = min(l.conf for l in lines)
        if conf < self.MIN_CONF[SUBTITLE.name] or word_count(text) < 3 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences (or fragments continued on the next line):
        # they end in punctuation. Labels and button hints don't.
        if text[-1] not in _SENTENCE_END:
            return None
        if _BUTTON_PROMPT.search(text) or _CREDITS_TOKEN.search(text) or is_name_row(text) or match_vocab(text, BANNER_VOCAB) is not None:
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
        # Respace first: the checks below read the name, and OCR drops the
        # spaces at random ("DemonfromBelow" passed the Title Case check
        # while "Demon fromBelow" did not).
        text = respace(" ".join(_strip_edges(w) for w in best.text.split()))
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
        return EventType.BOSS_ENGAGED, text, best.conf

    def _item_popup(self, lines: list[OcrLine], frame: np.ndarray | None) -> list[tuple[EventType, str, float]]:
        # A number anywhere left of the count column is a stat table, not
        # a pickup. The pickup's own count ("1" at 0.86) is rarely read.
        if any(l.text.strip().isdigit() and l.x0 < ITEM_COUNT_COLUMN_X0 for l in lines):
            return []
        candidates = [l for l in lines if l.x0 < ITEM_COUNT_COLUMN_X0 and re.search(r"[A-Za-z]", l.text)]
        if len(candidates) > MAX_ITEM_LINES:
            return []
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows(candidates):
            text = respace(_COUNT_SUFFIX.sub("", row.text.strip()))
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            # Left-aligned after the icon; a menu list cut by the crop edge
            # starts at 0.
            if not ITEM_NAME_X0[0] <= row.x0 <= ITEM_NAME_X0[1]:
                continue
            # And on one of the panel's rows; the invasion notice's panel
            # sits between them.
            if all(abs((row.y0 + row.y1) / 2 - c) > ITEM_ROW_TOLERANCE for c in ITEM_ROW_CENTERS):
                continue
            # Eight words: "Soul of the Blood of the Wolf" (chunk 03) is
            # seven once respaced, and Elden Ring lost a whole fight to a
            # cap set one word too tight.
            if not 1 <= word_count(text) <= 8 or not _LATIN_WORD.search(text) or _HAS_DIGIT.search(text):
                continue
            # Names are Title Case; a centre banner cut by the crop is all
            # caps, and prompts carry button glyphs.
            if text.isupper() or not _looks_like_name(text) or _BUTTON_PROMPT.search(text):
                continue
            if match_vocab(text, BANNER_VOCAB) is not None:
                continue
            # A pickup sits on the panel: dark around the name, a light
            # ornament line above and below the row.
            if frame is not None and not has_item_panel(frame, row):
                continue
            events.append((EventType.ITEM_ACQUIRED, text, row.conf))
        return events


# The bar's two border lines are 0.0129 of the frame apart (0.8315 and
# 0.8444) with a dark trough between them: the red fill and the grey
# where it has gone are both far from light.
BOSS_BAR_LINE_GAP = (0.010, 0.016)
BOSS_BAR_TROUGH_MAX = 0.10


def has_boss_hp_bar(
    frame: np.ndarray, bar: Region = BOSS_HP_BAR, min_row_fraction: float = 0.9, min_bottom_fraction: float = 0.6
) -> bool:
    """True when the bar's two light border lines span the bar strip.

    Measured on chunk 00 (1080p): with a bar drawn, one row in the top half
    of the strip is >= 0.97 light (V > 100, S < 90) across x 0.30-0.80 and
    one in the bottom half >= 0.66 (t 545: 0.97 / 0.98; t 560: 0.98 / 0.66
    over a bright arena; t 2530: 0.98 / 0.99), with the rows between them
    <= 0.08 light. The pickup panel's bottom ornament line lands at the
    same height as the top border (0.8315, up to 0.95 of the row on the
    item fixtures) and the "X :OK" box under it has a line of its own, but
    those two are 0.008 or 0.016-0.017 apart and the panel between them
    is not dark all the way across; the spacing and the trough are what
    tell the bar from the panel.
    """
    strip = crop(frame, bar)
    if strip.size == 0:
        return False
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    light = ((hsv[:, :, 2] > 100) & (hsv[:, :, 1] < 90)).mean(axis=1)
    half = len(light) // 2
    top, bottom = int(light[:half].argmax()), half + int(light[half:].argmax())
    if light[top] < min_row_fraction or light[bottom] < min_bottom_fraction:
        return False
    gap = (bottom - top) / len(light) * bar.h
    if not BOSS_BAR_LINE_GAP[0] <= gap <= BOSS_BAR_LINE_GAP[1]:
        return False
    trough = light[top + 1 : bottom]
    # The median, not the mean: the border line is two pixels thick on some
    # frames (chunk 08 t 350, a bar at full HP) and the second row lands
    # inside the trough at 0.81.
    return bool(len(trough)) and float(np.median(trough)) <= BOSS_BAR_TROUGH_MAX


# The pickup panel around a name row: on the fixtures >= 0.95 of the pixels
# right of the name (up to the count column) and in the 0.03-tall bands
# above and below the row have V < 60, and a light ornament line (>= 0.85
# of x 0.28-0.71) runs 0.035-0.045 above the row's top and 0.03-0.04 below
# its bottom (t 507: lines at y 0.728 and 0.8315 around a row at
# 0.768-0.796; t 1544: 0.6185 / 0.722 around the upper row at 0.657-0.685).
ITEM_PANEL_DARK = 0.95
ITEM_PANEL_MAX_V = 60
ITEM_PANEL_LINE = 0.85
ITEM_PANEL_LINE_X = (0.28, 0.71)
ITEM_PANEL_LINE_ABOVE = (0.025, 0.06)
ITEM_PANEL_LINE_BELOW = (0.02, 0.055)


def has_item_panel(frame: np.ndarray, row: OcrLine, region: Region = ITEM_POPUP) -> bool:
    """True when ``row`` (crop fractions) sits on the pickup panel."""
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
    if not all(p.size and float((p[:, :, 2] < ITEM_PANEL_MAX_V).mean()) >= ITEM_PANEL_DARK for p in parts):
        return False
    # The ornament lines, looked up on the full frame: the panel is wider
    # than the crop.
    fh, fw = frame.shape[:2]
    full = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    fx0, fx1 = int(ITEM_PANEL_LINE_X[0] * fw), int(ITEM_PANEL_LINE_X[1] * fw)
    top = region.y + row.y0 * region.h
    bottom = region.y + row.y1 * region.h

    def line_in(a: float, b: float) -> bool:
        ya, yb = max(0, int(a * fh)), min(fh, int(b * fh))
        if yb <= ya:
            return False
        band = full[ya:yb, fx0:fx1]
        light = ((band[:, :, 2] > 100) & (band[:, :, 1] < 90)).mean(axis=1)
        return float(light.max()) >= ITEM_PANEL_LINE

    return line_in(top - ITEM_PANEL_LINE_ABOVE[1], top - ITEM_PANEL_LINE_ABOVE[0]) and line_in(
        bottom + ITEM_PANEL_LINE_BELOW[0], bottom + ITEM_PANEL_LINE_BELOW[1]
    )


def _is_estus_label(text: str) -> bool:
    return _ESTUS_LABEL.sub("", text).strip() == ""


def _strip_edges(word: str) -> str:
    """Strip symbols from a word's edges, keeping inner ones ("Vordt's")."""
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
    # "from": "Demon from Below" (chunk 08 t 350) — the glued read passed
    # this check and the spaced one did not.
    small = {"of", "the", "and", "or", "in", "at", "on", "to", "from", "a", "an"}
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
