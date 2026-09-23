# Dark Souls III regression fixtures

Real frames, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames).

## Where the frames came from

A 1080p60 no-commentary YouTube playthrough of the PS5 version
(`tW3ZVQiOtyc`, 9.6 h), downloaded in one-hour chunks under
`recordings/ds3/` (gitignored; `setup.sh` / `download_chunk.sh` in
`.claude/skills/validate-playthrough/scripts/`). `t` in `labels.yaml` is the
second within chunk 00, cut with
`ffmpeg -ss T -i recordings/ds3/er_00.webm -frames:v 1 -q:v 3 out.jpg`.
Candidates were found with the add-game survey (`survey.py scan` /
`report` / `find` over the whole hour at 1 fps, `recordings/ds3/survey00.jsonl`);
a banner the survey read at second T is sometimes only on screen from
T+0.5, so several `t` values carry a half-second offset. The HUD is the PC
one; only the button glyphs differ, and they OCR as a letter and a colon
either way.

**Deaths** (`death_kingdd_*.jpg`): the playthrough edits its deaths out (a
`SOULS RETRIEVED` banner at t 2025 follows a respawn no death preceded), so
the death frames come from five minutes (1:00:00–1:05:00) of a streamer's
first run kept with every death (`0L1tJKnvESk`, as
`recordings/ds3/deaths/kingdd.webm`, 1080p30). The game is drawn at its
native layout there — the `Estus Flask` label and the souls counter sit
where the playthrough has them — with a small facecam and a death counter
along the top edge, outside every region. `YOU DIED` is dim (the letters'
V is 35–60 at their brightest) and OCR reads it for about a second of the
fade in that edit; the frames are the brightest moment of each. The
Pontiff Sulyvahn bar under the banner reads fine but its border is
darkened with the scene, so it is not labelled.

## What the frames cover

| Category | Frames |
|---|---|
| Death | five `YOU DIED` from the death clip (see above) |
| Boss defeated | `HEIR OF FIRE DESTROYED` for Iudex Gundyr (×2, one with the gesture menu open and the `Coiled Sword` drop under it), Vordt of the Boreal Valley (with `Soul of Boreal Valley Vordt`) |
| Checkpoint | six `BONFIRE LIT` |
| Area reveal | Cemetery of Ash, Firelink Shrine (×2), High Wall of Lothric, Undead Settlement (×3) |
| Boss bar | Iudex Gundyr (×2, one over a bright arena where the bottom border line reads only 0.66), Vordt of the Boreal Valley |
| Item popup | Titanite Shard (HUD hidden), a stacked pair (Titanite Shard + Ember), Soul of an Unknown Traveler, Coiled Sword (×2, one under `EMBER RESTORED`), the `Rest` gesture, Ember, Way of Blue (a covenant), Homeward Bone, Ashen Estus Flask, Fading Soul, Binoculars, Firebomb |
| Dialogue | the intro cutscene (no HUD), four NPC lines at Firelink Shrine and in the Undead Settlement, one wide two-sentence line (x 0.13–0.87) |
| Negative | the title splash (`-DARK SOULS III`, `PRESS ANY BUTTON`), character creation, the level-up table, the equipment and inventory screens, the bonfire warp menu, the bonfire menu, two loading screens with item lore, open world with the HUD, a fight with damage numbers, the invasion notice, `SOULS RETRIEVED`, `DARK SPIRIT DESTROYED` with the "has died" notice, the `Read message` and `Pillage remains` prompts |

## labels.yaml format

```yaml
- file: heir_vordt.jpg
  t: 2577.5                       # second within the chunk
  expected:
    - {type: boss_defeated, text: HEIR OF FIRE DESTROYED}
    - {type: item_acquired, text: Soul of Boreal Valley Vordt}
- file: subtitle_ash.jpg
  expected:
    - {type: dialogue}            # text optional; dialogue is allowed to be lossy
- file: neg_loading.jpg
  expected: []                    # negative frame
```

`type` is one of: `death`, `boss_defeated`, `enemy_defeated`,
`checkpoint_discovered`, `area_discovered`, `item_acquired`, `dialogue`,
`boss_engaged`. Label *everything* visible in a frame — the pickup under a
victory banner is a correct detection, not an invention.

## Tuning regions

`uv run previously-on calibrate --game ds3 frame.jpg` writes `overlay.png`
with every region drawn plus one crop per region;
`uv run previously-on ocr --game ds3 frame.jpg` shows what OCR and the
classifier make of each crop. Region notes (what each edge avoids) are in
`src/previously_on/games/ds3.py` next to each `Region`.

## Adding frames from sessions

For a false positive in a session log, cut the frame at that `t_rel`, drop
it here, label it (`expected: []` for a negative), then add the guard to
the profile and a unit test in `tests/test_classify_ds3.py` with the real
OCR read.
