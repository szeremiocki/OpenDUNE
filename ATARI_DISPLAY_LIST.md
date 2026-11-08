# Flat ST/STE launch display list

This synchronous experiment redirects existing BLITTER launches and selected
CPU draws into one ordered stream, rather than building a second rendering
pipeline. It targets plain 68000 ST/STE and the
tile-snapped battlefield cursor. The capture-79 implementation is preserved in
`objs/viewport-tile-clipped-repair/combined-list-builder/`.

## Implementation status

**Implemented and ready:** the current opt-in `viewport_blitter=1` display-list
path for plain 68000 ST/STE. This is not yet a universal CPU/BLITTER publication
API or a display-listed CPU-only viewport.

| Work | Status |
|---|---|
| Flat synchronous stream and cached sprite geometry/plane launches | Done |
| Queued opaque tiles, highlights, fog fragments and placement tint | Done |
| Fixed CPU masked-tile kernel, mixed with BLITTER commands | Done; native-tested |
| Direct native tile-cursor kernel with frame-stable arguments | Done |
| Explicit renderer ordering: scene, cursor, message; no implicit flush cursor | Done |
| Tile-aligned scroll arrows combined with the cursor frame in one halftone command | Done; host-side visual confirmation pending |
| Queued CPU text strips and persistent uncached-glyph storage | Done |
| Capacity reservations and cache replacement/teardown lifetime barriers | Done |
| Opaque selection publication without redundant immediate cursor repair | Done |

The message-list implementation passed 16 focused fixtures and seven ASan/UBSan
fixtures, and built in normal and damage-debug plain-68000 configurations.
Capture 87 validates the frozen `viewport-message-list` normal test delivery:
43,604 executed instruction encodings matched, with zero mismatches. It records
934 explicit cursor commands/kernel entries, zero immediate cursor restores,
and 31 message draws through 62 CPU rectangle commands. The masked-tile kernel
is covered by native fixtures but was not exercised by that capture.

**Retained intentionally:** software-cursor/legacy-placement backup-aware
compatibility paths, immediate bulk scrolling, unsupported-input fallbacks,
and the original immediate CPU-only viewport. The list is synchronous, not
VBL-submitted or guaranteed tear-free. Cache-enabled Mega STE launch behaviour
still needs separate hardware confirmation.

**Not done:** complete prepared CPU operation coverage, the explicit nullable
publication-context API below, removal of global scheduling/backend coupling,
and cursor halftone-upload reuse. These remain follow-up work, not claims about
this implementation.

## Execution

One lazily allocated 65,536-byte arena contains commands in execution order.
Commands load immediate register arguments, call an assembly drawing kernel,
and return directly to the following command. Flush writes one terminal RTS,
executes the prefix, and resets the write pointer without clearing storage.
There is no separate call stream, packet chain, backward allocation region,
argument frame, or cache-pin registry.

Ordinary full-width sprites now cache sixteen executable geometry prefixes
instead of sixteen data plans. Each 50-byte prefix sets geometry, clears the
tile-setup flag and jumps through A4 to the one shared plane recipe. A3 selects
the cached phase prefix. The register launch boundary emits a 40-byte command
loading source, mask, destination, geometry and recipe pointers plus height,
then calling the geometry launcher. It does not copy geometry into the stream.
The prefixes consume 800 bytes per image instead of 288 bytes of data plans:
32 KiB extra across 64 composite slots, plus resident phase tables.

Compiled plane recipes use a NOP between HOG-mode launches and return directly
after the final launch, instead of polling BUSY. This relies on 68000 bus
arbitration; cache-enabled Mega STE behaviour awaits host-side confirmation.
The fixed tile-cursor kernel uses the same NOP spacing between planes and
waits after its last launch before restoring HOP. Other drawing kernels
retain their completion waits.

Horizontally clipped fragments and highlight/protected draws retain immediate
geometry emission. `_Video_Atari_BlitSpriteCode` redirects these dynamic
launches while construction is active. No pointer to a temporary plan is
retained. Ordinary dynamic commands call the immutable plane recipe directly.
Opaque tile launch boundaries emit source/destination loads and a call to the
opaque kernel, retaining its hardware-setup cache.

Highlight and fog-protected launch loops emit per-plane register arguments and
calls in their existing order. Fog-pattern words become immediate hardware
writes. No highlighted pixel copy or mutable protected-recipe snapshot is
needed. Placement tint uses the same plane launcher. BLITTER publication may
overwrite the tile cursor. The renderer explicitly appends a six-byte cursor
JSR when its existing damage test requires the frame, then appends the viewport
message. Flush only terminates and executes the stream; unrelated, eviction
and capacity drains never insert drawing commands. A drain between the cursor
and message preserves their order. Immediate compatibility writers retain
their restoration hooks.
The CPU viewport retains its original cursor protection.

With `tile_cursor=1`, scroll arrows are cursor shapes, not separate sprite
publications. Four additional static 16-line patterns (128 bytes) combine the
normal brackets with a single-colour directional arrow. Top/bottom arrows
follow the mouse's tile column; left/right arrows follow its tile row, clamped
to the nearest battlefield edge tile. The top/right activation strips outside
the battlefield are included. Shape changes participate in the existing
old/new tile damage tracking; the same damage gate queues one six-byte command
only when the tile requires it. The CPU viewport uses the same shape and its
existing protected immediate draw. Placement remains separate, and disabling
tile-cursor mode retains the pixel-positioned software scroll arrows.

The scroll-shape extension passes 15 focused fixtures and five ASan/UBSan
fixtures, including edge-strip positioning, stationary damage gating,
same-tile shape changes, CPU/BLITTER drawing and fog-mask invalidation.
Normal and damage-debug plain-68000 deliveries are frozen in
`objs/viewport-tile-clipped-repair/tile-scroll-shapes/`; gameplay and appearance
still require host-side confirmation.

Capture 88 matches that normal delivery: 41,156 instruction encodings checked,
zero mismatches. All 14,995 terrain repairs were queued, with no backup-aware
immediate repairs or native software-cursor restore/compose/refresh executions.
It records 970 cursor commands/kernel entries and 33 bottom-arrow preparations;
the other arrow directions were not sampled. Cursor kernel cost remained
essentially unchanged at 1,384 cycles/draw versus 1,387 in capture 87.

The JSR enters the native cursor kernel directly, using dedicated destination,
pattern and predecoded-operation pointers prepared once per viewport. There is
no C callback, argument-stack setup, overlay test or saved-background merge.
Tile-cursor mode suppresses the classic battlefield pointer and excludes
placement mode; their ordinary rendering paths remain separate. The tail only
invalidates tile setup and marks the frame restored, besides programming the
BLITTER. Halftone uploads and conservative playback-boundary cache invalidation
remain unchanged. Immediate restores also invalidate halftone cache knowledge.
Fog protection is unchanged. Intermediate drains can leave the frame erased
until its final renderer command; scanout is not atomic.

The ordinary frame uses a fixed 68000 kernel: four paired MOVEM transfers
upload the 16 halftone words, fixed aligned geometry is installed once, and
four unrolled plane launches use predecoded OR/clear operations for the pen.
There is no C plane loop, clipping plan, per-drain recipe compilation or
geometry packet. The kernel invalidates opaque-tile setup and restores HOP;
playback boundaries invalidate C halftone residency knowledge.

| Command | Bytes |
|---|---:|
| Opaque 16x16 tile | 18 |
| CPU masked 16x16 tile | 24 |
| CPU masked text rectangle | 32 |
| Ordinary sprite with cached phase code | 40 |
| Ordinary sprite with temporary clipping plan | 76 |
| Highlight, maximum eight planes | 288 |
| Protected sprite, maximum eight planes | 384 |
| Placement tint | 174 |
| Explicit tile-cursor command | 6 |

## Capacity and lifetimes

Capacity-triggered drains belong to the viewport, not launch redirectors.
Before a cached sprite draw, the viewport checks 6,528 bytes: an at-most
48x48 image, including alignment edges, covers at most 4x4 cells, each requiring
at most 384 launch bytes and one 24-byte terrain repair. Disjoint damage/fog
splits do not increase that cell bound. Terrain repair checks 360 bytes before
each dirty row (15 masked tiles); final tint checks 174 bytes. The renderer
checks six bytes before the cursor, and text publication checks 32 bytes per
strip. Only the two-byte terminal RTS is reserved, leaving 65,534 bytes for
commands. Native emitters never trigger capacity drains.

Composite pixel and mask reservations are 48x48. Cache misses retain the original
canvas when it fits; oversized canvases are cropped to existing opaque bounds,
with CPU phase padding reapplied. Clipped composition discards only transparent
margins. A still-oversized composite reports an error rather than overrunning
its reservation. Resident images and the general blitting API are unchanged.
The 64 composite pixel/mask reservations save 176 KiB in BLITTER mode
(110 KiB in CPU mode); the highlight scratch buffer saves another 1,408 bytes.

Ordinary LRU selection is unchanged. Every occupied sprite victim drains
before its pixels, masks, plans or recipe are overwritten, even if that victim
was not referenced. Terrain-composite and selection-image retags likewise
drain before mutation. Cache teardown drains before freeing storage.
Cold fills and warm hits need no per-draw ownership bookkeeping.

Immediate compatibility screen writes drain first and then execute normally.
Live-screen reads used for backups also drain. No CPU argument packets are queued, and no
new classic-pointer or saved-placement machinery is added. Repair-on-first-touch
and foreground drawing order remain unchanged; this is not an all-terrain-first
pass.

Masked viewport tiles, including cached structure-selection borders, now call
a native CPU kernel through the same stream as BLITTER tiles and sprites.
Each 24-byte command loads cached pixel, mask and destination pointers into
A0/A1/A2 and calls the fixed aligned 16-row kernel. It merges two longwords per
row, without phase handling or empty/opaque-row branches, and leaves BLITTER
geometry and halftone RAM untouched. Selection-slot replacement still drains
before overwriting referenced pixels or masks. Queued tiles do not call cursor
repair; the renderer supplies the cursor command.
Opaque selection tiles use the ordinary 18-byte BLITTER command directly,
without preparing an immediate argument packet or restoring the cursor after
enqueueing. The immediate-only tile path retains its post-write restoration.

Viewport messages retain their four-entry planar cache and 80/48-pixel strip
layout. Each 32-byte command loads pixel/mask/destination pointers and group/row
counts, then calls a variable-size CPU masked-rectangle kernel. It skips empty
groups and merges two longwords for each nonempty group, without BLITTER MMIO.
Text uses only its own masks: it is not filtered by battlefield fog. The final
order is scene, cursor, message, then completion before minimap work. Viewport
protection ends before message publication; messages can overwrite the frame.
Damage-debug annotation runs before the final cursor/message commands.

Occupied text-cache victims drain before replacement. Unsupported whole-line
cases (including long/wrapped text and fonts without planar glyph masks) retain
glyph rasterization, but the existing up-to-32x32 planar glyph fallback now
phase-bakes into persistent storage and queues the same CPU kernel. That scratch
storage drains before reuse; no command references stack glyph buffers. The
extra scratch storage is 2,496 bytes. Classic-pointer/placement backup overlaps
retain ordered immediate publication, as do non-list modes; no new backup
machinery is added. The pre-existing oversized-font chunky fallback is unchanged.

Playback preserves D2-D7/A2-A6 once around the whole list. A future compiled CPU
sprite can use the same immediate-argument + JSR/RTS stream, with a private
register contract and cache-eviction barriers. Immediate CPU publishers drain;
CPU kernels running inside the list would not. This is not VBL-submitted or
guaranteed tear-free, and no emulator gameplay testing is performed here.

## Planned: explicit publication context, independent of backend

This is a follow-up plan, not implemented by the current display-list
experiment. It depends on CPU publication coverage described in
`ATARI_COMPILED_CPU_ASSETS.md`.

Separate two decisions:

- **Backend:** choose CPU or BLITTER when preparing the cached asset/operation.
  Its prepared kernel/recipe determines how pixels are written.
- **Scheduling:** choose immediate or deferred execution at publication.
  A nullable display-list argument determines when the prepared draw executes.

Conceptual API, with types still to be designed:

```c
Publish(compiledBlit, destination, list);
```

With `list == NULL`, execute the prepared draw immediately. Otherwise append
its immediate register arguments and kernel call to that list. Both paths
use the same drawing implementation. `viewport_blitter` remains a backend
selection option, not a display-list enable switch. A CPU-only viewport can
then use the list, and a list can continue mixing CPU and BLITTER commands.
Placement tint and the tile cursor follow the same publication contract.

Pass a builder reference, or access to its current `Next`, to higher-level
publication that can encounter capacity or cache-eviction drains. Those drains
reset the arena write pointer: a copied raw `Next` retained across them is
stale. A leaf emitter that cannot drain can accept raw `Next` and return its
updated value. Capacity ownership and eviction barriers must remain explicit;
passing a pointer alone does not solve either.

Prerequisites before replacing today's global active-list/launch-redirection
checks:

- Provide prepared plain-68000 CPU draws for every normal viewport operation:
  opaque and masked tiles, sprites including phase/clipping variants,
  highlights, fog-protected fragments, placement tint, the tile cursor and
  text. Existing immediate C fallbacks are not equivalent compiled CPU coverage.
  The current native CPU tile/text kernels are only part of this requirement;
  asset-specific generated CPU code remains a separate optimization.
- Select backend-dependent pixel/mask layouts and geometry at preparation,
  rather than branching throughout viewport publication loops. Backend changes
  must rebuild/invalidate incompatible cached representations.
- Define a shared private kernel ABI and an immediate-execution adapter.
  List playback saves D2-D7/A2-A6 once; immediate calls must preserve the
  caller's registers and maintain the same hardware/cache-state invariants.
- Keep queued pixels, masks, geometry and code alive and unchanged until drain.
  Embed transient launch values or retain stable storage; never queue stack
  pointers. Preserve cache-retag, eviction and teardown drains.
- Preserve painter order, including explicit cursor-before-message publication.
  Keep software-cursor/placement backup handling and bulk scrolling as explicit
  ordered compatibility boundaries until separately converted.
- Verify immediate versus deferred pixel equivalence for both backends,
  including masks, phasing, clipping, highlights, fog, cursor/tint ordering,
  capacity drains, cache replacement and register preservation. CPU-only
  playback must work without a BLITTER or BLITTER MMIO accesses.

Only after these prerequisites are met should `DisplayListBegin` stop gating
on `viewport_blitter`, and publication APIs replace implicit global scheduling
with their explicit list argument. This is separate from the current commit
candidate; recording it does not authorize the larger renderer conversion.

## Verification

`tools/test_atari_display_list.py` exercises actual arena capacity control,
CPU-write barriers, ordinary LRU eviction and terrain retagging. Its CPU-only
Unicorn harness runs the actual native launch redirectors, C highlight/fog/tint
emitters and playback wrapper. It checks planar pixels across all X phases,
clipping offsets and highlight recipes, mutable-plan/pattern lifetime, an
interleaved CPU kernel, stack/register preservation and the worst sprite batch
size. Existing renderer fixtures separately retain immediate-mode coverage.
The native masked-tile cases also check empty/full/mixed masks, word-aligned
longword accesses, CPU/BLITTER interleaving, untouched BLITTER state and inputs,
and the enlarged maximum repair reservation.
`tools/test_tile_cursor_tail.py` checks explicit versus empty/hidden drains,
repeated drains in one frame, an exactly full arena, immediate writes, stable
cursor state, retained CPU/fog protection, and the actual GUI pointer/placement
mode exclusion and old/new tile damage.
The native display-list fixture also checks the cursor kernel for all 16 pens,
both frame shapes, arbitrary pattern words, C ABI preservation, and tile
geometry reuse after a cursor tail.
Native text cases cover variable widths/heights, empty/full/mixed masks,
word alignment, CPU-only playback and message-over-cursor order.
`tools/test_viewport_messages.py` also exercises text-cache eviction and warm
hits, two-strip publication, full-arena drains, persistent glyph scratch reuse,
renderer ordering and immediate backup-aware compatibility.
