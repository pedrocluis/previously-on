# {{display_name}} regression fixtures

Real screenshots, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames). An empty `labels.yaml` is skipped.

The frames are cut from recordings you probably do not own, so they are
not committed (`.gitignore` drops `tests/fixtures/*/*.jpg`). What is
committed is `reads.json`: the OCR lines and pixel-check answers recorded
from each frame by `uv run python -m tests.reads {{id}}`, which
`tests/test_regression_reads.py` replays on any clone. Re-record after
adding a frame or changing a region.

Where the frames came from (recording, resolution, timestamps) goes here.
Each positive frame is the first half-second offset around the event where
`uv run previously-on ocr --game {{id}} frame.jpg` actually sees it, judged on
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
`boss_engaged`.

## Tuning regions

`uv run previously-on calibrate --game {{id}} frame.jpg` writes `overlay.png`
with every region drawn plus one crop per region. Adjust the coordinates in
`src/previously_on/games/{{id}}.py` until each crop contains exactly the text
it should and none of the persistent HUD. `uv run previously-on ocr --game
{{id}} frame.jpg` shows what OCR and the classifier make of each crop.

## Adding frames from live sessions

`previously-on run --game {{id}} --debug-frames debug/` saves a small frame
every 30 s. For a false positive in a session log, cut the frame at that
`t_rel`, drop it here, label it (`expected: []` for a negative), then add the
guard to the profile and a unit test with the real OCR read.
