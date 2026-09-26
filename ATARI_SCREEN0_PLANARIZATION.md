# Atari ST/STE `SCREEN_0` planarization migration

Date: 2026-09-25

Status: analysis and migration planning only. No planar `SCREEN_0`
implementation has been started on this branch.

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
*present mode*: an opt-in enclave inside which chunky `SCREEN_0` is not
the visible surface and is not maintained, and pixels are converted
straight from the work buffer that already holds the composed image into
the planar screen.

### Mechanism

`src/video/video_atari.c` gained a present-mode section (immediately
before `Video_Tick()`):

| Function | Role |
| --- | --- |
| `Video_Atari_PresentEnter()` / `Video_Atari_PresentLeave()` | Open/close an enclave. |
| `Video_Atari_PresentActive()` | Query, used by the hooks. |
| `Video_Atari_PresentChunky()` | Convert a rectangle of an 8bpp source (any stride) into the planar screen via `_c2p1x1_4_st`. |
| `Video_Atari_PresentFill()` | Flat-colour planar fill, used for clears. |
| `Video_Atari_PresentPalette()` | Install a quantization ahead of drawing (see below). |

`Video_Tick()` takes an early branch while present mode is on: it clears
the dirty state and jumps straight to the overlay stage, so the whole c2p
pass over chunky `SCREEN_0` is skipped.

### Hooks

Presentation is routed implicitly rather than through new call sites, so
that the 36 existing `dst == SCREEN_0` copy sites need no edits:

- `GFX_Screen_Copy()` (`src/gfx.c`) — presents when `dst == SCREEN_0 && src != SCREEN_0`.
- `GFX_ClearScreen()` (`src/gfx.c`) — present-fills when `dst == SCREEN_0`.
- `WSA_DrawFrame()` (`src/wsa.c`) — presents the decoded frame, using the
  source stride `skipBefore + width + skipAfter`.

Skipping `GFX_Screen_SetDirty()` is as essential as performing the
conversion: a presenting copy that still marked the rectangle dirty would
be immediately overwritten by `Video_Tick()` re-converting the stale
chunky shadow. Present mode clears dirty state wholesale instead.

### Quantization timing, and why there is no deferral queue

Presentation bakes pen numbers in. The chunky path can fix pens
retroactively — `Video_SetPalette()` raises `s_screen_needrepaint` and
`Video_Tick()` re-converts everything — but once the chunky copy is gone
there is nothing left to re-convert. Since the game routinely draws a
picture while the palette is still black and only then fades it in,
presenting naively would bake black pens into the whole image.

The solution is register-level: on ST/STE the software quantization and
the 16 hardware colour registers are independent. `Video_SetPalette()`
only rebuilds `s_palette4BitMap` / `s_palette4BitPairMap` and never calls
`Setcolor()`; only the fade helpers move registers. So an enclave calls
`Video_Atari_PresentPalette(<picture palette>)` *before* drawing. Pens
are correct from the first converted pixel, and the picture stays
invisible because the registers are still black — exactly the state the
following `GUI_SetPaletteAnimated()` fade-in ramps up from.

`Video_Atari_PresentPalette()` deliberately does **not** touch
`g_paletteActive`. The game must keep believing the screen is black, so
that the subsequent fade-in still takes the
`Video_Atari_TryPaletteFadeUniform()` fade-in-from-uniform path. That
path re-submits the same palette, which is then a no-op rebuild.

An earlier design deferred presents in a queue until the palette was
known. It was removed: queue entries stored a *pointer* to the source,
but WSA frames are decoded into a buffer the next frame overwrites, so a
deferred present could convert the wrong frame. Presents are now
immediate.

`Video_SetPalette()` warns (`quantization changed after presenting`) when
the quantization changes after something has been presented, which flags
any enclave that got the ordering wrong.

### Enclave 1: `Gameloop_Logos()`

`src/cutscene.c` enters present mode after `GFX_Screen_SetActive(SCREEN_0)`
and leaves it at `logos_exit`, with `Video_Atari_PresentPalette(g_palette_998A)`
before each of the three pictures (the WESTWOOD WSA, AND.CPS, VIRGIN.CPS).
It was chosen because it has no `SCREEN_0` readback at all, the mouse is
hidden throughout, every fade already takes a hardware path, and
`WSA_LoadFile(..., true)` reserves a display frame so the in-place
XOR-decode hazard does not apply.

`Video_Atari_PresentLeave()` does not re-convert the chunky shadow (it is
stale; converting it would flash pre-enclave content). It forces both
representations to black and clears dirty state. **This is only safe
because every current caller fades to black before returning** — a
constraint any future enclave must respect.

### Known limitations

- `_c2p1x1_4_st` converts whole 16-pixel groups, so presented rectangles
  must be 16-aligned in x and width. `Video_Atari_PresentChunky()` warns
  (`unaligned rect`) and refuses otherwise; in present mode the chunky
  fallback write is invisible, so such a rectangle would simply not
  appear. All rectangles in enclave 1 are full-screen.
- `GFX_Screen_Copy2()` and the direct planar overlays are not hooked.
- Masked (read-modify-write) presentation does not exist yet; it is
  required before `GameLoop_PlayAnimation()`'s `GUI_Screen_FadeIn/FadeIn2`
  and the credits' row-span scrolling can be converted.

### Verification so far

Host-side exhaustive check of the planar fill mask formula for all
x/width combinations in 0..320; clean TOS build with no new warnings.
Nothing has been run in Hatari or on hardware yet.

### Enclave 2: the whole intro (`GameLoop_GameIntroAnimation`)

The second enclave wraps `GameLoop_PrepareAnimation()` /
`GameLoop_PlayAnimation()` / `GameLoop_FinishAnimation()`. Four things
had to change for it.

**Masked presentation.** `Video_Atari_PresentChunkyMasked()` /
`Video_Atari_PresentGroupMasked()` present rectangles whose left edge or
width is not a multiple of 16. The group-aligned interior still goes
through `_c2p1x1_4_st`; only the (at most two) partially covered edge
groups take a C read-modify-write that builds the four plane words a
pixel at a time and merges them under a mask. It reads only source pixels
inside the rectangle, so it is safe for tightly packed sources such as
WSA frame buffers. Verified on the host against a reference planar
renderer for all 51360 x/width combinations (51150 of them masked), with
both full-width and packed strides.

**16 pixel fade-in blocks.** `GUI_Screen_FadeIn()` dissolved in 8x2
blocks, and the intro's region (x = 8..311) is not group aligned at
either end, so every single block would have needed masking. The TOS
path now builds its block list from the *screen's* 16 pixel group grid,
clipped to the region: for the intro that is 20 blocks per row of which
18 are perfectly aligned and only the two edge ones are masked, against
38 misaligned blocks before. The dissolve is half as many copies and the
coarser grid is not noticeable. Non-TOS builds take the same loop with a
one-column block list, which is exactly the original behaviour.

**No in-place WSA decode.** Intro steps 7, 15, 16, 17, 18 and 19 lack
`HOUSEANIM_FLAGS_DISPLAYFRAME`, so `WSA_DisplayFrame()` would decode
their deltas by XOR-ing them into the destination -- reading chunky
`SCREEN_0` back. `GameLoop_PlayAnimation()` now forces
`wsaReservedDisplayFrame` while presenting, so every frame is composed in
the WSA's own buffer and reaches the screen through `WSA_DrawFrame()`,
which the present hook already covers. It costs one width*height buffer;
`WSA_LoadFile()` falls back to streaming the file from disk if that no
longer fits.

**Subtitles.** These are drawn by the ordinary chunky renderers
(`GUI_DrawFilledRectangle`, `GUI_DrawText_Wrapper`) straight into
`SCREEN_0`, which no hook can intercept. Rather than redirect them,
`GameLoop_PlaySubtitle()` lets them write chunky `SCREEN_0` as before and
then presents that band explicitly. Doing so is only safe because the
band never overlaps a WSA picture, which the animation tables confirm:
every step that shows one uses `top = 154` (below the 24..143 picture
area), and every full-screen clear (`top == 85`, which clears from 0)
belongs to a text-only mode 0 step. The band is full width, so it is
always group aligned.

The subtitle pens need the same quantize-ahead treatment as a picture.
Colours 215..220 are blanked in `g_palette1` by
`GameLoop_PrepareAnimation()` and only filled in by the step's fade-in,
which runs *after* the text is drawn; presenting first would bake black
pens into it. `GameLoop_PresentSubtitleBand()` therefore installs
`s_palettePartTarget` into 215..220 via the new
`Video_Atari_PresentPaletteRange()` before converting. Submitting just
those six entries keeps `Rebuild_Palette4BitPairMap()` cheap and avoids
moving pens under already presented picture pixels.

**Fade to white.** `HOUSEANIM_FLAGS_FADETOWHITE` builds a palette that is
white everywhere except colour 0 and the subtitle pens, which is just
short of the uniform target `Video_Atari_TryPaletteFadeUniform()` needs
in order to ramp the hardware registers. Since presented pixels keep the
pens they were converted with, a software fade there would change nothing
on screen. While presenting, the target is made exactly uniform white --
which is the point of the effect -- so the registers ramp instead.

The ordering-guard warning in `Video_SetPalette()` is now reported only
once per enclave (`s_presentWarned`), because a software fade re-submits
an intermediate palette on every step.
