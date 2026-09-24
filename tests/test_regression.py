"""Regression set of real screenshots — see tests/fixtures/<game>/README.md.

Skipped until a labels.yaml and its frames exist (the frames are not in the
public repository; ``test_regression_reads.py`` runs the same set from the
reads recorded off them). Reports per-category accuracy and enforces the M2
targets: banners >= 95%, dialogue >= 80%, and no invented events on negative
frames.
"""

from __future__ import annotations

from collections import defaultdict

import cv2
import pytest

from previously_on.games import get_profile
from previously_on.pipeline import classify_image

from .regression import label_files, load_labels, score


@pytest.mark.parametrize("labels_path", label_files() or [None], ids=lambda p: p.parent.name if p else "none")
def test_real_screenshots(labels_path, ocr):
    if labels_path is None:
        pytest.skip("no tests/fixtures/<game>/labels.yaml yet — see the fixture README")
    game = labels_path.parent.name
    if not any(labels_path.parent.glob("*.jpg")):
        pytest.skip(f"no frames in {labels_path.parent} — they are not in the public repository")
    profile = get_profile(game)
    labels = load_labels(labels_path)
    if not labels:
        pytest.skip(f"{labels_path} is empty")

    def detect(entry: dict) -> dict[str, list[str]]:
        img = cv2.imread(str(labels_path.parent / entry["file"]), cv2.IMREAD_COLOR)
        assert img is not None, entry["file"]
        got: dict[str, list[str]] = defaultdict(list)
        for _, _, hits in classify_image(img, profile, ocr):
            for typ, text, _ in hits:
                got[typ.value].append(text)
        return got

    score(game, labels, detect)
