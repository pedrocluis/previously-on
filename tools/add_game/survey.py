#!/usr/bin/env python3
"""Full-frame OCR survey: where does a game put its HUD text, and what does it say?

    survey.py scan VIDEO --start S --duration D [--fps 1] --out survey.jsonl
    survey.py scan --images DIR --out survey.jsonl
    survey.py report survey.jsonl [--band 0.02] [--min-conf 0.7]
    survey.py find survey.jsonl PATTERN [--min-conf 0.8]

``scan`` OCRs every whole frame (no regions, detector at full resolution) and
writes one JSON line per text box with its bounding box as fractions of the
frame. ``report`` groups the boxes by vertical band so the banner band, the
subtitle band, the item column and the persistent HUD stand out; ``find``
lists the timestamps where a phrase was read, for cutting fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

CENTER_TOLERANCE = 0.06
MIN_BANNER_HEIGHT = 0.04  # of the frame; Elden Ring's banners are 0.055
HUD_SHARE = 0.4  # a phrase in this share of frames is HUD, not an event
_SENTENCE_END = set(".!?,;:…'\")»")


def cmd_scan(args: argparse.Namespace) -> int:
    from previously_on.ocr import Ocr

    if not args.images and not args.video:
        print("scan needs a VIDEO or --images DIR", file=sys.stderr)
        return 2
    frames = _image_frames(Path(args.images)) if args.images else _video_frames(args)
    ocr: Ocr | None = None
    out = open(args.out, "w", encoding="utf-8")
    n = 0
    for key, image in frames:
        if ocr is None:
            # The package caps the detector at 960 px for live capture; a
            # whole 1080p frame needs the full width or subtitles vanish.
            ocr = Ocr(det_max_side=max(image.shape[:2]))
        for line in ocr.read(image):
            out.write(
                json.dumps(
                    {
                        "t": key,
                        "text": line.text,
                        "conf": round(line.conf, 3),
                        "x0": round(line.x0, 4),
                        "y0": round(line.y0, 4),
                        "x1": round(line.x1, 4),
                        "y1": round(line.y1, 4),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        n += 1
        if n % 100 == 0:
            print(f"{n} frames", file=sys.stderr)
    out.close()
    print(f"{n} frames -> {args.out}", file=sys.stderr)
    return 0


def _video_frames(args: argparse.Namespace):
    from previously_on.capture.ffmpeg_source import FfmpegVideoSource

    src = FfmpegVideoSource(args.video, fps=args.fps, seek=args.start, duration=args.duration)
    for f in src.frames():
        yield round(f.t_rel, 2), f.image


def _image_frames(folder: Path):
    import cv2

    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            continue
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is not None:
            yield p.name, img


def _load(path: str, min_conf: float) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["conf"] >= min_conf:
                rows.append(r)
    return rows


def _norm(text: str) -> str:
    from previously_on.classify import normalize

    return normalize(text)


def cmd_report(args: argparse.Namespace) -> int:
    rows = _load(args.survey, args.min_conf)
    if not rows:
        print("no boxes above --min-conf")
        return 1
    frames = {r["t"] for r in rows}
    n_frames = len(frames)
    band = args.band
    bands: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        cy = (r["y0"] + r["y1"]) / 2
        bands[int(cy / band)].append(r)

    print(f"{len(rows)} boxes in {n_frames} frames with text; bands of {band:.2f} of the frame height\n")
    print(f"{'y band':>11}  {'boxes':>5}  {'frames':>6}  {'med h':>5}  {'centred':>7}  {'x0..x1':>11}  top texts")
    for b in sorted(bands):
        rs = bands[b]
        heights = [r["y1"] - r["y0"] for r in rs]
        centred = sum(1 for r in rs if abs((r["x0"] + r["x1"]) / 2 - 0.5) <= CENTER_TOLERANCE) / len(rs)
        frac = len({r["t"] for r in rs}) / n_frames
        x0 = statistics.median(r["x0"] for r in rs)
        x1 = statistics.median(r["x1"] for r in rs)
        top = Counter(_norm(r["text"]) for r in rs).most_common(5)
        texts = ", ".join(f"{t[:28]}×{c}" if c > 1 else t[:28] for t, c in top if t)
        flag = " HUD?" if frac >= HUD_SHARE else ""
        print(
            f"{b * band:5.2f}-{(b + 1) * band:4.2f}  {len(rs):5d}  {frac:6.2f}  {statistics.median(heights):5.3f}  "
            f"{centred:7.0%}  {x0:4.2f}..{x1:4.2f}  {texts}{flag}"
        )
    print("\n'frames' is the share of text-bearing frames the band appears in: ~1.00 is persistent HUD\n"
          "(keep it out of every region); 'centred' is the share of boxes centred within "
          f"{CENTER_TOLERANCE} of x=0.5.\n")

    # Tall centred boxes: banner vocabulary candidates. Banners are brief
    # (two or three frames at 1 fps), so no minimum count here.
    phrases: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = _norm(r["text"]).replace(" ", "")
        if 3 <= len(key) <= 40:
            phrases[key].append(r)

    def frame_share(rs: list[dict]) -> float:
        return len({r["t"] for r in rs}) / n_frames

    print("tall centred boxes (h >= %.2f, centred; banner vocabulary candidates):" % MIN_BANNER_HEIGHT)
    tall = {
        k: [r for r in rs if r["y1"] - r["y0"] >= MIN_BANNER_HEIGHT and abs((r["x0"] + r["x1"]) / 2 - 0.5) <= CENTER_TOLERANCE]
        for k, rs in phrases.items()
    }
    shown = 0
    for key, rs in sorted(tall.items(), key=lambda kv: -len(kv[1])):
        if not rs or frame_share(phrases[key]) >= HUD_SHARE:
            continue
        _print_phrase(rs, frame_share(rs))
        shown += 1
        if shown >= args.top:
            break
    if not shown:
        print("  (none)")

    # Recurring phrases: persistent HUD (high frame share) and repeated
    # names — boss bars, item pickups, prompts.
    print(f"\nrecurring phrases (seen >= 3 times; 'frames' >= {HUD_SHARE:.0%} is persistent HUD, keep it out of every region):")
    shown = 0
    for key, rs in sorted(phrases.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < 3:
            break
        _print_phrase(rs, frame_share(rs))
        shown += 1
        if shown >= args.top:
            break
    if not shown:
        print("  (none)")

    # Sentence-like bands: subtitle candidates.
    sentences: Counter[int] = Counter()
    for r in rows:
        t = r["text"].strip()
        if len(t.split()) >= 3 and t[-1] in _SENTENCE_END:
            sentences[int(((r["y0"] + r["y1"]) / 2) / band)] += 1
    print("\nsentence-like boxes (>= 3 words, ends in punctuation) per band:")
    for b, c in sentences.most_common(5):
        print(f"  y {b * band:.2f}-{(b + 1) * band:.2f}: {c}")
    if not sentences:
        print("  (none)")
    return 0


def _print_phrase(rs: list[dict], share: float) -> None:
    cy = statistics.median((r["y0"] + r["y1"]) / 2 for r in rs)
    h = statistics.median(r["y1"] - r["y0"] for r in rs)
    cx = statistics.median((r["x0"] + r["x1"]) / 2 for r in rs)
    raw = Counter(r["text"] for r in rs).most_common(1)[0][0]
    flag = "  HUD?" if share >= HUD_SHARE else ""
    print(f"  {len(rs):4d}×  frames={share:.2f}  y={cy:.2f} h={h:.3f} cx={cx:.2f}  {raw!r}{flag}")


def cmd_find(args: argparse.Namespace) -> int:
    pat = re.compile(args.pattern, re.IGNORECASE)
    rows = _load(args.survey, args.min_conf)
    hits = 0
    for r in rows:
        squashed = _norm(r["text"]).replace(" ", "")
        if pat.search(squashed) or pat.search(r["text"]):
            cy = (r["y0"] + r["y1"]) / 2
            print(f"{r['t']!s:>10}  y={cy:.2f} h={r['y1'] - r['y0']:.3f} x={r['x0']:.2f}..{r['x1']:.2f}  {r['conf']:.2f}  {r['text']}")
            hits += 1
    print(f"{hits} boxes", file=sys.stderr)
    return 0 if hits else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="OCR whole frames from a video slice or an image folder")
    s.add_argument("video", nargs="?", help="video file (decoded by ffmpeg)")
    s.add_argument("--images", help="folder of screenshots instead of a video")
    s.add_argument("--start", type=float, default=0.0, help="video: seconds to seek to")
    s.add_argument("--duration", type=float, help="video: seconds to survey")
    s.add_argument("--fps", type=float, default=1.0)
    s.add_argument("--out", required=True, help="JSONL output")
    s.set_defaults(func=cmd_scan)
    r = sub.add_parser("report", help="band table, recurring phrases, sentence bands")
    r.add_argument("survey")
    r.add_argument("--band", type=float, default=0.02, help="band height as a fraction of the frame")
    r.add_argument("--min-conf", type=float, default=0.7)
    r.add_argument("--top", type=int, default=25, help="recurring phrases to list")
    r.set_defaults(func=cmd_report)
    f = sub.add_parser("find", help="timestamps where a phrase was read (regex, matched space-stripped too)")
    f.add_argument("survey")
    f.add_argument("pattern")
    f.add_argument("--min-conf", type=float, default=0.8)
    f.set_defaults(func=cmd_find)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
