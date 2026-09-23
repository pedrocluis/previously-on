"""Integration: a scripted session of synthetic frames through the whole detector.

This is the M1 exit criterion in miniature — the log must contain exactly the
events the script shows, in order, with deaths attributed to the right boss.
"""

from datetime import datetime, timedelta

from previously_on.capture import Frame
from previously_on.events import EventType
from previously_on.games.eldenring import BOSS_BAR, CENTER_BANNER, ITEM_POPUP, SUBTITLE
from previously_on.pipeline import Detector
from previously_on.session import SessionLog, read_session
from previously_on.stats import compute, summary_line

from .synth import GOLD, RED, WHITE, blank_frame, frame_with

FPS = 2.0


def hold(entry, seconds):
    return [entry] * int(seconds * FPS)


# (region, text, colour, size) shown for N seconds; None = nothing on screen.
SCRIPT = (
    hold(None, 2)
    + hold((SUBTITLE, "Tarnished, seek the Roundtable Hold.", WHITE, 32), 3)
    + hold(None, 2)
    + hold((ITEM_POPUP, "Beast Horn", WHITE, 30), 2)
    + hold(None, 2)
    + hold((BOSS_BAR, "Margit, the Fell Omen", WHITE, 30), 4)
    + hold((CENTER_BANNER, "YOU DIED", RED, 110), 3)
    + hold(None, 10)  # respawn + walk back
    + hold((BOSS_BAR, "Margit, the Fell Omen", WHITE, 30), 4)
    + hold((CENTER_BANNER, "YOU DIED", RED, 110), 3)
    + hold(None, 10)
    + hold((BOSS_BAR, "Margit, the Fell Omen", WHITE, 30), 4)
    + hold((CENTER_BANNER, "GREAT ENEMY FELLED", GOLD, 96), 3)
    + hold(None, 2)
    + hold((CENTER_BANNER, "LOST GRACE DISCOVERED", GOLD, 90), 3)
    + hold(None, 2)
    + hold((CENTER_BANNER, "Liurnia of the Lakes", GOLD, 90), 3)
    + hold(None, 2)
)


class ScriptSource:
    name = "script"

    def frames(self):
        start = datetime(2026, 9, 15, 21, 0)
        for i, entry in enumerate(SCRIPT):
            if entry is None:
                img = blank_frame(i % 4)
            else:
                region, text, colour, size = entry
                img = frame_with(region, text, colour, size, seed=i % 4, align="item" if region is ITEM_POPUP else "left" if region is BOSS_BAR else "center")
            t = i / FPS
            yield Frame(index=i, ts=start + timedelta(seconds=t), t_rel=t, image=img)

    def close(self):
        pass


def test_scripted_session(tmp_path, eldenring, ocr):
    log = SessionLog.open(eldenring.id, "script", data_dir=tmp_path)
    detector = Detector(ScriptSource(), eldenring, ocr, log, on_event=lambda e: None)
    dstats = detector.run()

    _, events = read_session(log.path)
    assert [(e.type, e.text) for e in events] == [
        (EventType.DIALOGUE, "Tarnished, seek the Roundtable Hold."),
        (EventType.ITEM_ACQUIRED, "Beast Horn"),
        (EventType.BOSS_ENGAGED, "Margit, the Fell Omen"),
        (EventType.DEATH, "YOU DIED"),
        (EventType.DEATH, "YOU DIED"),
        (EventType.BOSS_DEFEATED, "GREAT ENEMY FELLED"),
        (EventType.CHECKPOINT_DISCOVERED, "LOST GRACE DISCOVERED"),
        (EventType.AREA_DISCOVERED, "Liurnia of the Lakes"),
    ]
    # Cost control: OCR ran on a small fraction of frames.
    assert dstats.ocr_calls < dstats.frames * 0.25

    s = compute(events)
    assert [(b.name, b.attempts, b.defeated) for b in s.bosses] == [("Margit, the Fell Omen", 3, True)]
    assert summary_line(s).endswith("2 deaths · Margit, the Fell Omen felled in 3 tries")
