"""Several playthroughs of one game: what a log records, the registry, moving
a session, the recap chain staying inside a playthrough, New Game+ in the
prompt, and the screens, API and CLI showing one playthrough at a time."""

import json
from datetime import datetime, timedelta

from previously_on import card
from previously_on.app import views
from previously_on.app.api import Api
from previously_on.app.config import AppConfig
from previously_on.app.sync import is_open
from previously_on.cli import main
from previously_on.games import list_profiles
from previously_on.playthroughs import Registry
from previously_on.recap import index as index_mod
from previously_on.recap.provider import FakeProvider
from previously_on.recap.schema import NpcState, PlaythroughState
from previously_on.recap.store import latest_record, previous_state, summarize_session
from previously_on.session import DEFAULT_PLAYTHROUGH, SessionLog, move_session, playthrough_of, read_session

from .test_app import GAME, SESSION_A, SESSION_B, recap_for

DAY = datetime(2026, 9, 16, 20, 0)


def write(tmp_path, started, events=SESSION_A, **tag):
    with SessionLog.open(GAME, "video", data_dir=tmp_path, started=started, **tag) as log:
        for e in events:
            log.append(e)
        played = events[-1].t_rel + 10
        log.close(ended=started + timedelta(seconds=played), played=played)
    return log.path


def first_line(path):
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def test_the_default_playthrough_writes_nothing_new(tmp_path):
    path = write(tmp_path, DAY)
    assert "playthrough" not in first_line(path)  # every log before playthroughs reads the same
    assert playthrough_of(path) == (DEFAULT_PLAYTHROUGH, None, 0)
    assert read_session(path)[0].playthrough == DEFAULT_PLAYTHROUGH
    assert not (tmp_path / "sessions" / GAME / "playthroughs.json").exists()
    assert [p.id for p in Registry.load(GAME, tmp_path).all()] == [DEFAULT_PLAYTHROUGH]


def test_registry_creates_switches_and_survives_a_reload(tmp_path):
    reg = Registry.load(GAME, tmp_path)
    alt = reg.create("  Moon   sorcerer ", now=DAY)
    assert alt.name == "Moon sorcerer" and reg.current_id == alt.id
    ng = reg.new_game_plus(alt.id, now=DAY + timedelta(hours=1))
    assert (ng.cycle, ng.follows, ng.name) == (1, alt.id, "Moon sorcerer · NG+")
    ng2 = reg.new_game_plus(ng.id, now=DAY + timedelta(hours=2))
    assert (ng2.cycle, ng2.name) == (2, "Moon sorcerer · NG++")
    reg.select(DEFAULT_PLAYTHROUGH)
    reg.rename(DEFAULT_PLAYTHROUGH, "Samurai")
    reg.save()

    again = Registry.load(GAME, tmp_path)
    assert again.current().label == "Samurai"
    assert [p.label for p in again.all()] == ["Samurai", "Moon sorcerer", "Moon sorcerer · NG+", "Moon sorcerer · NG++"]
    assert again.get(ng2.id).follows == ng.id


def test_registry_refuses_bad_names_and_deleting_what_has_sessions(tmp_path):
    reg = Registry.load(GAME, tmp_path)
    for bad in ("", "   ", "x" * 61):
        try:
            reg.create(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    alt = reg.create("Bleed", now=DAY)
    write(tmp_path, DAY, **reg.tag())
    for pid in (DEFAULT_PLAYTHROUGH, alt.id):
        try:
            reg.delete(pid)
        except ValueError:
            continue
        raise AssertionError(f"deleted {pid}")
    empty = reg.create("Empty", now=DAY + timedelta(minutes=1))
    reg.delete(empty.id)
    assert reg.current_id == DEFAULT_PLAYTHROUGH and len(reg.all()) == 2


def test_a_tagged_log_and_one_synced_from_another_pc(tmp_path):
    reg = Registry.load(GAME, tmp_path)
    alt = reg.create("Bleed", now=DAY)
    reg.save()
    path = write(tmp_path, DAY, **reg.tag())
    assert first_line(path)["playthrough"] == {"id": alt.id, "name": "Bleed"}
    meta = read_session(path)[0]
    assert (meta.playthrough, meta.playthrough_name, meta.cycle) == (alt.id, "Bleed", 0)

    # A log this PC's list has never heard of brings its name with it.
    write(tmp_path, DAY + timedelta(days=1), playthrough="20260901-120000", playthrough_name="Laptop run", cycle=1)
    reg = Registry.load(GAME, tmp_path)
    other = reg.get("20260901-120000")
    assert (other.label, other.cycle) == ("Laptop run", 1)
    assert [r["sessions"] for r in reg.rows()] == [0, 1, 1]


def test_moving_a_finished_session_appends_and_keeps_it_syncable(tmp_path):
    reg = Registry.load(GAME, tmp_path)
    alt = reg.create("Bleed", now=DAY)
    reg.save()
    path = write(tmp_path, DAY)
    before = path.read_text(encoding="utf-8")
    move_session(path, alt.id, alt.name)
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)  # append-only
    assert playthrough_of(path)[0] == alt.id
    assert read_session(path)[0].playthrough == alt.id
    assert not is_open(path)  # the line after session_end doesn't make it look unfinished
    move_session(path, DEFAULT_PLAYTHROUGH)
    assert playthrough_of(path)[0] == DEFAULT_PLAYTHROUGH

    # A log still being written belongs to the capture.
    live = SessionLog.open(GAME, "video", data_dir=tmp_path, started=DAY + timedelta(days=2))
    try:
        move_session(live.path, alt.id)
    except ValueError:
        pass
    else:
        raise AssertionError("moved an open log")
    finally:
        live.close()


def test_the_recap_chain_stays_inside_a_playthrough(tmp_path, eldenring):
    reg = Registry.load(GAME, tmp_path)
    first = write(tmp_path, DAY)
    alt = reg.create("Bleed", now=DAY)
    reg.save()
    other = write(tmp_path, DAY + timedelta(days=1), **reg.tag())
    second = write(tmp_path, DAY + timedelta(days=2))

    remembered = recap_for(first.stem, state=PlaythroughState(npcs=[NpcState(name="Miriel", evidence=[f"{first.stem}#0"])]))
    summarize_session(first, eldenring, FakeProvider(remembered))
    summarize_session(other, eldenring, FakeProvider(recap_for(other.stem, state=PlaythroughState(location="Limgrave"))))

    assert previous_state(other).npcs == []  # the other character starts empty
    assert previous_state(second).npcs[0].name == "Miriel"  # skips the other character's newer record
    assert latest_record(GAME, tmp_path)[1].session == other.stem  # current = Bleed
    assert latest_record(GAME, tmp_path, DEFAULT_PLAYTHROUGH)[1].session == first.stem
    assert alt.id == reg.current_id


def test_new_game_plus_is_told_to_the_model(tmp_path, eldenring):
    reg = Registry.load(GAME, tmp_path)
    write(tmp_path, DAY)
    ng = reg.new_game_plus(DEFAULT_PLAYTHROUGH, now=DAY)
    reg.save()
    assert ng.cycle == 1 and ng.name == "First playthrough · NG+"
    path = write(tmp_path, DAY + timedelta(days=1), **reg.tag())
    fake = FakeProvider(recap_for(path.stem))
    summarize_session(path, eldenring, fake)
    assert "New Game+ (cycle 2)" in fake.calls[0][1]
    assert '"npcs": []' in fake.calls[0][1]  # a fresh world: nothing carried over
    fake_first = FakeProvider(recap_for("x"))
    summarize_session(sorted((tmp_path / "sessions" / GAME).glob("*.jsonl"))[0], eldenring, fake_first)
    assert "New Game+" not in fake_first.calls[0][1]


def test_screens_show_the_current_playthrough(tmp_path):
    write(tmp_path, DAY, SESSION_A)
    reg = Registry.load(GAME, tmp_path)
    alt = reg.create("Bleed", now=DAY)
    reg.save()
    b = write(tmp_path, DAY + timedelta(days=1), SESSION_B, **reg.tag())

    assert [s["session"] for s in views.sessions(GAME, tmp_path)] == [b.stem]
    assert views.sessions(GAME, tmp_path)[0]["episode"] == 1  # numbered within the playthrough
    assert views.home(GAME, tmp_path)["session"] == b.stem
    assert card.gather(GAME, tmp_path).sessions == 1
    assert card.gather(GAME, tmp_path, DEFAULT_PLAYTHROUGH).sessions == 1
    assert not index_mod.search(index_mod.build(GAME, tmp_path), "Red Wolf")
    assert index_mod.search(index_mod.build(GAME, tmp_path, DEFAULT_PLAYTHROUGH), "Red Wolf")
    assert views.games(list_profiles(), tmp_path)[0]["sessions"] == 2  # the game counts every playthrough
    assert views.session(GAME, tmp_path, b.stem)["playthrough"] == alt.id


def test_api_switches_creates_and_moves(tmp_path):
    a = write(tmp_path, DAY, SESSION_A)
    api = Api(list_profiles(), tmp_path, None, AppConfig(), game=GAME)
    out = api.playthroughs()
    assert [p["label"] for p in out["playthroughs"]] == ["First playthrough"]

    out = api.new_playthrough("Bleed")
    new = next(p for p in out["playthroughs"] if p["label"] == "Bleed")
    assert out["current"] == new["id"] and api.sessions()["sessions"] == []
    assert api.new_playthrough(" ")["error"]
    assert "Elden Ring: Bleed" == api._card_name(api._profile())

    out = api.move_session(a.stem, new["id"])
    assert "error" not in out and [s["session"] for s in api.sessions()["sessions"]] == [a.stem]
    assert api.move_session("20000101-000000", new["id"])["error"]
    assert api.move_session(a.stem, "nope")["error"]

    out = api.new_game_plus(new["id"])
    assert out["playthroughs"][-1]["label"] == "Bleed · NG+" and out["playthroughs"][-1]["current"]
    assert api.select_playthrough(DEFAULT_PLAYTHROUGH)["current"] == DEFAULT_PLAYTHROUGH
    assert api.delete_playthrough(out["playthroughs"][-1]["id"])["playthroughs"][-1]["label"] == "Bleed"
    assert api.rename_playthrough(new["id"], "Blood")["playthroughs"][1]["label"] == "Blood"


def test_cli_playthroughs(tmp_path, capsys):
    write(tmp_path, DAY)
    base = ["playthroughs", "--game", GAME, "--data-dir", str(tmp_path)]
    assert main(base) == 0
    assert "* main" in capsys.readouterr().out
    assert main([*base, "new", "Bleed"]) == 0
    out = capsys.readouterr().out
    assert "* " in out and "Bleed" in out
    assert main([*base, "ng-plus"]) == 0
    assert "Bleed · NG+  [NG+]" in capsys.readouterr().out
    assert main([*base, "switch", "main"]) == 0
    stamp = sorted((tmp_path / "sessions" / GAME).glob("*.jsonl"))[0].stem
    pid = Registry.load(GAME, tmp_path).all()[1].id
    assert main([*base, "move", stamp, pid]) == 0
    assert main([*base, "switch", "nope"]) == 1
