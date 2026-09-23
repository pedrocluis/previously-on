# Previously On

Passive session memory for long single-player games. It watches the screen,
reads the announcements the game already makes (`YOU DIED`, `GREAT ENEMY
FELLED`, item popups, area names, subtitles) and logs them so that when you
come back after a month you can be told where you left off.

Supported games (PC, 16:9, English UI):

| Game | `--game` | Validated on |
|---|---|---|
| Elden Ring | `eldenring` (default) | a 15-hour playthrough, and live on Windows |
| Dark Souls: Remastered | `dsr` | a 6.6-hour playthrough |
| Dark Souls II: Scholar of the First Sin | `ds2` | an 8.6-hour playthrough |
| Dark Souls III | `ds3` | a 9.6-hour playthrough |
| Sekiro: Shadows Die Twice | `sekiro` | an 8-hour playthrough |

Live capture has only been run against Elden Ring so far; the other four
profiles were built and validated on recordings.

Live capture is Windows only (the games are). Everything else — replaying a
recording, the recap, search and the desktop window — also runs on Linux.

## Install (Windows)

Download `PreviouslyOn-<version>-windows-x64.zip` from the
[releases](https://github.com/pedrocluis/previously-on/releases), unzip it
anywhere and run `PreviouslyOn.exe`. Nothing to install beside it: Python,
the OCR models and the capture backend are in the folder. The window uses
the Microsoft Edge WebView2 Runtime, which Windows 11 and current Windows 10
already have.

If something does not work, run `previously-on-cli.exe check` from a terminal in
that folder and paste its output into an issue; it tests OCR, capture and
the window on your machine, and prints the data folder where the sessions
and the window's own `app.log` live.

The bundle is built by `.github/workflows/windows-bundle.yml` from
`packaging/previously-on.spec`:

```sh
uv sync --group bundle
uv run pyinstaller --noconfirm packaging/previously-on.spec   # -> dist/PreviouslyOn/
```

## Setup (from source)

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned.

```sh
uv sync
uv run previously-on --help
```

## The app

```sh
uv run previously-on app
```

One window, one process: it waits for the game, logs the session while you
play, writes the recap when the game exits, and next time you open it tells
you where you left off — one line of stats if you played yesterday, the
full "Previously on…" if it has been weeks. Sessions, a timeline of the
whole playthrough, and a search over every item, place, boss and NPC are
one click away. On Windows `previously-on-app` opens it without a
console.

Recaps need an API key, entered in Settings or set in the environment:
`OPENAI_API_KEY` for the default model (`gpt-5.4-mini`), or
`ANTHROPIC_API_KEY` with `PREVIOUSLY_ON_MODEL=claude-…`. Recaps cost cents
per session. **Only the text event log is ever sent, never a frame.**
Detection, stats and search are fully offline.

`--no-watch` only browses what is logged; `--source video --path X.webm`
drives the window from a recording.

## Command line

```sh
# Live capture on the gaming PC. Starts when the game (--game, default Elden Ring) appears, stops when it exits.
# On Windows this uses DXGI desktop duplication (dxcam), which sees exclusive-fullscreen
# games; --source mss (GDI) only works for windowed/borderless games.
uv run previously-on run --wait-for-game

# Check that capture works before a session: saves snapshot.png and prints what each region reads.
uv run previously-on snapshot

# Live capture runs OCR on 2 threads at below-normal process priority so the game keeps
# the machine; --ocr-threads N / --no-low-priority override that.

# Replay a recording (OBS / ShadowPlay) — same pipeline, no game needed.
# Any container/codec the system ffmpeg decodes (webm/AV1 included); falls
# back to OpenCV's bundled decoder when ffmpeg is not on PATH.
uv run previously-on run --source video --path session.webm
uv run previously-on run --source video --path session.webm --start 600 --duration 120

# Replay a folder of screenshots as consecutive frames.
uv run previously-on run --source images --path ./frames

# Summarise a session: "3h 12m · 14 deaths · Bayle still standing"
uv run previously-on stats ~/.local/share/previously-on/sessions/eldenring/*.jsonl

# Tune region coordinates / inspect what OCR sees on one screenshot.
uv run previously-on calibrate screenshot.png
uv run previously-on ocr screenshot.png
```

Session logs are append-only JSONL under the platform user-data dir
(`--out` overrides), one file per session:

```jsonl
{"kind": "session_start", "game": "eldenring", "source": "mss", "started": "..."}
{"kind": "event", "ts": "...", "t_rel": 512.0, "type": "death", "text": "YOU DIED", "conf": 0.97, "region": "center_banner", "raw": ["YOU DIED"], "frame_index": 1024}
{"kind": "session_end", "ended": "...", "played": 11520.0, "events": 37}
```

## How it works

```
frames (2 fps)  →  per-region text mask diff  →  [unchanged: discard]
                                 ↓ changed, then settled
                                OCR (RapidOCR, bundled ONNX)
                                 ↓
                   game profile classifies text → event
                                 ↓
                         dedupe → session JSONL → stats
```

Everything game-specific — process name, HUD regions, banner vocabulary,
classification rules, dedupe cooldowns — lives in one `GameProfile`
(`src/previously_on/games/<id>.py`). The pipeline, capture sources,
diffing, OCR, session log and stats never mention a specific game.

Classifiers are biased toward precision: a recap that invents an event is
worse than one that misses it. Beyond the text, profiles can check pixels —
the Elden Ring profile only accepts a boss name if the boss HP bar is drawn
under it.

Validated on a 2-hour Elden Ring recording (Messmer the Impaler, 30
attempts): every death, the kill (`DEMIGOD FELLED`), grace sites, area
reveals, 42 item pickups and the NPC dialogue, with no invented bosses or
places. Known gap: at 2 fps a 2-second `YOU DIED` over heavy fire effects can
occasionally fall between OCR shots (~1 in 30).

## Tests

```sh
uv run pytest                               # everything (~2 min; loads OCR models)
uv run pytest tests/test_regression.py -s   # real screenshots, with a per-category report
```

Every rule in a profile was measured on real frames, labelled in
`tests/fixtures/<game>/labels.yaml` with the source video and timestamp.
The frames themselves are cut from other people's recordings and are **not
in this repository**; the tests that need one skip without it, and the
rest (classification on recorded OCR reads, synthetic frames, dedupe,
stats, recap, app) run everywhere.

## Adding a game

1. Create `src/previously_on/games/<id>.py` with a class implementing
   `GameProfile` (`games/__init__.py`): `id`, `display_name`,
   `process_names`, `aspect_ratio`, `regions`, `cooldowns`,
   `quiet_after_event`, and `classify(region, ocr_lines, frame)`.
2. Register it in `_profiles()` in `games/__init__.py`.
3. Add `tests/fixtures/<id>/labels.yaml` and screenshots.
4. `previously-on run --game <id>`.

Never write a region or a banner phrase from memory: measure it on a
frame. Every classifier rule should reject by default — an invented event
is worse than a missed one.

## Disclaimer

Previously On only captures the screen, the way a recording tool does; it
never reads or modifies game memory or files. It has been used alongside
Elden Ring's Easy Anti-Cheat without issue, but that is not a guarantee —
use it at your own risk. Not affiliated with or endorsed by FromSoftware or
Bandai Namco; game names are used only to say what is supported.

## License

[MIT](LICENSE)
