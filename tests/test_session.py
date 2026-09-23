from datetime import datetime

from previously_on.events import Event, EventType
from previously_on.session import SessionLog, read_session


def test_roundtrip(tmp_path):
    started = datetime(2026, 9, 15, 20, 0, 0)
    with SessionLog.open("eldenring", "images", data_dir=tmp_path, started=started) as log:
        log.append(Event(ts=started, t_rel=1.5, type=EventType.DEATH, text="YOU DIED", conf=0.97, region="center_banner", raw=["YOU DIED"], frame_index=3))
        log.append(Event(ts=started, t_rel=9.0, type=EventType.DIALOGUE, text="Ç’est la vie — “quoted”", conf=0.7, region="subtitle"))
        path = log.path
        log.close(played=7133.3)

    assert path == tmp_path / "sessions" / "eldenring" / "20260915-200000.jsonl"
    meta, events = read_session(path)
    assert meta.game == "eldenring" and meta.source == "images" and meta.ended is not None
    assert meta.duration == 7133.3  # replay: game time, not wall clock
    assert [e.type for e in events] == [EventType.DEATH, EventType.DIALOGUE]
    assert events[0].raw == ["YOU DIED"] and events[0].frame_index == 3
    assert events[1].text == "Ç’est la vie — “quoted”"


def test_partial_log_without_end_is_readable(tmp_path):
    log = SessionLog.open("eldenring", "mss", data_dir=tmp_path)
    log.append(Event(ts=datetime.now(), t_rel=0, type=EventType.DEATH, text="YOU DIED", conf=1, region="r"))
    log._fh.flush()
    meta, events = read_session(log.path)  # simulate a crash: no session_end yet
    assert meta.ended is None and len(events) == 1
    log.close()
