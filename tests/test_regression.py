"""Regression set of real screenshots — see tests/fixtures/<game>/README.md.

Skipped until a labels.yaml and its frames exist (the frames are not in the
public repository). Reports per-category accuracy and enforces the M2
targets: banners >= 95%, dialogue >= 80%, and no invented events on negative
frames.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import pytest
import yaml

from previously_on.events import BANNER_TYPES, EventType
from previously_on.games import get_profile
from previously_on.pipeline import classify_image

FIXTURES = Path(__file__).parent / "fixtures"


def _label_files() -> list[Path]:
    return sorted(FIXTURES.glob("*/labels.yaml"))


@pytest.mark.parametrize("labels_path", _label_files() or [None], ids=lambda p: p.parent.name if p else "none")
def test_real_screenshots(labels_path, ocr):
    if labels_path is None:
        pytest.skip("no tests/fixtures/<game>/labels.yaml yet — see the fixture README")
    game = labels_path.parent.name
    if not any(labels_path.parent.glob("*.jpg")):
        pytest.skip(f"no frames in {labels_path.parent} — they are not in the public repository")
    profile = get_profile(game)
    labels = yaml.safe_load(labels_path.read_text()) or []
    if not labels:
        pytest.skip(f"{labels_path} is empty")

    totals: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    problems: list[str] = []

    for entry in labels:
        img = cv2.imread(str(labels_path.parent / entry["file"]), cv2.IMREAD_COLOR)
        assert img is not None, entry["file"]
        expected = {(e["type"], e.get("text")) for e in entry.get("expected", [])}
        got: dict[str, list[str]] = defaultdict(list)
        for _, _, hits in classify_image(img, profile, ocr):
            for typ, text, _ in hits:
                got[typ.value].append(text)

        if not expected:
            totals["negative"] += 1
            if not got:
                correct["negative"] += 1
            else:
                problems.append(f"{entry['file']}: invented {got}")
            continue

        for typ, text in expected:
            cat = "banner" if EventType(typ) in BANNER_TYPES else typ
            totals[cat] += 1
            if typ in got and (text is None or text.lower() in (g.lower() for g in got[typ])):
                correct[cat] += 1
            else:
                problems.append(f"{entry['file']}: expected {typ}={text!r}, got {dict(got)}")
        for typ in got:
            if typ not in {t for t, _ in expected}:
                problems.append(f"{entry['file']}: unexpected {typ}={got[typ]!r}")

    report = "  ".join(f"{cat} {correct[cat]}/{totals[cat]}" for cat in sorted(totals))
    print(f"\n[{game}] {report}")
    for p in problems:
        print("   ", p)

    def acc(cat: str) -> float:
        return correct[cat] / totals[cat] if totals[cat] else 1.0

    assert acc("banner") >= 0.95, f"banner accuracy {acc('banner'):.0%}"
    assert acc("dialogue") >= 0.80, f"dialogue accuracy {acc('dialogue'):.0%}"
    assert acc("negative") == 1.0, "invented events on negative frames"
