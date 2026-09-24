from datetime import datetime

from previously_on.events import Event, EventType
from previously_on.stats import compute, format_duration, summary_line


def ev(t, typ, text=""):
    return Event(ts=datetime.now(), t_rel=t, type=typ, text=text, conf=0.9, region="r")


def test_attempts_attributed_to_engaged_boss():
    events = [
        ev(10, EventType.BOSS_ENGAGED, "Margit, the Fell Omen"),
        ev(60, EventType.DEATH),
        ev(120, EventType.DEATH),
        ev(200, EventType.BOSS_ENGAGED, "Margit, the Fell Omen"),
        ev(260, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert s.deaths == 2
    assert [(b.name, b.attempts, b.defeated) for b in s.bosses] == [("Margit, the Fell Omen", 3, True)]
    assert s.current_boss is None
    assert "Margit, the Fell Omen felled in 3 tries" in summary_line(s)


def test_boss_still_standing():
    events = [ev(10, EventType.BOSS_ENGAGED, "Bayle"), ev(60, EventType.DEATH), ev(300, EventType.DEATH)]
    s = compute(events, duration=3 * 3600 + 12 * 60)
    assert s.current_boss is not None and s.current_boss.attempts == 2
    assert summary_line(s) == "3h 12m · 2 deaths · Bayle still standing"


def test_defeat_without_boss_bar_is_unknown_boss():
    s = compute([ev(1, EventType.DEATH), ev(2, EventType.BOSS_DEFEATED)])
    assert s.bosses[0].name == "unknown boss" and s.bosses[0].attempts == 1


def test_deaths_before_the_boss_do_not_count_as_attempts():
    events = [
        ev(1, EventType.DEATH),  # overworld
        ev(2, EventType.DEATH),
        ev(10, EventType.BOSS_ENGAGED, "Messmer the Impaler"),
        ev(20, EventType.DEATH),
        ev(30, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert s.deaths == 3
    assert s.bosses[0].attempts == 2


def test_area_ocr_variants_are_one_area():
    events = [
        ev(1, EventType.AREA_DISCOVERED, "Specimen Storehouse"),
        ev(2, EventType.AREA_DISCOVERED, "Specimdrhorehouse"),
        ev(3, EventType.AREA_DISCOVERED, "Scadu Altus"),
    ]
    assert compute(events).areas == ["Specimen Storehouse", "Scadu Altus"]


def test_counter_resets_between_bosses():
    events = [
        ev(1, EventType.BOSS_ENGAGED, "A"),
        ev(2, EventType.DEATH),
        ev(3, EventType.BOSS_DEFEATED),
        ev(4, EventType.BOSS_ENGAGED, "B"),
        ev(5, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert [(b.name, b.attempts) for b in s.bosses] == [("A", 2), ("B", 1)]


def test_other_counters():
    events = [
        ev(1, EventType.CHECKPOINT_DISCOVERED),
        ev(2, EventType.AREA_DISCOVERED, "Limgrave"),
        ev(3, EventType.AREA_DISCOVERED, "Limgrave"),
        ev(4, EventType.ITEM_ACQUIRED, "Golden Rune"),
        ev(5, EventType.DIALOGUE, "Hello."),
    ]
    s = compute(events)
    assert (s.checkpoints, s.areas, s.items, s.dialogue_lines) == (1, ["Limgrave"], 1, 1)


def test_format_duration():
    assert format_duration(59) == "0m"
    assert format_duration(3600 + 5 * 60) == "1h 05m"
    assert summary_line(compute([])) == "0m · 0 deaths"


def test_multi_phase_boss_and_ocr_variants_are_one_fight():
    events = [
        ev(1, EventType.BOSS_ENGAGED, "Messmer the Impaler"),
        ev(2, EventType.DEATH),
        ev(3, EventType.BOSS_ENGAGED, "Messmer the Impaler T"),  # OCR junk
        ev(4, EventType.DEATH),
        ev(5, EventType.BOSS_ENGAGED, "Base Serpent Messmer"),  # phase 2
        ev(6, EventType.DEATH),
        ev(7, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert [(b.name, b.attempts, b.phases) for b in s.bosses] == [("Messmer the Impaler", 4, ["Base Serpent Messmer"])]


def test_enemy_felled_ends_a_field_boss_fight():
    # Field bosses and evergaol bosses end in "ENEMY FELLED", not "GREAT ENEMY FELLED".
    events = [
        ev(1, EventType.BOSS_ENGAGED, "Tree Sentinel"),
        ev(2, EventType.DEATH),
        ev(3, EventType.ENEMY_DEFEATED, "ENEMY FELLED"),
        ev(4, EventType.ENEMY_DEFEATED, "ENEMY FELLED"),  # no bar seen: says nothing
        ev(5, EventType.BOSS_ENGAGED, "Grafted Scion"),
    ]
    s = compute(events)
    assert [(b.name, b.attempts, b.defeated) for b in s.bosses] == [("Tree Sentinel", 2, True), ("Grafted Scion", 0, False)]


def test_new_boss_after_a_checkpoint_is_a_new_fight():
    # Godrick's defeat banner was hidden by a popup; the next bar must not fold into his fight.
    events = [
        ev(1, EventType.BOSS_ENGAGED, "Godrick the Grafted"),
        ev(2, EventType.DEATH),
        ev(3, EventType.CHECKPOINT_DISCOVERED),
        ev(4, EventType.BOSS_ENGAGED, "Bloodhound Knight"),
        ev(5, EventType.ENEMY_DEFEATED, "ENEMY FELLED"),
    ]
    s = compute(events)
    assert [(b.name, b.attempts, b.defeated) for b in s.bosses] == [("Godrick the Grafted", 1, False), ("Bloodhound Knight", 1, True)]


def test_phase_rename_after_a_respawn_stays_one_fight():
    events = [
        ev(1, EventType.BOSS_ENGAGED, "Messmer the Impaler"),
        ev(2, EventType.BOSS_ENGAGED, "Base Serpent Messmer"),
        ev(3, EventType.DEATH),
        ev(4, EventType.AREA_DISCOVERED, "Shadow Keep"),  # replays on respawn
        ev(5, EventType.BOSS_ENGAGED, "Messmer the Impaler"),
        ev(6, EventType.BOSS_ENGAGED, "Base Serpent Messmer"),
        ev(7, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert [(b.name, b.attempts, b.phases) for b in s.bosses] == [("Messmer the Impaler", 2, ["Base Serpent Messmer"])]


def test_kill_goes_to_the_last_bar_when_the_name_changes_entirely():
    # Elden Ring's final fight: "Radagon of the Golden Order" becomes
    # "Elden Beast", which shares nothing with it. The Beast is what the
    # player put down, and Radagon stays in phases.
    events = [
        ev(1, EventType.BOSS_ENGAGED, "Radagon of the Golden Order"),
        ev(2, EventType.DEATH),
        ev(140, EventType.BOSS_ENGAGED, "Elden Beast"),
        ev(200, EventType.BOSS_DEFEATED),
    ]
    s = compute(events)
    assert [(b.name, b.attempts, b.phases) for b in s.bosses] == [("Elden Beast", 2, ["Radagon of the Golden Order"])]


def test_a_phase_rename_that_shares_a_name_keeps_the_first():
    # Malenia and Sister Friede must not become "Goddess of Rot" and
    # "Blackflame Friede": the later bar shares a name with the first.
    for first, second in (
        ("Malenia, Blade of Miquella", "Malenia, Goddess of Rot"),
        ("Sister Friede", "Blackflame Friede"),
        ("Messmer the Impaler", "Base Serpent Messmer"),
    ):
        events = [
            ev(1, EventType.BOSS_ENGAGED, first),
            ev(200, EventType.BOSS_ENGAGED, second),
            ev(300, EventType.BOSS_DEFEATED),
        ]
        assert [b.name for b in compute(events).bosses] == [first], (first, second)


def test_two_bosses_folded_for_want_of_a_defeat_credit_the_second():
    # Sekiro gives no defeat banner for a miniboss, so a miniboss and the
    # main boss after it fold into one fight when no idol separates them.
    # The banner belongs to the boss whose bar was up when it fired.
    events = [
        ev(10, EventType.BOSS_ENGAGED, "Juzou the Drunkard"),
        ev(320, EventType.BOSS_ENGAGED, "Lady Butterfly"),
        ev(430, EventType.BOSS_DEFEATED, "SHINOBI EXECUTION"),
    ]
    s = compute(events)
    assert [(b.name, b.defeated, b.phases) for b in s.bosses] == [
        ("Lady Butterfly", True, ["Juzou the Drunkard"])
    ]


def test_unknown_boss_is_unaffected_by_the_credit_rule():
    events = [ev(1, EventType.BOSS_DEFEATED)]
    assert [b.name for b in compute(events).bosses] == ["unknown boss"]


def test_a_fight_left_standing_carries_its_deaths_into_the_next_session():
    from previously_on.stats import BossStat, across_sessions

    fights = [
        BossStat("Red Wolf of Radagon", 2, True),
        BossStat("Rennala, Queen of the Full Moon", 20, False),  # evening one
        BossStat("Rennala Queen of the Full Moon", 14, True, ["Rennala, Full Moon"]),  # evening two, OCR slip
        BossStat("Royal Knight Loretta", 3, False),  # still standing at the end
    ]
    out = across_sessions(fights)
    assert [(f.name, f.attempts, f.defeated) for f in out] == [
        ("Red Wolf of Radagon", 2, True),
        ("Rennala Queen of the Full Moon", 34, True),
        ("Royal Knight Loretta", 3, False),
    ]
    assert out[1].phases == ["Rennala, Full Moon"]  # the first evening's spelling folds into the name


def test_a_felled_boss_does_not_lend_its_tries_to_a_namesake():
    from previously_on.stats import BossStat, across_sessions

    out = across_sessions([BossStat("Night's Cavalry", 3, True), BossStat("Night's Cavalry", 1, True)])
    assert [f.attempts for f in out] == [3, 1]
