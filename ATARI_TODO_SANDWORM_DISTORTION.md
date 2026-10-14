# Possible ST/STE sandworm distortion simplification

Proposal only; no renderer changes implemented.

The original worm effect uses a sprite mask to copy neighboring destination
pixels, with a changing horizontal displacement. The current profiling
experiment has removed actor-based chunky fallback selection, but native worm
distortion is not implemented yet. Exact reproduction is not required for this
proposal: the ground should visibly look disturbed.

## Native planar scanline shimmer

Replace horizontal displacement with small vertical permutations of terrain
scanlines under the worm mask. Start with alternating adjacent-row swaps
within each 16x16 tile:

- Phase A: swap 0/1, 2/3, 4/5, ..., 14/15.
- Phase B: swap 1/2, 3/4, 5/6, ..., 13/14; leave rows 0 and 15 unchanged.

Each 16-pixel group has four interleaved plane words per row. Selecting another
row requires no horizontal pixel shifts or cross-word carries; all four planes
must move together. Mask alignment, clipping and merging remain necessary.
Adjacent swaps should look less like scrambled strips than unrestricted
pseudo-random row shuffling. Additional small permutations can be evaluated
if two phases are not visually convincing.

## Integration constraints

- Derive every phase from clean terrain, potentially the existing planar tile
  cache, not the previous distorted result. Account for terrain overlays and
  fog; a ground-tile image alone is not always the complete background.
- Retain the existing mask shape and current/two-previous-position wake.
  Keep distortion confined to visible, clipped portions of those footprints.
- Preserve repair-on-first-touch: repair pending terrain before distortion,
  consume its pending bits, then let normal ground units draw above the effect.
  Later terrain repair must not erase an already-published shimmer.
- Moving/disappearing worms must still restore their old distorted footprints.
- Preserve cursor/placement overlays and their backups during publication.
- Use deterministic visual timing without consuming shared game RNG.
- Do not change movement, targeting, damage or swallowing behavior.

The initial scope is sandworms on plain 68000 ST/STE. Sonic Blast also needs a
native replacement now that actor-based fallback selection has been removed.
It remains a separate task and could use scene-row displacement or a cached
stippled wavefront.

Relevant code: `GUI_Widget_Viewport_CanDrawPlanar()`, the sandworm pass in
`GUI_Widget_Viewport_Draw()`, `GUI_Widget_Viewport_RepairTiles()`
(`src/gui/viewport.c`), and the blur cases in `GUI_DrawSpriteInternal()`
(`src/gui/gui.c`). See also `ATARI_PHASE_REVERSAL.md`.

Before enabling the replacement, assess its appearance on textured/uniform
sand and near fog/viewport boundaries, verify old-footprint and overlay
restoration, and profile its cost on the real 68000 path.
