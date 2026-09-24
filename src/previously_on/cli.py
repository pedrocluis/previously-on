"""Command-line entry point: ``previously-on``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .games import get_profile, list_profiles

DEFAULT_GAME = "eldenring"


def _add_game_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--game", default=DEFAULT_GAME, help=f"game profile id (default: {DEFAULT_GAME})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="previously-on", description="Passive session memory for long games.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="watch the screen (or a replay) and log events to a session file")
    _add_game_arg(run)
    run.add_argument(
        "--source",
        choices=["screen", "dxcam", "mss", "video", "images"],
        default="screen",
        help="screen = best live backend for this OS (dxcam on Windows, else mss)",
    )
    run.add_argument("--path", help="video file or image directory for replay sources")
    run.add_argument("--fps", type=float, default=2.0)
    run.add_argument("--monitor", type=int, default=1, help="mss monitor index (1 = primary)")
    run.add_argument("--start", type=float, default=0.0, help="video: start at this many seconds")
    run.add_argument("--duration", type=float, help="video: stop after this many seconds")
    run.add_argument("--out", type=Path, help="data directory (default: platform user data dir)")
    run.add_argument("--wait-for-game", action="store_true", help="start when the game process appears, stop when it exits")
    run.add_argument("-v", "--verbose", action="store_true", help="print raw OCR lines")
    run.add_argument(
        "--ocr-threads",
        type=int,
        help="CPU threads for OCR (default: 2 for live capture so the game keeps the rest; all cores for replays)",
    )
    run.add_argument(
        "--no-low-priority",
        action="store_true",
        help="live capture runs at below-normal process priority by default; disable that",
    )
    run.add_argument("--debug-frames", type=Path, metavar="DIR", help="save a downscaled frame every 30 s to DIR")
    run.add_argument("--debug-every", type=float, default=30.0, help="seconds between debug frames")
    run.add_argument(
        "--summarize",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="write the LLM recap when the session ends (default: yes for live capture, no for replays; "
        "skipped quietly when no API credentials are set)",
    )

    snap = sub.add_parser("snapshot", help="grab one frame from the screen and save it (checks that capture works)")
    _add_game_arg(snap)
    snap.add_argument("--source", choices=["screen", "dxcam", "mss"], default="screen")
    snap.add_argument("--monitor", type=int, default=1)
    snap.add_argument("--out", type=Path, default=Path("snapshot.png"))
    snap.add_argument(
        "--delay", type=float, default=10.0, help="seconds to wait before grabbing, so you can alt-tab into the game"
    )

    cal = sub.add_parser("calibrate", help="dump region crops + an overlay for a screenshot to tune coordinates")
    _add_game_arg(cal)
    cal.add_argument("screenshot", type=Path)
    cal.add_argument("--out", type=Path, default=Path("calibration"))

    ocr = sub.add_parser("ocr", help="OCR + classify every region of one image")
    _add_game_arg(ocr)
    ocr.add_argument("image", type=Path)
    ocr.add_argument("--region", help="only this region")

    st = sub.add_parser("stats", help="summarise a session log")
    st.add_argument("session", type=Path, nargs="+")

    sm = sub.add_parser("summarize", help="run the LLM recap pass over session logs (writes <stamp>.recap.json beside each)")
    _add_game_arg(sm)
    sm.add_argument("session", type=Path, nargs="+")
    sm.add_argument("--model", help="model id (default: $PREVIOUSLY_ON_MODEL or gpt-5.4-mini; claude-* goes through Anthropic)")
    sm.add_argument("--force", action="store_true", help="re-run sessions that already have a record")

    rc = sub.add_parser("recap", help="show the gap-scaled recap for the latest session (no network)")
    _add_game_arg(rc)
    rc.add_argument("--data-dir", type=Path, help="data directory (default: platform user data dir)")
    rc.add_argument("--as-of", help="pretend today is this date (YYYY-MM-DD) to see another tier")
    rc.add_argument("--tier", choices=["one_line", "short", "full"], help="force a tier")

    se = sub.add_parser("search", help="find an item, place, boss or NPC across all sessions")
    _add_game_arg(se)
    se.add_argument("query")
    se.add_argument("--data-dir", type=Path)
    se.add_argument("--kind", choices=["item", "area", "checkpoint", "boss", "npc"], action="append")

    ap = sub.add_parser("app", help="open the desktop window (resume screen, sessions, timeline) and watch for any game")
    ap.add_argument(
        "--game",
        help="watch only this game and open on it (default: every game; a replay defaults to eldenring)",
    )
    ap.add_argument("--data-dir", type=Path, help="data directory (default: platform user data dir)")
    ap.add_argument("--no-watch", action="store_true", help="only show what is logged; do not capture")
    ap.add_argument("--background", action="store_true", help="start in the tray with the window hidden (the sign-in start)")
    ap.add_argument("--no-tray", action="store_true", help="no tray icon: closing the window quits")
    ap.add_argument("--monitor", type=int, help="monitor to capture (default: from settings)")
    ap.add_argument(
        "--source",
        choices=["screen", "dxcam", "mss", "video", "images"],
        default="screen",
        help="video/images: drive the window from a replay once, without the game",
    )
    ap.add_argument("--path", help="video file or image directory for replay sources")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--start", type=float, default=0.0, help="video: start at this many seconds")
    ap.add_argument("--duration", type=float, help="video: stop after this many seconds")
    ap.add_argument("--debug", action="store_true", help="open the webview developer tools")

    sub.add_parser("games", help="list available game profiles")
    sub.add_parser("check", help="check that OCR, capture and the window work on this machine (paste it into an issue)")
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    import threading

    from .capture import open_source
    from .game_process import is_running, lower_priority, wait_until
    from .ocr import get_ocr
    from .pipeline import Detector
    from .session import SessionLog

    profile = get_profile(args.game)
    live = args.source in ("screen", "dxcam", "mss")
    if args.wait_for_game and live:
        if not is_running(profile):
            print(f"waiting for {profile.display_name}…", file=sys.stderr)
            wait_until(profile, running=True)
        print(f"{profile.display_name} detected, capturing.", file=sys.stderr)

    threads = args.ocr_threads if args.ocr_threads is not None else (2 if live else -1)
    if live and not args.no_low_priority:
        lower_priority()
    print(f"loading OCR models… ({'all cores' if threads < 0 else f'{threads} threads'})", file=sys.stderr)
    ocr = get_ocr(threads)
    source = open_source(
        args.source, args.path, fps=args.fps, monitor=args.monitor, seek=args.start, duration=args.duration
    )
    log = SessionLog.open(profile.id, source.name, data_dir=args.out)
    print(f"session log: {log.path}", file=sys.stderr)
    if live:
        print(f"capturing monitor {args.monitor} via {source.name}: {source.width}x{source.height}", file=sys.stderr)
    game_gone = threading.Event()
    detector = Detector(
        source,
        profile,
        ocr,
        log,
        verbose=args.verbose,
        debug_dir=args.debug_frames,
        debug_every=args.debug_every,
        should_stop=game_gone.is_set,
    )

    if args.wait_for_game and live:
        # Stop the capture loop when the game exits.
        def _watch() -> None:
            wait_until(profile, running=False)
            game_gone.set()

        threading.Thread(target=_watch, daemon=True).start()

    stats = detector.run()
    print(
        f"done: {stats.frames} frames, {stats.ocr_calls} OCR calls, {stats.events} events, "
        f"{stats.suppressed} duplicates suppressed → {log.path}",
        file=sys.stderr,
    )
    summarize = live if args.summarize is None else args.summarize
    if summarize:
        from .recap.store import summarize_after_run

        print("writing the recap…", file=sys.stderr)
        record, message = summarize_after_run(log.path, profile)
        print(message, file=sys.stderr)
        if record is not None:
            print(f"\n{record.recap.summary}\n")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """One frame from the live screen, plus what the detector would make of it."""
    import cv2

    from .capture import open_source
    from .capture.mss_source import list_monitors
    from .ocr import get_ocr
    from .pipeline import classify_image

    import time

    for i, m in list_monitors():
        print(f"monitor {i}: {m['width']}x{m['height']} at ({m['left']},{m['top']})")
    source = open_source(args.source, fps=1.0, monitor=args.monitor)
    if args.delay > 0:
        print(f"switch to the game now — grabbing in {args.delay:.0f} s…", flush=True)
        time.sleep(args.delay)
        # Drop the first frame: it may be the desktop-duplication frame from before the switch.
        next(source.frames())
    frame = next(source.frames())
    source.close()
    img = frame.image
    mean = float(img[::8, ::8].mean())
    cv2.imwrite(str(args.out), img)
    print(f"saved {args.out} via {source.name}: {img.shape[1]}x{img.shape[0]}, mean brightness {mean:.1f}")
    if mean < 4.0:
        print(
            "the frame is black. With --source mss that is expected for an exclusive-fullscreen game; "
            "use the default (dxcam on Windows) or check --monitor."
        )
        return 1
    profile = get_profile(args.game)
    for region, lines, hits in classify_image(img, profile, get_ocr()):
        texts = [l.text for l in lines]
        print(f"[{region.name:14s}] {texts if texts else '(no text)'}" + (f"  → {hits}" if hits else ""))
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    import cv2

    from .regions import crop

    profile = get_profile(args.game)
    image = cv2.imread(str(args.screenshot), cv2.IMREAD_COLOR)
    if image is None:
        print(f"could not read {args.screenshot}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    h, w = image.shape[:2]
    overlay = image.copy()
    for region in profile.regions:
        x0, y0, x1, y1 = region.pixel_box(w, h)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 255, 0), 2)
        cv2.putText(overlay, region.name, (x0 + 4, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite(str(args.out / f"{region.name}.png"), crop(image, region))
        print(f"{region.name:14s} x={x0:5d} y={y0:5d} w={x1 - x0:5d} h={y1 - y0:5d}")
    cv2.imwrite(str(args.out / "overlay.png"), overlay)
    print(f"wrote crops + overlay.png to {args.out}/")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    import cv2

    from .ocr import get_ocr
    from .pipeline import classify_image

    profile = get_profile(args.game)
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        print(f"could not read {args.image}", file=sys.stderr)
        return 1
    for region, lines, hits in classify_image(image, profile, get_ocr(), only_region=args.region):
        print(f"[{region.name}]")
        for line in lines:
            print(f"    {line.conf:.2f}  {line.text}")
        for typ, text, conf in hits:
            print(f"  → {typ.value}: {text!r} ({conf:.2f})")
        if not lines:
            print("    (no text)")
        elif not hits:
            print("  → rejected")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .session import read_session
    from .stats import compute, summary_line

    for path in args.session:
        meta, events = read_session(path)
        stats = compute(events, duration=meta.duration)
        print(f"{path}  [{meta.game}, {meta.started:%Y-%m-%d %H:%M}]")
        print(f"  {summary_line(stats)}")
        for boss in stats.bosses:
            status = f"felled in {boss.attempts}" if boss.defeated else f"{boss.attempts} deaths, still standing"
            print(f"    boss  {boss.name}: {status}")
        if stats.areas:
            print(f"    areas {', '.join(stats.areas)}")
        print(
            f"    {stats.checkpoints} checkpoints · {stats.items} items · {stats.dialogue_lines} dialogue lines"
            f" · {len(events)} events"
        )
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    from .recap.provider import RecapError, make_provider
    from .recap.store import recap_path, summarize_session

    profile = get_profile(args.game)
    try:
        provider = make_provider(args.model)
        if not provider.has_credentials:
            print("no API credentials: set OPENAI_API_KEY (ANTHROPIC_API_KEY for claude-* models)", file=sys.stderr)
            return 1
    except RecapError as exc:
        print(f"{exc} — set ANTHROPIC_API_KEY", file=sys.stderr)
        return 1
    # Chronological, so each session sees the state the previous one left.
    for path in sorted(args.session, key=lambda p: p.name):
        if recap_path(path).exists() and not args.force:
            print(f"{path}: already summarised (use --force)", file=sys.stderr)
            continue
        print(f"{path} → {provider.model}…", file=sys.stderr)
        try:
            record = summarize_session(path, profile, provider)
        except RecapError as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            return 1
        u = record.usage
        print(f"  {u.input_tokens} in ({u.cache_read_input_tokens} cached) / {u.output_tokens} out", file=sys.stderr)
        print(f"  {record.recap.summary}")
        for d in record.dropped:
            print(f"  dropped: {d}", file=sys.stderr)
    return 0


def cmd_recap(args: argparse.Namespace) -> int:
    from datetime import datetime

    from .recap.gap import pick_tier, render
    from .recap.store import latest_record
    from .session import read_session

    found = latest_record(args.game, args.data_dir)
    if found is None:
        print("no recap yet — run `summarize` on a session log first", file=sys.stderr)
        return 1
    path, record = found
    session_path = path.with_name(record.session + ".jsonl")
    if not session_path.exists():
        print(f"session log {session_path} is missing", file=sys.stderr)
        return 1
    now = datetime.strptime(args.as_of, "%Y-%m-%d") if args.as_of else datetime.now()
    meta, _ = read_session(session_path)
    tier = args.tier or pick_tier(meta.ended or meta.started, now)
    print(render(record, session_path, tier, now))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from .recap.index import build, format_hits, search

    index = build(args.game, args.data_dir)
    hits = search(index, args.query, set(args.kind) if args.kind else None)
    print(format_hits(hits))
    return 0 if hits else 1


def cmd_app(args: argparse.Namespace) -> int:
    from .app import run_app

    return run_app(
        args.game,
        args.data_dir,
        watch=not args.no_watch,
        source=args.source,
        path=args.path,
        fps=args.fps,
        start=args.start,
        duration=args.duration,
        monitor=args.monitor,
        debug=args.debug,
        background=args.background,
        tray=not args.no_tray,
    )


def cmd_games(_: argparse.Namespace) -> int:
    for p in list_profiles():
        print(f"{p.id:12s} {p.display_name}  (process: {', '.join(p.process_names)})")
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    from .doctor import failed, report, run_checks

    checks = run_checks()
    print(report(checks))
    return 1 if failed(checks) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "run": cmd_run,
        "snapshot": cmd_snapshot,
        "calibrate": cmd_calibrate,
        "ocr": cmd_ocr,
        "stats": cmd_stats,
        "summarize": cmd_summarize,
        "recap": cmd_recap,
        "search": cmd_search,
        "app": cmd_app,
        "games": cmd_games,
        "check": cmd_check,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
