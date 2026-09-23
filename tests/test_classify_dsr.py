"""Classifier rules for Dark Souls: Remastered — one test per fixture-backed rule.

Each test uses the real OCR read from a frame in tests/fixtures/dsr/ (the
mangled text, not the clean phrase) so a rule is never loosened from memory.
"""

from __future__ import annotations


import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.dsr import (
    BANNER_VOCAB,
    has_hud,
    has_item_panel,
    BOSS_BAR,
    BOSS_BAR_RAISED,
    BOSS_HP_BAR_RAISED,
    CENTER_BANNER,
    ITEM_POPUP,
    SUBTITLE,
    has_boss_hp_bar,
)
from previously_on.ocr import OcrLine

from .frames import load

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("dsr")


def L(text, conf=0.95, **box):
    return [OcrLine(text, conf, **box)]


def frame(name: str) -> np.ndarray:
    return load("dsr", name)


# Banner boxes as OCR returns them inside the centre crop (h 0.21 of the
# frame): a 0.10-tall banner is ~0.47 of the crop.
BANNER_BOX = dict(x0=0.13, x1=0.88, y0=0.33, y1=0.80)


@pytest.mark.parametrize("phrase", sorted(BANNER_VOCAB))
def test_banner_vocab_round_trips(profile, phrase):
    hits = profile.classify(CENTER_BANNER, L(phrase, **BANNER_BOX), BLACK)
    assert hits and hits[0][0] is BANNER_VOCAB[phrase] and hits[0][1] == phrase


@pytest.mark.parametrize(
    "read, phrase",
    [
        ("VICTORY ACHEVED", "VICTORY ACHIEVED"),  # t 580, first frame of the fade-in
        ("VICTORYACHIEVED", "VICTORY ACHIEVED"),  # t 1792, letter-spaced font loses the space
        ("EBONFIRE LIT", "BONFIRE LIT"),  # t 2512, ornament read as a letter
        ("BONFIRELIT", "BONFIRE LIT"),  # t 377
    ],
)
def test_mangled_banner_reads_match(profile, read, phrase):
    hits = profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK)
    assert hits and hits[0][1] == phrase


@pytest.mark.parametrize(
    "read",
    [
        "HUMANITYRESTORED",  # t 1092
        "HUMANITY RESTORED",
        "HUMANITY ACQUIRED",  # chunk 01 t 2165
        "HUMANITYACQUIRED",
        "RETRIEVAL",  # chunk 01 t 1353: the bloodstain, not the death that dropped it
        "RETRIEVAI",  # chunk 01 t 1352, L read as I: the stoplist is matched fuzzily
    ],
)
def test_non_event_banners_are_not_areas(profile, read):
    # Same font and band as the event banners; none of them is an event.
    assert profile.classify(CENTER_BANNER, L(read, **BANNER_BOX), BLACK) == []


def test_all_caps_read_that_matches_nothing_is_not_an_area(profile):
    # Chunk 01 t 2724: BONFIRE LIT read as two boxes, "BONE" and "RELIT",
    # scores 84 against the phrase — under the vocabulary threshold — and
    # became the area "Bone Relit". Area names are drawn in Title Case.
    lines = [
        OcrLine("BONE", 0.9, x0=0.25, x1=0.48, y0=0.3, y1=0.8),
        OcrLine("RELIT", 0.88, x0=0.50, x1=0.74, y0=0.3, y1=0.8),
    ]
    assert profile.classify(CENTER_BANNER, lines, BLACK) == []


def test_two_line_area_read_mid_fade_snaps_to_the_known_name(profile):
    # Chunk 05 t 2075: "Tomb of the Giants" wraps onto two lines and the
    # fade-in glues its small words; a read that snaps to a known area
    # (>= 85) is taken without the Title Case check. A worse garble is not.
    def two(a, b):
        return [OcrLine(a, 0.98, x0=0.3, x1=0.7, y0=0.1, y1=0.45), OcrLine(b, 0.98, x0=0.35, x1=0.65, y0=0.5, y1=0.85)]

    assert profile.classify(CENTER_BANNER, two("Tomb ofthe", "Giants"), BLACK)[0][1] == "Tomb of the Giants"
    assert profile.classify(CENTER_BANNER, two("Tomb", "ofhe Giants"), BLACK)[0][1] == "Tomb of the Giants"
    assert profile.classify(CENTER_BANNER, two("Tomb oll", "Gants"), BLACK) == []
    # An unknown name still has to look like one.
    assert profile.classify(CENTER_BANNER, L("Painted World ofAriamis", 0.98, **BANNER_BOX), BLACK)[0][1] == "Painted World of Ariamis"
    assert profile.classify(CENTER_BANNER, L("some new place", 0.98, **BANNER_BOX), BLACK) == []


def test_death_banner_is_tall_and_dim(profile):
    # The death compilation, rectified: y 0.45-0.61 of the frame, read at
    # conf 0.95-1.00 despite the dark red.
    box = dict(x0=0.23, x1=0.77, y0=0.21, y1=0.88)
    assert profile.classify(CENTER_BANNER, L("YOU DIED", 0.95, **box), BLACK) == [(EventType.DEATH, "YOU DIED", 0.95)]
    assert profile.classify(CENTER_BANNER, L("YOUDIED", 1.0, **box), BLACK)[0][1] == "YOU DIED"


def test_flourish_glued_to_a_name_is_dropped(profile):
    # Chunk 01 t 1405: the ornament beside the banner reads as a quote.
    hits = profile.classify(CENTER_BANNER, L("'Depths", 0.96, x0=0.35, x1=0.62, y0=0.15, y1=0.55), BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Depths", 0.96)]
    # Chunk 01 t 427: a star and a misread over the butterfly's glow. The
    # misread stays (names are stored as read; stats fold at 85 %).
    bar = frame("boss_bar_moonlight_butterfly_c01.jpg")
    hits = profile.classify(BOSS_BAR, L("*MoMlight Butterfly", 0.9, x0=0.03, x1=0.4, y0=0.2, y1=0.9), bar)
    assert hits == [(EventType.BOSS_ENGAGED, "MoMlight Butterfly", 0.9)]


def test_area_banner_is_title_case_and_tall(profile):
    # t 3472: OCR split "Darkroot Garden" into two boxes on one row.
    lines = [
        OcrLine("Darkroot", 1.0, x0=0.26, x1=0.55, y0=0.15, y1=0.60),
        OcrLine("t Garden", 0.98, x0=0.55, x1=0.74, y0=0.15, y1=0.60),
    ]
    hits = profile.classify(CENTER_BANNER, lines, BLACK)
    assert hits == [(EventType.AREA_DISCOVERED, "Darkroot Garden", 0.98)]
    # The upper row of a stacked pickup (t 1795, "Humanity" at y 0.55 of the
    # frame) is centred enough but 0.03 tall: never a banner.
    short = L("Humanity", 1.0, x0=0.32, x1=0.42, y0=0.64, y1=0.78)
    assert profile.classify(CENTER_BANNER, short, BLACK) == []


def test_subtitle_drops_the_estus_flask_label(profile):
    # t 3255: the line is drawn over the HUD label and OCR glues them.
    hits = profile.classify(SUBTITLE, L("EstusThoulappearest to lack faith, yet magnanimous are the Gods.", 0.98), BLACK)
    assert hits and hits[0][1] == "Thoulappearest to lack faith, yet magnanimous are the Gods."
    # On its own, in every spelling seen, the label is not speech.
    for label in ("Estus Flask", "EstusFlask", "EstusFlask+1", "Estus Flask+1"):
        assert profile.classify(SUBTITLE, L(label, 0.97), BLACK) == [], label
    # The upgrade suffix reads as "+l"/"+i" and glues onto the line (chunk 01).
    for read, want in (
        ("Estus Flask+l Neither of us want to see you go Hollow.", "Neither of us want to see you go Hollow."),
        ("Estus Flask+iOnly unkempt crooks and liars to be found there.", "Only unkempt crooks and liars to be found there."),
        ("Estus Flaskf1 There is no time for idle chat.", "There is no time for idle chat."),
        ("Estus FlaWell, what do we have here? You must be a new arrival.", "Well, what do we have here? You must be a new arrival."),
        ("Estus FlAhh, hello. Was it you who rang the Bell of Awakening?", "Ahh, hello. Was it you who rang the Bell of Awakening?"),  # chunk 02
        ("Estus Flask+A pyromancer must be in tune with nature herself.", "A pyromancer must be in tune with nature herself."),  # chunk 02
        ("Estus Flask+ What am I? Well...I am the Keeper of the bonfire.", "What am I? Well...I am the Keeper of the bonfire."),  # chunk 02
    ):
        hits = profile.classify(SUBTITLE, L(read, 0.95), BLACK)
        assert hits and hits[0][1] == want, read
    # Split into two boxes ("Est" / "Flas", t 1092.5) it is still nothing.
    assert profile.classify(SUBTITLE, [OcrLine("Est", 0.95, x0=0.0, x1=0.05), OcrLine("Flas", 0.99, x0=0.06, x1=0.12)], BLACK) == []


def test_subtitle_rejects_button_hints(profile):
    # The menu hint row shares the strip (t 1043); "A:OK" sits just above it.
    for text in (":Select A :Equip B :Back X :Toggle Display Y :Toggle Status", ":Close X :Toggle Display", "A :Rest at bonfire", "A:OK"):
        assert profile.classify(SUBTITLE, L(text, 0.99), BLACK) == [], text


def test_boss_name_needs_the_bar(profile):
    name = L("Asylum Demon", 0.99, x0=0.04, x1=0.27, y0=0.2, y1=0.9)
    assert profile.classify(BOSS_BAR, name, frame("boss_bar_asylum_demon.jpg")) == [(EventType.BOSS_ENGAGED, "Asylum Demon", 0.99)]
    # No bar under it (open world, a menu): a menu label, not a boss.
    assert profile.classify(BOSS_BAR, name, frame("neg_open_world.jpg")) == []
    assert profile.classify(BOSS_BAR, name, frame("neg_menu_forge.jpg")) == []
    assert profile.classify(BOSS_BAR, name, BLACK) == []


def test_boss_bar_pixels_on_real_frames():
    assert has_boss_hp_bar(frame("boss_bar_asylum_demon.jpg"))
    assert has_boss_hp_bar(frame("boss_bar_taurus_demon.jpg"))
    two = frame("boss_bar_gargoyles_two.jpg")
    assert has_boss_hp_bar(two) and has_boss_hp_bar(two, bar=BOSS_HP_BAR_RAISED)
    for name in ("neg_open_world.jpg", "neg_menu_forge.jpg", "neg_cutscene_black.jpg", "victory_asylum_demon.jpg", "item_large_soul.jpg"):
        assert not has_boss_hp_bar(frame(name)), name
        assert not has_boss_hp_bar(frame(name), bar=BOSS_HP_BAR_RAISED), name
    # A black frame has "dark lines" everywhere; no bar.
    assert not has_boss_hp_bar(BLACK)


def test_boss_strip_rejects_menu_labels_and_prompts(profile):
    bar = frame("boss_bar_asylum_demon.jpg")
    # Level-up labels start at x >= 0.70 of the frame, far right of the name.
    assert profile.classify(BOSS_BAR, L("Humanity", 1.0, x0=0.9, x1=1.0), bar) == []
    assert profile.classify(BOSS_BAR, L("Claymore+1", 0.99, x0=0.02, x1=0.2), bar) == []  # forge menu, t 2578
    assert profile.classify(BOSS_BAR, L("A:OK", 0.98, x0=0.05, x1=0.15), bar) == []
    assert profile.classify(BOSS_BAR, L("VICTORY ACHIEVED", 0.98, x0=0.05, x1=0.95), bar) == []


def test_credits_fill_the_strips_with_names(profile):
    # Chunk 06 t 2209: two credit rows in the raised strip, six in the item
    # crop, all Title Case on black — the pixel checks pass, the line
    # counts do not.
    credits = frame("neg_credits_cast_c06.jpg")
    rows = [
        OcrLine("riscilla,theDragonLrossbreed", 0.9, x0=0.0, x1=0.4, y0=0.0, y1=0.45),
        OcrLine("ClareCorbett", 0.99, x0=0.5, x1=0.7, y0=0.0, y1=0.45),
        OcrLine("KnightLautrecofCarim", 0.99, x0=0.02, x1=0.4, y0=0.55, y1=1.0),
        OcrLine("DanielRoberts", 0.99, x0=0.5, x1=0.7, y0=0.55, y1=1.0),
    ]
    assert profile.classify(BOSS_BAR_RAISED, rows, credits) == []
    column = [
        OcrLine(t, 0.99, x0=0.15, x1=0.5, y0=0.1 + i * 0.13, y1=0.2 + i * 0.13)
        for i, t in enumerate(["Project Managers", "SumitArora", "PiyooshSah", "Test Coordinator", "NeerajBhardwaj", "TestLeads"])
    ]
    assert profile.classify(ITEM_POPUP, column, frame("neg_credits_column_c06.jpg")) == []


def test_hud_gate_on_real_frames(profile):
    for name in ("item_large_soul.jpg", "boss_bar_capra_demon_c01.jpg", "boss_bar_nito_dark_arena_c05.jpg", "victory_asylum_demon.jpg"):
        assert has_hud(frame(name)), name
    for name in ("neg_credits_cast_c06.jpg", "neg_credits_column_c06.jpg", "subtitle_intro_wide.jpg", "neg_menu_forge.jpg"):
        assert not has_hud(frame(name)), name
    # A saturated scene under the zone (the intro's fire sky, t 24) passes
    # the gate: it is a gate against black and grey screens, not the only one.
    assert has_hud(frame("neg_cutscene_black.jpg"))
    # A single credit line at the pickup row, or joined across the two
    # columns in the boss strip, passes every text rule; the HUD gate is
    # what rejects it (chunk 06 t 2118, 2209).
    credits = frame("neg_credits_cast_c06.jpg")
    assert profile.classify(ITEM_POPUP, L("President&COO Naoki Katashima", 0.93, **ITEM_ROW), credits) == []
    assert profile.classify(BOSS_BAR_RAISED, L("Knight Lautrec of Carim Daniel Roberts", 0.99, x0=0.0, x1=0.6, y0=0.2, y1=0.9), credits) == []


@pytest.mark.parametrize(
    "line",
    [
        "MasatoshiSakuma AdditionalDebug Pole To Win Co.,Ltd.",
        "Marketing Executive Janice Teo(Singapore)",
        "MusicComposer MotoiSakuraba EndingVocal EmiEvans (freesscape)",
        "MoCap Studio IMAGICA Corp.",
        "Production&ProjectManagement KengoWatanabe (Frognation Ltd) LynnRobson (Frognation Ltd)",
        "CG Movie SHIROGUMI INC.",
        "Surround Sound MA Engineering PROCYON STUDIO CO.,LTD.",
    ],
)
def test_credit_lines_are_not_dialogue(profile, line):
    # Chunk 06 t 2051-2230: credit lines end like sentences.
    assert profile.classify(SUBTITLE, L(line, 0.97), BLACK) == []
    # Solaire (t 2500): "co-" is not a company.
    assert profile.classify(SUBTITLE, L("and engage in jolly co-operation!", 1.0), BLACK) != []


def test_boss_name_keeps_its_comma(profile):
    # Chunk 06 t 1847: "Gwyn, Lord of Cinder".
    bar = frame("boss_bar_gwyn_c06.jpg")
    hits = profile.classify(BOSS_BAR, L("Gwyn, Lord of Cinder", 0.99, x0=0.04, x1=0.4, y0=0.2, y1=0.9), bar)
    assert hits == [(EventType.BOSS_ENGAGED, "Gwyn, Lord of Cinder", 0.99)]


def test_raised_bar_reads_the_second_boss(profile):
    two = frame("boss_bar_gargoyles_two.jpg")
    name = L("Bell Gargoyle", 1.0, x0=0.04, x1=0.28, y0=0.2, y1=0.9)
    assert profile.classify(BOSS_BAR_RAISED, name, two) == [(EventType.BOSS_ENGAGED, "Bell Gargoyle", 1.0)]
    assert profile.classify(BOSS_BAR_RAISED, name, frame("boss_bar_asylum_demon.jpg")) == []


ITEM_ROW = dict(x0=0.176, x1=0.71, y0=0.75, y1=0.88)


def test_item_names_are_left_aligned_after_the_icon(profile):
    hits = profile.classify(ITEM_POPUP, L("Large Soul of a Lost Undead", 0.99, **ITEM_ROW))
    assert hits == [(EventType.ITEM_ACQUIRED, "Large Soul of a Lost Undead", 0.99)]
    # A shop or inventory list cut by the crop edge starts at 0 (t 1324).
    assert profile.classify(ITEM_POPUP, L("Tool for repairing weapons/armor at bonfire", 0.97, x0=0.0, x1=0.36, y0=0.1, y1=0.2)) == []
    # The level-up screen's stat labels start at 0.27 (t 1080).
    assert profile.classify(ITEM_POPUP, L("Physical Def.", 1.0, x0=0.272, x1=0.483, y0=0.11, y1=0.26)) == []


def test_item_popup_rejects_stat_tables_and_banners(profile):
    # t 1080: a number left of the count column means a stat table.
    lines = [
        OcrLine("Physical Def.", 1.0, x0=0.176, x1=0.48, y0=0.11, y1=0.26),
        OcrLine("84", 1.0, x0=0.613, x1=0.669, y0=0.11, y1=0.26),
    ]
    assert profile.classify(ITEM_POPUP, lines) == []
    # The crop's top overlaps the banner band: an all-caps fragment is a banner.
    assert profile.classify(ITEM_POPUP, L("ORY ACHIE", 0.9, x0=0.18, x1=0.6, y0=0.0, y1=0.2)) == []
    assert profile.classify(ITEM_POPUP, L("VICTORY ACHIEVED", 0.97, x0=0.18, x1=0.9, y0=0.0, y1=0.2)) == []


def test_item_row_needs_the_dark_panel(profile):
    tag = frame("neg_phantom_name_tag_c01.jpg")
    row = OcrLine("WitchBeatrice", 0.99, x0=0.205, x1=0.39, y0=0.72, y1=0.86)
    assert not has_item_panel(tag, row)
    assert profile.classify(ITEM_POPUP, [row], tag) == []
    # Without a frame the pixel check is skipped and the read stands.
    assert profile.classify(ITEM_POPUP, [row]) == [(EventType.ITEM_ACQUIRED, "WitchBeatrice", 0.99)]
    real = frame("item_large_soul.jpg")
    assert has_item_panel(real, OcrLine("Large Soul of a Lost Undead", 0.99, **ITEM_ROW))
    assert profile.classify(ITEM_POPUP, L("Large Soul of a Lost Undead", 0.99, **ITEM_ROW), real) != []


def test_stacked_pickups_yield_one_event_each(profile):
    lines = [
        OcrLine("Humanity", 1.0, x0=0.175, x1=0.356, y0=0.048, y1=0.203),
        OcrLine("Homeward Bone", 1.0, x0=0.175, x1=0.486, y0=0.736, y1=0.881),
    ]
    assert [h[1] for h in profile.classify(ITEM_POPUP, lines)] == ["Humanity", "Homeward Bone"]


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
    # The name strips stop above the bars' top border lines (0.812 and
    # 0.749 of the frame): the fill under them changes every hit.
    assert BOSS_BAR.y + BOSS_BAR.h <= 0.812
    assert BOSS_BAR_RAISED.y + BOSS_BAR_RAISED.h <= 0.749
