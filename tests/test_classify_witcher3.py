"""Classifier rules for The Witcher 3: Wild Hunt.

Each test uses the real OCR read (crop-relative boxes) from a frame in
tests/fixtures/witcher3/ so a rule is never loosened from memory.
"""

from __future__ import annotations

import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.witcher3 import AREA_BANNER, QUEST_NOTICE, SUBTITLE, SUBTITLE_FIELD
from previously_on.ocr import OcrLine

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("witcher3")


def L(text, conf=0.95, **box):
    return OcrLine(text, conf, **box)


def test_new_quest_snaps_a_misread_name(profile):
    # quest_new_contract, t 2481.5: glued, and the last L read as I.
    lines = [
        L("NEWQUEST", 0.98, x0=0.113, y0=0.024, x1=0.250, y1=0.315),
        L("CONTRACT:DEVILBY THE WELI", 0.94, x0=0.125, y0=0.444, x1=0.689, y1=0.782),
    ]
    assert profile.classify(QUEST_NOTICE, lines, None)[0][:2] == (
        EventType.QUEST_STARTED,
        "Contract: Devil by the Well",
    )


def test_unknown_quest_is_kept_in_name_case(profile):
    lines = [
        L("QUESTCOMPLETED!", 0.95, x0=0.113, y0=0.024, x1=0.300, y1=0.315),
        L("THE BEAST OF WHITE ORCHARD", 0.95, x0=0.125, y0=0.444, x1=0.689, y1=0.782),
    ]
    assert profile.classify(QUEST_NOTICE, lines, None)[0][:2] == (
        EventType.QUEST_COMPLETED,
        "The Beast of White Orchard",
    )


def test_tutorial_titled_quest_updates_is_not_a_notice(profile):
    # neg_tutorial_quest_updates, t 2480: the tutorial's title "QUEST
    # UPDATES" scores 92 against the header but starts at x 0.145; in this
    # frame only its sentence and a quest name bleeding through were read.
    lines = [
        L("You just got a new quest.", 0.99, x0=0.068, y0=0.282, x1=0.294, y1=0.556),
        L("EWELL", 1.00, x0=0.566, y0=0.460, x1=0.691, y1=0.766),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []
    # The title itself, at its own position (x 0.145 of the frame).
    x0 = (0.145 - QUEST_NOTICE.x) / QUEST_NOTICE.w
    lines = [
        L("QUEST UPDATES", 0.96, x0=x0, y0=0.0, x1=x0 + 0.2, y1=0.2),
        L("TWISTED FIRESTARTER", 0.96, x0=x0, y0=0.444, x1=x0 + 0.5, y1=0.782),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_tutorial_objective_card_is_not_a_notice(profile):
    # neg_tutorial_objective, t 3357.
    lines = [
        L("ACTIVE OBJECTIVE", 0.96, x0=0.225, y0=0.032, x1=0.411, y1=0.250),
        L("If aquesthasmultipleobjectives,ress", 0.85, x0=0.100, y0=0.710, x1=0.453, y1=0.944),
        L("R3", 0.98, x0=0.472, y0=0.726, x1=0.500, y1=0.879),
        L("to", 0.98, x0=0.516, y0=0.742, x1=0.538, y1=0.919),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_new_marker_is_not_logged(profile):
    # neg_new_marker, t 1365: drawn at x 0.031, left of the header column.
    lines = [
        L("NEWMARKER", 0.97, x0=0.025, y0=0.032, x1=0.178, y1=0.306),
        L("RANSACKED VILLAGE", 0.98, x0=0.027, y0=0.427, x1=0.420, y1=0.806),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_crowns_are_not_an_item(profile):
    # neg_crowns, t 2794.
    lines = [
        L("NEWITEMRECEIVED", 1.00, x0=0.097, y0=0.169, x1=0.320, y1=0.411),
        L("CROWNS X 20", 0.98, x0=0.098, y0=0.460, x1=0.354, y1=0.831),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_diagram_is_an_item_with_its_colon_spaced(profile):
    # item_diagram, t 3021.
    lines = [
        L("NEWCRAFTINGDIAGRAM", 0.96, x0=0.096, y0=0.185, x1=0.371, y1=0.403),
        L("DIAGRAM:BLUNTCROSSBOWBOLT", 0.99, x0=0.102, y0=0.492, x1=0.747, y1=0.815),
    ]
    assert profile.classify(QUEST_NOTICE, lines, None)[0][:2] == (EventType.ITEM_ACQUIRED, "Diagram: Bluntcrossbowbolt")


def test_quest_journal_menu_is_not_a_notice(profile):
    # neg_menu_quests, t 3415: quest names in Title Case, no header.
    lines = [
        L("Missing inAction", 0.95, x0=0.160, y0=0.000, x1=0.309, y1=0.185),
        L("WhiteOrchard", 1.00, x0=0.162, y0=0.202, x1=0.276, y1=0.395),
        L("WITCHERCONTRACTS", 0.99, x0=0.080, y0=0.702, x1=0.266, y1=0.911),
        L("Find the cart.", 0.95, x0=0.703, y0=0.782, x1=0.819, y1=1.000),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_area_title_card_snaps_its_glued_read(profile):
    # area_temeria, t 1029.
    lines = [L("TEMERIA,ROADTOVIZIMA", 0.94, x0=0.481, y0=0.234, x1=0.928, y1=0.781)]
    assert profile.classify(AREA_BANNER, lines, None)[0][:2] == (EventType.AREA_DISCOVERED, "Temeria, Road to Vizima")


def test_some_time_later_is_not_an_area(profile):
    # neg_some_time_later, t 1380.
    lines = [L("SOME TIME LATER..", 0.96, x0=0.583, y0=0.188, x1=0.924, y1=0.828)]
    assert profile.classify(AREA_BANNER, lines, BLACK) == []


def test_field_line_keeps_its_speaker(profile):
    # dialogue_field_yennefer, t 398.
    lines = [L("Yennefer: Geralt, stop fingering my toiletries.", 0.99, x0=0.347, y0=0.250, x1=0.620, y1=0.828)]
    assert profile.classify(SUBTITLE_FIELD, lines, None)[0][:2] == (
        EventType.DIALOGUE,
        "Yennefer: Geralt, stop fingering my toiletries.",
    )


def test_gwent_card_description_is_not_dialogue(profile):
    # neg_gwent, t 2069.
    lines = [
        L("MoraleBoost", 0.99, x0=0.468, y0=0.000, x1=0.535, y1=0.196),
        L("Adds+1 to all units in the row(excluding itself).", 0.93, x0=0.406, y0=0.467, x1=0.595, y1=0.707),
    ]
    assert profile.classify(SUBTITLE, lines, BLACK) == []


def test_quick_slots_are_not_dialogue(profile):
    # neg_tutorial_adrenaline, t 1293: the consumable slots bottom-left.
    lines = [
        L("5Bread", 0.99, x0=0.045, y0=0.326, x1=0.082, y1=0.620),
        L("2Water", 0.99, x0=0.046, y0=0.728, x1=0.082, y1=0.978),
    ]
    assert profile.classify(SUBTITLE, lines, BLACK) == []


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


def _framed(text, conf, x0, y0, x1, y1):
    """A box given in frame fractions (as the survey reports it), in crop fractions."""
    r = QUEST_NOTICE
    return L(text, conf, x0=(x0 - r.x) / r.w, y0=(y0 - r.y) / r.h, x1=(x1 - r.x) / r.w, y1=(y1 - r.y) / r.h)


def test_notice_sliding_in_is_not_read(profile):
    # Survey of chunk 01 t 854: the header half on screen scores 91 against
    # "QUEST UPDATED", but it starts at x 0.095, right of the column.
    lines = [
        _framed("ESTUPDATED", 0.95, 0.095, 0.392, 0.178, 0.419),
        _framed("HEBEASTOFWHII", 0.93, 0.102, 0.436, 0.279, 0.474),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_floating_tag_on_the_header_row_is_ignored(profile):
    # quest_completed_cargo, chunk 01 t 35: "Merchant" floats at x 0.42 on
    # the header's row; joined, the header matched nothing.
    lines = [
        _framed("QUEST COMPLETED!", 0.97, 0.084, 0.391, 0.198, 0.418),
        _framed("Merchant", 0.97, 0.419, 0.401, 0.450, 0.414),
        _framed("PRECIOUS CARGO", 0.98, 0.086, 0.434, 0.256, 0.477),
    ]
    assert profile.classify(QUEST_NOTICE, lines, None)[0][:2] == (EventType.QUEST_COMPLETED, "Precious Cargo")


def test_level_up_is_not_a_notice(profile):
    # Survey of chunk 01 t 1050: "LEVEL: 2" sits in the header column.
    lines = [
        _framed("LEVEL: 2", 0.97, 0.080, 0.405, 0.158, 0.435),
        _framed("POINTSAVAILABLE:3", 0.97, 0.081, 0.441, 0.204, 0.471),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_a_dark_name_is_not_a_notice(profile):
    # neg_quest_dissolving, t 2604.25: the same boxes as a solid notice, but
    # nothing bright where the name is (98th-percentile V 127, gate 180).
    lines = [
        L("NEWQUEST", 0.98, x0=0.113, y0=0.024, x1=0.250, y1=0.315),
        L("CONTRACT:DEVILBY THE WELI", 0.94, x0=0.125, y0=0.444, x1=0.689, y1=0.782),
    ]
    assert profile.classify(QUEST_NOTICE, lines, BLACK) == []


def test_death_screen(profile):
    from previously_on.games.witcher3 import DEATH_BANNER

    # death_02: "You AreDead", h 0.037, centred.
    r = DEATH_BANNER
    line = L("You AreDead", 0.97, x0=(0.45 - r.x) / r.w, y0=(0.359 - r.y) / r.h, x1=(0.549 - r.x) / r.w, y1=(0.396 - r.y) / r.h)
    assert profile.classify(DEATH_BANNER, [line], BLACK)[0][:2] == (EventType.DEATH, "YOU ARE DEAD")


def test_a_bark_is_not_a_death(profile):
    from previously_on.games.witcher3 import DEATH_BANNER

    # A passer-by's "You're dead!" (t 2439) — scores 95 space-stripped — even
    # if it floated into the band at the screen's height.
    r = DEATH_BANNER
    line = L("You're dead!", 0.96, x0=(0.459 - r.x) / r.w, y0=(0.36 - r.y) / r.h, x1=(0.519 - r.x) / r.w, y1=(0.39 - r.y) / r.h)
    assert profile.classify(DEATH_BANNER, [line], BLACK) == []


def _sub(region, text, x0, x1, conf=0.95):
    """One subtitle row given in frame x, centred vertically in the crop."""
    return L(text, conf, x0=(x0 - region.x) / region.w, y0=0.3, x1=(x1 - region.x) / region.w, y1=0.7)


@pytest.mark.parametrize(
    "text",
    [
        "PLAYER'SCURRENTPOSITION The witcher's current location.",  # chunk 00 t 3412
        "UNDISCOVEREDLOCATION Location orartifact that hasnot yet been discovered.",  # chunk 01 t 2194
        "BLOWBALL Used in alchemy.",  # chunk 01 t 577
        "CONTRACT:DEVILBYTHEWELL Ask Odolan about the contract.",  # chunk 01 t 1330
        "BitingFrost Sets the strength of all CloseCombat cards to1forboth players.",  # chunk 00 t 2076
        "KTake TakeAll Compare Close,",  # chunk 01 t 2106
    ],
)
def test_ui_text_in_the_cutscene_band_is_not_dialogue(profile, text):
    assert profile.classify(SUBTITLE, [_sub(SUBTITLE, text, 0.35, 0.65)], BLACK) == []


@pytest.mark.parametrize(
    "text",
    [
        "To begin, you draw 10 cards . This will be your hand for the rest of the match.",  # chunk 00 t 2066
        "Influences opponents' minds.",  # chunk 01 t 2164
        "Only three out of ten boys survive the Trial of the Grasses and become witchers. The rest die in agony.",
    ],
)
def test_field_band_text_without_a_speaker_is_not_dialogue(profile, text):
    assert profile.classify(SUBTITLE_FIELD, [_sub(SUBTITLE_FIELD, text, 0.25, 0.75)], BLACK) == []


@pytest.mark.parametrize(
    "text",
    [
        "Geralt:No.Really upset him,too...His theory collapsed.",  # chunk 00 t 1348
        "Geralt. Hm... Strange.",  # chunk 01 t 2241, the colon read as a full stop
        "Emhyr's Chamberlain: I see the gentleman is in the mood for jests.",
        "Dune: No. Neighbors' son.",  # chunk 02 t 254
    ],
)
def test_field_lines_with_a_speaker_are_dialogue(profile, text):
    assert profile.classify(SUBTITLE_FIELD, [_sub(SUBTITLE_FIELD, text, 0.30, 0.70)], BLACK)[0][0] is EventType.DIALOGUE
