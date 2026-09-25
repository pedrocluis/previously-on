"""The share card: a whole playthrough as one image.

``112 hours · 847 deaths · Bayle took 34 tries`` is what players post, so
the card leads with those three numbers and the fights that took the most
tries. It is drawn from the session logs alone — no model, no network,
nothing that is not already on the timeline — and the same PNG comes out
of ``previously-on card`` and the window's Timeline page.

The look is the window's: moss-black ground, bone text, the rust rule,
lichen green only for what was felled, Mona Sans across its width axis.
The font is the one the window ships (``app/ui/fonts``); FreeType reads
the woff2 and its variation axes directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from rapidfuzz import fuzz

from .text import normalize
from .session import SessionMeta, read_session, sessions_dir
from .stats import SAME_AREA, BossStat, SessionStats, across_sessions, compute, format_duration

WIDTH, HEIGHT = 1600, 900
MARGIN = 104
HARDEST = 3  # fights listed

# The window's palette (app.css), converted from oklch.
INK = "#11140e"
RAIL = "#0c0e09"
LINE = "#34372e"
TEXT = "#ebe8db"
DIM = "#b2b2a4"
FAINT = "#7a7c6f"
ACCENT = "#e07c55"
FELLED = "#b4cb8e"

SITE = "github.com/pedrocluis/previously-on"


@dataclass(slots=True)
class Playthrough:
    game: str
    sessions: int = 0
    seconds: float = 0.0
    deaths: int = 0
    fights: list[BossStat] = field(default_factory=list)  # play order, joined across sessions
    areas: list[str] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None

    @property
    def felled(self) -> list[BossStat]:
        return [f for f in self.fights if f.defeated]

    def hardest(self, n: int = HARDEST) -> list[BossStat]:
        """The felled fights with the most tries, most first; ties go to the
        earlier fight. Only fights that took more than one try."""
        ranked = sorted(self.felled, key=lambda f: -f.attempts)  # stable: play order breaks ties
        return [f for f in ranked if f.attempts > 1][:n]


def gather(game: str, data_dir: Path | None) -> Playthrough:
    directory = sessions_dir(game, data_dir)
    logs = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
    sessions = []
    for log in logs:
        meta, events = read_session(log)
        sessions.append((meta, compute(events, duration=meta.duration)))
    return gather_stats(game, sessions)


def gather_stats(game: str, sessions: list[tuple[SessionMeta, SessionStats]]) -> Playthrough:
    """The playthrough from each session's stats, in play order. The website
    caches ``SessionStats`` per synced session and totals them here, so its
    numbers and the window's are the same code."""
    p = Playthrough(game)
    fights: list[BossStat] = []
    for meta, stats in sessions:
        p.sessions += 1
        p.seconds += stats.duration
        p.deaths += stats.deaths
        fights.extend(stats.bosses)
        for area in stats.areas:
            if not any(fuzz.ratio(normalize(area), normalize(a)) >= SAME_AREA for a in p.areas):
                p.areas.append(area)
        ended = meta.ended or meta.started
        p.first = meta.started if p.first is None else min(p.first, meta.started)
        p.last = ended if p.last is None else max(p.last, ended)
    p.fights = across_sessions(fights)
    return p


def boss_json(b: BossStat) -> dict:
    return {"name": b.name, "attempts": b.attempts, "defeated": b.defeated, "phases": list(b.phases)}


def totals(p: Playthrough) -> dict:
    """``112 hours · 847 deaths · Bayle took 34 tries`` — the whole playthrough
    in one line, the share card's numbers (a fight that spans sessions counts
    every try). The window's Recap page and the website both show this."""
    hardest = p.hardest(1)
    return {
        "sessions": p.sessions,
        "seconds": p.seconds,
        "playtime": format_duration(p.seconds),
        "deaths": p.deaths,
        "bosses_felled": len(p.felled),
        "hardest": boss_json(hardest[0]) if hardest else None,
        "first": p.first.isoformat(timespec="seconds") if p.first else None,
        "last": p.last.isoformat(timespec="seconds") if p.last else None,
        "line": line(p),
    }


def playtime(seconds: float) -> tuple[str, str]:
    """The big number and its unit: ``("112", "hours")``, ``("42", "minutes")``."""
    hours = seconds / 3600
    if hours >= 1:
        n = round(hours)
        return str(n), "hour" if n == 1 else "hours"
    minutes = int(seconds // 60)
    return str(minutes), "minute" if minutes == 1 else "minutes"


def tries(n: int) -> str:
    return f"{n} {'try' if n == 1 else 'tries'}"


def line(p: Playthrough) -> str:
    """``112 hours · 847 deaths · Bayle took 34 tries`` — the card in one line."""
    if not p.sessions:
        return ""
    n, unit = playtime(p.seconds)
    parts = [f"{n} {unit}" if unit.startswith("hour") else format_duration(p.seconds)]
    parts.append(f"{p.deaths} death{'s' if p.deaths != 1 else ''}")
    hardest = p.hardest(1)
    if hardest:
        parts.append(f"{hardest[0].name} took {hardest[0].attempts} tries")
    return " · ".join(parts)


def date_span(first: datetime | None, last: datetime | None) -> str:
    """``16 – 18 Sep 2026``, ``28 Sep – 3 Oct 2026``, ``Dec 2025 – Jan 2026``-style spans."""
    if first is None or last is None:
        return ""
    if first.date() == last.date():
        return f"{first.day} {first:%b %Y}"
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day} – {last.day} {last:%b %Y}"
    if first.year == last.year:
        return f"{first.day} {first:%b} – {last.day} {last:%b %Y}"
    return f"{first.day} {first:%b %Y} – {last.day} {last:%b %Y}"


# --- drawing ----------------------------------------------------------------------


def font_path() -> Path:
    return Path(str(files("previously_on.app") / "ui" / "fonts" / "mona-sans-latin-wdth-normal.woff2"))


@lru_cache(maxsize=64)
def _font(size: int, weight: int = 400, width: int = 100):
    from PIL import ImageFont

    font = ImageFont.truetype(str(font_path()), size)
    font.set_variation_by_axes([width, weight])  # the file's axis order: wdth, wght
    return font


def _text_width(draw, text: str, font, tracking: float = 0.0) -> float:
    return draw.textlength(text, font=font) + tracking * max(len(text) - 1, 0)


def _caps(draw, xy: tuple[float, float], text: str, size: int, fill: str, weight: int = 650) -> float:
    """A label in the window's style: small, slightly wide caps, tracked out.
    Returns its width."""
    font = _font(size, weight, 112)
    tracking = size * 0.14
    x, y = xy
    for ch in text.upper():
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - tracking - xy[0]


def _fit(draw, text: str, max_width: float, size: int, min_size: int, weight: int, width: int = 100):
    """The largest font from ``size`` down to ``min_size`` that fits the
    text; below that the text is cut with an ellipsis."""
    for s in range(size, min_size - 1, -2):
        font = _font(s, weight, width)
        if _text_width(draw, text, font) <= max_width:
            return text, font
    font = _font(min_size, weight, width)
    while text and _text_width(draw, text + "…", font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…", font


def _rule(draw, x: float, y: float, length: float) -> None:
    """The window's one ornament: a short rust bar on a fading hairline."""
    steps = 48
    for i in range(steps):
        a = 1 - i / steps
        draw.line([(x + length * i / steps, y), (x + length * (i + 1) / steps, y)], fill=_mix(LINE, INK, a), width=1)
    draw.rectangle([x, y - 1, x + 48, y + 2], fill=ACCENT)


def _mix(a: str, b: str, t: float) -> str:
    """``a`` at weight ``t`` over ``b``."""
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(ca, cb))


def render(p: Playthrough, display_name: str):
    """The card as a 1600×900 RGB image (16:9 — what every feed and chat
    previews without cropping)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (WIDTH, HEIGHT), INK)
    draw = ImageDraw.Draw(img)
    x0, right = MARGIN, WIDTH - MARGIN

    # Title: "Previously on" in rust caps over the game, its subtitle below.
    _caps(draw, (x0, 92), "Previously on", 22, ACCENT)
    title, _, subtitle = display_name.partition(": ")
    text, font = _fit(draw, title, right - x0, 84, 56, 820, 125)
    draw.text((x0, 128), text, font=font, fill=TEXT)
    y = 128 + 96
    if subtitle:
        text, font = _fit(draw, subtitle, right - x0, 38, 28, 560, 112)
        draw.text((x0, y), text, font=font, fill=DIM)
        y += 52
    _rule(draw, x0, y + 22, 720)
    body = y + 86  # the top of the numbers' caps and of the fights column

    # The numbers.
    hardest = p.hardest()
    listed = hardest or p.felled[-HARDEST:][::-1]  # nobody took two tries: the latest ones felled
    split = 1000 if listed else right  # where the fights column starts
    n, unit = playtime(p.seconds)
    blocks = [(n, unit, TEXT), (str(p.deaths), "death" if p.deaths == 1 else "deaths", TEXT)]
    blocks.append((str(len(p.felled)), "boss felled" if len(p.felled) == 1 else "bosses felled", FELLED))
    gap = 64
    label_font = _font(20, 650, 112)
    size = 150
    while True:
        big = _font(size, 820, 125)
        widths = [
            max(_text_width(draw, number, big), _text_width(draw, label.upper(), label_font, 20 * 0.14))
            for number, label, _ in blocks
        ]
        if size <= 90 or sum(widths) + gap * (len(blocks) - 1) <= split - x0 - 96:
            break
        size -= 6
    baseline = body - big.getbbox("0", anchor="ls")[1]  # the digits' top sits on ``body``
    x = x0
    for (number, label, colour), w in zip(blocks, widths):
        draw.text((x, baseline), number, font=big, fill=colour, anchor="ls")
        _caps(draw, (x + 4, baseline + 28), label, 20, FAINT)
        x += w + gap

    # The fights column.
    if listed:
        _caps(draw, (split, body - 6), "Hardest fights" if hardest else "Latest felled", 20, FAINT)
        y = body + 40
        for fight in listed:
            name, font = _fit(draw, fight.name, right - split, 36, 26, 640)
            draw.text((split, y + 36), name, font=font, fill=TEXT, anchor="ls")
            said = tries(fight.attempts) if fight.attempts > 1 else "first try"
            draw.text((split, y + 74), said, font=_font(26, 560, 112), fill=FELLED, anchor="ls")
            y += 100
        draw.line([(split - 48, body - 6), (split - 48, y - 16)], fill=LINE, width=1)

    # Footer: when, how much, and where it came from.
    draw.rectangle([0, HEIGHT - 132, WIDTH, HEIGHT], fill=RAIL)
    draw.line([(0, HEIGHT - 132), (WIDTH, HEIGHT - 132)], fill=_mix(LINE, RAIL, 0.6), width=1)
    facts = [date_span(p.first, p.last), f"{p.sessions} session{'s' if p.sessions != 1 else ''}"]
    if p.areas:
        facts.append(f"{len(p.areas)} place{'s' if len(p.areas) != 1 else ''}")
    draw.text((x0, HEIGHT - 66), "  ·  ".join(f for f in facts if f), font=_font(26, 500), fill=DIM, anchor="lm")
    mark = _font(30, 820, 125)
    dots = draw.textlength("…", font=mark)
    wx = right - dots - draw.textlength("Previously on", font=mark)
    draw.text((wx, HEIGHT - 76), "Previously on", font=mark, fill=TEXT, anchor="ls")
    draw.text((right - dots, HEIGHT - 76), "…", font=mark, fill=ACCENT, anchor="ls")
    site = _font(18, 500)
    draw.text((right - draw.textlength(SITE, font=site), HEIGHT - 44), SITE, font=site, fill=FAINT, anchor="ls")
    return img


def png(p: Playthrough, display_name: str) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    render(p, display_name).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def filename(game: str, when: datetime | None = None) -> str:
    return f"previously-on-{game}-{(when or datetime.now()):%Y-%m-%d}.png"
