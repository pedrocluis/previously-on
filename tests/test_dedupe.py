from datetime import datetime

from previously_on.dedupe import Deduper, Verdict
from previously_on.events import Event, EventType


def ev(t, typ=EventType.DEATH, text="YOU DIED"):
    return Event(ts=datetime.now(), t_rel=t, type=typ, text=text, conf=0.9, region="r")


def test_suppresses_repeat_within_cooldown():
    d = Deduper({EventType.DEATH: 8.0})
    assert d.accept(ev(0.0))
    assert not d.accept(ev(3.0))
    assert d.accept(ev(9.0))


def test_different_text_is_not_a_duplicate():
    d = Deduper({EventType.DIALOGUE: 15.0})
    assert d.accept(ev(0.0, EventType.DIALOGUE, "Hello there."))
    assert d.accept(ev(1.0, EventType.DIALOGUE, "General Kenobi."))
    assert not d.accept(ev(2.0, EventType.DIALOGUE, "hello  there"))  # normalised match


def test_default_cooldown_for_unlisted_type():
    d = Deduper({})
    assert d.accept(ev(0.0))
    assert not d.accept(ev(1.0))


def test_near_identical_ocr_readings_are_one_event():
    d = Deduper({EventType.AREA_DISCOVERED: 30.0})
    assert d.accept(ev(0.0, EventType.AREA_DISCOVERED, "Specimen Storehouse"))
    assert not d.accept(ev(2.0, EventType.AREA_DISCOVERED, "Specimen Stbrehouse"))
    assert d.accept(ev(2.0, EventType.AREA_DISCOVERED, "Shadow Keep"))


def test_items_differing_by_number_are_distinct():
    d = Deduper({EventType.ITEM_ACQUIRED: 8.0})
    assert d.accept(ev(0.0, EventType.ITEM_ACQUIRED, "Smithing Stone [7]"))
    assert d.accept(ev(0.0, EventType.ITEM_ACQUIRED, "Smithing Stone [8]"))
    assert not d.accept(ev(1.0, EventType.ITEM_ACQUIRED, "Smithing Stone 7"))


def test_by_type_ignores_text_within_cooldown():
    d = Deduper({EventType.BOSS_DEFEATED: 30.0}, by_type={EventType.BOSS_DEFEATED})
    assert d.accept(ev(0.0, EventType.BOSS_DEFEATED, "DEMIGOD FELLED"))
    assert not d.accept(ev(8.0, EventType.BOSS_DEFEATED, "Godrick's Great Rune"))  # the drop that proves the same kill
    assert d.accept(ev(31.0, EventType.BOSS_DEFEATED, "GREAT ENEMY FELLED"))


def test_neighbouring_areas_sharing_a_prefix_are_distinct():
    # Dark Souls, chunk 00: Darkroot Garden at 3471 s, Darkroot Basin at
    # 3499 s (ratio 76); a mid-fade misread of one banner still folds (84).
    d = Deduper({EventType.AREA_DISCOVERED: 600.0})
    assert d.accept(ev(0.0, EventType.AREA_DISCOVERED, "Darkroot Garden"))
    assert d.accept(ev(28.0, EventType.AREA_DISCOVERED, "Darkroot Basin"))
    assert not d.accept(ev(29.0, EventType.AREA_DISCOVERED, "Darkroot Basim"))
    assert d.accept(ev(0.0, EventType.AREA_DISCOVERED, "Chapel of Anticipation"))
    assert not d.accept(ev(1.0, EventType.AREA_DISCOVERED, "NChapelof Anticlpauon"))


def test_sibling_boss_names_are_distinct():
    # Dark Souls II, chunk 02 t 802: the Ruin Sentinels draw three bars.
    # Two are read from one frame, the third a frame later; "Ruin Sentinel
    # Yahim" scores exactly 80 against "Ruin Sentinel Alessia" and was
    # folded away at that threshold.
    d = Deduper({EventType.BOSS_ENGAGED: 120.0})
    assert d.accept(ev(802.0, EventType.BOSS_ENGAGED, "Ruin Sentinel Ricce"))
    assert d.accept(ev(802.0, EventType.BOSS_ENGAGED, "Ruin Sentinel Alessia"))
    assert d.accept(ev(803.5, EventType.BOSS_ENGAGED, "Ruin Sentinel Yahim"))
    # A re-read of one of them inside the cooldown is still a duplicate.
    assert not d.accept(ev(805.0, EventType.BOSS_ENGAGED, "Ruin Sentimel Ricce"))


def test_stacked_pickups_in_one_frame_are_distinct():
    # Dark Souls, chunk 03 t 33: two gargoyle drops in one panel scored 80
    # and the second was folded into the first. Same frame, different text:
    # two rows. The next frame's re-read of either is still a duplicate.
    d = Deduper({EventType.ITEM_ACQUIRED: 8.0})
    assert d.accept(ev(33.0, EventType.ITEM_ACQUIRED, "Gargoyle's Shield"))
    assert d.accept(ev(33.0, EventType.ITEM_ACQUIRED, "Gargoyle Helm"))
    assert not d.accept(ev(33.5, EventType.ITEM_ACQUIRED, "Gargoyle Helm"))
    assert not d.accept(ev(33.5, EventType.ITEM_ACQUIRED, "Gargoyle's Shleld"))
    assert not d.accept(ev(33.0, EventType.ITEM_ACQUIRED, "Gargoyle's Shield"))  # the same row twice


def test_a_better_spaced_read_upgrades_the_kept_one():
    # Elden Ring hour 0, t 214-218: the glued read came first and the clean
    # one, a few seconds later, was dropped.
    d = Deduper({EventType.DIALOGUE: 15.0})
    first = ev(214.0, EventType.DIALOGUE, "A warleading to abandonmentby the GreaterWill.")
    assert d.offer(first) == (Verdict.NEW, None)
    clean = ev(218.5, EventType.DIALOGUE, "A war leading to abandonment by the Greater Will.")
    assert d.offer(clean) == (Verdict.UPGRADE, first)
    # Once upgraded, the glued read is no longer better than what is kept.
    assert d.offer(ev(219.0, EventType.DIALOGUE, "A warleading to abandonmentby the GreaterWill.")) == (Verdict.DUPLICATE, None)


def test_confidence_upgrades_only_on_a_clear_gap():
    d = Deduper({EventType.AREA_DISCOVERED: 30.0})
    garbled = ev(0.0, EventType.AREA_DISCOVERED, "NChapelof Anticlpauon")
    garbled.conf = 0.90
    assert d.accept(garbled)
    close = ev(1.0, EventType.AREA_DISCOVERED, "Chapel of Anticlpation")
    close.conf = 0.93  # within OCR's jitter between two clean reads
    assert d.offer(close) == (Verdict.DUPLICATE, None)
    clean = ev(1.5, EventType.AREA_DISCOVERED, "Chapel of Anticipation")
    clean.conf = 0.98
    assert d.offer(clean) == (Verdict.UPGRADE, garbled)


def test_a_confident_but_truncated_read_is_not_an_upgrade():
    d = Deduper({EventType.DIALOGUE: 15.0})
    full = ev(0.0, EventType.DIALOGUE, "Soon, Marika's offspring, demigods all, claimed the shards.")
    full.conf = 0.85
    assert d.accept(full)
    cut = ev(1.0, EventType.DIALOGUE, "Soon, Marika's offspring, demigods all, claimed the")
    cut.conf = 0.99
    assert d.offer(cut)[0] is Verdict.DUPLICATE


def test_by_type_events_are_never_upgraded():
    d = Deduper({EventType.BOSS_DEFEATED: 30.0}, by_type={EventType.BOSS_DEFEATED})
    assert d.accept(ev(0.0, EventType.BOSS_DEFEATED, "GREAT ENEMY FELLEO"))
    assert d.offer(ev(1.0, EventType.BOSS_DEFEATED, "GREAT ENEMY FELLED")) == (Verdict.DUPLICATE, None)
