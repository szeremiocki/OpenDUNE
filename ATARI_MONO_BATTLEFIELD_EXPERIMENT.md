# ST/STE monochrome saved-battlefield experiment

Status: an experimental native mono backend is implemented. External testing
found an invisible load dialog and a first-viewport panic; both identified
code paths are fixed, but those fixes still need external confirmation.

Priority: monochrome support takes precedence over the planned full-screen
battlefield mode. The goal is to make the game available to Atari monochrome
users, not merely to explore a different rendering technique.

## Implemented backend and current limits

- One executable detects an already-active ST-High resolution before asset
  preparation. Backend selection stays fixed for the run; it never switches
  a colour-monitor system into mono or changes mono palette polarity.
- The engine retains 320x200 logical coordinates. Each logical pixel becomes
  a 2x2 cell in a 640x400 one-plane bitmap: 80 bytes per physical scanline,
  160 bytes per logical row pair, and 32000 bytes per screen.
- Native asset pixels occupy the same padded byte count as ST-Low assets.
  There is one representation per cache. Mono CPU/BLITTER geometry uses
  one plane and twice the physical height; compact opacity remains logical,
  with expanded native masks where BLITTER commands require them.
- Shared phase-aware preparation feeds native mono tiles, sprites and UI.
  Publication, scrolling, cursor backups and overlays use mono geometry.
  Universal dithering is the initial text/UI policy, not bespoke readable
  mono artwork. Colour-native WSA caches are bypassed in mono.
- The message bar shares native background composition, retained text lines,
  damaged-area publication and scrolling with colour. Mono no longer converts
  the entire 320x24 banner from chunky pixels, including when individual
  glyphs must be drawn instead of using the whole-line compositor.
- Aligned opaque chunky artwork, including SCREEN.CPS, shares colour's direct
  presentation structure. A 68000 mono row kernel emits both physical rows
  directly, without expanded pen scratch or opaque masks.
- One startup-selected backend supplies native preparation, opaque conversion,
  group reads and destination addressing. Video_Tick and both damage sources
  share the same dirty-run discovery and vertical batching; the separate mono
  tick/dirty sweep has been removed. Cursor/placement repair and protected CPU
  tile-frame merging surround the backend conversion.
- Shared asset preparation uses that same mono packing backend, including
  narrow tails, source-relative phase, flips and zero padding. Active UI and
  frozen terrain mappings each have a derived 4 KiB packing lookup; custom
  policies compile a temporary lookup. No new quantization policy is added.
- Cached base/overlay tile composition uses one startup-selected native backend
  operation. Both kernels overwrite every pixel and compact opacity word;
  GFX retains caching and opacity classification, without layout checks.
  Mono no longer clears these outputs or uses the general clipped compositor.
- Opaque rectangles now share unaligned-copy scheduling and native window/
  saved-background publication. Phase-matching cached rectangles/subrectangles
  enter that same publisher; arbitrary source/destination phase shifts retain
  their native shift paths. The selected backend copies complete native
  row runs; only partial edges or CPU tile-frame masks use group merging.
  Cursor/placement backup repair remains common, including whole-group
  footprints outside visible overlay pixels. Mono emits both stored physical
  rows, not a duplicated first-row pattern.
- Unsupported mono fades install the final logical mapping immediately,
  without hardware palette ramps or stale chunky-screen reconstruction.
  FPS drawing is disabled in mono; OPTIONS dimming is disabled for both
  ST backends.
- Startup still uses the normal load dialog; no dedicated saved-game launch
  path was added. The first external run reported slow loading, an invisible
  dialog and a panic after terrain appeared. Fixes install the mono palette
  mapping outside presentation enclaves and avoid queuing a null tile-cursor
  callback when mono requires CPU cursor drawing.

External runs now reach the battlefield. The idle/selection/movement profiles
identified roughly 1.12 seconds per whole-banner mono conversion; the native
banner change removes that operation, with a large improvement reported externally.
Host-side pixel oracles, native 68000 command execution and cross-builds cover
the implemented paths.

Remaining UI work includes general masked sprite/text publication and menu/modal
text outside native text targets. Runtime sidebar drawing is already
largely native; its asset preparation now uses the native row packer. The
minimap still dirties its full 64x64 backing when moving the frame, as colour
does, but no longer routes it through the old per-row mono conversion stack.
External runs report the large battlefield stalls gone. In bettermono.txt the
shared dirty-conversion helper records 63 calls and 2.524 seconds inclusive
(40.07 ms per call); these are not a controlled same-rectangle comparison.

Before unification, the minimap.txt capture isolated five mono dirty sweeps costing
4.951 CPU-equivalent seconds in total, about 0.990 seconds per sweep. There
are 320 one-row conversions: 64 minimap rows per sweep. Actual minimap frame
drawing averages about 1.16 ms, not a second. Map_UpdateMinimapPosition still
marks the whole 64x64 chunky minimap dirty when moving its frame. The now-removed
MonoDirty path accounted for those 320 individual row conversions.

The pre-unification loadgame.txt and chromeandsidebar.txt captures identified
two further users of the old preparation path:

- loadgame.txt: all 17 opaque screen-copy calls fail the 16-pixel alignment
  gate and enter MonoChunky (12.767 seconds recorded inclusive). Actual
  rendering of 135 glyphs costs about 0.126 seconds. The generic scale-2 pen
  sampler and C bitpacker together consume 13.392 exclusive seconds across
  this 26.725-second capture; these costs overlap the copy totals.
- chromeandsidebar.txt: Sidebar_Preload costs 12.101 seconds, including
  10.162 seconds for 84 Sidebar_AssetLoad encodes. The shared preparation
  path expanded pens and packed them per bit; unlike direct opaque artwork
  publication, native cache preparation did not use the row kernel.
  The new kernel is exercised in this capture, and chrome is reported
  visibly quicker externally.

Shared mono preparation and masked-edge opaque publication are now implemented,
without separate sidebar/load-screen palette policies. In the later
loadgame2.txt capture, 21 unaligned button-backing copies still recorded
5.844 seconds, and one already-native dialog restoration recorded 2.116 seconds.
Those are the paths now moved out of MonoChunky/MonoPublish. New external
timings are needed; the profile predates rectangle unification.

### Sprite execution in battlemono.txt

The unattended capture uses the BLITTER for 2653 of 2748 low-level sprite
publications (96.5%): 2623 use cached geometry and 30 build clipped geometry.
Every normal mono recipe is 0x11, one mask-clear pass and one pixel-OR pass,
for 5306 launches. Geometry is one plane, twice the physical width and height;
the native sprite byte count matches colour, but launch count does not.

Generated recipe instruction cost, including launch-boundary stalls attributed
by the profiler, averages 172.3 us per mono draw versus 249.0 us in battleYYYb.txt.
The colour capture averages 7.495 passes: 2304 eight-pass draws, 92 seven-pass
draws and 748 six-pass draws. These are capture averages, not a controlled
same-sprite benchmark, and exclude cache lookup, terrain repair and geometry/
display-list overhead. Tight mono recipes are not the observed regression.

All 95 mono CPU fallbacks take the combined fog/tile-cursor protection-overlap
branch; no highlight, disabled-BLITTER or pointer/placement-overlap fallback
is observed in this capture. The combined protection mask does not distinguish
fog from the tile cursor in the recorded counters. Reconstructing the tail-called
MonoPublish cost from its own instructions and direct completed children gives
about 2.638 seconds, versus 3.367 seconds recorded in the whole low-level sprite
publisher. This explains why a small minority of calls can dominate publication.

This capture predates shared protected-sprite splitting. Both native formats
now use the same tile-band/column traversal: clear runs return to their ordinary
publishers, fully hidden tiles are skipped, and partial protection is handled
only in the intersecting slices. Mono clear runs retain their two-pass compiled
BLITTER recipes; protected slices use native CPU mask/word readers and the
common overlay-aware group merger. Colour retains its halftone-gated protected
BLITTER path. Its 16-word pattern cannot directly represent a 32x32 physical
mono tile, so this change does not invent a mono halftone launch.

The tile cursor now follows one draw-last policy in both formats. Neither mode
adds its frame to sprite/fog protection. The viewport queues the same final
native-command handle; its backend is selected at video initialization. Colour
keeps its four-launch halftone tail, while mono prepares an expanded native
mask/pixel image and a two-pass compiled BLITTER recipe. Prepared storage is
cached by pattern/pen and remains stable through playback. Without a BLITTER,
both formats use the common native CPU group-merging tail. Standalone cursor
draws drain pending commands and preserve the active viewport's prepared state.
Fog protection remains independent. External profiling is needed to measure
the combined splitter/cursor change.

The staging and effort discussion below records the original proposal.
Its direct-save launch and special readable-UI requirements are not current
implementation requirements; the adopted decisions above supersede them.

## Initial pen and asset proposal

Generate and open `ATARI_MONO_PALETTE.html` locally to review the current
IBM.PAL -> ST16 -> mono proposal. The generated preview is not versioned because
it embeds artwork from the local game data. It includes all 256 palette mappings,
the 16 source-anchored patterns, and real terrain, portrait and sprite examples
in all three versions. Zoom and transparency-background controls aid inspection.

Regenerate it with `python3 tools/preview_mono_palette.py`, using the local
DUNE.PAK and the active palette in src/video/video_atari.c. White coverage starts
from the nearest 1/16 step to hardware-RGB code-value luma, with explicit
perceptual adjustments: dark red and dark blue are lifted from 3/16 to 5/16;
dark grey is lowered from 5/16 to 4/16. Dark brown stays at 3/16 and dark green
at 5/16. Near-equal pens receive
different pattern structures. This deliberately retains the current 16-pen
quantization stage, rather than introducing a direct IBM.PAL -> mono mapping.
It is a proposal for imagery, not the final text or fine-UI rendering policy.

The same generator writes `src/video/atari_mono_palette.h`, ready for future
planarization code to include. `s_paletteMonoIBM[256]` directly maps base
IBM.PAL indices to packed 16-bit 4x4 patterns (512 bytes); `s_paletteMonoST[16]`
serves already-remapped ST pens. Named pattern constants show each cell's
binary rows and coverage. Bit 15 is top-left; one means white, not opacity.
Resolve sprite-local palettes and house remaps before the IBM lookup.
Other palettes/fades need an appropriate mapping rather than this fixed table.

Edit the generator's shared proposals and regenerate the files, not a second
hand-maintained palette. `python3 tools/preview_mono_palette.py --check` detects
stale HTML/header output against the local inputs.

## Shared foundation for later colour dithering

The dithered asset-planarization work on atari-st-mono is intended to be reused
for 4x4 dithering in the 320x200 colour renderer. It must not become a one-off
mono-only implementation.

Share pattern lookup, stable asset origins, per-asset policies and preparation
contracts. Keep output scaling, pattern dimensions, output pen values and
plane packing separate:

| Backend | Output per source pixel | 4x4 pattern spans | Pattern values |
| --- | --- | --- | --- |
| 640x400 mono | 2x2 physical pixels | 2x2 source pixels | Black / white |
| Later 320x200 colour | 1 physical pixel | 4x4 source pixels | ST hardware pen indices |

Thus mono needs source-coordinate parity for quadrant selection, whereas
the later colour path needs source coordinates modulo four. Do not hardcode
the mono parity rule as the general dither interface.

The initial ST16 -> mono pattern table is a reviewable starting point, not
a mandatory quantization stage for both backends. Future colour dithering
must retain enough original palette information to select mixtures of ST
pens, rather than first collapsing every source colour to its nearest pen.
The pattern-generation policy can differ while asset anchoring and the
preparation machinery remain shared.

`src/video/atari_dither_palette.h` now provides that shared data representation:
`AtariDitherPattern` is a `uint8[4][4]` of output pen values. Both
`s_paletteDitherSTIBM[256]` and `s_paletteDitherMonoIBM[256]` use it, at 4096
bytes per table. ST entries repeat the existing nearest pen in all 16 cells;
mono entries contain the same 0/1 patterns as the compact mono header. The
HTML asset preview samples these common-format tables.

The shared preparation stage samples
`pattern[(sourceY * scaleY + dy) & 3][(sourceX * scaleX + dx) & 3]`, with
stable asset coordinates and scale 1 for colour or 2 for mono, then passes
those pens to the appropriate planar packer. Constant ST patterns provide
an exact non-dithered baseline for validating the generalized path.

### Phase-aware preparation frontend

`src/video/atari_dither.c` implements the shared pen-sampling boundary:

```
resolved palette-index bytes + stable asset coordinates + selected lookup
    -> output pen bytes
    -> mode-specific packing
```

`Video_Atari_DitherPrepareLookup()` compiles a shared 4x4 pattern palette into
`AtariDitherLookup`, a 4096-byte phase-major table. A policy/palette is compiled
once, not per asset. `Video_Atari_DitherSetPen()` updates one colour to a
constant pattern, used to retain the current non-dithered quantization.

`AtariDitherSource` carries byte stride, true logical dimensions, stable source
origin and source-coordinate steps of +1/-1. Rows and pixels in memory are
always traversed forwards; negative steps describe already-flipped source
indices. Crop callers advance both the pointer and the origin. At scale 2,
negative steps also mirror the subpixels within each cell. The frontend keeps
all four phases in both axes; it does not reduce the general contract to
mono's two-by-two logical parity.

`Video_Atari_PreparePens()` writes into `AtariDitherTarget`, whose scale is 1
for colour pens or 2 for expanded mono pens. It does not infer transparency,
modify the input or touch output stride padding.

`Video_Atari_PreparePlanar()` is the current ST-Low packing backend. It samples
into an aligned, bounded 4096-byte temporary buffer and invokes the existing
four-plane c2p with an identity pair lookup. Larger assets use bands, advancing
the source phase across them. Arbitrary widths are supported; planar rows are
rounded to 16 pixels with zero pen padding. No phase-specific 128KB pair tables
are introduced, and no expanded full-screen buffer is allocated.

The existing `EncodePlanar`/`EncodePlanarStrided` asset entry points now delegate
to this backend with origin (0,0), positive steps and the active palette's
constant-pen lookup. Palette remap changes update this lookup alongside the
legacy pair table. Tile preparation expands house-adjusted logical indices
before sampling its separate, frozen IBM-palette lookup; it no longer discards
that colour information before the sampling boundary. Dirty-screen conversion
and other direct c2p presentation paths are unchanged.

Current rendering remains non-dithered. Callers preparing cropped/flipped
buffers or choosing a nonconstant per-asset policy must use the explicit source
descriptor rather than assuming compatibility wrappers recover an origin from
a pointer. Cache-hit drawing and native composition remain unchanged. The mono
packer is still separate; no monitor detection or mode switch has been added.
The new pass adds preparation work and two 4096-byte resident lookups (active
and frozen tile palettes), to be measured on the target before tuning.

Focused sampling/backend checks:
`env PATH=/usr/bin:/bin python3 -m unittest tools.test_dither_preparation`.

### Integration order: prove ST-Low first

Plug the shared asset-preparation API into the current 320x200, 16-pen
renderer before implementing mono monitor detection or a video-mode switch.
Use constant ST patterns first: this is a compatibility gate, not a colour
dithering experiment.

The existing colour packer and native drawing paths remain the output backend.
Prepared output pens must reach four-plane packing without a second IBM-to-ST
remap. Preserve local/house palette resolution, current palette changes,
independent opacity, cache behaviour and existing asset geometry. The fixed
base-IBM proposal alone is not sufficient for other active palettes.

Compare prepared pixels/masks against the existing implementation and exercise
the saved battlefield in ST-Low. Constant patterns must preserve output exactly;
separate nonconstant-pattern tests must check anchoring through crops, shifts
and layer composition, which a constant-pattern comparison cannot establish.
Assess preparation/cache-miss costs without adding conversion to cache-hit
drawing. Only after this integration is established should the shared API use
the mono packer and gain monitor detection/mode switching.

### Standalone mono packer

`src/video/atari_mono.c` now implements preparation without connecting it to
the live renderer. `Video_Atari_MonoPrepareLookup()` compiles a chosen shared
4x4 mono pattern palette into a 1024-byte lookup of 2x2 cells, indexed by
logical source parity and resolved colour. Build it once per policy/palette
generation. Black/white hardware polarity is selected at this boundary;
opacity is independent of it. The shared `AtariDitherPattern` type lives in
`src/video/atari_dither.h`, without pulling generated tables into every user.

`Video_Atari_MonoPack()` samples those cells and writes both physical rows
directly, without an expanded chunky bitmap. Input remains one resolved
palette-index byte per logical pixel, not a prepacked 1-bit image. Its
`AtariMonoSource` carries the stable logical origin, dimensions and source
strides; `AtariMonoBitmap` supplies output buffers and a physical word stride.

Eight logical pixels fill one word in each of two physical rows. A group of
16 therefore produces two words per row, eight bytes total. Smaller assets
need no artificial 16-pixel canvas:

| Logical width | Physical width | Words per physical row |
| --- | --- | --- |
| 1 | 2 | 1 |
| 5 | 10 | 1 |
| 8 | 16 | 1 |
| 9 | 18 | 2 |
| 16 | 32 | 2 |
| 17 | 34 | 3 |

Any positive width/height is accepted. Partial final words are left-aligned
and zero-padded without reading past the source width; stride padding is
untouched. Optional independent logical opacity is expanded to 2x2 cells,
and transparent output pixel bits are cleared. NULL source opacity means
all valid pixels are opaque, including colour zero. Masked input requires an
output opacity buffer; opaque input may omit one. Output uses native uint16
words, MSB leftmost, matching the big-endian target.

Crop callers must add their crop offsets to the stable source origin.
If texture should mirror with an image, flip the prepared bitmap/mask rather
than flipping indices and restarting the dither origin. Runtime crop/flip
integration, text/UI policies, cache wiring and mono drawing remain future work.

Run the focused checks with
`env PATH=/usr/bin:/bin python3 -m unittest tools.test_mono_palette tools.test_mono_packer`.

## Goal and scope

Run an existing saved battlefield on an ST/STE with a monochrome monitor in
640x400, one-plane ST-High mode. Keep the game world, input coordinates, UI
layout and source assets at their existing logical 320x200 resolution.
Each logical pixel becomes a prepared 2x2 monochrome cell.

The experiment should load a designated compatible save directly, bypassing
the intro, main menu, house selection and briefing presentation. Do not add
monochrome decoding/presentation for their pictures or animations. Keep the
normal game initialization needed by the save loader; removing unused startup
assets is a separate optimization, not a prerequisite.

The interactive target includes terrain, fog, units, projectiles, explosions,
selection/targeting, scrolling, battlefield messages, credits and the sidebar
needed to issue orders. Menus, Mentat/CHOAM screens, campaign flow and complete
game transitions are outside the first experiment. Unsupported screen changes
must be explicitly blocked or reported, not allowed to execute colour-native
screen writes.

## Dithering policy: asset anchored, not screen anchored

Define 4x4 monochrome pen patterns, selected by logical palette colour and an
asset-specific rendering policy. A 4x4 binary pattern offers 17 coverage
levels, not 17 uniquely distinguishable colours.

For each logical source pixel, select a 2x2 quadrant:

```
quadrant = pen[policy][colour][sourceY & 1][sourceX & 1]
```

Here source coordinates include the asset's stable original-origin offset.
They do not include its destination screen position.

This is intentional:

- The texture moves with a unit instead of crawling through its silhouette.
- An asset needs no four-way destination-parity dither cache.
- Each asset/category can choose a different treatment for legibility.
- Phase discontinuities between independently anchored assets are accepted.

Use the original asset canvas or an animation-wide stable origin, not a
changing cropped bounding box. Preserve that origin through crop, clipping
and composition. Define flips consistently with source anchoring: a prepared
texture may mirror with its source image; do not re-anchor it to the screen.

Suggested initial policies:

| Asset category | Initial treatment |
| --- | --- |
| Terrain and large shaded graphics | Full 4x4 ordered-dither pens |
| Units, projectiles and effects | Asset-anchored pens tuned for silhouettes |
| Text, small icons and fine UI borders | Deliberate solid black/white contrast |
| Health/power bars and selection/target shapes | Explicit readable mono styles |

Use a small category-based policy table initially, with per-asset overrides
where necessary. Do not create a hand-tuned replacement-art project before
seeing the first target-machine results. House identification needs an
explicit review: equal-luminance house colours will otherwise merge.

## Preparation and drawing architecture

Retain the existing decode/compose/cache structure, but add a mono output
format and preparation policy:

```
source asset + palette/house remap + stable origin + policy
    -> mono pixels and independent opacity
    -> mono geometry / CPU or BLITTER recipe
    -> draw at doubled physical coordinates
```

Do not resize the original chunky assets or change game-wide SCREEN_WIDTH /
SCREEN_HEIGHT. Perform 2x expansion when preparing native graphics. Source
decoding into temporary chunky buffers remains useful and is not prohibited.

Keep opacity separate from dither bits: both black and white can be opaque.
One opaque source pixel expands to four opaque destination pixels.

Preserve independently prepared layer policies when composing sprites or UI.
In particular, flattening text and background into one chunky image before
applying a universal dither would lose the readability benefit.

Existing logical damage tracking can remain, with physical expansion at the
backend boundary. Existing cache identity, crop bounds and game selection
logic should remain logical; add format/policy/generation identity where
required. Mono preparation must use one authoritative mapping implementation
for tiles, sprites and UI, rather than unrelated quantizers.

### Layout and cost

| Property | Existing ST-Low | Experimental ST-High |
| --- | --- | --- |
| Physical screen | 320x200, four interleaved planes | 640x400, one plane |
| Physical row stride | 160 bytes | 80 bytes |
| Screen storage | 32,000 bytes | 32,000 bytes |
| One logical 16x16 tile's pixels | 128 bytes | 128 bytes as 32x32 mono |
| One logical 16-pixel row block | 8 bytes | 4 bytes in each of two rows |

Equal pixel storage does not mean identical drawing code or total cache use.
A mono opacity bitmap is four times the size of the original compact
one-bit-per-logical-pixel mask. Some current colour paths already replicate
masks across four planes, so actual growth depends on the cache. Alignment,
padding and compiled recipes must be measured too.

Four destination-parity dither variants are unnecessary, but ordinary
destination word alignment/skew still matters. Logical integer positions
produce even physical X coordinates. Existing four-plane plane passes,
increments, clipping and generated commands cannot be reused unchanged.

## Required implementation slices

1. **Shared preparation API in unchanged ST-Low.** Connect the generalized
   asset-preparation boundary to the existing colour backend using constant
   patterns. Establish exact pixel/mask parity and working saved-battlefield
   drawing before enabling mono. Keep the standalone mono packer disconnected.
2. **Explicit experimental mode and direct-save entry.** Detect/require a
   suitable monochrome setup, preserve/restore screen state, and enter the
   save without drawing unsupported front-end screens. Reuse
   SaveGame_LoadFile() and its preparation sequence rather than inventing a
   partial save loader.
3. **Mono preparation integration and basic output.** Connect the tested
   shared API to the standalone mono packer, including asset policies, source
   anchoring, expansion and opacity. Prove a static prepared battlefield can
   be displayed before optimizing drawing.
4. **Native draw primitives.** Add mono copy, masked blit, fill, clipping
   and scroll operations, then connect terrain/fog and sprite caches.
   A correct CPU path can precede mono BLITTER recipes.
5. **Interactive graphics and UI.** Cover pointer backup/restore, tile
   cursor, placement/target overlays, text/glyphs, sidebar, credits and
   messages. Retain logical mouse coordinates and existing IKBD handling.
6. **Palette and effects audit.** Define mapping invalidation/rebuild for
   palette changes; cached mono pixels cannot be recoloured by hardware
   palette updates. Audit shake, flashes, forced repaints and FPS drawing.
   Initially disable nonessential unsupported effects explicitly.
7. **Target feedback and tuning.** Test saved-scene activity, orders,
   selection changes, scrolling and readability; profile before deciding
   how much mono-specific code generation is worthwhile.

Do not equate Video_Atari_CursorDirect() with generic native rendering for the
new mode: that flag currently selects multiple four-plane assumptions.
Separate capabilities or explicit mode dispatch are needed.

## Does full-game planarization have to happen first?

No, but it would reduce integration work. Existing native fragments can gain
mono preparation/draw paths independently.

Any remaining chunky UI fragment still needs a deliberate mono policy and
asset-relative origin at its publication boundary. A universal final-screen
dither cannot recover asset identity or keep text independently undithered.
For this experiment, planarize or explicitly adapt the fragments used by the
saved battlefield, not every screen in the game.

## Effort assessment

These are rough engineering estimates, not measured schedules. They assume
the existing toolchain, usable game data/save, and external testing on a
working monochrome ST/STE setup. Estimates are cumulative focused developer
days, excluding waits for hardware feedback:

| Milestone | Estimated effort from start |
| --- | --- |
| Direct-save/static battlefield proof with basic pens | 1-3 days |
| Interactive saved-scene experiment with essential readable UI, CPU mono drawing and explicitly limited effects | 8-15 days |
| Tuned native/BLITTER version with broader effect coverage and repeated regression/readability passes | 15-25 days |

Confidence is moderate-to-low until the static proof and the direct-write
audit. The dither lookup itself is small work; the dominant cost is adapting
the native drawing/overlay contracts and ensuring no colour-layout write
escapes into mono memory. Existing CPU/BLITTER implementations are not made
one-plane-safe merely by replacing the asset encoder.

Skipping intros and unrelated screens removes a substantial breadth of work,
but the saved battlefield still exercises most of the performance-critical
renderer. It remains a graphics-backend experiment, not an engine rewrite.
Neither equal framebuffer size nor fewer bitplanes guarantees equal speed.

## Validation and acceptance

- Host-side differential fixtures check all pen quadrants, stable source
  origins, crops/flips, independent opacity, clipping and logical-to-physical
  addressing. Add focused native primitive tests where practical.
- Build for plain 68000 with `/usr/bin/m68k-atari-mint-gcc` and
  `PATH=/usr/bin:/bin`, not the local ELF-output toolchain. Retain the normal
  colour backend unchanged.
- Test externally, not through local Hatari. Publish a distinct TOS 8.3
  binary name, for example MONOTEST.TOS.
- The target save must remain interactive: move/attack commands, selecting
  units/buildings, scrolling, messages and gauges must be usable.
- Review moving silhouettes, fine text, terrain/fog boundaries and ownership
  identification on the actual mono display, not only enlarged screenshots.
- Compare CPU milliseconds per viewport pass alongside workload counts/rates;
  report cache memory and startup preparation time separately.
- Verify clean mode restoration on normal exit and handled failures.

## Current code entry points

- src/opendune.c: GameLoop_Main() and OpenDune_Init() for startup sequencing.
- src/load.c: SaveGame_LoadFile() for the existing save-load entry.
- src/video/video_atari.c: Video_Init(), Video_Tick(),
  Video_Atari_EncodePlanarWithLookup(), tile preparation and native publication.
- src/gui/gui.c: viewport component/composite/resident preparation and credits.
- src/gui/viewport.c: native battlefield drawing, damage and selection overlays.
- src/gfx.c: decoded/planar tile caches and screen-copy paths.
- src/gui/sidebar.c and src/gui/glyph.c: prepared UI assets and glyph masks.
- src/video/atari_sprite_blit.s: current compiled BLITTER geometry dispatch.
