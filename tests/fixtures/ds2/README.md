# Dark Souls II: Scholar of the First Sin regression fixtures

Real frames, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames).

## Where the frames came from

A 1080p60 no-commentary YouTube playthrough (`GfaV_OAo8Vg`, 8.6 h — the
source is 1440p, the ≤1080p stream is what `download_chunk.sh` fetches),
downloaded in one-hour chunks under `recordings/ds2/` (gitignored;
`setup.sh` / `download_chunk.sh` in
`.claude/skills/validate-playthrough/scripts/`). `t` in `labels.yaml` is
the second within the chunk (chunk 00 unless the file name ends in
`_c01`), cut with
`ffmpeg -ss T -i recordings/ds2/er_NN.webm -frames:v 1 -q:v 3 out.jpg`.
Candidates were found with the add-game survey (`survey.py scan` /
`report` / `find` over chunk 00 at 1 fps and over t 1000–1240 of chunk
01); a banner the survey read at second T is sometimes only on screen from
T+0.5, so most `t` values carry a half-second offset.

**Deaths** (`death_montage_*.jpg`): the playthrough shows no `YOU DIED` in
its first two hours, so the death frames come from a streamer's Scholar
death montage (`aovN8ZL0Nuk`, 1080p30, first five minutes as
`recordings/ds2/deaths/gorman_deaths.mp4`). It is the native layout — the
HP bar (x 0.155–0.30, y 0.10–0.14), the quick-slot label (`10 Lifegem`,
y 0.91) and the souls counter (x 0.83+) sit where the playthrough has them
— so the frames are used as cut. `neg_montage_dark_hud.jpg` is the same
recording a beat before a death: a near-black scene with the HUD drawn.

## What the frames cover

| Category | Frames |
|---|---|
| Death | six `YOU DIED` from the montage (one over a saturated red scene, one mid fade read `YOUDIED`) |
| Boss engaged | Old Dragonslayer at full HP and mid-fight (damage number at the bar's right end) |
| Boss defeated | `VICTORY ACHIEVED` (Old Dragonslayer), followed by the `Old Dragonslayer Soul` + `Old Leo Ring` drop |
| Checkpoint | five `BONFIRE LIT` (one read `BONFIRELIT`) |
| Area reveal | Things Betwixt, Majula (×2, one mid fade), Forest of Fallen Giants (×2, one read `Forestof Fallen Giants`), Cathedral of Blue |
| Item popup | single rows (Rusted Coin, Human Effigy from a chest, Estus Flask Shard, Hollow Infantry Helm) and two-row stacks (Morning Star + Cleric's Sacred Chime, Soul of a Nameless Soldier + Lifegem, Shortsword + Soul of a Lost Undead, Soul of a Lost Undead + Torch, Hand Axe + Radiant Lifegem) — the soul names read `Soul ofa …` |
| Dialogue | the opening narration under the publisher splash, a letterboxed cutscene row (no HUD), a two-row line over the `10 Lifegem` label, a short line, the longest line (x 0.18–0.79) |
| Negative | `FROMSOFTWARE` splash; character creation (`Try to recall your name` centred in the area band; the gift list with `Human Effigy`, `Bonfire Ascetic`); `A:Light bonfire` and `A:Touch bloodstain` prompts; the level-up tutorial line and both level-up screens; inventory (`Pick an item.`, an item description row), equipment, Melentia's shop (`Lenigrast's Key` at x 0.08); the bonfire menu (`Cardinal Tower`, ×2); open world (×3), an arena, a near-black corridor |

## labels.yaml format

```yaml
- file: victory_old_dragonslayer_c01.jpg
  t: 1174.5                       # second within the chunk
  expected:
    - {type: boss_defeated, text: VICTORY ACHIEVED}
- file: subtitle_short.jpg
  expected:
    - {type: dialogue}            # text optional; dialogue is allowed to be lossy
- file: neg_menu_shop.jpg
  expected: []                    # negative frame
```

`type` is one of: `death`, `boss_defeated`, `enemy_defeated`,
`checkpoint_discovered`, `area_discovered`, `item_acquired`, `dialogue`,
`boss_engaged`. Label *everything* visible in a frame — the pickup under a
victory banner is a correct detection, not an invention.

## Tuning regions

`uv run previously-on calibrate --game ds2 frame.jpg` writes `overlay.png`
with every region drawn plus one crop per region;
`uv run previously-on ocr --game ds2 frame.jpg` shows what OCR and the
classifier make of each crop. Region notes (what each edge avoids) are in
`src/previously_on/games/ds2.py` next to each `Region`.

## Adding frames from sessions

For a false positive in a session log, cut the frame at that `t_rel`, drop
it here, label it (`expected: []` for a negative), then add the guard to
the profile and a unit test in `tests/test_classify_ds2.py` with the real
OCR read.
