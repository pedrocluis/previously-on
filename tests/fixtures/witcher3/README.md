# The Witcher 3: Wild Hunt regression fixtures

Real screenshots, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames). An empty `labels.yaml` is skipped.

The frames are cut from recordings you probably do not own, so they are
not committed (`.gitignore` drops `tests/fixtures/*/*.jpg`). What is
committed is `reads.json`: the OCR lines and pixel-check answers recorded
from each frame by `uv run python -m tests.reads witcher3`, which
`tests/test_regression_reads.py` replays on any clone. Re-record after
adding a frame or changing a region.

## Where the frames came from

* **The playthrough** — "THE WITCHER 3 REMASTERED Gameplay Walkthrough Part 1
  FULL GAME [4K 60FPS PC ULTRA] - No Commentary" by MKIceAndFire (YouTube
  `Eyob-Abhx54`, 6 h 13 min, the first part of a multi-part run on the
  next-gen PC version), fetched at 1080p60 in one-hour chunks under
  `recordings/witcher3/` (gitignored). `t` in `labels.yaml` is the second in
  the whole video: chunk 00 is t 0-3600, chunk 01 starts at 3600. The
  channel's watermark sits bottom right (y 0.93), below every region.
* **Deaths** — the playthrough edits its deaths out, so the `death_*`
  frames come from two short clips under `recordings/witcher3/deaths/`:
  "Witcher 3 Mod Showcase - Instant Death Screen" (YouTube `3F0IjSYgrXI`,
  720p; the mod only skips the death animation, the screen is the game's)
  and "Weirdest Death Animation - The Witcher 3: Wild Hunt" (`rPjCVfxJ6ps`,
  1080p). They agree on the screen's geometry to 0.003. A third
  (`vPf3xjhzjSg`) gives the combat-log negative. `t` for these is the
  second in the clip.
* The game's subtitles here are the defaults: cutscene lines carry no
  speaker name, field lines do ("Vesemir: …"). A player who turns on
  "speaker names" in the options would put a name on cutscene lines too;
  nothing here depends on either.

Cut a frame with the command below; the recordings are VP9 with a limited
colour range, which the JPEG encoder refuses unless told
(`-vf scale=out_range=full -pix_fmt yuvj420p`). Survey timestamps and a cut
at the same second can differ by half a second; take the first offset
where the event is read on the stored JPEG.

Each positive frame is the first half-second offset around the event where
`uv run previously-on ocr --game witcher3 frame.jpg` actually sees it, judged on
the JPEG as stored (`ffmpeg -ss T -i VIDEO -frames:v 1 -q:v 3 out.jpg`). Keep
`t:` = source timestamp for re-cutting.

## What to capture (aim for 30+)

| Category | Examples | How many |
|---|---|---|
| Death | the death banner at full opacity, and one mid-fade | 5 |
| Boss defeated | the defeat banner | 3 |
| Enemy defeated | the lesser-enemy banner, if the game has one | 3 |
| Checkpoint | the checkpoint banner | 3 |
| Area reveal | area name banners | 4 |
| Boss bar | any boss with its name visible above the health bar | 3 |
| Item popup | a common item, a key item, a stacked pickup | 3 |
| Dialogue | subtitles, short and long lines | 5 |
| **Negative** | open world with no text, map screen, inventory, a cutscene with letterboxing, the pause menu, the publisher splash | 6+ |

Negatives matter most: a recap that invents an event is far worse than one
that misses it. Label *everything* visible in a frame — a pickup still on
screen next to a banner is a correct detection, not an invention.

## labels.yaml format

```yaml
- file: death_01.jpg
  t: 661                          # source timestamp, seconds
  expected:
    - {type: death}
- file: area_first_town.jpg
  expected:
    - {type: area_discovered, text: First Town}
- file: boss_bar_01.jpg
  expected:
    - {type: boss_engaged, text: "Boss Name"}
- file: subtitle_01.jpg
  expected:
    - {type: dialogue}          # text optional; dialogue is allowed to be lossy
- file: map_screen.jpg
  expected: []                  # negative frame
```

`type` is one of: `death`, `boss_defeated`, `enemy_defeated`,
`checkpoint_discovered`, `area_discovered`, `item_acquired`, `dialogue`,
`boss_engaged`, `quest_started`, `quest_updated`, `quest_completed`.

## Tuning regions

`uv run previously-on calibrate --game witcher3 frame.jpg` writes `overlay.png`
with every region drawn plus one crop per region. Adjust the coordinates in
`src/previously_on/games/witcher3.py` until each crop contains exactly the text
it should and none of the persistent HUD. `uv run previously-on ocr --game
witcher3 frame.jpg` shows what OCR and the classifier make of each crop.

## Adding frames from live sessions

`previously-on run --game witcher3 --debug-frames debug/` saves a small frame
every 30 s. For a false positive in a session log, cut the frame at that
`t_rel`, drop it here, label it (`expected: []` for a negative), then add the
guard to the profile and a unit test with the real OCR read.
