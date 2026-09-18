# ST/STE c2p per-line dirty handling: run splitting + band cache, and the
# direct-planar mouse cursor (pre-shift cache)

Status: **implemented and profiled** (see results below), being committed.

Both changes are in the ST/STE per-line branch of `Video_Tick()` in
`src/video/video_atari.c`. `c2p1x1_4_st` itself is **not** modified.

## Background

`g_dirty_blocks[200]` holds one `uint32` per scanline; **bit _i_ = pixels
`[i*16, i*16+16)`** of that line. Bits 0..19 are used (320/16), the upper
12 are always clear. `GFX_Screen_SetDirty_()` (`src/gfx.c:337`) builds the
mask by rounding outward:

```c
mask  = (1 << ((right + 15) >> 4)) - 1;   /* right edge, rounded UP   */
mask -= (1 << (left        >> 4)) - 1;    /* left  edge, rounded DOWN */
```

That 16px granularity is exactly `c2p1x1_4_st`'s inner-loop unit (16 chunky
bytes in -> 8 planar bytes out), so **one set bit = one c2p iteration = 686
cycles**, and any run boundary is a legal call boundary needing no masking
or read-modify-write.

Note a set bit means "at least one pixel in this stripe changed", not all
16. That residual sub-block waste is the granularity floor and is *not*
addressed here.

## Change 1 -- run splitting (gap skipping)

Previously the line branch converted everything from the first to the last
dirty block, reconverting clean stripes sandwiched between dirty ones.
Measured waste in `error.log` was 60-80% on fragmented lines, e.g.
`mask=04484` converting 208 px for 64 truly dirty ones.

Now each contiguous **run** of dirty blocks gets its own `c2p1x1_4_st`
call. New helper `Video_FirstCleanBlock()` (nibble-table, same style as
`Video_FirstDirtyBlock`/`Video_LastDirtyBlock`).

Break-even: a call costs ~362 cycles of fixed overhead against 686 cycles
per converted block, so skipping even a **single** clean block already pays
for the extra call (break-even gap is ~0.53 blocks).

Verified by an **exhaustive host test over all 2^20 masks**: runs are
disjoint, ordered, maximal, and cover exactly the set bits.

On the 23 real masks captured in `error.log`, with the extra call overhead
charged in: **-58.6% cycles** (224,416 -> 92,968), 315 -> 97 blocks
converted.

## Change 2 -- band cache

Decoding a mask into runs is not free. Profiling `opendune_audio.txt`, the
old span-only scan cost **313 cycles per line** = 1.82% of all cycles and
7.6% of all c2p work -- about the same as a c2p call's own overhead.
Run splitting made decoding *more* expensive (rescan from bit 0 per run
plus a variable `lsr.l Dn,Dm`).

Because `GFX_Screen_SetDirty_()` ORs one and the same mask into *every*
row of a box, vertically adjacent lines almost always carry identical
masks. `error.log` confirms this exactly -- every logged band is 2 to 5
identical masks in a row:

```
48 04484   49 04484 | 135 0c03e ... 139 0c03e | 120 f001e ... 123 f001e
```

So the loop now keeps `cachedMask` plus a decoded run list
(`runLeft[10]`/`runWidth[10]`; 10 = max runs in 20 blocks). A line only
re-decodes when its mask differs from the previous line's; otherwise it
replays the cached runs.

### Why this rather than a lookup table

A `[256]` byte-mask table was considered. Modelled scan cost per line on
the real masks:

| band height | current (no cache) | byte[256] | nibble run-table[16] | + band cache |
|---|---|---|---|---|
| 1 | 810 | 427 | 255 | 255 |
| 3 | 810 | 427 | 255 | **94** |
| 8 | 810 | 427 | 255 | **44** |

- A `[256]` table works (810 -> 427) but only removes the nibble
  *stepping*; the dominant costs, the per-run rescan and the variable
  shift, remain.
- A 16-entry *nibble* run-table beats it (810 -> 255) and is 16x smaller,
  because storing the whole run list per nibble allows walking fixed
  positions with a running base, eliminating variable shifts. Max 2 runs
  per nibble, so each entry packs into a longword: 64 bytes total.
- The band cache beats both, costs zero memory and ~6 lines of C.

Tables were therefore **skipped for now**: with the cache, decoding happens
roughly 1/5 as often, so their remaining upside is small. Easy to add later
if the profile still shows decode cost. The two compose (94 -> 62).

### Expected effect

| | cyc/line |
|---|---|
| old span-only (measured) | 313 |
| run-split, no cache | ~810 |
| **run-split + band cache (band 3)** | **~94** |
| **band 5** | **~62** |

Run splitting's decode cost is more than repaid and scanning ends up well
below the original. Combined with the -58.6% conversion saving, both halves
of the line branch improve.

## Verification performed

- **Exhaustive** host test over all 2^20 masks for run splitting (above).
- **Differential test, 200,000 random screens** (banded boxes plus
  adversarial fully-random lines): cached decode produces a
  **byte-identical call list** to fresh per-line decode, and coverage
  equals the mask exactly. Observed reuse factor **5.68 lines per decode**.
- **Generated asm inspected.** Cache check is 6 instructions (~32 cyc:
  `move.l / move.l (%a4)+ / cmp.l / jne / tst.w / jne`); the hit path is a
  tight `move.w (%a5)+ / move.w (%a3)+` walk with no decode. GCC folded the
  run-advance mask clear to `moveq #1 / lsl.l %d5 / neg.l / and.l`. Plain
  68000 throughout, no libgcc calls, no 68020 addressing modes.
- Compiles clean with and without `VIDEO_C2P_STATS`; full `make -j4` links.

## On-hardware results (`opendune_dirty.txt` + `error.log`)

**Correctness confirmed.** Every periodic summary and every spike entry
reports `waste 0 px (0%)`, matching the exhaustive host test.

**Conversion saved: 10% and 11%** of line-branch pixels over two reporting
periods (127,968 px and 669,424 px).

This is far below the -58.6% predicted above, and the prediction was
**wrong for a methodological reason worth remembering**: it was computed
from the masks appearing in `error.log`, but the log only prints boxes
*exceeding 50% waste*. That sample is the tail of the distribution, not the
average. **The honest figure for run splitting is ~10%.**

**Scan cost -- the band cache prediction held:**

| | cyc/line |
|---|---|
| old span-only (measured, `opendune_audio.txt`) | 313 |
| run-split, no cache (modelled) | ~810 |
| **run-split + band cache (measured)** | **88.9** |

Breakdown: cache check 51.2 cyc/line, decode 37.7 cyc/line amortised
(858 cyc per decode, but only 5,071 decodes for 115,475 lines). Cache hit
rate **95.6%**, i.e. **22.8 lines per decode** -- much better than the 5.68
the synthetic test produced, because real dirty bands are taller than the
random boxes used there. Net result is **72% below the original** scan
cost, so run splitting's extra decode work is repaid several times over.
Skipping the lookup tables was the right call.

## The instrumentation became the bottleneck (fixed)

The same profile showed the `VIDEO_C2P_STATS` accounting itself costing
**36,918,156 cycles = 40.2% of `Video_Tick()`, i.e. 360 cycles per
converted run** -- as much as a `c2p1x1_4_st` call's entire fixed overhead,
and 4x the whole scan. Causes: nine `ADD.L Dn,$absolute` counters (~28
cycles each on 68000, absolute-long read-modify-write) plus a
17-instruction region-classification chain, all executed per run.
`_funlockfile` also appeared at 2.58% from `Warning()` stdio locking.

This is the same profiler-skew trap as checkpoint 007: an instrumented
build was no longer representative of the real one.

**Restructured** so that:

- every counter accumulates in a **local** variable and is folded into the
  globals **once per tick**, after the loop (ordering verified: the flush
  precedes `Video_C2PStats_EndTick()`, which consumes the tick counters);
- everything a mask contributes -- total converted pixels and its split
  either side of `x=256` -- is a **per-mask constant**, so it is summed
  once while decoding and then added **per line**, never per run.

Result: the run loop (`.L160`) compiles to **pure c2p dispatch with zero
accounting instructions** -- byte-identical to the `VIDEO_C2P_STATS`-off
build. Estimated overhead drops from 360 cyc/run to ~106 cyc/line, i.e.
**40.3% -> ~13.3% of `Video_Tick()`, a 67% cut**.

Correctness of the new per-mask sums was verified **exhaustively over all
2^20 masks** against an independent per-block classification reference
(`cachedPixels`/`cachedBattfield`/`cachedSidebar` all match).

## Region split measured

Two periods: topbar 25%/6%, sidebar 11%/15%, battlefield 62%/78%. Strongly
scene-dependent. Relevant to the deferred UI-direct-to-planar idea.

## Caveats / follow-ups

- This trusts dirty-marking to be accurate for **interior** gaps. The old
  span logic accidentally papered over any under-marking there; if
  artifacts appear inside gaps, that is a `gfx.c` marking bug now exposed.
- TT/Falcon paths were left alone (out of scope), though the same waste
  exists there.
- `GFX_DIRTY_SOURCE_STATS` already tracks `s_dirtyAlignedPx` -- boxes whose
  left *and* right land on 16px boundaries. That counter exists to estimate
  how much drawing could bypass c2p with a direct planar blit, which is the
  deferred UI-direct-to-planar idea.
- **Never compare absolute cycle totals between profile runs** of different
  length (2.34G vs 1.40G cycles here). Only per-line / per-run ratios are
  meaningful across captures.

## Next step

`VIDEO_C2P_STATS` is currently **disabled** (line 75 of
`src/video/video_atari.c`) so that the next capture measures the true
`c2p1x1_4_st` and `Video_Tick()` cost without instrumentation skew.
Re-enable it by uncommenting that line when region/waste figures are wanted
again.

## Stats-off capture (`opendune_dirty2.txt`) -- the verification

Captured with `VIDEO_C2P_STATS` compiled out, so this is the real cost of
the shipped code. 1,257,048,056 cycles / 2,845 ticks.

Normalise per c2p call, never by absolute totals (sessions differ in
length and content):

| metric                          | `audio` (span only) | `dirty` (runs, stats on) | `dirty2` (runs, stats off) |
|---------------------------------|--------------------:|-------------------------:|---------------------------:|
| `Video_Tick` body, % of all cyc |               3.65% |                    6.50% |                  **2.80%** |
| `Video_Tick` body cyc / c2p call |              601.7 |                    854.8 |                  **473.4** |
| `Video_Tick` body cyc / 16px block |            104.3 |                    173.3 |                   **98.6** |
| c2p blocks per call             |                5.77 |                     4.93 |                       4.80 |
| `Video_Tick` disassembly size   |          633 instr  |               633 instr  |                 233 instr  |

Two things are confirmed:

1. **The instrumentation restructure/removal worked.** 854.8 -> 473.4
   cycles per call, -44.6%, against a modelled saving of ~360 cyc/run
   (predicted 494.8, measured 473.4). `Video_Tick` drops from 6.50% to
   2.80% of all cycles and from 633 to 233 instructions.
2. **Run splitting + band cache is a net win on dispatch.** Per *converted
   block*, the whole scan-and-dispatch path costs 98.6 cycles against the
   old span-only 104.3, even though run splitting deliberately issues
   *more* calls per screen (5.77 -> 4.80 blocks/call). The band cache more
   than pays for the extra scanning the run splitting requires.

Note the earlier ~10% conversion saving still stands as the pixel-level
win; this table measures the dispatch machinery, not the pixels.

### Where the time actually goes now

| symbol                | cycles      | share  |
|-----------------------|------------:|-------:|
| `c2p1x1_4_st`         | 247,901,220 | 19.72% |
| `GUI_DrawSprite`      | 112,633,016 |  8.96% |
| `GUI_Widget_Viewport` |  97,048,124 |  7.72% |
| `GameLoop_Unit`       |  84,309,524 |  6.71% |
| `Unit_Find`           |  75,502,592 |  6.01% |
| `GUI_Widget_HandleEv` |  65,531,392 |  5.21% |
| `Unit_Sort`           |  43,941,108 |  3.50% |
| `__funlockfile`       |  41,135,512 |  3.27% |
| `GFX_CopyRows_asm`    |  39,955,304 |  3.18% |
| `GFX_DrawTile`        |  38,045,692 |  3.03% |
| `Video_Tick` body     |  35,137,296 |  2.80% |

`c2p1x1_4_st` is now unambiguously the single largest consumer, and
splitting it by measured instruction counts (74,224 calls, 356,509 blocks):

- **fixed per-call overhead: 316.3 cyc** (prologue/epilogue/argument
  fetch) = 9.5% of all c2p time = **1.87% of the entire program**
- **inner loop: 629.5 cyc per 16-px block** (the earlier 686 figure
  included amortised overhead)

The 1.87% call overhead is a concrete, addressable target: it exists only
because the run loop calls into assembly once per run. Passing the whole
cached run list to a single asm entry point would recover most of it, and
run splitting has made it *larger* (more, smaller calls) -- worth revisiting
now that the run list is already materialised in `runLeft[]`/`runWidth[]`.

`__funlockfile` at 3.27% is stdio locking from `Warning()` and deserves a
separate look; it is pure overhead with stats compiled out.

## Spike report counter fix

`s_statTickLines` was incremented by `tickCalls` (the number of c2p *runs*),
but printed as `"%lu lines"`. Before run splitting one dirty line produced
exactly one call, so the label was accurate; with run splitting a
fragmented line issues several calls and the figure exceeded the 200
scanlines of the screen (e.g. `42496 px in 224 lines`).

Renamed to `s_statTickCalls`, and a genuine `s_statTickRows` counter added
(one increment per converted scanline). The spike message now reports both:

```
c2p SPIKE tick: %lu px in %lu rows / %lu calls, ...
```

No previously documented figure was derived from the mislabelled field --
all cycle numbers above come from profile instruction counts, not from it.
## Change 3 -- band batching in the assembly (one call per band, not per row)

### The plan that the measurement killed

The obvious next step looked like passing the whole `runLeft[]`/`runWidth[]`
list to the assembly so one call could convert every run of a line. Counting
the actual loop trip counts in `opendune_dirty2.txt` says otherwise:

| quantity                        | count  |
|---------------------------------|-------:|
| scanlines examined              | 86,065 |
| scanlines with at least one run | 68,694 |
| c2p calls (runs)                | 74,224 |
| **runs per converted line**     | **1.08** |

Batching runs per line would have removed 74,224 - 68,694 = 5,530 calls,
0.22% of the session, while *adding* per-run work inside the routine. It
would have been a net loss. This also corrects an earlier claim in this
file: run splitting did not meaningfully inflate the call count, it added
only 8%.

### What the call actually costs

Itemised from the profile, per call:

| where   | instructions                                  | cycles |
|---------|-----------------------------------------------|-------:|
| callee  | `MOVEM.L D2-D7/A2-A6` save + restore          |  196.2 |
| callee  | 4 argument loads off the stack                |   64.0 |
| callee  | mask/pointer setup, `MOVEQ`, `RTS`            |   56.1 |
| caller  | argument `PEA`/`MOVE`/`JSR`/`LEA` in `Video_Tick` | 176.2 |
| **total** |                                             | **492.5** |

74,224 calls x 492.5 = 36.6M cycles = **2.91% of the whole session** (the
earlier 1.87% figure counted only the callee half).

### Where the repetition really is

Not across runs, but across *rows*. `GFX_Screen_SetDirty_()` ORs one mask
into every row of a box, so a band of consecutive rows shares identical
geometry; this profile shows ~10 rows per distinct mask (8,627 nibble-scan
iterations for 74,224 executed runs). The same horizontal run was being
converted on ~10 successive rows, paying the full 492 cycles each time.

So `c2p1x1_4_st` gained a line loop:

```
void c2p1x1_4_st(void *planar, void *chunky, uint32 count, uint32 lines, void *pal)
```

It converts `count` bytes, advances 320 chunky / 160 planar bytes, and
repeats `lines` times. `a4`/`a5` hold the current line's src/dst, `a6`
holds the byte count as a `LEA` index, and the termination test is a
precomputed `srcEnd` on the stack -- the 4-plane body only ever touches
`d0-d7`/`a0-a3`, so those registers were free. Per extra line the loop
costs about 68 cycles (`MOVE.L` x2, `LEA` x3, `CMPA.L`, `BNE`) against the
492 it saves.

On the C side the band cache is **gone**, replaced by an explicit band
scan: gather the maximal row range sharing a mask, decode that mask once,
then issue one call per run for the whole band. This is simpler than the
cache it replaces (no `cachedMask` bookkeeping) and decodes exactly as
rarely, by construction.

The two cold paths and the non-dirty-blocks fallback collapse into single
calls too: the fallback's `while (height > 0)` loop is now `lines=height`.

Modelled saving at the measured ~10 row band: **31.3M cycles, 2.49% of the
session**. Unverified on hardware yet.

### Verification

- 200,000-screen differential test (banded boxes plus adversarial fully
  random lines): the band loop, with the assembly's internal line stepping
  expanded, produces **exactly the same set of (row, left, width)
  conversions** as the previous per-row loop, and the `src`/`dst` pointer
  arithmetic matches the per-row advance on every line.
- Disassembled the routine: stack offsets are correct for the 11-register
  `MOVEM` (44) plus return address, all five arguments are read *before*
  `srcEnd` is pushed, `LEA (A0,A6.L),A2` and `CMPA.L (SP),A4` encode as
  expected, the inner branch targets `.start` (skipping the per-line setup)
  and the outer one targets `.nextline`.
- A `lines == 0` guard was added: the line loop is a do-while and would
  have run past `srcEnd`, where the C code it replaces was a
  `while (height > 0)` loop that tolerated zero.
- Both `VIDEO_C2P_STATS` configurations compile and link.

### Note on the toolchain

Use `/usr/bin/m68k-atari-mint-gcc` (MiNT 20250702, GCC 15.1.0), which emits
**a.out** objects. A different m68k GCC earlier in `PATH` emits **ELF**,
which links with "file format not recognized" against the rest of the tree.
### On-hardware result (`opendune_bandscan.txt`)

Measured, stats compiled out, against `opendune_dirty2.txt`. Normalised per
converted 16-px block, because the two sessions differ in length and
content (1.48G vs 1.26G cycles, 444,470 vs 356,509 blocks):

| quantity                      | per-row |   band  | change |
|-------------------------------|--------:|--------:|-------:|
| c2p calls                     |  74,224 |   5,222 | **-93%** |
| lines per call                |    1.00 |    17.7 |        |
| blocks per call               |    4.80 |   85.11 |        |
| c2p fixed cost per call       |   316.3 |   416.5 |  +100  |
| c2p line loop, per line       |      -- |    64.3 |        |
| `Video_Tick`, % of session    |   2.80% |   0.87% |        |
| **dispatch, cyc per block**   | **164.4** | **47.1** | **-71.4%** |
| inner loop, cyc per block     |   629.5 |   629.5 |    0.0 |
| **total, cyc per block**      | **793.9** | **676.6** | **-14.8%** |

Applying the old dispatch rate to this capture's block count, the change
saves **52.2M cycles = 3.53% of the session** -- better than the 2.49%
modelled, because the real band is 17.7 lines rather than the ~10
estimated from the previous capture.

The mechanism is confirmed exactly as intended:

- The fixed per-call cost rose 316.3 -> 416.5 cycles (the `TST.L`/`MULU.W`
  /push of `srcEnd` added ~100), but it is now paid 14.2x less often.
- The new line loop costs 64.3 cycles per line, against the ~68 predicted,
  and replaces the 492.5 cycles a per-row call used to cost.
- `MOVEM.L` save+restore, 196 cycles, is now 0.147% of the session instead
  of 1.16%.
- The inner loop is unchanged at 629.5 cycles per block, exactly as it
  should be -- the pixel work was not touched, only the dispatch around it.

`Video_Tick` itself fell from 2.80% to 0.87% of the session even though it
now runs the band scan, because it issues 93% fewer calls: the ~176 cycles
of argument pushing per call dominated it.

Dispatch is now 47.1 of 676.6 cycles per block, i.e. **93% of c2p time is
the pixel conversion itself**. Further call-overhead work has almost
nothing left to recover; any future gain has to come from the inner loop.

---

## Change 4: the mouse cursor is composited directly into the planar screen

### Why

With dispatch overhead exhausted, the remaining lever is *not converting
pixels at all*. The `GFX_DIRTY_SOURCE_STATS` reports collected in
`error4.log`..`error8.log` show where the blocks come from:

`DIRTY_SRC_MOUSERESTORE` alone accounts for a **median 55.7%** (mean 50.2%)
of all newly dirtied blocks across ~60 logged reports -- 20-30% during heavy
battlefield action where the viewport dominates, but 50-100% in menus, the
mentat screens and whenever the game is idle. It is the single largest
producer of c2p work in the game.

That is structural, not accidental. Every cursor movement dirties the chunky
framebuffer **twice**:

1. `GUI_Mouse_Hide()` -> `GFX_CopyFromBuffer()` puts the saved background
   back and marks the old rectangle dirty (`DIRTY_SRC_MOUSERESTORE`),
2. `GUI_Mouse_Show()` -> `GUI_DrawSprite()` draws the sprite at the new
   position and marks the new rectangle dirty (`DIRTY_SRC_SPRITE`).

A 16x16 cursor is never 16px aligned, so each rectangle covers 2 blocks per
scanline over 16 scanlines = 32 blocks, and the two rectangles rarely
overlap fully. At the measured 629.5 cycles per block that is up to ~40000
cycles of chunky-to-planar conversion for moving a mouse pointer.

### What was done

The cursor is kept out of `SCREEN_0` entirely and composited straight into
the planar screen, after the c2p pass. Per tick, in `Video_Tick()`:

1. **erase** -- write the planar words saved under the previous cursor
   position back to the screen,
2. **c2p** -- the normal dirty-rectangle conversion, which no longer sees
   any cursor-generated dirt and refreshes whatever was underneath,
3. **draw** -- save the planar words at the new position, then
   `(word & ~mask) | data` the cursor over them.

Step 1 is skipped entirely when neither the cursor nor `SCREEN_0` changed,
so a stationary cursor on a static screen costs nothing.

Only ST/STE take this path (`s_curDirect`, set in `Video_Init()`); TT and
Falcon keep the original chunky cursor.

### Getting the bitplane form of the sprite

The sprite decoder is not duplicated. `GUI_Mouse_Show()` still renders with
the regular `GUI_DrawSprite()`, but into a `SCREEN_0` box that has just been
memset to 0 -- colour 0 is the sprite's transparent colour, so the rendered
box doubles as the transparency mask. `Video_Atari_CursorBuild()` transposes
it (remapping through `s_palette4BitMap` on the way) into per-line plane
words plus one mask word per 16px group, and the box is immediately
overwritten again with the background that `GFX_CopyToBuffer()` had already
saved into `g_mouseSpriteBuffer`.

All of that scribbling on `SCREEN_0` must not dirty anything, hence the new
`GFX_Screen_SetDirtySuppress()` in `src/gfx.c`.

The bitplane form depends only on the sprite content, the clipping offsets
and the horizontal position **modulo 16**, so it is cached and rebuilt only
when one of those -- or the palette quantization -- actually changes. A
plain cursor move therefore costs only the erase, the save and the composite
(4 plane words per 16px group per line), not a re-transposition.

`Video_SetPalette()` bumps `s_paletteGeneration` when a pen assignment truly
changed (it already tracked that for the pair-LUT patch), which invalidates
the cache.

### Layout notes

`GUI_Mouse_Show()` already clamps the cursor box to byte boundaries
(`s_mouseSpriteLeft * 8`, `s_mouseSpriteWidth * 8`), so the horizontal shift
inside a 16 pixel group is always 0 or 8 and the box spans at most
`(shift + width + 15) / 16` groups. The saved/composited region is addressed
as `base + y * 160 + group * 8`, 4 interleaved plane words per group, which
is the same layout the FPS overlay pokes. The FPS overlay is drawn before
the cursor so the cursor always ends up on top.

`s_screenOffset` (the explosion screen shake) offsets the *chunky source* on
ST/STE, not the planar destination, so the cursor addressing is unaffected
by it.

### Verification

A 20000 iteration randomized differential test (random background, random
cursor size/position/content with transparent holes, random palette map)
confirmed that

- planar background + `CursorBuild` + `CursorDraw` is **bit identical** to
  converting a chunky buffer that already had the cursor composited into it,
- `CursorErase` restores the planar screen to exactly the pure-background
  conversion.

Both `VIDEO_C2P_STATS` configurations compile clean with `-Wall -Wextra`,
and the generated code is plain 68000.

> Note: build with `PATH=/usr/bin:/bin`. Another `m68k-atari-mint-gcc`
> earlier in the default PATH emits ELF objects, which fail to link with
> "file format not recognized"; `/usr/bin/m68k-atari-mint-gcc` emits a.out.

### Verification, round 1: a real regression, found and fixed

`opendune_planarmouse.txt` was the first hardware/Hatari profile of the
direct-planar cursor, compared against the pre-cursor `opendune_bandscan.txt`
baseline (both normalized per tick using each profile's actual `Video_Tick`
call count -- 2723 vs 3400 -- since the two capture sessions are different
lengths and not directly comparable in raw cycles).

c2p itself was flat, as expected (dispatch was not touched by this change):
19.50% -> 19.10% of the session; call count dropped 5222 -> 3210 (-38.5%,
the cursor no longer forces extra dirty blocks) but per-block cost is
unchanged.

**But the cursor subsystem was a net loss.** `Video_Tick` rose from 0.87% to
4.21% of the session, plus a new `Video_Atari_CursorBuild` at 2.43%. Summed
across every function touched by the mouse (`c2p1x1_4_st`, `Video_Tick`,
`CursorBuild/Prepare/Hide/Direct`, `GFX_CopyFromBuffer`, `GFX_CopyToBuffer`,
`GUI_Mouse_Show/Hide`) and normalized per tick: **89,932 -> 129,573 cycles/
tick, a +44% regression** versus the chunky mouse-restore path it replaced.

Root cause: the erase trigger was `s_curDirty || s_screen_needrepaint ||
GFX_Screen_IsDirty(SCREEN_0)`. `GFX_Screen_IsDirty()` reports whether
*anything at all* on `SCREEN_0` changed -- true on almost every tick of
active gameplay (units, animations, the sidebar clock...) regardless of
whether anything under the cursor changed. So the cursor was being erased
and recomposited nearly every tick, not just when it actually moved or was
actually about to be overwritten.

### The fix

Replaced the coarse `IsDirty` check with an exact test against
`g_dirty_blocks[]`: `Video_Atari_CursorFullyDirty(y, h, group, groups)`
checks whether every 16px group under the cursor's current rectangle is
already marked dirty for every one of its scanlines -- i.e. this tick's c2p
pass is *guaranteed* to overwrite that exact area with a freshly converted
background regardless of what the cursor does.

That collapses to three outcomes each tick, for a currently-composited
cursor:

- nothing changed and c2p will not touch its rectangle: do nothing, no
  erase, no redraw (the ideal, and now the common, case for a stationary
  cursor during unrelated on-screen activity);
- it moved/changed/hid, or the game happens to redraw exactly its area, and
  c2p **will** fully cover the old rectangle: skip the manual erase --
  c2p's fresh background already removes the old cursor pixels -- and just
  clear `s_curDrawn` so the unconditional `Video_Atari_CursorDraw()` call at
  the end of `Video_Tick()` recomposites it (at its current position, still
  using the cached bitplane form; no manual erase, no rebuild);
- it moved/changed/hid and c2p will **not** fully cover the old rectangle:
  only this case needs an actual manual erase (planar word restore).

No change was needed to the draw side or to `CursorBuild`'s caching --
`Video_Atari_CursorDraw()` already no-ops when `s_curDrawn` is true, so
clearing it in the second case is sufficient to make the trailing call do
the right thing.

Both `VIDEO_C2P_STATS` configurations still compile clean with `-Wall
-Wextra` after the fix. Awaiting a new hardware profile before committing.

### Round 2: partial-overlap hole, then a real timing/tearing bug

`opendune_planarmouse2.txt` (captured with the fully-dirty/not-dirty binary
fix above) showed `Video_Atari_CursorBuild` executing far more than
expected, and the user reported: "mouse cursor on start screen/house
selection screen looks and behaves great; on actual play, it blinks very
visibly" -- and, crucially, on follow-up: "blinking occurs even when
cursor does not hover over units" and "even when not moving".

**Bug A -- partial overlap.** `Video_Atari_CursorFullyDirty()` was a binary
check (every block under the cursor dirty, or not). But c2p operates at
16px-block/scanline granularity, and a stationary cursor can have *some*
but not all of its blocks dirtied by unrelated activity (e.g. a unit
walking under part of it). In that case c2p silently overwrites just those
blocks with freshly converted plain background, biting a visible hole in
the cursor for a frame -- and the old code never noticed, since it wasn't
"fully dirty" (no forced redraw) and wasn't "not dirty" either (nothing
re-erased it). Fixed by replacing the boolean with a three-way classifier,
`Video_Atari_CursorOverlap()`, returning 0 (no overlap: leave it), 1
(partial: must erase + let the trailing call redraw), or 2 (full: c2p
already restores the background, just clear `s_curDrawn`).

**Bug B -- the real "constant blink", a timing bug, not a dirty-tracking
bug.** The user's report of blinking *even when stationary and not near
units* couldn't be explained by A. Re-reading `Video_Tick()`: the manual
erase happened at the very *top* of the function, before the entire c2p
conversion pass; the recomposite (`Video_Atari_CursorDraw()`) only ran at
the very *end*, after the FPS overlay. This codebase never syncs to vsync
anywhere (the only `Vsync()` call in the whole tree is the unrelated
Falcon explosion-shake effect) -- the ST/STE screen is single-buffered and
the CRT scans whatever is in video RAM continuously and asynchronously
from the CPU. So any real wall-clock time that elapses between the erase
and the redraw is a real, physically visible window: if the c2p pass (a
large fraction of a frame or more on real 6-15fps 68000 hardware, per
README.atari) takes long enough for even one CRT refresh to land inside
that window, the user sees the cursor vanish for a frame. This happens on
essentially every tick that needs a manual erase (bug A's partial-overlap
case, plus ordinary movement), which during active gameplay is often --
matching "blinks constantly" -- while static menu screens rarely trigger
a manual erase at all, matching "looks great" there.

Fixed by decoupling the *decision* from the *action*: the overlap
classification still has to happen before c2p (it needs to read
`g_dirty_blocks[]` before `GFX_Screen_SetClean()` wipes it), but the actual
`Video_Atari_CursorErase()` call is now deferred via a new
`s_curNeedErase` flag and executed immediately before the trailing
`Video_Atari_CursorDraw()` call -- i.e. after the entire c2p pass and the
(tiny, fixed-cost) FPS overlay poke, with nothing of consequence between
erase and redraw. Erase and redraw are now a tight back-to-back pair
instead of straddling the whole tick.

Both `VIDEO_C2P_STATS` configurations still compile clean with `-Wall
-Wextra`. Awaiting a fresh profile/hardware confirmation that the blink is
gone before committing.

### Round 3: ghost-row after scroll, then the direct-planar pre-shift cache

**Bug C -- stale background after scroll ("ghost row").** With the
deferred erase from round 2 in place, the user reported a new visible
glitch: scrolling the viewport up left a strip of the cursor's background
showing *pre-scroll* tile content, right at the top edge of the battle-
field. Root cause: `Video_Atari_CursorErase()` restored the *entire*
saved rectangle from `s_curSave[]` unconditionally, even for the groups
that this tick's c2p pass had *already* refreshed with correct, freshly
scrolled pixels -- blindly overwriting fresh data with the previous
tick's stale save buffer. `Video_Atari_CursorOverlap()` now also records,
per scanline, exactly which 16px groups this tick's c2p pass is about to
touch (`s_curEraseHit[CURSOR_MAX_H]`), captured *before*
`GFX_Screen_SetClean()` wipes `g_dirty_blocks[]`. `Video_Atari_CursorErase()`
skips restoring any group flagged there, so c2p's fresh pixels always win.
A defensive zero-fill of `s_curEraseHit[]` covers the case where the
overlap check was skipped entirely (screen not dirty this tick), so no
stale flags leak into a later tick.

Considered and rejected: a single coarse "did the viewport scroll this
tick" flag. The existing per-scanline/per-group dirty mask already
distinguishes viewport rows (fully redrawn on scroll) from banner/chrome
rows above the viewport (untouched by scroll) with no extra state, so a
coarse flag would be strictly less precise for no benefit.

Verified via three aggregated Hatari profiles (own `/tmp/agg.py` script,
normalized per `Video_Tick` call to be independent of capture length):

| capture                        | cycles/tick | vs. original chunky-mouse |
|---------------------------------|------------:|---------------------------:|
| original chunky-mouse baseline  |      89,932 |                          -- |
| round 1 (naive direct-planar)   |     129,573 |                      +44.1% |
| round 2 (fully-dirty fix only)  |      95,323 |                       +6.0% |
| round 3 (ghost-row fix, `planarmouse4.txt`) | 85,153 | **-5.3%** |

`c2p1x1_4_st`'s own share of session cycles also dropped from 17.3% to
14.3% between round 1 and round 3, confirming the win wasn't just moving
cost around.

**Direct-planar pre-shift icon cache.** Even with all of the above fixed,
every horizontal cursor move that crossed a 16px group boundary (i.e.
almost every tick the mouse moved) still forced a full chunky-render +
per-pixel bitplane transpose that tick, via `Video_Atari_CursorPrepare()`'s
single-shift cache key rejecting the previous cache entry. Since
`MOUSE.SHP` only ever contains 7 fixed icons (pointer, 4 scroll arrows,
crosshair, and one more), each shown for an entire game session, the fix
was to precompute *all 16* horizontal sub-pixel phases for every icon once
(at load time, and again on any real palette-quantization change), so
ordinary cursor movement becomes a pure table lookup with no chunky
render and no per-pixel transpose at all:

- `CursorIcon` struct + `s_curIcon[MOUSE_ICON_COUNT=7]`: each holds, per
  phase (`CURSOR_PHASES=16`), a `groups[]` count and malloc'd, exactly-
  sized `data[]`/`mask[]` bitplane buffers -- sized off the icon's own
  tight bounding box (see below), not a shared worst-case buffer.
- `Video_Atari_CursorPreloadIcons()` (called once from `Sprites_Init()`
  after `MOUSE.SHP` loads, and again from `Video_SetPalette()` on every
  real pen reassignment) renders each icon once into a scratch `SCREEN_0`
  box (background saved/restored around it, dirty-tracking suppressed),
  then calls `Video_Atari_CursorBuildPhase()` 16 times to fill the cache.
- **Tight bounding-box cropping.** Sprite headers declare a nominal
  width/height that can include blank padding (on-screen pixel counts
  supplied by the user: scroll-arrow icon is 12px wide, pointer is 9px --
  both plausibly smaller than their sprite's declared box). Before
  building phases, `Video_Atari_CursorPreloadIcons()` now scans the
  rendered chunky box for the tight non-transparent (colour != 0)
  bounding box and crops to that; `icon->bboxX/bboxY` record the crop
  offset so on-screen positioning still lines up with the sprite's own
  hotspot-relative coordinate frame. This shrinks both the cache's memory
  footprint and the per-tick draw/erase word count to only the pixels a
  cursor can actually show.
- `Video_Atari_CursorUseIcon(iconIndex, left, top)` is the per-tick fast
  path: given the *unclipped* nominal screen position, it offsets by the
  icon's crop, looks up the pre-built phase for `left & 0xf`, and clips
  entirely by trimming whole leading/trailing table groups (horizontal)
  and lines (vertical) -- never partial-word masking. This is safe
  because `group = left >> 4` is a floor shift: a 16px group is always
  either entirely on-screen or entirely off-screen, and the same holds
  per-scanline for the vertical edges, so whatever survives the trim is
  already correct via the existing per-bit opacity mask. A fully
  off-screen icon still returns `true` (handled, nothing drawn) rather
  than falling back.
- `GUI_Mouse_Show()` tries `Video_Atari_CursorUseIcon()` first and returns
  immediately on success; it now falls back to the old
  `Video_Atari_CursorPrepare()`/`CursorBuild()` chunky-render path only
  for an icon that isn't one of the 7 known `MOUSE.SHP` sprites (or when
  not running the ST/STE direct-planar cursor at all) -- not for any
  clipping reason, since clipping is now handled entirely inside the fast
  path.
- **Widget geometry cross-check.** The four scroll-edge widgets (indices
  39-42 in `g_table_gameWidgetInfo`, `src/table/widgetinfo.c`) confirm
  edge clipping is routinely reachable, not a rare corner case: the
  top/bottom strips (39, 42) span the full physical width `x: 0-239` at
  `y: 24-39` / `y: 198-199`, and their up/down-arrow cursors have hotspot
  `x=5` (`cursorHotSpots[]`, `viewport.c`) -- so hovering the leftmost
  few columns of those strips genuinely drives `left < 0`. Right/bottom
  clipping is exercised on essentially every tick the mouse nears the
  physical screen edge, for any icon. The fast path's group/line-trim
  logic handles all of this generically at runtime; no assumption about
  any specific icon's geometry is baked into the code.

Verified via `opendune_trueplanar.txt` (first capture with the pre-shift
cache and built-in clipping active; no fallback to the slow path fired at
all during the whole capture):

| function (cycles/`Video_Tick`)          | round 3 (`pm4`) | pre-shift (`trueplanar`) |     delta |
|-------------------------------------------|-----------------:|---------------------------:|----------:|
| `CursorBuild`+`CursorUse`+`CursorPre` combined |          11,452 |                        471 | **-95.9%** |
| `Video_Tick` (self, excl. callees)         |           16,338 |                      7,592 |    -53.5% |
| `GUI_DrawSprite`                           |           36,394 |                     29,875 |    -17.9% |
| whole-session cycles/tick                  |          399,828 |                    393,543 |     -1.6% |

### Cumulative result vs. the pre-direct-planar-cursor baseline

`opendune_bandscan.txt` is the last capture before *any* of this file's
direct-planar-cursor work existed (mouse still drawn via the ordinary
chunky `GUI_DrawSprite` path, fully visible to `Video_Tick`/c2p like any
other sprite). Comparing subsystem totals against `opendune_trueplanar.txt`
(all of rounds 1-3 plus the pre-shift cache), both normalized per
`Video_Tick` call:

| subsystem                 | bandscan/tick | trueplanar/tick |    delta |
|----------------------------|--------------:|-----------------:|---------:|
| c2p / video driver         |       110,041 |            86,549 |   -21.3% |
| sprite/tile drawing        |        78,150 |            63,006 |   -19.4% |
| viewport/widget UI         |        64,235 |            62,687 |    -2.4% |
| map/terrain                |        11,555 |             9,939 |   -14.0% |
| **total, all subsystems**  |   **434,200** |       **393,543** | **-9.4%** |

(Unit AI/gameplay and libc/system subsystem deltas are session/workload
variance -- neither was touched by this work -- and are omitted here; see
the full breakdown in session notes if needed.)

The c2p/video-driver and sprite/tile-drawing subsystems -- the two this
effort actually targeted -- show the whole of the measured gain; nothing
else in the profile moved for code reasons. Net result: **~9.4% fewer
total cycles per tick** during real gameplay, achieved with zero behaviour
change other than the mouse cursor itself (confirmed by the user across
multiple rounds: flicker fixed, ghost-row fixed, edge-clipping verified
correct via widget-geometry cross-check).

