"""Classifier rules for Dark Souls III — one test per fixture-backed rule.

Each test uses the real OCR read from a frame in tests/fixtures/ds3/ (the
mangled text, not the clean phrase) so a rule is never loosened from memory.
"""

from __future__ import annotations


import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.ds3 import (
    BANNER_VOCAB,
    BOSS_BAR,
    BOSS_BAR_RAISED,
    BOSS_HP_BAR_RAISED,
    CENTER_BANNER,
    ITEM_POPUP,
    SUBTITLE,
    has_boss_hp_bar,
    has_item_panel,
)
from previously_on.ocr import OcrLine

from .frames import load

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("ds3")


def L(text, conf=0.95, **box):
    return [OcrLine(text, conf, **box)]


def frame(name: str) -> np.ndarray:
    return load("ds3", name)


# Banner boxes as OCR returns them inside the centre crop (h 0.20 of the
# frame): BONFIRE LIT at t 438 is x 0.30-0.70, y 0.24-0.76.
BANNER_BOX = dict(x0=0.30, x1=0.70, y0=0.24, y1=0.76)
# Item rows inside the pickup crop: the name at x 0.22, the single row at
# y 0.84-0.97 (t 507), the upper row of a stack at 0.29-0.43 (t 1544).
ITEM_ROW = dict(x0=0.22, x1=0.45, y0=0.84, y1=0.97)
ITEM_ROW_UPPER = dict(x0=0.22, x1=0.45, y0=0.29, y1=0.43)
# The boss name inside its strip (t 545).
BOSS_NAME = dict(x0=0.02, x1=0.22, y0=0.23, y1=1.0)


@pytest.mark.parametrize("phrase", sorted(BANNER_VOCAB))
def test_banner_vocab_round_trips(profile, phrase):
    hits = profile.classify(CENTER_BANNER, L(phrase, **BANNER_BOX), BLACK)
    assert hits and hits[0][0] is BANNER_VOCAB[phrase] and hits[0][1] == phrase


@pytest.mark.parametrize(
    "read, phrase",
    [
        ("HEIR OFFIREDESTROYED", "HEIR OF FIRE DESTROYED"),  # t 2577, the letter-spaced font loses spaces
        ("HEIR OFFIRE DESTROYED", "HEIR OF FIRE DESTROYED"),  # t 2577 in the survey
        ("BONFIRELIT", "BONFIRE LIT"),  # t 439
        ("YOUDIED", "YOU DIED"),
    ],
)
def test_mangled_banner_reads_match(profile, read, phrase):
    hits = profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK)
    assert hits and hits[0][1] == phrase


@pytest.mark.parametrize(
    "read",
    [
        "EMBERRESTORED",  # t 597
        "EMBER RESTORED",
        "SOULS RETRIEVED",  # t 2026: the bloodstain, not the death that dropped it
        "JULS RETRIEVED",  # t 2027, mid-fade: the stoplist is matched fuzzily
        "DARK SPIRIT DESTROYED",  # t 3595: an invader killed, no bar to credit it to
        "DARKSPIRIT DESTROYED",
        "-DARK SOULSⅡI",  # t 0-4: the title splash, h 0.195
    ],
)
def test_non_event_banners_are_not_areas(profile, read):
    # Same font and band as the event banners; none of them is an event.
    assert profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK) == []


def test_all_caps_read_that_matches_nothing_is_not_an_area(profile):
    # Area names are drawn in Title Case; every all-caps banner is a fixed
    # phrase, so a garbled all-caps read is never a place.
    assert profile.classify(CENTER_BANNER, L("OBONFT ELT", 0.9, **BANNER_BOX), BLACK) == []


def test_area_fade_in_reads_snap_to_the_known_name(profile):
    box = dict(x0=0.34, x1=0.70, y0=0.20, y1=0.65)
    # t 261: the first letter is not up yet.
    assert profile.classify(CENTER_BANNER, L("emetery of Ash", 0.99, **box), BLACK) == [
        (EventType.AREA_DISCOVERED, "Cemetery of Ash", 0.99)
    ]
    # t 260: and misread when it is.
    assert profile.classify(CENTER_BANNER, L("Lemetery of Ash", 0.88, **box), BLACK)[0][1] == "Cemetery of Ash"
    # t 2964: an ornament read as an ampersand inside the word.
    assert profile.classify(CENTER_BANNER, L("UndeadS&ttlement", 0.92, **box), BLACK)[0][1] == "Undead Settlement"
    # An unknown name still has to look like one.
    assert profile.classify(CENTER_BANNER, L("Road of Sacrifices", 0.98, **box), BLACK)[0][1] == "Road of Sacrifices"
    assert profile.classify(CENTER_BANNER, L("some new place", 0.98, **box), BLACK) == []


def test_split_area_banner_with_an_ornament_letter_snaps(profile):
    # Chunk 02 t 1885: the fade-in read the banner as two boxes, the
    # ornament glued to the second as an "I", and the log got "Cathedral
    # Iof the Deep" before the area was known.
    lines = [
        OcrLine("Cathedral", 0.92, x0=0.24, x1=0.47, y0=0.13, y1=0.68),
        OcrLine("Iof the Deep", 0.89, x0=0.47, x1=0.76, y0=0.13, y1=0.68),
    ]
    assert profile.classify(CENTER_BANNER, lines, BLACK) == [(EventType.AREA_DISCOVERED, "Cathedral of the Deep", 0.89)]
    assert profile.classify(CENTER_BANNER, L("Cathedralof the Deep", 0.99, x0=0.24, x1=0.76, y0=0.13, y1=0.68), BLACK)[0][1] == "Cathedral of the Deep"


def test_split_area_reads_from_later_chunks_snap(profile):
    # Chunk 03 t 2728: "Irithyllc" + "of the Boreal Valley" as two boxes
    # (the ornament glued as a "c"); t 2357: "Smouldering" / "Lake".
    box = dict(y0=0.13, y1=0.68)
    lines = [OcrLine("Irithyllc", 0.91, x0=0.18, x1=0.40, **box), OcrLine("of the Boreal Valley", 0.95, x0=0.41, x1=0.82, **box)]
    assert profile.classify(CENTER_BANNER, lines, BLACK) == [(EventType.AREA_DISCOVERED, "Irithyll of the Boreal Valley", 0.91)]
    lines = [OcrLine("Smouldering", 0.92, x0=0.28, x1=0.58, **box), OcrLine("Lake", 0.99, x0=0.59, x1=0.72, **box)]
    assert profile.classify(CENTER_BANNER, lines, BLACK)[0][1] == "Smouldering Lake"


def test_dropped_letters_in_an_area_name_snap(profile):
    # Chunk 06 t 3280: "Painted Wod of Ariandel" — the name scores 96
    # against the known one, and nothing else in KNOWN_AREAS is above 53.
    box = dict(x0=0.24, x1=0.76, y0=0.13, y1=0.68)
    hits = profile.classify(CENTER_BANNER, L("Painted Wod of Ariandel", 0.96, **box), BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Painted World of Ariandel", 0.96)]


def test_glued_of_a_tail_in_an_item_name(profile):
    # Chunk 03 t 816: "Cindersofa Lord" under the LORD OF CINDER FALLEN banner.
    img = frame("lord_abyss_watchers_c03.jpg")
    hits = profile.classify(ITEM_POPUP, L("Cindersofa Lord", 0.96, x0=0.22, x1=0.47, y0=0.29, y1=0.43), img)
    assert hits == [(EventType.ITEM_ACQUIRED, "Cinders of a Lord", 0.96)]


def test_death_banner_is_tall_and_dim(profile):
    # The death clip: y 0.44-0.57 of the frame, read at 0.96-1.00 when the
    # dark red is at its brightest.
    box = dict(x0=0.29, x1=0.73, y0=0.17, y1=0.86)
    assert profile.classify(CENTER_BANNER, L("YOU DIED", 0.96, **box), BLACK) == [(EventType.DEATH, "YOU DIED", 0.96)]


def test_short_text_in_the_band_is_not_a_banner(profile):
    # The upper row of a stacked pickup would be centred enough but 0.028
    # tall; damage numbers (t 2400, "128") and the invasion notice's
    # counter (t 3463) are shorter still.
    assert profile.classify(CENTER_BANNER, L("Titanite Shard", 1.0, x0=0.37, x1=0.55, y0=0.60, y1=0.74), BLACK) == []
    assert profile.classify(CENTER_BANNER, L("128", 1.0, x0=0.47, x1=0.52, y0=0.13, y1=0.24), BLACK) == []


def test_item_names_get_their_spaces_back(profile):
    # OCR on the pickup crop glues the words (t 386, 1544, 2577).
    img = frame("item_unknown_traveler.jpg")
    row = L("SoulofanUnknownTraveler", 0.99, x0=0.22, x1=0.67, y0=0.84, y1=0.97)
    assert profile.classify(ITEM_POPUP, row, img) == [(EventType.ITEM_ACQUIRED, "Soul of an Unknown Traveler", 0.99)]
    img = frame("item_stack.jpg")
    rows = [OcrLine("TitaniteShard", 0.99, **ITEM_ROW_UPPER), OcrLine("Ember", 0.99, x0=0.22, x1=0.33, y0=0.84, y1=0.97)]
    assert [h[1] for h in profile.classify(ITEM_POPUP, rows, img)] == ["Titanite Shard", "Ember"]


def test_item_row_sits_on_a_pickup_row(profile):
    # Chunk 01 t 3361 / 2327: the invasion notices sit on a pickup-styled
    # panel (dark, ornament lines) at y 0.70 of the frame — between the
    # single row (0.78) and the upper row of a stack (0.67). A short
    # notice even starts where a name does.
    img = frame("neg_invaded_c01.jpg")
    notice = L("InvadedbydarkspiritObscur!", 0.98, x0=0.24, x1=0.71, y0=0.50, y1=0.62)
    assert profile.classify(ITEM_POPUP, notice, img) == []
    img = frame("neg_invader_died_c01.jpg")
    notice = L("DarkspiritYellowfingerHeyselhasdied", 0.99, x0=0.17, x1=0.78, y0=0.49, y1=0.62)
    assert profile.classify(ITEM_POPUP, notice, img) == []


def test_item_names_with_a_glued_of_before_a_capital(profile):
    # Chunk 01 t 2026: "BrailleDivineTomeof Carim" — four letters before
    # the "of", the first of them the capital.
    img = frame("item_titanite_shard.jpg")
    hits = profile.classify(ITEM_POPUP, L("BrailleDivineTomeof Carim", 0.98, x0=0.22, x1=0.62, y0=0.84, y1=0.97), img)
    assert hits == [(EventType.ITEM_ACQUIRED, "Braille Divine Tome of Carim", 0.98)]


def test_respace_leaves_a_correct_item_read_alone(profile):
    # Chunk 05 t 2421: OCR read "Horsehoof Ring" correctly and the glued
    # "of" rule split it into "Horseho of Ring".
    img = frame("item_horsehoof_ring_c05.jpg")
    rows = [
        OcrLine("Winged Spear", 1.0, **ITEM_ROW_UPPER),
        OcrLine("Horsehoof Ring", 1.0, x0=0.22, x1=0.48, y0=0.84, y1=0.97),
    ]
    assert [h[1] for h in profile.classify(ITEM_POPUP, rows, img)] == ["Winged Spear", "Horsehoof Ring"]


def test_apostrophe_glued_to_the_next_word(profile):
    # Chunk 05 t 2419: "Patches'Ashes". A name's own "'s" is not touched.
    img = frame("item_patches_ashes_c05.jpg")
    hits = profile.classify(ITEM_POPUP, L("Patches'Ashes", 0.98, x0=0.22, x1=0.44, y0=0.84, y1=0.97), img)
    assert hits == [(EventType.ITEM_ACQUIRED, "Patches' Ashes", 0.98)]


def test_partly_glued_item_name_is_respaced_before_the_checks(profile):
    # Chunk 09 t 2019: OCR read the final drop three ways in as many
    # frames. Only the fully glued one used to pass — the others have a
    # word starting lowercase ("theLords") and failed the Title Case check.
    img = frame("item_soul_of_the_lords_c09.jpg")
    for read in ("SouloftheLords", "Soul of theLords", "Soulof theLords"):
        hits = profile.classify(ITEM_POPUP, L(read, 1.0, x0=0.22, x1=0.50, y0=0.84, y1=0.97), img)
        assert hits == [(EventType.ITEM_ACQUIRED, "Soul of the Lords", 1.0)], read


def test_item_row_needs_the_panel(profile):
    # The long invasion notices (t 3463, 3595) start left of where a name
    # does and run past the count column.
    notice = L("InvadedbymaddarkspiritHolyKnightHodrick!", 0.98, x0=0.11, x1=0.84, y0=0.49, y1=0.62)
    assert profile.classify(ITEM_POPUP, notice, frame("neg_invaded.jpg")) == []
    # A name-shaped read at the name's position still needs the panel's
    # dark background and its ornament lines around the row.
    name = L("Titanite Shard", 0.99, **ITEM_ROW)
    assert profile.classify(ITEM_POPUP, name, frame("item_titanite_shard.jpg")) == [(EventType.ITEM_ACQUIRED, "Titanite Shard", 0.99)]
    assert profile.classify(ITEM_POPUP, name, frame("neg_open_world.jpg")) == []
    assert profile.classify(ITEM_POPUP, name, frame("neg_loading.jpg")) == []
    assert profile.classify(ITEM_POPUP, name, BLACK) == []


def test_item_panel_pixels_on_real_frames():
    single = OcrLine("Titanite Shard", 0.99, **ITEM_ROW)
    assert has_item_panel(frame("item_titanite_shard.jpg"), single)
    assert has_item_panel(frame("item_stack.jpg"), OcrLine("TitaniteShard", 0.99, **ITEM_ROW_UPPER))
    assert has_item_panel(frame("item_stack.jpg"), OcrLine("Ember", 0.99, x0=0.22, x1=0.33, y0=0.84, y1=0.97))
    for name in ("neg_open_world.jpg", "neg_loading.jpg", "neg_equipment.jpg", "neg_invaded.jpg", "boss_gundyr.jpg"):
        assert not has_item_panel(frame(name), single), name
    # A black frame is dark everywhere but has no ornament lines.
    assert not has_item_panel(BLACK, single)


def test_item_rows_reject_menus_and_caps(profile):
    # The title screen's prompt (t 0) is all caps; a menu list cut by the
    # crop's left edge starts at 0; the level-up table carries numbers.
    assert profile.classify(ITEM_POPUP, L("PRESSANYBUTTON", 0.99, x0=0.31, x1=0.64, y0=0.57, y1=0.69), BLACK) == []
    assert profile.classify(ITEM_POPUP, L("Titanite Shard", 0.99, x0=0.0, x1=0.2, y0=0.84, y1=0.97), BLACK) == []
    table = [OcrLine("Attributerequirement", 0.99, x0=0.14, x1=0.48, y0=0.8, y1=0.95), OcrLine("800", 1.0, x0=0.6, x1=0.66, y0=0.8, y1=0.95)]
    assert profile.classify(ITEM_POPUP, table, frame("neg_level_up.jpg")) == []


def test_subtitle_rejects_prompts_and_labels(profile):
    # Interaction prompts share the strip (t 507, 2025, 727): a button
    # glyph reads as a colon, and the hint row is not a sentence.
    for text in (":Pillage remains", ":OK", ":Recover lost souls", "X :OK O :Close", "Read messago", "Select bonfire to travel to.Ember indicates Host of Embers presence"):
        assert profile.classify(SUBTITLE, L(text, 0.97), BLACK) == [], text
    # The flask label's top edge falls inside the strip.
    for label in ("Flask", "Estus Flask", "EstusFlask", "Estus Flask+1"):
        assert profile.classify(SUBTITLE, L(label, 0.97), BLACK) == [], label
    # Glued onto a line, it is stripped (the Remastered pattern; the line
    # itself survives).
    hits = profile.classify(SUBTITLE, L("Estus FlaskThat ash seeketh embers.", 0.98), BLACK)
    assert hits and hits[0][1] == "That ash seeketh embers."
    # A line starting with F keeps its F.
    hits = profile.classify(SUBTITLE, L("Flee, before the fire fades.", 0.98), BLACK)
    assert hits and hits[0][1] == "Flee, before the fire fades."


def test_subtitle_is_a_sentence(profile):
    line = L("And they'd have us seek the Lords of Cinder, and return them to their moulding thrones.", 0.99, x0=0.03, x1=0.96, y0=0.12, y1=0.58)
    assert profile.classify(SUBTITLE, line, BLACK)[0][0] is EventType.DIALOGUE
    assert profile.classify(SUBTITLE, L("to equip", 0.96), BLACK) == []


@pytest.mark.parametrize(
    "read",
    [
        # The splash's copyright line, logged as dialogue at chunk 00 t 1.
        "Dark SoulsTM Ⅲl & O2016 BANDAI NAMCO Entertainment Inc./ 2011-2016FromSoftware,Inc.",
        # The end credits (c8DyAJgWCxY) read every half second: staff rows
        # with the company in brackets, a row of names, the publisher's
        # offices, the licence block.
        "Maaya Kawamura (Teco Co.,Lid.) Cha Dongwoon (Teco Co.,Lid.)",
        "Ryuichi Nakajima (Tricrest,inc) Daisuke Higuchi (Tricrest,ine)",
        "Additional Debug Pole To Win Co., Lid.",
        "Jianhui Wang Qingmei Zhao Vana Hh.",
        "BANDAI NAMCO EntertainmentEuropeSA.S.",
        "cSilicon Studio Corp., all rights reserved.",
        "Uses Bink Video.Copyright O 1997-2016 by RAD Game Tools, Inc.",
        "FONTWORKS,and font names are trademarks or registered trademarksofFontworks Inc.",
    ],
)
def test_credits_and_licence_lines_are_not_speech(profile, read):
    assert profile.classify(SUBTITLE, L(read, 0.93), BLACK) == []


def test_lad_and_lid_are_words_not_company_suffixes(profile):
    for text in ("You haven't given up yet? Then you're a brasher lad than I thought.",
                 "A lid covering an overgrown privy; a prop to keep thee from the dark soul of thine desire."):
        assert profile.classify(SUBTITLE, L(text, 0.97), BLACK)[0][0] is EventType.DIALOGUE


def test_boss_name_needs_the_bar(profile):
    name = L("Iudex Gundyr", 0.97, **BOSS_NAME)
    assert profile.classify(BOSS_BAR, name, frame("boss_gundyr.jpg")) == [(EventType.BOSS_ENGAGED, "Iudex Gundyr", 0.97)]
    # t 560: the bottom border line reads only 0.66 light over the bright arena.
    assert profile.classify(BOSS_BAR, name, frame("boss_gundyr_2.jpg")) == [(EventType.BOSS_ENGAGED, "Iudex Gundyr", 0.97)]
    # No bar under it (open world, a menu, a pickup panel): not a boss.
    for name_ in ("neg_open_world.jpg", "neg_equipment.jpg", "item_titanite_shard.jpg", "item_binoculars.jpg"):
        assert profile.classify(BOSS_BAR, name, frame(name_)) == [], name_
    assert profile.classify(BOSS_BAR, name, BLACK) == []


def test_two_bosses_get_two_bars(profile):
    # Chunk 08 t 350: "Demon in Pain" over "Demon from Below", the upper
    # bar's border lines 0.0602 above the lower one's. The upper name also
    # reaches the item crop, cut by its left edge to "emon in Pain".
    img = frame("boss_two_bars_c08.jpg")
    assert profile.classify(BOSS_BAR, L("Demon from Below", 0.97, **BOSS_NAME), img) == [
        (EventType.BOSS_ENGAGED, "Demon from Below", 0.97)
    ]
    assert profile.classify(BOSS_BAR_RAISED, L("Demon in Pain", 0.99, **BOSS_NAME), img) == [
        (EventType.BOSS_ENGAGED, "Demon in Pain", 0.99)
    ]
    assert profile.classify(ITEM_POPUP, L("emon in Pain", 0.93, x0=0.0, x1=0.2, y0=0.84, y1=0.97), img) == []
    # One bar: nothing raised above it.
    assert profile.classify(BOSS_BAR_RAISED, L("Iudex Gundyr", 0.97, **BOSS_NAME), frame("boss_gundyr.jpg")) == []


def test_glued_from_in_a_boss_name(profile):
    # Chunk 08 t 349: "DemonfromBelow" — "from" joins the glued small words.
    img = frame("boss_two_bars_c08.jpg")
    hits = profile.classify(BOSS_BAR, L("DemonfromBelow", 0.99, **BOSS_NAME), img)
    assert hits == [(EventType.BOSS_ENGAGED, "Demon from Below", 0.99)]


def test_boss_bar_pixels_on_real_frames():
    for name in ("boss_gundyr.jpg", "boss_gundyr_2.jpg", "boss_vordt.jpg", "boss_two_bars_c08.jpg"):
        assert has_boss_hp_bar(frame(name)), name
    assert has_boss_hp_bar(frame("boss_two_bars_c08.jpg"), bar=BOSS_HP_BAR_RAISED)
    for name in ("boss_gundyr.jpg", "boss_vordt.jpg", "item_titanite_shard.jpg", "neg_open_world.jpg"):
        assert not has_boss_hp_bar(frame(name), bar=BOSS_HP_BAR_RAISED), name
    # The pickup panel's bottom line sits at the bar's top-line height and
    # the "X :OK" box has a line of its own (0.94 / 0.95 on t 1201): the
    # spacing between them is wrong for a bar.
    for name in ("item_binoculars.jpg", "item_firebomb.jpg", "item_titanite_shard.jpg", "neg_open_world.jpg", "neg_bonfire_menu.jpg", "heir_vordt.jpg"):
        assert not has_boss_hp_bar(frame(name)), name
    assert not has_boss_hp_bar(BLACK)


def test_boss_name_gets_its_spaces_back(profile):
    # t 2530: "Vordtof the Boreal Valley"; the death clip: "PontiffSulyvahn".
    hits = profile.classify(BOSS_BAR, L("Vordtof the Boreal Valley", 0.96, x0=0.02, x1=0.5, y0=0.2, y1=1.0), frame("boss_vordt.jpg"))
    assert hits == [(EventType.BOSS_ENGAGED, "Vordt of the Boreal Valley", 0.96)]


def test_boss_strip_rejects_menu_labels_and_prompts(profile):
    img = frame("boss_gundyr.jpg")  # the bar is drawn; the text alone must fail
    # A pickup name cut by the strip's top edge starts at x 0.24 (t 507).
    assert profile.classify(BOSS_BAR, L("Titanite Shard", 1.0, x0=0.24, x1=0.45, y0=0.0, y1=0.3), img) == []
    # The bonfire menu's "Firelink Shrine" label starts at 0.24 of the frame
    # = left of the strip; a read starting at 0 is cut by the edge.
    assert profile.classify(BOSS_BAR, L("k Shrine", 0.93, x0=0.0, x1=0.1, y0=0.2, y1=0.9), img) == []
    # Numbers (the HP number, a stat) and lowercase reads are not names.
    assert profile.classify(BOSS_BAR, L("10", 1.0, x0=0.02, x1=0.06), img) == []
    assert profile.classify(BOSS_BAR, L("yordt of the Boreal Valley", 0.94, x0=0.02, x1=0.5), img) == []


def test_regions_are_consistent(profile):
    names = {r.name for r in profile.regions}
    assert set(profile.MIN_CONF) == names
    assert set(profile.quiet_after_event) <= names
    for typ in EventType:
        assert typ in profile.cooldowns
