# Dark Souls: Remastered regression fixtures

Real frames, each described in `labels.yaml`.
`uv run pytest tests/test_regression.py -s` reports per-category accuracy
and enforces the targets (banners ≥ 95 %, dialogue ≥ 80 %, zero invented
events on negative frames).

## Where the frames came from

A 1080p60 no-commentary YouTube playthrough (`2WqgSPLE-3E`), downloaded in
one-hour chunks under `recordings/dsr/` (gitignored; `setup.sh` /
`download_chunk.sh` in `.claude/skills/validate-playthrough/scripts/`). `t`
in `labels.yaml` is the second within the chunk (chunk 00 unless the file
name ends in `_c01`), cut with
`ffmpeg -ss T -i recordings/dsr/er_NN.webm -frames:v 1 -q:v 3 out.jpg`.
Candidates were found with the add-game survey
(`survey.py scan` / `report` / `find` over the whole hour at 1 fps); a
banner the survey read at second T is sometimes only on screen from T+0.5,
so a few `t` values carry a half-second offset.

**Deaths** (`death_octo_*.jpg`): the playthrough edits its deaths out (a
`RETRIEVAL` banner in chunk 01 follows a respawn no death preceded), so the
death frames come from a streamer's Remastered death compilation
(`bizJynwzGNQ`, first three minutes as `recordings/dsr/deaths/octo_deaths.mp4`,
1080p60). The game sits inside a stream layout there (x 348–1920, y 0–884 of
the 1080p frame); each frame was rectified to the native layout with
`ffmpeg -ss T -i octo_deaths.mp4 -frames:v 1 -vf "crop=1572:884:348:0,scale=1920:1080" -q:v 3 out.jpg`
and the rectification checked against the HUD: the `Estus Flask` label
lands at x 0.218–0.299 / y 0.911 and the souls counter at x 0.87–0.92, where
the playthrough has them. The streamer's own "Death Count" overlay sits at
the top, outside every region.

## What the frames cover

| Category | Frames |
|---|---|
| Death | four `YOU DIED` from the compilation (see above) |
| Boss defeated | `VICTORY ACHIEVED` for the Asylum Demon (with the `Big Pilgrim's Key` drop under it), Taurus Demon, Bell Gargoyles (with `Gargoyle Helm`), Moonlight Butterfly, Capra Demon (with `Key to Depths`) |
| Checkpoint | four `BONFIRE LIT`, one read `EBONFIRE LIT` |
| Area reveal | Northern Undead Asylum, Firelink Shrine (×2, one with the tutorial popup above it), Undead Burg, Undead Parish, Darkroot Garden (OCR splits it in two boxes), Darkroot Basin, Depths (read `'Depths`), Blighttown |
| Boss bar | Asylum Demon, Taurus Demon, both Bell Gargoyles (two bars, the second raised 0.063), Moonlight Butterfly, Capra Demon (×2, one under the `RETRIEVAL` banner), Gaping Dragon |
| Item popup | a common soul, a stacked pair (Humanity + Homeward Bone), Twin Humanities |
| Dialogue | the intro cutscene (wide, no HUD), an NPC line drawn over the `Estus Flask` label, Oscar, the Crestfallen Warrior, a two-line box |
| Negative | equipment, inventory, level-up (`Physical Def.` in the item crop), shop (×2), blacksmith, forge menus and the forge confirmation dialog; `HUMANITY RESTORED`, `HUMANITY ACQUIRED`; the tutorial popup; open world; a black cutscene frame; a frame with no text |

## labels.yaml format

```yaml
- file: victory_asylum_demon.jpg
  t: 580                          # second within the chunk
  expected:
    - {type: boss_defeated, text: VICTORY ACHIEVED}
    - {type: item_acquired, text: "Big Pilgrim's Key"}
- file: subtitle_oscar.jpg
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

`uv run previously-on calibrate --game dsr frame.jpg` writes `overlay.png`
with every region drawn plus one crop per region;
`uv run previously-on ocr --game dsr frame.jpg` shows what OCR and the
classifier make of each crop. Region notes (what each edge avoids) are in
`src/previously_on/games/dsr.py` next to each `Region`.

## Adding frames from sessions

For a false positive in a session log, cut the frame at that `t_rel`, drop
it here, label it (`expected: []` for a negative), then add the guard to
the profile and a unit test in `tests/test_classify_dsr.py` with the real
OCR read.
