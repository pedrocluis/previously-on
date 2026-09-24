"""M3 offline tests: compaction, grounding checks, the record store and its
state chain, gap tiers, search, and the CLI with a fake provider. Nothing
here touches the network."""

from datetime import datetime, timedelta

from previously_on.cli import main
from previously_on.events import Event, EventType
from previously_on.recap import index as index_mod
from previously_on.recap.compact import compact
from previously_on.recap.gap import pick_tier, render
from previously_on.recap.provider import FakeProvider
from previously_on.recap.schema import Conversation, NpcState, PlaythroughState, SessionRecap, Thread
from previously_on.recap.store import latest_record, previous_state, read_record, recap_path, summarize_session
from previously_on.recap.verify import verify
from previously_on.session import SessionLog, SessionMeta

E = EventType


def ev(t, typ, text=""):
    return Event(ts=datetime(2026, 9, 16, 22, 0) + timedelta(seconds=t), t_rel=t, type=typ, text=text, conf=0.9, region="r")


SESSION = [
    ev(2, E.DIALOGUE, "I welcome you, to the Church of Vows."),
    ev(5, E.DIALOGUE, "I amMiriel,steward ofthissacredchamber."),
    ev(9, E.DIALOGUE, "If you find anything of use, you are free to take it with you."),
    ev(48, E.ITEM_ACQUIRED, "Golden Seed"),
    ev(59, E.AREA_DISCOVERED, "Liurnia of the Lakes"),
    ev(82, E.ITEM_ACQUIRED, "Thin Beast Bones"),
    ev(83, E.ITEM_ACQUIRED, "Thin Beast Bones"),
    ev(84, E.ITEM_ACQUIRED, "Thin Beast Bones"),
    ev(120, E.CHECKPOINT_DISCOVERED, "LOST GRACE DISCOVERED"),
    ev(200, E.BOSS_ENGAGED, "Red Wolf of Radagon"),
    ev(240, E.DEATH, "YOU DIED"),
    ev(300, E.BOSS_ENGAGED, "Red Wolf of Radagon"),
    ev(360, E.BOSS_DEFEATED, "GREAT ENEMY FELLED"),
    ev(400, E.DIALOGUE, "Hush, little culver."),
    ev(500, E.ENEMY_DEFEATED, "ENEMY FELLED"),
    ev(600, E.BOSS_ENGAGED, "Glintstone Dragon Adula"),
    ev(650, E.DEATH, "YOU DIED"),
]


def meta():
    return SessionMeta(game="eldenring", source="video", started=datetime(2026, 9, 16, 22, 0), played=700.0)


# --- compact ---------------------------------------------------------------


def test_compact_blocks_dialogue_folds_items_and_counts_attempts():
    txt = compact(meta(), SESSION)
    lines = txt.splitlines()
    assert lines[0].startswith("Session 2026-09-16 22:00 · 11m · 2 deaths · Glintstone Dragon Adula still standing")
    assert "[0:00:02] dialogue:" in lines
    assert "  #1 I amMiriel,steward ofthissacredchamber." in lines
    assert "#5 [0:01:22] item: Thin Beast Bones ×3 (#5-#7)" in lines
    assert "#4 [0:00:59] area: Liurnia of the Lakes" in lines
    assert "[0:06:40] dialogue @Liurnia of the Lakes:" in lines  # place carried into the block
    assert "#12 [0:06:00] defeated: Red Wolf of Radagon (attempt 2; banner GREAT ENEMY FELLED)" in lines
    assert "#14 [0:08:20] enemy felled (no boss bar seen; may be a stray)" in lines
    assert "#16 [0:10:50] died" in lines
    assert sum(1 for l in lines if l.startswith("#") or l.startswith("  #")) == 15  # 17 events, 3 identical items folded into one line


# --- verify ----------------------------------------------------------------


def _recap(**kw):
    base = dict(
        summary="s", short_recap="sh", full_recap="f", state=PlaythroughState(), conversations=[]
    )
    base.update(kw)
    return SessionRecap(**base)


def test_verify_drops_bad_citations_and_ungrounded_names():
    sid = "20260916-220000"
    recap = _recap(
        conversations=[
            Conversation(speaker="Miriel", speaker_basis="named", location="Church of Vows", events=[0, 1, 2], gist="welcome"),
            Conversation(speaker="Rennala", speaker_basis="named", location="Raya Lucaria", events=[13], gist="hush"),
            Conversation(speaker="Ghost", speaker_basis="named", events=[99], gist="nothing"),
            Conversation(speaker="Miriel", speaker_basis="named", events=[2], gist="later, no name in the line"),
        ],
        state=PlaythroughState(
            location="Liurnia of the Lakes",
            threads=[
                Thread(who="Miriel", what="look around", evidence=[f"{sid}#2"]),
                Thread(who="Melina", what="go to the Roundtable", evidence=[f"{sid}#2"]),
                Thread(who="Nobody", what="", evidence=[]),
            ],
            npcs=[NpcState(name="Miriel", last_location="Church of Vows", evidence=[f"{sid}#1"]),
                  NpcState(name="Miriel", last_location="Church of Vows", evidence=["20260101-000000#4"])],
            notable_items=["Golden Seed", "Elden Ring"],
        ),
    )
    out, dropped = verify(recap, SESSION, PlaythroughState(), sid)
    assert [c.speaker for c in out.conversations] == ["Miriel", "Rennala", "Miriel"]
    assert out.conversations[0].speaker_basis == "named"
    assert out.conversations[2].speaker_basis == "named"  # named earlier this session
    assert out.conversations[0].location == "Church of Vows"  # mentioned in a subtitle line
    assert out.conversations[1].speaker_basis == "inferred"  # "named" but no name in the cited line
    assert out.conversations[1].location is None  # Raya Lucaria appears nowhere
    assert [t.who for t in out.state.threads] == ["Miriel"]
    assert [x.name for x in out.state.npcs] == ["Miriel"]  # the second cites a session the state never had
    assert out.state.notable_items == ["Golden Seed"]
    assert out.state.location == "Liurnia of the Lakes"
    assert any("Ghost" in d for d in dropped) and any("Melina" in d for d in dropped)
    assert any("Elden Ring" in d for d in dropped)


def test_verify_accepts_names_and_references_carried_from_previous_state():
    sid = "20260916-220000"
    prior = PlaythroughState(
        location="Roundtable Hold",
        npcs=[NpcState(name="Melina", last_location="Roundtable Hold", evidence=["20260915-200000#7"])],
    )
    recap = _recap(
        state=PlaythroughState(
            location="Roundtable Hold",
            npcs=[NpcState(name="Melina", last_location="Roundtable Hold", evidence=["20260915-200000#7"])],
            threads=[Thread(who="Melina", what="seek the Erdtree", evidence=["20260915-200000#7", f"{sid}#0"])],
        )
    )
    out, dropped = verify(recap, SESSION, prior, sid)
    assert dropped == []
    assert out.state.npcs[0].evidence == ["20260915-200000#7"]
    assert out.state.threads[0].evidence == ["20260915-200000#7", f"{sid}#0"]


def test_speaker_known_only_from_previous_state_is_inferred():
    # Elden Ring eval, chunk 12: "Gideon Ofnir" was in the state, the session
    # never says his name, and the recap stated the attribution as fact.
    sid = "20260916-220000"
    prior = PlaythroughState(npcs=[NpcState(name="Gideon Ofnir", last_location="Roundtable Hold", evidence=["20260915-200000#7"])])
    recap = _recap(
        conversations=[Conversation(speaker="Gideon Ofnir", speaker_basis="named", events=[2], gist="take what you need")],
        state=prior.model_copy(deep=True),
    )
    out, dropped = verify(recap, SESSION, prior, sid)
    assert out.conversations[0].speaker_basis == "inferred"
    assert any("Gideon Ofnir" in d and "now inferred" in d for d in dropped)
    assert [x.name for x in out.state.npcs] == ["Gideon Ofnir"]  # the state entry itself stands


def test_verify_accepts_combined_names_session_wide_mentions_and_caps_items():
    sid = "20260916-220000"
    recap = _recap(
        conversations=[
            # Named in the session's dialogue (#1), but this conversation cites a line without the name.
            Conversation(speaker="Miriel", speaker_basis="named", events=[2], gist="later"),
        ],
        state=PlaythroughState(
            location="Church of Vows, Liurnia of the Lakes",  # combined: each part is in the log
            threads=[Thread(who="Miriel / Church of Vows", what="look around", evidence=[f"20260916-{sid}#2"])],  # doubled id
            npcs=[NpcState(name="Steward (Miriel)", evidence=[f"{sid}#{i}" for i in range(10)])],
            notable_items=["Golden Seed"] + ["Thin Beast Bones"] * 20,
        ),
    )
    out, dropped = verify(recap, SESSION, PlaythroughState(), sid)
    assert out.conversations[0].speaker_basis == "named"
    assert out.state.location == "Church of Vows, Liurnia of the Lakes"
    assert [t.who for t in out.state.threads] == ["Miriel / Church of Vows"]
    assert out.state.threads[0].evidence == [f"{sid}#2"]  # canonicalised
    assert [x.name for x in out.state.npcs] == ["Steward (Miriel)"]
    assert out.state.npcs[0].evidence == [f"{sid}#{i}" for i in range(4, 10)]  # newest 6 kept
    assert len(out.state.notable_items) == 15 and "Golden Seed" not in out.state.notable_items  # oldest dropped
    assert dropped == ["items: 6 over the cap of 15, oldest dropped"]


def test_verify_restores_what_the_model_forgot():
    sid = "20260916-220000"
    prior = PlaythroughState(
        location="Roundtable Hold",
        current_objective="Deliver the letter",
        threads=[Thread(who="Irina", what="Deliver her letter to Castle Morne", evidence=["20260915-200000#3"]),
                 Thread(who="Varre", what="Go to Stormveil", evidence=["20260915-200000#9"])],
        npcs=[NpcState(name="Varre", evidence=["20260915-200000#9"]), NpcState(name="Irina", evidence=["20260915-200000#3"])],
        notable_items=["Irina's Letter"],
    )
    # The model wiped everything but Varre, whom it updated, and Irina's thread, which it closed.
    recap = _recap(state=PlaythroughState(
        threads=[Thread(who="Irina", what="Hand the letter to the commander", status="done", evidence=["20260915-200000#3"])],  # reworded
        npcs=[NpcState(name="Varre", notes="updated", evidence=["20260915-200000#9", f"{sid}#0"])],
    ))
    out, dropped = verify(recap, SESSION, prior, sid)
    assert [(x.name, x.notes) for x in out.state.npcs] == [("Irina", ""), ("Varre", "updated")]
    assert [(t.who, t.status) for t in out.state.threads] == [("Varre", "open"), ("Irina", "done")]
    assert out.state.notable_items == ["Irina's Letter"]
    assert out.state.location == "Roundtable Hold" and out.state.current_objective == "Deliver the letter"
    assert len(dropped) == 4  # NPCs, threads, location, objective restored — items restore silently


# --- store + chain ---------------------------------------------------------


def _write_session(tmp_path, started, events):
    with SessionLog.open("eldenring", "video", data_dir=tmp_path, started=started) as log:
        for e in events:
            log.append(e)
        path = log.path
        played = events[-1].t_rel + 10 if events else 0.0
        log.close(ended=started + timedelta(seconds=played), played=played)
    return path


def test_summarize_chains_state_and_verifies(tmp_path, eldenring):
    first = _write_session(tmp_path, datetime(2026, 9, 15, 20, 0), SESSION)
    second = _write_session(tmp_path, datetime(2026, 9, 16, 22, 0), SESSION)
    sid1, sid2 = first.stem, second.stem

    fake = FakeProvider(_recap(
        summary="You met Miriel.",
        state=PlaythroughState(location="Liurnia of the Lakes", npcs=[NpcState(name="Miriel", evidence=[f"{sid1}#1"])]),
    ))
    rec1 = summarize_session(first, eldenring, fake)
    assert recap_path(first).exists() and rec1.dropped == []
    assert "Session id: " + sid1 in fake.calls[0][1]
    assert '"npcs": []' in fake.calls[0][1]  # no previous state

    assert previous_state(second).npcs[0].name == "Miriel"
    # Second session carries Miriel forward by the old reference and cites nothing new.
    fake2 = FakeProvider(_recap(
        summary="Back again.",
        state=PlaythroughState(npcs=[NpcState(name="Miriel", evidence=[f"{sid1}#1"]),
                                     NpcState(name="Miriel", evidence=[f"{sid1}#77"])]),
    ))
    rec2 = summarize_session(second, eldenring, fake2)
    assert "Miriel" in fake2.calls[0][1]  # previous state was passed in
    assert [x.evidence for x in rec2.recap.state.npcs] == [[f"{sid1}#1"]]
    assert len(rec2.dropped) == 3  # the invented old reference, the empty entry, the restored location
    assert rec2.recap.state.location == "Liurnia of the Lakes"  # carried from the first session

    path, latest = latest_record("eldenring", tmp_path)
    assert latest.session == sid2 and read_record(path).recap.summary == "Back again."
    assert previous_state(first).npcs == []  # nothing older than the first session


# --- gap -------------------------------------------------------------------


def test_gap_tiers_and_render(tmp_path, eldenring):
    ended = datetime(2026, 9, 16, 22, 12)
    assert pick_tier(ended, ended + timedelta(hours=20)) == "one_line"
    assert pick_tier(ended, ended + timedelta(days=3)) == "short"
    assert pick_tier(ended, ended + timedelta(days=20)) == "full"

    path = _write_session(tmp_path, datetime(2026, 9, 16, 22, 0), SESSION)
    record = summarize_session(path, eldenring, FakeProvider(_recap(short_recap="SHORT TEXT", full_recap="FULL TEXT")))
    one = render(record, path, "one_line", ended + timedelta(hours=3))
    assert one == "Last session, earlier today: 11m · 2 deaths · Glintstone Dragon Adula still standing"
    short = render(record, path, "short", ended + timedelta(days=4))
    assert short.startswith("Last played 4 days ago (16 Sep 2026, 11m).") and short.endswith("SHORT TEXT")
    assert "FULL TEXT" in render(record, path, "full", ended + timedelta(days=30))
    assert "4 weeks ago" in render(record, path, "full", ended + timedelta(days=30))


# --- index -----------------------------------------------------------------


def test_index_search_items_bosses_and_npcs(tmp_path, eldenring):
    path = _write_session(tmp_path, datetime(2026, 9, 16, 22, 0), SESSION)
    summarize_session(path, eldenring, FakeProvider(_recap(conversations=[
        Conversation(speaker="Miriel", speaker_basis="named", location="Church of Vows", events=[0, 1, 2], gist="welcomed you"),
        Conversation(speaker="Rennala", speaker_basis="inferred", events=[13], gist="hush"),
        Conversation(speaker="Enia", speaker_basis="named", events=[13], gist="fingers"),
    ])))
    idx = index_mod.build("eldenring", tmp_path)
    assert [e.name for e in index_mod.search(idx, "malenia")] == []  # Enia is inside "malenia"; not a hit

    bones = index_mod.search(idx, "thin beast bones")
    assert len(bones) == 3 and bones[0].location == "Liurnia of the Lakes"
    seed = index_mod.search(idx, "golden seed")
    assert [e.location for e in seed] == [None]  # before any area banner
    assert index_mod.search(idx, "ThinBeastBones")  # OCR-glued spelling still finds it

    wolf = index_mod.search(idx, "red wolf", kinds={"boss"})
    assert len(wolf) == 1 and wolf[0].detail == "felled in 2 tries" and wolf[0].t_rel == 200
    adula = index_mod.search(idx, "adula")[0]
    assert adula.detail == "1 death, still standing" and adula.location == "Liurnia of the Lakes"

    miriel = index_mod.search(idx, "miriel")
    assert len(miriel) == 1 and miriel[0].kind == "npc" and miriel[0].t_rel == 2 and miriel[0].location == "Church of Vows"
    assert index_mod.search(idx, "rennala")[0].detail == "hush (inferred)"
    assert index_mod.search(idx, "zzz") == []
    assert "Thin Beast Bones @ Liurnia of the Lakes" in index_mod.format_hits(bones)


# --- cli -------------------------------------------------------------------


def test_cli_recap_and_search_offline(tmp_path, eldenring, capsys, monkeypatch):
    path = _write_session(tmp_path, datetime(2026, 9, 16, 22, 0), SESSION)
    summarize_session(path, eldenring, FakeProvider(_recap(full_recap="THE WHOLE STORY")))

    assert main(["recap", "--data-dir", str(tmp_path), "--as-of", "2026-10-20"]) == 0
    assert "THE WHOLE STORY" in capsys.readouterr().out
    assert main(["recap", "--data-dir", str(tmp_path), "--as-of", "2026-09-17"]) == 0
    out = capsys.readouterr().out
    assert "still standing" in out and "THE WHOLE STORY" not in out

    assert main(["search", "seed", "--data-dir", str(tmp_path)]) == 0
    assert "Golden Seed" in capsys.readouterr().out
    assert main(["search", "nothing-here", "--data-dir", str(tmp_path)]) == 1

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-profiles"))  # no `ant auth login` profile either
    assert main(["summarize", str(path)]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert main(["summarize", "--model", "claude-haiku-4-5", str(path)]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_cli_recap_without_records(tmp_path, capsys):
    assert main(["recap", "--data-dir", str(tmp_path)]) == 1
    assert "no recap yet" in capsys.readouterr().err
