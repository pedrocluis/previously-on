import pytest

from previously_on.events import EventType
from previously_on.games.eldenring import BANNER_VOCAB, BOSS_BAR, CENTER_BANNER, ITEM_POPUP, SUBTITLE
from previously_on.ocr import OcrLine


def L(text, conf=0.95):
    return [OcrLine(text, conf)]


@pytest.fixture
def classify(eldenring):
    """Single-event view of profile.classify: the tuple, or None."""

    def _one(region, lines):
        hits = eldenring.classify(region, lines)
        assert len(hits) <= 1, hits
        return hits[0] if hits else None

    return _one


@pytest.mark.parametrize(
    "text,expected",
    [
        ("YOU DIED", EventType.DEATH),
        ("Y0U DIED", EventType.DEATH),
        ("YOU  DIED.", EventType.DEATH),
        ("ENEMY FELLED", EventType.ENEMY_DEFEATED),
        ("ENEMY FELLEO", EventType.ENEMY_DEFEATED),
        ("GREAT ENEMY FELLED", EventType.BOSS_DEFEATED),
        ("GREAT ENEMY FELLEO", EventType.BOSS_DEFEATED),
        ("GREAT ENEMY FELLED", EventType.BOSS_DEFEATED),
        ("LOST GRACE DISCOVERED", EventType.CHECKPOINT_DISCOVERED),
        ("L0ST GRACE DISC0VERED", EventType.CHECKPOINT_DISCOVERED),
        ("LLOSTGRACEDISCOVERED", EventType.CHECKPOINT_DISCOVERED),  # real OCR output: no spaces, flourish read as L
        ("YOUDIED", EventType.DEATH),
        ("GREATENEMYFELLED", EventType.BOSS_DEFEATED),
        ("DEMIGODFELLED", EventType.BOSS_DEFEATED),  # real OCR output at the Messmer kill
        ("Idemigodfelled", EventType.BOSS_DEFEATED),
        ("LEGEND FELLED", EventType.BOSS_DEFEATED),
        ("GOD SLAIN", EventType.BOSS_DEFEATED),
    ],
)
def test_banner_vocab(classify, text, expected):
    hit = classify(CENTER_BANNER, L(text))
    assert hit is not None
    typ, canonical, conf = hit
    assert typ is expected
    assert canonical.isupper() and canonical in BANNER_VOCAB  # stored as the phrase that matched, not the OCR output
    assert conf > 0.8


def test_great_enemy_not_swallowed_by_enemy(classify):
    typ, _, _ = classify(CENTER_BANNER, L("GREAT ENEMY FELLED"))
    assert typ is EventType.BOSS_DEFEATED


def test_banner_split_across_lines(classify):
    hit = classify(CENTER_BANNER, [OcrLine("LOST GRACE", 0.9), OcrLine("DISCOVERED", 0.9)])
    assert hit and hit[0] is EventType.CHECKPOINT_DISCOVERED


@pytest.mark.parametrize(
    "text,stored",
    [
        ("LIMGRAVE", "Limgrave"),
        ("STORMVEIL CASTLE", "Stormveil Castle"),
        ("Specimen Storehouse", "Specimen Storehouse"),  # real OCR output: the banner font reads as Title Case
        ("Liurnia of the Lakes", "Liurnia of the Lakes"),
        ("Specimen S Storehouse", "Specimen Storehouse"),  # ornament read as a stray letter
        ("Specimen & Storehouse", "Specimen Storehouse"),
    ],
)
def test_area_discovered(classify, text, stored):
    hit = classify(CENTER_BANNER, L(text))
    assert hit is not None
    typ, name, _ = hit
    assert typ is EventType.AREA_DISCOVERED
    assert name == stored


def test_menu_in_banner_band_is_not_a_banner(classify):
    # Equipment screen: a stat label with a slightly inflated box among many small lines.
    lines = [
        OcrLine("Lightning", 0.98, x0=0.35, y0=0.05, x1=0.44, y1=0.42),
        OcrLine("0", 0.99, x0=0.49, y0=0.15, x1=0.51, y1=0.27),
        OcrLine("Lightning", 0.99, x0=0.6, y0=0.1, x1=0.68, y1=0.33),
        OcrLine("20.0", 1.0, x0=0.78, y0=0.12, x1=0.82, y1=0.3),
    ]
    assert classify(CENTER_BANNER, lines) is None
    # Same label alone but off-centre is still not a banner.
    assert classify(CENTER_BANNER, lines[:1]) is None


def test_low_confidence_garbage_does_not_break_a_banner(classify):
    # Real frame: a fire-effect box read as "三" (0.54) shared the row with YOU DIED.
    lines = [
        OcrLine("三", 0.54, x0=0.04, y0=0.15, x1=0.22, y1=0.75),
        OcrLine("YOU DIED", 0.96, x0=0.33, y0=0.2, x1=0.67, y1=0.7),
    ]
    assert classify(CENTER_BANNER, lines)[0] is EventType.DEATH


def test_small_text_in_banner_band_is_not_a_banner(classify):
    # Map-screen location labels pass through the same band but are ~0.025 of the frame tall.
    small = [OcrLine("Storehouse, First Floor", 0.99, x0=0.5, y0=0.4, x1=0.6, y1=0.55)]
    assert classify(CENTER_BANNER, small) is None
    tall = [OcrLine("YOUDIED", 0.99, x0=0.35, y0=0.2, x1=0.65, y1=0.8)]
    assert classify(CENTER_BANNER, tall)[0] is EventType.DEATH


@pytest.mark.parametrize(
    "text,conf",
    [
        ("Press any button", 0.95),  # mixed case → menu text
        ("HOST OF FINGERS VANQUISHED", 0.95),  # stoplist
        ("LIMGRAVE", 0.5),  # low OCR confidence
        ("A", 0.95),  # too short
        ("SOME VERY LONG ALL CAPS TOOLTIP TEXT HERE", 0.95),  # too many words
        ("Dueling Shield x1", 0.95),  # digits: an item popup, not a place
        ("Jdied", 0.92),  # a mangled YOU DIED must not become a place
        ("NEW", 0.99),  # the "NEW item" tag
        ("", 0.95),
    ],
)
def test_center_banner_rejections(classify, text, conf):
    assert classify(CENTER_BANNER, L(text, conf)) is None


def test_empty_lines(classify):
    assert classify(CENTER_BANNER, []) is None


def test_demigod_felled_keeps_its_own_phrase(classify):
    assert classify(CENTER_BANNER, L("DEMIGODFELLED"))[1] == "DEMIGOD FELLED"


def test_dialogue_requires_sentence_punctuation(classify):
    assert classify(SUBTITLE, L("MeHearth Scott yStickMan SeanRoach", 0.95)) is None
    assert classify(SUBTITLE, L("As if using Lord Mohg to gain entrance were not enough,", 0.95)) is not None


def test_dialogue(classify):
    hit = classify(SUBTITLE, L("Leda asked me to find Ansbach.", 0.7))
    assert hit and hit[0] is EventType.DIALOGUE
    assert hit[1] == "Leda asked me to find Ansbach."


def test_dialogue_rejects_short_and_low_conf(classify):
    assert classify(SUBTITLE, L("Hm.", 0.9)) is None
    assert classify(SUBTITLE, L("Leda asked me to find Ansbach.", 0.3)) is None


def test_dialogue_rejects_banner_overlap(classify):
    assert classify(SUBTITLE, L("LOST GRACE DISCOVERED", 0.9)) is None


@pytest.mark.parametrize("prompt", ["Rest at site of grace", "Pick up item", "Retrieve lost runes", "A) :OK B :Close", ":OK:Close"])
def test_dialogue_rejects_interaction_prompts(classify, prompt):
    assert classify(SUBTITLE, L(prompt, 0.97)) is None


def test_dialogue_accepts_real_line(classify):
    hit = classify(SUBTITLE, L("What could they possibly have in mind for Lord Mohg's remains?", 0.98))
    assert hit and hit[0] is EventType.DIALOGUE


def test_boss_bar(classify):
    hit = classify(BOSS_BAR, L("Margit, the Fell Omen", 0.9))
    assert hit and hit[0] is EventType.BOSS_ENGAGED and hit[1] == "Margit, the Fell Omen"
    # Six words; a live session lost the whole Rennala fight to a 5-word cap.
    hit = classify(BOSS_BAR, L("Rennala, Queen of the Full Moon", 0.95))
    assert hit and hit[1] == "Rennala, Queen of the Full Moon"
    assert classify(BOSS_BAR, L("1234", 0.9)) is None
    assert classify(BOSS_BAR, L("Margit", 0.5)) is None


def I(text, conf=0.95, y0=0.7, y1=0.9):
    """An item-box line laid out like the real popup: right-aligned at ~0.7 of the crop."""
    return OcrLine(text, conf, x0=0.7 - 0.022 * len(text), y0=y0, x1=0.7, y1=y1)


def test_item_popup(classify):
    hit = classify(ITEM_POPUP, [I("Golden Rune [1]", 0.85), OcrLine("OK", 0.99)])
    assert hit and hit[0] is EventType.ITEM_ACQUIRED and hit[1] == "Golden Rune [1]"
    assert classify(ITEM_POPUP, L("OK", 0.99)) is None


def test_item_popup_strips_count(classify):
    # Real OCR output: name and count as separate lines, or glued together.
    hit = classify(ITEM_POPUP, [I("Beast Horn", 0.98), OcrLine("x4", 0.8, x0=0.78, x1=0.82, y0=0.7, y1=0.9)])
    assert hit and hit[1] == "Beast Horn"
    hit = classify(ITEM_POPUP, [I("Lump of Flesh x2", 0.96)])
    assert hit and hit[1] == "Lump of Flesh"
    assert classify(ITEM_POPUP, [OcrLine("x4", 0.9)]) is None


def test_boss_bar_rejects_sentences(classify):
    # A tutorial popup line straying into the strip.
    assert classify(BOSS_BAR, L("This causes a large amount of damage.", 0.98)) is None
    assert classify(BOSS_BAR, L("takes for the blood", 0.9)) is None


def test_boss_bar_ignores_hp_number(classify):
    hit = classify(BOSS_BAR, [OcrLine("Base Serpent Messmer", 0.95, x0=0.04), OcrLine("548", 1.0, x0=0.9)])
    assert hit and hit[1] == "Base Serpent Messmer"


def test_boss_bar_rejects_menu_tooltips(classify):
    # Item tooltips from the equipment menu land in the strip but start at x~0.34 of the crop.
    assert classify(BOSS_BAR, [OcrLine("Passive Effects", 0.99, x0=0.34)]) is None


def test_item_popup_rejoins_split_name(classify):
    # Real OCR output on the item box: the detector split one row into two boxes.
    lines = [
        OcrLine("Furlcalling", 0.99, x0=0.32, y0=0.3, x1=0.52, y1=0.6),
        OcrLine("Finger Remedy", 0.98, x0=0.53, y0=0.3, x1=0.72, y1=0.6),
        OcrLine("x1", 0.9, x0=0.78, y0=0.32, x1=0.82, y1=0.58),
    ]
    hit = classify(ITEM_POPUP, lines)
    assert hit and hit[1] == "Furlcalling Finger Remedy"


def test_boss_bar_rejoins_split_name(classify):
    lines = [
        OcrLine("Base Serpent", 0.95, x0=0.04, y0=0.3, x1=0.2, y1=0.6),
        OcrLine("Messmer", 0.97, x0=0.21, y0=0.3, x1=0.3, y1=0.6),
        OcrLine("548", 1.0, x0=0.95, y0=0.3, x1=0.99, y1=0.6),
    ]
    hit = classify(BOSS_BAR, lines)
    assert hit and hit[1] == "Base Serpent Messmer"


def test_item_popup_stacked_rows(eldenring):
    # Two pickups at once: rows 0.06 of the frame apart, both right-aligned to the count column.
    lines = [
        OcrLine("Smithing Stone [7]", 0.94, x0=0.43, y0=0.13, x1=0.70, y1=0.30),
        OcrLine("x1", 0.9, x0=0.78, y0=0.15, x1=0.81, y1=0.28),
        OcrLine("Smithing Stone [8]", 0.97, x0=0.43, y0=0.45, x1=0.70, y1=0.61),
        OcrLine("x1", 0.9, x0=0.78, y0=0.47, x1=0.81, y1=0.60),
    ]
    got = [text for _, text, _ in eldenring.classify(ITEM_POPUP, lines)]
    assert got == ["Smithing Stone [7]", "Smithing Stone [8]"]


def test_item_popup_rejects_menu_labels(classify):
    # Status-screen rows land in the taller item box but are left-aligned and end early.
    assert classify(ITEM_POPUP, [OcrLine("Discovery", 0.99, x0=0.33, x1=0.48, y0=0.2, y1=0.35)]) is None
    assert classify(ITEM_POPUP, [OcrLine("Memory Slots", 0.99, x0=0.33, x1=0.54, y0=0.4, y1=0.55)]) is None


def test_flourish_next_to_banner_is_ignored(classify):
    # The ornament beside an area name OCRs as a tiny "Sp" box on the same row.
    lines = [
        OcrLine("Sp", 0.9, x0=0.17, y0=0.3, x1=0.20, y1=0.7),
        OcrLine("Specimen Storehouse", 0.99, x0=0.22, y0=0.25, x1=0.78, y1=0.75),
    ]
    hit = classify(CENTER_BANNER, lines)
    assert hit and hit[1] == "Specimen Storehouse"


def test_cjk_garbage_is_not_an_event(classify):
    assert classify(ITEM_POPUP, [I("人", 0.86)]) is None
    assert classify(BOSS_BAR, [OcrLine("福", 0.9, x0=0.04)]) is None
    assert classify(CENTER_BANNER, L("金", 0.95)) is None


def test_boss_name_requires_hp_bar(eldenring):
    import numpy as np

    from previously_on.games.eldenring import BOSS_HP_BAR

    lines = [OcrLine("Messmer the Impaler", 0.99, x0=0.04, y0=0.2, x1=0.4, y1=0.8)]
    dark = np.zeros((1080, 1920, 3), np.uint8)
    assert eldenring.classify(BOSS_BAR, lines, dark) == []
    with_bar = dark.copy()
    x0, y0, x1, y1 = BOSS_HP_BAR.pixel_box(1920, 1080)
    with_bar[(y0 + y1) // 2, x0:x1] = (160, 160, 160)  # the bar's light border line
    assert eldenring.classify(BOSS_BAR, lines, with_bar)[0][1] == "Messmer the Impaler"


def test_startup_logos_are_not_areas(classify):
    # Real live-capture output on Windows: the publisher splash screens.
    assert classify(CENTER_BANNER, L("BANDAI NAMCO", 0.95)) is None
    assert classify(CENTER_BANNER, L("BANDAINAMCO", 0.995)) is None  # the splash font loses its space too
    assert classify(CENTER_BANNER, L("FROM SOFTWARE", 0.87)) is None


def test_map_found_banner_is_not_an_area(classify):
    assert classify(CENTER_BANNER, L("MAPFOUND", 1.0)) is None


@pytest.mark.parametrize(
    "read",
    ["BLOODYFINGERVANQUISHEI", "LOODYFINGERVANQUISHEI", "RECUSANT VANQUISHED", "HOST VANOUISHED", "HOSTVANQUISHED", "SLOODYFINGERVANOUISHEI"],
)
def test_invasion_outcome_banners_are_not_areas(classify, read):
    # Real reads: the NPC invader Nerijus going down, and a Volcano Manor invasion target.
    assert classify(CENTER_BANNER, L(read, 0.96)) is None


def test_summonwater_is_not_mistaken_for_a_summon_banner(classify):
    assert classify(CENTER_BANNER, L("Summonwater Village", 0.96))[1] == "Summonwater Village"


def test_boss_name_with_a_bracketed_suffix(eldenring):
    # Real read: the Consecrated Snowfield pair are "Night's Cavalry (Flail)" and "(Glaive)".
    lines = [OcrLine("Night's Cavalry (Glaive)", 0.97, x0=0.05, y0=0.3, x1=0.4, y1=0.8)]
    assert eldenring.classify(BOSS_BAR, lines)[0][1] == "Night's Cavalry (Glaive)"


def test_boss_hp_number_does_not_join_an_item_name(eldenring):
    # Real read mid-fight: the boss's HP number sits inside the item box and shared a row with the pickup.
    lines = [OcrLine("451", 1.0, x0=0.3, y0=0.72, x1=0.36, y1=0.8), I("FadedErdleafFlower", 0.99, y0=0.72, y1=0.8)]
    assert [e[1] for e in eldenring.classify(ITEM_POPUP, lines)] == ["Faded Erdleaf Flower"]


def test_great_rune_restored_is_not_an_area(classify):
    assert classify(CENTER_BANNER, L("GREATRUNERESTORED", 0.99)) is None


def test_great_rune_pickup_proves_the_shardbearer_died(eldenring):
    # Real read: "DEMIGOD FELLED" sat behind the Great Runes tutorial popup, only the drops were readable.
    events = eldenring.classify(
        ITEM_POPUP, [I("Godrick'sGreatRune", 0.98, y0=0.6, y1=0.7), I("Remembranceofthe Grafted", 0.97, y0=0.75, y1=0.85)]
    )
    assert events == [
        (EventType.ITEM_ACQUIRED, "Godrick's Great Rune", 0.98),
        (EventType.ITEM_ACQUIRED, "Remembrance of the Grafted", 0.97),
        (EventType.BOSS_DEFEATED, "Godrick's Great Rune", 0.98),
    ]
    rennala = [I("Great Rune of the Unborn", 0.98, y0=0.6, y1=0.7), I("Remembrance of the Full Moon Queen", 0.97, y0=0.75, y1=0.85)]
    assert eldenring.classify(ITEM_POPUP, rennala)[-1][0] is EventType.BOSS_DEFEATED
    # Neither alone: the Divine Tower shows the rune again on restoring it (real read, 8 min after
    # the kill), a mausoleum duplicates Remembrances, and Golden Runes are not Great Runes.
    for only in ("Godrick's Great Rune", "Remembrance of the Grafted", "Golden Rune [2]"):
        assert [e[0] for e in eldenring.classify(ITEM_POPUP, [I(only, 0.96)])] == [EventType.ITEM_ACQUIRED]


def test_achievement_toast_is_not_an_item(eldenring):
    # Real live-capture output: a Steam achievement toast in the lower right.
    lines = [
        OcrLine("ACHIEVEMENTS", 0.98, x0=0.33, y0=0.1, x1=0.55, y1=0.2),
        OcrLine("You'veunlockedallachievements!42/42（100%)", 0.9, x0=0.33, y0=0.3, x1=0.78, y1=0.4),
        I("Obtainedallachievements", 0.99, y0=0.6, y1=0.7),
    ]
    assert eldenring.classify(ITEM_POPUP, lines) == []


def test_steam_library_page_is_not_an_item(eldenring):
    # Real live-capture output: the game had quit and the Steam library page
    # sat under the item box until the process watcher stopped the session.
    lines = [
        OcrLine("FRIENDSWHO PLAY", 0.97, x0=0.33, y0=0.1, x1=0.55, y1=0.2),
        I("6 friends have played previously", 0.97, y0=0.4, y1=0.5),
        OcrLine("View all friends who play", 0.96, x0=0.33, y0=0.7, x1=0.6, y1=0.8),
    ]
    assert eldenring.classify(ITEM_POPUP, lines) == []


@pytest.mark.parametrize(
    "read,stored",
    [
        ("Stormveit Castle", "Stormveil Castle"),  # real live OCR slip
        ("Specimen Storehouse", "Specimen Storehouse"),
        ("Some Unknown Cave", "Some Unknown Cave"),  # not in the list: kept as read
        ("NChapelof Anticlpauon", "Chapel of Anticipation"),  # mid fade-in read: ornament glued on, space lost
        ("Chapel ofAnticipation", "Chapel of Anticipation"),  # only the space lost
        ("Ainsel River", "Ainsel River"),  # must not snap to "Ainsel River Main"
        ("Elphael,Brace of the Haligtree", "Elphael, Brace of the Haligtree"),  # five words
    ],
)
def test_area_names_snap_to_known_names(classify, read, stored):
    assert classify(CENTER_BANNER, L(read))[1] == stored


@pytest.mark.parametrize(
    "read,stored",
    [
        ("BallistaBolt", "Ballista Bolt"),
        ("RemembranceoftheGrafted", "Remembrance of the Grafted"),
        ("Godrick's GreatRune", "Godrick's Great Rune"),
        ("Golden Rune [2]", "Golden Rune [2]"),
        ("Flask of Crimson Tears +12", "Flask of Crimson Tears +12"),
        ("Flaskof Crimson Tears", "Flask of Crimson Tears"),
        ("Map:Limgrave,West", "Map: Limgrave, West"),
        ("AshofWar:RepeatingThrust", "Ash of War: Repeating Thrust"),
        ("Hand Axe", "Hand Axe"),  # a word merely ending in "and" is left alone
        ("Highland Axe", "Highland Axe"),
        ("Holyproof Pickled Liver", "Holyproof Pickled Liver"),
        ("Remembranceofthe Grafted", "Remembrance of the Grafted"),
        ("Remembrance ofthe Grafted", "Remembrance of the Grafted"),
        ("Letterfrom Volcano Manor", "Letter from Volcano Manor"),
        ("Blessingof the Erdtree", "Blessing of the Erdtree"),
        ("LightningproofDried Liver", "Lightningproof Dried Liver"),
    ],
)
def test_item_names_get_their_spaces_back(eldenring, read, stored):
    assert eldenring.classify(ITEM_POPUP, [I(read, 0.97)])[0][1] == stored


def test_letterless_box_is_dropped_from_dialogue(classify):
    lines = [OcrLine("1%", 0.8, x0=0.1, y0=0.1, x1=0.15, y1=0.5), OcrLine("Welcome, honoured guest.", 0.99, x0=0.3, y0=0.4, x1=0.7, y1=0.9)]
    assert classify(SUBTITLE, lines)[1] == "Welcome, honoured guest."


def test_weak_garbage_box_is_dropped_from_dialogue(classify):
    lines = [OcrLine("AAVUA", 0.68, x0=0.1, y0=0.1, x1=0.2, y1=0.5), OcrLine("Ahh, truest of dragons.", 0.99, x0=0.3, y0=0.4, x1=0.7, y1=0.9)]
    assert classify(SUBTITLE, lines)[1] == "Ahh, truest of dragons."


def test_count_column_is_ignored_whatever_it_reads(eldenring):
    # At lower OCR resolution the count reads "X" or "XI"; it still must not join the name.
    lines = [
        OcrLine("Dueling Shield", 1.0, x0=0.41, y0=0.7, x1=0.70, y1=0.9),
        OcrLine("X", 0.86, x0=0.77, y0=0.7, x1=0.80, y1=0.9),
    ]
    assert [t for _, t, _ in eldenring.classify(ITEM_POPUP, lines)] == ["Dueling Shield"]
