"""Generic text-classification helpers composed by game profiles."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .events import EventType
from .ocr import OcrLine

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


def word_count(text: str) -> int:
    return len(text.split())


def is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def match_vocab(
    text: str, vocab: dict[str, EventType], threshold: float = 85.0
) -> tuple[EventType, float, str] | None:
    """Fuzzy-match ``text`` against fixed phrases.

    Longer phrases are tried first so "GREAT ENEMY FELLED" is never swallowed
    by its suffix "ENEMY FELLED". Returns the type, the match score and the
    phrase that matched.
    """
    norm = normalize(text)
    if not norm:
        return None
    # The games' letter-spaced banner fonts make OCR drop word spaces
    # ("LOSTGRACEDISCOVERED"), so also compare with all spaces removed.
    squashed = norm.replace(" ", "")
    best: tuple[EventType, float, str] | None = None
    for phrase in sorted(vocab, key=len, reverse=True):
        target = normalize(phrase)
        score = max(fuzz.ratio(norm, target), fuzz.ratio(squashed, target.replace(" ", "")))
        if score >= threshold and (best is None or score > best[1]):
            best = (vocab[phrase], score, phrase)
        if best is not None and best[1] >= 99.0:
            break
    return best


# A credits row of names and job titles that OCR read as one centred line:
# six words or more, at least 90 % of them capitalised. Across the dialogue
# of four finished runs (Sekiro, the three Dark Souls) the most capitalised
# real line is 0.86 ("Consume 4 Prayer Beads to Enhance Physical
# Attributes?", a Sekiro confirmation box) and the most capitalised
# subtitle 0.83 ("The Senpou Temple on Mount Kongo..."); staff rows from
# the Dark Souls III and Sekiro credits are 1.0 ("Senior Analyst Daniel Pak
# Specialist Alana Sherer…!", "Jianhui Wang Qingmei Zhao Vana Hh.").
NAME_ROW_MIN_WORDS = 6
NAME_ROW_CAPITALISED = 0.9
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def is_name_row(text: str) -> bool:
    words = _WORD.findall(text)
    return len(words) >= NAME_ROW_MIN_WORDS and sum(w[0].isupper() for w in words) >= NAME_ROW_CAPITALISED * len(words)


def title_case(text: str) -> str:
    """Render an all-caps banner as a readable name ("LIMGRAVE" -> "Limgrave")."""
    small = {"OF", "THE", "AND", "OR", "IN", "AT", "ON", "TO", "A", "AN"}
    words = text.split()
    out = []
    for i, w in enumerate(words):
        wu = w.upper()
        out.append(w.capitalize() if (i == 0 or wu not in small) else w.lower())
    return " ".join(out)


def join_rows(lines: list[OcrLine], tolerance: float = 0.6) -> list[OcrLine]:
    """Merge boxes that sit on the same text row into one line, left to right.

    The detector often splits a single HUD line into several boxes
    ("Furlcalling" / "Finger Remedy"); classification wants the whole row.
    Two boxes share a row when their vertical centres are within
    ``tolerance`` × the taller box's height.
    """
    rows: list[list[OcrLine]] = []
    for line in sorted(lines, key=lambda l: (l.y0 + l.y1) / 2):
        cy = (line.y0 + line.y1) / 2
        for row in rows:
            rcy = sum((r.y0 + r.y1) / 2 for r in row) / len(row)
            rh = max(r.height for r in row)
            if abs(cy - rcy) <= tolerance * max(line.height, rh):
                row.append(line)
                break
        else:
            rows.append([line])
    merged: list[OcrLine] = []
    for row in rows:
        row.sort(key=lambda l: l.x0)
        merged.append(
            OcrLine(
                text=" ".join(l.text for l in row),
                conf=min(l.conf for l in row),
                x0=min(l.x0 for l in row),
                y0=min(l.y0 for l in row),
                x1=max(l.x1 for l in row),
                y1=max(l.y1 for l in row),
            )
        )
    return merged


# OCR on the games' UI fonts drops spaces: "BallistaBolt",
# "RemembranceoftheGrafted" (Elden Ring), "SoulofanUnknownTraveler" and
# "DemonfromBelow" (Dark Souls III). Every rule below came from a real
# read; the exclusions are real names that a looser rule split.
_CAMEL = re.compile(r"(?<=[a-z\]\)])(?=[A-Z\[])")
_SMALL_WORDS = ("of", "the", "and", "for", "from", "an", "a")
# A run of small words glued between two words. Not after "pro":
# "LightningproofDried Liver" ends in a real "-proof". "a"/"an" only at
# the end of a run that starts with a longer small word ("Soulofan
# Unknown Traveler"): "HumanPine Resin" and "TitanShard" must not lose
# their tails.
_GLUED_SMALL = re.compile(r"(?<=[a-z])(?<!pro)((?:of|the|and|for|from)+(?:an?)?)(?=[A-Z])")
# "of"/"from" glued to the end of a token before a space ("Flaskof Crimson",
# "Chapelof Anticipation", "Blessingof the Erdtree", "Letterfrom Volcano
# Manor"; "Braille Divine Tomeof Carim" in Dark Souls III). Not
# "the"/"and": too many real words end that way ("Scythe", "Highland
# Axe"). Four letters must precede it ("Hoof", "Roof"), the first of
# which may be the capital ("Tomeof"), and not "pro": "Holyproof Pickled
# Liver" is real, and not after "ho": "Horsehoof Ring" is a Dark Souls III
# ring that OCR read correctly (chunk 05 t 2421) and this rule split.
# "a"/"an" may follow ("Cindersofa Lord", Dark Souls III).
_GLUED_SMALL_TAIL = re.compile(r"(?<=[A-Za-z][a-z]{3})(?<!pro)(?<!ho)((?:of|from)(?:an?)?)(?=\s)")
# An apostrophe glued to the next word, which OCR does on the item font
# ("Patches'Ashes", chunk 05 t 2418). Only before a capital: "Jailbreaker's
# Key" and "Knight's Crossbow" keep their "'s". Two letters must precede
# the apostrophe: Sekiro has a boss called "O'Rin of the Water" (chunk 04
# t 2937) and a one-letter head is never a possessive.
_GLUED_APOSTROPHE = re.compile(r"(?<=[A-Za-z]{2}')(?=[A-Z])")
# Two or more small words glued to the end of a token ("Remembranceofthe
# Grafted") are unambiguous: no real word ends that way.
_GLUED_SMALL_RUN_TAIL = re.compile(r"(?<=[a-z]{4})((?:of|the|and|for|from){2,}(?:an?)?)(?=\s[A-Z])")
# "Map:Limgrave,West", "AshofWar:RepeatingThrust": the UI font's punctuation
# loses its trailing space too.
_GLUED_PUNCT = re.compile(r"([:,])(?=\S)")
# A whole token made of two or more small words ("Remembrance ofthe Grafted").
_SMALL_RUN = re.compile(r"(?<![A-Za-z])((?:of|the|and|for|from){2,}(?:an?)?)(?![A-Za-z])")


def respace(text: str) -> str:
    """Restore spaces OCR dropped: "RemembranceoftheGrafted" -> "Remembrance of the Grafted"."""

    def split_small(m: re.Match) -> str:
        run, words = m.group(1), []
        while run:
            w = next(w for w in _SMALL_WORDS if run.startswith(w))
            words.append(w)
            run = run[len(w) :]
        return " " + " ".join(words) + " "

    text = _GLUED_SMALL.sub(split_small, text)
    text = _SMALL_RUN.sub(split_small, text)
    text = _GLUED_SMALL_RUN_TAIL.sub(split_small, text)
    text = _GLUED_SMALL_TAIL.sub(split_small, text)
    text = _CAMEL.sub(" ", text)
    text = _GLUED_PUNCT.sub(r"\1 ", text)
    text = _GLUED_APOSTROPHE.sub(" ", text)
    return " ".join(text.split())
