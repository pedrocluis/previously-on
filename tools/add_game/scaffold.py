#!/usr/bin/env python3
"""Scaffold a new game: profile module, registry entry, fixture folder, tests.

    scaffold.py <id> --name "Display Name" --process game.exe [--process other.exe]
                [--aspect 16:9] [--regions center_banner,subtitle,boss_bar,item_popup]
                [--root REPO]

Writes src/previously_on/games/<id>.py (every unmeasured value marked TODO),
registers it in games/__init__.py, creates tests/fixtures/<id>/ with a README
and an empty labels.yaml, and tests/test_classify_<id>.py. Refuses to
overwrite anything.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWN_REGIONS = ("center_banner", "subtitle", "boss_bar", "item_popup")

# Placeholder geometry: valid for Region.__post_init__, obviously wrong on
# screen. Elden Ring's numbers are in the comment as a hint of what to expect
# on a 16:9 action game.
REGION_DEFS = {
    "center_banner": (
        "# Centre banners (deaths, checkpoints, area reveals). Elden Ring: x=0.18, y=0.43, w=0.64, h=0.14.\n"
        'CENTER_BANNER = Region("center_banner", x=0.2, y=0.4, w=0.6, h=0.2)  # TODO measure'
    ),
    "subtitle": (
        "# Subtitles / NPC lines, usually a strip near the bottom. Elden Ring: x=0.15, y=0.86, w=0.70, h=0.07.\n"
        'SUBTITLE = Region("subtitle", x=0.15, y=0.85, w=0.7, h=0.1)  # TODO measure'
    ),
    "boss_bar": (
        "# Boss name above its HP bar; the strip must stop above the bar (its fill changes every hit).\n"
        "# Elden Ring: name x=0.22, y=0.765, w=0.50, h=0.038; bar x=0.25, y=0.795, w=0.50, h=0.03.\n"
        'BOSS_BAR = Region("boss_bar", x=0.2, y=0.75, w=0.5, h=0.05)  # TODO measure\n'
        "# The bar itself: a pixel check on its border validates a boss name.\n"
        'BOSS_HP_BAR = Region("boss_hp_bar", x=0.25, y=0.8, w=0.5, h=0.03)  # TODO measure'
    ),
    "item_popup": (
        "# Item pickups; names may stack. Elden Ring: x=0.64, y=0.63, w=0.35, h=0.195.\n"
        'ITEM_POPUP = Region("item_popup", x=0.6, y=0.6, w=0.4, h=0.2)  # TODO measure'
    ),
}
REGION_CONST = {"center_banner": "CENTER_BANNER", "subtitle": "SUBTITLE", "boss_bar": "BOSS_BAR", "item_popup": "ITEM_POPUP"}
QUIET = {"center_banner": 3.0, "subtitle": 1.5, "boss_bar": 30.0, "item_popup": 1.5}
MIN_CONF = {"center_banner": 0.85, "subtitle": 0.60, "boss_bar": 0.80, "item_popup": 0.80}

HANDLERS = {
    "center_banner": '''
    def _center_banner(self, lines: list[OcrLine], frame: np.ndarray | None) -> tuple[EventType, str, float] | None:
        confident = [l for l in lines if l.conf >= 0.6]
        if len(confident) > MAX_BANNER_LINES:
            return None  # a menu full of labels, not a banner
        rows = join_rows(
            [
                l
                for l in confident
                if re.search(r"[A-Za-z]", l.text) and not (l.width < FLOURISH_MAX_WIDTH and len(l.text) <= 3)
            ]
        )
        tall = [
            l
            for l in rows
            if l.height * CENTER_BANNER.h >= MIN_BANNER_HEIGHT
            and abs((l.x0 + l.x1) / 2 - 0.5) <= BANNER_CENTER_TOLERANCE
        ]
        if not tall:
            return None
        joined = " ".join(l.text for l in tall)
        conf = min(l.conf for l in tall)
        hit = match_vocab(joined, BANNER_VOCAB)
        if hit is not None:
            typ, score, phrase = hit
            # Store the canonical phrase, not the OCR output.
            return typ, phrase, min(conf, score / 100.0)
        norm = normalize(joined)
        if any(fuzz.partial_ratio(norm, normalize(v)) >= BANNER_PARTIAL_REJECT for v in BANNER_VOCAB):
            return None
        # TODO Other tall centred text may be an area reveal. Off until a
        # fixture shows one; then set AREA_BANNERS = True and add the game's
        # stoplist (splash screens, notices) from the survey.
        if (
            AREA_BANNERS
            and conf >= self.MIN_CONF[CENTER_BANNER.name]
            and 1 <= word_count(norm) <= 5
            and len(norm) >= 4
            and norm.replace(" ", "") not in _BANNER_STOPLIST_NOSPACE
            and not _HAS_DIGIT.search(joined)
            and _LATIN_WORD.search(joined)
        ):
            return EventType.AREA_DISCOVERED, title_case(joined) if joined.isupper() else joined, conf
        return None
''',
    "subtitle": '''
    def _subtitle(self, lines: list[OcrLine], frame: np.ndarray | None) -> tuple[EventType, str, float] | None:
        lines = [l for l in lines if re.search(r"[A-Za-z]", l.text)] or lines
        # A weak box next to a clear line is OCR garbage, not speech.
        strong = [l for l in lines if l.conf >= 0.8]
        if strong and len(strong) < len(lines):
            lines = strong
        text = " ".join(l.text for l in lines).strip()
        conf = min(l.conf for l in lines)
        if conf < self.MIN_CONF[SUBTITLE.name] or word_count(text) < 3 or not _LATIN_WORD.search(text):
            return None
        # Subtitles are sentences: they end in punctuation. Labels don't.
        if text[-1] not in _SENTENCE_END:
            return None
        if normalize(text) in PROMPT_STOPLIST or match_vocab(text, BANNER_VOCAB) is not None:
            return None
        return EventType.DIALOGUE, text, conf
''',
    "boss_bar": '''
    def _boss_bar(self, lines: list[OcrLine], frame: np.ndarray | None) -> tuple[EventType, str, float] | None:
        # Names only: the HP number may share the strip.
        named = join_rows([l for l in lines if any(c.isalpha() for c in l.text)])
        named = [l for l in named if l.x0 <= BOSS_NAME_MAX_X0]
        if not named:
            return None
        best = max(named, key=lambda l: l.conf)
        text = best.text.strip()
        if best.conf < self.MIN_CONF[BOSS_BAR.name] or not 1 <= word_count(text) <= 7:
            return None
        # Sentences that stray into the strip end in punctuation or carry digits.
        if text[-1] in ".!?;:" or _HAS_DIGIT.search(text) or not _LATIN_WORD.search(text):
            return None
        if match_vocab(text, BANNER_VOCAB) is not None:
            return None
        # A name without the bar under it is a menu label or a tooltip.
        if frame is None or not has_boss_hp_bar(frame):
            return None
        return EventType.BOSS_ENGAGED, text, best.conf
''',
    "item_popup": '''
    def _item_popup(self, lines: list[OcrLine], frame: np.ndarray | None) -> list[tuple[EventType, str, float]]:
        events: list[tuple[EventType, str, float]] = []
        for row in join_rows([l for l in lines if normalize(l.text) not in ITEM_STOPLIST]):
            text = _COUNT_SUFFIX.sub("", row.text.strip())
            if row.conf < self.MIN_CONF[ITEM_POPUP.name]:
                continue
            # TODO Item names are usually aligned against a count column;
            # measure the edge on a fixture and reject rows that miss it
            # (Elden Ring: right edge within 0.64..0.78 of the crop).
            if ITEM_RIGHT_EDGE is None or not ITEM_RIGHT_EDGE[0] <= row.x1 <= ITEM_RIGHT_EDGE[1]:
                continue
            if not 1 <= word_count(text) <= 6 or not _LATIN_WORD.search(text) or _HAS_DIGIT.search(text):
                continue
            events.append((EventType.ITEM_ACQUIRED, text, row.conf))
        return events
''',
}
GENERIC_HANDLER = '''
    def _{name}(self, lines: list[OcrLine], frame: np.ndarray | None) -> tuple[EventType, str, float] | None:
        # TODO no rule yet: rejects everything until a fixture shows what this region carries.
        return None
'''

EXTRA = {
    "boss_bar": '''
# The boss name is left-aligned at the bar's edge; tooltips that drift into
# the strip start further right. Fraction of the crop.
BOSS_NAME_MAX_X0 = 0.15  # TODO confirm on a fixture


def has_boss_hp_bar(frame: np.ndarray, min_row_fraction: float = 0.6, bar: Region = BOSS_HP_BAR) -> bool:
    """True when the boss HP bar's border line spans the bar strip.

    TODO measure on real frames: Elden Ring's bar has a light-grey border
    (V > 100, S < 90) covering >= 0.95 of a row when drawn, <= 0.15 otherwise.
    Another game's bar may need a different colour test.
    """
    strip = crop(frame, bar)
    if strip.size == 0:
        return False
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    line = (hsv[:, :, 2] > 100) & (hsv[:, :, 1] < 90)
    return float(line.mean(axis=1).max()) >= min_row_fraction

''',
    "item_popup": '''
# "x4" glued to a name, and where names end (fraction of the crop).
_COUNT_SUFFIX = re.compile(r"\\s*[xX×]\\s*\\d+\\s*$")
# TODO measure on a fixture; None rejects every row until then.
ITEM_RIGHT_EDGE: tuple[float, float] | None = None
''',
}


def class_name(game_id: str) -> str:
    return "".join(p.capitalize() for p in re.split(r"[^a-z0-9]+", game_id) if p) + "Profile"


def render(game_id: str, name: str, processes: list[str], aspect: tuple[int, int], regions: list[str]) -> str:
    tpl = (HERE / "template_profile.py").read_text(encoding="utf-8")
    region_defs = "\n".join(REGION_DEFS.get(r, f'{r.upper()} = Region("{r}", x=0.0, y=0.0, w=1.0, h=1.0)  # TODO measure') for r in regions)
    consts = [REGION_CONST.get(r, r.upper()) for r in regions]
    handler_map = "\n".join(f"            {c}.name: self._{r}," for r, c in zip(regions, consts))
    handlers = "".join(HANDLERS.get(r, GENERIC_HANDLER.format(name=r)) for r in regions)
    extra = "".join(EXTRA[r] for r in regions if r in EXTRA)
    quiet = ", ".join(f"{c}.name: {QUIET.get(r, 1.5)}" for r, c in zip(regions, consts))
    min_conf = ", ".join(f"{c}.name: {MIN_CONF.get(r, 0.85)}" for r, c in zip(regions, consts))
    out = (
        tpl.replace("{{region_defs}}", region_defs + "\n" + ("AREA_BANNERS = False  # TODO see _center_banner\n" if "center_banner" in regions else "") + extra)
        .replace("{{region_list}}", ", ".join(consts))
        .replace("{{handler_map}}", handler_map)
        .replace("{{handlers}}", handlers)
        .replace("{{quiet_after_event}}", quiet)
        .replace("{{min_conf}}", min_conf)
        .replace("{{class_name}}", class_name(game_id))
        .replace("{{id}}", game_id)
        .replace("{{display_name}}", name)
        .replace("{{process_names}}", ", ".join(repr(p) for p in processes))
        .replace("{{aspect_w}}", str(aspect[0]))
        .replace("{{aspect_h}}", str(aspect[1]))
    )
    if "boss_bar" in regions:
        out = out.replace("from ..regions import Region\n", "from ..regions import Region, crop\n").replace(
            "import numpy as np\n", "import cv2\nimport numpy as np\n"
        )
    if "center_banner" in regions:
        out = out.replace("import numpy as np\n", "import numpy as np\nfrom rapidfuzz import fuzz\n")
    assert "{{" not in out, "unfilled placeholder"
    return out


def register(init_py: Path, game_id: str, cls: str) -> None:
    src = init_py.read_text(encoding="utf-8")
    import_line = "    from .eldenring import EldenRingProfile\n"
    if import_line not in src:
        raise SystemExit(f"{init_py}: could not find the profile import to extend")
    src = src.replace(import_line, import_line + f"    from .{game_id} import {cls}\n")
    m = re.search(r"return \{p\.id: p for p in \((.*?),?\)\}", src)
    if not m:
        raise SystemExit(f"{init_py}: could not find the _profiles() tuple to extend")
    src = src[: m.start(1)] + m.group(1).rstrip(",") + f", {cls}()" + src[m.end(1):]
    init_py.write_text(src, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("id", help="lowercase slug: module name, fixture folder, --game value")
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--process", action="append", required=True, help="Windows executable name; repeatable")
    p.add_argument("--aspect", default="16:9")
    p.add_argument("--regions", default=",".join(KNOWN_REGIONS), help=f"comma-separated; known: {', '.join(KNOWN_REGIONS)}")
    p.add_argument("--root", type=Path, default=HERE.parents[1], help="repository root")
    args = p.parse_args(argv)

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.id):
        print("id must be a lowercase identifier (a-z, 0-9, _)", file=sys.stderr)
        return 2
    aw, ah = (int(v) for v in args.aspect.split(":"))
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    root = args.root
    profile_py = root / "src/previously_on/games" / f"{args.id}.py"
    init_py = root / "src/previously_on/games/__init__.py"
    fixtures = root / "tests/fixtures" / args.id
    test_py = root / "tests" / f"test_classify_{args.id}.py"
    for target in (profile_py, fixtures, test_py):
        if target.exists():
            print(f"refusing to overwrite {target}", file=sys.stderr)
            return 1

    cls = class_name(args.id)
    profile_py.write_text(render(args.id, args.name, args.process, (aw, ah), regions), encoding="utf-8")
    register(init_py, args.id, cls)
    fixtures.mkdir(parents=True)
    readme = (HERE / "template_fixture_readme.md").read_text(encoding="utf-8")
    (fixtures / "README.md").write_text(readme.replace("{{display_name}}", args.name).replace("{{id}}", args.id), encoding="utf-8")
    (fixtures / "labels.yaml").write_text(
        f"# {args.name} regression frames. Empty until real frames are cut and labelled;\n"
        "# test_regression.py skips an empty file. Format: see README.md.\n",
        encoding="utf-8",
    )
    test_src = (HERE / "template_test.py").read_text(encoding="utf-8")
    test_py.write_text(test_src.replace("{{id}}", args.id).replace("{{display_name}}", args.name), encoding="utf-8")

    rel = lambda p: p.relative_to(root)  # noqa: E731
    print(f"wrote {rel(profile_py)}, {rel(fixtures)}/, {rel(test_py)}; registered {cls} in {rel(init_py)}")
    print("next:")
    print(f"  1. grep -n TODO {rel(profile_py)}   # every one is a measurement to make")
    print(f"  2. uv run previously-on calibrate --game {args.id} frame.jpg   # crops must contain exactly the text")
    print(f"  3. cut 30+ frames into {rel(fixtures)}/ and label them (README.md); >= 6 negatives")
    print("  4. uv run pytest tests/test_regression.py -s   # banners >= 95 %, dialogue >= 80 %, negatives 100 %")
    print(f"  5. uv run python -m tests.reads {args.id}   # record the reads; commit reads.json, not the frames")
    print(f"  6. recap_notes in {rel(profile_py)}, then summarize --game {args.id} one log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
