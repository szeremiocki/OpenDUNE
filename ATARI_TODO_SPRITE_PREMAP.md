# GUI_DrawSprite: compose sprite palette with house remap  [DONE]

Status: implemented and verified against `opendune_prof12.txt`.

## Problem

`GUI_DrawSprite`'s `REMAP|SPRITEPAL` path converted each stored index into a
screen colour with two dependent lookups per opaque pixel:

    MOVE.B (A3,D2.L),D2     16 cyc   palette[v]
    AND.L  #$ff,D2          16 cyc
    MOVE.B (A2,D2.L),(A0)   20 cyc   remap[...]

Measured at **92.04 cycles per opaque pixel** in prof11 over 102,400 pixels,
against **48.05** for the plain `SPRITEPAL` path.

## What shipped

That conversion is constant for a given sprite palette and remap table, and a
sprite palette is only **16 bytes** (header doc: `0A: [16 bytes] = house
colors`), so the stored index is 0..15. The whole of `rm[pal[v]]` therefore
collapses into a **16-byte table built once per call**:

    spritePalRemap[i] = remap applied remapCount times to palette[i]
    palette = spritePalRemap;
    flags &= ~DRAWSPRITE_FLAG_REMAP;

Clearing the flag redirects the dispatch at `switch (flags & 0xF00)` — which is
re-read inside the row loop, after this setup — onto the cheaper `SPRITEPAL`
case. BLUR combinations are excluded; they read `*buf` and the composition does
not apply.

## Result (per-instruction cycle counts)

| Loop | prof11 | prof12 |
|---|---|---|
| REMAP\|SPRITEPAL | 92.04 cyc/px (102,400 px) | gone |
| SPRITEPAL | 48.05 cyc/px (48,588 px) | 48.05 cyc/px (122,526 px) |

The `SPRITEPAL` loop is cycle-identical across the two profiles — registers were
reallocated (`A3,D2` -> `A0,D7`) but no instruction's cost changed. That is the
evidence the migrated pixels landed on the real cheap path.

- Saving **43.99 cyc/px**
- Compose block **1,771 cyc/call**, i.e. **break-even at 40 opaque px/call**;
  the measured path averages ~210 px/call, ~5x clear
- **Net ~0.357% of runtime** (0.370% saved, 0.013% overhead)

Predicted 0.45-0.5%; actual 0.36%. The earlier 108.10 cyc/px figure was
prof8-era and overstated the baseline.

## What this is NOT, and why

An earlier draft of this note proposed **rewriting the RLE stream** with
pre-mapped colour bytes, cached per (sprite, house). Rejected, for two
independent reasons:

1. **It would materialise a house into shared sprite data.** Any error in the
   cache key means Harkonnen units drawn in Atreides colours. The 16-byte
   version has no state outliving the call: `spritePalRemap` is a stack local,
   `palette` is a local pointer, `flags` is by-value. The bug class does not
   exist.
2. `0` is the RLE escape introducing a run of transparent pixels, so a mapped
   colour of 0 would corrupt the stream.

Also rejected: **pre-decoding sprites to byte-per-pixel**. Unit sprites are
small and sparse (64 pixels in 50 bytes is typical); flattening replaces
per-*run* skipping with a per-*pixel* test. The same mistake produced a measured
regression in `GFX_DrawTile`'s transparent loop. The composed LUT changes only
the lookup, never the data, so run-skipping is fully preserved.

## Verification

Host differential test vs the original two-lookup loop: 20,000 cases, all 6
houses, RTL (`incr == -1`), `remapCount` 1 and 2, sparse and dense rows,
comparing pixel output and final cursor positions. Zero mismatches. Houses are
iterated in sequence against the same sprites, so any cross-call bleed would
have shown.

## Sizing survey (retained, compiled out)

`GUI_SPRITE_PREDECODE_STATS_ENABLE` reports the sprite population at shutdown:

    calls=90233 pairs=90 distinct_sprites=77 overflow=0
    housecol pairs=41 calls=4308 (4% of calls)
    decode all sprites once = 28 KB; per sprite x remap pair = 33 KB

Off by default; the default build contains zero SPRSTAT strings.
