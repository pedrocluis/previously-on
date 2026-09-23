"""Sekiro: Shadows Die Twice profile (PC, 16:9).

Region coordinates and the rules below were measured from a 1080p YouTube
playthrough (``recordings/sekiro/``, gitignored; ``t`` in the comments is the
second within chunk 00 unless noted) with the add-game survey, then checked
with ``previously-on calibrate --game sekiro``. Fractions are of the full
frame.

Sekiro writes its notices as a vertical column of kanji with a small
letter-spaced English caption underneath (鬼仏見出 over ``SCULPTOR'S IDOL
FOUND``, 死 over ``DEATH``). The caption is the only part OCR can be trusted
on, and it is *short* — a banner here is no taller than a subtitle, so
unlike the Dark Souls profiles height cannot tell a banner from anything
else. The centre band therefore accepts nothing but a fixed phrase.

Area reveals are a separate thing: large Title Case serif text higher up the
screen (y 0.43-0.50), so they get their own region, as in Dark Souls II.
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

# -- regions -----------------------------------------------------------------
# Area reveals: large Title Case serif, y 0.4259-0.5046, x 0.351-0.648 on
# both reads of the hour ("Ashina Reservoir" t 313, "Ashina Outskirts"
# t 1333). The band is widened to x 0.18-0.82 because the longest area
# names in the game are half again as long as those two (16 characters
# span 0.291, so 0.0182 each). The perilous-attack kanji 危 flashes in the
# same place all fight long (y 0.36-0.58, x 0.44-0.52, conf up to 1.00,
# t 885-970) and the death mark 死 crosses it (y 0.26-0.615): both are
# rejected for carrying no Latin word.
AREA_BANNER = Region("area_banner", x=0.18, y=0.395, w=0.64, h=0.125)
# The English caption under a notice's kanji column: "SCULPTOR'S IDOL
# FOUND" at y 0.694-0.725, x 0.317-0.683 (t 1341, 1474) and "DEATH" at
# y 0.595-0.659, x 0.439-0.560 (the death montage, see the fixture
# README). The caption's height, 0.027-0.031, is exactly a subtitle's, so
# only BANNER_VOCAB may fire here. The item-description panel's last rows
# (x 0.44-0.71, y 0.58-0.66), the "OK" button (x 0.488-0.513, y 0.70-0.73)
# and the channel's intro card all fall inside and match nothing.
# The crop's geometry is load-bearing. At x 0.24-0.76 the detector kept
# clipping the caption's first and last letter ('EAT', 'BTAT' on the
# montage's fainter frames), and at h 0.08 it reads DEATH perfectly but
# misses the idol caption, which sits 0.04 lower. The top had to come up
# from 0.585 to 0.565 for "SHINOBI EXECUTION" (y 0.580-0.611, chunk 04
# t 1778-1781): clipped by five thousandths of a frame it read "INOBI
# EXECUTION" every time and matched nothing.
CENTER_BANNER = Region("center_banner", x=0.26, y=0.565, w=0.48, h=0.175)
# Subtitles come at two heights and are always centred on x=0.5. Field and
# eavesdropping lines sit at y 0.734-0.799 ("Not at all. Not only is he
# unarmed…", t 335; "This appears to be the escape route.", t 735);
# cutscene and NPC lines at y 0.83-0.92, up to three rows, the longest
# reaching x 0.178-0.821 (the Sculptor, probe t 133). They are two regions
# because a line in each band at the same moment must not be glued into
# one sentence. The strip stops at x 0.85: the bottom-right prompt
# (":Next :Cancel", x 0.84-0.95, y 0.93) and the bottom-left interaction
# prompt ("Rest at the Sculptor's Idol", x 0.059-0.226, y 0.892-0.918) are
# cut by the crop's edges and fail the centring rule.
SUBTITLE_FIELD = Region("subtitle_field", x=0.15, y=0.725, w=0.70, h=0.095)
SUBTITLE = Region("subtitle", x=0.15, y=0.825, w=0.70, h=0.110)
# The boss name is **top-left**, under its HP bar: y 0.095-0.132,
# x 0.059-0.159 ("Chained Ogre", t 2250) and 0.059-0.254 ("Leader
# Shigenori Yamauchi", t 656). The crop reaches x 0.46 for the longer
# names the game gives its Seven Spears. The menu's tabs share the
# band ("Equipment" x 0.17, "Inventory", "Options"); BOSS_NAME_MAX_X0 and
# the bar check keep them out.
BOSS_BAR = Region("boss_bar", x=0.04, y=0.090, w=0.42, h=0.055)
# The bar itself, just above the name: a track with a red fill that
# shrinks to nothing as the boss loses HP, and a light vertical end cap at
# each end that stays drawn whatever the fill does. The bar's *length* is
# per boss — the Chained Ogre's right cap sits at x 0.196, Genichiro's at
# 0.273 (fixtures boss_ogre, boss_genichiro) — so the check looks for the
# caps rather than assuming where the far one is. Its rows are the ones
# all four bosses of the first hour share (the bar's own y wanders by
# 0.007 between them).
BOSS_HP_BAR = Region("boss_hp_bar", x=0.048, y=0.0845, w=0.315, h=0.0105)
# The deathblow pips above the bar's left end: one to three small circles
# of bright red, drawn for every boss and miniboss. This is what separates
# a bar from the Sculptor's menus, whose wooden frame has light corner
# pieces exactly where the caps are ("Create Arm Tools" at t 3274,
# "Acquire Skills" at t 3370 both passed the cap check and sit where a
# boss name sits).
BOSS_PIPS = Region("boss_pips", x=0.052, y=0.048, w=0.046, h=0.030)
# Item pickups: a right-aligned list on the right edge. Names end at
# x 0.875-0.877 on every read of the hour and grow leftwards ("Shinobi
# Medicine Rank 1" starts at 0.754, t 2272); the count sits at x 0.91 and
# the icon at 0.92-0.95, both outside the crop. Rows are 0.024 tall and
# stack *upward* 0.0585 apart from a bottom row at y 0.635 (three at once
# at t 582: Kusabimaru 0.519, Healing Gourd 0.577, Pellet 0.635). The
# spirit-emblem counter (x 0.924-0.949) and the key-item description panel
# (which ends at x 0.71) stay outside.
ITEM_POPUP = Region("item_popup", x=0.70, y=0.505, w=0.19, h=0.165)

# -- vocabulary --------------------------------------------------------------
BANNER_VOCAB: dict[str, EventType] = {
    # 死. The playthrough has no deaths in its first hour, so the frames
    # come from a death montage (tests/fixtures/sekiro/README.md). OCR
    # reads the caption at 0.82-0.95 and gave "DRATH" once.
    "DEATH": EventType.DEATH,
    # 忍殺, the deathblow that ends a *main* boss. Drawn for five seconds
    # or more at y 0.580-0.611 — Gyoubu Oniwa (chunk 00 t 2995-2998), Lady
    # Butterfly (chunk 01 t 2352-2355), the Guardian Ape (chunk 04
    # t 1778-1781) and the Corrupted Monk (chunk 04 t 3391-3396), each
    # followed by its "Memory: <name>" drop. Minibosses do not get it: the
    # Chained Ogre (chunk 00 t 2256, sampled at 6 fps), the Armored
    # Warrior and Long-arm Centipede Sen'un (chunk 03, sampled at 4 fps)
    # all die with nothing in the band, and 700 s of chunk 03 containing
    # two of those fights yielded not one read of this phrase. What proves
    # a miniboss kill is still its Prayer Bead.
    "SHINOBI EXECUTION": EventType.BOSS_DEFEATED,
    # 不死斬り, the Mortal Blade finisher on a boss that cannot die
    # otherwise: the True Corrupted Monk (chunk 06 t 2580-2585, read for
    # five seconds and followed by "Memory: True Monk"). Same band and
    # font as SHINOBI EXECUTION. The items named for it are far enough
    # away that the item handler's vocabulary check cannot eat them —
    # "Immortal Severance Text" scores 71 against this phrase and a bare
    # "Immortal Severance" 81, both under match_vocab's 85.
    "IMMORTALITY SEVERED": EventType.BOSS_DEFEATED,
    # 鬼仏見出, t 1341 and 1474. The letter spacing loses every space, so
    # the read is "SCULPTOR'SIDOLFOUND"; match_vocab compares
    # space-stripped. The banner never names the idol (the menu that opens
    # on resting does, top-left, but it opens on every rest).
    "SCULPTOR'S IDOL FOUND": EventType.CHECKPOINT_DISCOVERED,
}
# A centred banner that only half-matches the vocabulary is a mangled
# banner, never anything else.
BANNER_PARTIAL_REJECT = 80.0

# Centre-screen text that is not an event. Nothing here can become an event
# anyway — the centre band accepts only BANNER_VOCAB and the area band wants
# a Title Case name — but they are the near misses worth naming.
BANNER_STOPLIST = {
    # The epilepsy warning on start-up: y 0.511-0.756, centred, huge
    # (montage t 0-3).
    "WARNING",
    # The channel's intro card, y 0.571-0.739 (t 4-7): "gamer's little"
    # over "PLAYGROUND".
    "PLAYGROUND",
    "GAMER'S LITTLE",
}
_BANNER_STOPLIST_NOSPACE = {normalize(s).replace(" ", "") for s in BANNER_STOPLIST}
BANNER_STOPLIST_MATCH = 85.0

# Area names seen so far, for snapping a mid-fade read back to the real
# name. Unknown names are kept as read, so the list need not be complete —
# but every entry here was read from a frame.
KNOWN_AREAS = (
    "Ashina Reservoir",  # t 313
    "Ashina Outskirts",  # t 1333
    "Hirata Estate",  # chunk 01 t 831
    "Ashina Castle",  # chunk 01 t 3149
    "Senpou Temple, Mt. Kongo",  # chunk 02 t 2896
    "Sunken Valley",  # chunk 03 t 2535
    "Sunken Valley Passage",  # chunk 03 t 3291
    "Abandoned Dungeon",  # chunk 04 t 1032
    "Mibu Village",  # chunk 04 t 2359
    "Fountainhead Palace",  # chunk 07 t 796, read "Fountainhead Palacc" off the JPEG
)
# These are every area banner the eight chunks produced. The game's names
# share a prefix more often than the Souls games' do, but the closest pair
# of the ten — "Sunken Valley" and "Sunken Valley Passage" — scores 77, so
# snapping at 90 cannot turn one into another. 90 is also the bar a fade
# read must clear to be taken on the list's strength rather than on
# looking like a name.
KNOWN_AREA_MATCH = 90.0

# UI text that is centred in a subtitle band and ends like a sentence.
# "Call the Divine Heir with the reed whistle?" (t 735) is a yes/no prompt
# drawn at y 0.794-0.820, inside the field band.
PROMPT_STOPLIST = {
    "CALL THE DIVINE HEIR WITH THE REED WHISTLE",
}
PROMPT_STOPLIST_MATCH = 88.0
# The confirmation boxes ("Consume 4 Prayer Beads to Enhance Physical
# Attributes?" with YES/NO under it, chunk 01 t 1142.5; "Physical
# attributes enhanced. Maximum Vitality and Posture have increased." with
# OK, t 1148.5) are drawn in the subtitle's own band, centred, and end in
# punctuation, so every rule that tells a subtitle from a prompt passes
# them. What gives them away is the font: they are set in the UI face,
# whose spaces OCR loses ("PrayerBeads", "toEnhancePhysical",
# "MaximumVitality"), while the subtitle face reads with every space
# intact — 2 of the 482 dialogue lines the first two hours logged carry a
# camel-case glue, and both are boxes.
_GLUED_WORDS = re.compile(r"(?<=[a-z])(?=[A-Z])")
# Button glyphs OCR as a letter and a colon, as in Dark Souls II:
# ":Next :Cancel", "A:Close", ": Stop hugging wall", ": Eavesdrop".
_BUTTON_PROMPT = re.compile(r"(?:^|\s)[A-Z]?\s?[:：]\s?[A-Z]")

# UI strings that reach the item crop but are not pickups. A bare prompt
# was read there twice ("Talk", chunks 02 and 07) and rejected both times
# for ending nowhere near the count column; the stoplist is the backstop.
ITEM_STOPLIST = {"TALK", "REST", "COMMUNE", "EAVESDROP", "PURCHASE", "TRAVEL", "PICK UP ITEM"}
# Sekiro floats its interaction prompt next to whatever it is for, so the
# prompt can land on a pickup row and join_rows glues the two into one box
# ("Talk Memory: Divine Dragon", chunk 07 t 1256.5 — the only one in 631
# distinct item-crop reads across the eight chunks). Every word here was
# read as a prompt somewhere in those logs: "Talk" and "Purchase" and
# "Travel" from the talk menus, "Pick Up Item" and "Commune" and "Rest at
# the Sculptor's Idol" from the world, "Eavesdrop" from the tutorial. A
# capitalised word must follow, and what is left still has to look like an
# item name.
_PROMPT_PREFIX = re.compile(
    r"^(?:Talk|Rest|Commune|Eavesdrop|Purchase|Travel|Pick\s?Up(?:\s?Item)?)\s+(?=[A-Z])"
)

# -- geometry guards ---------------------------------------------------------
# Area banners are the one tall thing the game draws: 0.076-0.078 on both
# reads. Everything else that passes through that band — tutorial cards,
# item descriptions, menu labels — is 0.024-0.035.
MIN_AREA_HEIGHT = 0.055  # of the frame
# A banner is alone in its band; a menu fills it with labels.
MAX_BANNER_LINES = 2
BANNER_CENTER_TOLERANCE = 0.06  # of the frame width
# Subtitles are centred on x=0.5 within this much of the *crop*; the
# interaction prompts that share the bands are pinned to a screen edge.
SUBTITLE_CENTER_TOLERANCE = 0.10
# Ornaments beside a banner OCR as a tiny box of one to three letters.
FLOURISH_MAX_WIDTH = 0.05
# The boss name starts at x 0.059 of the frame = 0.045 of the crop; the
# menu tabs that share the band start at 0.17 = 0.31.
BOSS_NAME_MAX_X0 = 0.15
# Item names end at x 0.875-0.877 of the frame = 0.921-0.932 of the crop.
ITEM_RIGHT_EDGE = (0.88, 0.98)
# Three rows fit the crop; a fourth box is the Acquire Skills menu's
# description panel bleeding in (chunk 01 t 3297.5 put four of its lines in
# the crop, ending at the panel's right edge where a name ends).
MAX_ITEM_LINES = 3
# A pickup name is one to four short words. The same description panel puts
# a glued run of prose in the crop ("Postureuponperforminga", chunk 01
# t 3297.5); the longest single-word item read so far is "Kusabimaru".
MAX_SINGLE_WORD = 16

_HAS_DIGIT = re.compile(r"\d")
_ALL_DIGITS = re.compile(r"^[\d\s]+$")
_SENTENCE_END = set(".!?,;:…'\")»")
# Names are Latin text; the kanji marks (死, 危, 炎) and OCR garbage from
# effects come back as CJK glyphs.
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")
_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*\d+\s*$")
# OCR reads the gap in a name as a middle dot ("Chained·Ogre", montage
# t 96.5). A hyphen is left alone: the game uses real ones ("Outskirts
# Wall - Gate Path").
_MIDDOT = re.compile(r"[·•]+")
# Several minibosses are written with a dash between a title and a name
# ("Ashina Elite - Jinsuke Saze", chunk 02 t 485; "Seven Ashina Spears -
# Shikibu Toshikatsu Yamauchi", t 2412; "Great Shinobi - Owl", chunk 05
# t 2791) and OCR sometimes loses the space on one side, after which
# _strip_edges eats the dash with the word's leading punctuation
# ("Spears -Shikibu" on the stored JPEG of t 2412).
#
# The repair only restores a space OCR itself half-kept: a dash with
# whitespace on exactly one side becomes " - ". A dash with no space at
# all is left alone, because that is how the game writes a compound —
# "Lone Shadow Masanaga the Spear-Bearer" (chunk 05 t 968, read that way
# on all three frames) is one word and an earlier "split before a capital"
# rule broke it. "Great Shinobi-Owl" (t 2917) stays glued too and folds
# into the spaced read at 100.
# Boss names only: the item font puts a hyphen inside a word
# ("Scrap-Magnetite", chunk 02).
_NAME_DASH = re.compile(r"\s+-(?=[A-Za-z])|(?<=[A-Za-z])-\s+")
# The pickup font glues a rank's digit to the word before it ("Shinobi
# MedicineRank1", t 2275.5, which the whole-frame survey read as "Shinobi
# Medicine Rank 1"). Three letters must precede the digit, so a button
# glyph ("L1", "R2") is left alone and rejected for carrying a digit.
_GLUED_DIGIT = re.compile(r"(?<=[A-Za-z]{3})(?=\d)")
# "of" glued to a three-letter word's tail, which classify.respace leaves
# alone because it wants four letters before it: "Shinobi Axeof the Monkey"
# (chunk 01 t 316). Only when a small word follows, and never after "pro"
# ("Waterproof the …" is not a thing, but the exclusion is free).
_GLUED_OF_TAIL = re.compile(r"(?<=[A-Za-z]{3})(?<!pro)(of)(?=\s(?:the|an?)\s)")


class SekiroProfile:
    id = "sekiro"
    display_name = "Sekiro: Shadows Die Twice"
    process_names = ("sekiro.exe",)
    aspect_ratio = (16, 9)
    regions = [AREA_BANNER, CENTER_BANNER, SUBTITLE_FIELD, SUBTITLE, BOSS_BAR, ITEM_POPUP]
    cooldowns = {
        EventType.DEATH: 8.0,
        EventType.BOSS_DEFEATED: 30.0,
        EventType.ENEMY_DEFEATED: 8.0,
        EventType.CHECKPOINT_DISCOVERED: 8.0,
        # An area banner replays on every entry and NPCs repeat their lines.
        EventType.AREA_DISCOVERED: 600.0,
        EventType.BOSS_ENGAGED: 120.0,
        # The pickup list lingers ~12 s and OCR loses it for a second at
        # a time as the scene moves behind the translucent panel, so one
        # Pellet read at t 1311-1322 was logged twice at the usual 8 s.
        EventType.ITEM_ACQUIRED: 15.0,
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
        CENTER_BANNER.name: 3.0,
        AREA_BANNER.name: 3.0,
        ITEM_POPUP.name: 1.5,
        SUBTITLE.name: 1.5,
        SUBTITLE_FIELD.name: 1.5,
    }
    recap_notes = (
        "Checkpoints are Sculptor's Idols; the banner reads SCULPTOR'S IDOL FOUND and never "
        "names the idol. Area names appear as banners on entry and replay on every visit. "
        "Subtitles carry no speaker name. "
"A main boss killed shows SHINOBI EXECUTION and is logged as boss_defeated, followed by "
        "its \"Memory: <name>\" drop. A *miniboss* gets no banner at all — the Chained Ogre, the "
        "Armored Warrior, the generals and the Lone Shadows die with nothing on screen — so a "
        "miniboss leaves a boss_engaged with no boss_defeated after it. Do not say such a boss is "
        "still alive because of that; what proves the kill is the Prayer Bead logged right after. "
        "Deaths are the player's; the Wolf can resurrect on the spot, so a death is not "
        "necessarily a trip back to an idol. "
        "Sen, Spirit Emblems, Pellets, Gourd Seeds and sugars (Gachiin's, Ako's, Ungo's) are "
        "consumables, not story items; Prayer Beads and Gourd Seeds are upgrade materials. "
        "A boss name can be misread by a letter; keep the transcript's spelling."
    )
    MIN_CONF = {
        AREA_BANNER.name: 0.85,
        CENTER_BANNER.name: 0.75,
        SUBTITLE_FIELD.name: 0.60,
        SUBTITLE.name: 0.60,
        BOSS_BAR.name: 0.80,
        ITEM_POPUP.name: 0.80,
    }

    def classify(
        self, region: Region, lines: list[OcrLine], frame: np.ndarray | None = None
    ) -> list[tuple[EventType, str, float]]:
        if not lines:
            return []
        if region.name == ITEM_POPUP.name:
            return self._item_popup(lines)
        if region.name == BOSS_BAR.name:
            hit = self._boss_bar(lines)
            if hit and frame is not None and not has_boss_hp_bar(frame):
                return []
            return [hit] if hit else []
        handler = {
            AREA_BANNER.name: self._area_banner,
            CENTER_BANNER.name: self._center_banner,
            SUBTITLE_FIELD.name: self._subtitle,
            SUBTITLE.name: self._subtitle,
        }.get(region.name)
        hit = handler(lines) if handler else None
        return [hit] if hit else []

    # -- region handlers -------------------------------------------------

    def _banner_rows(self, lines: list[OcrLine]) -> list[OcrLine]:
        """The centred rows of a banner crop: few, confident, on x=0.5."""
        confident = [l for l in lines if l.conf >= 0.6]
        if len(confident) > MAX_BANNER_LINES:
            return []  # a menu or a description panel, not a banner
        rows = join_rows(
            [
                l
                for l in confident
                if re.search(r"[A-Za-z]", l.text) and not (l.width < FLOURISH_MAX_WIDTH and len(l.text) <= 3)
            ]
        )
        return [l for l in rows if abs((l.x0 + l.x1) / 2 - 0.5) <= BANNER_CENTER_TOLERANCE]

    def _center_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        rows = self._banner_rows(lines)
        if not rows:
            return None
        joined = " ".join(l.text for l in rows)
        conf = min(l.conf for l in rows)
        if conf < self.MIN_CONF[CENTER_BANNER.name]:
            return None
        hit = match_vocab(joined, BANNER_VOCAB)
        if hit is None:
            # The caption is as short as a subtitle and as short as the
            # item panel's last line, so nothing but a fixed phrase may
            # fire here. Area names have their own band.
            return None
        typ, score, phrase = hit
        # Store the canonical phrase, not the OCR output.
        return typ, phrase, min(conf, score / 100.0)

    def _area_banner(self, lines: list[OcrLine]) -> tuple[EventType, str, float] | None:
        rows = self._banner_rows(lines)
        tall = [l for l in rows if l.height * AREA_BANNER.h >= MIN_AREA_HEIGHT]
        if not tall:
            return None
        joined = " ".join(l.text for l in tall)
        conf = min(l.conf for l in tall)
        if conf < self.MIN_CONF[AREA_BANNER.name]:
            return None
        if match_vocab(joined, BANNER_VOCAB) is not None:
            return None
        norm = normalize(joined)
        if any(fuzz.partial_ratio(norm, normalize(v)) >= BANNER_PARTIAL_REJECT for v in BANNER_VOCAB):
            return None
        squashed = norm.replace(" ", "")
        if any(fuzz.ratio(squashed, s) >= BANNER_STOPLIST_MATCH for s in _BANNER_STOPLIST_NOSPACE):
            return None
        name = respace(_tidy_name(joined))
        # A fade read can glue the small words; a read that snaps to a
        # known area is taken on that strength, an unknown name has to look
        # like one.
        snapped = _snap_area(name)
        if (
            1 <= word_count(norm) <= 6
            and len(norm) >= 4
            and not _HAS_DIGIT.search(joined)
            and _LATIN_WORD.search(joined)
            and (snapped != name or (_looks_like_name(name) and not name.isupper()))
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
        rows = join_rows(lines)
        # Subtitles are centred on x=0.5; the prompts that share the bands
        # are pinned to a screen edge and come back cut by the crop.
        rows = [l for l in rows if abs((l.x0 + l.x1) / 2 - 0.5) <= SUBTITLE_CENTER_TOLERANCE]
        if not rows:
            return None
        text = " ".join(l.text for l in rows).strip()
        conf = min(l.conf for l in rows)
        if conf < self.MIN_CONF[SUBTITLE.name] or word_count(text) < 3 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences (or a fragment continued on the next
        # line): they end in punctuation. Labels and button hints don't.
        if text[-1] not in _SENTENCE_END:
            return None
        if _BUTTON_PROMPT.search(text) or match_vocab(text, BANNER_VOCAB) is not None:
            return None
        if _GLUED_WORDS.search(text):
            return None
        norm = normalize(text)
        if any(fuzz.ratio(norm, p) >= PROMPT_STOPLIST_MATCH for p in PROMPT_STOPLIST):
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
        # Respace before the Title Case and word-count checks: where OCR
        # put the spaces must not decide anything ("Juzou theDrunkard" and
        # "JuzoutheDrunkard" are the same bar, montage t 41-44).
        text = respace(_tidy_name(_NAME_DASH.sub(" - ", best.text)))
        if best.conf < self.MIN_CONF[BOSS_BAR.name] or not 1 <= word_count(text) <= 8:
            return None
        if text[-1] in ".!?;:" or _HAS_DIGIT.search(text) or not _LATIN_WORD.search(text):
            return None
        if _BUTTON_PROMPT.search(text) or not _looks_like_name(text) or text.isupper():
            return None
        if match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.BOSS_ENGAGED, text, best.conf

    def _item_popup(self, lines: list[OcrLine]) -> list[tuple[EventType, str, float]]:
        candidates = [l for l in lines if re.search(r"[A-Za-z]", l.text)]
        if len(candidates) > MAX_ITEM_LINES:
            return []
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows(candidates):
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            # Right-aligned against the count column; the description
            # panel bleeding in from the left is cut by the crop's edge and
            # ends nowhere near it.
            if not ITEM_RIGHT_EDGE[0] <= row.x1 <= ITEM_RIGHT_EDGE[1]:
                continue
            text = _GLUED_DIGIT.sub(" ", respace(_tidy_name(_COUNT_SUFFIX.sub("", row.text.strip()))))
            text = " ".join(_GLUED_OF_TAIL.sub(r" \1", text).split())
            # A prompt on its own is rejected before the prefix is
            # stripped, or "Pick Up Item" would be left as "Item".
            if normalize(text) in ITEM_STOPLIST:
                continue
            text = _PROMPT_PREFIX.sub("", text)
            # A rank is part of the name ("Shinobi Medicine Rank 1",
            # t 2272), so digits are allowed — but a number on its own is
            # the count column drifting left.
            if not 1 <= word_count(text) <= 8 or not _LATIN_WORD.search(text) or _ALL_DIGITS.match(text):
                continue
            if text.isupper() or not _looks_like_name(text):
                continue
            # One long glued word is the skills menu's prose, not a name.
            if word_count(text) == 1 and len(text) > MAX_SINGLE_WORD:
                continue
            if normalize(text) in ITEM_STOPLIST or match_vocab(text, BANNER_VOCAB) is not None:
                continue
            events.append((EventType.ITEM_ACQUIRED, text, row.conf))
        return events


# has_boss_hp_bar, measured on chunk 00 (1080p) over the hour's six
# fights and every other frame of it at 0.5 fps.
# The end caps read >= 0.80 of the strip's height on all six; scenery and
# menu frames reach that on at most one side, or with a wide light run
# rather than a 1-6 column cap, or with a lit gap between the two.
CAP_MIN = 0.80
CAP_MAX_RUN = 6  # columns: a cap is a hairline, a lit wall is not
GAP_MAX_LIGHT = 0.25  # between the caps lies the track, never a lit scene
MIN_BAR_W = 0.12  # of the frame: the shortest bar seen spans 0.138
STRIP_MAX_LIGHT = 0.45  # a white loading screen has caps everywhere
# The pips are bright red (S > 140, V > 140): 0.17-0.66 of the zone on the
# four boss fixtures, 0.00 on every menu and red-lit scene tried. Not every
# miniboss has them, though — the Armored Warrior, the Folding Screen
# Monkeys and the Illusory Hall Monk (chunk 03) show a bar with no pips at
# all — so the pips are one of two ways to confirm a bar.
PIP_MIN = 0.06
# The other is the bar's own red fill, which the menus have nothing like:
# between the caps a drawn bar reads 0.37-0.99 red and the Sculptor's
# "Create Arm Tools" panel reads 0.000. It falls to zero in the last
# seconds of a fight (the Chained Ogre's last five frames, chunk 00
# t 2216-2222), which costs nothing: the bar is up for a minute before
# that and the event fires on the first frame of it.
FILL_MIN = 0.05


def _light_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges of consecutive True columns."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def has_boss_pips(frame: np.ndarray, region: Region = BOSS_PIPS) -> bool:
    """True when the deathblow pips are drawn above the bar's left end."""
    zone = crop(frame, region)
    if zone.size == 0:
        return False
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    red = ((hue <= 12) | (hue >= 168)) & (sat > 140) & (val > 140)
    return float(red.mean()) >= PIP_MIN


def has_boss_hp_bar(frame: np.ndarray, bar: Region = BOSS_HP_BAR) -> bool:
    """True when a boss HP bar — two end caps over a red fill — is drawn.

    The caps are the geometry; what tells the bar from the Sculptor's
    menus, whose wooden frame has light corner pieces in the same places,
    is what lies between them: a red fill, or the deathblow pips above.
    """
    strip = crop(frame, bar)
    if strip.size == 0:
        return False
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    light = ((val > 110) & (sat < 90)).mean(axis=0)
    fill = (((hue <= 14) | (hue >= 166)) & (sat > 90) & (val > 40)).mean(axis=0)
    n = len(light)
    if n < 40 or float(light.mean()) >= STRIP_MAX_LIGHT:
        return False
    caps = [r for r in _light_runs(light >= CAP_MIN) if r[1] - r[0] + 1 <= CAP_MAX_RUN]
    head = [r for r in caps if r[0] <= max(3, n // 12)]
    if not head:
        return False
    left = head[0]
    span = int(MIN_BAR_W / bar.w * n)
    pips = has_boss_pips(frame)
    for right in caps:
        if right[0] - left[1] < span:
            continue
        inner = slice(left[1] + 1, right[0])
        if light[inner].size and float(light[inner].mean()) <= GAP_MAX_LIGHT:
            if pips or float(fill[inner].mean()) >= FILL_MIN:
                return True
    return False


def _strip_edges(word: str) -> str:
    """Strip symbols from a word's edges, keeping inner ones ("Gachiin's").

    A trailing colon is kept: the memories and remnants a boss drops are
    named with one ("Memory: Gyoubu Oniwa", "Remnant: Gyoubu", t 3001 and
    3033), and stripping it lost the colon on the frames where OCR read
    the space after it. A boss name ending in a colon is rejected anyway.
    """
    return re.sub(r"^[^A-Za-z0-9(]+|[^A-Za-z0-9).!?,:]+$", "", word)


def _tidy_name(text: str) -> str:
    """Drop ornaments read as stray symbols and the dot OCR puts between words.

    A lone hyphen survives: the game writes several of its minibosses with
    one ("Ashina Elite - Jinsuke Saze", chunk 02 t 485; "Seven Ashina
    Spears - Shikibu Toshikatsu Yamauchi", t 2412) and dropping it changes
    the name. Every other one-character token is an ornament.
    """
    text = _MIDDOT.sub(" ", text)
    text = " ".join(_strip_edges(w) if w != "-" else w for w in text.split())
    return " ".join(w for w in text.split() if any(c.isalnum() for c in w) or w == "-")


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
    small = {"of", "the", "and", "or", "in", "at", "on", "to", "a", "an", "from"}
    # A name never *starts* with a small word in lower case: "to the Scul"
    # is a line of the skills menu's description cut by the item crop
    # (chunk 01 t 2570.5).
    if not next(c for c in words[0] if c.isalpha()).isupper():
        return False
    return all(next(c for c in w if c.isalpha()).isupper() or w.strip("()\"'").lower() in small for w in words)
