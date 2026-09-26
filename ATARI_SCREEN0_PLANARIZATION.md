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
