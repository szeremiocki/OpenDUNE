# Atari ST/STE `SCREEN_0` planarization migration

Date: 2026-09-25

The original analysis below is a historical planning snapshot. The current
branch has direct planar presentation and independent SCREEN_1 viewport
conversion; it no longer follows every screen-role assumption below.

## Remaining dirty-sweep diagnostics (2026-09-30)

`src/video/video_atari.c` provides optional `VIDEO_ATARI_SWEEP_LOG` diagnostics.
One synchronous `Warning()` report is written to `error.log` approximately
every five seconds of elapsed time, at the end of a video tick. No per-blit
logging is performed. Totals are accumulated locally within the band/run
loops and folded into the tick counters once per sweep.

The report separates:

- `legacy`: actual conversions from the old `g_dirty_blocks` sweep, including
  its non-palette full-width fallback. On current ST/STE builds this sweep
  reads SCREEN_1, despite being triggered by SCREEN_0 dirty state.
- `viewport`: actual conversions from `g_dirty_blocks_viewport`, whose pixels
  are already composed in SCREEN_1. This path is intentionally independent
  of SCREEN_0, so its use alone is not evidence of an incomplete migration.
- `repaint`: full conversions forced by `s_screen_needrepaint` (palette
  re-quantization), separated from normal dirty-block activity.

The header gives elapsed milliseconds, total video ticks, ticks doing any
sweep conversion (`active`), ticks doing none (`idle`), total converted pixels,
average pixels per video tick, that average as a percentage of a 320x200
frame, and the peak combined pixels in one tick. Each category gives its
active tick count, actual assembly-call count, pixel total, mean pixels per
active tick and peak pixels in a single tick.

For periods with viewport conversion, additional position diagnostics give
`vp-area` pixel totals for battlefield (x=0..239, y=40..199), minimap
(x=256..319, y=136..199) and everything else. These three totals sum to the
viewport pixel total.

`vp-field` entries are ordered by the ten 16-pixel tile rows, starting at
y=40 (last row y=184..199). `row-px` gives the work in each row.
`mask-union` ORs every converted battlefield mask in the reporting period;
bit n means column x=16*n..16*n+15. It is not a simultaneous dirty mask.
`widest-mask` is one actual converted band's mask with the largest number
of set bits seen in that tile row (first occurrence wins ties), so it
distinguishes a genuinely wide conversion from accumulated movement across
different columns. Mask aggregation runs once per converted band, not per
pixel or scanline.

Counts measure conversion workload, not unique screen coverage: a pixel
converted by both sweeps counts twice, and combined frame percentages can
exceed 100%. A dirty flag with an empty block mask contributes no conversion.
Immediate presents, masked edge merges and cursor composition are excluded;
the report does not give the percentage of *all* rendering done by sweeps.

Diagnostics are disabled by default. Enable with `-DVIDEO_ATARI_SWEEP_LOG=1`
for coverage logging; leave disabled for timing/profiling because synchronous
log output can introduce a brief pause and distort performance.
The release optimizer also removes the unused sweep bookkeeping when disabled.
The older, more verbose `VIDEO_C2P_STATS` instrumentation remains disabled.

### Observed capture before position diagnostics

The 2026-09-30 `error.log` capture contains 36 reporting periods spanning
182.980 seconds. The legacy sweep converted zero pixels in every period.
There was one 64000-pixel forced repaint during initial loading; all later
logged conversion came from the independent viewport sweep.

Using the last 20 periods to exclude the initial loading/selection phases:
101.445 seconds, 2872 video ticks, 765 active sweep ticks (26.64%),
1279 c2p calls and 4540416 converted pixels. Mean work was 1580.9 pixels
per video tick (2.47% of the full screen), or 5935.2 pixels per active tick.
The largest tick converted 33280 pixels. The busiest five-second period
in the whole capture converted 584960 viewport pixels in 5.035 seconds,
with activity in 64 of its 72 ticks.

The two current callers of `GFX_Screen_SetDirtyViewport()` are battlefield
row presentation in `src/gui/viewport.c` and full minimap refresh in
`src/map.c`. In that capture, battlefield presentation marked the span from
`minX[i]` through `maxX[i]` in a 16-pixel tile row. This can include unchanged gaps between
separated dirty tiles; masks/positions can locate the work but do not prove
which individual pixels could safely be skipped. Moving units, effects and
map/structure changes feed the composed battlefield image upstream.
The new position diagnostics distinguish that work from minimap refreshes.

Changing this independent sweep to immediate presentation alone would not
eliminate its c2p work: it already reads SCREEN_1 without copying through
chunky SCREEN_0. Remaining optimization concerns conversion area, batching,
redundant updates or genuinely planar rendering, not merely scheduling.
Zero legacy activity is evidence for this capture, not proof that its
fallback can safely be deleted for every screen and execution path.

### Confirmed conservative viewport marking before gap removal (2026-09-30)

Investigation of stationary-cursor blinking confirms that presentation can
cover the mouse even when no moving sprite visually touches it:

- `Unit_Move()` calls `Unit_UpdateMap(0)` before changing position and
  `Unit_UpdateMap(1)` afterward (`src/unit.c:1351,1512-1514`).
  The ground-unit dispatch is `{2,3,0}` (`src/map.c:38`), so the old footprint
  invokes Unit_RemoveFromTile and the new footprint Unit_AddToTile.
- Ground-unit invalidation uses `dimension + 3`; harvester dimension is 24,
  giving radius 27 normally (`src/table/unitinfo.c:1238`,
  `src/unit.c:2514`). Smoking/big-projectile cases and a harvester whose
  actionID is ACTION_HARVEST force radius 33 (`src/unit.c:2516`). A harvester
  visually returning to a refinery does not by itself establish its actionID.
- `Map_UpdateAround()` marks sampled **whole tiles**, not the actual sprite
  rectangle (`src/map.c:1075-1152`). Radius 27 can select a 3x3 tile set
  near a tile centre. Radius 33 explicitly selects a 5x5 set.
  Harvesters repeat this work around targetLast and targetPreLast, not
  just their current position (`src/unit.c:2520-2524`).
- Old-footprint removal calls `Map_Update(tile,0,false)`, which adds another
  eight-neighbour halo (`src/unit.c:2530-2544`, `src/map.c:614-647`).
  With clean dirty state and an interior visible tile, a radius-27 3x3
  footprint can therefore produce a 5x5 viewport-dirty union (80x80 pixels).
  Type-2 appearance updates also dispatch to Map_Update type 0.
  This is conservative invalidation; it does not prove every marked tile
  contains changed pixels.
- `GUI_Widget_Viewport_Draw()` reduces all marked columns in each tile row
  to minX/maxX (`src/gui/viewport.c:513-538`), then presents the entire span
  with **height 16** (`src/gui/viewport.c:1004-1045`). Separated unit patches
  therefore include the clean horizontal gap between them. The active
  viewport-message overlay can additionally widen row 6 to its full span
  (`src/gui/viewport.c:980-983`).

For example, dirty patches at columns 2 and 12 cause presentation of
columns 2..12 in that row, including a cursor at column 7. Combined with
the neighbour halo, the cursor can be one or more tile rows above the
moving units and several columns away from either visible sprite, yet
still be overwritten by a c2p rectangle.

The per-scanline dirty backend is already capable of vertical precision:
`GFX_Screen_SetDirtyViewport()` rounds only horizontal groups and marks
exactly [top,bottom) (`src/gfx.c:405-419`). The assembly accepts an arbitrary
line count. Band batching merges only consecutive equal masks and does
not add blank rows. Full 16-line marking is imposed upstream by the tile
producer, not by ST planar hardware or c2p.

After a batched opaque conversion, PlanarFinishRun synchronously recomposes
the mouse, but only after the whole run has finished. The shifter can scan
the cursor-free intermediate data during that interval. Conservative
conversion coverage is thus consistent with the reported stationary blink;
the exact blits responsible have not been logged.

Possible follow-up: relate old/new unit footprints and final row spans to
the actual drawn cursor rectangle, and count overlap groups whose newly
converted background is unchanged. Existing spatial sweep logs show final
conversion masks, not the original producer or actual sprite bounds.
Do not merely shrink Map_UpdateAround: it also maintains unit/tile
registration, and the current compositor restores full background tiles
and redraws overlapping objects. Precise presentation bounds must preserve
old/new sprite extents, harvester history, selection/effects, terrain changes
and overlap composition. No rendering code was changed in this investigation.

### Sparse tile-row presentation (2026-09-30)

The ST/STE direct viewport path now retains a 15-bit dirty-column mask for
each of its ten tile rows, recording both already-invalidated viewport
tiles and terrain tiles redrawn from dirty-minimap flags. Presentation
marks only contiguous runs of those columns, rather than the enclosing
minX/maxX span. A clean column between two patches is no longer marked
solely because both patches share a tile row.

The existing Video_Tick sweep remains unchanged: it merges consecutive
scanlines with identical masks into bands, then converts each contiguous
horizontal run in a band with one multi-line c2p call. It never extends a
run across a clean column or a band across clean scanlines. Different
adjacent masks remain separate bands; this does not introduce a new global
rectangle-packing algorithm.

Forced redraw still marks every battlefield column. Scrolling without a
successful planar-side shift still presents full-width rows; a successful
shift keeps only the marked edge tiles. The viewport-message row still
marks all 15 columns. Fade-in, draw-to-main-screen behavior, minimap refresh
and non-direct presentation retain their previous paths. Optional eager-row
statistics count actual dirty/copied columns on the direct path, not the
enclosing span.

Vertical marking is still 16 lines per tile row, and unit invalidation,
registration, history footprints and off-screen composition are unchanged.
This removes horizontal gap inflation only; it does not establish that
every remaining invalidated tile needs conversion or that cursor blinking
is completely eliminated.

Cross-target regression used the actual terrain/marking and presentation
sections, dirty-rectangle helpers, sweep and c2p assembly under an 8 MHz
68000 in Hatari. All 32768 possible battlefield row masks preserved exact
coverage; producer cases covered mixed viewport/terrain flags, the right
edge, forced redraw, both scroll paths, messages, fade, idle and non-direct
presentation. A sparse multi-row case generated three calls: 32x48 and
16x48 separated horizontally, then 32x16 after a clean tile row. Planar
pixels matched the reference, including unchanged pixels in both gaps.

### Structure animation changed-tile marking (2026-09-30)

On ST/STE, `Animation_Func_SetGroundTile()` now uses the existing
non-neighbor `Map_Update(...,4,false)` for changed structure animation
tiles. Its existing tile-ID comparison still skips unchanged tiles in the
structure layout; minimap queuing, house assignment, overlay handling and
selection repaint bookkeeping are preserved.

There is a deliberate conservative exception: if a unit or active explosion
is centered in the changed tile's 3x3 neighborhood, retain type 0. The
existing compositor uses center-tile dirty flags to choose neighboring
sprites for recomposition after terrain restoration. This guard avoids
erasing an overlapping unit/effect without introducing the larger
presentation/reconstruction separation described in the unit proposal.
Already-dirty terrain skips the actor scan because both update types
deduplicate that event. The guard is conservative, not a precise sprite
intersection test; animation updates near actors can still have a halo.

Only changed ground-frame updates use this rule. Animation stop/abort,
structure creation/state rebuilding, overlay animations and non-ST/STE
paths keep their existing behavior.

An isolated changed tile now publishes 256 pixels rather than the
2304-pixel 3x3 halo. Cross-target regression exercised the actual animation,
Map_Update and viewport marking code under an 8 MHz 68000 in Hatari:
unchanged frames, all neighboring actor positions, distant/inactive
effects, non-direct mode, visibility, selection, overlay retention and
turret rotation. Existing sparse-row and real-c2p batching tests also pass.
The `opendune_damage_limited.txt` comparison observed 17.14% fewer assembly
pixels per video callback, with modest throughput improvement. Differing
fade phases and cursor footprints prevent an isolated speedup claim.

### Opaque money-counter batch presentation (2026-09-30)

On ST/STE, GUI_DrawCredits now starts an explicitly opaque sprite batch.
Generic GUI_DrawSprite_BeginBatch remains transparent by default;
GUI_DrawSprite_EndBatch selects opaque Video_Atari_PresentChunky only for
the marked batch and resets the mode afterward. Rejected presentation
requests produce a Warning rather than silently losing the update.

Widget 5 is x=256, y=4, width=64, height=9: four complete planar groups,
with an even 64-byte source stride. The counter background in the local
SHAPES.SHP is 84x9, but its transparent columns are exclusively x=64..83,
outside the widget's clipping boundary. The visible 64x9 region and all
8x8 digit/blank sprites are opaque. Therefore the completed private batch
needs no content-transparent conversion.

This replaces the scalar transparent presentation with existing assembly
c2p, preserving the single completed-batch update, cursor/placement backups
and dirty-block clearing. The packed source uses nine row-wise assembly
calls, each converting four groups. Non-ST/STE rendering is unchanged.
Digit-phase caching is not part of this change.

A target regression compared both presentations for 96 asset-derived
counter frames covering all scroll phases, increasing/decreasing credits,
leading blanks, decimal carries and high values. It passed 242 pixel
checks on 8 MHz 68000 Hatari with real c2p, including cursor/placement
backups, subsequent generic transparent batches, opaque source color zero,
dirty-state clearing and failed-request reporting. Performance improvement
is now measured in `opendune_credit_scroll.txt`: inclusive counter
presentation cost falls from about 146,053 to 34,070 cycles per completed
batch (-76.67%). Observed video callback and unit-loop rates rise 20.93%
and 12.93%, respectively. Counter updates/second rise 29.01%, a desirable
consequence of reduced presentation cost. An extra fade tail prevents a
perfectly matched replay comparison. Details are in ATARI_PROFILE_FINDINGS.md.

### Decoded glyphs in a taller credits buffer (2026-09-30)

The next counter optimization uses decoded glyphs rather than storing every
scroll phase. After SHAPES.SHP loads, GUI_InitCreditsCache renders the visible
64x9 background and all eleven 8x8 digit/blank glyphs through the existing
private-buffer sprite renderer. The persistent cache is 1280 bytes
(1.25 KiB), storing logical palette indices; RGB/quantization changes still
apply normally during final c2p. Every sprite-load initialization rebuilds
the cache instead of trusting old sprite pointer addresses.

For the standard ST/STE counter, updates copy the background and whole glyphs
into a word-aligned 64x24 private buffer. The visible 64x9 slice starts eight
rows down. Old/new glyphs use the original animation offsets, but extend
above or below the slice without clipping. Only the visible slice reaches
the opaque presenter. The buffer is 1536 bytes, 512 bytes larger than the
previous allocation; no phase-image cache or planar asset cache is needed.

The six 8-pixel-wide digit cells have a uniform background pen in the local
assets, but the full published 64x9 rectangle also contains decorative
spacing/edge columns with other pens. Copying the decoded background
preserves these exactly, without interpreting the whole rectangle as a
single-color fill.

Cache initialization checks dimensions and nonzero decoded pixels.
Missing, incompatible or transparent sprites produce a Warning and retain
generic sprite drawing; nonstandard widget dimensions also keep the old
clipped path. Non-direct machines retain their existing renderer. Private
GUI_DrawSpriteToBuffer rendering no longer marks or attributes screen
damage: decoding assets does not alter any screen.

Animation arithmetic, update throttling, mode reset/force behavior,
g_playerCredits, sounds, leading spaces, carries and uint16 wrap behavior
are unchanged. A 68000 regression compared the actual old/new counter
functions and sprite renderer with real c2p across 687 checks, including
signed phases, large credit changes, overlays, reloads and fallbacks.
Cache-hit updates made no sprite-renderer calls. An isolated 80-update
forced-draw benchmark took 460 versus 166 200-Hz ticks at 8 MHz, about 64%
less time for the complete tested counter update. This is not a measured
whole-game speedup. The subsequent `opendune_credit_scroll2.txt` gameplay
capture confirms that counter sprite-renderer calls disappear, effective
whole-counter cost per completed update falls 60.77%, and counter
updates/second rise 47.40%. Presentation cost per update is unchanged.
Observed callback rate rises 25.64%; the missing earlier fade tail and
different capture duration prevent an exact isolated FPS claim. Detailed
comparison is in ATARI_PROFILE_FINDINGS.md.

## Goal

On DOS, `SCREEN_0` is the visible 320x200 8bpp VGA framebuffer, so the game
correctly treats it as the authoritative displayed image. The Atari port
currently preserves that storage model:

```text
SCREEN_1/2/3 composition
        |
        v
chunky 8bpp SCREEN_0
        |
        v
dirty-region c2p
        |
        v
ST-Low 4-plane display memory
```

The proposed Atari-specific migration keeps the semantic invariant that
`SCREEN_0` is the authoritative visible surface, but changes its physical
representation to the ST/STE planar framebuffer:

```text
SCREEN_1/2/3 logical 8bpp composition
        |
        v
direct logical-to-planar presentation
        |
        v
planar SCREEN_0 / visible display
```

The main expected saving is removal of the intermediate copy into chunky
`SCREEN_0` and the subsequent read of the same pixels by c2p. Most complex
gameplay composition already happens in logical 8bpp work buffers,
especially `SCREEN_1`.

## Confirmed screen roles

- `SCREEN_0`: currently the authoritative visible chunky image and c2p
  source.
- `SCREEN_1`: persistent off-screen composition/work buffer for the
  viewport, widgets, factory screens, strategic map, loaded images and
  animation frames.
- `SCREEN_2`: temporary backup and modal/cutscene workspace.
- `SCREEN_3`: credits/intro storage; documented as never active.

The active-screen mechanism is only software routing. `SCREEN_ACTIVE`
resolves to `g_screenActiveID`; it does not imply storage ownership or
synchronization.

## Important architectural conclusion

The migration should begin at presentation boundaries, not by immediately
rewriting every sprite, tile, text and primitive renderer.

The first useful target is:

```text
SCREEN_1 -> SCREEN_0
```

becoming:

```text
SCREEN_1 logical pixels -> ST/STE planar display
```

This covers much of the viewport and UI while retaining existing 8bpp
composition semantics. Direct `SCREEN_0` drawing can then be handled as a
smaller second phase.

During migration, a chunky `SCREEN_0` compatibility shadow may be retained
for unresolved readers. A fused presenter could update the shadow and
planar output in one operation, avoiding a later c2p reread. Regions can
stop updating the shadow once all of their readback dependencies have been
removed.

## Known `SCREEN_0` readbacks

These are the currently identified blockers to removing chunky `SCREEN_0`
storage entirely.

### Display conversion

- `src/video/video_atari.c`: `Video_Tick()` reads dirty regions from
  `SCREEN_0` as input to `_c2p1x1_4_st`.
  - Replacement: direct planar presentation/rendering.

### Viewport reuse

- `src/gui/gui.c`: viewport scrolling copies the surviving visible region
  from `SCREEN_0` back into `SCREEN_1`.
  - Replacement: scroll the persistent `SCREEN_1` viewport in place.

	- fallback for quick POC: force redraw there

### Strategic-map workspace reconstruction

- `src/gui/gui.c`: copies the complete displayed strategic map from
  `SCREEN_0` back to `SCREEN_1`.
- `src/gui/gui.c`: captures a strategic-map sprite/background rectangle
  from `SCREEN_0` into `SCREEN_1`.
- `src/gui/gui.c`: copies the strategic-map bottom text strip from
  `SCREEN_0` into `SCREEN_1`.
  - Replacement: keep the logical strategic-map image current in
    `SCREEN_1` throughout presentation and animation.

### Factory workspace reconstruction

- `src/gui/gui.c`: copies a sidebar strip from `SCREEN_0` into `SCREEN_1`
  while preparing the factory window.
  - Replacement: preserve that region in the `SCREEN_1` interface
    workspace/template.

### Modal and transition backups

- `src/gui/mentat.c`: saves the visible top 40 lines from `SCREEN_0` into
  `SCREEN_2`.
- `src/gui/security.c`: saves the visible top 40 lines from `SCREEN_0` into
  `SCREEN_2`.
- `src/gui/security.c`: saves the rectangle below the security dialog from
  `SCREEN_0` into `SCREEN_2`.
- `src/gui/gui.c`: modal-message background backup through
  `GFX_CopyToBuffer()`.
- `src/gui/widget_click.c`: Options/window background backup through
  `GFX_CopyToBuffer()`.
  - Replacement: Atari-specific planar rectangle save/restore, or retained
    logical templates where appropriate.

### Legacy mouse paths

- `src/gui/gui.c`: mouse background backup through `GFX_CopyToBuffer()`.
- `src/gui/gui.c`: direct chunky `SCREEN_0` reads used by legacy mouse
  restore/compare logic.
  - Replacement: bypass these paths when the Atari direct-planar cursor is
    active.

### Cursor preload scratch use

- `src/video/video_atari.c`: cursor icon preloading temporarily renders
  into and reads a small area of chunky `SCREEN_0`.
  - Replacement: use a private chunky scratch buffer.

## Confirmed non-blocker: `GFX_GetPixel()`

`GFX_GetPixel()` is not currently a `SCREEN_0` reader:

- the factory-window sample is taken while `SCREEN_1` is active;
- the strategic-map sample is taken while `SCREEN_1` is active;
- `GUI_Screen_FadeIn2()` explicitly activates its source before reading,
  and every current caller passes `SCREEN_1` as the source.

No planar `GFX_GetPixel()` implementation is therefore required for the
currently known call graph.

## Direct `SCREEN_0` writers still to classify

Replacing presentation copies does not cover every visible update.
`SCREEN_0` can still be modified directly through:

- `GUI_DrawSprite()`;
	only mouse sprite and mentat.c drawings; cutscene.c usage is into SCREEN_1;
	sems that all there is to do is switching 'GUI_DrawSprite(SCREEN_0,' case to planar
- `GFX_DrawTile()`;

- text/glyph rendering;
- `GFX_PutPixel()`;
- lines, borders and filled rectangles;
- WSA frame drawing;
- raw `GFX_Screen_Get_ByIndex(SCREEN_0)` or `GFX_Screen_GetActive()`
  pointers;
- special cutscene and transition loops.

Many of these functions usually render into `SCREEN_1`, but some call
sites intentionally draw directly to visible `SCREEN_0`. Those call sites
must be inventoried and divided into:

1. operations that can be redirected to an existing logical workspace;
2. operations that need a planar-native primitive;
3. exceptional effects that temporarily retain a chunky shadow.

-- I don't see why we would restrain from rendering into planar if
these functions chose SCREEN_0 as active;
## Proposed migration phases

1. **Instrument presentation and direct writes**
   - Measure visible pixels delivered through `SCREEN_1 -> SCREEN_0`
     copies versus direct `SCREEN_0` rendering.
   - Record which logical source regions require later readback.

2. **Add direct planar presentation**
   - Convert opaque `SCREEN_1 -> SCREEN_0` rectangles directly from logical
     indices to planar output.
   - Initially keep the chunky `SCREEN_0` shadow synchronized.
   - Preserve dirty/block semantics until equivalence is established.

3. **Remove viewport readback**
   - Make scrolling reuse `SCREEN_1` directly.
   - Keep `SCREEN_1` authoritative for viewport composition.

4. **Remove strategic-map and factory readbacks**
   - Preserve their complete logical state in `SCREEN_1`.
   - Stop reconstructing work buffers from the visible result.

5. **Replace modal backups**
   - Add planar rectangle save/restore for Atari.
   - Bypass legacy chunky mouse backups when direct-planar cursor mode is
     active.

6. **Handle direct visible drawing**
   - Redirect suitable drawing to `SCREEN_1` followed by presentation.
   - Add planar-native fills, lines, text or cached sprites where this is
     measurably worthwhile.

7. **Retire the chunky shadow**
   - Once no Atari path reads or byte-writes chunky `SCREEN_0`, make the
     planar display the only physical `SCREEN_0`.
   - Remove normal-gameplay c2p and its dirty conversion pass.

## Correctness constraints

- Logical 8bpp buffers contain palette indices, not hardware pen numbers.
  Representation boundaries must remain explicit.
- Destination-dependent sprite modes, transparency, remaps and blur must
  preserve their current composition semantics.
- The visible planar layout must remain compatible with the direct-planar
  mouse cursor, placement preview and FPS overlay.
- Dirty tracking cannot mark a region planar-current if a later direct
  writer changed its logical contents.
- Screen shake/double-buffer offsets must continue to select the correct
  planar base.
- Plain ST remains supported; STE Blitter acceleration may be optional but
  cannot be required for correctness.

## Current assessment

The migration appears feasible. The number of genuine `SCREEN_0` readbacks
is limited and substantially smaller than the set of rendering operations.
The most promising route is to preserve existing logical composition in
`SCREEN_1`, introduce direct planar presentation, then eliminate readbacks
and direct visible writers incrementally. Treating the planar framebuffer
as `SCREEN_0` immediately, before these dependencies are removed, would
cause byte-oriented renderers to corrupt planar memory.

## Implementation status: present mode (branch `atari-st-planar-present`)

The first increment of the plan above is implemented. It is called
*present mode*: an opt-in enclave inside which every rectangle written to
chunky `SCREEN_0` is converted to the planar screen at the moment it is
written, instead of a tick later by `Video_Tick()`'s c2p pass.

It went through two designs. The first was a **bypass**: hooked copies
skipped the chunky write entirely and `Video_Tick()` skipped its c2p pass,
on the theory that a sequence could be audited to never read `SCREEN_0`
back. That was reverted; see *Why bypass was abandoned* below. The design
in the tree is **write-through**.

### Mechanism

`src/video/video_atari.c` gained a present-mode section (immediately
before `Video_Tick()`):

| Function | Role |
| --- | --- |
| `Video_Atari_PresentEnter()` / `Video_Atari_PresentLeave()` | Open/close an enclave. |
| `Video_Atari_PresentActive()` | Query, used by the hooks. |
| `Video_Atari_PresentChunky()` | Convert a rectangle of an 8bpp source (any stride, any x/width) into the planar screen via `_c2p1x1_4_st`. |
| `Video_Atari_PresentFill()` | Flat-colour planar fill, used for clears. |
| `Video_Atari_PresentPalette()` / `…PaletteRange()` | Install a quantization ahead of drawing (see below). |

`_c2p1x1_4_st` writes whole 16-pixel groups and overwrites them
completely, so a rectangle whose left edge or width is not a multiple of
16 is split: the aligned interior goes through the fast path, and the (at
most two) partially covered edge groups go through
`Video_Atari_PresentGroupMasked()`, which builds the four plane words a
pixel at a time and merges them under
`mask = (0xFFFF >> a) & (0xFFFF << (16 - b))`. It reads only source pixels
inside the rectangle, so tightly packed WSA frame buffers are safe. This
was verified exhaustively on the host: 51,360 x/width combinations, 51,150
of them exercising the masked path, zero mismatches against a reference
converter.

`Video_Tick()` runs its normal dirty-rectangle pass in present mode. What
makes the presentation worth anything is that each hook calls
`GFX_Screen_ClearDirtyRect()` for the rectangle it converted, dropping the
corresponding bits from `g_dirty_blocks[]`. Only *whole* 16-pixel blocks
are dropped — a partially covered block may still hold dirty pixels
outside the rectangle. The dirty bounding box is deliberately left alone;
`Video_Tick()` batches scanlines by block mask and skips bands whose mask
came out zero, so a stale box costs a test per line and no conversion.

### Hooks

Presentation is routed implicitly rather than through new call sites, so
that the 36 existing `dst == SCREEN_0` copy sites need no edits. Each hook
runs *after* the chunky write it shadows, and reads the freshly written
bytes:

- `GFX_Screen_Copy()` (`src/gfx.c`) — presents when `dst == SCREEN_0`,
  reading the destination rectangle it just filled.
- `GFX_ClearScreen()` (`src/gfx.c`) — present-fills when `dst == SCREEN_0`.
- `WSA_DisplayFrame()` (`src/wsa.c`) — presents the frame rectangle from
  chunky `SCREEN_0` after the frame has been composed there, and after the
  `GFX_Screen_SetDirty()` call whose bits it then clears. Hooking here
  rather than in `WSA_DrawFrame()` covers the in-place XOR decode variant
  (`displayInBuffer == false`) as well as the buffered one.

Anything not hooked — `GUI_DrawText_Wrapper()`, `GUI_DrawFilledRectangle()`,
sprite blits — simply leaves its dirty bits standing and reaches the screen
through the ordinary c2p pass, exactly as outside present mode. Present
mode is therefore an accelerator, never a correctness requirement.

### Why bypass was abandoned

The bypass design failed in the intro in a way that the `SCREEN_0`
readback inventory earlier in this document does not capture: **chunky
`SCREEN_0` is an XOR accumulator**, not just a source of readbacks.

`WSA_DisplayFrame()` with `displayInBuffer == false` decodes each frame by
XOR-ing its format-40 deltas into the destination screen, so it both reads
and writes `SCREEN_0`. Worse, WSA files may carry no first frame at all
(`firstFrameOffset == 0`), in which case they continue from whatever the
*previous* animation left in `SCREEN_0`. `INTRO.PAK` has three of these:

| Step | File | Frames | First frame? |
| --- | --- | --- | --- |
| 15 | `INTRO7A` | 27 | yes (`FADEIN`) |
| 16 | `INTRO7B` | 22 | **no** |
| 17 | `INTRO8A` | 16 | yes (`FADEIN`) |
| 18 | `INTRO8B` | 19 | **no** |
| 19 | `INTRO8C` | 29 | **no** |

Under bypass these accumulated against a `SCREEN_0` that no hooked copy
had written, so the picture progressively decayed into black with only
moving edges left. The observed symptom matched the table exactly: the
"insidious Ordos" scene looked correct until the `INTRO7A`→`INTRO7B` cut
partway through it, the following Harkonnen scene reset cleanly because
`INTRO8A` has a first frame, then decayed again at `INTRO8B`.

An attempted workaround — forcing `wsaReservedDisplayFrame` so every
animation composes in its own buffer — cannot work, precisely because
these files *need* the previous animation's output as their base.

`GUI_Screen_FadeIn()` is load-bearing for the same reason: it is what
copies the first frame from `SCREEN_1` into `SCREEN_0`, seeding the
accumulator that the rest of the scene XOR-decodes against.

The general lesson is that auditing "does anything read `SCREEN_0` back"
is not a tractable gate. Write-through removes the question.

### Quantization timing

Presentation bakes pen numbers in: `_c2p1x1_4_st` resolves every chunky
byte through the current quantization, and converted pixels keep those
pens until something re-converts them. Since the game routinely draws a
picture while the palette is still all black and only then fades it in,
presenting naively would bake black pens into everything.

The fix exploits the independence of the two palette mechanisms on
ST/STE: `Video_SetPalette()` only rebuilds the chunky→pen tables and never
touches the hardware registers, which are moved only by the fade helpers.
An enclave therefore calls `Video_Atari_PresentPalette()` with the
picture's real palette *before* drawing it. The pens are correct from the
first converted pixel, and the picture stays invisible anyway because the
registers are still black — exactly the state the following fade-in ramps
up from.

Under write-through this is an optimization rather than a correctness
requirement. A wide palette change still raises `s_screen_needrepaint`,
and `Video_Tick()` still re-converts the whole screen from a chunky shadow
that is now guaranteed valid, so a mistimed quantization is a transient
blemish rather than permanent corruption. The bypass-era ordering guard
(`s_presentWarned`) and the `FADETOWHITE` uniform-white override have been
removed accordingly.

### Enclaves

| Enclave | Site | Status |
| --- | --- | --- |
| Logos | `Gameloop_Logos()`, `src/cutscene.c` | Committed (`5d1cbd4d`), verified in Hatari. |
| Whole intro | `GameLoop_GameIntroAnimation()`, `src/cutscene.c` | Committed as bypass (`de18666b`), converted to write-through, awaiting retest. |

Both open the enclave immediately after the sequence's palette is loaded
and the screen cleared, install the quantization with
`Video_Atari_PresentPalette()`, and close it after the closing fade.

### Verification so far

- Logos: both logos appear correctly, and in fact better than the base
  build, which briefly flashed partially converted buffer content at the
  logo switch. Presenting under black registers makes each logo appear
  atomically.
- Masked present: exhaustive host test, 51,360 cases, zero failures.
- Intro: the bypass build reproduced the WSA accumulator decay described
  above. The write-through build has not yet been run on hardware or in
  Hatari.

### Known limitations

- `GUI_Screen_FadeIn()` dissolves in 8-pixel columns, half the 16-pixel
  group the c2p works in, so every block is a masked read-modify-write. A
  16-pixel variant was written and measured correct (20 blocks: 18
  aligned, 2 masked edges) but changed the look of the dissolve enough to
  be noticeable, and has been reverted pending a decision.
- Present mode writes planar pixels directly underneath anything
  composited on the planar screen, so `Video_Atari_PresentEnter()` takes
  the placement preview and the mouse cursor down, and `Video_Tick()`
  keeps them down for the duration. Cutscenes hide the mouse anyway.
