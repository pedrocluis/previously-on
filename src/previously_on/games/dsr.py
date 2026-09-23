"""Dark Souls: Remastered profile (PC, 16:9).

Region coordinates and the rules below were measured from a 1080p60 YouTube
playthrough (``recordings/dsr/``, gitignored; ``t`` in the comments is the
second within chunk 00 unless noted) with the add-game survey, then checked
with ``previously-on calibrate --game dsr``. Fractions are of the full frame.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from ..classify import is_all_caps, join_rows, match_vocab, normalize, word_count
from ..events import EventType
from ..ocr import OcrLine
from ..regions import Region, crop

# Centre banners: VICTORY ACHIEVED y 0.47-0.57, x 0.24-0.77 (t 580);
# BONFIRE LIT 0.47-0.59, x 0.32-0.68 (t 354); HUMANITY RESTORED 0.475-0.585,
# x 0.21-0.79 (t 1092); area reveals 0.43-0.53 ("Northern Undead Asylum"
# x 0.24-0.76, t 316); YOU DIED is the tallest, 0.45-0.61, x 0.31-0.69
# (the death compilation, see tests/fixtures/dsr/README.md). Starts at
# 0.40 so the tutorial popup at y 0.28-0.32 ("In Lordran, level up and
# kindle at bonfires", t 672) stays out, and ends at 0.635, above the item
# popup's name row (0.685). The upper row of a stacked pickup (y
# 0.535-0.565) does fall inside; height rejects it.
CENTER_BANNER = Region("center_banner", x=0.15, y=0.40, w=0.70, h=0.235)
# Subtitles, y 0.87-0.94, centred: cutscene lines reach x 0.22-0.78 (t 204),
# NPC lines x 0.28-0.75 (t 3255). The "Estus Flask" HUD label (x 0.21-0.30)
# sits on the same row *under* long lines and OCR glues them
# ("EstusThou appearest to lack faith"), so the strip has to include it and
# _subtitle strips it from the text. The flask count (x 0.19) and the souls
# counter (x 0.87-0.92, changes on every kill) stay out.
SUBTITLE = Region("subtitle", x=0.21, y=0.865, w=0.59, h=0.08)
# Boss name, left-aligned at x 0.31, y 0.775-0.80 ("Asylum Demon", t 550).
# The strip stops above the bar's top border line (0.812): the red fill
# under it changes with every hit.
BOSS_BAR = Region("boss_bar", x=0.29, y=0.77, w=0.45, h=0.037)
# The bar itself: two thin *black* border lines at y ~0.812 and ~0.830
# spanning x 0.31-0.83, a red fill that shrinks as the boss loses HP and
# the scene showing through where it has gone. Elden Ring's bar has a light
# border; this one is validated on its dark lines (has_boss_hp_bar).
BOSS_HP_BAR = Region("boss_hp_bar", x=0.32, y=0.80, w=0.50, h=0.04)
# A second boss gets its own bar 0.063 higher (both Bell Gargoyles, t 3166:
# names at y 0.72 and 0.79, border lines at 0.749/0.766 and 0.812/0.830).
BOSS_BAR_RAISED = Region("boss_bar_raised", x=0.29, y=0.707, w=0.45, h=0.037)
BOSS_HP_BAR_RAISED = Region("boss_hp_bar_raised", x=0.32, y=0.737, w=0.50, h=0.04)
# Item pickups: a dark panel x 0.28-0.69, y 0.65-0.77 — icon at x 0.31-0.36,
# name left-aligned at x 0.37 (y 0.685-0.715), count right-aligned at x 0.67
# ("Big Pilgrim's Key  1", t 580) — with "A:OK" in its own box below
# (y 0.81-0.85). Several pickups stack *upward* 0.15 apart (Humanity +
# Homeward Bone, t 1795: rows at y 0.55 and 0.70); the crop takes two rows.
# A third row would sit at 0.40, inside the banner band; not covered.
ITEM_POPUP = Region("item_popup", x=0.30, y=0.525, w=0.39, h=0.21)
# The HP and stamina bars, top-left: saturated red and green fills. Drawn
# whenever the HUD is, and a pickup or a boss bar never appears without the
# HUD; the end credits, cutscenes and menus have none. Stamina is full when
# the player stands at a pickup; mid-fight the fills shrink but stay well
# above the gate (0.19-0.21 on the boss-bar fixtures, 0.22-0.30 on pickups,
# 0.00-0.05 without a HUD).
HUD_BARS = Region("hud_bars", x=0.135, y=0.10, w=0.135, h=0.06)
HUD_BARS_MIN = 0.10

BANNER_VOCAB: dict[str, EventType] = {
    # Dark red on a darkened scene, V well under the other banners'. The
    # playthrough never shows one (its deaths are edited out; a RETRIEVAL
    # banner at chunk 01 t 1353 is the bloodstain from a cut death), so
    # the frames come from a second recording.
    "YOU DIED": EventType.DEATH,
    # t 580 (Asylum Demon), 1790 (Taurus Demon), 3168 (Bell Gargoyles).
    "VICTORY ACHIEVED": EventType.BOSS_DEFEATED,
    # t 354, 1420, 2013, 2512. Never names the bonfire.
    "BONFIRE LIT": EventType.CHECKPOINT_DISCOVERED,
}
# A centred banner that only half-matches the vocabulary ("VICTORY ACHEVED"
# scores 97, but a fragment cut by the crop may not) is a mangled banner,
# never a place name.
BANNER_PARTIAL_REJECT = 80.0

# Area-reveal banners seen so far, for snapping OCR slips to the real name.
# Unknown names are kept as read, so the list need not be complete — but
# every entry here was read from a frame.
KNOWN_AREAS = (
    "Northern Undead Asylum",  # t 316
    "Firelink Shrine",  # t 673
    "Undead Burg",  # t 1203
    "Undead Parish",  # t 2010
    "Darkroot Garden",  # t 3471
    "Darkroot Basin",  # t 3498
    "Depths",  # chunk 01 t 1404
    "Blighttown",  # chunk 01 t 2616
    "Quelaag's Domain",  # chunk 01 t 3166
    "Valley of Drakes",  # chunk 02 t 187
    "Sen's Fortress",  # chunk 02 t 1912
    "Anor Londo",  # chunk 02 t 3128
    "New Londo Ruins",  # chunk 03 t 2804
    "The Abyss",  # chunk 03 t 3518
    "Firelink Altar",  # chunk 04 t 439 (a mid-fade read gave "Fireliok Altar")
    "The Duke's Archives",  # chunk 04 t 1021
    "Crystal Cave",  # chunk 04 t 2412
    "Demon Ruins",  # chunk 05 t 185
    "Lost Izalith",  # chunk 05 t 532
    "The Catacombs",  # chunk 05 t 1197
    "Tomb of the Giants",  # chunk 05 t 2076, drawn on two lines
    "Painted World of Ariamis",  # chunk 05 t 3557
    "Kiln of the First Flame",  # chunk 06 t 1631
)
KNOWN_AREA_MATCH = 85.0

# Centre-screen text that is not an event and must never become an "area".
BANNER_STOPLIST = {
    # Reversing hollowing at a bonfire (t 1092). Same font and band as the
    # event banners; not one of the event types.
    "HUMANITY RESTORED",
    # Chunk 01 t 2165: humanity gained from kills, a counter tick.
    "HUMANITY ACQUIRED",
    # Chunk 01 t 1353: souls recovered from the bloodstain. Implies a death
    # (the one that dropped it), but that death has its own banner.
    "RETRIEVAL",
}
_BANNER_STOPLIST_NOSPACE = {s.replace(" ", "") for s in BANNER_STOPLIST}
# Matched fuzzily: OCR turned RETRIEVAL into "RETRIEVAI" (chunk 01 t 1352),
# 89 against the entry. No known area scores above 44 against any entry.
BANNER_STOPLIST_MATCH = 85.0

# The "Estus Flask" HUD label, glued to the front of a subtitle or read on
# its own ("Estus Flask", "Estus Flask+1", "EstusThou appearest…").
# The upgrade suffix reads as "+1", "+l", "+i", "f1" or a bare "+" and glues
# onto the line's first word ("Estus Flask+iOnly unkempt crooks", chunk 01;
# "Estus Flask+A pyromancer must be", chunk 02), and the word itself is cut
# when the line covers it ("Estus" / "FlaWell, what do we have here?",
# t 689; "Estus FlAhh, hello", chunk 02).
# Only "Estus" is case-insensitive: the label's fragment is lowercase past
# the F, the line's own capital ("FlAhh") must survive.
_ESTUS_LABEL = re.compile(r"^\W*(?i:Estus)\s*(?:F(?:l(?:a(?:sk?)?)?)?\s*(?:[+f]\s*[0-9Ili|]{0,2})?)?\s*")
# Button glyphs OCR as a letter and a colon: "A:OK", "A :Rest at bonfire",
# ":Select A :Equip B :Back X :Toggle Display" (the menu hint row at y 0.90,
# x 0.08-0.53, shares the subtitle strip).
_BUTTON_PROMPT = re.compile(r"(?:^|\s)[A-Z]\s?[:：]|[:：]\s?[A-Z]")

# The end credits scroll through the subtitle strip too, and their lines
# end in "Ltd." or ")" like sentences. No subtitle in 6.6 hours contains a
# bracket, an ampersand or a company suffix ("Ltd", "INC.", "CO.,LTD.");
# every credit line has one. "Co" only with its dot or comma: Solaire's
# "jolly co-operation!" is dialogue.
_CREDITS_TOKEN = re.compile(r"[()&]|(?i:\b(?:inc|ltd|corp)\b)|\b(?:Co|CO)\b[.,]")
_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_END = set(".!?,;:…'\")»")
# Names are Latin text; OCR garbage from icons and effects often comes back as CJK glyphs.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")

# Banner text is tall: the shortest banner read is 0.078 ("Undead Parish",
# t 2871), the tallest 0.118 ("BONFIRE LIT"). Everything else that passes
# through the band — item rows (0.024-0.040), tutorial text (0.037), menu
# labels (0.030) — is under 0.045.
MIN_BANNER_HEIGHT = 0.06
# A banner is alone in the band and centred; menus fill it with many small
# left-aligned labels.
MAX_BANNER_LINES = 2
BANNER_CENTER_TOLERANCE = 0.06
# The boss name starts at x 0.31 of the frame = 0.044 of the crop; level-up
# and equipment labels in the same band start at x >= 0.70.
BOSS_NAME_MAX_X0 = 0.12
# Item names start at x 0.37 of the frame = 0.175-0.176 of the crop on every
# fixture. Menu lists (equipment, inventory, shop: names at x 0.17-0.44,
# rows 0.14 apart like a stacked popup) are cut by the crop's left edge and
# start at 0.0; the level-up screen's stat labels ("Physical Def.", t 1080)
# start at 0.27.
ITEM_NAME_X0 = (0.13, 0.22)
# The count column: "1" at x 0.665 of the frame = 0.94 of the crop.
ITEM_COUNT_COLUMN_X0 = 0.85
# Decorative flourishes beside a banner OCR as a tiny box of 1-3 letters.
FLOURISH_MAX_WIDTH = 0.05
# The end credits (chunk 06, from t 1950) scroll Title Case names on black
# through every strip: the pickup panel's dark background and the bar's
# dark lines are everywhere. A pickup panel holds two name rows at most
# (the count column is digits, rarely read); the credits put 6-8 boxes in
# the crop. A boss strip holds one name; the credits put two rows in it.
MAX_ITEM_LINES = 3


class DsrProfile:
    id = "dsr"
    display_name = "Dark Souls: Remastered"
    process_names = ("DarkSoulsRemastered.exe",)
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
        "speaker name; NPCs rarely introduce themselves. A boss kill shows VICTORY ACHIEVED and "
        "the boss's soul or gear is logged as an item pickup right after it. Souls picked up "
        "(Soul of a Lost Undead, Large Soul of a Nameless Soldier) are consumable currency, not "
        "story items, and a gesture learned from an NPC (\"Hurrah!\") comes through the same pickup "
        "panel. Deaths in the open world are logged the same as deaths to a boss. "
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
            if frame is not None and not has_hud(frame):
                return []
            return self._item_popup(lines, frame)
        bars = {BOSS_BAR.name: BOSS_HP_BAR, BOSS_BAR_RAISED.name: BOSS_HP_BAR_RAISED}
        if region.name in bars:
            hit = self._boss_bar(lines)
            if hit and frame is not None and not (has_hud(frame) and has_boss_hp_bar(frame, bar=bars[region.name])):
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
        # Title Case ("Darkroot Basin"); every all-caps banner is a fixed
        # phrase, so an all-caps read that matched nothing is a mangled one
        # ("BONE" / "RELIT" for BONFIRE LIT, chunk 01 t 2724) or a stoplisted
        # notice, never a place.
        name = _tidy_name(joined)
        squashed = norm.replace(" ", "")
        # A long name wraps onto two lines and a mid-fade read glues its
        # small words ("Tomb ofthe" / "Giants", chunk 05 t 2075), which is
        # not Title Case; a read that snaps to a known area is taken on
        # that strength, an unknown name has to look like one.
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
            return EventType.AREA_DISCOVERED, snapped, conf
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
        if _BUTTON_PROMPT.search(text) or _CREDITS_TOKEN.search(text) or match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.DIALOGUE, text, conf

    def _boss_bar(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        named = join_rows([l for l in lines if any(c.isalpha() for c in l.text)])
        if len(named) > 1:
            return None  # the credits, a menu: one name fits the strip
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
        return EventType.BOSS_ENGAGED, text, best.conf

    def _item_popup(self, lines: list[OcrLine], frame: np.ndarray | None) -> list[tuple[EventType, str, float]]:
        # A number anywhere left of the count column is a stat table (the
        # level-up screen: "Physical Def.  84  84", t 1080), not a pickup.
        # The pickup's own count ("1" at 0.94) is rarely read at all.
        if any(l.text.strip().isdigit() and l.x0 < ITEM_COUNT_COLUMN_X0 for l in lines):
            return []
        candidates = [l for l in lines if l.x0 < ITEM_COUNT_COLUMN_X0 and re.search(r"[A-Za-z]", l.text)]
        if len(candidates) > MAX_ITEM_LINES:
            return []
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows(candidates):
            text = _COUNT_SUFFIX.sub("", row.text.strip())
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            # Left-aligned after the icon; a menu list cut by the crop edge
            # starts at 0.
            if not ITEM_NAME_X0[0] <= row.x0 <= ITEM_NAME_X0[1]:
                continue
            if not 1 <= word_count(text) <= 7 or not _LATIN_WORD.search(text) or _HAS_DIGIT.search(text):
                continue
            # Names are Title Case; a centre banner cut by the crop
            # ("ORY ACHIE") is all caps, and prompts carry button glyphs.
            if text.isupper() or not _looks_like_name(text) or _BUTTON_PROMPT.search(text):
                continue
            if match_vocab(text, BANNER_VOCAB) is not None:
                continue
            # A summoned phantom's floating name tag ("WitchBeatrice", chunk
            # 01 t 434) drifts onto the row; a pickup sits on a dark panel.
            if frame is not None and not has_item_panel(frame, row):
                continue
            events.append((EventType.ITEM_ACQUIRED, text, row.conf))
        return events


def has_boss_hp_bar(
    frame: np.ndarray, bar: Region = BOSS_HP_BAR, min_row_fraction: float = 0.85, max_value: float = 45
) -> bool:
    """True when the bar's two black border lines span the bar strip.

    Measured on chunk 00 (1080p): with a bar drawn, one row in the top half
    of the strip and one in the bottom half are >= 0.88 dark (V < 45)
    across x 0.32-0.82 (t 550: 0.88 and 0.99; t 3166: 0.92 and 0.99, and
    the raised bar 0.99 and 1.00). The scene shows through between the
    lines where the fill has gone, so a uniformly dark frame would pass on
    the lines alone; the row midway must be lighter than the lines.
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


# The pickup panel around a name row: on every fixture >= 0.99 of the
# pixels right of the name (up to the count column) and in the 0.03-tall
# bands above and below the row have V < 60; under the phantom name tag
# over a night scene (chunk 01 t 434) 0.86-0.88, and the level-up screen's
# table rows 0.93.
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


def _is_estus_label(text: str) -> bool:
    return _ESTUS_LABEL.sub("", text).strip() == ""


def _strip_edges(word: str) -> str:
    """Strip symbols from a word's edges, keeping inner ones ("Pilgrim's")."""
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
    """Drop ornaments read as stray symbols or single letters; title-case an all-caps read.

    The flourish beside a banner also glues onto the first word as a quote
    or star ("'Depths", chunk 01 t 1405; "*MoMlight Butterfly" on a boss
    bar over the butterfly's glow), so word edges lose their symbols too.
    """
    text = " ".join(_strip_edges(w) for w in text.split())
    text = " ".join(w for w in text.split() if any(c.isalpha() for c in w) and len(w) > 1)
    if text.isupper():
        small = {"OF", "THE", "AND", "OR", "IN", "AT", "ON", "TO", "A", "AN"}
        words = text.split()
        return " ".join(w.capitalize() if (i == 0 or w not in small) else w.lower() for i, w in enumerate(words))
    return " ".join(text.split())
