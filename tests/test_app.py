"""M4 offline tests: the screens' view models, the app config and its
environment rule, the detector's stop hook, the watcher in replay mode, and
the API object the page talks to. No webview, no network."""

import json
import os
import threading
import time
from datetime import datetime, timedelta

from previously_on.app import views
from previously_on.app.api import Api
from previously_on.app.config import AppConfig, mask_key
from previously_on.app.watcher import Watcher
from previously_on.capture import Frame
from previously_on.games import get_profile, list_profiles
from previously_on.events import Event, EventType
from previously_on.pipeline import Detector
from previously_on.recap.provider import FakeProvider
from previously_on.recap.schema import Conversation, NpcState, PlaythroughState, SessionRecap, Thread
from previously_on.recap.store import recap_path, summarize_session
from previously_on.session import SessionLog, read_session

from .synth import blank_frame
from .test_pipeline import ScriptSource

E = EventType
GAME = "eldenring"


def ev(t, typ, text=""):
    return Event(ts=datetime(2026, 9, 16, 22, 0) + timedelta(seconds=t), t_rel=t, type=typ, text=text, conf=0.9, region="r")


SESSION_A = [
    ev(5, E.DIALOGUE, "I amMiriel,steward ofthissacredchamber."),
    ev(48, E.ITEM_ACQUIRED, "Golden Seed"),
    ev(59, E.AREA_DISCOVERED, "Liurnia of the Lakes"),
    ev(82, E.ITEM_ACQUIRED, "Thin Beast Bones"),
    ev(83, E.ITEM_ACQUIRED, "Thin Beast Bones"),
    ev(120, E.CHECKPOINT_DISCOVERED, "LOST GRACE DISCOVERED"),
    ev(200, E.BOSS_ENGAGED, "Red Wolf of Radagon"),
    ev(240, E.DEATH, "YOU DIED"),
    ev(300, E.BOSS_ENGAGED, "Red Wolf of Radagon"),
    ev(360, E.BOSS_DEFEATED, "GREAT ENEMY FELLED"),
]
SESSION_B = [
    ev(10, E.AREA_DISCOVERED, "Raya Lucaria Academy"),
    ev(100, E.BOSS_ENGAGED, "Rennala, Queen of the Full Moon"),
    ev(150, E.DEATH, "YOU DIED"),
    ev(200, E.BOSS_ENGAGED, "Rennala, Queen of the Full Moon"),
    ev(250, E.DEATH, "YOU DIED"),
]


def recap_for(sid, **kw):
    fields = dict(
        summary="Miriel welcomed you; the Red Wolf fell.",
        short_recap="You beat the Red Wolf of Radagon in Liurnia.",
        full_recap="Previously on Elden Ring: you met Miriel at the Church of Vows, then felled the Red Wolf of Radagon.",
        state=PlaythroughState(
            location="Liurnia of the Lakes",
            current_objective="Find Rennala",
            threads=[Thread(who="Miriel", what="take what you need", evidence=[f"{sid}#0"])],
            npcs=[NpcState(name="Miriel", last_location="Liurnia of the Lakes", evidence=[f"{sid}#0"])],
            notable_items=["Golden Seed"],
        ),
        conversations=[Conversation(speaker="Miriel", speaker_basis="named", events=[0], gist="Welcome.")],
    )
    fields.update(kw)
    return SessionRecap(**fields)


def write_session(tmp_path, started, events):
    with SessionLog.open(GAME, "video", data_dir=tmp_path, started=started) as log:
        for e in events:
            log.append(e)
        played = events[-1].t_rel + 10
        log.close(ended=started + timedelta(seconds=played), played=played)
    return log.path


def playthrough(tmp_path, eldenring, recap_second=False):
    """Two sessions a day apart; the first has a recap, the second only if asked."""
    a = write_session(tmp_path, datetime(2026, 9, 15, 20, 0), SESSION_A)
    b = write_session(tmp_path, datetime(2026, 9, 16, 22, 0), SESSION_B)
    summarize_session(a, eldenring, FakeProvider(recap_for(a.stem)))
    if recap_second:
        summarize_session(b, eldenring, FakeProvider(recap_for(b.stem, summary="Rennala twice.", state=PlaythroughState(location="Raya Lucaria Academy"))))
    return a, b


# --- views -----------------------------------------------------------------


def test_home_is_empty_without_logs(tmp_path):
    assert views.home(GAME, tmp_path) == {"empty": True}


def test_home_picks_the_tier_by_gap(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring, recap_second=True)
    ended = datetime(2026, 9, 16, 22, 0) + timedelta(seconds=260)
    same_day = views.home(GAME, tmp_path, now=ended + timedelta(hours=5))
    assert same_day["tier"] == "one_line" and same_day["session"] == b.stem
    assert same_day["text"].startswith("Last session, earlier today: 4m · 2 deaths · Rennala, Queen of the Full Moon still standing")
    assert "Previously on" in same_day["full_text"]  # available on request, not shown by default
    week = views.home(GAME, tmp_path, now=ended + timedelta(days=5))
    assert week["tier"] == "short" and "Last played 5 days ago" in week["text"]
    month = views.home(GAME, tmp_path, now=ended + timedelta(days=40))
    assert month["tier"] == "full" and month["full_text"] is None and "Previously on" in month["text"]
    assert month["state"]["location"] == "Raya Lucaria Academy" and month["state_from"] == b.stem
    assert month["needs_recap"] is False


def test_home_without_a_recap_falls_back_to_stats_and_the_older_state(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring)
    h = views.home(GAME, tmp_path, now=datetime(2026, 10, 30))
    assert h["needs_recap"] is True and h["tier"] == "one_line" and h["full_text"] is None
    assert "Rennala, Queen of the Full Moon still standing" in h["text"]
    assert h["state"]["location"] == "Liurnia of the Lakes" and h["state_from"] == a.stem
    assert h["state"]["threads"] == [{"who": "Miriel", "what": "take what you need", "status": "open"}]


def test_sessions_and_session_detail(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring)
    rows = views.sessions(GAME, tmp_path)
    assert [r["session"] for r in rows] == [b.stem, a.stem]  # newest first
    assert rows[1]["has_recap"] and rows[1]["summary"] == "Miriel welcomed you; the Red Wolf fell."
    assert not rows[0]["has_recap"] and rows[0]["summary"] is None
    assert rows[1]["bosses"] == [{"name": "Red Wolf of Radagon", "attempts": 2, "defeated": True, "phases": []}]
    assert rows[1]["areas"] == ["Liurnia of the Lakes"] and rows[1]["items"] == 3 and rows[1]["checkpoints"] == 1

    d = views.session(GAME, tmp_path, a.stem)
    assert [e["index"] for e in d["event_list"]] == list(range(10))
    assert d["event_list"][1] == {"index": 1, "at": "0:00:48", "t_rel": 48.0, "type": "item_acquired", "text": "Golden Seed", "conf": 0.9}
    assert d["conversations"] == [
        {"speaker": "Miriel", "basis": "named", "location": None, "at": "0:00:05", "events": [0], "gist": "Welcome."}
    ]
    assert d["full_recap"].startswith("Previously on")
    assert views.session(GAME, tmp_path, "nope") is None


def test_timeline_groups_index_entries_per_session(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring)
    t = views.timeline(GAME, tmp_path)
    assert [r["session"] for r in t] == [a.stem, b.stem]  # oldest first
    assert [(m["kind"], m["name"], m["detail"]) for m in t[0]["moments"]] == [
        ("area", "Liurnia of the Lakes", ""),
        ("boss", "Red Wolf of Radagon", "felled in 2 tries"),
    ]
    assert t[0]["moments"][1]["location"] == "Liurnia of the Lakes"
    assert t[0]["item_names"] == ["Golden Seed", "Thin Beast Bones ×2"] and t[0]["checkpoints"] == 1
    assert t[1]["moments"][1]["detail"] == "2 deaths, still standing"


def test_totals_line(tmp_path, eldenring):
    assert views.totals(GAME, tmp_path)["line"] == ""
    playthrough(tmp_path, eldenring)
    t = views.totals(GAME, tmp_path)
    assert t["sessions"] == 2 and t["deaths"] == 3 and t["bosses_felled"] == 1
    assert t["line"] == "10m · 3 deaths · Red Wolf of Radagon took 2 tries"


def test_search_returns_rows(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring)
    hits = views.search(GAME, tmp_path, "miriel")
    assert [(h["kind"], h["name"], h["session"]) for h in hits] == [("npc", "Miriel", a.stem)]
    assert views.search(GAME, tmp_path, "rennala", ["boss"])[0]["detail"] == "2 deaths, still standing"


# --- config -------------------------------------------------------------------


def test_config_round_trip_and_defaults(tmp_path):
    path = tmp_path / "cfg" / "config.json"
    assert AppConfig.load(path) == AppConfig()
    AppConfig(openai_api_key="sk-secret-1234", monitor=2).save(path)
    loaded = AppConfig.load(path)
    assert loaded.openai_api_key == "sk-secret-1234" and loaded.monitor == 2 and loaded.watch_on_start
    path.write_text("{not json")
    assert AppConfig.load(path) == AppConfig()


def test_apply_env_never_overrides_what_the_process_started_with(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PREVIOUSLY_ON_MODEL", raising=False)
    startup = frozenset({"OPENAI_API_KEY"})
    AppConfig(openai_api_key="from-file", anthropic_api_key="ant-file", model="gpt-x").apply_env(startup)
    assert os.environ["OPENAI_API_KEY"] == "from-shell"
    assert os.environ["ANTHROPIC_API_KEY"] == "ant-file" and os.environ["PREVIOUSLY_ON_MODEL"] == "gpt-x"
    # A later change replaces our own value; clearing removes it.
    AppConfig(anthropic_api_key="ant-file-2").apply_env(startup)
    assert os.environ["ANTHROPIC_API_KEY"] == "ant-file-2" and "PREVIOUSLY_ON_MODEL" not in os.environ


def test_mask_key():
    assert mask_key("") == "" and mask_key("short") == "•••••" and mask_key("sk-abcdefghijklmnop") == "sk-…mnop"


# --- detector stop hook + watcher ---------------------------------------------------


class EndlessBlankSource:
    """A live source stand-in: never ends on its own."""

    name = "endless"

    def __init__(self):
        self.closed = False

    def frames(self):
        i = 0
        while True:
            yield Frame(index=i, ts=datetime.now(), t_rel=i / 2.0, image=blank_frame(i % 4))
            i += 1

    def close(self):
        self.closed = True


class NoOcr:
    def read(self, image):
        return []


def test_detector_stops_on_the_hook_and_closes_the_log(tmp_path, eldenring):
    log = SessionLog.open(GAME, "endless", data_dir=tmp_path)
    source = EndlessBlankSource()
    stop = threading.Event()
    detector = Detector(source, eldenring, NoOcr(), log, on_event=lambda e: None, should_stop=stop.is_set)
    t = threading.Thread(target=detector.run)
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(5)
    assert not t.is_alive() and source.closed
    meta, events = read_session(log.path)
    assert meta.ended is not None and events == []


def test_watcher_replays_once_records_events_and_writes_the_recap(tmp_path, eldenring, ocr):
    fake = FakeProvider(recap_for("x", conversations=[], state=PlaythroughState()))

    def summarize(path, profile):
        return summarize_session(path, profile, fake), "recap written with fake"

    w = Watcher(
        eldenring,
        tmp_path,
        source_factory=ScriptSource,
        wait_for_game=False,
        summarize=summarize,
        get_ocr=lambda threads: ocr,
    )
    assert w.status()["state"] == "idle" and not w.running
    w.start()
    assert not w.start()  # already running
    seen = set()
    for _ in range(600):
        seen.add(w.status()["state"])
        if not w.running:
            break
        time.sleep(0.1)
    assert not w.running, "the replay did not finish"
    assert "capturing" in seen  # "summarizing" is too brief to sample with a fake provider
    s = w.status()
    assert s["state"] == "idle" and s["recap_ready"] and s["message"] == "recap written with fake"
    assert s["events"] == 8 and s["last_event"]["text"] == "Liurnia of the Lakes"
    assert [e["type"] for e in w.recent_events()][:3] == ["dialogue", "item_acquired", "boss_engaged"]
    logs = list((tmp_path / "sessions" / GAME).glob("*.jsonl"))
    assert len(logs) == 1 and recap_path(logs[0]).exists() and s["session"] == logs[0].stem


def test_watcher_waits_for_the_game_and_stops_when_asked(tmp_path, eldenring):
    w = Watcher(eldenring, tmp_path, find_game=lambda candidates: None, get_ocr=lambda n: NoOcr())
    w.start()
    time.sleep(0.2)
    assert w.status()["state"] == "waiting" and w.status()["message"] == "Waiting for Elden Ring…"
    w.stop()
    w.join(5)
    assert not w.running and w.status()["state"] == "idle"
    assert not (tmp_path / "sessions").exists()  # no session was opened


def test_watcher_captures_whichever_game_starts_until_that_game_exits(tmp_path, monkeypatch):
    import previously_on.app.watcher as watcher_mod

    monkeypatch.setattr(watcher_mod, "POLL", 0.05)
    running: set[str] = set()

    def find_game(candidates):
        return next((p for p in candidates if p.id in running), None)

    summarized = []
    w = Watcher(
        list_profiles(),
        tmp_path,
        source_factory=EndlessBlankSource,
        find_game=find_game,
        summarize=lambda path, profile: summarized.append(profile.id) or (None, "no key"),
        get_ocr=lambda n: NoOcr(),
        low_priority=False,
    )
    w.start()
    time.sleep(0.2)
    assert w.status()["message"] == "Waiting for a game…" and w.profile is None
    running.add("ds3")
    for _ in range(50):
        if w.status()["state"] == "capturing":
            break
        time.sleep(0.05)
    s = w.status()
    assert s["state"] == "capturing" and s["game"] == "ds3" and "Dark Souls III" in s["message"]
    running.add("eldenring")  # another watched game starting does not end the session
    time.sleep(0.3)
    assert w.status()["state"] == "capturing" and w.status()["game"] == "ds3"
    running.discard("ds3")
    for _ in range(100):
        if summarized:
            break
        time.sleep(0.05)
    assert summarized == ["ds3"]
    # Elden Ring is still running, so the next capture is Elden Ring's.
    for _ in range(100):
        if w.status()["game"] == "eldenring":
            break
        time.sleep(0.05)
    assert w.status()["game"] == "eldenring"
    w.stop()
    w.join(5)
    assert len(list((tmp_path / "sessions" / "ds3").glob("*.jsonl"))) == 1


# --- api ----------------------------------------------------------------------------


def test_api_returns_json_and_reports_errors_as_dicts(tmp_path, eldenring):
    a, b = playthrough(tmp_path, eldenring)
    api = Api(list_profiles(), tmp_path, None, AppConfig(), tmp_path / "config.json")
    for name, args in [
        ("home", ()), ("sessions", ()), ("session", (a.stem,)), ("timeline", ()), ("totals", ()),
        ("search", ("miriel",)), ("status", ()), ("recent_events", ()), ("get_settings", ()), ("games", ()),
    ]:
        out = getattr(api, name)(*args)
        json.dumps(out)
        assert "error" not in out, name
    assert api.home()["game"] == "Elden Ring"
    assert api.session("nope") == {"error": "no session nope"}
    assert api.start_watch()["error"].startswith("capture is disabled")
    assert api.summarize("nope") == {"error": "no session nope"}
    assert api.status()["state"] == "idle" and api.status()["summarize"]["state"] == "idle"


def test_api_shows_the_last_played_game_and_switches_on_request(tmp_path, eldenring):
    playthrough(tmp_path, eldenring)
    api = Api(list_profiles(), tmp_path, None, AppConfig())
    g = api.games()
    assert g["current"] == "eldenring"  # the only game with sessions
    assert [x["id"] for x in g["games"]] == [p.id for p in list_profiles()]
    assert {x["id"]: x["sessions"] for x in g["games"]}["eldenring"] == 2
    assert api.select_game("ds3") == {"current": "ds3"}
    home = api.home()
    assert home["empty"] and home["game"] == "Dark Souls III"
    assert api.sessions() == {"sessions": []} and api.status()["view"] == "ds3"
    assert api.select_game("nope")["error"] == "unknown game nope"
    # --game opens on that game even if another was played last.
    assert Api(list_profiles(), tmp_path, None, AppConfig(), game="sekiro").games()["current"] == "sekiro"


class StubWatcher:
    def __init__(self):
        self.state = {"state": "idle", "running": True, "message": "", "game": None, "session": None}

    def status(self):
        return dict(self.state)

    def waiting_for(self):
        return "a game"


def test_api_follows_a_capture_once_and_then_the_players_pick(tmp_path, eldenring):
    playthrough(tmp_path, eldenring)
    w = StubWatcher()
    api = Api(list_profiles(), tmp_path, w, AppConfig())
    s = api.status()
    assert s["view"] == "eldenring" and s["watching"] == "a game" and s["game"] is None
    w.state.update(state="capturing", game="sekiro", session="20260923-200000")
    s = api.status()
    assert s["view"] == "sekiro" and s["game"] == "Sekiro: Shadows Die Twice" and s["game_id"] == "sekiro"
    api.select_game("eldenring")  # browsing another game mid-capture sticks...
    assert api.status()["view"] == "eldenring"
    w.state.update(game="ds2", session="20260923-230000")  # ...until the next capture starts
    assert api.status()["view"] == "ds2"


def test_api_settings_mask_keys_and_validate(tmp_path, eldenring, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = Api(eldenring, tmp_path, None, AppConfig(), tmp_path / "config.json")
    assert api.save_settings({"monitor": 0})["error"].startswith("monitor:")
    out = api.save_settings({"openai_api_key": "sk-abcdefghijklmnop", "monitor": 2, "model": ""})
    assert out["openai_api_key"] == "sk-…mnop" and out["has_openai_key"] and out["monitor"] == 2
    assert "sk-abcdefghijklmnop" not in json.dumps(api.get_settings())
    assert AppConfig.load(tmp_path / "config.json").openai_api_key == "sk-abcdefghijklmnop"
    # An empty key field keeps the stored key; clear_ removes it.
    assert api.save_settings({"openai_api_key": ""})["has_openai_key"]
    assert not api.save_settings({"clear_openai_api_key": True})["has_openai_key"]


def test_running_profile_matches_process_names_case_insensitively(monkeypatch):
    import previously_on.game_process as gp

    class Proc:
        def __init__(self, name):
            self.info = {"name": name}

    procs = [Proc("explorer.exe"), Proc("darksoulsiii.exe"), Proc(None)]
    monkeypatch.setattr(gp.psutil, "process_iter", lambda attrs: iter(procs))
    assert gp.running_profile(list_profiles()).id == "ds3"
    assert gp.running_profile([get_profile("eldenring")]) is None


def test_gui_entry_logs_to_app_log(tmp_path, monkeypatch):
    import sys

    import previously_on.app as app

    monkeypatch.setattr(app, "default_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "run_app", lambda: print("hello from the window", file=sys.stderr) or 0)
    monkeypatch.setattr(sys, "stderr", sys.stderr)  # restored after the test
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    assert app.main() == 0
    sys.stderr.flush()
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert text.startswith("--- ") and "previously-on" in text
    assert "hello from the window" in text
