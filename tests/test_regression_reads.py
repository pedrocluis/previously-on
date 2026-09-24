"""The regression set from recorded reads — runs without the fixture frames.

Each profile classifies the OCR lines recorded from every labelled frame,
its pixel checks answered from the recording (see ``tests/reads.py``), and
is scored against ``labels.yaml`` with the same targets as the frame test.
"""

from __future__ import annotations

import json

import pytest

from previously_on.games import get_profile

from .reads import READS, MissingCheck, record_frame, replay_frame, reads_path
from .regression import label_files, load_labels, score


def _games() -> list[str]:
    return [p.parent.name for p in label_files()]


@pytest.mark.parametrize("game", _games() or [None])
def test_recorded_reads(game):
    if game is None:
        pytest.skip("no tests/fixtures/<game>/labels.yaml yet")
    labels = load_labels(reads_path(game).with_name("labels.yaml"))
    if not labels:
        pytest.skip(f"{game}: labels.yaml is empty")
    path = reads_path(game)
    assert path.exists(), f"{game} has labels but no {READS}: run `python -m tests.reads {game}` where the frames are"
    reads = json.loads(path.read_text(encoding="utf-8"))
    missing = [e["file"] for e in labels if e["file"] not in reads]
    assert not missing, f"{game}: no recorded reads for {missing[:5]} — re-record with `python -m tests.reads {game}`"
    profile = get_profile(game)
    score(game, labels, lambda entry: replay_frame(reads[entry["file"]], profile))


def test_replay_matches_the_frame(ocr):
    """Recording one real frame and replaying it (through JSON) gives what the frame gives."""
    from .frames import FIXTURES, load

    img = load("eldenring", "boss_mohg_omen_raised_bar.jpg")
    profile = get_profile("eldenring")
    recorded = json.loads(json.dumps(record_frame(img, profile, ocr)))
    assert any(r["checks"] for r in recorded.values()), "the boss bar's pixel check was not recorded"
    labels = {e["file"]: e for e in load_labels(FIXTURES / "eldenring" / "labels.yaml")}
    want = {e["type"] for e in labels["boss_mohg_omen_raised_bar.jpg"]["expected"]}
    assert set(replay_frame(recorded, profile)) == want


def test_replay_refuses_a_pixel_question_it_has_no_answer_for():
    profile = get_profile("eldenring")
    recorded = {"boss_bar": {"lines": [["Margit, the Fell Omen", 0.99, 0.05, 0.1, 0.5, 0.9]], "checks": {}}}
    with pytest.raises(MissingCheck, match="has_boss_hp_bar"):
        replay_frame(recorded, profile)
    recorded["boss_bar"]["checks"] = {"has_boss_hp_bar(bar=boss_hp_bar)": True}
    assert replay_frame(recorded, profile) == {"boss_engaged": ["Margit, the Fell Omen"]}
