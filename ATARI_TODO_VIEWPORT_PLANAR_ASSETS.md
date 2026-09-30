# Atari ST/STE: planar battlefield asset evaluation

Date: 2026-09-30

Status: approach 3 below is implemented for ordinary ST/STE gameplay,
with a correctness fallback for destination-reading effects. The original
comparative estimates below remain historical estimates, not measured
speedups of this implementation.

## Implemented direct-screen path

- Decode 16x16 terrain/structure tiles at ICN loading through the common
  `_c2p1x1_4_st`. The top-left 16x16 visible area serves as the decode
  target; its planar bytes are captured into the cache.
- Use canonical IBM.PAL for this fixed gameplay quantization. A loading
  screen's current palette is not a cache input. A temporary 128 KiB pair
  lookup is freed after decoding, without changing active UI quantization
  or hardware registers. There is no palette-generation tracking.
- Apply the existing house recoloring rule before conversion, including
  enhanced-mode handling of the upper 0x9x ramp. Only tiles that actually
  use affected palette entries get separate house variants. Other houses
  share the house-0 image.
- Standard ICON.ICN has 389 tiles, 62 affected tiles and 699 stored images:
  89,472 image bytes, 12,448 mask bytes and 4,668 index bytes; total
  **106,588 bytes (104.1 KiB)**. Keep the older logical tile cache for
  non-battlefield callers and legacy scene reconstruction.
- Restore changed map tiles directly into visible planar memory. Opaque
  rows copy four words; transparent overlays merge with their opacity
  mask. Cursor/placement-aware writes update clean background backups,
  then composite placement and cursor over the new scene.
- Both the initial hidden marker and fog pattern 15 (all four direction
  bits set) bypass ground/overlay drawing. Routine planar damage leaves
  their already-black screen pixels untouched. Full reconstruction and
  legacy/off-screen composition initialize them directly to logical black
  12; successful planar scrolling already clears exposed strips to black.
  In standard assets these are different IDs: 124 and opaque-black 123.
- Partial fog uses the cached fog opacity as an inverse ground-blit mask.
  Ground and fog plane words are combined before one screen write per row,
  preserving cursor/placement backups without exposing covered terrain.
  Only redrawn fog-edge tiles use this path; clear terrain stays unmasked.
  No composite tile variants or persistent staging buffer are allocated.
- Shift clearing covers the source/destination bounding viewport minus
  the copied destination, not just the old source minus the destination.
  Diagonal shifts expose extra corners outside the old overlap rectangle;
  leaving those corners untouched restores stray old terrain when hidden
  tiles deliberately skip redraw.
- ST/STE click-to-center actions share Map_SetViewportPosition and reuse
  incremental planar shifting whenever the old and new viewports overlap,
  just like edge scrolling through Map_MoveDirection. Even shifts larger
  than their remaining overlap are supported; non-overlapping jumps rebuild.
- Ordinary unit/turret/explosion sprites use the existing RLE renderer
  into an aligned private canvas. The common c2p converts its rows and
  merges explicit masks, rather than scalar transparent conversion.
  Unshifted normal/mirrored masks are cached for sprite 6 and 111..354;
  they represent source opacity even when remapping produces logical
  colour 0. Masks plus metadata cost about 29 KiB.
- No separate persistent planar battlefield buffer. No whole-background
  conversion after tile/actor composition. Clear only field columns
  0..14 at y=40..199 in both pending sweeps; minimap columns remain queued.
- Do not shift stale SCREEN_1 during a planar scroll. Shift the displayed
  scene and reconstruct exposed tiles. Without a matching planar shift,
  reconstruct the complete scene.
- Visible sandworms, destination-reading blurred units and aircraft
  shadows use the original chunky compositor. Off-screen composition,
  viewport fade-in and unsupported world sprites also use that path.
  Changing paths forces a full terrain/actor reconstruction.
- Allocation failures warn and retain legacy rendering. Tile unload/load
  frees/rebuilds the tile cache; sprite initialization/uninitialization
  owns the mask cache. Hardware palette fades/dimming do not rebuild it.
  TT/Falcon retain their existing compositor.

Validation used actual DUNE.PAK assets and the real 68000 converter:
7,194 native asset checks; on 68000, every cached tile image in both
recoloring modes plus 1,049 tile-blit/sprite checks. Whole-engine viewport
comparisons cover movement/erasure, house remapping, off-screen drawing,
shadow/blur transitions, shifted scrolling, message text, cache reload and
separate field/minimap dirty tracking. Gameplay throughput still needs a
new representative capture.

## Scope and assumptions

- Plain 68000 ST/STE, ST-Low, four interleaved bitplanes.
- Battlefield assets only: terrain, structures, units and battlefield
  effects. Exclude the money counter, minimap, sidebar and other UI assets.
- Assume a single static gameplay palette; palette animation and palette
  cache invalidation are outside this evaluation.
- Preserve pixel-resolution unit movement. "Aligned assets" means one
  unshifted stored version, not snapping units to a 16-pixel grid.
- Estimates are for CPU implementations, without depending on a blitter.

The three alternatives are:

1. Store one unshifted planar version; shift moving sprites at draw time.
2. Store all 16 horizontal phases of planar sprites.
3. Store aligned terrain/structure tiles; retain chunky sprite decoding
   and convert only sprite footprints through a fast masked c2p path.

## The architectural requirement

Changing asset storage alone is insufficient. The current battlefield
compositor draws tiles and sprites into chunky SCREEN_1, then publishes
dirty regions for the deferred c2p sweep. A planar cache is useful only
if the corresponding drawing stays planar through composition and
presentation, instead of being decoded back to chunky.

A persistent planar battlefield backing buffer was one possible replacement:
restore changed background tiles, composite sprites/effects in the existing
order, then copy completed dirty regions to the visible screen. This avoids
showing intermediate background restoration before sprites are redrawn.
Cursor and placement backups must still be maintained through the existing
overlay-aware presentation rules.

The chosen implementation instead composes directly into visible memory,
as preferred for this port. It removes tile conversion from redraws by
caching the resulting planar assets. Intermediate terrain restoration is
not hidden behind a second battlefield buffer.

## Current profile budget and estimated gains

Baseline: `opendune_damage_limited.txt`, after sparse viewport row
presentation and changed-tile structure-animation marking. See
[`ATARI_PROFILE_FINDINGS.md`](ATARI_PROFILE_FINDINGS.md).

| Candidate work | Approximate share of total CPU time |
|---|---:|
| Battlefield terrain/structure tile drawing, including child work | 5.6% |
| Battlefield sprite drawing, including child work | 2.8% |
| Deferred assembly c2p sweep | 10.9% |
| Combined candidate budget | 19.2% |

The sprite figure excludes minimap DrawTile, despite both functions
truncating to the same GST viewport symbol. It also excludes GUI_DrawCredits,
which is the money counter and accounts for much of the headline sprite
renderer cost. Do not use the whole GUI_DrawSpriteInternal cost as a
battlefield optimization budget.

The user identifies this baseline as an especially heavy credit-scroll
session: two returning harvesters rapidly raised credits toward the
greater-than-1000-credit mission goal while the battlefield was mostly
static. The whole money-counter subtree costs about 32.5%, and identified
minimap redraw/presentation paths another 10.2%, despite a visually
unchanged minimap with radar inactive. See the detailed capture-context
breakdown in ATARI_PROFILE_FINDINGS.md. Do not treat these battlefield
percentages as representative of general combat.

The sweep backend is shared with other screen regions; its 10.9% is a
capture-specific candidate budget, not a permanent battlefield-only
attribution for every workload. These figures combine distinct tile/sprite
call edges with assembly conversion, not overlapping parent totals.

| Approach | Estimated total CPU saving | Equivalent CPU-bound throughput gain |
|---|---:|---:|
| 1. Unshifted planar assets, shifted when drawn | 7-11% | 8-12% |
| 2. All 16 horizontal phases cached | 10-14% | 11-16% |
| 3. Planar tiles, fast masked c2p for chunky sprites | 6-10% | 6-11% |

These are engineering estimates, not measured results. Replacement blits,
masking, clipping, shifting and presentation retain real costs. Eliminating
the entire 19.2% candidate budget would yield only about 24% higher
CPU-bound throughput: `speedup = 1 / (1 - saved_fraction) - 1`.
The practical result must be lower.

The ranges overlap because sprite dimensions, opacity, redraw frequency
and implementation quality are not yet measured for this proposed path.
A busier battlefield could increase the value of sprite pre-shifting.
Do not interpret throughput estimates as guaranteed displayed FPS or
extrapolate the captures' approximately 16 MHz timing directly to an
8 MHz machine.

## 1. One unshifted planar version

Tiles have favorable alignment already. GUI_Widget_Viewport_Draw places
them at `left = x << 4`; structures are composed from ground tiles, not
large independently positioned building sprites. Normal battlefield tile
placement therefore needs no horizontal shift. Transparent map overlays
still need opacity masks.

An opaque 16-pixel row contains eight planar bytes. A tight 68000 copy
could take approximately 50-80 cycles including ordinary row-loop
overhead, versus about 645 cycles for the current assembly conversion
alone, before counting the preceding chunky tile drawing. This is a
local operation estimate, not an equivalent whole-game speedup.

Moving sprites have arbitrary horizontal phase. Their draw path must
combine adjacent source words using runtime shifts, for both the four
color planes and the opacity mask. This costs a few hundred cycles per
output group rather than a simple copy; exact cost depends on register
allocation, clipping and handling edge groups.

This removes per-draw RLE traversal, pixel expansion and subsequent c2p
for cached ordinary sprites, but shifting consumes part of the gain.
Do not assume a large additional total saving when battlefield sprite
drawing is only 2.8% of this capture.

## 2. All 16 horizontal phases

Select the phase using the resolved sprite top-left x coordinate `& 15`,
after centering and component offsets. Group handling is:

- Empty opacity word: skip.
- Full opacity word: copy the four plane words.
- Partial opacity word: mask-merge into the existing planar scene.

A tight pre-shifted masked merge might cost roughly 130-200 cycles per
occupied group, including ordinary addressing/loop overhead. This avoids
per-draw RLE traversal, color-pixel expansion and horizontal shifting.
These operation costs require a target implementation and measurement.

### Memory cost

Assuming four color planes plus one opacity plane, each stored group
uses ten bytes per scanline. For width `w`, height `h` and phase `p`:

`bytes(p) = 10 * h * ceil((w + p) / 16)`

| Asset dimensions | One aligned version | All 16 phases |
|---|---:|---:|
| 16x16 | 160 bytes | 4,960 bytes |
| 24x24 | 480 bytes | 9,360 bytes |
| 32x32 | 640 bytes | 15,040 bytes |

These figures exclude metadata and other variants. Expansion can exceed
16 times the aligned version: a shifted asset can spill into an additional
edge group. One hundred distinct 24x24 variants would use about 914 KiB
before additional frame, house or mirror variants.

Opacity masks can be shared between color variants. Vertical mirroring
can reuse rows in reverse order; horizontal mirroring needs additional
processing or cached transformed data. Empty groups can be omitted, but
that adds indexing/iteration costs. Asset/frame sharing is essential:
do not allocate copies per unit instance or a full Cartesian product of
unit statuses and components.

Blanket pre-shifting is therefore unattractive without a measured RAM
budget. Selectively cache hot frames and phases, or the moving sprites
that demonstrably amortize the memory cost. The likely incremental gain
over a tile-first path is a few total CPU percentage points in this scene,
not another several-fold whole-game improvement.

## 3. Aligned planar terrain/structures, chunky sprites

This is feasible and the preferred first architectural step. Here "tiles"
includes terrain as well as structure ground frames. A buildings-only
subset has a smaller, currently unquantified budget.

The mixed compositor would:

1. Restore changed terrain/structure tiles into the planar backing buffer.
2. Decode ordinary sprites into private chunky scratch.
3. Convert their footprints and opacity-mask-merge into the planar scene.
4. Publish completed dirty regions with correct cursor/placement handling.

There is no final conversion of restored background tiles; only sprite
footprints need c2p. Animated structure ground tiles use the same tile
path and need no pre-shifted variants.

**Do not simply reuse the current scalar transparent presenter.**
Video_Atari_ConvertGroupTransparent inspects individual pixels and constructs
plane bits in C. Its cost can consume the background conversion savings.
The estimates above assume an efficient batched path: fast conversion to
temporary planar data followed by mask merges, or fused conversion and
masked stores. Skip zero-mask groups and avoid one assembly call per tiny
group. The current assembly's fixed strides must also be handled correctly
for private sprite scratch and temporary planar destinations.

The existing 389-tile set would need about 48.6 KiB of planar color data,
plus at most 12.2 KiB of opacity masks if every tile had one. A packed
240x160 planar battlefield backing buffer adds 18.75 KiB; a full-screen
320x200 layout would instead use 31.25 KiB.

Whether the current chunky decoded-tile cache can be removed depends on
preserving non-battlefield GFX_DrawTile callers. Do not count its memory
as freed while retaining it for fallback rendering.

## Correctness and interaction with stripe invalidation

Opacity must come from actual sprite RLE transparency, before color
mapping. A source pixel mapped to planar color zero can still be opaque.
Use separate masks; color zero is not a transparency test.

Pre-baked ordinary sprites do not cover destination-dependent effects.
Aircraft shadows remap background pixels; sandworm blur can sample adjacent
background pixels. They need planar equivalents or fallback regions whose
chunky contents are correctly reconstructed. A stale SCREEN_1 cannot serve
as that fallback source once battlefield composition has moved to planar.

Preserve draw order, clipping, selection graphics, old/new footprint
erasure, scrolling, modal/transition behavior and the currently selected
planar screen base. Do not retain a later chunky sweep that overwrites
completed planar battlefield work with stale SCREEN_1 pixels.

Planar assets do not narrow invalidation by themselves. Broad tile
restoration still redraws unnecessarily and can touch cursor backups.
The [unit stripe invalidation proposal](ATARI_TODO_UNIT_STRIPE_INVALIDATION.md)
is complementary, but its savings overlap with removing background c2p:
do not add the two estimated percentages directly.

## Recommended direction

Start with option 3: aligned planar terrain/structure tiles plus an
efficient mixed sprite path and persistent planar composition.
Then selectively add option 2 for measured hot moving sprites.
Option 1 remains a lower-memory alternative for uncached sprite phases.

Before implementation, measure the battlefield frame/variant inventory,
cache RAM and actual sprite-footprint work. Validate any prototype against
the existing renderer on 68000, including overlapping units, clipped and
mirrored sprites, structure animations, effects, scrolling and overlays.
Measure both operation costs and matched gameplay captures.

## Relevant code

- `src/gfx.c:544-710`: current decoded chunky tile fast path and fallback.
- `src/gui/viewport.c:496-1100`: battlefield composition, actor effects,
  minimap handling and dirty-region publication.
- `src/gui/gui.c:1197-1911`: RLE sprite rendering, scratch/direct paths and
  destination-dependent blur behavior.
- `src/video/video_atari.c:1880-1955`: plain and overlay-aware plane merges.
- `src/video/video_atari.c:2199-2409`: fast c2p presentation and scalar
  masked/transparent conversion.
- `src/video/video_atari.c:2801-2868`: deferred dirty-block conversion.
- `ATARI_TODO_TILE_PREDECODE.md`: existing chunky tile cache, measured
  tile inventory and prior transparent-loop pitfalls.
