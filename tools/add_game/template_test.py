"""Classifier rules for {{display_name}} — scaffolded; grows one test per fixture-backed rule.

Each test uses the real OCR read from a frame in tests/fixtures/{{id}}/ so a
rule is never loosened from memory.
"""

from __future__ import annotations

import numpy as np
import pytest

from previously_on.events import EventType
from previously_on.games import get_profile
from previously_on.games.{{id}} import BANNER_VOCAB
from previously_on.ocr import OcrLine

BLACK = np.zeros((1080, 1920, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def profile():
    return get_profile("{{id}}")


def L(text, conf=0.95, **box):
    return [OcrLine(text, conf, **box)]


@pytest.mark.parametrize("phrase", sorted(BANNER_VOCAB) or [None])
def test_banner_vocab_round_trips(profile, phrase):
    if phrase is None:
        pytest.skip("BANNER_VOCAB is empty — fill it from the survey")
    region = next(r for r in profile.regions if r.name == "center_banner")
    # A tall, centred, confident read of the exact phrase must classify.
    hits = profile.classify(region, L(phrase, x0=0.3, x1=0.7, y0=0.2, y1=0.8), BLACK)
    assert hits and hits[0][0] is BANNER_VOCAB[phrase] and hits[0][1] == phrase


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
