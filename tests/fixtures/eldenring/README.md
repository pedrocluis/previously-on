# Elden Ring regression fixtures

Real 16:9 screenshots, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the M2 targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames).

The first 30 frames were cut from a 2-hour 1440p recording
(`elden-ring-test.webm`, not in the repo); the rest from a 15-hour 1080p60
base-game playthrough (YouTube `bg8i4CvE74M`, chunked under
`recordings/mkiceandfire/`), one frame per rule it forced. Each positive
frame was chosen at the first half-second offset around the labelled time
where the detector actually sees the event, judged on the JPEG as stored.
The `t:` field in `labels.yaml` is the source timestamp (absolute video
seconds for the playthrough), for re-cutting.

The frames are not in the public repository (they are cut from other
people's recordings); without them the tests that need a frame skip.

## What to capture (aim for 30+)

| Category | Examples | How many |
|---|---|---|
| Death | `YOU DIED` at full opacity, and one mid-fade | 5 |
| Boss defeated | `GREAT ENEMY FELLED` | 3 |
| Enemy defeated | `ENEMY FELLED` | 3 |
| Grace | `LOST GRACE DISCOVERED` | 3 |
| Area reveal | `LIMGRAVE`, `STORMVEIL CASTLE`, … | 4 |
| Boss bar | any boss with its name visible above the health bar | 3 |
| Item popup | rune, weapon, key item | 3 |
| Dialogue | NPC subtitles, short and long lines | 5 |
| **Negative** | open world with no text, map screen, inventory, a cutscene with letterboxing, the pause menu | 6+ |

Negatives matter most: a recap that invents an event is far worse than one
that misses it.

## labels.yaml format

```yaml
- file: death_01.png
  expected:
    - {type: death}
- file: area_limgrave.png
  expected:
    - {type: area_discovered, text: Limgrave}
- file: margit_bar.png
  expected:
    - {type: boss_engaged, text: "Margit, the Fell Omen"}
- file: subtitle_melina.png
  expected:
    - {type: dialogue}          # text optional; dialogue is allowed to be lossy
- file: map_screen.png
  expected: []                  # negative frame
```

`type` is one of: `death`, `boss_defeated`, `enemy_defeated`,
`checkpoint_discovered`, `area_discovered`, `item_acquired`, `dialogue`,
`boss_engaged`.

## Tuning regions

Run `uv run previously-on calibrate <screenshot.png>` to get an `overlay.png`
with every region drawn, plus one crop per region. Adjust the coordinates in
`src/previously_on/games/eldenring.py` until each crop contains exactly the
text it should. `uv run previously-on ocr <screenshot.png>` shows what OCR and
the classifier make of each crop.

## Anti-cheat and fullscreen (verified 2026-09-16)

Live capture alongside Easy Anti-Cheat is fine. Exclusive fullscreen needs
the DXGI desktop-duplication backend (`dxcam`, the default on Windows);
GDI capture (`--source mss`) returns black frames for it. Check with
`uv run previously-on snapshot` before a session.

## Adding frames from live sessions

`previously-on run --debug-frames debug/` saves a small frame every 30 s.
For a false positive in a session log, cut the frame at that `t_rel`,
drop it here, label it (`expected: []` for a negative), then add the guard.
