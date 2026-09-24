# Contributing

The most useful thing you can send is a wrong event. Every invented or
missed event is a classifier rule to fix, and the app makes reporting one a
single click: on the session's page, **Export for a bug report…** saves the
event log and the recap as a zip (text only — never a frame, never your
key). Attach it to a
[new issue](https://github.com/pedrocluis/previously-on/issues/new?template=wrong-event.yml)
and say which event is wrong and what the screen showed. From the command
line: `previously-on export --game <id> [<session stamp>]`.

## Setup and tests

```sh
uv sync            # Python 3.12; on Linux pygobject builds against girepository-2.0 and cairo
uv run pytest      # the whole suite, ~20 s without the frames (loads the OCR models once)
uv run pytest tests/test_regression_reads.py -s   # the regression set, per game and category
```

CI (`.github/workflows/tests.yml`) runs the same on Ubuntu for every pull
request.

### The regression set without the frames

Every rule in a profile was measured on a real frame, labelled in
`tests/fixtures/<game>/labels.yaml`. The frames are cut from other people's
recordings, so they are not in the repository. What the classifier sees of
a frame is text plus a few yes/no pixel answers ("is a boss HP bar drawn
under this name?"), and that is committed: `tests/fixtures/<game>/reads.json`
holds, per labelled frame and region, the OCR lines and the answer of every
pixel check the profile asked.

`tests/test_regression_reads.py` runs each profile's `classify` on those
lines, answers its pixel checks from the recording, and scores the result
against the labels with the product targets: **banners ≥ 95 %, dialogue
≥ 80 %, no invented event on a negative frame**. So you can change a rule
and see what it does to all ~380 frames of five games in under a second:

```
[ds3] banner 27/27  boss_engaged 5/5  dialogue 7/7  item_acquired 22/22  negative 24/24
```

Two limits, both loud rather than silent:

- A rule that asks the frame something new (a new `has_*` check, or the
  same one with different arguments) has no recorded answer; replay fails
  with `MissingCheck` naming the call. Say so in the pull request — the
  reads have to be re-recorded where the frames are.
- The reads come from the current OCR settings (`ocr.py`) and regions. A
  change to either needs a re-record, not just a replay.

With the frames on disk, `tests/test_regression.py` runs the same scoring on
the real pixels, and `uv run python -m tests.reads [game…]` re-records.

## Rules of the codebase

- **Precision over recall, always.** An invented event is worse than a
  missed one: it is what makes a player stop trusting the recap. Every rule
  rejects by default and is loosened from a real frame, one labelled
  fixture per rule, with a unit test in `tests/test_classify_<game>.py` that
  uses the real OCR read (the mangled text, not the clean phrase).
- **No game knowledge outside `src/previously_on/games/`.** Capture, diff,
  OCR, dedupe, the session log, stats, the recap and the app are generic. A
  game is one `GameProfile` module plus its fixture folder.
- **Never write a region or a banner phrase from memory.** Measure it on a
  frame.
- **Pixel checks go through module-level `has_*(frame, …)` functions** that
  return a bool; `classify` never reads the frame any other way. That is
  what lets the regression set run without the frames.
- **Only the text event log ever leaves the machine**, and only for the
  recap. Never a frame.
- The comments in the existing profiles (`games/eldenring.py`, `dsr.py`,
  `ds2.py`, `ds3.py`, `sekiro.py`) are the catalogue of what goes wrong on
  real frames — OCR dropping spaces, menus that look like names, credits
  that look like dialogue. Read the one closest to your game first.

## Adding a game

The pipeline is game-agnostic (`--game` on every command; both regression
tests pick up any `tests/fixtures/<id>/labels.yaml`). The work is measuring
the game, not wiring it. You need a recording of it — your own, or a
no-commentary playthrough at 1080p — and `ffmpeg` on the `PATH`.

### 1. Decide the basics

- **id**: a lowercase slug (`hollow_knight`) — the module name, the fixture
  folder and the `--game` value.
- **process names**: the Windows executable(s) (PCGamingWiki lists them;
  Task Manager confirms). Only a run on Windows proves them:
  `previously-on snapshot --game <id>` while the game is up.
- **aspect ratio**: 16:9 unless the game says otherwise. Regions are
  fractions of the frame, so resolution does not matter, aspect does.

### 2. Survey: where is the text?

`tools/add_game/survey.py` OCRs whole frames and groups what it reads by
position, so the banner band, the subtitle band, the item column and the
always-on HUD stand out:

```sh
uv run python tools/add_game/survey.py scan VIDEO --start S --duration D --out survey.jsonl   # ~0.5 s per 1080p frame at 1 fps
uv run python tools/add_game/survey.py scan --images DIR --out survey.jsonl                 # or a folder of screenshots
uv run python tools/add_game/survey.py report survey.jsonl
uv run python tools/add_game/survey.py find survey.jsonl 'YOUDIED|FELLED'                   # timestamps, for fixtures
```

Survey 5–15-minute slices that contain a death, a checkpoint, a boss fight
from bar to kill, item pickups, dialogue, and a menu, map, inventory and
loading screen for negatives. In the report, look for:

- **persistent HUD** (flagged `HUD?`, in ≥ 40 % of frames): health numbers,
  a flask name, a streamer's watermark. Every region must leave these out,
  or OCR runs on every frame and the classifier sees them all day.
- **banner vocabulary**: the "tall centred boxes" section. Banners last two
  or three frames, so counts are small; the tell is height and centring.
  Note what OCR actually returns (`LLOSTGRACEDISCOVEREDD`): `match_vocab`
  compares space-stripped forms, so the clean phrase goes in `BANNER_VOCAB`
  and the mangled read in a unit test.
- **subtitles**: the band with sentence-like boxes. Note whether lines carry
  a speaker name; it changes what the recap may say.
- **item pickups**: a column of Title Case names; note the edge they align to.
- **boss bar**: a name repeated at one height across a fight. It needs a
  pixel check on the bar (`has_boss_hp_bar`), or every menu label becomes a
  boss.
- **future false positives**: splash screens, tutorial titles, multiplayer
  notices, map labels, the end credits.

### 3. Map onto the existing events

Only the existing `EventType`s: `death`, `boss_engaged`, `boss_defeated`,
`enemy_defeated`, `checkpoint_discovered`, `area_discovered`,
`item_acquired`, `dialogue`. A game without item pickups has no item
region. A new event type is a product change (stats, search, the recap
prompt and the app all switch on the enum) — open an issue first.

### 4. Scaffold

```sh
uv run python tools/add_game/scaffold.py <id> --name "Display Name" --process game.exe \
    [--process launcher.exe] [--aspect 16:9] [--regions center_banner,subtitle,boss_bar,item_popup]
```

It writes `src/previously_on/games/<id>.py` and registers it,
`tests/fixtures/<id>/{README.md,labels.yaml}` and
`tests/test_classify_<id>.py`. The profile carries the generic guards (line
count, height, centring, sentence punctuation, edge alignment, the HP-bar
pixel check) and rejects everything until its `TODO`s are filled: the
profile is not done while `grep -n TODO src/previously_on/games/<id>.py`
prints anything. Leave out regions the game does not have.

### 5. Measure the regions

Cut a frame per region and look at what each crop holds:

```sh
ffmpeg -ss T -i VIDEO -frames:v 1 -q:v 3 f.jpg
uv run previously-on calibrate --game <id> f.jpg --out calibration/   # overlay.png + one crop per region
uv run previously-on ocr --game <id> f.jpg                             # what OCR and the classifier make of each crop
```

A crop must contain exactly the text it is for: tight enough to keep the
HUD and neighbouring popups out, wide enough for the longest name in the
game. Write the source resolution and timestamp next to each `Region`, as
the existing profiles do. A boss-name strip stops *above* the bar: the fill
changes on every hit and would re-trigger OCR all fight long.

### 6. Fixtures: 30 or more, at least 6 negatives

Cut frames into `tests/fixtures/<id>/<category>_<name>.jpg` and label them in
`labels.yaml` (format in the folder's README). Label *everything* visible in
a frame. Negatives: open world with no text, the map, the inventory, the
pause menu, a letterboxed cutscene, the publisher splash, a loading screen,
the end credits — anything with big centred text that is not an event.
Deaths are often edited out of walkthroughs; a streamer's death compilation
is a good second source.

```sh
uv run pytest tests/test_regression.py -s      # on the frames
uv run python -m tests.reads <id>              # record reads.json
uv run pytest tests/test_regression_reads.py -s
```

Commit `labels.yaml`, `reads.json` and the README with the sources and
timestamps — not the JPEGs.

### 7. Rules: the precision loop

For every miss or invention: find the frame, add it as a labelled fixture,
fix `games/<id>.py`, add a unit test with the real OCR read, re-record the
reads. Generic modules change only for provably generic problems. Check a
new fuzzy threshold against every known name before trusting it.

Then run a long stretch of the recording end to end and read every logged
event against the video:

```sh
uv run previously-on run --game <id> --source video --path VIDEO --start S --duration 3600 --out runs/
```

### 8. Recap notes

Fill `recap_notes` in the profile: what a checkpoint is called, whether
subtitles name the speaker, what a pickup implies (a boss's drop proves the
kill), anything the model must not infer. Summarise one log
(`previously-on summarize --game <id> runs/sessions/<id>/*.jsonl`, needs a
key) and check that every person, item, boss and place in the prose appears
in the log.

### 9. The pull request

One pull request with the profile, `labels.yaml`, `reads.json`, the fixture
README and the tests; the README table of supported games gains a row
saying what it was validated on. A profile that has never run against the
real game on Windows ships marked as such.
