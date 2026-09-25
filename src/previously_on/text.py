"""Text normalisation shared by the classifiers and the stats.

Dependency-free on purpose: ``stats`` and ``card`` import it, and the
website's server runs those two without the capture stack (OpenCV, numpy).
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")

# Common OCR confusions on stylised serif fonts. Applied to uppercased text
# before fuzzy matching so "Y0U DIED" and "GREAT ENEMY FELLEO" still score high.
_OCR_CONFUSIONS = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I"})


def normalize(text: str) -> str:
    """Uppercase, collapse OCR look-alikes, strip punctuation and extra spaces."""
    t = text.upper().translate(_OCR_CONFUSIONS)
    t = _NON_ALNUM.sub(" ", t)
    return _SPACES.sub(" ", t).strip()
