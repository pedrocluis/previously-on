"""Classifier rules for Sekiro: Shadows Die Twice — scaffolded; grows one test per fixture-backed rule.

Each test uses the real OCR read from a frame in tests/fixtures/sekiro/ so a
rule is never loosened from memory.
"""

from __future__ import annotations

import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.sekiro import BANNER_VOCAB
from previously_on.ocr import OcrLine

from .frames import load

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("sekiro")


def L(text, conf=0.95, **box):
    return [OcrLine(text, conf, **box)]


@pytest.mark.parametrize("phrase", sorted(BANNER_VOCAB) or [None])
def test_banner_vocab_round_trips(profile, phrase):
    if phrase is None:
        pytest.skip("BANNER_VOCAB is empty — fill it from the survey")
    region = next(r for r in profile.regions if r.name == "center_banner")
    # A tall, centred, confident read of the exact phrase must classify.
    hits = profile.classify(region, L(phrase, x0=0.3, x1=0.7, y0=0.2, y1=0.8), BLACK)
    assert hits and hits[0][0] is BANNER_VOCAB[phrase] and hits[0][1] == phrase


@pytest.mark.parametrize(
    "line",
    [
        OcrLine("1%", 0.3),  # HUD fragment, weak
        OcrLine("Settings", 0.99, x0=0.0, y0=0.0, x1=0.1, y1=0.05),  # small, left-aligned menu label
        OcrLine("HP 412 / 600", 0.99, x0=0.3, y0=0.2, x1=0.7, y1=0.8),  # tall and centred but digits
    ],
)
def test_junk_lines_produce_nothing(profile, line):
    for region in profile.regions:
        assert profile.classify(region, [line], BLACK) == [], region.name


def test_regions_are_consistent(profile):
    names = {r.name for r in profile.regions}
    assert set(profile.MIN_CONF) == names
    assert set(profile.quiet_after_event) <= names
    for typ in EventType:
        assert typ in profile.cooldowns


# -- the reads that actually came off the frames -----------------------------
# Every string below is what RapidOCR returned from the fixture named in the
# comment, not the clean phrase.

CENTER = next(r for r in get_profile("sekiro").regions if r.name == "center_banner")
AREA = next(r for r in get_profile("sekiro").regions if r.name == "area_banner")
SUBTITLE = next(r for r in get_profile("sekiro").regions if r.name == "subtitle")
FIELD = next(r for r in get_profile("sekiro").regions if r.name == "subtitle_field")
ITEM = next(r for r in get_profile("sekiro").regions if r.name == "item_popup")
BOSS = next(r for r in get_profile("sekiro").regions if r.name == "boss_bar")


def centred(text, conf=0.95, y0=0.2, y1=0.45):
    """A centred row of a banner crop."""
    return [OcrLine(text, conf, x0=0.15, y0=y0, x1=0.85, y1=y1)]


def test_idol_caption_loses_its_spaces(profile):
    # checkpoint_01.jpg: the letter-spaced caption reads as one run.
    hits = profile.classify(CENTER, centred("SCULPTOR'SIDOLFOUND", 0.98), BLACK)
    assert hits == [(EventType.CHECKPOINT_DISCOVERED, "SCULPTOR'S IDOL FOUND", pytest.approx(0.98, abs=0.02))]


def test_death_caption_misread_by_a_letter_is_rejected(profile):
    # montage t 91: 'BTAT' and 'EAT' are what a fading DEATH can come back
    # as; neither reaches the vocabulary's 85.
    for bad in ("BTAT", "EAT", "BEATH"):
        assert profile.classify(CENTER, centred(bad, 0.99), BLACK) == [], bad


def test_item_description_row_is_not_a_banner(profile):
    # neg_itemdesc.jpg: the panel's last lines sit in the centre band and
    # are exactly as tall as a caption. Only BANNER_VOCAB may fire there.
    text = "would also serve as a battle charm."
    assert profile.classify(CENTER, centred(text, 0.95), BLACK) == []


def test_area_banner_needs_a_latin_word(profile):
    # boss_perilous.jpg: the 危 mark flashes in the area band at conf 1.00,
    # as tall as an area name.
    assert profile.classify(AREA, centred("危", 1.0, y0=0.05, y1=0.80), BLACK) == []


def test_area_banner_takes_a_title_case_name(profile):
    hits = profile.classify(AREA, centred("Ashina Reservoir", 0.99, y0=0.25, y1=0.87), BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Ashina Reservoir", pytest.approx(0.99, abs=0.02))]


def test_area_banner_rejects_the_channel_card(profile):
    # neg_intro_card.jpg: "gamer's little" over "PLAYGROUND", centred and
    # tall. Neither half looks like a place name.
    assert profile.classify(AREA, centred("PLAYGROUND", 0.99, y0=0.25, y1=0.87), BLACK) == []
    assert profile.classify(AREA, centred("gamer'slittle", 0.97, y0=0.25, y1=0.87), BLACK) == []


def test_subtitle_prompt_pinned_to_an_edge_is_rejected(profile):
    # The bottom-left interaction prompt comes back cut by the crop's edge,
    # so its centre is nowhere near x=0.5.
    prompt = [OcrLine("Rest at the Sculptor's Idol", 0.98, x0=0.0, y0=0.55, x1=0.16, y1=0.95)]
    assert profile.classify(SUBTITLE, prompt, BLACK) == []


def test_subtitle_button_prompt_is_rejected(profile):
    hint = [OcrLine("B:Next O:Cancel", 0.99, x0=0.40, y0=0.55, x1=0.60, y1=0.95)]
    assert profile.classify(SUBTITLE, hint, BLACK) == []


def test_reed_whistle_prompt_is_not_speech(profile):
    # dialogue at t 735 shares the field band with this yes/no prompt.
    line = [OcrLine("Call the Divine Heir with the reed whistle?", 0.98, x0=0.30, y0=0.3, x1=0.70, y1=0.6)]
    assert profile.classify(FIELD, line, BLACK) == []


def test_field_subtitle_is_dialogue(profile):
    # dialogue_field.jpg
    text = "We didn't shackle him, restrain him, nothing. That doesn't worry anybody...?"
    hits = profile.classify(FIELD, [OcrLine(text, 0.98, x0=0.05, y0=0.2, x1=0.95, y1=0.6)], BLACK)
    assert hits and hits[0][0] is EventType.DIALOGUE


def test_item_name_is_respaced_and_ungued(profile):
    # item_stack3.jpg: "MibuBalloonofWealth" and "Shinobi MedicineRank1".
    for read, want in (
        ("MibuBalloonofWealth", "Mibu Balloon of Wealth"),
        ("Shinobi MedicineRank1", "Shinobi Medicine Rank 1"),
        ("OrnamentalLetter", "Ornamental Letter"),
    ):
        hits = profile.classify(ITEM, [OcrLine(read, 0.97, x0=0.30, y0=0.75, x1=0.93, y1=0.90)], BLACK)
        assert hits == [(EventType.ITEM_ACQUIRED, want, pytest.approx(0.97, abs=0.02))], read


def test_item_row_must_end_at_the_count_column(profile):
    # The description panel bleeds in from the left and is cut by the crop,
    # so its rows end far short of x 0.88.
    row = [OcrLine("Ornamental Letter", 0.97, x0=0.0, y0=0.75, x1=0.55, y1=0.90)]
    assert profile.classify(ITEM, row, BLACK) == []


def test_boss_name_needs_the_bar_under_it(profile):
    # boss_ogre.jpg's read, on a black frame: no pips, no caps, no event.
    name = [OcrLine("Chained Ogre", 0.99, x0=0.045, y0=0.1, x1=0.28, y1=0.75)]
    assert profile.classify(BOSS, name, BLACK) == []


def test_sculptor_menu_header_is_not_a_boss(profile):
    # neg_menu_armtools.jpg / neg_menu_skills.jpg: Title Case, in the boss
    # name's own place. The pip check is what rejects them on a real frame;
    # on a black one the bar check does.
    for header in ("Create Arm Tools", "Acquire Skills"):
        assert profile.classify(BOSS, [OcrLine(header, 0.99, x0=0.08, y0=0.1, x1=0.5, y1=0.75)], BLACK) == []


def test_menu_tab_sits_too_far_right_to_be_a_boss_name(profile):
    # neg_equipmenu.jpg: "Equipment" starts at x 0.17 of the frame = 0.31
    # of the crop; a boss name starts at 0.045.
    tab = [OcrLine("Equipment", 0.99, x0=0.31, y0=0.1, x1=0.55, y1=0.75)]
    assert profile.classify(BOSS, tab, BLACK) == []


def test_boss_name_is_respaced(profile):
    # boss_juzou.jpg and the montage's other reads of the same bar.
    from previously_on.games.sekiro import has_boss_hp_bar

    frame = load("sekiro", "boss_juzou.jpg")
    assert has_boss_hp_bar(frame)
    for read in ("JuzoutheDrunkard", "Juzou theDrunkard", "Juzou·the Drunkard"):
        hits = profile.classify(BOSS, [OcrLine(read, 0.96, x0=0.045, y0=0.1, x1=0.35, y1=0.75)], frame)
        assert hits == [(EventType.BOSS_ENGAGED, "Juzou the Drunkard", pytest.approx(0.96, abs=0.02))], read


def test_skills_menu_description_is_not_a_pickup(profile):
    # chunk 01 t 2570.5 and t 3297.5: the Acquire Skills menu's description
    # panel ends at the same x as an item name, so the right-edge rule lets
    # its lines through. These are the reads the run actually logged.
    for read in ("totheScul", "Postureuponperforminga", "gtheflavorwillenhanceits"):
        hits = profile.classify(ITEM, [OcrLine(read, 0.99, x0=0.02, y0=0.75, x1=0.93, y1=0.90)], BLACK)
        assert hits == [], read


def test_skills_menu_fills_the_crop_with_lines(profile):
    # Four boxes in the item crop is the description panel, never a pickup:
    # the panel holds three rows.
    lines = [
        OcrLine(t, 0.99, x0=0.30, y0=y, x1=0.93, y1=y + 0.12)
        for t, y in (("Prayer Bead", 0.10), ("Gourd Seed", 0.30), ("Pellet", 0.50), ("Ceramic Shard", 0.70))
    ]
    assert profile.classify(ITEM, lines, BLACK) == []


def test_of_glued_to_a_three_letter_word(profile):
    # chunk 01 t 316: classify.respace wants four letters before a tail
    # "of" and "Axe" has three.
    hits = profile.classify(ITEM, [OcrLine("Shinobi Axeof theMonkey", 0.94, x0=0.10, y0=0.75, x1=0.93, y1=0.90)], BLACK)
    assert hits == [(EventType.ITEM_ACQUIRED, "Shinobi Axe of the Monkey", pytest.approx(0.94, abs=0.02))]


def test_in_game_death_read_loses_its_first_letter(profile):
    # chunk 01 t 1243, the playthrough's own first death: "EATH" at 0.89.
    hits = profile.classify(CENTER, centred("EATH", 0.89), BLACK)
    assert hits and hits[0][0] is EventType.DEATH and hits[0][1] == "DEATH"


@pytest.mark.parametrize(
    "read",
    [
        "Consume 4 PrayerBeads toEnhancePhysical Attributes?",  # chunk 01 t 1142.5
        "MaximumVitality and Posture have increased.",          # chunk 01 t 1148.5
    ],
)
def test_confirmation_box_is_not_speech(profile, read):
    line = [OcrLine(read, 0.97, x0=0.10, y0=0.2, x1=0.90, y1=0.6)]
    assert profile.classify(FIELD, line, BLACK) == []
    assert profile.classify(SUBTITLE, line, BLACK) == []


def test_a_properly_spaced_line_is_still_speech(profile):
    # The same slice, six minutes later: the subtitle face keeps its spaces.
    text = "If I go through the cemetary there will be a path to the inner estate..."
    hits = profile.classify(FIELD, [OcrLine(text, 0.99, x0=0.05, y0=0.2, x1=0.95, y1=0.6)], BLACK)
    assert hits and hits[0][0] is EventType.DIALOGUE


@pytest.mark.parametrize(
    "read,want",
    [
        # chunk 02 t 485: the usual read, spaced on both sides.
        ("Ashina Elite - Jinsuke Saze", "Ashina Elite - Jinsuke Saze"),
        # t 502: fully glued. Kept as read — the repair only restores a
        # space OCR half-kept. normalize() drops the hyphen either way, so the
        # deduper and stats score the two forms at 100.
        ("Ashina Elite-Jinsuke Saze", "Ashina Elite-Jinsuke Saze"),
    ],
)
def test_dashed_miniboss_name_keeps_its_dash(profile, read, want):
    frame = load("sekiro", "boss_jinsuke.jpg")
    hits = profile.classify(BOSS, [OcrLine(read, 0.99, x0=0.045, y0=0.1, x1=0.40, y1=0.75)], frame)
    assert hits == [(EventType.BOSS_ENGAGED, want, pytest.approx(0.99, abs=0.02))]


def test_dash_glued_to_the_next_word(profile):
    # The stored JPEG of chunk 02 t 2412 reads "Spears -Shikibu"; before the
    # rule, _strip_edges ate the dash with the word's leading punctuation.
    frame = load("sekiro", "boss_sevenspears.jpg")
    read = "Seven Ashina Spears -Shikibu Toshikatsu Yamauchi"
    hits = profile.classify(BOSS, [OcrLine(read, 0.96, x0=0.03, y0=0.1, x1=0.95, y1=0.75)], frame)
    assert hits == [
        (EventType.BOSS_ENGAGED, "Seven Ashina Spears - Shikibu Toshikatsu Yamauchi", pytest.approx(0.96, abs=0.02))
    ]


def test_item_keeps_an_inner_hyphen_unspaced(profile):
    # "Scrap-Magnetite" (chunk 02) is one misread word, not a dashed name:
    # the dash rule is for boss bars only.
    hits = profile.classify(ITEM, [OcrLine("Scrap-Magnetite", 0.95, x0=0.30, y0=0.75, x1=0.93, y1=0.90)], BLACK)
    assert hits == [(EventType.ITEM_ACQUIRED, "Scrap-Magnetite", pytest.approx(0.95, abs=0.02))]


def test_main_boss_deathblow_is_a_defeat(profile):
    # The caption runs for five seconds or more and OCR loses its spaces:
    # chunk 00 t 2995 (Gyoubu), chunk 04 t 1778 (the Guardian Ape).
    for read in ("SHINOBIEXECUTION", "SHINOBI EXECUTION", "INOBI EXECUTION"):
        hits = profile.classify(CENTER, centred(read, 0.99), BLACK)
        assert hits and hits[0][0] is EventType.BOSS_DEFEATED and hits[0][1] == "SHINOBI EXECUTION", read


def test_bar_without_pips_is_still_a_bar(profile):
    # chunk 03: the Armored Warrior and the Folding Screen Monkeys show a
    # bar with no deathblow pips, which the first version of the check
    # required. The red fill is what confirms them.
    from previously_on.games.sekiro import has_boss_hp_bar, has_boss_pips

    for name, boss in (("boss_armored", "Armored Warrior"), ("boss_monkeys", "Folding Screen Monkeys")):
        frame = load("sekiro", f"{name}.jpg")
        assert not has_boss_pips(frame), name
        assert has_boss_hp_bar(frame), name
        hits = profile.classify(BOSS, [OcrLine(boss, 0.99, x0=0.045, y0=0.1, x1=0.40, y1=0.75)], frame)
        assert hits == [(EventType.BOSS_ENGAGED, boss, pytest.approx(0.99, abs=0.02))], name


def test_one_letter_before_an_apostrophe_is_not_a_possessive(profile):
    # chunk 04 t 2937: "O'Rin of the Water" was split into "O' Rin" by the
    # rule that repairs "Patches'Ashes".
    frame = load("sekiro", "boss_orin.jpg")
    hits = profile.classify(BOSS, [OcrLine("O'Rin of the Water", 0.98, x0=0.045, y0=0.1, x1=0.40, y1=0.75)], frame)
    assert hits == [(EventType.BOSS_ENGAGED, "O'Rin of the Water", pytest.approx(0.98, abs=0.02))]


@pytest.mark.parametrize(
    "read,want",
    [
        # Repaired: OCR kept the space on one side only (chunk 02 t 2412).
        ("Seven Ashina Spears -Shikibu Toshikatsu Yamauchi", "Seven Ashina Spears - Shikibu Toshikatsu Yamauchi"),
        # Left alone: the game writes these as one compound word.
        ("Lone Shadow Masanaga the Spear-Bearer", "Lone Shadow Masanaga the Spear-Bearer"),
        ("Great Shinobi-Owl", "Great Shinobi-Owl"),
        ("Great Shinobi - Owl", "Great Shinobi - Owl"),
    ],
)
def test_dash_repair_only_restores_a_half_kept_space(profile, read, want):
    frame = load("sekiro", "boss_masanaga.jpg")
    hits = profile.classify(BOSS, [OcrLine(read, 0.99, x0=0.02, y0=0.1, x1=0.95, y1=0.75)], frame)
    assert hits == [(EventType.BOSS_ENGAGED, want, pytest.approx(0.99, abs=0.02))], read


def test_mortal_blade_finisher_is_a_defeat(profile):
    # chunk 06 t 2580-2585, the True Corrupted Monk. OCR loses the space
    # and sometimes the leading letter.
    for read in ("IMMORTALITYSEVERED", "IMMORTALITY SEVERED", "MMORTALITYSEVERED", "IMMORTALITY-SEVERE"):
        hits = profile.classify(CENTER, centred(read, 0.99), BLACK)
        assert hits and hits[0][0] is EventType.BOSS_DEFEATED and hits[0][1] == "IMMORTALITY SEVERED", read


@pytest.mark.parametrize("item", ["Immortal Severance Text", "Immortal Severance Scrap"])
def test_immortal_severance_items_are_still_pickups(profile, item):
    # The banner phrase must not swallow the items named after it: they
    # score 69-71 against it, under match_vocab's 85.
    hits = profile.classify(ITEM, [OcrLine(item, 0.96, x0=0.10, y0=0.75, x1=0.93, y1=0.90)], BLACK)
    assert hits == [(EventType.ITEM_ACQUIRED, item, pytest.approx(0.96, abs=0.02))]


def test_floating_prompt_glued_to_a_pickup_row(profile):
    # chunk 07 t 1256.5: Sekiro draws the interaction prompt next to what
    # it is for, so "Talk" landed on the pickup row and join_rows made one
    # box of the two. The only such read in 631 distinct item-crop reads.
    hits = profile.classify(
        ITEM, [OcrLine("Talk Memory: Divine Dragon", 0.96, x0=0.05, y0=0.75, x1=0.93, y1=0.90)], BLACK
    )
    assert hits == [(EventType.ITEM_ACQUIRED, "Memory: Divine Dragon", pytest.approx(0.96, abs=0.02))]


@pytest.mark.parametrize("prompt", ["Talk", "Purchase", "Travel", "Pick Up Item"])
def test_a_bare_prompt_is_not_a_pickup(profile, prompt):
    hits = profile.classify(ITEM, [OcrLine(prompt, 0.99, x0=0.60, y0=0.75, x1=0.93, y1=0.90)], BLACK)
    assert hits == []


def test_area_name_snaps_to_a_known_one(profile):
    # chunk 07 t 796: the stored JPEG reads "Fountainhead Palacc".
    hits = profile.classify(AREA, centred("Fountainhead Palacc", 0.97, y0=0.25, y1=0.87), BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Fountainhead Palace", pytest.approx(0.97, abs=0.02))]


def test_snapping_cannot_turn_one_area_into_another(profile):
    # The closest pair of the ten areas the run produced scores 77.
    import itertools

    from rapidfuzz import fuzz

    from previously_on.classify import normalize
    from previously_on.games.sekiro import KNOWN_AREAS, KNOWN_AREA_MATCH

    for a, b in itertools.combinations(KNOWN_AREAS, 2):
        assert fuzz.ratio(normalize(a), normalize(b)) < KNOWN_AREA_MATCH, (a, b)
