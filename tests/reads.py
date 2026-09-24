"""Recorded reads: the regression set without the frames.

The fixture frames are cut from other people's recordings and stay out of
the public repository, but what the classifier sees of them is text and a
handful of yes/no pixel answers. For every labelled frame this records,
per region, the OCR lines and the answer of every ``has_*`` pixel
check the profile asked while classifying them, into
``tests/fixtures/<game>/reads.json``. ``test_regression_reads.py`` then runs
each profile's ``classify`` on those lines, answering its pixel checks from
the recording, and scores the result against ``labels.yaml`` exactly as the
frame test does — so a contributor changes a rule and sees what it does to
the whole set with nothing but a clone.

Re-record (needs the frames) after adding a fixture, after changing a
region or the OCR settings, or when replay reports a pixel check it has no
answer for (a rule that asks the frame something new)::

    uv run python -m tests.reads              # every game with frames
    uv run python -m tests.reads ds3 sekiro   # just these
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from previously_on.games import GameProfile, get_profile
from previously_on.ocr import OcrLine
from previously_on.regions import Region, crop

from .regression import FIXTURES, load_labels

READS = "reads.json"


def reads_path(game: str) -> Path:
    return FIXTURES / game / READS


def _arg(v: object) -> str:
    return v.name if isinstance(v, Region) else repr(v)


def check_key(name: str, args: tuple, kwargs: dict) -> str:
    """``has_boss_hp_bar(bar=boss_hp_bar_raised)`` — the call without its frame."""
    parts = [_arg(a) for a in args[1:]] + [f"{k}={_arg(v)}" for k, v in sorted(kwargs.items())]
    return f"{name}({', '.join(parts)})"


def _checks(profile: GameProfile) -> tuple[object, dict[str, Callable]]:
    module = sys.modules[type(profile).__module__]
    return module, {n: getattr(module, n) for n in dir(module) if n.startswith("has_") and callable(getattr(module, n))}


@contextmanager
def _patched(profile: GameProfile, make: Callable[[str, Callable], Callable]) -> Iterator[None]:
    module, checks = _checks(profile)
    try:
        for name, fn in checks.items():
            setattr(module, name, make(name, fn))
        yield
    finally:
        for name, fn in checks.items():
            setattr(module, name, fn)


def _line_to_json(l: OcrLine) -> list:
    # Full precision (JSON round-trips a float exactly): rounding a box by
    # 1e-4 flipped a pixel check that locates a panel from the row's edges.
    return [l.text, float(l.conf), float(l.x0), float(l.y0), float(l.x1), float(l.y1)]


def _line_from_json(v: list) -> OcrLine:
    text, conf, x0, y0, x1, y1 = v
    return OcrLine(text, conf, x0=x0, y0=y0, x1=x1, y1=y1)


# --- recording (needs the frames) ------------------------------------------------


def record_frame(image, profile: GameProfile, ocr) -> dict:
    """{region: {"lines": [...], "checks": {call: bool}}} for every region OCR read something in."""
    out: dict = {}
    for region in profile.regions:
        lines = ocr.read(crop(image, region))
        if not lines:
            continue
        answers: dict[str, bool] = {}

        def make(name, fn):
            def check(*args, **kwargs):
                result = bool(fn(*args, **kwargs))
                answers[check_key(name, args, kwargs)] = result
                return result

            return check

        with _patched(profile, make):
            profile.classify(region, lines, image)
        out[region.name] = {"lines": [_line_to_json(l) for l in lines], "checks": answers}
    return out


def record(game: str, ocr) -> Path | None:
    import cv2

    folder = FIXTURES / game
    labels = load_labels(folder / "labels.yaml")
    if not labels or not all((folder / e["file"]).exists() for e in labels):
        return None
    profile = get_profile(game)
    frames = {}
    for entry in labels:
        img = cv2.imread(str(folder / entry["file"]), cv2.IMREAD_COLOR)
        assert img is not None, entry["file"]
        frames[entry["file"]] = record_frame(img, profile, ocr)
    path = reads_path(game)
    # One frame per line: a re-record diffs frame by frame.
    body = ",\n".join(f"  {json.dumps(name)}: {json.dumps(r, ensure_ascii=False)}" for name, r in frames.items())
    path.write_text("{\n" + body + "\n}\n", encoding="utf-8")
    return path


# --- replay (runs anywhere) --------------------------------------------------------


class NoFrame:
    """Stands in for the frame on replay: ``frame is not None`` holds, any
    pixel read outside a ``has_*`` check fails loudly."""

    def __getattr__(self, name):
        raise AssertionError(f"the profile read frame.{name} outside a has_* check; replay cannot answer that")

    def __getitem__(self, key):
        raise AssertionError("the profile indexed the frame outside a has_* check; replay cannot answer that")

    def __array__(self, *args, **kwargs):
        raise AssertionError("the profile used the frame outside a has_* check; replay cannot answer that")


class MissingCheck(LookupError):
    pass


def replay_frame(recorded: dict, profile: GameProfile) -> dict[str, list[str]]:
    """{event type: [texts]} as ``classify_image`` would have produced them."""
    got: dict[str, list[str]] = defaultdict(list)
    frame = NoFrame()
    for region in profile.regions:
        r = recorded.get(region.name)
        if not r:
            continue
        answers = r["checks"]

        def make(name, fn):
            def check(*args, **kwargs):
                key = check_key(name, args, kwargs)
                if key not in answers:
                    raise MissingCheck(
                        f"{region.name}: {key} was never asked when the reads were recorded — "
                        "a rule asks the frame something new; re-record with `python -m tests.reads` where the frames are"
                    )
                return answers[key]

            return check

        with _patched(profile, make):
            for typ, text, _ in profile.classify(region, [_line_from_json(v) for v in r["lines"]], frame):
                got[typ.value].append(text)
    return got


def main(argv: list[str]) -> int:
    from previously_on.ocr import get_ocr

    games = argv or sorted(p.parent.name for p in FIXTURES.glob("*/labels.yaml"))
    ocr = get_ocr()
    for game in games:
        path = record(game, ocr)
        print(f"{game}: {path or 'skipped (no labels, or frames missing)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
