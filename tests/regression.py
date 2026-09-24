"""Scoring for the regression set, shared by the two ways of running it:
on the real frames (``test_regression.py``, needs the fixture JPEGs) and on
the reads recorded from them (``test_regression_reads.py``, runs anywhere).

Targets (M2): banners >= 95 %, dialogue >= 80 %, no invented event on a
negative frame.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import yaml

from previously_on.events import BANNER_TYPES, EventType

FIXTURES = Path(__file__).parent / "fixtures"


def label_files() -> list[Path]:
    return sorted(FIXTURES.glob("*/labels.yaml"))


def load_labels(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def score(game: str, labels: list[dict], detect: Callable[[dict], dict[str, list[str]]]) -> None:
    """Run ``detect`` (label entry → {event type: [texts]}) over every entry,
    print the per-category report and assert the targets."""
    totals: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    problems: list[str] = []

    for entry in labels:
        expected = {(e["type"], e.get("text")) for e in entry.get("expected", [])}
        got = detect(entry)

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
