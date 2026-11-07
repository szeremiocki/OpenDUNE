# Flat ST/STE launch display list

This synchronous experiment redirects existing BLITTER launches, rather than
building a second rendering pipeline. It targets plain 68000 ST/STE and the
tile-snapped battlefield cursor. The capture-79 implementation is preserved in
`objs/viewport-tile-clipped-repair/combined-list-builder/`.

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
Other drawing kernels retain their completion waits.

Horizontally clipped fragments and highlight/protected draws retain immediate
geometry emission. `_Video_Atari_BlitSpriteCode` redirects these dynamic
launches while construction is active. No pointer to a temporary plan is
retained. Ordinary dynamic commands call the immutable plane recipe directly.
Opaque tile launch boundaries emit source/destination loads and a call to the
opaque kernel, retaining its hardware-setup cache.

Highlight and fog-protected launch loops emit per-plane register arguments and
calls in their existing order. Fog-pattern words become immediate hardware
writes. No highlighted pixel copy or mutable protected-recipe snapshot is
needed. Placement tint uses the same plane launcher. The tile cursor is
overwritten during BLITTER publication and redrawn once after final playback;
the CPU viewport retains its original cursor protection.

| Command | Bytes |
|---|---:|
| Opaque 16x16 tile | 18 |
| Ordinary sprite with cached phase code | 40 |
| Ordinary sprite with temporary clipping plan | 76 |
| Highlight, maximum eight planes | 288 |
| Protected sprite, maximum eight planes | 384 |
| Placement tint | 174 |

## Capacity and lifetimes

Capacity-triggered drains belong to the viewport, not launch redirectors.
Before a cached sprite draw, the viewport checks 6,432 bytes: an at-most
48x48 image, including alignment edges, covers at most 4x4 cells, each requiring
at most 384 launch bytes and one 18-byte terrain repair. Disjoint damage/fog
splits do not increase that cell bound. Terrain repair checks 270 bytes before
each dirty row (15 opaque tiles); final tint checks 174 bytes. The terminal
RTS has its own reserved word. Emitters never trigger capacity drains.

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

Immediate CPU screen writes drain first and then execute normally. Live-screen
reads used for backups also drain. No CPU argument packets are queued, and no
new classic-pointer or saved-placement machinery is added. Repair-on-first-touch
and foreground drawing order remain unchanged; this is not an all-terrain-first
pass.

Playback preserves D2-D7/A2-A6 once around the whole list. A future compiled CPU
sprite can use the same immediate-argument + JSR/RTS stream, with a private
register contract and cache-eviction barriers. Immediate CPU publishers drain;
CPU kernels running inside the list would not. This is not VBL-submitted or
guaranteed tear-free, and no emulator gameplay testing is performed here.

## Verification

`tools/test_atari_display_list.py` exercises actual arena capacity control,
CPU-write barriers, ordinary LRU eviction and terrain retagging. Its CPU-only
Unicorn harness runs the actual native launch redirectors, C highlight/fog/tint
emitters and playback wrapper. It checks planar pixels across all X phases,
clipping offsets and highlight recipes, mutable-plan/pattern lifetime, an
interleaved CPU kernel, stack/register preservation and the worst sprite batch
size. Existing renderer fixtures separately retain immediate-mode coverage.
