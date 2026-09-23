"""Classifier rules for Dark Souls II: Scholar of the First Sin — one test per fixture-backed rule.

Each test uses the real OCR read from a frame in tests/fixtures/ds2/ (the
mangled text, not the clean phrase) so a rule is never loosened from memory.
"""

from __future__ import annotations


import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.ds2 import (
    _CREDITS_TOKEN,
    AREA_BANNER,
    BANNER_VOCAB,
    BOSS_BAR,
    BOSS_BAR_RAISED,
    BOSS_BAR_RAISED_2,
    BOSS_HP_BAR_RAISED,
    BOSS_HP_BAR_RAISED_2,
    CENTER_BANNER,
    ITEM_POPUP,
    SUBTITLE,
    _unglue_small,
    has_boss_hp_bar,
    has_hud,
    has_item_panel,
)
from previously_on.ocr import OcrLine

from .frames import load

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("ds2")


def L(text, conf=0.95, **box):
    return [OcrLine(text, conf, **box)]


def frame(name: str) -> np.ndarray:
    return load("ds2", name)


# Banner boxes as OCR returns them inside the lower crop (h 0.23 of the
# frame): BONFIRE LIT (0.647-0.766) is y 0.20-0.72 of the crop, x 0.24-0.75.
BANNER_BOX = dict(x0=0.24, x1=0.75, y0=0.20, y1=0.72)
# Area boxes inside the area crop (h 0.19): "Things Betwixt" (0.416-0.502)
# is y 0.29-0.75 of the crop, x 0.28-0.72.
AREA_BOX = dict(x0=0.28, x1=0.72, y0=0.29, y1=0.75)


@pytest.mark.parametrize("phrase", sorted(BANNER_VOCAB))
def test_banner_vocab_round_trips(profile, phrase):
    hits = profile.classify(CENTER_BANNER, L(phrase, **BANNER_BOX), BLACK)
    assert hits and hits[0][0] is BANNER_VOCAB[phrase] and hits[0][1] == phrase


@pytest.mark.parametrize(
    "read, phrase",
    [
        ("BONFIRELIT", "BONFIRE LIT"),  # bonfire_betwixt: the letter-spaced font loses its space
        ("VICTORY ACHIE VED", "VICTORY ACHIEVED"),  # chunk 01 t 1175, mid fade
        ("YOUDIED", "YOU DIED"),  # montage t 136
    ],
)
def test_mangled_banner_reads_match(profile, read, phrase):
    hits = profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK)
    assert hits and hits[0][1] == phrase


@pytest.mark.parametrize("read", ["RETRIEVAL", "INVADER BANISHED", "INVADERBANISHED"])
def test_lower_band_notices_are_not_events(profile, read):
    # Chunk 03 t 143 / 540: full-height banners that are not in the vocabulary.
    assert profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK) == []


def test_invader_name_tag_is_too_short_for_the_area_band(profile):
    # "Fencer Sharron" (chunk 03 t 3005): h 0.026 of the frame = 0.14 of the crop, off-centre.
    assert profile.classify(AREA_BANNER, L("Fencer Sharron", x0=0.73, x1=0.90, y0=0.44, y1=0.58), BLACK) == []


def test_lower_band_never_yields_an_area(profile):
    # Tall, centred, Title Case in the *lower* band: area names live in
    # their own band, so this can only be a mangled banner.
    assert profile.classify(CENTER_BANNER, L("Things Betwixt", **BANNER_BOX), BLACK) == []


def test_short_text_in_the_lower_band_is_not_a_banner(profile):
    # "A:Light bonfire" (t 661): 0.033 tall = 0.14 of the crop, centred.
    assert profile.classify(CENTER_BANNER, L("A:Light bonfire", x0=0.43, x1=0.60, y0=0.71, y1=0.85), BLACK) == []
    # A pickup row read through the lower band (t 753.5).
    assert profile.classify(CENTER_BANNER, L("Soul of a Nameless Soldier", x0=0.25, x1=0.51, y0=0.13, y1=0.25), BLACK) == []


def test_area_reveal(profile):
    hits = profile.classify(AREA_BANNER, L("Things Betwixt", **AREA_BOX), BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Things Betwixt", 0.95)]


def test_area_read_with_glued_words_snaps_to_the_known_name(profile):
    # t 1246, mid fade: not Title Case as read, but 85+ against the list.
    hits = profile.classify(AREA_BANNER, L("Forestof Fallen Giants", x0=0.20, x1=0.80, **{k: v for k, v in AREA_BOX.items() if k.startswith("y")}), BLACK)
    assert hits and hits[0][1] == "Forest of Fallen Giants"


def test_misread_area_snaps_to_the_known_name(profile):
    # Chunk 06 t 1851.5: the fade read "Shrineof Aiman" (93 against the
    # real name), and the deduper keeps the first read, not the best.
    hits = profile.classify(AREA_BANNER, L("Shrineof Aiman", **AREA_BOX), BLACK)
    assert hits and hits[0][1] == "Shrine of Amana"
    # The other Shrine must not be dragged in: the two score 71.
    hits = profile.classify(AREA_BANNER, L("Shrine of Winter", **AREA_BOX), BLACK)
    assert hits and hits[0][1] == "Shrine of Winter"


def test_unknown_area_must_look_like_a_name(profile):
    assert profile.classify(AREA_BANNER, L("forgotten ruins", **AREA_BOX), BLACK) == []
    hits = profile.classify(AREA_BANNER, L("Heide's Tower of Flame", **AREA_BOX), BLACK)
    assert hits and hits[0][0] is EventType.AREA_DISCOVERED


def test_short_centred_text_in_the_area_band_is_not_an_area(profile):
    # "Try to recall your name" (t 416): 0.035 tall = 0.18 of the crop.
    assert profile.classify(AREA_BANNER, L("Try to recall your name", x0=0.37, x1=0.64, y0=0.40, y1=0.58), BLACK) == []
    # The publisher splash (t 2), same height class.
    assert profile.classify(AREA_BANNER, L("BANDAI NAMCO GamesInc.", x0=0.31, x1=0.69, y0=0.70, y1=0.88), BLACK) == []


def test_all_caps_in_the_area_band_is_never_a_place(profile):
    assert profile.classify(AREA_BANNER, L("FROMSOFTWARE", **AREA_BOX), BLACK) == []
    assert profile.classify(AREA_BANNER, L("HUMANITY RESTORED", **AREA_BOX), BLACK) == []


def test_two_row_subtitle_joins(profile):
    # t 600: the last row's full stop is inside the strip since it grew to 0.915.
    lines = [
        OcrLine("This is alimbo.", 0.93, x0=0.38, x1=0.62, y0=0.35, y1=0.60),
        OcrLine("A link between Drangleic and the outer world.", 0.99, x0=0.13, x1=0.87, y0=0.62, y1=0.90),
    ]
    hits = profile.classify(SUBTITLE, lines, BLACK)
    assert hits and hits[0][0] is EventType.DIALOGUE
    assert hits[0][1] == "This is alimbo. A link between Drangleic and the outer world."


@pytest.mark.parametrize(
    "text",
    [
        "A:Close",  # the pickup panel's button, t 753.5
        "Touch Bloodstain",  # the prompt without its glyph, chunk 01 t 1350
        "Old Dragonslayer",  # the boss name crosses the strip, chunk 01
        "147",  # a damage number at the bar's right end
        "Pick an item",  # menu hint without its period
        ":Select A:Done B:Back",  # the menu hint row at y 0.91
        "Invaded by dark spiritFencerSharron!",  # a system notice in the subtitle bar, chunk 03 t 2967
        "InvadedbydarkspiritForlorn!",  # t 503
        "belluses Invaded by dark spirit Woodland Child Gully!",  # glued after a menu fragment, chunk 04 t 2832
        "Restatbonfire DarkspiritWoodland Child Victorhasbeenvanquished.",  # t 2801
    ],
)
def test_non_sentences_in_the_subtitle_strip(profile, text):
    assert profile.classify(SUBTITLE, L(text, x0=0.3, x1=0.7, y0=0.1, y1=0.4), BLACK) == []


@pytest.mark.parametrize(
    "text",
    [
        "nabe (Frognation Ltd) (Frognation Ltd)",  # chunk 08 t 1702
        "va (Teco Co.,Ltd.) mura (Teco Co.,Ltd.)",  # t 1954
        "ons Consultant- Tintagel K.K.)",  # t 1996
        "kai (D.H Inc.) ama (D.H Inc.)",  # t 1948
        "formmustreproducetheabovecopyright openssl-core@openssl.org.",  # the licence screen, t 2122
        "LIMITEDTOTHEWARRANTIESOFMERCHANTABILITY,FITNESSFORAPARTICULAR",  # t 2118
    ],
)
def test_credits_and_licence_are_not_dialogue(profile, text):
    assert profile.classify(SUBTITLE, L(text, x0=0.1, x1=0.9, y0=0.1, y1=0.4), BLACK) == []


@pytest.mark.parametrize(
    "text",
    [
        "Great Sovereign, take your throne.",  # the real ending lines, same sequence
        "You, who link the fire, you, who bear the curse...",
        "What lies ahead, only you can see.",
        "It is your choice...to embrace, or renounce this..",
    ],
)
def test_ending_lines_survive_the_credits_rule(profile, text):
    assert not _CREDITS_TOKEN.search(text)
    hits = profile.classify(SUBTITLE, L(text, x0=0.1, x1=0.9, y0=0.1, y1=0.4), BLACK)
    assert hits and hits[0][0] is EventType.DIALOGUE


def test_boss_name_punctuation_is_respaced(profile):
    # Chunk 08 t 1288: "Aldia,Scholar of the First Sin".
    img = frame("boss_aldia_c08.jpg")
    hits = profile.classify(BOSS_BAR, L("Aldia,Scholar of the First Sin", conf=0.96, x0=0.02, x1=0.45, y0=0.17, y1=0.91), img)
    assert hits == [(EventType.BOSS_ENGAGED, "Aldia, Scholar of the First Sin", 0.96)]


def test_boss_bar_reads_name_when_the_bar_is_drawn(profile):
    img = frame("boss_old_dragonslayer_c01.jpg")
    assert has_hud(img) and has_boss_hp_bar(img)
    hits = profile.classify(BOSS_BAR, L("Old Dragonslayer", conf=0.98, x0=0.02, x1=0.31, y0=0.17, y1=0.91), img)
    assert hits == [(EventType.BOSS_ENGAGED, "Old Dragonslayer", 0.98)]


def test_boss_bar_rejects_names_without_the_bar(profile):
    # The same read over a frame with no boss bar: a menu label, a tag.
    img = frame("subtitle_herald_two_rows.jpg")
    assert has_hud(img) and not has_boss_hp_bar(img)
    assert profile.classify(BOSS_BAR, L("Old Dragonslayer", conf=0.98, x0=0.02, x1=0.31, y0=0.17, y1=0.91), img) == []


def test_boss_bar_rejects_a_centred_prompt(profile):
    # "Touch Bloodstain" (chunk 01 t 1350) starts at x 0.45 of the frame =
    # 0.40 of the strip; names start at 0.02.
    img = frame("boss_old_dragonslayer_c01.jpg")
    assert profile.classify(BOSS_BAR, L("Touch Bloodstain", x0=0.40, x1=0.65, y0=0.1, y1=0.9), img) == []


def test_three_stacked_bars(profile):
    # The Ruin Sentinels (chunk 02 t 850): one bar per strip, each with its own lines.
    img = frame("boss_ruin_sentinels_three_bars_c02.jpg")
    assert has_boss_hp_bar(img) and has_boss_hp_bar(img, bar=BOSS_HP_BAR_RAISED) and has_boss_hp_bar(img, bar=BOSS_HP_BAR_RAISED_2)
    box = dict(x0=0.02, x1=0.40, y0=0.17, y1=0.91)
    assert profile.classify(BOSS_BAR_RAISED, L("Ruin Sentinel Ricce", **box), img) == [(EventType.BOSS_ENGAGED, "Ruin Sentinel Ricce", 0.95)]
    assert profile.classify(BOSS_BAR_RAISED_2, L("Ruin Sentinel Alessia", **box), img) == [(EventType.BOSS_ENGAGED, "Ruin Sentinel Alessia", 0.95)]
    # A single-bar fight has no lines in the raised strips.
    one = frame("boss_old_dragonslayer_c01.jpg")
    assert not has_boss_hp_bar(one, bar=BOSS_HP_BAR_RAISED) and not has_boss_hp_bar(one, bar=BOSS_HP_BAR_RAISED_2)


def test_pickup_row_under_the_top_raised_strip_is_not_a_boss(profile):
    # The panel's bottom row (x 0.322 = 0.115 of the strip) sits inside
    # BOSS_BAR_RAISED_2; names start at 0.02, and the panel has no bar lines.
    img = frame("item_stacked_soul_lifegem.jpg")
    assert profile.classify(BOSS_BAR_RAISED_2, L("Lifegem", x0=0.115, x1=0.25, y0=0.1, y1=0.9), img) == []
    assert not has_boss_hp_bar(img, bar=BOSS_HP_BAR_RAISED_2)


def test_boss_hp_bar_pixel_check():
    assert has_boss_hp_bar(frame("boss_old_dragonslayer_hit_c01.jpg"))
    for name in ("bonfire_betwixt.jpg", "item_stacked_soul_lifegem.jpg", "neg_black_c01.jpg", "death_montage_12.jpg"):
        assert not has_boss_hp_bar(frame(name)), name


# Item rows inside the item crop (h 0.15): the bottom row (0.668-0.707) is
# y 0.65-0.91 of the crop, the row above it (0.629-0.659) 0.39-0.59; names
# start at x 0.07.
ROW_BOTTOM = dict(y0=0.65, y1=0.91)
ROW_ABOVE = dict(y0=0.39, y1=0.59)


def test_stacked_pickup_with_glued_small_words(profile):
    img = frame("item_stacked_soul_lifegem.jpg")
    lines = [
        OcrLine("Soul ofa Nameless Soldier", 0.96, x0=0.072, x1=0.47, **ROW_ABOVE),
        OcrLine("Lifegem", 1.00, x0=0.069, x1=0.20, **ROW_BOTTOM),
        OcrLine("X3", 0.79, x0=0.89, x1=0.94, **ROW_BOTTOM),
    ]
    hits = profile.classify(ITEM_POPUP, lines, img)
    assert [h[1] for h in hits] == ["Soul of a Nameless Soldier", "Lifegem"]


def test_unglue_small_leaves_real_names_alone():
    assert _unglue_small("Soul ofa Lost Undead") == "Soul of a Lost Undead"
    assert _unglue_small("Soulofa Lost Undead") == "Soul of a Lost Undead"  # chunk 00 t 1237
    assert _unglue_small("Waterproof Cloak") == "Waterproof Cloak"
    assert _unglue_small("Soulof the Last Giant") == "Soul of the Last Giant"  # chunk 01 t 113.5, after respace
    assert _unglue_small("Hoof of Doom") == "Hoof of Doom"
    assert _unglue_small("Seed of a Tree of Giants") == "Seed of a Tree of Giants"
    assert _unglue_small("Estus Flask Shard") == "Estus Flask Shard"


def test_camel_glued_item_name_is_respaced(profile):
    # Chunk 00 run, t 1375: the pickup font loses the space between words.
    img = frame("item_hollow_infantry_helm.jpg")
    hits = profile.classify(ITEM_POPUP, L("HollowInfantry Armor", conf=0.98, x0=0.072, x1=0.40, **ROW_BOTTOM), img)
    assert [h[1] for h in hits] == ["Hollow Infantry Armor"]


@pytest.mark.parametrize(
    "read, name",
    [
        ("Pharros'Lockstone", "Pharros' Lockstone"),  # chunk 04 t 1658
        ("Smooth&SilkyStone", "Smooth & Silky Stone"),  # t 2047
        ("Executioner's Chariot", "Executioner's Chariot"),  # an apostrophe before a lowercase letter stays
    ],
)
def test_item_punctuation_is_respaced(profile, read, name):
    img = frame("item_stacked_soul_lifegem.jpg")
    hits = profile.classify(ITEM_POPUP, L(read, conf=0.98, x0=0.072, x1=0.40, **ROW_BOTTOM), img)
    assert [h[1] for h in hits] == [name]


def test_item_rows_must_start_after_the_icon(profile):
    img = frame("item_stacked_soul_lifegem.jpg")
    # A shop or inventory list cut by the crop's left edge (t 1855).
    assert profile.classify(ITEM_POPUP, L("Lenigrast's Key", x0=0.0, x1=0.2, **ROW_BOTTOM), img) == []
    # A tall banner's lower half read as a word (bonfire_betwixt: "RONEIRELT").
    assert profile.classify(ITEM_POPUP, L("RONEIRELT", x0=0.1, x1=0.8, y0=0.5, y1=1.0), img) == []


def test_item_rows_need_the_panel(profile):
    # The same row over a frame without the panel: a name tag or a label.
    img = frame("subtitle_herald_two_rows.jpg")
    assert has_hud(img)
    assert profile.classify(ITEM_POPUP, L("Lifegem", x0=0.069, x1=0.20, **ROW_BOTTOM), img) == []


def test_item_panel_pixel_check():
    row = OcrLine("Lifegem", 1.0, x0=0.069, x1=0.20, **ROW_BOTTOM)
    assert has_item_panel(frame("item_stacked_soul_lifegem.jpg"), row)
    assert not has_item_panel(frame("neg_open_world.jpg"), row)


def test_item_rows_need_the_hud(profile):
    # Credits, splash and menus carry no HP bar; nothing is picked up there.
    img = frame("neg_menu_shop.jpg")
    assert not has_hud(img)
    assert profile.classify(ITEM_POPUP, L("Lenigrast's Key", x0=0.07, x1=0.3, **ROW_BOTTOM), img) == []


def test_hud_gate_on_fixtures():
    for name in ("area_things_betwixt.jpg", "item_rusted_coin.jpg", "bonfire_majula.jpg"):
        assert has_hud(frame(name)), name  # t 284 is at half HP in a dark scene
    for name in ("neg_menu_shop.jpg", "neg_splash_from.jpg", "death_montage_12.jpg"):
        assert not has_hud(frame(name)), name


def test_stat_table_is_not_a_pickup(profile):
    # The level-up screen (chunk 01 t 450): numbers left of the count column.
    img = frame("neg_level_up_c01.jpg")
    lines = [
        OcrLine("Cast speed", 0.97, x0=0.30, x1=0.45, **ROW_ABOVE),
        OcrLine("47", 1.00, x0=0.55, x1=0.60, **ROW_ABOVE),
    ]
    assert profile.classify(ITEM_POPUP, lines, img) == []
