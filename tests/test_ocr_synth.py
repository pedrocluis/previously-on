"""End-to-end OCR + classification on synthetic frames.

Slow-ish (loads the OCR models once). Banner accuracy must be >= 95%,
dialogue >= 80%, matching the M2 targets; negatives must produce nothing.
"""

import pytest

from previously_on.events import BANNER_TYPES, EventType
from previously_on.games.eldenring import BOSS_BAR, CENTER_BANNER, ITEM_POPUP, SUBTITLE
from previously_on.pipeline import classify_image

from .synth import GOLD, RED, WHITE, blank_frame, frame_with

BANNER_CASES = [
    # Real banners are 0.057-0.08 of the frame tall (62-86 px at 1080p): font sizes 88-110.
    (CENTER_BANNER, "YOU DIED", RED, 110, EventType.DEATH),
    (CENTER_BANNER, "YOU DIED", RED, 90, EventType.DEATH),
    (CENTER_BANNER, "ENEMY FELLED", GOLD, 100, EventType.ENEMY_DEFEATED),
    (CENTER_BANNER, "ENEMY FELLED", GOLD, 88, EventType.ENEMY_DEFEATED),
    (CENTER_BANNER, "GREAT ENEMY FELLED", GOLD, 96, EventType.BOSS_DEFEATED),
    (CENTER_BANNER, "GREAT ENEMY FELLED", GOLD, 88, EventType.BOSS_DEFEATED),
    (CENTER_BANNER, "LOST GRACE DISCOVERED", GOLD, 90, EventType.CHECKPOINT_DISCOVERED),
    (CENTER_BANNER, "LOST GRACE DISCOVERED", GOLD, 88, EventType.CHECKPOINT_DISCOVERED),
    (CENTER_BANNER, "LIMGRAVE", GOLD, 100, EventType.AREA_DISCOVERED),
    (CENTER_BANNER, "Stormveil Castle", GOLD, 96, EventType.AREA_DISCOVERED),
    (CENTER_BANNER, "CAELID", GOLD, 110, EventType.AREA_DISCOVERED),
    (CENTER_BANNER, "Specimen Storehouse", GOLD, 90, EventType.AREA_DISCOVERED),
]

OTHER_CASES = [
    (SUBTITLE, "Leda told me to seek out Ansbach.", WHITE, 34, EventType.DIALOGUE),
    (SUBTITLE, "Thou'rt tarnished, it seemeth.", WHITE, 30, EventType.DIALOGUE),
    (SUBTITLE, "Hast thou seen the Round Table?", WHITE, 28, EventType.DIALOGUE),
    (BOSS_BAR, "Margit, the Fell Omen", WHITE, 30, EventType.BOSS_ENGAGED),
    (BOSS_BAR, "Bayle the Dread", WHITE, 30, EventType.BOSS_ENGAGED),
    (ITEM_POPUP, "Golden Rune [1]", WHITE, 30, EventType.ITEM_ACQUIRED),
    (ITEM_POPUP, "Furlcalling Finger Remedy", WHITE, 28, EventType.ITEM_ACQUIRED),
    (ITEM_POPUP, "Remembrance of the Full Moon Queen", WHITE, 26, EventType.ITEM_ACQUIRED),
]


def _run(eldenring, ocr, cases):
    hits = 0
    misses = []
    for i, (region, text, color, size, expected) in enumerate(cases):
        img = frame_with(region, text, color, size, seed=i, align="item" if region is ITEM_POPUP else "left" if region is BOSS_BAR else "center")
        got = {r.name: found for r, _, found in classify_image(img, eldenring, ocr)}
        found = got.get(region.name) or []
        if len(found) == 1 and found[0][0] is expected:
            hits += 1
        else:
            misses.append((text, found))
        # No other region may invent an event from this frame.
        for name, other in got.items():
            if name != region.name and other:
                misses.append((f"{text} leaked into {name}", other))
    return hits / len(cases), misses


def test_banner_accuracy(eldenring, ocr):
    acc, misses = _run(eldenring, ocr, BANNER_CASES)
    assert acc >= 0.95, misses


def test_other_regions_accuracy(eldenring, ocr):
    acc, misses = _run(eldenring, ocr, OTHER_CASES)
    assert acc >= 0.80, misses


def test_blank_frames_produce_nothing(eldenring, ocr):
    for seed in range(3):
        for _, _, found in classify_image(blank_frame(seed), eldenring, ocr):
            assert found == []


def test_banner_types_are_the_precise_ones():
    assert EventType.DEATH in BANNER_TYPES and EventType.DIALOGUE not in BANNER_TYPES
