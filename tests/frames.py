"""Real game frames under tests/fixtures/<game>/.

The JPEGs are cut from other people's recordings and are not part of the
public repository; a test that needs one skips when it is missing.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(game: str, name: str) -> np.ndarray:
    path = FIXTURES / game / name
    if not path.exists():
        pytest.skip(f"fixture frame {game}/{name} is not present")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert img is not None, name
    return img
