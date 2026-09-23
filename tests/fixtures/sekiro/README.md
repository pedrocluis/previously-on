# Sekiro: Shadows Die Twice regression fixtures

Real screenshots, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames).

## Where the frames came from

* **The playthrough** — "SEKIRO: SHADOWS DIE TWICE Full Gameplay
  Walkthrough / No Commentary 【FULL GAME】PS5 4K UHD" (YouTube
  `bXykENe1wwY`, 8 h 2 min), fetched at 1080p in one-hour chunks under
  `recordings/sekiro/` (gitignored). `t` in `labels.yaml` is the second
  within `er_00.webm` unless the comment says otherwise. Three frames come
  from `probe.webm`, a three-minute slice at 18:00 of the same video.
* **Deaths** — the playthrough's first hour has none (the run is clean, the
  way the Dark Souls walkthroughs edit theirs out), so the `death_*` frames
  come from "Death Montage - Sekiro: Shadows Die Twice" (YouTube
  `EVKiAeVHjf8`), first five minutes at 1080p as
  `recordings/sekiro/deaths/montage.webm`. Native layout, no stream
  overlay. `boss_juzou.jpg` and two dialogue frames come from it too.

Cut a frame with
`ffmpeg -ss T -i VIDEO -frames:v 1 -q:v 3 out.jpg`, then check it with
`uv run previously-on ocr --game sekiro out.jpg` — the label must match
what the classifier sees on the JPEG **as stored**.

## What this set covers

| Category | Frames | What the frame is there to prove |
|---|---|---|
| Death | 6 | the `DEATH` caption under 死, five from the montage and the playthrough's own first death, which reads `EATH` |
| Checkpoint | 3 | `SCULPTOR'S IDOL FOUND`, once with a pickup beside it |
| Area reveal | 4 | the large Title Case banner at y 0.43-0.50 |
| Boss bar | 10 | four bar lengths, a bright arena, the 危 mark over the area band, and a bar with an NPC shouting over it |
| Item popup | 8 | one, two and three rows; a name with a rank digit; names the font glues; the Memory and Remnant a boss drops, whose colon must survive |
| Dialogue | 6 | both subtitle bands, the longest line in the game so far, a line during a boss fight |
| Negative | 13 | the reading screen, the status menu, an item description, the channel's intro card, open world, the start-up WARNING; three of the Sculptor's menus, whose wooden frame has light end caps where the boss bar's are and whose headers sit where a boss name sits; two frames of its description panel, which ends at the same x as an item name; and the two confirmation boxes, drawn in the subtitle's own band |

Negatives matter most: a recap that invents an event is far worse than one
that misses it. Label *everything* visible in a frame — a pickup still on
screen next to a banner is a correct detection, not an invention.

## Adding frames from live sessions

`previously-on run --game sekiro --debug-frames debug/` saves a small frame
every 30 s. For a false positive in a session log, cut the frame at that
`t_rel`, drop it here, label it (`expected: []` for a negative), then add
the guard to `src/previously_on/games/sekiro.py` and a unit test in
`tests/test_classify_sekiro.py` with the real OCR read.
