# ST/STE c2p per-line dirty handling: run splitting + band cache

Status: **implemented and verified on hardware** (see results below); the
instrumentation that measured it was itself restructured after the profile
showed it distorting the numbers. Not committed yet.

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
